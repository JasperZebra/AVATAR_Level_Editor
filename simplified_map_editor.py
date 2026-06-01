import multiprocessing

# Prevent PyQt/OpenGL imports inside worker processes
if multiprocessing.current_process().name != "MainProcess":
    # Worker processes must NOT import PyQt/OpenGL/editor
    # So define a dummy placeholder class and exit early
    class SimplifiedMapEditor:
        pass
    # Do not import anything else
else:
    # Safe to import GUI + OpenGL:
    from PyQt6.QtWidgets import (
        QMainWindow, QWidget, QApplication, QFileDialog,
        QVBoxLayout, QHBoxLayout, QFormLayout,
        QPushButton, QLabel, QGroupBox, QDockWidget,
        QStatusBar, QMessageBox, QToolBar, QComboBox,
        QProgressDialog, QProgressBar, QDialog,
        QTreeWidget, QTreeWidgetItem,
        QLineEdit, QInputDialog, QListWidgetItem,
        QTextEdit, QMenu, QSlider, QTabBar, QDoubleSpinBox,
        QWidgetAction, QSpinBox
    )
    from PyQt6.QtOpenGLWidgets import QOpenGLWidget
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QPropertyAnimation
    from PyQt6.QtGui import (
        QAction, QColor, QVector3D, QShortcut,
        QActionGroup, QFont, QPixmap, QPainter, QTransform
    )

    from data_models import (
        Entity, GridConfig, MapInfo, ObjectEntity,
        WorldSectorManager, ObjectParser, ObjectLoadResult
    )

    from entity_export_import import (
        show_entity_export_dialog, 
        show_entity_import_dialog,
        setup_entity_export_import_system
    )

    from set_patch_folder import LevelSelectorDialog, integrate_patch_manager
    from cache_manager import get_cache_manager, shutdown_cache_manager
    from canvas.terrain_renderer import TerrainRenderer
    from canvas.map_canvas_gpu import MapCanvas
    from file_converter import FileConverter
    from all_in_one_copy_paste import setup_complete_smart_system
    from entity_export_import import setup_entity_export_import_system
    from theme_settings import ThemeSettings
    from canvas.model_loader import GLTFModel
    from canvas.water_editor_dialog import show_water_editor
    from ui_style_utils import apply_checkbox_style
    from movie_data import MovieData, find_moviedata_xml


    # Standard library
    import time
    import glob
    import json
    import math
    import sys
    import os
    import struct
    import xml.etree.ElementTree as ET
    import shutil
    import subprocess
    import platform
    from pathlib import Path

def _get_str_val(field_elem):
    """Read the string value from an XML field, supporting both value-String and strVal attributes."""
    if field_elem is None:
        return ""
    return (field_elem.get('value-String') or field_elem.get('strVal') or "").strip()


# ---------------------------------------------------------------------------
# Sector XML rebuild helpers (unified world sector mode)
# ---------------------------------------------------------------------------

def _int32_to_binhex(val):
    """Signed 32-bit int → little-endian hex string (8 chars)."""
    return struct.pack('<i', int(val)).hex().upper()


def _string_to_binhex(text):
    """Null-terminated ASCII string → hex string (matches entity_editor.py)."""
    if not text:
        return "00"
    return (text + '\x00').encode('ascii', errors='replace').hex().upper()


def _compute_hash32_to_binhex(text):
    """djb2-style hash of text → unsigned 32-bit little-endian hex (matches entity_editor.py)."""
    h = 0
    for ch in text:
        h = ((h << 5) + h + ord(ch)) & 0xFFFFFFFF
    return struct.pack('<I', h).hex().upper()


def _coords_to_binhex(x, y, z):
    """3 floats → 12-byte little-endian hex (Vector3 BinHex)."""
    return struct.pack('<fff', float(x), float(y), float(z)).hex().upper()


def rebuild_sector_xml(sector_id, gx, gy, entities, original_tree=None):
    """
    Rebuild a WorldSector XML tree for *entities* (a list of Entity objects).

    Strategy: clone the *original_tree* (preserving all WorldSector-level metadata the
    game needs) then replace the Entity elements inside each MissionLayer with the new
    set.  If no original_tree is provided, a minimal skeleton is created as a fallback
    (same as before — may miss game-required fields).

    Entity positions are taken from entity.x / entity.y / entity.z (the live Python
    values) and written directly into each cloned element so the saved XML always
    reflects where the entity actually is, even if the in-memory xml_element hasn't
    been flushed yet.

    Returns:
        ET.ElementTree: the rebuilt tree, ready to write to disk.
    """
    import copy

    if original_tree is not None:
        # Deep-clone the whole original tree so we don't mutate the live in-memory copy
        root = copy.deepcopy(original_tree.getroot())
    else:
        # Fallback: minimal skeleton (used when no original is available)
        root = ET.Element("object", {"name": "WorldSector"})
        id_field = ET.SubElement(root, "field", {"name": "Id", "value-Int32": str(sector_id)})
        id_field.text = _int32_to_binhex(sector_id)
        x_field = ET.SubElement(root, "field", {"name": "X", "value-Int32": str(gx)})
        x_field.text = _int32_to_binhex(gx)
        y_field = ET.SubElement(root, "field", {"name": "Y", "value-Int32": str(gy)})
        y_field.text = _int32_to_binhex(gy)

    # ── Remove all existing Entity elements from every MissionLayer ───────────
    for layer_elem in root.findall("./object[@name='MissionLayer']"):
        for ent in list(layer_elem.findall("./object[@name='Entity']")):
            layer_elem.remove(ent)

    # ── Group incoming entities by their source_layer ──────────────────────────
    layers: dict = {}
    for entity in entities:
        layer_name = getattr(entity, 'source_layer', 'main') or 'main'
        layers.setdefault(layer_name, []).append(entity)

    # ── For each layer: find or create the MissionLayer element and add entities ─
    for layer_name, layer_entities in layers.items():
        # Try to find an existing MissionLayer with this name
        layer_elem = None
        for elem in root.findall("./object[@name='MissionLayer']"):
            pf = elem.find("./field[@name='text_PathId']")
            if pf is not None and pf.get('value-String', '') == layer_name:
                layer_elem = elem
                break

        if layer_elem is None:
            # Create a new MissionLayer — hash/type attrs are required for FCBConverter
            layer_elem = ET.SubElement(root, "object", {"hash": "494C09F2", "name": "MissionLayer"})
            text_path_field = ET.SubElement(layer_elem, "field",
                                            {"hash": "C56F9204", "name": "text_PathId",
                                             "value-String": layer_name, "type": "BinHex"})
            text_path_field.text = _string_to_binhex(layer_name)
            _path_binhex = _compute_hash32_to_binhex(layer_name)
            _path_int    = struct.unpack('<I', bytes.fromhex(_path_binhex))[0]
            path_id_field = ET.SubElement(layer_elem, "field",
                                          {"hash": "D0E30BF7", "name": "PathId",
                                           "value-Int32": str(_path_int), "type": "BinHex"})
            path_id_field.text = _path_binhex

        for entity in layer_entities:
            if entity.xml_element is None:
                continue
            # Deep-copy the entity element and update its position to the live values
            entity_copy = ET.fromstring(
                ET.tostring(entity.xml_element, encoding='unicode')
            )
            # Overwrite position with current entity.x/y/z so moves are always saved
            for field_name in ('hidPos', 'hidPos_precise'):
                pos_field = entity_copy.find(f"./field[@name='{field_name}']")
                if pos_field is not None:
                    pos_str = f"{entity.x:.0f},{entity.y:.0f},{entity.z:.0f}"
                    pos_field.set('value-Vector3', pos_str)
                    pos_field.text = _coords_to_binhex(entity.x, entity.y, entity.z)
            layer_elem.append(entity_copy)

    return ET.ElementTree(root)


class ModelPreviewWidget(QOpenGLWidget):
    """Standalone 3D preview widget for the selected entity's model."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_model = None
        self.entity_name = ""
        self._models = []          # list of (model, name) for group preview
        self.rotation_x = 20.0
        self.rotation_y = 0.0
        self.zoom_dist = 4.0
        self.auto_rotate = True
        self._mouse_anchor_global = None
        self._preview_textures = {}   # mat_idx -> GL texture ID (this context only)
        self._group_textures = []     # per-model texture dicts for group preview
        # The fit-scale + per-model transforms are static per selection — cache
        # them once so the turntable paintGL skips the per-frame numpy bbox pass
        # (np.concatenate + min/max over every vertex, twice). The actual mesh
        # draw still goes through _draw_model_meshes each frame (textures intact).
        self._render_plan = None      # (global_scale, [(model, tex, dx,dy,dz, rx,ry,rz, esc, center)])
        self.setMinimumHeight(180)
        self.setMinimumWidth(180)
        self.setFocusPolicy(Qt.FocusPolicy.WheelFocus)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_model(self, model, entity_name="", entity=None):
        """Show a single model."""
        self.current_model = model
        self.entity_name = entity_name
        self._models = [(model, entity_name, entity)]
        self.rotation_y = 0.0
        self.zoom_dist = 4.0
        self.auto_rotate = True
        self.makeCurrent()
        self._preview_textures = {}
        self._upload_preview_textures(model)
        self._group_textures = [self._preview_textures]
        self.doneCurrent()
        self._rebuild_preview_cache()   # GL-free: just bbox/layout maths
        self.update()

    def set_models(self, models_list):
        """Show multiple models at world-relative positions.
        models_list: [(model, name, entity), ...]  entity may be None.
        """
        if not models_list:
            self.clear()
            return
        if len(models_list) == 1:
            m, n, e = models_list[0]
            self.set_model(m, n, e)
            return
        self._models = models_list
        self.current_model = models_list[0][0]
        self.entity_name = f"{len(models_list)} selected"
        self.rotation_y = 0.0
        self.zoom_dist = 4.0
        self.auto_rotate = True
        self.makeCurrent()
        self._group_textures = []
        for model, _name, _entity in models_list:
            self._preview_textures = {}
            self._upload_preview_textures(model)
            self._group_textures.append(self._preview_textures)
        self._preview_textures = self._group_textures[0] if self._group_textures else {}
        self.doneCurrent()
        self._rebuild_preview_cache()   # GL-free: just bbox/layout maths
        self.update()

    def clear(self):
        self.current_model = None
        self.entity_name = ""
        self._models = []
        self._preview_textures = {}
        self._group_textures = []
        self._render_plan = None
        self.update()

    def _tick(self):
        if self.auto_rotate and self.current_model:
            self.rotation_y = (self.rotation_y + 1.0) % 360.0
            self.update()

    def _upload_preview_textures(self, model):
        """Upload model textures into this widget's GL context."""
        from OpenGL.GL import (glGenTextures, glBindTexture, glTexImage2D,
                                glTexParameteri, glGenerateMipmap,
                                GL_TEXTURE_2D, GL_RGBA, GL_UNSIGNED_BYTE,
                                GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER,
                                GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T,
                                GL_LINEAR_MIPMAP_LINEAR, GL_LINEAR, GL_REPEAT)
        self._preview_textures = {}
        if model is None:
            return
        raw = getattr(model, 'texture_raw_data', {})
        if not raw:
            print(f"[preview] no texture_raw_data on model '{getattr(self, 'entity_name', '')}'")
            return
        mat_map = getattr(model, 'texture_material_map', {})
        # Two keyings exist: the old gltf path keys texture_raw_data by IMAGE index
        # (+ texture_material_map: mat_idx -> img_idx); the XBG direct path keys it
        # by MATERIAL index directly and sets no map. Handle both so XBG models
        # (which never populate the map) still texture the preview.
        if mat_map:
            pairs = [(mi, raw[ii]) for mi, ii in mat_map.items() if ii in raw]
        else:
            pairs = list(raw.items())   # XBG: already keyed by material index
        for mat_idx, entry in pairs:
            try:
                width, height, img_data = entry
                tex_id = glGenTextures(1)
                glBindTexture(GL_TEXTURE_2D, tex_id)
                glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height,
                             0, GL_RGBA, GL_UNSIGNED_BYTE, img_data)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
                glGenerateMipmap(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, 0)
                self._preview_textures[mat_idx] = tex_id
            except Exception as e:
                print(f"Preview texture upload failed for mat {mat_idx}: {e}")
        print(f"[preview] uploaded {len(self._preview_textures)}/{len(pairs)} textures "
              f"for '{getattr(self, 'entity_name', '')}' "
              f"(keying: {'material-map' if mat_map else 'direct'})")

    def _rebuild_preview_cache(self):
        """Compute the static fit-scale + per-model transforms ONCE per selection
        (the bbox `np.concatenate`/min-max pass that used to run every frame).
        GL-free — just numpy + entity reads — so it's safe to call outside a
        current context. paintGL then reuses the plan and still draws via
        _draw_model_meshes (textures intact). On failure, clears the plan and
        paintGL falls back to the original per-frame path."""
        import numpy as np
        self._render_plan = None
        models_to_draw = self._models if self._models else (
            [(self.current_model, self.entity_name, None)] if self.current_model else [])
        if not models_to_draw:
            return
        try:
            # Per-model local bbox/center (same maths as the old paintGL pre-pass).
            model_infos = []
            for i, entry in enumerate(models_to_draw):
                model = entry[0]
                tex_dict = self._group_textures[i] if i < len(self._group_textures) else {}
                if model is None or not model.meshes:
                    model_infos.append(None); continue
                all_verts = [np.asarray(m.vertices, np.float32).reshape(-1, 3)
                             for m in model.meshes if m.vertices is not None and len(m.vertices) > 0]
                if not all_verts:
                    model_infos.append(None); continue
                va = np.concatenate(all_verts, 0)
                mn, mx = va.min(0), va.max(0)
                model_infos.append((model, tex_dict, (mn + mx) * 0.5, float(np.max(mx - mn))))

            # Shared center per entity (kit-assembled NPCs align their parts).
            buckets = {}
            for i, entry in enumerate(models_to_draw):
                if model_infos[i] is None:
                    continue
                entity = entry[2] if len(entry) > 2 else None
                eid = id(entity)
                for m in entry[0].meshes:
                    if m.vertices is not None and len(m.vertices) > 0:
                        buckets.setdefault(eid, []).append(
                            np.asarray(m.vertices, np.float32).reshape(-1, 3))
            ecache = {}
            for eid, vl in buckets.items():
                c = np.concatenate(vl, 0)
                ecache[eid] = (c.min(0) + c.max(0)) * 0.5

            entries = []
            for i, entry in enumerate(models_to_draw):
                info = model_infos[i]
                if info is None:
                    entries.append(None); continue
                entity = entry[2] if len(entry) > 2 else None
                wx = float(entity.x) if entity and hasattr(entity, 'x') else 0.0
                wy = float(entity.y) if entity and hasattr(entity, 'y') else 0.0
                wz = float(entity.z) if entity and hasattr(entity, 'z') else 0.0
                rx, ry, rz, esc = self._get_entity_transform(entity)
                entries.append((info, wx, wy, wz, rx, ry, rz, esc, entity))

            valid = [(e[1], e[2], e[3]) for e in entries if e is not None]
            if not valid:
                return
            cx = sum(p[0] for p in valid) / len(valid)
            cy = sum(p[1] for p in valid) / len(valid)
            cz = sum(p[2] for p in valid) / len(valid)

            scene_pts = []
            for e in entries:
                if e is None:
                    continue
                info, wx, wy, wz, _, _, _, esc, _ent = e
                _m, _t, lc, lext = info
                r = lext * 0.5 * esc
                dx = wx - cx; dy = wz - cz; dz = -(wy - cy)
                scene_pts += [(dx - r, dy - r, dz - r), (dx + r, dy + r, dz + r)]
            if scene_pts:
                sp = np.array(scene_pts, np.float32)
                te = float(np.max(sp.max(0) - sp.min(0)))
                global_scale = (2.0 / te) if te > 0 else 1.0
            else:
                global_scale = 1.0

            # Cache the per-model transform + fit scale (no GL here).
            plan = []
            for e in entries:
                if e is None:
                    continue
                info, wx, wy, wz, rx, ry, rz, esc, entity = e
                model, tex_dict, lc, _ = info
                eid = id(entity) if entity is not None else -1
                center = ecache.get(eid, lc)
                dx = wx - cx; dy = wz - cz; dz = -(wy - cy)
                plan.append((model, tex_dict, dx, dy, dz, rx, ry, rz, esc,
                             (float(center[0]), float(center[1]), float(center[2]))))
            self._render_plan = (global_scale, plan)
        except Exception as _e:
            print(f"[preview] cache rebuild failed -> immediate path: {_e}")
            self._render_plan = None

    # ── OpenGL ────────────────────────────────────────────────────────────

    def initializeGL(self):
        from OpenGL import GL as gl
        import math
        gl.glClearColor(0.12, 0.12, 0.14, 1.0)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glEnable(gl.GL_NORMALIZE)
        gl.glEnable(gl.GL_LIGHTING)
        gl.glEnable(gl.GL_LIGHT0)
        gl.glEnable(gl.GL_LIGHT1)
        gl.glDisable(gl.GL_LIGHT2)
        gl.glEnable(gl.GL_COLOR_MATERIAL)
        gl.glEnable(gl.GL_TEXTURE_2D)
        gl.glColorMaterial(gl.GL_FRONT_AND_BACK, gl.GL_AMBIENT_AND_DIFFUSE)
        gl.glLightModeli(gl.GL_LIGHT_MODEL_LOCAL_VIEWER, gl.GL_TRUE)
        # World-space sun — same formula as _key_light_pos(), default azimuth=0° elevation=270°
        _az = math.radians(0)
        _el = math.radians(270)
        _ce, _se = math.cos(_el), math.sin(_el)
        _lx = _ce * math.cos(_az + math.radians(45))
        _ly = _se
        _lz = _ce * math.sin(_az + math.radians(45))
        gl.glLightfv(gl.GL_LIGHT0, gl.GL_POSITION, [_lx, _ly, _lz, 0.0])
        gl.glLightfv(gl.GL_LIGHT0, gl.GL_DIFFUSE,  [0.90, 0.88, 0.82, 1.0])
        gl.glLightfv(gl.GL_LIGHT0, gl.GL_SPECULAR, [0.50, 0.48, 0.44, 1.0])
        gl.glLightfv(gl.GL_LIGHT0, gl.GL_AMBIENT,  [0.00, 0.00, 0.00, 1.0])
        gl.glLightfv(gl.GL_LIGHT1, gl.GL_POSITION, [0.0,  1.0,  0.0,  0.0])
        gl.glLightfv(gl.GL_LIGHT1, gl.GL_DIFFUSE,  [0.30, 0.33, 0.42, 1.0])
        gl.glLightfv(gl.GL_LIGHT1, gl.GL_SPECULAR, [0.00, 0.00, 0.00, 1.0])
        gl.glLightfv(gl.GL_LIGHT1, gl.GL_AMBIENT,  [0.00, 0.00, 0.00, 1.0])
        gl.glLightModelfv(gl.GL_LIGHT_MODEL_AMBIENT, [0.38, 0.38, 0.42, 1.0])
        gl.glMaterialfv(gl.GL_FRONT_AND_BACK, gl.GL_SPECULAR, [0.15, 0.15, 0.15, 1.0])
        gl.glMaterialf(gl.GL_FRONT_AND_BACK, gl.GL_SHININESS, 40.0)

    def resizeGL(self, w, h):
        from OpenGL import GL as gl
        import math
        gl.glViewport(0, 0, w, max(h, 1))
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glLoadIdentity()
        aspect = w / max(h, 1)
        fov_y = 45.0
        near, far = 0.01, 5000.0
        top = near * math.tan(math.radians(fov_y / 2.0))
        right = top * aspect
        gl.glFrustum(-right, right, -top, top, near, far)
        gl.glMatrixMode(gl.GL_MODELVIEW)

    @staticmethod
    def _get_entity_transform(entity):
        """Extract (rot_x, rot_y, rot_z, scale) from entity XML — same logic as model_loader.prepare_batches."""
        import struct as _struct
        rot_x = rot_y = rot_z = 0.0
        scale = 1.0
        if entity is None or not hasattr(entity, 'xml_element') or entity.xml_element is None:
            return rot_x, rot_y, rot_z, scale
        xml = entity.xml_element
        # hidAngles
        angles_field = xml.find(".//field[@name='hidAngles']")
        if angles_field is not None:
            av = angles_field.get('value-Vector3')
            if av:
                try:
                    parts = av.split(',')
                    if len(parts) >= 3:
                        rot_x = float(parts[0].strip())
                        rot_y = float(parts[1].strip())
                        rot_z = (360.0 - float(parts[2].strip())) % 360.0
                except (ValueError, IndexError):
                    pass
        # hidScale (stored as BinHex little-endian float32)
        scale_field = xml.find(".//field[@name='hidScale']")
        if scale_field is not None:
            binhex = scale_field.text
            if binhex and len(binhex) >= 8:
                try:
                    s = _struct.unpack('<f', bytes.fromhex(binhex[:8]))[0]
                    if 0 < s <= 100:
                        scale = s
                except Exception:
                    pass
        return rot_x, rot_y, rot_z, scale

    def paintGL(self):
        from OpenGL import GL as gl
        import numpy as np
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        gl.glLoadIdentity()
        # Reset emission so meshes without emissive factors are unaffected
        gl.glMaterialfv(gl.GL_FRONT_AND_BACK, gl.GL_EMISSION, [0.0, 0.0, 0.0, 1.0])

        # Fast path: reuse the cached fit-scale + per-model transforms (the
        # per-frame numpy bbox pass is gone). Mesh drawing still goes through
        # _draw_model_meshes, so textures/materials are identical to before.
        if self._render_plan is not None:
            global_scale, plan = self._render_plan
            gl.glTranslatef(0.0, 0.0, -self.zoom_dist)
            gl.glRotatef(self.rotation_x, 1.0, 0.0, 0.0)
            gl.glRotatef(self.rotation_y, 0.0, 1.0, 0.0)
            gl.glScalef(global_scale, global_scale, global_scale)
            for model, tex_dict, dx, dy, dz, rx, ry, rz, esc, center in plan:
                gl.glPushMatrix()
                gl.glTranslatef(dx, dy, dz)
                gl.glRotatef(-90.0, 1.0, 0.0, 0.0)
                if rz != 0.0:
                    gl.glRotatef(-rz, 0.0, 0.0, 1.0)
                if rx != 0.0:
                    gl.glRotatef(rx, 1.0, 0.0, 0.0)
                if ry != 0.0:
                    gl.glRotatef(ry, 0.0, 1.0, 0.0)
                if esc != 1.0:
                    gl.glScalef(esc, esc, esc)
                gl.glTranslatef(-center[0], -center[1], -center[2])
                self._draw_model_meshes(gl, model, tex_dict)
                gl.glPopMatrix()
            gl.glDisableClientState(gl.GL_VERTEX_ARRAY)
            gl.glDisableClientState(gl.GL_NORMAL_ARRAY)
            gl.glDisableClientState(gl.GL_TEXTURE_COORD_ARRAY)
            gl.glEnable(gl.GL_TEXTURE_2D)
            return

        models_to_draw = self._models if self._models else (
            [(self.current_model, self.entity_name, None)] if self.current_model else []
        )
        if not models_to_draw:
            return

        n = len(models_to_draw)

        # ── Pre-pass: collect per-model local bounding boxes ──────────────
        model_infos = []  # (model, tex_dict, local_center, local_extent) or None
        for i, entry in enumerate(models_to_draw):
            model = entry[0]
            tex_dict = self._group_textures[i] if i < len(self._group_textures) else {}
            if model is None or not model.meshes:
                model_infos.append(None)
                continue
            all_verts = []
            for mesh in model.meshes:
                if mesh.vertices is not None and len(mesh.vertices) > 0:
                    all_verts.append(np.asarray(mesh.vertices, dtype=np.float32).reshape(-1, 3))
            if not all_verts:
                model_infos.append(None)
                continue
            verts_all = np.concatenate(all_verts, axis=0)
            min_v = verts_all.min(axis=0)
            max_v = verts_all.max(axis=0)
            local_center = (min_v + max_v) * 0.5
            local_extent = float(np.max(max_v - min_v))
            model_infos.append((model, tex_dict, local_center, local_extent))

        # ── Kit-assembled NPCs: compute one shared center per entity ──────
        # Multiple parts from the same entity (kit NPCs) must use the same
        # center offset so they render aligned instead of scattered.
        entity_vert_buckets = {}  # id(entity) -> list of vertex arrays
        for i, entry in enumerate(models_to_draw):
            if model_infos[i] is None:
                continue
            entity = entry[2] if len(entry) > 2 else None
            eid = id(entity)
            model = entry[0]
            for mesh in model.meshes:
                if mesh.vertices is not None and len(mesh.vertices) > 0:
                    entity_vert_buckets.setdefault(eid, []).append(
                        np.asarray(mesh.vertices, dtype=np.float32).reshape(-1, 3))

        entity_center_cache = {}  # id(entity) -> combined center ndarray
        for eid, vert_list in entity_vert_buckets.items():
            combined = np.concatenate(vert_list, axis=0)
            mn = combined.min(axis=0)
            mx = combined.max(axis=0)
            entity_center_cache[eid] = (mn + mx) * 0.5

        # ── Collect entity world positions and transforms ─────────────────
        # Game space: x=east, y=north, z=up
        # GL space:   x=right, y=up, z=toward viewer  →  gl=(game.x, game.z, -game.y)
        entries = []
        for i, entry in enumerate(models_to_draw):
            info = model_infos[i]
            if info is None:
                entries.append(None)
                continue
            entity = entry[2] if len(entry) > 2 else None
            wx = float(entity.x) if entity and hasattr(entity, 'x') else 0.0
            wy = float(entity.y) if entity and hasattr(entity, 'y') else 0.0
            wz = float(entity.z) if entity and hasattr(entity, 'z') else 0.0
            rot_x, rot_y, rot_z, esc = self._get_entity_transform(entity)
            entries.append((info, wx, wy, wz, rot_x, rot_y, rot_z, esc, entity))

        valid = [(e[1], e[2], e[3]) for e in entries if e is not None]
        if not valid:
            return

        # ── Group center (game space) ─────────────────────────────────────
        cx = sum(p[0] for p in valid) / len(valid)
        cy = sum(p[1] for p in valid) / len(valid)
        cz = sum(p[2] for p in valid) / len(valid)

        # ── Compute fitting scale ─────────────────────────────────────────
        # Build scene AABB: each model placed at its world offset, scaled by entity scale
        scene_pts = []
        for e in entries:
            if e is None:
                continue
            info, wx, wy, wz, _, _, _, esc, entity = e
            _model, _tex, lc, lext = info
            r = lext * 0.5 * esc
            # World offset in GL space
            dx = wx - cx;  dy = wz - cz;  dz = -(wy - cy)
            scene_pts += [(dx - r, dy - r, dz - r), (dx + r, dy + r, dz + r)]

        if scene_pts:
            sp = np.array(scene_pts, dtype=np.float32)
            total_extent = float(np.max(sp.max(axis=0) - sp.min(axis=0)))
            global_scale = (2.0 / total_extent) if total_extent > 0 else 1.0
        else:
            global_scale = 1.0

        # ── Camera ───────────────────────────────────────────────────────
        gl.glTranslatef(0.0, 0.0, -self.zoom_dist)
        gl.glRotatef(self.rotation_x, 1.0, 0.0, 0.0)
        gl.glRotatef(self.rotation_y, 0.0, 1.0, 0.0)
        gl.glScalef(global_scale, global_scale, global_scale)

        # ── Render each model with exact same transform as 3D canvas ─────
        for e in entries:
            if e is None:
                continue
            info, wx, wy, wz, rot_x, rot_y, rot_z, esc, entity = e
            model, tex_dict, local_center, _lext = info

            # Kit-assembled NPCs share one combined center so all parts align.
            # Solo models use their own local center.
            eid = id(entity) if entity is not None else -1
            center = entity_center_cache.get(eid, local_center)

            # World offset → GL space
            dx = wx - cx
            dy = wz - cz
            dz = -(wy - cy)

            gl.glPushMatrix()
            gl.glTranslatef(dx, dy, dz)             # world position offset
            gl.glRotatef(-90.0, 1.0, 0.0, 0.0)     # game→GL coord correction
            if rot_z != 0.0:
                gl.glRotatef(-rot_z, 0.0, 0.0, 1.0)
            if rot_x != 0.0:
                gl.glRotatef(rot_x, 1.0, 0.0, 0.0)
            if rot_y != 0.0:
                gl.glRotatef(rot_y, 0.0, 1.0, 0.0)
            if esc != 1.0:
                gl.glScalef(esc, esc, esc)
            gl.glTranslatef(-center[0], -center[1], -center[2])
            self._draw_model_meshes(gl, model, tex_dict)
            gl.glPopMatrix()

        gl.glDisableClientState(gl.GL_VERTEX_ARRAY)
        gl.glDisableClientState(gl.GL_NORMAL_ARRAY)
        gl.glDisableClientState(gl.GL_TEXTURE_COORD_ARRAY)
        gl.glEnable(gl.GL_TEXTURE_2D)

    def _draw_model_meshes(self, gl, model, tex_dict):
        """Draw all meshes of a model, matching main 3D canvas rendering."""
        import numpy as np

        # Split meshes into opaque/MASK and BLEND for correct two-pass rendering
        opaque_meshes = []
        blend_meshes = []
        for mesh in model.meshes:
            if mesh.vertices is None or len(mesh.vertices) == 0:
                continue
            mat_idx = mesh.material_index
            alpha_mode = (model.alpha_modes.get(mat_idx, 'OPAQUE')
                          if hasattr(model, 'alpha_modes') else 'OPAQUE')
            if alpha_mode == 'BLEND':
                blend_meshes.append(mesh)
            else:
                opaque_meshes.append(mesh)

        gl.glEnableClientState(gl.GL_VERTEX_ARRAY)

        def _draw_mesh(mesh):
            mat_idx = mesh.material_index
            alpha_mode  = (model.alpha_modes.get(mat_idx, 'OPAQUE')
                           if hasattr(model, 'alpha_modes') else 'OPAQUE')
            alpha_cutoff = (model.alpha_cutoffs.get(mat_idx, 0.5)
                            if hasattr(model, 'alpha_cutoffs') else 0.5)
            emissive    = (model.emissive_factors.get(mat_idx, [0.0, 0.0, 0.0])
                           if hasattr(model, 'emissive_factors') else [0.0, 0.0, 0.0])
            base_color  = (model.base_color_factors.get(mat_idx, [1.0, 1.0, 1.0, 1.0])
                           if hasattr(model, 'base_color_factors') else [1.0, 1.0, 1.0, 1.0])
            has_tex = (mat_idx is not None and mat_idx in tex_dict and
                       mesh.uvs is not None and len(mesh.uvs) > 0)

            if has_tex:
                gl.glEnable(gl.GL_TEXTURE_2D)
                gl.glBindTexture(gl.GL_TEXTURE_2D, tex_dict[mat_idx])
                gl.glTexEnvi(gl.GL_TEXTURE_ENV, gl.GL_TEXTURE_ENV_MODE, gl.GL_MODULATE)
                # Prevent fully-black base_color from hiding the texture (same as _emit_mesh_gl)
                bc = base_color
                if 0.299 * bc[0] + 0.587 * bc[1] + 0.114 * bc[2] < 0.05:
                    bc = [1.0, 1.0, 1.0, bc[3]]
                gl.glColor4f(bc[0], bc[1], bc[2], bc[3])
                gl.glEnableClientState(gl.GL_TEXTURE_COORD_ARRAY)
                gl.glTexCoordPointer(2, gl.GL_FLOAT, 0,
                                     np.ascontiguousarray(mesh.uvs, dtype=np.float32))
                if alpha_mode == 'MASK':
                    gl.glEnable(gl.GL_ALPHA_TEST)
                    gl.glAlphaFunc(gl.GL_GREATER, alpha_cutoff)
                else:
                    gl.glDisable(gl.GL_ALPHA_TEST)
            else:
                gl.glDisable(gl.GL_TEXTURE_2D)
                gl.glDisable(gl.GL_ALPHA_TEST)
                bc = base_color
                gl.glColor4f(bc[0] * 0.7, bc[1] * 0.7, bc[2] * 0.7, bc[3])
                gl.glDisableClientState(gl.GL_TEXTURE_COORD_ARRAY)

            # Scope emission changes so they don't bleed into adjacent meshes
            is_emissive = any(c > 0.01 for c in emissive)
            if is_emissive:
                gl.glPushAttrib(gl.GL_LIGHTING_BIT)
                gl.glMaterialfv(gl.GL_FRONT_AND_BACK, gl.GL_EMISSION,
                                [emissive[0], emissive[1], emissive[2], 1.0])

            verts = np.ascontiguousarray(mesh.vertices, dtype=np.float32)
            gl.glVertexPointer(3, gl.GL_FLOAT, 0, verts)
            if mesh.normals is not None and len(mesh.normals) > 0:
                gl.glEnableClientState(gl.GL_NORMAL_ARRAY)
                gl.glNormalPointer(gl.GL_FLOAT, 0,
                                   np.ascontiguousarray(mesh.normals, dtype=np.float32))
            else:
                gl.glDisableClientState(gl.GL_NORMAL_ARRAY)

            if mesh.indices is not None and len(mesh.indices) > 0:
                idx = np.ascontiguousarray(mesh.indices, dtype=np.uint32)
                gl.glDrawElements(gl.GL_TRIANGLES, len(idx), gl.GL_UNSIGNED_INT, idx)
            else:
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, len(mesh.vertices))

            if is_emissive:
                gl.glPopAttrib()

            if has_tex:
                gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
                gl.glDisable(gl.GL_TEXTURE_2D)
                if alpha_mode == 'MASK':
                    gl.glDisable(gl.GL_ALPHA_TEST)

        # Pass 1: opaque and MASK meshes
        for mesh in opaque_meshes:
            _draw_mesh(mesh)

        # Pass 2: BLEND meshes after all opaque geometry
        if blend_meshes:
            gl.glEnable(gl.GL_BLEND)
            gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
            gl.glDepthMask(gl.GL_FALSE)
            for mesh in blend_meshes:
                _draw_mesh(mesh)
            gl.glDisable(gl.GL_BLEND)
            gl.glDepthMask(gl.GL_TRUE)

        gl.glDisable(gl.GL_ALPHA_TEST)

    # ── Mouse interaction ─────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._mouse_anchor_global = self.mapToGlobal(event.position().toPoint())
            self.setCursor(Qt.CursorShape.BlankCursor)
            self.auto_rotate = False

    def mouseMoveEvent(self, event):
        if not hasattr(self, '_mouse_anchor_global') or self._mouse_anchor_global is None:
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return

        current_global = self.mapToGlobal(event.position().toPoint())
        dx = current_global.x() - self._mouse_anchor_global.x()
        dy = current_global.y() - self._mouse_anchor_global.y()

        if dx == 0 and dy == 0:
            return  # synthetic event from warp

        self.rotation_y = (self.rotation_y + dx * 0.5) % 360.0
        self.rotation_x = max(-89.0, min(89.0, self.rotation_x + dy * 0.5))

        from PyQt6.QtGui import QCursor
        QCursor.setPos(self._mouse_anchor_global)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._mouse_anchor_global = None
            self.unsetCursor()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        factor = 0.1
        self.zoom_dist = max(0.5, self.zoom_dist - delta * factor * 0.01 * self.zoom_dist)
        self.update()

    def mouseDoubleClickEvent(self, event):
        self.rotation_x = 20.0
        self.rotation_y = 0.0
        self.zoom_dist = 4.0
        self.auto_rotate = True


class StayOpenMenu(QMenu):
    """QMenu subclass that keeps itself open when a checkable action is clicked."""
    def mouseReleaseEvent(self, event):
        action = self.activeAction()
        if action and action.isCheckable():
            action.trigger()
            event.accept()  # consume event — do NOT call super, so menu stays open
        else:
            super().mouseReleaseEvent(event)


class SimplifiedMapEditor(QMainWindow):
    """Simplified main application window for XML Entity Coordinate Editor"""
    
    def __init__(self, game_mode="avatar"):
        """Fixed initialization method with game mode support and patch folder integration
            
        Args:
            game_mode (str): Either "avatar" or "farcry2"
        """
        super().__init__()
            
        # Store game mode FIRST
        self.game_mode = game_mode
        
        # *** NEW: Load theme settings before ANY UI setup ***
        try:
            self.theme_settings = ThemeSettings()
            self.force_dark_theme = self.theme_settings.get_dark_theme()

            print(f"=" * 60)
            print(f"DEBUG: ThemeSettings loaded successfully")
            print(f"DEBUG: force_dark_theme = {self.force_dark_theme}")
            print(f"=" * 60)
        except Exception as e:
            print(f"ERROR loading theme settings: {e}")
            import traceback
            traceback.print_exc()
            # Fallback to defaults
            self.force_dark_theme = False

        # Create startup progress dialog
        from simplified_map_editor import EnhancedProgressDialog
        startup_dialog = EnhancedProgressDialog(
            "Initializing Editor", 
            None,  # No parent yet since we're in __init__
            game_mode=game_mode
        )
        startup_dialog.show()
        QApplication.processEvents()
        
        def log(msg):
            """Helper to log to both console and dialog"""
            print(msg)
            startup_dialog.append_log(msg)
            QApplication.processEvents()

        # *** NEW: Setup game-specific paths ***
        startup_dialog.set_status("Setting up game paths...")
        startup_dialog.set_progress(5)
        log(f"Initializing editor for: {game_mode}")
        
        from canvas.game_paths_config import setup_game_paths
        setup_game_paths(self)

        self.current_mode = "2D"

        # ================================================================
        #   WORLDS FOLDER AUTO-DETECTION  (REQUIRED FOR 3D MODELS)
        # ================================================================
        startup_dialog.set_status("Detecting game folders...")
        startup_dialog.set_progress(10)
        
        self.worlds_folder = None
        self.game_data_path = None

        window_title_prefix = "Avatar: The Game" if game_mode == "avatar" else "Far Cry 2"

        # ================================================================
        #   CACHE MANAGER
        # ================================================================
        startup_dialog.set_status("Initializing cache manager...")
        startup_dialog.set_progress(15)
        self.cache = get_cache_manager()
        log("✓ Cache manager initialized")
            
        # ================================================================
        #   BASIC PROPERTIES
        # ================================================================
        startup_dialog.set_status("Setting up data structures...")
        startup_dialog.set_progress(20)
        self.entities = []
        self.selected_entity = None
        self.xml_tree = None
        self.xml_file_path = None
            
        # ================================================================
        #   GRID CONFIG
        # ================================================================
        if game_mode == "farcry2":
            self.grid_config = GridConfig(
                sector_count_x=16,
                sector_count_y=16,
                sector_granularity=64,
                maps=[]
            )
            self.is_fc2_world = True
            self.world_grid_size = 5
            self.current_fc2_world = "world1"
            self.current_fc2_region = None
        else:
            self.grid_config = GridConfig(
                sector_count_x=16,
                sector_count_y=16,
                sector_granularity=64,
                maps=[]
            )
            self.is_fc2_world = False
            
        self.current_map = None

        # Entity editor
        self.entity_editor = None        

        # Modification tracking
        self.entities_modified = False
        self.xml_tree_modified = False
        self.omnis_tree_modified = False
        self.managers_tree_modified = False
        self.sectordep_tree_modified = False

        # WorldSectors
        self.objects = []
        self.worldsectors_path = None
        self.objects_modified = False
        self.show_objects = True
        self.worldsectors_trees = {}
        self.worldsectors_modified = {}
        self.landmark_trees = {}        # xml_path → ET.ElementTree for landmark FCB files
        self.landmark_clean_hashes = {} # xml_path → hash_str for dirty detection

        # Unified world sector mode (Step 3)
        self.sector_clean_hashes = {}  # dict[sector_id, hash_str] for dirty detection

        # Main-file dirty detection — keyed by file_type ('mapsdata','omnis','managers','sectorsdep')
        self._main_clean_hashes = {}

        # Movie data (moviedata.xml sequences / cinematic paths)
        self.movie_data = None                  # MovieData | None
        self.selected_movie_sequence = None     # str sequence name | None
        self.selected_movie_node_id = None      # int node_id | None (None = show all nodes in seq)
        self._movie_preview_timer = QTimer()
        self._movie_preview_timer.setInterval(16)  # ~60 fps
        self._movie_preview_timer.timeout.connect(self._movie_preview_tick)
        self._movie_preview_start_wall = None   # time.time() when preview started
        self._movie_preview_saved = {}          # entity_id -> (orig_x, orig_y, orig_z)

        # SDAT support
        self.sdat_path = None
        self._avatar_sdat_paths = []       # all sdat folders found across Avatar level parts
        self._all_worldsectors_paths = []  # all worldsectors folders across Avatar level parts
        self.terrain_viewer = None
        self.terrain_dock = None

        # Additional trees
        self.omnis_tree = None
        self.managers_tree = None
        self.sectordep_tree = None

        # Caches & config
        self.tree_entity_type_cache = {}
        self._last_selection_log_time = 0
        self.file_config = LevelFileConfig()



        # UI setup
        startup_dialog.set_status("Setting up menus...")
        startup_dialog.set_progress(25)
        # self.setup_cache_menu() 
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.setup_mode_indicator()

        # Conversion tools
        startup_dialog.set_status("Initializing file converter...")
        startup_dialog.set_progress(30)
        try:
            self.setup_conversion_tools()
            log("✓ File converter initialized")
        except Exception as e:
            log(f"⚠ Could not setup conversion tools: {e}")
            self.file_converter = None

        # ================================================================
        # CRITICAL: Setup copy/paste system BEFORE creating UI
        # This binds all the methods that the UI components need (e.g. select_all_entities)
        # ================================================================
        startup_dialog.set_status("Setting up copy/paste system...")
        startup_dialog.set_progress(35)
        try:
            setup_complete_smart_system(self)
            log("✓ Copy/paste system ready")
        except Exception as e:
            log(f"⚠ Could not setup copy/paste: {e}")

        # Main UI (creates canvas and entity browser)
        # select_all_entities is already bound above so entity browser can reference it
        startup_dialog.set_status("Creating main interface...")
        startup_dialog.set_progress(40)
        try:
            self.setup_ui()
            log("✓ Main UI created")
        except Exception as e:
            log(f"✗ Error setting up UI: {e}")
            raise

        # Re-run context menu setup now that canvas exists
        # (setup_complete_smart_system skipped it earlier because canvas wasn't ready)
        try:
            from all_in_one_copy_paste import setup_context_menu
            setup_context_menu(self)
            log("✓ Context menu wired to canvas")
        except Exception as e:
            log(f"⚠ Could not wire context menu: {e}")

        # *** CRITICAL FIX: Setup enhanced context menu AFTER canvas is created ***
        startup_dialog.set_status("Setting up context menu...")
        startup_dialog.set_progress(45)
        try:
            self.add_sector_move_to_context_menu()
            log("✓ Enhanced context menu ready")
        except Exception as e:
            log(f"⚠ Could not setup context menu: {e}")

        # *** NEW: Update model loader with game-specific paths ***
        startup_dialog.set_status("Configuring 3D model loader...")
        startup_dialog.set_progress(50)
        if hasattr(self, 'canvas') and hasattr(self.canvas, 'model_loader'):
            from canvas.game_paths_config import update_model_loader_for_game
            update_model_loader_for_game(
                self.canvas.model_loader, 
                self.game_path_config
            )
            log("✓ Model loader configured")

        # ================================================================
        #   LINK CANVAS (NO MODEL INITIALIZATION HERE ANYMORE!)
        # ================================================================
        startup_dialog.set_status("Linking canvas...")
        startup_dialog.set_progress(60)
        if hasattr(self, 'canvas'):
            self.canvas.editor = self
            self.canvas.is_fc2_world = self.is_fc2_world
            self.canvas.game_mode = self.game_mode
                
            if self.worlds_folder:
                self.canvas.main_window = self
                log("✓ Canvas linked for 3D models")

        # ================================================================
        #   Sector boundaries UI
        # ================================================================
        startup_dialog.set_status("Setting up sector boundaries...")
        startup_dialog.set_progress(65)
        try:
            self.setup_sector_boundary_ui()
            log("✓ Sector boundaries configured")
        except Exception as e:
            log(f"⚠ Could not setup sector boundaries: {e}")

        # Window title
        self.setWindowTitle(f"{window_title_prefix} Level Editor | Version 2.1 | Made By: Jasper Zebra")

        # Connect entity selection
        startup_dialog.set_status("Connecting signals...")
        startup_dialog.set_progress(70)
        try:
            self.canvas.entitySelected.connect(self.on_entity_selected)
            log("✓ Entity selection connected")
        except Exception as e:
            log(f"⚠ Could not connect entity selection: {e}")

        # Window size
        self.resize(1600, 900)

        # Theme - apply the loaded preference
        startup_dialog.set_status("Applying saved theme...")
        startup_dialog.set_progress(75)
        try:
            print(f"🎨 Applying theme: force_dark_theme = {self.force_dark_theme}")
            self.apply_theme()
            if hasattr(self, 'theme_toggle_action'):
                self.theme_toggle_action.setChecked(self.force_dark_theme)
                self.theme_toggle_action.setText("Dark Mode" if self.force_dark_theme else "Light Mode")
            log(f"✓ Theme applied: {'Dark' if self.force_dark_theme else 'Light'} mode")
        except Exception as e:
            log(f"⚠ Could not apply theme: {e}")
            import traceback
            traceback.print_exc()

        # Entity import/export
        startup_dialog.set_status("Setting up entity export/import...")
        startup_dialog.set_progress(85)
        try:
            setup_entity_export_import_system(self)
            log("✓ Entity export/import ready")
        except Exception as e:
            log(f"⚠ Could not setup entity export/import: {e}")

        # Patch folder integration
        startup_dialog.set_status("Integrating patch manager...")
        startup_dialog.set_progress(90)
        try:
            from set_patch_folder import integrate_patch_manager
            integrate_patch_manager(self)
            log("✓ Patch manager integrated")
                
            from set_patch_folder import PATCH_CONFIG_FILE
            if not os.path.exists(PATCH_CONFIG_FILE):
                # First run — no config at all; check both folders after startup settles
                QTimer.singleShot(500, self._prompt_first_run_setup)
            elif hasattr(self, 'patch_manager') and not self.patch_manager.is_configured():
                QTimer.singleShot(1000, lambda: self.status_bar.showMessage(
                    "Tip: Set your patch folder via File → Set Patch Folder", 5000))
        except Exception as e:
            log(f"⚠ Could not integrate patch manager: {e}")

        startup_dialog.set_status("Finalizing initialization...")
        startup_dialog.set_progress(95)
        log(f"✓ Editor initialization complete for {game_mode}")

        # Close startup dialog
        startup_dialog.set_progress(100)
        startup_dialog.mark_complete()
        startup_dialog.stop_icon()
        startup_dialog.close()

        # Welcome screen
        try:
            QTimer.singleShot(100, self.show_welcome_message_conditionally)
        except Exception as e:
            print(f"Warning: Could not show welcome message: {e}")

    def _prompt_first_run_setup(self):
        """
        Shown on first run (no patch_config.json).
        Checks patch folder and resource folder independently for the selected game,
        prompting the user to set each one that is missing.
        """
        from set_patch_folder import update_worlds_folder, set_resource_folder
        game_label = "Avatar: The Game" if self.game_mode == "avatar" else "Far Cry 2"

        # --- Patch folder ---
        patch_configured = hasattr(self, 'patch_manager') and self.patch_manager.is_configured()
        if not patch_configured:
            reply = QMessageBox.question(
                self,
                "Welcome — Set Patch Folder",
                f"No patch folder has been configured for {game_label}.\n\n"
                "The patch folder is your game directory containing the "
                "'levels' and/or 'worlds' subdirectories.\n\n"
                "Would you like to set it now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                if hasattr(self, 'patch_manager') and self.patch_manager.set_patch_folder():
                    update_worlds_folder(self.patch_manager, self)
                    self.status_bar.showMessage("Patch folder set.", 3000)
                else:
                    self.status_bar.showMessage(
                        "Patch folder not set. Use File → Set Patch Folder when ready.", 5000)
            else:
                self.status_bar.showMessage(
                    "Tip: Set your patch folder via File → Set Patch Folder", 5000)

        # --- Resource folder ---
        resource_configured = bool(getattr(self, 'resource_folder', None))
        if not resource_configured:
            res_reply = QMessageBox.question(
                self,
                "Set Resource Folder",
                f"No resource folder has been configured for {game_label}.\n\n"
                "The resource folder (e.g. Data_Win32) is used to load 3D models in the editor.\n\n"
                "Would you like to set it now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if res_reply == QMessageBox.StandardButton.Yes:
                set_resource_folder(self)
            else:
                self.status_bar.showMessage(
                    "Tip: Set your resource folder via File → Set Resource Folder", 5000)

        # --- Open level selector if patch folder is now ready ---
        if hasattr(self, 'patch_manager') and self.patch_manager.is_configured():
            QTimer.singleShot(200, self.select_level)

    def capture_canvas_logs(self, startup_dialog):
        """Capture and display canvas initialization logs"""
        import sys
        from io import StringIO
        
        # Create a custom stdout that captures prints
        class TeeOutput:
            def __init__(self, dialog):
                self.terminal = sys.stdout
                self.dialog = dialog
                
            def write(self, message):
                self.terminal.write(message)
                if message.strip():  # Only log non-empty lines
                    self.dialog.append_log(message.strip())
                    QApplication.processEvents()
                    
            def flush(self):
                self.terminal.flush()
        
        # Replace stdout temporarily
        old_stdout = sys.stdout
        sys.stdout = TeeOutput(startup_dialog)
        
        return old_stdout

    def setup_ui(self):
        """Initialize the UI components - UPDATED with game mode support"""
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Create main layout
        main_layout = QVBoxLayout(central_widget)
        
        # Create menu bar
        self.create_menus()
        
        # Create toolbar
        self.create_toolbar()
        
        # Create canvas for editing
        print("Initializing canvas...")
        self.canvas = MapCanvas(self)
        
        # Pass game mode to canvas and editor references
        if hasattr(self.canvas, 'game_mode'):
            self.canvas.game_mode = self.game_mode
        self.canvas.editor = self
        self.canvas.is_fc2_world = (self.game_mode == "farcry2")
        
        main_layout.addWidget(self.canvas)
        
        # Create status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Set status bar message based on game mode
        if self.game_mode == "farcry2":
            self.status_bar.showMessage("Far Cry 2 Mode - Ready to load world")
        else:
            self.status_bar.showMessage("Avatar Mode - Ready to load level")
        
        # CRITICAL: Make sure these are called
        self.create_side_panel()      #This should be here
        self.create_entity_browser()  #And this
        self.create_model_preview_dock()
                        
        # Connect entity selection signal from canvas to handler
        try:
            self.canvas.entitySelected.connect(self.on_entity_selected)
        except Exception as e:
            print(f"Warning: Could not connect entity selection signal: {e}")

        # Connect position update signal for live Statistics/browser refresh
        try:
            self.canvas.position_update.connect(self.on_entity_position_updated)
            self.canvas.angle_update.connect(self.on_entity_angle_updated)
        except Exception as e:
            print(f"Warning: Could not connect canvas signals: {e}")

    def show_main_context_menu(self, event):
        """Main context menu that delegates to the enhanced context menu"""
        # Get the enhanced context menu function that was set up in add_sector_move_to_context_menu
        if hasattr(self.canvas, 'showContextMenu'):
            self.canvas.showContextMenu(event)
        else:
            # Fallback: create a basic context menu
            from PyQt6.QtWidgets import QMenu
            menu = QMenu(self.canvas)
            menu.addAction("No enhanced menu available")
            menu.exec(event.globalPosition().toPoint())

    def show_welcome_message_updated(self):
        """Show welcome message and open visual level selector when Start Modding is pressed"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QCheckBox
        from PyQt6.QtGui import QIcon

        # Create custom dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Welcome to Simplified Map Editor")
        dialog.setMinimumSize(600, 500)
        dialog.resize(600, 500)

        # Set window icon depending on game
        if hasattr(self, "game_mode") and self.game_mode == "farcry2":
            dialog.setWindowIcon(QIcon("icon/fc2_icon.ico"))
        else:
            dialog.setWindowIcon(QIcon("icon/avatar_icon.ico"))

        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)

        # Title
        title_label = QLabel("Simplified Map Editor")
        title_label.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #2196F3; margin-bottom: 10px;"
        )
        layout.addWidget(title_label)

        # Avatar content (full original text)
        avatar_text = """
    <b>Welcome to the Avatar: The Game Level Editor!</b><br><br>

    <b>Quick Start:</b><br>

    1. Click the green <b>"Select Level"</b> button to load a complete level<br>
    2. First: Select your <b>"WORLDS"</b> folder <b>(contains XML files)</b><br>
    3. Second: Select your <b>"LEVELS"</b> folder <b>(contains worldsectors)</b><br>
    4. Start editing entities with full copy/paste support!<br><br>

    <b>Key Features:</b><br>

    <b>Two-step loading:</b> Load both world data and level objects<br>
    <b>Smart entity placement:</b> Automatically places entities in correct files<br>
    <b>Copy/Paste system:</b> Duplicate entities with unique IDs and names<br>
    <b>Sector management:</b> Move entities between different sectors<br>
    <b>Visual editing:</b> 2D mode with gizmo controls<br>
    <b>Entity browser:</b> Color-coded entity browser with type grouping<br><br>

    <b>Keyboard Shortcuts:</b><br>

    <b>Ctrl+O:</b> Select Level (two-step loading)<br>
    <b>Delete:</b> Delete selected entities<br>

    <b>Right-click menu:</b><br>

    Move entities to different sectors<br>
    Copy, paste, and duplicate operations<br>
    View and selection controls<br><br>

    <b>Ready to get started? Click the green "Start Modding!" button!</b><br>
    """

        # Far Cry 2 content (full original text)
        fc2_text = """
    <b>Welcome to the Far Cry 2 World Editor Mode!</b><br><br>

    <b>Quick Start:</b><br>

    1. Click the green <b>"Select World"</b> button to load the main world grid<br>
    2. Choose your <b>"FC2 Worlds"</b> directory containing region XML files<br>
    3. Select one of the <b>25 world regions</b> (5×5 grid) to begin editing<br>
    4. Start editing entities, props, and terrain links!<br><br>

    <b>Key Features:</b><br>

    <b>World Grid System:</b> Edit up to 25 world sectors, each 16×16 regions<br>
    <b>Smart linking:</b> Automatically manages entities across region borders<br>
    <b>Entity Editor:</b> Modify positions, rotations, and properties<br>
    <b>Copy/Paste system:</b> Duplicate entities across world regions<br>
    <b>Visual Editor:</b> Zoom, pan, and select with gizmo support<br><br>

    <b>Keyboard Shortcuts:</b><br>

    <b>Ctrl+O:</b> Load World Grid<br>
    <b>Delete:</b> Delete selected entities<br>
    <b>Ctrl+C / Ctrl+V:</b> Copy and paste between world sectors<br><br>

    <b>Right-click menu:</b><br>

    Move entities between regions<br>
    Duplicate or edit linked props<br>
    Access debug and view controls<br><br>

    <b>Ready to explore the open world? Click the green "Start Modding!" button!</b><br>
    """

        # Choose which content to show
        if hasattr(self, "game_mode") and self.game_mode == "farcry2":
            content_text = fc2_text
            title_label.setStyleSheet(
                "font-size: 24px; font-weight: bold; color: #FF5722; margin-bottom: 10px;"
            )
        else:
            content_text = avatar_text

        # Main content label
        content_label = QLabel(content_text)
        content_label.setWordWrap(True)
        content_label.setStyleSheet("font-size: 13px; line-height: 1.4;")
        layout.addWidget(content_label)

        dont_show_checkbox = QCheckBox("Don't show this welcome screen again")
        apply_checkbox_style(dont_show_checkbox, dark=self.force_dark_theme)
        layout.addWidget(dont_show_checkbox)

        # Button layout
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        start_button = QPushButton("Start Modding!")
        start_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 8px 20px;
                border: none;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)

        # Open LevelSelectorDialog when pressed
        def open_level_selector():
            # Save the "don't show again" preference
            if dont_show_checkbox.isChecked():
                self.theme_settings.set_show_welcome(False)
                print("✓ Welcome screen disabled for future sessions")
            
            dialog.accept()  # close welcome dialog first
            self.select_level() 

        start_button.clicked.connect(open_level_selector)
        button_layout.addWidget(start_button)

        layout.addLayout(button_layout)

        dialog.exec()

    def show_welcome_message_conditionally(self):
        """Show welcome message only if not disabled by user preference"""
        try:
            # Check if user has disabled welcome screen using ThemeSettings
            if not self.theme_settings.get_show_welcome():
                print("Welcome screen disabled by user preference")
                
                # Auto-open level selector if patch folder is configured
                if hasattr(self, 'patch_manager') and self.patch_manager.is_configured():
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(500, lambda: self.select_level())
                return
            
            # Show the welcome message
            self.show_welcome_message_updated()
            
        except Exception as e:
            print(f"Error showing welcome message: {e}")

    def show_about(self):
        """Show about dialog with custom size"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
        
        # Create custom dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("About Simplified Map Editor")
        dialog.setMinimumSize(500, 400)  # Set custom size
        dialog.resize(600, 500)
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        
        # Title
        title_label = QLabel("Simplified Map Editor")
        title_label.setStyleSheet("font-size: 22px; font-weight: bold; color: #2196F3; margin-bottom: 10px;")
        layout.addWidget(title_label)
        
        # Version info
        version_label = QLabel("Version 2.0 - Enhanced Edition")
        version_label.setStyleSheet("font-size: 14px; color: #666; font-style: italic; margin-bottom: 15px;")
        layout.addWidget(version_label)
        
        # Main content
        about_text = """
    <b>A powerful tool for editing Dunia engine level files.</b><br><br>

    <b>Important:</b><br>

    <b>Always backup your level files before editing!</b><br>
    <b>Close the game completely before saving changes.</b><br><br>
        
    <b> Core Features:</b><br>

    Load and edit Avatar: The Game level XML files<br>
    Visual entity editing with 2D view mode<br>
    Smart copy/paste system with automatic ID generation<br>
    Entity browser with <b>color-coded</b> type grouping<br>
    Sector boundary visualization and violation detection<br>
    Move entities between different sectors<br>
    Automatic file format conversion <b>(FCB <-> XML)</b><br>
    Grid configuration support<br><br>

    <b> Designed for:</b><br>

    Avatar: The Game community<br><br>
    
    """
        
        content_label = QLabel(about_text)
        content_label.setWordWrap(True)
        content_label.setStyleSheet("font-size: 13px; line-height: 1.4;")
        layout.addWidget(content_label)
        
        # Button layout
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        close_button = QPushButton("Close")
        close_button.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                padding: 8px 20px;
                border: none;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        close_button.clicked.connect(dialog.accept)
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
        
        # Show dialog
        dialog.exec()

    def create_menus(self):
        """Create the application menu bars - SIMPLIFIED without terrain"""
        # Create file menu
        file_menu = self.menuBar().addMenu("File")
        
        # Main unified load action
        select_level_action = QAction("Select Level... (loads both world and level data)", self)
        select_level_action.triggered.connect(self.select_level)
        select_level_action.setShortcut("Ctrl+O")
        file_menu.addAction(select_level_action)

        # Save Level action (converts to FCB)
        save_level_action = QAction("Save Level (Convert to FCB)", self)
        save_level_action.triggered.connect(self.save_level)
        save_level_action.setShortcut("Ctrl+S")
        file_menu.addAction(save_level_action)
                
        # Add exit action
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        exit_action.setShortcut("Alt+F4")
        file_menu.addAction(exit_action)

        # Create entity tools menu
        edit_menu = self.menuBar().addMenu("Entity Tools")

        entity_editor_action = QAction("Entity Editor", self)
        entity_editor_action.triggered.connect(self.open_entity_editor)
        entity_editor_action.setShortcut("Ctrl+E")
        entity_editor_action.setToolTip("Open Entity Properties Editor (Ctrl+E)")
        edit_menu.addAction(entity_editor_action)

        edit_menu.addSeparator()

        export_entities_action = QAction("Export Entities", self)
        export_entities_action.triggered.connect(self.show_entity_export_dialog)
        export_entities_action.setShortcut("Ctrl+Shift+E")
        export_entities_action.setToolTip("Export selected entities to file")
        edit_menu.addAction(export_entities_action)

        import_entities_action = QAction("Import Entities", self)
        import_entities_action.triggered.connect(self.show_entity_import_dialog)
        import_entities_action.setShortcut("Ctrl+Shift+I")
        import_entities_action.setToolTip("Import entities from file")
        edit_menu.addAction(import_entities_action)

        edit_menu.addSeparator()

        mass_export_action = QAction("Mass Export Level...", self)
        mass_export_action.triggered.connect(self.show_mass_export_dialog)
        mass_export_action.setToolTip("Export all unique entity types from the loaded level to mass_exported_objects/")
        edit_menu.addAction(mass_export_action)

        # Create view menu — StayOpenMenu keeps it open when toggling checkable items
        view_menu = StayOpenMenu("Canvas", self)
        self.menuBar().addMenu(view_menu)

        toggle_mode_menu_action = QAction("Toggle 2D/3D", self)
        toggle_mode_menu_action.triggered.connect(self.toggle_mode)
        toggle_mode_menu_action.setToolTip("Switch between 2D and 3D view")
        view_menu.addAction(toggle_mode_menu_action)

        view_menu.addSeparator()

        # Reset view action
        reset_view_action = QAction("Reset View", self)
        reset_view_action.triggered.connect(self.reset_view)
        reset_view_action.setShortcut("Ctrl+R")
        view_menu.addAction(reset_view_action)
        
        # --- Visibility toggles ---
        toggle_entities_action = QAction("Toggle Entities", self)
        toggle_entities_action.triggered.connect(self.toggle_entities)
        toggle_entities_action.setShortcut("`")
        toggle_entities_action.setCheckable(True)
        toggle_entities_action.setChecked(True)
        view_menu.addAction(toggle_entities_action)

        # Per-source entity filters
        self.toggle_worldsector_action = QAction("  Toggle Worldsector Entities", self)
        self.toggle_worldsector_action.setCheckable(True)
        self.toggle_worldsector_action.setChecked(True)
        self.toggle_worldsector_action.triggered.connect(
            lambda checked: self._set_entity_source_visibility('worldsectors', checked))
        view_menu.addAction(self.toggle_worldsector_action)

        self.toggle_mapsdata_action = QAction("  Toggle Mapsdata Entities", self)
        self.toggle_mapsdata_action.setCheckable(True)
        self.toggle_mapsdata_action.setChecked(True)
        self.toggle_mapsdata_action.triggered.connect(
            lambda checked: self._set_entity_source_visibility('mapsdata', checked))
        view_menu.addAction(self.toggle_mapsdata_action)

        self.toggle_omnis_action = QAction("  Toggle Omnis Entities", self)
        self.toggle_omnis_action.setCheckable(True)
        self.toggle_omnis_action.setChecked(True)
        self.toggle_omnis_action.triggered.connect(
            lambda checked: self._set_entity_source_visibility('omnis', checked))
        view_menu.addAction(self.toggle_omnis_action)

        self.toggle_landmark_action = QAction("  Toggle Landmark Entities", self)
        self.toggle_landmark_action.setCheckable(True)
        self.toggle_landmark_action.setChecked(True)
        self.toggle_landmark_action.triggered.connect(
            lambda checked: self._set_entity_source_visibility('landmark', checked))
        view_menu.addAction(self.toggle_landmark_action)

        # Trigger zones wireframe toggle
        self.toggle_trigger_zones_action = QAction("Toggle Trigger Zones", self)
        self.toggle_trigger_zones_action.setCheckable(True)
        self.toggle_trigger_zones_action.setChecked(True)
        self.toggle_trigger_zones_action.setToolTip("Show/hide trigger volume wireframes in 2D and 3D")
        self.toggle_trigger_zones_action.triggered.connect(
            lambda checked: self._set_trigger_zones_visibility(checked))
        view_menu.addAction(self.toggle_trigger_zones_action)

        view_menu.addSeparator()

        sector_menu_action = QAction("Toggle Sectors", self)
        sector_menu_action.setCheckable(True)
        sector_menu_action.setChecked(True)
        sector_menu_action.triggered.connect(self.toggle_sector_boundaries)
        sector_menu_action.setToolTip("Show/hide sector boundary grid")
        view_menu.addAction(sector_menu_action)

        view_menu.addSeparator()

        self.theme_toggle_action = QAction("Light Mode", self)
        self.theme_toggle_action.triggered.connect(self.toggle_theme)
        self.theme_toggle_action.setCheckable(True)
        self.theme_toggle_action.setChecked(False)
        self.theme_toggle_action.setToolTip("Toggle between Light and Dark theme")
        view_menu.addAction(self.theme_toggle_action)

        view_menu.addSeparator()

        # Lighting controls
        from PyQt6.QtWidgets import QSlider
        from PyQt6.QtCore import Qt as _Qt
        _light_row = QWidget()
        _light_row.setMinimumWidth(300)
        _light_vbox = QVBoxLayout(_light_row)
        _light_vbox.setContentsMargins(12, 6, 12, 6)
        _light_vbox.setSpacing(4)

        # ── Azimuth row ─────────────────────────────────────────────────────
        _az_row = QHBoxLayout()
        _az_row.setSpacing(6)
        _az_row.addWidget(QLabel("Azimuth:"))
        _az_row.addStretch()
        _down_btn = QPushButton("▼")
        _down_btn.setFixedSize(24, 24)
        _down_btn.setToolTip("Decrease azimuth by 5°")
        self._light_angle_spin = QSpinBox()
        self._light_angle_spin.setRange(0, 360)
        self._light_angle_spin.setValue(0)
        self._light_angle_spin.setSuffix("°")
        self._light_angle_spin.setFixedWidth(72)
        self._light_angle_spin.setToolTip(
            "Horizontal compass direction of the sun (0° = front-right)")
        _up_btn = QPushButton("▲")
        _up_btn.setFixedSize(24, 24)
        _up_btn.setToolTip("Increase azimuth by 5°")
        _az_row.addWidget(_down_btn)
        _az_row.addWidget(self._light_angle_spin)
        _az_row.addWidget(_up_btn)
        _light_vbox.addLayout(_az_row)

        self._light_angle_slider = QSlider(_Qt.Orientation.Horizontal)
        self._light_angle_slider.setRange(0, 360)
        self._light_angle_slider.setValue(0)
        self._light_angle_slider.setToolTip("Drag to rotate the sun horizontally")
        _light_vbox.addWidget(self._light_angle_slider)

        # ── Elevation row ────────────────────────────────────────────────────
        _el_row = QHBoxLayout()
        _el_row.setSpacing(6)
        _el_row.addWidget(QLabel("Elevation:"))
        _el_row.addStretch()
        self._light_pitch_spin = QSpinBox()
        self._light_pitch_spin.setRange(0, 360)
        self._light_pitch_spin.setValue(270)
        self._light_pitch_spin.setSuffix("°")
        self._light_pitch_spin.setFixedWidth(72)
        self._light_pitch_spin.setToolTip(
            "Sun elevation (0°=horizon, 90°=overhead, 180°=below ground, 270°=horizon again)")
        _el_row.addWidget(self._light_pitch_spin)
        _light_vbox.addLayout(_el_row)

        self._light_pitch_slider = QSlider(_Qt.Orientation.Horizontal)
        self._light_pitch_slider.setRange(0, 360)
        self._light_pitch_slider.setValue(270)
        self._light_pitch_slider.setToolTip("Drag to change sun height")
        _light_vbox.addWidget(self._light_pitch_slider)

        # ── Day / night cycle ────────────────────────────────────────────────
        from PyQt6.QtWidgets import QCheckBox
        _dn_hdr = QLabel("— Day / Night cycle —")
        _dn_hdr.setStyleSheet("color:#888; margin-top:6px;")
        _light_vbox.addWidget(_dn_hdr)

        _dn_row = QHBoxLayout(); _dn_row.setSpacing(6)
        self._daynight_enable_cb = QCheckBox("Enable")
        self._daynight_enable_cb.setToolTip("Drive sun + sky + bioluminescence from time of day (also: F4)")
        self._daynight_play_btn = QPushButton("▶ Play")
        self._daynight_play_btn.setCheckable(True)
        self._daynight_play_btn.setFixedWidth(80)
        self._daynight_play_btn.setToolTip("Auto-advance the day/night cycle")
        _dn_row.addWidget(self._daynight_enable_cb)
        _dn_row.addStretch()
        _dn_row.addWidget(self._daynight_play_btn)
        _light_vbox.addLayout(_dn_row)

        _t_row = QHBoxLayout(); _t_row.setSpacing(6)
        _t_row.addWidget(QLabel("Time:"))
        _t_row.addStretch()
        self._daynight_time_label = QLabel("12:00")
        self._daynight_time_label.setFixedWidth(48)
        _t_row.addWidget(self._daynight_time_label)
        _light_vbox.addLayout(_t_row)

        self._daynight_time_slider = QSlider(_Qt.Orientation.Horizontal)
        self._daynight_time_slider.setRange(0, 1439)   # minutes in a day
        self._daynight_time_slider.setValue(720)        # noon
        self._daynight_time_slider.setToolTip("Time of day (00:00–23:59)")
        _light_vbox.addWidget(self._daynight_time_slider)

        def _dn_fmt(mins):
            return f"{int(mins) // 60:02d}:{int(mins) % 60:02d}"

        def _on_dn_enable(state):
            if hasattr(self, 'canvas'):
                self.canvas.set_day_night_enabled(state == _Qt.CheckState.Checked.value
                                                  if isinstance(state, int) else bool(state))

        def _on_dn_play(checked):
            self._daynight_play_btn.setText("⏸ Pause" if checked else "▶ Play")
            if checked:
                self._daynight_enable_cb.setChecked(True)
            if hasattr(self, 'canvas'):
                self.canvas.set_daynight_playing(checked)

        def _on_dn_time(mins):
            self._daynight_time_label.setText(_dn_fmt(mins))
            if hasattr(self, 'canvas'):
                self.canvas.set_time_of_day(mins / 1440.0)

        self._daynight_enable_cb.stateChanged.connect(_on_dn_enable)
        self._daynight_play_btn.toggled.connect(_on_dn_play)
        self._daynight_time_slider.valueChanged.connect(_on_dn_time)

        # While playing, the canvas advances time itself; poll it so the slider +
        # clock follow along (block signals to avoid a feedback loop).
        from PyQt6.QtCore import QTimer as _QTimer
        self._daynight_ui_timer = _QTimer(self)
        self._daynight_ui_timer.setInterval(200)

        def _sync_dn_ui():
            c = getattr(self, 'canvas', None)
            if c is None or not getattr(c, 'day_night_enabled', False) or not getattr(c, '_daynight_play', False):
                return
            mins = int(round((c.time_of_day % 1.0) * 1440.0)) % 1440
            self._daynight_time_slider.blockSignals(True)
            self._daynight_time_slider.setValue(mins)
            self._daynight_time_slider.blockSignals(False)
            self._daynight_time_label.setText(_dn_fmt(mins))

        self._daynight_ui_timer.timeout.connect(_sync_dn_ui)
        self._daynight_ui_timer.start()

        _light_widget_action = QWidgetAction(self)
        _light_widget_action.setDefaultWidget(_light_row)
        view_menu.addAction(_light_widget_action)

        # Bidirectional sync helpers
        def _set_light_angle(val):
            self._light_angle_spin.blockSignals(True)
            self._light_angle_slider.blockSignals(True)
            self._light_angle_spin.setValue(val)
            self._light_angle_slider.setValue(val)
            self._light_angle_spin.blockSignals(False)
            self._light_angle_slider.blockSignals(False)
            self._on_light_angle_changed(val)

        def _set_light_pitch(val):
            self._light_pitch_spin.blockSignals(True)
            self._light_pitch_slider.blockSignals(True)
            self._light_pitch_spin.setValue(val)
            self._light_pitch_slider.setValue(val)
            self._light_pitch_spin.blockSignals(False)
            self._light_pitch_slider.blockSignals(False)
            if hasattr(self, 'canvas'):
                self.canvas.set_light_pitch(val)

        _down_btn.clicked.connect(
            lambda: _set_light_angle((self._light_angle_spin.value() - 5) % 361))
        _up_btn.clicked.connect(
            lambda: _set_light_angle((self._light_angle_spin.value() + 5) % 361))
        self._light_angle_spin.valueChanged.connect(_set_light_angle)
        self._light_angle_slider.valueChanged.connect(_set_light_angle)
        self._light_pitch_spin.valueChanged.connect(_set_light_pitch)
        self._light_pitch_slider.valueChanged.connect(_set_light_pitch)

        # Create Tools menu
        tools_menu = self.menuBar().addMenu("Tools")

        # Enable All Sectors action
        enable_sectors_action = QAction("Enable All Sectors...", self)
        enable_sectors_action.triggered.connect(self.open_enable_all_sectors)
        enable_sectors_action.setToolTip("Force all world sectors to stream at once (testing tool)")
        tools_menu.addAction(enable_sectors_action)

        # Create New Sector action
        create_sector_action = QAction("Create New Sector...", self)
        create_sector_action.triggered.connect(self.open_create_sector)
        create_sector_action.setToolTip("Create a new empty worldsector entity file")
        tools_menu.addAction(create_sector_action)

        # Convert Entity Library FCB action
        convert_entitylib_action = QAction("Convert Entity Library FCB...", self)
        convert_entitylib_action.triggered.connect(self.open_convert_entitylibrary)
        convert_entitylib_action.setToolTip("Convert entitylibrary.fcb / entitylibrary_full.fcb to XML (per-file, safe)")
        tools_menu.addAction(convert_entitylib_action)

        # Convert Entity Library XML back to FCB
        convert_entitylib_xml_action = QAction("Convert Entity Library XML to FCB...", self)
        convert_entitylib_xml_action.triggered.connect(self.open_convert_entitylibrary_xml_to_fcb)
        convert_entitylib_xml_action.setToolTip("Convert entitylibrary .converted.xml back to FCB")
        tools_menu.addAction(convert_entitylib_xml_action)

        # Entity Library Browser
        entity_lib_browser_action = QAction("Entity Library Browser...", self)
        entity_lib_browser_action.triggered.connect(self.open_entity_library_browser)
        entity_lib_browser_action.setToolTip("Browse and inspect entitylibrary.fcb.converted.xml files")
        tools_menu.addAction(entity_lib_browser_action)

        tools_menu.addSeparator()

        # Water Editor action
        water_editor_action = QAction("🌊 Water Editor...", self)
        water_editor_action.triggered.connect(self.open_water_editor)
        water_editor_action.setShortcut("Ctrl+W")
        water_editor_action.setToolTip("Open the water editing tool")
        tools_menu.addAction(water_editor_action)


    def create_toolbar(self):
        """Toolbar removed — all actions are in the menu bar."""
        pass

    def setup_mode_indicator(self):
        """Setup mode indicator in status bar"""
        try:
            # Create mode indicator label
            self.mode_label = QLabel(" 2D Mode")
            self.mode_label.setStyleSheet("padding: 2px 10px; font-weight: bold; color: #2196F3;")
            
            # Add to status bar as permanent widget (stays on right side)
            self.status_bar.addPermanentWidget(self.mode_label)
            
            print("Mode indicator added to status bar")
        except Exception as e:
            print(f"Error setting up mode indicator: {e}")

    def _make_collapsible_section(self, title: str, expanded: bool = True):
        """Return (outer_widget, content_layout) for a collapsible panel section."""
        outer = QWidget()
        outer_vlay = QVBoxLayout(outer)
        outer_vlay.setContentsMargins(0, 2, 0, 2)
        outer_vlay.setSpacing(0)

        arrow = "▼" if expanded else "▶"
        toggle_btn = QPushButton(f" {arrow}  {title}")
        toggle_btn.setCheckable(True)
        toggle_btn.setChecked(expanded)
        toggle_btn.setStyleSheet(
            "QPushButton { text-align: left; padding: 4px 6px; font-weight: bold;"
            " font-size: 11px; border-radius: 3px; }"
        )
        outer_vlay.addWidget(toggle_btn)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 4, 4, 4)
        content_layout.setSpacing(4)
        content.setVisible(expanded)
        outer_vlay.addWidget(content)

        def _toggle(checked, btn=toggle_btn, w=content, t=title):
            w.setVisible(checked)
            btn.setText(f" {'▼' if checked else '▶'}  {t}")

        toggle_btn.clicked.connect(_toggle)
        return outer, content_layout

    def create_side_panel(self):
        """Create a dock widget for the side panel controls - 2D Editor"""
        from PyQt6.QtWidgets import QTabWidget, QScrollArea
        dock = QDockWidget("Level Information", self)
        dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)

        dock_widget = QWidget()
        dock_layout = QVBoxLayout(dock_widget)
        dock_layout.setSpacing(4)
        dock_layout.setContentsMargins(4, 4, 4, 4)

        _section_style = (
            "QGroupBox { font-weight: bold; font-size: 11px; border: 1px solid #555;"
            " border-radius: 4px; margin-top: 6px; padding-top: 4px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }"
        )

        # ════════════════════════════════════════════════════════════════════
        # Level Info  (3 tabs)
        # ════════════════════════════════════════════════════════════════════
        level_info_group = QGroupBox("Level Info")
        level_info_group.setStyleSheet(_section_style)
        level_info_vlay = QVBoxLayout(level_info_group)
        level_info_vlay.setContentsMargins(2, 6, 2, 2)
        level_info_vlay.setSpacing(0)

        level_info_tabs = QTabWidget()
        level_info_tabs.setDocumentMode(True)

        # ── Tab 0: Sector Colors ─────────────────────────────────────────────
        sec_tab = QWidget()
        sec_lay = QVBoxLayout(sec_tab)
        sec_lay.setContentsMargins(4, 6, 4, 4)
        sec_lay.setSpacing(3)
        for hex_color, label_text in [
            ("#00C800", "Worldsector"),
            ("#9600FF", "Landmark"),
            ("#FF8C00", "Omnis"),
        ]:
            row = QHBoxLayout()
            row.setContentsMargins(5, 2, 5, 2)
            swatch = QWidget()
            swatch.setFixedSize(18, 18)
            swatch.setStyleSheet(f"background-color:transparent; border:2px solid {hex_color}; border-radius:2px;")
            lbl = QLabel(label_text)
            lbl.setFont(QFont("Arial", 10))
            lbl.setStyleSheet("margin-left:6px;")
            row.addWidget(swatch)
            row.addWidget(lbl)
            row.addStretch()
            sec_lay.addLayout(row)
        sec_lay.addStretch()
        # ── Tab 1: Entity Colors ─────────────────────────────────────────────
        ent_tab = QWidget()
        ent_lay = QVBoxLayout(ent_tab)
        ent_lay.setContentsMargins(4, 6, 4, 4)
        ent_lay.setSpacing(2)
        header_label = QLabel("Entity type color coding:")
        header_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        header_label.setStyleSheet("margin-bottom:4px;")
        ent_lay.addWidget(header_label)
        self.entity_colors_header = header_label
        self.color_legend_labels = []
        self.create_color_legend_item(ent_lay, QColor(52, 152, 255),  "Vehicles")
        self.create_color_legend_item(ent_lay, QColor(46, 255, 113),  "NPCs/Characters")
        self.create_color_legend_item(ent_lay, QColor(255, 200, 100), "Animals/Wildlife")
        self.create_color_legend_item(ent_lay, QColor(255, 76, 60),   "Weapons/Combat")
        self.create_color_legend_item(ent_lay, QColor(255, 156, 18),  "Spawn Points")
        self.create_color_legend_item(ent_lay, QColor(185, 89, 255),  "Mission Objects")
        self.create_color_legend_item(ent_lay, QColor(255, 230, 15),  "Triggers/Zones")
        self.create_color_legend_item(ent_lay, QColor(170, 180, 190), "Props/Structures")
        self.create_color_legend_item(ent_lay, QColor(255, 255, 160), "Lights")
        self.create_color_legend_item(ent_lay, QColor(0, 255, 200),   "Effects/Audio")
        self.create_color_legend_item(ent_lay, QColor(255, 100, 100), "Special Objects")
        self.create_color_legend_item(ent_lay, QColor(130, 130, 130), "Unknown")
        ent_lay.addStretch()
        # ── Tab 2: Statistics ────────────────────────────────────────────────
        stat_tab = QWidget()
        stat_lay = QVBoxLayout(stat_tab)
        stat_lay.setContentsMargins(4, 6, 4, 4)
        stat_lay.setSpacing(2)

        self.entity_count_label = QLabel("Entities: 0")
        self.entity_count_label.setStyleSheet("font-weight:bold;")
        stat_lay.addWidget(self.entity_count_label)

        form = QFormLayout()
        form.setSpacing(2)
        form.setContentsMargins(0, 2, 0, 0)

        self.stat_name_label = QLabel("—")
        self.stat_name_label.setWordWrap(True)
        form.addRow("Name:", self.stat_name_label)

        self.stat_id_label = QLabel("—")
        self.stat_id_label.setWordWrap(True)
        form.addRow("ID:", self.stat_id_label)

        self.stat_type_label = QLabel("—")
        form.addRow("Type:", self.stat_type_label)

        self.stat_source_label = QLabel("—")
        form.addRow("Source:", self.stat_source_label)

        self.stat_map_label = QLabel("—")
        form.addRow("Map:", self.stat_map_label)

        self.stat_pos_label = QLabel("—")
        form.addRow("X,Y,Z:", self.stat_pos_label)

        angles_row = QWidget()
        angles_row_layout = QHBoxLayout(angles_row)
        angles_row_layout.setContentsMargins(0, 0, 0, 0)
        angles_row_layout.setSpacing(4)
        self.stat_angles_label = QLabel("—")
        angles_row_layout.addWidget(self.stat_angles_label, 1)
        self.stat_angles_add_btn = QPushButton("+ Add")
        self.stat_angles_add_btn.setFixedHeight(28)
        self.stat_angles_add_btn.setFixedWidth(62)
        self.stat_angles_add_btn.setToolTip("Add hidAngles field to this entity")
        self.stat_angles_add_btn.clicked.connect(self._add_hidangles_from_stats)
        self.stat_angles_add_btn.hide()
        angles_row_layout.addWidget(self.stat_angles_add_btn)
        form.addRow("Angles:", angles_row)

        stat_lay.addLayout(form)

        self.stat_relations_label = QLabel("")
        self.stat_relations_label.setWordWrap(True)
        self.stat_relations_label.setStyleSheet("margin-top:4px; font-size:10px;")
        self.stat_relations_label.hide()
        stat_lay.addWidget(self.stat_relations_label)
        stat_lay.addStretch()
        level_info_tabs.addTab(stat_tab, "Statistics")
        level_info_tabs.addTab(sec_tab, "Sector Colors")
        level_info_tabs.addTab(ent_tab, "Entity Colors")

        level_info_tabs.setCurrentIndex(0)  # default to Statistics tab
        level_info_vlay.addWidget(level_info_tabs)
        dock_layout.addWidget(level_info_group)

        # ════════════════════════════════════════════════════════════════════
        # Map Tools  (3 tabs)
        # ════════════════════════════════════════════════════════════════════
        terrain_group = QGroupBox("Map Tools")
        terrain_group.setStyleSheet(_section_style)
        terrain_vlay = QVBoxLayout(terrain_group)
        terrain_vlay.setContentsMargins(2, 6, 2, 2)
        terrain_vlay.setSpacing(0)

        terrain_tabs = QTabWidget()
        terrain_tabs.setDocumentMode(True)

        # ── Tab 0: Terrain Editing ───────────────────────────────────────────
        edit_tab = QWidget()
        te_lay = QVBoxLayout(edit_tab)
        te_lay.setContentsMargins(4, 6, 4, 4)
        te_lay.setSpacing(4)

        _te_tools = ['raise', 'lower', 'flatten', 'smooth']
        _te_labels = ['▲ Raise', '▼ Lower', '═ Flatten', '~ Smooth']

        self._te_tab_bar = QTabBar()
        self._te_tab_bar.setExpanding(True)
        for lbl in _te_labels:
            self._te_tab_bar.addTab(lbl)
        te_lay.addWidget(self._te_tab_bar)

        def _te_tab_changed(idx):
            tool = _te_tools[idx]
            if hasattr(self, 'canvas'):
                self.canvas._te_tool = tool
                self.canvas._sync_te_to_dialog()
                self.canvas.update()
            self._te_panel_update_height_visibility()
        self._te_tab_bar.currentChanged.connect(_te_tab_changed)

        brush_label = QLabel("Brush:")
        brush_label.setStyleSheet("font-size: 11px; margin-top: 4px;")
        te_lay.addWidget(brush_label)

        _brush_types = [
            ('circle',    '● Circle'),
            ('square',    '■ Square'),
            ('rectangle', '▬ Rect'),
            ('blur',      '◉ Blur'),
            ('smear',     '~ Smear'),
            ('airbrush',  '✦ Air'),
            ('hill',      '⛰ Hill'),
            ('slope',     '↗ Slope'),
        ]
        self._te_brush_btns = {}

        _btn_style_active   = "QPushButton { background-color: #2255aa; color: #ffffff; border-radius: 3px; font-size: 11px; padding: 2px 4px; }"
        _btn_style_inactive = "QPushButton { background-color: #333333; color: #cccccc; border-radius: 3px; font-size: 11px; padding: 2px 4px; }"

        def _make_brush_btn(key, label, row_layout):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setMinimumHeight(24)
            btn.setStyleSheet(_btn_style_inactive)
            self._te_brush_btns[key] = btn
            row_layout.addWidget(btn)

            def _on_brush(checked, k=key):
                if not checked:
                    btn.blockSignals(True)
                    btn.setChecked(True)
                    btn.blockSignals(False)
                    return
                for bk, bb in self._te_brush_btns.items():
                    bb.blockSignals(True)
                    bb.setChecked(bk == k)
                    bb.setStyleSheet(_btn_style_active if bk == k else _btn_style_inactive)
                    bb.blockSignals(False)
                if hasattr(self, 'canvas'):
                    self.canvas._te_brush_type = k
                    self.canvas._te_prev_hc = None
                    self.canvas.update()
            btn.toggled.connect(_on_brush)

        brush_col = QVBoxLayout(); brush_col.setContentsMargins(0,0,0,0); brush_col.setSpacing(2)
        for row_start in range(0, len(_brush_types), 4):
            row_w = QWidget(); row_lay = QHBoxLayout(row_w); row_lay.setContentsMargins(0,0,0,0); row_lay.setSpacing(2)
            for key, lbl in _brush_types[row_start:row_start + 4]:
                _make_brush_btn(key, lbl, row_lay)
            brush_col.addWidget(row_w)

        brush_col_w = QWidget()
        brush_col_w.setLayout(brush_col)
        te_lay.addWidget(brush_col_w)

        self._te_brush_btns['circle'].setChecked(True)
        self._te_brush_btns['circle'].setStyleSheet(_btn_style_active)

        def _make_len_wid_row(label, default, attr):
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(3)
            lbl_w = QLabel(f"{label}: {default}")
            lbl_w.setFixedWidth(72)
            row_l.addWidget(lbl_w)
            dec_btn = QPushButton("−"); dec_btn.setFixedWidth(24)
            slider  = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(1, 200)
            slider.setValue(default)
            inc_btn = QPushButton("+"); inc_btn.setFixedWidth(24)
            row_l.addWidget(dec_btn)
            row_l.addWidget(slider)
            row_l.addWidget(inc_btn)

            def _changed(v, lw=lbl_w, lb=label, a=attr):
                lw.setText(f"{lb}: {v}")
                if hasattr(self, 'canvas'):
                    setattr(self.canvas, a, v)
                    self.canvas.update()
            slider.valueChanged.connect(_changed)
            dec_btn.clicked.connect(lambda: slider.setValue(slider.value() - 1))
            inc_btn.clicked.connect(lambda: slider.setValue(slider.value() + 1))
            return row_w

        self._te_brush_len_row = _make_len_wid_row("Length", 32, '_te_brush_len')
        self._te_brush_wid_row = _make_len_wid_row("Width",  12, '_te_brush_wid')
        te_lay.addWidget(self._te_brush_len_row)
        te_lay.addWidget(self._te_brush_wid_row)
        self._te_brush_len_row.setVisible(False)
        self._te_brush_wid_row.setVisible(False)

        self._te_brush_angle_row = _make_len_wid_row("Angle°", 0, '_te_slope_angle')
        _angle_slider = self._te_brush_angle_row.findChild(QSlider)
        if _angle_slider:
            _angle_slider.setRange(0, 359)
            _angle_slider.setValue(0)
        te_lay.addWidget(self._te_brush_angle_row)
        self._te_brush_angle_row.setVisible(False)

        def _update_len_wid_visibility():
            brush = getattr(getattr(self, 'canvas', None), '_te_brush_type', 'circle')
            is_rect  = brush == 'rectangle'
            is_slope = brush == 'slope'
            self._te_brush_len_row.setVisible(is_rect or is_slope)
            self._te_brush_wid_row.setVisible(is_rect or is_slope)
            self._te_brush_angle_row.setVisible(is_slope)
            self._te_size_row_w.setVisible(not is_slope)

        for _bk, _bb in self._te_brush_btns.items():
            _bb.toggled.connect(lambda *_: _update_len_wid_visibility())

        self._te_size_row_w = QWidget()
        size_row = QHBoxLayout(self._te_size_row_w)
        size_row.setContentsMargins(0, 0, 0, 0)
        size_row.setSpacing(3)
        self._te_panel_size_lbl = QLabel("Size: 20")
        self._te_panel_size_lbl.setFixedWidth(68)
        size_row.addWidget(self._te_panel_size_lbl)
        sz_dec = QPushButton("−"); sz_dec.setFixedWidth(24)
        self._te_panel_size_slider = QSlider(Qt.Orientation.Horizontal)
        self._te_panel_size_slider.setRange(1, 150)
        self._te_panel_size_slider.setValue(20)
        sz_inc = QPushButton("+"); sz_inc.setFixedWidth(24)
        size_row.addWidget(sz_dec)
        size_row.addWidget(self._te_panel_size_slider)
        size_row.addWidget(sz_inc)
        te_lay.addWidget(self._te_size_row_w)

        def _te_size_changed(v):
            self._te_panel_size_lbl.setText(f"Size: {v}")
            if hasattr(self, 'canvas'):
                self.canvas._te_size = v
                self.canvas._sync_te_to_dialog()
        self._te_panel_size_slider.valueChanged.connect(_te_size_changed)
        sz_dec.clicked.connect(lambda: self._te_panel_size_slider.setValue(self._te_panel_size_slider.value() - 1))
        sz_inc.clicked.connect(lambda: self._te_panel_size_slider.setValue(self._te_panel_size_slider.value() + 1))

        str_row = QHBoxLayout()
        str_row.setSpacing(3)
        self._te_panel_str_lbl = QLabel("Str: 30%")
        self._te_panel_str_lbl.setFixedWidth(68)
        str_row.addWidget(self._te_panel_str_lbl)
        str_dec = QPushButton("−"); str_dec.setFixedWidth(24)
        self._te_panel_str_slider = QSlider(Qt.Orientation.Horizontal)
        self._te_panel_str_slider.setRange(1, 100)
        self._te_panel_str_slider.setValue(30)
        str_inc = QPushButton("+"); str_inc.setFixedWidth(24)
        str_row.addWidget(str_dec)
        str_row.addWidget(self._te_panel_str_slider)
        str_row.addWidget(str_inc)
        te_lay.addLayout(str_row)

        def _te_str_changed(v):
            self._te_panel_str_lbl.setText(f"Str: {v}%")
            if hasattr(self, 'canvas'):
                self.canvas._te_strength = v
                self.canvas._sync_te_to_dialog()
        self._te_panel_str_slider.valueChanged.connect(_te_str_changed)
        str_dec.clicked.connect(lambda: self._te_panel_str_slider.setValue(self._te_panel_str_slider.value() - 1))
        str_inc.clicked.connect(lambda: self._te_panel_str_slider.setValue(self._te_panel_str_slider.value() + 1))

        self._te_panel_height_row = QWidget()
        h_row = QHBoxLayout(self._te_panel_height_row)
        h_row.setContentsMargins(0, 0, 0, 0)
        h_row.setSpacing(4)
        h_row.addWidget(QLabel("Height:"))
        self._te_panel_height_edit = QLineEdit("100.0")
        self._te_panel_height_edit.setFixedWidth(70)
        self._te_panel_height_edit.setToolTip("Target height for Flatten tool")
        h_row.addWidget(self._te_panel_height_edit)
        h_row.addStretch()
        te_lay.addWidget(self._te_panel_height_row)
        self._te_panel_height_row.setVisible(False)

        def _te_height_changed(text):
            try:
                v = max(0.0, min(511.0, float(text)))
                if hasattr(self, 'canvas'):
                    self.canvas._te_target_h = v
                    self.canvas.update()
            except ValueError:
                pass
        self._te_panel_height_edit.textChanged.connect(_te_height_changed)

        sr_row = QHBoxLayout()
        sr_row.setSpacing(4)
        self._te_panel_save_btn = QPushButton("💾 Save")
        self._te_panel_save_btn.setMinimumHeight(28)
        self._te_panel_save_btn.setToolTip("Save terrain edits to disk")
        self._te_panel_save_btn.setStyleSheet(
            "QPushButton { background-color: #1a7a3a; color: #90ffb0; border-radius: 3px; }"
            "QPushButton:hover { background-color: #22993f; }"
            "QPushButton:disabled { color: #557755; background-color: #1a3320; }"
        )
        self._te_panel_refresh_btn = QPushButton("↺ Refresh")
        self._te_panel_refresh_btn.setMinimumHeight(28)
        self._te_panel_refresh_btn.setToolTip("Reload terrain heightmap and 3D model")
        self._te_panel_refresh_btn.setStyleSheet(
            "QPushButton { background-color: #1a3c6e; color: #90c0ff; border-radius: 3px; }"
            "QPushButton:hover { background-color: #234f90; }"
        )
        sr_row.addWidget(self._te_panel_save_btn)
        sr_row.addWidget(self._te_panel_refresh_btn)
        te_lay.addLayout(sr_row)

        def _te_save_clicked():
            if hasattr(self, 'canvas'):
                self.canvas._save_terrain_data()
                self.canvas.update()

        def _te_refresh_clicked():
            if hasattr(self, 'canvas'):
                self.canvas._refresh_full_terrain()
                self.canvas.update()

        self._te_panel_save_btn.clicked.connect(_te_save_clicked)
        self._te_panel_refresh_btn.clicked.connect(_te_refresh_clicked)
        te_lay.addStretch()
        terrain_tabs.addTab(edit_tab, "Terrain Editing")

        # ── Tab 1: Terrain Painting ──────────────────────────────────────────
        paint_tab = QWidget()
        paint_lay = QVBoxLayout(paint_tab)
        paint_lay.setContentsMargins(4, 6, 4, 4)
        paint_lay.setSpacing(4)

        from PyQt6.QtWidgets import QButtonGroup, QSizePolicy, QScrollArea, QGridLayout
        from PyQt6.QtGui import QImage, QPixmap, QIcon
        from PyQt6.QtCore import QSize
        import numpy as _np_tp
        import os as _os_tp

        # ── Inner tabs: Mask / Diffuse / Color ───────────────────────────────
        tp_inner_tabs = QTabWidget()
        tp_inner_tabs.setDocumentMode(True)
        paint_lay.addWidget(tp_inner_tabs, stretch=1)

        # ── MASK TAB ─────────────────────────────────────────────────────────
        mask_tab_w = QWidget()
        mask_tab_lay = QVBoxLayout(mask_tab_w)
        mask_tab_lay.setContentsMargins(4, 8, 4, 4)
        mask_tab_lay.setSpacing(6)

        mask_tab_lay.addWidget(
            QLabel("Paint Channel:", styleSheet="font-size:10px; color:#bbb;"))

        _TP_BTN_COLORS = [
            ("R",   (220,  30,  30), (255, 255, 255)),
            ("G",   ( 30, 200,  30), (  0,   0,   0)),
            ("B",   ( 30,  80, 220), (255, 255, 255)),
            ("BLK", (  0,   0,   0), (200, 200, 200)),
        ]
        self._tp_ch_btns = []
        self._tp_last_mask_ch = 0
        ch_row = QHBoxLayout(); ch_row.setSpacing(4)

        def _make_tp_btn_style(bg, fg, selected):
            border = "3px solid #fff" if selected else "1px solid #555"
            return (
                f"QPushButton {{ background-color: rgb({bg[0]},{bg[1]},{bg[2]});"
                f" color: rgb({fg[0]},{fg[1]},{fg[2]}); border: {border};"
                f" border-radius: 3px; font-weight: bold; font-size: 11px; }}"
                f"QPushButton:hover {{ border: 2px solid #ccc; }}"
            )

        def _tp_ch_select(idx):
            _TP_CHANNEL_COLORS = [
                (255, 0, 0, 0),   # R  — only layer 0 weight, A stays 0
                (0, 255, 0, 0),   # G  — only layer 1 weight
                (0, 0, 255, 0),   # B  — only layer 2 weight
                (0, 0, 0, 255),   # BLK — only layer 3 (alpha) weight
            ]
            self._tp_last_mask_ch = idx
            if hasattr(self, 'canvas'):
                self.canvas._tp_paint_channel = idx
                self.canvas._te_paint_color   = _TP_CHANNEL_COLORS[idx]
                self.canvas._tp_stamp_tex      = None
            for j, (btn, (_, bg, fg)) in enumerate(zip(self._tp_ch_btns, _TP_BTN_COLORS)):
                btn.setStyleSheet(_make_tp_btn_style(bg, fg, j == idx))

        for i, (label, bg, fg) in enumerate(_TP_BTN_COLORS):
            btn = QPushButton(label)
            btn.setMinimumHeight(34)
            btn.setStyleSheet(_make_tp_btn_style(bg, fg, i == 0))
            btn.clicked.connect(lambda checked, idx=i: _tp_ch_select(idx))
            ch_row.addWidget(btn)
            self._tp_ch_btns.append(btn)
        mask_tab_lay.addLayout(ch_row)

        # ── Brush shape selector ─────────────────────────────────────────────
        mask_tab_lay.addWidget(
            QLabel("Brush Shape:", styleSheet="font-size:10px; color:#bbb;"))

        _SHAPES = [
            ('⬤', 'circle',   'Circle (soft Gaussian)'),
            ('■', 'square',   'Square'),
            ('◆', 'diamond',  'Diamond'),
            ('▲', 'triangle', 'Triangle'),
        ]

        _shape_ss_on  = ("QPushButton { background:#1a3a6a; color:#fff; border:2px solid #4a9fff;"
                         " border-radius:4px; font-size:16px; }")
        _shape_ss_off = ("QPushButton { background:#252535; color:#aaa; border:1px solid #444;"
                         " border-radius:4px; font-size:16px; }"
                         "QPushButton:hover { border-color:#777; }")

        self._tp_all_shape_btn_sets = []

        def _tp_shape_select(key):
            if hasattr(self, 'canvas'):
                self.canvas._tp_brush_shape = key
                self.canvas.update()
            for btn_set in self._tp_all_shape_btn_sets:
                for btn, (_, sk, _tt) in zip(btn_set, _SHAPES):
                    btn.setStyleSheet(_shape_ss_on if sk == key else _shape_ss_off)

        def _make_shape_row(parent_layout):
            row = QHBoxLayout(); row.setSpacing(4)
            btns = []
            for sym, key, tip in _SHAPES:
                btn = QPushButton(sym)
                btn.setMinimumHeight(36)
                btn.setToolTip(tip)
                btn.setStyleSheet(_shape_ss_on if key == 'circle' else _shape_ss_off)
                btn.clicked.connect(lambda checked, k=key: _tp_shape_select(k))
                row.addWidget(btn)
                btns.append(btn)
            parent_layout.addLayout(row)
            self._tp_all_shape_btn_sets.append(btns)
            return btns

        self._tp_shape_btns = _make_shape_row(mask_tab_lay)
        mask_tab_lay.addStretch()
        tp_inner_tabs.addTab(mask_tab_w, "Mask")

        # ── DIFFUSE TAB ──────────────────────────────────────────────────────
        diff_tab_w = QWidget()
        diff_tab_lay = QVBoxLayout(diff_tab_w)
        diff_tab_lay.setContentsMargins(4, 6, 4, 4)
        diff_tab_lay.setSpacing(4)

        diff_tab_lay.addWidget(
            QLabel("Texture Catalog", styleSheet="font-size:10px; color:#bbb; font-weight:bold;"))

        _ASSETS_DIR = _os_tp.path.join(
            _os_tp.path.dirname(_os_tp.path.abspath(__file__)),
            'canvas', 'assets', 'painting_textures'
        )
        _CACHE_DIR  = _os_tp.path.join(_ASSETS_DIR, '_cache')
        _THUMB_SZ   = 72   # larger thumbnail for sharpness

        def _load_xbt_pixmap(xbt_name):
            """Return a QPixmap thumbnail for an XBT file (uses cached PNG if available)."""
            name   = _os_tp.path.splitext(xbt_name)[0]
            cached = _os_tp.path.join(_CACHE_DIR, name + '.png')
            try:
                from PIL import Image as _PIL
                import io as _io
                if _os_tp.path.exists(cached):
                    img = _PIL.open(cached)
                else:
                    with open(_os_tp.path.join(_ASSETS_DIR, xbt_name), 'rb') as _f:
                        raw = _f.read()
                    if raw[:4] == b'TBX\x00':
                        ds = raw.find(b'DDS ')
                        raw = raw[ds:] if ds != -1 else raw
                    img = _PIL.open(_io.BytesIO(raw))
                img.load()
                img = img.convert('RGBA').resize((_THUMB_SZ, _THUMB_SZ), _PIL.Resampling.NEAREST)
                arr = _np_tp.ascontiguousarray(_np_tp.array(img))
                qi  = QImage(arr.data, _THUMB_SZ, _THUMB_SZ,
                             _THUMB_SZ * 4, QImage.Format.Format_RGBA8888)
                return QPixmap.fromImage(qi.copy())
            except Exception:
                return None

        def _load_xbt_stamp(xbt_name):
            """Load full-res XBT as (H,W,4) uint8 numpy array for stamp painting."""
            cached = _os_tp.path.join(_CACHE_DIR,
                                      _os_tp.path.splitext(xbt_name)[0] + '.png')
            try:
                from PIL import Image as _PIL
                import io as _io
                if _os_tp.path.exists(cached):
                    img = _PIL.open(cached).convert('RGBA')
                else:
                    with open(_os_tp.path.join(_ASSETS_DIR, xbt_name), 'rb') as _f:
                        raw = _f.read()
                    if raw[:4] == b'TBX\x00':
                        ds = raw.find(b'DDS ')
                        raw = raw[ds:] if ds != -1 else raw
                    img = _PIL.open(_io.BytesIO(raw)).convert('RGBA')
                img.load()
                return _np_tp.array(img, dtype=_np_tp.uint8)
            except Exception:
                return None

        def _ensure_cache():
            """Use texconv.exe to convert XBT→PNG thumbnails into _cache/."""
            import subprocess, tempfile
            _os_tp.makedirs(_CACHE_DIR, exist_ok=True)
            texconv = _os_tp.path.join(
                _os_tp.path.dirname(_os_tp.path.abspath(__file__)),
                'tools', 'texconv.exe'
            )
            if not _os_tp.path.exists(texconv):
                return
            for xf in _os_tp.listdir(_ASSETS_DIR):
                if not xf.lower().endswith('.xbt'):
                    continue
                name   = _os_tp.path.splitext(xf)[0]
                cached = _os_tp.path.join(_CACHE_DIR, name + '.png')
                if _os_tp.path.exists(cached):
                    continue
                try:
                    with open(_os_tp.path.join(_ASSETS_DIR, xf), 'rb') as _f:
                        raw = _f.read()
                    if raw[:4] == b'TBX\x00':
                        ds = raw.find(b'DDS ')
                        raw = raw[ds:] if ds != -1 else raw
                    with tempfile.NamedTemporaryFile(
                            suffix='.dds', delete=False, dir=_CACHE_DIR) as tf:
                        tf.write(raw); tmp_dds = tf.name
                    subprocess.run(
                        [texconv, '-f', 'R8G8B8A8_UNORM', '-ft', 'png',
                         '-y', '-o', _CACHE_DIR, tmp_dds],
                        capture_output=True, timeout=30,
                        creationflags=0x08000000
                    )
                    _os_tp.unlink(tmp_dds)
                    gen = _os_tp.path.join(
                        _CACHE_DIR,
                        _os_tp.path.splitext(_os_tp.path.basename(tmp_dds))[0] + '.png'
                    )
                    if _os_tp.path.exists(gen):
                        _os_tp.rename(gen, cached)
                except Exception as _e:
                    print(f"[TexCatalog] cache {xf}: {_e}")

        _ensure_cache()

        cat_scroll = QScrollArea()
        cat_scroll.setWidgetResizable(True)
        cat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        cat_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        cat_grid_w  = QWidget()
        cat_grid    = QGridLayout(cat_grid_w)
        cat_grid.setSpacing(4)
        cat_grid.setContentsMargins(2, 2, 2, 2)
        cat_scroll.setWidget(cat_grid_w)
        diff_tab_lay.addWidget(cat_scroll, stretch=1)

        _cat_grp = QButtonGroup(cat_grid_w)
        _cat_grp.setExclusive(True)
        _cat_btn_ss = (
            "QPushButton { background:#252535; color:#aaa; border:1px solid #444;"
            " border-radius:3px; font-size:8px; padding:2px; }"
            "QPushButton:checked { border:2px solid #4a9fff; background:#1a3558; }"
            "QPushButton:hover:!checked { border-color:#777; }"
        )

        if _os_tp.path.isdir(_ASSETS_DIR):
            xbt_files = sorted(f for f in _os_tp.listdir(_ASSETS_DIR)
                               if f.lower().endswith('.xbt'))
            COLS = 4
            for _i, _xf in enumerate(xbt_files):
                _pix  = _load_xbt_pixmap(_xf)
                _name = _os_tp.path.splitext(_xf)[0]
                _btn  = QPushButton()
                _btn.setCheckable(True)
                _btn.setFixedSize(_THUMB_SZ + 4, _THUMB_SZ + 16)
                _btn.setToolTip(_name)
                _btn.setStyleSheet(_cat_btn_ss)
                if _pix:
                    _btn.setIcon(QIcon(_pix))
                    _btn.setIconSize(QSize(_THUMB_SZ, _THUMB_SZ))
                else:
                    _btn.setText(_name[:10])
                _cat_grp.addButton(_btn)
                cat_grid.addWidget(_btn, _i // COLS, _i % COLS)

                def _on_cat(_checked, _xname=_xf):
                    if hasattr(self, 'canvas'):
                        self.canvas._tp_stamp_tex = _load_xbt_stamp(_xname)

                _btn.clicked.connect(_on_cat)

        # ── Brush Shape ──────────────────────────────────────────────────────
        diff_tab_lay.addWidget(
            QLabel("Brush Shape:", styleSheet="font-size:10px; color:#bbb;"))
        _make_shape_row(diff_tab_lay)

        # ── Tile size slider (world meters per texture repeat) ────────────────
        # Slider int v → v * 0.5 meters (range 0.5m–16m)
        tile_row = QHBoxLayout(); tile_row.setSpacing(3)
        self._tp_tile_lbl = QLabel("Tile: 2.0m"); self._tp_tile_lbl.setFixedWidth(68)
        tile_row.addWidget(self._tp_tile_lbl)
        _tile_dec = QPushButton("−"); _tile_dec.setFixedWidth(24)
        self._tp_tile_slider = QSlider(Qt.Orientation.Horizontal)
        self._tp_tile_slider.setRange(1, 32); self._tp_tile_slider.setValue(4)
        _tile_inc = QPushButton("+"); _tile_inc.setFixedWidth(24)
        tile_row.addWidget(_tile_dec)
        tile_row.addWidget(self._tp_tile_slider)
        tile_row.addWidget(_tile_inc)
        diff_tab_lay.addLayout(tile_row)

        def _tile_changed(v):
            m = v * 0.5
            self._tp_tile_lbl.setText(f"Tile: {m:.1f}m")
            if hasattr(self, 'canvas'):
                self.canvas._tp_tile_meters = m

        self._tp_tile_slider.valueChanged.connect(_tile_changed)
        _tile_dec.clicked.connect(
            lambda: self._tp_tile_slider.setValue(self._tp_tile_slider.value() - 1))
        _tile_inc.clicked.connect(
            lambda: self._tp_tile_slider.setValue(self._tp_tile_slider.value() + 1))

        tp_inner_tabs.addTab(diff_tab_w, "Diffuse")

        # ── COLOR TAB ────────────────────────────────────────────────────────
        col_tab_w = QWidget()
        col_tab_lay = QVBoxLayout(col_tab_w)
        col_tab_lay.setContentsMargins(4, 8, 4, 4)
        col_tab_lay.setSpacing(6)

        col_tab_lay.addWidget(
            QLabel("Greyscale Brush:", styleSheet="font-size:10px; color:#bbb;"))

        _gray_bar = QLabel()
        _gray_bar.setFixedHeight(22)
        _gray_bar.setStyleSheet(
            "QLabel { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #000000,stop:1 #ffffff); border-radius:2px; }"
        )
        col_tab_lay.addWidget(_gray_bar)

        _gray_val_lbl = QLabel("Value: 128")
        _gray_val_lbl.setStyleSheet("font-size:10px; color:#aaa;")
        _gray_slider = QSlider(Qt.Orientation.Horizontal)
        _gray_slider.setRange(0, 255)
        _gray_slider.setValue(128)

        def _gray_changed(v):
            _gray_val_lbl.setText(f"Value: {v}")
            if hasattr(self, 'canvas'):
                self.canvas._te_paint_color = (v, v, v, 255)
                self.canvas._tp_stamp_tex   = None

        _gray_slider.valueChanged.connect(_gray_changed)

        col_tab_lay.addWidget(_gray_slider)
        col_tab_lay.addWidget(_gray_val_lbl)

        col_tab_lay.addWidget(
            QLabel("Brush Shape:", styleSheet="font-size:10px; color:#bbb;"))
        _make_shape_row(col_tab_lay)

        col_tab_lay.addStretch()
        tp_inner_tabs.addTab(col_tab_w, "Color")

        # Inner tab change → switch canvas texture type
        def _tp_inner_tab_changed(idx):
            keys = ['mask', 'diffuse', 'color']
            if hasattr(self, 'canvas'):
                self.canvas._switch_paint_texture(keys[idx])
                if keys[idx] != 'diffuse':
                    self.canvas._tp_stamp_tex = None
            if keys[idx] == 'mask':
                _tp_ch_select(self._tp_last_mask_ch)

        tp_inner_tabs.currentChanged.connect(_tp_inner_tab_changed)

        # ── Shared: Size / Strength / Save / Refresh ─────────────────────────
        tp_size_row = QHBoxLayout(); tp_size_row.setSpacing(3)
        self._tp_size_lbl = QLabel("Size: 20"); self._tp_size_lbl.setFixedWidth(68)
        tp_size_row.addWidget(self._tp_size_lbl)
        tp_sz_dec = QPushButton("−"); tp_sz_dec.setFixedWidth(24)
        self._tp_size_slider = QSlider(Qt.Orientation.Horizontal)
        self._tp_size_slider.setRange(1, 150); self._tp_size_slider.setValue(20)
        tp_sz_inc = QPushButton("+"); tp_sz_inc.setFixedWidth(24)
        tp_size_row.addWidget(tp_sz_dec)
        tp_size_row.addWidget(self._tp_size_slider)
        tp_size_row.addWidget(tp_sz_inc)
        paint_lay.addLayout(tp_size_row)

        tp_str_row = QHBoxLayout(); tp_str_row.setSpacing(3)
        self._tp_str_lbl = QLabel("Str: 30%"); self._tp_str_lbl.setFixedWidth(68)
        tp_str_row.addWidget(self._tp_str_lbl)
        tp_str_dec = QPushButton("−"); tp_str_dec.setFixedWidth(24)
        self._tp_str_slider = QSlider(Qt.Orientation.Horizontal)
        self._tp_str_slider.setRange(1, 100); self._tp_str_slider.setValue(30)
        tp_str_inc = QPushButton("+"); tp_str_inc.setFixedWidth(24)
        tp_str_row.addWidget(tp_str_dec)
        tp_str_row.addWidget(self._tp_str_slider)
        tp_str_row.addWidget(tp_str_inc)
        paint_lay.addLayout(tp_str_row)

        tp_fth_row = QHBoxLayout(); tp_fth_row.setSpacing(3)
        self._tp_fth_lbl = QLabel("Feather: 50%"); self._tp_fth_lbl.setFixedWidth(68)
        tp_fth_row.addWidget(self._tp_fth_lbl)
        tp_fth_dec = QPushButton("−"); tp_fth_dec.setFixedWidth(24)
        self._tp_fth_slider = QSlider(Qt.Orientation.Horizontal)
        self._tp_fth_slider.setRange(0, 100); self._tp_fth_slider.setValue(50)
        tp_fth_inc = QPushButton("+"); tp_fth_inc.setFixedWidth(24)
        tp_fth_row.addWidget(tp_fth_dec)
        tp_fth_row.addWidget(self._tp_fth_slider)
        tp_fth_row.addWidget(tp_fth_inc)
        paint_lay.addLayout(tp_fth_row)

        tex_btn_row = QHBoxLayout(); tex_btn_row.setSpacing(4)
        save_tex_btn = QPushButton("Save")
        save_tex_btn.setMinimumHeight(28)
        save_tex_btn.setToolTip("Save painted textures back to XBT files")
        save_tex_btn.setStyleSheet(
            "QPushButton { background-color: #1a7a3a; color: #90ffb0; border-radius: 3px; }"
            "QPushButton:hover { background-color: #22993f; }"
        )
        refresh_tex_btn = QPushButton("Refresh")
        refresh_tex_btn.setMinimumHeight(28)
        refresh_tex_btn.setToolTip("Reload atlas textures from disk")
        refresh_tex_btn.setStyleSheet(
            "QPushButton { background-color: #2a5a80; color: #90d0ff; border-radius: 3px; }"
            "QPushButton:hover { background-color: #3070a0; }"
        )
        tex_btn_row.addWidget(save_tex_btn)
        tex_btn_row.addWidget(refresh_tex_btn)
        paint_lay.addLayout(tex_btn_row)

        terrain_tabs.addTab(paint_tab, "Terrain Painting (experimental)")


        # Callbacks
        def _tp_size_changed(v):
            self._tp_size_lbl.setText(f"Size: {v}")
            if hasattr(self, 'canvas'):
                self.canvas._te_size = v

        def _tp_str_changed(v):
            self._tp_str_lbl.setText(f"Str: {v}%")
            if hasattr(self, 'canvas'):
                self.canvas._te_strength = v

        def _tp_fth_changed(v):
            self._tp_fth_lbl.setText(f"Feather: {v}%")
            if hasattr(self, 'canvas'):
                self.canvas._tp_feather = v

        def _save_tex_clicked():
            if hasattr(self, 'canvas'):
                self.canvas._save_texture_paint()

        def _refresh_tex_clicked():
            if hasattr(self, 'canvas'):
                self.canvas._refresh_texture_paint()

        self._tp_size_slider.valueChanged.connect(_tp_size_changed)
        tp_sz_dec.clicked.connect(lambda: self._tp_size_slider.setValue(self._tp_size_slider.value() - 1))
        tp_sz_inc.clicked.connect(lambda: self._tp_size_slider.setValue(self._tp_size_slider.value() + 1))
        self._tp_str_slider.valueChanged.connect(_tp_str_changed)
        tp_str_dec.clicked.connect(lambda: self._tp_str_slider.setValue(self._tp_str_slider.value() - 1))
        tp_str_inc.clicked.connect(lambda: self._tp_str_slider.setValue(self._tp_str_slider.value() + 1))
        self._tp_fth_slider.valueChanged.connect(_tp_fth_changed)
        tp_fth_dec.clicked.connect(lambda: self._tp_fth_slider.setValue(self._tp_fth_slider.value() - 1))
        tp_fth_inc.clicked.connect(lambda: self._tp_fth_slider.setValue(self._tp_fth_slider.value() + 1))
        save_tex_btn.clicked.connect(_save_tex_clicked)
        refresh_tex_btn.clicked.connect(_refresh_tex_clicked)

        terrain_vlay.addWidget(terrain_tabs)
        dock_layout.addWidget(terrain_group)

        # ── Stretch ──────────────────────────────────────────────────────────
        dock_layout.addStretch()

        dock.setWidget(dock_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.controls_dock = dock
        dock.setVisible(True)
        dock.show()

        if hasattr(self, "apply_theme"):
            dark = getattr(self, "force_dark_theme", False)
            color = "white" if dark else "black"
            self.entity_colors_header.setStyleSheet(f"color:{color}; margin-bottom:4px;")
            for label in self.color_legend_labels:
                label.setStyleSheet(f"color:{color};")

        print("Side panel created for 2D level editor")

    def _te_panel_update_height_visibility(self):
        """Show/hide the height row based on whether the Flatten tab is active."""
        if not hasattr(self, '_te_panel_height_row'):
            return
        idx = self._te_tab_bar.currentIndex() if hasattr(self, '_te_tab_bar') else 0
        # index 2 = flatten
        self._te_panel_height_row.setVisible(idx == 2)

    def update_mode_indicator(self):
        """Update the mode indicator in the status bar"""
        if not hasattr(self, 'canvas'):
            return
        
        if not hasattr(self, 'mode_label'):
            return
        
        try:
            if self.canvas.mode == 0:  # 2D mode
                self.mode_label.setText("2D Mode")
                self.mode_label.setStyleSheet("padding: 2px 10px; font-weight: bold; color: #2196F3;")
            else:  # 3D mode
                self.mode_label.setText("3D Mode")
                self.mode_label.setStyleSheet("padding: 2px 10px; font-weight: bold; color: #FF9800;")
        except Exception as e:
            print(f"Error updating mode indicator: {e}")

    # def setup_cache_menu(self):
    #     """Setup cache management menu"""
    #     from PyQt6.QtWidgets import QMessageBox
    #     from PyQt6.QtGui import QAction
        
    #     cache_menu = self.menuBar().addMenu("Cache")
        
    #     # View cache statistics
    #     stats_action = QAction("View Cache Statistics", self)
    #     stats_action.triggered.connect(self.show_cache_statistics)
    #     stats_action.setShortcut("Ctrl+Shift+C")
    #     cache_menu.addAction(stats_action)
        
    #     cache_menu.addSeparator()
        
    #     # Clear all caches
    #     clear_all_action = QAction("Clear All Caches", self)
    #     clear_all_action.triggered.connect(self.clear_all_caches)
    #     cache_menu.addAction(clear_all_action)
        
    #     # Clear specific cache types
    #     clear_fcb_action = QAction("Clear FCB Conversion Cache", self)
    #     clear_fcb_action.triggered.connect(lambda: self.cache.clear_cache_type('fcb_conversion'))
    #     cache_menu.addAction(clear_fcb_action)
        
    #     clear_xml_action = QAction("Clear XML Parsing Cache", self)
    #     clear_xml_action.triggered.connect(lambda: self.cache.clear_cache_type('xml_parsing'))
    #     cache_menu.addAction(clear_xml_action)
        
    #     clear_disk_action = QAction("Clear Disk Cache", self)
    #     clear_disk_action.triggered.connect(self.clear_disk_cache)
    #     cache_menu.addAction(clear_disk_action)
        
    #     cache_menu.addSeparator()
        
    #     # Toggle caching
    #     self.cache_enabled_action = QAction("Enable Caching", self)
    #     self.cache_enabled_action.setCheckable(True)
    #     self.cache_enabled_action.setChecked(self.cache.enabled)
    #     self.cache_enabled_action.triggered.connect(self.toggle_caching)
    #     cache_menu.addAction(self.cache_enabled_action)

    def toggle_mode(self):
        """Switch between 2D and 3D modes."""
        if self.current_mode == "2D":
            self.current_mode = "3D"
            self.canvas.set_3d_mode(True)  # tell the canvas to switch to 3D rendering
        else:
            self.current_mode = "2D"
            self.canvas.set_3d_mode(False)  # back to 2D rendering

        # Update the mode indicator label
        self.setup_mode_indicator()

    def show_cache_statistics(self):
        """Show cache statistics dialog"""
        stats = self.cache.get_cache_stats()
        
        msg = f"""Cache Statistics
    ================

    Status: {'ENABLED' if stats['enabled'] else 'DISABLED'}
    Memory Usage: {stats['memory_usage_mb']:.1f} / {stats['max_memory_mb']:.1f} MB

    Cache Sizes:
    FCB Conversions: {stats['cache_sizes']['fcb_conversion']} entries
    XML Parsing: {stats['cache_sizes']['xml_parsing']} entries
    Object Parsing: {stats['cache_sizes']['object_parsing']} entries
    Terrain: {stats['cache_sizes']['terrain']} entries

    Hit Rates:
    FCB: {stats['hit_rates']['fcb']['rate']:.1f}% ({stats['hit_rates']['fcb']['hits']} hits, {stats['hit_rates']['fcb']['misses']} misses)
    XML: {stats['hit_rates']['xml']['rate']:.1f}% ({stats['hit_rates']['xml']['hits']} hits, {stats['hit_rates']['xml']['misses']} misses)
    Objects: {stats['hit_rates']['object']['rate']:.1f}% ({stats['hit_rates']['object']['hits']} hits, {stats['hit_rates']['object']['misses']} misses)
    Terrain: {stats['hit_rates']['terrain']['rate']:.1f}% ({stats['hit_rates']['terrain']['hits']} hits, {stats['hit_rates']['terrain']['misses']} misses)

    Overall Hit Rate: {stats['overall_hit_rate']:.1f}%

    Total Requests: {stats['total_hits'] + stats['total_misses']}
    Total Cache Hits: {stats['total_hits']}
    Total Cache Misses: {stats['total_misses']}
    """
        
        QMessageBox.information(self, "Cache Statistics", msg)

    def clear_all_caches(self):
        """Clear all caches with confirmation"""
        reply = QMessageBox.question(
            self,
            "Clear All Caches",
            "This will clear all cached data. Cache will be rebuilt on next load.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.cache.clear_all_caches()
            QMessageBox.information(self, "Success", "All caches cleared!")

    def clear_disk_cache(self):
        """Clear disk cache with confirmation"""
        reply = QMessageBox.question(
            self,
            "Clear Disk Cache",
            "This will clear all cached terrain images and temp files.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.cache.clear_disk_cache()
            QMessageBox.information(self, "Success", "Disk cache cleared!")

    def toggle_caching(self):
        """Toggle caching on/off"""
        if self.cache_enabled_action.isChecked():
            self.cache.enable_caching()
        else:
            self.cache.disable_caching()

    def create_color_legend_item(self, layout, color, text):
        """Create a color sample with label for the legend - ENHANCED"""
        item_layout = QHBoxLayout()
        item_layout.setContentsMargins(5, 2, 5, 2)  # Tighter margins
        
        # Create color sample with improved styling
        color_sample = QWidget()
        color_sample.setFixedSize(14, 14)  # Slightly smaller for better fit
        color_sample.setAutoFillBackground(True)
        
        # Set color with subtle border
        palette = color_sample.palette()
        palette.setColor(color_sample.backgroundRole(), color)
        color_sample.setPalette(palette)
        
        # Add subtle border for better definition
        color_sample.setStyleSheet(f"""
            QWidget {{
                background-color: {color.name()};
                border: 1px solid rgba(0, 0, 0, 0.2);
                border-radius: 2px;
            }}
        """)
        
        # Create label with improved styling (color will be set by theme)
        label = QLabel(text)
        label.setFont(QFont("Arial", 10))
        label.setStyleSheet("margin-left: 8px;")
        
        # Store reference for theme updates
        if hasattr(self, 'color_legend_labels'):
            self.color_legend_labels.append(label)
        
        # Add to layout with label
        item_layout.addWidget(color_sample)
        item_layout.addWidget(label)
        item_layout.addStretch()  # Push everything to the left
        
        layout.addLayout(item_layout)

    def open_enable_all_sectors(self):
        """Open the Enable All Sectors tool"""
        import importlib.util
        import os
        script_path = os.path.join(os.path.dirname(__file__), "tools", "enable_all_sectors.py")
        spec = importlib.util.spec_from_file_location("enable_all_sectors", script_path)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self._enable_sectors_win = mod.EnableAllSectorsWindow()
        # Pre-fill the folder if a level is loaded
        if hasattr(self, 'worldsectors_path') and self.worldsectors_path:
            self._enable_sectors_win.dir_edit.setText(self.worldsectors_path)
        self._enable_sectors_win.show()

    def open_create_sector(self):
        """Open the Create New Sector tool"""
        import importlib.util
        import os
        script_path = os.path.join(os.path.dirname(__file__), "tools", "create_sector.py")
        spec = importlib.util.spec_from_file_location("create_sector", script_path)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        ws = getattr(self, 'worldsectors_path', '') or ''
        # Use the same worlds_folder the editor already resolved at load time
        wg = ''
        if getattr(self, 'worlds_folder', None):
            candidate = os.path.join(self.worlds_folder, 'generated')
            if os.path.isdir(candidate):
                wg = candidate
        self._create_sector_win = mod.CreateSectorWindow(
            worldsectors_dir=ws,
            worlds_generated_dir=wg,
        )
        self._create_sector_win.sectors_created.connect(self._load_new_worldsectors)
        self._create_sector_win.show()

    def _load_new_worldsectors(self, sector_ids: list):
        """Load newly created worldsector XMLs into the editor without a full reload."""
        import xml.etree.ElementTree as ET
        if not getattr(self, 'worldsectors_path', None):
            return
        loaded = []
        for sid in sector_ids:
            xml_path = os.path.join(
                self.worldsectors_path,
                f"worldsector{sid}.data.fcb.converted.xml"
            )
            if not os.path.exists(xml_path):
                print(f"New sector XML not found: {os.path.basename(xml_path)}")
                continue
            try:
                tree = ET.parse(xml_path)
                if not hasattr(self, 'worldsectors_trees'):
                    self.worldsectors_trees = {}
                self.worldsectors_trees[xml_path] = tree
                loaded.append(sid)
                print(f"Loaded new sector {sid} into editor")
            except Exception as e:
                print(f"Failed to load sector {sid} XML: {e}")
        if loaded:
            print(f"New sectors loaded into editor: {loaded}")
            if hasattr(self, 'canvas'):
                self.canvas.update()

    def open_water_editor(self):
        """Open the water editor dialog with live 3D preview"""
        from canvas.water_editor_dialog import show_water_editor
        
        # Get terrain renderer and canvas if available
        terrain_renderer = None
        canvas = None
        
        if hasattr(self, 'canvas'):
            canvas = self.canvas
            if hasattr(self.canvas, 'terrain_renderer'):
                terrain_renderer = self.canvas.terrain_renderer
        
        # Show the dialog with live preview support
        show_water_editor(parent=self, terrain_renderer=terrain_renderer, canvas=canvas)
        
        # Refresh canvas after editing
        if canvas:
            canvas.update()

    def open_convert_entitylibrary(self):
        """Convert entitylibrary_full.fcb files to .fcb.converted.xml (per-file, not batch).
        User chooses a specific .fcb file or a folder to scan."""
        print("[EntityLib] open_convert_entitylibrary called")
        import os
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit,
            QPushButton, QProgressBar, QFileDialog, QMessageBox
        )
        from PyQt6.QtCore import QThread, pyqtSignal

        print(f"[EntityLib] can_convert_fcb = {self.file_converter.can_convert_fcb}")
        if not self.file_converter.can_convert_fcb:
            QMessageBox.warning(self, "Convert Entity Library",
                                "FCBConverter.exe not found.\nCannot convert FCB files.")
            return

        # --- Step 1: ask user to pick a file or folder ---
        # Use QMessageBox with custom buttons so no nested event loop is needed.
        start_dir = ""
        if hasattr(self, 'patch_manager') and hasattr(self.patch_manager, 'patch_folder'):
            start_dir = self.patch_manager.patch_folder

        msg = QMessageBox(self)
        msg.setWindowTitle("Convert Entity Library FCB")
        msg.setText("Select an entitylibrary.fcb or entitylibrary_full.fcb file,\nor a folder to scan for one:")
        btn_file   = msg.addButton("Select File...",   QMessageBox.ButtonRole.ActionRole)
        btn_folder = msg.addButton("Select Folder...", QMessageBox.ButtonRole.ActionRole)
        msg.addButton(QMessageBox.StandardButton.Cancel)
        msg.exec()

        clicked = msg.clickedButton()
        print(f"[EntityLib] picker clicked: {clicked.text() if clicked else 'None'}")
        if clicked == btn_file:
            path, _ = QFileDialog.getOpenFileName(
                self, "Select Entity Library FCB", start_dir, "FCB Files (*.fcb)")
            if not path:
                print("[EntityLib] No file selected, returning")
                return
            mode, selected_path = 'file', path
        elif clicked == btn_folder:
            path = QFileDialog.getExistingDirectory(
                self, "Select Folder Containing Entity Library FCB", start_dir,
                QFileDialog.Option.ShowDirsOnly)
            if not path:
                print("[EntityLib] No folder selected, returning")
                return
            mode, selected_path = 'folder', path
        else:
            print("[EntityLib] Cancelled")
            return

        print(f"[EntityLib] mode={mode}, path={selected_path}")

        # --- Step 2: build list of files to convert ---
        full_fcbs = []
        display_root = selected_path  # for relative path display

        _allowed_fcb = {'entitylibrary.fcb', 'entitylibrary_full.fcb'}

        if mode == 'file':
            fname = os.path.basename(selected_path).lower()
            if fname not in _allowed_fcb:
                QMessageBox.warning(self, "Convert Entity Library",
                                    "Please select entitylibrary.fcb or entitylibrary_full.fcb.")
                return
            full_fcbs = [selected_path]
            display_root = os.path.dirname(selected_path)
        else:
            for dirpath, _, filenames in os.walk(selected_path):
                for fname in filenames:
                    if fname.lower() in _allowed_fcb:
                        full_fcbs.append(os.path.join(dirpath, fname))

        print(f"[EntityLib] full_fcbs={full_fcbs}")
        if not full_fcbs:
            QMessageBox.information(self, "Convert Entity Library",
                                    "No entitylibrary.fcb or entitylibrary_full.fcb files found.")
            return

        needs_convert = [f for f in full_fcbs if not os.path.exists(f + '.converted.xml')]
        print(f"[EntityLib] needs_convert={needs_convert}")

        info_lines = [f"Found {len(full_fcbs)} file(s):\n"]
        for f in full_fcbs:
            status = "needs conversion" if f in needs_convert else "already converted"
            try:
                rel = os.path.relpath(f, display_root)
            except ValueError:
                rel = f
            info_lines.append(f"  [{status}]  {rel}")

        if not needs_convert:
            QMessageBox.information(self, "Convert Entity Library",
                                    "\n".join(info_lines) + "\n\nAll files already converted.")
            return

        info_lines.append(f"\nConvert {len(needs_convert)} file(s) now?")
        reply = QMessageBox.question(self, "Convert Entity Library",
                                     "\n".join(info_lines),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            print("[EntityLib] User said No")
            return

        print(f"[EntityLib] Starting worker for {len(needs_convert)} file(s)")
        # --- Step 3: worker thread ---
        class _Worker(QThread):
            log_sig  = pyqtSignal(str)
            done_sig = pyqtSignal(int, int)

            def __init__(self, converter, files, root):
                super().__init__()
                self._converter = converter
                self._files = files
                self._root = root
                # Use the rebuilt fixed binary (has ByteLen guard in FindInDictionarySkip)
                # so the entitylibrary crash is fixed without touching main convert_folder.
                _fixed = os.path.join(
                    converter.tools_path, "FCBConverter-master", "bin",
                    "net7.0-windows", "win-x64", "FCBConverter.exe")
                self._fcb_path = _fixed if os.path.exists(_fixed) else converter.fcb_converter_path

            def run(self):
                print(f"[EntityLib Worker] run() started, {len(self._files)} file(s), binary={self._fcb_path}")
                ok = fail = 0
                for fcb_path in self._files:
                    try:
                        rel = os.path.relpath(fcb_path, self._root)
                    except ValueError:
                        rel = os.path.basename(fcb_path)

                    out_path = fcb_path + '.converted.xml'
                    folder  = os.path.dirname(fcb_path)
                    fname   = os.path.basename(fcb_path)
                    print(f"[EntityLib Worker] converting: {fcb_path}")
                    self.log_sig.emit(f"--- {rel} ---")
                    self.log_sig.emit(f"File : {fcb_path}")
                    self.log_sig.emit(f"Size : {os.path.getsize(fcb_path)} bytes")

                    try:
                        # Batch mode with the fixed binary — avoids single-file hang on large FCBs
                        # and the FindInDictionarySkip crash on short fields.
                        cmd = [self._fcb_path,
                               f"-source={folder}", f"-filter=*{fname}", "-fc2"]
                        print(f"Batch FCBConverter (entitylib): {' '.join(cmd)}")
                        result = subprocess.run(
                            cmd, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=600, **self._converter._hidden_window_kwargs())
                        stdout = result.stdout.decode(errors='replace').strip()
                        stderr = result.stderr.decode(errors='replace').strip()
                        print(f"[EntityLib Worker] exit={result.returncode}")
                        if stdout:
                            print(f"[EntityLib Worker] STDOUT:\n{stdout}")
                        if stderr:
                            print(f"[EntityLib Worker] STDERR:\n{stderr}")
                        if os.path.exists(out_path):
                            ok += 1
                            self.log_sig.emit(f"OK   : {out_path} ({os.path.getsize(out_path)} bytes)")
                        else:
                            fail += 1
                            self.log_sig.emit("FAIL : output not created — check console for FCBConverter output")
                    except Exception as exc:
                        fail += 1
                        self.log_sig.emit(f"ERROR: {exc}")
                    self.log_sig.emit("")
                self.done_sig.emit(ok, fail)

        # --- Step 4: progress dialog ---
        dlg = QDialog(self)
        dlg.setWindowTitle("Convert Entity Library FCB")
        dlg.setMinimumSize(520, 300)
        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel(f"Converting {len(needs_convert)} file(s) — please wait..."))

        log_box = QPlainTextEdit()
        log_box.setReadOnly(True)
        log_box.setMaximumBlockCount(1000)
        layout.addWidget(log_box)

        bar = QProgressBar()
        bar.setRange(0, 0)
        layout.addWidget(bar)

        close_btn = QPushButton("Close")
        close_btn.setEnabled(False)
        close_btn.clicked.connect(dlg.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        worker = _Worker(self.file_converter, needs_convert, display_root)

        def _on_log(msg):
            log_box.appendPlainText(msg)

        def _on_done(succeeded, failed):
            bar.setRange(0, 1)
            bar.setValue(1)
            close_btn.setEnabled(True)
            log_box.appendPlainText(f"\nFinished: {succeeded} succeeded, {failed} failed.")
            if failed == 0:
                dlg.setWindowTitle("Convert Entity Library FCB — Complete")
            else:
                dlg.setWindowTitle(f"Convert Entity Library FCB — {failed} failed")

        worker.log_sig.connect(_on_log)
        worker.done_sig.connect(_on_done)
        worker.start()
        dlg.exec()
        worker.wait()

    def open_convert_entitylibrary_xml_to_fcb(self):
        """Convert entitylibrary .fcb.converted.xml files back to .fcb."""
        print("[EntityLib XML→FCB] open_convert_entitylibrary_xml_to_fcb called")
        import os
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit,
            QPushButton, QProgressBar, QFileDialog, QMessageBox
        )
        from PyQt6.QtCore import QThread, pyqtSignal

        if not self.file_converter.can_convert_fcb:
            QMessageBox.warning(self, "Convert Entity Library XML to FCB",
                                "FCBConverter.exe not found.\nCannot convert files.")
            return

        start_dir = ""
        if hasattr(self, 'patch_manager') and hasattr(self.patch_manager, 'patch_folder'):
            start_dir = self.patch_manager.patch_folder

        msg = QMessageBox(self)
        msg.setWindowTitle("Convert Entity Library XML to FCB")
        msg.setText("Select an entitylibrary .fcb.converted.xml file,\nor a folder to scan for one:")
        btn_file   = msg.addButton("Select File...",   QMessageBox.ButtonRole.ActionRole)
        btn_folder = msg.addButton("Select Folder...", QMessageBox.ButtonRole.ActionRole)
        msg.addButton(QMessageBox.StandardButton.Cancel)
        msg.exec()

        _allowed_xml = {'entitylibrary.fcb.converted.xml', 'entitylibrary_full.fcb.converted.xml'}

        clicked = msg.clickedButton()
        if clicked == btn_file:
            path, _ = QFileDialog.getOpenFileName(
                self, "Select Entity Library XML", start_dir,
                "Converted XML Files (*.xml);;All Files (*)")
            if not path:
                return
            if os.path.basename(path).lower() not in _allowed_xml:
                QMessageBox.warning(self, "Convert Entity Library XML to FCB",
                                    "Please select entitylibrary.fcb.converted.xml or entitylibrary_full.fcb.converted.xml.")
                return
            mode, selected_path = 'file', path
        elif clicked == btn_folder:
            path = QFileDialog.getExistingDirectory(
                self, "Select Folder Containing Entity Library XML", start_dir,
                QFileDialog.Option.ShowDirsOnly)
            if not path:
                return
            mode, selected_path = 'folder', path
        else:
            return

        # Build list of XML files to convert
        xml_files = []
        display_root = selected_path

        if mode == 'file':
            xml_files = [selected_path]
            display_root = os.path.dirname(selected_path)
        else:
            for dirpath, _, filenames in os.walk(selected_path):
                for fname in filenames:
                    if fname.lower() in _allowed_xml:
                        xml_files.append(os.path.join(dirpath, fname))

        if not xml_files:
            QMessageBox.information(self, "Convert Entity Library XML to FCB",
                                    "No entitylibrary.fcb.converted.xml or entitylibrary_full.fcb.converted.xml files found.")
            return

        info_lines = [f"Found {len(xml_files)} file(s):\n"]
        for f in xml_files:
            try:
                rel = os.path.relpath(f, display_root)
            except ValueError:
                rel = f
            info_lines.append(f"  {rel}")

        info_lines.append(f"\nConvert {len(xml_files)} file(s) to FCB now?")
        reply = QMessageBox.question(self, "Convert Entity Library XML to FCB",
                                     "\n".join(info_lines),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        class _Worker(QThread):
            log_sig  = pyqtSignal(str)
            done_sig = pyqtSignal(int, int)

            def __init__(self, converter, files, root):
                super().__init__()
                self._converter = converter
                self._files = files
                self._root = root
                _fixed = os.path.join(
                    converter.tools_path, "FCBConverter-master", "bin",
                    "net7.0-windows", "win-x64", "FCBConverter.exe")
                self._fcb_path = _fixed if os.path.exists(_fixed) else converter.fcb_converter_path

            def run(self):
                ok = fail = 0
                for xml_path in self._files:
                    try:
                        rel = os.path.relpath(xml_path, self._root)
                    except ValueError:
                        rel = os.path.basename(xml_path)

                    self.log_sig.emit(f"--- {rel} ---")
                    self.log_sig.emit(f"File : {xml_path}")
                    self.log_sig.emit(f"Size : {os.path.getsize(xml_path)} bytes")

                    # Derive target FCB path: strip .converted.xml → .fcb
                    fname = os.path.basename(xml_path)
                    folder = os.path.dirname(xml_path)
                    fcb_name = fname[:-len('.converted.xml')]   # e.g. entitylibrary_full.fcb
                    fcb_path = os.path.join(folder, fcb_name)
                    base_name = os.path.splitext(fcb_name)[0]  # entitylibrary_full
                    new_fcb_path = os.path.join(folder, base_name + "_new.fcb")

                    try:
                        if os.path.exists(new_fcb_path):
                            os.remove(new_fcb_path)

                        # Single-file invocation: FCBConverter <file.fcb.converted.xml> -fc2 -enablecompress
                        # FCBConverter detects the .converted.xml suffix and outputs <base>_new.fcb
                        cmd = [self._fcb_path, xml_path, "-fc2", "-enablecompress"]
                        print(f"[EntityLib XML→FCB] cmd: {' '.join(cmd)}")
                        result = subprocess.run(
                            cmd, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=600, **self._converter._hidden_window_kwargs())
                        stdout = result.stdout.decode(errors='replace').strip()
                        stderr = result.stderr.decode(errors='replace').strip()
                        print(f"[EntityLib XML→FCB] exit={result.returncode}")
                        if stdout:
                            print(f"[EntityLib XML→FCB] STDOUT:\n{stdout}")
                            self.log_sig.emit(f"OUT  : {stdout[:300]}")
                        if stderr:
                            print(f"[EntityLib XML→FCB] STDERR:\n{stderr}")
                            self.log_sig.emit(f"ERR  : {stderr[:300]}")

                        if os.path.exists(new_fcb_path):
                            if os.path.exists(fcb_path):
                                os.remove(fcb_path)
                            os.rename(new_fcb_path, fcb_path)
                            ok += 1
                            self.log_sig.emit(f"OK   : {fcb_path} ({os.path.getsize(fcb_path)} bytes)")
                        else:
                            fail += 1
                            self.log_sig.emit(f"FAIL : {new_fcb_path} not created (exit={result.returncode})")
                    except Exception as exc:
                        fail += 1
                        self.log_sig.emit(f"ERROR: {exc}")
                        print(f"[EntityLib XML→FCB] Exception: {exc}")
                    self.log_sig.emit("")
                self.done_sig.emit(ok, fail)

        dlg = QDialog(self)
        dlg.setWindowTitle("Convert Entity Library XML to FCB")
        dlg.setMinimumSize(520, 300)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(f"Converting {len(xml_files)} file(s) — please wait..."))

        log_box = QPlainTextEdit()
        log_box.setReadOnly(True)
        log_box.setMaximumBlockCount(1000)
        layout.addWidget(log_box)

        bar = QProgressBar()
        bar.setRange(0, 0)
        layout.addWidget(bar)

        close_btn = QPushButton("Close")
        close_btn.setEnabled(False)
        close_btn.clicked.connect(dlg.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        worker = _Worker(self.file_converter, xml_files, display_root)

        def _on_log(msg):
            log_box.appendPlainText(msg)

        def _on_done(succeeded, failed):
            bar.setRange(0, 1)
            bar.setValue(1)
            close_btn.setEnabled(True)
            log_box.appendPlainText(f"\nFinished: {succeeded} succeeded, {failed} failed.")
            if failed == 0:
                dlg.setWindowTitle("Convert Entity Library XML to FCB — Complete")
            else:
                dlg.setWindowTitle(f"Convert Entity Library XML to FCB — {failed} failed")

        worker.log_sig.connect(_on_log)
        worker.done_sig.connect(_on_done)
        worker.start()
        dlg.exec()
        worker.wait()

    def open_entity_library_browser(self, file_path=None):
        """Open the Entity Library Browser dialog."""
        from entity_library_browser import EntityLibraryBrowserDialog
        dlg = EntityLibraryBrowserDialog(self, file_path=file_path)
        dlg.setWindowModality(Qt.WindowModality.NonModal)
        dlg.show()

    def open_terrain_editor(self):
        """Open the terrain editor as a non-modal window."""
        from canvas.terrain_editor_dialog import show_terrain_editor

        terrain_renderer = None
        canvas = None
        if hasattr(self, 'canvas'):
            canvas = self.canvas
            if hasattr(self.canvas, 'terrain_renderer'):
                terrain_renderer = self.canvas.terrain_renderer

        if not hasattr(self, '_terrain_editor_window') or self._terrain_editor_window is None:
            self._terrain_editor_window = show_terrain_editor(
                parent=self,
                terrain_renderer=terrain_renderer,
                canvas=canvas,
                sdat_path=getattr(self, 'sdat_path', None),
            )
        else:
            self._terrain_editor_window.show()
            self._terrain_editor_window.raise_()
            self._terrain_editor_window.activateWindow()

    def single_folder_fallback(self, selected_folder):
        """
        Fallback to single folder loading when user chooses not to do manual selection
        """
        print(f"\n=== SINGLE FOLDER FALLBACK ===")
        
        # Try to determine what type of folder this is
        worlds_valid = self.validate_worlds_folder(selected_folder)
        levels_valid = self.validate_levels_folder(selected_folder)
        
        if worlds_valid and levels_valid:
            # Folder contains both types
            level_info = {
                'name': os.path.basename(selected_folder),
                'worlds_path': selected_folder,
                'levels_path': selected_folder,
                'base_folder': os.path.dirname(selected_folder)
            }
            print(f"Folder contains both world and level data")
            self.load_complete_level(level_info)
            
        elif worlds_valid:
            # Only worlds data
            level_info = {
                'name': os.path.basename(selected_folder),
                'worlds_path': selected_folder,
                'levels_path': None,
                'base_folder': os.path.dirname(selected_folder)
            }
            print(f"Folder contains world data only")
            
            QMessageBox.information(
                self,
                "Worlds Data Only",
                f"Loading world data (entities) only from:\n{os.path.basename(selected_folder)}\n\n"
                f"No level objects (worldsectors) will be loaded."
            )
            self.load_complete_level(level_info)
            
        elif levels_valid:
            # Only levels data
            level_info = {
                'name': os.path.basename(selected_folder),
                'worlds_path': None,
                'levels_path': selected_folder,
                'base_folder': os.path.dirname(selected_folder)
            }
            print(f"Folder contains level data only")
            
            QMessageBox.information(
                self,
                "Level Objects Only",
                f"Loading level objects (worldsectors) only from:\n{os.path.basename(selected_folder)}\n\n"
                f"No world entities will be loaded."
            )
            self.load_complete_level(level_info)
            
        else:
            # No valid data found
            QMessageBox.warning(
                self,
                "No Valid Data Found",
                f"The selected folder doesn't contain valid level data:\n{selected_folder}\n\n"
                f"Please select a folder containing:\n"
                f"World data: XML files (mapsdata.xml, etc.)\n"
                f"Level data: worldsectors folder with .data.fcb files"
            )

    def validate_worlds_folder(self, folder_path):
        """Check if folder contains world data (XML files) - FIXED"""
        if not os.path.exists(folder_path):
            return False
        
        # Use the correct method name from your original code
        world_files = self.find_xml_files_enhanced(folder_path)  # Changed from find_xml_files_enhanced
        return len(world_files) > 0

    def validate_levels_folder(self, folder_path):
        """Check if folder contains level data (worldsectors) - FIXED"""
        if not os.path.exists(folder_path):
            return False
        
        # Use the correct method name from your original code
        worldsectors_info = self.find_worldsectors_folder_enhanced(folder_path)
        return worldsectors_info is not None

    def load_omnis_data(self, file_path):
        """Load omnis data from XML file"""
        try:
            print(f"Loading omnis data from: {os.path.basename(file_path)}")
            
            # Parse the XML file
            tree = ET.parse(file_path)
            self.omnis_tree = tree
            import io as _io_main
            _buf = _io_main.BytesIO()
            tree.write(_buf, encoding='utf-8', xml_declaration=True)
            self._main_clean_hashes['omnis'] = str(hash(_buf.getvalue()))
            root = tree.getroot()

            # Track entities loaded from this file
            entities_loaded = 0

            # Find all Entity objects in the omnis file (FCBConverter format)
            for entity_elem in root.findall(".//object[@name='Entity']"):
                try:
                    entity_id = "Unknown"
                    id_field = entity_elem.find("./field[@name='disEntityId']")
                    if id_field is not None:
                        entity_id = (id_field.get('value-Id64') or id_field.get('value-String') or "Unknown").strip()

                    entity_name = ""
                    name_field = entity_elem.find("./field[@name='hidName']")
                    if name_field is not None:
                        entity_name = _get_str_val(name_field)
                    if not entity_name:
                        creature_field = entity_elem.find("./field[@name='tplCreatureType']")
                        if creature_field is not None:
                            entity_name = _get_str_val(creature_field)
                    if not entity_name:
                        entity_name = "Unnamed"

                    pos_field = entity_elem.find("./field[@name='hidPos']")
                    if pos_field is None:
                        pos_field = entity_elem.find("./field[@name='hidPos_precise']")

                    if pos_field is not None:
                        pos_value = pos_field.get('value-Vector3', '')
                        if pos_value:
                            try:
                                coords = pos_value.split(',')
                                if len(coords) == 3:
                                    x = float(coords[0])
                                    y = float(coords[1])
                                    z = float(coords[2])

                                    entity = Entity(entity_id, entity_name, x, y, z, entity_elem)
                                    entity.source_file = "omnis"
                                    entity.source_file_path = file_path

                                    if self.grid_config and self.grid_config.maps:
                                        entity.map_name = self.determine_entity_map(entity)

                                    self.entities.append(entity)
                                    entities_loaded += 1
                            except (ValueError, IndexError):
                                pass

                except Exception as e:
                    print(f"Error parsing omnis entity: {str(e)}")
            
            print(f"Loaded {entities_loaded} entities from omnis file")
            return True
            
        except Exception as e:
            print(f"Error loading omnis data from {file_path}: {str(e)}")
            return False

    def load_managers_data(self, file_path):
        """Load managers data from XML file"""
        try:
            print(f"Loading managers data from: {os.path.basename(file_path)}")
            
            # Parse the XML file
            tree = ET.parse(file_path)
            self.managers_tree = tree
            import io as _io_main
            _buf = _io_main.BytesIO()
            tree.write(_buf, encoding='utf-8', xml_declaration=True)
            self._main_clean_hashes['managers'] = str(hash(_buf.getvalue()))
            root = tree.getroot()

            # Track entities loaded from this file
            entities_loaded = 0

            # Find all Entity objects in the managers file (FCBConverter format)
            for entity_elem in root.findall(".//object[@name='Entity']"):
                try:
                    entity_id = "Unknown"
                    id_field = entity_elem.find("./field[@name='disEntityId']")
                    if id_field is not None:
                        entity_id = (id_field.get('value-Id64') or id_field.get('value-String') or "Unknown").strip()

                    entity_name = ""
                    name_field = entity_elem.find("./field[@name='hidName']")
                    if name_field is not None:
                        entity_name = _get_str_val(name_field)
                    if not entity_name:
                        creature_field = entity_elem.find("./field[@name='tplCreatureType']")
                        if creature_field is not None:
                            entity_name = _get_str_val(creature_field)
                    if not entity_name:
                        entity_name = "Unnamed"

                    pos_field = entity_elem.find("./field[@name='hidPos']")
                    if pos_field is None:
                        pos_field = entity_elem.find("./field[@name='hidPos_precise']")

                    if pos_field is not None:
                        pos_value = pos_field.get('value-Vector3', '')
                        if pos_value:
                            try:
                                coords = pos_value.split(',')
                                if len(coords) == 3:
                                    x = float(coords[0])
                                    y = float(coords[1])
                                    z = float(coords[2])

                                    entity = Entity(entity_id, entity_name, x, y, z, entity_elem)
                                    entity.source_file = "managers"
                                    entity.source_file_path = file_path

                                    if self.grid_config and self.grid_config.maps:
                                        entity.map_name = self.determine_entity_map(entity)

                                    self.entities.append(entity)
                                    entities_loaded += 1
                            except (ValueError, IndexError):
                                pass

                except Exception as e:
                    print(f"Error parsing managers entity: {str(e)}")
            
            print(f"Loaded {entities_loaded} entities from managers file")

            # Pre-build vPos lookup: entity_id -> [vPos field elements]
            # Done once here so per-selection lookups are O(1) dict gets.
            vpos_map = {}
            root2 = self.managers_tree.getroot()
            for info in root2.findall(".//object[@name='PawnInteractionInfo']"):
                ef = info.find("field[@name='entEntity']")
                vf = info.find("field[@name='vPos']")
                if ef is not None and vf is not None:
                    eid = ef.get('value-Id64', '').strip()
                    if eid:
                        vpos_map.setdefault(eid, []).append(vf)
            self.managers_vpos_map = vpos_map
            print(f"managers.xml: {len(vpos_map)} entities linked to PawnInteractionInfo vPos")

            return True

        except Exception as e:
            print(f"Error loading managers data from {file_path}: {str(e)}")
            return False

    def load_sectordep_data(self, file_path):
        """Load sector dependencies data from XML file"""
        try:
            print(f"Loading sectordep data from: {os.path.basename(file_path)}")
            
            # Parse the XML file
            tree = ET.parse(file_path)
            self.sectordep_tree = tree
            import io as _io_main
            _buf = _io_main.BytesIO()
            tree.write(_buf, encoding='utf-8', xml_declaration=True)
            self._main_clean_hashes['sectorsdep'] = str(hash(_buf.getvalue()))
            root = tree.getroot()

            # Track entities loaded from this file
            entities_loaded = 0

            # Find all Entity objects in the sectordep file (FCBConverter format)
            for entity_elem in root.findall(".//object[@name='Entity']"):
                try:
                    entity_id = "Unknown"
                    id_field = entity_elem.find("./field[@name='disEntityId']")
                    if id_field is not None:
                        entity_id = (id_field.get('value-Id64') or id_field.get('value-String') or "Unknown").strip()

                    entity_name = ""
                    name_field = entity_elem.find("./field[@name='hidName']")
                    if name_field is not None:
                        entity_name = _get_str_val(name_field)
                    if not entity_name:
                        creature_field = entity_elem.find("./field[@name='tplCreatureType']")
                        if creature_field is not None:
                            entity_name = _get_str_val(creature_field)
                    if not entity_name:
                        entity_name = "Unnamed"

                    pos_field = entity_elem.find("./field[@name='hidPos']")
                    if pos_field is None:
                        pos_field = entity_elem.find("./field[@name='hidPos_precise']")

                    if pos_field is not None:
                        pos_value = pos_field.get('value-Vector3', '')
                        if pos_value:
                            try:
                                coords = pos_value.split(',')
                                if len(coords) == 3:
                                    x = float(coords[0])
                                    y = float(coords[1])
                                    z = float(coords[2])

                                    entity = Entity(entity_id, entity_name, x, y, z, entity_elem)
                                    entity.source_file = "sectorsdep"
                                    entity.source_file_path = file_path

                                    if self.grid_config and self.grid_config.maps:
                                        entity.map_name = self.determine_entity_map(entity)

                                    self.entities.append(entity)
                                    entities_loaded += 1
                            except (ValueError, IndexError):
                                pass

                except Exception as e:
                    print(f"Error parsing sectordep entity: {str(e)}")
            
            print(f"Loaded {entities_loaded} entities from sectordep file")
            return True
            
        except Exception as e:
            print(f"Error loading sectordep data from {file_path}: {str(e)}")
            return False
    
    def analyze_level_structure(self, base_folder):
        """
        Enhanced level structure analysis with better detection and debugging
        """
        level_data = []
        
        print(f"Analyzing level structure in: {base_folder}")
        
        # Pattern 1: Patch folder with worlds/levels subfolders
        worlds_folder = os.path.join(base_folder, "worlds")
        levels_folder = os.path.join(base_folder, "levels")
        
        if os.path.exists(worlds_folder) and os.path.exists(levels_folder):
            print("Found patch folder structure")
            
            # Find matching level names in both folders
            worlds_levels = set()
            levels_levels = set()
            
            try:
                if os.path.isdir(worlds_folder):
                    worlds_levels = {item for item in os.listdir(worlds_folder) 
                                if os.path.isdir(os.path.join(worlds_folder, item))}
                    print(f"   Worlds subfolders: {sorted(worlds_levels)}")
                
                if os.path.isdir(levels_folder):
                    levels_levels = {item for item in os.listdir(levels_folder) 
                                if os.path.isdir(os.path.join(levels_folder, item))}
                    print(f"   Levels subfolders: {sorted(levels_levels)}")
                    
            except Exception as e:
                print(f"Error scanning patch folders: {e}")
            
            # Find levels that exist in both folders
            common_levels = worlds_levels.intersection(levels_levels)
            all_levels = worlds_levels.union(levels_levels)
            
            print(f"Found {len(worlds_levels)} worlds, {len(levels_levels)} levels, {len(common_levels)} complete")
            
            for level_name in sorted(all_levels):
                worlds_path = os.path.join(worlds_folder, level_name) if level_name in worlds_levels else None
                levels_path = os.path.join(levels_folder, level_name) if level_name in levels_levels else None
                
                # Validate paths with detailed feedback
                worlds_valid = False
                levels_valid = False
                
                if worlds_path:
                    worlds_valid = self.validate_worlds_folder(worlds_path)
                    if worlds_valid:
                        print(f"   {level_name} worlds folder valid")
                    else:
                        print(f"   {level_name} worlds folder invalid (no XML files)")
                
                if levels_path:
                    levels_valid = self.validate_levels_folder(levels_path)
                    if levels_valid:
                        print(f"   {level_name} levels folder valid")
                    else:
                        print(f"   {level_name} levels folder invalid (no worldsectors)")
                
                if worlds_valid or levels_valid:
                    level_info = {
                        'name': level_name,
                        'worlds_path': worlds_path if worlds_valid else None,
                        'levels_path': levels_path if levels_valid else None,
                        'base_folder': base_folder,
                        'complete': worlds_valid and levels_valid
                    }
                    level_data.append(level_info)
                    
                    status = "complete" if worlds_valid and levels_valid else "partial"
                    print(f"   Added {level_name} ({status})")
                else:
                    print(f"   Skipped {level_name} (no valid data)")
        
        # Pattern 2: Direct level folder
        else:
            print("Checking direct level folder")
            worlds_valid = self.validate_worlds_folder(base_folder)
            levels_valid = self.validate_levels_folder(base_folder)
            
            print(f"   Worlds data valid: {worlds_valid}")
            print(f"   Levels data valid: {levels_valid}")
            
            if worlds_valid or levels_valid:
                level_name = os.path.basename(base_folder)
                level_info = {
                    'name': level_name,
                    'worlds_path': base_folder if worlds_valid else None,
                    'levels_path': base_folder if levels_valid else None,
                    'base_folder': os.path.dirname(base_folder),
                    'complete': worlds_valid and levels_valid
                }
                level_data.append(level_info)
                
                status = "complete" if worlds_valid and levels_valid else "partial"
                print(f"   Added {level_name} ({status})")
            else:
                print(f"   No valid level data found in direct folder")
        
        print(f" Analysis complete: {len(level_data)} levels found")
        
        # DEBUG: Show what was found
        if level_data:
            print(f"\nDetected levels:")
            for i, level in enumerate(level_data, 1):
                worlds_status = "" if level['worlds_path'] else ""
                levels_status = "" if level['levels_path'] else ""
                complete_status = "COMPLETE" if level['complete'] else "PARTIAL"
                print(f"   {i}. {level['name']} - Worlds:{worlds_status} Levels:{levels_status} {complete_status}")
        
        return level_data

    def show_level_selection_dialog(self, level_data, prefer_complete=True):
        """Show dialog for user to select which level to load - ENHANCED"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QLabel
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Select Level to Load ({len(level_data)} found)")
        dialog.setMinimumSize(600, 400)
        
        layout = QVBoxLayout(dialog)
        
        # Info label
        complete_count = len([l for l in level_data if l['complete']])
        partial_count = len(level_data) - complete_count
        
        info_text = f"Found {len(level_data)} levels: {complete_count} complete, {partial_count} partial"
        if prefer_complete and complete_count > 0:
            info_text += "\n(Complete levels are recommended - they have both world and level data)"
        
        info_label = QLabel(info_text)
        layout.addWidget(info_label)
        
        # Level list
        level_list = QListWidget()
        
        # Sort levels: complete first if preferred, then alphabetically
        if prefer_complete:
            sorted_levels = sorted(level_data, key=lambda x: (not x['complete'], x['name']))
        else:
            sorted_levels = sorted(level_data, key=lambda x: x['name'])
        
        for level_info in sorted_levels:
            # Build item text with detailed status
            item_text = f"{level_info['name']}"
            
            status_parts = []
            if level_info['worlds_path']:
                status_parts.append("World Data ")
            else:
                status_parts.append("World Data ")
                
            if level_info['levels_path']:
                status_parts.append("Level Objects ")
            else:
                status_parts.append("Level Objects ")
            
            if level_info['complete']:
                item_text += " [COMPLETE]"
            else:
                item_text += " [PARTIAL]"
                
            item_text += f"\n    {' | '.join(status_parts)}"
            
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, level_info)
            
            # Color coding
            if level_info['complete']:
                item.setBackground(QColor(200, 255, 200))  # Light green for complete
            else:
                item.setBackground(QColor(255, 255, 200))  # Light yellow for partial
            
            level_list.addItem(item)
        
        layout.addWidget(level_list)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        load_button = QPushButton("Load Selected Level")
        load_button.clicked.connect(
            lambda: self.load_selected_level_from_dialog(dialog, level_list)
        )
        button_layout.addWidget(load_button)
        
        manual_button = QPushButton("Manual Selection Instead...")
        manual_button.clicked.connect(
            lambda: self.switch_to_manual_selection_from_dialog(dialog)
        )
        button_layout.addWidget(manual_button)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
        
        # Show dialog
        dialog.exec()

    def reset_maps_and_ui(self):
        """Reset map configuration, canvas, and terrain renderer when loading a new level"""
        print("Resetting maps, UI, and terrain, please wait.")

        try:
            # ---------------- 1. Reset current map ----------------
            self.current_map = None

            # ---------------- 2. Reset grid configuration ----------------
            self.grid_config = GridConfig(
                sector_count_x=16,
                sector_count_y=16,
                sector_granularity=64,
                maps=[]  # Clear all maps
            )

            # ---------------- 3. Reset canvas state ----------------
            if hasattr(self, 'canvas'):
                self.canvas.current_map = None
                self.canvas.grid_config = self.grid_config

                # Clear terrain/minimap data
                for attr in ['minimap', 'terrain_data', 'heightmap', 'terrain_texture']:
                    if hasattr(self.canvas, attr):
                        setattr(self.canvas, attr, None)

                # Reset sector boundary data
                if hasattr(self.canvas, 'sector_data'):
                    self.canvas.sector_data = []
                if hasattr(self.canvas, 'show_sector_boundaries'):
                    self.canvas.show_sector_boundaries = False

            # ---------------- 4. Reset map combo box ----------------
            if hasattr(self, 'map_combo'):
                self.map_combo.clear()
                self.map_combo.addItem("No maps loaded")

            # ---------------- 5. Reset terrain renderer ----------------
            if hasattr(self, 'terrain_viewer') and self.terrain_viewer:
                # Recreate or reset terrain renderer
                self.terrain_viewer.setParent(None)  # Remove old widget
                self.terrain_viewer.deleteLater()
                self.terrain_viewer = TerrainRenderer(parent=self)
                if hasattr(self, 'terrain_dock') and self.terrain_dock:
                    self.terrain_dock.setWidget(self.terrain_viewer)

            print("Maps, UI, and terrain reset complete")

        except Exception as e:
            print(f"Error during maps, UI, or terrain reset: {e}")
            import traceback
            traceback.print_exc()

    def parse_xml_file(self, file_path):
        """Parse the XML file to extract entities - WITH CACHING"""
        
        # ============ CACHE INTEGRATION HERE ============
        # Try to get cached parsed data first
        cached_entities = self.cache.get_parsed_xml(file_path)
        if cached_entities is not None:
            print(f"Using cached parse for {os.path.basename(file_path)} ({len(cached_entities)} entities)")
            
            # Use a copy of the cached data so subsequent appends (omnis, worldsectors)
            # don't mutate the cached list and cause duplication on next reload.
            self.entities = list(cached_entities)
            
            # Still need to set xml_tree for saving later
            tree = ET.parse(file_path)
            self.xml_tree = tree
            import io as _io_main
            _buf = _io_main.BytesIO()
            tree.write(_buf, encoding='utf-8', xml_declaration=True)
            self._main_clean_hashes['mapsdata'] = str(hash(_buf.getvalue()))

            # Re-link entity.xml_element to the fresh tree's elements.
            # Cached entities hold references to the old parse tree; any edits
            # (shape points, position) written through xml_element would miss
            # self.xml_tree entirely if we skip this step.
            root = tree.getroot()
            elem_by_id = {}
            for elem in root.findall(".//object[@name='Entity']"):
                id_field = elem.find("./field[@name='disEntityId']")
                if id_field is not None:
                    eid = (id_field.get('value-Id64') or id_field.get('value-String') or '').strip()
                    if eid:
                        elem_by_id[eid] = elem
            relinked = 0
            for entity in self.entities:
                eid = getattr(entity, 'id', None)
                if eid and eid in elem_by_id:
                    entity.xml_element = elem_by_id[eid]
                    relinked += 1
            print(f"  Re-linked {relinked}/{len(self.entities)} entity XML references to fresh tree")

            # Reset maps if needed
            base_filename = os.path.basename(file_path)
            if ".mapsdata.xml" in base_filename or "mapsdata.xml" == base_filename:
                print("Main mapsdata file detected - performing full map reset")
                self.reset_maps_and_ui()
            
            # Update UI
            if hasattr(self, 'update_entity_statistics'):
                self.update_entity_statistics()
            if hasattr(self, 'entity_tree'):
                self.update_entity_tree()
            if hasattr(self, 'canvas'):
                self.canvas.set_entities(self.entities)
            
            return  # Done - used cache!
        # ============ END CACHE CHECK ============
        
        # Cache miss - parse normally
        print(f"Parsing {os.path.basename(file_path)}...")
        
        # Reset maps when parsing a new main XML file
        base_filename = os.path.basename(file_path)
        if ".mapsdata.xml" in base_filename or "mapsdata.xml" == base_filename:
            print("Main mapsdata file detected - performing full map reset")
            self.reset_maps_and_ui()
        
        # Reset current data
        self.entities = []
        self.selected_entity = None
        
        # Parse XML
        tree = ET.parse(file_path)
        self.xml_tree = tree
        import io as _io_main
        _buf = _io_main.BytesIO()
        tree.write(_buf, encoding='utf-8', xml_declaration=True)
        self._main_clean_hashes['mapsdata'] = str(hash(_buf.getvalue()))
        root = tree.getroot()

        # Determine the source file type based on filename
        source_type = "unknown"
        if ".mapsdata.xml" in base_filename:
            source_type = "mapsdata"
        elif ".managers.xml" in base_filename:
            source_type = "managers"
        elif ".omnis.xml" in base_filename:
            source_type = "omnis"
        elif ".sectorsdep.xml" in base_filename:
            source_type = "sectorsdep"
        
        # Iterate by MissionLayer so source_layer is captured per entity
        mission_layers = root.findall("./object[@name='MissionLayer']")
        if not mission_layers:
            # Fallback: no MissionLayer wrapper — treat entire tree as one unnamed layer
            mission_layers_iter = [('', root)]
        else:
            mission_layers_iter = []
            for ml in mission_layers:
                pf = ml.find("./field[@name='text_PathId']")
                layer_name = pf.get('value-String', '') if pf is not None else ''
                mission_layers_iter.append((layer_name, ml))

        for layer_name, layer_elem in mission_layers_iter:
            for entity_elem in layer_elem.findall(".//object[@name='Entity']"):
                try:
                    entity_id = "Unknown"
                    id_field = entity_elem.find("./field[@name='disEntityId']")
                    if id_field is not None:
                        entity_id = (id_field.get('value-Id64') or id_field.get('value-String') or "Unknown").strip()

                    entity_name = ""
                    name_field = entity_elem.find("./field[@name='hidName']")
                    if name_field is not None:
                        entity_name = _get_str_val(name_field)
                    if not entity_name:
                        creature_field = entity_elem.find("./field[@name='tplCreatureType']")
                        if creature_field is not None:
                            entity_name = _get_str_val(creature_field)
                    if not entity_name:
                        entity_name = "Unnamed"

                    pos_field = entity_elem.find("./field[@name='hidPos']")
                    if pos_field is None:
                        pos_field = entity_elem.find("./field[@name='hidPos_precise']")

                    if pos_field is not None:
                        pos_value = pos_field.get('value-Vector3', '')
                        if pos_value:
                            try:
                                coords = pos_value.split(',')
                                if len(coords) == 3:
                                    x = float(coords[0])
                                    y = float(coords[1])
                                    z = float(coords[2])

                                    entity = Entity(entity_id, entity_name, x, y, z, entity_elem)
                                    entity.source_file = source_type
                                    entity.source_layer = layer_name

                                    if self.grid_config and self.grid_config.maps:
                                        entity.map_name = self.determine_entity_map(entity)

                                    self.entities.append(entity)
                            except (ValueError, IndexError):
                                pass
                except Exception as e:
                    print(f"Error parsing entity: {str(e)}")
        
        # Print summary
        print(f"Parsed {len(self.entities)} entities from {file_path}")
        
        # ============ CACHE INTEGRATION HERE ============
        # Store a snapshot copy so later appends (omnis, worldsectors) don't
        # corrupt the cached list — the cache must only contain mapsdata entities.
        self.cache.cache_parsed_xml(file_path, list(self.entities))
        # ============ END CACHE INTEGRATION ============
        
        # Update entity statistics if the method exists
        if hasattr(self, 'update_entity_statistics'):
            self.update_entity_statistics()
        
        # Update the entity browser tree if it exists
        if hasattr(self, 'entity_tree'):
            self.update_entity_tree()
        
        # Update canvas with new entities
        if hasattr(self, 'canvas'):
            self.canvas.set_entities(self.entities)
                                        
    def reset_entire_editor_state(self):
        """Comprehensive reset of the entire editor state when loading a new level"""
        print("COMPREHENSIVE EDITOR RESET - Clearing all previous level data, Please wait.")
        
        try:
            # 1. CLEAR ALL ENTITY DATA
            print("   Clearing entity data, Please wait.")
            self.entities = []
            self.objects = []
            self.selected_entity = None
            
            # Clear canvas entities and selection
            if hasattr(self, 'canvas'):
                self.canvas.entities = []
                self.canvas.selected = []
                self.canvas.selected_entity = None
                self.canvas.selected_positions = []
                self.canvas.selected_rotations = []
                
                # Invalidate entity cache
                if hasattr(self.canvas, 'invalidate_entity_cache'):
                    self.canvas.invalidate_entity_cache()
            
            # 2. CLEAR ALL XML TREES AND FILE REFERENCES
            print("   Clearing XML file data, Please wait.")
            self.xml_tree = None
            self.xml_file_path = None
            self.omnis_tree = None
            self.managers_tree = None
            self.sectordep_tree = None
            
            # Clear worldsectors data
            if hasattr(self, 'worldsectors_trees'):
                self.worldsectors_trees.clear()
            else:
                self.worldsectors_trees = {}

            if hasattr(self, 'worldsectors_modified'):
                self.worldsectors_modified.clear()
            else:
                self.worldsectors_modified = {}

            if hasattr(self, 'landmark_trees'):
                self.landmark_trees.clear()
            else:
                self.landmark_trees = {}

            if hasattr(self, 'landmark_clean_hashes'):
                self.landmark_clean_hashes.clear()
            else:
                self.landmark_clean_hashes = {}

            self.worldsectors_path = None
            self._all_worldsectors_paths = []
            self._avatar_sdat_paths = []

            # 3. RESET MAP AND GRID CONFIGURATION
            print("   Resetting map configuration, Please wait.")
            self.current_map = None
            self.grid_config = GridConfig(
                sector_count_x=16,
                sector_count_y=16,
                sector_granularity=64,
                maps=[]  # Clear all maps
            )
            
            # Reset canvas map state
            if hasattr(self.canvas, 'current_map'):
                self.canvas.current_map = None
            if hasattr(self.canvas, 'grid_config'):
                self.canvas.grid_config = self.grid_config
            
            # 4. RESET MAP COMBO BOX
            print("   Resetting UI elements, Please wait.")
            if hasattr(self, 'map_combo'):
                self.map_combo.clear()
                self.map_combo.addItem("No maps loaded")
            
            # 5. CLEAR TERRAIN AND MINIMAP DATA
            print("   Clearing terrain data, Please wait.")
            if hasattr(self.canvas, 'minimap'):
                self.canvas.minimap = None
            if hasattr(self.canvas, 'terrain_data'):
                self.canvas.terrain_data = None
            if hasattr(self.canvas, 'heightmap'):
                self.canvas.heightmap = None
            if hasattr(self.canvas, 'terrain_texture'):
                self.canvas.terrain_texture = None
            
            
            # Reset terrain renderer to clear all loaded terrain data
            if hasattr(self.canvas, 'terrain_renderer'):
                try:
                    # Create a fresh terrain renderer instance
                    self.canvas.terrain_renderer = TerrainRenderer(game_mode=self.game_mode)
                    print("   Canvas terrain renderer reset")
                except Exception as e:
                    print(f"   Warning: Could not reset terrain renderer: {e}")
            
            # Reset editor-level terrain properties
            self.sdat_path = None
            
            # Close and clear terrain viewer widget
            if hasattr(self, 'terrain_viewer') and self.terrain_viewer is not None:
                try:
                    self.terrain_viewer.close()
                    self.terrain_viewer = None
                    print("   Terrain viewer closed")
                except Exception as e:
                    print(f"   Warning: Could not close terrain viewer: {e}")
            
            # Clear terrain dock widget
            if hasattr(self, 'terrain_dock') and self.terrain_dock is not None:
                try:
                    self.terrain_dock.setWidget(None)
                    print("   Terrain dock cleared")
                except Exception as e:
                    print(f"   Warning: Could not clear terrain dock: {e}")
            
            # 6. RESET SECTOR BOUNDARY DATA
            if hasattr(self.canvas, 'sector_data'):
                self.canvas.sector_data = []
            if hasattr(self.canvas, 'show_sector_boundaries'):
                self.canvas.show_sector_boundaries = False
            
            # 7. RESET MODIFICATION FLAGS
            print("   Resetting modification flags, Please wait.")
            self.entities_modified = False
            self.xml_tree_modified = False
            self.omnis_tree_modified = False
            self.managers_tree_modified = False
            self.sectordep_tree_modified = False
            self.objects_modified = False
            
            # 8. CLEAR ENTITY BROWSER/TREE
            if hasattr(self, 'entity_tree'):
                self.entity_tree.clear()
            
            # 9. RESET UI LABELS AND STATUS
            print("   Updating UI labels, Please wait.")
            if hasattr(self, 'level_info_label'):
                self.level_info_label.setText("No level loaded")
            elif hasattr(self, 'xml_file_label'):
                self.xml_file_label.setText("No level loaded")
            
            if hasattr(self, 'entity_count_label'):
                self.entity_count_label.setText("Entities: 0")
            
            if hasattr(self, 'stat_name_label'):
                self._clear_entity_stats()
            
            # 10. RESET ENTITY EDITOR IF OPEN
            if hasattr(self, 'entity_editor') and self.entity_editor is not None:
                try:
                    self.entity_editor.close()
                    self.entity_editor = None
                except:
                    pass
            
            # 11. RESET COPY/PASTE CLIPBOARD
            if hasattr(self, 'entity_clipboard'):
                try:
                    # Clear clipboard data
                    if hasattr(self.entity_clipboard, 'clipboard_data'):
                        self.entity_clipboard.clipboard_data = None
                    if hasattr(self.entity_clipboard, 'clear_clipboard'):
                        self.entity_clipboard.clear_clipboard()
                except:
                    pass
            
            # 12. CLEAR ANY CACHED RENDER DATA
            if hasattr(self.canvas, 'entity_cache_3d'):
                self.canvas.entity_cache_3d = None
            if hasattr(self.canvas, 'entity_cache_dirty'):
                self.canvas.entity_cache_dirty = True
            if hasattr(self.canvas, 'entities_modified'):
                self.canvas.entities_modified = True
            if hasattr(self.canvas, 'selection_modified'):
                self.canvas.selection_modified = True
            
            # 13. RESET VIEW TO DEFAULT
            print("   Resetting view, Please wait.")
            if hasattr(self.canvas, 'reset_view'):
                self.canvas.reset_view()
            
            # 14. UPDATE STATUS BAR
            self.status_bar.showMessage("Editor reset - ready to load new level")
            
            # 15. FORCE CANVAS UPDATE
            if hasattr(self, 'canvas'):
                self.canvas.update()
            
            print("COMPREHENSIVE EDITOR RESET COMPLETE")
            
        except Exception as e:
            print(f"Error during comprehensive reset: {e}")
            import traceback
            traceback.print_exc()

    def reset_editor_state_no_game_change(self):
        """
        Partial reset when switching levels within the same game mode.
        Does NOT trigger game selector - only clears level-specific data.
        """
        print("PARTIAL EDITOR RESET - Clearing level data only (keeping game mode)")
        
        try:
            # Clear entity data
            self.entities = []
            self.objects = []
            self.selected_entity = None
            
            if hasattr(self, 'canvas'):
                self.canvas.entities = []
                self.canvas.selected = []
                self.canvas.selected_entity = None
                self.canvas.selected_positions = []
                self.canvas.selected_rotations = []
                if hasattr(self.canvas, 'invalidate_entity_cache'):
                    self.canvas.invalidate_entity_cache()
            
            # Clear XML data
            self.xml_tree = None
            self.xml_file_path = None
            self.omnis_tree = None
            self.managers_tree = None
            self.sectordep_tree = None
            
            if hasattr(self, 'worldsectors_trees'):
                self.worldsectors_trees.clear()
            else:
                self.worldsectors_trees = {}

            if hasattr(self, 'worldsectors_modified'):
                self.worldsectors_modified.clear()
            else:
                self.worldsectors_modified = {}

            if hasattr(self, 'landmark_trees'):
                self.landmark_trees.clear()
            else:
                self.landmark_trees = {}

            if hasattr(self, 'landmark_clean_hashes'):
                self.landmark_clean_hashes.clear()
            else:
                self.landmark_clean_hashes = {}

            self.worldsectors_path = None
            self._all_worldsectors_paths = []
            self._avatar_sdat_paths = []

            # Reset map config (keep game-specific grid)
            self.current_map = None
            if self.grid_config:
                self.grid_config.maps = []
            
            if hasattr(self.canvas, 'current_map'):
                self.canvas.current_map = None
            if hasattr(self.canvas, 'grid_config'):
                self.canvas.grid_config = self.grid_config
            
            # Reset UI
            if hasattr(self, 'map_combo'):
                self.map_combo.clear()
                self.map_combo.addItem("No maps loaded")
            
            # Clear terrain
            if hasattr(self.canvas, 'terrain_renderer'):
                try:
                    from canvas.terrain_renderer import TerrainRenderer
                    self.canvas.terrain_renderer = TerrainRenderer(game_mode=self.game_mode)
                except:
                    pass
            
            self.sdat_path = None
            
            if hasattr(self, 'terrain_viewer') and self.terrain_viewer:
                try:
                    self.terrain_viewer.close()
                    self.terrain_viewer = None
                except:
                    pass
            
            # Clear sector data
            if hasattr(self.canvas, 'sector_data'):
                self.canvas.sector_data = []
            
            # Reset flags
            self.entities_modified = False
            self.xml_tree_modified = False
            self.omnis_tree_modified = False
            self.managers_tree_modified = False
            self.sectordep_tree_modified = False
            self.objects_modified = False
            
            # Clear UI
            if hasattr(self, 'entity_tree'):
                self.entity_tree.clear()
            
            if hasattr(self, 'level_info_label'):
                self.level_info_label.setText("No level loaded")
            elif hasattr(self, 'xml_file_label'):
                self.xml_file_label.setText("No level loaded")
            
            if hasattr(self, 'entity_editor') and self.entity_editor:
                try:
                    self.entity_editor.close()
                    self.entity_editor = None
                except:
                    pass
            
            # Reset view
            if hasattr(self.canvas, 'reset_view'):
                self.canvas.reset_view()
            
            self.status_bar.showMessage(f"Ready to load new level ({self.game_mode})")
            
            if hasattr(self, 'canvas'):
                self.canvas.update()
            
            print(f"PARTIAL RESET COMPLETE - Game mode '{self.game_mode}' preserved")
            
        except Exception as e:
            print(f"Error during partial reset: {e}")
            import traceback
            traceback.print_exc()

    def select_level(self):
            """
            Visual level selection using patch folder - ENHANCED VERSION
            """
            print(f"\n=== STARTING VISUAL LEVEL SELECTION ===")
            
            # COMPREHENSIVE RESET FIRST
            self.reset_entire_editor_state()
            
            # Check if patch manager is configured
            if not hasattr(self, 'patch_manager') or not self.patch_manager.is_configured():
                print("Patch folder not configured, prompting user...")
                reply = QMessageBox.question(
                    self,
                    "Patch Folder Not Set",
                    "No patch folder is configured. Would you like to set one now?\n\n"
                    "The patch folder should contain 'worlds' and 'levels' subdirectories.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    if not self.patch_manager.set_patch_folder():
                        print("User cancelled patch folder selection")
                        return
                    else:
                        # Update worlds_folder after setting patch folder
                        from set_patch_folder import update_worlds_folder
                        update_worlds_folder(self.patch_manager, self)
                else:
                    print("User declined to set patch folder")
                    return
            
            # Scan patch folder if levels_data is empty
            if not self.patch_manager.levels_data:
                print("No levels_data, scanning patch folder...")
                
                # Create enhanced progress dialog
                from simplified_map_editor import EnhancedProgressDialog
                
                progress_dialog = EnhancedProgressDialog(
                    "Scanning Patch Folder", 
                    self, 
                    game_mode=self.game_mode
                )
                progress_dialog.append_log(f"Scanning: {os.path.basename(self.patch_manager.patch_folder)}")
                progress_dialog.show()
                QApplication.processEvents()
                
                # Get file_converter
                file_converter = self.file_converter if hasattr(self, 'file_converter') else None
                
                # Create scanner thread
                from set_patch_folder import PatchFolderScanner
                scanner_thread = PatchFolderScanner(self.patch_manager.patch_folder, file_converter)
                self.patch_manager.scanner_thread = scanner_thread
                
                scan_completed = [False]
                
                def on_complete(levels_data):
                    self.patch_manager.levels_data = levels_data or {}
                    progress_dialog.set_progress(100)
                    progress_dialog.append_log(f"Scan complete: {len(self.patch_manager.levels_data)} levels found")
                    progress_dialog.mark_complete()
                    progress_dialog.stop_icon()
                    progress_dialog.close()
                    scan_completed[0] = True
                    print(f"Scan complete: Found {len(self.patch_manager.levels_data)} levels")
                
                def on_error(msg):
                    self.patch_manager.levels_data = {}
                    progress_dialog.append_log(f"Error: {msg}")
                    progress_dialog.mark_complete()
                    progress_dialog.stop_icon()
                    progress_dialog.close()
                    scan_completed[0] = True
                    print(f"Scan error: {msg}")
                    QMessageBox.critical(self, "Scan Error", msg)
                
                def on_progress(percent, message):
                    if progress_dialog.was_cancelled:
                        return
                    progress_dialog.set_progress(percent)
                    progress_dialog.set_status(message)
                    progress_dialog.append_log(message)
                    QApplication.processEvents()
                
                def on_scan_cancelled():
                    self.patch_manager.levels_data = {}
                    scan_completed[0] = True

                scanner_thread.scan_complete.connect(on_complete)
                scanner_thread.error_occurred.connect(on_error)
                scanner_thread.progress_updated.connect(on_progress)
                scanner_thread.log_message.connect(progress_dialog.append_log)
                progress_dialog.cancelled.connect(scanner_thread.stop)
                progress_dialog.cancelled.connect(on_scan_cancelled)
                scanner_thread.start()
                
                # Wait for scan to complete
                while not scan_completed[0]:
                    QApplication.processEvents()
                
                print("Scan finished.")
            
            # Check if we have any levels after scan
            if not self.patch_manager.levels_data:
                print("ERROR: No levels found after scan")
                QMessageBox.warning(
                    self,
                    "No Levels Found",
                    "No valid levels were found in the patch folder.\n\n"
                    f"Patch folder: {self.patch_manager.patch_folder}\n\n"
                    "Please ensure your patch folder contains 'worlds' and/or 'levels' subdirectories."
                )
                return
            
            # Show the visual level selector dialog
            print(f"Showing level selector dialog with {len(self.patch_manager.levels_data)} levels...")
            
            from set_patch_folder import LevelSelectorDialog
            dialog = LevelSelectorDialog(
                self.patch_manager.levels_data, 
                self, 
                self.game_mode, 
                self.patch_manager
            )
            
            def on_level_selected(level_dict):
                print(f"Level selected: {level_dict.get('name')}")
            
            def on_patch_folder_change():
                print("Patch folder change requested, restarting selection...")
                from set_patch_folder import update_worlds_folder
                update_worlds_folder(self.patch_manager, self)
                self.patch_manager.levels_data = {}
                QTimer.singleShot(100, self.select_level)
            
            dialog.level_selected.connect(on_level_selected)
            dialog.patch_folder_change_requested.connect(on_patch_folder_change)
            
            # Execute dialog
            result = dialog.exec()
            print(f"Level selector result: {result}")
            
            if result == QDialog.DialogCode.Accepted and hasattr(dialog, 'selected_level') and dialog.selected_level:
                level_dict = dialog.selected_level
                print(f"Loading selected level: {level_dict.get('name')}")
                
                worlds_path = level_dict.get("worlds_path")
                levels_path = level_dict.get("levels_path")
                
                # Validate paths - be lenient, allow partial data
                worlds_valid = self.validate_worlds_folder(worlds_path) if worlds_path else True
                levels_valid = self.validate_levels_folder(levels_path) if levels_path else True
                
                print(f"Validation: worlds={worlds_valid}, levels={levels_valid}")
                
                # Proceed if we have at least one valid path
                if (worlds_path and worlds_valid) or (levels_path and levels_valid):
                    print("Calling load_complete_level()...")
                    self.load_complete_level(level_dict)  #FIXED: Removed '_with_progress'
                else:
                    print("ERROR: No valid paths in selected level")
                    QMessageBox.warning(
                        self,
                        "Invalid Level",
                        "The selected level has no valid world or level data.\n\n"
                        f"Worlds path valid: {worlds_valid}\n"
                        f"Levels path valid: {levels_valid}"
                    )
            else:
                print("Level selection cancelled by user")

    @staticmethod
    def _get_fc2_world_offset(level_name, fallback_path=None):
        """Return (world_x, world_y) offset in game units for an FC2 world-cell name.

        FC2 world cells follow the naming pattern  w{world}_{col}_{row}  where:
          col  is a letter a–e  (a=col 0, b=col 1, c=col 2, d=col 3, e=col 4)
          row  is a digit  1–5  (1→row 0, 2→row 1, … 5→row 4, 0-indexed)

        The 5×5 world grid starts at world-space (0,0) so each cell's offset is:
          x = col_index × 1024
          y = row_index × 1024

        Example:  w1_a_1 → (0, 0)   w1_c_3 → (2048, 2048)   w1_e_5 → (4096, 4096)

        If level_name doesn't match (e.g. 'world1'), fallback_path is searched for a
        path component that does match (e.g. .../levels/w1_c_3/generated/sdat).
        """
        import re
        pattern = re.compile(r'w\d+_([a-e])_(\d+)', re.IGNORECASE)

        def _parse(s):
            m = pattern.search(s)
            if m:
                col = ord(m.group(1).lower()) - ord('a')
                row = int(m.group(2)) - 1
                return col * 1024, row * 1024
            return None

        result = _parse(level_name)
        if result is not None:
            return result

        # level_name didn't match — search each component of fallback_path
        if fallback_path:
            import os
            for part in fallback_path.replace('\\', '/').split('/'):
                result = _parse(part)
                if result is not None:
                    return result

        return 0, 0

    def load_complete_level(self, level_info):
        """
        Load both world and level data for a complete level with enhanced progress dialog.
        All progress is consolidated into ONE dialog - no popup spam.
        """
        print(f"\n=== LOADING COMPLETE LEVEL: {level_info['name']} ===")

        try:
            # Create enhanced progress dialog - THE ONLY ONE
            progress_dialog = EnhancedProgressDialog("Loading Complete Level", self, game_mode=self.game_mode)
            
            # Connect cancel signal
            progress_dialog.cancelled.connect(
                lambda: self.cancel_loading(progress_dialog)
            )
            
            progress_dialog.show()
            QApplication.processEvents()
            
            # Helper function for logging
            def log(msg):
                print(msg)
                progress_dialog.append_log(msg)
                QApplication.processEvents()
            
            # RESET
            progress_dialog.set_status("Initializing level loading...")
            progress_dialog.set_progress(5)
            log(f"Loading level: {level_info['name']}")
            QApplication.processEvents()
            
            self.entities = []
            self.objects = []
            self.selected_entity = None
            self.sector_clean_hashes = {}

            # Always reset terrain before loading a new level so the previous
            # level's terrain is never shown when the new level has no terrain
            # or when terrain loading fails (e.g. in the frozen exe build).
            if hasattr(self, 'canvas') and self.canvas:
                self.canvas.terrain_model = None
                self.canvas.terrain_world_offset_x = 0.0
                self.canvas.terrain_world_offset_y = 0.0
                if hasattr(self.canvas, 'terrain_renderer'):
                    self.canvas.terrain_renderer = TerrainRenderer(game_mode=self.game_mode)
                self.canvas.unified_mode = False
                self.canvas.dirty_sectors = set()

            total_entities = 0
            loaded_components = []
            
            if progress_dialog.was_cancelled:
                progress_dialog.close()
                return
            
            # Set worlds folder for 3D models
            if level_info['worlds_path']:
                self.worlds_folder = level_info['worlds_path']
                log(f"Set worlds_folder for 3D models")
                print(f"Set worlds_folder for 3D models: {self.worlds_folder}")
            
            if progress_dialog.was_cancelled:
                progress_dialog.close()
                return
            
            # 1️⃣ Load World Data (mapsdata / omnis / managers / sectorsdep)
            # FC2 stores these in <world>/generated/ — same file types as Avatar.
            if level_info['worlds_path']:
                progress_dialog.set_status("Loading world data (XML files)...")
                progress_dialog.set_progress(10)
                log(f"Worlds folder: {os.path.basename(level_info['worlds_path'])}")
                QApplication.processEvents()

                # FC2: files live in worlds_path/generated/; Avatar: directly in worlds_path.
                # find_xml_files_enhanced already recurses into subfolders, so passing
                # worlds_path works for both games.
                search_root = level_info['worlds_path']
                if self.game_mode == "farcry2":
                    generated = os.path.join(level_info['worlds_path'], "generated")
                    if os.path.isdir(generated):
                        search_root = generated

                print(f"Loading world data from: {search_root}")

                # Enhanced search for files
                found_files = self.find_xml_files_enhanced(search_root)
                log(f"Found {len(found_files)} file types in worlds folder")

                if progress_dialog.was_cancelled:
                    progress_dialog.close()
                    return

                # Convert files if needed
                progress_dialog.set_status("Converting FCB files to XML...")
                progress_dialog.set_progress(20)

                def update_conversion_progress(progress, message=None):
                    if progress_dialog.was_cancelled:
                        return
                    percent = int(20 + progress * 15)
                    progress_dialog.set_progress(percent)
                    if message:
                        log(message)
                    QApplication.processEvents()

                try:
                    success_count, error_count, errors = self.file_converter.convert_folder(
                        search_root,
                        progress_callback=update_conversion_progress
                    )
                    log(f"Conversion: {success_count} successful, {error_count} failed")

                    if error_count > 0:
                        for error in errors[:2]:
                            log(f"  Error: {error}")

                except Exception as e:
                    log(f"Conversion error: {str(e)}")
                    print(f"Error during conversion: {str(e)}. Continuing...")

                if progress_dialog.was_cancelled:
                    progress_dialog.close()
                    return

                # Load XML files
                progress_dialog.set_status("Loading XML files...")
                progress_dialog.set_progress(35)
                log("Processing XML files...")
                QApplication.processEvents()

                loaded_files = []

                # Load mapsdata first
                if "mapsdata" in found_files:
                    self.xml_file_path = found_files["mapsdata"]["path"]
                    self.parse_xml_file(self.xml_file_path)
                    loaded_files.append(f"mapsdata ({len(self.entities)} entities)")
                    log(f"Loaded mapsdata: {len(self.entities)} entities")
                    total_entities += len(self.entities)

                if progress_dialog.was_cancelled:
                    progress_dialog.close()
                    return

                # Load other files
                file_loaders = {
                    "omnis": self.load_omnis_data,
                    "managers": self.load_managers_data,
                    "sectorsdep": self.load_sectordep_data
                }

                for file_key, loader_func in file_loaders.items():
                    if progress_dialog.was_cancelled:
                        progress_dialog.close()
                        return

                    if file_key in found_files:
                        entity_count_before = len(self.entities)
                        loader_func(found_files[file_key]["path"])
                        entity_count_after = len(self.entities)
                        new_entities = entity_count_after - entity_count_before
                        loaded_files.append(f"{file_key} ({new_entities} entities)")
                        log(f"Loaded {file_key}: {new_entities} entities")

                if loaded_files:
                    loaded_components.append(f"World Data ({len(self.entities)} entities)")
                    print(f"Loaded {len(self.entities)} entities from world data")
            
            if progress_dialog.was_cancelled:
                progress_dialog.close()
                return
            
            # 2️⃣ Load Level Objects
            # Build list of level paths — FC2 multi-sector levels have multiple parts
            # (e.g. world1 → w1_a_1..w1_e_5), Avatar levels always have one path.
            all_levels_paths = level_info.get('levels_paths') or (
                [level_info['levels_path']] if level_info.get('levels_path') else []
            )

            if all_levels_paths:
                progress_dialog.set_status("Loading level objects...")
                progress_dialog.set_progress(50)
                log(f"Loading from {len(all_levels_paths)} level folder(s)")
                QApplication.processEvents()

                self.sdat_path = None  # reset; will be discovered below
                self._fc2_sdat_cells = []       # list of (sdat_path, cell_name) for multi-cell terrain
                self._avatar_sdat_paths = []    # all sdat folders across Avatar level parts
                self._all_worldsectors_paths = []  # all worldsectors folders across Avatar level parts

                def on_progress(progress):
                    if progress_dialog.was_cancelled:
                        return
                    percent = int(50 + progress * 15)
                    progress_dialog.set_progress(percent)
                    QApplication.processEvents()

                for lpath in all_levels_paths:
                    if progress_dialog.was_cancelled:
                        progress_dialog.close()
                        return

                    log(f"Levels folder: {os.path.basename(lpath)}")
                    print(f"Loading level objects from: {lpath}")

                    # --- sdat discovery ---
                    if self.game_mode == "farcry2":
                        # FC2: collect sdat from EVERY cell for multi-cell terrain.
                        # Priority: sector/generated/sdat > sector/sdat > sector/ itself.
                        cell_name = os.path.basename(lpath)
                        for candidate in [
                            os.path.join(lpath, "generated", "sdat"),
                            os.path.join(lpath, "sdat"),
                            lpath,
                        ]:
                            if os.path.isdir(candidate) and glob.glob(os.path.join(candidate, "*.sdat")):
                                if self.sdat_path is None:
                                    self.sdat_path = candidate  # keep first for backward compat
                                    log(f"Found FC2 sdat folder: {os.path.basename(candidate)}")
                                    print(f"Found FC2 sdat folder at: {self.sdat_path}")
                                already = any(p == candidate for p, _ in self._fc2_sdat_cells)
                                if not already:
                                    self._fc2_sdat_cells.append((candidate, cell_name))
                                    print(f"[Terrain] Registered FC2 sdat cell: {cell_name} → {candidate}")
                                break
                    else:
                        # Avatar: collect sdat from every level part (not just the first).
                        # Check generated/sdat first (most common), then sdat directly under lpath.
                        for sdat_candidate in [
                            os.path.join(lpath, "generated", "sdat"),
                            os.path.join(lpath, "sdat"),
                        ]:
                            if os.path.isdir(sdat_candidate) and sdat_candidate not in self._avatar_sdat_paths:
                                self._avatar_sdat_paths.append(sdat_candidate)
                                if self.sdat_path is None:
                                    self.sdat_path = sdat_candidate
                                log(f"Found sdat folder: {os.path.relpath(sdat_candidate, lpath)}")
                                print(f"Found sdat folder at: {sdat_candidate}")
                                break

                    # --- object loading ---
                    progress_dialog.set_status(f"Loading objects: {os.path.basename(lpath)}...")
                    log("Processing level files...")

                    if self.game_mode == "farcry2":
                        # FC2: .data.fcb files live directly in the sector folder
                        # find_worldsectors_folder_enhanced step 3 catches this case
                        worldsectors_info = self.find_worldsectors_folder_enhanced(lpath)
                        if worldsectors_info:
                            self.worldsectors_path = worldsectors_info["path"]
                            objects_success = self.load_level_objects_internal(lpath, progress_dialog, on_progress)
                            if objects_success:
                                log(f"Loaded objects from {os.path.basename(lpath)}")
                            else:
                                log(f"No objects loaded from {os.path.basename(lpath)}")
                        else:
                            log(f"No object files found in {os.path.basename(lpath)}")
                    else:
                        # Avatar: objects are inside a worldsectors subfolder
                        worldsectors_info = self.find_worldsectors_folder_enhanced(lpath)
                        if worldsectors_info:
                            log(f"Found worldsectors: {worldsectors_info['fcb_files']} FCB files")
                            self.worldsectors_path = worldsectors_info["path"]
                            if worldsectors_info["path"] not in self._all_worldsectors_paths:
                                self._all_worldsectors_paths.append(worldsectors_info["path"])
                            objects_success = self.load_level_objects_internal(lpath, progress_dialog, on_progress)
                            if objects_success:
                                log(f"Loaded {len(self.objects)} objects from worldsectors")
                            else:
                                log("No objects loaded from worldsectors")
                        else:
                            log(f"No worldsectors found in {os.path.basename(lpath)}")

                if self.objects:
                    loaded_components.append(f"Level Objects ({len(self.objects)} objects)")
                    total_entities += len(self.objects)
                    print(f"Loaded {len(self.objects)} total objects from level data")

                if not self.sdat_path:
                    log("No sdat folder found — terrain will not be available")
            
            if progress_dialog.was_cancelled:
                progress_dialog.close()
                return
            
            # 3️⃣ Setup 3D Models FROM GAME FILES
            progress_dialog.set_status("Setting up 3D models from game files...")
            progress_dialog.set_progress(52)
            log("Configuring 3D model loader...")
            QApplication.processEvents()

            if level_info['worlds_path']:
                if hasattr(self, 'canvas') and hasattr(self.canvas, 'setup_3d_models_for_level'):
                    resource_folder = getattr(self, 'resource_folder', None)
                    if resource_folder:
                        log(f"Using resource folder for models: {os.path.basename(resource_folder)}")
                    else:
                        log("Using patch folder for models")
                    success = self.canvas.setup_3d_models_for_level(
                        level_info['worlds_path'],
                        resource_folder=resource_folder
                    )
                    if success:
                        log("✓ Model loader configured")
                    else:
                        log("⚠ Model loader setup failed")

            if progress_dialog.was_cancelled:
                progress_dialog.close()
                return

            # 4️⃣ Launch unified sector loading on a background thread (Avatar only).
            #    Runs concurrently with Phase A model file I/O below so the two
            #    I/O-heavy operations overlap instead of running back-to-back.
            import threading
            import concurrent.futures
            import os as _os

            def _auto_parse_workers():
                """Parallel model-parse worker count, auto-scaled to whatever CPU
                this machine has: weak CPUs get fewer threads, strong ones more
                (capped at 16 for diminishing returns + memory). The parse is
                numpy + file I/O, which releases the GIL, so threads scale well.
                Robust to cpu_count() being undeterminable."""
                try:
                    logical = _os.cpu_count() or 4
                except Exception:
                    logical = 4
                return max(2, min(logical - 1, 16))

            _unified_done  = threading.Event()
            _unified_error = [None]
            unified_thread = None

            # Snapshot the entity list NOW, before the background thread can modify
            # self.entities. mapsdata/omnis Entity objects persist after unified sectors
            # (they're never replaced), so model assignments on this snapshot stick.
            _pre_unified_entities = list(self.entities)

            if self.game_mode != "farcry2" and getattr(self, 'worldsectors_path', None):
                def _run_unified():
                    try:
                        self.load_all_worldsectors(
                            self.worldsectors_path,
                            log_callback=lambda m: print(f"[sectors] {m}"),
                            progress_callback=lambda pct: None,
                        )
                    except Exception as _ue:
                        _unified_error[0] = str(_ue)
                    finally:
                        _unified_done.set()

                unified_thread = threading.Thread(target=_run_unified, daemon=True)
                unified_thread.start()
                log("Started unified sector loading in background...")

            # 5️⃣ Assign model paths to the pre-unified snapshot (mapsdata / omnis only).
            #    Uses the snapshot — immune to self.entities being modified by the thread.
            #    Skipped entirely if there's no background thread (FC2 / no worldsectors).
            if unified_thread is not None and _pre_unified_entities and hasattr(self, 'canvas') and hasattr(self.canvas, 'model_loader'):
                progress_dialog.set_status("Assigning 3D model paths...")
                progress_dialog.set_progress(55)
                log(f"Assigning model paths to {len(_pre_unified_entities)} pre-unified entities...")
                QApplication.processEvents()
                try:
                    self.canvas.model_loader.assign_models_to_entities(
                        _pre_unified_entities,
                        progress_dialog=progress_dialog,
                        parent=self,
                        game_mode=self.game_mode
                    )
                    log("✓ Pre-unified model paths assigned")
                except Exception as _ae:
                    log(f"⚠ Model assignment error: {_ae}")

            if progress_dialog.was_cancelled:
                progress_dialog.close()
                return

            # 6️⃣ Phase A — parallel GLTF file I/O (overlaps with unified sector thread).
            #    Only reads files and parses JSON/mesh structure — no OpenGL.
            _phase_a_results = {}   # model_path -> parsed GLTFModel (no GL resources yet)
            # Define worker + worker count outside try so the worldsector-only pass
            # (step 7) can reuse them even if Phase A's try block threw early.
            _workers = _auto_parse_workers()
            try:
                print(f"[load] CPU auto-detect: {_os.cpu_count()} logical cores "
                      f"-> {_workers} parallel parse workers")
            except Exception:
                pass

            if hasattr(self, 'canvas') and hasattr(self.canvas, 'model_loader'):
                _ml = self.canvas.model_loader

                try:
                    from canvas.model_loader import GLTFModel, GLTFMesh
                    from canvas.xbg_direct_loader import build_xbg_model
                    import json as _json
                except Exception as _imp_err:
                    log(f"⚠ Cannot import GLTFModel: {_imp_err}")
                    GLTFModel = None
                    GLTFMesh = None
                    build_xbg_model = None
                    _json = None

                def _phase_a_worker(args):
                    if GLTFModel is None:
                        return args[0], None
                    _mp, _bp = args
                    try:
                        # Direct-XBG: parse the .xbg straight (GL-free, thread-safe);
                        # no GLTF/.bin. GL textures are created later in Phase B.
                        if _mp.lower().endswith('.xbg') and build_xbg_model is not None:
                            return _mp, build_xbg_model(_mp, GLTFModel, GLTFMesh, 0)
                        _m = GLTFModel(os.path.basename(_mp), _mp)
                        with open(_mp, 'r', encoding='utf-8') as _f:
                            _m.gltf_data = _json.load(_f)
                        if _bp and os.path.exists(_bp):
                            with open(_bp, 'rb') as _f:
                                _m.bin_data = _f.read()
                        _ml._parse_gltf(_m)
                        return _mp, _m
                    except Exception:
                        return _mp, None

                try:
                    # Collect unique model files from the pre-unified snapshot.
                    # Using the snapshot avoids a race with the background thread
                    # modifying self.entities concurrently.
                    _unique = {}   # model_path -> bin_path
                    for _e in _pre_unified_entities:
                        if getattr(_e, 'model_file', None):
                            _bp = getattr(_e, 'bin_file', _e.model_file.replace('.gltf', '.bin'))
                            _unique.setdefault(_e.model_file, _bp)
                        for _kg, _kb in getattr(_e, 'kit_model_files', []):
                            _unique.setdefault(_kg, _kb or _kg.replace('.gltf', '.bin'))

                    _to_load = [(mp, bp) for mp, bp in _unique.items()
                                if mp not in _ml.models_cache]

                    log(f"Phase A: loading {len(_to_load)} model files in parallel...")
                    progress_dialog.set_status("Loading model files (parallel)...")
                    progress_dialog.set_progress(58)
                    QApplication.processEvents()

                    _workers = _auto_parse_workers()
                    _done_a = 0
                    _total_a = max(len(_to_load), 1)
                    _pa_t0 = time.time()

                    with concurrent.futures.ThreadPoolExecutor(max_workers=_workers) as _ex:
                        _futs = {_ex.submit(_phase_a_worker, args): args[0]
                                 for args in _to_load}
                        for _fut in concurrent.futures.as_completed(_futs):
                            _mp, _m = _fut.result()
                            if _m:
                                _phase_a_results[_mp] = _m
                            _done_a += 1
                            if _done_a % 20 == 0 or _done_a == _total_a:
                                _pct = 58 + int((_done_a / _total_a) * 17)
                                progress_dialog.set_progress(min(_pct, 74))
                                QApplication.processEvents()

                    log(f"Phase A complete: {len(_phase_a_results)}/{len(_to_load)} models parsed "
                        f"in {time.time() - _pa_t0:.2f}s ({_workers} workers)")

                except Exception as _pa_err:
                    log(f"Phase A error: {_pa_err}")
                    import traceback; traceback.print_exc()

            # 7️⃣ Wait for unified sectors, then assign + Phase A for worldsector-only models.
            if unified_thread is not None:
                progress_dialog.set_status("Finishing sector loading...")
                log("Waiting for unified sector loading...")
                while not _unified_done.is_set():
                    QApplication.processEvents()
                    time.sleep(0.02)

                if _unified_error[0]:
                    log(f"⚠ Unified sectors error: {_unified_error[0]}")
                else:
                    log(f"Unified sectors complete: {len(self.entities)} total entities")

                if hasattr(self, 'canvas') and hasattr(self.canvas, 'model_loader') and self.entities:
                    # Full assignment on the complete entity pool.
                    # Always runs — this is the ONLY assignment when unified sectors was fast,
                    # and the worldsector top-up when it ran concurrently with Phase A.
                    progress_dialog.set_status("Assigning models to all entities...")
                    progress_dialog.set_progress(75)
                    QApplication.processEvents()
                    try:
                        self.canvas.model_loader.assign_models_to_entities(
                            self.entities,
                            progress_dialog=progress_dialog,
                            parent=self,
                            game_mode=self.game_mode
                        )
                        log("✓ Model paths assigned for full entity pool")
                    except Exception as _rae:
                        log(f"⚠ Assignment error: {_rae}")

                    # Phase A for any worldsector-only models not already parsed/cached
                    try:
                        from canvas.model_loader import GLTFModel
                        import json as _json
                        _ws_only = {}
                        for _e in self.entities:
                            for _mp in ([getattr(_e, 'model_file', None)] +
                                        [g for g, _ in getattr(_e, 'kit_model_files', [])]):
                                if (_mp and _mp not in self.canvas.model_loader.models_cache
                                        and _mp not in _phase_a_results):
                                    _bp = getattr(_e, 'bin_file', _mp.replace('.gltf', '.bin'))
                                    _ws_only.setdefault(_mp, _bp)

                        if _ws_only:
                            log(f"Phase A (worldsector-only): {len(_ws_only)} additional models...")
                            _ws_list = list(_ws_only.items())
                            _done_ws = 0
                            with concurrent.futures.ThreadPoolExecutor(max_workers=_workers) as _ex:
                                _futs = {_ex.submit(_phase_a_worker, args): args[0]
                                         for args in _ws_list}
                                for _fut in concurrent.futures.as_completed(_futs):
                                    _mp, _m = _fut.result()
                                    if _m:
                                        _phase_a_results[_mp] = _m
                                    _done_ws += 1
                                    if _done_ws % 20 == 0:
                                        QApplication.processEvents()
                            log(f"Phase A worldsector done: {len(_phase_a_results)} total parsed")
                    except Exception as _ws_err:
                        log(f"Phase A worldsector error: {_ws_err}")

            # 8️⃣ Phase B — OpenGL resource creation (must run on main thread).
            if _phase_a_results and hasattr(self, 'canvas') and hasattr(self.canvas, 'model_loader'):
                progress_dialog.set_status("Creating OpenGL resources...")
                progress_dialog.set_progress(78)
                log(f"Phase B: creating GL resources for {len(_phase_a_results)} models...")
                QApplication.processEvents()

                if hasattr(self.canvas, 'makeCurrent'):
                    self.canvas.makeCurrent()

                _b_loaded = 0
                _b_textures = 0
                _b_total = max(len(_phase_a_results), 1)
                for _mp, _m in _phase_a_results.items():
                    # Re-assert context before every model — processEvents() can
                    # temporarily release it when Qt paints other widgets.
                    if hasattr(self.canvas, 'makeCurrent'):
                        self.canvas.makeCurrent()
                    try:
                        if getattr(_m, 'xbg_material_names', None) is not None:
                            self.canvas.model_loader._load_xbg_textures(_m)
                        else:
                            self.canvas.model_loader._load_embedded_textures(_m)
                        _b_textures += len(_m.textures)
                        _m.loaded = True
                        self.canvas.model_loader._create_opengl_resources(_m)
                        self.canvas.model_loader.models_cache[_mp] = _m
                        _b_loaded += 1
                    except Exception as _be:
                        log(f"GL error {os.path.basename(_mp)}: {_be}")
                    if _b_loaded % 30 == 0:
                        _pct = 78 + int((_b_loaded / _b_total) * 7)
                        progress_dialog.set_progress(min(_pct, 84))
                        QApplication.processEvents()

                log(f"Phase B complete: {_b_loaded} models, {_b_textures} textures")

            if progress_dialog.was_cancelled:
                progress_dialog.close()
                return

            # --- FC2: Detect coordinate system and shift entities to global space ---
            # FC2 worldsector .data.fcb files store positions in cell-local space (0–1024).
            # Mapsdata / omnis / managers entities are already in global world space.
            # Only detect and shift worldsector entities so global-coord entities are
            # never double-shifted.
            if self.game_mode == "farcry2":
                _cell_ox, _cell_oy = self._get_fc2_world_offset(
                    level_info['name'], fallback_path=getattr(self, 'sdat_path', None))
                # Use only worldsector entities for the local-vs-global detection
                _ws_entities = [e for e in self.entities
                                if getattr(e, 'source_file', '') == 'worldsectors']
                if _ws_entities:
                    _xs = [e.x for e in _ws_entities if hasattr(e, 'x')]
                    _ys = [e.y for e in _ws_entities if hasattr(e, 'y')]
                    if _xs and _ys:
                        _min_x, _max_x = min(_xs), max(_xs)
                        _min_y, _max_y = min(_ys), max(_ys)
                        print(f"FC2 worldsector coord range: x=[{_min_x:.1f}, {_max_x:.1f}]  y=[{_min_y:.1f}, {_max_y:.1f}]")
                        _has_small_x = _cell_ox > 0 and _min_x < _cell_ox * 0.5
                        _has_small_y = _cell_oy > 0 and _min_y < _cell_oy * 0.5
                        _entities_are_local = (_cell_ox or _cell_oy) and (
                            _has_small_x or _has_small_y
                        )
                        if _entities_are_local:
                            log(f"FC2: shifting {len(_ws_entities)} worldsector entities by "
                                f"({_cell_ox}, {_cell_oy}) to global world coords")
                            for _e in _ws_entities:
                                _e.x += _cell_ox
                                _e.y += _cell_oy
                            self.fc2_cell_offset_x = float(_cell_ox)
                            self.fc2_cell_offset_y = float(_cell_oy)
                        else:
                            log(f"FC2: worldsector entities appear to be in global coords "
                                f"(x_min={_min_x:.1f}, y_min={_min_y:.1f})")
                            self.fc2_cell_offset_x = 0.0
                            self.fc2_cell_offset_y = 0.0
                    else:
                        self.fc2_cell_offset_x = 0.0
                        self.fc2_cell_offset_y = 0.0
                else:
                    self.fc2_cell_offset_x = 0.0
                    self.fc2_cell_offset_y = 0.0
            else:
                self.fc2_cell_offset_x = 0.0
                self.fc2_cell_offset_y = 0.0

            # 9️⃣ Load Terrain
            progress_dialog.set_status("Loading terrain data...")
            progress_dialog.set_progress(86)
            QApplication.processEvents()

            terrain_loaded = False
            if hasattr(self, 'sdat_path') and self.sdat_path:
                # Guarantee the terrain renderer is configured for the current game
                if hasattr(self.canvas, 'terrain_renderer'):
                    if getattr(self.canvas.terrain_renderer, 'game_mode', 'avatar') != self.game_mode:
                        self.canvas.terrain_renderer = TerrainRenderer(game_mode=self.game_mode)
                        log(f"Re-initialized terrain renderer for {self.game_mode}")

                # Clear any multi-cell terrain from a previous load.
                if hasattr(self.canvas, 'terrain_renderer'):
                    self.canvas.terrain_renderer.terrain_pixmap_cells = []
                if hasattr(self.canvas, 'terrain_models'):
                    self.canvas.terrain_models = []

                fc2_cells = getattr(self, '_fc2_sdat_cells', [])
                use_multicell = self.game_mode == "farcry2" and len(fc2_cells) > 1
                avatar_sdats = getattr(self, '_avatar_sdat_paths', [])
                use_avatar_multicell = self.game_mode != "farcry2" and len(avatar_sdats) > 1

                if use_multicell:
                    # ── FC2 multi-cell terrain ──────────────────────────────────────
                    log(f"Loading FC2 terrain from {len(fc2_cells)} cells…")
                    cells_2d_ok = cells_3d_ok = 0
                    for idx, (cell_sdat, cell_name) in enumerate(fc2_cells):
                        cell_ox, cell_oy = self._get_fc2_world_offset(cell_name, fallback_path=cell_sdat)
                        progress_dialog.set_status(
                            f"Loading terrain cell {idx+1}/{len(fc2_cells)}: {cell_name}…")
                        progress_dialog.set_progress(86 + int(8 * idx / len(fc2_cells)))
                        QApplication.processEvents()
                        print(f"[Terrain] Cell {cell_name} sdat={cell_sdat} offset=({cell_ox},{cell_oy})")

                        # 2D
                        if hasattr(self.canvas, 'terrain_renderer'):
                            try:
                                if self.canvas.terrain_renderer.load_sdat_cell(cell_sdat, cell_ox, cell_oy):
                                    cells_2d_ok += 1
                            except Exception as e:
                                print(f"[Terrain 2D] Cell {cell_name} error: {e}")

                        # 3D
                        if hasattr(self.canvas, 'load_terrain_cell_3d'):
                            level_dir = os.path.dirname(cell_sdat) if 'generated' in cell_sdat.lower() else cell_sdat
                            try:
                                if self.canvas.load_terrain_cell_3d(level_dir, cell_ox, cell_oy,
                                                                     resolution=500000, scale=1.0):
                                    cells_3d_ok += 1
                            except Exception as e:
                                print(f"[Terrain 3D] Cell {cell_name} error: {e}")

                    if cells_2d_ok:
                        terrain_loaded = True
                        loaded_components.append(f"Terrain Data (2D — {cells_2d_ok} cells)")
                        log(f"2D terrain: {cells_2d_ok}/{len(fc2_cells)} cells loaded")
                    if cells_3d_ok:
                        terrain_loaded = True
                        loaded_components.append(f"Terrain Data (3D — {cells_3d_ok} cells)")
                        log(f"3D terrain: {cells_3d_ok}/{len(fc2_cells)} cells loaded")
                    if not terrain_loaded:
                        log("Terrain loading failed for all cells")

                elif use_avatar_multicell:
                    # ── Avatar multi-part terrain (e.g. l1 + l2) ───────────────────
                    # Each part is a separate 16×16 tile placed at its own world offset.
                    # The world offset is derived from the part's min sector number and
                    # the row width (sectors_x) established by the first part.
                    log(f"Loading Avatar terrain from {len(avatar_sdats)} parts…")
                    cells_2d_ok = cells_3d_ok = 0
                    sectors_x_hint = None  # set after first part loads

                    for idx, part_sdat in enumerate(avatar_sdats):
                        # Peek at filenames to find this part's global min sector number
                        _part_files = glob.glob(os.path.join(part_sdat, "*.csdat"))
                        _part_nums = []
                        for _f in _part_files:
                            _n = os.path.basename(_f).rsplit('.', 1)[0]
                            try:
                                _part_nums.append(int(_n[2:]) if _n.startswith('sd') else int(_n))
                            except ValueError:
                                pass
                        min_sector = min(_part_nums) if _part_nums else 0

                        if sectors_x_hint is None or min_sector == 0:
                            world_x, world_y = 0.0, 0.0
                        else:
                            _step = 64  # grid_size - 1
                            world_x = float((min_sector % sectors_x_hint) * _step)
                            world_y = float((min_sector // sectors_x_hint) * _step)

                        progress_dialog.set_status(
                            f"Loading terrain part {idx+1}/{len(avatar_sdats)}: "
                            f"{os.path.basename(os.path.dirname(part_sdat))}…")
                        progress_dialog.set_progress(86 + int(8 * idx / len(avatar_sdats)))
                        QApplication.processEvents()
                        print(f"[Terrain] Avatar part {idx+1}: min_sector={min_sector} "
                              f"offset=({world_x},{world_y}) sdat={part_sdat}")

                        # 2D
                        if hasattr(self.canvas, 'terrain_renderer'):
                            try:
                                if self.canvas.terrain_renderer.load_sdat_cell(part_sdat, world_x, world_y):
                                    cells_2d_ok += 1
                                    if sectors_x_hint is None:
                                        sectors_x_hint = self.canvas.terrain_renderer.sectors_x
                            except Exception as e:
                                print(f"[Terrain 2D] Part {idx+1} error: {e}")

                        # 3D
                        if hasattr(self.canvas, 'load_terrain_cell_3d'):
                            level_dir = (os.path.dirname(part_sdat)
                                         if 'generated' in part_sdat.lower() else part_sdat)
                            try:
                                if self.canvas.load_terrain_cell_3d(level_dir, world_x, world_y,
                                                                     resolution=500000, scale=1.0):
                                    cells_3d_ok += 1
                            except Exception as e:
                                print(f"[Terrain 3D] Part {idx+1} error: {e}")

                    if cells_2d_ok:
                        terrain_loaded = True
                        loaded_components.append(f"Terrain Data (2D — {cells_2d_ok} parts)")
                        log(f"2D terrain: {cells_2d_ok}/{len(avatar_sdats)} parts loaded")
                    if cells_3d_ok:
                        terrain_loaded = True
                        loaded_components.append(f"Terrain Data (3D — {cells_3d_ok} parts)")
                        log(f"3D terrain: {cells_3d_ok}/{len(avatar_sdats)} parts loaded")
                    if not terrain_loaded:
                        log("Terrain loading failed for all parts")

                else:
                    # ── Single-cell terrain (Avatar single-part or single FC2 cell) ──
                    fc2_offset_x, fc2_offset_y = 0, 0
                    if self.game_mode == "farcry2":
                        fc2_offset_x, fc2_offset_y = self._get_fc2_world_offset(
                            level_info['name'], fallback_path=self.sdat_path)
                    print(f"[Terrain] World offset: ({fc2_offset_x}, {fc2_offset_y}) for '{level_info['name']}'")

                    self.canvas.terrain_world_offset_x = float(fc2_offset_x)
                    self.canvas.terrain_world_offset_y = float(fc2_offset_y)
                    if hasattr(self.canvas, 'terrain_renderer'):
                        self.canvas.terrain_renderer.terrain_offset_x = float(fc2_offset_x)
                        self.canvas.terrain_renderer.terrain_offset_y = float(fc2_offset_y)
                    if fc2_offset_x or fc2_offset_y:
                        log(f"FC2 terrain world offset: ({fc2_offset_x}, {fc2_offset_y})")

                    log(f"Loading terrain from sdat folder...")
                    print(f"Loading terrain from: {self.sdat_path}")
                    try:
                        if hasattr(self.canvas, 'load_terrain'):
                            if self.canvas.load_terrain(self.sdat_path):
                                terrain_loaded = True
                                loaded_components.append("Terrain Data (2D Heightmap)")
                                log("2D terrain loaded successfully")

                        if hasattr(self.canvas, 'load_terrain_for_level'):
                            progress_dialog.set_status("Generating 3D terrain GLTF (500k tris)...")
                            progress_dialog.set_progress(90)
                            log("Generating 3D terrain model...")
                            QApplication.processEvents()
                            level_dir = (os.path.dirname(self.sdat_path)
                                         if 'generated' in self.sdat_path.lower()
                                         else self.sdat_path)
                            if self.canvas.load_terrain_for_level(level_dir, resolution=500000, scale=1.0):
                                terrain_loaded = True
                                loaded_components.append("Terrain Data (3D Model - 100k tris)")
                                log("3D terrain GLTF generated and loaded")
                            else:
                                log("3D terrain generation failed (will use fallback)")

                        if not terrain_loaded:
                            log("Terrain loading failed")

                    except Exception as terrain_error:
                        log(f"Error loading terrain: {str(terrain_error)}")
                        print(f"Error loading terrain: {terrain_error}")
                        import traceback
                        traceback.print_exc()


            # 🔟 Load moviedata.xml (cinematic sequences)
            self.movie_data = None
            self.selected_movie_sequence = None
            self.selected_movie_node_id = None
            try:
                _res_folder = getattr(self, 'resource_folder', None)
                movie_path = find_moviedata_xml(level_info, resource_folder=_res_folder)
                if movie_path:
                    self.movie_data = MovieData.load(movie_path)
                    seq_count = len(self.movie_data.sequences)
                    node_count = len(self.movie_data.node_defs)
                    log(f"Loaded moviedata.xml: {seq_count} sequences, {node_count} nodes")
                    loaded_components.append(f"Movie Data ({seq_count} sequences)")
                else:
                    log("No moviedata.xml found for this level")
            except Exception as _me:
                log(f"moviedata.xml load error: {_me}")
            if hasattr(self, 'sequences_tree'):
                self.update_sequences_tab()

            # 9️⃣ UI Finalization
            progress_dialog.set_status("Updating display...")
            progress_dialog.set_progress(90)
            log("Finalizing UI...")
            QApplication.processEvents()

            if hasattr(self, 'update_entity_statistics'):
                self.update_entity_statistics()
            self.canvas.set_entities(self.entities)
            if hasattr(self, 'entity_tree'):
                self.update_entity_tree()
            if self.canvas.mode != 1:  # don't reset 3D camera on level load — keep it where it is
                self.reset_view()

            level_name = level_info['name']
            if hasattr(self, 'level_info_label'):
                self.level_info_label.setText(f"Loaded complete level: {level_name}")
            elif hasattr(self, 'xml_file_label'):
                self.xml_file_label.setText(f"Loaded complete level: {level_name}")
            
            self.status_bar.showMessage(f"Loaded {level_name}: {total_entities} total entities/objects")
            
            # Store level info
            self.current_level_info = level_info
            
            # Complete
            progress_dialog.set_progress(100)
            log(f"Level loading complete!")
            progress_dialog.mark_complete()
            progress_dialog.close()
            
            # Summary popup
            if loaded_components:
                success_message = f"Successfully loaded level '{level_name}':\n\n"
                success_message += "\n".join([f"✓ {c}" for c in loaded_components])
                success_message += f"\n\nTotal entities/objects: {total_entities}"
                QMessageBox.information(self, "Level Loaded Successfully", success_message)
            else:
                QMessageBox.warning(self, "No Data Loaded", f"No valid data found for level '{level_name}'")
            
            # Reset all modification flags
            self.xml_tree_modified = False
            self.omnis_tree_modified = False
            self.managers_tree_modified = False
            self.sectordep_tree_modified = False
            self.entities_modified = False
            if hasattr(self, 'worldsectors_modified'):
                self.worldsectors_modified.clear()
            
            print(f"=== COMPLETE LEVEL LOADING FINISHED ===\n")
        
        except Exception as e:
            if 'progress_dialog' in locals():
                progress_dialog.mark_complete()
                progress_dialog.close()
            QMessageBox.critical(self, "Error Loading Level", f"Failed to load level: {str(e)}")
            print(f"Error loading complete level: {e}")
            import traceback
            traceback.print_exc()

    def load_level_objects_internal(self, levels_path, progress_dialog=None, progress_callback=None):
        """Internal method to load level objects without UI dialogs"""
        try:
            # Enhanced search for worldsectors
            worldsectors_info = self.find_worldsectors_folder_enhanced(levels_path)
            
            if not worldsectors_info:
                print(f"No worldsectors found in {levels_path}")
                return False
            
            worldsectors_path = worldsectors_info["path"]
            print(f"Found worldsectors at: {worldsectors_path}")
            
            # Store worldsectors path
            self.worldsectors_path = worldsectors_path
            
            # Load objects directly without threading (simpler and safer)
            from data_models import WorldSectorManager, ObjectParser
            
            # Step 1: Scan for sectors
            if progress_dialog:
                progress_dialog.append_log("Scanning worldsectors...")
            QApplication.processEvents()
            
            sectors = WorldSectorManager.scan_worldsectors_folder(worldsectors_path)
            
            if progress_dialog:
                progress_dialog.append_log(f"Found {len(sectors)} sectors")
            QApplication.processEvents()
            
            # Step 2: Convert FCB files if needed
            if progress_dialog:
                progress_dialog.append_log("Converting FCB files...")
            QApplication.processEvents()
            
            def conversion_progress(progress, message=None):
                if progress_callback:
                    progress_callback(progress * 0.5)  # Use first 50% for conversion
                if message and progress_dialog:
                    progress_dialog.append_log(message)
                QApplication.processEvents()
            
            success_count, error_count, converted_files = self.file_converter.convert_data_fcb_files(
                worldsectors_path,
                progress_callback=conversion_progress
            )
            
            if progress_dialog:
                progress_dialog.append_log(f"Converted: {success_count} successful, {error_count} failed")
            QApplication.processEvents()
            
            # Step 3: Re-scan after conversion
            sectors = WorldSectorManager.scan_worldsectors_folder(worldsectors_path)
            
            # Step 4: Load objects from XML files
            all_objects = []
            total_xml_files = sum(len(sector.data_xml_files) for sector in sectors)
            files_processed = 0
            
            if progress_dialog:
                progress_dialog.append_log(f"Loading objects from {total_xml_files} files...")
            QApplication.processEvents()
            
            for i, sector in enumerate(sectors):
                for xml_file in sector.data_xml_files:
                    if xml_file.endswith('.converted.xml'):
                        try:
                            objects = ObjectParser.extract_objects_from_data_xml(
                                xml_file,
                                sector_path=sector.folder_path
                            )

                            # Store landmark trees so edits can be saved back to disk.
                            # (landmark files are excluded from worldsectors_trees)
                            bn_lm = os.path.basename(xml_file).lower()
                            if bn_lm.startswith('landmarkfar') or bn_lm.startswith('landmarknear'):
                                try:
                                    if not hasattr(self, 'landmark_trees'):
                                        self.landmark_trees = {}
                                    if not hasattr(self, 'landmark_clean_hashes'):
                                        self.landmark_clean_hashes = {}
                                    with open(xml_file, 'r', encoding='utf-8') as _fh:
                                        _lm_text = _fh.read()
                                    import io as _io_lm
                                    _lm_tree = ET.ElementTree(ET.fromstring(_lm_text))
                                    _lm_buf = _io_lm.BytesIO()
                                    _lm_tree.write(_lm_buf, encoding='utf-8', xml_declaration=True)
                                    self.landmark_clean_hashes[xml_file] = str(hash(_lm_buf.getvalue()))
                                    self.landmark_trees[xml_file] = _lm_tree
                                except Exception:
                                    pass

                            for obj in objects:
                                if self.grid_config and self.grid_config.maps:
                                    obj.map_name = self._determine_object_map(obj)
                            
                            all_objects.extend(objects)
                            
                            if progress_dialog:
                                progress_dialog.append_log(f"Loaded {len(objects)} from {os.path.basename(xml_file)}")
                            
                        except Exception as e:
                            if progress_dialog:
                                progress_dialog.append_log(f"Error loading {xml_file}: {str(e)}")
                    
                    files_processed += 1
                    if progress_callback and total_xml_files > 0:
                        file_progress = 0.5 + (files_processed / total_xml_files) * 0.5  # Use second 50%
                        progress_callback(file_progress)
                    
                    # CRITICAL: Process events after each file
                    QApplication.processEvents()
            
            # Process loaded objects
            if all_objects:
                self.on_objects_loaded(all_objects)
                print(f"Loaded {len(all_objects)} objects from level data")
                return True
            else:
                print("No objects were loaded from level data")
                return False
            
        except Exception as e:
            print(f"Error loading level objects: {e}")
            import traceback
            traceback.print_exc()
            return False

    def load_all_worldsectors(self, worldsectors_folder, log_callback=None, progress_callback=None):
        """
        Load ALL worldsector files into a single unified entity pool.

        This is opt-in — load_complete_level (single-sector mode) is unchanged.
        After this call:
          - self.entities is extended with all sector entities
          - self.worldsectors_trees holds every sector's ET.ElementTree
          - self.sector_clean_hashes[sector_id] = hash_str for dirty detection
          - canvas.unified_mode = True
          - canvas.current_map = None (disables per-map filter)

        Avatar only. Skips landmarkfar_* and landmarknear* files.

        Returns:
            int: number of entities loaded across all sectors, or -1 on fatal error
        """
        def _log(msg):
            print(msg)
            if log_callback:
                try:
                    log_callback(msg)
                except Exception:
                    pass

        _log(f"\n=== UNIFIED SECTOR LOAD: {worldsectors_folder} ===")

        if not os.path.isdir(worldsectors_folder):
            _log(f"ERROR: worldsectors folder does not exist: {worldsectors_folder}")
            return -1

        # ── 1. Discover and convert FCB files ────────────────────────────────
        fcb_files = [
            f for f in glob.glob(os.path.join(worldsectors_folder, "worldsector*.data.fcb"))
            if not os.path.basename(f).startswith(("landmarkfar_", "landmarknear"))
        ]
        _log(f"Found {len(fcb_files)} worldsector FCB files")
        if not fcb_files:
            _log("No worldsector FCB files found — nothing to load")
            return 0

        convert_ok, convert_err, _ = self.file_converter.convert_data_fcb_files(
            worldsectors_folder
        )
        _log(f"FCB conversion: {convert_ok} OK, {convert_err} errors")

        # Build list of converted XML paths (one per FCB file)
        xml_files = []
        for fcb in fcb_files:
            xml_path = fcb + ".converted.xml"
            if os.path.exists(xml_path):
                xml_files.append(xml_path)
            else:
                _log(f"  WARNING: no converted XML for {os.path.basename(fcb)}")

        if not xml_files:
            _log("No converted XML files found — aborting")
            return -1

        # ── 2. Parse each sector XML ──────────────────────────────────────────
        total_entities = 0
        new_entities = []
        sorted_xml = sorted(xml_files)
        total_files = len(sorted_xml)
        log_interval = max(1, total_files // 10)

        for i, xml_path in enumerate(sorted_xml):
            basename = os.path.basename(xml_path)
            try:
                with open(xml_path, 'r', encoding='utf-8') as fh:
                    xml_text = fh.read()
                clean_hash = str(hash(xml_text))

                tree = ET.ElementTree(ET.fromstring(xml_text))
                root = tree.getroot()

                # Extract sector grid coords from WorldSector header fields
                gx = gy = 0
                x_field = root.find("./field[@name='X']")
                if x_field is not None:
                    try:
                        gx = int(x_field.get('value-Int32', 0))
                    except (ValueError, TypeError):
                        pass
                y_field = root.find("./field[@name='Y']")
                if y_field is not None:
                    try:
                        gy = int(y_field.get('value-Int32', 0))
                    except (ValueError, TypeError):
                        pass
                sector_id = gy * 16 + gx

                # Store tree and clean hash
                self.worldsectors_trees[xml_path] = tree
                self.sector_clean_hashes[sector_id] = clean_hash

                # Parse entities, grouped by MissionLayer
                file_entity_count = 0
                for layer_elem in root.findall("./object[@name='MissionLayer']"):
                    layer_name = "main"
                    path_id_field = layer_elem.find("./field[@name='text_PathId']")
                    if path_id_field is not None:
                        layer_name = path_id_field.get('value-String', 'main') or 'main'

                    for entity_elem in layer_elem.findall("./object[@name='Entity']"):
                        try:
                            # ID
                            entity_id = "Unknown"
                            id_field = entity_elem.find("./field[@name='disEntityId']")
                            if id_field is not None:
                                entity_id = (
                                    id_field.get('value-Id64') or
                                    id_field.get('value-String') or
                                    "Unknown"
                                ).strip()

                            # Name
                            entity_name = ""
                            name_field = entity_elem.find("./field[@name='hidName']")
                            if name_field is not None:
                                entity_name = name_field.get('value-String', '') or ''
                            if not entity_name:
                                ct_field = entity_elem.find("./field[@name='tplCreatureType']")
                                if ct_field is not None:
                                    entity_name = ct_field.get('value-String', '') or ''
                            if not entity_name:
                                entity_name = "Unnamed"

                            # Position
                            x = y = z = 0.0
                            pos_field = entity_elem.find("./field[@name='hidPos']")
                            if pos_field is None:
                                pos_field = entity_elem.find("./field[@name='hidPos_precise']")
                            if pos_field is not None:
                                pos_val = pos_field.get('value-Vector3', '')
                                if pos_val:
                                    coords = pos_val.split(',')
                                    if len(coords) == 3:
                                        x, y, z = float(coords[0]), float(coords[1]), float(coords[2])

                            entity = Entity(entity_id, entity_name, x, y, z, entity_elem)
                            entity.source_file = 'worldsectors'
                            entity.source_file_path = xml_path
                            entity.source_sector_id = sector_id
                            entity.source_layer = layer_name
                            if self.grid_config and self.grid_config.maps:
                                entity.map_name = self.determine_entity_map(entity)

                            new_entities.append(entity)
                            file_entity_count += 1

                        except Exception as e:
                            _log(f"  Error parsing entity in {basename}: {e}")

                total_entities += file_entity_count

                if progress_callback:
                    progress_callback(87 + int((i + 1) / total_files * 8))
                if (i + 1) % log_interval == 0 or (i + 1) == total_files:
                    _log(f"  Sectors: {i + 1}/{total_files} loaded ({total_entities} entities)")
                else:
                    QApplication.processEvents()

            except Exception as e:
                _log(f"  ERROR loading {basename}: {e}")
                import traceback
                traceback.print_exc()

        # ── 3. Replace entity pool with all-sectors data ─────────────────────
        # Remove any entity already in the pool whose ID matches one of the fresh
        # worldsector entities.  Using ID-based dedup (rather than source_file tagging)
        # is more robust: it catches entities that slipped through without being tagged
        # as 'worldsectors' (e.g. if source_file was None or the filename check missed
        # them), so we never end up with ghost duplicates on the canvas.
        new_entity_ids = {e.id for e in new_entities}
        before_count = len(self.entities)
        self.entities = [
            e for e in self.entities
            if e.id not in new_entity_ids
        ] + new_entities
        removed = before_count - (len(self.entities) - len(new_entities))
        _log(f"Unified load complete: {total_entities} entities from {len(xml_files)} sectors "
             f"(replaced {removed} pre-existing worldsector entities)")

        # ── 4. Activate unified mode ──────────────────────────────────────────
        if hasattr(self, 'canvas'):
            self.canvas.unified_mode = True
            self.canvas.current_map = None   # disables per-map filter
            self.canvas.set_entities(self.entities)

            # Auto-enable sector boundary overlay in unified mode
            self.canvas.show_sector_boundaries = True
            if not getattr(self.canvas, 'sector_data', None):
                try:
                    self.load_sector_data_for_canvas()
                except Exception:
                    pass

        if hasattr(self, 'update_entity_tree'):
            self.update_entity_tree()
        if hasattr(self, 'update_entity_statistics'):
            self.update_entity_statistics()

        # Status bar
        n_sectors = len(xml_files)
        if hasattr(self, 'statusBar'):
            self.statusBar().showMessage(
                f"Unified mode — {n_sectors} sectors loaded, {total_entities} entities")

        return total_entities

    def open_all_sectors(self):
        """Open all worldsector files at once into unified mode."""
        # If a worldsectors folder is already known from the current level, use it
        folder = getattr(self, 'worldsectors_path', None)

        if not folder or not os.path.isdir(folder):
            folder = QFileDialog.getExistingDirectory(
                self,
                "Select Worldsectors Folder (contains worldsector*.data.fcb files)",
                ""
            )

        if not folder:
            return

        if not os.path.isdir(folder):
            QMessageBox.warning(self, "Open All Sectors",
                                f"Folder not found:\n{folder}")
            return

        n = self.load_all_worldsectors(folder)
        if n < 0:
            QMessageBox.critical(self, "Open All Sectors",
                                 "No worldsector FCB files found in the selected folder.")
        elif n == 0:
            QMessageBox.information(self, "Open All Sectors",
                                    "Folder found but contained no entities.")

    def _determine_object_map(self, obj):
        """Determine which map an object belongs to based on its coordinates"""
        if not self.grid_config or not self.grid_config.maps:
            return None
            
        # Convert object coordinates to sector coordinates
        sector_x = int(obj.x / self.grid_config.sector_granularity)
        sector_y = int(obj.z / self.grid_config.sector_granularity)
        
        # Check each map
        for map_info in self.grid_config.maps:
            min_sector_x = map_info.sector_offset_x
            min_sector_y = map_info.sector_offset_y
            max_sector_x = min_sector_x + map_info.count_x
            max_sector_y = min_sector_y + map_info.count_y
            
            if (min_sector_x <= sector_x < max_sector_x and 
                min_sector_y <= sector_y < max_sector_y):
                return map_info.name
        
        return None
    
    def load_level_folder(self):
        """Load a level folder with enhanced subfolder search - WITH COMPREHENSIVE RESET"""
        # COMPREHENSIVE RESET FIRST
        self.reset_entire_editor_state()
        
        # Open folder selection dialog
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Select Worlds Folder (will search subfolders automatically)",
            ""
        )
        
        if not folder_path:
            return
        
        try:
            print(f"Loading level from: {folder_path}")
            
            # DEBUG: Check game mode before creating dialog
            print(f"DEBUG: self.game_mode = '{self.game_mode}'")
            
            # Create enhanced progress dialog
            progress_dialog = EnhancedProgressDialog("Loading Level", self, game_mode=self.game_mode)
            
            # Connect cancel signal
            progress_dialog.cancelled.connect(
                lambda: self.cancel_loading(self.object_loading_thread if hasattr(self, 'object_loading_thread') else None, progress_dialog)
            )
            
            progress_dialog.show()
            QApplication.processEvents()
            
            # Enhanced search for files
            progress_dialog.set_status("Searching for level files, Please wait.")
            progress_dialog.set_progress(10)
            progress_dialog.append_log("Searching for XML files...")
            QApplication.processEvents()
            
            found_files = self.find_xml_files_enhanced(folder_path)
            progress_dialog.append_log(f"Found {len(found_files)} file types")
            
            # Setup EntityLibrary folder for 3D model lookups
            if hasattr(self, 'canvas') and hasattr(self.canvas, 'model_loader'):
                print(f"\n=== Setting up EntityLibrary for 3D models ===")
                if self.canvas.model_loader.set_entity_library_folder(folder_path):
                    print(f"EntityLibrary configured for model lookups")
                    progress_dialog.append_log("EntityLibrary found for 3D models")
                else:
                    print(f"EntityLibrary not found (3D models will use fallback)")
                    progress_dialog.append_log("No EntityLibrary (3D models disabled)")
            
            # Also search for worldsectors
            worldsectors_info = self.find_worldsectors_folder_enhanced(folder_path)
            if worldsectors_info:
                progress_dialog.append_log(f"Found worldsectors: {worldsectors_info['fcb_files']} FCB files")
            
            # Progress callback for conversion
            def update_progress(progress, message=None):
                if progress_dialog.was_cancelled:
                    return  # Just return, don't raise exception
                percent = int(10 + progress * 40)
                progress_dialog.set_progress(percent)
                if message:
                    progress_dialog.append_log(message)
                else:
                    progress_dialog.set_status(f"Converting files, Please Wait. {percent}%")
                QApplication.processEvents()
            
            # Convert files if needed
            try:
                success_count, error_count, errors = self.file_converter.convert_folder(
                    folder_path, 
                    progress_callback=update_progress
                )
                progress_dialog.append_log(f"Conversion: {success_count} successful, {error_count} failed")
                
                if error_count > 0:
                    for error in errors[:3]:
                        progress_dialog.append_log(f"  Error: {error}")
                
                # Check if cancelled during conversion
                if progress_dialog.was_cancelled:
                    progress_dialog.append_log("Operation cancelled by user")
                    progress_dialog.stop_icon()
                    progress_dialog.close()
                    return
                                
            except Exception as e:
                progress_dialog.append_log(f"Conversion error: {str(e)}")
                print(f"Error during conversion: {str(e)}. Continuing with existing XML files, Please wait.")
            
            # Check if cancelled
            if progress_dialog.was_cancelled:
                progress_dialog.stop_icon()
                progress_dialog.close()
                return
            
            # Check if we found the essential files
            if not found_files:
                progress_dialog.stop_icon()
                progress_dialog.close()
                
                search_info = "Searched in:\nMain folder\nAll subfolders (up to 3 levels deep)\n\n"
                search_info += "Looking for:\nmapsdata.xml/.fcb\n.managers.xml/.fcb\n.omnis.xml/.fcb\nsectorsdep.xml/.fcb"
                
                if worldsectors_info:
                    search_info += f"\n\nFound worldsectors folder:\n{worldsectors_info['relative_path']} ({worldsectors_info['fcb_files']} .fcb files)"
                
                QMessageBox.warning(
                    self,
                    "Main Files Not Found",
                    f"Could not find the main level files in the selected folder or subfolders.\n\n{search_info}\n\n"
                    f"Please ensure the conversion tools are available or that XML versions exist."
                )
                return
            
            # Update progress for file loading
            progress_dialog.set_status("Loading XML files, Please wait.")
            progress_dialog.set_progress(60)
            progress_dialog.append_log("Processing XML files...")
            QApplication.processEvents()
            
            # Load the found files
            loaded_files = []
            
            progress_dialog.set_progress(70)
            progress_dialog.set_status("Processing entities, Please wait.")
            QApplication.processEvents()
            
            # Load mapsdata first
            if "mapsdata" in found_files:
                self.xml_file_path = found_files["mapsdata"]["path"]
                self.parse_xml_file(self.xml_file_path)
                
                location = found_files["mapsdata"]["location"]
                location_text = f" (found in {location})" if location != "." else ""
                loaded_files.append(f"{os.path.basename(self.xml_file_path)} ({len(self.entities)} entities){location_text}")
                progress_dialog.append_log(f"Loaded mapsdata: {len(self.entities)} entities")
            
            # Check if cancelled
            if progress_dialog.was_cancelled:
                progress_dialog.stop_icon()
                progress_dialog.close()
                return
            
            progress_dialog.set_progress(80)
            QApplication.processEvents()
            
            # Load other files
            file_loaders = {
                "omnis": self.load_omnis_data,
                "managers": self.load_managers_data, 
                "sectorsdep": self.load_sectordep_data
            }
            
            for file_key, loader_func in file_loaders.items():
                if progress_dialog.was_cancelled:
                    progress_dialog.stop_icon()
                    progress_dialog.close()
                    return
                
                if file_key in found_files:
                    entity_count_before = len(self.entities)
                    loader_func(found_files[file_key]["path"])
                    entity_count_after = len(self.entities)
                    new_entities = entity_count_after - entity_count_before
                    
                    location = found_files[file_key]["location"]
                    location_text = f" (found in {location})" if location != "." else ""
                    loaded_files.append(f"{os.path.basename(found_files[file_key]['path'])} ({new_entities} entities){location_text}")
                    progress_dialog.append_log(f"Loaded {file_key}: {new_entities} entities")
            
            # Check if cancelled
            if progress_dialog.was_cancelled:
                progress_dialog.stop_icon()
                progress_dialog.close()
                return
            
            progress_dialog.set_progress(95)
            progress_dialog.set_status("Updating display, Please wait.")
            QApplication.processEvents()
            
            # Update UI
            folder_name = os.path.basename(folder_path)
            if hasattr(self, 'xml_file_label'):
                self.xml_file_label.setText(f"Loaded {len(loaded_files)} main files from:\n{folder_name}")
            elif hasattr(self, 'level_info_label'):
                self.level_info_label.setText(f"Loaded {len(loaded_files)} main files from:\n{folder_name}")
            
            self.status_bar.showMessage(f"Loaded level: {len(self.entities)} total entities")
            
            # Update displays
            if hasattr(self, 'update_entity_statistics'):
                self.update_entity_statistics()
            
            self.canvas.set_entities(self.entities)
            
            if hasattr(self, 'entity_tree'):
                self.update_entity_tree()
            
            self.reset_view()
            
            # Mark complete and close progress dialog BEFORE showing success message
            progress_dialog.set_progress(100)
            progress_dialog.mark_complete()
            progress_dialog.stop_icon()
            progress_dialog.close()
            
            # Build success message
            success_message = f"Successfully loaded the main level files:\n\n" + "\n".join(loaded_files)
            
            if worldsectors_info:
                success_message += f"\n\nAlso found worldsectors folder:\n{worldsectors_info['relative_path']}"
                success_message += f"\n  ({worldsectors_info['fcb_files']} .fcb, {worldsectors_info['xml_files']} .xml files)"
                success_message += f"\n\nUse 'Load Objects' to load worldsector entities."
            
            success_message += f"\n\nTotal entities: {len(self.entities)}"
            
            # Show success message AFTER closing dialog
            QMessageBox.information(
                self,
                "Level Loaded Successfully",
                success_message
            )
            
            # Reset all modification flags
            self.xml_tree_modified = False
            self.omnis_tree_modified = False
            self.managers_tree_modified = False
            self.sectordep_tree_modified = False
            self.entities_modified = False

        except Exception as e:
            if 'progress_dialog' in locals():
                progress_dialog.mark_complete()
                progress_dialog.stop_icon()
                progress_dialog.close()
            QMessageBox.critical(
                self, 
                "Error", 
                f"Failed to load level: {str(e)}"
            )

    def handle_load_cancel(self, dialog):
        """Handle cancellation of load operation"""
        dialog.append_log("Stopping load operation...")
        # The dialog will close naturally when the method returns

    def load_level_objects(self):
        """Load objects from worldsectors folder with enhanced search - WITH ANIMATED LOADING ICON AND LOG"""
        print("=== Starting enhanced load_level_objects ===")
        
        # COMPREHENSIVE RESET FIRST
        self.reset_entire_editor_state()
        
        # Select folder
        selected_folder = QFileDialog.getExistingDirectory(
            self,
            "Select Level Folder (containing worldsectors)",
            ""
        )
        
        if not selected_folder:
            print("No folder selected")
            return
        
        print(f"Selected folder: {selected_folder}")
        
        # Enhanced search for worldsectors
        worldsectors_info = self.find_worldsectors_folder_enhanced(selected_folder)
        
        if not worldsectors_info:
            QMessageBox.warning(
                self,
                "No Worldsectors Found",
                f"No worldsectors folder found in:\n{selected_folder}"
            )
            return
        
        worldsectors_path = worldsectors_info["path"]
        print(f"Found worldsectors at: {worldsectors_path}")
        
        # *** NEW: Look for sdat folder in the same parent directory ***
        parent_dir = os.path.dirname(worldsectors_path)
        sdat_candidate = os.path.join(parent_dir, "sdat")
        if os.path.isdir(sdat_candidate):
            self.sdat_path = sdat_candidate
            print(f"Found sdat folder at: {self.sdat_path}")
        else:
            self.sdat_path = None
            print("No sdat folder found (terrain data will not be available)")
        
        # Check file counts
        total_files = worldsectors_info["fcb_files"] + worldsectors_info["xml_files"] + worldsectors_info["data_xml_files"]
        
        if total_files == 0:
            QMessageBox.warning(
                self,
                "No Object Files Found",
                f"No .data.fcb or .data.xml files found in:\n{worldsectors_info['relative_path']}"
            )
            return
        
        # Show confirmation dialog
        location_text = f"in {worldsectors_info['relative_path']}" if worldsectors_info['relative_path'] != "." else "in selected folder"
        
        message = (
            f"Found worldsectors {location_text}:\n\n"
            f"{worldsectors_info['fcb_files']} .data.fcb files\n"
            f"{worldsectors_info['xml_files']} .converted.xml files\n"
            f"{worldsectors_info['data_xml_files']} .data.xml files\n\n"
            f"Continue?"
        )
        
        reply = QMessageBox.question(
            self,
            "Load Level Objects",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Store worldsectors path
        self.worldsectors_path = worldsectors_path
        
        # Create enhanced progress dialog
        progress_dialog = EnhancedProgressDialog("Loading Level Objects", self, game_mode=self.game_mode)
        progress_dialog.show()
        QApplication.processEvents()
        
        print("Creating ObjectLoadingThread, Please wait.")
        
        try:
            # Create and start loading thread
            self.object_loading_thread = ObjectLoadingThread(
                worldsectors_path, 
                self.file_converter, 
                self.grid_config
            )
            
            # Connect thread signals
            self.object_loading_thread.progress_updated.connect(
                lambda p: progress_dialog.set_progress(int(p * 100))
            )
            self.object_loading_thread.status_updated.connect(
                lambda s: progress_dialog.set_status(s)
            )
            
            # Connect log messages signal
            self.object_loading_thread.log_message.connect(
                lambda msg: progress_dialog.append_log(msg)
            )
            
            self.object_loading_thread.objects_loaded.connect(self.on_objects_loaded)
            self.object_loading_thread.finished_loading.connect(
                lambda result: self.on_object_loading_finished(result, progress_dialog)
            )
                        
            # Handle cancel button AND X button via the cancelled signal
            progress_dialog.cancelled.connect(
                lambda: self.cancel_loading(self.object_loading_thread, progress_dialog)
            )

            print("Starting object loading thread, Please wait.")
            
            # Start loading
            self.object_loading_thread.start()
            
        except Exception as e:
            progress_dialog.stop_icon()
            progress_dialog.close()
            QMessageBox.critical(
                self,
                "Loading Error",
                f"Failed to start object loading:\n{str(e)}"
            )
            print(f"Error starting object loading: {e}")
            import traceback
            traceback.print_exc()

    def append_log_message(self, log_box, message):
        """Append a message to the log box and auto-scroll"""
        log_box.append(message)
        # Auto-scroll to bottom
        scrollbar = log_box.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def cancel_loading(self, thread, dialog):
        """Cancel the loading operation - close dialog after stopping thread"""
        thread.stop()
        dialog.stop_icon()
        # Close the dialog immediately after cancelling
        dialog.close()

    def on_object_loading_finished(self, result, progress_dialog):
        """
        Handle when object loading is complete and automatically load terrain if available.
        """
        progress_dialog.mark_complete()
        progress_dialog.stop_icon()
        progress_dialog.close()

        if not progress_dialog.was_cancelled:
            # Show conversion errors if any
            if result.conversion_errors:
                error_msg = "\n".join(result.conversion_errors[:5])
                if len(result.conversion_errors) > 5:
                    error_msg += f"\n... and {len(result.conversion_errors) - 5} more errors"
                QMessageBox.warning(
                    self,
                    "Loading Completed with Errors",
                    f"Loaded {result.loaded_objects} objects from {result.sectors_processed} sectors.\n\n"
                    f"Errors encountered:\n{error_msg}"
                )
            else:
                QMessageBox.information(
                    self,
                    "Objects Loaded Successfully",
                    f"Successfully loaded {result.loaded_objects} objects from {result.sectors_processed} sectors!"
                )

            # Update status bar
            self.status_bar.showMessage(
                f"Loaded {len(self.entities)} entities and {len(self.objects)} objects"
            )

            # Reset view
            self.reset_view()

            # Auto-load terrain
            if self.sdat_path:
                try:
                    print(f"Attempting to load terrain from: {self.sdat_path}")
                    if not hasattr(self.canvas, 'terrain_renderer') or self.canvas.terrain_renderer is None:
                        from canvas.terrain_renderer import TerrainRenderer
                        self.canvas.terrain_renderer = TerrainRenderer(game_mode=self.game_mode)
                        print(f"Initialized TerrainRenderer for game mode: {self.game_mode}")

                    success = self.canvas.load_terrain(self.sdat_path)

                    if success:
                        print("Terrain loaded successfully into canvas!")

                        if self.game_mode.lower() == "farcry2":
                            tr = self.canvas.terrain_renderer
                            center_x = (tr.terrain_world_min_x + tr.terrain_world_max_x) / 2
                            center_y = (tr.terrain_world_min_y + tr.terrain_world_max_y) / 2

                            if hasattr(self.canvas, "center_on_world"):
                                self.canvas.center_on_world(center_x, center_y)
                            else:
                                self.canvas.viewport_offset_x = center_x
                                self.canvas.viewport_offset_y = center_y

                            print(f"[FC2] View centered on terrain at ({center_x}, {center_y})")
                    else:
                        print("Failed to load terrain data")

                except Exception as e:
                    print(f"Error loading terrain: {e}")
                    import traceback
                    traceback.print_exc()
                    QMessageBox.warning(
                        self,
                        "Terrain Loading Error",
                        f"Could not load terrain:\n{str(e)}"
                    )

    def load_terrain_viewer(self):
        """Load terrain data directly into the canvas"""
        if not self.sdat_path:
            print("No sdat path available, cannot load terrain")
            return False

        try:
            print(f"Loading terrain data from: {self.sdat_path}")
            success = self.canvas.load_terrain(self.sdat_path)

            if success:
                print("Terrain loaded successfully into canvas!")
            else:
                print("Failed to load terrain data")
            return success

        except Exception as e:
            print(f"Error loading terrain: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.warning(
                self,
                "Terrain Loading Error",
                f"Could not load terrain:\n{str(e)}"
            )
            return False

    def auto_load_terrain_if_available(self, base_path):
        """Automatically search for and load terrain data from a base path"""
        if not base_path or not os.path.isdir(base_path):
            return False

        print(f"Searching for terrain data in: {base_path}")

        sdat_candidates = [
            os.path.join(base_path, "sdat"),
            os.path.join(os.path.dirname(base_path), "sdat"),
            os.path.join(base_path, "levels", "sdat"),
        ]

        found_sdat = None
        for candidate in sdat_candidates:
            if os.path.isdir(candidate):
                csdat_files = glob.glob(os.path.join(candidate, "*.csdat"))
                sdat_files = glob.glob(os.path.join(candidate, "*.sdat"))
                is_fc2 = self.game_mode.lower() == "farcry2"
                if (is_fc2 and sdat_files) or (not is_fc2 and csdat_files):
                    found_sdat = candidate
                    print(f"Found terrain folder at: {found_sdat}")
                    break

        if not found_sdat:
            print("No terrain folder with .csdat or .sdat files found")
            return False

        self.sdat_path = found_sdat
        return self.load_terrain_viewer()

    def load_world_data_internal(self, worlds_path, progress_dialog=None):
        """Load world data WITHOUT EntityLibrary FCB conversion"""
        try:
            # Find XML files in worlds_path
            found_files = self.find_xml_files_enhanced(worlds_path)
            if not found_files:
                print(f"No world XML files found in {worlds_path}")
                return False

            # EntityLibrary conversion removed entirely
            print("Skipping EntityLibrary FCB conversion")

            # Setup EntityLibrary for 3D model lookups (folder/XML only)
            if hasattr(self, 'canvas') and hasattr(self.canvas, 'model_loader'):
                print(f"\n=== Setting up EntityLibrary for 3D models ===")

                entity_library_fcb = os.path.join(worlds_path, "entitylibrary_full.fcb")
                entity_lib_folder = entity_library_fcb + ".converted"
                entity_lib_xml = entity_library_fcb + ".converted.xml"

                success = False
                if os.path.exists(entity_lib_folder) and os.path.isdir(entity_lib_folder):
                    success = self.canvas.model_loader.set_entity_library_folder(worlds_path)
                    print(f"EntityLibrary folder used: {entity_lib_folder}")
                elif os.path.exists(entity_lib_xml):
                    success = self.canvas.model_loader.set_entity_library_xml(entity_lib_xml)
                    print(f"EntityLibrary merged XML used: {entity_lib_xml}")
                else:
                    print("EntityLibrary not found (3D models disabled)")

                if success:
                    game_data_path = os.path.dirname(os.path.dirname(worlds_path))
                    possible_model_paths = [
                        os.path.join(game_data_path, "graphics", "_models"),
                        os.path.join(game_data_path, "worlds", "graphics", "_models"),
                        os.path.join(os.path.dirname(game_data_path), "graphics", "_models"),
                    ]
                    for models_path in possible_model_paths:
                        if os.path.exists(models_path):
                            gltf_count = len(list(Path(models_path).rglob('*.gltf')))
                            self.canvas.model_loader.set_models_directory(models_path)
                            print(f"Models directory set: {models_path} ({gltf_count} GLTF files)")
                            break

                    possible_material_paths = [
                        os.path.join(game_data_path, "graphics", "_materials"),
                        os.path.join(game_data_path, "worlds", "graphics", "_materials"),
                        os.path.join(os.path.dirname(game_data_path), "graphics", "_materials"),
                    ]
                    for materials_path in possible_material_paths:
                        if os.path.exists(materials_path):
                            self.canvas.model_loader.set_materials_directory(materials_path)
                            print(f"Materials directory set: {materials_path}")
                            break

                print(f"\nRe-assigning models to {len(self.entities)} entities...")
                self.canvas.model_loader.assign_models_to_entities(self.entities)

            else:
                print("Canvas or model_loader not available")

            # Load XML files into entities
            loaded_files = []
            entity_count_before = len(self.entities)

            if "mapsdata" in found_files:
                self.xml_file_path = found_files["mapsdata"]["path"]
                self.parse_xml_file(self.xml_file_path)
                loaded_files.append(f"mapsdata ({len(self.entities) - entity_count_before} entities)")

            file_loaders = {
                "omnis": self.load_omnis_data,
                "managers": self.load_managers_data,
                "sectorsdep": self.load_sectordep_data
            }
            for key, loader_func in file_loaders.items():
                if key in found_files:
                    entity_count_before = len(self.entities)
                    loader_func(found_files[key]["path"])
                    loaded_files.append(f"{key} ({len(self.entities) - entity_count_before} entities)")

            print(f"Loaded world files: {loaded_files}")
            return True

        except Exception as e:
            print(f"Error loading world data: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _save_and_convert_worldsectors(self):
        """Save and convert WorldSectors files using the improved separated approach"""
        if not hasattr(self, 'worldsectors_trees') or not self.worldsectors_trees:
            return 0
        
        print(f"\nStarting improved WorldSectors save and conversion, Please wait.")
        
        # Step 1: Save all XML files first
        print(f"Step 1: Saving modified XML files, Please wait.")
        saved_xml_files = []
        
        for xml_file_path, tree in self.worldsectors_trees.items():
            if xml_file_path.endswith('.converted.xml'):
                try:
                    # Save the XML with current entity positions
                    tree.write(xml_file_path, encoding='utf-8', xml_declaration=True)
                    saved_xml_files.append(xml_file_path)
                    print(f"   Saved: {os.path.basename(xml_file_path)}")
                except Exception as e:
                    print(f"   Failed to save {os.path.basename(xml_file_path)}: {e}")
        
        if not saved_xml_files:
            print(f"No XML files were saved")
            return 0
        
        print(f"Saved {len(saved_xml_files)} XML files")
        
        # Step 2: Use the improved conversion method
        print(f"\nStep 2: Converting files using improved method, Please wait.")
        
        if hasattr(self, 'worldsectors_path') and self.worldsectors_path:
            success = self.file_converter.convert_all_worldsector_files_improved(self.worldsectors_path)
        else:
            # Fallback: get path from first XML file
            if saved_xml_files:
                worldsectors_path = os.path.dirname(saved_xml_files[0])
                success = self.file_converter.convert_all_worldsector_files_improved(worldsectors_path)
            else:
                print(f"No worldsectors path available")
                return 0
        
        if success:
            # Step 3: Clean up worldsectors_trees for successfully converted files
            print(f"\nStep 3: Cleaning up memory, Please wait.")
            
            # Remove converted XML files from tracking
            xml_files_to_remove = []
            for xml_file_path in self.worldsectors_trees.keys():
                if xml_file_path.endswith('.converted.xml') and not os.path.exists(xml_file_path):
                    xml_files_to_remove.append(xml_file_path)
            
            for xml_file_path in xml_files_to_remove:
                del self.worldsectors_trees[xml_file_path]
                print(f"    Removed from tracking: {os.path.basename(xml_file_path)}")
            
            # Clear modification flags
            if hasattr(self, 'worldsectors_modified'):
                self.worldsectors_modified.clear()
            
            print(f"WorldSectors conversion completed successfully!")
            return len(saved_xml_files)
        else:
            print(f"WorldSectors conversion failed or was incomplete")
            return 0

    def save_level(self):
        """Save level — FCB conversion runs on a background thread to keep UI responsive."""
        # Always stop any running movie preview and restore entity positions before saving
        if getattr(self, '_movie_preview_timer', None) and self._movie_preview_timer.isActive():
            self._movie_preview_stop(restore=True)

        reply = QMessageBox.question(
            self,
            "Save Level",
            "This will save all changes and convert files back to FCB format:\n"
            "1. Save XML files with current entity positions\n"
            "2. Convert main XML files to FCB\n"
            "3. Convert WorldSector XML files to FCB\n"
            "4. Clean up temporary files\n\n"
            "Make sure the game is completely closed before proceeding!\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.No:
            return

        progress_dialog = EnhancedProgressDialog("Saving Level", self, game_mode=self.game_mode)
        progress_dialog.show()
        QApplication.processEvents()

        self._save_worker = SaveWorkerThread(self)
        w = self._save_worker

        w.log_message.connect(progress_dialog.append_log)
        w.status_updated.connect(progress_dialog.set_status)
        w.progress_updated.connect(progress_dialog.set_progress)
        w.save_finished.connect(lambda m, ws: self._on_save_finished(m, ws, progress_dialog))
        w.save_failed.connect(lambda err: self._on_save_failed(err, progress_dialog))
        progress_dialog.cancelled.connect(lambda: setattr(w, 'should_cancel', True))

        w.start()

    def _on_save_finished(self, main_converted, ws_converted, progress_dialog):
        """Called on the main thread when SaveWorkerThread completes successfully."""
        self.entities_modified = False
        self.xml_tree_modified = False
        if hasattr(self, 'worldsectors_modified'):
            self.worldsectors_modified.clear()

        if hasattr(self, 'update_entity_tree'):
            self.update_entity_tree()

        progress_dialog.mark_complete()
        progress_dialog.stop_icon()
        progress_dialog.close()

        if main_converted > 0 or ws_converted > 0:
            QMessageBox.information(
                self,
                "Level Saved Successfully",
                f"Successfully saved level!\n\n"
                f"Main files converted: {main_converted}\n"
                f"WorldSector files converted: {ws_converted}\n\n"
                f"Your changes should now appear in the game!\n\n"
                f"Make sure to launch the game to test your changes."
            )
        else:
            QMessageBox.warning(
                self,
                "Save Issues",
                "Save completed but some conversions may have failed.\n"
                "Check the console output for details."
            )

    def _on_save_failed(self, error_msg, progress_dialog):
        """Called on the main thread when SaveWorkerThread raises an exception."""
        progress_dialog.mark_complete()
        progress_dialog.stop_icon()
        progress_dialog.close()
        QMessageBox.critical(self, "Save Failed", f"Save failed: {error_msg}")

    def save_all_xml_files_before_conversion(self, log_callback=None):
        """Save all XML files before converting to FCB - CRITICAL STEP"""
        def _log(msg):
            print(msg)
            if log_callback:
                try:
                    log_callback(msg)
                except Exception:
                    pass

        _log(f"\nSTEP 1: Saving all XML files with current entity positions, Please wait.")

        import io as _io_main

        def _tree_hash(t):
            b = _io_main.BytesIO()
            t.write(b, encoding='utf-8', xml_declaration=True)
            return str(hash(b.getvalue()))

        # 0. Sync entity.x/y/z back into xml_element hidPos for non-worldsector entities.
        #    Only update the field when the float value actually changed — avoids spurious
        #    hash differences from format-only rewrites (same fix as landmark dirty check).
        synced_pos = 0
        non_ws_sources = {'mapsdata', 'omnis', 'managers', 'sectorsdep', None}
        for entity in getattr(self, 'entities', []):
            if getattr(entity, 'source_file', None) in non_ws_sources:
                elem = getattr(entity, 'xml_element', None)
                if elem is None:
                    continue
                changed = False
                for field_name in ('hidPos', 'hidPos_precise'):
                    pos_field = elem.find(f"./field[@name='{field_name}']")
                    if pos_field is None:
                        continue
                    existing = pos_field.get('value-Vector3', '')
                    try:
                        parts = existing.split(',')
                        if (len(parts) == 3 and
                                abs(float(parts[0]) - entity.x) < 1e-6 and
                                abs(float(parts[1]) - entity.y) < 1e-6 and
                                abs(float(parts[2]) - entity.z) < 1e-6):
                            continue  # value unchanged — skip to avoid false dirty
                    except (ValueError, IndexError):
                        pass
                    pos_str = f"{entity.x},{entity.y},{entity.z}"
                    pos_field.set('value-Vector3', pos_str)
                    try:
                        pos_field.text = _coords_to_binhex(entity.x, entity.y, entity.z)
                    except Exception:
                        pass
                    changed = True
                if changed:
                    synced_pos += 1
        if synced_pos:
            _log(f"   Synced positions for {synced_pos} non-worldsector entities")

        # 1. Save mapsdata XML — hash-gated so we only reconvert when content changed
        if hasattr(self, 'xml_tree') and self.xml_tree and hasattr(self, 'xml_file_path'):
            try:
                new_hash = _tree_hash(self.xml_tree)
                if new_hash != self._main_clean_hashes.get('mapsdata', ''):
                    self.xml_tree.write(self.xml_file_path, encoding='utf-8', xml_declaration=True)
                    self.xml_tree_modified = True
                    self._main_clean_hashes['mapsdata'] = new_hash
                    _log(f"   Saved main XML: {os.path.basename(self.xml_file_path)}")
                else:
                    _log(f"   Main XML unchanged (skipping): {os.path.basename(self.xml_file_path)}")
            except Exception as e:
                _log(f"   Failed to save main XML: {e}")

        # 1b. Sync managers.xml vPos (must happen BEFORE managers.xml is written to disk)
        synced = self._sync_managers_vpos()
        if hasattr(self, 'managers_tree') and self.managers_tree is not None:
            _log(f"   managers.xml vPos sync: {synced} entries updated")
        else:
            _log("   managers.xml not loaded - skipping vPos sync")

        # 2. Save omnis / managers / sectorsdep — hash-gated
        main_files = {
            'omnis_tree': 'omnis',
            'managers_tree': 'managers',
            'sectordep_tree': 'sectorsdep'
        }

        _modified_flags = {
            'omnis': 'omnis_tree_modified',
            'managers': 'managers_tree_modified',
            'sectorsdep': 'sectordep_tree_modified',
        }

        for tree_attr, file_type in main_files.items():
            if hasattr(self, tree_attr):
                tree = getattr(self, tree_attr)
                if tree is not None:
                    file_path = self._find_tree_file_path(file_type)
                    if file_path:
                        try:
                            new_hash = _tree_hash(tree)
                            if new_hash != self._main_clean_hashes.get(file_type, ''):
                                tree.write(file_path, encoding='utf-8', xml_declaration=True)
                                setattr(self, _modified_flags[file_type], True)
                                self._main_clean_hashes[file_type] = new_hash
                                print(f"   Saved {file_type} XML: {os.path.basename(file_path)}")
                            else:
                                print(f"   {file_type} XML unchanged (skipping)")
                        except Exception as e:
                            print(f"   Failed to save {file_type} XML: {e}")
        
        # 3. CRITICAL: Save WorldSector .converted.xml files
        if hasattr(self, 'worldsectors_trees'):

            unified = getattr(self.canvas, 'unified_mode', False) if hasattr(self, 'canvas') else False
            _log(f"   WorldSector save mode: {'UNIFIED (cross-sector redistribution)' if unified else 'SINGLE-SECTOR (no cross-sector moves)'}")
            _log(f"   Loaded sector trees: {len(self.worldsectors_trees)}")

            if unified:
                self._save_unified_worldsectors(_log)
            else:
                # Single-sector path (unchanged)
                # First, update all entity XML elements with current positions
                print(f"   Updating entity positions in XML...")
                updated_count = 0
                for entity in self.entities:
                    if hasattr(entity, 'xml_element') and entity.xml_element is not None:
                        source_file = getattr(entity, 'source_file', None)
                        source_file_path = getattr(entity, 'source_file_path', None)
                        is_worldsector = (source_file == 'worldsectors' or
                                        (source_file_path and 'worldsector' in source_file_path.lower()))
                        if is_worldsector:
                            if self._update_object_xml_position(entity):
                                updated_count += 1

                if updated_count > 0:
                    print(f"   Updated {updated_count} entity positions in XML")
                else:
                    print(f"   Warning: No entity XML positions were updated!")

                for xml_file_path, tree in self.worldsectors_trees.items():
                    if xml_file_path.endswith('.converted.xml'):
                        try:
                            try:
                                ET.indent(tree, space="  ")
                            except AttributeError:
                                pass  # Python < 3.9
                            old_mtime = os.path.getmtime(xml_file_path) if os.path.exists(xml_file_path) else 0
                            tree.write(xml_file_path, encoding='utf-8', xml_declaration=True)
                            new_size = os.path.getsize(xml_file_path) if os.path.exists(xml_file_path) else 0
                            new_mtime = os.path.getmtime(xml_file_path) if os.path.exists(xml_file_path) else 0
                            if new_mtime != old_mtime:
                                print(f"   Saved WorldSector XML: {os.path.basename(xml_file_path)} ({new_size} bytes)")
                            else:
                                print(f"   WorldSector XML may not have saved: {os.path.basename(xml_file_path)}")
                        except Exception as e:
                            print(f"   Failed to save WorldSector XML {os.path.basename(xml_file_path)}: {e}")

        # 4. Save Landmark .converted.xml files
        #    Landmark trees are stored in self.landmark_trees at load time (separate from
        #    worldsectors_trees so unified save can't corrupt them with wrong structure).
        #    We flush current entity positions into the stored tree and write it to disk.
        self._landmark_dirty_xml_paths = []
        if hasattr(self, 'landmark_trees') and self.landmark_trees:
            lm_entity_by_id = {}
            for entity in getattr(self, 'entities', []):
                sfp = getattr(entity, 'source_file_path', '') or ''
                if 'landmark' in sfp.lower():
                    eid = getattr(entity, 'id', None)
                    if eid:
                        lm_entity_by_id[eid] = entity

            import io as _io
            clean_hashes = getattr(self, 'landmark_clean_hashes', {})
            for xml_path, tree in self.landmark_trees.items():
                try:
                    root = tree.getroot()
                    updated = 0
                    for entity_elem in root.findall(".//object[@name='Entity']"):
                        id_field = entity_elem.find("./field[@name='disEntityId']")
                        if id_field is None:
                            continue
                        eid = (
                            id_field.get('value-Id64') or
                            id_field.get('value-String') or ''
                        ).strip()
                        if not eid or eid not in lm_entity_by_id:
                            continue
                        entity = lm_entity_by_id[eid]
                        for fn in ('hidPos', 'hidPos_precise'):
                            pos_field = entity_elem.find(f"./field[@name='{fn}']")
                            if pos_field is not None:
                                # Only touch the element when position actually changed.
                                # Python float formatting (e.g. "7.62e-06" vs "7.62E-06")
                                # differs from the original XML string — always rewriting
                                # causes a false dirty even for unmoved entities.
                                current_v3 = pos_field.get('value-Vector3', '')
                                try:
                                    parts = current_v3.split(',')
                                    if (len(parts) == 3 and
                                            float(parts[0]) == entity.x and
                                            float(parts[1]) == entity.y and
                                            float(parts[2]) == entity.z):
                                        break  # position unchanged — leave element untouched
                                except Exception:
                                    pass
                                pos_field.set('value-Vector3',
                                              f"{entity.x},{entity.y},{entity.z}")
                                try:
                                    pos_field.text = _coords_to_binhex(
                                        entity.x, entity.y, entity.z)
                                except Exception:
                                    pass
                                updated += 1
                                break

                    # Dirty check: serialize to bytes and compare hash with clean state
                    buf = _io.BytesIO()
                    tree.write(buf, encoding='utf-8', xml_declaration=True)
                    new_hash = str(hash(buf.getvalue()))
                    if new_hash == clean_hashes.get(xml_path):
                        _log(f"   Landmark unchanged (skipping): {os.path.basename(xml_path)}")
                        continue

                    tree.write(xml_path, encoding='utf-8', xml_declaration=True)
                    clean_hashes[xml_path] = new_hash
                    self._landmark_dirty_xml_paths.append(xml_path)
                    _log(f"   Saved landmark XML: {os.path.basename(xml_path)}"
                         f" ({updated} positions updated)")
                except Exception as e:
                    _log(f"   Failed to save landmark XML {os.path.basename(xml_path)}: {e}")

            # Merge landmark paths into the unified dirty list so FCB conversion picks them up
            if self._landmark_dirty_xml_paths:
                if not hasattr(self, '_unified_dirty_xml_paths'):
                    self._unified_dirty_xml_paths = []
                self._unified_dirty_xml_paths.extend(self._landmark_dirty_xml_paths)

        print(f"XML save phase complete")

    def _save_unified_worldsectors(self, log_callback=None):
        """
        Dirty-only save for unified world sector mode.

        Rebuilds XML for every sector that is dirty (moved entities or edited
        entities), skips sectors whose rebuilt XML hash matches the clean hash,
        writes changed sectors to disk, and updates entity metadata.

        Populates self._unified_dirty_xml_paths so _convert_worldsector_files_fixed
        knows which files actually changed and need FCBConverter conversion.
        """
        def _log(msg):
            if log_callback:
                try:
                    log_callback(msg)
                except Exception:
                    pass
            else:
                print(msg)

        self._unified_dirty_xml_paths = []

        # ── Build known-sectors map from loaded trees ─────────────────────────
        # known_sectors: sector_id → (gx, gy, xml_path)
        # Only include genuine worldsector files — landmarks share the folder but
        # must NOT be rebuilt by unified save (they have different XML structure and
        # their grid X/Y can collide with worldsector IDs, causing false dirty marks).
        known_sectors = {}
        for xml_path, tree in self.worldsectors_trees.items():
            if not xml_path.endswith('.converted.xml'):
                continue
            if not os.path.basename(xml_path).lower().startswith('worldsector'):
                continue
            root = tree.getroot()
            gx = gy = 0
            xf = root.find("./field[@name='X']")
            if xf is not None:
                try:
                    gx = int(xf.get('value-Int32', 0))
                except (ValueError, TypeError):
                    pass
            yf = root.find("./field[@name='Y']")
            if yf is not None:
                try:
                    gy = int(yf.get('value-Int32', 0))
                except (ValueError, TypeError):
                    pass
            known_sectors[gy * 16 + gx] = (gx, gy, xml_path)

        if not known_sectors:
            _log("   Unified save: no known sectors found, falling back to single-sector path")
            return

        # ── Collect worldsector entities and compute target sectors ────────────
        # Match only entities from genuine worldsector files (basename starts with
        # 'worldsector'), not landmarks that happen to live in the same folder.
        ws_entities = [
            e for e in self.entities
            if os.path.basename(getattr(e, 'source_file_path', '') or '').lower().startswith('worldsector')
        ]
        _log(f"   Total worldsector entities to assign: {len(ws_entities)}")

        # Build a reverse map: normalised xml_path → sector_id, so we can backfill
        # source_sector_id for entities that were tagged as worldsectors but never
        # had it set (e.g. entities loaded through the secondary object-loader path).
        path_to_sector: dict = {
            os.path.normcase(xml_path): sid
            for sid, (_, _, xml_path) in known_sectors.items()
        }
        backfilled = 0
        for entity in ws_entities:
            if getattr(entity, 'source_sector_id', -1) < 0:
                fp = getattr(entity, 'source_file_path', '') or ''
                sid = path_to_sector.get(os.path.normcase(fp), -1)
                if sid >= 0:
                    entity.source_sector_id = sid
                    backfilled += 1
        if backfilled:
            _log(f"   Backfilled source_sector_id for {backfilled} entities")

        # Group entities by their source sector (where they were loaded from).
        # Entities stay in their original file unless the user explicitly moved them
        # across a sector boundary — in that case mark_sector_dirty already updated
        # source_sector_id to the new sector.  New imports (source_sector_id == -1)
        # fall back to position-based sector assignment.
        sector_entities: dict = {sid: [] for sid in known_sectors}
        for entity in ws_entities:
            src = getattr(entity, 'source_sector_id', -1)
            if src >= 0 and src in known_sectors:
                sector_entities[src].append(entity)
            else:
                # New entity with no source sector — use position
                gx = int(entity.x // 64)
                gy = int(entity.y // 64)
                pos_id = gy * 16 + gx
                if pos_id in known_sectors:
                    sector_entities[pos_id].append(entity)

        # ── Build final dirty set (only what the user explicitly touched) ─────
        final_dirty: set = set(self.canvas.dirty_sectors)

        total = len(final_dirty & set(known_sectors.keys()))
        _log(f"   Unified save: {total} of {len(known_sectors)} sectors need rebuilding")
        if hasattr(self, 'statusBar'):
            self.statusBar().showMessage(f"Saving… {total} of {len(known_sectors)} sectors changed")

        # ── Rebuild dirty sectors ──────────────────────────────────────────────
        written = 0
        skipped = 0
        for sector_id in sorted(final_dirty):
            if sector_id not in known_sectors:
                continue

            gx, gy, xml_path = known_sectors[sector_id]
            entities_for_sector = sector_entities.get(sector_id, [])

            try:
                original_tree = self.worldsectors_trees.get(xml_path)
                new_tree = rebuild_sector_xml(sector_id, gx, gy, entities_for_sector,
                                              original_tree=original_tree)

                # Serialize to a string to compare hashes
                import io
                buf = io.StringIO()
                new_tree.write(buf, encoding='unicode', xml_declaration=False)
                xml_text = buf.getvalue()
                new_hash = str(hash(xml_text))

                if new_hash == self.sector_clean_hashes.get(sector_id):
                    skipped += 1
                    _log(f"   Sector ({gx},{gy}) unchanged — skipping")
                    continue

                new_tree.write(xml_path, encoding='utf-8', xml_declaration=True)
                self.sector_clean_hashes[sector_id] = new_hash
                self.worldsectors_trees[xml_path] = new_tree
                self._unified_dirty_xml_paths.append(xml_path)
                written += 1
                _log(f"   Rebuilt sector ({gx},{gy}) → {os.path.basename(xml_path)}"
                     f" ({len(entities_for_sector)} entities)")

            except Exception as e:
                _log(f"   ERROR rebuilding sector ({gx},{gy}): {e}")
                import traceback
                traceback.print_exc()

        # ── Update entity source_file_path to reflect their (possibly new) sector ─
        for entity in ws_entities:
            src = getattr(entity, 'source_sector_id', -1)
            if src in known_sectors:
                _, _, xml_path = known_sectors[src]
                entity.source_file_path = xml_path

        # ── Clear dirty set ────────────────────────────────────────────────────
        self.canvas.dirty_sectors.clear()

        _log(f"   Unified save complete: {written} sectors written, {skipped} unchanged")

    def _write_fcb_xml_tree(self, tree, path):
        """Write an ElementTree to path with FCBConverter-compatible attribute ordering.

        ElementTree.write() sorts attributes alphabetically, placing 'type' before
        'value-*'. FCBConverter requires value-* to come before type="BinHex".
        This serializer writes: hash, name, value-* (sorted), type, then any others.
        """
        FCB_HEADER = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<!--Converted by FCBConverter v20230711-1830, author ArmanIII.-->\n'
            '<!--Please remember that types are calculated and they may not be exactly the same as they are. Take care about this.-->\n'
            '<!--Based on Gibbed\'s Dunia Tools. Special thanks to: Fireboyd78 (FCBastard), Ekey (FC5 Unpacker), Gibbed, xBaebsae, id-daemon, Ganic, legendhavoc175, miru, eprilx-->\n'
        )

        def _escape(s):
            return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

        def _attr_str(elem):
            attrs = dict(elem.attrib)
            ordered = []
            for k in ('hash', 'name'):
                if k in attrs:
                    ordered.append(k)
            for k in sorted(attrs):
                if k.startswith('value-'):
                    ordered.append(k)
            if 'type' in attrs:
                ordered.append('type')
            for k in attrs:
                if k not in ordered:
                    ordered.append(k)
            return ''.join(f' {k}="{_escape(attrs[k])}"' for k in ordered)

        def _serialize(elem, level):
            indent = '  ' * level
            attr_str = _attr_str(elem)
            children = list(elem)
            text = (elem.text or '').strip()
            if not children and not text:
                return f'{indent}<{elem.tag}{attr_str} />\n'
            elif not children:
                return f'{indent}<{elem.tag}{attr_str}>{_escape(text)}</{elem.tag}>\n'
            else:
                parts = [f'{indent}<{elem.tag}{attr_str}>\n']
                for child in children:
                    parts.append(_serialize(child, level + 1))
                parts.append(f'{indent}</{elem.tag}>\n')
                return ''.join(parts)

        root = tree.getroot()
        content = FCB_HEADER + _serialize(root, 0)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)

    def _sync_managers_vpos(self):
        """Sync vPos in managers.xml PawnInteractionInfo records to match entity hidPos.

        For every PawnInteractionInfo that has an entEntity value-Id64 referencing any
        loaded entity, update the vPos field to the entity's current x/y/z so the
        managers.xml stays in sync.  Marks managers_tree_modified so the file gets
        saved and converted automatically.

        Returns the number of vPos entries synced.
        """
        print("   _sync_managers_vpos: checking managers tree...")
        if not hasattr(self, 'managers_tree') or self.managers_tree is None:
            print("   WARNING: managers_tree not loaded - skipping vPos sync")
            return 0

        import struct

        # Build lookup from ALL loaded entities (not just worldsector ones —
        # the entity may live in omnis, mapsdata, or worldsectors)
        entity_id_map = {}
        for entity in self.entities:
            entity_id_map[str(entity.id)] = entity

        print(f"   Entity pool for vPos sync: {len(entity_id_map)} entities total")
        if not entity_id_map:
            print("   WARNING: No entities loaded - skipping vPos sync")
            return 0

        root = self.managers_tree.getroot()
        synced = 0
        all_infos = root.findall(".//object[@name='PawnInteractionInfo']")
        print(f"   PawnInteractionInfo entries in managers.xml: {len(all_infos)}")

        for info in all_infos:
            ent_field = info.find("field[@name='entEntity']")
            if ent_field is None:
                continue
            eid = ent_field.get('value-Id64', '')
            if not eid or eid not in entity_id_map:
                if eid:
                    print(f"   entEntity {eid} not found in loaded entities")
                continue

            entity = entity_id_map[eid]
            x, y, z = entity.x, entity.y, entity.z

            pos_bytes = struct.pack('<fff', x, y, z)
            binhex = pos_bytes.hex().upper()
            vec_str = f"{x},{y},{z}"

            vpos_field = info.find("field[@name='vPos']")
            if vpos_field is not None:
                vpos_field.set('value-Vector3', vec_str)
                vpos_field.text = binhex
                synced += 1
                print(f"   vPos synced: entity {eid} ({entity.name}) -> ({x}, {y}, {z})")

        if synced > 0:
            self.managers_tree_modified = True
            print(f"   Synced {synced} managers.xml vPos entries - marked for save")
        else:
            print(f"   No vPos entries matched (0 synced)")

        return synced

    def _convert_worldsector_files_fixed(self, log_callback=None):
        """Convert WorldSector .converted.xml files back to .data.fcb - FIXED VERSION with logging"""
        
        def log(message):
            print(message)
            if log_callback:
                try:
                    log_callback(message)
                except:
                    pass
        
        log("\nSTEP 2: Converting WorldSector XML files to FCB, Please wait.")

        landmark_dirty = getattr(self, '_landmark_dirty_xml_paths', [])
        has_worldsectors = hasattr(self, 'worldsectors_trees') and self.worldsectors_trees
        if not has_worldsectors and not landmark_dirty:
            log("No WorldSector trees loaded")
            return 0

        # In unified mode only reconvert the sectors that were actually rebuilt.
        # Landmark dirty paths are pre-merged into _unified_dirty_xml_paths by
        # save_all_xml_files_before_conversion, so they're already in dirty_paths.
        unified = getattr(self.canvas, 'unified_mode', False) if hasattr(self, 'canvas') else False
        if unified:
            dirty_paths = set(getattr(self, '_unified_dirty_xml_paths', []))
            if not dirty_paths:
                log("Unified mode: no sectors changed — skipping FCB conversion")
                return 0
            log(f"Unified mode: reconverting {len(dirty_paths)} dirty sector(s)")
            converted_xml_files = [p for p in dirty_paths if os.path.exists(p)]
        else:
            # Find all .converted.xml files from worldsector trees
            converted_xml_files = []
            for file_path in (self.worldsectors_trees.keys() if has_worldsectors else []):
                if file_path.endswith('.converted.xml') and os.path.exists(file_path):
                    converted_xml_files.append(file_path)
            # Also include any landmark files saved in this cycle
            for lm_path in landmark_dirty:
                if lm_path not in converted_xml_files and os.path.exists(lm_path):
                    converted_xml_files.append(lm_path)

        if not converted_xml_files:
            log("No .converted.xml files found to convert")
            return 0
        
        log(f"Found {len(converted_xml_files)} .converted.xml files to convert")

        # Validate all files are in the same folder and have the expected format
        worldsectors_folder = os.path.dirname(converted_xml_files[0])
        valid_xml_files = []
        failed_files = []
        for xml_file in converted_xml_files:
            if not xml_file.endswith('.data.fcb.converted.xml'):
                log(f"Unexpected file format (skipping): {os.path.basename(xml_file)}")
                failed_files.append(xml_file)
            elif not os.path.exists(xml_file):
                log(f"XML file missing (skipping): {os.path.basename(xml_file)}")
                failed_files.append(xml_file)
            elif os.path.getsize(xml_file) == 0:
                log(f"XML file is empty (skipping): {os.path.basename(xml_file)}")
                failed_files.append(xml_file)
            else:
                valid_xml_files.append(xml_file)

        if not valid_xml_files:
            log("No valid .converted.xml files to convert")
            return 0

        converted_count = 0

        log(f"\nConverting {len(valid_xml_files)} sector(s) to FCB...")
        for xml_file in valid_xml_files:
            target_fcb = xml_file.replace('.data.fcb.converted.xml', '.data.fcb')
            log(f"\n   Converting: {os.path.basename(xml_file)}")
            try:
                result_path = self.file_converter.convert_converted_xml_back_to_fcb(target_fcb)

                if result_path and os.path.exists(result_path):
                    if result_path.endswith('_new.fcb'):
                        if os.path.exists(target_fcb):
                            os.remove(target_fcb)
                        os.rename(result_path, target_fcb)
                        log(f"   → {os.path.basename(target_fcb)}")

                    converted_count += 1

                    try:
                        os.remove(xml_file)
                        if xml_file in self.worldsectors_trees:
                            del self.worldsectors_trees[xml_file]
                    except Exception as cleanup_err:
                        log(f"   Cleanup warning: {cleanup_err}")
                else:
                    log(f"   [FAILED] No output produced")
                    failed_files.append(xml_file)

            except Exception as e:
                log(f"   [ERROR] {e}")
                failed_files.append(xml_file)

        # Summary
        log("\nWorldSector conversion summary:")
        log(f"   Successfully converted: {converted_count}/{len(valid_xml_files)} files")

        if failed_files:
            log(f"   Failed conversions: {len(failed_files)} files")
            for failed_file in failed_files[:5]:
                log(f"     - {os.path.basename(failed_file)}")
            if len(failed_files) > 5:
                log(f"     ... and {len(failed_files) - 5} more")

        return converted_count

    def debug_verify_entity_in_files(self, entity_name):
        """Debug method to trace an entity through the entire save process"""
        print(f"\nTRACING ENTITY: {entity_name}")
        
        # Find the entity
        target_entity = None
        for entity in self.entities:
            if entity.name == entity_name:
                target_entity = entity
                break
        
        if not target_entity:
            print(f"Entity {entity_name} not found")
            return
        
        print(f"Entity position: ({target_entity.x:.1f}, {target_entity.y:.1f}, {target_entity.z:.1f})")
        print(f"Source file: {getattr(target_entity, 'source_file_path', 'None')}")
        
        # Check if source file exists and contains the entity
        source_file = getattr(target_entity, 'source_file_path', None)
        if source_file and os.path.exists(source_file):
            try:
                import xml.etree.ElementTree as ET
                tree = ET.parse(source_file)
                root = tree.getroot()
                
                # Look for the entity in the XML (FCBConverter format)
                found_in_xml = False
                for entity_elem in root.findall(".//object[@name='Entity']"):
                    name_field = entity_elem.find("./field[@name='hidName']")
                    if name_field is not None and _get_str_val(name_field) == entity_name:
                        found_in_xml = True

                        pos_field = entity_elem.find("./field[@name='hidPos']")
                        if pos_field is not None:
                            pos_value = pos_field.get('value-Vector3', '')
                            if pos_value:
                                try:
                                    coords = pos_value.split(',')
                                    if len(coords) == 3:
                                        xml_pos = (float(coords[0]), float(coords[1]), float(coords[2]))
                                        print(f"Found in XML: ({xml_pos[0]:.1f}, {xml_pos[1]:.1f}, {xml_pos[2]:.1f})")
                                        if (abs(xml_pos[0] - target_entity.x) < 0.1 and
                                                abs(xml_pos[1] - target_entity.y) < 0.1 and
                                                abs(xml_pos[2] - target_entity.z) < 0.1):
                                            print(f"XML coordinates match entity coordinates")
                                        else:
                                            print(f"XML coordinates don't match entity coordinates!")
                                except (ValueError, IndexError):
                                    pass
                        break

                if not found_in_xml:
                    print(f"Entity not found in XML file")
                    
            except Exception as e:
                print(f"Error reading XML file: {e}")
        
        # Check corresponding FCB file
        if source_file and source_file.endswith('.converted.xml'):
            fcb_file = source_file.replace('.converted.xml', '')
            if os.path.exists(fcb_file):
                fcb_size = os.path.getsize(fcb_file)
                fcb_mtime = os.path.getmtime(fcb_file)
                print(f"Corresponding FCB: {os.path.basename(fcb_file)} ({fcb_size} bytes)")
                print(f"FCB last modified: {fcb_mtime}")
            else:
                print(f"No corresponding FCB file found: {fcb_file}")

    def emergency_restore_worldsectors(self):
        """Emergency method to restore WorldSector files from backups"""
        if not hasattr(self, 'worldsectors_path') or not self.worldsectors_path:
            QMessageBox.warning(self, "No WorldSectors Path", "No worldsectors path is set.")
            return
        
        # Find backup files
        import glob
        backup_pattern = os.path.join(self.worldsectors_path, "*.pre_delete_backup")
        backup_files = glob.glob(backup_pattern)
        
        if not backup_files:
            QMessageBox.information(self, "No Backups Found", "No backup files found to restore.")
            return
        
        reply = QMessageBox.question(
            self,
            "Restore from Backups",
            f"Found {len(backup_files)} backup files.\n\n"
            f"This will restore the original FCB files and may overwrite any changes.\n\n"
            f"Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            restored_count = self.file_converter.restore_from_backups(backup_files)
            QMessageBox.information(
                self,
                "Restore Complete",
                f"Restored {restored_count} files from backups."
            )

    def _convert_worldsector_xml_to_fcb(self):
        """Convert WorldSector .converted.xml files back to .data.fcb format - HANDLES _new.fcb RENAMING"""
        print(f"\nStarting WorldSector XML to FCB conversion, Please wait.")
        
        if not hasattr(self, 'file_converter'):
            print(f"No file converter available")
            return 0
        
        # Find all WorldSector .converted.xml files from entities
        converted_xml_files = set()
        for entity in self.entities:
            if hasattr(entity, 'source_file_path') and entity.source_file_path:
                if entity.source_file_path.endswith('.converted.xml'):
                    converted_xml_files.add(entity.source_file_path)
        
        # Also check worldsectors_trees for any loaded .converted.xml files
        if hasattr(self, 'worldsectors_trees'):
            for file_path in self.worldsectors_trees.keys():
                if file_path.endswith('.converted.xml'):
                    converted_xml_files.add(file_path)
        
        if not converted_xml_files:
            print(f"No WorldSector .converted.xml files found")
            return 0
        
        print(f"Found {len(converted_xml_files)} .converted.xml files to convert to FCB")
        
        converted_count = 0
        failed_files = []
        cleanup_files = []  # Files to clean up after successful conversion
        
        # Convert each .converted.xml file back to .data.fcb
        for xml_file in converted_xml_files:
            try:
                # Determine the original FCB file path
                # worldsector83.data.fcb.converted.xml -> worldsector83.data.fcb
                if xml_file.endswith('.data.fcb.converted.xml'):
                    fcb_file = xml_file.replace('.converted.xml', '')
                else:
                    print(f"Unexpected file format: {xml_file}")
                    failed_files.append(xml_file)
                    continue
                
                print(f"\nConverting: {os.path.basename(xml_file)}  {os.path.basename(fcb_file)}")
                
                # Check if XML file exists and has content
                if not os.path.exists(xml_file):
                    print(f"XML file not found: {xml_file}")
                    failed_files.append(xml_file)
                    continue
                    
                xml_size = os.path.getsize(xml_file)
                print(f"  XML file size: {xml_size} bytes")
                
                if xml_size == 0:
                    print(f"XML file is empty")
                    failed_files.append(xml_file)
                    continue
                
                # Remove existing FCB file if it exists
                if os.path.exists(fcb_file):
                    old_fcb_size = os.path.getsize(fcb_file)
                    print(f"  Removing old FCB file ({old_fcb_size} bytes)")
                    os.remove(fcb_file)
                
                # Convert using the file converter's method for .converted.xml files
                print(f"  Running conversion, Please wait.")
                success = self.file_converter.convert_converted_xml_back_to_fcb(fcb_file)
                
                # Check conversion result
                if success:
                    if os.path.exists(fcb_file):
                        fcb_size = os.path.getsize(fcb_file)
                        print(f"  Conversion successful!")
                        print(f"  FCB file size: {fcb_size} bytes")
                        converted_count += 1
                        
                        # Mark XML file for cleanup after all conversions are done
                        cleanup_files.append(xml_file)
                        
                        # Update entity source_file_path to point to FCB
                        updated_entities = 0
                        for entity in self.entities:
                            if hasattr(entity, 'source_file_path') and entity.source_file_path == xml_file:
                                entity.source_file_path = fcb_file
                                updated_entities += 1
                        
                        if updated_entities > 0:
                            print(f"  Updated {updated_entities} entity references")
                            
                    else:
                        print(f"  Conversion reported success but FCB file not created")
                        failed_files.append(xml_file)
                else:
                    print(f"  Conversion failed for: {os.path.basename(xml_file)}")
                    failed_files.append(xml_file)
                    
            except Exception as e:
                print(f"  Error converting {xml_file}: {e}")
                failed_files.append(xml_file)
        
        # Clean up successfully converted XML files
        if cleanup_files:
            print(f"\nCleaning up {len(cleanup_files)} successfully converted XML files, Please wait.")
            for xml_file in cleanup_files:
                try:
                    os.remove(xml_file)
                    print(f"  Removed: {os.path.basename(xml_file)}")
                except Exception as cleanup_error:
                    print(f"  Could not remove {os.path.basename(xml_file)}: {cleanup_error}")
        
        # Also clean up any leftover _new.fcb files
        worldsectors_path = None
        if cleanup_files:
            worldsectors_path = os.path.dirname(cleanup_files[0])
        elif hasattr(self, 'worldsectors_path'):
            worldsectors_path = self.worldsectors_path
        
        if worldsectors_path:
            print(f"\nChecking for leftover _new.fcb files, Please wait.")
            try:
                for file in os.listdir(worldsectors_path):
                    if file.endswith('_new.fcb'):
                        leftover_path = os.path.join(worldsectors_path, file)
                        try:
                            os.remove(leftover_path)
                            print(f"  Removed leftover: {file}")
                        except Exception as e:
                            print(f"  Could not remove leftover {file}: {e}")
            except Exception as e:
                print(f"  Error checking for leftover files: {e}")
        
        # Clear worldsectors_trees for successfully converted files
        if hasattr(self, 'worldsectors_trees') and cleanup_files:
            trees_to_remove = []
            for file_path in self.worldsectors_trees.keys():
                if file_path in cleanup_files:
                    trees_to_remove.append(file_path)
            
            for file_path in trees_to_remove:
                del self.worldsectors_trees[file_path]
            
            if trees_to_remove:
                print(f"  Cleared {len(trees_to_remove)} XML trees from memory")
        
        # Summary
        print(f"\nWorldSector conversion summary:")
        print(f"  Successfully converted: {converted_count}/{len(converted_xml_files)} files")
        print(f"  Cleaned up: {len(cleanup_files)} XML files")
        
        if failed_files:
            print(f"  Failed conversions: {len(failed_files)} files")
            for failed_file in failed_files:
                print(f"    - {os.path.basename(failed_file)}")
        
        return converted_count
    
    def save_worldsectors_changes(self):
        """Save WorldSectors changes and convert back to FCB format"""
        if not hasattr(self, 'worldsectors_trees') or not self.worldsectors_trees:
            QMessageBox.information(self, "No Changes", "No WorldSectors files are loaded.")
            return

        try:
            # Step 0: Update entity XML positions + sync managers.xml vPos
            print("Step 0: Updating entity positions in XML, Please wait.")
            for entity in self.entities:
                source_path = getattr(entity, 'source_file_path', '') or ''
                source = getattr(entity, 'source_file', '')
                if source == 'worldsectors' or 'worldsector' in source_path.lower():
                    self._update_object_xml_position(entity)

            # Sync vPos in managers.xml to match current worldsector positions
            self._sync_managers_vpos()

            # If managers was updated, save it to disk now (before FCB conversion)
            if self.managers_tree_modified and hasattr(self, 'managers_tree') and self.managers_tree:
                mgr_path = self._find_tree_file_path('managers')
                if mgr_path:
                    try:
                        self._write_fcb_xml_tree(self.managers_tree, mgr_path)
                        print(f"   Saved managers XML: {os.path.basename(mgr_path)}")
                    except Exception as e:
                        print(f"   Failed to save managers XML: {e}")

            # Step 1: Save all modified .converted.xml files
            print("Step 1: Saving modified .converted.xml files, Please wait.")
            
            modified_files = []
            for xml_file_path, tree in self.worldsectors_trees.items():
                if xml_file_path.endswith('.converted.xml'):
                    try:
                        # Save the XML with current entity positions
                        tree.write(xml_file_path, encoding='utf-8', xml_declaration=True)
                        modified_files.append(xml_file_path)
                        print(f"Saved: {os.path.basename(xml_file_path)}")
                    except Exception as e:
                        print(f" Failed to save {xml_file_path}: {e}")
            
            if not modified_files:
                QMessageBox.information(self, "No Changes", "No modified WorldSectors files to save.")
                return
            
            # Step 2: Convert .converted.xml back to .data.fcb
            progress_dialog = QProgressDialog("Converting XML to FCB, Please Wait.", "Cancel", 0, 100, self)
            progress_dialog.setWindowTitle("Saving WorldSectors")
            progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            progress_dialog.setMinimumDuration(0)
            progress_dialog.setValue(0)
            
            print("Step 2: Converting .converted.xml files back to .data.fcb, Please wait.")
            
            converted_count = 0
            failed_files = []
            
            for i, xml_file in enumerate(modified_files):
                if progress_dialog.wasCanceled():
                    break
                    
                # Get the original FCB path
                # worldsector83.data.fcb.converted.xml -> worldsector83.data.fcb
                if xml_file.endswith('.data.fcb.converted.xml'):
                    fcb_file = xml_file.replace('.converted.xml', '')
                    
                    progress_dialog.setLabelText(f"Converting {os.path.basename(fcb_file)}, Please Wait.")
                    progress_dialog.setValue(int((i / len(modified_files)) * 100))
                    QApplication.processEvents()
                    
                    print(f"Converting: {os.path.basename(xml_file)} -> {os.path.basename(fcb_file)}, Please Wait.")
                    
                    # Use the file converter to convert back to FCB
                    success = self.file_converter.convert_converted_xml_back_to_fcb(fcb_file)
                    
                    if success:
                        converted_count += 1
                        print(f"Converted: {os.path.basename(fcb_file)}")
                        
                        # Update entity source_file_path to point back to FCB
                        for entity in self.entities:
                            if hasattr(entity, 'source_file_path') and entity.source_file_path == xml_file:
                                entity.source_file_path = fcb_file
                                
                    else:
                        failed_files.append(xml_file)
                        print(f" Failed to convert: {os.path.basename(xml_file)}")
            
            progress_dialog.setValue(100)
            progress_dialog.close()
            
            # Step 3: Clean up .converted.xml files after successful conversion
            if converted_count > 0:
                print("Step 3: Cleaning up .converted.xml files, Please wait.")
                
                cleanup_files = []
                for xml_file in modified_files:
                    if xml_file not in failed_files:
                        try:
                            os.remove(xml_file)
                            cleanup_files.append(xml_file)
                            print(f"Removed: {os.path.basename(xml_file)}")
                        except Exception as e:
                            print(f"  Could not remove {xml_file}: {e}")
                
                # Clear worldsectors_trees for cleaned up files
                for xml_file in cleanup_files:
                    if xml_file in self.worldsectors_trees:
                        del self.worldsectors_trees[xml_file]
            
            # Step 4: Show results
            if failed_files:
                QMessageBox.warning(
                    self,
                    "Conversion Completed with Errors",
                    f"Successfully converted {converted_count} files to FCB format.\n\n"
                    f"Failed to convert {len(failed_files)} files:\n" +
                    "\n".join([os.path.basename(f) for f in failed_files[:5]]) +
                    (f"\n... and {len(failed_files) - 5} more" if len(failed_files) > 5 else "")
                )
            else:
                QMessageBox.information(
                    self,
                    "WorldSectors Saved Successfully",
                    f"Successfully saved and converted {converted_count} WorldSectors files!\n\n"
                    f"Your changes are now saved in FCB format and will appear in the game."
                )
            
            # Reset modification flags
            if hasattr(self, 'worldsectors_modified'):
                self.worldsectors_modified.clear()
            
            self.status_bar.showMessage(f"Saved {converted_count} WorldSectors files to FCB format")
            
        except Exception as e:
            if 'progress_dialog' in locals():
                progress_dialog.close()
            QMessageBox.critical(self, "Error", f"Failed to save WorldSectors: {str(e)}")

    def _convert_main_xml_to_fcb(self, log_callback=None):
        """Convert main XML files back to FCB format - ONLY IF MODIFIED"""

        def log(message):
            print(message)
            if log_callback:
                try:
                    log_callback(message)
                except:
                    pass

        log("\nStarting XML to FCB conversion (modified files only)...")

        if not hasattr(self, 'file_converter'):
            log("No file converter available")
            return 0

        converted_count = 0

        # List of main XML files to check
        main_xml_files = []

        # Check main XML file
        if hasattr(self, 'xml_tree') and self.xml_tree and hasattr(self, 'xml_file_path'):
            if self.xml_file_path and os.path.exists(self.xml_file_path):
                # Only convert if modified
                if self.xml_tree_modified:
                    main_xml_files.append({
                        'xml_path': self.xml_file_path,
                        'type': 'mapsdata',
                        'modified': True
                    })
                    log(f"  Main XML marked for conversion (modified)")
                else:
                    log(f"  Main XML skipped (not modified)")

        # Check other main XML files with their modification flags
        file_types = {
            'omnis': ('omnis_tree', 'omnis_tree_modified'),
            'managers': ('managers_tree', 'managers_tree_modified'),
            'sectorsdep': ('sectordep_tree', 'sectordep_tree_modified')
        }

        for file_type, (tree_attr, modified_attr) in file_types.items():
            if hasattr(self, tree_attr):
                tree = getattr(self, tree_attr)
                is_modified = getattr(self, modified_attr, False)

                if tree is not None:
                    file_path = self._find_tree_file_path(file_type)
                    if file_path and os.path.exists(file_path):
                        if is_modified:
                            main_xml_files.append({
                                'xml_path': file_path,
                                'type': file_type,
                                'modified': True
                            })
                            log(f"  {file_type} XML marked for conversion (modified)")
                        else:
                            log(f"  {file_type} XML skipped (not modified)")

        if not main_xml_files:
            log("No modified main XML files found to convert")
            return 0

        log(f"Found {len(main_xml_files)} modified XML files to convert to FCB")

        # Convert each modified XML file back to FCB
        for file_info in main_xml_files:
            xml_file = file_info['xml_path']
            file_type = file_info['type']

            try:
                fcb_file = xml_file.replace('.xml', '.fcb')

                log(f"\nConverting: {os.path.basename(xml_file)} {os.path.basename(fcb_file)}")

                # Check if XML file exists and has content
                if not os.path.exists(xml_file):
                    log(f"  XML file not found: {xml_file}")
                    continue

                xml_size = os.path.getsize(xml_file)
                log(f"  XML file size: {xml_size} bytes")

                if xml_size == 0:
                    log("  XML file is empty")
                    continue

                # Remove existing FCB file if it exists
                if os.path.exists(fcb_file):
                    old_fcb_size = os.path.getsize(fcb_file)
                    log(f"  Removing old FCB file ({old_fcb_size} bytes)")
                    os.remove(fcb_file)

                # Convert XML to FCB (always uses -fc2 flag internally)
                log("  Running conversion (with -fc2 flag)...")
                success = self.file_converter.convert_xml_to_fcb(xml_file)

                # Check conversion result
                if success:
                    if os.path.exists(fcb_file):
                        fcb_size = os.path.getsize(fcb_file)
                        log("  Conversion successful!")
                        log(f"  FCB file size: {fcb_size} bytes")
                        converted_count += 1

                        # Remove the temporary XML file after successful conversion
                        try:
                            os.remove(xml_file)
                            log(f"  Cleaned up XML file: {os.path.basename(xml_file)}")
                        except Exception as cleanup_error:
                            log(f"  Could not remove XML file: {cleanup_error}")

                        # Reset the modification flag for this file
                        if file_type == 'mapsdata':
                            self.xml_tree_modified = False
                        elif file_type == 'omnis':
                            self.omnis_tree_modified = False
                        elif file_type == 'managers':
                            self.managers_tree_modified = False
                        elif file_type == 'sectorsdep':
                            self.sectordep_tree_modified = False

                        log(f"  Reset modification flag for {file_type}")
                    else:
                        log("  Conversion reported success but FCB file not created")
                else:
                    log(f"  Conversion failed for: {os.path.basename(xml_file)}")

            except Exception as e:
                log(f"  Error converting {xml_file}: {e}")
                import traceback
                traceback.print_exc()

        log(f"\nConversion summary: {converted_count}/{len(main_xml_files)} modified files converted to FCB")
        return converted_count

    def save_worldsector_xml_with_precision_preservation(self, tree, file_path):
        """Save worldsector XML while preserving original formatting and precision"""
        try:
            # Create backup first
            backup_path = file_path + ".precision_backup"
            if os.path.exists(file_path):
                shutil.copy2(file_path, backup_path)
            
            # CRITICAL: Don't add XML declaration to match original format
            tree.write(
                file_path, 
                encoding='utf-8', 
                xml_declaration=True  # Changed from True to False
            )
            
            print(f"Saved worldsector XML with precision preservation: {os.path.basename(file_path)}")
            
        except Exception as e:
            print(f"Error saving worldsector XML with precision preservation: {e}")
            raise

    def _convert_all_data_files_to_fcb(self):
        """Convert all data XML files to FCB with verification"""
        import glob
        
        # Find all .data.xml files
        pattern = os.path.join(self.worldsectors_path, "*.data.xml")
        xml_files = glob.glob(pattern)
        
        success_count = 0
        error_count = 0
        
        print(f"Converting {len(xml_files)} data XML files to FCB, Please Wait.")
        
        for xml_file in xml_files:
            try:
                # Get the FCB path
                fcb_file = xml_file.replace('.data.xml', '.data.fcb')
                
                print(f"Converting: {os.path.basename(xml_file)} -> {os.path.basename(fcb_file)}, Please Wait.")
                
                # Check XML file size before conversion
                xml_size = os.path.getsize(xml_file)
                print(f"  XML size: {xml_size} bytes")
                
                # Perform conversion
                if self.file_converter.convert_data_xml_to_fcb(xml_file):
                    # Check if FCB was created
                    if os.path.exists(fcb_file):
                        fcb_size = os.path.getsize(fcb_file)
                        print(f"  FCB size: {fcb_size} bytes")
                        
                        # Remove XML after successful conversion
                        os.remove(xml_file)
                        success_count += 1
                        print(f"Converted and cleaned up: {os.path.basename(xml_file)}")
                    else:
                        error_count += 1
                        print(f" FCB file not created: {os.path.basename(fcb_file)}")
                else:
                    error_count += 1
                    print(f" Conversion failed: {os.path.basename(xml_file)}")
                    
            except Exception as e:
                error_count += 1
                print(f"Error converting {xml_file}: {e}")
        
        print(f"Data file conversion: {success_count} successful, {error_count} failed")

    def _save_all_main_xml_files(self):
        """Save all main XML files that have been modified"""
        # Save primary XML file
        if hasattr(self, 'xml_tree') and hasattr(self, 'xml_file_path'):
            self.xml_tree.write(self.xml_file_path, encoding='utf-8', xml_declaration=True)
            print(f"Saved main XML: {os.path.basename(self.xml_file_path)}")
        
        # Save other XML files
        file_mappings = {
            'omnis_tree': 'omnis',
            'managers_tree': 'managers', 
            'sectordep_tree': 'sectorsdep'
        }
        
        for tree_attr, file_type in file_mappings.items():
            if hasattr(self, tree_attr):
                tree = getattr(self, tree_attr)
                if tree is not None:
                    file_path = self._find_tree_file_path(file_type)
                    if file_path:
                        tree.write(file_path, encoding='utf-8', xml_declaration=True)
                        print(f"Saved {file_type} XML: {os.path.basename(file_path)}")

    def _convert_main_files_to_fcb(self):
        """Convert main XML files back to FCB format"""
        files_to_convert = []
        
        # Add primary XML file
        if hasattr(self, 'xml_file_path') and self.xml_file_path:
            files_to_convert.append(self.xml_file_path)
        
        # Add other XML files
        for file_type in ['omnis', 'managers', 'sectorsdep']:
            file_path = self._find_tree_file_path(file_type)
            if file_path and os.path.exists(file_path):
                files_to_convert.append(file_path)
        
        # Convert each file
        success_count = 0
        error_count = 0
        
        for xml_file in files_to_convert:
            try:
                fcb_file = xml_file.replace('.xml', '.fcb')

                # Remove existing FCB file
                if os.path.exists(fcb_file):
                    os.remove(fcb_file)

                # Convert XML to FCB
                if self.file_converter.convert_xml_to_fcb(xml_file):
                    success_count += 1
                    print(f"Converted to FCB: {os.path.basename(fcb_file)}")
                else:
                    error_count += 1
                    print(f" Failed to convert: {os.path.basename(xml_file)}")
                    
            except Exception as e:
                error_count += 1
                print(f"Error converting {xml_file}: {e}")
        
        print(f"Main file conversion: {success_count} successful, {error_count} failed")

    def _cleanup_temp_xml_files(self):
        """Remove temporary XML files after successful FCB conversion"""
        files_to_remove = []
        
        # Add main XML files
        if hasattr(self, 'xml_file_path') and self.xml_file_path:
            files_to_remove.append(self.xml_file_path)
        
        for file_type in ['omnis', 'managers', 'sectorsdep']:
            file_path = self._find_tree_file_path(file_type)
            if file_path and os.path.exists(file_path):
                files_to_remove.append(file_path)
        
        # Add modified data XML files
        if hasattr(self, 'worldsectors_modified'):
            for file_path, is_modified in self.worldsectors_modified.items():
                if is_modified:
                    files_to_remove.append(file_path)
        
        # Remove the files
        removed_count = 0
        for xml_file in files_to_remove:
            try:
                if os.path.exists(xml_file):
                    os.remove(xml_file)
                    print(f"Removed temp XML: {os.path.basename(xml_file)}")
                    removed_count += 1
            except Exception as e:
                print(f"Warning: Could not remove {xml_file}: {e}")
        
        print(f"Cleaned up {removed_count} temporary XML files")

    def show_sector_violations_dialog(self, violations):
        """Show dialog with entities that are outside their sector boundaries"""
        if not violations:
            return
        
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QTextEdit
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Sector Boundary Violations ({len(violations)} found)")
        dialog.setMinimumSize(600, 400)
        
        layout = QVBoxLayout(dialog)
        
        # Warning message
        warning_label = QLabel("The following entities are outside their sector boundaries.\n"
                            "This may cause crashes or unexpected behavior in the game!")
        warning_label.setStyleSheet("color: orange; font-weight: bold; padding: 10px;")
        layout.addWidget(warning_label)
        
        # List of violations
        violation_list = QListWidget()
        
        for violation in violations:
            entity = violation['entity']
            sector_id = violation['sector_id']
            bounds = violation['sector_bounds']
            pos = violation['entity_pos']
            distance = violation['distance_out']
            
            item_text = (f"{entity.name} (Sector {sector_id})\n"
                        f"Position: ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})\n"
                        f"Sector bounds: ({bounds[0]}-{bounds[2]}, {bounds[1]}-{bounds[3]})\n"
                        f"Distance outside: {distance:.1f} units")
            
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, entity)  # Store entity reference
            
            # Color code by severity
            if distance > 50:
                item.setBackground(QColor(255, 200, 200))  # Light red for far outside
            else:
                item.setBackground(QColor(255, 255, 200))  # Light yellow for slightly outside
            
            violation_list.addItem(item)
        
        layout.addWidget(violation_list)
        
        # Action buttons
        button_layout = QHBoxLayout()
        
        # Move to entity button
        move_to_button = QPushButton("Zoom to Selected Entity")
        move_to_button.clicked.connect(lambda: self.zoom_to_violation_entity(violation_list))
        button_layout.addWidget(move_to_button)
        
        # Fix entity button (move it back to sector)
        fix_button = QPushButton("Move Entity to Sector Center")
        fix_button.clicked.connect(lambda: self.fix_violation_entity(violation_list, violations))
        button_layout.addWidget(fix_button)
        
        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.close)
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
        
        # Show dialog
        dialog.exec()

    def zoom_to_violation_entity(self, violation_list):
        """Zoom to the selected entity in the violations list"""
        current_item = violation_list.currentItem()
        if current_item:
            entity = current_item.data(Qt.ItemDataRole.UserRole)
            if entity:
                # Use existing zoom to entity method
                if hasattr(self, 'zoom_to_entity'):
                    self.zoom_to_entity(entity)
                else:
                    # Fallback zoom
                    self.canvas.selected_entity = entity
                    self.canvas.selected = [entity]
                    if self.canvas.mode == 0:  # 2D mode
                        self.canvas.offset_x = (self.canvas.width() / 2) - (entity.x * self.canvas.scale_factor)
                        self.canvas.offset_y = (self.canvas.height() / 2) - (entity.y * self.canvas.scale_factor)
                    self.canvas.update()

    def fix_violation_entity(self, violation_list, violations):
        """Move the selected entity back to its sector center"""
        current_item = violation_list.currentItem()
        if not current_item:
            return
        
        entity = current_item.data(Qt.ItemDataRole.UserRole)
        if not entity:
            return
        
        # Find the violation info for this entity
        violation_info = None
        for violation in violations:
            if violation['entity'] == entity:
                violation_info = violation
                break
        
        if not violation_info:
            return
        
        # Calculate sector center
        bounds = violation_info['sector_bounds']
        center_x = (bounds[0] + bounds[2]) / 2
        center_y = (bounds[1] + bounds[3]) / 2
        
        # Ask user for confirmation
        reply = QMessageBox.question(
            self,
            "Move Entity",
            f"Move {entity.name} from ({entity.x:.1f}, {entity.y:.1f}) to sector center ({center_x:.1f}, {center_y:.1f})?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Move entity
            entity.x = center_x
            entity.y = center_y
            
            # Update XML
            self.canvas.update_entity_xml(entity)
            
            # Update UI
            self.canvas.update()
            self.status_bar.showMessage(f"Moved {entity.name} to sector center")
            
            # Mark as modified
            self.entities_modified = True

    def get_sector_statistics(self):
        """Get statistics about sector usage and violations"""
        if not hasattr(self.canvas, 'sector_data') or not self.canvas.sector_data:
            return None
        
        stats = {
            'total_sectors': len(self.canvas.sector_data),
            'sectors_with_violations': 0,
            'total_violations': 0,
            'violations_by_sector': {}
        }
        
        for sector_info in self.canvas.sector_data:
            sector_id = sector_info['id']
            has_violations = self.canvas.check_sector_violations(sector_info)
            
            if has_violations:
                stats['sectors_with_violations'] += 1
            
            # Count violations in this sector
            sector_violations = 0
            for entity in self.entities:
                entity_source = getattr(entity, 'source_file_path', '')
                if f'worldsector{sector_id}' in entity_source:
                    sector_x = sector_info['x']
                    sector_y = sector_info['y'] 
                    sector_size = sector_info['size']
                    
                    world_min_x = sector_x * sector_size
                    world_min_y = sector_y * sector_size
                    world_max_x = world_min_x + sector_size
                    world_max_y = world_min_y + sector_size
                    
                    if (entity.x < world_min_x or entity.x >= world_max_x or
                        entity.y < world_min_y or entity.y >= world_max_y):
                        sector_violations += 1
            
            if sector_violations > 0:
                stats['violations_by_sector'][sector_id] = sector_violations
                stats['total_violations'] += sector_violations
        
        return stats

    def show_entity_export_dialog(self):
        """Show the entity export dialog"""
        try:
            from entity_export_import import show_entity_export_dialog
            show_entity_export_dialog(self)
        except Exception as e:
            print(f"Error showing entity export dialog: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Failed to open entity export dialog:\n{str(e)}")

    def show_entity_import_dialog(self):
        """Show the entity import dialog"""
        try:
            from entity_export_import import show_entity_import_dialog
            show_entity_import_dialog(self)
        except Exception as e:
            print(f"Error showing entity import dialog: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Failed to open entity import dialog:\n{str(e)}")

    def show_mass_export_dialog(self):
        """Mass-export one collection per unique entity type in the loaded level."""
        if not getattr(self, 'entities', None):
            QMessageBox.warning(self, "No Level Loaded", "Please load a level before using mass export.")
            return

        try:
            import os, shutil
            from entity_export_import import mass_export_level

            level_name = 'unknown_level'
            if hasattr(self, 'current_level_info') and self.current_level_info:
                level_name = self.current_level_info.get('name', 'unknown_level')

            base_dir = os.path.dirname(os.path.abspath(__file__))
            output_root = os.path.join(base_dir, 'mass_exported_objects', level_name)

            if os.path.exists(output_root):
                reply = QMessageBox.question(
                    self, "Folder Already Exists",
                    f"Mass export folder for '{level_name}' already exists.\n\nOverwrite?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
                shutil.rmtree(output_root)

            progress = QProgressDialog(
                f"Mass exporting '{level_name}'...", "Cancel", 0, len(self.entities), self
            )
            progress.setWindowTitle("Mass Export")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
            progress.setValue(0)
            QApplication.processEvents()

            def on_progress(current, total):
                progress.setValue(current)
                QApplication.processEvents()
                return not progress.wasCanceled()

            categories, types, total_files = mass_export_level(self, output_root, on_progress)
            progress.close()

            if not progress.wasCanceled():
                QMessageBox.information(
                    self, "Mass Export Complete",
                    f"Exported {types} unique entity types across {categories} categories.\n"
                    f"Total XML files: {total_files}\n\n"
                    f"Location:\n{output_root}"
                )

        except Exception as e:
            print(f"Error during mass export: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Mass Export Error", f"Mass export failed:\n{str(e)}")

    def debug_export_import_system(self):
        """Debug the export/import system setup"""
        print("\n=== EXPORT/IMPORT SYSTEM DEBUG ===")
        
        # Check if system is setup
        has_clipboard = hasattr(self, 'entity_clipboard')
        print(f"Has entity_clipboard: {has_clipboard}")
        
        if has_clipboard:
            print(f"Clipboard has data: {self.entity_clipboard.has_clipboard_data()}")
        
        # Check objects folder
        objects_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "objects")
        print(f"Objects folder: {objects_folder}")
        print(f"Objects folder exists: {os.path.exists(objects_folder)}")
        
        if os.path.exists(objects_folder):
            collections = [d for d in os.listdir(objects_folder) 
                        if os.path.isdir(os.path.join(objects_folder, d))]
            print(f"Collections found: {len(collections)}")
            for collection in collections[:5]:
                collection_path = os.path.join(objects_folder, collection)
                xml_files = [f for f in os.listdir(collection_path) if f.endswith('.xml')]
                print(f"  - {collection} ({len(xml_files)} XML files)")
        
        # Check worldsectors
        has_worldsectors = hasattr(self, 'worldsectors_trees') and self.worldsectors_trees
        print(f"Has worldsectors loaded: {has_worldsectors}")
        
        if has_worldsectors:
            print(f"Worldsector files: {len(self.worldsectors_trees)}")
            for i, path in enumerate(list(self.worldsectors_trees.keys())[:5]):
                tree = self.worldsectors_trees[path]
                root = tree.getroot()
                entities = root.findall(".//object[@name='Entity']")
                print(f"  {i+1}. {os.path.basename(path)} ({len(entities)} entities)")
        
        # Check selected entities
        selected_count = 0
        if hasattr(self, 'canvas') and hasattr(self.canvas, 'selected'):
            selected_count = len(self.canvas.selected)
        print(f"Selected entities: {selected_count}")
        
        # Check total entities
        total_entities = len(self.entities) if hasattr(self, 'entities') else 0
        print(f"Total entities loaded: {total_entities}")
        
        print("=== END DEBUG ===\n")

    def _add_entity_to_worldsector(self, entity):
        """Add entity to worldsector XML with smart sector assignment"""
        print(f"Smart worldsector assignment for: {entity.name}")
        
        # Find the best target worldsector file
        target_file = self._find_target_worldsector_file(entity)
        
        if not target_file:
            print("No suitable worldsector file found")
            return False
        
        # Update entity's source file path to the target sector
        old_source = getattr(entity, 'source_file_path', 'none')
        entity.source_file_path = target_file
        
        if old_source != target_file:
            print(f"Reassigned entity from {old_source}  {target_file}")
        
        # Load XML file on-demand if not already loaded
        if target_file not in self.worldsectors_trees:
            print(f"Loading target XML file: {target_file}")
            try:
                import xml.etree.ElementTree as ET
                import os
                
                if not os.path.exists(target_file):
                    print(f"Target XML file does not exist: {target_file}")
                    return False
                
                # Load the XML tree
                tree = ET.parse(target_file)
                self.worldsectors_trees[target_file] = tree
                print(f"Loaded XML tree for {target_file}")
                
            except Exception as e:
                print(f"Error loading XML file {target_file}: {e}")
                return False
        
        try:
            print(f"Adding entity to target sector: {target_file}")
            tree = self.worldsectors_trees[target_file]
            root = tree.getroot()
            
            # Find ALL MissionLayers - use the first one for adding
            mission_layers = root.findall(".//object[@name='MissionLayer']")
            if not mission_layers:
                print("No MissionLayer found in target XML")
                return False
            
            # Use the first MissionLayer for adding
            mission_layer = mission_layers[0]
            print(f"Using MissionLayer 1 (of {len(mission_layers)}) for adding")
                
            # Count existing entities
            existing_entities = mission_layer.findall("object[@name='Entity']")
            print(f"Target sector has {len(existing_entities)} existing entities")
            
            # Create a clean copy of the entity XML
            import xml.etree.ElementTree as ET
            xml_string = ET.tostring(entity.xml_element, encoding='unicode')
            fresh_element = ET.fromstring(xml_string)
            
            # Add to MissionLayer
            mission_layer.append(fresh_element)
            
            # Verify addition
            new_entity_count = len(mission_layer.findall("object[@name='Entity']"))
            if new_entity_count > len(existing_entities):
                print(f"Successfully added {entity.name} to {target_file}")
                
                # Update entity reference
                entity.xml_element = fresh_element
                
                # Save the XML file immediately
                tree.write(target_file, encoding='utf-8', xml_declaration=True)
                print(f"Saved XML file with new entity")
                
                # Mark file as modified
                if not hasattr(self, 'worldsectors_modified'):
                    self.worldsectors_modified = {}
                self.worldsectors_modified[target_file] = True
                
                return True
            else:
                print(f"Entity addition verification failed")
                return False
                
        except Exception as e:
            print(f"Exception in smart worldsector assignment: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _find_target_worldsector_file(self, entity):
        """Find the best worldsector file for an entity using smart assignment"""
        x, y = entity.x, entity.y
        print(f" Finding target worldsector for {entity.name} at ({x}, {y})")
        
        # Initialize worldsectors_trees if needed
        if not hasattr(self, 'worldsectors_trees'):
            self.worldsectors_trees = {}
        
        # Get all available worldsector files
        available_files = list(self.worldsectors_trees.keys()) if self.worldsectors_trees else []
        print(f"Available worldsector files: {len(available_files)}")
        
        if not available_files:
            print("No worldsector files loaded - cannot assign sector")
            return None
        
        # Strategy: Use the first available file for now (you can enhance this logic later)
        fallback_file = available_files[0]
        print(f" Using fallback sector: {fallback_file}")
        return fallback_file

    def _calculate_worldsector_from_position(self, x, y):
        """Calculate which worldsector an entity should belong to based on position"""
        try:
            # Check if we have grid configuration
            if hasattr(self, 'grid_config') and self.grid_config:
                # Use existing grid configuration if available
                sector_size = getattr(self.grid_config, 'sector_size', 512)
                offset_x = getattr(self.grid_config, 'offset_x', 0)
                offset_y = getattr(self.grid_config, 'offset_y', 0)
            else:
                # Default grid configuration (common Avatar game values)
                sector_size = 512  # Each sector is typically 512x512 units
                offset_x = 0
                offset_y = 0
            
            # Calculate sector coordinates
            sector_x = int((x - offset_x) // sector_size)
            sector_y = int((y - offset_y) // sector_size)
            
            # Calculate sector ID (this may need adjustment based on your game's numbering)
            # Common patterns: sector_id = sector_y * max_sectors_x + sector_x
            # For now, using a simple formula - may need refinement
            sector_id = sector_y * 10 + sector_x  # Assuming 10x10 grid max
            
            # Ensure sector_id is positive and reasonable
            if sector_id < 0:
                sector_id = 0
            if sector_id > 99:  # Reasonable upper limit
                sector_id = 99
                
            print(f"Position ({x}, {y})  Sector X:{sector_x}, Y:{sector_y}  ID:{sector_id}")
            return sector_id
            
        except Exception as e:
            print(f"Error calculating sector from position: {e}")
            return None

    def toggle_sector_boundaries(self):
        """Toggle sector boundary visibility - FIXED VERSION"""
        try:
            # Ensure canvas has the required attributes
            if not hasattr(self.canvas, 'show_sector_boundaries'):
                self.canvas.show_sector_boundaries = False
            
            if not hasattr(self.canvas, 'sector_data'):
                self.canvas.sector_data = []
            
            # Toggle the visibility
            self.canvas.show_sector_boundaries = not self.canvas.show_sector_boundaries
            
            print(f"Toggling sector boundaries: {self.canvas.show_sector_boundaries}")
            
            # Always reload sector data when turning on so that landmark entries
            # are included (they are excluded from worldsectors_trees, so a stale
            # sector_data built before this fix would be missing them).
            if self.canvas.show_sector_boundaries:
                print("Loading sector data...")
                success = self.load_sector_data_for_canvas()
                if not success:
                    print("Failed to load sector data")
                    self.canvas.show_sector_boundaries = False
                    QMessageBox.warning(
                        self,
                        "No Sector Data",
                        "No worldsector files are loaded.\n\n"
                        "Load a level with worldsectors first."
                    )
                    return

                print(f"Sector boundaries enabled ({len(self.canvas.sector_data)} sectors/landmarks)")
            else:
                print("Sector boundaries disabled")
            
            # Update canvas
            self.canvas.update()
            
            # Update status
            visibility = "visible" if self.canvas.show_sector_boundaries else "hidden"
            self.status_bar.showMessage(f"Sector boundaries: {visibility}")
            
        except Exception as e:
            print(f"Error toggling sector boundaries: {e}")
            import traceback
            traceback.print_exc()

    def load_sector_data_for_canvas(self):
        """Load sector data for the canvas from worldsectors files"""
        try:
            print("\n=== Loading Sector Data ===")

            # Build a read-only view of trees for sector coordinate extraction.
            # We intentionally do NOT store freshly-parsed trees into
            # self.worldsectors_trees so that toggling sector boundaries does
            # not cause unmodified files to be written/converted on the next
            # save.
            if hasattr(self, 'worldsectors_trees') and self.worldsectors_trees:
                # Use the already-loaded trees (may contain entity edits).
                trees_to_process = self.worldsectors_trees
                print(f"Using {len(trees_to_process)} existing worldsector trees")
            elif (hasattr(self, '_all_worldsectors_paths') and self._all_worldsectors_paths) or \
                 (hasattr(self, 'worldsectors_path') and self.worldsectors_path):
                import glob
                import xml.etree.ElementTree as ET

                # Collect all search folders — prefer the accumulated list for multi-part levels
                ws_folders = getattr(self, '_all_worldsectors_paths', None) or []
                if not ws_folders and getattr(self, 'worldsectors_path', None):
                    ws_folders = [self.worldsectors_path]

                trees_to_process = {}
                for ws_path in ws_folders:
                    print(f"Reading sector positions from: {ws_path}")
                    pattern = os.path.join(ws_path, "*.converted.xml")
                    xml_files = glob.glob(pattern)
                    print(f"Found {len(xml_files)} .converted.xml files in {os.path.basename(ws_path)}")
                    for xml_file in xml_files:
                        try:
                            trees_to_process[xml_file] = ET.parse(xml_file)
                            print(f"  Read: {os.path.basename(xml_file)}")
                        except Exception as e:
                            print(f"  Error reading {os.path.basename(xml_file)}: {e}")

                if not trees_to_process:
                    print("No .converted.xml files found")
                    return False
            else:
                print("No worldsectors_trees or worldsectors_path available")
                return False

            # Clear existing sector data
            self.canvas.sector_data = []

            print(f"Processing {len(trees_to_process)} worldsector files...")

            # Process each worldsector file
            for xml_file_path, tree in trees_to_process.items():
                try:
                    root = tree.getroot()
                    
                    # Extract sector info from XML
                    sector_id = None
                    sector_x = None
                    sector_y = None
                    
                    # Get sector ID
                    id_field = root.find(".//field[@name='Id']")
                    if id_field is not None:
                        sector_id = int(id_field.get('value-Int32', 0))
                    
                    # Get X coordinate
                    x_field = root.find(".//field[@name='X']")
                    if x_field is not None:
                        sector_x = int(x_field.get('value-Int32', 0))
                    
                    # Get Y coordinate
                    y_field = root.find(".//field[@name='Y']")
                    if y_field is not None:
                        sector_y = int(y_field.get('value-Int32', 0))
                    
                    if sector_id is None or sector_x is None or sector_y is None:
                        print(f"  Skipping {os.path.basename(xml_file_path)}: missing sector info")
                        continue
                    
                    # Find entities in this sector
                    sector_entities = []
                    for entity in self.entities:
                        if hasattr(entity, 'source_file_path'):
                            if entity.source_file_path == xml_file_path:
                                sector_entities.append(entity)
                    
                    # Calculate world bounds for verification
                    world_min_x = sector_x * 64
                    world_min_y = sector_y * 64
                    world_max_x = world_min_x + 64
                    world_max_y = world_min_y + 64
                    
                    # Detect landmark files by name
                    bn_lower = os.path.basename(xml_file_path).lower()
                    is_lm = bn_lower.startswith('landmarkfar') or bn_lower.startswith('landmarknear')

                    # Create sector info
                    sector_info = {
                        'id': sector_id,
                        'x': sector_x,
                        'y': sector_y,
                        'size': 64,
                        'file_path': xml_file_path,
                        'entities': sector_entities,
                        'entity_count': len(sector_entities),
                        'is_landmark': is_lm,
                    }

                    self.canvas.sector_data.append(sector_info)

                    kind = "Landmark" if is_lm else "Sector"
                    print(f"  {kind} {sector_id}: Grid({sector_x},{sector_y}) = World({world_min_x}-{world_max_x}, {world_min_y}-{world_max_y}) with {len(sector_entities)} entities")
                    
                except Exception as e:
                    print(f"  Error processing {os.path.basename(xml_file_path)}: {e}")
            
            # ── Also load landmark files (excluded from worldsectors_trees) ──────
            _lm_ws_folders = getattr(self, '_all_worldsectors_paths', None) or []
            if not _lm_ws_folders and getattr(self, 'worldsectors_path', None):
                _lm_ws_folders = [self.worldsectors_path]
            if _lm_ws_folders:
                import glob
                import xml.etree.ElementTree as ET

                already_loaded = {os.path.normcase(p) for p in trees_to_process}
                _all_lm_paths = []
                for _ws_path in _lm_ws_folders:
                    _all_lm_paths.extend(glob.glob(os.path.join(_ws_path, "*.converted.xml")))
                for lm_path in _all_lm_paths:
                    bn_lower = os.path.basename(lm_path).lower()
                    if not (bn_lower.startswith('landmarkfar') or bn_lower.startswith('landmarknear')):
                        continue
                    if os.path.normcase(lm_path) in already_loaded:
                        continue
                    try:
                        lm_tree = ET.parse(lm_path)
                        lm_root = lm_tree.getroot()

                        sector_id = None
                        sector_x  = None
                        sector_y  = None
                        id_f = lm_root.find(".//field[@name='Id']")
                        x_f  = lm_root.find(".//field[@name='X']")
                        y_f  = lm_root.find(".//field[@name='Y']")
                        if id_f is not None:
                            sector_id = int(id_f.get('value-Int32', 0))
                        if x_f is not None:
                            sector_x = int(x_f.get('value-Int32', 0))
                        if y_f is not None:
                            sector_y = int(y_f.get('value-Int32', 0))

                        if sector_x is None or sector_y is None:
                            print(f"  Skipping {os.path.basename(lm_path)}: missing X/Y")
                            continue

                        lm_entities = [
                            e for e in self.entities
                            if getattr(e, 'source_file_path', '') == lm_path
                        ]

                        self.canvas.sector_data.append({
                            'id': sector_id,
                            'x': sector_x,
                            'y': sector_y,
                            'size': 64,
                            'file_path': lm_path,
                            'entities': lm_entities,
                            'entity_count': len(lm_entities),
                            'is_landmark': True,
                        })
                        print(f"  Landmark {os.path.basename(lm_path)}: Grid({sector_x},{sector_y}) with {len(lm_entities)} entities")
                    except Exception as e:
                        print(f"  Error reading landmark {os.path.basename(lm_path)}: {e}")

            print(f"\nLoaded {len(self.canvas.sector_data)} sectors/landmarks into canvas")
            return len(self.canvas.sector_data) > 0

        except Exception as e:
            print(f"Error loading sector data: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    def _add_landmark_sectors_to_data(self):
        """Add landmark file sectors to sector_data"""
        try:
            if not hasattr(self, 'worldsectors_path') or not self.worldsectors_path:
                return
            
            import glob
            import re
            
            # Find all landmark files
            landmark_pattern = os.path.join(self.worldsectors_path, "landmarkfar*.data.fcb.converted.xml")
            landmark_files = glob.glob(landmark_pattern)
            
            if not landmark_files:
                print("No landmark files found")
                return
            
            print(f"Found {len(landmark_files)} landmark files")
            
            for landmark_file in landmark_files:
                try:
                    # Extract landmark ID from filename
                    # Example: landmarkfar10.data.fcb.converted.xml -> 10
                    match = re.search(r'landmarkfar(\d+)', os.path.basename(landmark_file))
                    if not match:
                        continue
                    
                    landmark_id = int(match.group(1))
                    
                    # Load the landmark XML to get sector position
                    import xml.etree.ElementTree as ET
                    tree = ET.parse(landmark_file)
                    root = tree.getroot()
                    
                    # Find WorldSector element
                    sector_x = None
                    sector_y = None
                    
                    x_elem = root.find(".//field[@name='X']")
                    if x_elem is not None:
                        sector_x = int(x_elem.get('value-Int32', 0))
                    
                    y_elem = root.find(".//field[@name='Y']")
                    if y_elem is not None:
                        sector_y = int(y_elem.get('value-Int32', 0))
                    
                    if sector_x is None or sector_y is None:
                        print(f"Could not get sector position from {os.path.basename(landmark_file)}")
                        continue
                    
                    # Count entities in this landmark
                    entities_in_landmark = []
                    for entity in self.entities:
                        source_file = getattr(entity, 'source_file_path', '')
                        if f'landmarkfar{landmark_id}' in source_file:
                            entities_in_landmark.append(entity)
                    
                    # Create sector info for this landmark
                    sector_info = {
                        'id': f"LM{landmark_id}",  # Mark as landmark
                        'x': sector_x,
                        'y': sector_y,
                        'size': 64,
                        'file_path': landmark_file,
                        'entities': entities_in_landmark,
                        'entity_count': len(entities_in_landmark),
                        'is_landmark': True
                    }
                    
                    # Add to sector_data if not already present
                    if hasattr(self.canvas, 'sector_data'):
                        # Check if this sector position already exists
                        exists = False
                        for existing_sector in self.canvas.sector_data:
                            if (existing_sector.get('x') == sector_x and 
                                existing_sector.get('y') == sector_y):
                                exists = True
                                # Merge entities
                                existing_sector['entities'].extend(entities_in_landmark)
                                existing_sector['entity_count'] += len(entities_in_landmark)
                                print(f"Merged landmark {landmark_id} into existing sector at ({sector_x}, {sector_y})")
                                break
                        
                        if not exists:
                            self.canvas.sector_data.append(sector_info)
                            print(f"Added landmark {landmark_id} as sector at ({sector_x}, {sector_y}) with {len(entities_in_landmark)} entities")
                    
                except Exception as e:
                    print(f"Error processing landmark file {os.path.basename(landmark_file)}: {e}")
            
            print(f"Total sectors after adding landmarks: {len(self.canvas.sector_data)}")
            
        except Exception as e:
            print(f"Error adding landmark sectors: {e}")
            import traceback
            traceback.print_exc()

    def create_enhanced_sector_data(self):
        """Create enhanced sector data including landmarks"""
        try:
            sector_files = {}
            
            # Group entities by worldsector AND landmark files
            for entity in self.entities:
                source_file = getattr(entity, 'source_file_path', '')
                if source_file and ('worldsector' in source_file.lower() or 'landmarkfar' in source_file.lower()):
                    if source_file not in sector_files:
                        sector_files[source_file] = []
                    sector_files[source_file].append(entity)
            
            if not sector_files:
                print("No worldsector or landmark entities found")
                return False
            
            # Create sector data
            self.canvas.sector_data = []
            for source_file, entities in sector_files.items():
                # Extract sector number or landmark ID
                import re
                
                # Check if it's a landmark file
                is_landmark = 'landmarkfar' in source_file.lower()
                
                if is_landmark:
                    match = re.search(r'landmarkfar(\d+)', source_file.lower())
                    sector_id = f"LM{match.group(1)}" if match else "LM?"
                else:
                    match = re.search(r'worldsector(\d+)', source_file.lower())
                    sector_id = int(match.group(1)) if match else 0
                
                # Calculate sector bounds from entities
                if entities:
                    min_x = min(e.x for e in entities)
                    max_x = max(e.x for e in entities)
                    min_y = min(e.y for e in entities)
                    max_y = max(e.y for e in entities)
                    
                    # Estimate sector grid position (64-unit sectors)
                    center_x = (min_x + max_x) / 2
                    center_y = (min_y + max_y) / 2
                    sector_x = int(center_x // 64)
                    sector_y = int(center_y // 64)
                    
                    sector_info = {
                        'id': sector_id,
                        'x': sector_x,
                        'y': sector_y,
                        'size': 64,
                        'file_path': source_file,
                        'entities': entities,
                        'entity_count': len(entities),
                        'is_landmark': is_landmark
                    }
                    
                    self.canvas.sector_data.append(sector_info)
                    print(f"Added {'landmark' if is_landmark else 'sector'} {sector_id} with {len(entities)} entities")
            
            print(f"Created enhanced sector data: {len(self.canvas.sector_data)} sectors (including landmarks)")
            return len(self.canvas.sector_data) > 0
            
        except Exception as e:
            print(f"Error creating enhanced sector data: {e}")
            return False

    def create_fallback_sector_data(self):
        """Create basic sector data as fallback"""
        try:
            sector_files = {}
            
            # Group entities by worldsector file
            for entity in self.entities:
                source_file = getattr(entity, 'source_file_path', '')
                if source_file and 'worldsector' in source_file.lower():
                    if source_file not in sector_files:
                        sector_files[source_file] = []
                    sector_files[source_file].append(entity)
            
            if not sector_files:
                print("No worldsector entities found")
                return False
            
            # Create sector data
            self.canvas.sector_data = []
            for source_file, entities in sector_files.items():
                # Extract sector number
                import re
                match = re.search(r'worldsector(\d+)', source_file.lower())
                if match:
                    sector_id = int(match.group(1))
                    
                    # Calculate sector bounds from entities
                    if entities:
                        min_x = min(e.x for e in entities)
                        max_x = max(e.x for e in entities)
                        min_y = min(e.y for e in entities)
                        max_y = max(e.y for e in entities)
                        
                        # Estimate sector grid position (64-unit sectors)
                        center_x = (min_x + max_x) / 2
                        center_y = (min_y + max_y) / 2
                        sector_x = int(center_x // 64)
                        sector_y = int(center_y // 64)
                        
                        sector_info = {
                            'id': sector_id,
                            'x': sector_x,
                            'y': sector_y,
                            'size': 64,
                            'file_path': source_file,
                            'entities': entities,
                            'entity_count': len(entities)
                        }
                        
                        self.canvas.sector_data.append(sector_info)
                        print(f"Added sector {sector_id} with {len(entities)} entities")
            
            print(f"Created fallback sector data: {len(self.canvas.sector_data)} sectors")
            return len(self.canvas.sector_data) > 0
            
        except Exception as e:
            print(f"Error creating fallback sector data: {e}")
            return False

    def check_all_violations(self):
        """Check for sector violations and show results"""
        try:
            # Ensure sector data is loaded
            if not hasattr(self.canvas, 'sector_data') or not self.canvas.sector_data:
                print("Loading sector data for violation check, Please wait.")
                success = self.load_sector_data_for_canvas()
                if not success:
                    QMessageBox.warning(
                        self,
                        "No Sector Data",
                        "Could not load sector data to check for violations.\n\n"
                        "Make sure worldsector entities are loaded."
                    )
                    return
            
            # Get violations
            if hasattr(self.canvas, 'get_entity_violations'):
                violations = self.canvas.get_entity_violations()
            else:
                violations = self.get_entity_violations_fallback()
            
            if violations:
                self.show_sector_violations_dialog(violations)
            else:
                QMessageBox.information(
                    self,
                    "No Violations Found",
                    "All entities are within their sector boundaries!"
                )
                
        except Exception as e:
            print(f"Error checking violations: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Error checking sector violations:\n{str(e)}"
            )

    def get_entity_violations_fallback(self):
        """Fallback method to check entity violations"""
        violations = []
        
        try:
            if not hasattr(self.canvas, 'sector_data') or not self.canvas.sector_data:
                return violations
            
            for sector_info in self.canvas.sector_data:
                sector_id = sector_info.get('id', 0)
                sector_x = sector_info.get('x', 0)
                sector_y = sector_info.get('y', 0)
                sector_size = sector_info.get('size', 64)
                
                # Calculate sector boundaries
                world_min_x = sector_x * sector_size
                world_min_y = sector_y * sector_size
                world_max_x = world_min_x + sector_size
                world_max_y = world_min_y + sector_size
                
                # Check entities from this sector
                for entity in self.entities:
                    entity_source = getattr(entity, 'source_file_path', '')
                    if f'worldsector{sector_id}' not in entity_source:
                        continue
                    
                    # Check if outside boundaries
                    if (entity.x < world_min_x or entity.x >= world_max_x or
                        entity.y < world_min_y or entity.y >= world_max_y):
                        
                        distance_out = max(
                            max(world_min_x - entity.x, 0),
                            max(entity.x - world_max_x, 0),
                            max(world_min_y - entity.y, 0),
                            max(entity.y - world_max_y, 0)
                        )
                        
                        violations.append({
                            'entity': entity,
                            'sector_id': sector_id,
                            'sector_bounds': (world_min_x, world_min_y, world_max_x, world_max_y),
                            'entity_pos': (entity.x, entity.y, entity.z),
                            'distance_out': distance_out
                        })
            
        except Exception as e:
            print(f"Error in fallback violation check: {e}")
        
        return violations

    # Test method you can call from a menu or button
    def test_sector_boundaries(self):
        """Test method to debug sector boundary display"""
        print("\nTESTING SECTOR BOUNDARIES")
        
        # Step 1: Check canvas attributes
        print(f"Canvas has show_sector_boundaries: {hasattr(self.canvas, 'show_sector_boundaries')}")
        print(f"Canvas has sector_data: {hasattr(self.canvas, 'sector_data')}")
        
        # Step 2: Initialize if needed
        if not hasattr(self.canvas, 'show_sector_boundaries'):
            self.canvas.show_sector_boundaries = False
            print("Initialized show_sector_boundaries")
        
        if not hasattr(self.canvas, 'sector_data'):
            self.canvas.sector_data = []
            print("Initialized sector_data")
        
        # Step 3: Load sector data
        print("Loading sector data, Please wait.")
        success = self.load_sector_data_for_canvas()
        print(f"Sector data loaded: {success}")
        
        if hasattr(self.canvas, 'sector_data'):
            print(f"Sector data count: {len(self.canvas.sector_data)}")
            for i, sector in enumerate(self.canvas.sector_data[:3]):  # Show first 3
                print(f"  Sector {i}: {sector}")
        
        # Step 4: Enable and test
        print("Enabling sector boundaries, Please wait.")
        self.canvas.show_sector_boundaries = True
        
        # Step 5: Force update
        print("Forcing canvas update, Please wait.")
        self.canvas.update()
        
        print("Test complete!")

    def _remove_entity_from_worldsector_fixed(self, entity):
        """Remove entity from its worldsector XML file - FIXED for FCBConverter format and multiple MissionLayers"""
        try:
            source_file = entity.source_file_path
            print(f"\nRemoving {entity.name} from {os.path.basename(source_file)}")
            
            # Auto-load source file if not already loaded
            if not hasattr(self, 'worldsectors_trees'):
                self.worldsectors_trees = {}
            
            if source_file not in self.worldsectors_trees:
                if os.path.exists(source_file):
                    try:
                        import xml.etree.ElementTree as ET
                        tree = ET.parse(source_file)
                        self.worldsectors_trees[source_file] = tree
                        print(f"Auto-loaded source file: {os.path.basename(source_file)}")
                    except Exception as e:
                        print(f"Error loading source file {source_file}: {e}")
                        return False
                else:
                    print(f"Source file does not exist: {source_file}")
                    return False
            
            tree = self.worldsectors_trees[source_file]
            root = tree.getroot()
            
            # Find ALL MissionLayers - there can be multiple in worldsector files
            mission_layers = root.findall(".//object[@name='MissionLayer']")
            if not mission_layers:
                print(f"No MissionLayer found in {source_file}")
                return False
            
            print(f"Found {len(mission_layers)} MissionLayer(s) in file")
            
            entity_to_remove = None
            source_mission_layer = None
            
            # Search through ALL MissionLayers
            for layer_idx, mission_layer in enumerate(mission_layers):
                print(f"\nChecking MissionLayer {layer_idx + 1}/{len(mission_layers)}")
                
                # Look for entities directly under this MissionLayer
                entities_in_layer = mission_layer.findall("object[@name='Entity']")
                print(f"Found {len(entities_in_layer)} Entity objects in this MissionLayer")
                
                # Search through entities in FCBConverter format
                for i, entity_elem in enumerate(entities_in_layer):
                    # Look for hidName field (FCBConverter format)
                    name_field = entity_elem.find("field[@name='hidName']")
                    if name_field is not None:
                        stored_name = _get_str_val(name_field)
                        print(f"   Checking: '{stored_name}' vs '{entity.name}'")
                        
                        if stored_name == entity.name:
                            print(f"FOUND MATCH: {entity.name} in MissionLayer {layer_idx + 1}")
                            entity_to_remove = entity_elem
                            source_mission_layer = mission_layer
                            break
                
                # If found, break out of layer loop
                if entity_to_remove is not None:
                    break

            if entity_to_remove is None:
                print(f"Entity {entity.name} not found in any MissionLayer")
                return False

            # Remove the entity from the correct MissionLayer
            print(f"Removing entity from MissionLayer")
            source_mission_layer.remove(entity_to_remove)

            # Verify removal
            all_entities_after = []
            for ml in mission_layers:
                all_entities_after.extend(ml.findall("object[@name='Entity']"))
            print(f"Entity removed. All MissionLayers now have {len(all_entities_after)} total entities")

            # Save immediately
            try:
                ET.indent(tree, space="  ")
            except AttributeError:
                pass  # Python < 3.9
            tree.write(source_file, encoding='utf-8', xml_declaration=True)
            print(f"Saved {os.path.basename(source_file)}")

            # Mark file as modified
            if not hasattr(self, 'worldsectors_modified'):
                self.worldsectors_modified = {}
            self.worldsectors_modified[source_file] = True

            return True

        except Exception as e:
            print(f"Error removing entity: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _remove_entity_from_landmark_tree(self, entity, xml_path):
        """Remove entity from its in-memory landmark XML tree.

        The save loop detects the hash change and writes the file + queues FCB conversion.
        Returns True on success, False if the entity was not found.
        """
        tree = self.landmark_trees.get(xml_path)
        if tree is None:
            return False
        root = tree.getroot()
        eid = getattr(entity, 'id', None)
        if not eid:
            return False

        # Build parent map so we can remove a child from its parent
        parent_map = {child: parent for parent in root.iter() for child in parent}

        for entity_elem in root.findall(".//object[@name='Entity']"):
            id_field = entity_elem.find("./field[@name='disEntityId']")
            if id_field is None:
                continue
            stored_id = (id_field.get('value-Id64') or id_field.get('value-String') or '').strip()
            if stored_id != eid:
                continue
            parent_elem = parent_map.get(entity_elem)
            if parent_elem is not None:
                parent_elem.remove(entity_elem)
                print(f"  Removed {entity.name} (ID {eid}) from landmark tree {os.path.basename(xml_path)}")
                return True

        print(f"  Entity {entity.name} (ID {eid}) not found in {os.path.basename(xml_path)}")
        return False

    def remove_entity_from_sector(self, entity, source_file):
        """Remove entity from its current sector XML file - FIXED for FCBConverter format"""
        try:
            print(f"\nRemoving {entity.name} from {os.path.basename(source_file)}")
            
            # Auto-load source file if not already loaded
            if not hasattr(self, 'worldsectors_trees'):
                self.worldsectors_trees = {}
            
            if source_file not in self.worldsectors_trees:
                if os.path.exists(source_file):
                    try:
                        import xml.etree.ElementTree as ET
                        tree = ET.parse(source_file)
                        self.worldsectors_trees[source_file] = tree
                        print(f"Auto-loaded source file: {os.path.basename(source_file)}")
                    except Exception as e:
                        print(f"Error loading source file {source_file}: {e}")
                        return False
                else:
                    print(f"Source file does not exist: {source_file}")
                    return False
            
            tree = self.worldsectors_trees[source_file]
            root = tree.getroot()
            
            # Find ALL MissionLayers - there can be multiple in worldsector files
            mission_layers = root.findall(".//object[@name='MissionLayer']")
            if not mission_layers:
                print(f"No MissionLayer found in {source_file}")
                return False
            
            print(f"Found {len(mission_layers)} MissionLayer(s) in file")
            
            entity_to_remove = None
            source_mission_layer = None
            
            # Search through ALL MissionLayers
            for layer_idx, mission_layer in enumerate(mission_layers):
                print(f"\nChecking MissionLayer {layer_idx + 1}/{len(mission_layers)}")
                print(f"This MissionLayer has {len(mission_layer)} children")
                
                # Look for entities directly under this MissionLayer
                entities_in_layer = mission_layer.findall("object[@name='Entity']")
                print(f"Found {len(entities_in_layer)} Entity objects in this MissionLayer")
                
                # Search through entities in FCBConverter format
                for i, entity_elem in enumerate(entities_in_layer):
                    print(f"Checking entity {i+1}/{len(entities_in_layer)}")
                    
                    # Look for hidName field (FCBConverter format)
                    name_field = entity_elem.find("field[@name='hidName']")
                    if name_field is not None:
                        stored_name = _get_str_val(name_field)
                        print(f"   Name in XML: '{stored_name}'")
                        print(f"   Looking for: '{entity.name}'")
                        
                        if stored_name == entity.name:
                            print(f"FOUND MATCH: {entity.name} in rMissionLayer {layer_idx + 1}")
                            entity_to_remove = entity_elem
                            source_mission_layer = mission_layer
                            break
                        else:
                            print(f"No match")
                    else:
                        print(f"   No hidName field found")
                
                # If found, break out of layer loop
                if entity_to_remove is not None:
                    break
                
                # Debug: Show all entity names in this layer
                if entities_in_layer:
                    print(f"All entities in MissionLayer {layer_idx + 1}:")
                    for i, entity_elem in enumerate(entities_in_layer):
                        name_field = entity_elem.find("field[@name='hidName']")
                        stored_name = _get_str_val(name_field) if name_field is not None else "[No name field]"
                        print(f"   {i+1}: {stored_name}")
            
            if entity_to_remove is None:
                print(f"Entity {entity.name} not found in any MissionLayer")
                return False
            
            # Remove the entity from the correct MissionLayer
            print(f"Removing entity from MissionLayer")
            source_mission_layer.remove(entity_to_remove)
            
            # Verify removal
            all_entities_after = []
            for ml in mission_layers:
                all_entities_after.extend(ml.findall("object[@name='Entity']"))
            print(f"Entity removed. All MissionLayers now have {len(all_entities_after)} total entities")
            
            # Save immediately
            tree.write(source_file, encoding='utf-8', xml_declaration=True)
            print(f"Saved {os.path.basename(source_file)}")
            
            return True
            
        except Exception as e:
            print(f"Error removing entity: {e}")
            import traceback
            traceback.print_exc()
            return False

    def move_entity_to_sector_manually(self, entity):
        """Move entity to a different sector chosen by user"""
        from PyQt6.QtWidgets import QInputDialog, QMessageBox
        
        if not entity:
            QMessageBox.warning(self, "No Entity", "No entity selected to move.")
            return False
        
        # Get current sector info
        current_file = getattr(entity, 'source_file_path', 'Unknown')
        current_sector = "Unknown"
        if current_file:
            import re
            match = re.search(r'worldsector(\d+)', current_file)
            if match:
                current_sector = match.group(1)
        
        print(f"Moving entity: {entity.name}")
        print(f"Current sector: {current_sector}")
        print(f"Current file: {current_file}")
        
        # Get list of available sectors
        available_sectors = []
        
        if hasattr(self, 'worldsectors_trees') and self.worldsectors_trees:
            for file_path in self.worldsectors_trees.keys():
                import re
                match = re.search(r'worldsector(\d+)', file_path)
                if match:
                    sector_num = match.group(1)
                    available_sectors.append(sector_num)
        
        if not available_sectors and hasattr(self, 'entities'):
            seen_sectors = set()
            for entity in self.entities:
                source_file = getattr(entity, 'source_file_path', None)
                if source_file and 'worldsector' in source_file:
                    import re
                    match = re.search(r'worldsector(\d+)', source_file)
                    if match:
                        sector_num = match.group(1)
                        seen_sectors.add(sector_num)
            available_sectors = list(seen_sectors)
        
        if not available_sectors and current_file and current_file != "Unknown":
            import os
            import glob
            directory = os.path.dirname(current_file)
            if os.path.exists(directory):
                pattern = os.path.join(directory, "worldsector*.converted.xml")
                found_files = glob.glob(pattern)
                for file_path in found_files:
                    import re
                    match = re.search(r'worldsector(\d+)', file_path)
                    if match:
                        sector_num = match.group(1)
                        available_sectors.append(sector_num)
        
        if not available_sectors:
            QMessageBox.warning(
                self, 
                "No Sectors Available", 
                f"No worldsector files found.\n\n"
                f"Current entity file: {current_file}\n"
                f"Worldsectors_trees loaded: {len(self.worldsectors_trees) if hasattr(self, 'worldsectors_trees') else 0}\n"
                f"Please load worldsectors first or check file paths."
            )
            return False
        
        available_sectors.sort(key=int)
        
        # Ask user which sector to move to
        sector_choice, ok = QInputDialog.getItem(
            self,
            "Move to Sector",
            f"Move {entity.name} from sector {current_sector} to which sector?",
            available_sectors,
            0,
            False
        )
        
        if not ok:
            return False
        
        # Find the target file
        target_file = None
        
        if hasattr(self, 'worldsectors_trees'):
            for file_path in self.worldsectors_trees.keys():
                if f'worldsector{sector_choice}' in file_path:
                    target_file = file_path
                    break
        
        if not target_file and current_file and current_file != "Unknown":
            import os
            directory = os.path.dirname(current_file)
            possible_names = [
                f"worldsector{sector_choice}.data.fcb.converted.xml",
                f"worldsector{sector_choice}.converted.xml",
                f"worldsector{sector_choice}.data.xml"
            ]
            
            for name in possible_names:
                potential_path = os.path.join(directory, name)
                if os.path.exists(potential_path):
                    target_file = potential_path
                    
                    if not hasattr(self, 'worldsectors_trees'):
                        self.worldsectors_trees = {}
                    
                    if target_file not in self.worldsectors_trees:
                        try:
                            import xml.etree.ElementTree as ET
                            tree = ET.parse(target_file)
                            self.worldsectors_trees[target_file] = tree
                            print(f"Loaded {target_file} for sector move")
                        except Exception as e:
                            print(f"Error loading {target_file}: {e}")
                            continue
                    break
        
        if not target_file:
            QMessageBox.critical(
                self,
                "Sector Not Found", 
                f"Could not find worldsector{sector_choice} file.\n\n"
                f"Looked for file in directory: {os.path.dirname(current_file) if current_file != 'Unknown' else 'Unknown'}"
            )
            return False
        
        if target_file == current_file:
            QMessageBox.information(
                self,
                "Same Sector",
                f"Entity {entity.name} is already in sector {sector_choice}."
            )
            return False
        
        # NEW: Get available MissionLayers in target sector
        try:
            import xml.etree.ElementTree as ET
            target_tree = self.worldsectors_trees[target_file]
            target_root = target_tree.getroot()
            mission_layers = target_root.findall(".//object[@name='MissionLayer']")
            
            if not mission_layers:
                QMessageBox.warning(
                    self,
                    "No MissionLayers Found",
                    f"Target sector has no MissionLayers!\n\nCannot move entity."
                )
                return False
            
            # If only one layer, use it automatically
            if len(mission_layers) == 1:
                target_layer_index = 0
                print(f"Target sector has 1 MissionLayer, using it automatically")
            else:
                # Extract actual layer names from text_PathId field
                layer_names = []
                for i, layer in enumerate(mission_layers):
                    name_field = layer.find("./field[@name='text_PathId']")
                    if name_field is not None:
                        full_path = name_field.get('value-String', '')
                        # Extract just the layer name (part after last \)
                        if full_path and '\\' in full_path:
                            layer_name = full_path.split('\\')[-1]
                        else:
                            layer_name = full_path if full_path else f"MissionLayer {i+1}"
                        layer_names.append(f"{i+1}. {layer_name}")
                    else:
                        # Fallback if no text_PathId found
                        layer_names.append(f"{i+1}. MissionLayer {i+1}")
                
                layer_choice, ok = QInputDialog.getItem(
                    self,
                    "Choose Target MissionLayer",
                    f"Target sector has {len(mission_layers)} MissionLayers.\n"
                    f"Which layer should receive {entity.name}?",
                    layer_names,
                    0,  # Default to first layer
                    False
                )
                
                if not ok:
                    return False
                
                # Extract index from choice (the number before the dot)
                target_layer_index = layer_names.index(layer_choice)
                print(f"User chose MissionLayer {target_layer_index + 1}: {layer_choice}")
            
        except Exception as e:
            print(f"Error checking MissionLayers: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to check target sector's MissionLayers:\n{str(e)}"
            )
            return False
        
        # Confirm the move
        reply = QMessageBox.question(
            self,
            "Confirm Move",
            f"Move {entity.name} from sector {current_sector} to sector {sector_choice}?\n\n"
            f"Target: MissionLayer {target_layer_index + 1} of {len(mission_layers)}\n\n"
            f"From:\n{current_file}\n\n"
            f"To:\n{target_file}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return False
        
        # Perform the move with chosen layer
        return self.execute_sector_move(entity, current_file, target_file, sector_choice, target_layer_index)

    def execute_sector_move(self, entity, current_file, target_file, target_sector, target_layer_index=0):
        """Execute the actual sector move operation - WITH STRUCTURE CHILDREN SUPPORT AND LAYER SELECTION"""
        try:
            print(f"\nðŸšš Executing sector move for {entity.name}")
            print(f"From: {current_file}")
            print(f"To: {target_file} (MissionLayer {target_layer_index + 1})")
            
            # Collect all entities to move (parent + children)
            entities_to_move = self.collect_entities_for_sector_move(entity)
            
            if len(entities_to_move) > 1:
                print(f"\nMoving Structure group: {len(entities_to_move)} entities")
            
            moved_count = 0
            failed_entities = []
            
            # Move each entity
            for i, ent in enumerate(entities_to_move):
                print(f"\n--- Moving entity {i+1}/{len(entities_to_move)}: {ent.name} ---")
                
                # Get entity's current file
                ent_current_file = getattr(ent, 'source_file_path', current_file)
                
                # Step 1: Remove from current sector
                if ent_current_file and ent_current_file != "Unknown":
                    success = self.remove_entity_from_sector(ent, ent_current_file)
                    if not success:
                        print(f"Failed to remove {ent.name} from source")
                        failed_entities.append(ent.name)
                        continue
                    print(f"Removed {ent.name} from {os.path.basename(ent_current_file)}")
                
                # Step 2: Update entity's file reference
                ent.source_file_path = target_file
                
                # Step 3: Add to target sector with specified layer
                success = self.add_entity_to_sector(ent, target_file, target_layer_index)
                if not success:
                    print(f"Failed to add {ent.name} to target")
                    failed_entities.append(ent.name)
                    continue
                
                print(f"Added {ent.name} to {os.path.basename(target_file)} (Layer {target_layer_index + 1})")
                moved_count += 1
            
            # Step 4: Update UI
            if hasattr(self, 'update_entity_tree'):
                self.update_entity_tree()
            
            if hasattr(self, 'canvas'):
                self.canvas.update()
            
            # Step 5: Mark as modified
            self.entities_modified = True
            
            # Show result
            if failed_entities:
                QMessageBox.warning(
                    self,
                    "Partial Move Success",
                    f"Moved {moved_count}/{len(entities_to_move)} entities to sector {target_sector} (Layer {target_layer_index + 1}).\n\n"
                    f"Failed entities:\n" + "\n".join(f"{name}" for name in failed_entities)
                )
            else:
                if len(entities_to_move) > 1:
                    QMessageBox.information(
                        self,
                        "Move Successful",
                        f"Successfully moved {entity.name} and {len(entities_to_move)-1} children "
                        f"({moved_count} total entities) to sector {target_sector}!\n\n"
                        f"Placed in: MissionLayer {target_layer_index + 1}"
                    )
                else:
                    QMessageBox.information(
                        self,
                        "Move Successful",
                        f"Successfully moved {entity.name} to sector {target_sector}!\n\n"
                        f"Placed in: MissionLayer {target_layer_index + 1}"
                    )
            
            return moved_count > 0
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Move Error",
                f"Error moving entity: {str(e)}"
            )
            print(f"Error in execute_sector_move: {e}")
            import traceback
            traceback.print_exc()
            return False

    def add_entity_to_sector(self, entity, target_file, target_layer_index=0):
        """Add entity to target sector XML file - WITH LAYER SELECTION SUPPORT AND MISSION COMPONENT"""
        try:
            print(f"\n➕ Adding {entity.name} to {os.path.basename(target_file)} (Layer {target_layer_index + 1})")
            
            # Auto-load target file if not already loaded
            if not hasattr(self, 'worldsectors_trees'):
                self.worldsectors_trees = {}
            
            if target_file not in self.worldsectors_trees:
                if os.path.exists(target_file):
                    try:
                        import xml.etree.ElementTree as ET
                        tree = ET.parse(target_file)
                        self.worldsectors_trees[target_file] = tree
                        print(f"📂 Auto-loaded target file: {os.path.basename(target_file)}")
                    except Exception as e:
                        print(f"❌ Error loading target file {target_file}: {e}")
                        return False
                else:
                    print(f"❌ Target file does not exist: {target_file}")
                    return False
            
            tree = self.worldsectors_trees[target_file]
            root = tree.getroot()
            
            # Find ALL MissionLayers
            mission_layers = root.findall(".//object[@name='MissionLayer']")
            if not mission_layers:
                print(f"❌ No MissionLayer found in {target_file}")
                return False
            
            print(f"📋 Found {len(mission_layers)} MissionLayer(s) in target file")
            
            # Validate layer index
            if target_layer_index < 0 or target_layer_index >= len(mission_layers):
                print(f"⚠️ Invalid layer index {target_layer_index}, using layer 0")
                target_layer_index = 0
            
            # Use the specified MissionLayer
            mission_layer = mission_layers[target_layer_index]
            
            # Get the mission layer name
            mission_layer_name = None
            name_field = mission_layer.find(".//field[@name='text_PathId']")
            if name_field is not None:
                mission_layer_name = name_field.get('value-String', '').lower()
            
            print(f"🎯 Using MissionLayer {target_layer_index + 1}: '{mission_layer_name}' for adding entity")
            
            # Count existing entities in the target MissionLayer
            existing_entities = mission_layer.findall("object[@name='Entity']")
            print(f"📊 Target MissionLayer has {len(existing_entities)} existing entities")
            
            # Create a completely fresh copy of the entity XML element
            import xml.etree.ElementTree as ET
            
            if hasattr(entity, 'xml_element') and entity.xml_element is not None:
                # Create a deep copy of the existing XML element
                xml_string = ET.tostring(entity.xml_element, encoding='unicode')
                fresh_element = ET.fromstring(xml_string)
                print(f"✅ Created fresh XML element from existing element")
            else:
                print(f"❌ Entity has no xml_element - cannot proceed")
                return False
            
            # 🆕 ADD MISSION COMPONENT if mission layer is not "main" or "outside_entity"
            skip_layers = ['main', 'outside_entity']
            if mission_layer_name and mission_layer_name not in skip_layers:
                print(f"🔧 Adding CMissionComponent for mission layer: {mission_layer_name}")
                
                # Find or create Components object
                components = fresh_element.find(".//object[@name='Components']")
                if components is None:
                    print(f"   Creating new Components object")
                    components = ET.SubElement(fresh_element, 'object', {
                        'hash': 'A115F62D',
                        'name': 'Components'
                    })
                
                # Check if CMissionComponent already exists
                existing_mission_comp = components.find(".//object[@name='CMissionComponent']")
                if existing_mission_comp is not None:
                    print(f"   Removing existing CMissionComponent")
                    components.remove(existing_mission_comp)
                
                # Create CMissionComponent
                mission_comp = ET.SubElement(components, 'object', {
                    'hash': 'D18498C8',
                    'name': 'CMissionComponent'
                })
                
                # Convert mission layer name to BinHex
                mission_layer_binhex = mission_layer_name.encode('utf-8').hex().upper() + '00'
                
                # Add text_hidMissionLayerPath field
                ET.SubElement(mission_comp, 'field', {
                    'hash': '7AF1FD74',
                    'name': 'text_hidMissionLayerPath',
                    'value-String': mission_layer_name,
                    'type': 'BinHex'
                }).text = mission_layer_binhex
                
                # Calculate ComputeHash32 for the mission layer name
                # This is a placeholder - you may need proper hash calculation
                import struct
                mission_hash = sum(ord(c) for c in mission_layer_name) % (2**32)
                mission_hash_hex = struct.pack('<I', mission_hash).hex().upper()
                
                # Add hidMissionLayerPath field
                ET.SubElement(mission_comp, 'field', {
                    'hash': '90AF9D50',
                    'name': 'hidMissionLayerPath',
                    'value-ComputeHash32': mission_layer_name,
                    'type': 'BinHex'
                }).text = mission_hash_hex
                
                # Add text_hidCategory field (empty)
                ET.SubElement(mission_comp, 'field', {
                    'hash': '27B31D2E',
                    'name': 'text_hidCategory',
                    'value-String': '',
                    'type': 'BinHex'
                }).text = '00'
                
                # Add hidCategory field (0xFFFFFFFF)
                ET.SubElement(mission_comp, 'field', {
                    'hash': '37F59D7D',
                    'name': 'hidCategory',
                    'type': 'BinHex'
                }).text = 'FFFFFFFF'
                
                # Add ForceMerge field
                ET.SubElement(mission_comp, 'field', {
                    'hash': '136C40D8',
                    'name': 'ForceMerge',
                    'type': 'BinHex'
                }).text = '01'
                
                print(f"   ✅ CMissionComponent added successfully")
            else:
                print(f"   ⏭️ Skipping CMissionComponent (layer: {mission_layer_name})")
            
            # Add to MissionLayer
            mission_layer.append(fresh_element)
            
            # Verify addition
            new_entities = mission_layer.findall("object[@name='Entity']")
            if len(new_entities) > len(existing_entities):
                print(f"✅ Successfully added {entity.name} to {os.path.basename(target_file)} (Layer {target_layer_index + 1})")
                print(f"📊 MissionLayer now has {len(new_entities)} entities")
                
                # Update entity's XML reference
                entity.xml_element = fresh_element
                
                # Save immediately
                tree.write(target_file, encoding='utf-8', xml_declaration=True)
                print(f"💾 Saved {os.path.basename(target_file)}")
                
                # Mark file as modified
                if not hasattr(self, 'worldsectors_modified'):
                    self.worldsectors_modified = {}
                self.worldsectors_modified[target_file] = True
                
                return True
            else:
                print(f"❌ Entity addition verification failed")
                return False
                
        except Exception as e:
            print(f"❌ Error adding entity: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def collect_entities_for_sector_move(self, entity):
        """
        Collect entity and all its children/seated NPCs if it's a Structure or Vehicle.
        Returns list of entities to move together.
        """
        entities_to_move = [entity]
        
        # Check if this is a Structure/Prefab entity
        if hasattr(entity, 'xml_element') and entity.xml_element is not None:
            entity_class_field = entity.xml_element.find(".//field[@name='text_hidEntityClass']")
            if entity_class_field is not None:
                entity_class = entity_class_field.get('value-String', '')
                
                # 1. Handle Structure children
                if 'Prefab' in entity_class or 'Structure' in entity.name:
                    print(f"🗗️ Moving Structure: {entity.name}, collecting children...")
                    
                    # Build entity lookup dict
                    entities_dict = {}
                    for ent in self.entities:
                        entities_dict[ent.id] = ent
                    
                    # Find children
                    children_obj = entity.xml_element.find(".//object[@name='Children']")
                    if children_obj is not None:
                        child_objects = children_obj.findall("object[@name='Child']")
                        
                        for child_obj in child_objects:
                            id_field = child_obj.find("field[@name='ID']")
                            name_field = child_obj.find("field[@name='Name']")
                            
                            if id_field is not None:
                                child_id = id_field.get('value-Hash64')
                                child_name = _get_str_val(name_field) if name_field is not None else 'unknown'
                                
                                # Find the actual child entity
                                if child_id in entities_dict:
                                    child_entity = entities_dict[child_id]
                                    entities_to_move.append(child_entity)
                                    print(f"  ✅ Will move child: {child_name}")
                                elif child_name:
                                    # Fallback: find by name
                                    for ent_id, ent in entities_dict.items():
                                        if ent.name == child_name:
                                            entities_to_move.append(ent)
                                            print(f"  ✅ Will move child by name: {child_name}")
                                            break
                        
                        if len(entities_to_move) > 1:
                            print(f"  ✅ Total entities to move: {len(entities_to_move)} (1 parent + {len(entities_to_move)-1} children)")
            
            # 2. Handle seated NPCs (NEW!)
            ai_component = entity.xml_element.find(".//object[@name='CFCXAIComponent']")
            if ai_component is not None:
                ai_object = ai_component.find(".//object[@name='AIObject']")
                if ai_object is not None:
                    print(f"🚗 Moving Vehicle: {entity.name}, collecting seated NPCs...")
                    
                    # Build entity lookup dict if not already done
                    if 'entities_dict' not in locals():
                        entities_dict = {}
                        for ent in self.entities:
                            entities_dict[ent.id] = ent
                    
                    seated_ids = []
                    # Find all fields in AIObject that reference entities
                    for field in ai_object.findall("field"):
                        entity_id_ref = field.get('value-Hash64')
                        if entity_id_ref and entity_id_ref in entities_dict:
                            seated_entity = entities_dict[entity_id_ref]
                            # Make sure it's not self-reference
                            if seated_entity.id != entity.id:
                                if seated_entity not in entities_to_move:
                                    entities_to_move.append(seated_entity)
                                    seated_ids.append(seated_entity.id)
                                    print(f"  🪑 Will move seated NPC: {seated_entity.name}")
                    
                    if seated_ids:
                        print(f"  ✅ Vehicle has {len(seated_ids)} seated NPCs to move")
        
        return entities_to_move

    def add_sector_move_to_context_menu(self):
        """Add sector move option to existing context menu - WITH STRUCTURE GROUP SUPPORT"""
        
        # Store the original context menu function if it exists
        if hasattr(self.canvas, 'showContextMenu'):
            original_context_menu = self.canvas.showContextMenu
        else:
            original_context_menu = None
        
        def enhanced_showContextMenu(event):
            """Enhanced context menu with sector move option"""
            from PyQt6.QtWidgets import QMenu
            from PyQt6.QtCore import Qt
            
            menu = QMenu(self.canvas)
            
            # Check if we have a selected entity
            selected_entity = None
            if hasattr(self.canvas, 'selected') and self.canvas.selected:
                selected_entity = self.canvas.selected[0]
            elif hasattr(self, 'selected_entity') and self.selected_entity:
                selected_entity = self.selected_entity
            
            # Add sector move option if entity is selected
            if selected_entity:
                # Count how many entities will be moved (including children)
                entities_to_move = self.collect_entities_for_sector_move(selected_entity)
                entity_count = len(entities_to_move)
                
                if entity_count > 1:
                    menu.addAction(f"Selected: {selected_entity.name} + {entity_count-1} children").setEnabled(False)
                else:
                    menu.addAction(f"Selected: {selected_entity.name}").setEnabled(False)
                
                menu.addSeparator()
                
                # Check if entity is from worldsectors
                # In unified mode the editor auto-assigns sectors on save — no manual move needed
                source_file = getattr(selected_entity, 'source_file_path', None)
                is_unified = getattr(self.canvas, 'unified_mode', False)
                if source_file and 'worldsector' in source_file and not is_unified:
                    if entity_count > 1:
                        move_label = f"Move Structure to Different Sector... ({entity_count} entities)"
                    else:
                        move_label = "Move to Different Sector..."

                    move_sector_action = menu.addAction(move_label)
                    move_sector_action.triggered.connect(
                        lambda: self.move_entity_to_sector_manually(selected_entity)
                    )
                    menu.addSeparator()
                elif not is_unified:
                    menu.addAction("(Not a worldsector entity)").setEnabled(False)
                    menu.addSeparator()
            
            # Add original context menu items from your existing copy/paste system
            selected_entities = getattr(self.canvas, 'selected', [])
            has_selection = len(selected_entities) > 0
            has_clipboard = hasattr(self, 'entity_clipboard') and self.entity_clipboard.has_clipboard_data()
            
            if has_selection:
                copy_action = menu.addAction("Copy Entities")
                copy_action.triggered.connect(self.copy_selected_entities)
                
                duplicate_action = menu.addAction("Duplicate Entities")
                duplicate_action.triggered.connect(self.duplicate_selected_entities)
                
                delete_action = menu.addAction("Delete Entities")
                delete_action.triggered.connect(self.delete_selected_entities)
                
                menu.addSeparator()
            
            if has_clipboard:
                clipboard_info = self.entity_clipboard.get_clipboard_info()
                if clipboard_info:
                    paste_label = f"Paste {clipboard_info['count']} Entities"
                    
                    paste_action = menu.addAction(paste_label)
                    paste_action.triggered.connect(lambda: self.paste_entities(at_cursor=True))
                    
                    paste_original_action = menu.addAction("Paste at Original Position")
                    paste_original_action.triggered.connect(lambda: self.paste_entities(at_cursor=False))
                    
                    menu.addSeparator()
            
            # MP Spawn Point creator (only when worldsectors are loaded)
            if getattr(self, 'worldsectors_trees', None):
                menu.addSeparator()
                mp_spawn_action = menu.addAction("Add MP Spawn Point (LeftForDeadTrigger)...")
                def _open_mp_spawn(checked=False, _event=event):
                    lpos = _event.position()
                    wx, wy = self.canvas.screen_to_world(lpos.x(), lpos.y())
                    from canvas.mp_spawn_creator import MPSpawnCreatorDialog
                    dlg = MPSpawnCreatorDialog(self, wx, wy, parent=self)
                    dlg.exec()
                mp_spawn_action.triggered.connect(_open_mp_spawn)

            # Selection actions
            if not has_selection:
                select_all_action = menu.addAction("Select All Entities")
                select_all_action.triggered.connect(self.select_all_entities)
                menu.addSeparator()

            # View actions
            center_action = menu.addAction("Center View Here")
            center_action.triggered.connect(lambda: self.center_view_here(event))
            
            reset_action = menu.addAction("Reset View")
            reset_action.triggered.connect(self.reset_view)
            
            # Toggle options
            menu.addSeparator()
            toggle_grid_action = menu.addAction("Toggle Grid")
            toggle_grid_action.setCheckable(True)
            toggle_grid_action.setChecked(self.canvas.show_grid)
            toggle_grid_action.triggered.connect(self.toggle_grid)
            
            toggle_entities_action = menu.addAction("Toggle Entities")
            toggle_entities_action.setCheckable(True)
            toggle_entities_action.setChecked(self.canvas.show_entities)
            toggle_entities_action.triggered.connect(self.toggle_entities)

            # Add sector boundaries toggle if available
            if hasattr(self.canvas, 'show_sector_boundaries'):
                toggle_sectors_action = menu.addAction("Toggle Sector Boundaries")
                toggle_sectors_action.setCheckable(True)
                toggle_sectors_action.setChecked(self.canvas.show_sector_boundaries)
                toggle_sectors_action.triggered.connect(self.toggle_sector_boundaries)
            
            # Show the menu
            menu.exec(event.globalPosition().toPoint())
        
        # Replace the context menu
        self.canvas.showContextMenu = enhanced_showContextMenu
        print("Added 'Move Structure to Different Sector' to enhanced right-click menu")

    def center_view_here(self, event):
        """Center view at click location"""
        width = self.canvas.width()
        height = self.canvas.height()
        self.canvas.offset_x += width / 2 - event.position().x()
        self.canvas.offset_y += height / 2 - event.position().y()
        self.canvas.update()

    def _find_tree_file_path(self, tree_type):
        """Find the file path for a specific tree type"""
        if not hasattr(self, 'xml_file_path') or not self.xml_file_path:
            return None
        
        folder_path = os.path.dirname(self.xml_file_path)
        
        # Define patterns to look for each tree type
        patterns = {
            'omnis': ['.omnis.xml', 'omnis.xml'],
            'managers': ['.managers.xml', 'managers.xml'],
            'sectordep': ['sectorsdep.xml', 'sectordep.xml', '.sectorsdep.xml']
        }
        
        if tree_type not in patterns:
            return None
        
        # Try to find existing file
        for pattern in patterns[tree_type]:
            file_path = os.path.join(folder_path, pattern)
            if os.path.exists(file_path):
                return file_path
            
            # Also try with level name prefix
            if hasattr(self, 'xml_file_path') and self.xml_file_path:
                level_name = os.path.splitext(os.path.basename(self.xml_file_path))[0]
                prefixed_pattern = f"{level_name}{pattern}"
                file_path = os.path.join(folder_path, prefixed_pattern)
                if os.path.exists(file_path):
                    return file_path
        
        # If not found, return None (don't create new files)
        return None
        
    def determine_entity_map(self, entity):
        """Determine which map an entity belongs to based on its coordinates"""
        if not self.grid_config or not self.grid_config.maps:
            return None
            
        # Convert entity coordinates to sector coordinates
        sector_x = int(entity.x / self.grid_config.sector_granularity)
        sector_y = int(entity.z / self.grid_config.sector_granularity)  # Note: using Z for Y-axis
        
        # Check each map to see if entity belongs to it
        for map_info in self.grid_config.maps:
            min_sector_x = map_info.sector_offset_x
            min_sector_y = map_info.sector_offset_y
            max_sector_x = min_sector_x + map_info.count_x
            max_sector_y = min_sector_y + map_info.count_y
            
            if (min_sector_x <= sector_x < max_sector_x and 
                min_sector_y <= sector_y < max_sector_y):
                return map_info.name
        
        return None

    def create_entity_browser(self):
        """Create a dock widget for browsing and organizing entities"""
        entity_dock = QDockWidget("Entity Browser", self)
        entity_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        entity_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable |
                                QDockWidget.DockWidgetFeature.DockWidgetFloatable)

        dock_widget = QWidget()
        dock_layout = QVBoxLayout(dock_widget)
        dock_layout.setContentsMargins(4, 4, 4, 4)
        dock_layout.setSpacing(4)

        # Shared filter bar (applies to whichever tab is active)
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter:"))
        self.entity_filter = QLineEdit()
        self.entity_filter.setPlaceholderText("Search entities...")
        self.entity_filter.textChanged.connect(self.filter_entities)
        filter_layout.addWidget(self.entity_filter)
        dock_layout.addLayout(filter_layout)

        # Tab widget
        from PyQt6.QtWidgets import QTabWidget
        self.browser_tabs = QTabWidget()
        self.browser_tabs.setDocumentMode(True)
        dock_layout.addWidget(self.browser_tabs)

        # ── Tab 1: Entity List (existing behaviour unchanged) ──────────────
        entity_tab = QWidget()
        entity_tab_layout = QVBoxLayout(entity_tab)
        entity_tab_layout.setContentsMargins(0, 4, 0, 0)
        entity_tab_layout.setSpacing(4)

        self.entity_tree = QTreeWidget()
        self.entity_tree.setHeaderLabels(["Name", "ID", "Position", "Angles"])
        self.entity_tree.setColumnWidth(0, 180)
        self.entity_tree.setColumnWidth(1, 80)
        self.entity_tree.setColumnWidth(2, 130)
        self.entity_tree.setColumnWidth(3, 110)
        self.entity_tree.setAlternatingRowColors(False)
        self.entity_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.entity_tree.itemSelectionChanged.connect(self.on_entity_tree_selection_changed)
        self.entity_tree.itemDoubleClicked.connect(self.on_entity_tree_double_clicked)
        self.entity_tree.itemClicked.connect(self.on_entity_tree_item_clicked)
        self.entity_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.entity_tree.customContextMenuRequested.connect(self.on_entity_tree_context_menu)
        entity_tab_layout.addWidget(self.entity_tree)

        btn_layout = QHBoxLayout()
        select_all_button = QPushButton("Select All")
        select_all_button.clicked.connect(self.select_all_entities)
        btn_layout.addWidget(select_all_button)
        select_none_button = QPushButton("Select None")
        select_none_button.clicked.connect(self.clear_entity_selection)
        btn_layout.addWidget(select_none_button)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.update_entity_tree)
        btn_layout.addWidget(refresh_button)
        self.browser_add_angles_btn = QPushButton("+ Angles")
        self.browser_add_angles_btn.setToolTip("Add hidAngles field to selected entity")
        self.browser_add_angles_btn.clicked.connect(self._add_hidangles_from_browser)
        self.browser_add_angles_btn.hide()
        btn_layout.addWidget(self.browser_add_angles_btn)
        entity_tab_layout.addLayout(btn_layout)

        self.browser_tabs.addTab(entity_tab, "Entities")

        # ── Tab 2: Mission Layers ───────────────────────────────────────────
        mission_tab = QWidget()
        mission_tab_layout = QVBoxLayout(mission_tab)
        mission_tab_layout.setContentsMargins(0, 4, 0, 0)
        mission_tab_layout.setSpacing(4)

        self.mission_layer_tree = QTreeWidget()
        self.mission_layer_tree.setHeaderLabels(["Layer / Entity", "Type", "Position"])
        self.mission_layer_tree.setColumnWidth(0, 220)
        self.mission_layer_tree.setColumnWidth(1, 80)
        self.mission_layer_tree.setColumnWidth(2, 120)
        self.mission_layer_tree.setAlternatingRowColors(False)
        self.mission_layer_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.mission_layer_tree.itemSelectionChanged.connect(self.on_mission_layer_tree_selection_changed)
        self.mission_layer_tree.itemDoubleClicked.connect(self.on_entity_tree_double_clicked)
        mission_tab_layout.addWidget(self.mission_layer_tree)

        self.browser_tabs.addTab(mission_tab, "Mission Layers")

        # ── Tab 3: Sequences ────────────────────────────────────────────────
        seq_tab = QWidget()
        seq_tab_layout = QVBoxLayout(seq_tab)
        seq_tab_layout.setContentsMargins(0, 4, 0, 0)
        seq_tab_layout.setSpacing(4)

        self.sequences_tree = QTreeWidget()
        self.sequences_tree.setHeaderLabels(["Sequence", "Duration"])
        self.sequences_tree.setColumnWidth(0, 220)
        self.sequences_tree.setColumnWidth(1, 60)
        self.sequences_tree.setAlternatingRowColors(False)
        self.sequences_tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.sequences_tree.itemSelectionChanged.connect(self._on_sequence_selected)
        seq_tab_layout.addWidget(self.sequences_tree)

        # Preview controls row
        seq_ctrl = QWidget()
        seq_ctrl_layout = QHBoxLayout(seq_ctrl)
        seq_ctrl_layout.setContentsMargins(4, 0, 4, 4)
        seq_ctrl_layout.setSpacing(4)
        self._seq_play_btn = QPushButton("▶  Preview")
        self._seq_play_btn.setEnabled(False)
        self._seq_play_btn.clicked.connect(self._movie_preview_start)
        self._seq_stop_btn = QPushButton("■  Stop")
        self._seq_stop_btn.setEnabled(False)
        self._seq_stop_btn.clicked.connect(self._movie_preview_stop)
        self._seq_reset_btn = QPushButton("↺  Reset")
        self._seq_reset_btn.setEnabled(False)
        self._seq_reset_btn.clicked.connect(self._movie_preview_reset)
        self._seq_time_label = QLabel("")
        self._seq_time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        seq_ctrl_layout.addWidget(self._seq_play_btn)
        seq_ctrl_layout.addWidget(self._seq_stop_btn)
        seq_ctrl_layout.addWidget(self._seq_reset_btn)
        seq_ctrl_layout.addWidget(self._seq_time_label, 1)
        seq_tab_layout.addWidget(seq_ctrl)

        self.browser_tabs.addTab(seq_tab, "Sequences")

        # Expand All / Collapse All buttons in the tab bar corner
        corner_widget = QWidget()
        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(0, 0, 2, 0)
        corner_layout.setSpacing(2)
        expand_btn = QPushButton("Expand All")
        expand_btn.clicked.connect(self._browser_expand_all)
        collapse_btn = QPushButton("Collapse All")
        collapse_btn.clicked.connect(self._browser_collapse_all)
        corner_layout.addWidget(expand_btn)
        corner_layout.addWidget(collapse_btn)
        self.browser_tabs.setCornerWidget(corner_widget, Qt.Corner.TopRightCorner)

        # Populate mission layer tree when that tab is made active
        self.browser_tabs.currentChanged.connect(self._on_browser_tab_changed)

        entity_dock.setWidget(dock_widget)
        entity_dock.setMinimumWidth(400)
        entity_dock.setMaximumWidth(500)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, entity_dock)
        self.entity_browser_dock = entity_dock

        self.update_entity_tree()
        return entity_dock

    def _browser_expand_all(self):
        idx = self.browser_tabs.currentIndex()
        if idx == 1:
            self.mission_layer_tree.expandAll()
        elif idx == 2:
            self.sequences_tree.expandAll()
        else:
            self.entity_tree.expandAll()

    def _browser_collapse_all(self):
        idx = self.browser_tabs.currentIndex()
        if idx == 1:
            self.mission_layer_tree.collapseAll()
        elif idx == 2:
            self.sequences_tree.collapseAll()
        else:
            self.entity_tree.collapseAll()

    def _on_browser_tab_changed(self, index):
        """Populate the mission layer tab on first switch, then keep it in sync."""
        if index == 1:
            self.update_mission_layer_tree()
        elif index == 2:
            self.update_sequences_tab()

    def update_mission_layer_tree(self):
        """Populate the Mission Layers tab, grouping entities by hidMissionLayerPath."""
        # Save expanded state before clearing so switching tabs doesn't reset it.
        # Keys: mission base name (strip " (N)" count suffix) → {'_top': bool, 'children': {layer: bool}}
        expanded_state = {}
        for i in range(self.mission_layer_tree.topLevelItemCount()):
            top = self.mission_layer_tree.topLevelItem(i)
            key = top.text(0).split('  (')[0]
            children = {}
            for j in range(top.childCount()):
                ch = top.child(j)
                children[ch.text(0)] = ch.isExpanded()
            expanded_state[key] = {'_top': top.isExpanded(), 'children': children}

        self.mission_layer_tree.clear()
        if not self.entities:
            return

        filter_text = self.entity_filter.text().lower()

        # Build dict:  mission_script -> { layer_name -> [entity, ...] }
        layers = {}
        for entity in self.entities:
            layer_path = ""
            if hasattr(entity, 'xml_element') and entity.xml_element is not None:
                f = entity.xml_element.find(".//field[@name='text_hidMissionLayerPath']")
                if f is not None:
                    layer_path = f.get('value-String') or f.get('value-string') or ""

            if not layer_path:
                mission = "Main"
                layer   = ""
            elif "\\" in layer_path:
                mission, layer = layer_path.split("\\", 1)
            else:
                mission = layer_path
                layer   = ""

            layers.setdefault(mission, {}).setdefault(layer, []).append(entity)

        # Render tree
        for mission in sorted(layers):
            sub = layers[mission]

            # Count matching entities under this mission for the header
            mission_item = QTreeWidgetItem()
            mission_item.setText(0, mission)
            bold = mission_item.font(0)
            bold.setBold(True)
            mission_item.setFont(0, bold)
            self.mission_layer_tree.addTopLevelItem(mission_item)

            entity_count = 0
            for layer_name in sorted(sub):
                entities = sub[layer_name]

                if layer_name:
                    parent = QTreeWidgetItem(mission_item)
                    parent.setText(0, layer_name)
                    f = parent.font(0)
                    f.setItalic(True)
                    parent.setFont(0, f)
                else:
                    parent = mission_item  # flat — entities go directly under mission

                for entity in entities:
                    display_name = self._entity_display_name(entity)
                    if filter_text and filter_text not in display_name.lower() and filter_text not in entity.id.lower():
                        continue
                    entity_type = self._determine_entity_type_for_browser(entity)
                    item = QTreeWidgetItem(parent)
                    item.setText(0, display_name)
                    item.setText(1, entity_type)
                    item.setText(2, f"({entity.x:.0f}, {entity.y:.0f}, {entity.z:.0f})")
                    item.setData(0, Qt.ItemDataRole.UserRole, entity)
                    self._set_item_theme_color(item)
                    entity_count += 1

            total = sum(len(v) for v in sub.values())
            mission_item.setText(0, f"{mission}  ({total})")
            saved = expanded_state.get(mission)
            mission_item.setExpanded(saved['_top'] if saved else True)
            for i in range(mission_item.childCount()):
                ch = mission_item.child(i)
                ch.setExpanded(saved['children'].get(ch.text(0), True) if saved else True)

    def on_mission_layer_tree_selection_changed(self):
        """Mirror entity-tree selection logic for the mission layer tree."""
        selected_entities = []
        for item in self.mission_layer_tree.selectedItems():
            entity = item.data(0, Qt.ItemDataRole.UserRole)
            if entity:
                selected_entities.append(entity)

        if not selected_entities:
            if hasattr(self.canvas, 'selected'):
                self.canvas.selected = []
            self.selected_entity = None
            if hasattr(self.canvas, 'selected_entity'):
                self.canvas.selected_entity = None
            if hasattr(self.canvas, 'gizmo_renderer'):
                self.canvas.gizmo_renderer.hide_gizmo()
            if hasattr(self.canvas, 'gizmo_3d'):
                self.canvas.gizmo_3d.move_to(None)
            self.update_ui_for_selected_entity(None)
            self.update_model_preview(None)
            return

        primary_entity = selected_entities[0]
        if hasattr(self.canvas, 'selected'):
            self.canvas.selected = selected_entities
        self.on_entity_selected(primary_entity)
        if len(selected_entities) > 1:
            self.update_model_preview(selected_entities)

    # ── Sequences tab ──────────────────────────────────────────────────────────

    def update_sequences_tab(self):
        """Rebuild the Sequences tree from self.movie_data."""
        if not hasattr(self, 'sequences_tree'):
            return
        self.sequences_tree.clear()
        if not self.movie_data:
            item = QTreeWidgetItem(["No moviedata.xml loaded", ""])
            item.setForeground(0, QColor(120, 120, 120))
            self.sequences_tree.addTopLevelItem(item)
            self._seq_play_btn.setEnabled(False)
            self._seq_reset_btn.setEnabled(False)
            return

        for seq in self.movie_data.sequences:
            dur_str = f"{seq.duration():.1f}s"
            top = QTreeWidgetItem([seq.name, dur_str])
            top.setData(0, Qt.ItemDataRole.UserRole, seq.name)
            # Child rows show participating entity names
            for seq_node in seq.nodes:
                nd = self.movie_data.node_defs.get(seq_node.node_id)
                node_name = nd.name if nd else f"Node {seq_node.node_id}"
                track_ids = sorted(seq_node.tracks.keys())
                track_str = ",".join(str(p) for p in track_ids)
                child = QTreeWidgetItem([f"  {node_name}", f"tracks:{track_str}"])
                child.setForeground(0, QColor(180, 180, 180))
                # Store node_id so _on_sequence_selected can filter to this node
                child.setData(0, Qt.ItemDataRole.UserRole + 1, seq_node.node_id)
                top.addChild(child)
            self.sequences_tree.addTopLevelItem(top)

    def _on_sequence_selected(self):
        """A sequence row was clicked — store selection and redraw canvas paths."""
        items = self.sequences_tree.selectedItems()
        if not items:
            self.selected_movie_sequence = None
            self.selected_movie_node_id = None
            self._seq_play_btn.setEnabled(False)
            if hasattr(self, 'canvas'):
                self.canvas.update()
            return

        item = items[0]
        parent = item.parent()

        if parent is not None:
            # Child item — a specific node inside a sequence
            seq_name = parent.data(0, Qt.ItemDataRole.UserRole)
            node_id  = item.data(0, Qt.ItemDataRole.UserRole + 1)
            self.selected_movie_sequence = seq_name
            self.selected_movie_node_id  = node_id
        else:
            # Top-level sequence item — show all nodes
            seq_name = item.data(0, Qt.ItemDataRole.UserRole)
            self.selected_movie_sequence = seq_name
            self.selected_movie_node_id  = None

        has_seq = self.selected_movie_sequence is not None and self.movie_data is not None
        self._seq_play_btn.setEnabled(has_seq)
        self._seq_reset_btn.setEnabled(has_seq)
        if hasattr(self, 'canvas'):
            self.canvas.update()

    # ── Preview playback ───────────────────────────────────────────────────────

    def _movie_preview_start(self):
        """Start animating the selected sequence."""
        if not self.movie_data or not self.selected_movie_sequence:
            return
        seq = self.movie_data.get_sequence(self.selected_movie_sequence)
        if seq is None:
            return

        # Stop any running preview first
        self._movie_preview_stop(restore=False)

        # Build entity lookup: entity_id (str) -> entity
        entity_map = {e.id: e for e in (self.entities or [])}

        # Save original positions for every entity involved in this sequence
        self._movie_preview_saved = {}
        for seq_node in seq.nodes:
            nd = self.movie_data.node_defs.get(seq_node.node_id)
            if nd and nd.entity_id in entity_map:
                ent = entity_map[nd.entity_id]
                self._movie_preview_saved[nd.entity_id] = (ent.x, ent.y, ent.z)

        self._movie_preview_start_wall = time.time()
        self._seq_play_btn.setEnabled(False)
        self._seq_stop_btn.setEnabled(True)
        self._movie_preview_timer.start()

    def _movie_preview_stop(self, restore=True):
        """Stop playback and optionally restore entity positions."""
        self._movie_preview_timer.stop()
        self._seq_stop_btn.setEnabled(False)
        has_seq = self.selected_movie_sequence is not None and self.movie_data is not None
        self._seq_play_btn.setEnabled(has_seq)
        self._seq_reset_btn.setEnabled(has_seq)
        self._seq_time_label.setText("")

        if restore and self._movie_preview_saved:
            entity_map = {e.id: e for e in (self.entities or [])}
            for eid, (ox, oy, oz) in self._movie_preview_saved.items():
                if eid in entity_map:
                    ent = entity_map[eid]
                    ent.x, ent.y, ent.z = ox, oy, oz

        if restore and self._movie_preview_saved and hasattr(self, 'canvas'):
            # Patch restored positions into the cached arrays so culling stays correct
            updates = {eid: pos for eid, pos in self._movie_preview_saved.items()}
            self.canvas.patch_preview_positions(updates)

        self._movie_preview_saved = {}
        self._movie_preview_start_wall = None
        if hasattr(self, 'canvas'):
            self.canvas.update()

    def _movie_preview_tick(self):
        """Called ~30 fps during preview — interpolate and push positions to entities."""
        if not self.movie_data or not self.selected_movie_sequence:
            self._movie_preview_stop()
            return
        seq = self.movie_data.get_sequence(self.selected_movie_sequence)
        if seq is None:
            self._movie_preview_stop()
            return

        t = time.time() - self._movie_preview_start_wall
        if t > seq.end_time:
            # Done — restore and stop
            self._movie_preview_stop(restore=True)
            return

        entity_map = {e.id: e for e in (self.entities or [])}
        updates = {}
        for seq_node in seq.nodes:
            nd = self.movie_data.node_defs.get(seq_node.node_id)
            if not nd or nd.entity_id not in entity_map:
                continue
            pos = seq_node.pos_at(t)
            if pos:
                ent = entity_map[nd.entity_id]
                ent.x, ent.y, ent.z = pos[0], pos[1], pos[2]
                updates[nd.entity_id] = pos

        self._seq_time_label.setText(f"{t:.1f} / {seq.end_time:.1f}s")
        if hasattr(self, 'canvas') and updates:
            # Patch only the moving entities in the cached arrays — no full rebuild
            self.canvas.patch_preview_positions(updates)
            self.canvas.update()

    def _movie_preview_reset(self):
        """Stop preview and restore entities to their original worldsector positions."""
        # Delegate to stop(restore=True) — this restores saved originals if a preview
        # was running, and is a no-op if nothing was playing (saved dict is empty).
        self._movie_preview_stop(restore=True)

    def create_model_preview_dock(self):
        """Create a dock widget with a 3D model preview below the entity browser."""
        preview_dock = QDockWidget("Model Preview", self)
        preview_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        preview_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable |
                                 QDockWidget.DockWidgetFeature.DockWidgetFloatable)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # OpenGL preview widget
        self.model_preview = ModelPreviewWidget()
        layout.addWidget(self.model_preview)

        # Label showing entity name / model status
        self.model_preview_label = QLabel("No entity selected")
        self.model_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.model_preview_label.setWordWrap(True)
        self.model_preview_label.setMaximumHeight(36)
        layout.addWidget(self.model_preview_label)

        preview_dock.setWidget(container)
        preview_dock.setMinimumWidth(400)
        preview_dock.setMaximumWidth(500)

        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, preview_dock)
        self.splitDockWidget(self.entity_browser_dock, preview_dock, Qt.Orientation.Vertical)

        self.model_preview_dock = preview_dock
        return preview_dock

    def _resolve_model_for_entity(self, entity):
        """Return (model, entity_display_name, entity) or (None, name, entity).

        For kit-assembled NPCs, also returns kit part models via _resolve_kit_models_for_entity.
        """
        entity_name = self._entity_display_name(entity)
        model_file = getattr(entity, 'model_file', None)
        if not model_file:
            return None, entity_name, entity
        model = None
        if hasattr(self, 'canvas') and hasattr(self.canvas, 'model_loader'):
            model = self.canvas.model_loader.models_cache.get(model_file)
            if model is None:
                try:
                    model = self.canvas.model_loader.get_model_for_entity(entity)
                except Exception:
                    pass
        return model, entity_name, entity

    def _resolve_kit_models_for_entity(self, entity):
        """Return list of (model, name, entity) for all kit parts of a kit-assembled NPC.
        Returns empty list for entities with no kit parts or whose parts aren't cached yet.
        """
        if not hasattr(self, 'canvas') or not hasattr(self.canvas, 'model_loader'):
            return []
        cache = self.canvas.model_loader.models_cache
        result = []
        for kit_gltf, _kit_bin in getattr(entity, 'kit_model_files', []):
            kit_model = cache.get(kit_gltf)
            if kit_model is None:
                try:
                    # On-demand load if not yet in cache
                    kit_model = self.canvas.model_loader.get_model_for_entity(
                        type('_KitProxy', (), {'model_file': kit_gltf, 'bin_file': _kit_bin})()
                    )
                except Exception:
                    pass
            if kit_model and kit_model.meshes:
                result.append((kit_model, self._entity_display_name(entity), entity))
        return result

    def update_model_preview(self, entity_or_list):
        """Update the 3D model preview. Accepts a single entity or a list of entities."""
        if not hasattr(self, 'model_preview'):
            return

        if entity_or_list is None:
            self.model_preview.clear()
            self.model_preview_label.setText("No entity selected")
            return

        # Normalise to a list
        if isinstance(entity_or_list, list):
            entities = [e for e in entity_or_list if e is not None]
        else:
            entities = [entity_or_list]

        if not entities:
            self.model_preview.clear()
            self.model_preview_label.setText("No entity selected")
            return

        MAX_PREVIEW = 6
        entities = entities[:MAX_PREVIEW]

        if len(entities) == 1:
            # Single entity path — mirror prepare_batches/render_batched_models exactly:
            # collect base model + all kit parts from models_cache, pass to set_models.
            entity = entities[0]
            entity_name = self._entity_display_name(entity)
            models_list = []

            if not hasattr(self, 'canvas') or not hasattr(self.canvas, 'model_loader'):
                self.model_preview.clear()
                self.model_preview_label.setText(f"{entity_name}\n(no model)")
                return

            cache = self.canvas.model_loader.models_cache

            # Base model (may be None for kit-only NPCs)
            model_file = getattr(entity, 'model_file', None)
            if model_file:
                base_model = cache.get(model_file)
                if base_model and base_model.meshes:
                    models_list.append((base_model, entity_name, entity))

            # Kit parts — same lookup as render_batched_models
            for kit_gltf, _kit_bin in getattr(entity, 'kit_model_files', []):
                kit_model = cache.get(kit_gltf)
                if kit_model and kit_model.meshes:
                    models_list.append((kit_model, entity_name, entity))

            if models_list:
                self.model_preview.set_models(models_list)
                if len(models_list) > 1:
                    self.model_preview_label.setText(f"{entity_name}\n({len(models_list)} parts)")
                else:
                    import os
                    self.model_preview_label.setText(f"{entity_name}\n{os.path.basename(model_file or '')}")
            else:
                self.model_preview.clear()
                self.model_preview_label.setText(f"{entity_name}\n(no model)")
        else:
            # Group path — collect all models with meshes, keeping entity for world pos
            models_list = []
            no_model_names = []
            for entity in entities:
                model, entity_name, ent = self._resolve_model_for_entity(entity)
                if model and model.meshes:
                    models_list.append((model, entity_name, ent))
                else:
                    no_model_names.append(entity_name)

            if models_list:
                self.model_preview.set_models(models_list)  # already (model, name, entity) tuples
                label = f"{len(entities)} selected"
                if no_model_names:
                    label += f" ({len(no_model_names)} no model)"
                self.model_preview_label.setText(label)
            else:
                self.model_preview.clear()
                self.model_preview_label.setText(f"{len(entities)} selected\n(no models)")

    def debug_entity_update(self):
        """Debug the currently selected entity"""
        if self.selected_entity:
            print(f"\nDEBUG: Starting debug for {self.selected_entity.name}")
            self.canvas.debug_entity_xml_update(self.selected_entity.name)
        else:
            print("No entity selected for debugging")
            print("Please select an entity first, then click Debug Entity")

    def setup_entity_browser_connections(self):
        """Setup additional connections for the entity browser"""
        # Double-click handler for zooming to entity location
        self.entity_tree.itemDoubleClicked.connect(self.on_entity_tree_double_clicked)

    def on_entity_tree_selection_changed(self):
        """Handle selection change in the entity tree - FIXED to fully select entity like grid selection"""
        # Get selected items
        selected_items = self.entity_tree.selectedItems()
        
        # Filter out group items (which don't have entity data)
        selected_entities = []
        for item in selected_items:
            entity = item.data(0, Qt.ItemDataRole.UserRole)
            if entity:
                selected_entities.append(entity)
        
        # Skip if no entities selected
        if not selected_entities:
            # Clear selection and hide gizmo
            if hasattr(self.canvas, 'selected'):
                self.canvas.selected = []
            self.selected_entity = None
            if hasattr(self.canvas, 'selected_entity'):
                self.canvas.selected_entity = None

            # Hide gizmo when nothing is selected
            if hasattr(self.canvas, 'gizmo_renderer'):
                self.canvas.gizmo_renderer.hide_gizmo()
            if hasattr(self.canvas, 'gizmo_3d'):
                self.canvas.gizmo_3d.move_to(None)

            # Update UI
            self.update_ui_for_selected_entity(None)
            self.update_model_preview(None)
            if hasattr(self, 'browser_add_angles_btn'):
                self.browser_add_angles_btn.hide()
            self.canvas.update()
            return

        # CRITICAL FIX: Use the same handler as grid selection to ensure full selection
        # This ensures the entity is fully selected for the entity editor (Ctrl+E)
        primary_entity = selected_entities[0]
        
        # Print which entity was selected from the browser
        print(f"Entity Browser: Selected '{primary_entity.name}' (ID: {primary_entity.id})")
        
        # Set canvas selection for multiple selection support
        if hasattr(self.canvas, 'selected'):
            self.canvas.selected = selected_entities
        
        # Call the same handler as grid selection to ensure consistent behavior
        # This ensures the entity is fully recognized by entity editor and all systems
        self.on_entity_selected(primary_entity)

        # Group preview: update model preview with all selected entities
        if len(selected_entities) > 1:
            if hasattr(self.canvas, 'selected'):
                self.canvas.selected = selected_entities
            print(f"Multiple entities selected ({len(selected_entities)}), primary: {primary_entity.name}")
            self.update_model_preview(selected_entities)

        # Show/hide "Add Angles" button based on whether primary entity has hidAngles
        if hasattr(self, 'browser_add_angles_btn'):
            has_angles = (
                hasattr(primary_entity, 'xml_element') and
                primary_entity.xml_element is not None and
                primary_entity.xml_element.find(".//field[@name='hidAngles']") is not None
            )
            self.browser_add_angles_btn.setVisible(not has_angles)

    def on_entity_tree_item_clicked(self, item, column):
        """Left-click col 0 → copy name to clipboard."""
        if column == 0:
            text = item.text(0)
            if text:
                QApplication.clipboard().setText(text)
                self.status_bar.showMessage(f"Copied name: {text}", 2000)

    def on_entity_tree_context_menu(self, pos):
        """Right-click on entity tree → context menu with copy options."""
        item = self.entity_tree.itemAt(pos)
        if not item:
            return
        col = self.entity_tree.columnAt(pos.x())
        from PyQt6.QtWidgets import QMenu as _QMenu
        menu = _QMenu(self)
        if col == 1:
            id_text = item.text(1)
            copy_id_action = menu.addAction(f"Copy ID: {id_text}")
            copy_id_action.triggered.connect(lambda: (
                QApplication.clipboard().setText(id_text),
                self.status_bar.showMessage(f"Copied ID: {id_text}", 2000)
            ))
        name_text = item.text(0)
        copy_name_action = menu.addAction(f"Copy Name: {name_text}")
        copy_name_action.triggered.connect(lambda: (
            QApplication.clipboard().setText(name_text),
            self.status_bar.showMessage(f"Copied name: {name_text}", 2000)
        ))
        menu.exec(self.entity_tree.viewport().mapToGlobal(pos))

    def on_entity_tree_double_clicked(self, item, column):
        """Enhanced double-click handler that shows gizmo and centers view"""
        # Get the entity
        entity = item.data(0, Qt.ItemDataRole.UserRole)
        if not entity:
            return
        
        print(f" Double-clicked entity: {entity.name}")
        
        # Select the entity
        self.selected_entity = entity
        self.canvas.selected_entity = entity
        self.canvas.selected = [entity]
        
        # Update gizmos for double-clicked entity
        if hasattr(self.canvas, 'gizmo_renderer'):
            self.canvas.gizmo_renderer.update_gizmo_for_entity(entity)
        if hasattr(self.canvas, 'gizmo_3d'):
            self.canvas.gizmo_3d.move_to(entity)
        
        # Update UI
        self.update_ui_for_selected_entity(entity)
        
        # Center view on entity — reuse zoom_to_entity which handles both 2D and 3D correctly
        if hasattr(self, 'zoom_to_entity'):
            self.zoom_to_entity(entity)
        else:
            self.canvas.update()

        # Return keyboard focus to canvas so WASD / arrow keys work immediately
        self.canvas.setFocus()

        print(f"Double-click complete: Entity {entity.name} selected with gizmo visible")

    def zoom_to_entity(self, entity):
        """Zoom and center view on the specified entity - WORKS IN 2D AND 3D"""
        print(f"zoom_to_entity called for: {entity.name if entity else 'None'}")
        
        if not entity:
            print("No entity provided!")
            return
            
        print(f"Zooming to entity: {entity.name}")
        print(f"Entity position: ({entity.x:.1f}, {entity.y:.1f}, {entity.z:.1f})")
        print(f"Entity map: {entity.map_name}")
        print(f"Current map: {self.current_map.name if self.current_map else 'None'}")
        print(f"Current mode: {'2D' if self.canvas.mode == 0 else '3D'}")
            
        # Check if entity is in current map
        if self.current_map is not None and entity.map_name != self.current_map.name:
            print(f"Entity is in a different map, switching to {entity.map_name}")
            # First switch to the correct map
            for i in range(self.map_combo.count()):
                map_info = self.map_combo.itemData(i)
                if map_info and map_info.name == entity.map_name:
                    print(f"Found matching map at index {i}")
                    self.map_combo.setCurrentIndex(i)
                    break
            else:
                print("Could not find matching map in combo box")
        
        # Zoom based on current mode
        if self.canvas.mode == 0:  # 2D mode
            print("Using 2D zoom...")
            
            # Use canvas zoom method if available
            if hasattr(self.canvas, 'zoom_to_entity'):
                self.canvas.zoom_to_entity(entity)
            else:
                # Fallback: manual 2D positioning
                print("Using fallback 2D zoom")
                self.canvas.selected_entity = entity
                self.canvas.selected = [entity]
                
                # Center on entity
                self.canvas.offset_x = (self.canvas.width() / 2) - (entity.x * self.canvas.scale_factor)
                self.canvas.offset_y = (self.canvas.height() / 2) - (entity.y * self.canvas.scale_factor)
                
                # Set a reasonable zoom level
                self.canvas.scale_factor = max(self.canvas.scale_factor, 1.0)
                
                self.canvas.update()
                
            print(f"2D zoom complete: offset=({self.canvas.offset_x:.1f}, {self.canvas.offset_y:.1f}), "
                f"scale={self.canvas.scale_factor:.2f}")
            
        else:  # 3D mode
            print("Using 3D camera positioning...")

            import numpy as np

            camera_offset_distance = 100.0
            camera_height_offset = 50.0

            # Entities render at glTranslatef(entity.x, entity.z, -entity.y)
            # so the entity's OpenGL position is (entity.x, entity.z, -entity.y).
            # Place the camera offset in +OpenGL-Z from the entity so it sits
            # in the same quadrant and the default yaw (-90) points straight at it.
            entity_opengl_z = -entity.y
            camera_x = entity.x
            camera_y = entity.z + camera_height_offset
            camera_z = entity_opengl_z + camera_offset_distance

            self.canvas.camera_3d.position = np.array([camera_x, camera_y, camera_z], dtype=float)

            # Vector from camera to entity in OpenGL space
            dx = entity.x - camera_x                   # 0
            dz = entity_opengl_z - camera_z            # -camera_offset_distance
            dh = entity.z - camera_y                   # -camera_height_offset

            # yaw: arctan2(forward.z, forward.x) — same convention as update_vectors
            self.canvas.camera_3d.yaw = np.degrees(np.arctan2(dz, dx))

            horizontal_dist = np.sqrt(dx * dx + dz * dz)
            if horizontal_dist > 0:
                self.canvas.camera_3d.pitch = np.degrees(np.arctan2(dh, horizontal_dist))
            else:
                self.canvas.camera_3d.pitch = -20.0

            self.canvas.camera_3d.pitch = np.clip(self.canvas.camera_3d.pitch, -89, 89)
            self.canvas.camera_3d.update_vectors()
            self.canvas.update()

            print(f"3D camera positioned at ({camera_x:.0f}, {camera_y:.0f}, {camera_z:.0f})")
            print(f"Looking at entity: yaw={self.canvas.camera_3d.yaw:.1f} "
                f"pitch={self.canvas.camera_3d.pitch:.1f}")

            self.status_bar.showMessage(f"3D camera focused on {entity.name}")

    def _set_item_color_by_source(self, item, entity):
        """Set item text color based on entity source and type - SILENT VERSION"""
        # Define colors that EXACTLY match your legend
        legend_colors = {
            "Vehicle": QColor(52, 152, 255),     # Blue - Vehicles
            "NPC": QColor(46, 255, 113),         # Green - NPCs/Characters
            "Weapon": QColor(255, 76, 60),       # Red - Weapons/Explosives
            "Spawn": QColor(255, 156, 18),       # Orange - Spawn Locations
            "Mission": QColor(185, 89, 255),     # Purple - Mission Objects
            "Trigger": QColor(255, 230, 15),     # Yellow - Triggers/Zones
            "Prop": QColor(170, 180, 190),       # Gray - Props/Static Objects
            "Light": QColor(255, 255, 160),      # Light Yellow - Lights
            "Effect": QColor(0, 255, 200),       # Teal - Effects/Particles
            "WorldSectors": QColor(255, 100, 100), # Red - WorldSectors Objects
            "Unknown": QColor(130, 130, 130)     # Dark Gray - Unknown Type
        }
        
        # Determine entity type using the SAME logic as your canvas entity renderer
        entity_type = self._determine_entity_type_for_browser(entity)
        
        # Only use "WorldSectors" color as absolute fallback for truly unknown entities from worldsectors
        source_file_path = getattr(entity, 'source_file_path', None)
        source_file = getattr(entity, 'source_file', None)
        
        is_from_worldsectors = (source_file == 'worldsectors' or 
                            (source_file_path and 'worldsector' in source_file_path.lower()))
        
        # Only override to WorldSectors color if the entity type is Unknown AND it's from worldsectors
        if is_from_worldsectors and entity_type == "Unknown":
            entity_type = "WorldSectors"
        
        # Get the color for this entity type
        entity_color = legend_colors.get(entity_type, legend_colors["Unknown"])
        
        # Check if entity is selected
        is_selected = (entity == self.selected_entity or 
                    (hasattr(self.canvas, 'selected') and entity in self.canvas.selected))
        
        if is_selected:
            # SELECTED ENTITY STYLING
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            
            selected_bg = QColor(52, 152, 255, 120)  # Blue with opacity
            item.setBackground(0, selected_bg)
            item.setForeground(0, QColor(255, 255, 255))  # White text for selected
            
            # REMOVE/REDUCE: Only log occasionally
            if not hasattr(self, '_last_selection_log_time'):
                self._last_selection_log_time = 0
            
            current_time = time.time()
            if current_time - self._last_selection_log_time > 2.0:  # Only every 2 seconds
                print(f" Selected entity styling applied: {getattr(entity, 'name', 'unknown')}")
                self._last_selection_log_time = current_time
        else:
            # NON-SELECTED ENTITY STYLING
            font = item.font(0)
            font.setBold(False)
            item.setFont(0, font)
            
            item.setBackground(0, QColor(0, 0, 0, 0))  # Transparent background
            item.setForeground(0, entity_color)
        
    def _determine_entity_type_for_browser(self, entity):
        """Cached version to avoid repeated analysis"""
        entity_id = id(entity)
        
        # Check cache first
        if entity_id in self.tree_entity_type_cache:
            return self.tree_entity_type_cache[entity_id]
        
        # Calculate once and cache
        entity_type = self._calculate_entity_type(entity)
        self.tree_entity_type_cache[entity_id] = entity_type
        
        return entity_type

    def _calculate_entity_type(self, entity):
        """The actual calculation logic - SILENT VERSION"""
        entity_name = getattr(entity, 'name', '').lower()
        
        # Vehicle patterns (check first as they're most specific)
        vehicle_patterns = ['vehicle', 'car', 'truck', 'boat', 'ship', 'plane', 'helicopter', 
                        'bike', 'motorcycle', 'aircraft', 'transport', 'scorpion', 'samson']
        for pattern in vehicle_patterns:
            if pattern in entity_name:
                return "Vehicle"
        
        # NPC/Character patterns  
        npc_patterns = ['npc', 'character', 'ai_', 'enemy', 'friend', 'ally', 'neutral', 
                    'soldier', 'civilian', 'avatar', 'human', 'person']
        for pattern in npc_patterns:
            if pattern in entity_name:
                return "NPC"
        
        # Weapon patterns
        weapon_patterns = ['weapon', 'gun', 'rifle', 'pistol', 'sword', 'bomb', 'explosive', 
                        'grenade', 'missile', 'rocket', 'ammo', 'ammunition']
        for pattern in weapon_patterns:
            if pattern in entity_name:
                return "Weapon"
        
        # Spawn patterns
        spawn_patterns = ['spawn', 'start', 'respawn', 'checkpoint', 'playerstart', 
                        'spawnpoint', 'birth', 'entry']
        for pattern in spawn_patterns:
            if pattern in entity_name:
                return "Spawn"
        
        # Mission patterns
        mission_patterns = ['mission', 'objective', 'goal', 'target', 'quest', 'task', 
                        'pickup', 'collectible', 'artifact']
        for pattern in mission_patterns:
            if pattern in entity_name:
                return "Mission"
        
        # Trigger patterns
        trigger_patterns = ['trigger', 'zone', 'area', 'region', 'volume', 'detector', 
                        'sensor', 'activator', 'switch']
        for pattern in trigger_patterns:
            if pattern in entity_name:
                return "Trigger"
        
        # Light patterns
        light_patterns = ['light', 'lamp', 'torch', 'spotlight', 'illumination', 'glow', 
                        'bulb', 'lantern', 'beacon']
        for pattern in light_patterns:
            if pattern in entity_name:
                return "Light"
        
        # Effect patterns
        effect_patterns = ['fx_', 'effect', 'particle', 'vfx', 'smoke', 'fire', 'explosion',
                        'steam', 'dust', 'spark', 'emitter']
        for pattern in effect_patterns:
            if pattern in entity_name:
                return "Effect"
        
        # Prop patterns (check last as it's most generic)
        prop_patterns = ['prop_', 'object_', 'static_', 'decoration', 'furniture', 'building',
                        'structure', 'rock', 'tree', 'plant', 'debris']
        for pattern in prop_patterns:
            if pattern in entity_name:
                return "Prop"
        
        # Default to Unknown
        return "Unknown"

    def debug_entity_colors(self):
        """Debug method to check why entities are showing as red"""
        print(f"\nDEBUG: Entity Browser Colors")
        print(f"Total entities: {len(self.entities) if hasattr(self, 'entities') else 0}")
        
        if hasattr(self, 'entities') and self.entities:
            # Check first 5 entities
            for i, entity in enumerate(self.entities[:5]):
                entity_name = getattr(entity, 'name', 'unknown')
                source_file = getattr(entity, 'source_file', 'none')
                source_file_path = getattr(entity, 'source_file_path', 'none')
                
                print(f"\nEntity {i+1}: {entity_name}")
                print(f"  source_file: {source_file}")
                print(f"  source_file_path: {source_file_path}")
                
                # Test type detection
                entity_type = self._determine_entity_type_for_browser(entity)
                print(f"  detected_type: {entity_type}")
                
                # Check if it's being classified as WorldSectors
                is_worldsector = (source_file == 'worldsectors' or 
                                (source_file_path and 'worldsector' in source_file_path.lower()))
                print(f"  is_worldsector: {is_worldsector}")
                
                # Final type
                final_type = "WorldSectors" if is_worldsector else entity_type
                print(f"  final_type: {final_type}")

    def fix_red_entities_in_browser(self):
        """Quick fix method to refresh entity browser colors"""
        try:
            print("Fixing red entity highlighting in browser...")
            
            # Debug current state
            self.debug_entity_colors()
            
            # Force refresh the entity tree
            if hasattr(self, 'update_entity_tree'):
                self.update_entity_tree()
            
            print("Entity browser colors refreshed")
            
        except Exception as e:
            print(f"Error fixing entity colors: {e}")

    def update_entity_tree(self):
        """Update the entity tree with current entities and grouping, theme-aware"""
        self.entity_tree.clear()
        
        if not self.entities:
            return
        
        filter_text = self.entity_filter.text().lower()
        if getattr(self.canvas, 'unified_mode', False):
            self._populate_tree_by_sector(filter_text)
        else:
            self._populate_tree_by_source(filter_text)

        # Expand all group headers at every level
        def expand_all(item):
            item.setExpanded(True)
            for i in range(item.childCount()):
                expand_all(item.child(i))

        for i in range(self.entity_tree.topLevelItemCount()):
            expand_all(self.entity_tree.topLevelItem(i))

        # Keep mission layer tab in sync if it's currently visible
        if hasattr(self, 'browser_tabs') and self.browser_tabs.currentIndex() == 1:
            self.update_mission_layer_tree()

    def _populate_tree_by_type_enhanced(self, filter_text=""):
        type_groups = {}
        group_colors = {
            "Vehicle": QColor(52, 152, 255),
            "NPC": QColor(46, 255, 113),
            "Weapon": QColor(255, 76, 60),
            "Spawn": QColor(255, 156, 18),
            "Mission": QColor(185, 89, 255),
            "Trigger": QColor(255, 230, 15),
            "Prop": QColor(170, 180, 190),
            "Light": QColor(255, 255, 160),
            "Effect": QColor(0, 255, 200),
            "WorldSectors": QColor(255, 100, 100),
            "Landmarks": QColor(255, 180, 80),
            "Unknown": QColor(130, 130, 130)
        }

        for entity in self.entities:
            display_name = self._entity_display_name(entity)
            if filter_text and filter_text not in display_name.lower() and filter_text not in entity.id.lower():
                continue

            entity_type = self._determine_entity_type_for_browser(entity)
            source_file_path = getattr(entity, 'source_file_path', None)
            source_file = getattr(entity, 'source_file', None)
            bn = os.path.basename(source_file_path or '').lower()
            if bn.startswith('landmarkfar') or bn.startswith('landmarknear'):
                entity_type = "Landmarks"
            elif source_file == 'worldsectors' or (source_file_path and 'worldsector' in source_file_path.lower()):
                entity_type = "WorldSectors"

            # Create group header if it doesn't exist
            if entity_type not in type_groups:
                type_group = QTreeWidgetItem()
                type_group.setText(0, f"{entity_type} (0)")
                # Keep background color
                group_color = group_colors.get(entity_type, group_colors["Unknown"])
                bg_color = QColor(group_color)
                bg_color.setAlpha(80)
                type_group.setBackground(0, bg_color)

                # Use theme-aware text for header
                self._set_item_theme_color(type_group)

                # Bold font for group headers
                font = type_group.font(0)
                font.setBold(True)
                type_group.setFont(0, font)

                self.entity_tree.addTopLevelItem(type_group)
                type_groups[entity_type] = {'group': type_group, 'count': 0}

            # Add entity to group
            item = QTreeWidgetItem(type_groups[entity_type]['group'])
            item.setText(0, display_name)
            item.setText(1, entity.id)
            item.setText(2, f"({entity.x:.1f}, {entity.y:.1f}, {entity.z:.1f})")
            item.setText(3, self._get_entity_angles_text(entity))
            item.setData(0, Qt.ItemDataRole.UserRole, entity)

            # Theme-aware text color
            self._set_item_theme_color(item)

            type_groups[entity_type]['count'] += 1

        # Update group counts
        for entity_type, group_data in type_groups.items():
            count = group_data['count']
            group_data['group'].setText(0, f"{entity_type} ({count})")
            # Apply theme-aware color again after updating text
            self._set_item_theme_color(group_data['group'])

    def _entity_display_name(self, entity):
        """Return the best display name for an entity, falling back to tplCreatureType."""
        name = entity.name
        if (not name or name in ("Unnamed", "Unnamed Object")) and hasattr(entity, 'xml_element') and entity.xml_element is not None:
            name_f = entity.xml_element.find("./field[@name='hidName']")
            if name_f is not None:
                name = _get_str_val(name_f)
            if not name:
                ct_f = entity.xml_element.find("./field[@name='tplCreatureType']")
                if ct_f is not None:
                    name = _get_str_val(ct_f)
            if not name:
                name = "Unnamed"
        return name

    def _set_item_theme_color(self, item):
        """Set QTreeWidgetItem text color based on current theme"""
        color = QColor(255, 255, 255) if self.force_dark_theme else QColor(0, 0, 0)
        for col in range(item.columnCount()):
            item.setForeground(col, color)

    def create_color_legend_group(self):
        """Enhanced color legend with better organization"""
        legend_group = QGroupBox("Entity Type Color Legend")
        legend_layout = QVBoxLayout(legend_group)
        
        # Add header
        header_label = QLabel("Colors match entity browser and canvas:")
        header_label.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        legend_layout.addWidget(header_label)
        
        # Create color samples with labels (matching your existing legend)
        self.create_color_legend_item(legend_layout, QColor(52, 152, 255), "Blue - Vehicles")        
        self.create_color_legend_item(legend_layout, QColor(46, 255, 113), "Green - NPCs/Characters") 
        self.create_color_legend_item(legend_layout, QColor(255, 76, 60), "Red - Weapons/Explosives") 
        self.create_color_legend_item(legend_layout, QColor(255, 156, 18), "Orange - Spawn Locations") 
        self.create_color_legend_item(legend_layout, QColor(185, 89, 255), "Purple - Mission Objects") 
        self.create_color_legend_item(legend_layout, QColor(255, 230, 15), "Yellow - Triggers/Zones") 
        self.create_color_legend_item(legend_layout, QColor(170, 180, 190), "Gray - Props/Static Objects") 
        self.create_color_legend_item(legend_layout, QColor(255, 255, 160), "Light Yellow - Lights") 
        self.create_color_legend_item(legend_layout, QColor(0, 255, 200), "Teal - Effects/Particles") 
        self.create_color_legend_item(legend_layout, QColor(255, 100, 100), "Red - WorldSectors Objects") 
        self.create_color_legend_item(legend_layout, QColor(130, 130, 130), "Dark Gray - Unknown Type") 
        
    def _populate_tree_no_grouping(self, filter_text=""):
        for entity in self.entities:
            display_name = self._entity_display_name(entity)
            if filter_text and filter_text not in display_name.lower() and filter_text not in entity.id.lower():
                continue

            item = QTreeWidgetItem()
            item.setText(0, display_name)
            item.setText(1, entity.id)
            item.setText(2, f"({entity.x:.1f}, {entity.y:.1f}, {entity.z:.1f})")
            item.setData(0, Qt.ItemDataRole.UserRole, entity)
            
            # Set theme-aware text color
            self._set_item_theme_color(item)
            
            self.entity_tree.addTopLevelItem(item)

    def _populate_tree_by_map(self, filter_text=""):
        map_groups = {}
        
        no_map_group = QTreeWidgetItem()
        no_map_group.setText(0, "No Map")
        no_map_group.setBackground(0, QColor(200, 200, 200, 100))
        self.entity_tree.addTopLevelItem(no_map_group)
        
        for entity in self.entities:
            display_name = self._entity_display_name(entity)
            if filter_text and filter_text not in display_name.lower() and filter_text not in entity.id.lower():
                continue

            map_name = entity.map_name
            if not map_name:
                item = QTreeWidgetItem(no_map_group)
            else:
                if map_name not in map_groups:
                    map_group = QTreeWidgetItem()
                    map_group.setText(0, os.path.basename(map_name))
                    map_group.setBackground(0, QColor(220, 240, 255, 100))
                    self.entity_tree.addTopLevelItem(map_group)
                    map_groups[map_name] = map_group
                item = QTreeWidgetItem(map_groups[map_name])

            item.setText(0, display_name)
            item.setText(1, entity.id)
            item.setText(2, f"({entity.x:.1f}, {entity.y:.1f}, {entity.z:.1f})")
            item.setData(0, Qt.ItemDataRole.UserRole, entity)
            self._set_item_theme_color(item)
        
        if no_map_group.childCount() == 0:
            index = self.entity_tree.indexOfTopLevelItem(no_map_group)
            self.entity_tree.takeTopLevelItem(index)

    def _populate_tree_by_sector(self, filter_text=""):
        """Group entities by source_sector_id (unified mode) with layer as sub-header.
        Non-sector entities (omnis, managers, etc.) are grouped by their source_file name."""
        sector_groups = {}
        world_file_groups = {}  # source_file → QTreeWidgetItem

        for entity in self.entities:
            display_name = self._entity_display_name(entity)
            if filter_text and filter_text not in display_name.lower() and filter_text not in entity.id.lower():
                continue

            sid = getattr(entity, 'source_sector_id', -1)
            layer = getattr(entity, 'source_layer', 'main') or 'main'

            if sid < 0:
                # Group by source_file (omnis, managers, mapsdata, sectorsdep, unknown…)
                # Landmark files get their own per-file group (like sectors), not one big bucket.
                fp = getattr(entity, 'source_file_path', '') or ''
                bn = os.path.basename(fp).lower()
                if bn.startswith('landmarkfar') or bn.startswith('landmarknear'):
                    # Strip all extensions to get a clean display name
                    src = os.path.basename(fp).split('.')[0]
                else:
                    src = getattr(entity, 'source_file', None) or 'unknown'
                if src not in world_file_groups:
                    wg = QTreeWidgetItem()
                    wg.setText(0, src)
                    bg = QColor(255, 200, 120, 100) if (bn.startswith('landmarkfar') or bn.startswith('landmarknear')) else QColor(200, 200, 200, 100)
                    wg.setBackground(0, bg)
                    self.entity_tree.addTopLevelItem(wg)
                    world_file_groups[src] = wg
                parent = world_file_groups[src]
            else:
                gx = sid % 16
                gy = sid // 16
                sector_label = f"Sector {sid} ({gx},{gy})"
                if sid not in sector_groups:
                    sg = QTreeWidgetItem()
                    sg.setText(0, sector_label)
                    sg.setBackground(0, QColor(220, 240, 255, 100))
                    self.entity_tree.addTopLevelItem(sg)
                    sector_groups[sid] = {'_group': sg, '_layers': {}}
                sd = sector_groups[sid]
                if layer not in sd['_layers']:
                    lg = QTreeWidgetItem(sd['_group'])
                    lg.setText(0, layer)
                    lg.setBackground(0, QColor(230, 245, 230, 100))
                    sd['_layers'][layer] = lg
                parent = sd['_layers'][layer]

            item = QTreeWidgetItem(parent)
            item.setText(0, display_name)
            item.setText(1, entity.id)
            item.setText(2, f"({entity.x:.1f}, {entity.y:.1f}, {entity.z:.1f})")
            item.setData(0, Qt.ItemDataRole.UserRole, entity)
            self._set_item_theme_color(item)

    def _populate_tree_by_source(self, filter_text=""):
        source_groups = {}   # source_key -> {'group': QTreeWidgetItem, 'count': int}

        for entity in self.entities:
            display_name = self._entity_display_name(entity)
            if filter_text and filter_text not in display_name.lower() and filter_text not in entity.id.lower():
                continue

            source = getattr(entity, 'source_file', None) or 'unknown'
            fp = getattr(entity, 'source_file_path', '') or ''
            bn = os.path.basename(fp).lower()
            if bn.startswith('landmarkfar') or bn.startswith('landmarknear'):
                source = os.path.basename(fp).split('.')[0]

            if source not in source_groups:
                source_group = QTreeWidgetItem()
                source_group.setText(0, source)
                source_group.setBackground(0, QColor(220, 220, 220, 100))
                font = source_group.font(0)
                font.setBold(True)
                source_group.setFont(0, font)
                self._set_item_theme_color(source_group)
                self.entity_tree.addTopLevelItem(source_group)
                source_groups[source] = {'group': source_group, 'count': 0}

            item = QTreeWidgetItem(source_groups[source]['group'])
            item.setText(0, display_name)
            item.setText(1, entity.id)
            item.setText(2, f"({entity.x:.1f}, {entity.y:.1f}, {entity.z:.1f})")
            item.setText(3, self._get_entity_angles_text(entity))
            item.setData(0, Qt.ItemDataRole.UserRole, entity)
            self._set_item_theme_color(item)
            source_groups[source]['count'] += 1

        # Update group headers with counts
        for source, data in source_groups.items():
            data['group'].setText(0, f"{source} ({data['count']})")
            self._set_item_theme_color(data['group'])

    def _update_tree_selection(self):
        """Update tree selection to match canvas, without overriding theme colors"""
        if not hasattr(self, 'entity_tree'):
            return
        
        self.entity_tree.blockSignals(True)
        try:
            selected_entities = getattr(self.canvas, 'selected', [])
            self.entity_tree.clearSelection()
            self._refresh_all_item_colors()
            
            for i in range(self.entity_tree.topLevelItemCount()):
                top_item = self.entity_tree.topLevelItem(i)
                if top_item.childCount() > 0:
                    for j in range(top_item.childCount()):
                        child = top_item.child(j)
                        entity = child.data(0, Qt.ItemDataRole.UserRole)
                        if entity in selected_entities:
                            child.setSelected(True)
                else:
                    entity = top_item.data(0, Qt.ItemDataRole.UserRole)
                    if entity in selected_entities:
                        top_item.setSelected(True)
        finally:
            self.entity_tree.blockSignals(False)

    def _refresh_all_item_colors(self):
        """Refresh all tree items to theme colors only"""
        for i in range(self.entity_tree.topLevelItemCount()):
            top_item = self.entity_tree.topLevelItem(i)
            
            # If it's a group with children
            if top_item.childCount() > 0:
                for j in range(top_item.childCount()):
                    child = top_item.child(j)
                    self._set_item_theme_color(child)
            else:
                self._set_item_theme_color(top_item)

        # Force repaint so colors update immediately
        self.entity_tree.viewport().update()

    def on_entity_selected(self, entity):
        """Handle when an entity is selected - WORKS IN BOTH MODES - NOW SHOWS CHILDREN AND SEATED NPCs"""
        self.selected_entity = entity

        # Update 3D model preview — include children/seated NPCs via select_entity_with_children
        if entity and hasattr(self, 'canvas') and hasattr(self.canvas, 'select_entity_with_children'):
            group = self.canvas.select_entity_with_children(entity)
            self.canvas.selected_entity = entity
            # Preserve canvas.selected when this signal was fired by a Ctrl+click multi-select.
            # A Ctrl+click builds the full selection BEFORE emitting entitySelected, so if the
            # entity is already in canvas.selected and the selection is larger than this entity's
            # own group, the user intentionally built a multi-select — don't overwrite it.
            current = getattr(self.canvas, 'selected', [])
            entity_in_current = any(e is entity for e in current)
            if entity_in_current and len(current) > len(group):
                # Multi-select active — keep it, just update model preview with primary entity
                self.update_model_preview(entity)
            else:
                self.canvas.selected = group
                self.update_model_preview(group if len(group) > 1 else entity)
        else:
            self.update_model_preview(entity)
            if hasattr(self, 'canvas'):
                self.canvas.selected_entity = entity   # None clears it
                if not entity:
                    self.canvas.selected = []

        # Log selection
        if entity:
            print(f"Entity selected: {entity.name} (ID: {entity.id}) in {'2D' if self.canvas.mode == 0 else '3D'} mode")
            
            # Check for relationships and log them
            if hasattr(entity, 'xml_element') and entity.xml_element:
                # Check for Structure children
                children_obj = entity.xml_element.find(".//object[@name='Children']")
                if children_obj:
                    child_objects = children_obj.findall("object[@name='Child']")
                    if child_objects:
                        print(f"  🗗️ This Structure has {len(child_objects)} children:")
                        for child_obj in child_objects:
                            name_field = child_obj.find("field[@name='Name']")
                            if name_field:
                                child_name = name_field.get('value-String', 'unknown')
                                print(f"    - {child_name}")
                
                # Check for seated NPCs
                ai_component = entity.xml_element.find(".//object[@name='CFCXAIComponent']")
                if ai_component:
                    ai_object = ai_component.find(".//object[@name='AIObject']")
                    if ai_object:
                        # Build entity lookup for name resolution
                        entities_dict = {}
                        for ent in self.entities:
                            entities_dict[ent.id] = ent
                        
                        seated_npcs = []
                        for field in ai_object.findall("field"):
                            entity_id_ref = field.get('value-Hash64')
                            if entity_id_ref and entity_id_ref in entities_dict:
                                seated_entity = entities_dict[entity_id_ref]
                                if seated_entity.id != entity.id:  # Not self-reference
                                    seated_npcs.append(seated_entity.name)
                        
                        if seated_npcs:
                            print(f"  🚗 This Vehicle has {len(seated_npcs)} seated NPCs:")
                            for npc_name in seated_npcs:
                                print(f"    🪑 {npc_name}")
        else:
            print(f"Entity deselected in {'2D' if self.canvas.mode == 0 else '3D'} mode")
        
        # Update gizmo (2D mode only)
        if self.canvas.mode == 0:  # 2D mode
            if hasattr(self.canvas, 'gizmo_renderer') and entity:
                selected = getattr(self.canvas, 'selected', [])
                if len(selected) > 1:
                    # Multi-selection — centre the gizmo on the whole group
                    center = self.canvas.calculate_group_center(selected)
                    virtual_entity = type('VirtualEntity', (), {
                        'x': center[0],
                        'y': center[1],
                        'z': center[2],
                        'name': f'Group ({len(selected)} entities)'
                    })()
                    print(f"2D mode: Positioning gizmo at group center of {len(selected)} entities")
                    self.canvas.gizmo_renderer.update_gizmo_for_entity(virtual_entity)
                else:
                    print(f"2D mode: Updating gizmo for {entity.name}")
                    self.canvas.gizmo_renderer.update_gizmo_for_entity(entity)
            elif hasattr(self.canvas, 'gizmo_renderer'):
                # Hide gizmo when nothing is selected
                self.canvas.gizmo_renderer.hide_gizmo()
        else:  # 3D mode
            if hasattr(self.canvas, 'gizmo_renderer'):
                self.canvas.gizmo_renderer.hide_gizmo()

        # Always sync the 3D gizmo position regardless of current mode,
        # so it's already positioned when the user switches to 3D.
        if hasattr(self.canvas, 'gizmo_3d'):
            self.canvas.gizmo_3d.move_to(entity)

        # Sync "Add Angles" browser button visibility
        if hasattr(self, 'browser_add_angles_btn'):
            has_angles = (
                entity is not None and
                hasattr(entity, 'xml_element') and
                entity.xml_element is not None and
                entity.xml_element.find(".//field[@name='hidAngles']") is not None
            )
            self.browser_add_angles_btn.setVisible(entity is not None and not has_angles)

        # Update UI (works in both modes)
        self.update_ui_for_selected_entity(entity)

        # Update selection in entity tree
        self._update_tree_selection()

        # Push selection to the entity editor if it is open.
        # Canvas clicks reach it via the entitySelected signal; browser/other
        # selections call this method directly and need the explicit push.
        if hasattr(self, 'entity_editor') and self.entity_editor is not None:
            try:
                self.entity_editor.on_entity_selected(entity)
            except Exception:
                pass

        # Force canvas update
        self.canvas.update()

    def update_entity_tree_colors_only(self):
        """Update only the colors in the entity tree without rebuilding it"""
        try:
            if not hasattr(self, 'entity_tree'):
                return
                
            print("Updating entity tree colors, Please wait.")
            
            # Refresh all item colors
            self._refresh_all_item_colors()
            
            print("Entity tree colors updated")
            
        except Exception as e:
            print(f"Error updating entity tree colors: {e}")

    def force_refresh_entity_tree_colors(self):
        """Force refresh of all entity tree colors - useful after selection changes"""
        try:
            # This method can be called from external systems when selection changes
            self.update_entity_tree_colors_only()
            
            # Also update the tree selection highlighting
            self._update_tree_selection()
            
        except Exception as e:
            print(f"Error force refreshing entity tree colors: {e}")

    def filter_entities(self):
        """Filter entities in the tree based on search text"""
        self.update_entity_tree()
        if hasattr(self, 'browser_tabs') and self.browser_tabs.currentIndex() == 1:
            self.update_mission_layer_tree()

    def fix_xml_element_references(self):
        """Fix xml_element references to point to the actual tree elements"""
        print(f"\nFIXING: XML element references")
        
        if not hasattr(self, 'worldsectors_trees'):
            print(f"No worldsectors_trees found")
            return
        
        fixed_count = 0
        
        for entity in self.entities:
            if hasattr(entity, 'source_file_path') and entity.source_file_path:
                source_file = entity.source_file_path
                
                if source_file in self.worldsectors_trees:
                    tree = self.worldsectors_trees[source_file]
                    root = tree.getroot()
                    
                    # Find the entity in the tree (FCBConverter format)
                    for entity_elem in root.findall(".//object[@name='Entity']"):
                        name_field = entity_elem.find("./field[@name='hidName']")
                        if name_field is not None and _get_str_val(name_field) == entity.name:
                            entity.xml_element = entity_elem
                            fixed_count += 1
                            print(f"   Fixed reference for {entity.name}")
                            break
        
        print(f"Fixed {fixed_count} XML element references")

    def test_xml_save_after_fix(self, entity_name="Avatar.Scorpion_Pilotable_0"):
        """Test XML save after fixing references"""
        print(f"\nTEST: XML save after fixing references")
        
        # Step 1: Fix references
        self.fix_xml_element_references()
        
        # Step 2: Find entity
        target_entity = None
        for entity in self.entities:
            if entity.name == entity_name:
                target_entity = entity
                break
        
        if not target_entity:
            print(f"Entity not found")
            return
        
        # Step 3: Move entity
        original_y = target_entity.y
        test_y = 777.54321
        target_entity.y = test_y
        
        print(f"Moved entity Y: {original_y} -> {test_y}")
        
        # Step 4: Update XML using normal method
        xml_updated = self.canvas.update_entity_xml(target_entity)
        if xml_updated:
            self.canvas._auto_save_entity_changes(target_entity)
            print(f"Updated and saved XML")
        
        # Step 5: Verify save
        self._verify_position_sync_in_file(target_entity.source_file_path, entity_name)
        
        # Step 6: Restore
        target_entity.y = original_y
        self.canvas.update_entity_xml(target_entity)
        self.canvas._auto_save_entity_changes(target_entity)
        
        print(f"Restored position")
        print(f"Test complete")

    def clear_entity_selection(self):
        """Clear entity selection in the tree"""
        self.entity_tree.clearSelection()
        
        # Also clear canvas selection
        if hasattr(self.canvas, 'selected'):
            self.canvas.selected = []
        if hasattr(self.canvas, 'selected_entity'):
            self.canvas.selected_entity = None
        
        # Update canvas
        self.canvas.update()
        
        # Update UI
        self.update_ui_for_selected_entity(None)
        
    def on_objects_loaded(self, objects):
        """Handle when objects are loaded from the thread - SIMPLIFIED"""
        print(f"Received {len(objects)} objects from loading thread")
        
        # Store objects
        self.objects = objects
        
        # Convert ObjectEntity objects to Entity objects for display compatibility
        converted_entities = []
        for obj in objects:
            try:
                # Create Entity object from ObjectEntity
                entity = Entity(
                    id=obj.id,
                    name=obj.name,
                    x=obj.x,
                    y=obj.y,
                    z=obj.z,
                    xml_element=obj.xml_element
                )
                
                # Set the source file path for XML updates
                entity.source_file_path = obj.source_file
                
                # Set source file type
                source_filename = os.path.basename(obj.source_file) if obj.source_file else ""
                if source_filename.startswith('worldsector'):
                    entity.source_file = "worldsectors"
                elif source_filename.lower().startswith(('landmarkfar', 'landmarknear')):
                    entity.source_file = "landmark"

                entity.map_name = obj.map_name
                converted_entities.append(entity)
                
            except Exception as e:
                print(f"Error converting object {obj.name}: {e}")
        
        # Add converted entities to the main entities list
        self.entities.extend(converted_entities)
        print(f"Added {len(converted_entities)} converted entities. Total entities: {len(self.entities)}")
        
        # Update canvas with combined entities
        self.canvas.set_entities(self.entities, center_view=False)
        
        # Update entity browser
        if hasattr(self, 'update_entity_tree'):
            self.update_entity_tree()
        
        # Update statistics
        if hasattr(self, 'update_entity_statistics'):
            self.update_entity_statistics()
        
        # Force canvas update
        self.canvas.update()
        print("Canvas updated with worldsectors objects")

    def save_xml_files(self):
        """Save all XML files without converting to FCB - UPDATED VERSION"""
        try:
            # Find all XML files that need saving
            files_to_save = []
            
            # 1. Main XML files (if loaded)
            if hasattr(self, 'xml_tree') and self.xml_tree and hasattr(self, 'xml_file_path'):
                files_to_save.append({
                    'type': 'main',
                    'path': self.xml_file_path,
                    'tree': self.xml_tree,
                    'name': os.path.basename(self.xml_file_path)
                })
            
            # 2. Other main XML files
            main_files = {
                'omnis_tree': 'omnis',
                'managers_tree': 'managers', 
                'sectordep_tree': 'sectorsdep'
            }
            
            for tree_attr, file_type in main_files.items():
                if hasattr(self, tree_attr):
                    tree = getattr(self, tree_attr)
                    if tree is not None:
                        file_path = self._find_tree_file_path(file_type)
                        if file_path:
                            files_to_save.append({
                                'type': file_type,
                                'path': file_path,
                                'tree': tree,
                                'name': os.path.basename(file_path)
                            })
            
            # 3. WorldSector XML files (from the loaded trees)
            if hasattr(self, 'worldsectors_trees'):
                for xml_file_path, tree in self.worldsectors_trees.items():
                    if os.path.exists(xml_file_path):
                        files_to_save.append({
                            'type': 'worldsector',
                            'path': xml_file_path,
                            'tree': tree,
                            'name': os.path.basename(xml_file_path)
                        })
            
            if not files_to_save:
                QMessageBox.information(self, "No Files to Save", "No XML files are currently loaded.")
                return
            
            # Create progress dialog
            progress_dialog = QProgressDialog("Saving XML files, Please Wait.", "Cancel", 0, 100, self)
            progress_dialog.setWindowTitle("Saving XML Files")
            progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            progress_dialog.setMinimumDuration(0)
            progress_dialog.setValue(0)
            
            saved_files = []
            total_files = len(files_to_save)
            
            for i, file_info in enumerate(files_to_save):
                if progress_dialog.wasCanceled():
                    break
                    
                progress_dialog.setLabelText(f"Saving {file_info['name']}, Please Wait.")
                progress_dialog.setValue(int((i / total_files) * 100))
                QApplication.processEvents()
                
                try:
                    if file_info['type'] == 'worldsector':
                        # Use precision preservation for worldsector files
                        self.save_worldsector_xml_with_precision_preservation(file_info['tree'], file_info['path'])
                        saved_files.append(f"{file_info['name']} (precision preserved)")
                    else:
                        # Use precision preservation for main files too
                        self.save_xml_with_precision_preservation(file_info['tree'], file_info['path'])
                        saved_files.append(f"{file_info['name']}")
                    
                    print(f"Saved: {file_info['name']}")
                            
                except Exception as e:
                    saved_files.append(f" {file_info['name']} - Error: {str(e)}")
                    print(f" Failed to save {file_info['name']}: {e}")
            
            # Close progress dialog
            progress_dialog.setValue(100)
            progress_dialog.close()
            
            # Show results
            success_count = len([f for f in saved_files if f.startswith('')])
            error_count = len([f for f in saved_files if f.startswith('')])
            
            if error_count == 0:
                QMessageBox.information(
                    self,
                    "XML Files Saved",
                    f"Successfully saved {success_count} XML files with precision preservation!\n\n" + 
                    "\n".join(saved_files)
                )
            else:
                QMessageBox.warning(
                    self,
                    "XML Save Complete with Errors", 
                    f"Saved {success_count} files successfully, {error_count} files had errors:\n\n" + 
                    "\n".join(saved_files)
                )
            
            # Update status
            self.status_bar.showMessage(f"Saved {success_count} XML files with precision preservation")
            
        except Exception as e:
            if 'progress_dialog' in locals():
                progress_dialog.close()
            QMessageBox.critical(self, "Error", f"Failed to save XML files: {str(e)}")

    def check_loaded_files(self):
        """Debug method to check what files are currently loaded"""
        print(f"\nLOADED FILES CHECK:")
        
        # Check main XML files
        print(f"Main XML files:")
        if hasattr(self, 'xml_tree') and self.xml_tree and hasattr(self, 'xml_file_path'):
            print(f"  Main: {os.path.basename(self.xml_file_path)}")
        else:
            print(f"  Main: Not loaded")
        
        # Check other main files
        main_files = ['omnis_tree', 'managers_tree', 'sectordep_tree']
        for tree_attr in main_files:
            if hasattr(self, tree_attr) and getattr(self, tree_attr) is not None:
                print(f"  {tree_attr}: Loaded")
            else:
                print(f"  {tree_attr}: Not loaded")
        
        # Check WorldSector files
        worldsector_files = set()
        for entity in self.entities:
            if hasattr(entity, 'source_file_path') and entity.source_file_path:
                if entity.source_file_path.endswith('.data.xml'):
                    worldsector_files.add(entity.source_file_path)
        
        print(f"WorldSector XML files:")
        if worldsector_files:
            for xml_file in worldsector_files:
                exists = "" if os.path.exists(xml_file) else ""
                print(f"  {exists} {os.path.basename(xml_file)}")
        else:
            print(f"  No WorldSector files found")
        
        print(f"Total entities: {len(self.entities)}")
        print(f"Total objects: {len(getattr(self, 'objects', []))}")

    def verify_worldsector_save(self, entity_name):
        """Verify that the entity coordinates were actually saved to the file"""
        print(f"\nVERIFY: Checking if {entity_name} coordinates were saved")
        
        # Find the entity
        target_entity = None
        for entity in self.entities:
            if entity.name == entity_name:
                target_entity = entity
                break
        
        if not target_entity:
            print(f"   Entity {entity_name} not found")
            return
        
        if not hasattr(target_entity, 'source_file_path'):
            print(f"   Entity has no source_file_path")
            return
        
        source_file = target_entity.source_file_path
        print(f"   Source file: {os.path.basename(source_file)}")
        print(f"   Current entity position: ({target_entity.x:.3f}, {target_entity.y:.3f}, {target_entity.z:.3f})")
        
        # Read the file fresh from disk
        try:
            import xml.etree.ElementTree as ET
            fresh_tree = ET.parse(source_file)
            root = fresh_tree.getroot()
            
            # Find the entity in the file (FCBConverter format)
            for entity_elem in root.findall(".//object[@name='Entity']"):
                name_field = entity_elem.find("./field[@name='hidName']")
                if name_field is not None and _get_str_val(name_field) == entity_name:
                    print(f"   Found entity in saved file")

                    pos_field = entity_elem.find("./field[@name='hidPos']")
                    if pos_field is not None:
                        pos_value = pos_field.get('value-Vector3', '')
                        if pos_value:
                            try:
                                coords = pos_value.split(',')
                                if len(coords) == 3:
                                    file_pos = (float(coords[0]), float(coords[1]), float(coords[2]))
                                    entity_pos = (target_entity.x, target_entity.y, target_entity.z)
                                    print(f"   hidPos in file: ({file_pos[0]:.3f}, {file_pos[1]:.3f}, {file_pos[2]:.3f})")
                                    print(f"   Entity position: ({entity_pos[0]:.3f}, {entity_pos[1]:.3f}, {entity_pos[2]:.3f})")
                                    tolerance = 0.001
                                    if all(abs(file_pos[i] - entity_pos[i]) < tolerance for i in range(3)):
                                        print(f"   Coordinates match! Save was successful.")
                                    else:
                                        print(f"   Coordinates don't match! Save failed.")
                            except (ValueError, IndexError):
                                pass
                    break
            else:
                print(f"   Entity not found in saved file")
                
        except Exception as e:
            print(f"   Error reading saved file: {e}")

    def save_objects(self):
        """Save objects back to FCB format"""
        if not self.objects or not self.worldsectors_path:
            QMessageBox.warning(self, "No Objects", "No objects loaded to save.")
            return
        
        reply = QMessageBox.question(
            self,
            "Save Objects",
            f"Convert {len(self.objects)} objects back to FCB format?\n\n"
            f"This will:\n"
            f"Save XML files with current object positions\n"
            f"Convert XML files back to FCB format\n"
            f"Remove temporary XML files\n\n"
            f"Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        try:
            # First, save any modified XML files
            self._save_modified_object_xml_files()
            
            # Create progress dialog
            progress_dialog = QProgressDialog("Saving objects, Please Wait.", "Cancel", 0, 100, self)
            progress_dialog.setWindowTitle("Saving Objects")
            progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            progress_dialog.setMinimumDuration(0)
            progress_dialog.setValue(0)
            
            # Convert XML back to FCB
            def progress_callback(progress):
                progress_dialog.setValue(int(progress * 100))
                QApplication.processEvents()
            
            success_count, error_count, errors = self.file_converter.convert_worldsectors_back_to_fcb(
                self.worldsectors_path,
                progress_callback=progress_callback
            )
            
            progress_dialog.close()
            
            if error_count > 0:
                error_msg = "\n".join(errors[:5])
                if len(errors) > 5:
                    error_msg += f"\n... and {len(errors) - 5} more errors"
                
                QMessageBox.warning(
                    self,
                    "Save Completed with Errors",
                    f"Saved {success_count} files successfully.\n"
                    f"{error_count} files had errors:\n\n{error_msg}"
                )
            else:
                QMessageBox.information(
                    self,
                    "Objects Saved Successfully",
                    f"Successfully saved {success_count} object files!"
                )
            
            # Reset modification flag
            self.objects_modified = False
            
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save objects: {str(e)}")

    def _save_modified_object_xml_files(self):
        """Save modified object XML files before conversion"""
        modified_files = set()
        
        # Update XML elements with current object positions
        for obj in self.objects:
            if hasattr(obj, 'xml_element') and obj.xml_element is not None:
                # Update position in XML
                self._update_object_xml_position(obj)
                
                # Track which file this object belongs to
                if obj.source_file:
                    modified_files.add(obj.source_file)
        
        # Save each modified XML file
        for xml_file_path in modified_files:
            try:
                # Find the tree for this file
                tree = None
                for obj in self.objects:
                    if obj.source_file == xml_file_path and hasattr(obj, 'xml_element'):
                        # Create tree from the root element
                        root = obj.xml_element
                        while root.getparent() is not None:
                            root = root.getparent()
                        tree = ET.ElementTree(root)
                        break
                
                if tree:
                    tree.write(xml_file_path, encoding='utf-8', xml_declaration=True)
                    print(f"Saved modified object XML: {xml_file_path}")
                    
            except Exception as e:
                print(f"Error saving object XML {xml_file_path}: {str(e)}")

    def toggle_objects(self):
        """Toggle object visibility - ENHANCED VERSION"""
        if not hasattr(self, 'show_objects'):
            self.show_objects = True
        
        self.show_objects = not self.show_objects
        
        # Update the entities list shown in canvas
        if self.show_objects:
            # Show both entities and converted objects
            all_items = self.entities.copy()  # This should already include converted worldsectors objects
        else:
            # Show only non-worldsectors entities
            all_items = [entity for entity in self.entities if getattr(entity, 'source_file', None) != 'worldsectors']
        
        self.canvas.set_entities(all_items, center_view=False)
        self.canvas.update()

        visibility = "visible" if self.show_objects else "hidden"
        self.status_bar.showMessage(f"WorldSectors objects visibility: {visibility}")
        print(f"Objects visibility toggled: {visibility}, showing {len(all_items)} entities")
    
    def _update_object_xml_position(self, obj):
        """Update the XML element with the current object position"""
        if not hasattr(obj, 'xml_element') or obj.xml_element is None:
            return False
        
        try:
            import struct
            
            # Find hidPos field
            pos_field = obj.xml_element.find(".//field[@name='hidPos']")
            if pos_field is not None:
                # Update the value-Vector3 attribute
                pos_field.set('value-Vector3', f"{obj.x},{obj.y},{obj.z}")
                
                # Update the BinHex data
                pos_bytes = struct.pack('<fff', obj.x, obj.y, obj.z)
                pos_field.set('type', 'BinHex')
                pos_field.text = pos_bytes.hex().upper()
            
            # Also update hidPos_precise if it exists
            pos_precise_field = obj.xml_element.find(".//field[@name='hidPos_precise']")
            if pos_precise_field is not None:
                # Update the value-Vector3 attribute
                pos_precise_field.set('value-Vector3', f"{obj.x},{obj.y},{obj.z}")
                
                # Update the BinHex data
                pos_bytes = struct.pack('<fff', obj.x, obj.y, obj.z)
                pos_precise_field.set('type', 'BinHex')
                pos_precise_field.text = pos_bytes.hex().upper()
            
            return True
            
        except Exception as e:
            print(f"Error updating object XML position: {e}")
            return False
    
    def setup_conversion_tools(self):
        """Setup the file conversion tools (internal use only)"""
        import sys
        
        # Get correct tools directory for exe vs script
        if getattr(sys, 'frozen', False):
            # Running as exe - use executable directory
            base_dir = os.path.dirname(sys.executable)
        else:
            # Running as script - use script directory  
            base_dir = os.path.dirname(os.path.abspath(__file__))
        
        tools_dir = os.path.join(base_dir, "tools")
        
        if not os.path.exists(tools_dir):
            os.makedirs(tools_dir)
        
        # Check for FCBConverter
        fcb_converter_path = os.path.join(tools_dir, "FCBConverter.exe")
        if not os.path.exists(fcb_converter_path):
            fcb_converter_path = os.path.join(tools_dir, "fcbconverter.exe")
        if not os.path.exists(fcb_converter_path):
            print(f"WARNING: FCBConverter.exe not found in {tools_dir}")
            print(f"File conversion will not be available.")
        
        # Initialize the file converter with error handling
        try:
            print(f"Initializing FileConverter with tools_dir: {tools_dir}")
            self.file_converter = FileConverter(tools_dir, game_mode=self.game_mode)
            print("File converter initialized successfully")
        except Exception as e:
            print(f"Error initializing FileConverter: {e}")
            import traceback
            traceback.print_exc()
            self.file_converter = None
            raise  # Re-raise to trigger the fallback in __init__
        
        return self.file_converter is not None and self.file_converter.can_convert_fcb

    def find_worldsectors_folder_enhanced(self, base_folder):
        """
        Enhanced search for worldsectors folder and files
        
        Args:
            base_folder: Base folder to search in
            
        Returns:
            Dict with worldsectors path and file counts
        """
        print(f"Searching for worldsectors in: {base_folder}")
        
        # Common worldsectors folder names
        worldsectors_folder_names = [
            "worldsectors",
            "Worldsectors", 
            "WorldSectors",
            "worldsector",
            "sectors"
        ]
        
        # Search for worldsectors folders
        worldsectors_paths = []
        
        # 1. Check direct subfolders
        for folder_name in worldsectors_folder_names:
            potential_path = os.path.join(base_folder, folder_name)
            if os.path.exists(potential_path) and os.path.isdir(potential_path):
                worldsectors_paths.append(potential_path)
                print(f"  Found worldsectors folder: {folder_name}")
        
        # 2. Search in subfolders (up to 2 levels deep)
        for root, dirs, files in os.walk(base_folder):
            # Limit depth
            depth = len(os.path.relpath(root, base_folder).split(os.sep))
            if depth > 2:
                continue
            
            for dir_name in dirs:
                if dir_name.lower() in [name.lower() for name in worldsectors_folder_names]:
                    potential_path = os.path.join(root, dir_name)
                    if potential_path not in worldsectors_paths:
                        worldsectors_paths.append(potential_path)
                        relative_path = os.path.relpath(potential_path, base_folder)
                        print(f"  Found worldsectors folder: {relative_path}")
        
        # 3. If no worldsectors folder found, check if base folder contains .data.fcb files
        if not worldsectors_paths:
            fcb_files = glob.glob(os.path.join(base_folder, "*.data.fcb"))
            converted_files = glob.glob(os.path.join(base_folder, "*.converted.xml"))
            
            if fcb_files or converted_files:
                worldsectors_paths.append(base_folder)
                print(f"  Base folder contains worldsector files ({len(fcb_files)} .fcb, {len(converted_files)} .converted.xml)")
        
        if not worldsectors_paths:
            return None
        
        # Choose the best worldsectors folder (prefer one with most files)
        best_path = None
        best_score = 0
        
        for ws_path in worldsectors_paths:
            fcb_count = len(glob.glob(os.path.join(ws_path, "*.data.fcb")))
            xml_count = len(glob.glob(os.path.join(ws_path, "*.converted.xml")))
            data_xml_count = len(glob.glob(os.path.join(ws_path, "*.data.xml")))
            
            score = fcb_count * 2 + xml_count + data_xml_count  # Prefer FCB files
            
            print(f"  {os.path.relpath(ws_path, base_folder)}: {fcb_count} .fcb, {xml_count} .converted.xml, {data_xml_count} .data.xml (score: {score})")
            
            if score > best_score:
                best_score = score
                best_path = ws_path
        
        if best_path:
            return {
                "path": best_path,
                "fcb_files": len(glob.glob(os.path.join(best_path, "*.data.fcb"))),
                "xml_files": len(glob.glob(os.path.join(best_path, "*.converted.xml"))),
                "data_xml_files": len(glob.glob(os.path.join(best_path, "*.data.xml"))),
                "relative_path": os.path.relpath(best_path, base_folder)
            }
        
        return None

    def find_files_in_subfolders(self, base_folder, patterns, max_depth=3):
        """
        Search for files matching patterns in base folder and subfolders
        
        Args:
            base_folder: Root folder to search
            patterns: List of file patterns to match (e.g., ['*.xml', '*.fcb'])
            max_depth: Maximum depth to search (default 3)
        
        Returns:
            Dict of {pattern: [matching_files]}
        """
        found_files = {pattern: [] for pattern in patterns}
        
        def search_folder(folder_path, current_depth):
            if current_depth > max_depth:
                return
            
            try:
                # Search current folder
                for pattern in patterns:
                    matches = glob.glob(os.path.join(folder_path, pattern))
                    found_files[pattern].extend(matches)
                
                # Search subfolders
                if current_depth < max_depth:
                    for item in os.listdir(folder_path):
                        item_path = os.path.join(folder_path, item)
                        if os.path.isdir(item_path):
                            search_folder(item_path, current_depth + 1)
            except PermissionError:
                # Skip folders we can't access
                pass
            except Exception as e:
                print(f"Error searching {folder_path}: {e}")
        
        search_folder(base_folder, 0)
        return found_files
        
    def find_xml_files_enhanced(self, folder_path):
        """Enhanced XML file finder that searches subfolders - FIXED VERSION"""
        print(f"Enhanced search in: {folder_path}")
        
        # Search patterns for main files
        main_patterns = [
            "*.mapsdata.fcb", "*.mapsdata.xml",
            "*.managers.fcb", "*.managers.xml", 
            "*.omnis.fcb", "*.omnis.xml",
            "*.sectorsdep.fcb", "*.sectorsdep.xml",
            "mapsdata.fcb", "mapsdata.xml",
            "managers.fcb", "managers.xml",
            "omnis.fcb", "omnis.xml", 
            "sectorsdep.fcb", "sectorsdep.xml"
        ]

        # Search for files
        search_results = self.find_files_in_subfolders(folder_path, main_patterns)
        
        # Organize results by file type
        found_files = {}
        
        # Find mapsdata file first to get level name
        level_name = None
        mapsdata_files = []
        
        for pattern in ["*.mapsdata.fcb", "*.mapsdata.xml", "mapsdata.fcb", "mapsdata.xml"]:
            mapsdata_files.extend(search_results[pattern])
        
        if mapsdata_files:
            main_file = mapsdata_files[0]
            filename = os.path.basename(main_file)
            if '.mapsdata.' in filename:
                level_name = filename.split('.mapsdata.')[0]
            print(f"Level name detected: {level_name}")
            
            # Convert FCB to XML if needed
            if main_file.endswith('.fcb'):
                xml_file = main_file.replace('.fcb', '.xml')
                try:
                    success = self.file_converter.convert_fcb_to_xml(main_file)
                    if success and os.path.exists(xml_file):
                        found_files["mapsdata"] = {
                            "path": xml_file,
                            "description": "Map Data",
                            "original_fcb": main_file,
                            "location": os.path.relpath(os.path.dirname(xml_file), folder_path)
                        }
                except Exception as e:
                    print(f"Error converting {main_file}: {e}")
            else:
                found_files["mapsdata"] = {
                    "path": main_file,
                    "description": "Map Data", 
                    "original_fcb": None,
                    "location": os.path.relpath(os.path.dirname(main_file), folder_path)
                }
        
        # Find other files using the same logic
        file_types = {
            "omnis": {
                "patterns": [f"{level_name}.omnis.fcb", f"{level_name}.omnis.xml", ".omnis.fcb", ".omnis.xml"] if level_name else [".omnis.fcb", ".omnis.xml"],
                "description": "Omnis Data"
            },
            "managers": {
                "patterns": [f"{level_name}.managers.fcb", f"{level_name}.managers.xml", ".managers.fcb", ".managers.xml"] if level_name else [".managers.fcb", ".managers.xml"],
                "description": "Managers Data"
            },
            "sectorsdep": {
                "patterns": [f"{level_name}.sectorsdep.fcb", f"{level_name}.sectorsdep.xml", "sectorsdep.fcb", "sectorsdep.xml"] if level_name else ["sectorsdep.fcb", "sectorsdep.xml"],
                "description": "Sector Dependencies"
            }
        }

        for file_type, info in file_types.items():
            for pattern in info["patterns"]:
                # Collect all files from search results whose basename ends with the pattern
                matching_files = []
                for file_list in search_results.values():
                    for f in file_list:
                        if os.path.basename(f).endswith(pattern) or os.path.basename(f) == pattern:
                            matching_files.append(f)

                if matching_files:
                    file_path = matching_files[0]

                    # Standard handling for all files using FCBConverter
                    if file_path.endswith('.fcb'):
                        xml_file = file_path.replace('.fcb', '.xml')
                        try:
                            success = self.file_converter.convert_fcb_to_xml(file_path)
                            if success and os.path.exists(xml_file):
                                found_files[file_type] = {
                                    "path": xml_file,
                                    "description": info["description"],
                                    "original_fcb": file_path,
                                    "location": os.path.relpath(os.path.dirname(xml_file), folder_path)
                                }
                            break
                        except Exception as e:
                            print(f"Error converting {file_path}: {e}")
                            continue
                    else:
                        # Already XML - use directly
                        found_files[file_type] = {
                            "path": file_path,
                            "description": info["description"],
                            "original_fcb": None,
                            "location": os.path.relpath(os.path.dirname(file_path), folder_path)
                        }
                    break

        return found_files

    def open_entity_editor(self):
            """Open or show the entity editor window - FIXED IMPORT"""
            
            # Try multiple import methods
            EntityEditorWindow = None
            
            # Method 1: Try direct import
            try:
                from entity_editor import EntityEditorWindow
                print("Successfully imported EntityEditorWindow from entity_editor.py")
            except ImportError as e1:
                print(f"Failed direct import: {e1}")
                
                # Method 2: Try importing from current directory
                try:
                    import sys
                    import os
                    current_dir = os.path.dirname(__file__)
                    if current_dir not in sys.path:
                        sys.path.insert(0, current_dir)
                    from entity_editor import EntityEditorWindow
                    print("Successfully imported EntityEditorWindow from current directory")
                except ImportError as e2:
                    print(f"Failed current directory import: {e2}")
                    
                    # Method 3: Try to find the file and give helpful error
                    try:
                        import os
                        current_dir = os.path.dirname(__file__) if hasattr(self, '__file__') else os.getcwd()
                        entity_editor_path = os.path.join(current_dir, "entity_editor.py")
                        
                        if os.path.exists(entity_editor_path):
                            error_msg = f"Entity editor file exists at {entity_editor_path} but import failed.\nError: {e2}"
                        else:
                            # Look for the file in nearby directories
                            found_files = []
                            for root, dirs, files in os.walk(current_dir):
                                if "entity_editor.py" in files:
                                    found_files.append(os.path.join(root, "entity_editor.py"))
                            
                            if found_files:
                                error_msg = f"Entity editor file found at:\n" + "\n".join(found_files[:3])
                                error_msg += f"\n\nMove one of these files to: {current_dir}"
                            else:
                                error_msg = f"Entity editor file not found!\n\nCurrent directory: {current_dir}\nExpected file: {entity_editor_path}\n\nPlease create entity_editor.py in the same directory as your main application."
                        
                        from PyQt6.QtWidgets import QMessageBox
                        QMessageBox.critical(self, "Entity Editor Import Error", error_msg)
                        return
                        
                    except Exception as e3:
                        from PyQt6.QtWidgets import QMessageBox
                        QMessageBox.critical(self, "Entity Editor Error", 
                                        f"Could not import Entity Editor:\n{e1}\n\nAlso failed to diagnose the problem:\n{e3}")
                        return
            
            # If we get here, import was successful
            if EntityEditorWindow is None:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "Error", "EntityEditorWindow class not found after import!")
                return
            
            # Create editor if it doesn't exist
            if not hasattr(self, 'entity_editor') or self.entity_editor is None:
                try:
                    print("=== Creating new Entity Editor window ===")
                    self.entity_editor = EntityEditorWindow(self, self.canvas)
                    print("Successfully created EntityEditorWindow instance")
                    
                    # Set current entity if one is selected
                    if hasattr(self.canvas, 'selected') and self.canvas.selected:
                        entity = self.canvas.selected[0]
                        print(f"Entity Editor: Opening with entity '{entity.name}' (ID: {entity.id})")
                        self.entity_editor.set_entity(entity)
                    elif hasattr(self.canvas, 'selected_entity') and self.canvas.selected_entity:
                        entity = self.canvas.selected_entity
                        print(f"Entity Editor: Opening with entity '{entity.name}' (ID: {entity.id})")
                        self.entity_editor.set_entity(entity)
                    else:
                        print("Entity Editor: No entity currently selected")
                        
                except Exception as e:
                    from PyQt6.QtWidgets import QMessageBox
                    import traceback
                    error_details = traceback.format_exc()
                    QMessageBox.critical(self, "Entity Editor Creation Error", 
                                    f"Failed to create Entity Editor:\n{str(e)}\n\nDetails:\n{error_details}")
                    print(f"Entity Editor creation failed: {e}")
                    print(f"Full traceback:\n{error_details}")
                    return
            else:
                # Editor already exists, just update the entity
                print("=== Entity Editor window already exists ===")
                if hasattr(self.canvas, 'selected') and self.canvas.selected:
                    entity = self.canvas.selected[0]
                    print(f"Entity Editor: Updating to entity '{entity.name}' (ID: {entity.id})")
                    self.entity_editor.set_entity(entity)
                elif hasattr(self.canvas, 'selected_entity') and self.canvas.selected_entity:
                    entity = self.canvas.selected_entity
                    print(f"Entity Editor: Updating to entity '{entity.name}' (ID: {entity.id})")
                    self.entity_editor.set_entity(entity)
                else:
                    print("Entity Editor: No entity currently selected to update")
            
            # Show and raise the window
            try:
                self.entity_editor.show()
                self.entity_editor.raise_()
                self.entity_editor.activateWindow()
                if hasattr(self, 'current_entity') or (hasattr(self.canvas, 'selected') and self.canvas.selected):
                    entity_name = self.canvas.selected[0].name if (hasattr(self.canvas, 'selected') and self.canvas.selected) else "Unknown"
                    print(f"Entity Editor window opened successfully with '{entity_name}'")
                else:
                    print("Entity Editor window opened successfully (no entity loaded)")
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "Error", f"Failed to show Entity Editor window:\n{str(e)}")
                print(f"Failed to show Entity Editor: {e}")

    def toggle_grid(self):
        """Toggle grid visibility"""
        self.canvas.show_grid = not self.canvas.show_grid
        self.canvas.update()

        visibility = "visible" if self.canvas.show_grid else "hidden"
        self.status_bar.showMessage(f"Grid visibility: {visibility}")

    def toggle_entities(self):
        """Toggle entities visibility"""
        self.canvas.show_entities = not self.canvas.show_entities
        self.canvas.update()
        visibility = "visible" if self.canvas.show_entities else "hidden"
        self.status_bar.showMessage(f"Entities visibility: {visibility}")

    def _set_entity_source_visibility(self, source, visible):
        """Show/hide entities from a specific source file."""
        flag_map = {
            'worldsectors': 'show_worldsector_entities',
            'mapsdata':     'show_mapsdata_entities',
            'omnis':        'show_omnis_entities',
            'landmark':     'show_landmark_entities',
        }
        flag = flag_map.get(source)
        if flag:
            setattr(self.canvas, flag, visible)
            self.canvas.invalidate_position_cache()
            self.canvas.update()
            self.status_bar.showMessage(f"{source} entities: {'visible' if visible else 'hidden'}")

    def _set_trigger_zones_visibility(self, visible):
        """Show/hide trigger volume wireframes."""
        self.canvas.show_trigger_zones = visible
        self.canvas.update()
        self.status_bar.showMessage(f"Trigger zones: {'visible' if visible else 'hidden'}")
    
    def _on_light_angle_changed(self, angle):
        if hasattr(self, 'canvas'):
            self.canvas.set_light_elevation(angle)

    def toggle_theme(self):
        """Toggle between light and dark theme and save preference"""
        self.force_dark_theme = not self.force_dark_theme
        
        # Save the preference
        self.theme_settings.set_dark_theme(self.force_dark_theme)
        
        # Apply the theme
        self.apply_theme()
        
        # Update button text
        if self.force_dark_theme:
            self.theme_toggle_action.setText("Dark Mode")
            self.status_bar.showMessage("Dark theme enabled and saved")
        else:
            self.theme_toggle_action.setText("Light Mode")
            self.status_bar.showMessage("Light theme enabled and saved")
        
        # Force the entity tree to update colors immediately
        if hasattr(self, 'entity_tree'):
            self.force_refresh_entity_tree_colors()

    def apply_theme(self):
        """Apply the selected theme to the application"""
        if self.force_dark_theme:
            # Dark theme stylesheet
            dark_style = """
                QWidget {
                    background-color: #2b2b2b;
                    color: #ffffff;
                }
                QGroupBox {
                    background-color: #353535;
                    border: 1px solid #555555;
                    border-radius: 5px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: #ffffff;
                }
                QGroupBox::title {
                    color: #ffffff;
                    subcontrol-origin: margin;
                    subcontrol-position: top left;
                    padding: 2px 5px;
                }
                QPushButton {
                    background-color: #404040;
                    color: #ffffff;
                    border: 1px solid #555555;
                    border-radius: 3px;
                    padding: 5px;
                }
                QPushButton:hover {
                    background-color: #4a4a4a;
                }
                QPushButton:pressed {
                    background-color: #353535;
                }
                QPushButton:checked {
                    background-color: #0078d7;       /* Same blue as light mode */
                    border: 1px solid #005a9e;
                    color: #ffffff;
                }
                QPushButton:checked:hover {
                    background-color: #1e88e5;
                }
                QLabel {
                    color: #ffffff;
                    background-color: transparent;
                }
                QLineEdit {
                    background-color: #353535;
                    color: #ffffff;
                    border: 1px solid #555555;
                    border-radius: 3px;
                    padding: 2px;
                }
                QComboBox {
                    background-color: #353535;
                    color: #ffffff;
                    border: 1px solid #555555;
                    border-radius: 3px;
                    padding: 2px;
                }
                QComboBox::drop-down {
                    border: none;
                }
                QComboBox::down-arrow {
                    image: none;
                    border-left: 5px solid transparent;
                    border-right: 5px solid transparent;
                    border-top: 5px solid #ffffff;
                }
                QComboBox QAbstractItemView {
                    background-color: #353535;
                    color: #ffffff;
                    selection-background-color: #404040;
                }
                QTreeWidget {
                    background-color: #2b2b2b;
                    color: #ffffff;
                    border: 1px solid #555555;
                }
                QTreeWidget::item:selected {
                    background-color: #404040;
                    color: #ffffff;
                }
                QTextEdit {
                    background-color: #2b2b2b;
                    color: #ffffff;
                    border: 1px solid #555555;
                }
                QScrollBar:vertical {
                    background-color: #2b2b2b;
                    width: 12px;
                }
                QScrollBar::handle:vertical {
                    background-color: #555555;
                    border-radius: 6px;
                }
                QScrollBar:horizontal {
                    background-color: #2b2b2b;
                    height: 12px;
                }
                QScrollBar::handle:horizontal {
                    background-color: #555555;
                    border-radius: 6px;
                }
                QMenuBar {
                    background-color: #2b2b2b;
                    color: #ffffff;
                }
                QMenuBar::item:selected {
                    background-color: #404040;
                }
                QMenu {
                    background-color: #2b2b2b;
                    color: #ffffff;
                    border: 1px solid #555555;
                }
                QMenu::item:selected {
                    background-color: #404040;
                }
                QStatusBar {
                    background-color: #2b2b2b;
                    color: #ffffff;
                }
                QDockWidget {
                    color: #ffffff;
                }
                QDockWidget::title {
                    background-color: #353535;
                    color: #ffffff;
                    padding: 4px;
                }
                QToolBar {
                    background-color: #2b2b2b;
                    border: 1px solid #555555;
                }
                QToolBar QToolButton {
                    color: #ffffff;
                    background-color: transparent;
                }
                QToolBar QToolButton:hover {
                    background-color: #404040;
                }
                QToolBar QToolButton:checked {
                    background-color: #0078d7;       /* Match light mode */
                    border: 1px solid #005a9e;
                    color: #ffffff;
                }
                QToolBar QToolButton:checked:hover {
                    background-color: #1e88e5;
                }
                QToolBar::separator {
                    background-color: #555555;
                    width: 1px;
                }
                QHeaderView::section {
                    background-color: #353535;
                    color: #ffffff;
                    border: 1px solid #555555;
                }
                QTabWidget::pane {
                    border: 1px solid #555555;
                    background-color: #2b2b2b;
                }
                QTabBar::tab {
                    background-color: #353535;
                    color: #ffffff;
                    border: 1px solid #555555;
                    padding: 5px;
                }
                QTabBar::tab:selected {
                    background-color: #404040;
                }
            """
            self.setStyleSheet(dark_style)
        else:
            # Light theme stylesheet
            light_style = """
                QWidget {
                    background-color: #f0f0f0;
                    color: #000000;
                }
                QGroupBox {
                    background-color: #ffffff;
                    border: 1px solid #c0c0c0;
                    border-radius: 5px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: #000000;
                }
                QGroupBox::title {
                    color: #000000;
                    subcontrol-origin: margin;
                    subcontrol-position: top left;
                    padding: 2px 5px;
                }
                QPushButton {
                    background-color: #e0e0e0;
                    color: #000000;
                    border: 1px solid #b0b0b0;
                    border-radius: 3px;
                    padding: 5px;
                }
                QPushButton:hover {
                    background-color: #d0d0d0;
                }
                QPushButton:pressed {
                    background-color: #c0c0c0;
                }
                QPushButton:checked {
                    background-color: #0078d7;
                    color: #ffffff;
                    border: 1px solid #005a9e;
                }
                QPushButton:checked:hover {
                    background-color: #1e88e5;
                }
                QLabel {
                    color: #000000;
                    background-color: transparent;
                }
                QLineEdit {
                    background-color: #ffffff;
                    color: #000000;
                    border: 1px solid #b0b0b0;
                }
                QComboBox {
                    background-color: #ffffff;
                    color: #000000;
                    border: 1px solid #b0b0b0;
                }
                QComboBox::down-arrow {
                    image: none;
                    border-left: 5px solid transparent;
                    border-right: 5px solid transparent;
                    border-top: 5px solid #000000;
                }
                QTreeWidget {
                    background-color: #ffffff;
                    color: #000000;
                    border: 1px solid #b0b0b0;
                }
                QTreeWidget::item:selected {
                    background-color: #0078d7;
                    color: #ffffff;
                }
                QTextEdit {
                    background-color: #ffffff;
                    color: #000000;
                    border: 1px solid #b0b0b0;
                }
                QMenuBar {
                    background-color: #f0f0f0;
                    color: #000000;
                }
                QMenuBar::item:selected {
                    background-color: #e0e0e0;
                }
                QMenu {
                    background-color: #ffffff;
                    color: #000000;
                    border: 1px solid #b0b0b0;
                }
                QMenu::item:selected {
                    background-color: #0078d7;
                    color: #ffffff;
                }
                QStatusBar {
                    background-color: #f0f0f0;
                    color: #000000;
                }
                QDockWidget {
                    color: #000000;
                }
                QDockWidget::title {
                    background-color: #e0e0e0;
                    color: #000000;
                    padding: 4px;
                }
                QToolBar {
                    background-color: #f0f0f0;
                    border: 1px solid #c0c0c0;
                }
                QToolBar QToolButton {
                    color: #000000;
                    background-color: transparent;
                }
                QToolBar QToolButton:hover {
                    background-color: #e0e0e0;
                }
                QToolBar QToolButton:checked {
                    background-color: #0078d7;
                    border: 1px solid #005a9e;
                    color: #ffffff;
                }
                QToolBar QToolButton:checked:hover {
                    background-color: #1e88e5;
                }
                QHeaderView::section {
                    background-color: #e0e0e0;
                    color: #000000;
                    border: 1px solid #b0b0b0;
                }
                QTabWidget::pane {
                    border: 1px solid #b0b0b0;
                    background-color: #ffffff;
                }
                QTabBar::tab {
                    background-color: #e0e0e0;
                    color: #000000;
                    border: 1px solid #b0b0b0;
                    padding: 5px;
                }
                QTabBar::tab:selected {
                    background-color: #ffffff;
                }
            """
            self.setStyleSheet(light_style)

        # Update entity color legend text colors dynamically
        if hasattr(self, "entity_colors_header"):
            if self.force_dark_theme:
                self.entity_colors_header.setStyleSheet("color: white; margin-bottom: 8px; padding: 2px;")
                for label in getattr(self, "color_legend_labels", []):
                    label.setStyleSheet("color: white;")
            else:
                self.entity_colors_header.setStyleSheet("color: black; margin-bottom: 8px; padding: 2px;")
                for label in getattr(self, "color_legend_labels", []):
                    label.setStyleSheet("color: black;")
    
    def force_canvas_update(self):
        """Force the canvas to update and redraw entities"""
        if hasattr(self, 'canvas'):
            print("Forcing canvas update, Please wait.")
            
            # Ensure entities are set
            if hasattr(self, 'entities') and self.entities:
                print(f"Re-applying {len(self.entities)} entities to canvas")
                self.canvas.set_entities(self.entities)
            
            # Reset the view if needed
            self.reset_view()
            
            # Force a redraw
            self.canvas.update()
            
            # Force the application to process events
            QApplication.processEvents()

    
    def save_xml_with_precision_preservation(self, tree, file_path):
        """Save XML while preserving original floating-point precision"""
        try:
            # Create backup first
            backup_path = file_path + ".precision_backup"
            if os.path.exists(file_path):
                shutil.copy2(file_path, backup_path)
            
            # Save with minimal changes to preserve precision
            root = tree.getroot()
            
            # Don't use pretty printing - it can change precision
            # Write directly as-is
            tree.write(file_path, encoding='utf-8', xml_declaration=False)
            
            print(f"Saved with precision preservation: {file_path}")
            
        except Exception as e:
            print(f"Error saving XML with precision preservation: {e}")
            raise

    def _find_tree_file_path(self, tree_type):
        """Find the file path for a specific tree type using proper naming"""
        if not hasattr(self, 'xml_file_path') or not self.xml_file_path:
            return None
        
        folder_path = os.path.dirname(self.xml_file_path)
        
        # Get the level name from the main XML file
        # For example: "z_anim_creatures.mapsdata.xml" -> "z_anim_creatures"
        main_filename = os.path.basename(self.xml_file_path)
        if '.mapsdata.' in main_filename:
            level_name = main_filename.split('.mapsdata.')[0]
        else:
            # Fallback if naming doesn't match expected pattern
            level_name = os.path.splitext(main_filename)[0]
        
        print(f"Looking for {tree_type} file with level name: {level_name}")
        
        # Define the correct naming patterns for each file type
        file_patterns = {
            'omnis': [
                f"{level_name}.omnis.xml",     # z_anim_creatures.omnis.xml
                f"{level_name}.omnis.fcb",     # z_anim_creatures.omnis.fcb (original)
                ".omnis.xml",                  # fallback
                ".omnis.fcb"                   # fallback
            ],
            'managers': [
                f"{level_name}.managers.xml",   # z_anim_creatures.managers.xml
                f"{level_name}.managers.fcb",   # z_anim_creatures.managers.fcb (original)
                ".managers.xml",                # fallback
                ".managers.fcb"                 # fallback
            ],
            'sectorsdep': [
                f"{level_name}.sectorsdep.xml", # z_anim_creatures.sectorsdep.xml
                f"{level_name}.sectorsdep.fcb", # z_anim_creatures.sectorsdep.fcb (original)
                "sectorsdep.xml",               # fallback
                "sectorsdep.fcb",               # fallback
                "sectordep.xml",                # alternative naming
                "sectordep.fcb"                 # alternative naming
            ]
        }
        
        if tree_type not in file_patterns:
            return None
        
        # Try to find existing file (prefer XML, then FCB)
        for pattern in file_patterns[tree_type]:
            file_path = os.path.join(folder_path, pattern)
            if os.path.exists(file_path):
                print(f"Found existing file: {pattern}")
                
                # If it's an FCB file, we need to return the XML equivalent
                if file_path.endswith('.fcb'):
                    xml_path = file_path.replace('.fcb', '.xml')
                    print(f"FCB file found, XML equivalent would be: {os.path.basename(xml_path)}")
                    return xml_path
                else:
                    return file_path
        
        # If no existing file found, return the preferred XML path (with level name)
        preferred_path = os.path.join(folder_path, f"{level_name}.{tree_type}.xml")
        print(f"No existing file found, using preferred path: {os.path.basename(preferred_path)}")
        return preferred_path

    def update_ui_for_selected_entity(self, entity):
        """Update UI when an entity is selected - MODE AWARE - SHOWS CHILDREN AND SEATED NPCs"""
        if entity:
            # Get source_file attribute safely
            source_file = getattr(entity, 'source_file', None)
            source_text = f"Source: {source_file}" if source_file else "Source: unknown"
            
            # Get current mode
            mode_text = "2D Mode" if self.canvas.mode == 0 else "3D Mode"
            
            # Check for relationships
            relationships = []
            if hasattr(entity, 'xml_element') and entity.xml_element:
                # 1. Check for Structure children
                children_obj = entity.xml_element.find(".//object[@name='Children']")
                if children_obj:
                    child_objects = children_obj.findall("object[@name='Child']")
                    if child_objects:
                        child_names = []
                        for child_obj in child_objects:
                            name_field = child_obj.find("field[@name='Name']")
                            if name_field:
                                child_name = name_field.get('value-String', 'unknown')
                                child_names.append(child_name)
                        
                        if child_names:
                            relationships.append(f"🗗️ {len(child_names)} children:")
                            for child_name in child_names[:3]:  # Show first 3
                                relationships.append(f"  - {child_name}")
                            if len(child_names) > 3:
                                relationships.append(f"  ... and {len(child_names) - 3} more")
                
                # 2. Check for seated NPCs
                ai_component = entity.xml_element.find(".//object[@name='CFCXAIComponent']")
                if ai_component:
                    ai_object = ai_component.find(".//object[@name='AIObject']")
                    if ai_object:
                        # Build entity lookup for name resolution
                        entities_dict = {}
                        for ent in self.entities:
                            entities_dict[ent.id] = ent
                        
                        seated_npcs = []
                        for field in ai_object.findall("field"):
                            entity_id_ref = field.get('value-Hash64')
                            if entity_id_ref and entity_id_ref in entities_dict:
                                seated_entity = entities_dict[entity_id_ref]
                                if seated_entity.id != entity.id:  # Not self-reference
                                    seated_npcs.append(seated_entity.name)
                        
                        if seated_npcs:
                            relationships.append(f"🚗 {len(seated_npcs)} seated NPCs:")
                            for npc_name in seated_npcs[:3]:  # Show first 3
                                relationships.append(f"  🪑 {npc_name}")
                            if len(seated_npcs) > 3:
                                relationships.append(f"  ... and {len(seated_npcs) - 3} more")
            
            # Populate structured stat labels
            self.stat_name_label.setText(entity.name)
            entity_id = entity.id
            self.stat_id_label.setText(entity_id[:22] + "..." if len(entity_id) > 22 else entity_id)
            self.stat_type_label.setText(getattr(entity, 'entity_type', None) or "—")
            self.stat_source_label.setText(getattr(entity, 'source_file', None) or "—")
            if getattr(self.canvas, 'unified_mode', False):
                sid = getattr(entity, 'source_sector_id', -1)
                layer = getattr(entity, 'source_layer', 'main') or 'main'
                self.stat_map_label.setText(f"Sector {sid} ({layer})" if sid >= 0 else "—")
            else:
                self.stat_map_label.setText(getattr(entity, 'map_name', None) or "—")
            self.stat_pos_label.setText(f"{entity.x:.2f}, {entity.y:.2f}, {entity.z:.2f}")
            self._update_stat_angles(entity)

            if relationships:
                self.stat_relations_label.setText("\n".join(relationships))
                self.stat_relations_label.show()
            else:
                self.stat_relations_label.hide()

            # Update status bar
            relationship_summary = ""
            if relationships:
                counts = []
                for rel in relationships:
                    if "children:" in rel:
                        counts.append(rel.split()[1] + " children")
                    elif "seated NPCs:" in rel:
                        counts.append(rel.split()[1] + " NPCs")
                if counts:
                    relationship_summary = f" + {', '.join(counts)}"

            self.status_bar.showMessage(
                f"Selected: {entity.name}{relationship_summary} at ({entity.x:.0f}, {entity.y:.0f}, {entity.z:.0f}) | {mode_text}"
            )
        else:
            mode_text = "2D Mode" if self.canvas.mode == 0 else "3D Mode"
            self._clear_entity_stats()
            self.status_bar.showMessage(f"No selection | {mode_text}")

    def _clear_entity_stats(self):
        """Reset all structured stat labels to their default empty state."""
        if not hasattr(self, 'stat_name_label'):
            return
        self.stat_name_label.setText("—")
        self.stat_id_label.setText("—")
        self.stat_type_label.setText("—")
        self.stat_source_label.setText("—")
        self.stat_map_label.setText("—")
        self.stat_pos_label.setText("—")
        if hasattr(self, 'stat_angles_label'):
            self.stat_angles_label.setText("—")
        if hasattr(self, 'stat_angles_add_btn'):
            self.stat_angles_add_btn.hide()
        self.stat_relations_label.hide()

    def _get_entity_angles_text(self, entity):
        """Return display string for hidAngles, or '—' if absent."""
        if not hasattr(entity, 'xml_element') or entity.xml_element is None:
            return "—"
        f = entity.xml_element.find(".//field[@name='hidAngles']")
        if f is None:
            return "—"
        v = f.get('value-Vector3', '')
        try:
            parts = [float(p) for p in v.split(',')]
            return f"({parts[0]:.1f}, {parts[1]:.1f}, {parts[2]:.1f})"
        except Exception:
            return "—"

    def _update_stat_angles(self, entity):
        """Refresh the angles label and add-button in the stats panel."""
        if not hasattr(self, 'stat_angles_label'):
            return
        if not entity or not hasattr(entity, 'xml_element') or entity.xml_element is None:
            self.stat_angles_label.setText("—")
            self.stat_angles_add_btn.hide()
            return
        f = entity.xml_element.find(".//field[@name='hidAngles']")
        if f is not None:
            v = f.get('value-Vector3', '')
            try:
                parts = [float(p) for p in v.split(',')]
                self.stat_angles_label.setText(f"{parts[0]:.2f}, {parts[1]:.2f}, {parts[2]:.2f}")
            except Exception:
                self.stat_angles_label.setText("—")
            self.stat_angles_add_btn.hide()
        else:
            self.stat_angles_label.setText("—")
            self.stat_angles_add_btn.show()

    def _add_hidangles_to_entity(self, entity):
        """Add hidAngles field after hidPos, same logic as entity editor."""
        if not entity or not hasattr(entity, 'xml_element') or entity.xml_element is None:
            return False
        if entity.xml_element.find(".//field[@name='hidAngles']") is not None:
            return False
        from xml.etree import ElementTree as ET
        pos_field = entity.xml_element.find(".//field[@name='hidPos']")
        if pos_field is None:
            pos_field = entity.xml_element.find(".//field[@name='hidPos_precise']")
        angles_field = ET.Element("field")
        angles_field.set("hash", "6553B60B")
        angles_field.set("name", "hidAngles")
        angles_field.set("value-Vector3", "0,-0,0")
        angles_field.set("type", "BinHex")
        angles_field.text = "000000000000008000000000"
        if pos_field is not None:
            angles_field.tail = pos_field.tail
            pos_field.tail = "\n      "
            parent = None
            for element in entity.xml_element.iter():
                for child in element:
                    if child is pos_field:
                        parent = element
                        break
                if parent is not None:
                    break
            if parent is not None:
                parent.insert(list(parent).index(pos_field) + 1, angles_field)
            else:
                entity.xml_element.append(angles_field)
        else:
            entity.xml_element.append(angles_field)
        if hasattr(self.canvas, 'mark_entity_modified'):
            self.canvas.mark_entity_modified(entity)
        return True

    def _add_hidangles_from_stats(self):
        """Add hidAngles to the currently selected entity (called from stats panel button)."""
        entity = self.selected_entity
        if self._add_hidangles_to_entity(entity):
            self._update_stat_angles(entity)
            self._update_tree_item_angles(entity, 0.0, 0.0, 0.0)
            if hasattr(self, 'browser_add_angles_btn'):
                self.browser_add_angles_btn.hide()

    def _add_hidangles_from_browser(self):
        """Add hidAngles to the currently selected entity (called from browser button)."""
        entity = self.selected_entity
        if self._add_hidangles_to_entity(entity):
            self._update_stat_angles(entity)
            self._update_tree_item_angles(entity, 0.0, 0.0, 0.0)
            self.browser_add_angles_btn.hide()

    def on_entity_angle_updated(self, entity, angles_tuple):
        """Live-update angles label and tree when the 3D gizmo rotates an entity."""
        ax, ay, az = angles_tuple
        if hasattr(self, 'stat_angles_label') and entity is self.selected_entity:
            self.stat_angles_label.setText(f"{ax:.2f}, {ay:.2f}, {az:.2f}")
            self.stat_angles_add_btn.hide()
        if hasattr(self, 'entity_tree'):
            self._update_tree_item_angles(entity, ax, ay, az)

    def _update_tree_item_angles(self, entity, ax, ay, az):
        """Update the Angles column of the tree row matching entity."""
        ang_text = f"({ax:.1f}, {ay:.1f}, {az:.1f})"

        def search(parent_item):
            for i in range(parent_item.childCount()):
                child = parent_item.child(i)
                if child.data(0, Qt.ItemDataRole.UserRole) is entity:
                    child.setText(3, ang_text)
                    return True
                if search(child):
                    return True
            return False

        for i in range(self.entity_tree.topLevelItemCount()):
            if search(self.entity_tree.topLevelItem(i)):
                break

    def on_entity_position_updated(self, entity, pos_tuple):
        """Live-update the Statistics position label, sector label, status bar, and entity browser row when an entity moves."""
        if entity is None:
            return
        x, y, z = pos_tuple

        # Position label
        if hasattr(self, 'stat_pos_label'):
            self.stat_pos_label.setText(f"{x:.2f}, {y:.2f}, {z:.2f}")

        # Sector / map label — show live computed sector in unified mode
        if hasattr(self, 'stat_map_label'):
            if getattr(self.canvas, 'unified_mode', False):
                cur_gx = int(x // 64)
                cur_gy = int(y // 64)
                cur_sid = cur_gy * 16 + cur_gx
                src_sid = getattr(entity, 'source_sector_id', -1)
                layer = getattr(entity, 'source_layer', 'main') or 'main'
                if cur_sid != src_sid and src_sid >= 0:
                    self.stat_map_label.setText(f"Sector {src_sid} → {cur_sid} ({layer})")
                else:
                    self.stat_map_label.setText(f"Sector {cur_sid} ({layer})")
            else:
                self.stat_map_label.setText(getattr(entity, 'map_name', None) or "—")

        # Entity browser position column
        if hasattr(self, 'entity_tree'):
            self._update_tree_item_position(entity, x, y, z)

        # Status bar
        if hasattr(self, 'status_bar') and hasattr(self, 'canvas'):
            mode_text = "2D Mode" if self.canvas.mode == 0 else "3D Mode"
            self.status_bar.showMessage(
                f"Selected: {entity.name} at ({x:.0f}, {y:.0f}, {z:.0f}) | {mode_text}"
            )

    def _update_tree_item_position(self, entity, x, y, z):
        """Update the Position column of the entity tree item matching entity."""
        pos_text = f"({x:.1f}, {y:.1f}, {z:.1f})"

        def search_children(parent_item):
            for i in range(parent_item.childCount()):
                child = parent_item.child(i)
                if child.data(0, Qt.ItemDataRole.UserRole) is entity:
                    child.setText(2, pos_text)
                    return True
                if search_children(child):
                    return True
            return False

        for i in range(self.entity_tree.topLevelItemCount()):
            item = self.entity_tree.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) is entity:
                item.setText(2, pos_text)
                return
            if search_children(item):
                return

    def update_entity_statistics(self):
        """Update entity and object statistics by source file and type - ENHANCED VERSION"""
        try:
            # Count entities from each source
            entity_stats = {
                "mapsdata": 0,
                "managers": 0,
                "omnis": 0,
                "sectorsdep": 0,
                "worldsectors": 0,  # Add worldsectors category
                "preload": 0,
                "particles": 0,
                "unknown": 0
            }
            
            # Count entities by source
            for entity in self.entities:
                source = getattr(entity, 'source_file', None)
                if not source:
                    source = "unknown"
                    entity_stats["unknown"] += 1
                elif source.startswith("particles_"):
                    entity_stats["particles"] += 1
                elif source in entity_stats:
                    entity_stats[source] += 1
                else:
                    entity_stats["unknown"] += 1
            
            # Count objects separately
            object_stats_by_type = {}
            object_stats_by_sector = {}
            
            for obj in self.objects:
                # Count by object type
                obj_type = getattr(obj, 'object_type', 'Unknown')
                if obj_type not in object_stats_by_type:
                    object_stats_by_type[obj_type] = 0
                object_stats_by_type[obj_type] += 1
                
                # Count by sector
                sector_path = getattr(obj, 'sector_path', None)
                if sector_path:
                    sector_name = os.path.basename(sector_path)
                    if sector_name not in object_stats_by_sector:
                        object_stats_by_sector[sector_name] = 0
                    object_stats_by_sector[sector_name] += 1
            
            # Build statistics text
            total_entities = len(self.entities)
            total_objects = len(self.objects)
            
            stats_text = f"Total: {total_entities} entities"
            if total_objects > 0:
                stats_text += f" + {total_objects} objects"
            
            # Add entity breakdown
            if total_entities > 0:
                entity_breakdown = []
                for source, count in entity_stats.items():
                    if count > 0:
                        entity_breakdown.append(f"{count} {source}")
                
                if entity_breakdown:
                    stats_text += f"\nEntities: " + ", ".join(entity_breakdown)
            
            # Add object breakdown if we have objects
            if total_objects > 0:
                sorted_obj_types = sorted(object_stats_by_type.items(), key=lambda x: x[1], reverse=True)
                top_obj_types = sorted_obj_types[:3]
                
                obj_breakdown = []
                for obj_type, count in top_obj_types:
                    obj_breakdown.append(f"{count} {obj_type}")
                
                if len(sorted_obj_types) > 3:
                    others_count = sum(count for _, count in sorted_obj_types[3:])
                    obj_breakdown.append(f"{others_count} others")
                
                if obj_breakdown:
                    stats_text += f"\nObjects: " + ", ".join(obj_breakdown)
                
                if object_stats_by_sector:
                    sector_count = len(object_stats_by_sector)
                    stats_text += f"\nFrom {sector_count} sectors"
            
            # Update UI
            self.entity_count_label.setText(stats_text)
            
            # Status bar message
            if total_objects > 0:
                status_message = f"Loaded {total_entities} entities and {total_objects} objects"
            else:
                status_message = f"Loaded {total_entities} entities"
            
            self.status_bar.showMessage(status_message)
            
            print(f"Statistics: {total_entities} entities, {total_objects} objects")
            print(f"Entity breakdown: {entity_stats}")
            
        except Exception as e:
            print(f"Error updating statistics: {str(e)}")
            # Fallback
            try:
                total_entities = len(self.entities) if hasattr(self, 'entities') else 0
                total_objects = len(self.objects) if hasattr(self, 'objects') else 0
                self.entity_count_label.setText(f"Entities: {total_entities}, Objects: {total_objects}")
            except:
                self.entity_count_label.setText("Statistics unavailable")

    def change_to_topdownview(self):
        """Simplified - no mode switching needed"""
        # Since we only have 2D mode now, this just ensures we're in the right state
        self.statusBar().showMessage("2D top-down view active")

    def update_side_panel_for_2d(self):
        """Update side panel UI elements for 2D mode - SIMPLIFIED"""
        # Since we only have 2D mode, this can be simplified or removed
        # Update the entity info panel if needed
        self.update_ui_for_selected_entity(self.selected_entity)

    def keyPressEvent(self, event):
        """Handle key press events - WITH 2D/3D MODE SUPPORT AND 3D TOGGLES"""
        
        # TAB KEY - Toggle between 2D and 3D
        if event.key() == Qt.Key.Key_Tab:
            if hasattr(self.canvas, 'toggle_view_mode'):
                old_mode = self.canvas.mode
                self.canvas.toggle_view_mode()
                new_mode = self.canvas.mode
                
                print(f"Mode toggled from {old_mode} to {new_mode}")
                
                # Update status bar with mode-specific tips
                if self.canvas.mode == 0:  # 2D mode
                    mode_name = "2D Top-Down View"
                    tips = "WASD: Pan | Wheel: Zoom | Left-Click: Select | Tab: Switch to 3D"
                    print("Switched to 2D mode")
                else:  # 3D mode
                    mode_name = "3D Perspective View"
                    tips = "WASD: Move | QE: Up/Down | Mouse: Look | H: HUD | G: Grid | B: Cubes | Tab: Switch to 2D"
                    print("Switched to 3D mode")
                
                self.statusBar().showMessage(f"Mode: {mode_name} | {tips}", 5000)
                
                # Update mode indicator if it exists
                if hasattr(self, 'update_mode_indicator'):
                    self.update_mode_indicator()
                    
            event.accept()
            return
        
        # F1 - Help (mode-aware)
        if event.key() == Qt.Key.Key_F1:
            self.show_help_dialog_with_3d()
            event.accept()
            return
        
        # G - Toggle grid (mode-aware: 2D grid in 2D mode, 3D grid in 3D mode)
        if event.key() == Qt.Key.Key_G:
            if hasattr(self.canvas, 'mode') and self.canvas.mode == 1:  # 3D mode
                if hasattr(self.canvas, 'toggle_3d_grid'):
                    self.canvas.toggle_3d_grid()
                    grid_status = "ON" if self.canvas.show_3d_grid else "OFF"
                    self.statusBar().showMessage(f"3D Grid: {grid_status}", 2000)
                else:
                    self.toggle_grid()  # Fallback to regular toggle
            else:  # 2D mode
                self.toggle_grid()
                grid_status = "ON" if self.canvas.show_grid else "OFF"
                self.statusBar().showMessage(f"2D Grid: {grid_status}", 2000)
            event.accept()
            return
        
        # H - Toggle 3D HUD (only in 3D mode)
        if event.key() == Qt.Key.Key_H:
            if hasattr(self.canvas, 'mode') and self.canvas.mode == 1:  # 3D mode
                if hasattr(self.canvas, 'toggle_3d_hud'):
                    self.canvas.toggle_3d_hud()
                    hud_status = "ON" if self.canvas.show_3d_hud else "OFF"
                    self.statusBar().showMessage(f"3D HUD: {hud_status}", 2000)
                    event.accept()
                    return
        
        # B - Toggle 3D Cubes (only in 3D mode)
        if event.key() == Qt.Key.Key_B:
            if hasattr(self.canvas, 'mode') and self.canvas.mode == 1:  # 3D mode
                if hasattr(self.canvas, 'toggle_3d_cubes'):
                    self.canvas.toggle_3d_cubes()
                    cubes_status = "ON" if self.canvas.show_3d_cubes else "OFF"
                    self.statusBar().showMessage(f"3D Cubes: {cubes_status} (Models always visible)", 2000)
                    event.accept()
                    return
        
        # ` - Toggle entities (works in both modes)
        if event.key() == Qt.Key.Key_QuoteLeft:  # Backtick/tilde key
            self.toggle_entities()
            event.accept()
            return
        
        # Ctrl+R - Reset view (mode-aware)
        if event.key() == Qt.Key.Key_R and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.reset_view()
            event.accept()
            return
        
        # Delete - Delete selected entities (works in both modes)
        if event.key() == Qt.Key.Key_Delete:
            if hasattr(self, 'delete_selected_entities'):
                self.delete_selected_entities()
                event.accept()
                return
        
        # Ctrl+C - Copy (works in both modes)
        if event.key() == Qt.Key.Key_C and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if hasattr(self, 'copy_selected_entities'):
                self.copy_selected_entities()
                event.accept()
                return
        
        # Ctrl+V - Paste (works in both modes)
        if event.key() == Qt.Key.Key_V and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if hasattr(self, 'paste_entities'):
                self.paste_entities()
                event.accept()
                return
        
        # Ctrl+D - Duplicate (works in both modes)
        if event.key() == Qt.Key.Key_D and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if hasattr(self, 'duplicate_selected_entities'):
                self.duplicate_selected_entities()
                event.accept()
                return
        
        # Ctrl+E - Entity Editor (works in both modes)
        if event.key() == Qt.Key.Key_E and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if hasattr(self, 'open_entity_editor'):
                self.open_entity_editor()
                event.accept()
                return
        
        # Pass other keys to canvas (handles WASD differently per mode)
        if hasattr(self, 'canvas'):
            self.canvas.keyPressEvent(event)
        
        # Call parent handler for any unhandled keys
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        """Handle key release events from the main window"""
        # Pass the key event to the canvas for camera movement
        if hasattr(self.canvas, 'keyReleaseEvent'):
            self.canvas.keyReleaseEvent(event)


    def show_help_dialog_with_3d(self):
        """Show help dialog with keyboard and mouse controls - INCLUDING 3D MODE"""
        help_text = (
            "Keyboard Controls:\n"
            "  General:\n"
            "    Tab        - Toggle between 2D and 3D view modes\n"
            "    F1         - Show this help dialog\n"
            "    Delete     - Delete selected entity/entities\n"
            "    Ctrl+C     - Copy selected entity/entities\n"
            "    Ctrl+V     - Paste entity/entities\n"
            "    Ctrl+Z     - Undo (if available)\n"
            "\n"
            "  2D Mode Navigation:\n"
            "    W/A/S/D    - Pan camera (Up/Left/Down/Right)\n"
            "    Shift      - Speed boost for panning\n"
            "    Mouse Wheel - Zoom in/out\n"
            "\n"
            "  3D Mode Navigation:\n"
            "    W/S        - Move forward/backward\n"
            "    A/D        - Move left/right (strafe)\n"
            "    Q/E        - Move up/down (vertical)\n"
            "    Shift      - Speed boost for movement\n"
            "\n"
            "Mouse Controls:\n"
            "  2D Mode:\n"
            "    Left Click      - Select entity\n"
            "    Ctrl+Left Click - Multi-select entities\n"
            "    Left Drag       - Move selected entity\n"
            "    Mouse Wheel     - Zoom in/out\n"
            "    Right Click     - Context menu\n"
            "\n"
            "  3D Mode:\n"
            "    Left Click           - Select entity\n"
            "    Right Click + Drag   - Rotate camera (look around)\n"
            "    Middle Click + Drag  - Pan camera\n"
            "    Mouse Wheel          - Move forward/backward\n"
            "    Right Click          - Context menu\n"
            "\n"
            "View Options:\n"
            "  G          - Toggle grid visibility\n"
            "  E          - Toggle entity visibility\n"
            "  T          - Toggle terrain visibility (if loaded)\n"
            "  B          - Toggle sector boundaries (2D mode)\n"
            "\n"
            "Gizmo Controls (Both Modes):\n"
            "  Click and drag the colored arrows to move entities\n"
            "  Red arrow    - X axis\n"
            "  Green arrow  - Y axis (Z in 3D)\n"
            "  Blue arrow   - Z axis (Y in 3D)\n"
            "\n"
            "Tips:\n"
            "  Hold Shift while moving for faster camera movement\n"
            "  Double-click an entity in the tree to focus on it\n"
            "  Right-click entities for quick actions\n"
            "  Use Tab to switch between top-down editing and 3D preview\n"
        )
        
        # Create and show help dialog
        from PyQt6.QtWidgets import QMessageBox
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Level Editor Controls - 2D & 3D Modes")
        msg_box.setText(help_text)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.exec()
    
    def reset_view(self):
        """Reset the view to show all content - UPDATED for 2D and 3D"""
        if not self.entities:
            print("No entities to display")
            self.status_bar.showMessage("No entities to display")
            return
            
        print(f"Resetting view for {len(self.entities)} entities in mode {self.canvas.mode}")
        
        if self.canvas.mode == 0:  # 2D mode
            # Get current scale factor before reset
            old_scale = self.canvas.scale_factor
            
            # Call the canvas reset_view method
            new_scale = self.canvas.reset_view()
            
            # Debug output
            print(f"2D view reset: scale changed from {old_scale:.2f} to {new_scale:.2f}")
            
            # Update status bar
            self.status_bar.showMessage(f"2D view reset (scale: {new_scale:.2f})")
            
            # Return the new scale
            return new_scale
            
        else:  # 3D mode
            # Calculate center of all entities
            min_x = min_y = min_z = float('inf')
            max_x = max_y = max_z = float('-inf')
            
            valid_entities = 0
            for entity in self.entities:
                if hasattr(entity, 'x') and hasattr(entity, 'y') and hasattr(entity, 'z'):
                    min_x = min(min_x, entity.x)
                    max_x = max(max_x, entity.x)
                    min_y = min(min_y, entity.y)
                    max_y = max(max_y, entity.y)
                    min_z = min(min_z, entity.z)
                    max_z = max(max_z, entity.z)
                    valid_entities += 1
            
            if valid_entities == 0:
                print("No valid entities with 3D coordinates")
                return 1.0
            
            # Calculate center point
            center_x = (min_x + max_x) / 2
            center_y = (min_y + max_y) / 2
            center_z = (min_z + max_z) / 2
            
            # Calculate span to determine camera distance
            span_x = max_x - min_x
            span_y = max_y - min_y
            span_z = max_z - min_z
            max_span = max(span_x, span_y, span_z, 100)  # Minimum span of 100

            # Position camera to view all entities
            camera_distance = max_span * 2  # Distance based on span

            # Position camera behind and above the center
            import numpy as np
            self.canvas.camera_3d.position = np.array([
                center_x - camera_distance * 0.5,  # Behind on X
                center_z + camera_distance * 0.7,  # Above (Z is height)
                center_y + camera_distance * 0.5   # Back on Y
            ], dtype=float)

            # Calculate yaw to look at center
            dx = center_x - self.canvas.camera_3d.position[0]
            dy = center_y - self.canvas.camera_3d.position[2]
            self.canvas.camera_3d.yaw = np.degrees(np.arctan2(dy, dx))

            # Set pitch to look down at scene
            self.canvas.camera_3d.pitch = -30.0
            
            # Update camera vectors
            self.canvas.camera_3d.update_vectors()
            
            print(f"3D camera positioned at ({self.canvas.camera_3d.position[0]:.0f}, "
                f"{self.canvas.camera_3d.position[1]:.0f}, {self.canvas.camera_3d.position[2]:.0f})")
            print(f"Looking at center: ({center_x:.0f}, {center_y:.0f}, {center_z:.0f})")
            
            # Update canvas
            self.canvas.update()
            
            # Update status bar
            self.status_bar.showMessage(f"3D view reset - viewing {valid_entities} entities")
            
            return 1.0  # No scale factor in 3D
    
    def action_ground_objects(self):
        """Ground selected objects to the terrain - SIMPLIFIED for 2D only"""
        # Simplified implementation for 2D mode only
        for pos in self.canvas.selected_positions:
            if self.canvas.collision is None:
                return None
            height = self.canvas.collision.collide_ray_closest(pos.x, pos.z, pos.y)

            if height is not None:
                pos.y = height

        self.pik_control.update_info()
        self.canvas.gizmo.move_to_average(self.canvas.selected, None, None, False)
        self.set_has_unsaved_changes(True)
        self.canvas.update()

    def action_move_objects(self, deltax, deltay, deltaz):
        """Handle moving objects - SIMPLIFIED for 2D only"""
        # Proceed with the move implementation (no mode check needed)
        for pos in self.canvas.selected_positions:
            pos.add_position(deltax, deltay, deltaz)

        # Update the view
        self.canvas.update()
        self.pik_control.update_info()
        self.set_has_unsaved_changes(True)

    def action_rotate_object(self, deltarotation):
        """Handle rotating objects in both 2D and 3D modes"""
        # Pass through to the canvas's rotation implementation
        self.canvas.action_rotate_object(deltarotation)
        
        # Update UI
        self.canvas.update()
        self.pik_control.update_info()
        self.set_has_unsaved_changes(True)
    
    def action_update_info(self):
        """Update information panel based on selection"""
        if self.level_file is not None:
            selected = self.canvas.selected
            if len(selected) == 1:
                currentobj = selected[0]
                self.pik_control.set_info(currentobj, self.reset_view)
                self.pik_control.update_info()
            else:
                self.pik_control.reset_info("{0} objects selected".format(len(self.canvas.selected)))
                self.pik_control.set_objectlist(selected)    

    def toggle_display_mode(self):
        """Remove this method entirely or make it a no-op"""
        # Since we only have 2D mode, this method is no longer needed
        self.statusBar().showMessage("Only 2D mode available")

    def _indent_xml_elements(self, elem, level=0):
        """Recursively add proper indentation to XML elements"""
        indent = "\n" + level * "  "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = indent + "  "
            if not elem.tail or not elem.tail.strip():
                elem.tail = indent
            for child in elem:
                self._indent_xml_elements(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = indent
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = indent

    def _indent_xml(self, elem, level=0):
        """Add proper indentation to XML elements"""
        indent = "\n" + level * "  "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = indent + "  "
            if not elem.tail or not elem.tail.strip():
                elem.tail = indent
            for child in elem:
                self._indent_xml(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = indent
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = indent

    def _int32_to_binhex(self, value):
        """Convert 32-bit integer to BinHex format"""
        try:
            import struct
            binary_data = struct.pack('<I', int(value))  # Little-endian unsigned int
            return binary_data.hex().upper()
        except:
            return "00000000"

    def _string_to_binhex(self, text):
        """Convert string to BinHex format with null terminator"""
        try:
            binary_data = text.encode('utf-8') + b'\x00'
            return binary_data.hex().upper()
        except:
            return "00"

    def _get_next_available_sector_id(self):
        """Get the next available sector ID"""
        if not hasattr(self, 'worldsectors_path') or not self.worldsectors_path:
            return 0
        
        try:
            import glob
            import os
            import re
            
            # Find all existing sector files
            pattern = os.path.join(self.worldsectors_path, "worldsector*.data.fcb.converted.xml")
            existing_files = glob.glob(pattern)
            
            # Also check for .data.fcb files
            fcb_pattern = os.path.join(self.worldsectors_path, "worldsector*.data.fcb")
            existing_fcb_files = glob.glob(fcb_pattern)
            
            used_ids = set()
            
            # Extract IDs from .converted.xml files
            for file_path in existing_files:
                filename = os.path.basename(file_path)
                match = re.match(r'worldsector(\d+)\.data\.fcb\.converted\.xml', filename)
                if match:
                    used_ids.add(int(match.group(1)))
            
            # Extract IDs from .data.fcb files
            for file_path in existing_fcb_files:
                filename = os.path.basename(file_path)
                match = re.match(r'worldsector(\d+)\.data\.fcb', filename)
                if match:
                    used_ids.add(int(match.group(1)))
            
            # Find next available ID
            next_id = 0
            while next_id in used_ids:
                next_id += 1
            
            return next_id
            
        except Exception as e:
            print(f"Error finding next sector ID: {e}")
            return 0

    def closeEvent(self, event):
        """Handle application close event - cleanup resources"""
        print("Application closing - cleaning up resources...")
        
        # Clean up patch manager if it exists
        if hasattr(self, 'patch_manager'):
            try:
                self.patch_manager.cleanup()
            except Exception as e:
                print(f"Error cleaning up patch manager: {e}")
        
        # Clean up cache manager
        if hasattr(self, 'cache'):
            try:
                from cache_manager import shutdown_cache_manager
                shutdown_cache_manager()
                print("Cache manager shutdown complete")
            except Exception as e:
                print(f"Error shutting down cache manager: {e}")
        
        # Close entity editor if open
        if hasattr(self, 'entity_editor') and self.entity_editor:
            try:
                self.entity_editor.close()
            except:
                pass
        
        # Clean up any running threads
        if hasattr(self, 'object_loading_thread') and self.object_loading_thread:
            try:
                if self.object_loading_thread.isRunning():
                    self.object_loading_thread.stop()
                    self.object_loading_thread.wait(2000)
            except:
                pass
        
        # Accept the close event
        event.accept()
        print("Application cleanup complete")

class SaveWorkerThread(QThread):
    """Runs the full level save (XML write + FCB conversion) off the UI thread."""
    progress_updated = pyqtSignal(int)
    status_updated   = pyqtSignal(str)
    log_message      = pyqtSignal(str)
    save_finished    = pyqtSignal(int, int)  # (main_converted, ws_converted)
    save_failed      = pyqtSignal(str)

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.should_cancel = False

    def run(self):
        try:
            ed = self.editor

            self.status_updated.emit("Saving XML files with current positions, Please wait.")
            self.progress_updated.emit(10)
            ed.save_all_xml_files_before_conversion(log_callback=self.log_message.emit)
            self.log_message.emit("XML files saved")

            if self.should_cancel:
                return

            self.status_updated.emit("Converting main files to FCB, Please wait.")
            self.progress_updated.emit(30)
            main_converted = ed._convert_main_xml_to_fcb(log_callback=self.log_message.emit)
            self.log_message.emit(f"Main files: {main_converted} converted")

            if self.should_cancel:
                return

            self.status_updated.emit("Converting WorldSector files to FCB, Please wait.")
            self.progress_updated.emit(60)
            ws_converted = ed._convert_worldsector_files_fixed(log_callback=self.log_message.emit)
            self.log_message.emit(f"WorldSector files: {ws_converted} converted")

            self.progress_updated.emit(100)
            self.save_finished.emit(main_converted or 0, ws_converted or 0)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.save_failed.emit(str(e))


class ObjectLoadingThread(QThread):
    """Thread for loading objects from worldsectors in the background"""
    
    progress_updated = pyqtSignal(float)  # Progress from 0.0 to 1.0
    status_updated = pyqtSignal(str)      # Status message
    log_message = pyqtSignal(str)         # NEW: Log messages for the log box
    objects_loaded = pyqtSignal(list)     # List of loaded objects
    finished_loading = pyqtSignal(object) # ObjectLoadResult
    
    def __init__(self, worldsectors_path, file_converter, grid_config=None):
        super().__init__()
        self.worldsectors_path = worldsectors_path
        self.file_converter = file_converter
        self.grid_config = grid_config
        self.should_stop = False
    
    def stop(self):
        """Stop the loading process"""
        self.should_stop = True
        print("Stop requested for object loading thread")

    def run(self):
        """Run the object loading process with cleanup - UPDATED with cancellation check"""
        try:
            from data_models import ObjectLoadResult, WorldSectorManager, ObjectParser
            
            result = ObjectLoadResult()
            
            # Progress weights
            CLEANUP_WEIGHT = 0.02
            SCAN_WEIGHT = 0.03
            CONVERT_WEIGHT = 0.70
            RESCAN_WEIGHT = 0.05
            LOAD_WEIGHT = 0.20
            
            current_progress = 0.0
            
            # Helper for logging
            def log(message):
                print(message)
                self.log_message.emit(message)
            
            # Step 1: Cleanup
            self.status_updated.emit("Cleaning up duplicate files, Please wait.")
            self.progress_updated.emit(0.0)
            self.cleanup_duplicate_xml_files(self.worldsectors_path)
            current_progress = CLEANUP_WEIGHT
            self.progress_updated.emit(current_progress)
            
            if self.should_stop:
                return
            
            # Step 2: Initial scan
            self.status_updated.emit("Scanning for converted XML files, Please wait.")
            sectors = WorldSectorManager.scan_worldsectors_folder(self.worldsectors_path, log_callback=log)
            log(f"Found {len(sectors)} sectors")
            current_progress += SCAN_WEIGHT
            self.progress_updated.emit(current_progress)
            
            if self.should_stop:
                return
            
            # Step 3: Convert FCB files
            self.status_updated.emit("Converting .data.fcb files to XML, Please wait.")

            # Create callback that checks for cancellation and handles logging
            def conversion_progress_with_logging(progress, message=None):
                # Check if cancelled
                if self.should_stop:
                    raise InterruptedError("Conversion cancelled by user")
                
                # If message is provided, always send it to log
                if message:
                    self.log_message.emit(message)
                
                # Update progress bar only if progress is a valid number
                if progress is not None:
                    overall = current_progress + (progress * CONVERT_WEIGHT)
                    self.progress_updated.emit(overall)

            try:
                success_count, error_count, converted_files = self.file_converter.convert_data_fcb_files(
                    self.worldsectors_path,
                    progress_callback=conversion_progress_with_logging
                )
            except InterruptedError:
                print("Conversion interrupted by user")
                return

            log(f"Conversion results: {success_count} successful, {error_count} failed")
            current_progress += CONVERT_WEIGHT
            self.progress_updated.emit(current_progress)
            
            if self.should_stop:
                return
            
            # Step 4: Re-scan
            self.status_updated.emit("Re-scanning for XML files, Please wait.")
            sectors = WorldSectorManager.scan_worldsectors_folder(self.worldsectors_path, log_callback=log)
            result.sectors_processed = len(sectors)
            result.loaded_sectors = sectors
            log(f"After conversion, found {len(sectors)} sectors")
            current_progress += RESCAN_WEIGHT
            self.progress_updated.emit(current_progress)
            
            if self.should_stop:
                return
            
            # Step 5: Load objects
            self.status_updated.emit("Loading objects from converted XML files, Please wait.")
            all_objects = []
            
            total_xml_files = sum(len(sector.data_xml_files) for sector in sectors)
            files_processed = 0
            
            for i, sector in enumerate(sectors):
                if self.should_stop:
                    break
                
                log(f"Processing sector {i+1}/{len(sectors)} with {len(sector.data_xml_files)} XML files")
                sector_objects = []
                
                for xml_file in sector.data_xml_files:
                    if self.should_stop:
                        break
                    
                    try:
                        if xml_file.endswith('.converted.xml'):
                            log(f"Loading objects from: {xml_file}")
                            objects = ObjectParser.extract_objects_from_data_xml(
                                xml_file, 
                                sector_path=sector.folder_path
                            )
                            
                            log(f"Extracted {len(objects)} objects from {os.path.basename(xml_file)}")
                            
                            for obj in objects:
                                if self.grid_config and self.grid_config.maps:
                                    obj.map_name = self._determine_object_map(obj)
                            
                            sector_objects.extend(objects)
                        else:
                            log(f"Skipping non-converted XML file: {xml_file}")
                            
                    except Exception as e:
                        error_msg = f"Error loading {xml_file}: {str(e)}"
                        log(error_msg)
                        result.conversion_errors.append(error_msg)
                        result.failed_objects += 1
                    
                    files_processed += 1
                    if total_xml_files > 0:
                        file_progress = files_processed / total_xml_files
                        overall = current_progress + (file_progress * LOAD_WEIGHT)
                        self.progress_updated.emit(overall)
                        self.status_updated.emit(f"Loading objects: {files_processed}/{total_xml_files} files")
                
                sector.object_count = len(sector_objects)
                all_objects.extend(sector_objects)
                log(f"Sector {i+1} loaded {len(sector_objects)} objects (total: {len(all_objects)})")
            
            # Check if cancelled before emitting results
            if self.should_stop:
                print("Loading cancelled by user")
                return
            
            # Final results
            result.total_objects = len(all_objects)
            result.loaded_objects = len(all_objects)
            
            log(f"Loading complete: {len(all_objects)} total objects loaded")
            self.status_updated.emit(f"Complete: {len(all_objects)} objects loaded")
            self.progress_updated.emit(1.0)
            
            # Emit results
            self.objects_loaded.emit(all_objects)
            self.finished_loading.emit(result)
            
        except Exception as e:
            error_msg = f"Error during loading: {str(e)}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            
            self.status_updated.emit(error_msg)
            result = ObjectLoadResult()
            result.conversion_errors.append(str(e))
            self.finished_loading.emit(result)

    def cleanup_duplicate_xml_files(self, worldsectors_path):
        """Remove duplicate .data.xml files, keep only .converted.xml"""
        try:
            duplicate_files = []
            
            for file in os.listdir(worldsectors_path):
                if file.endswith(".data.xml") and not file.endswith(".converted.xml"):
                    # Check if corresponding .converted.xml exists
                    base_name = file.replace(".data.xml", "")
                    converted_file = base_name + ".data.fcb.converted.xml"
                    converted_path = os.path.join(worldsectors_path, converted_file)
                    
                    if os.path.exists(converted_path):
                        # Remove the duplicate .data.xml file
                        duplicate_path = os.path.join(worldsectors_path, file)
                        duplicate_files.append(duplicate_path)
            
            # Remove duplicate files
            for duplicate_file in duplicate_files:
                try:
                    os.remove(duplicate_file)
                    print(f"Removed duplicate file: {os.path.basename(duplicate_file)}")
                except Exception as e:
                    print(f"Error removing {duplicate_file}: {e}")
            
            if duplicate_files:
                print(f"Cleaned up {len(duplicate_files)} duplicate .data.xml files")
            else:
                print("No duplicate files found")
                
        except Exception as e:
            print(f"Error during cleanup: {e}")

    def _determine_object_map(self, obj):
        """Determine which map an object belongs to based on its coordinates - ENHANCED"""
        if not self.grid_config or not self.grid_config.maps:
            print(f"No grid config available for object {obj.name}")
            return None
            
        # Convert object coordinates to sector coordinates
        sector_x = int(obj.x / self.grid_config.sector_granularity)
        sector_y = int(obj.z / self.grid_config.sector_granularity)  # Note: using Z for Y-axis
        
        print(f"Object {obj.name} at ({obj.x:.1f}, {obj.y:.1f}, {obj.z:.1f}) -> sector ({sector_x}, {sector_y})")
        
        # Check each map to see if object belongs to it
        for map_info in self.grid_config.maps:
            min_sector_x = map_info.sector_offset_x
            min_sector_y = map_info.sector_offset_y
            max_sector_x = min_sector_x + map_info.count_x
            max_sector_y = min_sector_y + map_info.count_y
            
            if (min_sector_x <= sector_x < max_sector_x and 
                min_sector_y <= sector_y < max_sector_y):
                print(f"Object {obj.name} belongs to map {map_info.name}")
                return map_info.name
        
        print(f"Object {obj.name} does not belong to any map")
        return None

    @staticmethod
    def extract_objects_from_data_xml(xml_file_path, sector_path=None):
        """
        Extract all Entity objects from a .data.xml file
        
        Args:
            xml_file_path (str): Path to the .data.xml file
            sector_path (str): Path to the sector folder
            
        Returns:
            List[ObjectEntity]: List of parsed objects
        """
        objects = []
        
        try:
            print(f"\n=== Processing {os.path.basename(xml_file_path)} ===")
            
            tree = ET.parse(xml_file_path)
            root = tree.getroot()
            
            print(f"Root element type: {root.get('type')}")
            
            # Handle different file types
            if root.get("type") == "WorldSector":
                print("Processing as WorldSector file")
                
                # Extract WorldSector information
                sector_id = None
                sector_x = None
                sector_y = None
                
                id_elem = root.find("./value[@name='Id']")
                if id_elem is not None and id_elem.text:
                    try:
                        sector_id = int(id_elem.text)
                    except (ValueError, TypeError):
                        pass
                
                x_elem = root.find("./value[@name='X']")
                if x_elem is not None and x_elem.text:
                    try:
                        sector_x = int(x_elem.text)
                    except (ValueError, TypeError):
                        pass
                
                y_elem = root.find("./value[@name='Y']")
                if y_elem is not None and y_elem.text:
                    try:
                        sector_y = int(y_elem.text)
                    except (ValueError, TypeError):
                        pass
                
                print(f"WorldSector {sector_id} at ({sector_x}, {sector_y})")
            
            elif "landmark" in os.path.basename(xml_file_path).lower():
                print("Processing as Landmark file")
            
            else:
                print(f"Processing as {root.get('type', 'unknown')} file")
            
            # Find all Entity objects anywhere in the file (FCBConverter format)
            entity_elements = root.findall(".//object[@name='Entity']")
            
            print(f"Found {len(entity_elements)} Entity objects")
            
            # Parse each Entity
            for i, entity_elem in enumerate(entity_elements):
                print(f"\n--- Processing Entity {i+1}/{len(entity_elements)} ---")
                
                obj_entity = ObjectParser.parse_object_from_xml(
                    entity_elem, 
                    source_file=xml_file_path,
                    sector_path=sector_path
                )
                
                if obj_entity is not None:
                    objects.append(obj_entity)
                    print(f"Added {obj_entity.name} to objects list")
                else:
                    print("Failed to parse entity")
            
            print(f"\n=== Successfully parsed {len(objects)} objects from {os.path.basename(xml_file_path)} ===")
            
        except Exception as e:
            print(f"Error extracting objects from {xml_file_path}: {str(e)}")
            import traceback
            traceback.print_exc()
        
        return objects
        
    def debug_check_xml_coordinates(self, entity_name):
        """Debug method to check if coordinates are actually in the XML files"""
        if not hasattr(self, 'worldsectors_trees'):
            print("No worldsectors_trees available")
            return
        
        for file_path, tree in self.worldsectors_trees.items():
            root = tree.getroot()
            
            # Find entities with the given name (FCBConverter format)
            for entity_elem in root.findall(".//object[@name='Entity']"):
                name_field = entity_elem.find("./field[@name='hidName']")
                if name_field is not None and _get_str_val(name_field) == entity_name:
                    print(f"DEBUG: Found {entity_name} in {os.path.basename(file_path)}")

                    for field_name in ('hidPos', 'hidPos_precise'):
                        pf = entity_elem.find(f"./field[@name='{field_name}']")
                        if pf is not None:
                            pos_value = pf.get('value-Vector3', '')
                            if pos_value:
                                print(f"  {field_name} in XML: {pos_value}")


class LevelFileConfig:
    """Configuration for which level files to load and convert"""
    
    def __init__(self):
        # Main files that are always loaded
        self.main_files = {
            "mapsdata": {
                "enabled": True,
                "required": True,  # Cannot be disabled
                "patterns": ["mapsdata.fcb", "mapsdata.xml", "*.mapsdata.xml", "*.mapsdata.fcb"],
                "description": "Map Data (Main entities)"
            },
            "entitylibrary_full": {
                "enabled": True,
                "required": False,
                "patterns": ["entitylibrary_full.fcb", "entitylibrary_full.xml"],
                "description": "Entity Library (Entity definitions)"
            },
            "managers": {
                "enabled": True,
                "required": False,
                "patterns": [".managers.fcb", ".managers.xml", "managers.fcb", "managers.xml", "*.managers.fcb", "*.managers.xml"],
                "description": "Managers (Game systems)"
            },
            "omnis": {
                "enabled": True,
                "required": False,
                "patterns": [".omnis.fcb", ".omnis.xml", "omnis.fcb", "omnis.xml", "*.omnis.fcb", "*.omnis.xml"],
                "description": "Omnis (Universal objects)"
            },
            "sectorsdep": {
                "enabled": True,
                "required": False,
                "patterns": ["sectorsdep.fcb", "sectorsdep.xml", "sectordep.fcb", "sectordep.xml"],
                "description": "Sector Dependencies"
            }
        }
        
        # Optional files that are now disabled by default
        self.optional_files = {
            "preload": {
                "enabled": False,  # Disabled by default
                "patterns": [".preload.xml", "preload.xml"],
                "description": "Preload Data"
            },
            "particles": {
                "enabled": False,  # Disabled by default
                "patterns": ["_deploadnewparticles_*.xml"],
                "description": "Particle Data"
            },
            "game": {
                "enabled": False,  # Disabled by default
                "patterns": ["*.game.xml"],
                "description": "Game Configuration"
            }
        }
    
    def get_enabled_files(self):
        """Get list of enabled file types"""
        enabled = {}
        
        # Add enabled main files
        for file_type, config in self.main_files.items():
            if config["enabled"]:
                enabled[file_type] = config
        
        # Add enabled optional files
        for file_type, config in self.optional_files.items():
            if config["enabled"]:
                enabled[file_type] = config
        
        return enabled
    
    def is_file_enabled(self, file_type):
        """Check if a specific file type is enabled"""
        if file_type in self.main_files:
            return self.main_files[file_type]["enabled"]
        elif file_type in self.optional_files:
            return self.optional_files[file_type]["enabled"]
        return False
    
    def set_file_enabled(self, file_type, enabled):
        """Enable or disable a file type"""
        if file_type in self.main_files:
            # Cannot disable required files
            if self.main_files[file_type].get("required", False) and not enabled:
                print(f"Cannot disable required file type: {file_type}")
                return False
            self.main_files[file_type]["enabled"] = enabled
            return True
        elif file_type in self.optional_files:
            self.optional_files[file_type]["enabled"] = enabled
            return True
        return False
        
class RotatingLoadingIcon(QLabel):
    """Custom rotating loading icon widget"""
    
    def __init__(self, background_path, rotating_path, parent=None):
        super().__init__(parent)
        
        # Load images
        self.background = QPixmap(background_path)
        self.rotating = QPixmap(rotating_path)
        
        # Check if images loaded
        if self.background.isNull():
            print(f"Failed to load background: {background_path}")
            self.background = QPixmap(64, 64)
            self.background.fill(Qt.GlobalColor.lightGray)
        
        if self.rotating.isNull():
            print(f"Failed to load rotating image: {rotating_path}")
            self.rotating = QPixmap(64, 64)
            self.rotating.fill(Qt.GlobalColor.blue)
        
        # Set widget size to match images
        size = max(self.background.width(), self.background.height())
        self.setFixedSize(size, size)
        
        # Rotation angle
        self.rotation_angle = 0
        
        # Setup rotation timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.rotate)
        self.timer.start(100)  # Update every 100ms
    
    def rotate(self):
        """Rotate the icon smoothly and continuously"""
        self.rotation_angle = (self.rotation_angle + 30) % 360  # Rotate 30 degrees each frame
        self.update()
    
    def paintEvent(self, event):
        """Paint the rotating loading icon - works in both 2D and 3D modes"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Draw background centered
        if hasattr(self, 'background') and self.background is not None:
            bg_x = (self.width() - self.background.width()) // 2
            bg_y = (self.height() - self.background.height()) // 2
            painter.drawPixmap(bg_x, bg_y, self.background)

        # Draw rotated foreground
        if hasattr(self, 'rotating') and self.rotating is not None:
            painter.save()
            painter.translate(self.width() / 2, self.height() / 2)
            painter.rotate(self.rotation_angle)
            painter.translate(-self.rotating.width() / 2, -self.rotating.height() / 2)
            painter.drawPixmap(0, 0, self.rotating)
            painter.restore()

        painter.end()

    def stop(self):
        """Stop the rotation"""
        self.timer.stop()

class EnhancedProgressDialog(QDialog):
    """Enhanced progress dialog with rotating loading icon and log - auto-selects icon based on game mode"""
    
    cancelled = pyqtSignal()  # Signal for cancellation
    
    def __init__(self, title, parent=None, game_mode="avatar"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumSize(800, 520)
        
        # DEBUG: Print received game mode
        print(f"EnhancedProgressDialog: Received game_mode = '{game_mode}'")
        
        layout = QVBoxLayout(self)
        
        # Add rotating icons at the top
        icon_layout = QHBoxLayout()
        icon_layout.addStretch()
        
        # Select icon paths based on game mode
        if game_mode == "farcry2":
            # FC2: Use same image for background and rotating (single icon that rotates)
            background_path = "loading_logo2.png"
            rotating_path = "loading_logo3.png"
            print(f"EnhancedProgressDialog: Using FC2 icons: {background_path}")
        else:  # avatar
            # Avatar: Use default icons
            background_path = "default_i3.png"
            rotating_path = "default_i5.png"
            print(f"EnhancedProgressDialog: Using Avatar icons: {background_path}, {rotating_path}")
        
        # Rotating icons
        self.loading_icon = RotatingLoadingIcon(background_path, rotating_path)
        icon_layout.addWidget(self.loading_icon)
        icon_layout.addStretch()
        
        layout.addLayout(icon_layout)
        
        # Status label
        self.status_label = QLabel("Initializing, please wait...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        # Log box
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(200)
        self.log_box.setMaximumHeight(320)
        self.log_box.setStyleSheet("""
            QTextEdit {
                background-color: #333333;
                color: #d4d4d4;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 16px;
                border: 1px solid #3e3e3e;
                border-radius: 8px;
                padding: 8px;
            }
        """)
        layout.addWidget(self.log_box)
        
        # Cancel button
        self.cancel_button = QPushButton("Cancel")
        layout.addWidget(self.cancel_button)
        
        self.was_cancelled = False
        self.is_complete = False  # Track if operation completed
        self.cancel_button.clicked.connect(self.on_cancel)

    def closeEvent(self, event):
        # Don't call shutdown_cache_manager here - it blocks the UI
        if not self.was_cancelled and not self.is_complete:
            self.on_cancel()
            event.ignore()
        else:
            # Stop the icon before closing
            self.stop_icon()
            event.accept()

    def on_cancel(self):
        if not self.was_cancelled:
            self.was_cancelled = True
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("Cancelling...")
            self.append_log("Cancellation requested...")
            self.cancelled.emit()

    def set_status(self, text):
        self.status_label.setText(text)

    def set_progress(self, value):
        self.progress_bar.setValue(int(value))

    def append_log(self, message):
        if not message or not message.strip():
            return
        self.log_box.append(message)
        scrollbar = self.log_box.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def stop_icon(self):
        """Stop the rotating icon"""
        if hasattr(self, "loading_icon"):
            self.loading_icon.stop()

    def mark_complete(self):
        """Mark operation as complete - allows dialog to close"""
        self.is_complete = True