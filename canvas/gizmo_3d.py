"""3D transform gizmo — translate (X/Y/Z) and rotate (X/Y/Z) in 3D mode."""

import math
import struct

from OpenGL.GL import *
from OpenGL.GLU import *

# ---------------------------------------------------------------------------
# Handle constants
# ---------------------------------------------------------------------------

HANDLE_NONE     = -1
HANDLE_TRANS_X  =  0   # World X  (red)
HANDLE_TRANS_Z  =  1   # World Z / height  (blue, GL +Y)
HANDLE_TRANS_Y  =  2   # World Y  (green, GL -Z)
HANDLE_ROT_X    =  3   # Rotate around world X
HANDLE_ROT_Z    =  4   # Rotate around world Z / height (= 2-D gizmo Z rotation)
HANDLE_ROT_Y    =  5   # Rotate around world Y
HANDLE_TRANS_XY =  6   # Free XY plane move (purple centre cube)

_TRANS_HANDLES = (HANDLE_TRANS_X, HANDLE_TRANS_Z, HANDLE_TRANS_Y, HANDLE_TRANS_XY)
_ROT_HANDLES   = (HANDLE_ROT_X,   HANDLE_ROT_Z,   HANDLE_ROT_Y)


# GL axis direction (gx, gy, gz) for each handle
_GL_AXIS = {
    HANDLE_TRANS_X: ( 1.0,  0.0,  0.0),
    HANDLE_TRANS_Z: ( 0.0,  1.0,  0.0),
    HANDLE_TRANS_Y: ( 0.0,  0.0, -1.0),
    HANDLE_ROT_X:   ( 1.0,  0.0,  0.0),
    HANDLE_ROT_Z:   ( 0.0,  1.0,  0.0),
    HANDLE_ROT_Y:   ( 0.0,  0.0,  1.0),  # ring normal for world-Y rotation
}

# Base RGB colours per handle
_COLOR = {
    HANDLE_TRANS_X:  (1.00, 0.25, 0.25),
    HANDLE_TRANS_Z:  (0.35, 0.60, 1.00),
    HANDLE_TRANS_Y:  (0.25, 1.00, 0.25),
    HANDLE_ROT_X:    (1.00, 0.35, 0.35),
    HANDLE_ROT_Z:    (0.45, 0.65, 1.00),
    HANDLE_ROT_Y:    (0.35, 1.00, 0.35),
    HANDLE_TRANS_XY: (0.75, 0.20, 0.90),   # purple
}
_HIGHLIGHT = (1.0, 1.0, 0.0)   # yellow when active / hovered

_RING_SEGS       = 36
_CONE_SEGS       =  8
_PROJ_RING_SAMPS = 24


# ---------------------------------------------------------------------------
# Gizmo3D
# ---------------------------------------------------------------------------

