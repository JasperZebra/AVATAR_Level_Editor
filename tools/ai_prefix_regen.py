"""ai_prefix_regen.py

Regenerate the FULL prefix [0:nodeStart] of a BlackBox.AI ".ai.rml" brain file
purely from the decoded node tree (C.decode_ai_rml root <BlackBox.AI>).

Implements the spec in tools/ai_slice_spec.md:
  header(16) | class-template table | path/hash table

Public API:
  regen_prefix(node_tree_root) -> bytes      # the prefix [0:nodeStart]
  emit_slice(ctx, obj)         -> bytes      # one object's metadata-blob slice
  build_context(root)          -> Ctx        # ridx/valHashes/parent maps etc.

The one acknowledged-open piece in the spec is the BLOB-SLICE ORDER (the B offsets);
this module computes slice CONTENT for every object and offers several order strategies.
"""
import sys, os, struct, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert_avatar_xml as C
import xml.etree.ElementTree as ET


# ----------------------------------------------------------------------------- crc32
# Standard CRC-32 (poly 0xEDB88320, init/xorout 0xFFFFFFFF) — identical to
# zlib.crc32, which is a C implementation (~1000x faster than the bit loop).
# Verified byte-exact equal over 10k random strings.
def crc32(b):
    if isinstance(b, str):
        b = b.encode()
    return zlib.crc32(b) & 0xFFFFFFFF


# ----------------------------------------------------------------------------- tree helpers
def addressable_objects(root):
    """Direct children of root that have a Class attribute, in document order."""
    return [ch for ch in root if ch.get("Class") is not None]


def is_brain(cls):
    return cls is not None and "Brain" in cls


def is_container(cls):
    return is_brain(cls) or (cls is not None and "PlayActionBrain" in cls)


TAG2T = {"Anchor": 1, "Exit": 2, "Event": 3, "UserEvent": 3}


def conn_children(port):
    """Connection children of a source port: <Connection> and (rare) <UserEvent>."""
    return [c for c in port if c.tag in ("Connection", "UserEvent")]


def source_ports(o):
    """All <Anchor>/<Exit>/<Event>/<UserEvent> descendants (any depth) that have
    >=1 connection child, in document order."""
    out = []
    for el in o.iter():
        if el is o:
            continue
        if el.tag in TAG2T and conn_children(el):
            out.append(el)
    return out


def last_comp(path):
    return path.rsplit("/", 1)[-1]


# ----------------------------------------------------------------------------- context
class Ctx:
    pass


def build_context(root):
    ctx = Ctx()
    objs = addressable_objects(root)
    ctx.root = root
    ctx.objs = objs
    ctx.by_name = {o.get("Name"): o for o in objs}

    # ridx: sort object names by crc32 ascending (record order)
    names = [o.get("Name") for o in objs]
    ctx.name_crc = {n: crc32(n) for n in names}
    rec_order = sorted(names, key=lambda n: ctx.name_crc[n])
    ctx.rec_order = rec_order
    ctx.ridx = {n: i for i, n in enumerate(rec_order)}

    # parent via Add tree
    parent = {}
    for o in objs:
        oname = o.get("Name")
        for ch in o.iter():
            if ch.tag == "Add":
                tgt = ch.get("Task") or ch.get("Plan") or ch.get("Brain")
                if tgt is not None:
                    parent[tgt] = oname
    ctx.parent = parent

    # valHashes (section 2): first-occurrence DFS over every element of every object
    valhashes = []
    seen = set()

    def add(name):
        if name is None:
            return
        h = crc32(name)
        if h not in seen:
            seen.add(h)
            valhashes.append(h)

    for o in objs:
        for el in o.iter():
            if el.tag == "Selectable" and el.get("Task") is not None and el.get("Filter") is not None:
                add(el.get("Filter"))
            if el.tag in TAG2T:
                cc = conn_children(el)
                if cc:
                    add(el.get("Name"))
                    for c in cc:
                        add(c.get("TargetAnchor"))
    ctx.valhashes = valhashes
    ctx.code_index = {h: i for i, h in enumerate(valhashes)}
    return ctx


def code(ctx, name):
    return ctx.code_index[crc32(name)]


def ridx(ctx, path):
    return ctx.ridx[path]


