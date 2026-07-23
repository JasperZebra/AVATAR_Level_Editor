#!/usr/bin/env python3
"""Native .hkx (Havok 5.5) collision reader — port of the XBG Importer v3
addon's `hkx_native_avatar.py` read path (the FC2 copy is byte-identical, so
this single module serves BOTH games).

Avatar / Far Cry 2 .hkx files are Havok 5.5.0-r1 BINARY PACKFILES (32-bit LE,
layout 04 01 00 01), optionally behind the game's 16-byte wrapper header. The
packfile's __types__ section is empty but __data__ carries full fixup tables,
which is everything needed to read it:

    virtual fixups : object offset -> class name    (object enumeration)
    global fixups  : pointer field -> target object (shape graph edges)
    local fixups   : array field   -> array data    (verts, indices, names)

Never dereference raw pointer bytes inside objects — always resolve through
the fixup dicts keyed by the pointer FIELD's data-relative offset.

Confirmed Havok 5.5 32-bit member offsets (object-relative):
    hkpShape base           : +0x10 f32 radius (convex/sphere/capsule)
    hkpBoxShape             : +0x20 hkVector4 halfExtents
    hkpSphereShape          : +0x10 f32 radius (no other geometry)
    hkpCapsule/CylinderShape: +0x20 vertexA, +0x30 vertexB
    hkpConvexTranslateShape : +0x20 hkVector4 translation
    hkpConvexTransformShape : +0x20/0x30/0x40 rotation columns, +0x50 trans
    hkpConvexVerticesShape  : +0x40 m_rotatedVertices (FourVectors SoA:
                              48-byte chunks = x[4] y[4] z[4]; vertex j of a
                              chunk is (v[j], v[4+j], v[8+j])), +0x4c count
    hkpListShape            : +0x18 childInfo array (16-byte entries, child
                              shape ptr at entry+0 via GLOBAL fixup), +0x1c n
    hkpMoppBvTreeShape      : transparent wrapper — descend, ignore bytecode
    *MeshSubpartStorage     : +0x08 m_vertices (hkVector4 AoS, use xyz),
                              +0x0c count, +0x14 m_indices16 (u16 stride 4:
                              a, b, c, pad), +0x18 index count
    hkpRigidBody            : +0x10 shape ptr, +0xE0/0xF0/0x100 rotation
                              columns + 0x110 translation (world transform)

Coordinate space: raw Havok = game space (right-handed Z-up meters) — the
same space as .xbg model vertices, so the editor's usual entity transform
(overlay_matrix: translate, -90°X, rotations, scale) applies unchanged.

GL-free on purpose (safe on loader threads). Consumers use
`load_collision_wireframe(path)` → world = rb_xform @ shape_xform baked in,
returned as flat GL_LINES segment pairs ready for LineBatch.
"""

import os
import struct

import numpy as np

HAVOK_MAGIC = b'\x57\xe0\xe0\x57\x10\xc0\xc0\x10'

_SHAPE_CLASSES = {
    'hkpBoxShape', 'hkpConvexTranslateShape', 'hkpConvexTransformShape',
    'hkpConvexVerticesShape', 'hkpListShape', 'hkpMoppBvTreeShape',
    'hkpStorageExtendedMeshShape', 'hkpExtendedMeshShape', 'hkpSphereShape',
    'hkpCapsuleShape', 'hkpCylinderShape', 'hkpTriangleShape',
}

# Safety cap on wireframe size (a huge triangle collision mesh could emit
# hundreds of thousands of segments; beyond this we stop adding shapes).
_MAX_SEGMENTS = 120_000


