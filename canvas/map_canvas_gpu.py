"""Main GPU-accelerated map canvas - 2D AND 3D VERSION
Integrates 3D camera view with existing 2D level editor
"""
import os
import ctypes
from time import time
import math
import numpy as np
import OpenGL.GL as gl
from PyQt6.QtGui import QMatrix4x4, QVector3D
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPainter, QColor, QPixmap, QTransform, QFont, QPen, QVector4D, QCursor
from PyQt6.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem, QPushButton, QApplication

# View mode constants
MODE_TOPDOWN = 0
MODE_3D = 1

# Import GPU components
try:
    from PyQt6.QtOpenGLWidgets import QOpenGLWidget
    from OpenGL.GL import *
    from OpenGL.GLU import *
    import OpenGL.GL as gl
    OPENGL_AVAILABLE = True
    print("OpenGL libraries loaded successfully")
except ImportError as e:
    from PyQt6.QtWidgets import QWidget as QOpenGLWidget
    OPENGL_AVAILABLE = False
    print(f"OpenGL not available ({e}) - falling back to CPU rendering")

# Import modular components (your existing ones)
from .terrain_renderer import TerrainRenderer
from .grid_renderer import GridRenderer
from .entity_renderer import EntityRenderer
from .gizmo_renderer import GizmoRenderer
from .gizmo_3d import Gizmo3D, HANDLE_NONE as GIZMO3D_HANDLE_NONE
from .input_handler import InputHandler
from .camera_controller import CameraController
from .opengl_utils import OpenGLUtils
from .model_loader import ModelLoader
from .undo_redo import UndoRedoManager, MoveCommand, RotateCommand
from water_mesh_editor import ImprovedWaterMeshEditor
from water_plane_renderer import WaterPlaneRenderer, strip_baked_water
from .movie_renderer import draw_movie_paths_2d, render_movie_paths_3d

"""Enhanced 3D Camera with 2D-style smooth movement"""
import numpy as np

class Camera3D:
    """3D Camera for FPS-style navigation with smooth acceleration like 2D camera"""
    
    def __init__(self):
        self.position = np.array([0.0, 0.0, 0.0], dtype=float)
        self.yaw = -90.0  # Looking along -Z
        self.pitch = -30.0  # Looking down slightly
        
        # Movement state flags (like 2D camera)
        self.MOVE_FORWARD = 0
        self.MOVE_BACKWARD = 0
        self.MOVE_LEFT = 0
        self.MOVE_RIGHT = 0
        self.MOVE_UP = 0
        self.MOVE_DOWN = 0
        
        # SHIFT modifier state for speed boost (like 2D camera)
        self.shift_modifier = False
        
        # SMOOTH MOVEMENT - matching 2D camera settings
        self.movement_speed = 1.0  # Base movement speed
        self.shift_speed_multiplier = 2.5  # Speed multiplier when SHIFT is held
        self.movement_acceleration = 1.3  # Acceleration
        self.max_movement_speed = 20.0  # Maximum movement speed (normal)
        self.max_movement_speed_shift = 50.0  # Maximum movement speed with SHIFT
        self.current_movement_speed = self.movement_speed
        
        # Frame rate independent movement
        self.last_update_time = 0
        self.target_fps = 60.0
        self.frame_time = 1.0 / self.target_fps
        
        # Mouse sensitivity
        self.sensitivity = 0.2
        
        self.update_vectors()
        print("Camera3D initialized with 2D-style smooth movement")
    
    def is_point_in_frustum(self, point, vfov_deg, aspect, near, far, padding=1.4):
        """Test whether a world-space point lies inside the view frustum.

        Args:
            point:    np.array world position to test
            vfov_deg: vertical field-of-view in degrees
            aspect:   viewport width / height
            near:     near clip distance
            far:      far clip distance
            padding:  multiplier on the half-angle bounds (1.0 = exact frustum,
                      1.4 = 40% larger to prevent edge pop-in)
        """
        to_point = point - self.position

        # Depth along view direction
        z = np.dot(to_point, self.forward)
        if z < near or z > far:
            return False

        # Half-angle tangent (vfov_deg is the FULL vertical angle)
        half_tan = np.tan(np.radians(vfov_deg) * 0.5) * padding

        # Vertical bounds
        v = z * half_tan
        y = np.dot(to_point, self.up)
        if abs(y) > v:
            return False

        # Horizontal bounds
        h = v * aspect
        x = np.dot(to_point, self.right)
        if abs(x) > h:
            return False

        return True

    def get_distance_to_point(self, point):
        """Get distance from camera to a point"""
        return np.linalg.norm(point - self.position)

    def update_vectors(self):
        rad_yaw = np.radians(self.yaw)
        rad_pitch = np.radians(self.pitch)

        forward = np.array([
            np.cos(rad_pitch) * np.cos(rad_yaw),
            np.sin(rad_pitch),
            np.cos(rad_pitch) * np.sin(rad_yaw)
        ])

        self.forward = forward / np.linalg.norm(forward)

        world_up = np.array([0.0, 1.0, 0.0])

        self.right = np.cross(world_up, self.forward)
        self.right /= np.linalg.norm(self.right)

        self.up = np.cross(self.forward, self.right)
        self.up /= np.linalg.norm(self.up)
    
    def set_shift_modifier(self, shift_pressed):
        """Set the shift modifier state for speed boost (like 2D camera)"""
        old_shift = self.shift_modifier
        self.shift_modifier = shift_pressed
        
        # Reset movement speed when shift state changes
        if old_shift != shift_pressed:
            if shift_pressed:
                self.current_movement_speed = self.movement_speed * self.shift_speed_multiplier
            else:
                self.current_movement_speed = self.movement_speed
    
    def get_effective_movement_speed(self):
        """Get the effective movement speed based on shift modifier"""
        if self.shift_modifier:
            return self.movement_speed * self.shift_speed_multiplier
        return self.movement_speed
    
    def get_effective_max_speed(self):
        """Get the effective maximum speed based on shift modifier"""
        if self.shift_modifier:
            return self.max_movement_speed_shift
        return self.max_movement_speed
    
    def set_movement_flag(self, key_direction, pressed):
        """Set movement flags based on key presses (like 2D camera)"""
        old_flags = (self.MOVE_FORWARD, self.MOVE_BACKWARD, self.MOVE_LEFT, 
                     self.MOVE_RIGHT, self.MOVE_UP, self.MOVE_DOWN)
        
        if key_direction == "FORWARD":
            self.MOVE_FORWARD = 1 if pressed else 0
        elif key_direction == "BACKWARD":
            self.MOVE_BACKWARD = 1 if pressed else 0
        elif key_direction == "LEFT":
            self.MOVE_LEFT = 1 if pressed else 0
        elif key_direction == "RIGHT":
            self.MOVE_RIGHT = 1 if pressed else 0
        elif key_direction == "UP":
            self.MOVE_UP = 1 if pressed else 0
        elif key_direction == "DOWN":
            self.MOVE_DOWN = 1 if pressed else 0
        
        # Reset movement speed when starting new movement (considering shift state)
        if pressed and not any(old_flags):
            self.current_movement_speed = self.get_effective_movement_speed()
        
        new_flags = (self.MOVE_FORWARD, self.MOVE_BACKWARD, self.MOVE_LEFT, 
                     self.MOVE_RIGHT, self.MOVE_UP, self.MOVE_DOWN)
    
    def needs_update(self):
        """Check if camera movement requires view update"""
        return any([self.MOVE_FORWARD, self.MOVE_BACKWARD, self.MOVE_LEFT, 
                   self.MOVE_RIGHT, self.MOVE_UP, self.MOVE_DOWN])
    
    def update_movement(self):
        """Update camera movement with fixed distance per keypress"""
        if not self.needs_update():
            return False
        
        # Fixed movement distance
        movement_distance = 0.1
        
        # Apply SHIFT multiplier if active
        if self.shift_modifier:
            movement_distance *= 20.0  # Increased from 2.5 to 5.0
        
        moved = False
        
        # Apply movement in all 6 directions
        if self.MOVE_FORWARD:
            self.position += self.forward * movement_distance
            moved = True
        if self.MOVE_BACKWARD:
            self.position -= self.forward * movement_distance
            moved = True
        if self.MOVE_LEFT:
            self.position += self.right * movement_distance
            moved = True
        if self.MOVE_RIGHT:
            self.position -= self.right * movement_distance
            moved = True
        if self.MOVE_UP:
            self.position += self.up * movement_distance
            moved = True
        if self.MOVE_DOWN:
            self.position -= self.up * movement_distance
            moved = True
        
        return moved
    
    def rotate(self, dx, dy):
        """Rotate camera view"""
        self.yaw += dx * self.sensitivity
        self.pitch -= dy * self.sensitivity
        self.pitch = np.clip(self.pitch, -89, 89)
        self.update_vectors()
    
    def get_look_at(self):
        """Get the point the camera is looking at"""
        return self.position + self.forward
    
    def pan(self, dx, dy):
        """Pan camera position in screen space"""
        # Scale pan speed based on distance or a fixed sensitivity
        pan_speed = 0.01  # Adjust this value as needed
        
        # Move right based on horizontal mouse movement
        self.position -= self.right * dx * pan_speed
        
        # Move up based on vertical mouse movement  
        self.position += self.up * dy * pan_speed

