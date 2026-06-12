"""3D Model Loader - FIXED to load embedded GLTF textures
Extracts base64 PNG textures from GLTF and loads them into OpenGL
"""

import subprocess
import sys
import os
import json
import struct
import base64
import ctypes
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
        self.tangents = None          # per-vertex tangents (GLSL normal mapping)
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

        # Models are read directly from .xbg game files (no GLTF conversion).
        # See load_static_xbg / canvas/xbg_direct_loader.py.

        # GLSL material shader (per-pixel diffuse+normal+spec+emission). Compiled
        # lazily on first render; falls back to fixed-function display lists if
        # it can't build. See model_shader.py / render_batched_models.
        self._model_shader = None
        self._model_shader_disabled = False
        # Depth-prepass program (occlusion / early-Z). Independent of the material
        # shader: if it fails to compile we just skip the prepass (color pass still
        # renders correctly, only without the overdraw savings).
        self._depth_shader = None
        self._depth_shader_disabled = False
        # Depth prepass is a GPU (overdraw) optimization but costs a SECOND
        # geometry submission (~40% more draw calls). This editor is CPU-bound on
        # draw submission, so the prepass currently costs more than it saves —
        # default OFF. Flip to True (and it'll lazily compile the depth program)
        # if you become GPU/fragment-bound (heavy overdraw, expensive shader).
        self._depth_prepass_enabled = False
        # Whether PyOpenGL per-call error checking is on (main.py disables it for
        # speed). When OFF we run a single glGetError() probe per frame instead.
        self._shader_gl_error_logged = False
        try:
            import OpenGL
            self._gl_checks_on = bool(getattr(OpenGL, 'ERROR_CHECKING', True))
        except Exception:
            self._gl_checks_on = True

        # VAO-based instancing: cache each mesh's full attribute setup (per-vertex
        # 0-3 + per-instance 4-7) in one Vertex Array Object, so a draw is just
        # glBindVertexArray + glDrawElementsInstanced instead of ~12 attrib-pointer
        # calls/mesh.
        #
        # DISABLED BY DEFAULT (May 2026): when first enabled it caused models to go
        # missing AND the fixed-function terrain to render black — VAO/generic-attrib
        # state leaking into the compat-profile fixed-function passes that run before/
        # after entities (terrain, cubes, glow). The manual per-draw attrib path
        # (still the active path) is proven and only ~13 ms slower in dense scenes;
        # not worth the breakage. Re-enable + debug the leak before trusting it.
        self._vao_enabled = False
        self._vao_supported = None

        # GPU-driven renderer (GL 4.3+ MultiDrawIndirect). force_render_tier is set
        # by the F2/F3 debug keys ('bindless' | 'texarray' | None). When set AND the
        # context supports it, render_batched_models routes to the GPU-driven path;
        # otherwise the universal instanced path. _gpu_driven is lazily created.
        self.force_render_tier = None
        self._gpu_driven = None

        # ── Array-native instance pipeline (GPU-driven mode only) ──
        # Static "row" tables aligned to the canvas's _valid_entities_3d list:
        # one row per (entity, model) pair (kit parts add extra rows). Per frame,
        # prepare_gpu_frame() turns the cull's index array into the instance
        # SSBO + per-model counts with pure numpy — replacing the per-entity
        # Python loops of prepare_batches/_collect_frame on the hot path.
        self._gdr_row_ent = None       # (R,) int32 — index into _valid_entities_3d
        self._gdr_row_slot = None      # (R,) int32 — model slot id
        self._gdr_row_rot = None       # (R,3) f32
        self._gdr_row_scale = None     # (R,) f32
        self._gdr_overlay = None       # (R,) f32 — selection overlay (0 / 0.35)
        self._gdr_row_map = {}         # id(entity) -> [row indices]
        self._gdr_model_paths = []     # slot id -> model_path
        self._gdr_modelled_ids = set() # id(entity) for entities with a loaded model
        self._gdr_rows_version = None  # canvas._pos_arrays_version rows were built for
        self._gdr_slots_version = 0    # bumps only when the slot list CONTENT changes
        self._gdr_sel_ids = frozenset()  # selection snapshot the overlay reflects
        self._gdr_frame = None         # per-frame {inst, counts, offsets} for the GDR
        self._gdr_fallback_args = None # (entities, selected) to rebuild batches if GDR fails
        self.gdr_drew_last = False     # True when the last frame drew via the GDR
        # Contribution culling (GDR mode): skip model instances whose bounding
        # sphere projects smaller than this many pixels on screen — distant
        # clutter costs full vertex work for sub-noise visuals. The big lever
        # for vertex-bound GPUs (integrated Radeon/Intel). 0 disables. F9 cycles.
        self.gdr_min_pixel_size = 4.0

        # True while load_complete_level runs: mid-load repaints must NOT hit the
        # model render paths (the GPU-driven rebuild on a churning models_cache
        # froze the GUI thread). prepare_batches / prepare_gpu_frame /
        # render_batched_models / cast_shadows all early-out on this.
        self.loading_suspended = False

        # Memo for _extract_gltf_path_from_resource: (resource_path, game_mode)
        # -> (gltf_path, bin_path). Resolution does case-insensitive directory
        # walks, and the load pipeline resolves the same resource for hundreds
        # of entities — twice (pre-unified pass + full-pool pass). Negative
        # results are cached too. Cleared in clear_cache.
        self._extract_cache = {}
        # Depth prepass (early-Z occlusion) on the GPU-driven path. F8 toggles it.
        # Default OFF: a prepass only pays off when the scene is GPU-fragment-bound
        # (heavy overdraw of the expensive material shader). It adds a full extra
        # geometry pass, so on vertex/draw/CPU-bound scenes it's pure overhead and
        # FPS drops. Turn on with F8 to test fragment-heavy views.
        self.gpu_depth_prepass = False

        # Sun shadow-map inputs, set per frame by the canvas (set_shadow_inputs).
        # The GPU-driven path casts model depth (cast_shadows) then samples it.
        self._shadow_tex = 0
        self._shadow_light_vp = None
        self._shadows_on = False

        # Bioluminescence / day-night: 0 = day (emission off), 1 = night (emission
        # glows). Set per frame by the canvas from its day/night cycle; both the
        # universal shader and the GPU-driven shader scale emission by it.
        self.night_factor = 0.0

        # Fragment-cost A/B debug switches. Flip one at runtime
        # (model_loader.dbg_no_normal = True, etc.) and watch the GPU-time readout:
        # the delta is that feature's per-pixel cost. Lets us measure normal-map /
        # specular / emission / lighting cost without a per-op GPU profiler.
        self.dbg_no_normal = False     # force u_has_normal = 0 (skip normal mapping)
        self.dbg_no_spec = False       # force u_has_specular = 0
        self.dbg_no_emission = False   # force u_has_emission = 0
        self.dbg_unlit = False         # u_unlit = 1 (skip the per-light loop entirely)
        self.dbg_flip_green = True     # Avatar normal maps are DirectX-Y (green flipped) — CONFIRMED correct; F5 toggles for debug
        self.dbg_flip_normal = False   # F6: flip the base geometry normal (base normals already outward)

        # Animated-UV state (Unlit/FX scroll). has_animated_materials is set when
        # any loaded material has nonzero AnimType/USpeed/VSpeed; the canvas uses
        # it to keep repainting so the scroll is visible. _anim_t0 is the time
        # origin for the per-frame UV offset.
        self.has_animated_materials = False
        self._anim_t0 = time.monotonic()

        # Hardware-instancing buffer: per-instance (pos3, rot3, scale, overlay)
        # uploaded once per model per frame and consumed by glDrawElementsInstanced
        # so all copies of a model draw in ONE call. Lazily created in
        # _setup_instance_attribs; freed in clear_cache.
        self._instance_vbo = None

        self._load_local_entity_library()
        print("ModelLoader initialized with embedded texture support and batch rendering")

    def _extract_gltf_path_from_resource(self, resource_path, game_mode="avatar", _recursion_depth=0):
        """Cached wrapper around _extract_gltf_path_uncached.

        Resolution walks directories case-insensitively; the same resource path
        is resolved for hundreds of entities and in BOTH assignment passes, so
        memoizing (incl. negative results) makes the second pass near-free.
        Recursive sub-resolutions (depth > 0) are NOT cached — near the depth
        limit they can return truncated results that must not be reused."""
        if _recursion_depth:
            return self._extract_gltf_path_uncached(resource_path, game_mode, _recursion_depth)
        key = (resource_path, game_mode)
        if key in self._extract_cache:
            return self._extract_cache[key]
        result = self._extract_gltf_path_uncached(resource_path, game_mode, 0)
        self._extract_cache[key] = result
        return result

    def _extract_gltf_path_uncached(self, resource_path, game_mode="avatar", _recursion_depth=0):
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
        # DIRECT XBG — read the .xbg straight from the game files. No GLTF /
        # .bin intermediates. entity.model_file becomes the .xbg path; the
        # loaders (Phase A/B, get_model_for_entity) route '.xbg' to
        # load_static_xbg / build_xbg_model. If the .xbg isn't at this exact
        # path, the STEP 3 fallbacks below fix the path and re-enter here.
        # ==========================================
        xbg_path = self._find_xbg_case_insensitive(rel_parts)
        if xbg_path:
            if _recursion_depth == 0:
                print(f"  Direct XBG: {os.path.basename(xbg_path)}")
            return xbg_path, None

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
        skipped_done = 0   # entities already resolved by an earlier pass this load
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
            
            # Assign-then-skip: the load pipeline runs assignment TWICE (pre-
            # unified snapshot, then the full pool after unified sectors swaps
            # in new worldsector objects). Objects that survived the swap keep
            # this marker and are skipped; load_all_worldsectors also TRANSFERS
            # marker + assignment from replaced objects to their new twins.
            # The marker is set at the END of each iteration (not here) — the
            # unified-sectors thread reads it concurrently for that transfer
            # and must never see a marked-but-half-assigned entity.
            if getattr(entity, '_model_assign_done', False):
                skipped_done += 1
                continue

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
                if gltf_path and bool(gltf_path) and gltf_path.lower().endswith('.xbg'):
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
                            if bool(gltf_path) and gltf_path.lower().endswith('.xbg'):
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
                        if bool(gltf_path) and gltf_path.lower().endswith('.xbg'):
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
                            if bool(gltf_path) and gltf_path.lower().endswith('.xbg'):
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
                        'was_converted': bool(gltf_path) and gltf_path.lower().endswith('.xbg')
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

            # Marked LAST (see comment at the top of the loop): the concurrent
            # unified-sectors swap only carries assignments from fully-processed
            # entities.
            entity._model_assign_done = True

        log(f"Model assignment complete: {matched} matched, {unmatched} unmatched, "
            f"{converted_xbg_count} read directly from XBG"
            + (f", {skipped_done} already assigned (skipped)" if skipped_done else ""))
        
        if kit_fallback_count > 0:
            log(f"  _Kit fallbacks used: {kit_fallback_count}")
        if obsolete_fallback_count > 0:
            log(f"  Obsolete fallbacks used: {obsolete_fallback_count}")

        print(f"🎉 {matched} matched, {unmatched} unmatched, {converted_xbg_count} direct-XBG models ({game_mode} mode)")
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
                    f.write(f"Direct-XBG models: {converted_xbg_count}\n")
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
                            f.write(f"NOTE: Read directly from XBG file\n")
                        
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
        """Set the materials (XBM/XBT) base directory for DIRECT-XBG texture loading.

        WAS a no-op stub from the embedded-GLTF era ("not needed — using embedded
        GLTF textures") that silently dropped the path, leaving
        self.materials_directory = None → every XBM/XBT failed to resolve →
        models rendered untextured/grey. The direct-XBG pipeline resolves
        materials/textures from disk, so it needs this root.
        """
        if not materials_path or not os.path.isdir(materials_path):
            print(f" Invalid materials directory: {materials_path!r} "
                  f"— models will render untextured")
            return False
        self.materials_directory = os.path.abspath(materials_path)
        # Rebuild the texture loader against the new root: it may have been
        # created earlier with a None/stale path (and cached 'not found' results)
        # during model loads that happened before this was set.
        try:
            from texture_loader import TextureLoader
            self.texture_loader = TextureLoader(self.materials_directory)
        except Exception as e:
            print(f" TextureLoader init failed for {self.materials_directory}: {e}")
            self.texture_loader = None
        print(f" Materials directory set: {self.materials_directory}")
        return True

    def _index_models_directory(self):
        """Index all XBG model files (diagnostic count only — the loader
        resolves paths by directory walk in _find_xbg_case_insensitive, not via
        this index)."""
        self._models_index = {}
        root = Path(self.models_directory)

        for p in root.rglob('*.xbg'):
            rel = p.relative_to(root).as_posix()
            key = p.name.lower()
            self._models_index.setdefault(key, []).append(rel)

        total_models = sum(len(v) for v in self._models_index.values())
        print(f" Indexed {total_models} XBG models")

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

    # ==================================================================
    # DIRECT XBG LOADING (no GLTF / .bin intermediates)
    # ------------------------------------------------------------------
    # load_static_xbg() parses an .xbg straight into the same GLTFModel the
    # gltf path produced (geometry via canvas/xbg_direct_loader, textures via
    # _load_xbg_textures). This is the replacement for the old runtime
    # xbg2gltf.py subprocess conversion.
    # ==================================================================
    def load_static_xbg(self, xbg_path, lod_level=0):
        """Load a model DIRECTLY from .xbg + on-the-fly XBM/XBT — no caching.

        Produces the same GLTFModel/GLTFMesh data the gltf round-trip did, so
        the existing fixed-function renderer (render_batched_models / display
        lists / picking) works unchanged. Requires a current OpenGL context
        (textures + display lists are created here).
        """
        if xbg_path in self.models_cache:
            return self.models_cache[xbg_path]

        from xbg_direct_loader import build_xbg_model
        model = build_xbg_model(xbg_path, GLTFModel, GLTFMesh, lod_level)
        self._load_xbg_textures(model)
        self._create_opengl_resources(model)
        model.loaded = True
        self.models_cache[xbg_path] = model
        return model

    def _load_xbg_textures(self, model):
        """Create GL textures + per-material render properties for a directly-
        loaded XBG model, sourcing from XBM materials + XBT textures.

        Mirrors _load_embedded_textures' GL upload exactly (same filters,
        GL_MODULATE brighten, mipmaps, OPAQUE→MASK auto-promotion) so directly
        loaded models look identical to the old cached-gltf path — the only
        difference is the pixel source (XBT decoded on the fly vs an embedded
        base64 PNG). Requires a current OpenGL context.
        """
        names = getattr(model, 'xbg_material_names', None)
        if not names:
            return
        if not PIL_AVAILABLE:
            print("  PIL not available - skipping XBG textures")
            return
        try:
            if not gl.glGetString(gl.GL_VERSION):
                print("  No OpenGL context - cannot load XBG textures")
                return
        except Exception:
            print("  OpenGL context not available - cannot load XBG textures")
            return

        tl = self.texture_loader
        if tl is None:
            try:
                from texture_loader import TextureLoader
                tl = TextureLoader(self.materials_directory)
                self.texture_loader = tl
            except Exception as e:
                print(f"  Could not create TextureLoader: {e}")
                return

        if not hasattr(model, 'textures_has_alpha'):
            model.textures_has_alpha = {}
        if not hasattr(model, 'texture_raw_data'):
            model.texture_raw_data = {}
        # Per-material data for the GLSL shader path (all 4 slots + params).
        # model.textures (diffuse only) + alpha_modes/etc. are still set below
        # for the fixed-function fallback renderer.
        model.mat_textures = {}   # mat_idx -> {'diffuse','normal','specular','emission'} GL ids (0 = none)
        model.mat_params = {}     # mat_idx -> {tint, emissive, spec_color, shininess, alpha_mode, alpha_cutoff}

        _AMODE = {'OPAQUE': 0, 'MASK': 1, 'BLEND': 2}

        def _upload(rel, is_normal, store_raw=False):
            """Decode an XBT and upload as a GL texture. Returns (tex_id, had_alpha); (0, False) on miss."""
            if not rel:
                return 0, False
            try:
                full = tl.resolve_xbt_full_path(rel, mat_name)
                if not full:
                    return 0, False
                res = tl.decode_xbt_to_rgba(full, is_normal_map=is_normal)
                if not res:
                    return 0, False
                w, h, data, had_alpha = res
                tid = glGenTextures(1)
                glBindTexture(GL_TEXTURE_2D, tid)
                glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, data)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
                glGenerateMipmap(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, 0)
                if store_raw:
                    model.texture_raw_data[mat_idx] = (w, h, data)
                return tid, had_alpha
            except Exception as e:
                print(f"  XBT upload failed ({rel}): {e}")
                return 0, False

        bound = 0
        for mat_idx, mat_name in enumerate(names):
            xbm = None
            try:
                xbm = tl.load_material(mat_name)
            except Exception as e:
                print(f"  XBM load failed for {mat_name}: {e}")

            # ── Per-material render properties (fixed-function fallback) ──
            if xbm is not None:
                dr, dg, db = (max(0.0, min(1.0, c)) for c in xbm.diffuse_color)
                model.base_color_factors[mat_idx] = [dr, dg, db, 1.0]
                if xbm.alpha_blend_enabled:
                    model.alpha_modes[mat_idx] = 'BLEND'
                elif xbm.alpha_test_enabled:
                    model.alpha_modes[mat_idx] = 'MASK'
                    model.alpha_cutoffs[mat_idx] = 0.5
                else:
                    model.alpha_modes[mat_idx] = 'OPAQUE'
                if xbm.illumination_color is not None:
                    er, eg, eb = xbm.illumination_color
                    mx = max(er, eg, eb, 1.0)
                    model.emissive_factors[mat_idx] = [er / mx, eg / mx, eb / mx]
                spec_color = [max(0.0, min(1.0, c)) for c in xbm.specular_color]
                shininess = max(1.0, min(128.0, float(xbm.specular_power)))
                two_sided = bool(xbm.two_sided)
                # Animated UVs (Unlit/FX scroll) — AnimType/USpeed/VSpeed live in
                # the raw param dict. The editor doesn't bake DiffuseTiling into
                # the UVs, so the scroll offset is just speed*time (no tiling
                # pre-mult, and no V-flip — mesh.py keeps game-space V).
                try:
                    _props = xbm.properties or {}
                    anim_type = int(_props.get('AnimType') or 0)
                    uspeed = float(_props.get('USpeed') or 0.0)
                    vspeed = float(_props.get('VSpeed') or 0.0)
                except Exception:
                    anim_type, uspeed, vspeed = 0, 0.0, 0.0
            else:
                model.base_color_factors[mat_idx] = [1.0, 1.0, 1.0, 1.0]
                model.alpha_modes.setdefault(mat_idx, 'OPAQUE')
                spec_color, shininess = [0.3, 0.3, 0.3], 32.0
                anim_type, uspeed, vspeed = 0, 0.0, 0.0
                two_sided = False

            # ── All four texture slots (diffuse/normal/specular/emission) ──
            d_id, d_alpha = _upload(xbm.textures.get('diffuse') if xbm else None, False, store_raw=True)
            n_id, _ = _upload(xbm.textures.get('normal') if xbm else None, True)
            s_id, _ = _upload(xbm.textures.get('specular') if xbm else None, False)
            e_id, _ = _upload(xbm.textures.get('emission') if xbm else None, False)
            model.mat_textures[mat_idx] = {'diffuse': d_id, 'normal': n_id,
                                           'specular': s_id, 'emission': e_id}
            if d_id:
                model.textures[mat_idx] = d_id            # fallback renderer binds diffuse
                model.textures_has_alpha[mat_idx] = d_alpha
                bound += 1

            emissive = model.emissive_factors.get(mat_idx, [0.0, 0.0, 0.0])
            if e_id and emissive == [0.0, 0.0, 0.0]:
                emissive = [1.0, 1.0, 1.0]   # emission texture but no illum colour → show it (mirror gltf path)
            if anim_type or uspeed or vspeed:
                self.has_animated_materials = True
            bc = model.base_color_factors[mat_idx]
            model.mat_params[mat_idx] = {
                'tint': [bc[0], bc[1], bc[2]],
                'emissive': emissive,
                'spec_color': spec_color,
                'shininess': shininess,
                'alpha_mode': _AMODE.get(model.alpha_modes.get(mat_idx, 'OPAQUE'), 0),
                'alpha_cutoff': float(model.alpha_cutoffs.get(mat_idx, 0.5)),
                'anim_type': anim_type,
                'uspeed': uspeed,
                'vspeed': vspeed,
                'two_sided': two_sided,
            }

        # Auto-promote OPAQUE→MASK when the diffuse carried a real alpha channel
        # (foliage/cloud/billboard textures) — mirror _load_embedded_textures.
        for mat_idx in range(len(names)):
            if (model.alpha_modes.get(mat_idx, 'OPAQUE') == 'OPAQUE'
                    and model.textures_has_alpha.get(mat_idx, False)):
                model.alpha_modes[mat_idx] = 'MASK'
                cut = 0.1 if model.alpha_cutoffs.get(mat_idx, 0.5) >= 0.5 else model.alpha_cutoffs[mat_idx]
                model.alpha_cutoffs[mat_idx] = cut
                if mat_idx in model.mat_params:
                    model.mat_params[mat_idx]['alpha_mode'] = 1
                    model.mat_params[mat_idx]['alpha_cutoff'] = cut

        print(f"  XBG direct: {bound}/{len(names)} materials textured (shader-ready)")

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

        # Direct-XBG path: parse the .xbg straight (no GLTF/.bin). load_static_xbg
        # handles geometry + XBM/XBT textures + display lists + caching.
        if gltf_path.lower().endswith('.xbg'):
            try:
                return self.load_static_xbg(gltf_path)
            except Exception as e:
                print(f"❌ Failed to direct-load XBG {os.path.basename(gltf_path)}: {e}")
                import traceback
                traceback.print_exc()
                return None

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

    def _get_entity_rs(self, entity):
        """Rotation (rx, ry, rz) + scale for an entity, parsed from XML once and
        cached in _entity_rs_cache (mark_entity_modified pops the cache entry).
        Shared by prepare_batches (classic path) and the GDR row tables."""
        eid = id(entity)
        cached = self._entity_rs_cache.get(eid)
        if cached is not None:
            return cached
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
        rs = (rotation_x, rotation_y, rotation_z, scale)
        self._entity_rs_cache[eid] = rs
        return rs

    def prepare_batches(self, entities, selected_entities):
        """Prepare instance batches for all entities - call once per frame before rendering

        OPTIMIZATION: For 10K+ entities, this tracks entity count and logs performance stats
        """
        self.instance_batches.clear()
        self._gdr_frame = None   # classic path active — drop any stale array frame
        if self.loading_suspended:
            return   # level load in progress — mid-load paints draw no models

        # Selection lookup as an id-set (was `entity in selected_entities` on a
        # LIST → O(N×S) per frame; this makes it O(1) per entity).
        selected_ids = {id(e) for e in selected_entities}

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
            rotation_x, rotation_y, rotation_z, scale = self._get_entity_rs(entity)

            is_selected = id(entity) in selected_ids

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

    # ──────────────── Array-native instance pipeline (GPU-driven mode) ────────────────

    def _ensure_gdr_rows(self, canvas):
        """(Re)build the static row tables aligned to canvas._valid_entities_3d.

        One row per (entity, model) pair — kit parts contribute extra rows at the
        same transform, mirroring prepare_batches exactly. Rebuilt only when the
        canvas position arrays rebuild (level load, model-count change, entity
        move invalidation) — keyed on canvas._pos_arrays_version. Returns True
        when rows are usable."""
        version = getattr(canvas, '_pos_arrays_version', None)
        if version is None:
            return False
        valid = getattr(canvas, '_valid_entities_3d', None)
        if not valid:
            return False
        if self._gdr_rows_version == version and self._gdr_row_ent is not None:
            return True

        paths = []
        slot_of = {}
        row_ent, row_slot, row_rot, row_scale = [], [], [], []
        row_map = {}
        modelled = set()
        mc = self.models_cache
        for i, e in enumerate(valid):
            mf = getattr(e, 'model_file', None)
            kits = getattr(e, 'kit_model_files', []) or []
            if not mf and not kits:
                continue
            if not all(hasattr(e, a) for a in ('x', 'y', 'z')):
                continue
            rx, ry, rz, sc = self._get_entity_rs(e)
            first_row = len(row_ent)
            mpaths = ([mf] if mf else []) + [kg for kg, _kb in kits]
            for p in mpaths:
                s = slot_of.get(p)
                if s is None:
                    s = len(paths)
                    slot_of[p] = s
                    paths.append(p)
                row_ent.append(i)
                row_slot.append(s)
                row_rot.append((rx, ry, rz))
                row_scale.append(sc)
            row_map[id(e)] = list(range(first_row, len(row_ent)))
            for p in mpaths:
                m = mc.get(p)
                if m is not None and getattr(m, 'loaded', False):
                    modelled.add(id(e))
                    break

        if not row_ent:
            return False
        self._gdr_row_ent = np.asarray(row_ent, np.int32)
        self._gdr_row_slot = np.asarray(row_slot, np.int32)
        self._gdr_row_rot = np.asarray(row_rot, np.float32).reshape(-1, 3)
        self._gdr_row_scale = np.asarray(row_scale, np.float32)
        self._gdr_row_map = row_map
        self._gdr_modelled_ids = modelled
        if paths != self._gdr_model_paths:
            # Slot CONTENT changed → the GDR's command templates must rebuild.
            # (Per-drag-frame array rebuilds keep the same paths/order, so this
            # stays stable during drags and templates are NOT rebuilt per frame.)
            self._gdr_model_paths = paths
            self._gdr_slots_version += 1
        # Fresh overlay rows — all zeros. The blue selection tint is disabled
        # (selection shows via the pulsing yellow glow pass only), so there is
        # nothing to re-apply after a rebuild; _gdr_sel_ids is kept for the
        # change-detection in _gdr_update_overlay.
        self._gdr_overlay = np.zeros(len(row_ent), np.float32)
        self._gdr_rows_version = version
        return True

    def _gdr_update_overlay(self, selected_entities):
        """Update the per-row selection overlay only when the selection changed.

        Selection is indicated by the pulsing yellow glow pass ONLY (June 2026,
        user request) — the blue shader tint is disabled, so selected rows also
        get 0.0. The plumbing is kept (and still clears stale values) in case a
        tint is ever wanted again; to re-enable, change the second 0.0 below."""
        sel_ids = frozenset(id(e) for e in selected_entities) if selected_entities else frozenset()
        if sel_ids == self._gdr_sel_ids:
            return
        row_map = self._gdr_row_map
        ov = self._gdr_overlay
        for eid in self._gdr_sel_ids - sel_ids:
            for r in row_map.get(eid, ()):
                ov[r] = 0.0
        for eid in sel_ids - self._gdr_sel_ids:
            for r in row_map.get(eid, ()):
                ov[r] = 0.0   # was 0.35 — blue tint removed, yellow pulse only
        self._gdr_sel_ids = sel_ids

    def gdr_refresh_entity(self, entity):
        """Refresh one entity's rotation/scale rows after mark_entity_modified
        (rotation/scale edits don't bump the canvas position-array version, so
        rows would otherwise go stale). Call AFTER _entity_rs_cache is popped."""
        if self._gdr_row_ent is None:
            return
        rows = self._gdr_row_map.get(id(entity))
        if not rows:
            return
        rx, ry, rz, sc = self._get_entity_rs(entity)
        for r in rows:
            self._gdr_row_rot[r] = (rx, ry, rz)
            self._gdr_row_scale[r] = sc

    def prepare_gpu_frame(self, canvas, entities_sorted):
        """Array-native replacement for prepare_batches when the GPU-driven path
        is active. Pure numpy from the cull's index array to the instance SSBO
        contents — no per-entity Python loop on the hot path.

        Returns True when a frame was staged in self._gdr_frame (the canvas then
        SKIPS prepare_batches); False → caller must run prepare_batches as usual.
        Interior-exempt anchors are already inside the cull's index array via the
        inside-sphere bypass; never-cull markers have no models — neither needs
        special handling here."""
        self._gdr_frame = None
        if self.loading_suspended:
            return True   # claim the frame so prepare_batches is skipped too
        if not self.force_render_tier or self._gpu_driven is False:
            return False
        # GDR exists but permanently failed → stop staging frames (the classic
        # prepare_batches + universal path is the steady state from here on).
        if self._gpu_driven is not None and getattr(self._gpu_driven, '_failed', False):
            return False
        try:
            if not self._ensure_gdr_rows(canvas):
                return False
            vis_idx = getattr(canvas, '_visible_idx_3d', None)
            pos = getattr(canvas, '_positions_3d', None)
            valid = canvas._valid_entities_3d
            if vis_idx is None or pos is None or len(pos) != len(valid):
                return False
            self._gdr_update_overlay(getattr(canvas, 'selected', None) or [])

            from gpu_driven_renderer import assemble_frame
            ent_vis = np.zeros(len(valid), bool)
            ent_vis[vis_idx] = True

            # Contribution cull: drop entities whose bounding sphere projects
            # under gdr_min_pixel_size px. projected_px ≈ (2r/d)·k with
            # k = (screen_h/2)/tan(vfov/2); compared squared (no sqrt):
            # keep ⇔ r² ≥ d²·(min_px/2k)². Markers (radius 0) are unaffected —
            # they have no model rows. VFOV 50 matches the renderer/cull.
            min_px = float(getattr(self, 'gdr_min_pixel_size', 0.0) or 0.0)
            if min_px > 0.0:
                radii = getattr(canvas, '_radii_3d', None)
                cam = getattr(getattr(canvas, 'camera_3d', None), 'position', None)
                scr_h = float(canvas.height() or 0)
                if radii is not None and len(radii) == len(valid) and cam is not None and scr_h > 0:
                    import math as _m
                    k = (scr_h * 0.5) / _m.tan(_m.radians(25.0))
                    dpts = pos - np.asarray(cam, np.float32)
                    d2 = np.einsum('ij,ij->i', dpts, dpts)
                    lim = min_px / (2.0 * k)
                    ent_vis &= (radii * radii >= d2 * (lim * lim)) | (radii <= 0.0)

            inst, counts, offsets = assemble_frame(
                self._gdr_row_ent, self._gdr_row_slot, self._gdr_row_rot,
                self._gdr_row_scale, self._gdr_overlay,
                pos, ent_vis, len(self._gdr_model_paths))
            self._gdr_frame = {'inst': inst, 'counts': counts, 'offsets': offsets}
            # If the GDR fails mid-frame we must rebuild instance_batches for the
            # universal fallback (we skipped prepare_batches this frame).
            self._gdr_fallback_args = (entities_sorted, getattr(canvas, 'selected', None) or [])
            return True
        except Exception as _e:
            if not getattr(self, '_gdr_prep_error_logged', False):
                self._gdr_prep_error_logged = True
                import traceback
                print(f"[gpu-driven] prepare_gpu_frame failed -> classic path: {_e}")
                traceback.print_exc()
            self._gdr_frame = None
            return False

    def set_shadow_inputs(self, shadow_tex, light_vp, on):
        """Canvas sets the sun shadow map + light matrix each frame; the
        GPU-driven model shader samples them when `on`."""
        self._shadow_tex = int(shadow_tex) if shadow_tex else 0
        self._shadow_light_vp = light_vp
        self._shadows_on = bool(on)

    def cast_shadows(self, light_vp):
        """Render model depth into the currently-bound shadow FBO (GPU-driven
        path only). Caller binds the FBO via ShadowMap.begin() first. Returns
        True if it cast anything."""
        if self.loading_suspended:
            return False   # never touch the GDR build mid-level-load
        if self.force_render_tier and self._gpu_driven:
            try:
                return self._gpu_driven.cast(light_vp)
            except Exception as _e:
                print(f"[gpu-driven] cast_shadows failed: {_e}")
        return False

    def render_batched_models(self):
        """Render all models. Uses the GLSL material shader (per-pixel diffuse +
        normal map + spec + emission, lit by the studio rig) when it compiles;
        falls back to the fixed-function display-list path on ANY shader problem,
        so the 3D view can never go blank."""
        if self.loading_suspended:
            # Level load in progress: skip ALL model rendering (GDR rebuilds on a
            # churning models_cache from mid-load repaints froze the GUI thread).
            self.gdr_drew_last = False
            return 0
        if not self.instance_batches and self._gdr_frame is None:
            self.gdr_drew_last = False
            return 0
        if not getattr(self, '_render_diag_done', False):
            self._render_diag_done = True
            try:
                self._print_render_diagnostic()
            except Exception as _e:
                print(f"[render-diag] failed: {_e}")

        # GPU-driven fast path (F2/F3): one glMultiDrawElementsIndirect for all
        # models. Falls through to the universal path if unavailable or it errors.
        self.gdr_drew_last = False
        if self.force_render_tier:
            if self._gpu_driven is None:
                try:
                    from gpu_driven_renderer import GPUDrivenRenderer
                    self._gpu_driven = GPUDrivenRenderer(self)
                except Exception as _e:
                    print(f"[gpu-driven] init failed -> fallback: {_e}")
                    self._gpu_driven = False
            if self._gpu_driven:
                anim_t = time.monotonic() - self._anim_t0
                had_array_frame = self._gdr_frame is not None
                drew = self._gpu_driven.render(anim_t, self._shadow_tex,
                                               self._shadow_light_vp, self._shadows_on)
                self._gdr_frame = None   # consumed (or invalid) — never reuse next frame
                if drew:
                    self.gdr_drew_last = True
                    return 0   # drew via MDI
                if had_array_frame and self._gdr_fallback_args is not None:
                    # We skipped prepare_batches this frame (array mode) but the
                    # GDR failed — rebuild instance_batches so the universal path
                    # below has something to draw. One-time cost on failure only.
                    ents, sel = self._gdr_fallback_args
                    self.prepare_batches(ents, sel)
            elif self._gdr_frame is not None:
                # Renderer import failed but an array frame was staged: the
                # universal path needs instance_batches.
                self._gdr_frame = None
                if self._gdr_fallback_args is not None:
                    ents, sel = self._gdr_fallback_args
                    self.prepare_batches(ents, sel)

        if self._ensure_shader():
            try:
                # Clear any pre-existing GL error so our post-render probe is clean.
                # (With OpenGL.ERROR_CHECKING off, per-call checks are gone — we do
                # ONE glGetError per frame instead of ~tens-of-thousands.)
                if not self._gl_checks_on:
                    glGetError()
                result = self._render_batched_models_shader()
                if not self._gl_checks_on and not self._shader_gl_error_logged:
                    err = glGetError()
                    if err != 0:
                        # A real GL error slipped through with per-call checks off.
                        # Log ONCE (don't spam / don't flap to fallback mid-fly).
                        self._shader_gl_error_logged = True
                        print(f"[model_shader] GL error 0x{err:04x} during shader "
                              f"render (per-call checks are OFF; set OPENGL_DEBUG=1 "
                              f"to make it raise + fall back). Investigate.")
                return result
            except Exception as _e:
                print(f"[model_shader] runtime error -> fixed-function fallback: {_e}")
                import traceback
                traceback.print_exc()
                try:
                    glUseProgram(0)
                except Exception:
                    pass
                self._model_shader_disabled = True   # stop retrying a broken path
        return self._render_batched_models_fixed()

    def _print_render_diagnostic(self):
        """One-shot ground-truth dump (first rendered frame): which render path is
        live and whether textures actually loaded. Printed as one copy-pasteable
        block so we don't have to guess from a screenshot."""
        try:
            import OpenGL
            checks = getattr(OpenGL, 'ERROR_CHECKING', True)
        except Exception:
            checks = '?'
        ms = self._model_shader
        ms_state = ('disabled->FIXED-FUNCTION' if self._model_shader_disabled
                    else 'compiled+ACTIVE' if (ms and getattr(ms, 'program', None))
                    else 'not yet compiled')
        ds = self._depth_shader
        ds_state = ('disabled' if self._depth_shader_disabled
                    else 'compiled' if (ds and getattr(ds, 'program', None))
                    else 'not yet compiled')

        # Texture coverage across loaded models.
        n_models = 0; n_with_diffuse = 0; n_diffuse_total = 0; n_mats = 0
        sample = None
        for path, m in self.models_cache.items():
            if not getattr(m, 'loaded', False):
                continue
            n_models += 1
            mt = getattr(m, 'mat_textures', None) or {}
            names = getattr(m, 'xbg_material_names', None) or []
            n_mats += len(names)
            has_diff = False
            for mi, slots in mt.items():
                if slots.get('diffuse'):
                    n_diffuse_total += 1
                    has_diff = True
            if has_diff:
                n_with_diffuse += 1
            elif sample is None and names:
                # First textureless model — capture detail for diagnosis.
                sample = (os.path.basename(path), names[0] if names else '?',
                          {k: v for k, v in (mt.get(0, {}) or {}).items()})

        print("=" * 64)
        print("=== RENDER DIAGNOSTIC (one-shot) ===")
        print(f"  PyOpenGL ERROR_CHECKING = {checks}   (False = fast path active)")
        print(f"  material shader : {ms_state}")
        print(f"  depth prepass   : {ds_state}")
        print(f"  PIL available   : {PIL_AVAILABLE}")
        print(f"  materials_dir   : {self.materials_directory}")
        print(f"  models loaded   : {n_models}")
        print(f"  models w/ diffuse texture : {n_with_diffuse}/{n_models}")
        print(f"  total diffuse textures    : {n_diffuse_total}  (materials: {n_mats})")
        if n_with_diffuse == 0:
            print("  >>> NO diffuse textures loaded on ANY model — this is why models are grey.")
            if sample:
                print(f"      e.g. {sample[0]}: mat0='{sample[1]}' slots={sample[2]}")
        print("=" * 64)

    def _ensure_shader(self):
        """Lazily compile the GLSL material program (once). False -> use fixed-function."""
        if self._model_shader_disabled:
            return False
        if self._model_shader is None:
            try:
                from model_shader import ModelShader
                self._model_shader = ModelShader()
            except Exception as _e:
                print(f"[model_shader] import failed: {_e}")
                self._model_shader_disabled = True
                return False
        try:
            return self._model_shader.compile()
        except Exception as _e:
            print(f"[model_shader] compile crashed: {_e}")
            self._model_shader_disabled = True
            return False

    def _ensure_depth_shader(self):
        """Lazily compile the depth-prepass program. Returns the DepthShader or
        None — None just means "skip the prepass" (not fatal; the color pass still
        renders, only without early-Z overdraw savings)."""
        if self._depth_shader_disabled:
            return None
        if self._depth_shader is None:
            try:
                from model_shader import DepthShader
                self._depth_shader = DepthShader()
            except Exception as _e:
                print(f"[model_shader] depth import failed: {_e}")
                self._depth_shader_disabled = True
                return None
        try:
            return self._depth_shader if self._depth_shader.compile() else None
        except Exception as _e:
            print(f"[model_shader] depth compile crashed: {_e}")
            self._depth_shader_disabled = True
            return None

    def _ensure_mesh_vbo(self, mesh):
        """Upload a mesh's geometry to GPU buffers ONCE (pos/nrm/uv/tan + index).
        Returns the vbo dict, or False if it can't be built. This is the key perf
        fix: without it, the shader path re-transferred every mesh's vertex arrays
        from CPU to the driver on every draw of every frame."""
        vbo = getattr(mesh, '_vbo', None)
        if vbo is not None:
            return vbo
        if mesh.vertices is None or mesh.indices is None:
            mesh._vbo = False
            return False
        try:
            def _buf(target, arr, dtype):
                a = np.ascontiguousarray(arr, dtype=dtype)
                b = glGenBuffers(1)
                glBindBuffer(target, b)
                glBufferData(target, a.nbytes, a, GL_STATIC_DRAW)
                return int(b)
            pos = _buf(GL_ARRAY_BUFFER, mesh.vertices, np.float32)
            nrm = _buf(GL_ARRAY_BUFFER, mesh.normals, np.float32) if mesh.normals is not None else 0
            uv  = _buf(GL_ARRAY_BUFFER, mesh.uvs, np.float32) if mesh.uvs is not None else 0
            tan = _buf(GL_ARRAY_BUFFER, mesh.tangents, np.float32) if mesh.tangents is not None else 0
            idx = np.ascontiguousarray(mesh.indices, dtype=np.uint32)
            ibo = glGenBuffers(1)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ibo)
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx, GL_STATIC_DRAW)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0)
            vao = self._build_mesh_vao(pos, nrm, uv, tan, ibo)
            mesh._vbo = {'pos': pos, 'nrm': nrm, 'uv': uv, 'tan': tan,
                         'ibo': int(ibo), 'count': int(len(idx)), 'vao': int(vao)}
            return mesh._vbo
        except Exception as e:
            print(f"[model_shader] VBO build failed: {e}")
            mesh._vbo = False
            return False

    def _build_mesh_vao(self, pos, nrm, uv, tan, ibo):
        """Bake this mesh's whole attribute layout into a VAO: per-vertex attribs
        0-3 (from the mesh VBOs) + per-instance attribs 4-7 (from the shared
        instance VBO, divisor 1). A draw then needs only glBindVertexArray +
        glDrawElementsInstanced. Returns the VAO id, or 0 (caller uses the manual
        per-draw attrib path). VAOs orphan-safe: re-glBufferData'ing the instance
        VBO each frame is still seen by the VAO (it references the buffer by name)."""
        if not self._vao_enabled or self._vao_supported is False:
            return 0
        from model_shader import (ATTR_POSITION, ATTR_NORMAL, ATTR_UV, ATTR_TANGENT,
                                   ATTR_INST_POS, ATTR_INST_ROT, ATTR_INST_SCALE,
                                   ATTR_INST_OVERLAY, INSTANCE_STRIDE)
        try:
            if self._instance_vbo is None:
                self._instance_vbo = int(glGenBuffers(1))   # must exist; VAO captures it
            vao = int(glGenVertexArrays(1))
            glBindVertexArray(vao)
            _z = ctypes.c_void_p(0)
            glBindBuffer(GL_ARRAY_BUFFER, pos)
            glEnableVertexAttribArray(ATTR_POSITION)
            glVertexAttribPointer(ATTR_POSITION, 3, GL_FLOAT, GL_FALSE, 0, _z)
            if nrm:
                glBindBuffer(GL_ARRAY_BUFFER, nrm)
                glEnableVertexAttribArray(ATTR_NORMAL)
                glVertexAttribPointer(ATTR_NORMAL, 3, GL_FLOAT, GL_FALSE, 0, _z)
            if uv:
                glBindBuffer(GL_ARRAY_BUFFER, uv)
                glEnableVertexAttribArray(ATTR_UV)
                glVertexAttribPointer(ATTR_UV, 2, GL_FLOAT, GL_FALSE, 0, _z)
            if tan:
                glBindBuffer(GL_ARRAY_BUFFER, tan)
                glEnableVertexAttribArray(ATTR_TANGENT)
                glVertexAttribPointer(ATTR_TANGENT, 3, GL_FLOAT, GL_FALSE, 0, _z)
            st = INSTANCE_STRIDE
            glBindBuffer(GL_ARRAY_BUFFER, self._instance_vbo)
            glEnableVertexAttribArray(ATTR_INST_POS)
            glVertexAttribPointer(ATTR_INST_POS, 3, GL_FLOAT, GL_FALSE, st, ctypes.c_void_p(0))
            glVertexAttribDivisor(ATTR_INST_POS, 1)
            glEnableVertexAttribArray(ATTR_INST_ROT)
            glVertexAttribPointer(ATTR_INST_ROT, 3, GL_FLOAT, GL_FALSE, st, ctypes.c_void_p(12))
            glVertexAttribDivisor(ATTR_INST_ROT, 1)
            glEnableVertexAttribArray(ATTR_INST_SCALE)
            glVertexAttribPointer(ATTR_INST_SCALE, 1, GL_FLOAT, GL_FALSE, st, ctypes.c_void_p(24))
            glVertexAttribDivisor(ATTR_INST_SCALE, 1)
            glEnableVertexAttribArray(ATTR_INST_OVERLAY)
            glVertexAttribPointer(ATTR_INST_OVERLAY, 1, GL_FLOAT, GL_FALSE, st, ctypes.c_void_p(28))
            glVertexAttribDivisor(ATTR_INST_OVERLAY, 1)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ibo)
            glBindVertexArray(0)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            if self._vao_supported is None:
                self._vao_supported = True
                print("[model_shader] VAO instancing active")
            return vao
        except Exception as e:
            if self._vao_supported is None:
                self._vao_supported = False
                print(f"[model_shader] VAOs unavailable ({e}) — using per-draw attribs")
            try:
                glBindVertexArray(0)
            except Exception:
                pass
            return 0

    def _vao_active(self):
        return bool(self._vao_enabled and self._vao_supported)

    def _setup_instance_attribs(self, instances):
        """Upload this frame's instance data (pos3, rot3, scale, overlay) for ONE
        model to the shared instance VBO and bind it to attribs 4-7 with divisor 1,
        so a single glDrawElementsInstanced draws every copy. Returns the count."""
        from model_shader import (ATTR_INST_POS, ATTR_INST_ROT, ATTR_INST_SCALE,
                                   ATTR_INST_OVERLAY, INSTANCE_STRIDE)
        n = len(instances)
        if n == 0:
            return 0
        # (px,py,pz, rx,ry,rz, scale, overlay) per instance — one np.array build.
        # Overlay fixed at 0.0: the blue selection tint is disabled (selection
        # shows via the pulsing yellow glow pass only — June 2026 user request).
        arr = np.array(
            [(i[1], i[2], i[3], i[4], i[5], i[6], i[7], 0.0)
             for i in instances], dtype=np.float32)
        if self._instance_vbo is None:
            self._instance_vbo = int(glGenBuffers(1))
        glBindBuffer(GL_ARRAY_BUFFER, self._instance_vbo)
        glBufferData(GL_ARRAY_BUFFER, arr.nbytes, arr, GL_DYNAMIC_DRAW)  # orphan+reupload
        # When VAOs are active each mesh's VAO already binds attribs 4-7 to this
        # same buffer — uploading the data is all that's needed. Only bind the
        # attribs manually on the fallback (no-VAO) path.
        if not self._vao_active():
            st = INSTANCE_STRIDE
            glEnableVertexAttribArray(ATTR_INST_POS)
            glVertexAttribPointer(ATTR_INST_POS, 3, GL_FLOAT, GL_FALSE, st, ctypes.c_void_p(0))
            glVertexAttribDivisor(ATTR_INST_POS, 1)
            glEnableVertexAttribArray(ATTR_INST_ROT)
            glVertexAttribPointer(ATTR_INST_ROT, 3, GL_FLOAT, GL_FALSE, st, ctypes.c_void_p(12))
            glVertexAttribDivisor(ATTR_INST_ROT, 1)
            glEnableVertexAttribArray(ATTR_INST_SCALE)
            glVertexAttribPointer(ATTR_INST_SCALE, 1, GL_FLOAT, GL_FALSE, st, ctypes.c_void_p(24))
            glVertexAttribDivisor(ATTR_INST_SCALE, 1)
            glEnableVertexAttribArray(ATTR_INST_OVERLAY)
            glVertexAttribPointer(ATTR_INST_OVERLAY, 1, GL_FLOAT, GL_FALSE, st, ctypes.c_void_p(28))
            glVertexAttribDivisor(ATTR_INST_OVERLAY, 1)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        return n

    def _disable_instance_attribs(self):
        """Unbind the per-instance attribs and clear their divisors so instance
        data can't leak into other draws or the fixed-function path."""
        from model_shader import (ATTR_INST_POS, ATTR_INST_ROT, ATTR_INST_SCALE,
                                   ATTR_INST_OVERLAY)
        for loc in (ATTR_INST_POS, ATTR_INST_ROT, ATTR_INST_SCALE, ATTR_INST_OVERLAY):
            glVertexAttribDivisor(loc, 0)
            glDisableVertexAttribArray(loc)

    def _draw_mesh_instanced(self, model, mesh, sh, anim_t, n_instances):
        """Bind one mesh's material + geometry VBO and draw ALL n_instances copies
        in a SINGLE glDrawElementsInstanced call. The per-instance transform and
        selection overlay come from attribs 4-7 (bound by _setup_instance_attribs);
        the shader replicates the legacy glRotatef order exactly."""
        from model_shader import ATTR_POSITION, ATTR_NORMAL, ATTR_UV, ATTR_TANGENT
        vbo = self._ensure_mesh_vbo(mesh)
        if not vbo:
            return
        mi = mesh.material_index
        p = (getattr(model, 'mat_params', None) or {}).get(mi)
        if p is None:
            p = {'tint': [1.0, 1.0, 1.0], 'emissive': [0.0, 0.0, 0.0],
                 'spec_color': [0.3, 0.3, 0.3], 'shininess': 32.0,
                 'alpha_mode': 0, 'alpha_cutoff': 0.5}
        texs = (getattr(model, 'mat_textures', None) or {}).get(mi, {})

        if p.get('two_sided'):
            glDisable(GL_CULL_FACE)
        else:
            glEnable(GL_CULL_FACE)

        tn = p['tint']; glUniform3f(sh.u('u_tint'), tn[0], tn[1], tn[2])
        em = p['emissive']; glUniform3f(sh.u('u_emissive'), em[0], em[1], em[2])
        sc = p['spec_color']; glUniform3f(sh.u('u_spec_color'), sc[0], sc[1], sc[2])
        glUniform1f(sh.u('u_shininess'), p['shininess'])
        glUniform1i(sh.u('u_alpha_mode'), p['alpha_mode'])
        glUniform1f(sh.u('u_alpha_cutoff'), p['alpha_cutoff'])

        anim = p.get('anim_type', 0); us = p.get('uspeed', 0.0); vs = p.get('vspeed', 0.0)
        if anim == 3:
            glUniform2f(sh.u('u_uv_offset'), float(np.cos(anim_t) * us), float(np.sin(anim_t) * vs))
        elif anim or us or vs:
            glUniform2f(sh.u('u_uv_offset'), us * anim_t, vs * anim_t)
        else:
            glUniform2f(sh.u('u_uv_offset'), 0.0, 0.0)

        d = texs.get('diffuse', 0); n = texs.get('normal', 0)
        s = texs.get('specular', 0); e = texs.get('emission', 0)
        has_n = 0 if self.dbg_no_normal else (1 if (n and vbo['nrm'] and vbo['tan']) else 0)
        has_s = 0 if self.dbg_no_spec else (1 if s else 0)
        has_e = 0 if self.dbg_no_emission else (1 if e else 0)
        glUniform1i(sh.u('u_has_diffuse'), 1 if d else 0)
        glUniform1i(sh.u('u_has_normal'), has_n)
        glUniform1i(sh.u('u_has_specular'), has_s)
        glUniform1i(sh.u('u_has_emission'), has_e)
        glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, d or 0)
        glActiveTexture(GL_TEXTURE1); glBindTexture(GL_TEXTURE_2D, n or 0)
        glActiveTexture(GL_TEXTURE2); glBindTexture(GL_TEXTURE_2D, s or 0)
        glActiveTexture(GL_TEXTURE3); glBindTexture(GL_TEXTURE_2D, e or 0)
        glActiveTexture(GL_TEXTURE0)

        _z = ctypes.c_void_p(0)
        if vbo.get('vao'):
            # Fast path: one bind restores all attribs (0-3 mesh + 4-7 instance).
            glBindVertexArray(vbo['vao'])
            glDrawElementsInstanced(GL_TRIANGLES, vbo['count'], GL_UNSIGNED_INT, _z, n_instances)
            # left bound; the pass-end cleanup unbinds the VAO.
            return

        # Fallback: bind this mesh's geometry attribs (0-3) by hand. Optional
        # attribs are disabled when absent so a previous mesh's buffer can't bleed in.
        glBindBuffer(GL_ARRAY_BUFFER, vbo['pos'])
        glEnableVertexAttribArray(ATTR_POSITION)
        glVertexAttribPointer(ATTR_POSITION, 3, GL_FLOAT, GL_FALSE, 0, _z)
        if vbo['nrm']:
            glBindBuffer(GL_ARRAY_BUFFER, vbo['nrm'])
            glEnableVertexAttribArray(ATTR_NORMAL)
            glVertexAttribPointer(ATTR_NORMAL, 3, GL_FLOAT, GL_FALSE, 0, _z)
        else:
            glDisableVertexAttribArray(ATTR_NORMAL)
        if vbo['uv']:
            glBindBuffer(GL_ARRAY_BUFFER, vbo['uv'])
            glEnableVertexAttribArray(ATTR_UV)
            glVertexAttribPointer(ATTR_UV, 2, GL_FLOAT, GL_FALSE, 0, _z)
        else:
            glDisableVertexAttribArray(ATTR_UV)
        if vbo['tan']:
            glBindBuffer(GL_ARRAY_BUFFER, vbo['tan'])
            glEnableVertexAttribArray(ATTR_TANGENT)
            glVertexAttribPointer(ATTR_TANGENT, 3, GL_FLOAT, GL_FALSE, 0, _z)
        else:
            glDisableVertexAttribArray(ATTR_TANGENT)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, vbo['ibo'])

        # ONE draw for every copy of this mesh. Transform + overlay per instance
        # come from attribs 4-7 (divisor 1); the shader builds the world transform.
        glDrawElementsInstanced(GL_TRIANGLES, vbo['count'], GL_UNSIGNED_INT, _z, n_instances)

        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0)

    def _draw_mesh_depth(self, model, mesh, dsh, anim_t, n_instances):
        """Depth-prepass draw for ONE mesh (all instances) — writes ONLY depth
        (color is masked off by the caller). Replicates the color pass's per-
        material backface cull + alpha-mask discard + animated-UV offset so the
        depth silhouette is identical to what the color pass will shade; that's
        what lets the color pass early-Z with GL_LEQUAL against this depth."""
        from model_shader import ATTR_POSITION, ATTR_NORMAL, ATTR_UV, ATTR_TANGENT
        vbo = self._ensure_mesh_vbo(mesh)
        if not vbo:
            return
        mi = mesh.material_index
        p = (getattr(model, 'mat_params', None) or {}).get(mi) or {}
        alpha_mode = p.get('alpha_mode', 0)

        if p.get('two_sided'):
            glDisable(GL_CULL_FACE)
        else:
            glEnable(GL_CULL_FACE)

        # Animated UV only shifts the cutout for masked materials — opaque depth
        # is offset-independent, so skip the uniform churn there.
        if alpha_mode == 1:
            anim = p.get('anim_type', 0); us = p.get('uspeed', 0.0); vs = p.get('vspeed', 0.0)
            if anim == 3:
                glUniform2f(dsh.u('u_uv_offset'), float(np.cos(anim_t) * us), float(np.sin(anim_t) * vs))
            elif anim or us or vs:
                glUniform2f(dsh.u('u_uv_offset'), us * anim_t, vs * anim_t)
            else:
                glUniform2f(dsh.u('u_uv_offset'), 0.0, 0.0)
        glUniform1i(dsh.u('u_alpha_mode'), alpha_mode)
        glUniform1f(dsh.u('u_alpha_cutoff'), p.get('alpha_cutoff', 0.5))

        _z = ctypes.c_void_p(0)
        # Masked materials need the diffuse texture bound for the discard (the VAO
        # already provides the UV attrib); opaque needs neither.
        if alpha_mode == 1:
            texs = (getattr(model, 'mat_textures', None) or {}).get(mi, {})
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, texs.get('diffuse', 0) or 0)

        if vbo.get('vao'):
            glBindVertexArray(vbo['vao'])
            glDrawElementsInstanced(GL_TRIANGLES, vbo['count'], GL_UNSIGNED_INT, _z, n_instances)
            return

        glBindBuffer(GL_ARRAY_BUFFER, vbo['pos'])
        glEnableVertexAttribArray(ATTR_POSITION)
        glVertexAttribPointer(ATTR_POSITION, 3, GL_FLOAT, GL_FALSE, 0, _z)
        if alpha_mode == 1 and vbo['uv']:
            glBindBuffer(GL_ARRAY_BUFFER, vbo['uv'])
            glEnableVertexAttribArray(ATTR_UV)
            glVertexAttribPointer(ATTR_UV, 2, GL_FLOAT, GL_FALSE, 0, _z)
        else:
            glDisableVertexAttribArray(ATTR_UV)
        # Normal/tangent aren't declared by the depth program.
        glDisableVertexAttribArray(ATTR_NORMAL)
        glDisableVertexAttribArray(ATTR_TANGENT)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, vbo['ibo'])

        glDrawElementsInstanced(GL_TRIANGLES, vbo['count'], GL_UNSIGNED_INT, _z, n_instances)

        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0)

    def _render_batched_models_shader(self):
        """GLSL + hardware-instancing render path with a DEPTH PREPASS for early-Z
        occlusion. Three passes:

          0. Depth prepass (non-blend meshes): writes ONLY depth, color masked off,
             cheap position-only shader. Lays down the nearest-surface depth.
          1. Color pass (non-blend meshes): full material shader, depth writes OFF,
             GL_LEQUAL — so a fragment shades ONLY if it's the front-most (visible)
             one at that pixel. Occluded fragments fail early-Z BEFORE the expensive
             4-texture / normal-map / 3-light shader runs. This is the "only render
             the pixels we can see" win.
          2. Blend pass: transparent meshes, back-to-front-ish, no depth writes.

        If the depth program isn't available the color pass falls back to a plain
        GL_LESS depth-write pass (correct, just without the overdraw savings)."""
        from model_shader import ATTR_POSITION, ATTR_NORMAL, ATTR_UV, ATTR_TANGENT
        sh = self._model_shader
        anim_t = time.monotonic() - self._anim_t0   # elapsed seconds for UV scroll

        # XBG winding is CW → front faces are CW. Shared by all passes; two-sided
        # materials toggle GL_CULL_FACE per-mesh inside the draw helpers.
        glFrontFace(GL_CW)
        glCullFace(GL_BACK)
        glEnable(GL_CULL_FACE)
        glEnable(GL_DEPTH_TEST)

        # Categorise meshes ONCE per frame (was re-filtered per pass before).
        renderlist = []   # (model, instances, nonblend_meshes, blend_meshes)
        for model_path, instances in self.instance_batches.items():
            if not instances:
                continue
            model = self.models_cache.get(model_path)
            if not model or not model.loaded or not model.meshes:
                continue
            amodes = model.alpha_modes
            nonblend = []; blend = []
            for m in model.meshes:
                if m.vertices is None:
                    continue
                (blend if amodes.get(m.material_index, 'OPAQUE') == 'BLEND'
                 else nonblend).append(m)
            if nonblend or blend:
                renderlist.append((model, instances, nonblend, blend))

        rendered = 0

        # ── Pass 0: DEPTH PREPASS (non-blend) ── (only when enabled; see __init__)
        dsh = self._ensure_depth_shader() if self._depth_prepass_enabled else None
        if dsh is not None:
            glUseProgram(dsh.program)
            glUniform1i(dsh.u('u_diffuse'), 0)
            glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE)
            glDepthMask(GL_TRUE)
            glDepthFunc(GL_LESS)
            for model, instances, nonblend, _blend in renderlist:
                if not nonblend:
                    continue
                n = self._setup_instance_attribs(instances)
                if n == 0:
                    continue
                for mesh in nonblend:
                    self._draw_mesh_depth(model, mesh, dsh, anim_t, n)
            glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)

        # ── Pass 1: COLOR (non-blend), early-Z against the prepass ──
        glUseProgram(sh.program)
        glUniform1i(sh.u('u_diffuse'), 0)
        glUniform1i(sh.u('u_normal'), 1)
        glUniform1i(sh.u('u_specular'), 2)
        glUniform1i(sh.u('u_emission'), 3)
        glUniform3f(sh.u('u_overlay_color'), 0.35, 0.50, 1.0)
        glUniform1i(sh.u('u_unlit'), 1 if self.dbg_unlit else 0)   # debug A/B
        glUniform1f(sh.u('u_night'), float(self.night_factor))     # bio emission scale
        glUniform1i(sh.u('u_flip_green'), 1 if self.dbg_flip_green else 0)
        glUniform1i(sh.u('u_flip_normal'), 1 if self.dbg_flip_normal else 0)
        if dsh is not None:
            glDepthMask(GL_FALSE)    # depth already laid down by the prepass
            glDepthFunc(GL_LEQUAL)   # shade only the front-most fragment per pixel
        else:
            glDepthMask(GL_TRUE)     # no prepass: ordinary depth-tested fill
            glDepthFunc(GL_LESS)
        for model, instances, nonblend, _blend in renderlist:
            if not nonblend:
                continue
            n = self._setup_instance_attribs(instances)
            if n == 0:
                continue
            for mesh in nonblend:
                self._draw_mesh_instanced(model, mesh, sh, anim_t, n)
            rendered += n

        # ── Pass 2: BLEND (after all opaque) ──
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDepthMask(GL_FALSE)
        glDepthFunc(GL_LEQUAL)
        for model, instances, _nonblend, blend in renderlist:
            if not blend:
                continue
            n = self._setup_instance_attribs(instances)
            if n == 0:
                continue
            for mesh in blend:
                self._draw_mesh_instanced(model, mesh, sh, anim_t, n)
        glDisable(GL_BLEND)

        # Restore depth state for the passes that draw AFTER entities (selection
        # glow / beacon lines / gizmo) and for next frame's terrain.
        glDepthMask(GL_TRUE)
        glDepthFunc(GL_LESS)

        # CRITICAL: unbind the VAO BEFORE touching any attrib state — otherwise the
        # glDisable*VertexAttribArray calls below would edit (corrupt) whichever
        # mesh VAO is currently bound, blanking that mesh next frame. After
        # binding 0 the teardown lands on the harmless default VAO.
        if self._vao_active():
            glBindVertexArray(0)
        # Tear down every vertex/instance attrib so nothing (esp. the divisors)
        # leaks into the fixed-function fallback or the next frame.
        self._disable_instance_attribs()
        for loc in (ATTR_POSITION, ATTR_NORMAL, ATTR_UV, ATTR_TANGENT):
            glDisableVertexAttribArray(loc)
        glDisable(GL_CULL_FACE)          # restore (other passes manage their own)

        glUseProgram(0)
        glActiveTexture(GL_TEXTURE0)
        return rendered

    def _render_batched_models_fixed(self):
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

    def render_selection_glow(self, glow_intensity, selected_entities=None):
        """Re-render selected instances with a pulsing pure-yellow overlay.

        Renders raw vertex geometry only (no textures, no lighting) so the glow
        colour is always yellow regardless of the model's own texture colours.
        The old approach used GL_EMISSION × GL_MODULATE, which multiplied yellow
        by the texture colour — blue models turned dark, orange models turned red.
        Bypassing the display list and textures entirely fixes this.

        In GPU-driven array mode instance_batches is empty/stale (prepare_batches
        doesn't run), so the glow transforms are built directly from
        `selected_entities` — same position/RS data the instance SSBO uses.
        Without this the yellow pulse silently vanished in GDR mode and only the
        shader's static blue tint remained.
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
            # The model's depth was written by a SHADER (GDR/universal) while the
            # glow re-renders with fixed-function matrices — the two depth values
            # aren't bit-identical, so without an offset the glow loses the
            # GL_LEQUAL fight in patches (yellow only partially covered the
            # model). Pull the glow slightly toward the viewer; still occluded
            # correctly by genuinely closer geometry.
            glEnable(GL_POLYGON_OFFSET_FILL)
            glPolygonOffset(-2.0, -2.0)

            glColor4f(1.0, 0.85, 0.0, glow_intensity)  # pure yellow, no texture influence

            if self.gdr_drew_last and selected_entities:
                # Array mode: build the few selected transforms directly.
                for e in selected_entities:
                    mf = getattr(e, 'model_file', None)
                    kits = getattr(e, 'kit_model_files', []) or []
                    paths = ([mf] if mf else []) + [kg for kg, _kb in kits]
                    if not paths or not all(hasattr(e, a) for a in ('x', 'y', 'z')):
                        continue
                    rx, ry, rz, sc = self._get_entity_rs(e)
                    inst = (e, float(e.x), float(e.z), float(-e.y), rx, ry, rz, sc, True)
                    for p in paths:
                        model = self.models_cache.get(p)
                        if model and model.loaded and model.meshes:
                            self._render_glow_geometry(model, inst)
            else:
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
            if getattr(model, 'display_list_blend', None):
                glDeleteLists(model.display_list_blend, 1)
            # Delete every GL texture this model owns. XBG models now carry all
            # four slots in mat_textures (model.textures only has diffuse), so
            # deleting just model.textures would leak the normal/spec/emission
            # textures. Dedup so the shared diffuse id isn't double-deleted.
            seen = set()
            for slots in getattr(model, 'mat_textures', {}).values():
                for tid in slots.values():
                    if tid and tid not in seen:
                        seen.add(tid)
                        glDeleteTextures([tid])
            for tex_id in model.textures.values():
                if tex_id and tex_id not in seen:
                    seen.add(tex_id)
                    glDeleteTextures([tex_id])
            # Delete per-mesh GPU buffers (VBOs) created by the shader path.
            for mesh in (model.meshes or []):
                vbo = getattr(mesh, '_vbo', None)
                if isinstance(vbo, dict):
                    bufs = [vbo[k] for k in ('pos', 'nrm', 'uv', 'tan', 'ibo') if vbo.get(k)]
                    if bufs:
                        try:
                            glDeleteBuffers(len(bufs), bufs)
                        except Exception:
                            pass
                    if vbo.get('vao'):
                        try:
                            glDeleteVertexArrays(1, [vbo['vao']])
                        except Exception:
                            pass
                    mesh._vbo = None

        for tex_id in self._texture_cache.values():
            glDeleteTextures([tex_id])

        if self.fallback_cube_list:
            glDeleteLists(self.fallback_cube_list, 1)

        # Free the shared hardware-instancing buffer.
        if self._instance_vbo is not None:
            try:
                glDeleteBuffers(1, [self._instance_vbo])
            except Exception:
                pass
            self._instance_vbo = None

        self.models_cache.clear()
        self.has_animated_materials = False
        self._extract_cache.clear()   # resource→path memo (paths may change with level/resource folder)

        # Reset the array-native GDR row tables — they reference the old level's
        # entity indices/model slots and must rebuild against the new level.
        self._gdr_row_ent = None
        self._gdr_row_slot = None
        self._gdr_row_rot = None
        self._gdr_row_scale = None
        self._gdr_overlay = None
        self._gdr_row_map = {}
        self._gdr_model_paths = []
        self._gdr_modelled_ids = set()
        self._gdr_rows_version = None
        self._gdr_slots_version += 1
        self._gdr_sel_ids = frozenset()
        self._gdr_frame = None
        self._gdr_fallback_args = None
        self.gdr_drew_last = False
        print("Cache cleared")