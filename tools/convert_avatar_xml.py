"""Avatar (Dunia-1) binary-XML <-> text converter.  DRAG-AND-DROP a file onto me.

  * Drag a COMPILED file (binary; starts with 00 00) e.g. armors.xml / oasisstrings.rml
        -> writes  <name>.decoded.xml   (editable UTF-8 text)
  * Drag a TEXT .xml back onto me
        -> writes  repacked/<name>      (binary, ready to repack into the game)

Auto-detects direction.  Pure-Python stdlib.  Byte-exact round-trip verified on the
game's own files (armors, weapons, skills, oasisstrings, exclusivecontent, ...).

Format notes:
  * Header = `00 00` + a VARINT string-pool size (the pool sits at the END of the file).
    (There is NO fixed `00 00 FF` magic — the FF only appears when the varint uses its
    0xFF + uint32 escape; small values store in one byte, e.g. 0x7E / 0xDA.)
  * VARINT escape threshold: the game's WRITER escapes (writes 0xFF + uint32-LE) for any
    value >= 0xFE — it reserves 0xFE as well as 0xFF, so a one-byte value never exceeds
    0xFD. The READER only treats a leading 0xFF as the escape marker. This asymmetry is
    real: e.g. a string-pool offset of exactly 254 is stored as `FF FE 00 00 00`, not as
    the single byte `FE`. (Verified byte-exact on 120 game files + all 29 .ai.rml brains;
    using a 0xFF write-threshold silently corrupts any file referencing offset 254.)
  * Each node = name_ref, TYPE_ref, attr_count, child_count, [attrs], children — where
    every ref is an offset into the string pool. The per-node "type" string is almost
    always empty; when it isn't (rare, e.g. skills.xml) it is preserved on the element
    as an `avx_type="..."` attribute so it survives editing. Do not hand-edit avx_type.
  * Strings are UTF-8 (so accents / ellipsis / smart-quotes round-trip correctly).
"""

import sys
import os
import re
import struct
import base64
import xml.etree.ElementTree as ET

_TYPE_ATTR = 'avx_type'      # element attribute carrying a node's (rare) non-empty type
_AI_PREFIX_ATTR = 'avx_ai_prefix'   # root-only: base64 of an .ai.rml header/class/path prefix
_ENC, _ERR = 'utf-8', 'surrogateescape'   # pool encoding (+ lossless fallback for stray bytes)
_META_ATTRS = (_TYPE_ATTR, _AI_PREFIX_ATTR)   # synthesized attributes, never pooled


def _cnt(data, i):
    """Variable-length count: 1 byte, or 0xFF + uint32-LE for large values."""
    if data[i] == 0xFF:
        return struct.unpack_from('<I', data, i + 1)[0], i + 5
    return data[i], i + 1


def _vcnt(n):
    # WRITE: escape at >= 0xFE (the game reserves 0xFE too — see module docstring).
    return bytes((n,)) if n < 0xFE else b'\xff' + struct.pack('<I', n)


def decode(data):
    """binary -> root Element (UTF-8; per-node type kept as an avx_type attribute)."""
    if data[:2] != b'\x00\x00':
        raise ValueError("not an Avatar binary-XML object (bad signature)")
    pool_size, hdr_i = _cnt(data, 2)               # 00 00 + varint pool size
    pool = data[len(data) - pool_size:]
    strings, off = {}, 0
    for chunk in pool.split(b'\x00'):
        strings[off] = chunk.decode(_ENC, _ERR)
        off += len(chunk) + 1

    def S(r):
        if r not in strings:
            raise ValueError("dangling string ref 0x%x" % r)
        return strings[r]

    def ref(i):
        if data[i] == 0xFF:
            return struct.unpack_from('<I', data, i + 1)[0], i + 5
        return data[i], i + 1

    def node(i, parent):
        name, i = ref(i)
        tref, i = ref(i)                            # node TYPE string ref (usually "")
        ntype = S(tref)
        ac, i = _cnt(data, i)
        cc, i = _cnt(data, i)
        el = ET.Element(S(name)) if parent is None else ET.SubElement(parent, S(name))
        if ac > 0:
            i += 1                                  # leading 0x00
            for k in range(ac):
                an, i = ref(i)
                av, i = ref(i)
                el.set(S(an), S(av))
                if k < ac - 1:
                    i += 1                          # 0x00 terminator
        if ntype != "":                            # keep rare non-empty types (set last)
            el.set(_TYPE_ATTR, ntype)
        for _ in range(cc):
            _, i = node(i, el)
        return el, i

    i = hdr_i                                       # first byte after the pool-size varint
    _, i = _cnt(data, i)                            # total node count (skip)
    _, i = _cnt(data, i)                            # total attr count (skip)
    root, _ = node(i, None)
    return root


def _etype(el):
    """A node's type string (the avx_type attribute, default empty)."""
    return el.attrib.get(_TYPE_ATTR, "")


