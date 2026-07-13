"""RealTree (.rtx) vegetation-mesh loader for the Avatar / Far Cry 2 editor.

The game's trees, bushes, grass and shrooms are NOT .xbg models — they are
`.rtx` RealTree files (a SpeedTree-like proprietary format). Level vegetation
(see VegetationData in the landmarkfar_*.fcb files) references these by a CRC32
of the model path. This module reverse-engineers the `.rtx` mesh so the editor
can render the real vegetation geometry instead of nothing.

Format (little-endian throughout), reverse-engineered from the Avatar data:
  * Header: u32@0 = filesize-8 ; u32@8 = 138 (const) ; then the source `.rta`
    path string @0x18. Internal pointers are ABSOLUTE with base = the smallest
    pointer value, which maps to file offset 0x100.
  * VERTEX BUFFER: interleaved float32 records at a 32-byte stride; the vertex
    POSITION is the first 3 floats (x, y, z) of each record. (Game space is
    Z-up.)
  * TRIANGLES: one or more "draw-record" arrays. Each record is 40 bytes with a
    0xFFFFFFFF marker at +28; u32@+0 = strip start vertex, u32@+4 = strip vertex
    count. These are TRIANGLE STRIPS that index DIRECTLY into the vertex buffer
    (there is no separate index buffer). Consecutive records chain as
    next.start == prev.start + prev.count + 1.

Validated on rt_of_bush_a/b/c, rt_shroom_a, hya_risingstar_a, rt_baobab_a: all
reconstruct to geometrically coherent meshes (triangle edge lengths well within
each model's bounding box).

Public API:
    load_rtx(path) -> RtxMesh | None
    RtxMesh: .positions (list[(x,y,z)]), .triangles (list[(a,b,c)]),
             .materials (list[str] of .mlm paths), .bbox ((minx,miny,minz),(maxx,maxy,maxz))
"""

import struct
import os


class RtxMesh:
    __slots__ = ("positions", "triangles", "materials", "bbox", "source")

    def __init__(self, positions, triangles, materials, bbox, source=""):
        self.positions = positions      # list of (x, y, z) in GAME space (Z-up)
        self.triangles = triangles      # list of (a, b, c) indices into positions
        self.materials = materials       # list of .mlm material paths (strings)
        self.bbox = bbox                # ((minx,miny,minz), (maxx,maxy,maxz))
        self.source = source

    def __repr__(self):
        return "RtxMesh(%d verts, %d tris, %d mats)" % (
            len(self.positions), len(self.triangles), len(self.materials))


def _decode_strip_run(recs):
    """Turn a contiguous run of (col0, col1) draw records into a list of
    (firstVertex, vertexCount) triangle strips. Two encodings are seen in the
    data, distinguished by col0:
      * col0 varies and chains (next.start == start + count + 1): col0=start,
        col1=count  (openfield trees/bushes; 1-vertex gap between strips).
      * col0 is always 0: col1 is a CUMULATIVE end offset, so each strip is
        [prev_end, col1)  (rainforest realtree; contiguous strips).
    Records with an out-of-range count are treated as the end of the real run
    (they're trailing non-strip data that merely carried a 0xFFFFFFFF word)."""
    clean = []
    for s, c in recs:
        if c >= 100000:
            break
        clean.append((s, c))
    if len(clean) < 3:
        return []
    if all(s == 0 for s, _ in clean):
        # cumulative-end form; col1 must be monotonic non-decreasing
        strips = []
        prev = 0
        for _, end in clean:
            if end < prev or end - prev > 100000:
                break
            if end - prev >= 3:
                strips.append((prev, end - prev))
            prev = end
        return strips
    # (start, count) form; keep the leading cleanly-chaining run
    good = []
    for s, c in clean:
        if good:
            ps, pc = good[-1]
            if s != ps + pc + 1:
                break
        good.append((s, c))
    return good if len(good) >= 3 else []


