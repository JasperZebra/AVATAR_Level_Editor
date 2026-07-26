"""
canvas/movie_renderer.py — 2D and 3D rendering for moviedata.xml sequences.

Draws:
  • Purple dashed path lines connecting keyframe positions
  • Diamond markers at each keyframe
  • Orange dot markers for event keys (particle start/stop)
  • Grey cube fallback for NodeDef entities not found in the loaded entity list

Only renders the currently selected sequence (canvas.main_window.selected_movie_sequence).
"""

import math
import os

import OpenGL.GL as gl
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QPen, QBrush, QColor, QPolygonF, QFont

# Purple path colour
_PATH_COLOR   = QColor(160, 80, 255, 220)
_PATH_DARK    = QColor(120, 50, 200, 160)
_DIAMOND_SEL  = QColor(200, 120, 255, 255)
_DIAMOND_NORM = QColor(160, 80, 255, 210)
_EVENT_COLOR  = QColor(255, 160, 40, 220)   # orange — particle/event markers

# GL colours (0-1)
_GL_PATH   = (0.63, 0.31, 1.0, 0.85)
_GL_DIAM   = (0.78, 0.47, 1.0, 1.0)
_GL_EVENT  = (1.0,  0.63, 0.16, 1.0)
_GL_GHOST  = (0.5,  0.5,  0.5,  0.7)   # unmatched NodeDef cubes

# Cutscene-camera colours — taken from the AM3D editor's cineractive display
# (src/map_canvas.py::_render_coords) so the two editors read identically.
_GL_CAM_PATH = (1.0,  0.85, 0.2,  1.0)   # 🟡 camera flight path      (AM3D 1.0,0.85,0.2)
_GL_CAM_KEY  = (1.0,  0.85, 0.2,  1.0)   # 🟡 camera keyframe cube    (AM3D Bookmark colour)
_GL_AIM_PATH = (0.35, 0.85, 0.45, 1.0)   # 🟢 look-at path            (AM3D 0.35,0.85,0.45)
_GL_AIM_KEY  = (0.37, 0.90, 0.43, 1.0)   # 🟢 look-at target cube     (AM3D 95,230,110)
_GL_SIGHT    = (0.95, 0.85, 0.3,  1.0)   # the live sight line        (AM3D 0.95,0.85,0.3)
_GL_CAM_BODY = (0.80, 0.83, 0.92, 1.0)   # camera model, idle         (AM3D 0.80,0.83,0.92)
_GL_CAM_SEL  = (1.0,  0.92, 0.35, 1.0)   # camera model, live/selected(AM3D 1.0,0.92,0.35)

# Pending-placement colours — an imported sequence that has NOT been committed
# yet. Deliberately cyan rather than the purple used for real sequences, so a
# preview can never be mistaken for something that exists in the level.
_PENDING_PATH = QColor(60, 220, 220, 230)
_PENDING_CAM  = QColor(255, 210, 80, 230)
_PENDING_NODE = QColor(90, 240, 200, 230)
_PENDING_TEXT = QColor(120, 250, 240, 255)

_GL_PENDING_PATH = (0.24, 0.86, 0.86, 0.9)
_GL_PENDING_CAM  = (1.0,  0.82, 0.31, 0.9)
_GL_PENDING_NODE = (0.35, 0.94, 0.78, 0.9)

# How far in front of a camera to place its look-at point when the sequence has
# no actors to aim at (moviedata has no explicit focus target — see aim_point).
_AIM_FALLBACK = 25.0

_CAM_MODEL_SIZE = 6.0     # world height of the camera marker

# Lazily-built display list for the film-camera marker (canvas/assets/camera).
_cam_dl = None
_cam_h = 1.0
_cam_tried = False