def _real_attrs(el):
    """The node's real attributes, excluding our synthesized metadata attributes."""
    return [(k, v) for k, v in el.attrib.items() if k not in _META_ATTRS]


def encode(root):
    """ElementTree root -> binary blob.  Byte-exact when the source string order is
    preserved — our DFS adds strings in pool order: tag, type, attr name/value pairs,
    then children (recursively from the root)."""
    order, seen = [], set()
    seen_add = seen.add
    order_append = order.append
    META = _META_ATTRS

    # collect strings in pool order (tag, type, attr name/value pairs, recurse).
    # Inlined add()/_etype()/_real_attrs() to avoid per-node call overhead.
    def collect(el):
        s = el.tag
        if s not in seen:
            seen_add(s); order_append(s)
        s = el.attrib.get(_TYPE_ATTR, "")
        if s not in seen:
            seen_add(s); order_append(s)
        for k, v in el.attrib.items():
            if k in META:
                continue
            if k not in seen:
                seen_add(k); order_append(k)
            if v not in seen:
                seen_add(v); order_append(v)
        for c in el:
            collect(c)
    collect(root)

    pool, offset = bytearray(), {}
    pool_extend = pool.extend
    for s in order:
        offset[s] = len(pool)
        pool_extend(s.encode(_ENC, _ERR))
        pool.append(0)

    def ref(o):
        return bytes((o,)) if o < 0xFE else b'\xff' + struct.pack('<I', o)

    nn = 0
    na = 0
    pack = struct.pack

    def enc(el):
        nonlocal nn, na
        nn += 1
        out = bytearray(ref(offset[el.tag]))
        out += ref(offset[el.attrib.get(_TYPE_ATTR, "")])   # type ref
        attrs = [(k, v) for k, v in el.attrib.items() if k not in META]
        nattr = len(attrs)
        na += nattr
        out += bytes((nattr,)) if nattr < 0xFE else b'\xff' + pack('<I', nattr)
        nch = len(el)
        out += bytes((nch,)) if nch < 0xFE else b'\xff' + pack('<I', nch)
        if attrs:
            out.append(0x00)
            last = nattr - 1
            for k, (an, av) in enumerate(attrs):
                out += ref(offset[an]); out += ref(offset[av])
                if k < last:
                    out.append(0x00)
        for c in el:
            out += enc(c)
        return out

    body = enc(root)
    header = b'\x00\x00' + _vcnt(len(pool)) + _vcnt(nn) + _vcnt(na)
    return bytes(header + body + pool)


# ── BlackBox.AI `.ai.rml` brain files ───────────────────────────────────────────
# A v4 `.ai.rml` is an OPAQUE PREFIX followed by a self-contained Dunia object:
#
#   [0:16]   header = uint32-LE  ver(=4), poolSize, tailSize, classCount
#   [16:..]  class-template table  (classCount entries: CRC32 + size + inline bytes)
#   [..:S]   path/hash table       (node-path CRC32 lookups, inline path strings)
#   [S:E]    embedded Dunia node tree  (`00 00` + varint poolSize + nodes)  ← the brain
#   [E:end]  shared string pool    (poolSize bytes; the node tree refs into it)
#
# Crucially  tailSize == len(file) - S  == size of (node tree + shared pool), so the
# brain region is exactly  data[len-tailSize:]  — a standalone Dunia object we already
# round-trip byte-exact.  The prefix's class/path tables use INLINE strings (independent
# of the shared pool), so we can preserve the whole prefix verbatim and only the brain
# tree needs decoding/re-encoding.  We carry the prefix as base64 on the decoded root so
# the repack is byte-exact.  (Verified exact on all 29 game brains, incl. the 6.5 MB
# mercbrain with 1668 class templates.)
_AI_MAGIC = b'\x04\x00\x00\x00'          # ver = 4 little-endian (vs Dunia's `00 00`)
# The opaque prefix is carried as a comment near the TOP of the XML (with a human-readable
# explanation above it) so users don't mistake the base64 blob for a broken conversion.
# {16,} keeps the regex from matching the word "avx_ai_prefix" inside the prose above it.
_AI_PREFIX_COMMENT = re.compile(r'<!--\s*' + _AI_PREFIX_ATTR + r':\s*([A-Za-z0-9+/=]{16,})\s*-->')

# Short note placed above the encoded prefix line so the base64 blob isn't mistaken
# for a broken conversion.
_AI_INFO_COMMENT = (
    "<!-- .ai.rml format cracked by JasperZebra and QuietJoker -->\n"
    "<!-- The encoded line below (avx_ai_prefix) is the brain's compiled lookup data,\n"
    "     base64-encoded. It is a normal part of the file, not a conversion error. -->"
)


def is_ai_rml(data):
    return data[:4] == _AI_MAGIC