# ----------------------------------------------------------------------------- slice
def qualifying_selectables(ctx, o):
    """Direct/descendant <Selectable> children with resolvable Task AND a Filter,
    in document order."""
    out = []
    for el in o.iter():
        if el.tag == "Selectable":
            t = el.get("Task")
            f = el.get("Filter")
            if t is not None and f is not None and t in ctx.ridx:
                out.append(el)
    return out


def st2_for(ctx, oname, conn):
    if conn.tag == "UserEvent":
        return 6
    tgt = conn.get("Target")
    if tgt == oname or tgt.startswith(oname + "/"):
        return 1
    p_tgt = ctx.parent.get(tgt)
    p_src = ctx.parent.get(oname)
    if p_tgt is not None and p_tgt == p_src and last_comp(tgt).startswith(last_comp(oname)):
        return 1
    return 2


def emit_slice(ctx, o):
    out = bytearray()
    cls = o.get("Class")
    name = o.get("Name")
    has_parent = name in ctx.parent
    sels = qualifying_selectables(ctx, o)

    # 3.1 header
    if not has_parent and is_brain(cls):
        # root brain
        if sels:
            first = sels[0]
            X = ctx.ridx[first.get("Task")]
            marker = code(ctx, first.get("Filter"))
        else:
            X = 0
            marker = 0
        out += struct.pack("<BHH", 0x00, X, marker)
        membership_sels = sels[1:]  # skip first
    elif not has_parent and not is_brain(cls):
        # headerless orphan
        membership_sels = []  # never emit membership for headerless
    else:
        # standard
        out += struct.pack("<BH", 0x04, ctx.ridx[ctx.parent[name]])
        membership_sels = sels

    # 3.2 membership (only containers, not headerless)
    if is_container(cls) and has_parent:
        # non-root container: emit all
        membership_sels = sels
    elif is_container(cls) and not has_parent and is_brain(cls):
        # root brain: skip first (already set above)
        pass
    else:
        membership_sels = []

    for s in membership_sels:
        out += struct.pack("<BHH", 0x00, ctx.ridx[s.get("Task")], code(ctx, s.get("Filter")))

    # 3.3 connection groups
    for port in source_ports(o):
        conns = conn_children(port)
        t = TAG2T[port.tag]
        out += struct.pack("<BHH", t, code(ctx, port.get("Name")), len(conns))
        for c in conns:
            out += struct.pack("<HHB", ctx.ridx[c.get("Target")], code(ctx, c.get("TargetAnchor")),
                               st2_for(ctx, name, c))
    return bytes(out)


# ----------------------------------------------------------------------------- class table
def build_parameters_element(o):
    P = ET.Element("Parameters")
    if o.get("Name") is not None:
        pass
    P.set("Name", " ")
    for a in ("Looping", "Independent"):
        if o.get(a) is not None:
            P.set(a, o.get(a))
    top_params = [ch for ch in o if ch.tag == "Parameter"]
    for p in top_params:
        nm = p.get("Name")
        val = p.get("Value")
        if val is None:
            val = ""
        P.set(nm, val)
    for p in top_params:
        nested = [ch for ch in p if ch.tag == "Parameter"]
        if nested:
            child = ET.SubElement(P, p.get("Name"))
            for np_ in nested:
                v = np_.get("Value")
                if v is None:
                    v = ""
                child.set(np_.get("Name"), v)
    return P


def _param_struct_key(o):
    """A cheap structural key capturing everything build_parameters_element reads:
    Class, Looping/Independent, and the (possibly nested) Parameter name/value tree.
    Two objects with equal keys produce identical encoded Parameters, so the encode
    (and crc32) can be memoized — most brains repeat ~6x (1668 unique / 10836)."""
    parts = [o.get("Class"), o.get("Looping"), o.get("Independent")]
    for p in o:
        if p.tag != "Parameter":
            continue
        parts.append(p.get("Name"))
        parts.append(p.get("Value"))
        for np_ in p:
            if np_.tag == "Parameter":
                parts.append(np_.get("Name"))
                parts.append(np_.get("Value"))
        parts.append("\x00")           # nested-group terminator
    return tuple(parts)


def build_class_table(ctx):
    seen = {}            # struct-key -> (crc, enc)
    order = []           # unique (crc, enc) in first-seen order
    emitted = set()      # (crc, enc) already in order
    for o in ctx.objs:
        sk = _param_struct_key(o)
        ce = seen.get(sk)
        if ce is None:
            P = build_parameters_element(o)
            enc = C.encode(P)
            crc = crc32(o.get("Class"))
            ce = (crc, enc)
            seen[sk] = ce
        if ce not in emitted:
            emitted.add(ce)
            order.append(ce)
    table = bytearray()
    for crc, enc in order:
        table += struct.pack("<II", crc, len(enc))
        table += enc
    return bytes(table), len(order)


