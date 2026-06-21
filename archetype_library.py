"""
archetype_library.py — fast, lazy reader for a level's converted entitylibrary XML.

Background
----------
Every Avatar map ships its archetype definitions in
``<worlds>/<map>/generated/entitylibrary.fcb`` — the game's native
``EntityLibraries → EntityLibrary → EntityPrototype → Entity`` structure. A
placed entity in a worldsector is only a *delta*; the bulk of its definition
lives in this library and the game merges the two at runtime.

This module lets the editor do the same. On level load the editor converts that
FCB → ``entitylibrary.fcb.converted.xml`` (via :func:`ensure_converted_xml`,
run on a worker thread — see the load hook in ``simplified_map_editor``), then
hands the resulting XML path to :meth:`ArchetypeLibrary.build_index`.

The converted XML is large (~48 MB for a regular per-level library), so we never
``ET.parse`` the whole thing. Instead we scan it **once** to build a
``prototype-name → (byte start, byte end)`` index, then on each lookup we
``seek`` + read just that one ``<object name="EntityPrototype">`` block and parse
only it. A small LRU keeps recently used prototypes hot.

There is **no local fallback**: if the level's patch folder has no
``entitylibrary.fcb`` (or a name isn't in it), the lookup simply returns None and
the archetype-driven UI stays empty. By design — the patch folder is the single
source of truth.

Lookup keys
-----------
A placed entity references its archetype by ``hidName`` (e.g.
``Avatar.Valkyrie_Scripted_1``) or ``tplCreatureType`` (e.g.
``vehicle.Avatar.Valkyrie_Scripted``). The library keys prototypes by their
``Name`` field (e.g. ``Avatar.Valkyrie_Scripted``) and also aliases each
prototype's inner ``Entity/hidName`` (e.g. ``vehicle.Avatar.Valkyrie_Scripted``).
:meth:`_candidates` strips a trailing ``_<N>`` instance suffix, strips known
archetype prefixes, and tries dot-separated suffixes longest-first.
"""

import os
import re
import sys
import subprocess
import xml.etree.ElementTree as ET
from collections import OrderedDict

_ARCH_NAMES = None   # cached hash→name table for native entitylibrary conversion


# Prefixes a tplCreatureType may carry over the bare archetype name.
_KNOWN_PREFIXES = (
    'enemy_archetypes.', 'STP_archetypes.', 'object_archetypes.',
    'AvatarInteractive.', 'Avatar_ScriptedEvents.', 'weapons.',
    'Animals.Avatar.', 'vehicle.Avatar.', 'Plants.Avatar.',
    'Animals.', 'vehicle.', 'Plants.',
)

# FCBConverter object-hash for an EntityPrototype container.
_PROTO_HASH = '256A1FF9'

_INSTANCE_SUFFIX_RE = re.compile(r'_\d+$')

_CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


def _strip_instance(name):
    """Drop a single trailing ``_<digits>`` instance suffix (``Foo_3`` → ``Foo``)."""
    return _INSTANCE_SUFFIX_RE.sub('', name.strip())