def draw_3d_grid(canvas, size=5120, sector_size=64):
    """Draw 3D grid for Avatar or FC2 worlds, matching the 2D grid exactly."""
    
    # --------------------
    # Detect FC2 mode
    is_fc2 = getattr(canvas, 'is_fc2_world', False) or getattr(canvas, 'game_mode', '') == 'farcry2'
    if not is_fc2 and hasattr(canvas, 'editor'):
        is_fc2 = getattr(canvas.editor, 'is_fc2_world', False) or getattr(canvas.editor, 'game_mode', '') == 'farcry2'

    # --------------------
    if is_fc2:
        # FC2 grid: 10x10 world cells, each 16x16 sectors
        sector_size = 64
        sectors_per_world = 16
        world_cell_size = sector_size * sectors_per_world  # 1024 units
        world_grid_size = 10

        # Grid limit (add extra padding)
        grid_limit = world_cell_size * (world_grid_size + 2) // 2  # Ãƒâ€šÃ‚Â±6144

        # Minor sector lines (gray)
        glLineWidth(1.0)
        glColor3f(0.2, 0.2, 0.2)
        glBegin(GL_LINES)
        for wx in range(-world_grid_size // 2, world_grid_size // 2):
            for wz in range(-world_grid_size // 2, world_grid_size // 2):
                cell_origin_x = wx * world_cell_size
                cell_origin_z = wz * world_cell_size
                for i in range(1, sectors_per_world):
                    x = cell_origin_x + i * sector_size
                    glVertex3f(x, 0, cell_origin_z)
                    glVertex3f(x, 0, cell_origin_z + world_cell_size)
                    z = cell_origin_z + i * sector_size
                    glVertex3f(cell_origin_x, 0, z)
                    glVertex3f(cell_origin_x + world_cell_size, 0, z)
        glEnd()

        # World cell boundaries (blue, thick)
        glLineWidth(3.0)
        glColor3f(0.0, 0.3, 0.8)
        glBegin(GL_LINES)
        for wx in range(-world_grid_size // 2, world_grid_size // 2 + 1):
            for wz in range(-world_grid_size // 2, world_grid_size // 2 + 1):
                x0 = wx * world_cell_size
                z0 = wz * world_cell_size
                x1 = x0 + world_cell_size
                z1 = z0 + world_cell_size
                # Vertical line
                glVertex3f(x0, 0, z0)
                glVertex3f(x0, 0, z1)
                # Horizontal line
                glVertex3f(x0, 0, z0)
                glVertex3f(x1, 0, z0)
        # Draw the outermost right and bottom edges explicitly
        outer = world_grid_size // 2 * world_cell_size
        glVertex3f(outer, 0, -outer)
        glVertex3f(outer, 0, outer)
        glVertex3f(-outer, 0, outer)
        glVertex3f(outer, 0, outer)
        glEnd()
    
    else:
        # Avatar grid
        major_interval = 5
        major_size = sector_size * major_interval
        grid_limit = size

        # Minor lines
        glLineWidth(1.0)
        glColor3f(0.2, 0.2, 0.2)
        glBegin(GL_LINES)
        for x in range(-grid_limit, grid_limit + 1, sector_size):
            if x % major_size != 0 and x != 0:
                glVertex3f(x, 0, -grid_limit)
                glVertex3f(x, 0, grid_limit)
                glVertex3f(-grid_limit, 0, x)
                glVertex3f(grid_limit, 0, x)
        glEnd()

        # Major lines
        glLineWidth(3.0)
        glColor3f(0.0, 0.0, 0.0)
        glBegin(GL_LINES)
        for x in range(-grid_limit, grid_limit + 1, major_size):
            if x != 0:
                glVertex3f(x, 0, -grid_limit)
                glVertex3f(x, 0, grid_limit)
                glVertex3f(-grid_limit, 0, x)
                glVertex3f(grid_limit, 0, x)
        glEnd()

    # Axes
    glLineWidth(5.0)
    glBegin(GL_LINES)
    glColor3f(1.0, 0.0, 0.0)
    glVertex3f(-grid_limit, 0, 0)
    glVertex3f(grid_limit, 0, 0)
    glColor3f(0.0, 1.0, 0.0)
    glVertex3f(0, 0, -grid_limit)
    glVertex3f(0, 0, grid_limit)
    glEnd()
    glLineWidth(1.0)


def _ray_aabb_intersect(ray_origin, ray_dir, box_min, box_max):
    """Slab-method ray vs AABB. Returns distance t along the ray, or None on miss."""
    t_min = -np.inf
    t_max = np.inf
    for i in range(3):
        if abs(ray_dir[i]) < 1e-8:
            if ray_origin[i] < box_min[i] or ray_origin[i] > box_max[i]:
                return None
        else:
            t1 = (box_min[i] - ray_origin[i]) / ray_dir[i]
            t2 = (box_max[i] - ray_origin[i]) / ray_dir[i]
            t_min = max(t_min, min(t1, t2))
            t_max = min(t_max, max(t1, t2))
    if t_max < max(t_min, 0.0):
        return None
    return max(t_min, 0.0)


def _make_rot_x(deg):
    r = np.radians(deg); c, s = np.cos(r), np.sin(r)
    return np.array([[1,0,0],[0,c,-s],[0,s,c]], dtype=np.float64)

def _make_rot_y(deg):
    r = np.radians(deg); c, s = np.cos(r), np.sin(r)
    return np.array([[c,0,s],[0,1,0],[-s,0,c]], dtype=np.float64)

def _make_rot_z(deg):
    r = np.radians(deg); c, s = np.cos(r), np.sin(r)
    return np.array([[c,-s,0],[s,c,0],[0,0,1]], dtype=np.float64)


def _ray_triangle_mesh_intersect(ray_o, ray_d, vertices, indices):
    """Vectorised Möller-Trumbore ray vs triangle mesh.

    ray_o, ray_d: (3,) float64 in model-local space.
    vertices: float array, any shape — reshaped to (N, 3).
    indices:  int array, any shape  — reshaped to (M, 3) triangle index triples.

    The t parameter is in the same units as the world-space ray (the local-space
    ray direction is not normalised, so t_local == t_world).

    Returns minimum t > 0, or None on miss.
    """
    verts = np.asarray(vertices, dtype=np.float64).reshape(-1, 3)
    tris  = np.asarray(indices,  dtype=np.int64).reshape(-1, 3)

    v0 = verts[tris[:, 0]]   # (M, 3)
    v1 = verts[tris[:, 1]]
    v2 = verts[tris[:, 2]]

    edge1 = v1 - v0
    edge2 = v2 - v0

    h = np.cross(ray_d, edge2)                       # (M, 3)
    a = np.einsum('ij,ij->i', edge1, h)              # (M,)

    valid  = np.abs(a) > 1e-8
    a_safe = np.where(valid, a, 1.0)
    f      = np.where(valid, 1.0 / a_safe, 0.0)

    s = ray_o - v0                                   # (M, 3)
    u = f * np.einsum('ij,ij->i', s, h)
    valid &= (u >= 0.0) & (u <= 1.0)

    q = np.cross(s, edge1)                           # (M, 3)
    v = f * (q @ ray_d)                              # (M,)
    valid &= (v >= 0.0) & ((u + v) <= 1.0)

    t = f * np.einsum('ij,ij->i', edge2, q)          # (M,)
    valid &= (t > 1e-8)

    if not np.any(valid):
        return None
    return float(np.min(np.where(valid, t, np.inf)))


class MapCanvas(QOpenGLWidget):
    """Main GPU-accelerated canvas widget - 2D AND 3D VERSION"""
    
    # Signals
    entitySelected = pyqtSignal(object)
    position_update = pyqtSignal(object, tuple)
    angle_update = pyqtSignal(object, tuple)   # (entity, (ax, ay, az))
    move_points = pyqtSignal(float, float, float)
    height_update = pyqtSignal(float)
    create_waypoint = pyqtSignal(float, float)
    rotate_current = pyqtSignal(object)

    def __init__(self, parent=None):
        """Initialize MapCanvas - 2D AND 3D"""
        super().__init__(parent)
        self.main_window = parent
        
        self.setMinimumSize(600, 400)

        # View mode (0 = 2D, 1 = 3D)
        self.mode = MODE_TOPDOWN
        
        # Game mode tracking
        self.game_mode = "avatar"
        self.is_fc2_world = False
        
        # OpenGL setup
        self.opengl_initialized = False
        self.use_gpu_rendering = OPENGL_AVAILABLE
        
        # Display list for cube geometry
        self.cube_display_list = None
        self._cube_batch = None          # instanced marker-cube renderer (canvas/cube_batch.py)
        self._use_cube_instancing = True # F-key/debug switch; falls back to display list if off
        self._line_batch = None          # batched wireframe-overlay renderer (canvas/line_batch.py)
        self._use_overlay_batch = True   # falls back to immediate-mode if off/unavailable
        self._ov_matrix = None           # cached line_batch.overlay_matrix
        self._ov_transform = None        # cached line_batch.transform_points
        self._wire_cube_seg = None       # cached unit wireframe-cube segments
        
        # Core canvas state
        self.entities = []
        self.selected_entity = None
        self.selected = []
        self.selected_positions = []
        self.selected_rotations = []
        self.scale_factor = 1.0

        # managers.xml vPos links: {entity_id_str: [vPos XML field elements]}
        # Populated once when an entity is selected; cleared on deselect.
        self._managers_vpos_links = {}
        
        # Canvas offset attributes (2D mode)
        self.offset_x = 0
        self.offset_y = 0
        
        self.grid_config = None
        self.current_map = None
        self.unified_mode = False  # True when all sectors loaded together via load_all_worldsectors
        self.dirty_sectors: set = set()  # sector IDs that need reconverting on save (unified mode)

        # View options
        self.show_grid = True
        self.show_entities = True
        self.terrain_snap_enabled = False
        self._snap_badge_rect = None   # set by _draw_3d_ui_overlays, used for click detection

        # Terrain edit mode (3D in-viewport painting)
        self.terrain_edit_mode = False
        self._terrain_edit_badge_rect = None
        self._terrain_edit_hit = None    # (wx, wy, wz) last unproject hit
        self._terrain_edit_pressing = False
        self._terrain_edit_stroking = False
        # Inline brush controls (shown when terrain_edit_mode is active)
        self._te_tool = 'raise'
        self._te_size = 20
        self._te_strength = 30
        self._te_target_h = 100.0
        self._te_brush_type = 'circle'
        self._te_drag_dir   = (0.0, 1.0)   # normalised drag direction (unused for slope — kept for compat)
        self._te_prev_hc    = None          # last heightmap coord
        self._te_brush_len  = 32            # rectangle/slope length
        self._te_brush_wid  = 12            # rectangle/slope width
        self._te_slope_angle = 0            # slope brush fixed rotation (degrees)
        # Canvas-owned terrain data (loaded from sdat on first EDIT TERRAIN click)
        self._terrain_data = None
        # GL mesh arrays rebuilt from heightmap whenever terrain is edited
        self._te_mesh_verts   = None
        self._te_mesh_colors  = None
        self._te_mesh_indices = None
        # Debounce timer so mesh only rebuilds ~50 ms after the last brush sample
        self._te_mesh_rebuild_timer = QTimer(self)
        self._te_mesh_rebuild_timer.setSingleShot(True)
        self._te_mesh_rebuild_timer.setInterval(50)
        self._te_mesh_rebuild_timer.timeout.connect(self._rebuild_terrain_edit_mesh)

        # Terrain texture paint mode
        self.terrain_paint_mode = False
        self._ttp = None             # active TerrainTexturePainter instance
        self._ttp_painters = {}      # {'mask': ttp, 'diffuse': ttp, 'color': ttp}
        self._tp_active_tex_key = 'mask'
        self._te_tex_id = None       # GL texture object ID (kept for save round-trip)
        self._te_mesh_uvs = None     # (N, 2) float32 UV array
        self._te_paint_color = (255, 0, 0, 255)
        self._tp_pressing = False
        self._terrain_paint_badge_rect = None
        self._tp_paint_channel = 0   # 0=R  1=G  2=B  3=Black
        self._tp_gizmo_rects = []
        self._te_paint_colors = None # (N, 3) float32 — vertex colors for paint display
        self._tp_stamp_tex = None    # (H, W, 4) uint8 — texture stamp for diffuse painting
        self._tp_brush_shape = 'circle'  # 'circle' | 'square' | 'diamond' | 'triangle'
        self._tp_tile_meters = 2.0       # world meters per one stamp tile repeat
        self._tp_feather = 50            # 0=hard edge, 100=full gradient

        # Per-source entity visibility filters
        self.show_worldsector_entities = True
        self.show_mapsdata_entities    = True
        self.show_omnis_entities       = True
        self.show_landmark_entities    = True
        self.show_trigger_zones        = True

        # *** NEW: 3D rendering toggles (independent from 2D toggles) ***
        self.show_3d_hud = True          # Toggle HUD overlay (camera info, controls)
        self.show_3d_grid = True         # Toggle 3D grid (independent from 2D grid)
        self.show_3d_cubes = True        # Toggle fallback cubes (models always render)
        
        # Rendering state
        self.entities_modified = False
        self.selection_modified = False
        self.last_mouse_world_pos = (0, 0)

        # 3D lighting
        self._light_elevation = 0   # degrees; azimuth — horizontal rotation around world Y
        self._light_pitch     = 270  # degrees; elevation (0=horizon, 90=overhead, 180=below, 270=horizon again)

        # Day/night cycle. When enabled, time_of_day (0=midnight, .25=sunrise,
        # .5=noon, .75=sunset) drives the sun direction/colour, ambient, sky colour
        # and the bioluminescence night factor (emission glows at night, off by
        # day). Off by default → the static sun rig is unchanged. F4 toggles play.
        self.day_night_enabled = False
        self.time_of_day = 0.5          # noon
        self._daynight_play = False
        self._daynight_speed = 1.0 / 600.0   # ~20 s full cycle at the 30 FPS glow tick
        self._night_factor = 0.0        # 0 day → 1 night (read by the bio shaders)
        self._sun_elev_sin = 1.0        # sin(sun elevation), set by _apply_day_night
        self._sun_az = 0.0              # sun azimuth (editor world), set by _apply_day_night
        self._night_sky = None          # lazily-loaded star-dome (assets/avatar/skybox/*.glb)
        self._sky_atmosphere = None     # lazily-built spectral daytime sky
        self._shadow_map = None         # lazily-built sun shadow map (canvas/shadow_map.py)
        self.shadows_enabled = True     # F7: sun shadows (only active when day/night + sun up)
        
        # Sector display
        self.show_sector_boundaries = False
        self.sector_data = []

        self.is_3d_mode = False

        # 3D Camera
        self.camera_3d = Camera3D()
        self.last_mouse_3d = None
        self.mouse_captured_3d = False

        self.camera_3d_initialized = False
        
        # Setup all rendering modules
        self.setup_renderers()

        self.model_loader = ModelLoader()

        self.setup_canvas()

        self.terrain_model = None
        # Multi-cell 3D terrain (FC2 5×5 grid): list of (model, world_x, world_y)
        self.terrain_models = []

        print(f"MapCanvas initialized - 2D AND 3D VERSION (OpenGL: {self.use_gpu_rendering})")

    def _key_light_pos(self):
        """World-space sun direction built from azimuth + elevation.
        Azimuth (_light_elevation): horizontal rotation 0–360°.
        Elevation (_light_pitch):   full 0–360° — 0/360=horizon, 90=overhead,
                                    180=below ground, 270=horizon from below."""
        az = math.radians(self._light_elevation)
        el = math.radians(self._light_pitch)
        ce = math.cos(el)
        se = math.sin(el)
        x = ce * math.cos(az + math.radians(45))
        y = se
        z = ce * math.sin(az + math.radians(45))
        return [x, y, z, 0.0]

    def set_light_elevation(self, angle):
        """Set sun azimuth (0–360°) and redraw."""
        self._light_elevation = int(angle) % 361
        self.update()

    def set_light_pitch(self, pitch):
        """Set sun elevation (0–360°, full circle) and redraw."""
        self._light_pitch = int(pitch) % 361
        self.update()

    def _daynight_factors(self):
        """From time_of_day → (sun_elevation -1..1, day 0..1, horizon 0..1).
        day smoothly ramps 0(night)→1(day) through dawn/dusk; horizon peaks when
        the sun is near the horizon (for warm dawn/dusk + sky tint)."""
        t = float(self.time_of_day) % 1.0
        phi = 2.0 * math.pi * (t - 0.25)         # -π/2 at midnight, 0 sunrise, π/2 noon, π sunset
        elev = math.sin(phi)                     # 1 noon, 0 horizon, -1 midnight
        d = max(0.0, min(1.0, (elev + 0.12) / 0.30))
        day = d * d * (3.0 - 2.0 * d)            # smoothstep
        horizon = max(0.0, 1.0 - min(1.0, abs(elev) / 0.28))
        return phi, elev, day, horizon

    def _apply_day_night(self):
        """Drive the sun/moon light, sky-fill, ambient and the night factor from
        time_of_day. Overrides the static rig (called only when day_night_enabled).
        Affects BOTH render paths since they read gl_LightSource/gl_LightModel."""
        phi, elev, day, horizon = self._daynight_factors()
        self._night_factor = 1.0 - day

        # Sun arcs east→west; y = elevation. Direction the light comes FROM (w=0).
        sun_dir = [math.cos(phi) * 0.7, elev, 0.35, 0.0]
        # For the atmosphere sky: sin(sun elevation) + sun azimuth + normalized dir.
        self._sun_elev_sin = elev
        self._sun_az = math.atan2(sun_dir[2], sun_dir[0])
        _sl = math.sqrt(sun_dir[0]**2 + sun_dir[1]**2 + sun_dir[2]**2) or 1.0
        self._sun_dir_world = (sun_dir[0] / _sl, sun_dir[1] / _sl, sun_dir[2] / _sl)
        # Warm sun by day, oranger near the horizon; dim cool moonlight at night.
        sr = 0.95
        sg = 0.90 - 0.30 * horizon
        sb = 0.82 - 0.55 * horizon
        moon = (0.10, 0.13, 0.22)
        sun = [day * sr + (1 - day) * moon[0],
               day * sg + (1 - day) * moon[1],
               day * sb + (1 - day) * moon[2], 1.0]
        glLightfv(GL_LIGHT0, GL_POSITION, sun_dir)
        glLightfv(GL_LIGHT0, GL_DIFFUSE, sun)
        glLightfv(GL_LIGHT0, GL_SPECULAR, [day * 0.5, day * 0.48, day * 0.44, 1.0])
        # Sky fill from above: blue daylight bounce, near-nothing at night.
        glLightfv(GL_LIGHT1, GL_POSITION, [0.0, 1.0, 0.0, 0.0])
        glLightfv(GL_LIGHT1, GL_DIFFUSE, [day * 0.30, day * 0.33, day * 0.42, 1.0])
        glLightfv(GL_LIGHT1, GL_SPECULAR, [0.0, 0.0, 0.0, 1.0])
        # Ambient: bright neutral day → dim blue night (keeps geometry faintly lit).
        glLightModelfv(GL_LIGHT_MODEL_AMBIENT,
                       [day * 0.38 + (1 - day) * 0.05,
                        day * 0.38 + (1 - day) * 0.06,
                        day * 0.42 + (1 - day) * 0.11, 1.0])

    def _sky_color(self):
        """Background/clear colour for the current time-of-day (placeholder sky
        until the atmosphere + night-dome are in): day blue → dawn/dusk orange →
        night near-black."""
        _phi, _elev, day, horizon = self._daynight_factors()
        day_sky = (0.45, 0.62, 0.85)
        night_sky = (0.015, 0.02, 0.05)
        r = night_sky[0] + (day_sky[0] - night_sky[0]) * day
        g = night_sky[1] + (day_sky[1] - night_sky[1]) * day
        b = night_sky[2] + (day_sky[2] - night_sky[2]) * day
        # Warm the horizon band at dawn/dusk.
        warm = horizon * day
        r += 0.35 * warm; g += 0.12 * warm; b -= 0.10 * warm
        return (max(0.0, min(1.0, r)), max(0.0, min(1.0, g)), max(0.0, min(1.0, b)))

    def initializeGL(self):
        """Initialize OpenGL context"""
        if not self.use_gpu_rendering:
            return

        try:
            print("Initializing OpenGL...")

            version = gl.glGetString(gl.GL_VERSION).decode()
            vendor = gl.glGetString(gl.GL_VENDOR).decode()
            renderer = gl.glGetString(gl.GL_RENDERER).decode()

            print(f"OpenGL Version: {version}")
            print(f"GPU Vendor: {vendor}")
            print(f"GPU Renderer: {renderer}")

            gl.glEnable(gl.GL_DEPTH_TEST)
            gl.glDepthFunc(gl.GL_LESS)  # Standard depth testing
            gl.glClearDepth(1.0)  # Clear to farthest value
            gl.glEnable(gl.GL_BLEND)
            gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)

            if hasattr(self, 'grid_renderer'):
                success = self.grid_renderer.initialize_gl()
                if success:
                    print("Grid renderer OpenGL initialized")
                else:
                    print("Grid renderer OpenGL initialization failed")
                    self.use_gpu_rendering = False
                    self.grid_renderer.use_opengl = False

            # Create cube display list
            self.cube_display_list = glGenLists(1)
            glNewList(self.cube_display_list, GL_COMPILE)
            self._draw_cube_geometry(0.1)
            glEndList()
            print("Created cube display list for efficient 3D rendering")

            # Don't load terrain here - it will be loaded per-level
            self.terrain_model = None
            print("Terrain will be loaded dynamically per level")

            self.opengl_initialized = True
            print("OpenGL initialization complete - 2D AND 3D")

        except Exception as e:
            print(f"OpenGL initialization failed: {e}")
            import traceback
            traceback.print_exc()
            self.use_gpu_rendering = False
            self.opengl_initialized = False

    def load_terrain_for_level(self, level_path, resolution=500000, scale=1.0):
        """
        Load or generate terrain for a specific level.
        
        Args:
            level_path: Path to the level directory (containing sdat folder)
            resolution: Triangle resolution for terrain mesh (default: 100000)
            scale: Meters per coordinate scale (default: 1.0)
        """
        if not self.opengl_initialized:
            print("OpenGL not initialized, skipping terrain load")
            return False

        # Always clear the previous terrain model before attempting to load new terrain.
        # This ensures a stale model from the previous level is never shown if loading
        # fails or no terrain exists for the new level (critical for frozen-exe builds).
        self.terrain_model = None

        try:
            from pathlib import Path
            import sys

            # Find sdat folder
            level_path = Path(level_path)
            possible_sdat_paths = [
                level_path / "generated" / "sdat",
                level_path / "sdat",
                level_path
            ]

            sdat_path = None
            file_ext = ".sdat" if getattr(self, 'game_mode', 'avatar') == "farcry2" else ".csdat"
            for path in possible_sdat_paths:
                if path.exists() and list(path.glob(f"*{file_ext}")):
                    sdat_path = path
                    break

            if not sdat_path:
                print(f"No sdat folder found for level: {level_path}")
                return False

            print(f"Generating 3D terrain from: {sdat_path}")
            print(f"  Resolution: {resolution} triangles")
            print(f"  Scale: {scale} meters per coordinate")

            # Import the terrain generator. Use a regular module import so this works
            # in both dev mode and frozen-exe builds (cx_Freeze bundles canvas.terrain_to_gltf).
            try:
                from canvas import terrain_to_gltf as terrain_gen
            except ImportError:
                # Fallback for unusual environments where canvas isn't a package on sys.path
                import importlib.util
                current_dir = os.path.dirname(os.path.abspath(__file__))
                parent_dir = os.path.dirname(current_dir)
                for candidate in [
                    os.path.join(current_dir, "terrain_to_gltf.py"),
                    os.path.join(parent_dir, "terrain_to_gltf.py"),
                ]:
                    if os.path.exists(candidate):
                        spec = importlib.util.spec_from_file_location("terrain_gen", candidate)
                        terrain_gen = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(terrain_gen)
                        break
                else:
                    print("terrain_to_gltf module not found")
                    return False

            # Generate terrain GLTF with custom resolution and scale
            print("Calling terrain generator...")
            gltf_path, bin_path = terrain_gen.generate_terrain_for_level(
                str(sdat_path),
                resolution=resolution,
                scale=scale,
                game_mode=getattr(self, 'game_mode', 'avatar')
            )
            
            if not gltf_path or not bin_path:
                print("Failed to generate terrain GLTF")
                self.terrain_model = None
                return False
            
            print(f"Terrain generated successfully:")
            print(f"  GLTF: {gltf_path}")
            print(f"  BIN: {bin_path}")
            
            # Load the generated terrain
            print("Loading terrain into OpenGL...")
            self.terrain_model = self.model_loader.load_static_gltf(gltf_path, bin_path)

            if self.terrain_model:
                # Drop any baked water mesh (older cached terrain GLTFs) — the
                # procedural WaterPlaneRenderer is the single water display.
                # Must happen before the display-list rebuild below.
                strip_baked_water(self.terrain_model)
                # Normals must be computed BEFORE the display list is used, but
                # load_static_gltf already compiled the list without normals.
                # Delete the old list and recompile with normals now present.
                self._compute_mesh_normals(self.terrain_model)
                _old_dl = getattr(self.terrain_model, 'display_list', None)
                if _old_dl:
                    from OpenGL.GL import glDeleteLists
                    try:
                        glDeleteLists(_old_dl, 1)
                    except Exception:
                        pass
                    self.terrain_model.display_list = None
                self.model_loader._create_opengl_resources(self.terrain_model)
                print("✓ Terrain GLTF loaded into OpenGL successfully")
                
                # Initialize water mesh editor
                if hasattr(self, 'water_mesh_editor'):
                    try:
                        success = self.water_mesh_editor.initialize_from_gltf_model(self.terrain_model)
                        if success:
                            print("✓ Water mesh editor initialized")
                    except Exception as e:
                        print(f"⚠ Water mesh editor error: {e}")
                
                self.update()
                return True
                
        except Exception as e:
            print(f"Error loading terrain for level: {e}")
            import traceback
            traceback.print_exc()
            self.terrain_model = None
            return False

    def load_terrain_cell_3d(self, level_path, world_x: float, world_y: float,
                             resolution=500000, scale=1.0) -> bool:
        """Load one FC2 terrain cell into 3D and append to terrain_models list."""
        if not self.opengl_initialized:
            return False
        try:
            from pathlib import Path
            try:
                from canvas import terrain_to_gltf as terrain_gen
            except ImportError:
                import importlib.util
                current_dir = os.path.dirname(os.path.abspath(__file__))
                parent_dir = os.path.dirname(current_dir)
                for candidate in [
                    os.path.join(current_dir, "terrain_to_gltf.py"),
                    os.path.join(parent_dir, "terrain_to_gltf.py"),
                ]:
                    if os.path.exists(candidate):
                        spec = importlib.util.spec_from_file_location("terrain_gen", candidate)
                        terrain_gen = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(terrain_gen)
                        break
                else:
                    return False

            level_path = Path(level_path)
            file_ext = ".sdat" if getattr(self, 'game_mode', 'avatar') == "farcry2" else ".csdat"
            sdat_path = None
            for candidate in [level_path / "generated" / "sdat", level_path / "sdat", level_path]:
                if candidate.exists() and list(candidate.glob(f"*{file_ext}")):
                    sdat_path = candidate
                    break
            if not sdat_path:
                return False

            gltf_path, bin_path = terrain_gen.generate_terrain_for_level(
                str(sdat_path), resolution=resolution, scale=scale,
                game_mode=getattr(self, 'game_mode', 'avatar')
            )
            if not gltf_path or not bin_path:
                return False

            model = self.model_loader.load_static_gltf(gltf_path, bin_path)
            if model:
                strip_baked_water(model)   # cached FC2 cells may still embed water
                self._compute_mesh_normals(model)
                _old_dl = getattr(model, 'display_list', None)
                if _old_dl:
                    from OpenGL.GL import glDeleteLists
                    try:
                        glDeleteLists(_old_dl, 1)
                    except Exception:
                        pass
                    model.display_list = None
                self.model_loader._create_opengl_resources(model)
                self.terrain_models.append((model, float(world_x), float(world_y)))
                return True
            return False
        except Exception as e:
            print(f"Error loading terrain cell 3D at ({world_x},{world_y}): {e}")
            return False

    @staticmethod
    def _compute_mesh_normals(model):
        """Compute smooth per-vertex normals for every mesh in model that has none.

        Called after loading terrain GLTFs, which intentionally omit normals in the
        file (to avoid a dark-mesh issue in Blender).  Without normals OpenGL defaults
        to (0,0,1) for all vertices, making the terrain invisible to the sun whose
        dominant direction is +Y.  Computing normals here restores correct lighting
        without touching the GLTF exporter.
        """
        import numpy as np
        for mesh in model.meshes:
            if mesh.normals is not None or mesh.vertices is None:
                continue
            verts = np.array(mesh.vertices, dtype=np.float32).reshape(-1, 3)
            n_verts = len(verts)
            normals = np.zeros((n_verts, 3), dtype=np.float32)

            if mesh.indices is not None:
                idx = np.array(mesh.indices, dtype=np.int32).flatten().reshape(-1, 3)
            else:
                idx = np.arange(n_verts, dtype=np.int32).reshape(-1, 3)

            v0 = verts[idx[:, 0]]
            v1 = verts[idx[:, 1]]
            v2 = verts[idx[:, 2]]
            face_normals = np.cross(v1 - v0, v2 - v0)

            np.add.at(normals, idx[:, 0], face_normals)
            np.add.at(normals, idx[:, 1], face_normals)
            np.add.at(normals, idx[:, 2], face_normals)

            lengths = np.linalg.norm(normals, axis=1, keepdims=True)
            lengths = np.where(lengths < 1e-8, 1.0, lengths)
            normals /= lengths
            mesh.normals = normals.flatten()
            print(f"  Computed {n_verts} terrain vertex normals")

    def _draw_cube_geometry(self, size):
        """Draw a solid cube with no outline."""
        s = size / 2

        glBegin(GL_QUADS)

        # Front face
        glNormal3f(0, 0, 1)
        glVertex3f(-s, -s, s)
        glVertex3f(s, -s, s)
        glVertex3f(s, s, s)
        glVertex3f(-s, s, s)

        # Back face
        glNormal3f(0, 0, -1)
        glVertex3f(-s, -s, -s)
        glVertex3f(-s, s, -s)
        glVertex3f(s, s, -s)
        glVertex3f(s, -s, -s)

        # Top face
        glNormal3f(0, 1, 0)
        glVertex3f(-s, s, -s)
        glVertex3f(-s, s, s)
        glVertex3f(s, s, s)
        glVertex3f(s, s, -s)

        # Bottom face
        glNormal3f(0, -1, 0)
        glVertex3f(-s, -s, -s)
        glVertex3f(s, -s, -s)
        glVertex3f(s, -s, s)
        glVertex3f(-s, -s, s)

        # Right face
        glNormal3f(1, 0, 0)
        glVertex3f(s, -s, -s)
        glVertex3f(s, s, -s)
        glVertex3f(s, s, s)
        glVertex3f(s, -s, s)

        # Left face
        glNormal3f(-1, 0, 0)
        glVertex3f(-s, -s, -s)
        glVertex3f(-s, -s, s)
        glVertex3f(-s, s, s)
        glVertex3f(-s, s, -s)

        glEnd()

    def _render_3d_selection_lines(self):
        """Draw a tall vertical beacon line + crosshair for each selected entity in 3D mode."""
        if not self.selected:
            return

        LINE_BOTTOM = -100.0
        LINE_TOP    =  500.0
        CROSS_HALF  =    3.0  # crosshair arm length at entity height

        glPushAttrib(GL_LINE_BIT | GL_CURRENT_BIT | GL_ENABLE_BIT | GL_DEPTH_BUFFER_BIT)
        try:
            glDisable(GL_LIGHTING)
            glDisable(GL_CULL_FACE)
            glEnable(GL_DEPTH_TEST)
            glDepthMask(GL_FALSE)
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glEnable(GL_LINE_SMOOTH)
            glLineWidth(2.5)

            glBegin(GL_LINES)
            for entity in self.selected:
                ex = float(entity.x)
                ey = float(entity.z)   # GL Y = world height
                ez = float(-entity.y)  # GL Z

                # Tall vertical beacon (blue)
                glColor4f(0.2, 0.55, 1.0, 0.9)
                glVertex3f(ex, LINE_BOTTOM, ez)
                glVertex3f(ex, LINE_TOP,    ez)

                # Crosshair at entity height (white)
                glColor4f(1.0, 1.0, 1.0, 0.85)
                glVertex3f(ex - CROSS_HALF, ey, ez)
                glVertex3f(ex + CROSS_HALF, ey, ez)
                glVertex3f(ex, ey, ez - CROSS_HALF)
                glVertex3f(ex, ey, ez + CROSS_HALF)
            glEnd()
        finally:
            glPopAttrib()

    def _render_3d_selection_glow(self):
        """Pulse a yellow tint over the selected entity's 3D model textures."""
        import math, time
        if not self.selected_entity:
            return
        if not hasattr(self, 'model_loader') or self.model_loader is None:
            return

        phase = math.sin(time.time() * 6.0) * 0.5 + 0.5   # 0..1 at ~6 Hz
        glow_intensity = phase * 0.35                      # 0.00..0.35

        self.model_loader.render_selection_glow(glow_intensity)

    def _render_entities_3d(self, entities_sorted=None):
        """Render entities in 3D mode - OPTIMIZED FOR PERFORMANCE
        
        PERFORMANCE OPTIMIZATION:
        - Renders 3D models when available
        - Only renders fallback cubes for entities WITHOUT models (not on top of models)
        - This prevents double-rendering and gives smooth 60 FPS even with 10K+ entities
        """
        if not self.entities or not self.cube_display_list:
            return

        # Accept pre-computed visible list from _render_3d_opengl to avoid redundant cull pass
        if entities_sorted is None:
            entities_sorted = self._get_visible_entities()
        
        models_rendered = 0
        cubes_rendered = 0
        
        # --- Entity dict and relationship sets: rebuilt only when entity list changes ---
        # Keyed on id(self.entities) so any replacement (new level load) invalidates the cache.
        entities_list_id = id(self.entities)
        if getattr(self, '_rel_cache_key', None) != entities_list_id:
            ed = {}
            v_ids = set()
            snpc_ids = set()
            sp_ids = set()
            sc_ids = set()
            for ent in self.entities:
                ed[ent.id] = ent
            for ent in self.entities:
                if not hasattr(ent, 'xml_element') or ent.xml_element is None:
                    continue
                ai_component = ent.xml_element.find(".//object[@name='CFCXAIComponent']")
                if ai_component is not None:
                    ai_object = ai_component.find(".//object[@name='AIObject']")
                    if ai_object is not None:
                        v_ids.add(ent.id)
                        for field in ai_object.findall("field"):
                            ref = field.get('value-Hash64')
                            if ref and ref in ed and ref != ent.id:
                                snpc_ids.add(ref)
                entity_class_field = ent.xml_element.find(".//field[@name='text_hidEntityClass']")
                if entity_class_field is not None:
                    entity_class = entity_class_field.get('value-String', '')
                    if 'Prefab' in entity_class or 'Structure' in ent.name:
                        sp_ids.add(ent.id)
                        children_obj = ent.xml_element.find(".//object[@name='Children']")
                        if children_obj is not None:
                            for child_obj in children_obj.findall("object[@name='Child']"):
                                id_field = child_obj.find("field[@name='ID']")
                                if id_field is not None:
                                    child_id = id_field.get('value-Hash64')
                                    if child_id in ed:
                                        sc_ids.add(child_id)
            self._rel_cache_key = entities_list_id
            self._entities_dict = ed
            self._vehicle_ids = v_ids
            self._seated_npc_ids = snpc_ids
            self._structure_parent_ids = sp_ids
            self._structure_child_ids = sc_ids
            # Clear per-entity color cache so relationship-based colors rebuild
            for ent in self.entities:
                ent._cached_3d_color = None

        entities_dict        = self._entities_dict
        vehicle_ids          = self._vehicle_ids
        seated_npc_ids       = self._seated_npc_ids
        structure_parent_ids = self._structure_parent_ids
        structure_child_ids  = self._structure_child_ids
        
        # Track which entities have 3D models successfully rendered
        entities_with_models = set()

        # *** RENDER 3D MODELS ***
        from time import perf_counter as _pc
        if hasattr(self, 'model_loader'):
            try:
                import gc as _gc
                _gc.disable()   # prevent GC gen-2 sweep from stalling mid-loop
                try:
                    # Bio emission: scaled by night when the cycle is on; full (1.0)
                    # when off so emissive materials look normal (unchanged behaviour).
                    self.model_loader.night_factor = (
                        self._night_factor if self.day_night_enabled else 1.0)
                    _ps = _pc()
                    # Array-native fast path (GPU-driven mode): assemble the
                    # instance data with pure numpy from the cull's index array.
                    # Falls back to the classic per-entity prepare_batches loop
                    # when unavailable (universal path, no rows yet, 2D, …).
                    _ml = self.model_loader
                    _gdr_prepared = False
                    if getattr(_ml, 'force_render_tier', None):
                        _gdr_prepared = _ml.prepare_gpu_frame(self, entities_sorted)
                    if not _gdr_prepared:
                        _ml.prepare_batches(entities_sorted, self.selected)
                    _ps = self._pf('prepare', _ps)
                    # Sun shadow map: cast model depth NOW (instance_batches is
                    # current for this frame) so render_batched_models can sample it.
                    self._cast_sun_shadows()
                    instances_rendered = self.model_loader.render_batched_models()
                    self._pf('models', _ps)
                    models_rendered = instances_rendered

                    # Track which entities got models rendered
                    if getattr(_ml, 'gdr_drew_last', False):
                        # Array mode: instance_batches wasn't filled this frame.
                        # The modelled-id set is maintained with the row tables —
                        # constant per level, no per-frame loop needed.
                        entities_with_models = _ml._gdr_modelled_ids
                    else:
                        for model_path, instances in self.model_loader.instance_batches.items():
                            model = self.model_loader.models_cache.get(model_path)
                            if model and model.loaded and (model.display_list or (hasattr(model, 'use_immediate_mode') and model.use_immediate_mode)):
                                for instance_data in instances:
                                    entities_with_models.add(id(instance_data[0]))
                finally:
                    _gc.enable()
                    _gc.collect(0)  # fast gen-0 sweep so short-lived objects don't accumulate

            except Exception as e:
                if not hasattr(self, '_batch_error_logged'):
                    self._batch_error_logged = True
                    print(f"Error in batch rendering: {e}")
        
        # *** OPTIMIZED: Only render cubes for entities WITHOUT models (fallback) ***
        # This prevents double-rendering and dramatically improves performance
        show_cubes = getattr(self, 'show_3d_cubes', True)
        
        _cs = _pc()
        if show_cubes:
            # GDR fast path: numpy-gathered instance array (no per-entity loop).
            # Falls through to the classic loop on any failure or in non-GDR mode.
            _fast_done = False
            if (getattr(self.model_loader, 'gdr_drew_last', False)
                    and getattr(self, '_use_cube_instancing', True)):
                try:
                    _ci = self._build_marker_cube_instances()
                    if _ci is not None:
                        cubes_rendered = len(_ci)
                        _fast_done = True
                        if cubes_rendered:
                            if self._cube_batch is None:
                                from cube_batch import CubeBatch
                                self._cube_batch = CubeBatch()
                            if not self._cube_batch.render(_ci):
                                _fast_done = False   # GL path failed → classic loop
                except Exception as _ce:
                    print(f"[cube-fast] error -> classic path: {_ce}")
                    _fast_done = False
            if _fast_done:
                self._pf('cubes', _cs)
                # Skip the classic cube loop entirely.
                self._render_log_frame = getattr(self, '_render_log_frame', 0) + 1
                if self._render_log_frame >= 600:
                    self._render_log_frame = 0
                    total_visible = len(entities_sorted)
                    print(f"3D Rendering: {total_visible} visible | {models_rendered} models | {cubes_rendered} cubes (cubes: ON, fast)")
                return

            # Build list of (color, entity) for cubes only, skipping modelled entities
            selected_set = set(id(e) for e in self.selected)
            cube_list = []
            for entity in entities_sorted:
                if id(entity) in entities_with_models:
                    continue
                is_selected = id(entity) in selected_set
                color = self._get_entity_color_for_3d(
                    entity, vehicle_ids, seated_npc_ids,
                    structure_parent_ids, structure_child_ids, is_selected)
                cube_list.append((color, entity.x, entity.z, -entity.y))

            cubes_rendered = len(cube_list)

            # Fast path: ONE glDrawArraysInstanced for every marker cube (was 2000+
            # glPushMatrix/glTranslatef/glCallList calls — ~3.4 ms of CPU submit).
            # Falls back to the display-list loop if the instanced path is
            # unavailable or errors.
            drew = False
            if cube_list and getattr(self, '_use_cube_instancing', True):
                try:
                    if self._cube_batch is None:
                        from cube_batch import CubeBatch
                        self._cube_batch = CubeBatch()
                    inst = np.asarray(
                        [(wx, wy, wz, c[0], c[1], c[2]) for c, wx, wy, wz in cube_list],
                        dtype=np.float32)
                    drew = self._cube_batch.render(inst)
                except Exception as _ce:
                    print(f"[cube-batch] error -> display-list fallback: {_ce}")
                    drew = False

            if not drew:
                # Fallback: display-list loop, colour-sorted to cut glColor changes.
                cube_list.sort(key=lambda t: t[0])
                current_color = None
                for color, wx, wy, wz in cube_list:
                    if color is not current_color:
                        glColor3f(*color)
                        current_color = color
                    glPushMatrix()
                    glTranslatef(wx, wy, wz)
                    glCallList(self.cube_display_list)
                    glPopMatrix()
        self._pf('cubes', _cs)

        # Log rendering stats every ~600 frames (~10s at 60fps) without calling time.time() per frame
        self._render_log_frame = getattr(self, '_render_log_frame', 0) + 1
        if self._render_log_frame >= 600:
            self._render_log_frame = 0
            cube_status = "ON" if show_cubes else "OFF"
            total_visible = len(entities_sorted)
            print(f"3D Rendering: {total_visible} visible | {models_rendered} models | {cubes_rendered} cubes (cubes: {cube_status})")
            if vehicle_ids or structure_parent_ids:
                print(f"  Relationships: {len(vehicle_ids)} vehicles, {len(seated_npc_ids)} seated NPCs, "
                    f"{len(structure_parent_ids)} structures, {len(structure_child_ids)} children")

    # Base colors computed once at class level – no per-frame division arithmetic
    _LEGEND_COLORS = {
        "Vehicle":      (52/255,  152/255, 255/255),
        "NPC":          (46/255,  255/255, 113/255),
        "Animal":       (255/255, 200/255, 100/255),   # Amber – Pandoran wildlife
        "Weapon":       (255/255,  76/255,  60/255),
        "Spawn":        (255/255, 156/255,  18/255),
        "Mission":      (185/255,  89/255, 255/255),
        "Trigger":      (255/255, 230/255,  15/255),
        "Prop":         (170/255, 180/255, 190/255),
        "Light":        (255/255, 255/255, 160/255),
        "Effect":       (  0/255, 255/255, 200/255),
        "WorldSectors": (255/255, 100/255, 100/255),
        "Landmarks":    (255/255, 100/255, 100/255),   # Same as WorldSectors
        "Unknown":      (130/255, 130/255, 130/255),
    }

    # Prefix-to-type map for the first dot-segment of hidName / tplCreatureType.
    _HIDNAME_PREFIX_TYPES = {
        "vehicle":                          "Vehicle",
        "enemy_archetypes":                 "NPC",
        "animals":                          "Animal",
        "weapons":                          "Weapon",
        "oa_explosives":                    "Weapon",
        "turrets":                          "Weapon",
        "props":                            "Prop",
        "object_archetypes":                "Prop",
        "breakable":                        "Prop",
        "avatar_vegetation_gatheringobject":"Prop",
        "avatar_vegetation_rf":             "Prop",
        "avatar_vegetation_fm":             "Prop",
        "plants":                           "Prop",
        "tables":                           "Prop",
        "domino":                           "Prop",
        "curves":                           "Prop",
        "weaponproperties":                 "Prop",
        "player":                           "NPC",
        "multiplayer":                      "NPC",
        "ghostpatrols":                     "NPC",
        "interactive":                      "Trigger",
        "stp_archetypes":                   "Spawn",
        "avatar_scriptedevents":            "Mission",
        "cameras":                          "Mission",
        "metagame":                         "Mission",
        "stimemitters":                     "Effect",
        "postfxs":                          "Effect",
        "beautifiers":                      "Effect",
        "realtree":                         "Prop",
    }

    def _get_base_color_for_entity(self, entity, vehicle_ids, seated_npc_ids,
                                   structure_parent_ids, structure_child_ids):
        """Return the unselected base color for an entity, with per-entity caching.

        The result is stored on the entity object itself (_cached_3d_color) so the
        string-pattern matching in _determine_entity_type_for_3d only runs once per
        entity per level load, not once per frame.
        """
        cached = getattr(entity, '_cached_3d_color', None)
        if cached is not None:
            return cached

        lc = self._LEGEND_COLORS
        eid = entity.id

        if eid in vehicle_ids:
            color = lc["Vehicle"]
        elif eid in seated_npc_ids:
            c = lc["NPC"]
            color = (c[0]*0.8, c[1]*0.8, c[2]*0.8)
        elif eid in structure_parent_ids:
            color = lc["Mission"]
        elif eid in structure_child_ids:
            c = lc["Mission"]
            color = (c[0]*0.9, c[1]*0.9, c[2]*0.9)
        else:
            entity_type = self._determine_entity_type_for_3d(entity)
            if entity_type == "Unknown":
                src = getattr(entity, 'source_file', None)
                srcp = getattr(entity, 'source_file_path', None)
                if src == 'worldsectors' or (srcp and 'worldsector' in srcp.lower()):
                    entity_type = "WorldSectors"
            color = lc.get(entity_type, lc["Unknown"])

        entity._cached_3d_color = color
        return color

    def _get_entity_color_for_3d(self, entity, vehicle_ids, seated_npc_ids,
                                 structure_parent_ids, structure_child_ids, is_selected):
        """Return render color, brightened if selected."""
        base = self._get_base_color_for_entity(
            entity, vehicle_ids, seated_npc_ids, structure_parent_ids, structure_child_ids)
        if is_selected:
            return (min(base[0]*1.3, 1.0), min(base[1]*1.3, 1.0), min(base[2]*1.3, 1.0))
        return base

    def _build_marker_cube_instances(self):
        """Numpy fast path for the marker-cube instance array (GDR mode only).

        Replaces the per-frame Python loop over every visible entity (membership
        test + color lookup + tuple append + np.asarray) with cached per-entity
        color/marker arrays gathered by index. Cache is keyed on things that
        actually change marker membership/colors — NOT the position-array
        version, so drags don't trigger O(N) rebuilds. Positions come straight
        from _positions_3d (already GL-space, kept fresh by the existing
        invalidate/patch machinery).

        Returns an (M, 6) float32 [x, y, z, r, g, b] array, or None when the
        fast path can't run (caller falls back to the classic loop)."""
        ml = self.model_loader
        valid = getattr(self, '_valid_entities_3d', None)
        pos = getattr(self, '_positions_3d', None)
        vis = getattr(self, '_visible_idx_3d', None)
        if not valid or pos is None or vis is None or len(pos) != len(valid):
            return None
        modelled = ml._gdr_modelled_ids
        key = (id(self.entities), len(valid), len(modelled),
               getattr(self, '_rel_cache_key', None))
        if getattr(self, '_cube_arr_key', None) != key:
            n = len(valid)
            colors = np.zeros((n, 3), np.float32)
            marker = np.zeros(n, bool)
            idx_of = {}
            for i, e in enumerate(valid):
                idx_of[id(e)] = i
                if id(e) in modelled:
                    continue
                marker[i] = True
                colors[i] = self._get_entity_color_for_3d(
                    e, self._vehicle_ids, self._seated_npc_ids,
                    self._structure_parent_ids, self._structure_child_ids, False)
            nc = [idx_of[id(e)] for e in (getattr(self, '_never_cull_entities_3d', None) or [])
                  if id(e) in idx_of]
            self._cube_colors_3d = colors
            self._cube_marker_mask = marker
            self._cube_nc_idx = np.asarray(nc, np.int64)
            self._cube_idx_of = idx_of
            self._cube_arr_key = key
        mask = np.zeros(len(valid), bool)
        mask[vis] = True
        if self._cube_nc_idx.size:
            mask[self._cube_nc_idx] = True
        rows = np.nonzero(mask & self._cube_marker_mask)[0]
        inst = np.empty((rows.size, 6), np.float32)
        inst[:, 0:3] = pos[rows]
        inst[:, 3:6] = self._cube_colors_3d[rows]
        # Selected markers get the brightened color (selection sets are small).
        for e in (self.selected or []):
            i = self._cube_idx_of.get(id(e))
            if i is None or not self._cube_marker_mask[i]:
                continue
            w = np.searchsorted(rows, i)
            if w < rows.size and rows[w] == i:
                inst[w, 3:6] = self._get_entity_color_for_3d(
                    e, self._vehicle_ids, self._seated_npc_ids,
                    self._structure_parent_ids, self._structure_child_ids, True)
        return inst


    def _overlay_batch(self):
        """The shared wireframe-overlay LineBatch, or None to use immediate mode.
        Lazily creates it + caches the transform helpers on first use."""
        if not getattr(self, '_use_overlay_batch', True):
            return None
        if self._line_batch is None:
            try:
                from line_batch import (LineBatch, overlay_matrix,
                                        transform_points, wire_cube_segments,
                                        loop_to_segments)
                self._line_batch = LineBatch()
                self._ov_matrix = overlay_matrix
                self._ov_transform = transform_points
                self._wire_cube_seg = wire_cube_segments()
                self._ov_loop_to_seg = loop_to_segments
            except Exception as _e:
                print(f"[line-batch] init failed -> immediate mode: {_e}")
                self._use_overlay_batch = False
                return None
        if getattr(self._line_batch, '_failed', False):
            return None
        return self._line_batch

    def _overlay_batch_begin(self):
        b = self._overlay_batch()
        if b is not None:
            b.begin()

    def _overlay_batch_flush(self):
        b = self._overlay_batch()
        if b is not None:
            b.flush()   # on failure it sets _failed; next frame falls back to immediate

    def _render_primitives_3d(self, visible_entities=None):
        """Render primitive blocking volumes in 3D mode as wireframe outlines"""
        if not self.entities:
            return

        if not hasattr(self, 'entity_renderer'):
            return

        # Accept pre-computed visible list to avoid a second frustum cull pass
        if visible_entities is None:
            visible_entities = self._get_visible_entities()
        primitives = [e for e in visible_entities if self.entity_renderer.is_primitive_object(e)]
        
        if not primitives:
            return

        # Fast path: batch cube primitives into the shared LineBatch; the rarer
        # sphere/cylinder shapes stay immediate-mode (no batched geometry for them).
        batch = self._overlay_batch()
        if batch is not None:
            cube = self._wire_cube_seg
            sphere_cyl = []
            for entity in primitives:
                if not all(hasattr(entity, attr) for attr in ('x', 'y', 'z')):
                    continue
                is_selected = entity in self.selected
                color = (0.0, 0.4, 1.0) if is_selected else (0.0, 0.8, 0.8)
                shape_data = self.entity_renderer.get_primitive_shape_data(entity)
                shape_type = shape_data['shape_type']
                vscale = shape_data['scale']; hid = shape_data['hidScale']
                rot = [0.0, 0.0, 0.0]
                ha = getattr(entity, 'hidAngles', None)
                if ha and len(ha) >= 3:
                    rot = [ha[0], ha[1], ha[2]]
                fsx, fsy, fsz = vscale[0] * hid, vscale[1] * hid, vscale[2] * hid
                if shape_type == 0:   # cube
                    M = self._ov_matrix(entity.x, entity.z, -entity.y, rot[0], rot[1], rot[2],
                                        fsx, fsy, fsz)
                    batch.add_lines(self._ov_transform(cube, M), color)
                else:                 # sphere(1) / cylinder(2)
                    sphere_cyl.append((entity, shape_type, fsx, fsy, fsz, rot, color, is_selected))
            # Sphere/cylinder prims can't be line-batched — hand them to the
            # caller (drawn immediate-mode via _draw_sphere_cyl_prims). Stored
            # rather than drawn inline so the cached-overlay path can replay
            # them on frames where this function doesn't run at all.
            self._ov_sphere_cyl_pending = sphere_cyl
            return

        # Disable lighting for wireframes
        gl.glDisable(gl.GL_LIGHTING)
        gl.glDisable(gl.GL_TEXTURE_2D)

        for entity in primitives:
            if not all(hasattr(entity, attr) for attr in ('x', 'y', 'z')):
                continue
            
            # Check if entity is selected
            is_selected = entity in self.selected
            
            # Set color based on selection state
            if is_selected:
                gl.glColor3f(0.0, 0.4, 1.0)  # Blue when selected
                gl.glLineWidth(2.0)  # Thicker lines when selected
            else:
                gl.glColor3f(0.0, 0.8, 0.8)  # Cyan/teal when not selected
                gl.glLineWidth(1.0)
            
            # Get shape data
            shape_data = self.entity_renderer.get_primitive_shape_data(entity)
            shape_type = shape_data['shape_type']
            vector_scale = shape_data['scale']
            hid_scale = shape_data['hidScale']
            
            # Get rotation from hidAngles
            rotation_angles = [0.0, 0.0, 0.0]
            hid_angles = getattr(entity, 'hidAngles', None)
            if hid_angles and len(hid_angles) >= 3:
                rotation_angles = [hid_angles[0], hid_angles[1], hid_angles[2]]
            
            gl.glPushMatrix()
            
            # Position the primitive
            gl.glTranslatef(entity.x, entity.z, -entity.y)
            
            # 1. Convert from game coords to OpenGL coords (same as models)
            gl.glRotatef(-90, 1, 0, 0)
            
            # 2-4. Apply rotations (same order as models)
            if rotation_angles[2] != 0:
                gl.glRotatef(-rotation_angles[2], 0, 0, 1)
            if rotation_angles[0] != 0:
                gl.glRotatef(rotation_angles[0], 1, 0, 0)
            if rotation_angles[1] != 0:
                gl.glRotatef(rotation_angles[1], 0, 1, 0)
            
            # 5. Apply scale - BOTH hidScale (uniform) and vectorScale (per-axis)
            # This matches how 3D models are scaled
            final_scale_x = vector_scale[0] * hid_scale
            final_scale_y = vector_scale[1] * hid_scale
            final_scale_z = vector_scale[2] * hid_scale
            gl.glScalef(final_scale_x, final_scale_y, final_scale_z)
            
            # Draw the wireframe based on shape type
            if shape_type == 0:  # Cube
                self._draw_wireframe_cube()
            elif shape_type == 1:  # Sphere
                self._draw_wireframe_sphere(16, 16)
            elif shape_type == 2:  # Cylinder
                self._draw_wireframe_cylinder(16, 1.0, 1.0)
            
            gl.glPopMatrix()
        
        # Re-enable lighting
        gl.glEnable(gl.GL_LIGHTING)

    def _draw_sphere_cyl_prims(self, items):
        """Immediate-mode draw of the rare sphere/cylinder primitives collected
        by _render_primitives_3d's batch path (no batched geometry for them)."""
        if not items:
            return
        gl.glDisable(gl.GL_LIGHTING)
        gl.glDisable(gl.GL_TEXTURE_2D)
        for entity, stype, fsx, fsy, fsz, rot, color, is_sel in items:
            gl.glColor3f(*color)
            gl.glLineWidth(2.0 if is_sel else 1.0)
            gl.glPushMatrix()
            gl.glTranslatef(entity.x, entity.z, -entity.y)
            gl.glRotatef(-90, 1, 0, 0)
            if rot[2] != 0: gl.glRotatef(-rot[2], 0, 0, 1)
            if rot[0] != 0: gl.glRotatef(rot[0], 1, 0, 0)
            if rot[1] != 0: gl.glRotatef(rot[1], 0, 1, 0)
            gl.glScalef(fsx, fsy, fsz)
            if stype == 1:
                self._draw_wireframe_sphere(16, 16)
            elif stype == 2:
                self._draw_wireframe_cylinder(16, 1.0, 1.0)
            gl.glPopMatrix()
        gl.glEnable(gl.GL_LIGHTING)
        gl.glLineWidth(1.0)

    def _render_overlays_3d(self, visible_entities):
        """Prims + triggers + shape-points + movie paths, with a cross-frame cache.

        All the batched overlay geometry is WORLD-SPACE (camera-independent), so
        the packed line/point arrays only change when an entity, the selection,
        or a show-flag changes — not when the camera moves. The cached path
        builds the arrays once over the FULL entity list (so they stay valid for
        any camera) and replays them each frame via LineBatch.flush_packed —
        replacing the 8-14 ms/frame Python rebuild (the 'shape/prims/triggers'
        profiler stages) with one cheap draw.

        Classic per-frame path runs when: the LineBatch is unavailable, a movie
        sequence is selected (preview animates entity positions without bumping
        the position version), or the cache was disabled by a GL failure.

        Cache invalidation: key fields below, plus mark_entity_modified clears
        _ov_cache_key directly (rotation/scale edits don't bump the position
        version). Visual note: overlays are no longer frustum-gated, so distant
        in-frustum wireframes (beyond the old cull FAR) are now drawn too — GL
        clips off-screen ones for free."""
        from time import perf_counter as _pc
        batch = self._overlay_batch()
        mw = getattr(self, 'main_window', None)
        movie_active = bool(mw is not None and getattr(mw, 'selected_movie_sequence', None))
        use_cache = (batch is not None and not movie_active
                     and getattr(self, '_use_overlay_cache', True))

        if not use_cache:
            _ts = _pc()
            self._overlay_batch_begin()
            self._ov_sphere_cyl_pending = []
            self._render_primitives_3d(visible_entities)
            self._draw_sphere_cyl_prims(getattr(self, '_ov_sphere_cyl_pending', None))
            _ts = self._pf('prims', _ts)
            self._render_triggers_3d(visible_entities)
            _ts = self._pf('triggers', _ts)
            self._render_shape_points_3d(visible_entities)
            self._overlay_batch_flush()
            render_movie_paths_3d(self)
            self._pf('shape', _ts)
            return

        _ts = _pc()
        key = (getattr(self, '_pos_arrays_version', 0),
               id(self.entities), len(self.entities),
               frozenset(id(e) for e in (self.selected or [])),
               bool(self.show_trigger_zones))
        if key != getattr(self, '_ov_cache_key', None):
            full = self._get_map_filtered_entities()
            batch.begin()
            self._ov_sphere_cyl_pending = []
            self._render_primitives_3d(full)
            self._render_triggers_3d(full)
            self._render_shape_points_3d(full)
            self._ov_cache_lines, self._ov_cache_points = batch.snapshot()
            self._ov_cache_spherecyl = getattr(self, '_ov_sphere_cyl_pending', []) or []
            self._ov_cache_key = key
            batch.begin()   # drop the accumulators — snapshot holds the packed copy
        if not batch.flush_packed(getattr(self, '_ov_cache_lines', None),
                                  getattr(self, '_ov_cache_points', None)):
            # GL failure → classic (then immediate-mode) path from next frame on.
            self._use_overlay_cache = False
            self._ov_cache_key = None
        self._draw_sphere_cyl_prims(getattr(self, '_ov_cache_spherecyl', None))
        render_movie_paths_3d(self)
        self._pf('overlay3d', _ts)

    def _render_triggers_3d(self, visible_entities=None):
        """Render trigger volumes in 3D mode as yellow wireframe boxes"""
        if not self.entities or not hasattr(self, 'entity_renderer'):
            return
        if not self.show_trigger_zones:
            return
        if visible_entities is None:
            visible_entities = self._get_visible_entities()
        triggers = [e for e in visible_entities if self.entity_renderer.is_trigger_entity(e)]
        if not triggers:
            return

        # Fast path: accumulate every trigger box into the shared LineBatch (one
        # draw at flush) instead of a per-entity immediate-mode wireframe.
        batch = self._overlay_batch()
        if batch is not None:
            cube = self._wire_cube_seg
            for entity in triggers:
                if not all(hasattr(entity, attr) for attr in ('x', 'y', 'z')):
                    continue
                is_selected = entity in self.selected
                r, g, b = self.entity_renderer.get_trigger_color(entity)
                color = (r, g, b) if is_selected else (r * 0.8, g * 0.8, b * 0.8)
                data = self.entity_renderer.get_trigger_size(entity)
                size = data['size']; hid_scale = data['hidScale']
                rot = [0.0, 0.0, 0.0]
                ha = getattr(entity, 'hidAngles', None)
                if ha and len(ha) >= 3:
                    rot = [ha[0], ha[1], ha[2]]
                M = self._ov_matrix(entity.x, entity.z, -entity.y, rot[0], rot[1], rot[2],
                                    size[0] * hid_scale, size[1] * hid_scale, size[2] * hid_scale)
                batch.add_lines(self._ov_transform(cube, M), color)
            return

        gl.glDisable(gl.GL_LIGHTING)
        gl.glDisable(gl.GL_TEXTURE_2D)

        for entity in triggers:
            if not all(hasattr(entity, attr) for attr in ('x', 'y', 'z')):
                continue

            is_selected = entity in self.selected
            r, g, b = self.entity_renderer.get_trigger_color(entity)
            if is_selected:
                gl.glColor3f(r, g, b)
                gl.glLineWidth(2.0)
            else:
                gl.glColor3f(r * 0.8, g * 0.8, b * 0.8)
                gl.glLineWidth(1.0)

            data = self.entity_renderer.get_trigger_size(entity)
            size = data['size']
            hid_scale = data['hidScale']

            rotation_angles = [0.0, 0.0, 0.0]
            hid_angles = getattr(entity, 'hidAngles', None)
            if hid_angles and len(hid_angles) >= 3:
                rotation_angles = [hid_angles[0], hid_angles[1], hid_angles[2]]

            gl.glPushMatrix()
            gl.glTranslatef(entity.x, entity.z, -entity.y)
            gl.glRotatef(-90, 1, 0, 0)

            if rotation_angles[2] != 0:
                gl.glRotatef(-rotation_angles[2], 0, 0, 1)
            if rotation_angles[0] != 0:
                gl.glRotatef(rotation_angles[0], 1, 0, 0)
            if rotation_angles[1] != 0:
                gl.glRotatef(rotation_angles[1], 0, 1, 0)

            # Same scale formula as _render_primitives_3d: vectorSize * hidScale
            gl.glScalef(size[0] * hid_scale, size[1] * hid_scale, size[2] * hid_scale)
            self._draw_wireframe_cube()
            gl.glPopMatrix()

        gl.glEnable(gl.GL_LIGHTING)

    def _render_shape_points_3d(self, visible_entities=None):
        """Render hidShapePoints as connected polygon lines + point markers in 3D mode."""
        if not self.entities or not hasattr(self, 'entity_renderer'):
            return
        if visible_entities is None:
            visible_entities = self._get_visible_entities()
        shape_entities = [e for e in visible_entities
                          if self.entity_renderer.has_shape_points(e)]
        if not shape_entities:
            return

        # Fast path: shape-point polygons are already world-space, so just gather
        # the loop segments + markers into the shared LineBatch (one draw each).
        batch = self._overlay_batch()
        if batch is not None:
            for entity in shape_entities:
                points = self.entity_renderer.get_shape_points(entity)
                if len(points) < 2:
                    continue
                is_selected = entity in self.selected
                pw = np.asarray([(px, pz, -py) for px, py, pz in points], np.float32)
                line_color = (0.0, 1.0, 0.3) if is_selected else (0.0, 0.6, 0.2)
                batch.add_lines(self._ov_loop_to_seg(pw), line_color)
                # Per-point markers: first point gold, rest match the loop colour.
                pcol = np.empty((pw.shape[0], 3), np.float32)
                pcol[:] = line_color
                pcol[0] = (1.0, 0.78, 0.0)
                batch.add_points(pw, pcol)
            return

        gl.glDisable(gl.GL_LIGHTING)
        gl.glDisable(gl.GL_TEXTURE_2D)

        for entity in shape_entities:
            points = self.entity_renderer.get_shape_points(entity)
            if len(points) < 2:
                continue
            is_selected = entity in self.selected

            # Polygon outline
            gl.glColor3f(0.0, 1.0, 0.3) if is_selected else gl.glColor3f(0.0, 0.6, 0.2)
            gl.glLineWidth(2.0 if is_selected else 1.0)
            gl.glBegin(gl.GL_LINE_LOOP)
            for px, py, pz in points:
                gl.glVertex3f(px, pz, -py)
            gl.glEnd()

            # Point markers — first point gold, rest cyan/teal
            gl.glPointSize(7.0)
            gl.glBegin(gl.GL_POINTS)
            for i, (px, py, pz) in enumerate(points):
                if i == 0:
                    gl.glColor3f(1.0, 0.78, 0.0)
                elif is_selected:
                    gl.glColor3f(0.0, 1.0, 0.3)
                else:
                    gl.glColor3f(0.0, 0.6, 0.2)
                gl.glVertex3f(px, pz, -py)
            gl.glEnd()

        gl.glEnable(gl.GL_LIGHTING)
        gl.glLineWidth(1.0)
        gl.glPointSize(1.0)

    def _draw_wireframe_cube(self):
        """Draw a wireframe cube centered at origin with size 2x2x2"""
        gl.glBegin(gl.GL_LINES)
        
        # Define cube vertices (unit cube from -1 to 1)
        vertices = [
            [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],  # Front face
            [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]       # Back face
        ]
        
        # Draw front face
        for i in range(4):
            gl.glVertex3f(*vertices[i])
            gl.glVertex3f(*vertices[(i + 1) % 4])
        
        # Draw back face
        for i in range(4, 8):
            gl.glVertex3f(*vertices[i])
            gl.glVertex3f(*vertices[4 + ((i + 1) % 4)])
        
        # Draw connecting edges
        for i in range(4):
            gl.glVertex3f(*vertices[i])
            gl.glVertex3f(*vertices[i + 4])
        
        gl.glEnd()
    
    def _draw_wireframe_sphere(self, slices, stacks):
        """Draw a wireframe sphere centered at origin with radius 1"""
        import math
        
        # Draw latitude lines
        for i in range(stacks):
            lat0 = math.pi * (-0.5 + float(i) / stacks)
            lat1 = math.pi * (-0.5 + float(i + 1) / stacks)
            
            z0 = math.sin(lat0)
            z1 = math.sin(lat1)
            zr0 = math.cos(lat0)
            zr1 = math.cos(lat1)
            
            gl.glBegin(gl.GL_LINE_LOOP)
            for j in range(slices):
                lng = 2 * math.pi * float(j) / slices
                x = math.cos(lng)
                y = math.sin(lng)
                
                gl.glVertex3f(x * zr0, y * zr0, z0)
            gl.glEnd()
        
        # Draw longitude lines
        for j in range(slices):
            lng = 2 * math.pi * float(j) / slices
            
            gl.glBegin(gl.GL_LINE_STRIP)
            for i in range(stacks + 1):
                lat = math.pi * (-0.5 + float(i) / stacks)
                x = math.cos(lng) * math.cos(lat)
                y = math.sin(lng) * math.cos(lat)
                z = math.sin(lat)
                
                gl.glVertex3f(x, y, z)
            gl.glEnd()
    
    def _draw_wireframe_cylinder(self, slices, radius, height):
        """Draw a wireframe cylinder centered at origin, aligned with Y axis"""
        import math
        
        half_height = height / 2
        
        # Draw top circle
        gl.glBegin(gl.GL_LINE_LOOP)
        for i in range(slices):
            angle = 2 * math.pi * i / slices
            x = radius * math.cos(angle)
            z = radius * math.sin(angle)
            gl.glVertex3f(x, half_height, z)
        gl.glEnd()
        
        # Draw bottom circle
        gl.glBegin(gl.GL_LINE_LOOP)
        for i in range(slices):
            angle = 2 * math.pi * i / slices
            x = radius * math.cos(angle)
            z = radius * math.sin(angle)
            gl.glVertex3f(x, -half_height, z)
        gl.glEnd()
        
        # Draw vertical lines connecting top and bottom
        gl.glBegin(gl.GL_LINES)
        for i in range(0, slices, slices // 4):  # Draw 4 vertical lines
            angle = 2 * math.pi * i / slices
            x = radius * math.cos(angle)
            z = radius * math.sin(angle)
            
            gl.glVertex3f(x, half_height, z)
            gl.glVertex3f(x, -half_height, z)
        gl.glEnd()


    def _determine_entity_type_for_3d(self, entity):
        """Determine entity type for 3D rendering."""
        entity_name = getattr(entity, 'name', '')

        # Prefix-based classification: check hidName and tplCreatureType dot-prefix.
        for candidate in self._get_type_candidates_3d(entity, entity_name):
            prefix = candidate.split('.')[0].lower()
            result = self._HIDNAME_PREFIX_TYPES.get(prefix)
            if result:
                return result

        # Fallback: legacy substring patterns on lowercased name.
        # Must mirror entity_renderer.py type_patterns in both terms and order.
        name_lower = entity_name.lower()

        if any(p in name_lower for p in ['vehicle', 'car', 'truck', 'boat', 'ship', 'plane',
                                          'helicopter', 'scorpion', 'samson', 'valkyrie',
                                          'dragon', 'ampsuit', 'buggy', 'atv', 'quad', 'dove']):
            return "Vehicle"
        # Animal before NPC so creature names beat "avatar"/"navi" NPC match
        if any(p in name_lower for p in ['viperwolf', 'direhorse', 'hammerhead', 'hexapede',
                                          'thanator', 'leonopteryx', 'stingbat', 'sturmbeest',
                                          'hellfirewasp', 'banshee']):
            return "Animal"
        if any(p in name_lower for p in ['npc', 'character', 'ai_', 'enemy', 'soldier',
                                          'marine', 'civilian', 'avatar', 'navi', 'friend',
                                          'ally', 'neutral']):
            return "NPC"
        if any(p in name_lower for p in ['weapon', 'gun', 'rifle', 'pistol', 'sword',
                                          'bow', 'arrow', 'spear', 'shotgun', 'flamethrower',
                                          'bomb', 'explosive', 'grenade', 'missile', 'rocket']):
            return "Weapon"
        if any(p in name_lower for p in ['spawn', 'start', 'respawn', 'checkpoint',
                                          'spawnpoint', 'birth']):
            return "Spawn"
        if any(p in name_lower for p in ['mission', 'objective', 'goal', 'target',
                                          'pickup', 'collectible', 'artifact']):
            return "Mission"
        if any(p in name_lower for p in ['trigger', 'zone', 'area', 'region', 'volume',
                                          'detector', 'sensor', 'activator', 'switch']):
            return "Trigger"
        if any(p in name_lower for p in ['light', 'lamp', 'torch', 'spotlight', 'glow',
                                          'bulb', 'lantern', 'beacon']):
            return "Light"
        if any(p in name_lower for p in ['fx_', 'effect', 'particle', 'vfx', 'smoke',
                                          'fire', 'explosion', 'steam', 'dust', 'emitter']):
            return "Effect"

        return "Unknown"

    def _get_type_candidates_3d(self, entity, entity_name):
        """Return name candidates (hidName then tplCreatureType) for prefix lookup."""
        candidates = [entity_name] if entity_name else []
        xml_el = getattr(entity, 'xml_element', None)
        if xml_el is not None:
            ct_field = xml_el.find("./field[@name='tplCreatureType']")
            if ct_field is not None:
                ct = (ct_field.get('value-String') or ct_field.get('strVal') or '').strip()
                if ct and ct not in candidates:
                    candidates.append(ct)
        props = getattr(entity, 'properties', None)
        if props:
            ct = props.get('creature_type', '')
            if ct and ct not in candidates:
                candidates.append(ct)
        return candidates

    def set_3d_mode(self, enabled: bool):
        """Enable or disable 3D rendering."""
        self.is_3d_mode = enabled
        self.mode = MODE_3D if enabled else MODE_TOPDOWN
        
        if enabled:
            print("Switching to 3D mode")
            # ONLY auto-position camera if it hasn't been initialized yet
            if not self.camera_3d_initialized and self.entities:
                # Calculate center of entities
                min_x = min_y = float('inf')
                max_x = max_y = float('-inf')
                
                for entity in self.entities:
                    if hasattr(entity, 'x') and hasattr(entity, 'y'):
                        min_x = min(min_x, entity.x)
                        max_x = max(max_x, entity.x)
                        min_y = min(min_y, entity.y)
                        max_y = max(max_y, entity.y)
                
                if min_x != float('inf'):
                    center_x = (min_x + max_x) / 2
                    center_y = (min_y + max_y) / 2
                    
                    # Position camera above and behind center
                    self.camera_3d.position = np.array([center_x, 100.0, center_y + 0.0])
                    self.camera_3d.yaw = -90.0
                    self.camera_3d.pitch = -30.0
                    self.camera_3d.update_vectors()
                    
                    self.camera_3d_initialized = True
                    print(f"Initialized 3D camera at position")
            else:
                print(f"Keeping 3D camera at current position")
        else:
            print("Switching to 2D mode")
            self.mouse_captured_3d = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
        
        self.update()

    def switch_to_3d_mode(self):
        """Switch to 3D view mode"""
        self.set_3d_mode(True)

    def switch_to_2d_mode(self):
        """Switch to 2D view mode"""
        self.set_3d_mode(False)

    def toggle_view_mode(self):
        """Toggle between 2D and 3D modes"""
        self.set_3d_mode(not self.is_3d_mode)
        print(f"Toggled to: {'3D' if self.is_3d_mode else '2D'} mode")

    def load_terrain(self, sdat_path):
        """Load terrain heightmap data"""
        if not hasattr(self, 'terrain_renderer'):
            print("No terrain renderer available")
            return False
        
        try:
            success = self.terrain_renderer.load_sdat_folder(sdat_path)
            if success:
                print(f"Terrain loaded from {sdat_path}")
                self.update()
            else:
                print(f"Failed to load terrain from {sdat_path}")
            return success
        except Exception as e:
            print(f"Error loading terrain: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_terrain_height_at(self, world_x: float, world_y: float) -> float:
        """Return terrain height (Z) at world (x, y). Used by terrain snap in 3D mode."""
        tr = getattr(self, 'terrain_renderer', None)
        if tr is None:
            return 0.0
        if getattr(tr, 'combined_heightmap', None) is None:
            print("[TerrainSnap] combined_heightmap not loaded — 2D terrain may not be loaded yet")
            return 0.0
        ox = getattr(self, 'terrain_world_offset_x', tr.terrain_offset_x)
        oy = getattr(self, 'terrain_world_offset_y', tr.terrain_offset_y)
        return tr.get_height_at_world(world_x, world_y, ox, oy)

    # -------------------------------------------------------------------------
    # Terrain edit mode helpers
    # -------------------------------------------------------------------------

    def _get_terrain_editor(self):
        """Return the open TerrainEditorDialog, or None if unavailable."""
        parent = self.parent()
        if parent is None:
            return None
        te = getattr(parent, '_terrain_editor_window', None)
        if te is None:
            return None
        return te

    def _terrain_undo(self):
        td = getattr(self, '_terrain_data', None)
        if td is None:
            return
        if td.undo():
            self._sync_terrain_after_undo_redo(td)

    def _terrain_redo(self):
        td = getattr(self, '_terrain_data', None)
        if td is None:
            return
        if td.redo():
            self._sync_terrain_after_undo_redo(td)

    def _sync_terrain_after_undo_redo(self, td):
        tr = getattr(self, 'terrain_renderer', None)
        if tr is not None:
            tr.combined_heightmap = td.combined
        self._rebuild_terrain_edit_mesh()
        self.update()

    def _refresh_full_terrain(self):
        """Reload heightmap + water data, then regenerate the 3D terrain model at lower resolution."""
        import os
        main_win = getattr(self, 'editor', None) or self.parent()
        sdat_path = getattr(main_win, 'sdat_path', None)
        if not sdat_path:
            print("[TerrainRefresh] No sdat_path — load a level first")
            return

        # 1. Reload 2D heightmap + water data in terrain_renderer
        self.load_terrain(sdat_path)

        # 2. Reload canvas-local heightmap used for brush editing
        self._terrain_data = None
        self._te_mesh_verts = self._te_mesh_colors = self._te_mesh_indices = None
        self._load_terrain_data()

        # 3. Regenerate 3D model at reduced resolution (25k vs 100k at level load) for speed
        level_dir = (os.path.dirname(sdat_path)
                     if 'generated' in sdat_path.lower()
                     else sdat_path)
        print("[TerrainRefresh] Regenerating 3D model (100k tris)...")
        self.load_terrain_for_level(level_dir, resolution=500000, scale=1.0)
        print("[TerrainRefresh] Done")

    def _load_terrain_data(self):
        """Load terrain heightmap from the level's sdat folder into self._terrain_data."""
        from .terrain_editor_dialog import TerrainData
        # canvas.editor is set to SimplifiedMapEditor directly (parent() is central_widget)
        main_win = getattr(self, 'editor', None) or self.parent()
        sdat_path = getattr(main_win, 'sdat_path', None)
        if not sdat_path:
            print("[TerrainEdit] No sdat_path found — load a level first")
            return
        td = TerrainData()
        if td.load(sdat_path):
            self._terrain_data = td
            tr = getattr(self, 'terrain_renderer', None)
            if tr is not None:
                tr.update_from_heightmap(td.combined)
            self._rebuild_terrain_edit_mesh()
            print(f"[TerrainEdit] Loaded {td.sectors_x}×{td.sectors_y} sectors from {sdat_path}")
        else:
            print(f"[TerrainEdit] No csdat files found in {sdat_path}")

    def _rebuild_terrain_edit_mesh(self):
        """Build vertex/color/index arrays from self._terrain_data for 3D rendering."""
        td = getattr(self, '_terrain_data', None)
        if td is None or td.combined is None:
            self._te_mesh_verts = self._te_mesh_colors = self._te_mesh_indices = None
            return

        combined = td.combined
        tr = getattr(self, 'terrain_renderer', None)
        ox = getattr(self, 'terrain_world_offset_x',
                     getattr(tr, 'terrain_offset_x', 0.0) if tr else 0.0)
        oy = getattr(self, 'terrain_world_offset_y',
                     getattr(tr, 'terrain_offset_y', 0.0) if tr else 0.0)

        STRIDE = 2
        h_px, w_px = combined.shape
        # flipud: row 0 of combined = top = max world Y, but mesh row 0 = min world Y (oy)
        sampled = np.flipud(combined[::STRIDE, ::STRIDE])
        ny, nx = sampled.shape

        world_w = float(w_px - 1)
        world_h = float(h_px - 1)
        step_x = world_w / max(w_px - 1, 1) * STRIDE
        step_z = world_h / max(h_px - 1, 1) * STRIDE

        cols = np.arange(nx, dtype=np.float32) * step_x + ox
        rows = np.arange(ny, dtype=np.float32) * step_z + oy
        cc, rr = np.meshgrid(cols, rows)

        verts = np.stack([cc.flatten(),
                          sampled.flatten(),
                          (-rr).flatten()], axis=1)
        self._te_mesh_verts = np.ascontiguousarray(verts, dtype=np.float32)

        # UV coords for texture paint mode (v=0 at high world Y end in GL convention)
        u_vals = np.arange(nx, dtype=np.float32) / max(nx - 1, 1)
        v_vals = 1.0 - np.arange(ny, dtype=np.float32) / max(ny - 1, 1)
        uu, vv = np.meshgrid(u_vals, v_vals)
        self._te_mesh_uvs = np.ascontiguousarray(
            np.stack([uu.flatten(), vv.flatten()], axis=1), dtype=np.float32)

        # Elevation-based coloring
        flat = sampled.flatten().astype(np.float32)
        mn, mx = float(flat.min()), float(flat.max())
        norm = (flat - mn) / (mx - mn + 1e-6)
        colors = np.zeros((len(norm), 3), dtype=np.float32)
        lo = norm < 0.35
        mi = (norm >= 0.35) & (norm < 0.70)
        hi = norm >= 0.70
        colors[lo]  = np.column_stack([norm[lo]*0.3,        0.45+norm[lo]*0.3,  norm[lo]*0.2])
        colors[mi]  = np.column_stack([0.45+norm[mi]*0.3,   0.32+norm[mi]*0.1,  0.12+np.zeros(mi.sum())])
        colors[hi]  = np.column_stack([0.55+norm[hi]*0.35,  0.55+norm[hi]*0.35, 0.55+norm[hi]*0.35])
        self._te_mesh_colors = np.ascontiguousarray(colors, dtype=np.float32)

        rr_i, cc_i = np.meshgrid(np.arange(ny - 1), np.arange(nx - 1), indexing='ij')
        tl = (rr_i * nx + cc_i).flatten()
        tr2 = (rr_i * nx + cc_i + 1).flatten()
        bl = ((rr_i + 1) * nx + cc_i).flatten()
        br = ((rr_i + 1) * nx + cc_i + 1).flatten()
        self._te_mesh_indices = np.ascontiguousarray(
            np.column_stack([tl, bl, tr2, tr2, bl, br]).flatten(), dtype=np.uint32)

    def _update_terrain_mesh_heights(self):
        """Fast path used during brush strokes: only updates Y and colors, keeps X/Z/indices."""
        td = getattr(self, '_terrain_data', None)
        if td is None or td.combined is None or self._te_mesh_verts is None:
            self._rebuild_terrain_edit_mesh()
            return
        STRIDE = 2
        sampled = np.flipud(td.combined[::STRIDE, ::STRIDE])
        flat = sampled.flatten().astype(np.float32)
        self._te_mesh_verts[:, 1] = flat
        mn, mx = float(flat.min()), float(flat.max())
        norm = (flat - mn) / (mx - mn + 1e-6)
        colors = np.zeros((len(norm), 3), dtype=np.float32)
        lo = norm < 0.35
        mi = (norm >= 0.35) & (norm < 0.70)
        hi = norm >= 0.70
        colors[lo] = np.column_stack([norm[lo]*0.3,        0.45+norm[lo]*0.3,  norm[lo]*0.2])
        colors[mi] = np.column_stack([0.45+norm[mi]*0.3,   0.32+norm[mi]*0.1,  0.12+np.zeros(mi.sum())])
        colors[hi] = np.column_stack([0.55+norm[hi]*0.35,  0.55+norm[hi]*0.35, 0.55+norm[hi]*0.35])
        self._te_mesh_colors = np.ascontiguousarray(colors, dtype=np.float32)

    def _render_terrain_edit_mesh(self):
        """Render the heightmap edit mesh in the 3D view."""
        if not self.terrain_edit_mode:
            return
        if self._te_mesh_verts is None or self._te_mesh_indices is None:
            return
        try:
            glDisable(GL_LIGHTING)
            glDisable(GL_CULL_FACE)
            glEnable(GL_DEPTH_TEST)
            glDepthFunc(GL_LEQUAL)
            glEnable(GL_POLYGON_OFFSET_FILL)
            glPolygonOffset(-2.0, -2.0)   # pull toward camera so it sits on top

            glEnableClientState(GL_VERTEX_ARRAY)
            glEnableClientState(GL_COLOR_ARRAY)
            glVertexPointer(3, GL_FLOAT, 0, self._te_mesh_verts)
            glColorPointer(3, GL_FLOAT, 0, self._te_mesh_colors)
            glDrawElements(GL_TRIANGLES, len(self._te_mesh_indices),
                           GL_UNSIGNED_INT, self._te_mesh_indices)
            glDisableClientState(GL_VERTEX_ARRAY)
            glDisableClientState(GL_COLOR_ARRAY)

            glDisable(GL_POLYGON_OFFSET_FILL)
            glEnable(GL_LIGHTING)
            glEnable(GL_CULL_FACE)
        except Exception as e:
            print(f"[TerrainEdit] Mesh render error: {e}")

    def _save_terrain_data(self):
        """Write all dirty sectors back to their .csdat files."""
        td = getattr(self, '_terrain_data', None)
        if td is None or not td.dirty_sectors:
            return
        written, failed = td.save_dirty_sectors()
        print(f"[TerrainEdit] Saved {written} sector(s)" +
              (f", {failed} failed" if failed else ""))

    # ------------------------------------------------------------------
    # Terrain texture painting
    # ------------------------------------------------------------------

    def _load_texture_painter(self):
        """Load all available atlas texture types (mask/diffuse/color) and activate the best one."""
        from .terrain_texture_painter import TerrainTexturePainter
        if self._terrain_data is None:
            self._load_terrain_data()
        if self._terrain_data is None:
            print("[TexturePaint] No terrain data — load terrain first")
            return False
        td = self._terrain_data
        sdat_dir = getattr(td, 'sdat_path', None)
        if not sdat_dir:
            main_win = getattr(self, 'editor', None) or self.parent()
            sdat_dir = getattr(main_win, 'sdat_path', None)
        if not sdat_dir:
            print("[TexturePaint] No sdat_path available")
            return False

        self._ttp_painters = {}
        for key, suffix in [('mask', '_mask'), ('diffuse', '_diffuse'), ('color', '_color')]:
            ttp = TerrainTexturePainter()
            ok = ttp.load(sdat_dir, td.sectors_x, td.sectors_y, force_suffix=suffix)
            if ok:
                self._ttp_painters[key] = ttp
                print(f"[TexturePaint] Loaded '{key}' atlas")

        if not self._ttp_painters:
            return False

        # Activate the best available type
        for key in ('mask', 'diffuse', 'color'):
            if key in self._ttp_painters:
                self._tp_active_tex_key = key
                self._ttp = self._ttp_painters[key]
                break

        self._upload_paint_texture()
        self._resample_paint_vertex_colors()
        return True

    def _switch_paint_texture(self, key):
        """Switch which atlas texture type is shown in the 3D paint overlay."""
        if key not in self._ttp_painters:
            return
        self._tp_active_tex_key = key
        self._ttp = self._ttp_painters[key]
        self._upload_paint_texture()
        self._resample_paint_vertex_colors()
        self.update()

    def _notify_tex_thumbnails_updated(self):
        """Tell the main window to refresh the texture-selector thumbnails."""
        main_win = getattr(self, 'editor', None) or self.parent()
        cb = getattr(main_win, '_update_tp_tex_thumbnails', None)
        if callable(cb):
            cb()

    @staticmethod
    def _rotate_tex_ccw(arr):
        """Return a contiguous copy of arr rotated 90° CCW (left). Shape (H,W,4)→(W,H,4) or same if square."""
        return np.ascontiguousarray(np.rot90(arr, k=1))

    def _upload_paint_texture(self):
        """Create / replace the GL texture from the TerrainTexturePainter combined_tex."""
        if self._ttp is None or self._ttp.combined_tex is None:
            return
        try:
            self.makeCurrent()
            if self._te_tex_id is not None:
                glDeleteTextures(1, [self._te_tex_id])
            tex_id = glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, tex_id)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            arr = self._rotate_tex_ccw(self._ttp.combined_tex)
            h, w = arr.shape[:2]
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0,
                         GL_RGBA, GL_UNSIGNED_BYTE, arr.tobytes())
            glBindTexture(GL_TEXTURE_2D, 0)
            self._te_tex_id = tex_id
            print(f"[TexturePaint] GL texture uploaded ({w}×{h}, rotated 90° CCW)")
        except Exception as e:
            print(f"[TexturePaint] GL upload error: {e}")

    def _update_gl_tex_tiles(self, dirty_tiles):
        """Re-upload the full rotated texture after paint strokes (tile sub-regions shift after rotation)."""
        if self._ttp is None or self._te_tex_id is None:
            return
        if not dirty_tiles:
            return
        try:
            self.makeCurrent()
            arr = self._rotate_tex_ccw(self._ttp.combined_tex)
            h, w = arr.shape[:2]
            glBindTexture(GL_TEXTURE_2D, self._te_tex_id)
            glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, w, h,
                            GL_RGBA, GL_UNSIGNED_BYTE, arr.tobytes())
            glBindTexture(GL_TEXTURE_2D, 0)
        except Exception as e:
            print(f"[TexturePaint] GL tile update error: {e}")

    def _resample_paint_vertex_colors(self):
        """Sample combined_tex into a per-vertex color array for rendering.
        Mirrors the terrain edit mesh approach: vertex colors, no GL texture needed."""
        if self._ttp is None or self._ttp.combined_tex is None:
            return
        if self._terrain_data is None or self._te_mesh_verts is None:
            return

        tex = np.ascontiguousarray(np.rot90(self._ttp.combined_tex, k=1))  # 90° CCW
        tex_h, tex_w = tex.shape[:2]

        STRIDE = 2
        h_px, w_px = self._terrain_data.combined.shape
        ny = len(range(0, h_px, STRIDE))      # e.g. 513 for 1025-px heightmap
        nx = len(range(0, w_px, STRIDE))

        mesh_rows = np.arange(ny)
        mesh_cols = np.arange(nx)

        # mesh_row 0 = south (min Y) after flipud;  tex row 0 = north (max Y)  → inverted
        tex_rows = np.clip(
            ((ny - 1 - mesh_rows) * (tex_h - 1) / max(ny - 1, 1)).astype(int), 0, tex_h - 1)
        tex_cols = np.clip(
            (mesh_cols * (tex_w - 1) / max(nx - 1, 1)).astype(int), 0, tex_w - 1)

        sampled = tex[np.ix_(tex_rows, tex_cols)]   # (ny, nx, 4)
        self._te_paint_colors = np.ascontiguousarray(
            sampled[:, :, :3].reshape(-1, 3).astype(np.float32) / 255.0
        )

    def _render_terrain_paint_mesh(self):
        """Render the terrain mask texture overlay in paint mode.
        Renders the atlas mask as per-vertex colors, exactly mirroring how
        _render_terrain_edit_mesh works — same GL state, same polygon offset."""
        if not self.terrain_paint_mode:
            return
        if self._te_mesh_verts is None or self._te_mesh_indices is None:
            return
        if self._te_paint_colors is None:
            return
        try:
            glDisable(GL_LIGHTING)
            glDisable(GL_CULL_FACE)
            glEnable(GL_DEPTH_TEST)
            glDepthFunc(GL_LEQUAL)
            glEnable(GL_POLYGON_OFFSET_FILL)
            glPolygonOffset(-2.0, -2.0)

            glEnableClientState(GL_VERTEX_ARRAY)
            glEnableClientState(GL_COLOR_ARRAY)
            glVertexPointer(3, GL_FLOAT, 0, self._te_mesh_verts)
            glColorPointer(3, GL_FLOAT, 0, self._te_paint_colors)
            glDrawElements(GL_TRIANGLES, len(self._te_mesh_indices),
                           GL_UNSIGNED_INT, self._te_mesh_indices)
            glDisableClientState(GL_VERTEX_ARRAY)
            glDisableClientState(GL_COLOR_ARRAY)

            glDisable(GL_POLYGON_OFFSET_FILL)
            glEnable(GL_LIGHTING)
            glEnable(GL_CULL_FACE)
        except Exception as e:
            print(f"[TexturePaint] Mesh render error: {e}")

    def _terrain_paint_apply(self, hx, hy, first=False):
        """Apply one paint stroke sample via TerrainTexturePainter."""
        if self._ttp is None or self._terrain_data is None:
            return
        td = self._terrain_data
        hmap_h, hmap_w = td.combined.shape
        # Display samples rot90(combined_tex, k=1): rotated[i,j] = original[j, W-1-i]
        # Invert: to paint at visual pos (hy, hx), write to original[hx, W-1-hy].
        rot_hx = hmap_w - 1 - hy
        rot_hy = hx
        if self._tp_stamp_tex is not None:
            pixels_per_meter = self._ttp._tile_w / 64.0
            atlas_tile_px = max(1, round(self._tp_tile_meters * pixels_per_meter))
        else:
            atlas_tile_px = 4
        dirty = self._ttp.paint_at(
            rot_hx, rot_hy, hmap_w, hmap_h,
            self._te_paint_color,
            self._te_size,
            self._te_strength,
            stamp_tex=self._tp_stamp_tex,
            shape=self._tp_brush_shape,
            tile_size=atlas_tile_px,
            feather=self._tp_feather,
        )
        if dirty:
            # Rebuild vertex color display (same pattern as terrain edit height update)
            self._resample_paint_vertex_colors()
            # Keep GL texture in sync for XBT save round-trip
            self._update_gl_tex_tiles(dirty)

    def _save_texture_paint(self):
        """Save all painted atlas XBT files back to disk."""
        if self._ttp is None:
            return
        saved, errors = self._ttp.save()
        msg = f"[TexturePaint] Saved {saved} atlas file(s)"
        if errors:
            msg += f"; {len(errors)} error(s): {', '.join(os.path.basename(p) for p in errors)}"
        print(msg)
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(self, "Save Textures",
                                f"Saved {saved} atlas file(s)." +
                                (f"\nErrors: {len(errors)}" if errors else ""))

    def _refresh_texture_paint(self):
        """Reload atlas textures from disk, discarding any unsaved paint."""
        try:
            self.makeCurrent()
            if self._te_tex_id is not None:
                glDeleteTextures(1, [self._te_tex_id])
                self._te_tex_id = None
        except Exception:
            pass
        self._ttp = None
        self._ttp_painters = {}
        self._te_paint_colors = None
        ok = self._load_texture_painter()
        if ok:
            print("[TexturePaint] Texture refreshed from disk")
            self._notify_tex_thumbnails_updated()
        else:
            print("[TexturePaint] Refresh failed — check console for errors")
        self.update()

    def _has_terrain_heightmap(self):
        """Return True if any heightmap source is ready for editing."""
        if getattr(self, '_terrain_data', None) is not None and self._terrain_data.combined is not None:
            return True
        tr = getattr(self, 'terrain_renderer', None)
        if tr is not None and getattr(tr, 'combined_heightmap', None) is not None:
            return True
        te = self._get_terrain_editor()
        if te is not None and getattr(te._td, 'combined', None) is not None:
            return True
        return False

    def _sync_te_to_dialog(self):
        """Push canvas brush params (_te_tool/size/strength) to the terrain editor dialog."""
        te = self._get_terrain_editor()
        if te is not None:
            try:
                te.sync_brush_params(self._te_tool, self._te_size, self._te_strength, self._te_target_h)
            except Exception:
                pass

    def _terrain_stroke_apply(self, hx, hy, first=False):
        """Apply one brush sample to the canvas-owned terrain data."""
        self._apply_canvas_terrain_brush(hx, hy, first)

    def _apply_canvas_terrain_brush(self, cx, cy, first=False):
        """Apply the active brush to self._terrain_data.combined."""
        td = getattr(self, '_terrain_data', None)
        if td is None or td.combined is None:
            if not getattr(self, '_te_no_hm_warned', False):
                print("[TerrainEdit] No terrain loaded — click EDIT TERRAIN to load sdat data")
                self._te_no_hm_warned = True
            return
        self._te_no_hm_warned = False

        # Track drag direction for slope brush
        if first or self._te_prev_hc is None:
            self._te_prev_hc = (cx, cy)
        else:
            px, py = self._te_prev_hc
            ddx, ddy = cx - px, cy - py
            length = math.sqrt(ddx * ddx + ddy * ddy)
            if length > 0.5:
                self._te_drag_dir = (ddx / length, ddy / length)
            self._te_prev_hc = (cx, cy)

        if first:
            td.push_undo()

        c = td.combined
        radius   = self._te_size
        strength = self._te_strength / 100.0
        tool     = self._te_tool
        brush    = getattr(self, '_te_brush_type', 'circle')

        b_len = max(1, getattr(self, '_te_brush_len', 32))
        b_wid = max(1, getattr(self, '_te_brush_wid', 12))
        if brush == 'rectangle':
            bw, bh = b_len, b_wid
        elif brush == 'slope':
            bw = bh = max(b_len, b_wid)
        elif brush in ('blur', 'airbrush'):
            bw = bh = int(radius * 2.0)
        else:
            bw = bh = radius

        x0 = max(0, cx - bw);  x1 = min(c.shape[1] - 1, cx + bw)
        y0 = max(0, cy - bh);  y1 = min(c.shape[0] - 1, cy + bh)
        if x0 > x1 or y0 > y1:
            return

        xs = np.arange(x0, x1 + 1, dtype=np.float32)
        ys = np.arange(y0, y1 + 1, dtype=np.float32)
        xx, yy = np.meshgrid(xs, ys)
        dx = xx - cx
        dy = yy - cy
        dist2 = dx ** 2 + dy ** 2

        if brush == 'circle':
            sigma   = max(1.0, radius / 3.0)
            falloff = np.exp(-dist2 / (2 * sigma ** 2)).astype(np.float32)
            mask    = (dist2 <= radius ** 2).astype(np.float32)
            alpha   = (strength * falloff * mask).astype(np.float32)
        elif brush == 'square':
            mask  = ((np.abs(dx) <= radius) & (np.abs(dy) <= radius)).astype(np.float32)
            alpha = (strength * mask).astype(np.float32)
        elif brush == 'rectangle':
            mask  = ((np.abs(dx) <= b_len) & (np.abs(dy) <= b_wid)).astype(np.float32)
            alpha = (strength * mask).astype(np.float32)
        elif brush == 'blur':
            sigma   = max(1.0, radius / 1.5)
            falloff = np.exp(-dist2 / (2 * sigma ** 2)).astype(np.float32)
            alpha   = (strength * falloff).astype(np.float32)
        elif brush == 'smear':
            inner2 = (radius * 0.5) ** 2
            ring   = ((dist2 >= inner2) & (dist2 <= radius ** 2)).astype(np.float32)
            sigma  = max(1.0, radius / 3.0)
            soft   = np.exp(-dist2 / (2 * sigma ** 2)).astype(np.float32)
            alpha  = (strength * ring * soft).astype(np.float32)
        elif brush == 'airbrush':
            sigma   = max(1.0, radius / 1.2)
            falloff = np.exp(-dist2 / (2 * sigma ** 2)).astype(np.float32)
            alpha   = (strength * 0.35 * falloff).astype(np.float32)
        elif brush == 'hill':
            # Raised-cosine dome — full raise at centre, smooth taper to 0 at edge
            dist_n  = np.sqrt(dist2) / max(1.0, float(radius))
            dome    = (0.5 * (1.0 + np.cos(np.pi * np.clip(dist_n, 0.0, 1.0)))).astype(np.float32)
            mask    = (dist2 <= radius ** 2).astype(np.float32)
            alpha   = (strength * dome * mask).astype(np.float32)
        elif brush == 'slope':
            # One-sided linear ramp: 0 at bottom (back), 1 at top (front)
            _sa = math.radians(getattr(self, '_te_slope_angle', 0))
            dir_x, dir_y = math.cos(_sa), math.sin(_sa)
            perp_x, perp_y = -dir_y, dir_x
            proj      = np.clip((dx * dir_x + dy * dir_y) / max(1.0, float(b_len)) * 0.5 + 0.5,
                                0.0, 1.0).astype(np.float32)
            perp_dist = np.abs(dx * perp_x + dy * perp_y)
            wid_mask  = (perp_dist <= b_wid).astype(np.float32)
            alpha     = (strength * proj * wid_mask).astype(np.float32)
        else:
            sigma   = max(1.0, radius / 3.0)
            falloff = np.exp(-dist2 / (2 * sigma ** 2)).astype(np.float32)
            mask    = (dist2 <= radius ** 2).astype(np.float32)
            alpha   = (strength * falloff * mask).astype(np.float32)

        sl_y = slice(y0, y1 + 1)
        sl_x = slice(x0, x1 + 1)
        region = c[sl_y, sl_x].copy()

        target_h = self._te_target_h
        if brush == 'slope':
            # Slope always applies signed gradient regardless of tool
            region += alpha * 5.0
        elif brush == 'hill':
            # Hill: raise + dome shape (lower with Lower tool)
            if tool == 'lower':
                region -= alpha * 5.0
            elif tool == 'flatten':
                region += (target_h - region) * alpha
            elif tool == 'smooth':
                pad = np.pad(region, 1, mode='edge')
                smoothed = (
                    pad[:-2, :-2] + pad[:-2, 1:-1] + pad[:-2, 2:] +
                    pad[1:-1, :-2] + pad[1:-1, 1:-1] + pad[1:-1, 2:] +
                    pad[2:, :-2]   + pad[2:, 1:-1]   + pad[2:, 2:]
                ) / 9.0
                region = region * (1 - alpha) + smoothed * alpha
            else:
                region += alpha * 5.0
        elif tool == 'raise':
            region += alpha * 5.0
        elif tool == 'lower':
            region -= alpha * 5.0
        elif tool == 'flatten':
            region += (target_h - region) * alpha
        elif tool == 'smooth':
            pad = np.pad(region, 1, mode='edge')
            smoothed = (
                pad[:-2, :-2] + pad[:-2, 1:-1] + pad[:-2, 2:] +
                pad[1:-1, :-2] + pad[1:-1, 1:-1] + pad[1:-1, 2:] +
                pad[2:, :-2]   + pad[2:, 1:-1]   + pad[2:, 2:]
            ) / 9.0
            region = region * (1 - alpha) + smoothed * alpha

        c[sl_y, sl_x] = np.clip(region, 0.0, 511.99)
        td.mark_dirty_from_brush(cx, cy, self._te_size)
        tr = getattr(self, 'terrain_renderer', None)
        if tr is not None:
            if self.is_3d_mode:
                # In 3D mode the 2D pixmap is invisible — just sync the heightmap reference
                tr.combined_heightmap = c
            else:
                tr.update_from_heightmap(c)
        self._update_terrain_mesh_heights()

    @staticmethod
    def _in_rect(x, y, rect):
        if rect is None:
            return False
        rx, ry, rw, rh = rect
        return rx <= x <= rx + rw and ry <= y <= ry + rh

    def _is_over_te_ui(self, x, y):
        """Return True if (x, y) is over any terrain-edit UI element (suppress gizmo/stroke)."""
        for r in (self._snap_badge_rect, self._terrain_edit_badge_rect):
            if self._in_rect(x, y, r):
                return True
        return False

    def _terrain_edit_unproject(self, sx, sy):
        """Read depth at screen pixel (sx, sy) and unproject to 3D world coords.
        Returns (wx, wy, wz) or None if nothing was hit (sky/depth=1.0)."""
        try:
            dpr = self.devicePixelRatio()
            px  = float(sx) * dpr
            vp  = glGetIntegerv(GL_VIEWPORT)
            gl_y = float(vp[3]) - float(sy) * dpr

            mv   = glGetDoublev(GL_MODELVIEW_MATRIX)
            proj = glGetDoublev(GL_PROJECTION_MATRIX)

            depth = glReadPixels(int(px), int(gl_y), 1, 1, GL_DEPTH_COMPONENT, GL_FLOAT)
            if depth is None:
                return None
            d = float(np.asarray(depth).flat[0])
            if d >= 0.9999:
                return None

            wx, wy, wz = gluUnProject(px, gl_y, d, mv, proj, vp)
            return float(wx), float(wy), float(wz)
        except Exception as e:
            print(f"[TerrainEdit] unproject error: {e}")
            return None

    def _world_to_heightmap_coords(self, wx, wz):
        """Convert 3D world (wx, wz) to heightmap pixel (hx, hy).
        In the 3D scene: map_x = wx, map_y = -wz.
        Falls back to the terrain editor dialog's heightmap shape when the
        terrain renderer has no combined_heightmap loaded.
        Returns (hx, hy) or None if outside terrain bounds."""
        tr = getattr(self, 'terrain_renderer', None)
        combined = getattr(tr, 'combined_heightmap', None) if tr else None

        if combined is None:
            td = getattr(self, '_terrain_data', None)
            if td is not None:
                combined = td.combined

        if combined is None:
            te = self._get_terrain_editor()
            if te is not None:
                combined = getattr(te._td, 'combined', None)

        if combined is None:
            return None

        h_px, w_px = combined.shape
        ox = getattr(self, 'terrain_world_offset_x',
                     getattr(tr, 'terrain_offset_x', 0.0) if tr else 0.0)
        oy = getattr(self, 'terrain_world_offset_y',
                     getattr(tr, 'terrain_offset_y', 0.0) if tr else 0.0)
        map_x = wx
        map_y = -wz
        world_w = float(w_px - 1)
        world_h = float(h_px - 1)
        if world_w <= 0 or world_h <= 0:
            return None
        nx = (map_x - ox) / world_w
        ny = (map_y - oy) / world_h
        if nx < 0.0 or nx > 1.0 or ny < 0.0 or ny > 1.0:
            return None
        hx = int(nx * (w_px - 1) + 0.5)
        hy = int((1.0 - ny) * (h_px - 1) + 0.5)
        return hx, hy

    def _render_terrain_edit_gizmo(self):
        """Draw a brush outline on the terrain surface matching the active brush shape."""
        if not self.terrain_edit_mode or self._terrain_edit_hit is None:
            return
        wx, wy, wz = self._terrain_edit_hit

        tr    = getattr(self, 'terrain_renderer', None)
        r     = float(self._te_size)
        brush = getattr(self, '_te_brush_type', 'circle')
        LIFT  = 1.5
        SEG   = 64

        def _gy(gx, gz):
            if tr is not None and getattr(tr, 'combined_heightmap', None) is not None:
                ox = getattr(self, 'terrain_world_offset_x', tr.terrain_offset_x)
                oy = getattr(self, 'terrain_world_offset_y', tr.terrain_offset_y)
                return tr.get_height_at_world(gx, -gz, ox, oy)
            return wy

        def _ring(radius, color):
            glColor3f(*color)
            glBegin(GL_LINE_LOOP)
            for i in range(SEG):
                a = 2.0 * math.pi * i / SEG
                gx = wx + math.cos(a) * radius
                gz = wz + math.sin(a) * radius
                glVertex3f(gx, _gy(gx, gz) + LIFT, gz)
            glEnd()

        def _rect(rw, rh, color):
            glColor3f(*color)
            glBegin(GL_LINE_LOOP)
            for ddx, ddz in ((-rw, -rh), (rw, -rh), (rw, rh), (-rw, rh)):
                gx = wx + ddx; gz = wz + ddz
                glVertex3f(gx, _gy(gx, gz) + LIFT, gz)
            glEnd()

        try:
            glDisable(GL_LIGHTING)
            glDisable(GL_DEPTH_TEST)
            glLineWidth(2.0)

            if brush == 'circle':
                _ring(r, (1.0, 1.0, 0.0))

            elif brush == 'square':
                _rect(r, r, (1.0, 1.0, 0.0))

            elif brush == 'rectangle':
                _rect(float(getattr(self, '_te_brush_len', 32)),
                      float(getattr(self, '_te_brush_wid', 12)), (1.0, 1.0, 0.0))

            elif brush == 'blur':
                _ring(r * 2.0, (0.5, 0.8, 1.0))
                glLineWidth(1.0)
                _ring(r, (0.3, 0.5, 0.8))
                glLineWidth(2.0)

            elif brush == 'smear':
                _ring(r, (1.0, 0.8, 0.0))
                glLineWidth(1.0)
                _ring(r * 0.5, (1.0, 0.8, 0.0))
                glLineWidth(2.0)

            elif brush == 'airbrush':
                _ring(r * 2.0, (0.8, 0.6, 1.0))
                glLineWidth(1.0)
                _ring(r, (0.5, 0.3, 0.8))
                glLineWidth(2.0)

            elif brush == 'hill':
                _ring(r, (1.0, 1.0, 0.0))
                glLineWidth(1.0)
                _ring(r * 0.5, (1.0, 0.5, 0.0))
                glLineWidth(2.0)

            elif brush == 'slope':
                _sa = math.radians(getattr(self, '_te_slope_angle', 0))
                dir_x, dir_z = math.cos(_sa), math.sin(_sa)
                perp_x, perp_z = -dir_z, dir_x
                s_len = float(getattr(self, '_te_brush_len', 32))
                s_wid = float(getattr(self, '_te_brush_wid', 12))
                bot_x = wx - dir_x * s_len;  bot_z = wz - dir_z * s_len
                tip_x = wx + dir_x * s_len;  tip_z = wz + dir_z * s_len
                glColor3f(1.0, 0.8, 0.0)
                glBegin(GL_LINE_LOOP)
                for along, perp in ((-s_len, -s_wid), (s_len, -s_wid), (s_len, s_wid), (-s_len, s_wid)):
                    gx = wx + along * dir_x + perp * perp_x
                    gz = wz + along * dir_z + perp * perp_z
                    glVertex3f(gx, _gy(gx, gz) + LIFT, gz)
                glEnd()
                # Green arrow from bottom (low end) to tip (rise direction)
                glColor3f(0.0, 1.0, 0.4)
                glBegin(GL_LINES)
                glVertex3f(bot_x, _gy(bot_x, bot_z) + LIFT, bot_z)
                glVertex3f(tip_x, _gy(tip_x, tip_z) + LIFT, tip_z)
                glEnd()
                # Crosshair at bottom (low end of slope)
                cross = r * 0.25
                glColor3f(1.0, 1.0, 0.0)
                glBegin(GL_LINES)
                glVertex3f(bot_x - cross, _gy(bot_x, bot_z) + LIFT, bot_z)
                glVertex3f(bot_x + cross, _gy(bot_x, bot_z) + LIFT, bot_z)
                glVertex3f(bot_x, _gy(bot_x, bot_z) + LIFT, bot_z - cross)
                glVertex3f(bot_x, _gy(bot_x, bot_z) + LIFT, bot_z + cross)
                glEnd()

            # Crosshair at cursor centre (all brushes except slope which draws its own)
            if brush != 'slope':
                cross = r * 0.25
                glColor3f(1.0, 1.0, 0.0)
                glBegin(GL_LINES)
                glVertex3f(wx - cross, wy + LIFT, wz)
                glVertex3f(wx + cross, wy + LIFT, wz)
                glVertex3f(wx, wy + LIFT, wz - cross)
                glVertex3f(wx, wy + LIFT, wz + cross)
                glEnd()

            glLineWidth(1.0)
            glEnable(GL_DEPTH_TEST)
            glEnable(GL_LIGHTING)
        except Exception:
            pass

    def _render_terrain_paint_gizmo(self):
        """Draw a brush gizmo on the terrain surface for texture paint mode.
        Shape mirrors _tp_brush_shape; colour reflects the active texture type."""
        if not self.terrain_paint_mode or self._terrain_edit_hit is None:
            return
        wx, wy, wz = self._terrain_edit_hit
        tr    = getattr(self, 'terrain_renderer', None)
        r     = float(self._te_size)
        shape = self._tp_brush_shape
        SEG   = 48
        LIFT  = 1.5

        def _gy(gx, gz):
            if tr is not None and getattr(tr, 'combined_heightmap', None) is not None:
                ox = getattr(self, 'terrain_world_offset_x', tr.terrain_offset_x)
                oy = getattr(self, 'terrain_world_offset_y', tr.terrain_offset_y)
                return tr.get_height_at_world(gx, -gz, ox, oy)
            return wy

        # Colour depends on active texture type
        tex_key = getattr(self, '_tp_active_tex_key', 'mask')
        if tex_key == 'mask':
            _TP_GL_COLORS = [
                (0.86, 0.12, 0.12),
                (0.12, 0.78, 0.12),
                (0.12, 0.31, 0.86),
                (0.15, 0.15, 0.15),
            ]
            ch = max(0, min(3, self._tp_paint_channel))
            cr, cg, cb = _TP_GL_COLORS[ch]
        elif tex_key == 'color':
            v = max(0.25, self._te_paint_color[0] / 255.0)
            cr, cg, cb = v, v, v
        else:  # diffuse
            cr, cg, cb = 1.0, 0.85, 0.3

        def _ring(radius, col):
            glColor3f(*col)
            glBegin(GL_LINE_LOOP)
            for i in range(SEG):
                a  = 2.0 * math.pi * i / SEG
                gx = wx + math.cos(a) * radius
                gz = wz + math.sin(a) * radius
                glVertex3f(gx, _gy(gx, gz) + LIFT, gz)
            glEnd()

        def _rect(rw, rh, col):
            glColor3f(*col)
            glBegin(GL_LINE_LOOP)
            for ddx, ddz in ((-rw, -rh), (rw, -rh), (rw, rh), (-rw, rh)):
                gx = wx + ddx; gz = wz + ddz
                glVertex3f(gx, _gy(gx, gz) + LIFT, gz)
            glEnd()

        def _diamond(rad, col):
            glColor3f(*col)
            glBegin(GL_LINE_LOOP)
            for ddx, ddz in ((0.0, -rad), (rad, 0.0), (0.0, rad), (-rad, 0.0)):
                gx = wx + ddx; gz = wz + ddz
                glVertex3f(gx, _gy(gx, gz) + LIFT, gz)
            glEnd()

        def _triangle(rad, col):
            glColor3f(*col)
            glBegin(GL_LINE_LOOP)
            for ddx, ddz in ((0.0, -rad), (rad, rad), (-rad, rad)):
                gx = wx + ddx; gz = wz + ddz
                glVertex3f(gx, _gy(gx, gz) + LIFT, gz)
            glEnd()

        try:
            glDisable(GL_LIGHTING)
            glDisable(GL_DEPTH_TEST)
            glLineWidth(2.5)

            if shape == 'square':
                _rect(r, r, (cr, cg, cb))
            elif shape == 'diamond':
                _diamond(r, (cr, cg, cb))
            elif shape == 'triangle':
                _triangle(r, (cr, cg, cb))
            else:  # circle
                _ring(r, (cr, cg, cb))
                glLineWidth(1.0)
                _ring(r * 0.4, (cr * 0.6, cg * 0.6, cb * 0.6))
                glLineWidth(2.5)

            # Crosshair at cursor centre
            cross = r * 0.25
            glColor3f(cr, cg, cb)
            glBegin(GL_LINES)
            glVertex3f(wx - cross, wy + LIFT, wz)
            glVertex3f(wx + cross, wy + LIFT, wz)
            glVertex3f(wx, wy + LIFT, wz - cross)
            glVertex3f(wx, wy + LIFT, wz + cross)
            glEnd()

            glLineWidth(1.0)
            glEnable(GL_DEPTH_TEST)
            glEnable(GL_LIGHTING)
        except Exception:
            pass

    def set_terrain_visibility(self, visible):
        """Toggle terrain visibility"""
        if hasattr(self, 'terrain_renderer'):
            self.terrain_renderer.show_terrain = visible
            self.update()

    def set_terrain_opacity(self, opacity):
        """Set terrain opacity (0.0 to 1.0)"""
        if hasattr(self, 'terrain_renderer'):
            self.terrain_renderer.set_opacity(opacity)
            self.update()

    def setup_3d_models(self):
        """Setup 3D model loader with models directory, EntityLibrary, AND materials for textures"""
        import os
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        models_path = os.path.join(current_dir, "assets", "models", "graphics")
        
        print(f"\n=== 3D Models & Textures Setup ===")
        
        # Setup models directory
        if os.path.exists(models_path):
            success = self.model_loader.set_models_directory(models_path)
            if success:
                print(f"3D models directory indexed")
        else:
            print(f" Models directory not found: {models_path}")
        
        # Setup EntityLibrary folder - TRY MULTIPLE WAYS TO FIND IT
        worlds_path = None
        
        # Method 1: Direct attribute
        if hasattr(self, 'main_window'):
            worlds_path = getattr(self.main_window, 'worlds_folder', None)
            if worlds_path:
                print(f"Found worlds_folder from main_window.worlds_folder")
        
        # Method 2: Try parent
        if not worlds_path and hasattr(self, 'parent') and self.parent():
            worlds_path = getattr(self.parent(), 'worlds_folder', None)
            if worlds_path:
                print(f"Found worlds_folder from parent")
        
        # Method 3: Search for it from loaded XML path
        if not worlds_path and hasattr(self, 'main_window'):
            if hasattr(self.main_window, 'xml_file_path'):
                xml_path = self.main_window.xml_file_path
                if xml_path:
                    # Go up from XML to worlds folder
                    # e.g., worlds/generated/worlds/level.xml -> worlds/
                    worlds_path = os.path.dirname(os.path.dirname(os.path.dirname(xml_path)))
                    print(f"Derived worlds_folder from XML path: {worlds_path}")
        
        # Method 4: Ask user to set it manually (fallback)
        if not worlds_path:
            print(" Could not find worlds folder automatically")
            print("   Please add this to your main window initialization:")
            print("   self.worlds_folder = r'path/to/your/Avatar/worlds'")
            print("\n   Example paths:")
            print("   - Avatar: D:\\Games\\Avatar The Game\\Data_Win32\\worlds")
            print("   - FC2: D:\\Games\\Far Cry 2\\Data_Win32\\worlds")
        
        if worlds_path and os.path.exists(worlds_path):
            success = self.model_loader.set_entity_library_folder(worlds_path)
            if success:
                print(f"EntityLibrary configured")
        
        # Setup materials directory for textures
        if worlds_path:
            # Derive game data path from worlds folder
            game_data_path = os.path.dirname(worlds_path)  # worlds/../Data
            materials_path = os.path.join(game_data_path, "graphics", "_materials")
            
            if os.path.exists(materials_path):
                self.model_loader.set_materials_directory(materials_path)
            else:
                print(f" Materials folder not found at: {materials_path}")
                print("   Models will render without textures")
        
        print("=" * 50 + "\n")

    def setup_renderers(self):
        """Initialize all renderer modules"""
        try:
            self.grid_renderer = GridRenderer()
            self.entity_renderer = EntityRenderer()
            self.gizmo_renderer = GizmoRenderer()
            self.gizmo_3d = Gizmo3D()
            self.terrain_renderer = TerrainRenderer(game_mode=getattr(self, 'game_mode', 'avatar'))
            self.water_mesh_editor = ImprovedWaterMeshEditor()
            self.water_plane_renderer = WaterPlaneRenderer()
            self.camera_controller = CameraController()
            self.input_handler = InputHandler(self)
            self.undo_redo = UndoRedoManager()
            
            if self.use_gpu_rendering:
                self.grid_renderer.use_opengl = True
            
            print("All renderer modules initialized (2D AND 3D)")
            
        except Exception as e:
            print(f"Error setting up renderers: {e}")
            import traceback
            traceback.print_exc()

    def setup_canvas(self):
        """Setup canvas properties and timers"""
        self.movement_timer = QTimer(self)
        self.movement_timer.setInterval(16)  # 60 FPS
        self.movement_timer.timeout.connect(self.update_movement)
        self.movement_timer.start()

        self._glow_timer = QTimer(self)
        self._glow_timer.setInterval(33)  # ~30 FPS pulse
        self._glow_timer.timeout.connect(self._on_glow_tick)
        self._glow_timer.start()
        
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus()
        
        print("Canvas event handling setup complete - 2D AND 3D")

    def _on_glow_tick(self):
        """Drive the selection-glow pulse AND animated-UV (Unlit/FX scroll)
        repaint in 3D mode. Repaints at the glow timer's ~30 FPS whenever
        something is selected OR any loaded material has scrolling UVs."""
        if self.mode != MODE_3D:
            return
        # Advance the day/night cycle when playing.
        if self.day_night_enabled and self._daynight_play:
            self.time_of_day = (self.time_of_day + self._daynight_speed) % 1.0
        if (self.selected_entity is not None
                or getattr(self, '_dbg_mode', 0) != 0   # keep profiler updating live
                or (self.day_night_enabled and self._daynight_play)
                or getattr(getattr(self, 'model_loader', None),
                           'has_animated_materials', False)):
            self.update()

    def resizeGL(self, width, height):
        """Handle OpenGL viewport resize"""
        if not self.use_gpu_rendering:
            return
            
        try:
            gl.glViewport(0, 0, width, height)
            print(f"OpenGL viewport resized: {width}x{height}")
        except Exception as e:
            print(f"Error resizing OpenGL viewport: {e}")
    
    def _print_gl_caps(self):
        """One-shot dump of the GL context's capabilities — decides the GPU-driven
        (MultiDrawIndirect) render design: which GL version we actually have, and
        how to feed 1500+ unique textures to few draws (bindless vs texture array).
        Read-only; fully guarded so it can never break rendering."""
        import OpenGL.GL as _g
        def s(e):
            try: return _g.glGetString(e).decode(errors='replace')
            except Exception: return '?'
        def i(e):
            try: return int(_g.glGetIntegerv(e))
            except Exception: return '?'
        exts = set()
        try:
            from OpenGL.GL import glGetStringi
            for k in range(i(_g.GL_NUM_EXTENSIONS)):
                exts.add(glGetStringi(_g.GL_EXTENSIONS, k).decode(errors='replace'))
        except Exception:
            try: exts = set(s(_g.GL_EXTENSIONS).split())
            except Exception: pass
        def fn(name): return hasattr(_g, name)
        print("=" * 64)
        print("=== GL CAPABILITIES (for GPU-driven / MultiDrawIndirect design) ===")
        print(f"  VERSION : {s(_g.GL_VERSION)}")
        print(f"  GLSL    : {s(_g.GL_SHADING_LANGUAGE_VERSION)}")
        print(f"  VENDOR  : {s(_g.GL_VENDOR)}")
        print(f"  RENDERER: {s(_g.GL_RENDERER)}")
        print(f"  MultiDrawElementsIndirect fn : {fn('glMultiDrawElementsIndirect')}")
        print(f"  DrawElementsIndirect fn      : {fn('glDrawElementsIndirect')}")
        print(f"  ARB_multi_draw_indirect ext  : {'GL_ARB_multi_draw_indirect' in exts}")
        print(f"  ARB_bindless_texture ext     : {'GL_ARB_bindless_texture' in exts}")
        print(f"  ARB_shader_storage_buffer    : {'GL_ARB_shader_storage_buffer_object' in exts}")
        print(f"  ARB_draw_indirect ext        : {'GL_ARB_draw_indirect' in exts}")
        print(f"  MAX_ARRAY_TEXTURE_LAYERS     : {i(_g.GL_MAX_ARRAY_TEXTURE_LAYERS)}")
        print(f"  MAX_COMBINED_TEXTURE_UNITS   : {i(_g.GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS)}")
        print(f"  total extensions             : {len(exts)}")
        print("=" * 64)

    # F1 debug-mode cycle: Off → Profile → per-feature A/B. Each mode beyond
    # "Off" enables the per-stage + GPU profiler print; modes 2-5 also toggle one
    # fragment feature so the GPU-ms delta reveals that feature's cost.
    _DBG_MODES = ('OFF', 'PROFILE (all features on)', 'NO NORMAL MAPS',
                  'NO SPECULAR', 'NO EMISSION', 'UNLIT (skip per-light loop)')

    def _cycle_debug_mode(self):
        self._dbg_mode = (getattr(self, '_dbg_mode', 0) + 1) % len(self._DBG_MODES)
        m = self._dbg_mode
        ml = getattr(self, 'model_loader', None)
        if ml is not None:
            ml.dbg_no_normal = (m == 2)
            ml.dbg_no_spec = (m == 3)
            ml.dbg_no_emission = (m == 4)
            ml.dbg_unlit = (m == 5)
        print(f"🔧 [F1] render debug: {self._DBG_MODES[m]}"
              + ("  — watch the GPU ms vs PROFILE mode" if m >= 2 else ""))
        self.update()

    def _set_render_tier(self, tier):
        """F2/F3: force the GPU-driven render tier ('bindless'=NVIDIA, 'texarray'
        =AMD), or toggle back off (universal fallback). Lets us test both paths on
        one machine. v1 is flat-lit/untextured, so both tiers look the same for now
        (textures diverge in the next stage)."""
        ml = getattr(self, 'model_loader', None)
        if ml is None:
            print("🖥️ no model_loader yet")
            return
        cur = getattr(ml, 'force_render_tier', None)
        ml.force_render_tier = None if cur == tier else tier
        label = {'bindless': 'NVIDIA / bindless', 'texarray': 'AMD / texture-array'}.get(tier, tier)
        state = label if ml.force_render_tier else 'OFF (universal fallback path)'
        print(f"🖥️ [GPU-driven] render tier: {state}")
        self.update()

    def _toggle_day_night(self):
        """F4: cycle OFF → ON(playing) → PAUSED → OFF. (Temporary control while the
        slider/play UI is built.)"""
        if not self.day_night_enabled:
            self.day_night_enabled = True
            self._daynight_play = True
            print(f"🌅 Day/night cycle: ON (playing), time={self.time_of_day:.2f}")
        elif self._daynight_play:
            self._daynight_play = False
            print(f"⏸️ Day/night cycle: PAUSED at time={self.time_of_day:.2f}")
        else:
            self.day_night_enabled = False
            print("☀️ Day/night cycle: OFF (static lighting)")
        self.update()

    def _toggle_flip_green(self):
        ml = getattr(self, 'model_loader', None)
        if ml is None:
            return
        ml.dbg_flip_green = not getattr(ml, 'dbg_flip_green', False)
        print(f"🟢 [F5] normal-map GREEN (Y) flip: {'ON' if ml.dbg_flip_green else 'OFF'}")
        self.update()

    def _toggle_flip_normal(self):
        ml = getattr(self, 'model_loader', None)
        if ml is None:
            return
        ml.dbg_flip_normal = not getattr(ml, 'dbg_flip_normal', False)
        print(f"🔵 [F6] base NORMAL flip: {'ON' if ml.dbg_flip_normal else 'OFF'}")
        self.update()

    def _toggle_shadows(self):
        self.shadows_enabled = not getattr(self, 'shadows_enabled', True)
        state = 'ON' if self.shadows_enabled else 'OFF'
        extra = '' if self.day_night_enabled else ' (enable day/night [F4] to see them)'
        print(f"🌑 [F7] sun shadows: {state}{extra}")
        self.update()

    def _toggle_depth_prepass(self):
        ml = getattr(self, 'model_loader', None)
        if ml is None:
            return
        ml.gpu_depth_prepass = not getattr(ml, 'gpu_depth_prepass', True)
        on = ml.gpu_depth_prepass
        extra = '' if getattr(ml, 'force_render_tier', None) else ' (needs GPU-driven path [F2])'
        print(f"🟣 [F8] depth prepass (early-Z occlusion): {'ON' if on else 'OFF'}{extra}")
        self.update()

    def _cast_sun_shadows(self):
        """Render model depth from the sun into the shadow map, then tell the
        model_loader to sample it. Called after prepare_batches (so the visible
        instance set is current) and before render_batched_models. Only active
        when day/night is on, shadows are enabled, and the sun is above the
        horizon. On any problem the scene simply renders unshadowed."""
        ml = getattr(self, 'model_loader', None)
        if ml is None:
            return
        active = False
        # Stage 1 receivers are the GPU-driven models (F2/F3). On the universal
        # fallback path there's nothing to receive yet, so skip the depth pass.
        if (getattr(ml, 'force_render_tier', None)
                and self.day_night_enabled and getattr(self, 'shadows_enabled', True)
                and getattr(self, '_sun_elev_sin', -1.0) > 0.05):
            try:
                if self._shadow_map is None:
                    from shadow_map import ShadowMap
                    self._shadow_map = ShadowMap()
                sm = self._shadow_map
                light_vp = sm.update_light_vp(
                    self.camera_3d.position, self.camera_3d.forward,
                    getattr(self, '_sun_dir_world', (0.0, 1.0, 0.0)))
                if sm.begin() is not None:
                    cast = ml.cast_shadows(light_vp)
                    sm.end(self.defaultFramebufferObject(), self.width(), self.height())
                    if cast:
                        ml.set_shadow_inputs(sm.tex, light_vp, True)
                        active = True
            except Exception as _e:
                print(f"[shadow] cast pass error: {_e}")
        if not active:
            ml.set_shadow_inputs(0, None, False)

    # ── Day/night control API (for the slider/play UI) ──
    def set_day_night_enabled(self, enabled):
        self.day_night_enabled = bool(enabled)
        self.update()

    def set_time_of_day(self, t01):
        """Set time of day as a 0..1 fraction (0=midnight, .25=sunrise, .5=noon)."""
        self.time_of_day = float(t01) % 1.0
        self.update()

    def set_daynight_playing(self, playing):
        self._daynight_play = bool(playing)
        if playing:
            self.day_night_enabled = True
        self.update()

    def _pf(self, key, t0):
        """Accumulate elapsed ms since perf_counter t0 into this frame's profile
        under `key`; return the current perf_counter (for chaining stages)."""
        from time import perf_counter as _pc
        now = _pc()
        pf = getattr(self, '_prof', None)
        if pf is not None:
            pf[key] = pf.get(key, 0.0) + (now - t0) * 1000.0
        return now

    def _gpu_timer_begin(self):
        """Start this frame's GL_TIME_ELAPSED query (ping-pong, 2 queries) and
        return an earlier frame's GPU time in ms (or None). Frame-latent so it
        never stalls; fully wrapped so a missing extension can't break rendering."""
        if getattr(self, '_gpu_timer_failed', False):
            return None
        try:
            if getattr(self, '_gpu_q', None) is None:
                qs = glGenQueries(2)
                self._gpu_q = [int(qs[0]), int(qs[1])]
                self._gpu_q_n = 0
                self._gpu_q_started = [False, False]
            i = self._gpu_q_n % 2
            ms = None
            if self._gpu_q_started[i]:               # issued 2 frames ago → ready
                # 32-bit getter on purpose: PyOpenGL's ui64 result converter is
                # broken on AMD (GL_UNSIGNED_INT64_AMD). Nanoseconds fit in uint32
                # up to ~4.29s/frame — far beyond any real frame time.
                val = glGetQueryObjectuiv(self._gpu_q[i], GL_QUERY_RESULT)
                try:
                    val = val[0]                     # PyOpenGL may return a 1-array
                except (TypeError, IndexError):
                    pass
                ms = float(val) / 1.0e6
            glBeginQuery(GL_TIME_ELAPSED, self._gpu_q[i])
            self._gpu_q_started[i] = True
            self._gpu_q_pending_end = True
            self._gpu_q_n += 1
            return ms
        except Exception as e:
            self._gpu_timer_failed = True
            print(f"[profiler] GPU timer unavailable ({e}) — CPU timing only")
            return None

    def _gpu_timer_end(self):
        if getattr(self, '_gpu_timer_failed', False):
            return
        if not getattr(self, '_gpu_q_pending_end', False):
            return
        try:
            glEndQuery(GL_TIME_ELAPSED)
        except Exception:
            self._gpu_timer_failed = True
        self._gpu_q_pending_end = False

    def _accumulate_profile(self, frame_ms, gpu_ms):
        """Roll this frame's CPU stage times + total CPU/GPU ms into a 60-frame
        average and print a breakdown so we can SEE which stage dominates."""
        acc = getattr(self, '_prof_acc', None)
        if acc is None:
            acc = self._prof_acc = {}
        for k, v in (getattr(self, '_prof', None) or {}).items():
            acc[k] = acc.get(k, 0.0) + v
        self._frame_ms_accum = getattr(self, '_frame_ms_accum', 0.0) + frame_ms
        if gpu_ms is not None:
            self._gpu_ms_accum = getattr(self, '_gpu_ms_accum', 0.0) + gpu_ms
            self._gpu_ms_n = getattr(self, '_gpu_ms_n', 0) + 1
        self._frame_ms_n = getattr(self, '_frame_ms_n', 0) + 1
        if self._frame_ms_n < 60:
            return
        n = self._frame_ms_n
        cpu = self._frame_ms_accum / n
        drawn = getattr(self, '_cull_last_drawn', 0)
        # Stage breakdown, biggest first.
        stages = sorted(acc.items(), key=lambda kv: -kv[1])
        parts = "  ".join(f"{k}={v/n:.1f}" for k, v in stages if v / n >= 0.05)
        gpu_txt = ""
        if getattr(self, '_gpu_ms_n', 0) > 0:
            gpu_txt = f" | GPU {self._gpu_ms_accum / self._gpu_ms_n:.1f}ms"
        print(f"⏱️ FRAME {cpu:.1f}ms CPU{gpu_txt}  ({drawn} drawn) | {parts}")
        self._prof_acc = {}
        self._frame_ms_accum = 0.0
        self._frame_ms_n = 0
        self._gpu_ms_accum = 0.0
        self._gpu_ms_n = 0

    def paintGL(self):
        """Main OpenGL rendering"""
        if not self.use_gpu_rendering or not self.opengl_initialized:
            return

        # Frame-to-frame FPS (EMA-smoothed) for the on-screen counter.
        import time as _fpst
        _now = _fpst.perf_counter()
        _prev = getattr(self, '_fps_t_prev', None)
        if _prev is not None:
            _dt = _now - _prev
            if _dt > 0:
                _inst = 1.0 / _dt
                self._fps = _inst if not hasattr(self, '_fps') else (self._fps * 0.9 + _inst * 0.1)
        self._fps_t_prev = _now

        try:
            if self.mode == MODE_TOPDOWN:
                # 2D rendering
                gl.glClearColor(0.94, 0.94, 0.94, 1.0)
                gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
                self._render_2d_opengl()
            else:
                # 3D rendering — sky/background colour (time-driven when day/night on)
                if self.day_night_enabled:
                    _sr, _sg, _sb = self._sky_color()
                    gl.glClearColor(_sr, _sg, _sb, 1.0)
                else:
                    gl.glClearColor(0.94, 0.94, 0.94, 1.0)
                gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
                if not getattr(self, '_gl_caps_printed', False):
                    self._gl_caps_printed = True
                    try:
                        self._print_gl_caps()
                    except Exception as _e:
                        print(f"[gl-caps] probe failed: {_e}")
                # === Per-stage render profiler (only when F1 debug is on) ===
                # CPU: per-stage submit time (which pass eats the time) via _prof,
                # filled by _render_3d_opengl / _render_entities_3d. GPU: total frame
                # time via a (frame-latent, non-stalling) timer query — proves whether
                # we're CPU- or GPU-bound. No glFinish, so CPU/GPU still pipeline.
                # Off (mode 0) → zero overhead: _prof=None makes _pf() a no-op.
                dbg = getattr(self, '_dbg_mode', 0) != 0
                if dbg:
                    import time as _t
                    self._prof = {}                   # this frame's stage -> ms
                    gpu_ms = self._gpu_timer_begin()  # reads an earlier frame's GPU time
                    _f0 = _t.perf_counter()
                    self._render_3d_opengl()
                    _fms = (_t.perf_counter() - _f0) * 1000.0
                    self._gpu_timer_end()
                    self._accumulate_profile(_fms, gpu_ms)
                else:
                    self._prof = None
                    self._render_3d_opengl()

        except Exception as e:
            print(f"Error in paintGL: {e}")
            import traceback
            traceback.print_exc()

    def _render_selection_box(self, painter):
        """Render the selection box during drag"""
        if not hasattr(self, 'input_handler'):
            return
        
        box_coords = self.input_handler.get_selection_box()
        if not box_coords:
            return
        
        start_x, start_y, end_x, end_y = box_coords
        
        # Draw selection box rectangle
        from PyQt6.QtGui import QPen, QBrush, QColor
        
        # Semi-transparent blue fill
        painter.setBrush(QBrush(QColor(100, 150, 255, 50)))
        # Solid blue border
        painter.setPen(QPen(QColor(100, 150, 255, 200), 2))
        
        # Calculate rectangle bounds
        x = min(start_x, end_x)
        y = min(start_y, end_y)
        width = abs(end_x - start_x)
        height = abs(end_y - start_y)
        
        painter.drawRect(int(x), int(y), int(width), int(height))

    def _filter_entities_by_source(self, entities):
        """Filter entity list by per-source visibility flags. Returns same list if all on."""
        show_ws = self.show_worldsector_entities
        show_md = self.show_mapsdata_entities
        show_om = self.show_omnis_entities
        show_lm = self.show_landmark_entities
        if show_ws and show_md and show_om and show_lm:
            return entities
        result = []
        for e in entities:
            src  = getattr(e, 'source_file', '') or ''
            srcp = getattr(e, 'source_file_path', '') or ''
            is_landmark = 'landmark' in srcp.lower()
            if is_landmark:
                if show_lm:
                    result.append(e)
            elif src == 'worldsectors':
                if show_ws:
                    result.append(e)
            elif src == 'mapsdata':
                if show_md:
                    result.append(e)
            elif src == 'omnis':
                if show_om:
                    result.append(e)
            else:
                result.append(e)  # managers, sectorsdep etc. always visible
        return result

    def _render_2d_opengl(self):
        """Render 2D scene"""
        if self.show_grid:
            self.grid_renderer.render_2d_grid(self)
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        try:
            if hasattr(self, 'terrain_renderer'):
                self.terrain_renderer.render_terrain_2d(painter, self)
            
            if self.show_entities:
                entities_to_draw = self._filter_entities_by_source(self._get_visible_entities())
                if entities_to_draw:
                    self.entity_renderer.render_entities_2d(painter, self, entities_to_draw)

            draw_movie_paths_2d(painter, self)

            self.gizmo_renderer.render_rotation_gizmo_2d(painter, self)

            # ADD THIS LINE HERE:
            self._render_selection_box(painter)

            if getattr(self, 'show_sector_boundaries', False):
                self.draw_sector_boundaries(painter)

            self._draw_2d_mode_indicator(painter)

        finally:
            painter.end()

    def _ensure_terrain_vbo(self, mesh):
        """Upload a large static terrain mesh to GPU buffers ONCE.

        The terrain (often 1.5M+ indices) was rendered in 'immediate mode' —
        client-side vertex arrays re-sent from CPU to GPU EVERY frame (~9 MB/frame
        of marshalling through PyOpenGL). That's a big hidden per-frame cost not
        even counted in the `entities=` profiler (terrain draws before entities).
        Uploading to a VBO once and drawing from GPU memory eliminates it.

        Returns a dict of buffer ids, or False (caller falls back to client arrays).
        """
        vbo = getattr(mesh, '_terr_vbo', None)
        if vbo is not None:
            return vbo
        try:
            verts = np.ascontiguousarray(mesh.vertices, dtype=np.float32)
            pos = glGenBuffers(1); glBindBuffer(GL_ARRAY_BUFFER, pos)
            glBufferData(GL_ARRAY_BUFFER, verts.nbytes, verts, GL_STATIC_DRAW)
            nrm = 0
            if mesh.normals is not None:
                n = np.ascontiguousarray(mesh.normals, dtype=np.float32)
                nrm = glGenBuffers(1); glBindBuffer(GL_ARRAY_BUFFER, nrm)
                glBufferData(GL_ARRAY_BUFFER, n.nbytes, n, GL_STATIC_DRAW)
            uv = 0
            if mesh.uvs is not None and len(mesh.uvs) > 0:
                u = np.ascontiguousarray(mesh.uvs, dtype=np.float32)
                uv = glGenBuffers(1); glBindBuffer(GL_ARRAY_BUFFER, uv)
                glBufferData(GL_ARRAY_BUFFER, u.nbytes, u, GL_STATIC_DRAW)
            ibo = 0; count = 0
            if mesh.indices is not None:
                idx = np.ascontiguousarray(mesh.indices, dtype=np.uint32)
                ibo = glGenBuffers(1); glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ibo)
                glBufferData(GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx, GL_STATIC_DRAW)
                count = int(len(idx))
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0)
            mesh._terr_vbo = {'pos': int(pos), 'nrm': int(nrm), 'uv': int(uv),
                              'ibo': int(ibo), 'count': count, 'nverts': int(verts.size // 3)}
            print(f"  ✅ Terrain VBO uploaded ({count} indices) — no more per-frame CPU transfer")
            return mesh._terr_vbo
        except Exception as e:
            print(f"  Terrain VBO creation failed ({e}) — falling back to client arrays")
            mesh._terr_vbo = False
            return False

    def _render_3d_opengl(self):
        """Render 3D scene using OpenGL with matching grid style"""
        try:
            # Regenerate terrain display list if water was updated
            if hasattr(self, 'water_mesh_editor'):
                self.water_mesh_editor.regenerate_if_needed()
            
            # Set up 3D projection
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            gluPerspective(50, self.width() / self.height(), 0.1, 10000.0)

            glMatrixMode(GL_MODELVIEW)
            glLoadIdentity()

            # Position camera first
            cam = self.camera_3d
            gluLookAt(
                cam.position[0], cam.position[1], cam.position[2],
                *cam.get_look_at(),
                0, 1, 0
            )

            # ── World-space sun lighting ────────────────────────────────────
            # Lights are set AFTER gluLookAt so their positions are in world
            # space — the sun stays fixed as the camera orbits, exactly like a
            # real sun in the sky.
            glEnable(GL_LIGHTING)
            glEnable(GL_LIGHT0)
            glEnable(GL_LIGHT1)
            glDisable(GL_LIGHT2)
            glEnable(GL_COLOR_MATERIAL)
            glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
            glEnable(GL_NORMALIZE)
            glLightModeli(GL_LIGHT_MODEL_LOCAL_VIEWER, GL_TRUE)

            # Sun: strong warm directional light high in the sky (world-space)
            glLightfv(GL_LIGHT0, GL_POSITION, self._key_light_pos())
            glLightfv(GL_LIGHT0, GL_DIFFUSE,  [0.90, 0.88, 0.82, 1.0])
            glLightfv(GL_LIGHT0, GL_SPECULAR, [0.50, 0.48, 0.44, 1.0])
            glLightfv(GL_LIGHT0, GL_AMBIENT,  [0.00, 0.00, 0.00, 1.0])
            # Sky fill: soft cool light from directly above (bounced sky light)
            glLightfv(GL_LIGHT1, GL_POSITION, [0.0, 1.0, 0.0, 0.0])
            glLightfv(GL_LIGHT1, GL_DIFFUSE,  [0.30, 0.33, 0.42, 1.0])
            glLightfv(GL_LIGHT1, GL_SPECULAR, [0.00, 0.00, 0.00, 1.0])
            glLightfv(GL_LIGHT1, GL_AMBIENT,  [0.00, 0.00, 0.00, 1.0])
            # Global ambient keeps unlit faces visible without a fake bottom light
            glLightModelfv(GL_LIGHT_MODEL_AMBIENT, [0.38, 0.38, 0.42, 1.0])
            glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR, [0.15, 0.15, 0.15, 1.0])
            glMaterialf(GL_FRONT_AND_BACK, GL_SHININESS, 40.0)
            # Day/night override: time-driven sun/moon + ambient + night factor
            # (set after the static rig so it wins; both render paths read these).
            if self.day_night_enabled:
                self._apply_day_night()
            else:
                self._night_factor = 0.0
            # ────────────────────────────────────────────────────────────────

            # Daytime atmosphere — fullscreen spectral sky (replaces the flat blue),
            # with a real sun + horizon gradient; darkens itself as the sun sets.
            if self.day_night_enabled:
                try:
                    if self._sky_atmosphere is None:
                        from sky_atmosphere import AtmosphereSky
                        self._sky_atmosphere = AtmosphereSky()
                    self._sky_atmosphere.render(
                        self.camera_3d, self._sun_elev_sin, self._sun_az,
                        self.width(), self.height(),
                        default_fbo=self.defaultFramebufferObject(),
                        sun_world=getattr(self, '_sun_dir_world', (0.0, 1.0, 0.0)))
                except Exception as _e:
                    print(f"[atmosphere] render error: {_e}")

            # Night-sky star dome — drawn as background (over the atmosphere), glows
            # in at night. Camera-centered + huge, additive (black→transparent).
            if self.day_night_enabled and self._night_factor > 0.01:
                try:
                    if self._night_sky is None:
                        from night_sky import NightSky
                        self._night_sky = NightSky(os.path.join(
                            os.path.dirname(__file__), 'assets', 'avatar', 'skybox', 'Night Sky.glb'))
                    self._night_sky.render(self.camera_3d.position, self._night_factor)
                except Exception as _e:
                    print(f"[night-sky] render error: {_e}")

            # Enable proper depth testing for solid rendering
            glEnable(GL_DEPTH_TEST)
            glDepthFunc(GL_LESS)
            glDepthMask(GL_TRUE)

            # Enable face culling to only render front faces
            glEnable(GL_CULL_FACE)
            glCullFace(GL_BACK)
            glFrontFace(GL_CCW)

            # Disable blending for opaque rendering
            glDisable(GL_BLEND)

            # --------------------------------------------------
            # DRAW TERRAIN (includes water - both in same display list)
            # --------------------------------------------------
            def _render_terrain_model(model, tx, ty):
                glPushMatrix()
                try:
                    if tx or ty:
                        glTranslatef(float(tx), 0.0, float(-ty))

                    # FC2 only: rotate 180° around terrain AABB centre to match the
                    # two -90° rotations applied to the 2D terrain image.
                    # Avatar 3D terrain is already in the correct orientation.
                    if getattr(self, 'game_mode', 'avatar') == 'farcry2':
                        _bmin = model.bounds_min if model.bounds_min is not None else [0, 0, 0]
                        _bmax = model.bounds_max if model.bounds_max is not None else [1024, 0, 1024]
                        _cx = (_bmin[0] + _bmax[0]) / 2.0
                        _cz = (_bmin[2] + _bmax[2]) / 2.0
                        glTranslatef(float(_cx), 0.0, float(-_cz))
                        glRotatef(180.0, 0.0, 1.0, 0.0)
                        glTranslatef(float(-_cx), 0.0, float(_cz))

                    # Terrain uses the same material as entities now that it has
                    # correct per-vertex normals and responds to sun lighting properly.
                    if hasattr(model, 'use_immediate_mode') and model.use_immediate_mode:
                        _z = ctypes.c_void_p(0)
                        for mesh in model.meshes:
                            if mesh.vertices is None:
                                continue
                            has_uvs = mesh.uvs is not None and len(mesh.uvs) > 0
                            has_texture = mesh.material_index is not None and mesh.material_index in model.textures
                            if has_texture:
                                glEnable(GL_TEXTURE_2D)
                                glBindTexture(GL_TEXTURE_2D, model.textures[mesh.material_index])
                                glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
                                glColor4f(1.0, 1.0, 1.0, 1.0)

                            # Default on (big win). If the ground ever renders black,
                            # set canvas._terrain_vbo_enabled = False to fall back to
                            # the proven client-array path while we debug.
                            tvbo = (self._ensure_terrain_vbo(mesh)
                                    if getattr(self, '_terrain_vbo_enabled', True) else False)
                            if tvbo:
                                # GPU-resident: bind buffers, draw with offsets — no
                                # per-frame CPU→GPU transfer of the 1.5M-index mesh.
                                glBindBuffer(GL_ARRAY_BUFFER, tvbo['pos'])
                                glEnableClientState(GL_VERTEX_ARRAY)
                                glVertexPointer(3, GL_FLOAT, 0, _z)
                                if tvbo['nrm']:
                                    glBindBuffer(GL_ARRAY_BUFFER, tvbo['nrm'])
                                    glEnableClientState(GL_NORMAL_ARRAY)
                                    glNormalPointer(GL_FLOAT, 0, _z)
                                if has_uvs and has_texture and tvbo['uv']:
                                    glBindBuffer(GL_ARRAY_BUFFER, tvbo['uv'])
                                    glEnableClientState(GL_TEXTURE_COORD_ARRAY)
                                    glTexCoordPointer(2, GL_FLOAT, 0, _z)
                                if tvbo['ibo']:
                                    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, tvbo['ibo'])
                                    glDrawElements(GL_TRIANGLES, tvbo['count'], GL_UNSIGNED_INT, _z)
                                else:
                                    glDrawArrays(GL_TRIANGLES, 0, tvbo['nverts'])
                                glBindBuffer(GL_ARRAY_BUFFER, 0)
                                glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0)
                                glDisableClientState(GL_VERTEX_ARRAY)
                                if tvbo['nrm']:
                                    glDisableClientState(GL_NORMAL_ARRAY)
                                if has_uvs and has_texture and tvbo['uv']:
                                    glDisableClientState(GL_TEXTURE_COORD_ARRAY)
                            else:
                                # Fallback: client arrays (re-sent from CPU each frame).
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
                    else:
                        if model.display_list:
                            glCallList(model.display_list)
                except Exception as e:
                    print(f"Error rendering terrain: {e}")
                finally:
                    glPopMatrix()

            import time as _time
            _ts = _time.perf_counter()
            if getattr(self, 'terrain_models', []):
                # Multi-cell mode (FC2 5×5 grid): each entry has its own world offset.
                for t_model, t_wx, t_wy in self.terrain_models:
                    _render_terrain_model(t_model, t_wx, t_wy)
            elif self.terrain_model:
                # Single-cell mode (Avatar / single FC2 cell).
                tx = getattr(self, 'terrain_world_offset_x',
                             getattr(self.terrain_renderer, 'terrain_offset_x', 0.0)
                             if hasattr(self, 'terrain_renderer') else 0.0)
                ty = getattr(self, 'terrain_world_offset_y',
                             getattr(self.terrain_renderer, 'terrain_offset_y', 0.0)
                             if hasattr(self, 'terrain_renderer') else 0.0)
                _render_terrain_model(self.terrain_model, tx, ty)
            _ts = self._pf('terrain', _ts)

            # *** MODIFIED: Check show_3d_grid toggle instead of show_grid ***
            if getattr(self, 'show_3d_grid', True):
                # Isolate all grid state changes (color, linewidth, lighting) from entity rendering
                glPushAttrib(GL_LINE_BIT | GL_CURRENT_BIT | GL_ENABLE_BIT)
                glDisable(GL_LIGHTING)
                # Compile grid into a display list on first use (or when game mode changes).
                # GL_COMPILE_AND_EXECUTE on first build so the grid draws immediately on that frame.
                grid_cache_key = (getattr(self, 'is_fc2_world', False), getattr(self, 'game_mode', ''))
                if getattr(self, '_grid_display_list', None) is None or getattr(self, '_grid_cache_key', None) != grid_cache_key:
                    if getattr(self, '_grid_display_list', None) is not None:
                        glDeleteLists(self._grid_display_list, 1)
                    self._grid_display_list = glGenLists(1)
                    self._grid_cache_key = grid_cache_key
                    glNewList(self._grid_display_list, GL_COMPILE_AND_EXECUTE)
                    draw_3d_grid(self, 5440, 64)
                    glEndList()
                else:
                    glCallList(self._grid_display_list)
                glPopAttrib()  # restores lighting, color, linewidth
            _ts = self._pf('grid', _ts)

            # Render water planes
            if hasattr(self, 'water_plane_renderer') and hasattr(self, 'terrain_renderer'):
                self.water_plane_renderer.render_water_planes(
                    self.terrain_renderer,
                    canvas=self,
                    water_mesh_editor=getattr(self, 'water_mesh_editor', None),
                )
            _ts = self._pf('water', _ts)

            # Draw entities (models always render, cubes conditional). Per-stage
            # timing goes into self._prof (printed by _accumulate_profile); the
            # 'cull'/'prepare'/'models'/'cubes' splits come from _render_entities_3d.
            if self.show_entities:
                _ts = _time.perf_counter()
                visible = self._get_visible_entities()
                _ts = self._pf('cull', _ts)
                visible = self._filter_entities_by_source(visible)
                _ts = self._pf('srcfilter', _ts)
                self._render_entities_3d(visible)        # times prepare/models/cubes internally
                # Wireframe overlays (prims + triggers + shape points + movie
                # paths) — cached across frames in world space; rebuilt only on
                # entity/selection changes. See _render_overlays_3d ('overlay3d'
                # profiler stage when cached; 'prims/triggers/shape' when not).
                self._render_overlays_3d(visible)

            _ts = _time.perf_counter()
            # Pulsing glow tint on selected entity's mesh (before beacon lines so lines stay on top)
            self._render_3d_selection_glow()

            # Selection beacon lines (always drawn, independent of show_entities)
            self._render_3d_selection_lines()

            # 3D gizmo — only visible in Edit mode
            if (hasattr(self, 'gizmo_3d') and
                    getattr(self.input_handler, 'edit_mode_3d', False)):
                self.gizmo_3d.render(self)
            _ts = self._pf('overlays', _ts)

            # Terrain edit heightmap mesh (visible when edit mode is active)
            self._render_terrain_edit_mesh()

            # Terrain edit brush gizmo
            self._render_terrain_edit_gizmo()

            # Terrain texture paint mesh (vertex-color overlay, same render path as edit mesh)
            self._render_terrain_paint_mesh()

            # Terrain paint brush gizmo (circle at cursor)
            self._render_terrain_paint_gizmo()

            # RESTORE OpenGL STATE for 2D rendering
            glDisable(GL_LIGHTING)
            glDisable(GL_LIGHT0)
            glDisable(GL_LIGHT1)
            glDisable(GL_NORMALIZE)
            glDisable(GL_CULL_FACE)
            glDisable(GL_DEPTH_TEST)

            # Re-enable blending for 2D mode
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

            # *** MODIFIED: Check show_3d_hud toggle before drawing UI overlays ***
            if getattr(self, 'show_3d_hud', True):
                # Draw 2D UI overlays on top
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)

                try:
                    self._draw_3d_ui_overlays(painter)
                finally:
                    painter.end()

        except Exception as e:
            print(f"Error in 3D rendering: {e}")
            import traceback
            traceback.print_exc()

    def _draw_3d_ui_overlays(self, painter):
        """Draw UI overlays for 3D mode"""
        margin = 10
        edit_mode = getattr(self.input_handler, 'edit_mode_3d', False)

        # ── FPS counter (top-right) ──
        fps = getattr(self, '_fps', None)
        if fps is not None:
            painter.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
            fm = painter.fontMetrics()
            fps_text = f"{fps:5.1f} FPS"
            if fps >= 50.0:
                fps_color = QColor(120, 230, 120)
            elif fps >= 30.0:
                fps_color = QColor(235, 215, 110)
            else:
                fps_color = QColor(235, 120, 120)
            tw = fm.horizontalAdvance(fps_text)
            fx = self.width() - margin - tw
            fy = margin + fm.ascent()
            painter.fillRect(fx - 6, margin, tw + 12, fm.height() + 4, QColor(0, 0, 0, 110))
            painter.setPen(QPen(fps_color, 1))
            painter.drawText(fx, fy + 2, fps_text)

        # View/Edit mode badge (bottom-left) — mirrors 2D badge style
        painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        metrics = painter.fontMetrics()

        mode_label = "EDIT MODE" if edit_mode else "VIEW MODE"
        hint_label = "Space: switch mode"

        if edit_mode:
            badge_color = QColor(180, 100, 0, 200)
            text_color  = QColor(255, 220, 120)
        else:
            badge_color = QColor(30, 100, 30, 200)
            text_color  = QColor(140, 220, 140)

        badge_w = metrics.horizontalAdvance(mode_label) + 14
        badge_h = metrics.height() + 6
        badge_x = margin
        badge_y = self.height() - margin - badge_h

        painter.fillRect(badge_x, badge_y, badge_w, badge_h, badge_color)
        painter.setPen(QPen(text_color, 1))
        painter.drawText(badge_x + 7, badge_y + metrics.ascent() + 3, mode_label)

        painter.setFont(QFont("Arial", 8))
        painter.setPen(QPen(QColor(160, 160, 160, 180), 1))
        painter.drawText(badge_x, badge_y - 3, hint_label)

        # Terrain snap badge (immediately right of the View/Edit badge)
        painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        metrics = painter.fontMetrics()
        snap_label = "TERRAIN SNAP"
        snap_w = metrics.horizontalAdvance(snap_label) + 14
        snap_h = badge_h
        snap_x = badge_x + badge_w + 6
        snap_y = badge_y

        snap_enabled = self.terrain_snap_enabled
        if snap_enabled:
            snap_bg    = QColor(20, 100, 160, 220)
            snap_fg    = QColor(120, 210, 255)
        else:
            snap_bg    = QColor(40, 40, 60, 160)
            snap_fg    = QColor(110, 110, 140, 200)

        painter.fillRect(snap_x, snap_y, snap_w, snap_h, snap_bg)
        painter.setPen(QPen(snap_fg, 1))
        painter.drawText(snap_x + 7, snap_y + metrics.ascent() + 3, snap_label)

        self._snap_badge_rect = (snap_x, snap_y, snap_w, snap_h)

        # EDIT TERRAIN badge (immediately right of TERRAIN SNAP)
        edit_terrain_label = "EDIT TERRAIN"
        et_w = metrics.horizontalAdvance(edit_terrain_label) + 14
        et_h = badge_h
        et_x = snap_x + snap_w + 6
        et_y = snap_y

        if self.terrain_edit_mode:
            et_bg = QColor(160, 40, 160, 220)
            et_fg = QColor(255, 160, 255)
        else:
            et_bg = QColor(40, 40, 60, 160)
            et_fg = QColor(110, 110, 140, 200)

        painter.fillRect(et_x, et_y, et_w, et_h, et_bg)
        painter.setPen(QPen(et_fg, 1))
        painter.drawText(et_x + 7, et_y + metrics.ascent() + 3, edit_terrain_label)

        self._terrain_edit_badge_rect = (et_x, et_y, et_w, et_h)

        # PAINT TEXTURE badge (immediately right of EDIT TERRAIN)
        paint_texture_label = "PAINT TEXTURE (experimental)"
        pt_w = metrics.horizontalAdvance(paint_texture_label) + 14
        pt_h = badge_h
        pt_x = et_x + et_w + 6
        pt_y = et_y
        if self.terrain_paint_mode:
            pt_bg = QColor(20, 80, 180, 220)
            pt_fg = QColor(120, 190, 255)
        else:
            pt_bg = QColor(40, 40, 60, 160)
            pt_fg = QColor(110, 110, 140, 200)
        painter.fillRect(pt_x, pt_y, pt_w, pt_h, pt_bg)
        painter.setPen(QPen(pt_fg, 1))
        painter.drawText(pt_x + 7, pt_y + metrics.ascent() + 3, paint_texture_label)
        self._terrain_paint_badge_rect = (pt_x, pt_y, pt_w, pt_h)

        # Warning badge — shown when terrain edit is on but no heightmap is loaded
        if self.terrain_edit_mode and not self._has_terrain_heightmap():
            painter.setFont(QFont("Arial", 9, QFont.Weight.Bold))
            warn_m = painter.fontMetrics()
            warn_text = "⚠ Load terrain in panel to edit"
            warn_w = warn_m.horizontalAdvance(warn_text) + 14
            warn_h = badge_h
            warn_x = badge_x
            warn_y = badge_y - badge_h - 5
            painter.fillRect(warn_x, warn_y, warn_w, warn_h, QColor(160, 80, 0, 210))
            painter.setPen(QPen(QColor(255, 220, 100), 1))
            painter.drawText(warn_x + 7, warn_y + warn_m.ascent() + 3, warn_text)

        # Camera info (top-left)
        painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        metrics = painter.fontMetrics()
        cam = self.camera_3d
        info_text = f"Cam: ({cam.position[0]:.0f}, {cam.position[1]:.0f}, {cam.position[2]:.0f})"
        painter.drawText(margin, margin + metrics.ascent(), info_text)

        # Controls hint (just above badge)
        painter.setFont(QFont("Arial", 8))
        painter.setPen(QPen(QColor(160, 160, 160, 180), 1))
        controls_text = "WASD+QE: Move | T: 2D/3D | F1: Profiler | F2/F3: GPU-driven | F4: Day/Night | F5: flip green | F6: flip normal | F7: Shadows | F8: Occlusion | F9: Detail cull"
        painter.drawText(margin, self.height() - margin - metrics.height() - badge_h - 4, controls_text)

    def _draw_2d_mode_indicator(self, painter):
        """Draw a small View/Edit mode badge in the bottom-left corner of the 2D canvas."""
        edit_mode = getattr(self.input_handler, 'edit_mode_2d', False)

        mode_label = "EDIT MODE" if edit_mode else "VIEW MODE"
        hint_label = "Space: switch mode"

        if edit_mode:
            badge_color  = QColor(180, 100, 0, 200)   # amber — editing enabled
            text_color   = QColor(255, 220, 120)
        else:
            badge_color  = QColor(30, 100, 30, 200)   # green — view / safe
            text_color   = QColor(140, 220, 140)

        painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        metrics = painter.fontMetrics()
        margin  = 8

        # Mode badge (bottom-left)
        badge_w = metrics.horizontalAdvance(mode_label) + 14
        badge_h = metrics.height() + 6
        badge_x = margin
        badge_y = self.height() - margin - badge_h

        painter.fillRect(badge_x, badge_y, badge_w, badge_h, badge_color)
        painter.setPen(QPen(text_color, 1))
        painter.drawText(badge_x + 7, badge_y + metrics.ascent() + 3, mode_label)

        # Hint line just above the badge
        painter.setFont(QFont("Arial", 8))
        painter.setPen(QPen(QColor(160, 160, 160, 180), 1))
        painter.drawText(badge_x, badge_y - 3, hint_label)

    def _get_map_filtered_entities(self):
        """Return the entity list filtered to the current map, with caching.

        Also pre-builds and caches the NumPy position array used by the 3D
        frustum culler (_positions_3d, _valid_entities_3d) so that array is
        never rebuilt more than once per level load.
        """
        map_name = getattr(self.current_map, 'name', None) if self.current_map else None
        _mc_len = len(self.model_loader.models_cache) if getattr(self, 'model_loader', None) else 0
        cache_key = (id(self.entities), map_name, _mc_len)
        if getattr(self, '_map_filter_cache_key', None) == cache_key:
            return self._map_filter_cache
        # Rebuild filtered list
        if not getattr(self, 'unified_mode', False) and map_name is not None:
            filtered = [e for e in self.entities if getattr(e, 'map_name', None) == map_name]
        else:
            filtered = self.entities
        self._map_filter_cache_key = cache_key
        self._map_filter_cache = filtered

        # Pre-build the position array for 3D frustum culling
        valid = [e for e in filtered if hasattr(e, 'x') and hasattr(e, 'y') and hasattr(e, 'z')]
        if valid:
            self._valid_entities_3d = valid
            self._positions_3d = np.array([[e.x, e.z, -e.y] for e in valid], dtype=np.float32)
        else:
            self._valid_entities_3d = []
            self._positions_3d = None
        # Version counter for everything keyed to these arrays (GDR row tables in
        # model_loader). Bumps on every rebuild — level load, model-count change,
        # invalidate_position_cache after entity moves.
        self._pos_arrays_version = getattr(self, '_pos_arrays_version', 0) + 1

        # Pre-build bounding-sphere radii and geometric-center Y offsets for frustum culling.
        # Entity origins sit at the model foot/base; using the bounding-box centre as the sphere
        # centre is more accurate and prevents close-range culling of entities whose origin has
        # drifted below the camera frustum while the visible top half is still on screen.
        if hasattr(self, 'model_loader') and self.model_loader is not None:
            _rs  = self.model_loader._entity_rs_cache
            _mc  = self.model_loader.models_cache
            _rad = []
            _yoff = []  # GL-Y offset from entity origin to bounding-box centre
            for _e in valid:
                _r   = 0.0
                _off = 0.0
                _mf  = getattr(_e, 'model_file', None)
                if _mf:
                    _m = _mc.get(_mf)
                    if _m and _m.bounds_min is not None and _m.bounds_max is not None:
                        _cached = _rs.get(id(_e))
                        _scale  = _cached[3] if _cached else 1.0
                        bmn, bmx = _m.bounds_min, _m.bounds_max
                        # Radius = distance from the model ORIGIN to the farthest AABB
                        # corner. The mesh rotates about its origin, so this is
                        # rotation-invariant, and a sphere AT the entity origin with
                        # this radius always contains the mesh — even when the mesh is
                        # modelled far from its origin (e.g. a background whose origin
                        # is map-centre but geometry is ~1000 m away). That offset was
                        # why such objects popped when their ORIGIN left the frustum
                        # while the mesh itself was still on screen.
                        _cx = max(abs(bmn[0]), abs(bmx[0]))
                        _cy = max(abs(bmn[1]), abs(bmx[1]))
                        _cz = max(abs(bmn[2]), abs(bmx[2]))
                        _r  = _scale * float(np.sqrt(_cx * _cx + _cy * _cy + _cz * _cz))
                        _off = 0.0   # centred at origin; the radius covers the full extent
                    else:
                        _r   = 4.0   # model not yet loaded — conservative sphere until bounds known
                        _off = 0.0
                _rad.append(_r)
                _yoff.append(_off)
            self._radii_3d = np.array(_rad,  dtype=np.float32)
            _yoff_arr = np.array(_yoff, dtype=np.float32)
        else:
            self._radii_3d = np.zeros(len(valid), dtype=np.float32)
            _yoff_arr = np.zeros(len(valid), dtype=np.float32)

        # Build centred position array: origin + (0, centre_Y_offset, 0)
        if self._positions_3d is not None and len(_yoff_arr) == len(self._positions_3d):
            _pos_c = self._positions_3d.copy()
            _pos_c[:, 1] += _yoff_arr
            self._positions_centered_3d = _pos_c
        else:
            self._positions_centered_3d = self._positions_3d

        # "Never cull" = non-worldsector entities WITHOUT a model — i.e. cheap
        # markers (spawn points, managers, triggers) drawn as small cubes/icons
        # that should always be visible and cost ~nothing. MODEL-bearing entities
        # are EXCLUDED so background props (e.g. the 110 omni "bkg_faketree"
        # models) get frustum-culled like everything else instead of rendering
        # off-screen every frame. Forcing all non-worldsector entities on was
        # rendering ~10x the on-screen count (709 drawn vs ~65-318 in frustum).
        self._never_cull_entities_3d = [
            e for e in valid
            if getattr(e, 'source_file', '') != 'worldsectors'
            and not (getattr(e, 'model_file', None) or getattr(e, 'kit_model_files', None))
        ]

        # Pre-build position array for 2D viewport culling (mirrors 3D approach)
        valid_2d = [e for e in filtered if hasattr(e, 'x') and hasattr(e, 'y')]
        if valid_2d:
            self._valid_entities_2d = valid_2d
            self._positions_2d = np.array([[e.x, e.y] for e in valid_2d], dtype=np.float32)
        else:
            self._valid_entities_2d = []
            self._positions_2d = None

        return filtered

    def _rebuild_interior_aabb_cache(self):
        """Build numpy arrays for vectorised interior-anchor detection.
        Expensive — only called when entity list changes or invalidate_position_cache fires.
        """
        valid = getattr(self, '_valid_entities_3d', [])
        entities_out = []
        positions    = []   # GL-space (x, z, -y)
        R_inv_list   = []   # (3,3) each — R.T
        scales       = []
        bmin_list    = []
        bmax_list    = []
        w_min_list   = []
        w_max_list   = []

        rs_cache = self.model_loader._entity_rs_cache
        for entity in valid:
            model_file = getattr(entity, 'model_file', None)
            if not model_file:
                continue
            model = self.model_loader.models_cache.get(model_file)
            if model is None or model.bounds_min is None or model.bounds_max is None:
                continue

            # Reuse model_loader's rotation/scale cache — populated by prepare_batches
            cached = rs_cache.get(id(entity))
            if cached:
                rx, ry, rz, scale = cached
            else:
                rx = ry = rz = 0.0
                scale = 1.0

            pos = np.array([float(entity.x), float(entity.z), float(-entity.y)], dtype=np.float64)
            R = (_make_rot_x(-90.0) @
                 _make_rot_z(-rz) @
                 _make_rot_x(rx) @
                 _make_rot_y(ry))
            bmin = np.array(model.bounds_min, dtype=np.float64)
            bmax = np.array(model.bounds_max, dtype=np.float64)

            cx = np.array([bmin[0], bmax[0]])
            cy = np.array([bmin[1], bmax[1]])
            cz = np.array([bmin[2], bmax[2]])
            corners = np.array([[x, y, z] for x in cx for y in cy for z in cz], dtype=np.float64)
            wc = (corners * scale) @ R.T + pos

            entities_out.append(entity)
            positions.append(pos)
            R_inv_list.append(R.T)
            scales.append(scale)
            bmin_list.append(bmin)
            bmax_list.append(bmax)
            w_min_list.append(wc.min(axis=0))
            w_max_list.append(wc.max(axis=0))

        n = len(entities_out)
        self._ic_entities = entities_out
        if n:
            self._ic_positions = np.array(positions,  dtype=np.float64)   # (N,3)
            self._ic_R_inv     = np.array(R_inv_list, dtype=np.float64)   # (N,3,3)
            self._ic_scales    = np.array(scales,     dtype=np.float64)   # (N,)
            self._ic_bmin      = np.array(bmin_list,  dtype=np.float64)   # (N,3)
            self._ic_bmax      = np.array(bmax_list,  dtype=np.float64)   # (N,3)
            self._ic_w_min     = np.array(w_min_list, dtype=np.float64)   # (N,3)
            self._ic_w_max     = np.array(w_max_list, dtype=np.float64)   # (N,3)
        else:
            self._ic_positions = None

        self._interior_aabb_cache_key = id(getattr(self, 'entities', None))

    def _get_interior_exempt_entities(self):
        """Return model entities that bypass frustum culling because the camera
        is inside their AABB, plus all model entities overlapping that anchor.

        Per-frame cost: two fully-vectorised numpy operations — no Python loops
        over entity count.
        """
        if not hasattr(self, 'model_loader') or self.model_loader is None:
            return []
        if not hasattr(self, 'camera_3d'):
            return []

        # Interior AABB is only meaningful for Avatar-scale levels (buildings you walk into).
        # For dense open-world scenes (FC2, 50K+ entities) the rebuild cost is prohibitive
        # and interior exemption adds no real value.
        if len(getattr(self, '_valid_entities_3d', [])) > 20000:
            return []

        current_key = id(getattr(self, 'entities', None))
        if getattr(self, '_interior_aabb_cache_key', None) != current_key:
            self._rebuild_interior_aabb_cache()

        if not self._ic_entities or self._ic_positions is None:
            return []

        cam_pos = np.asarray(self.camera_3d.position, dtype=np.float64)  # (3,)

        # Pass 1 — vectorised: transform camera into every model's local space, check inside AABB
        diff      = cam_pos - self._ic_positions                             # (N,3)
        local_cam = np.einsum('nij,nj->ni', self._ic_R_inv, diff) / self._ic_scales[:, None]  # (N,3)
        inside    = (np.all(local_cam >= self._ic_bmin, axis=1) &
                     np.all(local_cam <= self._ic_bmax, axis=1))             # (N,) bool

        anchor_idx = np.where(inside)[0]
        if len(anchor_idx) == 0:
            return []

        # Exempt ONLY the anchors (entities whose AABB the camera is literally
        # inside) — NOT every entity overlapping them. The old "overlap expansion"
        # (pass 2) exploded in dense scenes: one large background prop the camera
        # sits inside overlaps ~the whole level, so it pulled hundreds of
        # off-screen objects back in and defeated frustum culling (709 drawn vs
        # ~65-318 in frustum). Anchors are also already kept by the frustum's
        # inside-sphere bypass (the bounding sphere circumscribes the AABB), so
        # this is belt-and-suspenders, not a behaviour change for "don't cull the
        # thing I'm standing in".
        return [self._ic_entities[i] for i in anchor_idx]

    def _get_visible_entities(self):
        """Return entities visible this frame.

        3-D mode uses fully-vectorised NumPy frustum culling so the hot path
        never touches a Python-level loop over individual entities.  The result
        list is already sorted front-to-back by squared distance, so
        _render_entities_3d does NOT need to re-sort it.
        """
        if not hasattr(self, 'entities') or not self.entities:
            self._visible_idx_3d = None
            return []
        if not self.show_entities:
            self._visible_idx_3d = None
            return []

        # Index array (into _valid_entities_3d) of this frame's frustum survivors.
        # Consumed by model_loader.prepare_gpu_frame (array-native GDR pipeline).
        # Reset here so early-return paths never leave a stale index array behind.
        self._visible_idx_3d = None

        entities_to_check = self._get_map_filtered_entities()

        # =========================
        # 3D MODE - VECTORISED FRUSTUM CULL
        # =========================
        if self.mode == MODE_3D:
            # Adaptive FAR: tighten for dense scenes so prepare_batches stays fast.
            # Target: at most ~3000 entities surviving the frustum.
            _n = len(getattr(self, '_valid_entities_3d', None) or ())
            if _n > 50000:
                FAR = 800.0    # FC2 full world (longer reach; occlusion keeps GPU in check)
            elif _n > 15000:
                FAR = 1300.0   # FC2 per-cell
            else:
                FAR = 2500.0   # Avatar / small levels — see much further
            NEAR = 0.1
            VFOV_DEG = 50.0
            # Wider padding keeps objects that are only just off-screen (and large
            # ones near the camera) from popping out at the frame edges.
            FRUSTUM_PADDING = 1.8

            aspect = self.width() / self.height() if self.height() > 0 else 1.0
            half_tan = np.tan(np.radians(VFOV_DEG) * 0.5) * FRUSTUM_PADDING

            cam_pos     = self.camera_3d.position   # (3,)
            cam_forward = self.camera_3d.forward     # (3,)
            cam_up      = self.camera_3d.up          # (3,)
            cam_right   = self.camera_3d.right       # (3,)

            # Use the pre-built centred position array (entity origin + bounding-box centre offset).
            # Centred positions give a much more accurate frustum test for entities whose origin
            # is at their base — the camera can be above them without falsely culling their tops.
            valid     = getattr(self, '_valid_entities_3d', None)
            positions = getattr(self, '_positions_centered_3d', None)
            if positions is None:
                positions = getattr(self, '_positions_3d', None)
            if not valid or positions is None:
                return []

            # Vectors from camera to each entity centre  (N, 3)
            to_pts = positions - cam_pos  # broadcasting

            # --- Pass 1: squared-distance pre-reject (no sqrt) ---
            dist_sq = np.einsum('ij,ij->i', to_pts, to_pts)  # (N,)
            in_range = dist_sq <= (FAR * FAR)

            # --- Pass 2: depth pre-reject (generous near margin so sphere-expanded test below can rescue
            #     large entities whose origin has slipped just behind the camera plane) ---
            depth = to_pts @ cam_forward  # (N,)  dot with forward
            # Generous behind-camera margin so large objects the camera is right on
            # top of (origin just behind the eye plane) aren't culled prematurely.
            in_depth = (depth >= -120.0) & (depth <= FAR)

            # Combined early mask before the angular tests
            mask = in_range & in_depth
            if not np.any(mask):
                return []

            # Work only on surviving candidates from here on
            idx       = np.where(mask)[0]
            tp_masked = to_pts[idx]            # (M, 3)
            d_masked  = depth[idx]             # (M,)

            # Bounding-sphere radii for surviving candidates (pre-built at load time)
            radii_all = getattr(self, '_radii_3d', None)
            if radii_all is not None and len(radii_all) == len(valid):
                radii_masked = radii_all[idx]  # (M,)
            else:
                radii_masked = np.zeros(len(idx), dtype=np.float32)

            # --- Pass 2.5: sphere-expanded near/far depth test ---
            # An entity passes if ANY part of its sphere is between NEAR and FAR.
            # This prevents large entities from being culled the instant their origin
            # crosses the near plane as the camera walks toward them.
            near_far_ok = (d_masked + radii_masked >= NEAR) & (d_masked - radii_masked <= FAR)

            # --- Inside-sphere bypass ---
            # If the camera is inside the entity's bounding sphere the entity is
            # definitely visible — skip the angular tests entirely for those.
            inside_sphere = dist_sq[idx] <= (radii_masked * radii_masked)

            # --- Pass 3: vertical frustum (sphere-expanded) ---
            # Clamp depth to a small positive floor so v_half never collapses toward
            # zero/negative for close objects (their origin may be below eye level,
            # making the angular tolerance a near-zero needle that falsely culls them).
            d_safe = np.maximum(d_masked, 0.5)
            v_half = d_safe * half_tan               # half-height at each depth
            proj_y = tp_masked @ cam_up                # (M,)
            vert_ok = np.abs(proj_y) <= v_half + radii_masked

            # --- Pass 4: horizontal frustum (sphere-expanded) ---
            h_half = v_half * aspect
            proj_x = tp_masked @ cam_right             # (M,)
            horiz_ok = np.abs(proj_x) <= h_half + radii_masked

            frustum_mask = inside_sphere | (near_far_ok & vert_ok & horiz_ok)
            final_idx = idx[frustum_mask]              # indices into `valid`

            if len(final_idx) == 0:
                return []

            # Sort surviving entities by squared distance (front-to-back)
            # _render_entities_3d must NOT re-sort – the list arrives pre-sorted.
            sorted_order = np.argsort(dist_sq[final_idx])
            ordered_idx  = final_idx[sorted_order]

            # Stash for the array-native GDR pipeline. Interior-exempt anchors are
            # already included (camera inside the AABB ⇒ inside the bounding
            # sphere ⇒ the inside_sphere bypass kept them); never-cull markers
            # have no models, so neither extra needs to be added here.
            self._visible_idx_3d = ordered_idx

            visible_entities = [valid[i] for i in ordered_idx]

            n_frustum = len(visible_entities)

            # Interior exemption: keep entities the camera is literally inside
            # (anchors only — see _get_interior_exempt_entities).
            n_interior = 0
            interior_exempt = self._get_interior_exempt_entities()
            if interior_exempt:
                visible_set = set(id(e) for e in visible_entities)
                interior_extra = [e for e in interior_exempt if id(e) not in visible_set]
                if interior_extra:
                    visible_entities = visible_entities + interior_extra
                    n_interior = len(interior_extra)

            # Always include cheap non-model markers (spawn points, managers, …).
            # Model-bearing entities are NOT here — they're frustum-culled.
            n_markers = 0
            never_cull = getattr(self, '_never_cull_entities_3d', [])
            if never_cull:
                visible_set = set(id(e) for e in visible_entities)
                extra = [e for e in never_cull if id(e) not in visible_set]
                if extra:
                    visible_entities = visible_entities + extra
                    n_markers = len(extra)

            self._cull_last_drawn = len(visible_entities)   # for the frame-time print

            # --- Periodic logging (frame counter, no time.time() per frame) ---
            self._cull_log_frame = getattr(self, '_cull_log_frame', 0) + 1
            if self._cull_log_frame >= 300:  # every ~5s at 60fps
                self._cull_log_frame = 0
                n_total = len(entities_to_check)
                print(
                    f"⚡ CULL: {len(visible_entities)} drawn = "
                    f"{n_frustum} frustum + {n_interior} interior + {n_markers} markers "
                    f"| {n_total} total ({n_total - len(visible_entities)} culled)"
                )

            return visible_entities

        # =========================
        # 2D MODE CULLING - VECTORISED (mirrors 3D frustum cull)
        # =========================
        # Budget sized above the maximum entity count of any Avatar/FC2 level so
        # the cap only triggers at extreme zoom-out (whole map visible at once).
        # When it does trigger, entities are subsampled uniformly instead of by
        # distance-to-centre — that avoids the circular render-zone boundary.
        MAX_2D_BUDGET = 15000
        margin_pixels = 50

        try:
            world_left, world_bottom = self.screen_to_world(
                -margin_pixels,
                self.height() + margin_pixels
            )
            world_right, world_top = self.screen_to_world(
                self.width() + margin_pixels,
                -margin_pixels
            )

            valid_2d = getattr(self, '_valid_entities_2d', None)
            pos_2d   = getattr(self, '_positions_2d', None)

            if valid_2d is not None and pos_2d is not None:
                # Vectorised AABB — no Python for-loop over individual entities
                xs = pos_2d[:, 0]
                ys = pos_2d[:, 1]
                mask = ((xs >= world_left) & (xs <= world_right) &
                        (ys >= world_bottom) & (ys <= world_top))
                indices = np.where(mask)[0]

                if len(indices) == 0:
                    return []

                # Budget cap: uniform stride subsample to preserve map-wide coverage.
                # A circular closest-to-centre sort would create a visible circle
                # boundary at the edge of the render zone — avoid that.
                if len(indices) > MAX_2D_BUDGET:
                    stride = len(indices) // MAX_2D_BUDGET + 1
                    indices = indices[::stride]

                return [valid_2d[i] for i in indices]

            else:
                # Fallback: Python loop (slow path, only before first level load)
                visible_entities = []
                for entity in entities_to_check:
                    if hasattr(entity, 'x') and hasattr(entity, 'y'):
                        if (world_left <= entity.x <= world_right and
                                world_bottom <= entity.y <= world_top):
                            visible_entities.append(entity)
                return visible_entities

        except Exception as e:
            print(f"Error in 2D spatial culling: {e}")
            return entities_to_check
    
    def keyPressEvent(self, event):
        """Handle key press - mode aware with smooth 3D camera"""
        k = event.key()

        # Undo / Redo
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if ctrl and k == Qt.Key.Key_Z:
            if self.terrain_edit_mode and getattr(self, '_terrain_data', None) is not None:
                if shift:
                    self._terrain_redo()
                else:
                    self._terrain_undo()
            elif hasattr(self, 'undo_redo'):
                if shift:
                    self.undo_redo.redo(self)
                else:
                    self.undo_redo.undo(self)
            return
        if ctrl and k == Qt.Key.Key_Y:
            if self.terrain_edit_mode and getattr(self, '_terrain_data', None) is not None:
                self._terrain_redo()
            elif hasattr(self, 'undo_redo'):
                self.undo_redo.redo(self)
            return

        # F1 — cycle the render debug profiler (Off → Profile → per-feature A/B)
        if k == Qt.Key.Key_F1:
            self._cycle_debug_mode()
            return
        # F2 / F3 — force the GPU-driven render tier (NVIDIA/bindless, AMD/texarray)
        if k == Qt.Key.Key_F2:
            self._set_render_tier('bindless')
            return
        if k == Qt.Key.Key_F3:
            self._set_render_tier('texarray')
            return
        # F4 — day/night cycle (off → playing → paused → off)
        if k == Qt.Key.Key_F4:
            self._toggle_day_night()
            return
        # F5 / F6 — normal-map debug: flip green (Y) channel / flip base normal
        if k == Qt.Key.Key_F5:
            self._toggle_flip_green()
            return
        if k == Qt.Key.Key_F6:
            self._toggle_flip_normal()
            return
        # F7 — sun shadow mapping (only visible with day/night on + sun up)
        if k == Qt.Key.Key_F7:
            self._toggle_shadows()
            return
        # F8 — depth prepass (early-Z occlusion) on the GPU-driven path
        if k == Qt.Key.Key_F8:
            self._toggle_depth_prepass()
            return
        # F9 — contribution cull threshold (GPU-driven path): skip model
        # instances smaller than N px on screen. The vertex-load lever for
        # integrated/weak GPUs. Cycles OFF → 3 → 6 → 10 px.
        if k == Qt.Key.Key_F9:
            ml = getattr(self, 'model_loader', None)
            if ml is not None:
                steps = [0.0, 3.0, 6.0, 10.0]
                cur = float(getattr(ml, 'gdr_min_pixel_size', 4.0))
                nxt = steps[(steps.index(cur) + 1) % len(steps)] if cur in steps else 0.0
                ml.gdr_min_pixel_size = nxt
                label = 'OFF (draw everything)' if nxt == 0 else f'{nxt:.0f}px minimum on-screen size'
                print(f"🔬 [F9] contribution cull: {label}")
                self.update()
            return

        # Toggle 2D/3D view mode
        if k == Qt.Key.Key_T:
            self.toggle_view_mode()
            return

        # Space — toggle View/Edit mode (2D or 3D)
        if k == Qt.Key.Key_Space:
            if self.mode == MODE_3D:
                self.input_handler.toggle_edit_mode_3d()
            else:
                self.input_handler.toggle_edit_mode_2d()
            return

        # Update SHIFT modifier state for both 2D and 3D
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if self.mode == MODE_3D:
                self.camera_3d.set_shift_modifier(True)
            else:
                self.camera_controller.set_shift_modifier(True)

        # ========== 3D VIEW TOGGLES (only work in 3D mode) ==========
        if self.mode == MODE_3D:
            # H - Toggle 3D HUD
            if k == Qt.Key.Key_H:
                self.toggle_3d_hud()
                return
            
            # G - Toggle 3D Grid
            if k == Qt.Key.Key_G:
                self.toggle_3d_grid()
                return
            
            # B - Toggle 3D Cubes
            if k == Qt.Key.Key_B:
                self.toggle_3d_cubes()
                return

        # Rotation controls for selected entity/entities (K = rotate left, L = rotate right)
        if k in (Qt.Key.Key_K, Qt.Key.Key_L) and self.selected_entity is not None:
            # Calculate rotation amount
            rotation_delta = -1.0 if k == Qt.Key.Key_K else 1.0  # K rotates left (CCW), L rotates right (CW)

            # Fine control with SHIFT (0.1 degree increments)
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                rotation_delta = rotation_delta * 0.1  # 0.1 degree for fine control

            # Get all selected entities (supports group selection and Structure children)
            entities_to_rotate = self.selected if hasattr(self, 'selected') and self.selected else [self.selected_entity]

            # --- Undo snapshot (before) ---
            before_state = UndoRedoManager.snapshot_rotations(entities_to_rotate, self)

            if len(entities_to_rotate) > 1:
                # GROUP ROTATION: Rotate around common center
                center = self.calculate_group_center(entities_to_rotate)
                self.rotate_group_around_center(entities_to_rotate, rotation_delta, center)

                print(f"🔄 Group rotated {rotation_delta:+.1f}° ({len(entities_to_rotate)} entities)")
            else:
                # SINGLE ENTITY ROTATION
                entity = entities_to_rotate[0]

                # Get current rotation
                if hasattr(self, 'gizmo_renderer') and self.gizmo_renderer.rotation_gizmo:
                    current_rotation = self.gizmo_renderer.rotation_gizmo.extract_entity_rotation(entity)
                else:
                    current_rotation = 0.0

                # Calculate new rotation
                new_rotation = (current_rotation + rotation_delta) % 360

                # Update entity rotation
                if hasattr(self, 'gizmo_renderer') and self.gizmo_renderer.rotation_gizmo:
                    success = self.gizmo_renderer.rotation_gizmo.update_entity_rotation(entity, new_rotation)
                    if success:
                        # Update gizmo display
                        self.gizmo_renderer.rotation_gizmo.current_rotation = new_rotation

                        # Mark as modified and auto-save
                        self.mark_entity_modified(entity)
                        self._auto_save_entity_changes(entity)

                        # Live-update the angles label in the stats panel
                        if hasattr(self, 'gizmo_3d'):
                            ax, ay, az = self.gizmo_3d._read_angles(entity)
                            self.angle_update.emit(entity, (ax, ay, az))

                        print(f"🔄 {entity.name} rotated: {current_rotation:.1f}° -> {new_rotation:.1f}° (Δ{rotation_delta:+.1f}°)")
                    else:
                        print(f"Failed to update rotation for {entity.name}")
                else:
                    print(f"Gizmo renderer not available for rotation")

            # --- Undo snapshot (after) and push ---
            if hasattr(self, 'undo_redo'):
                after_state = UndoRedoManager.snapshot_rotations(entities_to_rotate, self)
                self.undo_redo.push(RotateCommand(before_state, after_state))

            # Update display
            self.update()
            return

        # In 2D View mode, arrow keys and comma/period are blocked (no entity movement)
        _edit_mode_2d = getattr(self.input_handler, 'edit_mode_2d', True)
        _movement_blocked = (not _edit_mode_2d) and (self.mode != MODE_3D)

        if k in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right) and self.selected_entity is not None:
            if _movement_blocked:
                return
            # Calculate movement delta
            move_amount = 1.0
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                move_amount = 0.01  # Fine control

            # Determine direction
            delta_x = 0.0
            delta_y = 0.0
            delta_z = 0.0

            if k == Qt.Key.Key_Up:
                delta_z = move_amount  # Height up
            elif k == Qt.Key.Key_Down:
                delta_z = -move_amount  # Height down
            elif k == Qt.Key.Key_Left:
                delta_x = -move_amount  # Move left
            elif k == Qt.Key.Key_Right:
                delta_x = move_amount  # Move right

            # Get all selected entities (supports group selection)
            entities_to_move = self.selected if hasattr(self, 'selected') and self.selected else [self.selected_entity]

            # --- Undo snapshot (before) ---
            before_state = UndoRedoManager.snapshot_positions(entities_to_move)

            # Move all selected entities
            for entity in entities_to_move:
                old_x, old_y, old_z = entity.x, entity.y, entity.z

                entity.x += delta_x
                entity.y += delta_y
                entity.z += delta_z

                # Update XML and mark as modified
                self.update_entity_xml(entity)
                self.mark_entity_modified(entity)

                # Auto-save changes
                if hasattr(self, '_auto_save_entity_changes'):
                    self._auto_save_entity_changes(entity)

                # Log the change
                if delta_x != 0:
                    print(f"Moved {getattr(entity, 'name', 'entity')} X: {old_x:.1f} -> {entity.x:.1f} (Δ{delta_x:+.1f})")
                elif delta_y != 0:
                    print(f"Moved {getattr(entity, 'name', 'entity')} Y: {old_y:.1f} -> {entity.y:.1f} (Δ{delta_y:+.1f})")
                elif delta_z != 0:
                    print(f"Height adjusted: {getattr(entity, 'name', 'entity')} Z: {old_z:.1f} -> {entity.z:.1f} (Δ{delta_z:+.1f})")

            # --- Undo snapshot (after) and push ---
            if hasattr(self, 'undo_redo'):
                after_state = UndoRedoManager.snapshot_positions(entities_to_move)
                self.undo_redo.push(MoveCommand(before_state, after_state))

            # Invalidate position cache so frustum culler uses updated coordinates
            self.invalidate_position_cache()

            # Update gizmo for the primary selected entity
            if hasattr(self, 'gizmo_renderer'):
                self.gizmo_renderer.update_gizmo_for_entity(self.selected_entity)
            if hasattr(self, 'gizmo_3d'):
                self.gizmo_3d.sync_position()

            # Emit signals for primary entity
            if delta_z != 0 and hasattr(self, 'height_update'):
                self.height_update.emit(self.selected_entity.z)

            # Notify Statistics panel and entity browser of the new position
            self.position_update.emit(
                self.selected_entity,
                (self.selected_entity.x, self.selected_entity.y, self.selected_entity.z)
            )

            self.update()
            return

        # Comma and Period keys for forward/backward movement (Y-axis)
        if k in (Qt.Key.Key_Comma, Qt.Key.Key_Period, Qt.Key.Key_Less, Qt.Key.Key_Greater) and self.selected_entity is not None:
            if _movement_blocked:
                return
            # Calculate movement delta
            move_amount = 1.0
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                move_amount = 0.01  # Fine control

            # Determine direction (Y-axis in game coordinates)
            # Handle both , and < (shift+comma), . and > (shift+period)
            delta_y = -move_amount if k in (Qt.Key.Key_Comma, Qt.Key.Key_Less) else move_amount

            # Get all selected entities (supports group selection)
            entities_to_move = self.selected if hasattr(self, 'selected') and self.selected else [self.selected_entity]

            # --- Undo snapshot (before) ---
            before_state = UndoRedoManager.snapshot_positions(entities_to_move)

            # Move all selected entities
            for entity in entities_to_move:
                old_y = entity.y
                entity.y += delta_y

                # Update XML and mark as modified
                self.update_entity_xml(entity)
                self.mark_entity_modified(entity)

                # Auto-save changes
                if hasattr(self, '_auto_save_entity_changes'):
                    self._auto_save_entity_changes(entity)

                print(f"Moved {getattr(entity, 'name', 'entity')} Y: {old_y:.1f} -> {entity.y:.1f} (Δ{delta_y:+.1f})")

            # --- Undo snapshot (after) and push ---
            if hasattr(self, 'undo_redo'):
                after_state = UndoRedoManager.snapshot_positions(entities_to_move)
                self.undo_redo.push(MoveCommand(before_state, after_state))

            # Invalidate position cache so frustum culler uses updated coordinates
            self.invalidate_position_cache()

            # Update gizmo for the primary selected entity
            if hasattr(self, 'gizmo_renderer'):
                self.gizmo_renderer.update_gizmo_for_entity(self.selected_entity)
            if hasattr(self, 'gizmo_3d'):
                self.gizmo_3d.sync_position()

            # Notify Statistics panel and entity browser of the new position
            self.position_update.emit(
                self.selected_entity,
                (self.selected_entity.x, self.selected_entity.y, self.selected_entity.z)
            )

            self.update()
            return

        # 3D camera controls with FLAG-BASED system (like 2D)
        if self.mode == MODE_3D:
            from canvas.opengl_utils import movement_action
            action = movement_action(event)
            if action:
                self.camera_3d.set_movement_flag(action, True)
        else:
            # 2D controls - WASD pans the camera regardless of selection state.
            # Arrow keys already return early above, so there is no conflict.
            self.input_handler.handle_key_press(event)

    def keyReleaseEvent(self, event):
        """Handle key release - mode aware"""
        k = event.key()
        
        # Update SHIFT modifier state for both 2D and 3D
        if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            if self.mode == MODE_3D:
                self.camera_3d.set_shift_modifier(False)
            else:
                self.camera_controller.set_shift_modifier(False)
        
        if self.mode == MODE_3D:
            from canvas.opengl_utils import movement_action
            action = movement_action(event)
            if action:
                self.camera_3d.set_movement_flag(action, False)
        else:
            self.input_handler.handle_key_release(event)

    def toggle_3d_hud(self):
        """Toggle 3D HUD overlay (camera info, mode indicator, controls)"""
        self.show_3d_hud = not self.show_3d_hud
        status = "ON" if self.show_3d_hud else "OFF"
        print(f"3D HUD: {status}")
        self.update()

    def toggle_3d_grid(self):
        """Toggle 3D grid (independent from 2D grid toggle)"""
        self.show_3d_grid = not self.show_3d_grid
        status = "ON" if self.show_3d_grid else "OFF"
        print(f"3D Grid: {status}")
        self.update()

    def toggle_3d_cubes(self):
        """Toggle 3D fallback cubes (3D models always render regardless)"""
        self.show_3d_cubes = not self.show_3d_cubes
        status = "ON" if self.show_3d_cubes else "OFF"
        print(f"3D Cubes: {status} (3D models always render)")
        self.update()

    def update_movement(self):
        """Update camera movement for both 2D and 3D"""
        try:
            if self.mode == MODE_TOPDOWN:
                # 2D movement
                if not self.camera_controller.needs_update():
                    return
                
                self.camera_controller.update_movement(self)
                self.update()
            
            elif self.mode == MODE_3D:
                # 3D movement with smooth acceleration
                if not self.camera_3d.needs_update():
                    return
                
                moved = self.camera_3d.update_movement()
                if moved:
                    self.update()
        
        except Exception as e:
            print(f"Error in update_movement: {e}")

    def _auto_save_entity_changes(self, entity):
        """Auto-save entity changes"""
        if not entity:
            return False
        
        try:
            # Update XML first
            self.update_entity_xml(entity)
            
            # Then save the file
            source_file_path = getattr(entity, 'source_file_path', None)
            
            if source_file_path:
                # WorldSector file
                return self._auto_save_worldsector_file(source_file_path)
            else:
                # Main file
                return self._auto_save_main_file()
                
        except Exception as e:
            print(f"Error auto-saving entity {getattr(entity, 'name', 'unknown')}: {e}")
            return False

    def _auto_save_entity_changes(self, entity):
        """Auto-save entity changes"""
        if not entity:
            return False

        try:
            # Update XML first
            self.update_entity_xml(entity)

            # Then save the file
            source_file = getattr(entity, 'source_file', None)
            source_file_path = getattr(entity, 'source_file_path', None)

            if source_file in ('omnis', 'managers'):
                return self._auto_save_named_tree(entity)
            elif source_file_path:
                # WorldSector file
                return self._auto_save_worldsector_file(source_file_path)
            else:
                # Main file
                return self._auto_save_main_file()

        except Exception as e:
            print(f"Error auto-saving entity {getattr(entity, 'name', 'unknown')}: {e}")
            return False

    def _update_managers_vpos_for_entity(self, entity):
        """Update PawnInteractionInfo.vPos in managers.xml for a single entity (in memory).

        Uses self._managers_vpos_links populated at selection time.
        Call _flush_managers_xml() once after dragging ends to write to disk.
        """
        try:
            eid = str(getattr(entity, 'id', ''))
            vpos_fields = self._managers_vpos_links.get(eid)
            if not vpos_fields:
                return
            import struct
            x, y, z = entity.x, entity.y, entity.z
            binhex = struct.pack('<fff', x, y, z).hex().upper()
            vec_str = f"{x},{y},{z}"
            for vf in vpos_fields:
                vf.set('value-Vector3', vec_str)
                vf.text = binhex
            self._managers_vpos_dirty = True
        except Exception as e:
            print(f"Error updating managers vPos for {getattr(entity, 'name', '?')}: {e}")

    def _flush_managers_xml(self):
        """Write managers.xml to disk in a background thread if vPos changed.

        Called once on mouse release so large managers files don't block the UI.
        """
        if not getattr(self, '_managers_vpos_dirty', False):
            return
        self._managers_vpos_dirty = False
        try:
            main_window = self
            while main_window.parent():
                main_window = main_window.parent()
            managers_tree = getattr(main_window, 'managers_tree', None)
            if managers_tree is None:
                return
            mgr_path = main_window._find_tree_file_path('managers')
            if not mgr_path:
                return
            main_window.managers_tree_modified = True

            import threading
            writer = getattr(main_window, '_write_fcb_xml_tree', None)
            def _write():
                try:
                    if writer:
                        writer(managers_tree, mgr_path)
                    else:
                        managers_tree.write(mgr_path, encoding='utf-8', xml_declaration=True)
                    print(f"managers.xml saved")
                except Exception as ex:
                    print(f"Error writing managers.xml: {ex}")
            threading.Thread(target=_write, daemon=True).start()
        except Exception as e:
            print(f"Error flushing managers.xml: {e}")

    def _auto_save_worldsector_file(self, xml_file_path):
        """Auto-save WorldSector file"""
        try:
            import xml.etree.ElementTree as ET
            main_window = self
            while main_window.parent():
                main_window = main_window.parent()

            if (hasattr(main_window, 'worldsectors_trees') and
                xml_file_path in main_window.worldsectors_trees):
                tree = main_window.worldsectors_trees[xml_file_path]
                try:
                    ET.indent(tree, space="  ")
                except AttributeError:
                    pass  # Python < 3.9
                tree.write(xml_file_path, encoding='utf-8', xml_declaration=True)
                
                # Mark as modified
                if not hasattr(main_window, 'worldsectors_modified'):
                    main_window.worldsectors_modified = {}
                main_window.worldsectors_modified[xml_file_path] = True
                
                return True
            
            return False
            
        except Exception as e:
            print(f"Error auto-saving WorldSector file: {e}")
            return False

    def _update_entity_fcb_in_place(self, entity):
        """Update omnis/managers entity position directly in its xml_element (which is a live ref into the tree)."""
        xml_elem = getattr(entity, 'xml_element', None)
        if xml_elem is None:
            return False
        self._update_fcb_position_field(xml_elem, "hidPos", entity.x, entity.y, entity.z)
        self._update_fcb_position_field(xml_elem, "hidPos_precise", entity.x, entity.y, entity.z)
        return True

    def _auto_save_named_tree(self, entity):
        """Write omnis or managers tree to disk after an in-place position update."""
        try:
            import xml.etree.ElementTree as ET
            source_file = getattr(entity, 'source_file', None)
            file_path = getattr(entity, 'source_file_path', None)
            if not source_file or not file_path:
                return False
            main_window = self
            while main_window.parent():
                main_window = main_window.parent()
            tree = getattr(main_window, f'{source_file}_tree', None)
            if tree is None:
                return False
            try:
                ET.indent(tree, space="  ")
            except AttributeError:
                pass
            tree.write(file_path, encoding='utf-8', xml_declaration=True)
            setattr(main_window, f'{source_file}_tree_modified', True)
            return True
        except Exception as e:
            print(f"Error auto-saving {getattr(entity, 'source_file', '?')} tree: {e}")
            return False

    def _auto_save_main_file(self):
        """Auto-save main XML file"""
        try:
            main_window = self
            while main_window.parent():
                main_window = main_window.parent()
            
            if (hasattr(main_window, 'xml_tree') and 
                hasattr(main_window, 'xml_file_path')):
                main_window.xml_tree.write(main_window.xml_file_path, encoding='utf-8', xml_declaration=True)
                main_window.xml_tree_modified = True
                if hasattr(main_window, 'entities_modified'):
                    main_window.entities_modified = True
                return True
            
            return False
            
        except Exception as e:
            print(f"Error auto-saving main file: {e}")
            return False
    
    def mousePressEvent(self, event):
        """Handle mouse press - mode aware with Structure group selection"""
        if self.mode == MODE_3D:
            if event.button() == Qt.MouseButton.LeftButton:
                mouse_x = event.position().x()
                mouse_y = event.position().y()

                # Snap badge click
                if self._snap_badge_rect is not None:
                    sx, sy, sw, sh = self._snap_badge_rect
                    if sx <= mouse_x <= sx + sw and sy <= mouse_y <= sy + sh:
                        self.terrain_snap_enabled = not self.terrain_snap_enabled
                        if (self.terrain_snap_enabled and
                                getattr(getattr(self, 'terrain_renderer', None),
                                        'combined_heightmap', None) is None):
                            self._load_terrain_data()
                        self.update()
                        return

                # Edit Terrain badge click
                if self._terrain_edit_badge_rect is not None:
                    ex, ey, ew, eh = self._terrain_edit_badge_rect
                    if ex <= mouse_x <= ex + ew and ey <= mouse_y <= ey + eh:
                        self.terrain_edit_mode = not self.terrain_edit_mode
                        if self.terrain_edit_mode:
                            self.terrain_paint_mode = False
                            if self._terrain_data is None:
                                self._load_terrain_data()
                        self._terrain_edit_hit = None
                        self.update()
                        return

                # Paint Texture badge click
                if self._terrain_paint_badge_rect is not None:
                    px, py, pw, ph = self._terrain_paint_badge_rect
                    if px <= mouse_x <= px + pw and py <= mouse_y <= py + ph:
                        self.terrain_paint_mode = not self.terrain_paint_mode
                        if self.terrain_paint_mode:
                            self.terrain_edit_mode = False
                            if self._ttp is None or self._te_paint_colors is None:
                                ok = self._load_texture_painter()
                                if not ok:
                                    self.terrain_paint_mode = False
                                else:
                                    self._notify_tex_thumbnails_updated()
                        self._terrain_edit_hit = None
                        self.update()
                        return

                # Terrain edit stroke start
                if self.terrain_edit_mode:
                    self.makeCurrent()
                    hit = self._terrain_edit_unproject(mouse_x, mouse_y)
                    if hit is not None:
                        self._terrain_edit_hit = hit
                        hc = self._world_to_heightmap_coords(hit[0], hit[2])
                        if hc is not None:
                            self._terrain_edit_pressing = True
                            self._terrain_edit_stroking = False
                            self._sync_te_to_dialog()
                            self._terrain_stroke_apply(hc[0], hc[1], first=True)
                            self._terrain_edit_stroking = True
                    self.update()
                    return

                # Terrain paint stroke start
                if self.terrain_paint_mode:
                    self.makeCurrent()
                    hit = self._terrain_edit_unproject(mouse_x, mouse_y)
                    print(f"[Paint] click ({mouse_x:.0f},{mouse_y:.0f}) → hit={hit} ttp={self._ttp is not None} td={self._terrain_data is not None}")
                    if hit is not None:
                        self._terrain_edit_hit = hit
                        hc = self._world_to_heightmap_coords(hit[0], hit[2])
                        print(f"[Paint] world ({hit[0]:.1f},{hit[2]:.1f}) → hc={hc}")
                        if hc is not None:
                            self._tp_pressing = True
                            self._terrain_paint_apply(hc[0], hc[1], first=True)
                    self.update()
                    return

                self.makeCurrent()

                glMatrixMode(GL_PROJECTION)
                glLoadIdentity()
                gluPerspective(60, self.width() / self.height(), 0.1, 10000.0)
                
                glMatrixMode(GL_MODELVIEW)
                glLoadIdentity()
                cam = self.camera_3d
                gluLookAt(
                    cam.position[0], cam.position[1], cam.position[2],
                    *cam.get_look_at(),
                    0, 1, 0
                )
                
                edit_mode_3d = getattr(self.input_handler, 'edit_mode_3d', False)

                # Check 3D gizmo hit first (only in Edit mode, only if entity selected)
                if (edit_mode_3d and hasattr(self, 'gizmo_3d') and self.selected_entity and
                        not self.gizmo_3d.hidden):
                    self.gizmo_3d.reproject_for_hit(self)
                    dpr = self.devicePixelRatio()
                    hit = self.gizmo_3d.hit_test(mouse_x * dpr, mouse_y * dpr)
                    if hit != GIZMO3D_HANDLE_NONE:
                        self.gizmo_3d.start_drag(hit, mouse_x * dpr, mouse_y * dpr,
                                                  self.selected_entity, self)
                        self.update()
                        return

                selected_entity = self.select_entity_3d(mouse_x, mouse_y)

                if selected_entity:
                    selected_group = self.select_entity_with_children(selected_entity)

                    self.selected = selected_group
                    self.selected_entity = selected_entity

                    if hasattr(self, 'gizmo_renderer'):
                        self.gizmo_renderer.update_gizmo_for_entity(selected_entity)
                    if hasattr(self, 'gizmo_3d'):
                        self.gizmo_3d.move_to(selected_entity)

                    self.entitySelected.emit(selected_entity)
                    self.selection_modified = True
                    print(f"Selected in 3D: {selected_entity.name} ({len(selected_group)} entities total)")
                else:
                    self.selected = []
                    self.selected_entity = None
                    self._managers_vpos_links = {}

                    if hasattr(self, 'gizmo_renderer'):
                        self.gizmo_renderer.hide_gizmo()
                    if hasattr(self, 'gizmo_3d'):
                        self.gizmo_3d.move_to(None)

                    self.entitySelected.emit(None)
                    self.selection_modified = True
                    print("Cleared selection in 3D mode")

                self.update()
                return
                
            elif event.button() == Qt.MouseButton.RightButton:
                self.mouse_captured_3d = True
                self.setCursor(Qt.CursorShape.BlankCursor)
                self._mouse_anchor_global = self.mapToGlobal(event.position().toPoint())
                return
        else:
            # 2D mode - use input_handler
            self.input_handler.handle_mouse_press(event)

    def mouseReleaseEvent(self, event):
        """Handle mouse release - mode aware"""
        if self.mode == MODE_3D:
            if event.button() == Qt.MouseButton.LeftButton:
                # End terrain edit stroke
                if self.terrain_edit_mode and self._terrain_edit_pressing:
                    self._terrain_edit_pressing = False
                    if self._terrain_edit_stroking:
                        self._terrain_edit_stroking = False
                        te = self._get_terrain_editor()
                        if te is not None:
                            te.end_stroke_external()
                    return

                # End terrain paint stroke
                if self.terrain_paint_mode and self._tp_pressing:
                    self._tp_pressing = False
                    return

                edit_mode_3d = getattr(self.input_handler, 'edit_mode_3d', False)
                if (edit_mode_3d and hasattr(self, 'gizmo_3d') and
                        self.gizmo_3d.active_handle != GIZMO3D_HANDLE_NONE and
                        self.selected_entity):
                    was_trans = self.gizmo_3d.active_handle in (0, 1, 2, 6)
                    self.gizmo_3d.end_drag(self.selected_entity, self)
                    if was_trans:
                        self._auto_save_entity_changes(self.selected_entity)
                        if hasattr(self, '_flush_managers_xml'):
                            self._flush_managers_xml()
                    self.update()
            elif event.button() == Qt.MouseButton.RightButton:
                self.mouse_captured_3d = False
                self.unsetCursor()
        else:
            # 2D mode - use input_handler
            self.input_handler.handle_mouse_release(event)

    def mouseMoveEvent(self, event):
        """Handle mouse move - mode aware"""
        if self.mode == MODE_3D:
            # Gizmo drag takes priority over camera pan (only in Edit mode)
            edit_mode_3d = getattr(self.input_handler, 'edit_mode_3d', False)
            if (edit_mode_3d and hasattr(self, 'gizmo_3d') and
                    self.gizmo_3d.active_handle != GIZMO3D_HANDLE_NONE and
                    self.selected_entity):
                dpr = self.devicePixelRatio()
                mx = event.position().x() * dpr
                my = event.position().y() * dpr
                self.gizmo_3d.update_drag(mx, my, self.selected_entity, self)
                return

            if self.mouse_captured_3d and hasattr(self, '_mouse_anchor_global'):
                current_global = self.mapToGlobal(event.position().toPoint())
                dx = current_global.x() - self._mouse_anchor_global.x()
                dy = current_global.y() - self._mouse_anchor_global.y()

                if dx == 0 and dy == 0:
                    return  # Skip the synthetic event generated by the warp below

                self.camera_3d.rotate(dx, dy)
                QCursor.setPos(self._mouse_anchor_global)
                self.update()
                return

            # Terrain edit: hover gizmo and stroke continuation
            if self.terrain_edit_mode and not self.mouse_captured_3d:
                mx = event.position().x()
                my = event.position().y()
                # Skip stroke when cursor is over any UI element (keep last hit so gizmo stays)
                if self._is_over_te_ui(mx, my):
                    return
                self.makeCurrent()
                hit = self._terrain_edit_unproject(mx, my)
                self._terrain_edit_hit = hit
                if hit is not None and self._terrain_edit_pressing:
                    hc = self._world_to_heightmap_coords(hit[0], hit[2])
                    if hc is not None:
                        self._terrain_stroke_apply(hc[0], hc[1], first=False)
                self.update()

            # Terrain paint: stroke continuation
            elif self.terrain_paint_mode and not self.mouse_captured_3d:
                mx = event.position().x()
                my = event.position().y()
                self.makeCurrent()
                hit = self._terrain_edit_unproject(mx, my)
                self._terrain_edit_hit = hit
                if hit is not None and self._tp_pressing:
                    hc = self._world_to_heightmap_coords(hit[0], hit[2])
                    if hc is not None:
                        self._terrain_paint_apply(hc[0], hc[1])
                self.update()
        else:
            # 2D mode - use input_handler
            self.input_handler.handle_mouse_move(event)

    def wheelEvent(self, event):
        """Handle wheel - mode aware"""
        if self.mode == MODE_TOPDOWN:
            self.input_handler.handle_wheel(event)
            self.update()
        
    def select_entity_2d(self, mouse_x, mouse_y):
        """Select entity in 2D (your existing implementation)"""
        if not self.entities:
            return None
        
        world_x, world_y = self.screen_to_world(mouse_x, mouse_y)
        
        closest_entity = None
        closest_distance = float('inf')
        selection_radius = 10.0 / self.scale_factor
        
        for entity in self.entities:
            dx = entity.x - world_x
            dy = entity.y - world_y
            distance = (dx * dx + dy * dy) ** 0.5
            
            if distance < selection_radius and distance < closest_distance:
                closest_distance = distance
                closest_entity = entity
        
        return closest_entity
    
    def select_entity_3d(self, mouse_x, mouse_y):
        """Select entity in 3D mode using per-triangle raycasting.

        Pipeline:
          1. Build a world-space ray via gluUnProject (FOV 50, matching paintGL).
          2. For each visible entity with a loaded model:
               a. Transform the ray into model-local space (undo translation,
                  rotation, scale) so the AABB test is tight and rotation-correct.
               b. AABB broad phase against bounds_min/bounds_max — skip if miss or
                  already have a closer hit.
               c. Vectorised Möller-Trumbore narrow phase across all mesh triangles.
          3. Entities without a model fall back to a small unit box.
          4. Return the closest hit entity by t.
        """
        if not self.entities:
            return None

        try:
            dpr    = self.devicePixelRatio()
            aspect = self.width() / self.height() if self.height() > 0 else 1.0
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            gluPerspective(50, aspect, 0.1, 10000.0)

            viewport   = glGetIntegerv(GL_VIEWPORT)
            modelview  = glGetDoublev(GL_MODELVIEW_MATRIX)
            projection = glGetDoublev(GL_PROJECTION_MATRIX)

            px = float(mouse_x) * dpr
            py = float(mouse_y) * dpr
            h  = float(viewport[3])
            near_pt = gluUnProject(px, h - py, 0.0, modelview, projection, viewport)
            far_pt  = gluUnProject(px, h - py, 1.0, modelview, projection, viewport)

            ray_o     = np.array(near_pt, dtype=np.float64)
            ray_d_raw = np.array(far_pt,  dtype=np.float64) - ray_o
            ray_len   = np.linalg.norm(ray_d_raw)
            if ray_len < 1e-10:
                return None
            ray_d = ray_d_raw / ray_len  # normalised world-space direction

            closest_entity = None
            closest_t      = float('inf')
            FALLBACK_RADIUS = 1.5
            tested_ids = set()

            if hasattr(self, 'model_loader') and self.model_loader is not None:
                # Array-native GDR mode skips prepare_batches, so instance_batches
                # is empty/stale. Rebuild it once at click time (a few ms) so the
                # ray test below sees current per-instance transforms.
                if getattr(self.model_loader, 'gdr_drew_last', False):
                    try:
                        self.model_loader.prepare_batches(
                            self._get_visible_entities(), self.selected)
                    except Exception as _pe:
                        print(f"select_entity_3d: pick-time batch rebuild failed: {_pe}")
                for model_path, instances in self.model_loader.instance_batches.items():
                    model      = self.model_loader.models_cache.get(model_path)
                    has_bounds = (model is not None and
                                  model.bounds_min is not None and
                                  model.bounds_max is not None)
                    has_meshes = (model is not None and bool(model.meshes) and
                                  any(m.vertices is not None for m in model.meshes))

                    bmin = np.array(model.bounds_min, dtype=np.float64) if has_bounds else None
                    bmax = np.array(model.bounds_max, dtype=np.float64) if has_bounds else None

                    for inst in instances:
                        # tuple: (entity, px, py, pz, rx, ry, rz, scale, is_selected)
                        entity = inst[0]
                        tested_ids.add(id(entity))

                        pos   = np.array((inst[1], inst[2], inst[3]), dtype=np.float64)
                        rot   = (inst[4], inst[5], inst[6])  # (rx, ry, rz) degrees
                        scale = float(inst[7])

                        # Build the combined rotation matrix matching the renderer:
                        #   glRotatef(-90, X)  glRotatef(-rz, Z)  glRotatef(rx, X)  glRotatef(ry, Y)
                        R = (_make_rot_x(-90.0) @
                             _make_rot_z(-rot[2]) @
                             _make_rot_x( rot[0]) @
                             _make_rot_y( rot[1]))

                        # Transform world ray into model-local space.
                        # Key identity: t_local == t_world when the direction is
                        # divided by scale (not normalised), so hits are comparable.
                        R_inv    = R.T                              # R is orthogonal
                        local_o  = (R_inv @ (ray_o - pos)) / scale
                        local_d  = (R_inv @ ray_d)        / scale  # preserves t mapping

                        # --- Broad phase: AABB in model-local space ---
                        if has_bounds:
                            t_broad = _ray_aabb_intersect(local_o, local_d, bmin, bmax)
                        else:
                            r = FALLBACK_RADIUS / max(scale, 1e-6)
                            t_broad = _ray_aabb_intersect(local_o, local_d,
                                                          np.full(3, -r), np.full(3, r))

                        if t_broad is None or t_broad >= closest_t:
                            continue

                        # --- Narrow phase: per-triangle Möller-Trumbore ---
                        if has_meshes:
                            t_hit = None
                            for mesh in model.meshes:
                                if mesh.vertices is None:
                                    continue
                                if mesh.indices is not None:
                                    idx = mesh.indices
                                else:
                                    # drawArrays path — sequential triangle triplets
                                    n = len(np.asarray(mesh.vertices).reshape(-1, 3))
                                    idx = np.arange(n, dtype=np.int64)
                                t_tri = _ray_triangle_mesh_intersect(
                                    local_o, local_d, mesh.vertices, idx)
                                if t_tri is not None and (t_hit is None or t_tri < t_hit):
                                    t_hit = t_tri
                            if t_hit is not None and 0.0 < t_hit < closest_t:
                                closest_t      = t_hit
                                closest_entity = entity
                        else:
                            # No mesh data available — accept the AABB hit
                            if 0.0 < t_broad < closest_t:
                                closest_t      = t_broad
                                closest_entity = entity

            # Pass 2: visible entities with no 3D model — small box fallback
            for entity in self._get_visible_entities():
                if id(entity) in tested_ids:
                    continue
                if not (hasattr(entity, 'x') and hasattr(entity, 'y') and hasattr(entity, 'z')):
                    continue
                p = np.array([float(entity.x), float(entity.z), float(-entity.y)])
                t = _ray_aabb_intersect(ray_o, ray_d, p - FALLBACK_RADIUS, p + FALLBACK_RADIUS)
                if t is not None and 0.0 < t < closest_t:
                    closest_t      = t
                    closest_entity = entity

            return closest_entity

        except Exception as e:
            print(f"Error in select_entity_3d: {e}")
            import traceback
            traceback.print_exc()
            return None

    def select_entity_with_children(self, entity):
        """
        Select an entity and automatically select:
        1. Structure children (if it's a Structure/Prefab) — via value-Hash64
        2. Any entity referenced by an ent* field — value-Id64 OR bare BinHex
           (covers entUser in InitialUsers, entInitialUser in AIObject, etc.)

        Returns list of all selected entities (parent + all linked entities).
        """
        if not entity:
            return []

        selected_group = [entity]

        # Always build fresh — _entities_dict can be stale after paste/import adds new entities
        entities_dict = {ent.id: ent for ent in getattr(self, 'entities', [])}

        if hasattr(entity, 'xml_element') and entity.xml_element is not None:

            # 1. Structure children (value-Hash64 refs in Children/Child objects)
            entity_class_field = entity.xml_element.find(".//field[@name='text_hidEntityClass']")
            if entity_class_field is not None:
                entity_class = entity_class_field.get('value-String', '')
                if 'Prefab' in entity_class or 'Structure' in entity.name:
                    children_obj = entity.xml_element.find(".//object[@name='Children']")
                    if children_obj is not None:
                        for child_obj in children_obj.findall("object[@name='Child']"):
                            id_field = child_obj.find("field[@name='ID']")
                            name_field = child_obj.find("field[@name='Name']")
                            if id_field is not None:
                                child_id = id_field.get('value-Hash64')
                                child_name = name_field.get('value-String') if name_field is not None else ''
                                if child_id and child_id in entities_dict:
                                    child_ent = entities_dict[child_id]
                                    if child_ent not in selected_group:
                                        selected_group.append(child_ent)
                                elif child_name:
                                    for ent in entities_dict.values():
                                        if ent.name == child_name and ent not in selected_group:
                                            selected_group.append(ent)
                                            break

            # 2. All ent* entity reference fields — value-Id64 AND bare BinHex
            #    Covers: entUser (InitialUsers seats), entInitialUser (AIObject),
            #            and any future ent* refs without hard-coding component paths.
            import struct as _struct
            for field in entity.xml_element.iter('field'):
                fname = field.get('name', '')
                if not fname.startswith('ent'):
                    continue

                ref_id = field.get('value-Id64')
                if not ref_id:
                    # Bare BinHex fallback
                    binhex = (field.text or '').strip().upper()
                    if len(binhex) == 16 and binhex != 'FFFFFFFFFFFFFFFF':
                        try:
                            ref_id = str(_struct.unpack('<Q', bytes.fromhex(binhex))[0])
                        except Exception:
                            pass

                if ref_id and ref_id in entities_dict:
                    ref_ent = entities_dict[ref_id]
                    if ref_ent.id != entity.id and ref_ent not in selected_group:
                        selected_group.append(ref_ent)

        # Link all selected entities to their managers.xml vPos fields
        self._build_managers_vpos_links(selected_group)

        return selected_group

    def _build_managers_vpos_links(self, entities):
        """Populate self._managers_vpos_links from the pre-built managers_vpos_map.

        managers_vpos_map is built once when managers.xml loads so this is just
        a series of O(1) dict gets — no tree scan at selection time.
        """
        self._managers_vpos_links = {}
        main_window = self
        while main_window.parent():
            main_window = main_window.parent()
        vpos_map = getattr(main_window, 'managers_vpos_map', None)
        if not vpos_map:
            return
        for entity in entities:
            eid = str(getattr(entity, 'id', ''))
            fields = vpos_map.get(eid)
            if fields:
                self._managers_vpos_links[eid] = fields
        if self._managers_vpos_links:
            print(f"managers.xml: linked vPos for entity IDs {list(self._managers_vpos_links)}")

    def calculate_group_center(self, entities):
        """Calculate the center point of a group of entities"""
        if not entities:
            return (0, 0, 0)
        
        valid_entities = [e for e in entities if hasattr(e, 'x') and hasattr(e, 'y') and hasattr(e, 'z')]
        
        if not valid_entities:
            return (0, 0, 0)
        
        total_x = sum(e.x for e in valid_entities)
        total_y = sum(e.y for e in valid_entities)
        total_z = sum(e.z for e in valid_entities)
        
        count = len(valid_entities)
        return (total_x / count, total_y / count, total_z / count)

    def rotate_group_around_center(self, entities, rotation_degrees, center=None):
        """
        Rotate a group of entities around their common center point.
        This handles:
        1. Structure children
        2. Seated NPCs in vehicles
        3. Regular entities
        
        Rotates each entity's position AND updates each entity's individual rotation.
        """
        if not entities:
            return
        
        # Calculate center if not provided
        if center is None:
            center = self.calculate_group_center(entities)
        
        center_x, center_y, center_z = center
        
        # Convert rotation to radians
        rotation_rad = math.radians(rotation_degrees)
        cos_angle = math.cos(rotation_rad)
        sin_angle = math.sin(rotation_rad)
        
        # Build entity lookup dict for relationship detection
        entities_dict = {}
        if hasattr(self, 'entities'):
            for ent in self.entities:
                entities_dict[ent.id] = ent
        
        # Analyze group composition
        structure_parents = 0
        structure_children = 0
        vehicles = 0
        seated_npcs = 0
        regular_entities = 0
        
        for entity in entities:
            if hasattr(entity, 'xml_element') and entity.xml_element is not None:
                # Check if Structure parent
                entity_class_field = entity.xml_element.find(".//field[@name='text_hidEntityClass']")
                if entity_class_field is not None:
                    entity_class = entity_class_field.get('value-String', '')
                    if 'Prefab' in entity_class or 'Structure' in entity.name:
                        structure_parents += 1
                        continue
                
                # Check if vehicle with seated NPCs
                ai_component = entity.xml_element.find(".//object[@name='CFCXAIComponent']")
                if ai_component is not None:
                    ai_object = ai_component.find(".//object[@name='AIObject']")
                    if ai_object is not None:
                        vehicles += 1
                        continue
                
                # Check if this is a seated NPC (referenced by a vehicle)
                is_seated = False
                for other_entity in entities:
                    if other_entity == entity:
                        continue
                    if hasattr(other_entity, 'xml_element') and other_entity.xml_element is not None:
                        ai_comp = other_entity.xml_element.find(".//object[@name='CFCXAIComponent']")
                        if ai_comp is not None:
                            ai_obj = ai_comp.find(".//object[@name='AIObject']")
                            if ai_obj is not None:
                                for field in ai_obj.findall("field"):
                                    entity_id_ref = field.get('value-Hash64')
                                    if entity_id_ref == entity.id:
                                        seated_npcs += 1
                                        is_seated = True
                                        break
                            if is_seated:
                                break
                    if is_seated:
                        break
                
                if is_seated:
                    continue
                
                # Otherwise it's a regular entity or structure child
                regular_entities += 1
            else:
                regular_entities += 1
        
        # Log group composition
        composition = []
        if structure_parents > 0:
            composition.append(f"{structure_parents} structure(s)")
        if vehicles > 0:
            composition.append(f"{vehicles} vehicle(s)")
        if seated_npcs > 0:
            composition.append(f"{seated_npcs} seated NPC(s)")
        if structure_children > 0:
            composition.append(f"{structure_children} child(ren)")
        if regular_entities > 0:
            composition.append(f"{regular_entities} regular")
        
        composition_str = ", ".join(composition) if composition else "unknown types"
        
        print(f"🔄 Rotating {len(entities)} entities by {rotation_degrees:.1f}° around center ({center_x:.1f}, {center_y:.1f})")
        print(f"   Composition: {composition_str}")
        
        for entity in entities:
            if not (hasattr(entity, 'x') and hasattr(entity, 'y')):
                continue
            
            # Calculate offset from center
            offset_x = entity.x - center_x
            offset_y = entity.y - center_y
            
            # Rotate the offset around center (2D rotation in X-Y plane)
            rotated_offset_x = offset_x * cos_angle - offset_y * sin_angle
            rotated_offset_y = offset_x * sin_angle + offset_y * cos_angle
            
            # Update entity position
            old_x, old_y = entity.x, entity.y
            entity.x = center_x + rotated_offset_x
            entity.y = center_y + rotated_offset_y
            # Z stays the same
            
            # Get entity's current individual rotation
            if hasattr(self, 'gizmo_renderer') and self.gizmo_renderer.rotation_gizmo:
                current_rotation = self.gizmo_renderer.rotation_gizmo.extract_entity_rotation(entity)
            else:
                current_rotation = 0.0
            
            # FIXED: Negate rotation_degrees to match the corrected group rotation direction
            # This ensures entities rotate in the same direction as their positions
            new_rotation = (current_rotation - rotation_degrees) % 360
            
            # Update entity rotation in XML
            if hasattr(self, 'gizmo_renderer') and self.gizmo_renderer.rotation_gizmo:
                self.gizmo_renderer.rotation_gizmo.update_entity_rotation(entity, new_rotation)
            
            # Update position in XML
            self.update_entity_xml(entity)
            self.mark_entity_modified(entity)
            
            # Determine entity type for logging
            entity_type = "entity"
            if hasattr(entity, 'xml_element') and entity.xml_element is not None:
                entity_class_field = entity.xml_element.find(".//field[@name='text_hidEntityClass']")
                if entity_class_field is not None:
                    entity_class = entity_class_field.get('value-String', '')
                    if 'Prefab' in entity_class or 'Structure' in entity.name:
                        entity_type = "🗿 structure"
                
                ai_component = entity.xml_element.find(".//object[@name='CFCXAIComponent']")
                if ai_component is not None:
                    entity_type = "🚗 vehicle"
            
            print(f"  {entity_type} {entity.name}: pos ({old_x:.1f}, {old_y:.1f}) → ({entity.x:.1f}, {entity.y:.1f}), rot {current_rotation:.1f}° → {new_rotation:.1f}°")
        
        # Auto-save changes
        if len(entities) > 0:
            self._auto_save_entity_changes(entities[0])

    def set_entities(self, entities, center_view=True):
        """Set entities after level load - models should already be assigned by load_complete_level.

        Args:
            entities: New entity list.
            center_view: If True (default), recentre the camera on the entity cloud.
                         Pass False when updating the list without wanting a camera jump
                         (e.g. after a delete, paste, or undo operation).
        """
        print(f"Setting {len(entities)} entities.")
        self.entities = entities
        self.show_entities = True

        # Build entity cache for 2D rendering
        if hasattr(self, 'entity_renderer'):
            for entity in entities:
                self.entity_renderer.get_or_cache_entity_data(entity)

        self.selected_entity = None
        self.selected = []
        self.entities_modified = True
        self.selection_modified = True

        # Prime all per-frame caches immediately so the first rendered frame is never cold.
        # This builds _positions_3d, _valid_entities_3d, and _map_filter_cache.
        self._map_filter_cache_key = None  # force rebuild
        self._rel_cache_key = None         # force relationship cache rebuild
        self._get_map_filtered_entities()  # populates _positions_3d / _valid_entities_3d

        if entities and center_view:
            self._center_view_on_entities()

        print(f"Entities set: count={len(entities)}")
        self.update()

    def setup_3d_models_for_level(self, worlds_path, resource_folder=None):
        """
        Setup 3D models specifically for a loaded level.
        Loads models from user's unpacked game data folder, not local assets.
        
        Args:
            worlds_path: Path to the level's worlds folder (for EntityLibrary)
            resource_folder: Optional override for models location (user's unpacked data folder)
        
        Models: resource_folder/graphics OR patch/graphics (game files)
        EntityLibrary: LOCAL editor assets (canvas/assets/[game]/entitylibrary/)
        Materials: resource_folder/graphics/_materials (game files)
        """
        print(f"\n=== Setting up 3D models for level ===")
        print(f"Level worlds path: {worlds_path}")
        print(f"Resource folder: {resource_folder or 'Using patch folder'}")
        
        if not worlds_path or not os.path.exists(worlds_path):
            print(f"Invalid worlds path: {worlds_path}")
            return False
        
        # ============================================
        # Derive patch root from worlds path
        # ============================================
        path_parts = worlds_path.replace('\\', '/').split('/')
        
        # Find 'worlds' or 'Worlds' in path
        worlds_index = -1
        for i, part in enumerate(path_parts):
            if part.lower() == 'worlds':
                worlds_index = i
                break
        
        if worlds_index == -1:
            print(f"Could not find 'worlds' folder in path: {worlds_path}")
            return False
        
        # Patch root is everything up to (but not including) 'worlds'
        patch_root = '/'.join(path_parts[:worlds_index])
        print(f"Derived patch root: {patch_root}")
        
        # ============================================
        # 1. Setup EntityLibrary from LOCAL editor assets
        # ============================================
        # Get local EntityLibrary path based on game mode
        current_dir = os.path.dirname(os.path.abspath(__file__))
        editor_root = os.path.dirname(current_dir)
        
        game_folder = "avatar" if getattr(self, 'game_mode', 'avatar') == "avatar" else "fc2"
        
        # Try multiple possible paths for EntityLibrary
        entitylib_paths = [
            os.path.join(editor_root, "canvas", "assets", game_folder, "entitylibrary", "entitylibrary_full.fcb.converted.xml"),
            os.path.join(editor_root, "assets", game_folder, "entitylibrary", "entitylibrary_full.fcb.converted.xml"),
            os.path.join(current_dir, "assets", game_folder, "entitylibrary", "entitylibrary_full.fcb.converted.xml"),
        ]
        
        local_entitylib_path = None
        for path in entitylib_paths:
            if os.path.exists(path):
                local_entitylib_path = path
                break
        
        if local_entitylib_path and os.path.exists(local_entitylib_path):
            # Load local EntityLibrary
            try:
                import xml.etree.ElementTree as ET
                tree = ET.parse(local_entitylib_path)
                root = tree.getroot()
                self.model_loader.entity_patterns = {}
                
                # Parse EntityLibrary
                for proto_obj in root.findall(".//object[@name='EntityPrototype']"):
                    name_field = proto_obj.find(".//field[@name='Name']")
                    if name_field is None:
                        continue
                    
                    proto_name = name_field.get('value-String')
                    if not proto_name:
                        continue
                    
                    entity_obj = proto_obj.find(".//object[@name='Entity']")
                    if entity_obj is None:
                        continue
                    
                    hid_field = entity_obj.find(".//field[@name='hidName']")
                    hid_name = hid_field.get('value-String') if hid_field is not None else None
                    
                    descriptor_component = entity_obj.find(".//object[@name='CFileDescriptorComponent']")
                    if descriptor_component is not None:
                        hid_descriptor = descriptor_component.find(".//field[@name='hidDescriptor']")
                        if hid_descriptor is not None:
                            # Try GraphicComponent
                            graphic_component = hid_descriptor.find(".//component[@class='GraphicComponent']")
                            if graphic_component is not None:
                                resource = graphic_component.find(".//resource")
                                if resource is not None:
                                    model_file = resource.get('fileName')
                                    if model_file:
                                        self.model_loader.entity_patterns[proto_name] = model_file
                                        if hid_name:
                                            self.model_loader.entity_patterns[hid_name] = model_file
                            
                            # Try GraphicKitComponent
                            kit_component = hid_descriptor.find(".//component[@class='GraphicKitComponent']")
                            if kit_component is not None:
                                resource = kit_component.find(".//resource")
                                if resource is not None:
                                    model_file = resource.get('fileName')
                                    if model_file:
                                        self.model_loader.entity_patterns[proto_name] = model_file
                                        if hid_name:
                                            self.model_loader.entity_patterns[hid_name] = model_file
                
                self.model_loader._entity_library_loaded = True
                print(f"✓ EntityLibrary loaded (LOCAL): {local_entitylib_path}")
                print(f"  Loaded {len(self.model_loader.entity_patterns)} entity patterns")
            except Exception as e:
                print(f"✗ Failed to load local EntityLibrary: {e}")
                import traceback
                traceback.print_exc()
                return False
        else:
            print(f"✗ Local EntityLibrary not found. Tried:")
            for path in entitylib_paths:
                print(f"  - {path}")
            return False
        
        # ============================================
        # 2. Setup Models from resource folder OR patch
        # ============================================
        models_path = None
        
        if resource_folder and os.path.exists(resource_folder):
            # Use user's unpacked data folder
            models_path = os.path.join(resource_folder, "graphics")
            if os.path.exists(models_path):
                print(f"Using resource folder for models: {models_path}")
            else:
                print(f"⚠ Graphics folder not found in resource folder: {models_path}")
                models_path = None
        
        # Fallback to patch folder if no resource folder
        if not models_path:
            models_path = os.path.join(patch_root, "graphics")
            if os.path.exists(models_path):
                print(f"Using patch folder for models: {models_path}")
            else:
                print(f"✗ Models directory not found: {models_path}")
                return False
        
        self.model_loader.set_models_directory(models_path, scan_recursive=True)
        print(f"✓ Models directory set: {models_path}")
        
        # ============================================
        # 3. Setup Materials from resource folder OR patch
        # ============================================
        materials_path = None
        
        if resource_folder and os.path.exists(resource_folder):
            # Try resource folder first
            materials_path = os.path.join(resource_folder, "graphics", "_materials")
            if not os.path.exists(materials_path):
                materials_path = os.path.join(resource_folder, "graphics", "materials")
            if not os.path.exists(materials_path):
                materials_path = None
        
        # Fallback to patch folder
        if not materials_path:
            materials_path = os.path.join(patch_root, "graphics", "_materials")
            if not os.path.exists(materials_path):
                materials_path = os.path.join(patch_root, "graphics", "materials")
        
        if materials_path and os.path.exists(materials_path):
            self.model_loader.set_materials_directory(materials_path)
            print(f"✓ Materials directory set: {materials_path}")
        else:
            print(f"⚠ Materials directory not found")
            print(f"   Models will render without textures")
        
        print(f"=== 3D model setup complete ===\n")
        return True

    def _center_view_on_entities(self):
        """Center 2D view on all entities"""
        if not self.entities:
            return
        
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        
        valid_entities = 0
        for entity in self.entities:
            if hasattr(entity, 'x') and hasattr(entity, 'y'):
                min_x = min(min_x, entity.x)
                max_x = max(max_x, entity.x)
                min_y = min(min_y, entity.y)
                max_y = max(max_y, entity.y)
                valid_entities += 1
        
        if valid_entities == 0:
            return
        
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        
        if max_x > min_x and max_y > min_y:
            width_span = max_x - min_x
            height_span = max_y - min_y
            
            scale_x = (self.width() * 0.8) / width_span if width_span > 0 else 1.0
            scale_y = (self.height() * 0.8) / height_span if height_span > 0 else 1.0
            self.scale_factor = min(scale_x, scale_y, 2.0)
        else:
            self.scale_factor = 1.0
        
        new_offset_x = self.width() / 2 - center_x * self.scale_factor
        new_offset_y = self.height() / 2 - center_y * self.scale_factor
        
        self.camera_controller.offset_x = new_offset_x
        self.camera_controller.offset_y = new_offset_y
        self.offset_x = new_offset_x
        self.offset_y = new_offset_y
        
        print(f"Centered view on {valid_entities} entities at scale {self.scale_factor:.2f}")
    
    def render_models_thumbnail(self, models, size=128, azimuth=45.0, elevation=-17.0, distance_mult=1.8):
        """Render a list of GLTFModels into one FBO (for kit-assembled NPCs)."""
        try:
            from PyQt6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
            from OpenGL.GLU import gluPerspective, gluLookAt

            self.makeCurrent()

            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setAttachment(QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
            fbo = QOpenGLFramebufferObject(size, size, fmt)
            if not fbo.isValid() or not fbo.bind():
                self.doneCurrent()
                return None

            glViewport(0, 0, size, size)
            glClearColor(0.12, 0.12, 0.20, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            glFrontFace(GL_CW)
            glDisable(GL_CULL_FACE)
            glEnable(GL_DEPTH_TEST)
            glDepthFunc(GL_LEQUAL)
            glDepthMask(GL_TRUE)
            glEnable(GL_LIGHTING)
            glEnable(GL_LIGHT0)
            glEnable(GL_LIGHT1)
            glDisable(GL_LIGHT2)
            glEnable(GL_COLOR_MATERIAL)
            glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
            glEnable(GL_NORMALIZE)
            glLightModeli(GL_LIGHT_MODEL_LOCAL_VIEWER, GL_TRUE)
            glLightfv(GL_LIGHT0, GL_POSITION, self._key_light_pos())
            glLightfv(GL_LIGHT0, GL_DIFFUSE,  [0.90, 0.88, 0.82, 1.0])
            glLightfv(GL_LIGHT0, GL_SPECULAR, [0.50, 0.48, 0.44, 1.0])
            glLightfv(GL_LIGHT0, GL_AMBIENT,  [0.00, 0.00, 0.00, 1.0])
            glLightfv(GL_LIGHT1, GL_POSITION, [0.0, 1.0, 0.0, 0.0])
            glLightfv(GL_LIGHT1, GL_DIFFUSE,  [0.30, 0.33, 0.42, 1.0])
            glLightfv(GL_LIGHT1, GL_SPECULAR, [0.00, 0.00, 0.00, 1.0])
            glLightfv(GL_LIGHT1, GL_AMBIENT,  [0.00, 0.00, 0.00, 1.0])
            glLightModelfv(GL_LIGHT_MODEL_AMBIENT, [0.38, 0.38, 0.42, 1.0])
            glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR, [0.15, 0.15, 0.15, 1.0])
            glMaterialf(GL_FRONT_AND_BACK, GL_SHININESS, 40.0)
            glColor3f(1.0, 1.0, 1.0)

            # Combined bounds across all parts
            all_min = [float('inf')] * 3
            all_max = [float('-inf')] * 3
            for m in models:
                bmin, bmax = m.get_bounds() if hasattr(m, 'get_bounds') else (None, None)
                if bmin and bmax:
                    for i in range(3):
                        all_min[i] = min(all_min[i], bmin[i])
                        all_max[i] = max(all_max[i], bmax[i])

            if all_min[0] != float('inf'):
                cx = (all_min[0] + all_max[0]) / 2.0
                cy = (all_min[1] + all_max[1]) / 2.0
                cz = (all_min[2] + all_max[2]) / 2.0
                span = max(all_max[i] - all_min[i] for i in range(3))
                span = max(span, 0.1)
            else:
                cx = cy = cz = 0.0
                span = 2.0

            cam_dist = span * distance_mult
            _az = math.radians(azimuth)
            _el = math.radians(elevation)
            eye_x = cx + cam_dist * math.cos(_el) * math.sin(_az)
            eye_y = cy + cam_dist * math.sin(_el)
            eye_z = cz + cam_dist * math.cos(_el) * math.cos(_az)
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            gluPerspective(45.0, 1.0, max(cam_dist * 0.01, 0.01), cam_dist * 20.0)
            glMatrixMode(GL_MODELVIEW)
            glLoadIdentity()
            gluLookAt(eye_x, eye_y, eye_z, cx, cy, cz, 0, 1, 0)

            for m in models:
                if getattr(m, 'display_list', None):
                    glCallList(m.display_list)
                elif hasattr(self, 'model_loader'):
                    self.model_loader._render_immediate_mode(m)

            glDisable(GL_ALPHA_TEST)
            raw = fbo.toImage()
            fbo.release()
            self.doneCurrent()

            from PyQt6.QtGui import QTransform as _QT
            raw = raw.transformed(_QT().rotate(90))
            raw = raw.mirrored(True, False)
            return raw

        except Exception as _e:
            print(f"render_models_thumbnail error: {_e}")
            try:
                self.doneCurrent()
            except Exception:
                pass
            return None

    def render_model_thumbnail(self, model, size=128, azimuth=45.0, elevation=-17.0, distance_mult=1.8):
        """Render a single GLTFModel to an offscreen FBO and return a QImage.

        Requires the GL context to be available (i.e., the canvas has been shown).
        Returns None on any failure.
        """
        try:
            from PyQt6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
            from OpenGL.GLU import gluPerspective, gluLookAt

            self.makeCurrent()

            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setAttachment(QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
            fbo = QOpenGLFramebufferObject(size, size, fmt)
            if not fbo.isValid() or not fbo.bind():
                self.doneCurrent()
                return None

            glViewport(0, 0, size, size)
            glClearColor(0.12, 0.12, 0.20, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

            # Match render_batched_models exactly — XBG models use CW winding
            glFrontFace(GL_CW)
            glDisable(GL_CULL_FACE)
            glEnable(GL_DEPTH_TEST)
            glDepthFunc(GL_LEQUAL)
            glDepthMask(GL_TRUE)

            glEnable(GL_LIGHTING)
            glEnable(GL_LIGHT0)
            glEnable(GL_LIGHT1)
            glDisable(GL_LIGHT2)
            glEnable(GL_COLOR_MATERIAL)
            glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
            glEnable(GL_NORMALIZE)
            glLightModeli(GL_LIGHT_MODEL_LOCAL_VIEWER, GL_TRUE)
            glLightfv(GL_LIGHT0, GL_POSITION, self._key_light_pos())
            glLightfv(GL_LIGHT0, GL_DIFFUSE,  [0.90, 0.88, 0.82, 1.0])
            glLightfv(GL_LIGHT0, GL_SPECULAR, [0.50, 0.48, 0.44, 1.0])
            glLightfv(GL_LIGHT0, GL_AMBIENT,  [0.00, 0.00, 0.00, 1.0])
            glLightfv(GL_LIGHT1, GL_POSITION, [0.0, 1.0, 0.0, 0.0])
            glLightfv(GL_LIGHT1, GL_DIFFUSE,  [0.30, 0.33, 0.42, 1.0])
            glLightfv(GL_LIGHT1, GL_SPECULAR, [0.00, 0.00, 0.00, 1.0])
            glLightfv(GL_LIGHT1, GL_AMBIENT,  [0.00, 0.00, 0.00, 1.0])
            glLightModelfv(GL_LIGHT_MODEL_AMBIENT, [0.38, 0.38, 0.42, 1.0])
            glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR, [0.15, 0.15, 0.15, 1.0])
            glMaterialf(GL_FRONT_AND_BACK, GL_SHININESS, 40.0)
            glColor3f(1.0, 1.0, 1.0)

            bmin, bmax = model.get_bounds() if hasattr(model, 'get_bounds') else (None, None)
            if bmin and bmax:
                cx = (bmin[0] + bmax[0]) / 2.0
                cy = (bmin[1] + bmax[1]) / 2.0
                cz = (bmin[2] + bmax[2]) / 2.0
                span = max(bmax[0]-bmin[0], bmax[1]-bmin[1], bmax[2]-bmin[2], 0.1)
            else:
                cx = cy = cz = 0.0
                span = 2.0

            cam_dist = span * distance_mult
            _az = math.radians(azimuth)
            _el = math.radians(elevation)
            eye_x = cx + cam_dist * math.cos(_el) * math.sin(_az)
            eye_y = cy + cam_dist * math.sin(_el)
            eye_z = cz + cam_dist * math.cos(_el) * math.cos(_az)
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            gluPerspective(45.0, 1.0, max(cam_dist * 0.01, 0.01), cam_dist * 20.0)
            glMatrixMode(GL_MODELVIEW)
            glLoadIdentity()
            gluLookAt(eye_x, eye_y, eye_z, cx, cy, cz, 0, 1, 0)

            if getattr(model, 'display_list', None):
                glCallList(model.display_list)
            elif hasattr(self, 'model_loader'):
                self.model_loader._render_immediate_mode(model)

            glDisable(GL_ALPHA_TEST)

            raw = fbo.toImage()
            fbo.release()
            self.doneCurrent()

            # Rotate 90° clockwise then mirror vertically
            from PyQt6.QtGui import QTransform as _QT
            raw = raw.transformed(_QT().rotate(90))
            raw = raw.mirrored(True, False)
            return raw

        except Exception as _e:
            print(f"render_model_thumbnail error: {_e}")
            try:
                self.doneCurrent()
            except Exception:
                pass
            return None

    def world_to_screen(self, world_x, world_y):
        """Convert world coordinates to screen (2D mode)"""
        return OpenGLUtils.world_to_screen(world_x, world_y, self)

    def screen_to_world(self, screen_x, screen_y):
        """Convert screen coordinates to world (2D mode)"""
        return OpenGLUtils.screen_to_world(screen_x, screen_y, self)
    
    def set_grid_config(self, grid_config):
        """Set grid configuration"""
        self.grid_config = grid_config
        self.update()
    
    def set_current_map(self, map_info):
        """Set current map"""
        self.current_map = map_info
        self.entities_modified = True
        self.update()
        
    def zoom_to_entity(self, entity):
        """Zoom to entity"""
        if not entity:
            return
        
        self.camera_controller.zoom_to_entity_2d(entity, self)
    
    def reset_view(self):
        """Reset view"""
        if not self.entities:
            self.camera_controller.offset_x = self.width() / 2
            self.camera_controller.offset_y = self.height() / 2
            self.offset_x = self.camera_controller.offset_x
            self.offset_y = self.camera_controller.offset_y
            self.scale_factor = 1.0
            
            self.update()
            return self.scale_factor
        
        self._center_view_on_entities()
        self.update()
        return self.scale_factor
    
    def zoom_in(self):
        """Zoom in"""
        self.camera_controller.zoom_in(self)

    def zoom_out(self):
        """Zoom out"""
        self.camera_controller.zoom_out(self)
    
    def invalidate_entity_caches(self):
        """Invalidate all entity caches"""
        self.entity_cache_dirty = True
        self.last_3d_camera_pos = None
        self.last_3d_camera_angles = None
        
        if hasattr(self, 'entity_renderer'):
            self.entity_renderer.invalidate_all_entity_caches()
        
        self.entities_modified = True
        self.selection_modified = True
        
    
    def update_entity_xml(self, entity):
        """Update entity XML coordinates"""
        self.entities_modified = True

        if not entity:
            return False

        source_file_path = getattr(entity, 'source_file_path', None)
        source_file = getattr(entity, 'source_file', None)

        if source_file_path:
            if source_file_path.endswith('.data.xml') or source_file_path.endswith('.converted.xml'):
                return self._update_worldsector_xml_fcb_format(entity, source_file_path)
            elif source_file in ('omnis', 'managers'):
                return self._update_entity_fcb_in_place(entity)
        else:
            return self._update_memory_xml_dunia_format(entity)

        return False
    
    def _update_worldsector_xml_fcb_format(self, entity, xml_file_path):
        """Update WorldSector XML (FCB format)"""
        try:
            main_window = self
            while main_window.parent():
                main_window = main_window.parent()
            
            if not hasattr(main_window, 'worldsectors_trees'):
                main_window.worldsectors_trees = {}
            
            if xml_file_path not in main_window.worldsectors_trees:
                import xml.etree.ElementTree as ET
                tree = ET.parse(xml_file_path)
                main_window.worldsectors_trees[xml_file_path] = tree
            
            tree = main_window.worldsectors_trees[xml_file_path]
            root = tree.getroot()
            
            for entity_elem in root.findall(".//object[@name='Entity']"):
                name_field = entity_elem.find("./field[@name='hidName']")
                if name_field is not None:
                    name_value = name_field.get('value-String')
                    if name_value == getattr(entity, 'name', ''):
                        # If entity.xml_element has been structurally modified (e.g.
                        # children added/removed via the entity editor) and is a
                        # different object from entity_elem in the cached tree, copy
                        # the modified content into entity_elem so those changes are
                        # preserved when the tree is written to disk.
                        existing = getattr(entity, 'xml_element', None)
                        if existing is not None and existing is not entity_elem:
                            _saved_tail = entity_elem.tail   # clear() also nukes tail whitespace
                            entity_elem.clear()
                            entity_elem.tail = _saved_tail   # restore so sibling spacing is intact
                            entity_elem.attrib.update(existing.attrib)
                            entity_elem.text = existing.text
                            for child in list(existing):
                                entity_elem.append(child)

                        # Subtract any FC2 cell offset that was applied at load time
                        # so we write back the original local (cell-space) coordinates.
                        editor = getattr(self, 'editor', None)
                        cell_off_x = getattr(editor, 'fc2_cell_offset_x', 0.0)
                        cell_off_y = getattr(editor, 'fc2_cell_offset_y', 0.0)
                        save_x = entity.x - cell_off_x
                        save_y = entity.y - cell_off_y
                        self._update_fcb_position_field(entity_elem, "hidPos", save_x, save_y, entity.z)
                        self._update_fcb_position_field(entity_elem, "hidPos_precise", save_x, save_y, entity.z)

                        entity.xml_element = entity_elem
                        return True
            
            return False
            
        except Exception as e:
            print(f"Error updating FCB XML: {e}")
            return False

    def _update_fcb_position_field(self, entity_elem, field_name, x, y, z):
        """Update position field (FCB format)"""
        pos_field = entity_elem.find(f"./field[@name='{field_name}']")
        if pos_field is not None:
            new_pos_value = f"{x:.0f},{y:.0f},{z:.0f}"
            pos_field.set('value-Vector3', new_pos_value)
            
            binary_hex = self._coordinates_to_binhex(x, y, z)
            pos_field.text = binary_hex

    def _coordinates_to_binhex(self, x, y, z):
        """Convert coordinates to BinHex"""
        import struct
        binary_data = struct.pack('<fff', float(x), float(y), float(z))
        hex_string = binary_data.hex().upper()
        return hex_string

    def _update_memory_xml_dunia_format(self, entity):
        """Update main file entity (Dunia format) - preserves decimal precision, updates position AND rotation"""
        if not hasattr(entity, 'xml_element') or entity.xml_element is None:
            return False
        
        try:
            # UPDATE POSITION
            pos_elem = entity.xml_element.find("./value[@name='hidPos']")
            if pos_elem is not None:
                x_elem = pos_elem.find("./x")
                y_elem = pos_elem.find("./y")
                z_elem = pos_elem.find("./z")
                
                if x_elem is not None:
                    # Format with decimals if value has decimals, otherwise as integer
                    x_elem.text = f"{entity.x:.2f}" if entity.x % 1 != 0 else str(int(entity.x))
                if y_elem is not None:
                    y_elem.text = f"{entity.y:.2f}" if entity.y % 1 != 0 else str(int(entity.y))
                if z_elem is not None:
                    z_elem.text = f"{entity.z:.2f}" if entity.z % 1 != 0 else str(int(entity.z))
            
            pos_precise_elem = entity.xml_element.find("./value[@name='hidPos_precise']")
            if pos_precise_elem is not None:
                x_elem = pos_precise_elem.find("./x")
                y_elem = pos_precise_elem.find("./y")
                z_elem = pos_precise_elem.find("./z")
                
                if x_elem is not None:
                    x_elem.text = f"{entity.x:.2f}" if entity.x % 1 != 0 else str(int(entity.x))
                if y_elem is not None:
                    y_elem.text = f"{entity.y:.2f}" if entity.y % 1 != 0 else str(int(entity.y))
                if z_elem is not None:
                    z_elem.text = f"{entity.z:.2f}" if entity.z % 1 != 0 else str(int(entity.z))

            # FCB/mapsdata field format fallback: <field name="hidPos" value-Vector3="x,y,z">BinHex</field>
            if pos_elem is None:
                for fname in ('hidPos', 'hidPos_precise'):
                    fld = entity.xml_element.find(f"./field[@name='{fname}']")
                    if fld is not None:
                        fld.set('value-Vector3', f"{entity.x},{entity.y},{entity.z}")
                        fld.text = self._coordinates_to_binhex(entity.x, entity.y, entity.z)

            # UPDATE ROTATION (hidAngles) - CRITICAL FIX FOR MAPSDATA ENTITIES
            # Get current rotation from gizmo renderer
            current_rotation = 0.0
            if hasattr(self, 'gizmo_renderer') and self.gizmo_renderer.rotation_gizmo:
                current_rotation = self.gizmo_renderer.rotation_gizmo.extract_entity_rotation(entity)
            
            # Convert editor rotation to game rotation
            game_rotation = (360 - current_rotation) % 360
            
            # Update hidAngles in Dunia format (value/x/y/z structure)
            angles_elem = entity.xml_element.find("./value[@name='hidAngles']")
            if angles_elem is not None:
                # Get existing X and Y rotations (preserve them)
                x_elem = angles_elem.find("./x")
                y_elem = angles_elem.find("./y")
                z_elem = angles_elem.find("./z")
                
                # Only update Z rotation, preserve X and Y
                if z_elem is not None:
                    z_elem.text = f"{game_rotation:.2f}" if game_rotation % 1 != 0 else str(int(game_rotation))

            # FCB/mapsdata field format fallback for rotation: preserve X/Y, update Z only
            if angles_elem is None:
                angles_field = entity.xml_element.find("./field[@name='hidAngles']")
                if angles_field is not None:
                    old_vec = angles_field.get('value-Vector3', '0,0,0')
                    parts = old_vec.split(',')
                    ax = float(parts[0]) if len(parts) > 0 else 0.0
                    ay = float(parts[1]) if len(parts) > 1 else 0.0
                    angles_field.set('value-Vector3', f"{ax},{ay},{game_rotation}")
                    angles_field.text = self._coordinates_to_binhex(ax, ay, game_rotation)

            return True
            
        except Exception as e:
            print(f"Error updating Dunia XML: {e}")
            import traceback
            traceback.print_exc()
        return False
        
    def invalidate_position_cache(self):
        """Call after moving any entity to ensure the frustum culler uses fresh positions.

        The _positions_3d array is rebuilt from entity coordinates at load time and cached.
        If an entity moves, we need to rebuild it. This is cheap - just clears the cache key
        so _get_map_filtered_entities rebuilds on the next frame.
        """
        self._map_filter_cache_key = None
        self._interior_aabb_cache_key = None

    def patch_preview_positions(self, updates: dict):
        """
        Directly patch cached position arrays for a small set of preview entities.
        Much faster than invalidate_position_cache() which rebuilds all ~1600 entries.

        updates: dict[entity_id_str -> (x, y, z)]
        """
        # 3D arrays — world(x,y,z) → gl(x, z, -y)
        valid_3d = getattr(self, '_valid_entities_3d', None)
        pos_3d   = getattr(self, '_positions_3d', None)
        if valid_3d is not None and pos_3d is not None and len(pos_3d) == len(valid_3d):
            for i, ent in enumerate(valid_3d):
                if ent.id in updates:
                    x, y, z = updates[ent.id]
                    pos_3d[i, 0] =  x
                    pos_3d[i, 1] =  z
                    pos_3d[i, 2] = -y
            # _positions_centered_3d is a view/copy of _positions_3d used by the
            # frustum culler — keep it in sync so culling uses the new positions.
            self._positions_centered_3d = pos_3d

        # 2D arrays — world(x, y)
        valid_2d = getattr(self, '_valid_entities_2d', None)
        pos_2d   = getattr(self, '_positions_2d', None)
        if valid_2d is not None and pos_2d is not None and len(pos_2d) == len(valid_2d):
            for i, ent in enumerate(valid_2d):
                if ent.id in updates:
                    x, y, _ = updates[ent.id]
                    pos_2d[i, 0] = x
                    pos_2d[i, 1] = y

    def mark_entity_modified(self, entity):
        """Mark entity as modified"""
        if not entity:
            return

        if hasattr(self, 'entity_renderer'):
            self.entity_renderer.invalidate_entity_cache(entity)

        # Clear cached rotation/scale so prepare_batches re-reads from XML next frame
        if hasattr(self, 'model_loader') and self.model_loader is not None:
            self.model_loader._entity_rs_cache.pop(id(entity), None)
            # Array-native GDR rows cache rotation/scale too — refresh this
            # entity's rows now (re-parses RS since the cache was just popped).
            # Position-only moves are covered by invalidate_position_cache, but
            # rotation/scale edits don't bump the position-array version.
            try:
                self.model_loader.gdr_refresh_entity(entity)
            except Exception:
                pass

        # Force interior AABB cache rebuild (entity's bounds may have shifted)
        self._interior_aabb_cache_key = None

        # Invalidate the cached 3D overlay buffer — rotation/scale edits change
        # wireframe orientation without bumping the position-array version.
        self._ov_cache_key = None

        self.invalidate_entity_caches()

        # Only mark dirty sectors on settled moves (not during drag — would dirty every
        # transient sector the entity passes through).
        if self.unified_mode and not getattr(self.input_handler, 'dragging', False):
            self.mark_sector_dirty(entity)

    def mark_sector_dirty(self, entity):
        """Mark the sector(s) affected by this entity as needing reconversion on save."""
        if not entity:
            return
        gx = int(entity.x // 64)
        gy = int(entity.y // 64)
        new_sector_id = gy * 16 + gx
        source_id = getattr(entity, 'source_sector_id', -1)
        # Always dirty the old source sector (it must be rebuilt to remove/update the entity)
        if source_id >= 0:
            self.dirty_sectors.add(source_id)
        # If the entity genuinely moved to a different sector, dirty the new sector too
        # and update source_sector_id so save groups it into the correct file.
        if new_sector_id != source_id:
            self.dirty_sectors.add(new_sector_id)
            entity.source_sector_id = new_sector_id

    def mark_entities_modified(self):
        """Mark entities as modified"""
        self.entities_modified = True
        if self.parent():
            if hasattr(self.parent(), 'entities_modified'):
                self.parent().entities_modified = True
    
    def draw_sector_boundaries(self, painter):
        """Draw sector boundaries (2D only).

        Worldsector boxes: full green outline.
        Landmark boxes: full purple outline, inset 3px so both are visible
        when they share the same grid position.
        """
        if not getattr(self, 'show_sector_boundaries', False):
            return

        if not hasattr(self, 'sector_data') or not self.sector_data:
            print("No sector_data, creating fallback...")
            self.create_fallback_sector_data()
            if not self.sector_data:
                return

        try:
            from PyQt6.QtGui import QPen, QBrush, QColor, QFont
            from PyQt6.QtCore import Qt
            from collections import defaultdict

            original_pen = painter.pen()
            original_brush = painter.brush()
            original_font = painter.font()

            # ── Group entries by grid position ─────────────────────────────────
            position_groups = defaultdict(lambda: {'sector': None, 'landmark_far': None, 'landmark_near': None})
            for info in self.sector_data:
                gx = info.get('x', 0)
                gy = info.get('y', 0)
                if info.get('is_landmark', False):
                    fname = os.path.basename(info.get('file_path', '')).lower()
                    if 'landmarkfar' in fname:
                        position_groups[(gx, gy)]['landmark_far'] = info
                    else:
                        position_groups[(gx, gy)]['landmark_near'] = info
                else:
                    position_groups[(gx, gy)]['sector'] = info

            # Scale font with the canvas zoom so labels grow/shrink with the boxes.
            _font_px = max(4, min(16, round(6 * self.scale_factor)))
            _lbl_font = QFont("Arial")
            _lbl_font.setPixelSize(_font_px)
            _lbl_font.setWeight(QFont.Weight.Bold)
            painter.setFont(_lbl_font)
            bg_padding = 2
            boundaries_drawn = 0

            for (grid_x, grid_y), group in position_groups.items():
                try:
                    sector_info   = group['sector']
                    landmark_far  = group['landmark_far']
                    landmark_near = group['landmark_near']
                    landmark_ref  = landmark_far if landmark_far is not None else landmark_near
                    ref_info      = sector_info if sector_info is not None else landmark_ref

                    sector_size = ref_info.get('size', 64)
                    world_min_x = grid_x * sector_size
                    world_min_y = grid_y * sector_size
                    world_max_x = world_min_x + sector_size
                    world_max_y = world_min_y + sector_size

                    screen_tl = self.world_to_screen(world_min_x, world_max_y)
                    screen_br = self.world_to_screen(world_max_x, world_min_y)

                    rect_x = screen_tl[0]
                    rect_y = screen_tl[1]
                    rect_w = screen_br[0] - screen_tl[0]
                    rect_h = screen_br[1] - screen_tl[1]

                    if abs(rect_w) < 2 or abs(rect_h) < 2:
                        continue
                    if rect_w < 0:
                        rect_x += rect_w
                        rect_w = abs(rect_w)
                    if rect_h < 0:
                        rect_y += rect_h
                        rect_h = abs(rect_h)

                    margin = 50
                    if (rect_x > self.width() + margin or
                            rect_y > self.height() + margin or
                            rect_x + rect_w < -margin or
                            rect_y + rect_h < -margin):
                        continue

                    metrics = painter.fontMetrics()
                    rx, ry = int(rect_x), int(rect_y)
                    rw, rh = int(rect_w), int(rect_h)

                    # ── Draw worldsector box (green) ───────────────────────────
                    if sector_info:
                        painter.setBrush(QBrush(QColor(0, 200, 0, 10)))
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.drawRect(rx, ry, rw, rh)
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.setPen(QPen(QColor(0, 200, 0, 220), 2))
                        painter.drawRect(rx, ry, rw, rh)

                        # Sector label: top-left
                        s_text = f"Sector {sector_info.get('id', '?')}"
                        s_tr   = metrics.boundingRect(s_text)
                        s_lx   = rx + 3
                        s_ly   = ry + 15
                        painter.fillRect(s_lx - bg_padding, s_ly - s_tr.height() - bg_padding,
                                         s_tr.width() + bg_padding * 2, s_tr.height() + bg_padding * 2,
                                         QColor(0, 0, 0, 200))
                        painter.setPen(QPen(QColor(100, 255, 100), 2))
                        painter.drawText(s_lx, s_ly, s_text)

                        boundaries_drawn += 1

                    # ── Draw landmark box (purple) ─────────────────────────────
                    if landmark_ref:
                        painter.setBrush(QBrush(QColor(150, 0, 255, 8)))
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.drawRect(rx, ry, rw, rh)
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.setPen(QPen(QColor(150, 0, 255, 220), 2))
                        painter.drawRect(rx, ry, rw, rh)

                        # Compact label: "LMN & LMF [N]", "LMF [N]", or "LMN [N]"
                        sector_n = landmark_ref.get('id', '?')
                        if landmark_far and landmark_near:
                            lm_text = f"LMN & LMF [{sector_n}]"
                        elif landmark_far:
                            lm_text = f"LMF [{sector_n}]"
                        else:
                            lm_text = f"LMN [{sector_n}]"

                        lm_tr = metrics.boundingRect(lm_text)
                        lm_lx = rx + 3
                        lm_ly = ry + rh - 5
                        painter.fillRect(lm_lx - bg_padding, lm_ly - lm_tr.height() - bg_padding,
                                         lm_tr.width() + bg_padding * 2, lm_tr.height() + bg_padding * 2,
                                         QColor(0, 0, 0, 200))
                        painter.setPen(QPen(QColor(220, 180, 255), 2))
                        painter.drawText(lm_lx, lm_ly, lm_text)

                        boundaries_drawn += 1

                except Exception as group_error:
                    print(f"Error drawing sector group ({grid_x},{grid_y}): {group_error}")
                    continue

            # ── Draw omnis sector boxes (orange, inset 6px) ───────────────
            omnis_entities = [e for e in getattr(self, 'entities', [])
                              if getattr(e, 'source_file', '') == 'omnis']
            if omnis_entities:
                # Group by grid cell — one box per occupied cell
                omnis_cells = {}
                for ent in omnis_entities:
                    gx = int(ent.x // 64)
                    gy = int(ent.y // 64)
                    cell = (gx, gy)
                    if cell not in omnis_cells:
                        omnis_cells[cell] = []
                    omnis_cells[cell].append(ent)

                painter.setFont(_lbl_font)
                metrics = painter.fontMetrics()

                for (gx, gy), cell_ents in omnis_cells.items():
                    world_min_x = gx * 64
                    world_min_y = gy * 64
                    world_max_x = world_min_x + 64
                    world_max_y = world_min_y + 64

                    screen_tl = self.world_to_screen(world_min_x, world_max_y)
                    screen_br = self.world_to_screen(world_max_x, world_min_y)
                    rx = int(screen_tl[0])
                    ry = int(screen_tl[1])
                    rw = int(screen_br[0] - screen_tl[0])
                    rh = int(screen_br[1] - screen_tl[1])

                    if abs(rw) < 2 or abs(rh) < 2:
                        continue
                    if rw < 0:
                        rx += rw; rw = abs(rw)
                    if rh < 0:
                        ry += rh; rh = abs(rh)

                    margin = 50
                    if (rx > self.width() + margin or ry > self.height() + margin or
                            rx + rw < -margin or ry + rh < -margin):
                        continue

                    painter.setBrush(QBrush(QColor(255, 140, 0, 8)))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawRect(rx, ry, rw, rh)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(QColor(255, 140, 0, 220), 2))
                    painter.drawRect(rx, ry, rw, rh)

                    # "Omnis (N)" label at top-right
                    o_text = "Omnis"
                    o_tr = metrics.boundingRect(o_text)
                    o_lx = rx + rw - o_tr.width() - 8
                    o_ly = ry + 15
                    painter.fillRect(o_lx - bg_padding, o_ly - o_tr.height() - bg_padding,
                                     o_tr.width() + bg_padding * 2, o_tr.height() + bg_padding * 2,
                                     QColor(0, 0, 0, 200))
                    painter.setPen(QPen(QColor(255, 180, 80), 2))
                    painter.drawText(o_lx, o_ly, o_text)

                    boundaries_drawn += 1

            painter.setPen(original_pen)
            painter.setBrush(original_brush)
            painter.setFont(original_font)

            print(f"Drew {boundaries_drawn} sector boundary groups")

        except Exception as e:
            print(f"Error in draw_sector_boundaries: {e}")
            import traceback
            traceback.print_exc()

    def create_fallback_sector_data(self):
        """Create fallback sector data"""
        print("Creating fallback sector data...")
        
        if not hasattr(self, 'entities') or not self.entities:
            self.sector_data = []
            return
        
        sector_map = {}
        
        for entity in self.entities:
            if not (hasattr(entity, 'x') and hasattr(entity, 'y')):
                continue
                
            sector_x = int(entity.x // 64)
            sector_y = int(entity.y // 64)
            sector_key = (sector_x, sector_y)
            
            if sector_key not in sector_map:
                sector_map[sector_key] = {
                    'id': len(sector_map) + 1,
                    'x': sector_x,
                    'y': sector_y,
                    'size': 64,
                    'entities': [],
                    'expected_ids': []
                }
            
            sector_map[sector_key]['entities'].append(entity)
            
            entity_id = getattr(entity, 'id', id(entity))
            if entity_id not in sector_map[sector_key]['expected_ids']:
                sector_map[sector_key]['expected_ids'].append(entity_id)
        
        self.sector_data = list(sector_map.values())
        
        print(f"Created fallback sector data: {len(self.sector_data)} sectors")