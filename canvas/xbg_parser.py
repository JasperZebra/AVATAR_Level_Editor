#!/usr/bin/env python3
"""
XBG file parser - Updated with Unsigned Integer Fixes for SDOL
"""

from typing import List, Optional
from binary_reader import BinaryReader
from mesh import Mesh, SubMesh, parse_mesh_vertices, compute_face_normals
from skeleton import Skeleton, parse_skeleton_chunk


class XBGData:
    """Container for XBG file data"""
    def __init__(self):
        self.skeleton = Skeleton()
        self.meshes: List[Mesh] = []
        self.sub_mesh_list: List[List[SubMesh]] = []
        self.materials: List[str] = []  # List of material names
        self.lod_count: int = 0
        self.vert_pos_scale: float = 1.0
        self.uv_trans: float = 0.0
        self.uv_scale: float = 1.0


class XBGParser:
    """Parser for XBG files"""
    
    def __init__(self, filename: str):
        self.filename = filename
        self.data = XBGData()
        
    def parse(self, lod_level: int = 0) -> XBGData:
        """Parse the XBG file"""
        with BinaryReader(self.filename) as g:
            # Read header
            g.word(4)
            header_data = g.i(7)
            chunk_count = header_data[6]
            
            print(f"Parsing {chunk_count} chunks...")
            
            # Parse chunks
            for m in range(chunk_count):
                back = g.tell()
                chunk = g.word(4)
                chunk_info = g.i(2)
                
                # Dispatch to chunk parsers
                self._parse_chunk(g, chunk)
                
                # Move to next chunk
                g.seek(back + chunk_info[1])
            
            # Filter meshes by LOD level
            self._filter_lod(lod_level)
            
            # Process mesh vertices
            self._process_mesh_vertices(g)
            
            # Remap bone indices using palette data
            self._remap_skin_indices(g)

            # Process mesh faces (Primitives splitting)
            self._process_mesh_faces(g)

            # Compute smooth normals from triangle geometry
            for mesh in self.data.meshes:
                if mesh.vert_pos_list:
                    compute_face_normals(mesh)

        return self.data
    
    def _parse_chunk(self, g, chunk: str):
        if chunk == 'PMCP':
            self._parse_pmcp(g)
        elif chunk == 'PMCU':
            self._parse_pmcu(g)
        elif chunk == 'EDON':
            parse_skeleton_chunk(g, self.data.skeleton)
        elif chunk == 'DIKS':
            self._parse_diks(g)
        elif chunk == 'SDOL':
            self._parse_sdol(g)
        elif chunk == 'DNKS':
            self._parse_dnks(g)
        elif chunk == 'LTMR':
            self._parse_ltmr(g)
        else:
            g.i(2)
    
    def _parse_pmcp(self, g):
        g.i(2)
        unk, self.data.vert_pos_scale = g.f(2)
    
    def _parse_pmcu(self, g):
        g.i(2)
        self.data.uv_trans, self.data.uv_scale = g.f(2)
    
    def _parse_diks(self, g):
        g.i(2)
        self.data.lod_count = g.i(1)[0]
        for m in range(self.data.lod_count):
            g.H(2)
            g.B(4)

    def _parse_ltmr(self, g):
        """Parse LTMR chunk - Material list"""
        print("Parsing Materials (LTMR)...")
        g.tell()
        w = g.i(4)
        mat_count = w[2]
        
        for m in range(mat_count):
            # Read material file path string
            name_len = g.i(1)[0]
            mat_file = g.word(name_len)
            
            # Store simple name
            simple_name = mat_file.split('/')[-1].replace('.mat', '')
            if not simple_name:
                simple_name = f"Material_{m}"
                
            self.data.materials.append(simple_name)
            print(f"  Found Material {m}: {simple_name}")
            
            # Skip the rest of the material definition bytes
            g.b(1) 

    def _parse_sdol(self, g):
        """Parse SDOL chunk with proper parts/subparts handling"""
        g.i(2)
        lod_count = g.i(1)[0]
        
        if lod_count == 0:
            print("SDOL lod_count=0, no data")
            return
        
        print(f"Parsing {lod_count} LOD levels in SDOL...")
        mesh_dict = {}
        
        # Loop through each LOD level
        for current_lod in range(lod_count):
            lod_dist = g.f(1)[0]
            vb_count = g.i(1)[0]
            
            # Read vertex buffer info
            vb_info = []
            for vb in range(vb_count):
                vb_flags = g.i(1)[0]
                vb_stride = g.i(1)[0]
                vb_unk = g.i(1)[0]
                vb_offset = g.i(1)[0]
                vb_info.append((vb_flags, vb_stride, vb_offset))
            
            # Read submesh info
            submesh_count = g.i(1)[0]
            submesh_info = []
            for sm in range(submesh_count):
                vb_idx = g.i(1)[0]
                lod_grp = g.i(1)[0]
                sub_idx = g.i(1)[0]
                idx_offset = g.i(1)[0]
                vert_marker = g.i(1)[0]
                unk1 = g.i(1)[0]
                unk2 = g.i(1)[0]
                submesh_info.append((vb_idx, lod_grp, sub_idx, idx_offset, vert_marker))
            
            # Calculate index counts
            submesh_data = []
            for i in range(len(submesh_info)):
                vb_idx, lod_grp, sub_idx, idx_offset, vert_marker = submesh_info[i]
                if i + 1 < len(submesh_info):
                    next_offset = submesh_info[i + 1][3]
                    idx_count = next_offset - idx_offset
                else:
                    idx_count = -1  # Will be calculated later
                submesh_data.append((vb_idx, lod_grp, sub_idx, idx_offset, idx_count))
            
            # Read vertex section
            vert_section_size = g.I(1)[0]
            g.seekpad(16)
            vert_section_base = g.tell()
            g.seek(vert_section_base + vert_section_size)
            
            # Read index section
            indice_section_size = g.I(1)[0]
            g.seekpad(16)
            indice_section_offset = g.tell()
            total_indices = indice_section_size
            g.seek(indice_section_offset + indice_section_size * 2)
            
            # Fix last submesh index count
            if submesh_data and submesh_data[-1][4] == -1:
                last = list(submesh_data[-1])
                last[4] = total_indices - last[3]
                submesh_data[-1] = tuple(last)
            
            # Create meshes for this LOD level - one mesh per submesh
            for sm_idx, (vb_idx, lod_grp, sub_idx, idx_offset, idx_count) in enumerate(submesh_data):
                key = (current_lod, sm_idx)  # Unique per submesh
                mesh = Mesh()
                
                # Set LOD and part information
                mesh.lod_level = current_lod
                mesh.part_number = sub_idx  # sub_idx is the part number
                mesh.vb_index = vb_idx
                mesh.indice_section_offset = indice_section_offset
                
                # Set vertex buffer info
                if vb_idx < len(vb_info):
                    vb_flags, vb_stride, vb_offset = vb_info[vb_idx]
                    mesh.vert_format_flags = vb_flags
                    mesh.vert_stride = vb_stride
                    mesh.vert_section_offset = vert_section_base + vb_offset
                
                # Each submesh gets its own mat_list_info entry
                mesh.mat_list_info.append((vb_idx, lod_grp, sub_idx, idx_offset, idx_count))
                mesh_dict[key] = mesh
            
            # Calculate vertex counts for meshes in this LOD
            for key, mesh in mesh_dict.items():
                if key[0] != current_lod:
                    continue  # Skip if not current LOD
                
                if mesh.vb_index < len(vb_info):
                    vb_flags, vb_stride, vb_offset = vb_info[mesh.vb_index]
                    if mesh.vb_index + 1 < len(vb_info):
                        next_offset = vb_info[mesh.vb_index + 1][2]
                        vb_size = next_offset - vb_offset
                    else:
                        vb_size = vert_section_size - vb_offset
                    
                    if vb_stride > 0:
                        mesh.vert_count = vb_size // vb_stride
                    else:
                        mesh.vert_count = 0
                else:
                    mesh.vert_count = 0
        
        # Add all meshes to list
        for mesh in mesh_dict.values():
            self.data.meshes.append(mesh)
        
        # Detect and number sub-parts
        part_groups = {}
        for mesh in mesh_dict.values():
            key = (mesh.lod_level, mesh.part_number)
            if key not in part_groups:
                part_groups[key] = []
            part_groups[key].append(mesh)
        
        # If multiple meshes share the same (lod, part), they're sub-parts
        for key, meshes in part_groups.items():
            if len(meshes) > 1:
                meshes.sort(key=lambda m: m.vb_index)
                for i, mesh in enumerate(meshes):
                    mesh.sub_part_index = i
        
        # Log structure
        lods = {}
        for m in mesh_dict.values():
            if m.lod_level not in lods:
                lods[m.lod_level] = {}
            if m.part_number not in lods[m.lod_level]:
                lods[m.lod_level][m.part_number] = []
            lods[m.lod_level][m.part_number].append(m)
        
        print("Found structure:")
        for lod in sorted(lods.keys()):
            parts_info = []
            for part in sorted(lods[lod].keys()):
                ms = lods[lod][part]
                if len(ms) == 1:
                    parts_info.append(f"P{part}")
                else:
                    parts_info.append(f"P{part}({len(ms)} sub-parts)")
            print(f"  LOD{lod}: {', '.join(parts_info)}")
        
    
    def _parse_dnks(self, g):
        g.i(2)
        g.word(4)
        g.i(4)
        
        self.data.sub_mesh_list = []
        
        if not hasattr(self.data, 'lod_count') or self.data.lod_count == 0:
            return
            
        for n in range(self.data.lod_count):
            lod_submeshes = []
            mat_count = g.i(1)[0]
            
            for m in range(mat_count):
                submesh = SubMesh()
                submesh.header_data = list(g.H(7))
                submesh.bone_data = list(g.h(48)) 
                submesh.face_count = submesh.get_face_count()
                lod_submeshes.append(submesh)
            
            self.data.sub_mesh_list.append(lod_submeshes)
        
        # Skip the rest
        count = g.i(1)[0]
        for n in range(count):
            g.f(11)
            A, B = g.i(2)
            word_len = g.i(1)[0]
            if word_len > 0:
                g.word(word_len)
            g.B(1)
        g.word(4)
    
    def _filter_lod(self, lod_level: int):
        """Filter meshes to keep only the specified LOD level"""
        if lod_level == -1:
            print("Importing all LODs and all Parts")
            return
        
        print(f"Filtering to LOD {lod_level} only...")
        
        # Group meshes by (part_number, lod_level)
        groups = {}
        for mesh in self.data.meshes:
            key = (mesh.part_number, mesh.lod_level)
            if key not in groups:
                groups[key] = []
            groups[key].append(mesh)
        
        # Get all parts
        all_parts = set(m.part_number for m in self.data.meshes)
        filtered = []
        
        for part_num in sorted(all_parts):
            # Try to find meshes at the exact LOD for this part
            key = (part_num, lod_level)
            if key in groups:
                # Found! Add ALL meshes (including sub-parts) for this part at this LOD
                part_meshes = groups[key]
                filtered.extend(part_meshes)
                if len(part_meshes) > 1:
                    print(f"  P{part_num} at LOD{lod_level}: {len(part_meshes)} sub-parts")
                else:
                    print(f"  P{part_num} at LOD{lod_level}: Found")
            else:
                # Not found at exact LOD, find closest available
                available_lods = []
                for (p, l), meshes in groups.items():
                    if p == part_num:
                        available_lods.append((l, meshes))
                
                if available_lods:
                    available_lods.sort(key=lambda x: abs(x[0] - lod_level))
                    closest_lod, meshes = available_lods[0]
                    filtered.extend(meshes)
                    print(f"  P{part_num}: LOD{lod_level} unavailable, using LOD{closest_lod}")
        
        self.data.meshes = filtered
    
    def _process_mesh_vertices(self, g):
        for mesh in self.data.meshes:
            parse_mesh_vertices(g, mesh, self.data.vert_pos_scale, 
                              self.data.uv_trans, self.data.uv_scale)

    def _remap_skin_indices(self, g):
        """Remap bone indices from palette to global bone IDs
        
        CRITICAL: When multiple meshes share the same vertex buffer,
        process all submesh palettes for that vertex buffer, then share.
        """
        # Group meshes by vertex buffer
        vb_groups = {}  # (lod, offset) -> list of meshes
        for mesh in self.data.meshes:
            vb_key = (mesh.lod_level, mesh.vert_section_offset)
            if vb_key not in vb_groups:
                vb_groups[vb_key] = []
            vb_groups[vb_key].append(mesh)
        
        # Process each vertex buffer once
        for vb_key, meshes in vb_groups.items():
            if not meshes:
                continue
            
            # Use the first mesh as reference
            ref_mesh = meshes[0]
            if not ref_mesh.skin_indice_list:
                continue
            
            # Collect all mat_list_info from all meshes sharing this VB
            # and remap using all relevant palettes
            all_mat_info = []
            for mesh in meshes:
                all_mat_info.extend(mesh.mat_list_info)
            
            # Sort by vertex range to process in order
            vert_id_start = 0
            for info in all_mat_info:
                lod_grp, sub_idx = info[1], info[2]
                if lod_grp < len(self.data.sub_mesh_list):
                    submesh = self.data.sub_mesh_list[lod_grp][sub_idx] if sub_idx < len(self.data.sub_mesh_list[lod_grp]) else None
                    if submesh:
                        count = submesh.header_data[5]
                        palette = submesh.bone_data
                        end = min(vert_id_start + count, len(ref_mesh.skin_indice_list))
                        for v_idx in range(vert_id_start, end):
                            ref_mesh.skin_indice_list[v_idx] = tuple(
                                (palette[r] if r < len(palette) and palette[r] != -1 else 0) 
                                for r in ref_mesh.skin_indice_list[v_idx]
                            )
                        vert_id_start += count
            
            # Share the remapped data with all meshes using this VB
            for mesh in meshes[1:]:
                mesh.skin_indice_list = ref_mesh.skin_indice_list
                mesh.skin_weight_list = ref_mesh.skin_weight_list

    def _process_mesh_faces(self, g):
        """Split mesh faces into primitives based on material info"""
        for mesh_idx, mesh in enumerate(self.data.meshes):
            self._process_mesh_faces_with_submesh(g, mesh, mesh_idx)
    
    def _process_mesh_faces_with_submesh(self, g, mesh: Mesh, mesh_idx: int):
        """
        Reads faces and groups them into primitives by material.
        """
        for info in mesh.mat_list_info:
            lod_group_idx = info[1]
            submesh_idx = info[2]
            
            if lod_group_idx < len(self.data.sub_mesh_list):
                lod_submeshes = self.data.sub_mesh_list[lod_group_idx]
                if submesh_idx < len(lod_submeshes):
                    submesh = lod_submeshes[submesh_idx]
                    
                    material_id = submesh.header_data[0]
                    
                    mat_name = f"Material_{material_id}"
                    if material_id < len(self.data.materials):
                        mat_name = self.data.materials[material_id]
                    
                    expected_face_count = submesh.face_count
                    
                    if expected_face_count > 0:
                        index_offset = mesh.indice_section_offset + info[3] * 2
                        g.seek(index_offset)
                        
                        primitive_indices = []
                        
                        for _ in range(expected_face_count):
                            try:
                                face_indices = g.H(3)
                                if 65535 not in face_indices:
                                    primitive_indices.extend(face_indices)
                            except:
                                break
                        
                        if primitive_indices:
                            mesh.add_primitive(primitive_indices, material_id, mat_name)