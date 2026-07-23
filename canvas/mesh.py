#!/usr/bin/env python3
"""
Mesh data structures and processing
"""

import math
from typing import List, Tuple, Optional
from math_utils import Vector


# ── XBG vertex format flags (SDOL per-VB flags word) ─────────────────────────
# Port of the XBG Importer v3 addon's VertexFlags. Components appear in the
# vertex stride in the _VERTEX_COMPONENT_ORDER below, each contributing its
# size only when its flag bit is set. Position flags are mutually exclusive.
POS_FLOAT = 0x0001   # 12B: 3×float32
POS_INT16 = 0x0002   # 8B:  3×int16 + 2 pad (dequantize by PMCP vert_pos_scale)
POS_HALF  = 0x0004   # 8B:  3×float16 + pad
UV0       = 0x0008   # 4B:  2×int16 (dequantize by PMCU)
BONE_WTS1 = 0x0010   # 8B:  4×uint8 weights + 4×uint8 palette indices
BONE_WTS2 = 0x0020   # 8B:  second influence set (not decoded)
NORMAL    = 0x0040   # 4B:  3×uint8 D3DCOLOR (unsigned BGRA) + 1 byte
COLOR     = 0x0080   # 4B:  4×uint8 BGRA
TANGENT   = 0x0100   # 4B:  3×uint8 D3DCOLOR + handedness byte (usually 0x80)
BINORMAL  = 0x0200   # 4B:  3×uint8 D3DCOLOR + handedness byte
UNK_400   = 0x0400   # 4B:  unknown, skipped
UV1       = 0x0800   # 4B:  2×int16; (-32768,-32768) = unused sentinel
UV2       = 0x1000   # 4B:  2×int16; same sentinel

_VERTEX_COMPONENT_ORDER = (
    ('pos_float', POS_FLOAT, 12),
    ('pos_int16', POS_INT16, 8),
    ('pos_half',  POS_HALF,  8),
    ('uv0',       UV0,       4),
    ('uv1',       UV1,       4),
    ('uv2',       UV2,       4),
    ('bone1',     BONE_WTS1, 8),
    ('bone2',     BONE_WTS2, 8),
    ('normal',    NORMAL,    4),
    ('color',     COLOR,     4),
    ('tangent',   TANGENT,   4),
    ('binormal',  BINORMAL,  4),
    ('unk400',    UNK_400,   4),
)


def compute_component_offsets(flags: int) -> Tuple[dict, int]:
    """Byte offset of each vertex component for an XBG format flags word.

    Returns ({component_key: offset}, computed_stride). The caller should trust
    the offsets only when computed_stride matches the SDOL stride — that's the
    addon-verified validity check (known-good words: 0x0BCA=32B static,
    0x0BDA=40B skinned).
    """
    offsets = {}
    stride = 0
    for key, bit, size in _VERTEX_COMPONENT_ORDER:
        if flags & bit:
            offsets[key] = stride
            stride += size
    return offsets, stride


class MeshPrimitive:
    """A group of faces sharing a material"""
    def __init__(self):
        self.indices: List[int] = []
        self.material_index: int = 0
        self.material_name: str = "Default"