class Gizmo3D:
    """3-D transform gizmo (translate + rotate) for the OpenGL 3-D view."""

    def __init__(self):
        self.hidden  = True
        self.entity  = None
        self.position = (0.0, 0.0, 0.0)   # world (x, y, z)

        self.active_handle  = HANDLE_NONE
        self.hovered_handle = HANDLE_NONE

        # Per-drag bookkeeping
        self._drag_start_screen       = (0, 0)
        self._drag_start_center_screen = (0.0, 0.0)
        self._drag_start_init_gl      = (0.0, 0.0, 0.0)  # GL pos at drag start
        self._drag_start_pos          = (0.0, 0.0, 0.0)  # entity world pos
        self._drag_start_pos_all      = []               # [(entity, x, y, z)]
        self._drag_start_angles       = (0.0, 0.0, 0.0)  # hidAngles at drag start

        # Undo snapshots
        self._undo_before_pos    = None
        self._undo_before_angles = None

        # Screen projections updated each render
        self._proj_center  = (0.0, 0.0)
        self._proj_handles = {}    # handle → [(sx, sy), ...]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def move_to(self, entity):
        self.entity = entity
        if entity:
            self.position = (entity.x, entity.y, entity.z)
            self.hidden = False
        else:
            self.hidden = True
            self.active_handle = HANDLE_NONE

    def sync_position(self):
        """Sync gizmo position from entity after external move."""
        if self.entity:
            self.position = (self.entity.x, self.entity.y, self.entity.z)

    def gl_pos(self):
        """World (x, y, z) → OpenGL (gx, gy, gz)."""
        x, y, z = self.position
        return (x, z, -y)

    def reproject_for_hit(self, canvas):
        """Rebuild _proj_handles using render-time matrices. Must be called before hit_test."""
        if self.hidden or self.entity is None:
            return
        try:
            canvas.makeCurrent()
            w, h = canvas.width(), max(canvas.height(), 1)
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            gluPerspective(50, w / h, 0.1, 10000.0)
            glMatrixMode(GL_MODELVIEW)
            glLoadIdentity()
            cam = canvas.camera_3d
            gluLookAt(cam.position[0], cam.position[1], cam.position[2],
                      *cam.get_look_at(), 0, 1, 0)
            viewport   = glGetIntegerv(GL_VIEWPORT)
            modelview  = glGetDoublev(GL_MODELVIEW_MATRIX)
            projection = glGetDoublev(GL_PROJECTION_MATRIX)
        except Exception as exc:
            print(f"[Gizmo3D] reproject_for_hit failed: {exc}")
            return
        gx, gy, gz = self.gl_pos()
        scale = 5.0
        self._update_projections(gx, gy, gz, scale, scale * 0.65,
                                  viewport, modelview, projection)

    def hit_test(self, mouse_x, mouse_y):
        """Return the nearest handle within threshold, or HANDLE_NONE."""
        best = HANDLE_NONE
        best_d = 40.0   # pixel threshold

        for handle, pts in self._proj_handles.items():
            for sx, sy in pts:
                d = math.hypot(mouse_x - sx, mouse_y - sy)
                if d < best_d:
                    best_d = d
                    best = handle

        return best

    def start_drag(self, handle, mouse_x, mouse_y, entity, canvas):
        """Begin a drag on the given handle. Call after hit_test succeeds."""
        self.active_handle            = handle
        self._drag_start_screen       = (mouse_x, mouse_y)
        self._drag_start_center_screen = self._proj_center
        self._drag_start_pos          = (entity.x, entity.y, entity.z)
        self._drag_start_init_gl      = self.gl_pos()
        self._drag_start_angles       = self._read_angles(entity)

        # Snapshot all selected entities for multi-entity translation
        selected = list(getattr(canvas, 'selected', None) or [])
        if not selected:
            selected = [entity]
        self._drag_start_pos_all = [(e, e.x, e.y, e.z) for e in selected]

        from .undo_redo import UndoRedoManager
        self._undo_before_pos    = [(e, x, y, z) for e, x, y, z in self._drag_start_pos_all]
        self._undo_before_angles = list(self._drag_start_angles)
        return True

    def update_drag(self, mouse_x, mouse_y, entity, canvas):
        """Call every mouse-move while a drag is active."""
        if self.active_handle == HANDLE_NONE:
            return

        canvas.makeCurrent()
        try:
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            gluPerspective(50, canvas.width() / max(canvas.height(), 1), 0.1, 10000.0)

            glMatrixMode(GL_MODELVIEW)
            glLoadIdentity()
            cam = canvas.camera_3d
            gluLookAt(cam.position[0], cam.position[1], cam.position[2],
                      *cam.get_look_at(), 0, 1, 0)

            viewport   = glGetIntegerv(GL_VIEWPORT)
            modelview  = glGetDoublev(GL_MODELVIEW_MATRIX)
            projection = glGetDoublev(GL_PROJECTION_MATRIX)
        except Exception as exc:
            print(f"[Gizmo3D] GL setup failed in update_drag: {exc}")
            return

        if self.active_handle in _TRANS_HANDLES:
            self._drag_translate(mouse_x, mouse_y, entity, canvas,
                                 viewport, modelview, projection)
        else:
            self._drag_rotate(mouse_x, mouse_y, entity, canvas)

        canvas.update()

    def end_drag(self, entity, canvas):
        """Finish drag; push undo command."""
        if self.active_handle == HANDLE_NONE:
            return

        h = self.active_handle
        self.active_handle = HANDLE_NONE

        if h in _TRANS_HANDLES:
            if hasattr(canvas, 'undo_redo') and self._undo_before_pos:
                from .undo_redo import MoveCommand
                after = [(e, e.x, e.y, e.z) for e, *_ in self._undo_before_pos]
                canvas.undo_redo.push(MoveCommand(self._undo_before_pos, after))
        else:
            if hasattr(canvas, 'undo_redo') and self._undo_before_angles is not None:
                from .undo_redo import Rotate3DCommand
                cur = self._read_angles(entity)
                before = [(entity,) + tuple(self._undo_before_angles)]
                after  = [(entity,) + tuple(cur)]
                canvas.undo_redo.push(Rotate3DCommand(before, after))

        self._undo_before_pos    = None
        self._undo_before_angles = None
        self._drag_start_pos_all = []

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, canvas):
        """Draw the gizmo. Must be called from within an active GL context."""
        if self.hidden or self.entity is None:
            return

        cam = canvas.camera_3d
        gx, gy, gz = self.gl_pos()

        scale = 5.0

        arrow_len   = scale
        arrow_head  = scale * 0.20
        ring_radius = scale * 0.65

        try:
            viewport   = glGetIntegerv(GL_VIEWPORT)
            modelview  = glGetDoublev(GL_MODELVIEW_MATRIX)
            projection = glGetDoublev(GL_PROJECTION_MATRIX)
        except Exception:
            return

        glPushAttrib(GL_ALL_ATTRIB_BITS)
        try:
            glDisable(GL_DEPTH_TEST)
            glDisable(GL_LIGHTING)
            glDisable(GL_CULL_FACE)
            glEnable(GL_LINE_SMOOTH)
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

            glPushMatrix()
            glTranslatef(gx, gy, gz)

            # --- Translation arrows ---
            for h, gl_dir in [
                (HANDLE_TRANS_X, ( 1.0,  0.0,  0.0)),
                (HANDLE_TRANS_Z, ( 0.0,  1.0,  0.0)),
                (HANDLE_TRANS_Y, ( 0.0,  0.0, -1.0)),
            ]:
                col = _HIGHLIGHT if (h == self.active_handle or h == self.hovered_handle) else _COLOR[h]
                self._draw_arrow(gl_dir, col, arrow_len, arrow_head)

            # --- Rotation rings ---
            for h, ring_axis in [
                (HANDLE_ROT_X, (1.0, 0.0, 0.0)),
                (HANDLE_ROT_Z, (0.0, 1.0, 0.0)),
                (HANDLE_ROT_Y, (0.0, 0.0, 1.0)),
            ]:
                col = _HIGHLIGHT if (h == self.active_handle or h == self.hovered_handle) else _COLOR[h]
                self._draw_ring(ring_axis, col, ring_radius)

            # --- Centre cube (free XY move) ---
            cube_col = _HIGHLIGHT if (self.active_handle == HANDLE_TRANS_XY or
                                       self.hovered_handle == HANDLE_TRANS_XY) else _COLOR[HANDLE_TRANS_XY]
            self._draw_center_cube(cube_col, scale * 0.12)

            glPopMatrix()
        finally:
            glPopAttrib()

        self._update_projections(gx, gy, gz, arrow_len, ring_radius,
                                  viewport, modelview, projection)

    # ------------------------------------------------------------------
    # Primitive drawing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _perp(axis):
        """Two unit vectors perpendicular to *axis*."""
        ax, ay, az = float(axis[0]), float(axis[1]), float(axis[2])
        # Pick the cardinal axis least aligned with input (guarantees non-parallel)
        if abs(ax) <= abs(ay) and abs(ax) <= abs(az):
            ref = (1.0, 0.0, 0.0)
        elif abs(ay) <= abs(az):
            ref = (0.0, 1.0, 0.0)
        else:
            ref = (0.0, 0.0, 1.0)
        rx, ry, rz = ref
        # p1 = axis × ref
        p1x = ay*rz - az*ry
        p1y = az*rx - ax*rz
        p1z = ax*ry - ay*rx
        n = math.sqrt(p1x**2 + p1y**2 + p1z**2)
        if n < 1e-9:
            return (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
        p1 = (p1x/n, p1y/n, p1z/n)
        # p2 = p1 × axis
        p2x = p1[1]*az - p1[2]*ay
        p2y = p1[2]*ax - p1[0]*az
        p2z = p1[0]*ay - p1[1]*ax
        n2  = math.sqrt(p2x**2 + p2y**2 + p2z**2)
        if n2 < 1e-9:
            return p1, (0.0, 0.0, 1.0)
        return p1, (p2x/n2, p2y/n2, p2z/n2)

    def _draw_arrow(self, direction, color, length, head_size):
        dx, dy, dz = direction
        tx, ty, tz = dx*length, dy*length, dz*length
        # positive cone base
        bx  = dx*(length - head_size)
        by  = dy*(length - head_size)
        bz  = dz*(length - head_size)
        # negative tip and cone base
        ntx, nty, ntz = -tx, -ty, -tz
        nbx = -bx; nby = -by; nbz = -bz

        glColor3f(*color)
        glLineWidth(6.0)

        # Shaft spans both directions from origin
        glBegin(GL_LINES)
        glVertex3f(ntx, nty, ntz)
        glVertex3f(tx, ty, tz)
        glEnd()

        p1, p2 = self._perp(direction)
        p1x, p1y, p1z = p1
        p2x, p2y, p2z = p2
        r = head_size * 0.35

        # Positive cone
        glBegin(GL_LINES)
        for i in range(_CONE_SEGS):
            a  = 2 * math.pi * i / _CONE_SEGS
            c, s = math.cos(a), math.sin(a)
            glVertex3f(bx + (p1x*c + p2x*s)*r,
                       by + (p1y*c + p2y*s)*r,
                       bz + (p1z*c + p2z*s)*r)
            glVertex3f(tx, ty, tz)
        glEnd()

        # Negative cone
        glBegin(GL_LINES)
        for i in range(_CONE_SEGS):
            a  = 2 * math.pi * i / _CONE_SEGS
            c, s = math.cos(a), math.sin(a)
            glVertex3f(nbx + (p1x*c + p2x*s)*r,
                       nby + (p1y*c + p2y*s)*r,
                       nbz + (p1z*c + p2z*s)*r)
            glVertex3f(ntx, nty, ntz)
        glEnd()

    def _draw_ring(self, axis, color, radius):
        p1, p2 = self._perp(axis)
        p1x, p1y, p1z = p1
        p2x, p2y, p2z = p2

        glColor3f(*color)
        glLineWidth(5.0)
        glBegin(GL_LINE_LOOP)
        for i in range(_RING_SEGS):
            a = 2 * math.pi * i / _RING_SEGS
            c, s = math.cos(a), math.sin(a)
            glVertex3f((p1x*c + p2x*s)*radius,
                       (p1y*c + p2y*s)*radius,
                       (p1z*c + p2z*s)*radius)
        glEnd()

    @staticmethod
    def _draw_center_cube(color, s):
        """Draw a solid + wireframe cube of half-size s at the gizmo origin."""
        verts = [
            (-s,-s,-s), ( s,-s,-s), ( s, s,-s), (-s, s,-s),
            (-s,-s, s), ( s,-s, s), ( s, s, s), (-s, s, s),
        ]
        faces = [
            (0,1,2,3), (4,5,6,7),
            (0,1,5,4), (2,3,7,6),
            (1,2,6,5), (0,3,7,4),
        ]
        edges = [
            (0,1),(1,2),(2,3),(3,0),
            (4,5),(5,6),(6,7),(7,4),
            (0,4),(1,5),(2,6),(3,7),
        ]
        # Semi-transparent filled faces
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glColor4f(color[0], color[1], color[2], 0.35)
        glBegin(GL_QUADS)
        for face in faces:
            for idx in face:
                glVertex3f(*verts[idx])
        glEnd()
        # Solid wireframe outline
        glColor3f(*color)
        glLineWidth(2.5)
        glBegin(GL_LINES)
        for a, b in edges:
            glVertex3f(*verts[a])
            glVertex3f(*verts[b])
        glEnd()

    # ------------------------------------------------------------------
    # Hit-test projections
    # ------------------------------------------------------------------

    def _update_projections(self, gx, gy, gz, arrow_len, ring_radius,
                             viewport, modelview, projection):
        """Project all handle sample points to screen for hit testing."""
        vph = viewport[3]

        def proj(wx, wy, wz):
            try:
                p = gluProject(gx+wx, gy+wy, gz+wz, modelview, projection, viewport)
                return (p[0], vph - p[1])
            except Exception:
                return None

        c = proj(0, 0, 0)
        if c:
            self._proj_center = c

        pts = {}

        # Translation arrows — sample along shaft
        for h, (dx, dy, dz) in [
            (HANDLE_TRANS_X, ( 1.0,  0.0,  0.0)),
            (HANDLE_TRANS_Z, ( 0.0,  1.0,  0.0)),
            (HANDLE_TRANS_Y, ( 0.0,  0.0, -1.0)),
        ]:
            hpts = []
            for t in (-1.0, -0.65, -0.35, 0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 1.0):
                p = proj(dx*arrow_len*t, dy*arrow_len*t, dz*arrow_len*t)
                if p:
                    hpts.append(p)
            pts[h] = hpts

        # Rotation rings — sample around circumference
        for h, axis in [
            (HANDLE_ROT_X, (1.0, 0.0, 0.0)),
            (HANDLE_ROT_Z, (0.0, 1.0, 0.0)),
            (HANDLE_ROT_Y, (0.0, 0.0, 1.0)),
        ]:
            p1, p2 = self._perp(axis)
            p1x, p1y, p1z = p1
            p2x, p2y, p2z = p2
            hpts = []
            for i in range(_PROJ_RING_SAMPS):
                a  = 2 * math.pi * i / _PROJ_RING_SAMPS
                c2, s2 = math.cos(a), math.sin(a)
                p = proj((p1x*c2 + p2x*s2)*ring_radius,
                         (p1y*c2 + p2y*s2)*ring_radius,
                         (p1z*c2 + p2z*s2)*ring_radius)
                if p:
                    hpts.append(p)
            pts[h] = hpts

        # Centre cube (free XY move) — project corners + centre for hit testing
        cs = arrow_len * 0.12
        cube_corners = [
            (-cs,-cs,-cs), ( cs,-cs,-cs), ( cs, cs,-cs), (-cs, cs,-cs),
            (-cs,-cs, cs), ( cs,-cs, cs), ( cs, cs, cs), (-cs, cs, cs),
            (0, 0, 0),
        ]
        pts[HANDLE_TRANS_XY] = [p for p in (proj(vx, vy, vz) for vx, vy, vz in cube_corners) if p]

        self._proj_handles = pts

    # ------------------------------------------------------------------
    # Translation drag
    # ------------------------------------------------------------------

    def _drag_translate(self, mouse_x, mouse_y, entity, canvas,
                        viewport, modelview, projection):
        """Move all selected entities along the active axis.

        Uses ray-axis intersection: unproject each mouse position to a 3-D ray,
        then find the closest point on the drag axis to that ray.  The difference
        in axis parameter (t) between the start ray and the current ray is the
        world-space displacement — numerically stable at any camera distance or
        viewing angle.
        """
        if self.active_handle == HANDLE_TRANS_XY:
            self._drag_translate_xy(mouse_x, mouse_y, entity, canvas,
                                    viewport, modelview, projection)
            return

        vph = viewport[3]
        ax, ay, az = _GL_AXIS[self.active_handle]
        igx, igy, igz = self._drag_start_init_gl   # axis origin (GL pos at drag start)

        def _unproject_ray(px, py):
            yy = vph - py
            near = gluUnProject(px, yy, 0.0, modelview, projection, viewport)
            far  = gluUnProject(px, yy, 1.0, modelview, projection, viewport)
            dx, dy, dz = far[0]-near[0], far[1]-near[1], far[2]-near[2]
            length = math.sqrt(dx*dx + dy*dy + dz*dz)
            if length < 1e-12:
                return None, None
            return (near[0], near[1], near[2]), (dx/length, dy/length, dz/length)

        def _axis_t(px, py):
            """Closest-point parameter on the drag axis for screen pixel (px, py)."""
            ro, rd = _unproject_ray(px, py)
            if ro is None:
                return None
            wx, wy, wz = ro[0]-igx, ro[1]-igy, ro[2]-igz
            b     = rd[0]*ax + rd[1]*ay + rd[2]*az       # ray_dir · axis_dir
            denom = 1.0 - b*b
            if abs(denom) < 1e-6:
                return None                               # ray parallel to axis
            d_val = rd[0]*wx + rd[1]*wy + rd[2]*wz       # ray_dir · w
            e_val =  ax*wx  +  ay*wy  +  az*wz           # axis_dir · w
            return (e_val - b * d_val) / denom

        sx0, sy0 = self._drag_start_screen
        t_start = _axis_t(sx0, sy0)
        t_now   = _axis_t(mouse_x, mouse_y)
        if t_start is None or t_now is None:
            return

        delta_gl = t_now - t_start

        # Apply delta to all selected entities
        _snap = getattr(canvas, 'terrain_snap_enabled', False)
        _height_fn = canvas.get_terrain_height_at if (_snap and hasattr(canvas, 'get_terrain_height_at')) else None
        for ent, ex0, ey0, ez0 in self._drag_start_pos_all:
            h = self.active_handle
            if   h == HANDLE_TRANS_X:
                ent.x = ex0 + delta_gl
            elif h == HANDLE_TRANS_Z:
                ent.z = ez0 + delta_gl
            elif h == HANDLE_TRANS_Y:
                ent.y = ey0 + delta_gl

            if _height_fn is not None:
                _ht = _height_fn(ent.x, ent.y)
                if h in (HANDLE_TRANS_X, HANDLE_TRANS_Y):
                    # Horizontal move — snap Z exactly to terrain surface
                    ent.z = _ht
                elif h == HANDLE_TRANS_Z:
                    # Vertical move — terrain acts as solid floor; can go up, not below
                    ent.z = max(ent.z, _ht)

            if hasattr(canvas, 'update_entity_xml'):
                canvas.update_entity_xml(ent)
            if hasattr(canvas, 'mark_entity_modified'):
                canvas.mark_entity_modified(ent)
            if hasattr(canvas, '_update_managers_vpos_for_entity'):
                canvas._update_managers_vpos_for_entity(ent)

        # Sync gizmo position to primary entity
        self.position = (entity.x, entity.y, entity.z)

        # Live stats panel update
        try:
            mw = canvas
            while mw.parent():
                mw = mw.parent()
            if hasattr(mw, 'on_entity_position_updated'):
                mw.on_entity_position_updated(entity, (entity.x, entity.y, entity.z))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Free XY-plane drag (centre cube)
    # ------------------------------------------------------------------

    def _drag_translate_xy(self, mouse_x, mouse_y, entity, canvas,
                           viewport, modelview, projection):
        """Move all selected entities freely on the world XY ground plane."""
        vph = viewport[3]
        _, igy, _ = self._drag_start_init_gl   # GL Y at drag start (fixed plane height)
        sx0, sy0  = self._drag_start_screen

        def _ray_plane_hit(px, py):
            """Ray vs horizontal GL plane at y = igy. Returns (gl_x, gl_z) or None."""
            yy = vph - py
            try:
                near = gluUnProject(px, yy, 0.0, modelview, projection, viewport)
                far  = gluUnProject(px, yy, 1.0, modelview, projection, viewport)
            except Exception:
                return None
            dy = far[1] - near[1]
            if abs(dy) < 1e-9:   # ray parallel to ground plane
                return None
            t = (igy - near[1]) / dy
            if t < 0:
                return None
            return (near[0] + t * (far[0] - near[0]),
                    near[2] + t * (far[2] - near[2]))

        hit_start = _ray_plane_hit(sx0, sy0)
        hit_now   = _ray_plane_hit(mouse_x, mouse_y)
        if hit_start is None or hit_now is None:
            return

        delta_x =   hit_now[0] - hit_start[0]   # GL X  = World X
        delta_y = -(hit_now[1] - hit_start[1])   # GL -Z = World Y

        _snap = getattr(canvas, 'terrain_snap_enabled', False)
        _height_fn = canvas.get_terrain_height_at if (_snap and hasattr(canvas, 'get_terrain_height_at')) else None

        for ent, ex0, ey0, ez0 in self._drag_start_pos_all:
            ent.x = ex0 + delta_x
            ent.y = ey0 + delta_y
            if _height_fn is not None:
                ent.z = _height_fn(ent.x, ent.y)
            if hasattr(canvas, 'update_entity_xml'):
                canvas.update_entity_xml(ent)
            if hasattr(canvas, 'mark_entity_modified'):
                canvas.mark_entity_modified(ent)
            if hasattr(canvas, '_update_managers_vpos_for_entity'):
                canvas._update_managers_vpos_for_entity(ent)

        self.position = (entity.x, entity.y, entity.z)

        try:
            mw = canvas
            while mw.parent():
                mw = mw.parent()
            if hasattr(mw, 'on_entity_position_updated'):
                mw.on_entity_position_updated(entity, (entity.x, entity.y, entity.z))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Rotation drag
    # ------------------------------------------------------------------

    def _drag_rotate(self, mouse_x, mouse_y, entity, canvas):
        """Rotate entity around the active axis using angle-from-center drag."""
        cx, cy = self._drag_start_center_screen
        sx0, sy0 = self._drag_start_screen

        sa = math.degrees(math.atan2(-(sy0 - cy), sx0 - cx))
        ca = math.degrees(math.atan2(-(mouse_y - cy), mouse_x - cx))
        delta = ca - sa

        # Normalise
        while delta >  180: delta -= 360
        while delta < -180: delta += 360

        ax0, ay0, az0 = self._drag_start_angles
        h = self.active_handle

        if   h == HANDLE_ROT_X:
            self._write_angles(entity, (ax0 - delta) % 360, ay0, az0, canvas)
        elif h == HANDLE_ROT_Z:
            self._write_angles(entity, ax0, ay0, (az0 + delta) % 360, canvas)
        elif h == HANDLE_ROT_Y:
            self._write_angles(entity, ax0, (ay0 + delta) % 360, az0, canvas)

    # ------------------------------------------------------------------
    # hidAngles read / write
    # ------------------------------------------------------------------

    @staticmethod
    def _read_angles(entity):
        """Return (ax, ay, az) game-coords from hidAngles, or (0,0,0)."""
        if not hasattr(entity, 'xml_element') or entity.xml_element is None:
            return (0.0, 0.0, 0.0)
        f = entity.xml_element.find("./field[@name='hidAngles']")
        if f is not None:
            v = f.get('value-Vector3')
            if v:
                try:
                    parts = [float(p.strip()) for p in v.split(',')]
                    if len(parts) >= 3:
                        return (parts[0], parts[1], parts[2])
                except (ValueError, IndexError):
                    pass
        return (0.0, 0.0, 0.0)

    @staticmethod
    def _write_angles(entity, ax, ay, az, canvas):
        """Write hidAngles and recompute BinHex. No-op if field absent."""
        if not hasattr(entity, 'xml_element') or entity.xml_element is None:
            return
        f = entity.xml_element.find("./field[@name='hidAngles']")
        if f is None:
            return
        f.set('value-Vector3', f"{ax:.2f},{ay:.2f},{az:.2f}")
        f.text = struct.pack('<fff', float(ax), float(ay), float(az)).hex().upper()
        if hasattr(canvas, 'mark_entity_modified'):
            canvas.mark_entity_modified(entity)
        if hasattr(canvas, 'entity_renderer') and canvas.entity_renderer:
            canvas.entity_renderer.invalidate_entity_cache(entity)
        if hasattr(canvas, 'angle_update'):
            canvas.angle_update.emit(entity, (float(ax), float(ay), float(az)))