class HkxFile:
    """Parsed Havok 5.5 packfile — read-only view (no patch/write support)."""

    def __init__(self, path, raw=None):
        self.path = path
        self.raw = raw if raw is not None else open(path, 'rb').read()
        # The game wrapper is 16 bytes before the Havok magic; some tools
        # strip it, so detect rather than assume.
        if self.raw[:8] == HAVOK_MAGIC:
            self.wrapper = 0
        elif self.raw[16:24] == HAVOK_MAGIC:
            self.wrapper = 16
        else:
            raise ValueError("not a Havok 5.5 packfile: %s" % path)
        d = self.raw[self.wrapper:]
        self.d = d

        num_sections, = struct.unpack_from('<i', d, 20)
        ver = d[40:56].split(b'\0')[0].decode('latin-1')
        if not ver.startswith('Havok-5.'):
            print("[HKX] warning: untested Havok version %r" % ver)
        self.version = ver

        self.sections = {}
        for i in range(num_sections):
            off = 64 + i * 48
            tag = d[off:off + 19].split(b'\0')[0].decode('latin-1')
            vals = struct.unpack_from('<7i', d, off + 20)
            self.sections[tag] = dict(zip(
                ('abs', 'local', 'global', 'virtual', 'exports',
                 'imports', 'end'), vals))

        cn = self.sections['__classnames__']
        dat = self.sections['__data__']
        self.data_abs = dat['abs']
        self._cn_abs = cn['abs']

        def classname(off):
            e = d.index(b'\0', self._cn_abs + off)
            return d[self._cn_abs + off:e].decode('latin-1')

        # objects: data-section offset -> class name (virtual fixups)
        self.objects = {}
        p = self.data_abs + dat['virtual']
        while p + 12 <= self.data_abs + dat['exports']:
            o, s, c = struct.unpack_from('<3i', d, p); p += 12
            if o != -1:
                self.objects[o] = classname(c)
        self._sorted = sorted(self.objects)
        self.obj_size = {}
        for i, o in enumerate(self._sorted):
            nxt = (self._sorted[i + 1] if i + 1 < len(self._sorted)
                   else dat['local'])
            self.obj_size[o] = nxt - o

        # local fixups: from-offset -> to-offset (both data-relative)
        self.local = {}
        p = self.data_abs + dat['local']
        while p + 8 <= self.data_abs + dat['global']:
            f, t = struct.unpack_from('<2i', d, p); p += 8
            if f != -1:
                self.local[f] = t
        # global fixups: from-offset -> target object offset
        self.globals = {}
        p = self.data_abs + dat['global']
        while p + 12 <= self.data_abs + dat['virtual']:
            f, s, t = struct.unpack_from('<3i', d, p); p += 12
            if f != -1:
                self.globals[f] = t

    # ── primitives ──────────────────────────────────────────────────────
    def f32s(self, data_off, n):
        return struct.unpack_from('<%df' % n, self.d, self.data_abs + data_off)

    def u32(self, data_off):
        return struct.unpack_from('<I', self.d, self.data_abs + data_off)[0]

    def u16s(self, data_off, n):
        return struct.unpack_from('<%dH' % n, self.d, self.data_abs + data_off)

    def obj_globals(self, obj_off):
        """Global fixups whose pointer field lies inside this object,
        sorted by field offset -> [(field_off, target_obj_off)]."""
        end = obj_off + self.obj_size[obj_off]
        return sorted((f, t) for f, t in self.globals.items()
                      if obj_off <= f < end)

    def obj_name(self, obj_off):
        """hkpWorldObject m_name: a local fixup inside the object header
        whose target is a printable NUL-terminated string."""
        end = obj_off + min(self.obj_size[obj_off], 0x80)
        for f, t in self.local.items():
            if obj_off <= f < end:
                a = self.data_abs + t
                e = self.d.index(b'\0', a)
                s = self.d[a:e]
                if 0 < len(s) < 96 and all(0x20 <= c < 0x7F for c in s):
                    return s.decode('latin-1')
        return None

    # ── shape graph ─────────────────────────────────────────────────────
    def shape_children(self, obj_off):
        """Child SHAPE objects pointed to from inside this object."""
        return [(f, t) for f, t in self.obj_globals(obj_off)
                if self.objects.get(t) in _SHAPE_CLASSES]

    def walk_shape(self, obj_off, xform=None, out=None):
        """Flatten the shape graph into leaf records:
        [{'class', 'off', 'xform' (4×4 numpy), ...geometry}]."""
        if out is None:
            out = []
        xf = xform if xform is not None else np.eye(4)
        cls = self.objects.get(obj_off)

        if cls == 'hkpBoxShape':
            out.append({'class': cls, 'off': obj_off, 'xform': xf,
                        'half_extents': self.f32s(obj_off + 0x20, 3),
                        'radius': self.f32s(obj_off + 0x10, 1)[0]})

        elif cls == 'hkpConvexVerticesShape':
            n = self.u32(obj_off + 0x4c)
            arr = self.local.get(obj_off + 0x40)
            verts = []
            if arr is not None:
                # FourVectors SoA: 48-byte chunks of 4 verts = x[4] y[4] z[4]
                nchunks = (n + 3) // 4
                for c in range(nchunks):
                    v = self.f32s(arr + c * 48, 12)
                    for j in range(min(4, n - c * 4)):
                        verts.append((v[j], v[4 + j], v[8 + j]))
            out.append({'class': cls, 'off': obj_off, 'xform': xf,
                        'verts': verts})

        elif cls in ('hkpStorageExtendedMeshShape', 'hkpExtendedMeshShape'):
            sto = next((t for f, t in self.obj_globals(obj_off)
                        if self.objects.get(t, '').endswith(
                            'MeshSubpartStorage')), None)
            verts, tris = [], []
            if sto is not None:
                voff = self.local.get(sto + 0x08)
                nv = self.u32(sto + 0x0c)
                ioff = self.local.get(sto + 0x14)
                ni = self.u32(sto + 0x18)
                if voff is not None:
                    for i in range(nv):
                        x, y, z, _ = self.f32s(voff + i * 16, 4)
                        verts.append((x, y, z))
                if ioff is not None:
                    idx = self.u16s(ioff, ni)
                    for i in range(0, ni - 3, 4):
                        a, b, c = idx[i], idx[i + 1], idx[i + 2]
                        if a != b and b != c and a != c:
                            tris.append((a, b, c))
            out.append({'class': cls, 'off': obj_off, 'xform': xf,
                        'verts': verts, 'tris': tris})

        elif cls in ('hkpCapsuleShape', 'hkpCylinderShape'):
            out.append({'class': cls, 'off': obj_off, 'xform': xf,
                        'verts': [self.f32s(obj_off + 0x20, 3),
                                  self.f32s(obj_off + 0x30, 3)],
                        'radius': self.f32s(obj_off + 0x10, 1)[0]})

        elif cls == 'hkpSphereShape':
            out.append({'class': cls, 'off': obj_off, 'xform': xf,
                        'radius': self.f32s(obj_off + 0x10, 1)[0]})

        elif cls == 'hkpConvexTranslateShape':
            t = self.f32s(obj_off + 0x20, 3)
            m = np.eye(4)
            m[:3, 3] = t
            for f, child in self.shape_children(obj_off):
                self.walk_shape(child, xf @ m, out)

        elif cls == 'hkpConvexTransformShape':
            c0 = self.f32s(obj_off + 0x20, 3)
            c1 = self.f32s(obj_off + 0x30, 3)
            c2 = self.f32s(obj_off + 0x40, 3)
            tr = self.f32s(obj_off + 0x50, 3)
            m = np.array([
                [c0[0], c1[0], c2[0], tr[0]],
                [c0[1], c1[1], c2[1], tr[1]],
                [c0[2], c1[2], c2[2], tr[2]],
                [0.0, 0.0, 0.0, 1.0]])
            for f, child in self.shape_children(obj_off):
                self.walk_shape(child, xf @ m, out)

        elif cls == 'hkpListShape':
            # children live in the childInfo ARRAY (local fixup at +0x18,
            # count at +0x1c, shape ptr at entry+0) — the array may sit
            # anywhere in the data section, not inside the object's range
            arr = self.local.get(obj_off + 0x18)
            cnt = self.u32(obj_off + 0x1c)
            if arr is not None:
                for i in range(cnt):
                    t = self.globals.get(arr + 16 * i)
                    if t is not None and \
                            self.objects.get(t) in _SHAPE_CLASSES:
                        self.walk_shape(t, xf, out)
            else:
                for f, child in self.shape_children(obj_off):
                    self.walk_shape(child, xf, out)

        elif cls == 'hkpMoppBvTreeShape':
            for f, child in self.shape_children(obj_off):
                self.walk_shape(child, xf, out)

        elif cls is not None:
            # unknown shape wrapper — descend through its shape pointers
            for f, child in self.shape_children(obj_off):
                self.walk_shape(child, xf, out)
        return out

    def rigid_bodies(self):
        """[{'off', 'name', 'xform' (4×4 numpy), 'shapes': [leaf records]}]"""
        out = []
        for o, cls in sorted(self.objects.items()):
            if cls != 'hkpRigidBody':
                continue
            c0 = self.f32s(o + 0xE0, 3)
            c1 = self.f32s(o + 0xF0, 3)
            c2 = self.f32s(o + 0x100, 3)
            tr = self.f32s(o + 0x110, 3)
            m = np.array([
                [c0[0], c1[0], c2[0], tr[0]],
                [c0[1], c1[1], c2[1], tr[1]],
                [c0[2], c1[2], c2[2], tr[2]],
                [0.0, 0.0, 0.0, 1.0]])
            shape = self.globals.get(o + 0x10)
            shapes = (self.walk_shape(shape) if shape is not None else [])
            out.append({'off': o, 'name': self.obj_name(o), 'xform': m,
                        'shapes': shapes})
        return out


