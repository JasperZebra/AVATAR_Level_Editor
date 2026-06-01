#!/usr/bin/env python3
"""
GLTF exporter for XBG data with proper skeleton/skin support and texture embedding
"""

import os
import json
import math
import struct
from typing import Dict, List, Any, Optional
from xbg_parser import XBGData
from texture_loader import TextureLoader, XBMMaterialData


class GLTFExporter:
    """Export XBG data to GLTF format with proper armature support and texture embedding"""
    
    def __init__(self, xbg_data: XBGData, materials_path: Optional[str] = None):
        self.xbg_data = xbg_data
        self.materials_path = materials_path
        self.texture_loader = TextureLoader(materials_path) if materials_path else None
        self.gltf: Dict[str, Any] = {
            "asset": {
                "version": "2.0",
                "generator": "XBG to GLTF Converter with Textures"
            },
            "scene": 0,
            "scenes": [],
            "nodes": [],
            "meshes": [],
            "skins": [],
            "materials": [],
            "textures": [],
            "images": [],
            "samplers": [],
            "accessors": [],
            "bufferViews": [],
            "buffers": []
        }
        self.binary_data = bytearray()
        self.skeleton_root_index = None
        self.joint_indices = []
        self.material_map = {}
        self.texture_cache = {}  # Cache texture indices by material name 
        
    def export(self, output_path: str):
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        self._add_materials()
        self._add_skeleton_nodes()
        self._add_skin()
        self._add_meshes()
        self._setup_scene()
        self._write_files(output_path)

    def _add_materials(self):
        print(f"\nExporting {len(self.xbg_data.materials)} materials...")

        # Add default sampler for textures
        if self.texture_loader:
            self.gltf["samplers"].append({
                "magFilter": 9729,  # LINEAR
                "minFilter": 9987,  # LINEAR_MIPMAP_LINEAR
                "wrapS": 10497,     # REPEAT
                "wrapT": 10497      # REPEAT
            })

        for i, mat_name in enumerate(self.xbg_data.materials):
            mat_def = self._build_gltf_material(mat_name)
            self.gltf["materials"].append(mat_def)
            self.material_map[i] = len(self.gltf["materials"]) - 1

    # ------------------------------------------------------------------
    # Build one GLTF PBR material from a parsed XBM.
    # Supports diffuse, normal, specular, and emission textures plus
    # base/emissive colour factors, alpha mode, and double-sided flag.
    # ------------------------------------------------------------------
    def _build_gltf_material(self, mat_name: str) -> Dict[str, Any]:
        # Fallback definition for when the XBM can't be loaded.
        mat_def: Dict[str, Any] = {
            "name": mat_name,
            "pbrMetallicRoughness": {
                "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
                "metallicFactor": 0.0,
                "roughnessFactor": 1.0,
            },
            "doubleSided": True,
        }

        if not self.texture_loader:
            return mat_def

        xbm = self.texture_loader.load_material(mat_name)
        if xbm is None:
            return mat_def

        # ── PBR factors derived from XBM scalars/colors ───────────────
        # Base colour tint: DiffuseColor1 (clamped to [0, 1]).  Alpha
        # channel kept at 1.0 (transparency is handled via alphaMode
        # below and the diffuse texture's alpha channel).
        dr, dg, db = (max(0.0, min(1.0, c)) for c in xbm.diffuse_color)
        pbr = mat_def["pbrMetallicRoughness"]
        pbr["baseColorFactor"] = [dr, dg, db, 1.0]

        # Blinn-Phong → GGX roughness: sqrt(2 / (SpecularPower + 2))
        # This is the standard conversion; matches the Blender add-on's
        # _spec_roughness() in nodes.py.
        sp = max(0.0, float(xbm.specular_power))
        roughness = max(0.02, min(1.0, math.sqrt(2.0 / (sp + 2.0))))
        pbr["roughnessFactor"] = float(roughness)
        # Avatar's shaders aren't metallic; keep metallicFactor at 0.
        pbr["metallicFactor"] = 0.0

        # ── Diffuse texture (baseColorTexture) ────────────────────────
        diff_idx = self._add_xbm_texture(xbm, mat_name, 'diffuse', is_normal=False)
        if diff_idx is not None:
            pbr["baseColorTexture"] = {"index": diff_idx, "texCoord": 0}

        # ── Normal map (NormalTexture1) ───────────────────────────────
        # Avatar packs normals DXT5-GA (X in alpha, Y in green, Z derived).
        # Pass is_normal=True so the loader decodes it to a standard
        # tangent-space RGB map that GLTF viewers understand.
        norm_idx = self._add_xbm_texture(xbm, mat_name, 'normal', is_normal=True)
        if norm_idx is not None:
            mat_def["normalTexture"] = {"index": norm_idx, "texCoord": 0, "scale": 1.0}

        # ── Specular map → metallicRoughnessTexture slot ──────────────
        # GLTF's PBR-metallic-roughness packs metallic in B, roughness in G.
        # Avatar's spec map is a single-channel intensity; plugging it
        # straight in approximates surface gloss variation.
        spec_idx = self._add_xbm_texture(xbm, mat_name, 'specular', is_normal=False)
        if spec_idx is not None:
            pbr["metallicRoughnessTexture"] = {"index": spec_idx, "texCoord": 0}

        # ── Emission / illumination ───────────────────────────────────
        emis_idx = self._add_xbm_texture(xbm, mat_name, 'emission', is_normal=False)
        if emis_idx is not None:
            mat_def["emissiveTexture"] = {"index": emis_idx, "texCoord": 0}
        if xbm.illumination_color is not None:
            # GLTF's emissiveFactor must be in [0, 1].  Avatar's HDR values
            # can exceed 1.0, so normalise by the brightest channel.
            er, eg, eb = xbm.illumination_color
            max_c = max(er, eg, eb, 1.0)
            mat_def["emissiveFactor"] = [er / max_c, eg / max_c, eb / max_c]
        elif emis_idx is not None:
            # emissiveTexture is present but IlluminationColor1 wasn't in the
            # XBM (e.g. a template variant that stores no colour scalar).
            # GLTF default emissiveFactor is [0,0,0] which would make the
            # texture invisible — fall back to white so the texture shows.
            mat_def["emissiveFactor"] = [1.0, 1.0, 1.0]

        # ── Alpha mode ────────────────────────────────────────────────
        if xbm.alpha_blend_enabled:
            mat_def["alphaMode"] = "BLEND"
        elif xbm.alpha_test_enabled:
            mat_def["alphaMode"] = "MASK"
            mat_def["alphaCutoff"] = 0.5

        # ── Double-sided ──────────────────────────────────────────────
        # Use the XBM TwoSided flag directly.  The previous default of
        # `True` masked the source-of-truth value; respecting the XBM
        # gives correct backface culling for everything that should have
        # it (vehicles, weapons, walls, etc.).
        mat_def["doubleSided"] = bool(xbm.two_sided)

        # Stash the source-XBM metadata for downstream tools (Blender
        # gltf importer exposes "extras" on materials, so anyone
        # round-tripping can see the template + raw params).
        mat_def["extras"] = {
            "xbm_template": xbm.template,
            "xbm_name": xbm.name,
            "xbm_specular_power": xbm.specular_power,
            "xbm_two_sided": xbm.two_sided,
            "xbm_alpha_test": xbm.alpha_test_enabled,
            "xbm_alpha_blend": xbm.alpha_blend_enabled,
            "xbm_illumination_always_on": xbm.illumination_always_on,
        }
        return mat_def

    # ------------------------------------------------------------------
    # Add a single texture (diffuse/normal/specular/emission) for a
    # material; returns the GLTF texture index or None.  Converts the
    # XBT to PNG via the TextureLoader.  Normal maps are decoded from
    # Avatar's DXT5-GA pack (X in alpha, Y in green, Z reconstructed)
    # to standard tangent-space RGB when is_normal=True.
    # Cached by (path, is_normal) so the same XBT used as both a colour
    # texture and a normal map in different materials is encoded correctly
    # for each use.
    # ------------------------------------------------------------------
    def _add_xbm_texture(
        self,
        xbm: "XBMMaterialData",
        mat_name: str,
        category: str,
        is_normal: bool = False,
    ) -> Optional[int]:
        if category not in xbm.textures:
            return None
        rel = xbm.textures[category]
        if not rel:
            return None

        cache_key = (rel, is_normal)
        if cache_key in self.texture_cache:
            return self.texture_cache[cache_key]

        full_path = self.texture_loader.resolve_xbt_full_path(rel, mat_name)
        if not full_path:
            print(f"  [SKIP] {mat_name} / {category}: texture not on disk ({rel})")
            return None

        result = self.texture_loader.convert_xbt_to_png_base64(full_path, is_normal_map=is_normal)
        if not result:
            return None
        base64_data, _w, _h = result

        # Image
        image_index = len(self.gltf["images"])
        self.gltf["images"].append({
            "name": os.path.basename(full_path).replace('.xbt', ''),
            "mimeType": "image/png",
            "uri": f"data:image/png;base64,{base64_data}",
        })

        # Texture
        texture_index = len(self.gltf["textures"])
        self.gltf["textures"].append({"sampler": 0, "source": image_index})

        self.texture_cache[cache_key] = texture_index
        print(f"  + {mat_name} / {category}: texture {texture_index} "
              f"({os.path.basename(full_path)})")
        return texture_index

    def _add_skeleton_nodes(self):
        skeleton = self.xbg_data.skeleton
        print(f"\nExporting {len(skeleton.bones)} bones to GLTF...")
        self.joint_indices = []
        
        for i, bone in enumerate(skeleton.bones):
            node = { "name": bone.name or f"Bone_{i}" }
            
            # Calculate relative transform from World Matrices
            if bone.world_matrix:
                if bone.parent_id is not None and bone.parent_id >= 0 and bone.parent_id < len(skeleton.bones):
                    parent = skeleton.bones[bone.parent_id]
                    if parent.world_matrix:
                        parent_inv = parent.world_matrix.invert()
                        local_mat = parent_inv.multiply(bone.world_matrix)
                    else:
                        local_mat = bone.world_matrix
                else:
                    local_mat = bone.world_matrix
                
                trans = local_mat.get_translation()
                rot = local_mat.get_rotation_quat()
                scale = local_mat.get_scale()
                
                if any(abs(x) > 1e-6 for x in trans): node["translation"] = trans
                if rot != [0, 0, 0, 1]: node["rotation"] = rot
                if any(abs(s - 1.0) > 1e-4 for s in scale): node["scale"] = scale

            node_index = len(self.gltf["nodes"])
            self.gltf["nodes"].append(node)
            self.joint_indices.append(node_index)
            
            if bone.parent_id is None or bone.parent_id < 0:
                if self.skeleton_root_index is None:
                    self.skeleton_root_index = node_index
        
        for i, bone in enumerate(skeleton.bones):
            node_index = self.joint_indices[i]
            if bone.parent_id is not None and bone.parent_id >= 0 and bone.parent_id < skeleton.get_bone_count():
                parent_node_index = self.joint_indices[bone.parent_id]
                parent_node = self.gltf["nodes"][parent_node_index]
                if "children" not in parent_node:
                    parent_node["children"] = []
                parent_node["children"].append(node_index)
    
    def _add_skin(self):
        skeleton = self.xbg_data.skeleton
        bone_count = len(skeleton.bones)
        print(f"\nCalculating Inverse Bind Matrices for {bone_count} joints...")
        
        inverse_bind_matrices = []
        for i, bone in enumerate(skeleton.bones):
            if bone.world_matrix:
                inv_mat = bone.world_matrix.invert()
                inverse_bind_matrices.extend(inv_mat.to_gl_list())
            else:
                inverse_bind_matrices.extend([1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0])
        
        ibm_offset = len(self.binary_data)
        ibm_data = struct.pack(f'<{len(inverse_bind_matrices)}f', *inverse_bind_matrices)
        self.binary_data.extend(ibm_data)
        
        ibm_buffer_view = len(self.gltf["bufferViews"])
        self.gltf["bufferViews"].append({"buffer": 0, "byteOffset": ibm_offset, "byteLength": len(ibm_data)})
        
        ibm_accessor = len(self.gltf["accessors"])
        self.gltf["accessors"].append({"bufferView": ibm_buffer_view, "componentType": 5126, "count": bone_count, "type": "MAT4"})
        
        skin = {"inverseBindMatrices": ibm_accessor, "joints": self.joint_indices, "name": "Armature"}
        if self.skeleton_root_index is not None: skin["skeleton"] = self.skeleton_root_index
        self.gltf["skins"].append(skin)
    
    def _add_meshes(self):
        for mesh_idx, mesh in enumerate(self.xbg_data.meshes):
            if not mesh.vert_pos_list: continue
            self._add_mesh_to_buffer(mesh, mesh_idx)
    
    def _add_mesh_to_buffer(self, mesh, mesh_idx: int):
        positions = []
        for pos in mesh.vert_pos_list: positions.extend(pos)
        uvs = []
        for uv in mesh.vert_uv_list: uvs.extend(uv)

        has_normals = len(getattr(mesh, 'vert_normal_list', [])) == len(mesh.vert_pos_list)
        normals_flat = []
        if has_normals:
            for n in mesh.vert_normal_list:
                normals_flat.extend(n)

        joints = []
        weights = []
        has_skinning = (len(mesh.skin_weight_list) == len(mesh.vert_pos_list))

        if has_skinning:
            for i in range(len(mesh.vert_pos_list)):
                weights.extend([w / 255.0 for w in mesh.skin_weight_list[i]])
                joints.extend(mesh.skin_indice_list[i])
        else:
            for _ in range(len(mesh.vert_pos_list)):
                joints.extend([0, 0, 0, 0])
                weights.extend([1.0, 0.0, 0.0, 0.0])

        pos_offset = len(self.binary_data)
        self.binary_data.extend(struct.pack(f'<{len(positions)}f', *positions))

        norm_offset = len(self.binary_data)
        norm_len = 0
        if has_normals:
            norm_bytes = struct.pack(f'<{len(normals_flat)}f', *normals_flat)
            norm_len = len(norm_bytes)
            self.binary_data.extend(norm_bytes)

        uv_offset = len(self.binary_data)
        uv_len = 0
        if uvs:
            uv_bytes = struct.pack(f'<{len(uvs)}f', *uvs)
            uv_len = len(uv_bytes)
            self.binary_data.extend(uv_bytes)

        joints_offset = len(self.binary_data)
        self.binary_data.extend(struct.pack(f'<{len(joints)}H', *joints))

        weights_offset = len(self.binary_data)
        self.binary_data.extend(struct.pack(f'<{len(weights)}f', *weights))

        self.gltf["bufferViews"].append({"buffer": 0, "byteOffset": pos_offset, "byteLength": len(positions)*4, "target": 34962})
        pos_view_idx = len(self.gltf["bufferViews"]) - 1

        norm_view_idx = None
        norm_acc_idx = None
        if has_normals:
            self.gltf["bufferViews"].append({"buffer": 0, "byteOffset": norm_offset, "byteLength": norm_len, "target": 34962})
            norm_view_idx = len(self.gltf["bufferViews"]) - 1

        uv_view_idx = None
        if uvs:
            self.gltf["bufferViews"].append({"buffer": 0, "byteOffset": uv_offset, "byteLength": uv_len, "target": 34962})
            uv_view_idx = len(self.gltf["bufferViews"]) - 1

        self.gltf["bufferViews"].append({"buffer": 0, "byteOffset": joints_offset, "byteLength": len(joints)*2, "target": 34962})
        joints_view_idx = len(self.gltf["bufferViews"]) - 1

        self.gltf["bufferViews"].append({"buffer": 0, "byteOffset": weights_offset, "byteLength": len(weights)*4, "target": 34962})
        weights_view_idx = len(self.gltf["bufferViews"]) - 1

        self.gltf["accessors"].append({"bufferView": pos_view_idx, "componentType": 5126, "count": len(mesh.vert_pos_list), "type": "VEC3", "min": [min(p[i] for p in mesh.vert_pos_list) for i in range(3)], "max": [max(p[i] for p in mesh.vert_pos_list) for i in range(3)]})
        pos_acc_idx = len(self.gltf["accessors"]) - 1

        if has_normals:
            self.gltf["accessors"].append({"bufferView": norm_view_idx, "componentType": 5126, "count": len(mesh.vert_pos_list), "type": "VEC3"})
            norm_acc_idx = len(self.gltf["accessors"]) - 1

        uv_acc_idx = None
        if uvs:
            self.gltf["accessors"].append({"bufferView": uv_view_idx, "componentType": 5126, "count": len(mesh.vert_uv_list), "type": "VEC2"})
            uv_acc_idx = len(self.gltf["accessors"]) - 1

        self.gltf["accessors"].append({"bufferView": joints_view_idx, "componentType": 5123, "count": len(mesh.vert_pos_list), "type": "VEC4"})
        joints_acc_idx = len(self.gltf["accessors"]) - 1

        self.gltf["accessors"].append({"bufferView": weights_view_idx, "componentType": 5126, "count": len(mesh.vert_pos_list), "type": "VEC4"})
        weights_acc_idx = len(self.gltf["accessors"]) - 1

        gltf_primitives = []
        if mesh.primitives:
            for prim in mesh.primitives:
                self._add_primitive_to_buffer(prim.indices, prim.material_index, prim.material_name, pos_acc_idx, norm_acc_idx, joints_acc_idx, weights_acc_idx, uv_acc_idx, gltf_primitives)
        elif mesh.face_list:
             all_indices = []
             for face in mesh.face_list: all_indices.extend(face)
             self._add_primitive_to_buffer(all_indices, 0, "Default", pos_acc_idx, None, joints_acc_idx, weights_acc_idx, uv_acc_idx, gltf_primitives)

        # Build mesh name based on parts/subparts
        if mesh.sub_part_index >= 0:
            mesh_name = f"Mesh_LOD{mesh.lod_level}_P{mesh.part_number}_Sub{mesh.sub_part_index}"
        else:
            mesh_name = f"Mesh_LOD{mesh.lod_level}_P{mesh.part_number}"
        
        self.gltf["meshes"].append({"name": mesh_name, "primitives": gltf_primitives})
        mesh_idx_gltf = len(self.gltf["meshes"]) - 1
        self.gltf["nodes"].append({"name": f"MeshNode_{mesh_name}", "mesh": mesh_idx_gltf, "skin": 0})

    def _add_primitive_to_buffer(self, indices, mat_idx, mat_name, pos_acc, norm_acc, joints_acc, weights_acc, uv_acc, gltf_primitives):
        indices_offset = len(self.binary_data)
        indices_bytes = struct.pack(f'<{len(indices)}H', *indices)
        self.binary_data.extend(indices_bytes)
        self.gltf["bufferViews"].append({"buffer": 0, "byteOffset": indices_offset, "byteLength": len(indices_bytes), "target": 34963})
        indices_view_idx = len(self.gltf["bufferViews"]) - 1
        self.gltf["accessors"].append({"bufferView": indices_view_idx, "componentType": 5123, "count": len(indices), "type": "SCALAR"})
        indices_acc_idx = len(self.gltf["accessors"]) - 1

        primitive_def = {"attributes": {"POSITION": pos_acc, "JOINTS_0": joints_acc, "WEIGHTS_0": weights_acc}, "indices": indices_acc_idx}
        if norm_acc is not None: primitive_def["attributes"]["NORMAL"] = norm_acc
        if uv_acc is not None: primitive_def["attributes"]["TEXCOORD_0"] = uv_acc
        
        if mat_idx in self.material_map: primitive_def["material"] = self.material_map[mat_idx]
        elif mat_idx < len(self.gltf["materials"]): primitive_def["material"] = mat_idx
        else:
            self.gltf["materials"].append({"name": mat_name or f"Mat_{mat_idx}"})
            new_idx = len(self.gltf["materials"]) - 1
            self.material_map[mat_idx] = new_idx
            primitive_def["material"] = new_idx
        gltf_primitives.append(primitive_def)

    def _setup_scene(self):
        children_indices = []
        if self.skeleton_root_index is not None: children_indices.append(self.skeleton_root_index)
        for i, node in enumerate(self.gltf["nodes"]):
            if "mesh" in node: children_indices.append(i)
        
        correction_node = {"name": "Correction_Root", "rotation": [-0.70710678, 0.0, 0.0, 0.70710678], "children": children_indices}
        correction_node_idx = len(self.gltf["nodes"])
        self.gltf["nodes"].append(correction_node)
        self.gltf["scenes"] = [{"name": "Scene", "nodes": [correction_node_idx]}]
        print(f"Scene setup with Correction Root (Rotated -90 X)")
    
    def _write_files(self, output_path: str):
        self.gltf["buffers"].append({"byteLength": len(self.binary_data)})
        base_name = os.path.splitext(output_path)[0]
        gltf_path = base_name + '.gltf'
        bin_path = base_name + '.bin'
        self.gltf["buffers"][0]["uri"] = os.path.basename(bin_path)
        with open(gltf_path, 'w') as f: json.dump(self.gltf, f, indent=2)
        with open(bin_path, 'wb') as f: f.write(self.binary_data)
        
        texture_count = len(self.gltf["textures"])
        if texture_count > 0:
            print(f"\nGLTF files written to: {gltf_path} and {bin_path} (with {texture_count} textures embedded)")
        else:
            print(f"\nGLTF files written to: {gltf_path} and {bin_path}")