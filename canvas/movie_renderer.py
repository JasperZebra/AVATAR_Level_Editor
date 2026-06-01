"""
canvas/movie_renderer.py — 2D and 3D rendering for moviedata.xml sequences.

Draws:
  • Purple dashed path lines connecting keyframe positions
  • Diamond markers at each keyframe
  • Orange dot markers for event keys (particle start/stop)
  • Grey cube fallback for NodeDef entities not found in the loaded entity list

Only renders the currently selected sequence (canvas.main_window.selected_movie_sequence).
"""

import OpenGL.GL as gl
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPen, QBrush, QColor, QPolygonF, QFont

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
        painter.setPen(QPen(_PATH_COLOR, 1.5, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
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
    painter.setPen(QPen(Qt.GlobalColor.white, 0.5))
    painter.setBrush(QBrush(color))
    painter.drawPolygon(pts)


def _draw_ghost_nodes_2d(painter, canvas, movie_data, seq, selected_node_id=None):
    """Draw a small grey square for nodes whose EntityId isn't in the loaded entity list."""
    loaded_ids = {e.id for e in (canvas.entities or [])}
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
        painter.setPen(QPen(Qt.GlobalColor.white, 0.5))
        painter.setBrush(QBrush(ghost))
        painter.drawRect(QRectF(sx - r, sy - r, r * 2, r * 2))


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

    gl.glDisable(gl.GL_LIGHTING)
    gl.glDisable(gl.GL_TEXTURE_2D)
    gl.glDisable(gl.GL_DEPTH_TEST)   # always on top like shape points

    for seq_node in seq.nodes:
        if selected_node_id is not None and seq_node.node_id != selected_node_id:
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
    loaded_ids = {e.id for e in (canvas.entities or [])}
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