def _camera_display_list():
    """(display_list, model_height) for the film-camera marker, built once.

    The model is the AM3D editor's `filmCamera.fbx`, copied into
    canvas/assets/camera and read by the ported canvas/fbx_mesh.py. Its LENS
    looks down local +X and it stands on Y=0, matching AM3D's placement basis.
    Returns (None, 1.0) if the asset or the parse is unavailable — the caller
    then falls back to the wireframe frustum.
    """
    global _cam_dl, _cam_h, _cam_tried
    if _cam_tried:
        return _cam_dl, _cam_h
    _cam_tried = True
    try:
        import numpy as np
        from fbx_mesh import load_fbx_mesh
        path = os.path.join(os.path.dirname(__file__), 'assets', 'camera',
                            'filmCamera.fbx')
        V, T, N = load_fbx_mesh(path)
        mn, mx = V.min(0), V.max(0)
        # Centre on X/Z, sit on Y=0 — same normalisation AM3D uses.
        Vc = (V - np.array([(mn[0] + mx[0]) / 2, mn[1], (mn[2] + mx[2]) / 2])).astype('f4')
        _cam_h = float(mx[1] - mn[1]) or 1.0
        dl = gl.glGenLists(1)
        gl.glNewList(dl, gl.GL_COMPILE)
        gl.glBegin(gl.GL_TRIANGLES)
        for t in T:
            for j in t:
                gl.glNormal3fv(N[j])
                gl.glVertex3fv(Vc[j])
        gl.glEnd()
        gl.glEndList()
        _cam_dl = dl
        print(f"[movie] camera marker model ready ({len(V)} verts)")
    except Exception as e:
        print(f"[movie] camera model unavailable ({e}) — using wireframe marker")
        _cam_dl = None
    return _cam_dl, _cam_h


def _draw_camera_model(pos_gl, look_gl, live):
    """Place the film-camera model at pos_gl with its lens aimed at look_gl.

    Mirrors AM3D's `_camera_basis`: local +X is the lens (points at the look-at
    target), +Y is up, +Z is the side; all three columns scaled so the model
    stands `_CAM_MODEL_SIZE` tall. Both points are already in editor GL space.
    """
    dl, h = _camera_display_list()
    if not dl:
        return False
    import numpy as np
    p = np.asarray(pos_gl, dtype=float)
    f = np.asarray(look_gl, dtype=float) - p
    n = np.linalg.norm(f)
    f = f / n if n > 1e-6 else np.array([0.0, 0.0, 1.0])
    wup = np.array([0.0, 1.0, 0.0])
    side = np.cross(f, wup)
    sn = np.linalg.norm(side)
    side = side / sn if sn > 1e-6 else np.array([0.0, 0.0, 1.0])
    tup = np.cross(side, f)
    s = _CAM_MODEL_SIZE / (h or 1.0)
    cx, cy, cz = f * s, tup * s, side * s
    M = [cx[0], cx[1], cx[2], 0.0,
         cy[0], cy[1], cy[2], 0.0,
         cz[0], cz[1], cz[2], 0.0,
         p[0],  p[1],  p[2],  1.0]
    gl.glPushMatrix()
    gl.glMultMatrixf(M)
    gl.glEnable(gl.GL_LIGHTING)
    gl.glColor3f(*( _GL_CAM_SEL[:3] if live else _GL_CAM_BODY[:3]))
    gl.glCallList(dl)
    gl.glDisable(gl.GL_LIGHTING)
    gl.glPopMatrix()
    return True


def _loaded_entity_ids(canvas):
    """{entity.id} for the canvas's entity list — cached on the canvas.

    Both ghost-node passes rebuilt this set from scratch on EVERY paint, an
    O(N) cost per frame that only bit while a sequence was selected (~0.4 ms
    per frame on a 5,600-entity level, several ms on big ones). The entity
    list only changes on load/add/delete, so key it on identity + length.
    """
    ents = getattr(canvas, 'entities', None) or []
    key = (id(ents), len(ents))
    if getattr(canvas, '_movie_loaded_ids_key', None) != key:
        canvas._movie_loaded_ids = {e.id for e in ents}
        canvas._movie_loaded_ids_key = key
    return canvas._movie_loaded_ids


# ── 2D rendering ───────────────────────────────────────────────────────────────

