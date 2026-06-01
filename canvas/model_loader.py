"""3D Model Loader - FIXED to load embedded GLTF textures
Extracts base64 PNG textures from GLTF and loads them into OpenGL
"""

import subprocess
import sys
import os
import json
import struct
import base64
import numpy as np
import xml.etree.ElementTree as ET
from pathlib import Path
import OpenGL.GL as gl
from OpenGL.GL import *
from PyQt6.QtGui import QVector3D, QMatrix4x4, QImage
from PyQt6.QtWidgets import QApplication
from io import BytesIO

import time

# Try to import PIL for texture loading
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print(" PIL/Pillow not available - textures will not be loaded")
    print("   Install with: pip install Pillow")

class GLTFModel:
    """Represents a loaded GLTF model with all its data"""

    def __init__(self, name, path):
        self.name = name
        self.path = path
        self.gltf_data = None
        self.bin_data = None
        self.meshes = []
        self.materials = []
        self.display_list = None
        self.display_list_blend = None  # separate display list for BLEND-mode meshes
        self.bounds_min = None
        self.bounds_max = None
        self.loaded = False
        self.textures = {}  # material_index -> OpenGL texture ID
        self.alpha_modes = {}        # material_index -> "OPAQUE" | "MASK" | "BLEND"
        self.alpha_cutoffs = {}      # material_index -> float
        self.emissive_factors = {}   # material_index -> [r, g, b]
        self.base_color_factors = {} # material_index -> [r, g, b, a]
        
    def get_bounds(self):
        if self.bounds_min and self.bounds_max:
            return self.bounds_min, self.bounds_max
        return None, None

class GLTFMesh:
    """Represents a single mesh from a GLTF model"""
    
    def __init__(self):
        self.vertices = None
        self.normals = None
        self.uvs = None
        self.indices = None
        self.vao = None
        self.vbo_vertices = None
        self.vbo_normals = None
        self.vbo_uvs = None
        self.ibo = None
        self.material_index = None
        self.texture_id = None