def ensure_converted_xml(fcb_path, converter_exe, fc2=True, timeout=600, log=None):
    """Return the path to ``entitylibrary.fcb.converted.xml``, converting the FCB
    if the XML is missing or older than it. Returns None if the FCB doesn't
    exist or conversion produced nothing.

    This is a blocking subprocess call — run it on a worker thread so the UI
    stays responsive. Uses FCBConverter batch mode (``-source=<folder>
    -filter=*<file> -fc2``) to match the editor's Tools→Convert Entity Library
    path, which needs the rebuilt/fixed binary to avoid crashing on the library.
    """
    def _log(m):
        if log:
            try:
                log(m)
            except Exception:
                pass

    if not (fcb_path and os.path.isfile(fcb_path)):
        _log(f"entitylibrary FCB not found: {fcb_path}")
        return None

    xml_path = fcb_path + '.converted.xml'
    try:
        if os.path.isfile(xml_path) and os.path.getmtime(xml_path) >= os.path.getmtime(fcb_path):
            return xml_path                      # already up to date — skip conversion
    except OSError:
        pass

    fname = os.path.basename(fcb_path)
    try:
        _log(f"Converting {fname} → XML (native) …")
        _tools = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools')
        if _tools not in sys.path:
            sys.path.insert(0, _tools)
        import fcb_convert
        global _ARCH_NAMES
        if _ARCH_NAMES is None:
            _ARCH_NAMES = fcb_convert.load_names()
        with open(fcb_path, 'rb') as f:
            data = f.read()
        xml = fcb_convert.fcb_to_xml(data, names=_ARCH_NAMES)
        with open(xml_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(xml)
    except Exception as exc:
        _log(f"entitylibrary conversion failed: {exc}")
        return xml_path if os.path.isfile(xml_path) else None
    return xml_path if os.path.isfile(xml_path) else None


class ArchetypeLibrary:
    """Offset-indexed, lazy reader over one converted entitylibrary XML. Construct
    once and reuse across a level; call :meth:`build_index` whenever a new level's
    library becomes available."""

    def __init__(self, cache_size=64):
        self._xml_path = None
        # name(lower) -> (byte_start, byte_end) of the <object EntityPrototype> block
        self._index = {}
        # ordered prototype names as they appear in the file (for all_names())
        self._names = []
        # name(lower) -> model descriptor path (CFileDescriptorComponent.text_fileName),
        # used to dedupe the Object Library to one entry per unique model.
        self._model_paths = {}
        self._cache = OrderedDict()     # name(lower) -> ET.Element  (LRU)
        self._cache_size = cache_size

    # ------------------------------------------------------------------ state
    @property
    def is_loaded(self):
        return bool(self._index) and self._xml_path is not None

    def clear(self):
        self._xml_path = None
        self._index = {}
        self._names = []
        self._model_paths = {}
        self._cache.clear()

    # ------------------------------------------------------------------ index
    def build_index(self, xml_path):
        """Scan ``xml_path`` once and build the prototype-name → byte-range index.

        Tracks ``<object>`` nesting depth by token (robust to formatting) and
        records each EntityPrototype's byte span plus its ``Name`` (and inner
        ``Entity/hidName`` alias). Returns True on success; on any failure the
        library is left cleared.
        """
        try:
            if not (xml_path and os.path.isfile(xml_path)):
                self.clear()
                return False

            index = {}
            names = []
            model_paths = {}
            with open(xml_path, 'rb') as fh:
                data = fh.read()

            depth = 0
            proto_stack = []          # (depth_at_open, byte_start) for open prototypes
            pos = 0
            n = len(data)
            CLOSE = b'</object>'
            proto_marker = ('hash="%s"' % _PROTO_HASH).encode('ascii')

            while pos < n:
                o = data.find(b'<object', pos)
                c = data.find(CLOSE, pos)
                if o == -1 and c == -1:
                    break
                if c == -1 or (o != -1 and o < c):
                    tag_end = data.find(b'>', o)
                    if tag_end == -1:
                        break
                    tag = data[o:tag_end + 1]
                    self_closing = tag.rstrip().endswith(b'/>')
                    is_proto = proto_marker in tag and b'name="EntityPrototype"' in tag
                    if not self_closing:
                        depth += 1
                        if is_proto:
                            proto_stack.append((depth, o))
                    pos = tag_end + 1
                else:
                    block_end = c + len(CLOSE)
                    if proto_stack and proto_stack[-1][0] == depth:
                        _d, start = proto_stack.pop()
                        self._record(data[start:block_end], start, block_end,
                                     index, names, model_paths)
                    depth -= 1
                    pos = block_end

            if not index:
                self.clear()
                return False

            self._xml_path = xml_path
            self._index = index
            self._names = names
            self._model_paths = model_paths
            self._cache.clear()
            return True
        except Exception as exc:    # pragma: no cover - defensive
            print(f"[ArchetypeLibrary] index build failed: {exc}")
            self.clear()
            return False

    def _record(self, block_bytes, start, end, index, names, model_paths):
        """Register the prototype Name (+ inner hidName alias) as keys for a block,
        and capture its model descriptor path (first `text_fileName`) for dedup."""
        try:
            text = block_bytes.decode('utf-8', errors='replace')
        except Exception:
            return
        m = re.search(r'name="Name"\s+value-String="([^"]*)"', text)
        proto_name = m.group(1).strip() if m else None
        if proto_name:
            key = proto_name.lower()
            if key not in index:
                index[key] = (start, end)
                names.append(proto_name)
                # First text_fileName = CFileDescriptorComponent model descriptor
                # (e.g. graphics\...\valkyrie.xml). Absent for markerless entities.
                dm = re.search(r'name="text_fileName"\s+value-String="([^"]*)"', text)
                if dm:
                    mp = dm.group(1).strip()
                    if mp:
                        model_paths[key] = mp
        h = re.search(r'name="hidName"\s+value-String="([^"]*)"', text)
        if h:
            hid = h.group(1).strip()
            if hid:
                index.setdefault(hid.lower(), (start, end))

    # --------------------------------------------------------------- matching
    def _candidates(self, raw_name):
        """Yield candidate lookup keys for an entity name, best-first: exact,
        instance-stripped, prefix-stripped, and dot-suffix variants longest-first."""
        if not raw_name:
            return
        seen = set()

        def norm(v):
            if v:
                k = v.strip().lower()
                if k and k not in seen:
                    seen.add(k)
                    return k
            return None

        base = _strip_instance(raw_name)
        for variant in (raw_name, base):
            c = norm(variant)
            if c:
                yield c
            for pfx in _KNOWN_PREFIXES:
                if variant.lower().startswith(pfx.lower()):
                    c = norm(variant[len(pfx):])
                    if c:
                        yield c
                    break
            parts = variant.split('.')
            for i in range(1, len(parts)):
                c = norm('.'.join(parts[i:]))
                if c:
                    yield c

    # ---------------------------------------------------------------- lookups
    def get_prototype_element(self, *names):
        """Return the ``<object name="EntityPrototype">`` Element for the first
        matching name, or None. ``names`` are tried in order — pass ``hidName``
        then ``tplCreatureType`` to mirror the old precedence."""
        for raw in names:
            if not raw:
                continue
            for key in self._candidates(raw):
                el = self._from_library(key)
                if el is not None:
                    return el
        return None

    def _from_library(self, key):
        if not self.is_loaded:
            return None
        rng = self._index.get(key)
        if rng is None:
            return None
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        try:
            start, end = rng
            with open(self._xml_path, 'rb') as fh:
                fh.seek(start)
                block = fh.read(end - start)
            el = ET.fromstring(block)
        except Exception as exc:    # pragma: no cover - defensive
            print(f"[ArchetypeLibrary] slice/parse failed for {key!r}: {exc}")
            return None
        self._cache[key] = el
        self._cache.move_to_end(key)
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return el

    def all_names(self):
        """All prototype Names from the loaded library (for autocomplete). Empty
        when no library is loaded."""
        return list(self._names)

    def model_path_for(self, name):
        """The model descriptor path for a prototype Name, or None (no model)."""
        return self._model_paths.get((name or '').strip().lower())

    def unique_model_names(self):
        """One representative prototype Name per **unique model** — so the Object
        Library shows one Banshee / one Direhorse / one Buggy instead of every
        archetype variant that reuses the same mesh. Only names that HAVE a model
        (a `text_fileName` descriptor) are included; markerless logic entities are
        dropped. The representative is the shortest (cleanest, e.g. 'Avatar.Banshee'
        over 'Avatar.Banshee_HunterPet_X') name in each model group. Sorted."""
        groups = {}    # model_key(lower) -> representative name
        for name in self._names:
            mp = self._model_paths.get(name.lower())
            if not mp:
                continue
            key = mp.strip().lower()
            cur = groups.get(key)
            if cur is None or (len(name), name) < (len(cur), cur):
                groups[key] = name
        return sorted(groups.values())


# --------------------------------------------------------------------------- #
# Process-wide singleton so canvas/model_loader.py and the root-level
# entity_editor.py share one loaded library without threading a reference
# through every call site.
# --------------------------------------------------------------------------- #

_LIBRARY = None


def get_library():
    """Return the shared ArchetypeLibrary (created on first use)."""
    global _LIBRARY
    if _LIBRARY is None:
        _LIBRARY = ArchetypeLibrary()
    return _LIBRARY
