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

# Cutscene-camera colours, mirroring the AM3D editor's cineractive display so the
# two editors read the same way: YELLOW = the camera's flight path, GREEN = where
# it is aiming, and a camera marker that flies the path during playback.
_GL_CAM_PATH = (1.0,  0.85, 0.2,  1.0)   # 🟡 camera flight path
_GL_CAM_KEY  = (1.0,  0.7,  0.1,  1.0)   # 🟡 camera keyframe cube
_GL_AIM      = (0.4,  0.95, 0.45, 0.9)   # 🟢 aim arrow (camera -> look-at)
_GL_AIM_PATH = (0.35, 0.85, 0.45, 0.9)   # 🟢 look-at path
_GL_CAM_LIVE = (1.0,  1.0,  0.55, 1.0)   # ▶ the camera that is live right now

# How far in front of a camera to place its look-at point when the sequence has
# no actors to aim at (moviedata has no explicit focus target — see aim_point).
_AIM_FALLBACK = 25.0


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


def _draw_camera_track(canvas, movie_data, seq, seq_node, nd, live_t):
    """Yellow flight path + green aim lines for ONE cutscene camera, plus a
    frustum marker: flying the path at `live_t` when the sequence is playing,
    otherwise parked at its first keyframe."""
    keys = seq_node.all_pos_keys()
    pts = [(k.x, k.y, k.z) for k in keys] or ([tuple(nd.pos)] if nd else [])
    if not pts:
        return
    reach = _seq_reach(movie_data, seq, pts[0])

    # 🟡 flight path
    if len(pts) >= 2:
        gl.glColor4f(*_GL_CAM_PATH)
        gl.glLineWidth(2.5)
        gl.glBegin(gl.GL_LINE_STRIP)
        for p in pts:
            gl.glVertex3f(p[0], p[2], -p[1])
        gl.glEnd()

    # 🟢 aim arrow at each keyframe + the look-at path connecting them
    aims = []
    for k in keys:
        q = seq_node.rot_at(k.time) or (nd.rotate if nd else (1.0, 0.0, 0.0, 0.0))
        aims.append(aim_point((k.x, k.y, k.z), q, reach))
    if aims:
        gl.glColor4f(*_GL_AIM)
        gl.glLineWidth(1.3)
        gl.glBegin(gl.GL_LINES)
        for p, a in zip(pts, aims):
            gl.glVertex3f(p[0], p[2], -p[1])
            gl.glVertex3f(a[0], a[2], -a[1])
        gl.glEnd()
        if len(aims) >= 2:
            gl.glColor4f(*_GL_AIM_PATH)
            gl.glLineWidth(1.7)
            gl.glBegin(gl.GL_LINE_STRIP)
            for a in aims:
                gl.glVertex3f(a[0], a[2], -a[1])
            gl.glEnd()

    # 🟡 keyframe cubes
    gl.glColor4f(*_GL_CAM_KEY)
    gl.glLineWidth(1.4)
    for p in pts:
        _draw_wireframe_cube_3d(p[0], p[2], -p[1], 1.2)

    # camera marker: flies the path while playing, else parked at key 0
    if live_t is not None:
        pos = seq_node.pos_at(live_t) or pts[0]
        quat = seq_node.rot_at(live_t) or (nd.rotate if nd else (1.0, 0.0, 0.0, 0.0))
        gl.glColor4f(*_GL_CAM_LIVE)
        gl.glLineWidth(2.2)
        # live facing line all the way to what it's looking at
        a = aim_point(pos, quat, reach)
        gl.glBegin(gl.GL_LINES)
        gl.glVertex3f(pos[0], pos[2], -pos[1])
        gl.glVertex3f(a[0], a[2], -a[1])
        gl.glEnd()
    else:
        pos = pts[0]
        quat = seq_node.rot_at(keys[0].time) if keys else None
        quat = quat or (nd.rotate if nd else (1.0, 0.0, 0.0, 0.0))
        gl.glColor4f(*_GL_CAM_PATH)
        gl.glLineWidth(1.6)
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
        from cs_camera_preview import is_camera
    except Exception:
        is_camera = lambda nd: False

    for seq_node in seq.nodes:
        if selected_node_id is not None and seq_node.node_id != selected_node_id:
            continue
        nd = movie_data.node_defs.get(seq_node.node_id)
        # Cutscene cameras get the AM3D-style treatment (flight path + aim lines
        # + a frustum marker) instead of the generic purple actor path.
        if is_camera(nd):
            try:
                _draw_camera_track(canvas, movie_data, seq, seq_node, nd, live_t)
            except Exception as e:
                print(f"[movie] camera track draw failed: {e}")
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
