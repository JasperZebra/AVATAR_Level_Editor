#!/usr/bin/env python3
"""
Mesh data structures and processing
"""

import math
from typing import List, Tuple, Optional
from math_utils import Vector


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


def parse_mesh_vertices(g, mesh: Mesh, vert_pos_scale: float, uv_trans: float, uv_scale: float):
    """Parse vertex data for a mesh.

    Vectorised: one bulk read of the whole vertex section, then numpy slicing at
    fixed byte offsets (pos = 3×int16 @0, uv = 2×int16 @8, skin = 8×uint8 @16 for
    stride-40). This replaces a Python per-vertex loop that was ~40× slower and
    dominated model load time. Falls back to the per-vertex loop on any error.
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
        # Position: 3 little-endian int16 at byte 0 (4th int16 @6 is skipped).
        # Keep the numpy array (no .tolist()) — build_xbg_model + compute_face_normals
        # consume it directly, so we never round-trip through Python lists.
        pos = (arr[:, 0:6].copy().view('<i2').reshape(n, 3).astype(np.float32)
               * vert_pos_scale)
        mesh.vert_pos_arr = pos
        if stride >= 12:
            # UV: 2 int16 at byte 8.
            uv = (arr[:, 8:12].copy().view('<i2').reshape(n, 2).astype(np.float32)
                  * uv_scale + uv_trans)
            mesh.vert_uv_arr = uv
        if stride == 40:
            mesh.skin_weight_list = [tuple(r) for r in arr[:, 16:20].tolist()]
            mesh.skin_indice_list = [tuple(r) for r in arr[:, 20:24].tolist()]
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