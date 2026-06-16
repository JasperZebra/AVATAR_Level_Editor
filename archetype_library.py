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
FCB → ``entitylibrary.fcb.converted.xml`` (reusing the fixed FCBConverter
binary, on a worker thread — see the load hook in ``simplified_map_editor``),
then hands the resulting XML path to :meth:`ArchetypeLibrary.build_index`.

The converted XML is large (~48 MB for a regular per-level library), so we never
``ET.parse`` the whole thing. Instead we scan it **once** to build a
``prototype-name → (byte start, byte end)`` index, then on each lookup we
``seek`` + read just that one ``<object name="EntityPrototype">`` block and parse
only it. A small LRU keeps recently used prototypes hot.

When no converted library is available (or a name isn't in it), every lookup
**falls back to the local ``entities/`` folder** — the old per-file archetype
store — so nothing breaks and we delete nothing.

Lookup keys
-----------
A placed entity references its archetype by ``hidName`` (e.g.
``Avatar.Valkyrie_Scripted_1``) or ``tplCreatureType`` (e.g.
``vehicle.Avatar.Valkyrie_Scripted``). The library keys prototypes by their
``Name`` field (e.g. ``Avatar.Valkyrie_Scripted``) and we also alias each
prototype's inner ``Entity/hidName`` (e.g. ``vehicle.Avatar.Valkyrie_Scripted``).
:meth:`_candidates` reproduces — and unions — the matching strategies the old
consumers used: strip a trailing ``_<N>`` instance suffix, strip known
archetype prefixes, and try dot-separated suffixes longest-first.
"""

import os
import re
import glob
import xml.etree.ElementTree as ET
from collections import OrderedDict


# Prefixes the old model_loader stripped from a tplCreatureType to reach the bare
# archetype name. Kept here so the unified matcher is at least as capable as the
# code it replaces.
_KNOWN_PREFIXES = (
    'enemy_archetypes.', 'STP_archetypes.', 'object_archetypes.',
    'AvatarInteractive.', 'Avatar_ScriptedEvents.', 'weapons.',
    'Animals.Avatar.', 'vehicle.Avatar.', 'Plants.Avatar.',
    'Animals.', 'vehicle.', 'Plants.',
)

# FCBConverter object-hash for an EntityPrototype container.
_PROTO_HASH = '256A1FF9'

_INSTANCE_SUFFIX_RE = re.compile(r'_\d+$')


def _strip_instance(name):
    """Drop a single trailing ``_<digits>`` instance suffix (``Foo_3`` → ``Foo``)."""
    return _INSTANCE_SUFFIX_RE.sub('', name.strip())


class ArchetypeLibrary:
    """Offset-indexed, lazy reader over one converted entitylibrary XML, with a
    local ``entities/`` folder fallback. Construct once and reuse across a level;
    call :meth:`build_index` whenever a new level's library becomes available."""

    def __init__(self, local_entities_dir=None, cache_size=64):
        self.local_entities_dir = local_entities_dir
        self._xml_path = None
        # name(lower) -> (byte_start, byte_end) of the <object EntityPrototype> block
        self._index = {}
        # ordered prototype names as they appear in the file (for all_names())
        self._names = []
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
        self._cache.clear()

    # ------------------------------------------------------------------ index
    def build_index(self, xml_path):
        """Scan ``xml_path`` once and build the prototype-name → byte-range index.

        Robust to formatting: it tracks ``<object>`` nesting depth by token
        rather than relying on indentation, and records each EntityPrototype's
        byte span plus its ``Name`` (and inner ``Entity/hidName`` alias).

        Returns True on success. On any failure the library is left cleared so
        callers transparently fall back to the local ``entities/`` folder.
        """
        try:
            if not (xml_path and os.path.isfile(xml_path)):
                self.clear()
                return False

            index = {}
            names = []

            # We read raw bytes and work with byte offsets so the later seek/slice
            # is exact regardless of multi-byte UTF-8 content.
            with open(xml_path, 'rb') as fh:
                data = fh.read()

            depth = 0
            # Stack of (depth_at_open, byte_start) for prototypes currently open.
            proto_stack = []
            pos = 0
            n = len(data)
            OPEN = b'<object'
            CLOSE = b'</object>'
            proto_marker = ('hash="%s"' % _PROTO_HASH).encode('ascii')

            while pos < n:
                o = data.find(b'<object', pos)
                c = data.find(b'</object>', pos)
                if o == -1 and c == -1:
                    break
                # Process whichever token comes first.
                if c == -1 or (o != -1 and o < c):
                    # An opening <object ...>. Determine if self-closing (/>).
                    tag_end = data.find(b'>', o)
                    if tag_end == -1:
                        break
                    tag = data[o:tag_end + 1]
                    self_closing = tag.rstrip().endswith(b'/>')
                    is_proto = proto_marker in tag and b'name="EntityPrototype"' in tag
                    if self_closing:
                        # opens and closes immediately — never a prototype container
                        pass
                    else:
                        depth += 1
                        if is_proto:
                            proto_stack.append((depth, o))
                    pos = tag_end + 1
                else:
                    # A closing </object>. If it closes a prototype we tracked,
                    # finalise that block.
                    block_end = c + len(CLOSE)
                    if proto_stack and proto_stack[-1][0] == depth:
                        _d, start = proto_stack.pop()
                        block = data[start:block_end]
                        self._record(block, start, block_end, index, names)
                    depth -= 1
                    pos = block_end

            if not index:
                self.clear()
                return False

            self._xml_path = xml_path
            self._index = index
            self._names = names
            self._cache.clear()
            return True
        except Exception as exc:    # pragma: no cover - defensive
            print(f"[ArchetypeLibrary] index build failed: {exc}")
            self.clear()
            return False

    def _record(self, block_bytes, start, end, index, names):
        """Extract the prototype Name (+ inner hidName alias) from a block and
        register both as keys pointing at the block's byte range."""
        try:
            text = block_bytes.decode('utf-8', errors='replace')
        except Exception:
            return
        # Prototype Name: first <field ... name="Name" value-String="...">
        m = re.search(r'name="Name"\s+value-String="([^"]*)"', text)
        proto_name = m.group(1) if m else None
        if proto_name:
            key = proto_name.lower()
            if key not in index:
                index[key] = (start, end)
                names.append(proto_name)
        # Inner Entity hidName alias (so a tplCreatureType like
        # "vehicle.Avatar.Valkyrie_Scripted" resolves directly).
        h = re.search(r'name="hidName"\s+value-String="([^"]*)"', text)
        if h:
            hid = h.group(1).strip()
            if hid:
                index.setdefault(hid.lower(), (start, end))

    # --------------------------------------------------------------- matching
    def _candidates(self, raw_name):
        """Yield candidate lookup keys for an entity name, best-first.

        Mirrors (and unions) the old strategies: exact, instance-stripped,
        prefix-stripped, and dot-suffix variants longest-first.
        """
        if not raw_name:
            return
        seen = set()

        def emit(v):
            if v:
                k = v.strip().lower()
                if k and k not in seen:
                    seen.add(k)
                    return k
            return None

        base = _strip_instance(raw_name)
        for variant in (raw_name, base):
            c = emit(variant)
            if c:
                yield c
            # known-prefix stripped
            for pfx in _KNOWN_PREFIXES:
                if variant.lower().startswith(pfx.lower()):
                    c = emit(variant[len(pfx):])
                    if c:
                        yield c
                    break
            # dot-suffix variants, longest-first
            parts = variant.split('.')
            for i in range(1, len(parts)):
                c = emit('.'.join(parts[i:]))
                if c:
                    yield c

    # ---------------------------------------------------------------- lookups
    def get_prototype_element(self, *names):
        """Return the ``<object name="EntityPrototype">`` Element for the first
        matching name, or None. Tries the converted library first (seek+slice),
        then the local ``entities/`` folder. ``names`` are tried in order — pass
        ``hidName`` then ``tplCreatureType`` to mirror the old precedence."""
        for raw in names:
            if not raw:
                continue
            for key in self._candidates(raw):
                el = self._from_library(key)
                if el is not None:
                    return el
        # fall back to the local per-file folder
        for raw in names:
            el = self._from_local_folder(raw)
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

    def _from_local_folder(self, raw_name):
        """Old per-file lookup: try ``<suffix>_1.xml`` (exact then ``*`` glob),
        dot-suffixes longest-first, in the local ``entities/`` directory."""
        d = self.local_entities_dir
        if not (d and raw_name and os.path.isdir(d)):
            return None
        base = _strip_instance(raw_name)
        if not base:
            return None
        parts = base.split('.')
        for i in range(len(parts)):
            filename = '.'.join(parts[i:]) + '_1.xml'
            exact = os.path.join(d, filename)
            if os.path.exists(exact):
                return self._parse_file(exact)
            matches = glob.glob(os.path.join(d, '*' + filename))
            if matches:
                return self._parse_file(matches[0])
        return None

    @staticmethod
    def _parse_file(path):
        try:
            return ET.parse(path).getroot()
        except Exception:
            return None

    def all_names(self):
        """All prototype Names from the loaded library (for autocomplete). Empty
        when no library is loaded — callers should fall back to their own list."""
        return list(self._names)


# --------------------------------------------------------------------------- #
# Process-wide singleton so canvas/model_loader.py and the root-level
# entity_editor.py share one loaded library without threading a reference
# through every call site.
# --------------------------------------------------------------------------- #

_LIBRARY = None


def _default_local_entities_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'entities')


def get_library():
    """Return the shared ArchetypeLibrary (created on first use)."""
    global _LIBRARY
    if _LIBRARY is None:
        _LIBRARY = ArchetypeLibrary(local_entities_dir=_default_local_entities_dir())
    return _LIBRARY