def _find_strip_arrays(data, n):
    """Locate every draw-record (triangle-strip) array: runs of 40-byte records
    whose u32@+28 == 0xFFFFFFFF AND whose (start, count) fields CHAIN as
    next.start == start + count + 1 (this is what distinguishes a real strip
    list from an incidental 0xFFFFFFFF alignment). Returns a list of (start,
    count) strips indexing into the vertex buffer."""
    u32 = lambda o: struct.unpack_from("<I", data, o)[0]
    strips = []
    seen = set()
    o = 0
    while o + 40 <= n:
        if u32(o + 28) == 0xFFFFFFFF:
            p = o
            while p - 40 >= 0 and u32(p - 40 + 28) == 0xFFFFFFFF:
                p -= 40
            if p in seen:
                o += 4
                continue
            recs = []
            q = p
            while q + 40 <= n and u32(q + 28) == 0xFFFFFFFF:
                recs.append((u32(q), u32(q + 4)))
                seen.add(q)
                q += 40
            strips.extend(_decode_strip_run(recs))
            o = q
        else:
            o += 4
    return strips


def _is_pos(data, n, o):
    if o + 12 > n:
        return False
    x, y, z = struct.unpack_from("<fff", data, o)
    return all(abs(v) < 1e3 for v in (x, y, z)) and any(v != 0.0 for v in (x, y, z))


def _find_vertex_buffer(data, n, min_count):
    """First 32-byte-stride float run of valid positions with >= min_count verts."""
    for base in range(0x100, n - 32, 4):
        if all(_is_pos(data, n, base + k * 32) for k in range(4)):
            cnt = 0
            while _is_pos(data, n, base + cnt * 32):
                cnt += 1
            if cnt >= min_count:
                return base, cnt
    return None, 0


def _materials(data, n):
    out = []
    low = data.lower()
    key = b".mlm"
    i = low.find(key)
    while i != -1:
        s = i
        while s > 0 and 32 <= data[s - 1] < 127:
            s -= 1
        try:
            out.append(data[s:i + 4].decode("latin-1"))
        except Exception:
            pass
        i = low.find(key, i + 4)
    # de-dup preserving order
    seen = set(); uniq = []
    for m in out:
        if m not in seen:
            seen.add(m); uniq.append(m)
    return uniq


def load_rtx(path):
    """Parse a .rtx file into an RtxMesh, or return None if no geometry found."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    n = len(data)
    if n < 0x120:
        return None

    strips = _find_strip_arrays(data, n)
    if not strips:
        return None
    max_idx = max(s + c for s, c in strips)

    vb, vn = _find_vertex_buffer(data, n, max_idx)
    if not vb:
        return None

    f32 = lambda o: struct.unpack_from("<f", data, o)[0]
    positions = [(f32(vb + k * 32), f32(vb + k * 32 + 4), f32(vb + k * 32 + 8))
                 for k in range(vn)]

    triangles = []
    for s, c in strips:
        for i in range(c - 2):
            a, b, d = s + i, s + i + 1, s + i + 2
            if a >= vn or b >= vn or d >= vn:
                continue
            # strip winding alternates each step
            triangles.append((a, d, b) if (i & 1) else (a, b, d))

    if not triangles:
        return None

    xs = [p[0] for p in positions]; ys = [p[1] for p in positions]; zs = [p[2] for p in positions]
    bbox = ((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))
    return RtxMesh(positions, triangles, _materials(data, n), bbox, os.path.basename(path))


def export_obj(mesh, out_path):
    """Debug helper: dump an RtxMesh to a Wavefront .obj."""
    with open(out_path, "w") as fh:
        for x, y, z in mesh.positions:
            fh.write("v %f %f %f\n" % (x, y, z))
        for a, b, c in mesh.triangles:
            fh.write("f %d %d %d\n" % (a + 1, b + 1, c + 1))


if __name__ == "__main__":
    import sys
    m = load_rtx(sys.argv[1])
    print(m)
    if m and len(sys.argv) > 2:
        export_obj(m, sys.argv[2])
        print("wrote", sys.argv[2])
