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
    """Compute per-vertex normals by averaging area-weighted face normals."""
    verts = mesh.vert_pos_list
    if not verts:
        return

    normals = [[0.0, 0.0, 0.0] for _ in range(len(verts))]

    all_tris = []
    for prim in mesh.primitives:
        inds = prim.indices
        for i in range(0, len(inds) - 2, 3):
            all_tris.append((inds[i], inds[i + 1], inds[i + 2]))

    nv = len(verts)
    for i0, i1, i2 in all_tris:
        if i0 >= nv or i1 >= nv or i2 >= nv:
            continue
        v0, v1, v2 = verts[i0], verts[i1], verts[i2]
        ax = v1[0] - v0[0]; ay = v1[1] - v0[1]; az = v1[2] - v0[2]
        bx = v2[0] - v0[0]; by = v2[1] - v0[1]; bz = v2[2] - v0[2]
        cx = ay * bz - az * by
        cy = az * bx - ax * bz
        cz = ax * by - ay * bx
        for idx in (i0, i1, i2):
            normals[idx][0] += cx
            normals[idx][1] += cy
            normals[idx][2] += cz

    for i, n in enumerate(normals):
        length = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
        if length > 1e-6:
            normals[i] = [n[0] / length, n[1] / length, n[2] / length]
        else:
            normals[i] = [0.0, 1.0, 0.0]

    mesh.vert_normal_list = normals


def parse_mesh_vertices(g, mesh: Mesh, vert_pos_scale: float, uv_trans: float, uv_scale: float):
    """Parse vertex data for a mesh"""
    g.seek(mesh.vert_section_offset)
    
    for m in range(mesh.vert_count):
        tm = g.tell()
        
        # Read vertex position
        pos_data = g.h(3)
        pos = Vector(pos_data) * vert_pos_scale
        mesh.vert_pos_list.append(pos.to_list())
        
        g.h(1)  # skip
        
        # Read UV coordinates
        u = uv_trans + g.h(1)[0] * uv_scale
        v = uv_trans + g.h(1)[0] * uv_scale
        mesh.vert_uv_list.append([u, v])
        
        g.seek(4, 1)  # skip 4 bytes
        
        # Read skinning data if present
        if mesh.vert_stride == 40:
            mesh.skin_weight_list.append(g.B(4))
            mesh.skin_indice_list.append(g.B(4))
        
        g.seek(tm + mesh.vert_stride)