# ----------------------------------------------------------------------------- path/hash table
def build_blob(ctx, order_names):
    """Concatenate slices in the given object-name order. Returns blob bytes and
    {name: (B, C)}."""
    blob = bytearray()
    bc = {}
    for n in order_names:
        o = ctx.by_name[n]
        sl = emit_slice(ctx, o)
        bc[n] = (len(blob), len(sl))
        blob += sl
    return bytes(blob), bc


def build_a_values(ctx):
    """Compute the A trailer (Add-tree traversal ordinal). Two classes per spec;
    we use pure DFS-preorder from root brains. Returns {name: A}."""
    # children in Add document order
    children = {o.get("Name"): [] for o in ctx.objs}
    for o in ctx.objs:
        oname = o.get("Name")
        for ch in o.iter():
            if ch.tag == "Add":
                tgt = ch.get("Task") or ch.get("Plan") or ch.get("Brain")
                if tgt is not None and tgt in children:
                    children[oname].append(tgt)
    A = {}
    counter = [0]
    visited = set()

    def dfs(n):
        if n in visited:
            return
        visited.add(n)
        A[n] = counter[0]
        counter[0] += 1
        for c in children[n]:
            dfs(c)

    roots = [o.get("Name") for o in ctx.objs if o.get("Name") not in ctx.parent]
    for r in roots:
        dfs(r)
    # any leftover
    for o in ctx.objs:
        if o.get("Name") not in A:
            dfs(o.get("Name"))
    return A


def build_path_table(ctx, order_names, a_values):
    blob, bc = build_blob(ctx, order_names)
    out = bytearray()
    out += struct.pack("<I", len(blob))
    out += blob
    out += struct.pack("<I", len(ctx.valhashes))
    for h in ctx.valhashes:
        out += struct.pack("<I", h)
    out += struct.pack("<I", len(ctx.rec_order))
    for n in ctx.rec_order:
        h = ctx.name_crc[n]
        out += struct.pack("<II", h, len(n))
        out += n.encode()
        B, Csz = bc[n]
        A = a_values.get(n, 0)
        out += struct.pack("<III", A, B, Csz)
    return bytes(out), bc


# ----------------------------------------------------------------------------- extract true order
def extract_order_and_a(orig_data):
    """Read the true blob-slice ORDER and A-trailer values from an original .ai.rml.
    Returns (blob_order:list[name], a_values:dict[name->A]).  Used for byte-exact
    repack of edits that PRESERVE the object set/order (the blob ORDER is the one
    still-open derivation — section 8 of the spec)."""
    ver, poolSize, tailSize, classCount = struct.unpack_from("<IIII", orig_data, 0)
    node_start = len(orig_data) - tailSize
    i = 16
    for _ in range(classCount):
        crc, sz = struct.unpack_from("<II", orig_data, i)
        i += 8 + sz
    region = orig_data[i:node_start]
    pos = 0
    blobSize = struct.unpack_from("<I", region, pos)[0]; pos += 4 + blobSize
    valHashCount = struct.unpack_from("<I", region, pos)[0]; pos += 4 + 4 * valHashCount
    recordCount = struct.unpack_from("<I", region, pos)[0]; pos += 4
    recs = []
    for _ in range(recordCount):
        h = struct.unpack_from("<I", region, pos)[0]; pos += 4
        ln = struct.unpack_from("<I", region, pos)[0]; pos += 4
        path = region[pos:pos + ln].decode(); pos += ln
        A, B, Csz = struct.unpack_from("<III", region, pos); pos += 12
        recs.append((path, A, B, Csz))
    blob_order = [r[0] for r in sorted(recs, key=lambda r: r[2])]
    a_values = {r[0]: r[1] for r in recs}
    return blob_order, a_values