class Mesh:
    """Mesh data structure"""
    def __init__(self):
        self.vert_pos_list: List[List[float]] = []
        self.vert_uv_list: List[List[float]] = []
        self.vert_normal_list: List[List[float]] = []
        # Numpy fast-path arrays. parse_mesh_vertices / compute_face_normals fill
        # these and SKIP the .tolist() conversion; consumers (compute_face_normals,
        # build_xbg_model) prefer them. This kills the numpy->list->numpy round-trips
        # that dominated model-load time and — being pure-Python — held the GIL,
        # which is why the parallel loader wasn't scaling. None = use the lists.
        self.vert_pos_arr = None      # (N,3) float32
        self.vert_uv_arr = None       # (N,2) float32
        self.vert_normal_arr = None   # (N,3) float32
        # Authored (file-decoded) vertex attributes — filled when the vertex
        # format flags say the component exists. has_authored_normals
        # distinguishes decoded normals from compute_face_normals output.
        self.has_authored_normals = False
        self.vert_tangent_arr = None  # (N,3) float32 (handedness byte separate)
        self.tangent_sign_arr = None  # (N,) uint8 raw handedness byte
        self.vert_color_arr = None    # (N,4) uint8 RGBA

        # Replaced simple face_list with list of primitives
        self.primitives: List[MeshPrimitive] = []
        
        # Legacy support (optional, can be used for validation)
        self.face_list: List[List[int]] = [] 
        
        self.mat_list_info: List[Tuple] = []
        self.skin_weight_list: List[Tuple] = []
        self.skin_indice_list: List[Tuple] = []
        self.vert_count: int = 0
        self.face_count: int = 0
        self.vert_stride: int = 0
        self.vert_format_flags: int = 0
        self.vert_section_offset: int = 0
        self.indice_section_offset: int = 0
        self.lod_level: int = 0
        self.part_number: int = 0
        self.sub_part_index: int = -1
        self.vb_index: int = 0
        self.name_index: int = 0   # flat positional index within the LOD (SDOL order)

    def add_vertex(self, position: List[float], uv: Optional[List[float]] = None):
        """Add a vertex to the mesh"""
        self.vert_pos_list.append(position)
        if uv:
            self.vert_uv_list.append(uv)
            
    def add_primitive(self, indices: List[int], mat_idx: int, mat_name: str):
        """Add a primitive (material group) to the mesh"""
        prim = MeshPrimitive()
        prim.indices = indices
        prim.material_index = mat_idx
        prim.material_name = mat_name
        self.primitives.append(prim)
        
        # Keep legacy flat list for debug if needed
        # Convert triangle strip/list to raw faces for flat list if necessary
        # But for GLTF we use indices directly
        pass


class SubMesh:
    """Submesh data for material groups"""
    def __init__(self):
        self.header_data: List[int] = []
        self.bone_data: List[int] = []
        self.face_count: int = 0
        
    def get_face_count(self) -> int:
        """Get face count from header data"""
        if len(self.header_data) > 1:
            return self.header_data[1]
        return 0