# ──────────────────────────────────────────────────────────────────────
# Wireframe building (shape-local geometry → GL_LINES segment pairs)
# ──────────────────────────────────────────────────────────────────────

_BOX_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0),
              (4, 5), (5, 6), (6, 7), (7, 4),
              (0, 4), (1, 5), (2, 6), (3, 7))


def _circle_pts(radius, axis, n=16):
    """Unit-frame circle of `radius` around origin in the plane ⊥ `axis`
    (axis: 0=x, 1=y, 2=z). Returns (n,3)."""
    t = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    pts = np.zeros((n, 3))
    a, b = [(1, 2), (0, 2), (0, 1)][axis]
    pts[:, a] = np.cos(t) * radius
    pts[:, b] = np.sin(t) * radius
    return pts


def _loop_segments(pts):
    """Closed polygon (N,3) → (2N,3) GL_LINES pairs."""
    n = len(pts)
    seg = np.empty((n * 2, 3))
    seg[0::2] = pts
    seg[1::2] = np.roll(pts, -1, axis=0)
    return seg


def _edges_to_segments(verts, edges):
    v = np.asarray(verts, dtype=np.float64)
    seg = np.empty((len(edges) * 2, 3))
    for i, (a, b) in enumerate(edges):
        seg[2 * i] = v[a]
        seg[2 * i + 1] = v[b]
    return seg