def decode_ai_rml(data):
    """`.ai.rml` binary -> root Element (brain tree; prefix kept as a base64 attr)."""
    ver, pool_size, tail_size, class_count = struct.unpack_from('<IIII', data, 0)
    split = len(data) - tail_size               # start of (node tree + shared pool)
    prefix, region = data[:split], data[split:]
    root = decode(region)                       # the brain is a plain Dunia object
    root.set(_AI_PREFIX_ATTR, base64.b64encode(prefix).decode('ascii'))
    return root


def encode_ai_rml(root):
    """root Element (with its avx_ai_prefix) -> `.ai.rml` binary.

    The prefix (class-template table + path/hash table) is REGENERATED from the edited
    tree via ai_prefix_regen, so edits actually take effect (the class templates encode
    parameter values and the path slices encode the connection graph — a preserved-
    verbatim prefix would silently keep stale data).  Byte-exact for round-trips and for
    edits that preserve the object set/order; add/remove is functionally valid but the
    blob-slice ORDER for brand-new objects is best-effort (spec section 8, still open).
    Falls back to the old preserve-and-patch behavior if the regenerator is unavailable."""
    b64 = root.attrib.get(_AI_PREFIX_ATTR)
    if b64 is None:
        raise ValueError("missing %s attribute — not a decoded .ai.rml" % _AI_PREFIX_ATTR)
    orig_prefix = base64.b64decode(b64)
    region = encode(root)                       # _real_attrs() drops the prefix attr → the tail
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import ai_prefix_regen as _R
        prefix = _R.regen_prefix_for_edit(root, orig_prefix)
        return prefix + region
    except Exception:
        # Fallback: preserve the original prefix, patch only tailSize (round-trip only).
        prefix = bytearray(orig_prefix)
        struct.pack_into('<I', prefix, 8, len(region))
        return bytes(prefix) + region


def root_to_text(root):
    """Element -> pretty XML text.  For an `.ai.rml` brain the carried prefix
    (the avx_ai_prefix attribute) is emitted at the TOP — a plain-English banner
    explaining it, then the encoded prefix line, then the readable brain tree — so a
    user opening the file understands the base64 blob is normal, not a failed convert.
    The passed-in root is left unmodified."""
    b64 = root.attrib.pop(_AI_PREFIX_ATTR, None)
    try:
        ET.indent(root, '  ')
    except Exception:
        pass
    xml = ET.tostring(root, encoding='unicode')
    if b64 is None:
        return xml
    root.set(_AI_PREFIX_ATTR, b64)                  # restore (don't mutate caller's tree)
    prefix_line = '<!-- %s: %s -->' % (_AI_PREFIX_ATTR, b64)
    return _AI_INFO_COMMENT + '\n' + prefix_line + '\n' + xml


def text_to_root(text):
    """XML text -> Element, reattaching an `.ai.rml` prefix carried in a trailing comment
    (written by root_to_text) as the avx_ai_prefix attribute so encode_ai_rml can use it."""
    m = _AI_PREFIX_COMMENT.search(text)
    root = ET.fromstring(text)                       # ET ignores the trailing comment
    if m and root.get(_AI_PREFIX_ATTR) is None:
        root.set(_AI_PREFIX_ATTR, m.group(1))
    return root


_SUFFIX = '.decoded.xml'


def main():
    if len(sys.argv) < 2:
        print("Drag a file onto this script (or: python convert_avatar_xml.py <file>)")
        return
    src = sys.argv[1]
    data = open(src, 'rb').read()

    if is_ai_rml(data) or data[:2] == b'\x00\x00':   # UNPACK: binary -> text
        root = decode_ai_rml(data) if is_ai_rml(data) else decode(data)
        xml = root_to_text(root)                     # .ai.rml prefix -> trailing comment
        out = src + _SUFFIX                          # foo.rml -> foo.rml.decoded.xml
        with open(out, 'w', encoding='utf-8', errors=_ERR, newline='\n') as f:
            f.write(xml)
        kind = '.ai.rml brain' if is_ai_rml(data) else 'binary'
        print("UNPACKED (%s -> text):\n  %s\nEdit it, then drag it back to repack." % (kind, out))
    else:                                           # REPACK: text -> binary
        text = data.decode('utf-8-sig', _ERR)        # tolerate a BOM and stray bytes
        root = text_to_root(text)                    # recover any .ai.rml prefix comment
        blob = encode_ai_rml(root) if root.get(_AI_PREFIX_ATTR) else encode(root)
        # restore the exact game filename, into a safe repacked/ subfolder
        name = os.path.basename(src)
        game = name[:-len(_SUFFIX)] if name.endswith(_SUFFIX) else name + '.bin'
        outdir = os.path.join(os.path.dirname(os.path.abspath(src)), 'repacked')
        os.makedirs(outdir, exist_ok=True)
        out = os.path.join(outdir, game)
        with open(out, 'wb') as f:
            f.write(blob)
        print("REPACKED (text -> game binary):\n  %s\nCopy it into the "
              "game to replace the original." % out)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("\nERROR: %s" % e)
    try:
        input("\nPress Enter to close...")
    except Exception:
        pass