class ModelLoader:
    """Handles loading and caching of GLTF models with EMBEDDED TEXTURE SUPPORT"""
    
    def __init__(self):
        self.models_cache = {}
        self.entity_to_model = {}
        self.entity_library_cache = {}
        self.models_directory = None
        self.entity_library_path = None
        self.materials_directory = None
        self.texture_loader = None
        self.fallback_cube_list = None
        self.entity_patterns = {}
        self._models_index = {}
        self._texture_cache = {}
        self._entity_library_loaded = False
        
        # NEW: Batch rendering support
        self.instance_batches = {}  # model_path -> list of (position, rotation, scale, is_selected)
        self.batch_vbos = {}  # model_path -> instance VBO for transforms
        
        # OPTIMIZATION: Octree for 10K+ objects spatial culling
        self.octree = None
        self.octree_enabled = False
        self.entities_count_threshold = 5000  # Enable octree when entities > 5000
        
        # Per-entity rotation/scale cache — keyed by id(entity), cleared on entity modification
        self._entity_rs_cache = {}  # id(entity) -> (rx, ry, rz, scale)

        # ADD THESE LINES:
        self.xbg_converter_script = self._find_xbg_converter()
        self.model_cache_dir = self._get_model_cache_dir()
        self.conversion_cache = {}  # Track converted models
        
        print(f"XBG Converter: {'Found' if self.xbg_converter_script else 'Not available'}")

        self._load_local_entity_library()
        print("ModelLoader initialized with embedded texture support and batch rendering")

    def _extract_gltf_path_from_resource(self, resource_path, game_mode="avatar", _recursion_depth=0):
        """
        Extract GLTF path from resource - WITH AUTOMATIC XBG CONVERSION
        
        FIXED: Added recursion depth limit to prevent infinite loops
        """
        # RECURSION GUARD: Prevent infinite loops
        if _recursion_depth > 5:
            print(f"  ⚠️ Max recursion depth reached for: {resource_path}")
            return None, None
        
        if not resource_path or not self.models_directory:
            return None, None
        
        # Log what we're searching for (only at top level)
        if _recursion_depth == 0:
            print(f"🔍 Searching for: {resource_path}")
        
        # Parse the resource path to get relative parts
        parts = resource_path.replace("\\", "/").split("/")
        
        try:
            graphics_index = next(i for i, p in enumerate(parts) if p.lower() == "graphics")
            rel_parts = parts[graphics_index + 1:]
        except StopIteration:
            rel_parts = parts
        
        base_name = os.path.splitext(rel_parts[-1])[0]
        rel_parts[-1] = base_name
        
        if _recursion_depth == 0:
            print(f"  Relative path: {'/'.join(rel_parts)}")
        
        # ==========================================
        # STEP 1: Try to find existing GLTF file
        # ==========================================
        gltf_path, bin_path = self._find_gltf_case_insensitive(rel_parts)

        if gltf_path and bin_path:
            # If the cached GLTF has no embedded textures but materials are available,
            # fall through to reconvert so textures get embedded this time.
            materials_path = self._get_materials_path_for_resource(resource_path)
            if materials_path:
                try:
                    with open(gltf_path, 'r') as _f:
                        _cached = json.load(_f)
                    if len(_cached.get('images', [])) == 0:
                        if _recursion_depth == 0:
                            print(f"  ↺ Reconverting (no textures in cache): {os.path.basename(gltf_path)}")
                        gltf_path = None  # fall through to XBG conversion below
                except Exception:
                    pass
            if gltf_path:
                if _recursion_depth == 0:
                    print(f"  ✅ Found GLTF: {os.path.basename(gltf_path)}")
                return gltf_path, bin_path
        
        # ==========================================
        # STEP 2: If GLTF not found, try XBG conversion
        # ==========================================
        if self.xbg_converter_script:
            # Try to find XBG file (with all fallback strategies)
            xbg_path = self._find_xbg_case_insensitive(rel_parts)
            
            if xbg_path:
                # Get materials path for texture support
                materials_path = self._get_materials_path_for_resource(resource_path)
                
                if materials_path and _recursion_depth == 0:
                    print(f"  📦 Using materials: {os.path.basename(materials_path)}")
                elif _recursion_depth == 0:
                    print(f"  ⚠️ No materials folder found - textures will not be embedded")
                
                # Convert XBG to GLTF with game mode for proper cache organization
                converted_gltf, converted_bin = self.convert_xbg_to_gltf(
                    xbg_path, 
                    materials_path=materials_path,
                    lod_level=0,  # Always use highest detail LOD
                    game_mode=game_mode  # Pass game mode for cache organization
                )
                
                if converted_gltf and converted_bin:
                    if _recursion_depth == 0:
                        print(f"  ✅ XBG converted successfully")
                    return converted_gltf, converted_bin
                else:
                    if _recursion_depth == 0:
                        print(f"  ❌ XBG conversion failed")
        else:
            if _recursion_depth == 0:
                print(f"  ⚠️ XBG converter not available")
        
        # ==========================================
        # STEP 3: Try special fallback paths
        # ==========================================
        
        # FALLBACK 3A: Try _Kit to static conversion
        if '/_Kit/' in resource_path:
            static_path = self._convert_to_static_path(resource_path)
            if static_path and static_path != resource_path:
                if _recursion_depth == 0:
                    print(f"  🔄 Trying _Kit fallback: {os.path.basename(static_path)}")
                # IMPORTANT: Pass recursion depth + 1
                return self._extract_gltf_path_from_resource(static_path, game_mode, _recursion_depth + 1)
        
        # FALLBACK 3B: Try removing _Obsolete suffix
        if '_Obsolete' in resource_path:
            non_obsolete_path = resource_path.replace('_Obsolete', '')
            if _recursion_depth == 0:
                print(f"  🔄 Trying non-obsolete fallback: {os.path.basename(non_obsolete_path)}")
            # IMPORTANT: Pass recursion depth + 1
            return self._extract_gltf_path_from_resource(non_obsolete_path, game_mode, _recursion_depth + 1)
        
        # FALLBACK 3C: Try Baltazar/Z_3D to main graphics folder
        if 'Baltazar/Z_3D/' in resource_path:
            filename = os.path.basename(resource_path)
            filename = filename.replace('_Obsolete', '')
            
            fallback_locations = [
                f"graphics/av_Vehicles_Corp/{filename}",
                f"graphics/av_Props/{filename}",
                f"graphics/av_Environment/{filename}",
            ]
            
            for fallback_loc in fallback_locations:
                if _recursion_depth == 0:
                    print(f"  🔄 Trying Baltazar fallback: {fallback_loc}")
                # IMPORTANT: Pass recursion depth + 1
                result = self._extract_gltf_path_from_resource(fallback_loc, game_mode, _recursion_depth + 1)
                if result[0] is not None:
                    return result
        
        # FALLBACK 3D: For _Kit models, try alternate LOD levels or simplified versions
        # CRITICAL FIX: Only try LOD0 if not already tried
        if '_Kit' in resource_path and '_LOD0' not in resource_path:
            # Try LOD0 suffix (some kits have this)
            lod_path = resource_path.replace('.xbg', '_LOD0.xbg')
            if lod_path != resource_path:
                if _recursion_depth == 0:
                    print(f"  🔄 Trying LOD0 variant: {os.path.basename(lod_path)}")
                # IMPORTANT: Pass recursion depth + 1
                result = self._extract_gltf_path_from_resource(lod_path, game_mode, _recursion_depth + 1)
                if result[0] is not None:
                    return result
        
        # ==========================================
        # STEP 4: Nothing found
        # ==========================================
        if _recursion_depth == 0:
            print(f"  ❌ No model found for: {resource_path}")
        return None, None


    def _convert_to_static_path(self, kit_path):
        """
        Convert _Kit model path to static model path
        
        FIXED: Removed recursive calls to prevent infinite loops
        Returns the converted path string only, without searching
        """
        if '/_Kit/' not in kit_path and '_kit' not in kit_path.lower():
            return None
        
        # Parse the path
        parts = kit_path.replace("\\", "/").split("/")
        try:
            graphics_index = next(i for i, p in enumerate(parts) if p.lower() == "graphics")
            rel_parts = parts[graphics_index + 1:]
        except StopIteration:
            rel_parts = parts
        
        base_name = os.path.splitext(rel_parts[-1])[0]
        rel_parts[-1] = base_name
        
        # STRATEGY 1: Check if file exists IN _Kit folder
        print(f"  📁 Checking _Kit folder for: {base_name}")
        xbg_path = self._find_xbg_case_insensitive(rel_parts)
        if xbg_path:
            print(f"    ✅ Found in _Kit folder: {os.path.basename(xbg_path)}")
            return kit_path  # Return original path since file exists there
        
        # STRATEGY 2: Try removing /_Kit/ from path (static version)
        static_path = kit_path.replace('/_Kit/', '/')
        
        # Don't search here - just return the path
        # The calling function will search for it
        print(f"    ℹ️ No _Kit file found, returning static path")
        return static_path

    def _get_materials_path_for_resource(self, resource_path):
        """
        Get materials path for a given resource.
        
        All textures are in graphics/_materials/ - there are no category-specific materials folders.
        """
        materials_path = None
        
        # Priority 1: Use explicitly set materials directory
        if self.materials_directory and os.path.exists(self.materials_directory):
            materials_path = self.materials_directory
            return materials_path
        
        # Priority 2: Derive from models directory (graphics/_materials)
        if self.models_directory:
            # models_directory should be graphics/
            # So materials should be graphics/_materials
            possible_materials = os.path.join(self.models_directory, "_materials")
            
            if os.path.exists(possible_materials):
                materials_path = possible_materials
                return materials_path
            
            # Fallback: Try going up one level if models_directory was set to a subfolder
            parent_dir = os.path.dirname(self.models_directory)
            possible_materials = os.path.join(parent_dir, "_materials")
            
            if os.path.exists(possible_materials):
                materials_path = possible_materials
                return materials_path
        
        # Priority 3: No materials found
        if not materials_path:
            print(f"  ⚠ Materials folder not found")
            print(f"    models_directory: {self.models_directory}")
            print(f"    Looked for: {os.path.join(self.models_directory, '_materials') if self.models_directory else 'N/A'}")
        
        return materials_path

    def _log_special_model_handling(self, entity_name, original_path, resolved_path, reason):
        """Log special model path resolution for debugging"""
        if not hasattr(self, '_special_model_log'):
            self._special_model_log = []
        
        self._special_model_log.append({
            'entity': entity_name,
            'original': original_path,
            'resolved': resolved_path,
            'reason': reason
        })
        
        # Print occasionally
        if len(self._special_model_log) % 10 == 0:
            print(f"  Special handling: {reason} for {os.path.basename(original_path)}")

    def assign_models_to_entities(self, entities, progress_dialog=None, parent=None, game_mode="avatar"):
        """Assign 3D models to entities - using parent's progress dialog
        
        Args:
            entities: List of entities to assign models to
            progress_dialog: Optional progress dialog for status updates
            parent: Parent widget (unused, kept for compatibility)
            game_mode: "avatar" or "farcry2" for cache organization
        """
        if not self._entity_library_loaded:
            print("⚠ No EntityLibrary loaded")
            return

        # Helper function for logging
        def log(msg):
            print(msg)
            if progress_dialog:
                try:
                    progress_dialog.append_log(msg)
                except:
                    pass

        log(f"🔄 Assigning models to {len(entities)} entities ({game_mode} mode)...")

        matched = 0
        unmatched = 0
        unfound_models = []
        found_models = []
        converted_xbg_count = 0
        kit_fallback_count = 0
        obsolete_fallback_count = 0
        
        # Reset special model handling log
        self._special_model_log = []
        
        normalized_patterns = {}
        for key, val in self.entity_patterns.items():
            normalized_patterns[key.lower()] = val
            if '.' in key:
                parts = key.split('.', 1)
                if len(parts) == 2:
                    normalized_patterns[parts[1].lower()] = val

        total_entities = len(entities)
        
        for idx, entity in enumerate(entities):
            # Update progress every 50 entities
            if idx % 50 == 0 and progress_dialog:
                percent = int((idx / total_entities) * 100)
                if hasattr(progress_dialog, 'set_progress'):
                    progress_dialog.set_progress(percent)
                if hasattr(progress_dialog, 'set_status'):
                    progress_dialog.set_status(f"Assigning 3D models: {idx}/{total_entities}")
                QApplication.processEvents()
                
                # Check for cancellation
                if hasattr(progress_dialog, 'was_cancelled') and progress_dialog.was_cancelled:
                    log("Model assignment cancelled by user")
                    return
            
            entity_name = getattr(entity, "hid_name", getattr(entity, "name", None))
            if not entity_name:
                unmatched += 1
                continue

            model_file = None
            
            # STEP 1: Check entity's own XML data
            if hasattr(entity, 'xml_element') and entity.xml_element is not None:
                resource_elem = entity.xml_element.find(".//resource[@fileName]")
                if resource_elem is not None:
                    model_file = resource_elem.get('fileName')
                    if model_file and idx % 100 == 0:
                        print(f"  Found model for: {entity_name[:30]}...")
            
            # STEP 2: Search entity library - FIXED to handle _Copy and other instance suffixes
            if not model_file:
                import re
                
                # Try exact name first (lowercase)
                norm_name = entity_name.lower()
                model_file = normalized_patterns.get(norm_name)
                
                # If not found, strip instance suffixes
                if not model_file:
                    # FIXED: Pattern handles combinations like:
                    # - _0_Copy_9739  -> strips entire suffix
                    # - _Copy_123     -> strips entire suffix  
                    # - _Instance_5   -> strips entire suffix
                    # - _Clone_12     -> strips entire suffix
                    base_name = re.sub(r'(_Copy)?(_\d+)?(_Copy)?(_\d+)?$', '', entity_name, flags=re.IGNORECASE)
                    base_name = re.sub(r'(_Instance|_Clone|_Duplicate)(_\d+)?$', '', base_name, flags=re.IGNORECASE)
                    
                    if base_name != entity_name:
                        model_file = normalized_patterns.get(base_name.lower())
                
                # Try with prefix removed (e.g., Avatar.Dove_Drivable -> Dove_Drivable)
                if not model_file and '.' in entity_name:
                    parts = entity_name.split('.', 1)
                    if len(parts) == 2:
                        suffix = parts[1]
                        model_file = normalized_patterns.get(suffix.lower())

                        if not model_file:
                            # FIXED: Also strip instance suffixes from suffix part
                            suffix_base = re.sub(r'(_Copy)?(_\d+)?(_Copy)?(_\d+)?$', '', suffix, flags=re.IGNORECASE)
                            suffix_base = re.sub(r'(_Instance|_Clone|_Duplicate)(_\d+)?$', '', suffix_base, flags=re.IGNORECASE)
                            model_file = normalized_patterns.get(suffix_base.lower())

                # STEP 2b: Fall back to tplCreatureType — entities like Vegetation.RF_Puff_Daddy_81
                # have instance numbers in hidName that can't be resolved to a variant (_01/_02)
                # but tplCreatureType directly names the prototype (Breakable.Vegetation.RF_Puff_Daddy_02)
                if not model_file and hasattr(entity, 'xml_element') and entity.xml_element is not None:
                    creature_field = entity.xml_element.find("./field[@name='tplCreatureType']")
                    if creature_field is None:
                        creature_field = entity.xml_element.find(".//field[@name='tplCreatureType']")
                    if creature_field is not None:
                        creature_type = creature_field.get('value-String') or creature_field.get('value-string')
                        if creature_type:
                            model_file = normalized_patterns.get(creature_type.lower())
                            if not model_file and '.' in creature_type:
                                # Also try without the first prefix segment
                                _, ct_suffix = creature_type.split('.', 1)
                                model_file = normalized_patterns.get(ct_suffix.lower())
            
            if model_file:
                original_model_file = model_file
                model_file = self._fix_resource_path_typos(model_file)
                
                # Pass game_mode to extraction method
                gltf_path, bin_path = self._extract_gltf_path_from_resource(model_file, game_mode=game_mode)
                
                # Track XBG conversions
                if gltf_path and ".model_cache" in gltf_path:
                    converted_xbg_count += 1
                
                # Track special fallbacks
                is_kit_fallback = False
                is_obsolete_fallback = False
                
                # Try static version if _Kit not found
                if not gltf_path and '/_Kit/' in model_file:
                    static_model_file = self._convert_to_static_path(model_file)
                    if static_model_file and static_model_file != model_file:
                        log(f"  Trying _Kit fallback for: {entity_name[:30]}...")
                        gltf_path, bin_path = self._extract_gltf_path_from_resource(static_model_file, game_mode=game_mode)
                        if gltf_path:
                            model_file = static_model_file
                            is_kit_fallback = True
                            kit_fallback_count += 1
                            self._log_special_model_handling(entity_name, original_model_file, model_file, "_Kit to static conversion")
                            # Track XBG conversions for static fallback too
                            if ".model_cache" in gltf_path:
                                converted_xbg_count += 1
                
                # Try obsolete fallback if still not found
                if not gltf_path and '_Obsolete' in model_file:
                    non_obsolete_file = model_file.replace('_Obsolete', '')
                    log(f"  Trying non-obsolete fallback for: {entity_name[:30]}...")
                    gltf_path, bin_path = self._extract_gltf_path_from_resource(non_obsolete_file, game_mode=game_mode)
                    if gltf_path:
                        model_file = non_obsolete_file
                        is_obsolete_fallback = True
                        obsolete_fallback_count += 1
                        self._log_special_model_handling(entity_name, original_model_file, model_file, "Obsolete to current version")
                        if ".model_cache" in gltf_path:
                            converted_xbg_count += 1
                
                # Try Baltazar/Z_3D fallback if still not found
                if not gltf_path and 'Baltazar/Z_3D/' in model_file:
                    filename = os.path.basename(model_file)
                    filename = filename.replace('_Obsolete', '')
                    
                    fallback_locations = [
                        f"graphics/av_Vehicles_Corp/{filename}",
                        f"graphics/av_Props/{filename}",
                        f"graphics/av_Environment/{filename}",
                    ]
                    
                    for fallback_loc in fallback_locations:
                        log(f"  Trying Baltazar fallback: {fallback_loc}")
                        gltf_path, bin_path = self._extract_gltf_path_from_resource(fallback_loc, game_mode=game_mode)
                        if gltf_path:
                            model_file = fallback_loc
                            self._log_special_model_handling(entity_name, original_model_file, model_file, "Baltazar/Z_3D to main graphics")
                            if ".model_cache" in gltf_path:
                                converted_xbg_count += 1
                            break
                
                if gltf_path:
                    entity.model_file = gltf_path
                    entity.bin_file = bin_path
                    # Resolve kit-assembled character parts (Corp/Avatar/Na'vi NPCs)
                    entity.kit_model_files = self._resolve_kit_parts(entity, game_mode=game_mode)
                    # Fill empty/missing slots from the archetype (positional inheritance)
                    entity.kit_model_files = self._supplement_kit_parts_from_archetype(entity, entity.kit_model_files, game_mode=game_mode)
                    # Kit parts are the complete visual — the base skeleton XBG is redundant when parts exist
                    if entity.kit_model_files:
                        entity.model_file = None
                    found_models.append({
                        'entity_name': entity_name,
                        'resource_path': original_model_file,
                        'resolved_path': model_file if model_file != original_model_file else None,
                        'gltf_path': gltf_path,
                        'is_kit_fallback': is_kit_fallback,
                        'is_obsolete_fallback': is_obsolete_fallback,
                        'was_converted': ".model_cache" in gltf_path
                    })
                    matched += 1
                else:
                    # Base model path found but unresolvable — still check for kit parts
                    entity.model_file = None
                    entity.kit_model_files = self._resolve_kit_parts(entity, game_mode=game_mode)
                    entity.kit_model_files = self._supplement_kit_parts_from_archetype(entity, entity.kit_model_files, game_mode=game_mode)
                    if entity.kit_model_files:
                        matched += 1
                    else:
                        unfound_models.append({
                            'entity_name': entity_name,
                            'resource_path': original_model_file
                        })
                        unmatched += 1
            else:
                # No model path found at all — check for kit-assembled NPC
                entity.model_file = None
                entity.kit_model_files = self._resolve_kit_parts(entity, game_mode=game_mode)
                entity.kit_model_files = self._supplement_kit_parts_from_archetype(entity, entity.kit_model_files, game_mode=game_mode)
                if entity.kit_model_files:
                    matched += 1
                else:
                    unmatched += 1

        log(f"Model assignment complete: {matched} matched, {unmatched} unmatched, {converted_xbg_count} converted from XBG")
        
        if kit_fallback_count > 0:
            log(f"  _Kit fallbacks used: {kit_fallback_count}")
        if obsolete_fallback_count > 0:
            log(f"  Obsolete fallbacks used: {obsolete_fallback_count}")

        print(f"🎉 {matched} matched, {unmatched} unmatched, {converted_xbg_count} XBG conversions ({game_mode} mode)")
        if kit_fallback_count > 0:
            print(f"  ⚙️ _Kit fallbacks: {kit_fallback_count}")
        if obsolete_fallback_count > 0:
            print(f"  🔄 Obsolete fallbacks: {obsolete_fallback_count}")
        
        # Write FOUND models report
        if found_models:
            try:
                script_dir = os.path.dirname(os.path.abspath(__file__))
                output_file = os.path.join(script_dir, f"loaded_models_{game_mode}.txt")
                
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(f"Loaded Models Report ({game_mode.upper()})\n")
                    f.write(f"Generated: {self._get_timestamp()}\n")
                    f.write(f"Total loaded: {len(found_models)}\n")
                    f.write(f"XBG conversions: {converted_xbg_count}\n")
                    f.write(f"_Kit fallbacks: {kit_fallback_count}\n")
                    f.write(f"Obsolete fallbacks: {obsolete_fallback_count}\n")
                    f.write("=" * 80 + "\n\n")
                    
                    for item in found_models:
                        f.write(f"Entity: {item['entity_name']}\n")
                        f.write(f"Resource Path: {item['resource_path']}\n")
                        
                        if item['resolved_path']:
                            f.write(f"Resolved Path: {item['resolved_path']}\n")
                        
                        f.write(f"GLTF File: {item['gltf_path']}\n")
                        
                        # ADD MATERIALS PATH DEBUG INFO
                        materials_path = self._get_materials_path_for_resource(item['resource_path'])
                        if materials_path:
                            f.write(f"Materials Path: {materials_path}\n")
                            f.write(f"Materials Exists: {os.path.exists(materials_path)}\n")
                        else:
                            f.write(f"Materials Path: NOT FOUND\n")
                        
                        if item['is_kit_fallback']:
                            f.write(f"NOTE: Used _Kit to static conversion\n")
                        if item['is_obsolete_fallback']:
                            f.write(f"NOTE: Used obsolete to current version fallback\n")
                        if item['was_converted']:
                            f.write(f"NOTE: Converted from XBG file\n")
                        
                        f.write("-" * 80 + "\n")
                
                print(f"📄 Wrote {len(found_models)} loaded models to {output_file}")
            except Exception as e:
                print(f"Failed to write loaded models file: {e}")

        # Write UNFOUND models report
        if unfound_models:
            try:
                script_dir = os.path.dirname(os.path.abspath(__file__))
                output_file = os.path.join(script_dir, f"unfound_models_{game_mode}.txt")
                
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(f"Unfound Models Report ({game_mode.upper()})\n")
                    f.write(f"Generated: {self._get_timestamp()}\n")
                    f.write(f"Total unfound: {len(unfound_models)}\n")
                    f.write("=" * 80 + "\n\n")
                    
                    # Group by resource path for better analysis
                    path_groups = {}
                    for item in unfound_models:
                        path = item['resource_path']
                        if path not in path_groups:
                            path_groups[path] = []
                        path_groups[path].append(item['entity_name'])
                    
                    f.write("SUMMARY BY RESOURCE PATH:\n")
                    f.write("-" * 80 + "\n")
                    for path, entity_names in sorted(path_groups.items(), key=lambda x: len(x[1]), reverse=True):
                        f.write(f"\nResource: {path}\n")
                        f.write(f"Entities using this: {len(entity_names)}\n")
                        
                        # ADD MATERIALS PATH DEBUG INFO
                        materials_path = self._get_materials_path_for_resource(path)
                        if materials_path:
                            f.write(f"Materials Path: {materials_path}\n")
                            f.write(f"Materials Exists: {os.path.exists(materials_path)}\n")
                        else:
                            f.write(f"Materials Path: NOT FOUND\n")
                        
                        f.write(f"Examples: {', '.join(entity_names[:3])}\n")
                        if len(entity_names) > 3:
                            f.write(f"... and {len(entity_names) - 3} more\n")
                    
                    f.write("\n" + "=" * 80 + "\n\n")
                    f.write("DETAILED LIST:\n")
                    f.write("-" * 80 + "\n")
                    
                    for item in unfound_models:
                        f.write(f"Entity: {item['entity_name']}\n")
                        f.write(f"Resource Path: {item['resource_path']}\n")
                        
                        # ADD MATERIALS PATH DEBUG INFO
                        materials_path = self._get_materials_path_for_resource(item['resource_path'])
                        if materials_path:
                            f.write(f"Materials Path: {materials_path}\n")
                        else:
                            f.write(f"Materials Path: NOT FOUND\n")
                        
                        # Add hints for common issues
                        path = item['resource_path']
                        if '/_Kit/' in path:
                            f.write(f"HINT: This is a _Kit model - may need static version\n")
                        if '_Obsolete' in path:
                            f.write(f"HINT: This is an obsolete model - may need current version\n")
                        if 'Baltazar/Z_3D/' in path:
                            f.write(f"HINT: This is from Baltazar/Z_3D - may be in main graphics folder\n")
                        
                        f.write("-" * 80 + "\n")
                
                print(f"📄 Wrote {len(unfound_models)} unfound models to {output_file}")
            except Exception as e:
                print(f"Failed to write unfound models file: {e}")

        # Write SPECIAL MODEL HANDLING report
        if hasattr(self, '_special_model_log') and self._special_model_log:
            try:
                script_dir = os.path.dirname(os.path.abspath(__file__))
                output_file = os.path.join(script_dir, f"special_models_{game_mode}.txt")
                
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(f"Special Model Handling Report ({game_mode.upper()})\n")
                    f.write(f"Generated: {self._get_timestamp()}\n")
                    f.write(f"Total special cases: {len(self._special_model_log)}\n")
                    f.write("=" * 80 + "\n\n")
                    
                    for entry in self._special_model_log:
                        f.write(f"Entity: {entry['entity']}\n")
                        f.write(f"Original Path: {entry['original']}\n")
                        f.write(f"Resolved Path: {entry['resolved']}\n")
                        f.write(f"Reason: {entry['reason']}\n")
                        f.write("-" * 80 + "\n")
                
                print(f"📄 Wrote {len(self._special_model_log)} special model cases to {output_file}")
            except Exception as e:
                print(f"Failed to write special models file: {e}")

    def _find_gltf_case_insensitive(self, path_parts):
        """
        Find GLTF file case-insensitively
        
        Searches through directory structure ignoring case,
        returns both GLTF and BIN file paths if found
        """
        current = self.models_directory
        
        # Navigate through path parts (except last)
        for part in path_parts[:-1]:
            try:
                matches = [f for f in os.listdir(current) if f.lower() == part.lower()]
                if not matches:
                    return None, None
                current = os.path.join(current, matches[0])
            except FileNotFoundError:
                return None, None
        
        # Find GLTF and BIN files in final directory
        last_part = path_parts[-1]
        gltf_path = None
        bin_path = None
        
        try:
            for f in os.listdir(current):
                if f.lower().startswith(last_part.lower()):
                    if f.lower().endswith(".gltf"):
                        gltf_path = os.path.join(current, f)
                    elif f.lower().endswith(".bin"):
                        bin_path = os.path.join(current, f)
        except FileNotFoundError:
            return None, None
        
        return gltf_path, bin_path

    def _find_xbg_case_insensitive(self, path_parts):
        """
        Find XBG file case-insensitively with multiple fallback strategies
        
        NEW: Now tries multiple variations to find hard-to-locate files
        """
        current = self.models_directory
        
        # STRATEGY 1: Exact path navigation (original method)
        temp_current = current
        found_exact = True
        
        # Navigate through path parts (except last)
        for part in path_parts[:-1]:
            try:
                matches = [f for f in os.listdir(temp_current) if f.lower() == part.lower()]
                if not matches:
                    found_exact = False
                    break
                temp_current = os.path.join(temp_current, matches[0])
            except (FileNotFoundError, PermissionError):
                found_exact = False
                break
        
        # If we successfully navigated to the directory, try to find the file
        if found_exact:
            last_part = path_parts[-1]
            try:
                for f in os.listdir(temp_current):
                    if f.lower().startswith(last_part.lower()) and f.lower().endswith(".xbg"):
                        xbg_path = os.path.join(temp_current, f)
                        print(f"    ✓ Found via exact path: {os.path.basename(xbg_path)}")
                        return xbg_path
            except (FileNotFoundError, PermissionError):
                pass
        
        # STRATEGY 2: For _Kit models, try the actual _Kit folder
        # The issue is that _convert_to_static_path removes /_Kit/ but the file IS in _Kit
        if '/_Kit/' in '/'.join(path_parts) or '_kit' in '/'.join(path_parts).lower():
            # Try finding it in the _Kit folder itself
            temp_current = current
            found_kit = True
            
            for part in path_parts[:-1]:
                try:
                    matches = [f for f in os.listdir(temp_current) if f.lower() == part.lower()]
                    if not matches:
                        found_kit = False
                        break
                    temp_current = os.path.join(temp_current, matches[0])
                except (FileNotFoundError, PermissionError):
                    found_kit = False
                    break
            
            if found_kit:
                last_part = path_parts[-1]
                try:
                    # Try exact filename match
                    for f in os.listdir(temp_current):
                        if f.lower().startswith(last_part.lower()) and f.lower().endswith(".xbg"):
                            xbg_path = os.path.join(temp_current, f)
                            print(f"    ✓ Found _Kit model: {os.path.basename(xbg_path)}")
                            return xbg_path
                    
                    # Try component parts (e.g., Corp_M -> corp_m_mid_01.xbg)
                    base_name = last_part.lower()
                    for f in os.listdir(temp_current):
                        f_lower = f.lower()
                        if f_lower.startswith(base_name) and f_lower.endswith(".xbg"):
                            xbg_path = os.path.join(temp_current, f)
                            print(f"    ✓ Found _Kit component: {os.path.basename(xbg_path)}")
                            return xbg_path
                except (FileNotFoundError, PermissionError):
                    pass
        
        # STRATEGY 3: Recursive search from current category folder
        # Sometimes the file is in a subfolder we didn't expect
        if len(path_parts) >= 2:
            # Start from the category folder (e.g., av_Characters)
            category_folder = path_parts[0]
            try:
                category_path = os.path.join(current, category_folder)
                
                # Check if category folder exists (case-insensitive)
                matches = [f for f in os.listdir(current) if f.lower() == category_folder.lower()]
                if matches:
                    category_path = os.path.join(current, matches[0])
                    
                    # Search recursively for the file
                    last_part = path_parts[-1]
                    for root, dirs, files in os.walk(category_path):
                        for f in files:
                            if f.lower().startswith(last_part.lower()) and f.lower().endswith(".xbg"):
                                xbg_path = os.path.join(root, f)
                                print(f"    ✓ Found via recursive search: {os.path.basename(xbg_path)}")
                                return xbg_path
            except (FileNotFoundError, PermissionError):
                pass
        
        # STRATEGY 4: Try alternative naming conventions
        # Sometimes NPC_Name vs Npc_Name vs npc_name
        last_part = path_parts[-1]
        alternatives = [
            last_part,
            last_part.upper(),
            last_part.lower(),
            last_part.title(),
            last_part.replace('NPC_', 'Npc_'),
            last_part.replace('Npc_', 'NPC_'),
            last_part.replace('_F', '_f'),
            last_part.replace('_M', '_m'),
        ]
        
        # Try navigating with alternative names
        for alt_name in alternatives:
            temp_current = current
            found_alt = True
            
            # Navigate to directory
            for part in path_parts[:-1]:
                try:
                    matches = [f for f in os.listdir(temp_current) if f.lower() == part.lower()]
                    if not matches:
                        found_alt = False
                        break
                    temp_current = os.path.join(temp_current, matches[0])
                except (FileNotFoundError, PermissionError):
                    found_alt = False
                    break
            
            if found_alt:
                try:
                    for f in os.listdir(temp_current):
                        if f.lower().startswith(alt_name.lower()) and f.lower().endswith(".xbg"):
                            xbg_path = os.path.join(temp_current, f)
                            print(f"    ✓ Found via alternative naming: {os.path.basename(xbg_path)}")
                            return xbg_path
                except (FileNotFoundError, PermissionError):
                    pass
        
        print(f"    ✗ Could not find XBG: {'/'.join(path_parts)}")
        return None
    
    def _find_xbg_converter(self):
        """Find the xbg2gltf.py converter script in canvas folder"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Converter is in canvas/xbg2gltf.py (same folder as model_loader.py)
        possible_paths = [
            os.path.join(current_dir, "xbg2gltf.py"),  # Same folder (canvas/)
        ]
        
        for path in possible_paths:
            abs_path = os.path.abspath(path)
            if os.path.exists(abs_path):
                print(f"✓ Found XBG converter: {abs_path}")
                return abs_path
        
        print("⚠ XBG converter (xbg2gltf.py) not found in canvas/ folder")
        print(f"   Expected location: {os.path.join(current_dir, 'xbg2gltf.py')}")
        return None

    def _get_model_cache_dir(self):
        """Get/create cache directory for converted GLTF models with game-specific subfolders"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        cache_dir = os.path.join(current_dir, ".model_cache")
        
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
            print(f"✓ Created model cache: {cache_dir}")
        
        # Create game-specific subfolders
        avatar_cache = os.path.join(cache_dir, "avatar")
        fc2_cache = os.path.join(cache_dir, "fc2")
        
        if not os.path.exists(avatar_cache):
            os.makedirs(avatar_cache)
            print(f"✓ Created Avatar cache: {avatar_cache}")
        
        if not os.path.exists(fc2_cache):
            os.makedirs(fc2_cache)
            print(f"✓ Created Far Cry 2 cache: {fc2_cache}")
        
        return cache_dir

    def _get_game_specific_cache_dir(self, game_mode):
        """Get the game-specific cache subdirectory
        
        Args:
            game_mode: "avatar" or "farcry2"
        
        Returns:
            Path to game-specific cache directory
        """
        base_cache = self.model_cache_dir
        
        if game_mode == "farcry2" or game_mode == "fc2":
            return os.path.join(base_cache, "fc2")
        else:
            return os.path.join(base_cache, "avatar")

    def convert_xbg_to_gltf(self, xbg_path, materials_path=None, lod_level=0, game_mode="avatar"):
        """
        Convert XBG file to GLTF format using direct import
        
        Args:
            xbg_path: Path to XBG file
            materials_path: Optional materials directory path
            lod_level: LOD level to extract (default: 0 = highest detail)
            game_mode: "avatar" or "farcry2" for cache organization
        """
        if not self.xbg_converter_script:
            print(f"⚠ Cannot convert {os.path.basename(xbg_path)} - converter script not found")
            return None, None
        
        if not os.path.exists(xbg_path):
            print(f"⚠ XBG file not found: {xbg_path}")
            return None, None
        
        # Check cache first
        cache_key = f"{xbg_path}_{lod_level}_{game_mode}"
        if cache_key in self.conversion_cache:
            cached = self.conversion_cache[cache_key]
            if os.path.exists(cached[0]) and os.path.exists(cached[1]):
                print(f"✓ Using cached conversion: {os.path.basename(cached[0])}")
                return cached
        
        # Get game-specific cache directory
        game_cache_dir = self._get_game_specific_cache_dir(game_mode)
        
        # Create cache path within game-specific folder
        if self.models_directory:
            rel_path = os.path.relpath(xbg_path, self.models_directory)
        else:
            rel_path = os.path.basename(xbg_path)
        
        cache_subdir = os.path.join(game_cache_dir, os.path.dirname(rel_path))
        if not os.path.exists(cache_subdir):
            os.makedirs(cache_subdir)
        
        base_name = os.path.splitext(os.path.basename(xbg_path))[0]
        gltf_output = os.path.join(cache_subdir, f"{base_name}.gltf")
        bin_output = os.path.join(cache_subdir, f"{base_name}.bin")
        
        # Skip if already converted, up-to-date, and has embedded textures
        if os.path.exists(gltf_output) and os.path.exists(bin_output):
            xbg_mtime = os.path.getmtime(xbg_path)
            gltf_mtime = os.path.getmtime(gltf_output)
            if gltf_mtime > xbg_mtime:
                # If we now have materials but the cached file has no textures, reconvert
                if materials_path:
                    try:
                        with open(gltf_output, 'r') as _cf:
                            _cd = json.load(_cf)
                        if len(_cd.get('images', [])) == 0:
                            print(f"↺ Reconverting (no textures in cache): {os.path.basename(gltf_output)}")
                            # fall through to fresh conversion
                        else:
                            print(f"✓ Using cached: {os.path.basename(gltf_output)}")
                            self.conversion_cache[cache_key] = (gltf_output, bin_output)
                            return gltf_output, bin_output
                    except Exception:
                        print(f"✓ Using cached: {os.path.basename(gltf_output)}")
                        self.conversion_cache[cache_key] = (gltf_output, bin_output)
                        return gltf_output, bin_output
                else:
                    print(f"✓ Using cached: {os.path.basename(gltf_output)}")
                    self.conversion_cache[cache_key] = (gltf_output, bin_output)
                    return gltf_output, bin_output
        
        # Run conversion using direct import
        print(f"🔄 Converting XBG -> GLTF ({game_mode}): {os.path.basename(xbg_path)}")
        
        try:
            import sys
            
            # Add canvas directory to Python path
            converter_dir = os.path.dirname(self.xbg_converter_script)
            if converter_dir not in sys.path:
                sys.path.insert(0, converter_dir)
            
            # Import the converter modules
            from xbg_parser import XBGParser
            from gltf_exporter import GLTFExporter
            
            # Parse XBG file
            parser = XBGParser(xbg_path)
            xbg_data = parser.parse(lod_level)
            
            # Export to GLTF
            mat_path = materials_path if materials_path and os.path.exists(materials_path) else None
            if mat_path:
                print(f"  With textures from: {os.path.basename(mat_path)}")
            else:
                print(f"  Without textures (materials not found)")
            
            exporter = GLTFExporter(xbg_data, mat_path)
            exporter.export(gltf_output)
            
            # Verify output files exist
            if os.path.exists(gltf_output) and os.path.exists(bin_output):
                # Check if textures were embedded
                with open(gltf_output, 'r') as f:
                    gltf_data = json.load(f)
                    texture_count = len(gltf_data.get('textures', []))
                    image_count = len(gltf_data.get('images', []))
                    material_count = len(gltf_data.get('materials', []))
                    
                    # Write debug info to file
                    debug_file = gltf_output.replace('.gltf', '_debug.txt')
                    with open(debug_file, 'w') as df:
                        df.write(f"XBG File: {os.path.basename(xbg_path)}\n")
                        df.write(f"Materials Path: {materials_path}\n")
                        df.write(f"Materials Exists: {os.path.exists(materials_path) if materials_path else False}\n")
                        df.write(f"Material Count: {material_count}\n")
                        df.write(f"Texture Count: {texture_count}\n")
                        df.write(f"Image Count: {image_count}\n\n")
                        
                        df.write("Materials in GLTF:\n")
                        for i, mat in enumerate(gltf_data.get('materials', [])):
                            df.write(f"  {i}: {mat.get('name', 'unnamed')}\n")
                    
                    print(f"  ✓ Converted with {texture_count} textures, {image_count} images embedded")
                    print(f"  📝 Debug info written to: {os.path.basename(debug_file)}")
                
                self.conversion_cache[cache_key] = (gltf_output, bin_output)
                return gltf_output, bin_output
                
        except Exception as e:
            print(f"✗ Conversion error for {os.path.basename(xbg_path)}: {e}")
            import traceback
            traceback.print_exc()
            return None, None
    
    def _load_local_entity_library(self):
        """Load the local entitylibrary_full.fcb.converted.xml file"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        possible_paths = [
            os.path.join(current_dir, "assets", "entitylibrary", "entitylibrary_full.fcb.converted.xml"),
            os.path.join(current_dir, "..", "canvas", "assets", "entitylibrary", "entitylibrary_full.fcb.converted.xml"),
            os.path.join(current_dir, "..", "assets", "entitylibrary", "entitylibrary_full.fcb.converted.xml"),
        ]
        for path in possible_paths:
            if os.path.exists(path):
                self.entity_library_path = path
                print(f"Found local EntityLibrary: {path}")
                try:
                    tree = ET.parse(path)
                    root = tree.getroot()
                    self.entity_patterns = {}

                    # Search for EntityPrototype objects
                    for proto_obj in root.findall(".//object[@name='EntityPrototype']"):
                        # Get the Name field from EntityPrototype (this is the clean name)
                        name_field = proto_obj.find(".//field[@name='Name']")
                        if name_field is None:
                            continue
                        
                        proto_name = name_field.get('value-String')
                        if not proto_name:
                            continue
                        
                        # Find the Entity object within this prototype
                        entity_obj = proto_obj.find(".//object[@name='Entity']")
                        if entity_obj is None:
                            continue
                        
                        # Also get the hidName for alternate matching
                        hid_field = entity_obj.find(".//field[@name='hidName']")
                        hid_name = hid_field.get('value-String') if hid_field is not None else None
                        
                        # Find the model file from CFileDescriptorComponent
                        descriptor_component = entity_obj.find(".//object[@name='CFileDescriptorComponent']")
                        if descriptor_component is not None:
                            hid_descriptor = descriptor_component.find(".//field[@name='hidDescriptor']")
                            if hid_descriptor is not None:
                                # Try GraphicComponent first
                                graphic_component = hid_descriptor.find(".//component[@class='GraphicComponent']")
                                if graphic_component is not None:
                                    resource = graphic_component.find(".//resource")
                                    if resource is not None:
                                        model_file = resource.get('fileName')
                                        if model_file:
                                            # Store using the EntityPrototype Name (clean name)
                                            self.entity_patterns[proto_name] = model_file
                                            # Also store using hidName for fallback
                                            if hid_name:
                                                self.entity_patterns[hid_name] = model_file
                                
                                # Try GraphicKitComponent for characters
                                kit_component = hid_descriptor.find(".//component[@class='GraphicKitComponent']")
                                if kit_component is not None:
                                    resource = kit_component.find(".//resource")
                                    if resource is not None:
                                        model_file = resource.get('fileName')
                                        if model_file:
                                            self.entity_patterns[proto_name] = model_file
                                            if hid_name:
                                                self.entity_patterns[hid_name] = model_file
                    
                    self._entity_library_loaded = True
                    print(f" Loaded {len(self.entity_patterns)} entity patterns")
                    return True
                except Exception as e:
                    print(f" Error parsing EntityLibrary: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
        
        print(f" Local EntityLibrary not found")
        return False
        
    def set_models_directory(self, directory_path, scan_recursive=True):
        """Set the models directory and index all models"""
        if not os.path.isdir(directory_path):
            print(f" Invalid models directory: {directory_path}")
            return False
        
        self.models_directory = os.path.abspath(directory_path)
        print(f" Models directory set: {self.models_directory}")
        
        if scan_recursive:
            self._index_models_directory()
        
        return True

    def set_materials_directory(self, materials_path):
        """Compatibility method - not needed for embedded textures"""
        print(" directory not needed (using embedded GLTF textures)")
        return True

    def _index_models_directory(self):
        """Index all GLTF files"""
        self._models_index = {}
        root = Path(self.models_directory)
        
        gltf_files = list(root.rglob('*.gltf'))
        
        for p in gltf_files:
            rel = p.relative_to(root).as_posix()
            key = p.name.lower()
            
            if key not in self._models_index:
                self._models_index[key] = []
            self._models_index[key].append(rel)
        
        total_models = sum(len(v) for v in self._models_index.values())
        print(f" Indexed {total_models} GLTF models")

    def set_entity_library_folder(self, worlds_path):
        """Compatibility method"""
        if not self._entity_library_loaded:
            return self._load_local_entity_library()
        return True

    def _get_timestamp(self):
        """Get current timestamp for logging"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _fix_resource_path_typos(self, resource_path):
        """Fix common typos and path issues in resource paths"""
        if not resource_path:
            return resource_path
        
        # Common typo fixes
        fixes = {
            'grahpics': 'graphics',
            'grpahics': 'graphics',
            'graphcis': 'graphics',
            'modles': 'models',
            'charaters': 'characters',
            'enviornment': 'environment',
            'enviroment': 'environment',
        }
        
        # Normalize path separators
        fixed_path = resource_path.replace('\\', '/')
        
        # Fix case-insensitive typos in path segments
        parts = fixed_path.split('/')
        fixed_parts = []
        
        for part in parts:
            part_lower = part.lower()
            # Check if this part matches any known typo
            fixed_part = part
            for typo, correct in fixes.items():
                if typo in part_lower:
                    fixed_part = part_lower.replace(typo, correct)
                    break
            fixed_parts.append(fixed_part)
        
        return '/'.join(fixed_parts)

    def load_static_gltf(self, gltf_path, bin_path=None):
        if gltf_path in self.models_cache:
            return self.models_cache[gltf_path]

        model = GLTFModel(os.path.basename(gltf_path), gltf_path)

        with open(gltf_path, "r", encoding="utf-8") as f:
            model.gltf_data = json.load(f)

        if bin_path and os.path.exists(bin_path):
            with open(bin_path, "rb") as f:
                model.bin_data = f.read()

        self._parse_gltf(model)
        self._load_embedded_textures(model)
        self._create_opengl_resources(model)

        model.loaded = True
        self.models_cache[gltf_path] = model
        return model

    # Cache of tplCreatureType -> {part_id: glm_path} so archetype XMLs are only parsed once
    _archetype_part_cache = {}
    # Cache of tplCreatureType -> [active_pid, ...] (positional, '' for empty slots)
    _archetype_active_cache = {}

    def _load_archetype_part_map(self, xml):
        """Look up the <part> descriptor for an in-game entity via its tplCreatureType.

        Worldsector entity instances don't embed the full kit descriptor, but the
        matching archetype file in the entities/ folder does.
        """
        creature_field = (xml.find("./field[@name='tplCreatureType']") or
                          xml.find(".//field[@name='tplCreatureType']"))
        if creature_field is None:
            return {}
        tpl = creature_field.get('value-String', '').strip()
        if not tpl:
            return {}

        if tpl in self._archetype_part_cache:
            return self._archetype_part_cache[tpl]

        # Strip known archetype prefixes to get the bare name
        bare = tpl
        for prefix in ('enemy_archetypes.', 'STP_archetypes.', 'object_archetypes.',
                        'AvatarInteractive.', 'Avatar_ScriptedEvents.', 'weapons.',
                        'Animals.Avatar.', 'vehicle.Avatar.', 'Plants.Avatar.',
                        'Animals.', 'vehicle.', 'Plants.'):
            if bare.startswith(prefix):
                bare = bare[len(prefix):]
                break

        entities_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'entities')
        if not os.path.isdir(entities_dir):
            self._archetype_part_cache[tpl] = {}
            return {}

        import glob as _glob
        matches = _glob.glob(os.path.join(entities_dir, bare + '_*.xml'))
        if not matches:
            self._archetype_part_cache[tpl] = {}
            return {}

        try:
            arch_root = ET.parse(matches[0]).getroot()
            part_map = {p.get('id'): p.get('fileName', '')
                        for p in arch_root.findall('.//part')
                        if p.get('id') and p.get('fileName', '')}
        except Exception as e:
            print(f"  Archetype parse failed for {bare}: {e}")
            part_map = {}

        self._archetype_part_cache[tpl] = part_map
        return part_map

    def _load_archetype_active_ids(self, xml):
        """Return the ordered list of default ActivePartOverwrite IDs from the archetype XML.

        Empty slots are stored as '' to preserve positional alignment with sector overrides.
        """
        creature_field = (xml.find("./field[@name='tplCreatureType']") or
                          xml.find(".//field[@name='tplCreatureType']"))
        if creature_field is None:
            return []
        tpl = creature_field.get('value-String', '').strip()
        if not tpl:
            return []

        if tpl in self._archetype_active_cache:
            return self._archetype_active_cache[tpl]

        bare = tpl
        for prefix in ('enemy_archetypes.', 'STP_archetypes.', 'object_archetypes.',
                        'AvatarInteractive.', 'Avatar_ScriptedEvents.', 'weapons.',
                        'Animals.Avatar.', 'vehicle.Avatar.', 'Plants.Avatar.',
                        'Animals.', 'vehicle.', 'Plants.'):
            if bare.startswith(prefix):
                bare = bare[len(prefix):]
                break

        entities_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'entities')

        import glob as _glob
        matches = _glob.glob(os.path.join(entities_dir, bare + '_*.xml')) if os.path.isdir(entities_dir) else []
        if not matches:
            self._archetype_active_cache[tpl] = []
            return []

        try:
            arch_root = ET.parse(matches[0]).getroot()
            active_ids = []
            for overwrite in arch_root.findall(".//object[@name='ActivePartOverwrite']"):
                field = overwrite.find("field[@name='text_PartID']")
                pid = field.get('value-String', '') if field is not None else ''
                active_ids.append(pid)
        except Exception:
            active_ids = []

        self._archetype_active_cache[tpl] = active_ids
        return active_ids

    def _resolve_kit_parts(self, entity, game_mode="avatar"):
        """Return list of (gltf_path, bin_path) for all active kit parts on a kit-assembled entity.

        Works for both archetype files (which embed <part> descriptors directly) and
        in-game worldsector entities (which only have PartIDs — the archetype is looked
        up via tplCreatureType to build the id->glm map).
        """
        xml = getattr(entity, 'xml_element', None)
        if xml is None:
            return []

        kit_comp = xml.find(".//object[@name='CGraphicKitComponent']")
        if kit_comp is None:
            return []

        # Build id -> glm-fileName map: embedded descriptor first, archetype fallback second
        part_map = {p.get('id'): p.get('fileName', '')
                    for p in xml.findall('.//part')
                    if p.get('id') and p.get('fileName', '')}
        if not part_map:
            part_map = self._load_archetype_part_map(xml)

        # Collect active PartIDs
        active_ids = []
        for overwrite in kit_comp.findall(".//object[@name='ActivePartOverwrite']"):
            field = overwrite.find("field[@name='text_PartID']")
            if field is not None:
                pid = field.get('value-String', '')
                if pid:
                    active_ids.append(pid)

        results = []
        seen = set()

        # Resolve PartIDs -> .glm -> .xbg -> gltf
        # The active kit parts are the COMPLETE visual representation of the character.
        # text_objModel in CGraphicComponent is used by the engine for physics/attachment
        # and is always a duplicate of one of the kit parts — do not include it separately.
        for pid in active_ids:
            glm_path = part_map.get(pid)
            if not glm_path:
                continue
            xbg_path = os.path.splitext(glm_path)[0] + '.xbg'
            if xbg_path in seen:
                continue
            seen.add(xbg_path)
            try:
                gltf_path, bin_path = self._extract_gltf_path_from_resource(xbg_path, game_mode=game_mode)
                if gltf_path:
                    results.append((gltf_path, bin_path))
            except Exception as e:
                print(f"  Kit part resolve failed for {os.path.basename(xbg_path)}: {e}")

        return results

    def _supplement_kit_parts_from_archetype(self, entity, existing_parts, game_mode="avatar"):
        """Add archetype-default kit parts that are missing from the sector entity.

        Handles three cases:
        - No inline CGraphicKitComponent: use the full archetype active list.
        - Kit component present but some ActivePartOverwrite slots are empty
          (no text_PartID): fill those positions from the archetype at the same index.
        - Kit component present with FEWER slots than the parent archetype (variant
          archetypes like WithMask/Hazmat): append parent parts for missing positions.
        """
        xml = getattr(entity, 'xml_element', None)
        if xml is None:
            return existing_parts

        arch_active_ids = self._load_archetype_active_ids(xml)
        if not arch_active_ids:
            return existing_parts

        # Build part_map from entity's own <part> elements, then merge parent archetype
        # parts so variant entities can resolve part IDs that live in the parent body kit.
        part_map = {p.get('id'): p.get('fileName', '')
                    for p in xml.findall('.//part')
                    if p.get('id') and p.get('fileName', '')}
        parent_parts = self._load_archetype_part_map(xml)
        if parent_parts:
            merged = dict(parent_parts)
            merged.update(part_map)  # entity's own parts take priority
            part_map = merged
        if not part_map:
            return existing_parts

        kit_comp = xml.find(".//object[@name='CGraphicKitComponent']")

        if kit_comp is None:
            extra_ids = [pid for pid in arch_active_ids if pid]
        else:
            extra_ids = []
            overwrites = kit_comp.findall(".//object[@name='ActivePartOverwrite']")
            for i, overwrite in enumerate(overwrites):
                field = overwrite.find("field[@name='text_PartID']")
                if field is None or not field.get('value-String', ''):
                    if i < len(arch_active_ids) and arch_active_ids[i]:
                        extra_ids.append(arch_active_ids[i])
            # Append parent parts for positions beyond this entity's slot count.
            # Variant archetypes (WithMask etc.) only define the override slot, so
            # slots 1…N from the parent go unseen without this.
            for i in range(len(overwrites), len(arch_active_ids)):
                if arch_active_ids[i]:
                    extra_ids.append(arch_active_ids[i])

        if not extra_ids:
            return existing_parts

        existing_gltf_names = {os.path.basename(gp) for gp, _ in existing_parts}
        result = list(existing_parts)

        for pid in extra_ids:
            glm_path = part_map.get(pid)
            if not glm_path:
                continue
            xbg_path = os.path.splitext(glm_path)[0] + '.xbg'
            try:
                gltf_path, bin_path = self._extract_gltf_path_from_resource(xbg_path, game_mode=game_mode)
                if gltf_path and os.path.basename(gltf_path) not in existing_gltf_names:
                    result.append((gltf_path, bin_path))
                    existing_gltf_names.add(os.path.basename(gltf_path))
            except Exception as e:
                print(f"  Archetype kit supplement failed for {os.path.basename(xbg_path)}: {e}")

        return result

    def get_model_for_entity(self, entity):
        """Get loaded model for entity - prefer cached models"""
        if not hasattr(entity, 'model_file') or not entity.model_file:
            return None
        
        gltf_path = entity.model_file
        
        # Return cached model if available (should be pre-loaded)
        if gltf_path in self.models_cache:
            cached_model = self.models_cache[gltf_path]
            print(f"📦 Using cached model: {os.path.basename(gltf_path)} - Textures: {len(cached_model.textures)}")
            return cached_model
        
        # If not cached, load it now (fallback for on-demand loading)
        bin_path = getattr(entity, 'bin_file', None)
        
        print(f"🔄 Loading model: {os.path.basename(gltf_path)}")
        
        model = GLTFModel(os.path.basename(gltf_path), gltf_path)
        try:
            with open(gltf_path, 'r', encoding='utf-8') as f:
                model.gltf_data = json.load(f)
            
            print(f"  GLTF has {len(model.gltf_data.get('images', []))} images, {len(model.gltf_data.get('materials', []))} materials")
            
            if bin_path and os.path.exists(bin_path):
                with open(bin_path, 'rb') as f:
                    model.bin_data = f.read()
            
            self._parse_gltf(model)
            
            print(f"  Calling _load_embedded_textures...")
            self._load_embedded_textures(model)
            print(f"  After _load_embedded_textures: {len(model.textures)} textures loaded")
            
            self._create_opengl_resources(model)
            model.loaded = True
            self.models_cache[gltf_path] = model

            print(f"⚠ Late-loaded model (should have been pre-loaded): {os.path.basename(gltf_path)}")
            return model

        except Exception as e:
            print(f"❌ Failed to load {gltf_path}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _load_embedded_textures(self, model):
        """Load textures embedded in GLTF as base64 PNG data"""
        if not PIL_AVAILABLE:
            print("  ⚠️ PIL not available - skipping textures")
            return
        
        # CHECK: Is OpenGL context current?
        try:
            version = gl.glGetString(gl.GL_VERSION)
            if not version:
                print("  ⚠️ No OpenGL context - cannot load textures")
                return
        except:
            print("  ⚠️ OpenGL context not available - cannot load textures")
            return
        
        gltf = model.gltf_data
        
        if 'materials' not in gltf or 'images' not in gltf:
            print("  ℹ️ No materials or images in GLTF")
            return
        
        print(f"  Loading textures from {len(gltf['materials'])} materials, {len(gltf['images'])} images...")
        
        # Load all images into OpenGL textures
        image_textures = {}
        image_has_alpha = {}   # img_idx → bool: source image had a real alpha channel
        for img_idx, image_def in enumerate(gltf['images']):
            if 'uri' in image_def and image_def['uri'].startswith('data:image/png;base64,'):
                # Extract base64 data
                base64_data = image_def['uri'].split(',', 1)[1]

                try:
                    # Decode base64 to PNG bytes
                    png_bytes = base64.b64decode(base64_data)

                    # Load PNG with PIL
                    pil_image = Image.open(BytesIO(png_bytes))

                    # Record whether the source image genuinely had an alpha channel
                    # before we potentially synthesise one via convert('RGBA').
                    src_had_alpha = pil_image.mode in ('RGBA', 'LA', 'PA')
                    image_has_alpha[img_idx] = src_had_alpha

                    # Convert to RGBA if needed
                    if pil_image.mode != 'RGBA':
                        pil_image = pil_image.convert('RGBA')

                    # Get image data
                    img_data = pil_image.tobytes()
                    width, height = pil_image.size

                    # Store raw pixel data so other GL contexts (e.g. preview widget) can upload their own copy
                    if not hasattr(model, 'texture_raw_data'):
                        model.texture_raw_data = {}
                    model.texture_raw_data[img_idx] = (width, height, img_data)

                    # Create OpenGL texture
                    texture_id = glGenTextures(1)
                    glBindTexture(GL_TEXTURE_2D, texture_id)
                    
                    # Upload texture data
                    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 
                                0, GL_RGBA, GL_UNSIGNED_BYTE, img_data)
                    
                    # Set texture parameters
                    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
                    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
                    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
                    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
                    
                    # Brighten textures using texture environment
                    glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
                    glTexEnvfv(GL_TEXTURE_ENV, GL_TEXTURE_ENV_COLOR, [1.5, 1.5, 1.5, 1.0])
                    
                    # Generate mipmaps
                    glGenerateMipmap(GL_TEXTURE_2D)
                    
                    glBindTexture(GL_TEXTURE_2D, 0)
                    
                    image_textures[img_idx] = texture_id
                    print(f"    ✅ Loaded image {img_idx}: {image_def.get('name', 'unnamed')} ({width}x{height}) -> GL texture {texture_id}")
                    
                except Exception as e:
                    print(f"    ❌ Failed to load image {img_idx}: {e}")
                    import traceback
                    traceback.print_exc()
        
        if not image_textures:
            print(f"  ⚠️ No images were successfully loaded (0/{len(gltf.get('images', []))})")
            return
        
        print(f"  ✅ Loaded {len(image_textures)} images into OpenGL textures")
        
        # Map materials to textures - USE ACTUAL MATERIAL INDEX, NOT ENUMERATION
        textures_in_gltf = gltf.get('textures', [])
        
        # Iterate through materials but preserve their actual indices
        materials_with_textures = 0
        for mat_idx in range(len(gltf['materials'])):
            material = gltf['materials'][mat_idx]
            mat_name = material.get('name', f'Material_{mat_idx}')
            
            # Check for baseColorTexture
            if 'pbrMetallicRoughness' in material:
                pbr = material['pbrMetallicRoughness']
                if 'baseColorTexture' in pbr:
                    tex_idx = pbr['baseColorTexture']['index']
                    
                    if tex_idx < len(textures_in_gltf):
                        texture_def = textures_in_gltf[tex_idx]
                        if 'source' in texture_def:
                            img_idx = texture_def['source']
                            
                            if img_idx in image_textures:
                                model.textures[mat_idx] = image_textures[img_idx]
                                # Track whether this material's texture has real alpha
                                if not hasattr(model, 'textures_has_alpha'):
                                    model.textures_has_alpha = {}
                                model.textures_has_alpha[mat_idx] = image_has_alpha.get(img_idx, False)
                                # Store mat_idx → img_idx mapping for context-independent re-upload
                                if not hasattr(model, 'texture_material_map'):
                                    model.texture_material_map = {}
                                model.texture_material_map[mat_idx] = img_idx
                                materials_with_textures += 1
                                print(f"    ✅ Material {mat_idx} ({mat_name}): Bound texture {image_textures[img_idx]} (from image {img_idx})")
                            else:
                                print(f"    ⚠️ Material {mat_idx} ({mat_name}): Image {img_idx} not in loaded images")
                        else:
                            print(f"    ⚠️ Material {mat_idx} ({mat_name}): Texture {tex_idx} has no source")
                    else:
                        print(f"    ⚠️ Material {mat_idx} ({mat_name}): Invalid texture index {tex_idx} (max {len(textures_in_gltf)-1})")
                else:
                    print(f"    ℹ️ Material {mat_idx} ({mat_name}): No baseColorTexture")
            else:
                print(f"    ℹ️ Material {mat_idx} ({mat_name}): No pbrMetallicRoughness")
        
        print(f"  📊 Final: {materials_with_textures}/{len(gltf['materials'])} materials have textures, {len(model.textures)} bindings created")

        # Read per-material PBR properties for renderer
        for mat_idx in range(len(gltf['materials'])):
            material = gltf['materials'][mat_idx]
            model.alpha_modes[mat_idx] = material.get('alphaMode', 'OPAQUE')
            model.alpha_cutoffs[mat_idx] = float(material.get('alphaCutoff', 0.5))
            model.emissive_factors[mat_idx] = material.get('emissiveFactor', [0.0, 0.0, 0.0])
            pbr = material.get('pbrMetallicRoughness', {})
            model.base_color_factors[mat_idx] = pbr.get('baseColorFactor', [1.0, 1.0, 1.0, 1.0])

        # Auto-promote OPAQUE materials whose source texture had a real alpha channel.
        # Avatar cloud, foliage, and billboard textures carry transparency in their
        # alpha channel but are frequently exported without alphaMode set, causing grey
        # rectangles (transparent pixels rendered as their opaque RGB color).
        _has_alpha = getattr(model, 'textures_has_alpha', {})
        for mat_idx in range(len(gltf['materials'])):
            if model.alpha_modes.get(mat_idx, 'OPAQUE') == 'OPAQUE' and _has_alpha.get(mat_idx, False):
                model.alpha_modes[mat_idx] = 'MASK'
                # Use a low cutoff so wispy/thin edges are preserved; override the
                # default 0.5 but respect any intentionally-low value already present.
                if model.alpha_cutoffs.get(mat_idx, 0.5) >= 0.5:
                    model.alpha_cutoffs[mat_idx] = 0.1

    def _parse_gltf(self, model):
        """Parse GLTF JSON and extract mesh data"""
        gltf = model.gltf_data
        
        buffers = []
        if 'buffers' in gltf:
            for buffer_def in gltf['buffers']:
                buffers.append(model.bin_data or b'')
        
        buffer_views = []
        if 'bufferViews' in gltf:
            for view_def in gltf['bufferViews']:
                buffer_idx = view_def['buffer']
                byte_offset = view_def.get('byteOffset', 0)
                byte_length = view_def['byteLength']
                
                buffer_data = buffers[buffer_idx]
                view_data = buffer_data[byte_offset:byte_offset + byte_length]
                buffer_views.append(view_data)
        
        accessors = []
        if 'accessors' in gltf:
            for accessor_def in gltf['accessors']:
                accessors.append(accessor_def)
        
        if 'meshes' in gltf:
            for mesh_def in gltf['meshes']:
                for primitive in mesh_def.get('primitives', []):
                    mesh = GLTFMesh()
                    attributes = primitive.get('attributes', {})
                    
                    if 'POSITION' in attributes:
                        pos_accessor = accessors[attributes['POSITION']]
                        mesh.vertices = self._extract_accessor_data(pos_accessor, buffer_views)
                        
                        if 'min' in pos_accessor and 'max' in pos_accessor:
                            model.bounds_min = pos_accessor['min']
                            model.bounds_max = pos_accessor['max']
                    
                    if 'NORMAL' in attributes:
                        norm_accessor = accessors[attributes['NORMAL']]
                        mesh.normals = self._extract_accessor_data(norm_accessor, buffer_views)
                    
                    if 'TEXCOORD_0' in attributes:
                        uv_accessor = accessors[attributes['TEXCOORD_0']]
                        mesh.uvs = self._extract_accessor_data(uv_accessor, buffer_views)
                    
                    if 'indices' in primitive:
                        idx_accessor = accessors[primitive['indices']]
                        mesh.indices = self._extract_accessor_data(idx_accessor, buffer_views)
                    
                    if 'material' in primitive:
                        mesh.material_index = primitive['material']
                    
                    model.meshes.append(mesh)

    def _extract_accessor_data(self, accessor, buffer_views):
        """Extract typed data from accessor"""
        view_idx = accessor['bufferView']
        byte_offset = accessor.get('byteOffset', 0)
        count = accessor['count']
        component_type = accessor['componentType']
        accessor_type = accessor['type']
        
        view_data = buffer_views[view_idx]
        
        type_sizes = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
        type_formats = {5120: 'b', 5121: 'B', 5122: 'h', 5123: 'H', 5125: 'I', 5126: 'f'}
        component_counts = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}
        
        components = component_counts[accessor_type]
        format_char = type_formats[component_type]
        element_size = type_sizes[component_type] * components
        
        data = []
        for i in range(count):
            offset = byte_offset + (i * element_size)
            element = struct.unpack_from(f'<{components}{format_char}', view_data, offset)
            
            if components == 1:
                data.append(element[0])
            else:
                data.append(element)
        
        return np.array(data, dtype=np.float32)

    def _emit_mesh_gl(self, model, mesh):
        """Emit GL commands for one mesh into the currently open display list.
        Returns False if the mesh is too large and should use immediate mode."""
        has_uvs = mesh.uvs is not None and len(mesh.uvs) > 0
        has_texture = mesh.material_index is not None and mesh.material_index in model.textures
        mat_idx = mesh.material_index

        alpha_mode   = model.alpha_modes.get(mat_idx, 'OPAQUE')
        alpha_cutoff = model.alpha_cutoffs.get(mat_idx, 0.5)
        emissive     = model.emissive_factors.get(mat_idx, [0.0, 0.0, 0.0])
        base_color   = model.base_color_factors.get(mat_idx, [1.0, 1.0, 1.0, 1.0])

        if has_texture:
            glEnable(GL_TEXTURE_2D)
            glBindTexture(GL_TEXTURE_2D, model.textures[mat_idx])
            glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
            # Some emissive-only materials export baseColorFactor=[0,0,0,1] because
            # they zero out diffuse in-game.  With GL_MODULATE that blacks out the
            # texture.  Use white instead so the texture is always visible.
            bc = base_color
            if 0.299 * bc[0] + 0.587 * bc[1] + 0.114 * bc[2] < 0.05:
                bc = [1.0, 1.0, 1.0, bc[3]]
            glColor4f(bc[0], bc[1], bc[2], bc[3])
            if alpha_mode == 'MASK':
                glEnable(GL_ALPHA_TEST)
                glAlphaFunc(GL_GREATER, alpha_cutoff)
            else:
                glDisable(GL_ALPHA_TEST)
        else:
            glDisable(GL_TEXTURE_2D)
            glDisable(GL_ALPHA_TEST)
            glColor4f(base_color[0] * 0.7, base_color[1] * 0.7, base_color[2] * 0.7, base_color[3])

        # glPushAttrib/glPopAttrib inside a display list scopes the emission change
        # to this mesh only.  Without this, the reset to [0,0,0,1] at the end of
        # each emissive mesh bleeds into subsequent meshes during the glow pass,
        # overriding the yellow emission set by render_selection_glow.
        is_emissive = any(c > 0.01 for c in emissive)
        if is_emissive:
            glPushAttrib(GL_LIGHTING_BIT)
            glMaterialfv(GL_FRONT_AND_BACK, GL_EMISSION, [emissive[0], emissive[1], emissive[2], 1.0])

        verts_c = np.ascontiguousarray(mesh.vertices, dtype=np.float32)
        norms_c = np.ascontiguousarray(mesh.normals, dtype=np.float32) if mesh.normals is not None else None

        if mesh.indices is not None:
            num_indices = len(mesh.indices)
            if num_indices > 100000:
                print(f"  ⚠ Large mesh ({num_indices} indices) — immediate mode")
                return False
            indices_c = np.ascontiguousarray(mesh.indices.flatten(), dtype=np.uint32)
            glEnableClientState(GL_VERTEX_ARRAY)
            glVertexPointer(3, GL_FLOAT, 0, verts_c)
            if norms_c is not None:
                glEnableClientState(GL_NORMAL_ARRAY)
                glNormalPointer(GL_FLOAT, 0, norms_c)
            if has_uvs and has_texture:
                glEnableClientState(GL_TEXTURE_COORD_ARRAY)
                glTexCoordPointer(2, GL_FLOAT, 0, np.ascontiguousarray(mesh.uvs, dtype=np.float32))
            glDrawElements(GL_TRIANGLES, num_indices, GL_UNSIGNED_INT, indices_c)
            glDisableClientState(GL_VERTEX_ARRAY)
            if norms_c is not None:
                glDisableClientState(GL_NORMAL_ARRAY)
            if has_uvs and has_texture:
                glDisableClientState(GL_TEXTURE_COORD_ARRAY)
        else:
            glEnableClientState(GL_VERTEX_ARRAY)
            glVertexPointer(3, GL_FLOAT, 0, verts_c)
            if norms_c is not None:
                glEnableClientState(GL_NORMAL_ARRAY)
                glNormalPointer(GL_FLOAT, 0, norms_c)
            if has_uvs and has_texture:
                glEnableClientState(GL_TEXTURE_COORD_ARRAY)
                glTexCoordPointer(2, GL_FLOAT, 0, np.ascontiguousarray(mesh.uvs, dtype=np.float32))
            glDrawArrays(GL_TRIANGLES, 0, len(mesh.vertices))
            glDisableClientState(GL_VERTEX_ARRAY)
            if norms_c is not None:
                glDisableClientState(GL_NORMAL_ARRAY)
            if has_uvs and has_texture:
                glDisableClientState(GL_TEXTURE_COORD_ARRAY)

        if has_texture:
            glBindTexture(GL_TEXTURE_2D, 0)
            glDisable(GL_TEXTURE_2D)
            if alpha_mode == 'MASK':
                glDisable(GL_ALPHA_TEST)

        if is_emissive:
            glPopAttrib()

        return True

    def _compile_mesh_display_list(self, model, meshes):
        """Compile a display list for the given mesh subset.
        Returns the list ID, 'immediate' if a mesh was too large, or None on error."""
        dl = glGenLists(1)
        list_started = False
        try:
            glNewList(dl, GL_COMPILE)
            list_started = True
            for mesh in meshes:
                if mesh.vertices is None:
                    continue
                if not self._emit_mesh_gl(model, mesh):
                    glEndList()
                    list_started = False
                    glDeleteLists(dl, 1)
                    return 'immediate'
        except Exception as e:
            print(f"  ✗ Display list compile error: {e}")
            if list_started:
                glEndList()
            try:
                glDeleteLists(dl, 1)
            except Exception:
                pass
            return None
        finally:
            if list_started:
                glEndList()
        return dl

    def _create_opengl_resources(self, model):
        """Build display lists for this model, split into opaque and blend passes."""
        if not model.meshes:
            return

        opaque_meshes = []
        blend_meshes  = []
        for mesh in model.meshes:
            if mesh.vertices is None:
                continue
            if model.alpha_modes.get(mesh.material_index, 'OPAQUE') == 'BLEND':
                blend_meshes.append(mesh)
            else:
                opaque_meshes.append(mesh)

        if opaque_meshes:
            result = self._compile_mesh_display_list(model, opaque_meshes)
            if result == 'immediate':
                model.use_immediate_mode = True
                return
            model.display_list = result

        if blend_meshes:
            result = self._compile_mesh_display_list(model, blend_meshes)
            if result and result != 'immediate':
                model.display_list_blend = result

    def render_model(self, model, position, rotation=0, scale=1.0):
        """Render model at position"""
        if not model or not model.loaded or (not model.display_list and not getattr(model, 'display_list_blend', None)):
            return False
        
        glPushMatrix()
        glTranslatef(position[0], position[1], position[2])
        
        if rotation != 0:
            glRotatef(rotation, 0, 1, 0)
        
        if scale != 1.0:
            glScalef(scale, scale, scale)
        
        glCallList(model.display_list)
        glPopMatrix()
        
        return True

    def prepare_batches(self, entities, selected_entities):
        """Prepare instance batches for all entities - call once per frame before rendering
        
        OPTIMIZATION: For 10K+ entities, this tracks entity count and logs performance stats
        """
        self.instance_batches.clear()
        
        # OPTIMIZATION: Track entity count for performance logging
        total_entities = len(entities)
        entities_with_models = 0
        
        for entity in entities:
            model_path = getattr(entity, 'model_file', None)
            kit_parts = getattr(entity, 'kit_model_files', [])

            if not model_path and not kit_parts:
                continue

            if not all(hasattr(entity, attr) for attr in ('x', 'y', 'z')):
                continue

            entities_with_models += 1

            if model_path and model_path not in self.instance_batches:
                self.instance_batches[model_path] = []

            # Position: swap Y and Z, negate Y for OpenGL coordinates
            pos_x = float(entity.x)
            pos_y = float(entity.z)
            pos_z = float(-entity.y)

            # Rotation + scale — extracted once and cached; re-extracted only after invalidation
            eid = id(entity)
            if eid not in self._entity_rs_cache:
                rotation_x = rotation_y = rotation_z = 0.0
                scale = 1.0
                xml_elem = getattr(entity, 'xml_element', None)
                if xml_elem is not None:
                    angles_field = xml_elem.find(".//field[@name='hidAngles']")
                    if angles_field is not None:
                        angles_value = angles_field.get('value-Vector3')
                        if angles_value:
                            try:
                                parts = angles_value.split(',')
                                if len(parts) >= 3:
                                    rotation_x = float(parts[0].strip())
                                    rotation_y = float(parts[1].strip())
                                    rotation_z = (360 - float(parts[2].strip())) % 360
                            except (ValueError, IndexError):
                                pass
                    if rotation_z == 0.0 and rotation_x == 0.0 and rotation_y == 0.0:
                        angles_elem = xml_elem.find("./value[@name='hidAngles']")
                        if angles_elem is not None:
                            x_elem = angles_elem.find("./x")
                            y_elem = angles_elem.find("./y")
                            z_elem = angles_elem.find("./z")
                            if x_elem is not None and x_elem.text:
                                rotation_x = float(x_elem.text.strip())
                            if y_elem is not None and y_elem.text:
                                rotation_y = float(y_elem.text.strip())
                            if z_elem is not None and z_elem.text:
                                rotation_z = (360 - float(z_elem.text.strip())) % 360
                    scale_field = xml_elem.find(".//field[@name='hidScale']")
                    if scale_field is not None and scale_field.text and len(scale_field.text) >= 8:
                        try:
                            import struct
                            s = struct.unpack('<f', bytes.fromhex(scale_field.text[:8]))[0]
                            if 0 < s <= 100:
                                scale = s
                        except Exception:
                            pass
                self._entity_rs_cache[eid] = (rotation_x, rotation_y, rotation_z, scale)
            else:
                rotation_x, rotation_y, rotation_z, scale = self._entity_rs_cache[eid]

            is_selected = entity in selected_entities

            # Tuple layout: (entity, px, py, pz, rx, ry, rz, scale, is_selected)
            # Tuples are ~2x faster to allocate than dicts and reduce GC pressure.
            instance_tuple = (entity, pos_x, pos_y, pos_z,
                              rotation_x, rotation_y, rotation_z, scale, is_selected)
            if model_path:
                self.instance_batches[model_path].append(instance_tuple)

            # Kit-assembled NPCs: add each kit part at the same transform
            for kit_gltf, _kit_bin in kit_parts:
                if kit_gltf not in self.instance_batches:
                    self.instance_batches[kit_gltf] = []
                self.instance_batches[kit_gltf].append(instance_tuple)
        
        # Log batch stats every ~300 frames (~5s at 60fps) without calling time.time() per frame
        self._batch_log_frame = getattr(self, '_batch_log_frame', 0) + 1
        if self._batch_log_frame >= 300 and entities_with_models >= 1000:
            self._batch_log_frame = 0
            unique_models = len(self.instance_batches)
            print(f"📊 Batch Stats: {entities_with_models}/{total_entities} entities with models, {unique_models} unique models")

    def render_batched_models(self):
        """Render all models using optimized batching for 10K+ objects
        
        OPTIMIZATION: Group instances by selection state to reduce glColor calls
        For 10K objects: reduces 10,000 glColor calls to ~2 per model type
        """
        if not self.instance_batches:
            return 0
        
        instances_rendered = 0
        
        # XBG winding is CW. Culling is explicitly disabled so the full model is
        # visible from all angles — another render pass (e.g. terrain) may have
        # left GL_CULL_FACE enabled, so we must turn it off here.
        glFrontFace(GL_CW)
        glDisable(GL_CULL_FACE)

        # Enable depth testing
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        glDepthMask(GL_TRUE)

        # GL_ALPHA_TEST is now controlled per-mesh inside each display list,
        # keyed on whether the source texture genuinely had an alpha channel.
        # This prevents opaque models (whose textures were RGB-only) from
        # being incorrectly discarded by the alpha test.

        # OPTIMIZATION: Track last color to avoid redundant glColor calls
        last_color = None

        for model_path, instances in self.instance_batches.items():
            if not instances:
                continue
            
            # Get or load model
            model = self.models_cache.get(model_path)
            if not model:
                continue
            
            # Display list should already exist (created at level load time).
            # This fallback handles any model that slipped through (e.g. late-loaded).
            if model.loaded and model.display_list is None and not getattr(model, 'display_list_blend', None) and not hasattr(model, 'use_immediate_mode'):
                print(f"⚠️ FREEZE SOURCE — mid-render display list: {os.path.basename(model_path)}")
                try:
                    self._create_opengl_resources(model)
                except Exception as e:
                    print(f"Error creating OpenGL resources for {os.path.basename(model_path)}: {e}")
                    continue

            if not model.loaded or (not model.display_list and not getattr(model, 'display_list_blend', None) and not hasattr(model, 'use_immediate_mode')):
                continue
            
            # OPTIMIZATION: Group instances by selection state to reduce glColor calls
            selected_instances = [i for i in instances if i[8]]
            unselected_instances = [i for i in instances if not i[8]]
            
            # Render unselected instances first (most common case)
            if unselected_instances:
                color = (1.0, 1.0, 1.0)
                if last_color != color:
                    glColor3f(*color)
                    last_color = color
                
                for instance_data in unselected_instances:
                    self._render_single_instance(model, instance_data)
                    instances_rendered += 1
            
            # Render selected instances
            if selected_instances:
                color = (1.2, 1.2, 1.5)
                if last_color != color:
                    glColor3f(*color)
                    last_color = color
                
                for instance_data in selected_instances:
                    self._render_single_instance(model, instance_data)
                    instances_rendered += 1
        
        # Restore default state (display lists may have left GL_ALPHA_TEST enabled)
        glDisable(GL_ALPHA_TEST)

        # Pass 2: BLEND-mode meshes — rendered after all opaque geometry
        blend_models = [(p, self.models_cache[p]) for p in self.instance_batches
                        if p in self.models_cache and getattr(self.models_cache[p], 'display_list_blend', None)]
        if blend_models:
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glDepthMask(GL_FALSE)
            glColor3f(1.0, 1.0, 1.0)

            for model_path, model in blend_models:
                for instance_data in self.instance_batches.get(model_path, []):
                    self._render_single_instance(model, instance_data,
                                                 display_list=model.display_list_blend)
                    instances_rendered += 1

            glDisable(GL_BLEND)
            glDepthMask(GL_TRUE)

        return instances_rendered

    def render_selection_glow(self, glow_intensity):
        """Re-render selected instances with a pulsing pure-yellow overlay.

        Renders raw vertex geometry only (no textures, no lighting) so the glow
        colour is always yellow regardless of the model's own texture colours.
        The old approach used GL_EMISSION × GL_MODULATE, which multiplied yellow
        by the texture colour — blue models turned dark, orange models turned red.
        Bypassing the display list and textures entirely fixes this.
        """
        if glow_intensity <= 0:
            return

        glPushAttrib(GL_ALL_ATTRIB_BITS)
        try:
            glDisable(GL_LIGHTING)
            glDisable(GL_TEXTURE_2D)
            glDisable(GL_CULL_FACE)
            glDisable(GL_ALPHA_TEST)

            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glDepthFunc(GL_LEQUAL)   # passes at same depth as already-rendered model
            glDepthMask(GL_FALSE)    # don't overwrite depth — overlay only

            glColor4f(1.0, 0.85, 0.0, glow_intensity)  # pure yellow, no texture influence

            for model_path, instances in self.instance_batches.items():
                selected = [i for i in instances if i[8]]
                if not selected:
                    continue
                model = self.models_cache.get(model_path)
                if not model or not model.loaded or not model.meshes:
                    continue
                for instance_data in selected:
                    self._render_glow_geometry(model, instance_data)
        finally:
            glPopAttrib()

    def _render_glow_geometry(self, model, instance_data):
        """Render raw vertex geometry for the glow pass — no textures, no lighting."""
        glPushMatrix()
        glTranslatef(instance_data[1], instance_data[2], instance_data[3])
        glRotatef(-90, 1, 0, 0)
        if instance_data[6] != 0:
            glRotatef(-instance_data[6], 0, 0, 1)
        if instance_data[4] != 0:
            glRotatef(instance_data[4], 1, 0, 0)
        if instance_data[5] != 0:
            glRotatef(instance_data[5], 0, 1, 0)
        if instance_data[7] != 1.0:
            glScalef(instance_data[7], instance_data[7], instance_data[7])

        for mesh in model.meshes:
            if mesh.vertices is None:
                continue
            glEnableClientState(GL_VERTEX_ARRAY)
            glVertexPointer(3, GL_FLOAT, 0, mesh.vertices)
            if mesh.indices is not None:
                glDrawElements(GL_TRIANGLES, len(mesh.indices), GL_UNSIGNED_INT, mesh.indices)
            else:
                glDrawArrays(GL_TRIANGLES, 0, len(mesh.vertices))
            glDisableClientState(GL_VERTEX_ARRAY)

        glPopMatrix()

    def _render_single_instance(self, model, instance_data, display_list=None):
        """Render a single instance of a model.
        Pass display_list to override the default model.display_list (e.g. for the blend pass)."""
        # instance_data tuple: (entity, px, py, pz, rx, ry, rz, scale, is_selected)
        glPushMatrix()

        glTranslatef(instance_data[1], instance_data[2], instance_data[3])

        glRotatef(-90, 1, 0, 0)

        if instance_data[6] != 0:
            glRotatef(-instance_data[6], 0, 0, 1)
        if instance_data[4] != 0:
            glRotatef(instance_data[4], 1, 0, 0)
        if instance_data[5] != 0:
            glRotatef(instance_data[5], 0, 1, 0)

        if instance_data[7] != 1.0:
            glScalef(instance_data[7], instance_data[7], instance_data[7])

        dl = display_list if display_list is not None else model.display_list
        if hasattr(model, 'use_immediate_mode') and model.use_immediate_mode:
            self._render_immediate_mode(model)
        elif dl:
            glCallList(dl)

        glPopMatrix()

    def _render_immediate_mode(self, model):
        """Render model in immediate mode (for large meshes)"""
        for mesh in model.meshes:
            if mesh.vertices is None:
                continue

            has_uvs = mesh.uvs is not None and len(mesh.uvs) > 0
            has_texture = mesh.material_index is not None and mesh.material_index in model.textures
            mat_idx = mesh.material_index
            alpha_mode   = model.alpha_modes.get(mat_idx, 'OPAQUE')
            alpha_cutoff = model.alpha_cutoffs.get(mat_idx, 0.5)
            base_color   = model.base_color_factors.get(mat_idx, [1.0, 1.0, 1.0, 1.0])

            if has_texture:
                glEnable(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, model.textures[mat_idx])
                glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
                glColor4f(base_color[0], base_color[1], base_color[2], base_color[3])
                if alpha_mode == 'MASK':
                    glEnable(GL_ALPHA_TEST)
                    glAlphaFunc(GL_GREATER, alpha_cutoff)
                else:
                    glDisable(GL_ALPHA_TEST)
            else:
                glDisable(GL_TEXTURE_2D)
                glDisable(GL_ALPHA_TEST)

            glEnableClientState(GL_VERTEX_ARRAY)
            glVertexPointer(3, GL_FLOAT, 0, mesh.vertices)

            if mesh.normals is not None:
                glEnableClientState(GL_NORMAL_ARRAY)
                glNormalPointer(GL_FLOAT, 0, mesh.normals)

            if has_uvs and has_texture:
                glEnableClientState(GL_TEXTURE_COORD_ARRAY)
                glTexCoordPointer(2, GL_FLOAT, 0, mesh.uvs)

            if mesh.indices is not None:
                glDrawElements(GL_TRIANGLES, len(mesh.indices), GL_UNSIGNED_INT, mesh.indices)
            else:
                glDrawArrays(GL_TRIANGLES, 0, len(mesh.vertices))

            glDisableClientState(GL_VERTEX_ARRAY)
            if mesh.normals is not None:
                glDisableClientState(GL_NORMAL_ARRAY)
            if has_uvs and has_texture:
                glDisableClientState(GL_TEXTURE_COORD_ARRAY)

            if has_texture:
                glBindTexture(GL_TEXTURE_2D, 0)
                glDisable(GL_TEXTURE_2D)
                if mesh_has_alpha:
                    glDisable(GL_ALPHA_TEST)

    def clear_cache(self):
        """Clear all cached resources"""
        for model in self.models_cache.values():
            if model.display_list:
                glDeleteLists(model.display_list, 1)
            for tex_id in model.textures.values():
                glDeleteTextures([tex_id])
        
        for tex_id in self._texture_cache.values():
            glDeleteTextures([tex_id])
        
        if self.fallback_cube_list:
            glDeleteLists(self.fallback_cube_list, 1)
        
        self.models_cache.clear()
        print("Cache cleared")