def _convex_edge_segments(verts):
    """Edges of the convex hull of a point cloud; AABB edges as fallback."""
    v = np.asarray(verts, dtype=np.float64)
    if len(v) >= 4:
        try:
            from scipy.spatial import ConvexHull
            hull = ConvexHull(v)
            edges = set()
            for simplex in hull.simplices:
                for i in range(3):
                    a, b = int(simplex[i]), int(simplex[(i + 1) % 3])
                    edges.add((a, b) if a < b else (b, a))
            return _edges_to_segments(v, sorted(edges))
        except Exception:
            pass
    # Fallback: AABB of the points (degenerate clouds / no scipy).
    lo, hi = v.min(axis=0), v.max(axis=0)
    corners = np.array([[x, y, z] for z in (lo[2], hi[2])
                        for y in (lo[1], hi[1]) for x in (lo[0], hi[0])])
    # reorder to the _BOX_EDGES corner convention
    c = np.array([corners[0], corners[1], corners[3], corners[2],
                  corners[4], corners[5], corners[7], corners[6]])
    return _edges_to_segments(c, _BOX_EDGES)


def shape_wire_segments(rec):
    """Shape-LOCAL wireframe segments (K·2, 3) float64 for one leaf record."""
    cls = rec['class']
    if cls == 'hkpBoxShape':
        hx, hy, hz = rec['half_extents']
        corners = np.array([[-hx, -hy, -hz], [hx, -hy, -hz],
                            [hx, hy, -hz], [-hx, hy, -hz],
                            [-hx, -hy, hz], [hx, -hy, hz],
                            [hx, hy, hz], [-hx, hy, hz]])
        return _edges_to_segments(corners, _BOX_EDGES)

    if cls == 'hkpSphereShape':
        r = rec['radius']
        return np.concatenate([_loop_segments(_circle_pts(r, ax))
                               for ax in (0, 1, 2)])

    if cls in ('hkpCapsuleShape', 'hkpCylinderShape'):
        a = np.asarray(rec['verts'][0], dtype=np.float64)
        b = np.asarray(rec['verts'][1], dtype=np.float64)
        r = rec['radius']
        axis = b - a
        ln = np.linalg.norm(axis)
        axis = axis / ln if ln > 1e-9 else np.array([0.0, 0.0, 1.0])
        # orthonormal frame around the axis
        ref = np.array([1.0, 0.0, 0.0])
        if abs(axis @ ref) > 0.9:
            ref = np.array([0.0, 1.0, 0.0])
        u = np.cross(axis, ref)
        u /= np.linalg.norm(u)
        w = np.cross(axis, u)
        t = np.linspace(0.0, 2.0 * np.pi, 16, endpoint=False)
        ring = (np.outer(np.cos(t), u) + np.outer(np.sin(t), w)) * r
        segs = [_loop_segments(a + ring), _loop_segments(b + ring)]
        # four side lines connecting the end rings
        for k in (0, 4, 8, 12):
            segs.append(np.array([a + ring[k], b + ring[k]]))
        return np.concatenate(segs)

    if cls == 'hkpConvexVerticesShape':
        verts = rec.get('verts') or []
        if len(verts) >= 2:
            return _convex_edge_segments(verts)
        return np.zeros((0, 3))

    if cls in ('hkpStorageExtendedMeshShape', 'hkpExtendedMeshShape'):
        verts = rec.get('verts') or []
        tris = rec.get('tris') or []
        if not verts or not tris:
            return np.zeros((0, 3))
        edges = set()
        for a, b, c in tris:
            for p, q in ((a, b), (b, c), (c, a)):
                if p < len(verts) and q < len(verts):
                    edges.add((p, q) if p < q else (q, p))
        return _edges_to_segments(verts, sorted(edges))

    return np.zeros((0, 3))