def compute_face_normals(mesh: Mesh):
    """Compute per-vertex normals by averaging area-weighted face normals.

    Vectorised (numpy cross + scatter-add) — was a Python per-triangle loop that
    cost a big chunk of model load time. Falls back to the loop on any error.

    Prefers mesh.vert_pos_arr (numpy) and writes mesh.vert_normal_arr (numpy), so
    positions/normals never round-trip through Python lists during load."""
    import numpy as np
    varr = getattr(mesh, 'vert_pos_arr', None)
    if varr is not None and len(varr):
        v = np.asarray(varr, dtype=np.float64)
    elif mesh.vert_pos_list:
        v = np.asarray(mesh.vert_pos_list, dtype=np.float64)
    else:
        return

    try:
        idx = []
        for prim in mesh.primitives:
            idx.extend(prim.indices)
        if not idx:
            return
        nv = v.shape[0]
        tri = np.asarray(idx, dtype=np.int64)
        tri = tri[: (len(tri) // 3) * 3].reshape(-1, 3)
        tri = tri[(tri < nv).all(axis=1)]            # drop out-of-range tris
        i0, i1, i2 = tri[:, 0], tri[:, 1], tri[:, 2]
        # OUTWARD area-weighted face normal. XBG is CW-wound, so cross(e1,e2)
        # points INWARD — use cross(e2,e1) so lit/normal-mapped surfaces face out
        # (was inward, which inverted normal-map detail under the TBN).
        fn = np.cross(v[i2] - v[i0], v[i1] - v[i0])
        normals = np.zeros_like(v)
        np.add.at(normals, i0, fn)
        np.add.at(normals, i1, fn)
        np.add.at(normals, i2, fn)
        ln = np.linalg.norm(normals, axis=1)
        good = ln > 1e-6
        normals[good] /= ln[good, None]
        normals[~good] = (0.0, 1.0, 0.0)
        mesh.vert_normal_arr = normals.astype(np.float32)   # keep numpy (no .tolist())
        return
    except Exception as _e:
        print(f"  compute_face_normals: vectorised path failed ({_e}); using slow loop")

    # Fallback works off the numpy `v` (vert_pos_list may be empty on the fast path).
    normals = [[0.0, 0.0, 0.0] for _ in range(v.shape[0])]
    all_tris = []
    for prim in mesh.primitives:
        inds = prim.indices
        for i in range(0, len(inds) - 2, 3):
            all_tris.append((inds[i], inds[i + 1], inds[i + 2]))
    nv = v.shape[0]
    for i0, i1, i2 in all_tris:
        if i0 >= nv or i1 >= nv or i2 >= nv:
            continue
        v0, v1, v2 = v[i0], v[i1], v[i2]
        # cross(e2,e1) → OUTWARD for CW-wound XBG (see vectorised path above).
        ax = v2[0] - v0[0]; ay = v2[1] - v0[1]; az = v2[2] - v0[2]
        bx = v1[0] - v0[0]; by = v1[1] - v0[1]; bz = v1[2] - v0[2]
        cx = ay * bz - az * by
        cy = az * bx - ax * bz
        cz = ax * by - ay * bx
        for vid in (i0, i1, i2):
            normals[vid][0] += cx
            normals[vid][1] += cy
            normals[vid][2] += cz
    for i, n in enumerate(normals):
        length = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
        if length > 1e-6:
            normals[i] = [n[0] / length, n[1] / length, n[2] / length]
        else:
            normals[i] = [0.0, 1.0, 0.0]
    mesh.vert_normal_list = normals


def _decode_d3dcolor_vectors(arr, offset):
    """Decode a 4-byte D3DCOLOR vector column (normal/tangent/binormal).

    XBG Importer v3 addon fix: these are UNSIGNED-normalized bytes in BGRA
    order — value = b/255*2-1, and XYZ come from bytes (2,1,0) (x = byte2).
    The old obvious guesses (signed int8, in-order) scramble axes. Returns a
    unit-normalized (N,3) float32 array (degenerates fall back to +Z).
    """
    import numpy as np
    v = (arr[:, [offset + 2, offset + 1, offset + 0]].astype(np.float32)
         / 255.0) * 2.0 - 1.0
    ln = np.linalg.norm(v, axis=1)
    good = ln > 1e-6
    v[good] /= ln[good, None]
    v[~good] = (0.0, 0.0, 1.0)
    return v.astype(np.float32)


def parse_mesh_vertices(g, mesh: Mesh, vert_pos_scale: float, uv_trans: float, uv_scale: float):
    """Parse vertex data for a mesh.

    Flag-driven (XBG Importer v3 addon port): component offsets are computed
    from the SDOL vertex format flags (mesh.vert_format_flags), and trusted
    only when the computed stride matches the SDOL stride. This decodes the
    AUTHORED normals/tangents/colors (previously the editor recomputed normals
    geometrically) using the addon's verified unsigned-BGRA D3DCOLOR formula.
    When the flags don't validate, falls back to the legacy fixed offsets
    (pos = 3×int16 @0, uv = 2×int16 @8, skin @16/20 for stride-40).

    UV convention: the editor keeps game-space V (no 1-V flip — the shaders
    and XBT decode assume it); do not copy the addon's Blender-side V flip.

    Vectorised: one bulk read + numpy slicing. Falls back to the per-vertex
    loop on any error.
    """
    count = mesh.vert_count
    stride = mesh.vert_stride
    if count <= 0 or stride <= 0:
        return

    g.seek(mesh.vert_section_offset)
    raw = g.read(count * stride)

    try:
        import numpy as np
        n = min(count, len(raw) // stride)
        if n <= 0:
            return
        arr = np.frombuffer(raw, dtype=np.uint8, count=n * stride).reshape(n, stride)

        offs, computed_stride = compute_component_offsets(mesh.vert_format_flags)
        flags_ok = bool(offs) and computed_stride == stride

        # ── Position ──
        if flags_ok and 'pos_float' in offs:
            o = offs['pos_float']
            pos = arr[:, o:o + 12].copy().view('<f4').reshape(n, 3).astype(np.float32)
        elif flags_ok and 'pos_half' in offs:
            # float16 positions carry real coordinates (no PMCP dequant — the
            # int16 quantization scale doesn't apply to float storage).
            o = offs['pos_half']
            pos = arr[:, o:o + 6].copy().view('<f2').reshape(n, 3).astype(np.float32)
        else:
            # pos_int16, or legacy fallback layout (int16 @0).
            o = offs.get('pos_int16', 0) if flags_ok else 0
            pos = (arr[:, o:o + 6].copy().view('<i2').reshape(n, 3).astype(np.float32)
                   * vert_pos_scale)
        mesh.vert_pos_arr = pos

        # ── UV0 ──
        if flags_ok:
            uv_off = offs.get('uv0')
        else:
            uv_off = 8 if stride >= 12 else None
        if uv_off is not None and uv_off + 4 <= stride:
            uv = (arr[:, uv_off:uv_off + 4].copy().view('<i2').reshape(n, 2)
                  .astype(np.float32) * uv_scale + uv_trans)
            mesh.vert_uv_arr = uv

        # ── Authored normal / tangent / color (flag path only) ──
        if flags_ok and 'normal' in offs:
            mesh.vert_normal_arr = _decode_d3dcolor_vectors(arr, offs['normal'])
            mesh.has_authored_normals = True
        if flags_ok and 'tangent' in offs:
            to = offs['tangent']
            mesh.vert_tangent_arr = _decode_d3dcolor_vectors(arr, to)
            mesh.tangent_sign_arr = arr[:, to + 3].copy()
        if flags_ok and 'color' in offs:
            co = offs['color']
            # Stored BGRA → RGBA (bytes 2,1,0,3), kept uint8.
            mesh.vert_color_arr = arr[:, [co + 2, co + 1, co + 0, co + 3]].copy()

        # ── Skin weights / palette indices ──
        if flags_ok:
            bone_off = offs.get('bone1')
        else:
            bone_off = 16 if stride == 40 else None
        if bone_off is not None and bone_off + 8 <= stride:
            mesh.skin_weight_list = [tuple(r) for r in arr[:, bone_off:bone_off + 4].tolist()]
            mesh.skin_indice_list = [tuple(r) for r in arr[:, bone_off + 4:bone_off + 8].tolist()]
        return
    except Exception as _e:
        print(f"  parse_mesh_vertices: vectorised path failed ({_e}); using slow loop")

    # ── Fallback: original per-vertex loop ──
    mesh.vert_pos_list = []
    mesh.vert_uv_list = []
    mesh.skin_weight_list = []
    mesh.skin_indice_list = []
    g.seek(mesh.vert_section_offset)
    for m in range(count):
        tm = g.tell()
        pos_data = g.h(3)
        pos = Vector(pos_data) * vert_pos_scale
        mesh.vert_pos_list.append(pos.to_list())
        g.h(1)  # skip
        u = uv_trans + g.h(1)[0] * uv_scale
        v = uv_trans + g.h(1)[0] * uv_scale
        mesh.vert_uv_list.append([u, v])
        g.seek(4, 1)  # skip 4 bytes
        if mesh.vert_stride == 40:
            mesh.skin_weight_list.append(g.B(4))
            mesh.skin_indice_list.append(g.B(4))
        g.seek(tm + mesh.vert_stride)