def draw_movie_paths_2d(painter, canvas):
    """
    Draw the selected sequence's keyframe paths in the 2D view.
    Called from map_canvas_gpu after render_entities_2d.
    """
    mw = getattr(canvas, 'main_window', None)
    if mw is None:
        return
    movie_data = getattr(mw, 'movie_data', None)
    seq_name   = getattr(mw, 'selected_movie_sequence', None)
    if movie_data is None or seq_name is None:
        return

    seq = movie_data.get_sequence(seq_name)
    if seq is None:
        return

    selected_node_id = getattr(mw, 'selected_movie_node_id', None)

    for seq_node in seq.nodes:
        # If a specific node is selected, only draw that one
        if selected_node_id is not None and seq_node.node_id != selected_node_id:
            continue

        keys = seq_node.all_pos_keys()
        if not keys:
            continue

        screen_pts = [
            QPointF(*canvas.world_to_screen(k.x, k.y))
            for k in keys
        ]

        # Dashed purple path line
        painter.setPen(QPen(_PATH_COLOR, 1.5, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        if len(screen_pts) >= 2:
            for i in range(len(screen_pts) - 1):
                painter.drawLine(screen_pts[i], screen_pts[i + 1])

        # Diamond at each keyframe position
        for i, sp in enumerate(screen_pts):
            color = _DIAMOND_SEL if i == 0 else _DIAMOND_NORM
            _draw_diamond_2d(painter, sp.x(), sp.y(), 5, color)

        # Orange dot for event keys (param 4)
        event_track = seq_node.tracks.get(4)
        if event_track:
            for ek in event_track.event_keys:
                pos = seq_node.pos_at(ek.time)
                if pos:
                    sx, sy = canvas.world_to_screen(pos[0], pos[1])
                    painter.setPen(QPen(_EVENT_COLOR, 1))
                    painter.setBrush(QBrush(_EVENT_COLOR))
                    painter.drawEllipse(QRectF(sx - 4, sy - 4, 8, 8))

    # Ghost cubes for NodeDef entries not matched to a loaded entity
    _draw_ghost_nodes_2d(painter, canvas, movie_data, seq, selected_node_id)


def draw_pending_sequence_2d(painter, canvas):
    """Draw an imported-but-not-yet-placed sequence as a movable ghost.

    Reads canvas.main_window.pending_sequence (a sequence_link.PlacementGroup).
    Nothing exists in the level yet -- this is drawn straight from the bundle,
    so cancelling costs nothing and there is nothing to undo.

    Deliberately styled apart from the committed-sequence colours above: cyan
    instead of purple, so a preview is never mistaken for something real.
    """
    mw = getattr(canvas, 'main_window', None)
    group = getattr(mw, 'pending_sequence', None) if mw else None
    if group is None or getattr(group, 'committed', False):
        return

    try:
        paths = group.preview_paths()
        nodes = group.preview_nodes()
    except Exception:
        return

    for path in paths:
        pts = path.get('points') or []
        if len(pts) < 2:
            continue
        colour = _PENDING_CAM if path.get('is_camera') else _PENDING_PATH
        screen = [QPointF(*canvas.world_to_screen(p[1], p[2])) for p in pts]
        painter.setPen(QPen(colour, 2.0, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        for i in range(len(screen) - 1):
            painter.drawLine(screen[i], screen[i + 1])
        for sp in screen:
            _draw_diamond_2d(painter, sp.x(), sp.y(), 4, colour)

    # Node markers, plus a label on the group origin so it is obvious what is
    # being placed and that it is not committed yet.
    for nd in nodes:
        sx, sy = canvas.world_to_screen(nd['pos'][0], nd['pos'][1])
        colour = _PENDING_CAM if nd.get('is_camera') else _PENDING_NODE
        painter.setPen(QPen(colour, 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(sx - 6, sy - 6, 12, 12))

    ox, oy = canvas.world_to_screen(group.origin[0], group.origin[1])
    painter.setPen(QPen(_PENDING_TEXT, 1))
    painter.setFont(QFont('Arial', 9, QFont.Bold))
    painter.drawText(QPointF(ox + 10, oy - 8),
                     f"{group.name}  (placing — click to confirm)")
    painter.setPen(QPen(_PENDING_TEXT, 1, Qt.DashLine))
    painter.drawLine(QPointF(ox - 12, oy), QPointF(ox + 12, oy))
    painter.drawLine(QPointF(ox, oy - 12), QPointF(ox, oy + 12))


def render_pending_sequence_3d(canvas):
    """3D counterpart of draw_pending_sequence_2d."""
    mw = getattr(canvas, 'main_window', None)
    group = getattr(mw, 'pending_sequence', None) if mw else None
    if group is None or getattr(group, 'committed', False):
        return

    try:
        paths = group.preview_paths()
        nodes = group.preview_nodes()
    except Exception:
        return

    gl.glDisable(gl.GL_LIGHTING)
    gl.glDisable(gl.GL_DEPTH_TEST)      # preview reads through geometry
    gl.glEnable(gl.GL_BLEND)
    gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
    gl.glLineWidth(2.0)

    for path in paths:
        pts = path.get('points') or []
        if len(pts) < 2:
            continue
        gl.glColor4f(*(_GL_PENDING_CAM if path.get('is_camera')
                       else _GL_PENDING_PATH))
        gl.glBegin(gl.GL_LINE_STRIP)
        for _t, x, y, z in pts:
            gx, gy, gz = canvas.world_to_gl(x, y, z)
            gl.glVertex3f(gx, gy, gz)
        gl.glEnd()

    for nd in nodes:
        gl.glColor4f(*(_GL_PENDING_CAM if nd.get('is_camera')
                       else _GL_PENDING_NODE))
        gx, gy, gz = canvas.world_to_gl(*nd['pos'])
        _draw_wireframe_cube_3d(gx, gy, gz, 1.5)

    gl.glLineWidth(1.0)
    gl.glEnable(gl.GL_DEPTH_TEST)
    gl.glEnable(gl.GL_LIGHTING)


def _draw_diamond_2d(painter, cx, cy, r, color):
    """Draw a filled rotated-square (diamond) centred at (cx, cy) with half-size r."""
    pts = QPolygonF([
        QPointF(cx,     cy - r),
        QPointF(cx + r, cy),
        QPointF(cx,     cy + r),
        QPointF(cx - r, cy),
    ])
    painter.setPen(QPen(Qt.white, 0.5))
    painter.setBrush(QBrush(color))
    painter.drawPolygon(pts)


def _draw_ghost_nodes_2d(painter, canvas, movie_data, seq, selected_node_id=None):
    """Draw a small grey square for nodes whose EntityId isn't in the loaded entity list."""
    loaded_ids = _loaded_entity_ids(canvas)
    for seq_node in seq.nodes:
        if selected_node_id is not None and seq_node.node_id != selected_node_id:
            continue
        nd = movie_data.node_defs.get(seq_node.node_id)
        if nd is None or nd.entity_id in loaded_ids:
            continue
        # Entity not loaded — render at NodeDef rest position
        sx, sy = canvas.world_to_screen(nd.pos[0], nd.pos[1])
        r = 5
        ghost = QColor(140, 140, 140, 180)
        painter.setPen(QPen(Qt.white, 0.5))
        painter.setBrush(QBrush(ghost))
        painter.drawRect(QRectF(sx - r, sy - r, r * 2, r * 2))


# ── Cutscene camera display (AM3D-style) ──────────────────────────────────────

def _quat_forward(q):
    """Camera forward in GAME space for quaternion (w,x,y,z) — +Y is forward,
    re-confirmed across 237 camera NodeDefs (see AGENTS.md)."""
    w, x, y, z = (float(q[0]), float(q[1]), float(q[2]), float(q[3]))
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if n < 1e-9:
        return (0.0, 1.0, 0.0)
    w, x, y, z = w / n, x / n, y / n, z / n
    # R · (0,1,0)
    return (2.0 * (x * y - z * w),
            1.0 - 2.0 * (x * x + z * z),
            2.0 * (y * z + x * w))


def aim_point(pos, quat, reach):
    """Where a camera at `pos` with orientation `quat` is looking, `reach` away.

    moviedata has NO explicit look-at target (unlike AM3D's Focus curve), so the
    aim point is reconstructed by projecting the camera's forward axis. `reach`
    is the distance to the sequence's action so the aim line lands ON the
    subject instead of an arbitrary distance out.
    """
    f = _quat_forward(quat)
    return (pos[0] + f[0] * reach, pos[1] + f[1] * reach, pos[2] + f[2] * reach)


def _seq_reach(movie_data, seq, cam_pos):
    """Distance from a camera to the sequence's action, for sizing aim lines."""
    try:
        from cs_camera_preview import sequence_action_centre
        c = sequence_action_centre(movie_data, seq)
        if c is None:
            return _AIM_FALLBACK
        d = math.dist((float(c[0]), float(c[1]), float(c[2])),
                      (float(cam_pos[0]), float(cam_pos[1]), float(cam_pos[2])))
        return max(2.0, min(d, 400.0))
    except Exception:
        return _AIM_FALLBACK


def _draw_camera_marker(pos, quat, reach, size):
    """A small wireframe view-frustum at the camera, pointing where it looks —
    the equivalent of AM3D's film-camera model, but built from lines so it needs
    no asset and no lighting state."""
    f = _quat_forward(quat)
    fl = math.sqrt(sum(c * c for c in f)) or 1.0
    f = (f[0] / fl, f[1] / fl, f[2] / fl)
    up = (0.0, 0.0, 1.0)                      # game world up
    r = (f[1] * up[2] - f[2] * up[1],
         f[2] * up[0] - f[0] * up[2],
         f[0] * up[1] - f[1] * up[0])
    rl = math.sqrt(sum(c * c for c in r))
    if rl < 1e-6:
        r = (1.0, 0.0, 0.0); rl = 1.0
    r = (r[0] / rl, r[1] / rl, r[2] / rl)
    u = (r[1] * f[2] - r[2] * f[1],
         r[2] * f[0] - r[0] * f[2],
         r[0] * f[1] - r[1] * f[0])

    d = max(size * 2.0, min(reach * 0.25, size * 6.0))   # frustum length
    hw, hh = d * 0.45, d * 0.26                          # ~16:9 at ~50 deg
    cx, cy, cz = float(pos[0]), float(pos[1]), float(pos[2])
    ctr = (cx + f[0] * d, cy + f[1] * d, cz + f[2] * d)

    def corner(sx, sy):
        return (ctr[0] + r[0] * hw * sx + u[0] * hh * sy,
                ctr[1] + r[1] * hw * sx + u[1] * hh * sy,
                ctr[2] + r[2] * hw * sx + u[2] * hh * sy)

    c = [corner(-1, -1), corner(1, -1), corner(1, 1), corner(-1, 1)]
    gl.glBegin(gl.GL_LINES)
    for p in c:                                  # apex -> the four corners
        gl.glVertex3f(cx, cz, -cy)
        gl.glVertex3f(p[0], p[2], -p[1])
    for i in range(4):                           # the far rectangle
        a, b = c[i], c[(i + 1) % 4]
        gl.glVertex3f(a[0], a[2], -a[1])
        gl.glVertex3f(b[0], b[2], -b[1])
    gl.glEnd()


def _camera_curves(movie_data, seq, seq_node, nd):
    """(flight_pts, aim_pts, reach) for one cutscene camera, in GAME space.

    aim_pts[i] is where the camera is looking at keyframe i — the look-at target
    curve. Both lists are parallel, and the same `reach` is used for the live
    sight line, so that line always ENDS exactly on this curve.
    """
    keys = seq_node.all_pos_keys()
    pts = [(k.x, k.y, k.z) for k in keys] or ([tuple(nd.pos)] if nd else [])
    if not pts:
        return [], [], _AIM_FALLBACK
    reach = _seq_reach(movie_data, seq, pts[0])
    rest = nd.rotate if nd else (1.0, 0.0, 0.0, 0.0)
    aims = [aim_point((k.x, k.y, k.z), seq_node.rot_at(k.time) or rest, reach)
            for k in keys]
    if not aims:
        aims = [aim_point(pts[0], rest, reach)]
    return pts, aims, reach


def _draw_camera_curves(movie_data, seq, seq_node, nd):
    """The two curves for one camera: 🟡 flight path and 🟢 look-at target path,
    with a small cube at each keyframe of both. No per-keyframe aim arrows —
    those are what made a thicket of green lines shooting past the look-at
    curve. The single sight line is drawn once, by the caller, from the LIVE
    camera position (AM3D draws exactly one, only while playing)."""
    pts, aims, _ = _camera_curves(movie_data, seq, seq_node, nd)
    if not pts:
        return

    if len(pts) >= 2:                                   # 🟡 flight path
        gl.glColor4f(*_GL_CAM_PATH)
        gl.glLineWidth(2.5)
        gl.glBegin(gl.GL_LINE_STRIP)
        for p in pts:
            gl.glVertex3f(p[0], p[2], -p[1])
        gl.glEnd()

    if len(aims) >= 2:                                  # 🟢 look-at path
        gl.glColor4f(*_GL_AIM_PATH)
        gl.glLineWidth(1.7)
        gl.glBegin(gl.GL_LINE_STRIP)
        for a in aims:
            gl.glVertex3f(a[0], a[2], -a[1])
        gl.glEnd()

    gl.glColor4f(*_GL_CAM_KEY)                          # 🟡 camera keyframes
    gl.glLineWidth(1.4)
    for p in pts:
        _draw_wireframe_cube_3d(p[0], p[2], -p[1], 1.2)

    gl.glColor4f(*_GL_AIM_KEY)                          # 🟢 look-at targets
    gl.glLineWidth(1.2)
    for a in aims:
        _draw_wireframe_cube_3d(a[0], a[2], -a[1], 1.0)


def _draw_live_camera(movie_data, seq, cam_node, nd, t):
    """The ONE camera marker + the ONE sight line, at sequence time `t`.

    AM3D shows a single film camera sliding along the path, not one per
    keyframe. The sight line runs from the camera to its look-at target and
    STOPS there — it must not shoot past the look-at curve.
    """
    pts, aims, reach = _camera_curves(movie_data, seq, cam_node, nd)
    if not pts:
        return
    rest = nd.rotate if nd else (1.0, 0.0, 0.0, 0.0)
    pos = cam_node.pos_at(t) or pts[0]
    quat = cam_node.rot_at(t) or rest
    look = aim_point(pos, quat, reach)      # lands ON the look-at curve

    gl.glColor4f(*_GL_SIGHT)                # the single sight line
    gl.glLineWidth(1.6)
    gl.glBegin(gl.GL_LINES)
    gl.glVertex3f(pos[0], pos[2], -pos[1])
    gl.glVertex3f(look[0], look[2], -look[1])
    gl.glEnd()

    pos_gl = (pos[0], pos[2], -pos[1])
    look_gl = (look[0], look[2], -look[1])
    if not _draw_camera_model(pos_gl, look_gl, live=True):
        gl.glColor4f(*_GL_CAM_SEL)          # fallback: wireframe frustum
        gl.glLineWidth(2.0)
        _draw_camera_marker(pos, quat, reach, 1.5)


# ── 3D rendering ───────────────────────────────────────────────────────────────

def render_movie_paths_3d(canvas):
    """
    Draw the selected sequence's keyframe paths in the 3D view.
    Called from map_canvas_gpu after _render_shape_points_3d.
    GL coordinate mapping: world(x, y, z) → gl(x, z, -y)
    """
    mw = getattr(canvas, 'main_window', None)
    if mw is None:
        return
    movie_data = getattr(mw, 'movie_data', None)
    seq_name   = getattr(mw, 'selected_movie_sequence', None)
    if movie_data is None or seq_name is None:
        return

    seq = movie_data.get_sequence(seq_name)
    if seq is None:
        return

    selected_node_id = getattr(mw, 'selected_movie_node_id', None)
    # Playback time, published by _movie_apply_time. None => not playing, so the
    # camera markers sit parked at their first keyframe.
    live_t = getattr(mw, '_movie_preview_t', None)

    gl.glDisable(gl.GL_LIGHTING)
    gl.glDisable(gl.GL_TEXTURE_2D)
    gl.glDisable(gl.GL_DEPTH_TEST)   # always on top like shape points

    try:
        from cs_camera_preview import is_camera, camera_shots, active_camera_at
    except Exception:
        is_camera = lambda nd: False
        camera_shots = lambda *a: []
        active_camera_at = lambda *a, **k: None

    # ONE live camera for the whole sequence, not one per node: resolve which
    # camera is on air at `live_t` from the shot list, exactly like the CS
    # preview does, and only that one gets a model + sight line. Parked (not
    # playing) it sits at the opening shot's first keyframe.
    live_cam_id = None
    try:
        shots = camera_shots(movie_data, seq)
        if shots:
            live_cam_id = active_camera_at(shots, live_t if live_t is not None
                                           else float(getattr(seq, 'start_time', 0.0) or 0.0))
    except Exception:
        shots = []

    for seq_node in seq.nodes:
        if selected_node_id is not None and seq_node.node_id != selected_node_id:
            continue
        nd = movie_data.node_defs.get(seq_node.node_id)
        # Cutscene cameras get the AM3D treatment: 🟡 flight path + 🟢 look-at
        # path, instead of the generic purple actor path.
        if is_camera(nd):
            try:
                _draw_camera_curves(movie_data, seq, seq_node, nd)
            except Exception as e:
                print(f"[movie] camera curve draw failed: {e}")
            continue
        keys = seq_node.all_pos_keys()
        if not keys:
            continue

        # Path line — purple
        gl.glColor4f(*_GL_PATH)
        gl.glLineWidth(2.0)
        gl.glBegin(gl.GL_LINE_STRIP)
        for k in keys:
            gl.glVertex3f(k.x, k.z, -k.y)
        gl.glEnd()

        # Diamond markers at each keyframe
        for i, k in enumerate(keys):
            if i == 0:
                gl.glColor4f(0.9, 0.6, 1.0, 1.0)   # first key — lighter
            else:
                gl.glColor4f(*_GL_DIAM)
            _draw_diamond_3d(k.x, k.z, -k.y, 0.8)

        # Orange markers for event keys
        event_track = seq_node.tracks.get(4)
        if event_track:
            gl.glColor4f(*_GL_EVENT)
            gl.glPointSize(8.0)
            gl.glBegin(gl.GL_POINTS)
            for ek in event_track.event_keys:
                pos = seq_node.pos_at(ek.time)
                if pos:
                    gl.glVertex3f(pos[0], pos[2], -pos[1])
            gl.glEnd()
            gl.glPointSize(1.0)

    # THE camera — exactly one for the whole sequence, sliding along whichever
    # shot is live. Drawn last so it sits over the curves.
    if live_cam_id is not None and (selected_node_id is None
                                    or selected_node_id == live_cam_id):
        cam_node = seq.node_by_id(live_cam_id)
        cam_nd = movie_data.node_defs.get(live_cam_id)
        if cam_node is not None:
            try:
                _draw_live_camera(
                    movie_data, seq, cam_node, cam_nd,
                    live_t if live_t is not None
                    else float(getattr(seq, 'start_time', 0.0) or 0.0))
            except Exception as e:
                print(f"[movie] live camera draw failed: {e}")

    # Ghost cubes for unmatched NodeDef entries
    _draw_ghost_nodes_3d(canvas, movie_data, seq, selected_node_id)

    gl.glEnable(gl.GL_DEPTH_TEST)
    gl.glEnable(gl.GL_LIGHTING)
    gl.glLineWidth(1.0)


def _draw_diamond_3d(gx, gy, gz, size):
    """Draw a small octahedron (3D diamond) at GL position (gx, gy, gz)."""
    s = size * 0.5
    verts = [
        (gx,     gy + s, gz),    # top
        (gx,     gy - s, gz),    # bottom
        (gx + s, gy,     gz),    # +X
        (gx - s, gy,     gz),    # -X
        (gx,     gy,     gz + s),# +Z
        (gx,     gy,     gz - s),# -Z
    ]
    faces = [
        (0, 2, 4), (0, 4, 3), (0, 3, 5), (0, 5, 2),
        (1, 4, 2), (1, 3, 4), (1, 5, 3), (1, 2, 5),
    ]
    gl.glBegin(gl.GL_TRIANGLES)
    for f in faces:
        for vi in f:
            gl.glVertex3f(*verts[vi])
    gl.glEnd()


def _draw_ghost_nodes_3d(canvas, movie_data, seq, selected_node_id=None):
    """Render a small grey wireframe cube at the rest position of unmatched NodeDef entries."""
    loaded_ids = _loaded_entity_ids(canvas)
    gl.glColor4f(*_GL_GHOST)
    gl.glLineWidth(1.5)
    for seq_node in seq.nodes:
        if selected_node_id is not None and seq_node.node_id != selected_node_id:
            continue
        nd = movie_data.node_defs.get(seq_node.node_id)
        if nd is None or nd.entity_id in loaded_ids:
            continue
        gx, gz, gy_neg = nd.pos[0], nd.pos[2], -nd.pos[1]
        _draw_wireframe_cube_3d(gx, gz, gy_neg, 1.5)
    gl.glLineWidth(1.0)


def _draw_wireframe_cube_3d(cx, cy, cz, s):
    s = s * 0.5
    corners = [
        (cx-s, cy-s, cz-s), (cx+s, cy-s, cz-s),
        (cx+s, cy+s, cz-s), (cx-s, cy+s, cz-s),
        (cx-s, cy-s, cz+s), (cx+s, cy-s, cz+s),
        (cx+s, cy+s, cz+s), (cx-s, cy+s, cz+s),
    ]
    edges = [
        (0,1),(1,2),(2,3),(3,0),
        (4,5),(5,6),(6,7),(7,4),
        (0,4),(1,5),(2,6),(3,7),
    ]
    gl.glBegin(gl.GL_LINES)
    for a, b in edges:
        gl.glVertex3f(*corners[a])
        gl.glVertex3f(*corners[b])
    gl.glEnd()