def _apply_xform(seg, m4):
    if m4 is None or seg is None or not len(seg):
        return seg
    return seg @ np.asarray(m4)[:3, :3].T + np.asarray(m4)[:3, 3]


def find_collision_for_model(model_path):
    """Sibling .hkx for a .xbg model (foo.xbg ↔ foo.hkx), or None."""
    if not model_path:
        return None
    base, _ = os.path.splitext(model_path)
    hkx = base + '.hkx'
    return hkx if os.path.exists(hkx) else None


# path -> (mtime, segments float32 (N,3) | None). None = unreadable file
# (negative-cached so a broken .hkx isn't re-parsed every frame).
_wire_cache = {}
_WIRE_CACHE_MAX = 256


def load_collision_wireframe(path):
    """Model-space GL_LINES segment pairs for every shape of every rigid body
    in a .hkx file: (N·2, 3) float32, rb_xform @ shape_xform baked in.
    Returns None if the file can't be read. Cached by (path, mtime)."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    key = os.path.normcase(path)
    hit = _wire_cache.get(key)
    if hit is not None and hit[0] == mtime:
        return hit[1]

    segs = None
    try:
        hk = HkxFile(path)
        parts = []
        total = 0
        for rb in hk.rigid_bodies():
            for rec in rb['shapes']:
                s = shape_wire_segments(rec)
                if s is None or not len(s):
                    continue
                s = _apply_xform(s, rec.get('xform'))
                s = _apply_xform(s, rb.get('xform'))
                parts.append(s)
                total += len(s)
                if total > _MAX_SEGMENTS * 2:
                    print(f"[HKX] {os.path.basename(path)}: wireframe capped "
                          f"at {_MAX_SEGMENTS} segments")
                    break
            if total > _MAX_SEGMENTS * 2:
                break
        if parts:
            segs = np.concatenate(parts).astype(np.float32)
    except Exception as e:
        print(f"[HKX] failed to read {os.path.basename(path)}: {e}")
        segs = None

    while len(_wire_cache) >= _WIRE_CACHE_MAX:
        _wire_cache.pop(next(iter(_wire_cache)))
    _wire_cache[key] = (mtime, segs)
    return segs