def extract_order_and_a_from_prefix(prefix):
    """Like extract_order_and_a but from the prefix bytes alone ([0:nodeStart], so
    nodeStart == len(prefix)). The converter stores the original prefix, not the file."""
    classCount = struct.unpack_from("<IIII", prefix, 0)[3]
    node_start = len(prefix)
    i = 16
    for _ in range(classCount):
        crc, sz = struct.unpack_from("<II", prefix, i)
        i += 8 + sz
    region = prefix[i:node_start]
    pos = 0
    blobSize = struct.unpack_from("<I", region, pos)[0]; pos += 4 + blobSize
    valHashCount = struct.unpack_from("<I", region, pos)[0]; pos += 4 + 4 * valHashCount
    recordCount = struct.unpack_from("<I", region, pos)[0]; pos += 4
    recs = []
    for _ in range(recordCount):
        h = struct.unpack_from("<I", region, pos)[0]; pos += 4
        ln = struct.unpack_from("<I", region, pos)[0]; pos += 4
        path = region[pos:pos + ln].decode(); pos += ln
        A, B, Csz = struct.unpack_from("<III", region, pos); pos += 12
        recs.append((path, A, B, Csz))
    blob_order = [r[0] for r in sorted(recs, key=lambda r: r[2])]
    a_values = {r[0]: r[1] for r in recs}
    return blob_order, a_values


def regen_prefix_for_edit(root, orig_prefix):
    """Regenerate the prefix for an EDITED brain.

    Byte-exact when the object SET/ORDER is unchanged (value / connection / param
    edits): the blob-slice order + A-trailers are reused from orig_prefix while
    everything else (class templates, slices, hashes, sizes) is recomputed from the
    edited tree. For add/remove, objects absent from orig_prefix are appended via the
    best-effort derived order (functionally valid — the game addresses each slice by
    its per-record (B,C) offset — but not byte-matched to a hypothetical original)."""
    order_src, a_src = extract_order_and_a_from_prefix(orig_prefix)
    ctx = build_context(root)
    cur = [o.get("Name") for o in ctx.objs]
    curset = set(cur)
    order = [n for n in order_src if n in curset]      # original order, minus removed
    have = set(order)
    for n in derive_blob_order(ctx):                   # append any added objects
        if n not in have:
            order.append(n); have.add(n)
    a_derived = build_a_values(ctx)
    a_values = {n: a_src.get(n, a_derived.get(n, 0)) for n in cur}
    return regen_prefix(root, blob_order=order, a_values=a_values)


# ----------------------------------------------------------------------------- full prefix
def regen_prefix(root, blob_order=None, a_values=None, orig_data=None):
    """Rebuild prefix [0:nodeStart] purely from the node tree.

    blob_order / a_values: if None, derive from the tree. The blob-slice ORDER and
    A-trailer are the one still-open derivation (spec section 8); for a byte-exact
    repack of an edit that preserves the object set/order, pass orig_data (the
    original file bytes) and the true order/A are extracted from it."""
    ctx = build_context(root)
    class_table, class_count = build_class_table(ctx)

    if orig_data is not None and (blob_order is None or a_values is None):
        bo, av = extract_order_and_a(orig_data)
        if blob_order is None:
            blob_order = bo
        if a_values is None:
            a_values = av

    if a_values is None:
        a_values = build_a_values(ctx)

    if blob_order is None:
        blob_order = derive_blob_order(ctx)

    path_table, bc = build_path_table(ctx, blob_order, a_values)

    tail = C.encode(root)
    node_start = 16 + len(class_table) + len(path_table)
    pool_size = node_start - 12
    tail_size = len(tail)

    header = struct.pack("<IIII", 4, pool_size, tail_size, class_count)
    return header + class_table + path_table


# ----------------------------------------------------------------------------- blob order (OPEN)
def derive_blob_order(ctx):
    """Best-effort blob-slice order. Default: children-before-parent DFS post-order
    over the Add tree with forward child order. (See section 8 — open item.)"""
    children = {o.get("Name"): [] for o in ctx.objs}
    for o in ctx.objs:
        oname = o.get("Name")
        for ch in o.iter():
            if ch.tag == "Add":
                tgt = ch.get("Task") or ch.get("Plan") or ch.get("Brain")
                if tgt is not None and tgt in children:
                    children[oname].append(tgt)
    order = []
    visited = set()

    def post(n):
        if n in visited:
            return
        visited.add(n)
        for c in children[n]:
            post(c)
        order.append(n)

    roots = [o.get("Name") for o in ctx.objs if o.get("Name") not in ctx.parent]
    for r in roots:
        post(r)
    for o in ctx.objs:
        if o.get("Name") not in visited:
            post(o.get("Name"))
    return order


if __name__ == "__main__":
    pass
