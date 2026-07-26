"""
sequence_placement.py — mouse/keyboard interaction for placing an imported
cinematic sequence.

While a placement is active the imported sequence follows the cursor as a cyan
ghost (drawn by canvas/movie_renderer.py). Left click drops it, Escape cancels.
Nothing is created and nothing is written until the drop -- cancelling costs
nothing.

Wired into canvas/input_handler.py as three early-return checks, so placement
mode takes priority over selection and dragging without altering any of that
existing logic:

    if sequence_placement.handle_mouse_move(self.canvas, event):  return
    if sequence_placement.handle_mouse_press(self.canvas, event): return
    if sequence_placement.handle_key(self.canvas, event):         return

Each returns True only when a placement is genuinely active and it consumed the
event, so normal editing is untouched the rest of the time.
"""

from __future__ import annotations

import math


# ── state access ───────────────────────────────────────────────────────────────

def active_group(canvas):
    """The PlacementGroup currently being placed, or None."""
    mw = getattr(canvas, "main_window", None)
    if mw is None:
        return None
    group = getattr(mw, "pending_sequence", None)
    if group is None or getattr(group, "committed", False):
        return None
    return group


def begin(main_window, group, snap_to_terrain: bool = True):
    """Start placing `group`. It will follow the cursor until clicked."""
    main_window.pending_sequence = group
    main_window.pending_sequence_snap = snap_to_terrain
    print(f"[seq] placing '{group.name}' - move the mouse, click to drop, Esc to cancel")


def cancel(main_window):
    """Abandon the placement. Nothing was written, so nothing to undo."""
    group = getattr(main_window, "pending_sequence", None)
    main_window.pending_sequence = None
    if group is not None:
        print(f"[seq] placement of '{group.name}' cancelled - nothing was written")
    return group is not None


# ── cursor -> world ────────────────────────────────────────────────────────────

def _cursor_world(canvas, event):
    """World position under the cursor, with terrain height when available.

    2D uses screen_to_world directly. In 3D that mapping is only meaningful for
    a top-down-ish view, so placement there is best treated as coarse -- drop it
    roughly and fine-tune with the gizmo afterwards.
    """
    try:
        pos = event.localPos()
        sx, sy = pos.x(), pos.y()
    except Exception:
        return None
    if not hasattr(canvas, "screen_to_world"):
        return None
    try:
        wx, wy = canvas.screen_to_world(sx, sy)
    except Exception:
        return None

    wz = None
    mw = getattr(canvas, "main_window", None)
    if getattr(mw, "pending_sequence_snap", True):
        getter = getattr(canvas, "get_terrain_height_at", None)
        if callable(getter):
            try:
                wz = float(getter(wx, wy))
            except Exception:
                wz = None
    if wz is None:
        group = active_group(canvas)
        wz = group.origin[2] if group else 0.0
    return (float(wx), float(wy), float(wz))


# ── handlers ───────────────────────────────────────────────────────────────────

def handle_mouse_move(canvas, event) -> bool:
    group = active_group(canvas)
    if group is None:
        return False
    world = _cursor_world(canvas, event)
    if world is None:
        return False
    group.move_to(world)
    canvas.update()
    return True


def handle_mouse_press(canvas, event) -> bool:
    """Left click drops the sequence; right click cancels."""
    group = active_group(canvas)
    if group is None:
        return False

    try:
        from PyQt5.QtCore import Qt
        button = event.button()
    except Exception:
        return False

    mw = getattr(canvas, "main_window", None)

    if button == Qt.RightButton:
        cancel(mw)
        canvas.update()
        return True

    if button != Qt.LeftButton:
        return False

    world = _cursor_world(canvas, event)
    if world is not None:
        group.move_to(world)

    result = commit(canvas, group)
    canvas.update()
    print(f"[seq] dropped '{group.name}' at "
          f"({group.origin[0]:.1f}, {group.origin[1]:.1f}, {group.origin[2]:.1f})"
          f"  {result}")
    return True


def handle_key(canvas, event) -> bool:
    group = active_group(canvas)
    if group is None:
        return False
    try:
        from PyQt5.QtCore import Qt
        key = event.key()
    except Exception:
        return False

    if key == Qt.Key_Escape:
        cancel(getattr(canvas, "main_window", None))
        canvas.update()
        return True

    # Enter drops it where it currently sits, for keyboard-only placement.
    if key in (Qt.Key_Return, Qt.Key_Enter):
        commit(canvas, group)
        canvas.update()
        return True

    return False


# ── picking sequence handles in the viewport ───────────────────────────────────
#
# A sequence node whose entity exists in the level is selected by clicking that
# entity -- it is an ordinary entity and moving it already drags its keyframes
# along (sequence_link). What is NOT otherwise reachable is the sequence's OWN
# geometry: the keyframe diamonds along a path, and the grey rest marker of a
# node whose entity this level does not have. Both are drawn but had nothing
# behind them. These make them clickable and draggable, in 2D AND in 3D.

# In 3D the markers are hit by a RAY, the same way models / fallback boxes /
# marker cubes are (map_canvas_gpu.select_entity_3d): unproject the cursor to a
# world ray and intersect the marker's own box, so you click the SHAPE and the
# nearest one along the ray wins. In 2D the markers are drawn at a fixed pixel
# size, so the test is the drawn square — the same test the entity squares get
# (input_handler.get_entity_at_position).
#
# World half-extents below are exactly what movie_renderer draws:
#   diamond  _draw_diamond_3d(..., 0.8)        -> 0.4
#   cam key  _draw_wireframe_cube_3d(..., 1.2) -> 0.6
#   rest     _draw_wireframe_cube_3d(..., 1.5) -> 0.75
_HALF_DIAMOND = 0.4
_HALF_CAM_KEY = 0.6
_HALF_REST    = 0.75

_MARKER_2D_HALF_PX = 5      # _draw_diamond_2d / ghost square are drawn at r=5
PICK_RADIUS_PX = 8          # 3D rescue: a marker too small to ray-hit at range

_MODE_3D = 1        # map_canvas_gpu.MODE_3D


def _selected_sequence(canvas):
    mw = getattr(canvas, "main_window", None)
    if mw is None:
        return None, None
    return getattr(mw, "movie_data", None), getattr(mw, "selected_movie_sequence", None)


def _is_3d(canvas) -> bool:
    return getattr(canvas, "mode", 0) == _MODE_3D


def _gl_matrices(canvas):
    """(viewport, modelview, projection, dpr) for the live 3D view, or None.

    Rebuilt exactly like `map_canvas_gpu.select_entity_3d` and
    `Gizmo3D.reproject_for_hit` -- FOV 50, the same as the render pass -- so a
    click lands where the marker was actually drawn.
    """
    try:
        from OpenGL.GL import (glMatrixMode, glLoadIdentity, glGetIntegerv,
                               glGetDoublev, GL_PROJECTION, GL_MODELVIEW,
                               GL_VIEWPORT, GL_MODELVIEW_MATRIX,
                               GL_PROJECTION_MATRIX)
        from OpenGL.GLU import gluPerspective, gluLookAt
        canvas.makeCurrent()
        w = canvas.width()
        h = max(canvas.height(), 1)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(50, w / float(h), 0.1, 10000.0)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        cam = canvas.camera_3d
        gluLookAt(cam.position[0], cam.position[1], cam.position[2],
                  *cam.get_look_at(), 0, 1, 0)
        return (glGetIntegerv(GL_VIEWPORT),
                glGetDoublev(GL_MODELVIEW_MATRIX),
                glGetDoublev(GL_PROJECTION_MATRIX),
                float(canvas.devicePixelRatio()))
    except Exception as exc:
        print(f"[seq] 3D pick matrices unavailable: {exc}")
        return None


def _screen_projector(canvas):
    """world (x, y, z) -> (screen_x, screen_y) in LOGICAL pixels, or None.

    One projector for both views so PICK_RADIUS_PX means the same thing in
    each. In 3D, points behind the camera project to None.
    """
    if not _is_3d(canvas):
        w2s = getattr(canvas, "world_to_screen", None)
        if w2s is None:
            return None

        def project_2d(x, y, z):
            try:
                return w2s(x, y)
            except Exception:
                return None
        return project_2d

    mats = _gl_matrices(canvas)
    if mats is None:
        return None
    viewport, modelview, projection, dpr = mats
    vph = float(viewport[3])
    from OpenGL.GLU import gluProject

    def project_3d(x, y, z):
        try:
            p = gluProject(x, z, -y, modelview, projection, viewport)
        except Exception:
            return None
        if p is None or not (0.0 <= p[2] <= 1.0):
            return None                      # behind the camera / clipped
        return (p[0] / dpr, (vph - p[1]) / dpr)
    return project_3d


def _is_camera_node(nd) -> bool:
    """Camera nodes get bigger cube markers than the actor diamonds."""
    try:
        from canvas.cs_camera_preview import is_camera
        return bool(is_camera(nd))
    except Exception:
        name = getattr(nd, "name", "") or ""
        return name.startswith("CameraCinematic") or "Camera.Cinematic" in name


def _pick_targets(canvas, movie_data, seq):
    """Everything grabbable in `seq`, as dicts carrying the marker's own size.

    Mirrors what the renderers actually DRAW: only the selected node when one
    is picked in the Sequences tab, a node's rest marker only when its entity
    is missing from the level (otherwise the entity itself is the handle, and
    moving it already drags the path along), and each marker's `half` is the
    half-extent movie_renderer gives it — so the ray hits the shape you see.
    """
    mw = getattr(canvas, "main_window", None)
    only = getattr(mw, "selected_movie_node_id", None)
    loaded = {e.id for e in (getattr(canvas, "entities", None) or [])}

    out = []
    for seq_node in seq.nodes:
        if only is not None and seq_node.node_id != only:
            continue
        nd = movie_data.node_defs.get(seq_node.node_id)
        half = _HALF_CAM_KEY if _is_camera_node(nd) else _HALF_DIAMOND
        for i, k in enumerate(seq_node.all_pos_keys()):
            out.append({"kind": "key", "node_id": seq_node.node_id, "index": i,
                        "time": k.time, "world": (k.x, k.y, k.z), "half": half})
        if nd is not None and nd.entity_id not in loaded:
            out.append({"kind": "node", "node_id": seq_node.node_id, "index": -1,
                        "time": 0.0, "world": tuple(nd.pos), "half": _HALF_REST})
    return out


# ── ray casting (3D) ───────────────────────────────────────────────────────────

def _pick_ray(canvas, screen_x, screen_y):
    """(origin, direction) in GL space for the cursor, or None.

    Built exactly like `map_canvas_gpu.select_entity_3d`: unproject the pixel at
    both depths and normalise, so marker hits and entity hits agree about where
    the ray is.
    """
    mats = _gl_matrices(canvas)
    if mats is None:
        return None
    viewport, modelview, projection, dpr = mats
    from OpenGL.GLU import gluUnProject
    px = float(screen_x) * dpr
    py = float(viewport[3]) - float(screen_y) * dpr
    try:
        near = gluUnProject(px, py, 0.0, modelview, projection, viewport)
        far  = gluUnProject(px, py, 1.0, modelview, projection, viewport)
    except Exception as exc:
        print(f"[seq] pick ray unavailable: {exc}")
        return None
    if near is None or far is None:
        return None
    d = (far[0] - near[0], far[1] - near[1], far[2] - near[2])
    n = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
    if n < 1e-10:
        return None
    return ((float(near[0]), float(near[1]), float(near[2])),
            (d[0] / n, d[1] / n, d[2] / n))


def _ray_box_t(origin, direction, centre, half):
    """Slab test: distance along the ray to an axis-aligned box, or None.

    Same shape as `map_canvas_gpu._ray_aabb_intersect`, kept local so picking
    never depends on importing the GL-heavy canvas package.
    """
    tmin, tmax = float("-inf"), float("inf")
    for i in range(3):
        o, d, c = origin[i], direction[i], centre[i]
        if abs(d) < 1e-12:                      # parallel to this slab
            if abs(o - c) > half:
                return None
            continue
        t1 = (c - half - o) / d
        t2 = (c + half - o) / d
        if t1 > t2:
            t1, t2 = t2, t1
        tmin = max(tmin, t1)
        tmax = min(tmax, t2)
        if tmin > tmax:
            return None
    if tmin > 0.0:
        return tmin
    return tmax if tmax > 0.0 else None          # origin inside the box


def _raycast_3d(canvas, screen_x, screen_y, targets):
    """Closest marker along the cursor ray, or None. GL space — the markers are
    axis-aligned there, which is also axis-aligned in world (world x,y,z ->
    gl x,z,-y is an axis permutation)."""
    ray = _pick_ray(canvas, screen_x, screen_y)
    if ray is None:
        return None
    origin, direction = ray
    best, best_t = None, float("inf")
    for tgt in targets:
        wx, wy, wz = tgt["world"]
        t = _ray_box_t(origin, direction, (wx, wz, -wy), tgt["half"])
        if t is not None and t < best_t:
            best_t, best = t, tgt
    return best


def keyframe_at(canvas, screen_x, screen_y):
    """Which sequence handle is under the cursor?

    Returns {'kind', 'node_id', 'index', 'time', 'world', 'half'} or None --
    'kind' is 'key' for a keyframe marker, 'node' for a node's rest marker.
    3D casts a ray at the marker boxes (nearest along the ray wins, like every
    other 3D pick); 2D tests the drawn square. Only the sequence currently
    selected in the Sequences tab is considered, so paths you are not working
    on cannot be grabbed by accident.
    """
    movie_data, seq_name = _selected_sequence(canvas)
    if movie_data is None or not seq_name:
        return None
    seq = movie_data.get_sequence(seq_name)
    if seq is None:
        return None
    targets = _pick_targets(canvas, movie_data, seq)
    if not targets:
        return None

    if _is_3d(canvas):
        hit = _raycast_3d(canvas, screen_x, screen_y, targets)
        if hit is not None:
            return hit
        # A marker far enough away is only a pixel or two wide — the ray can
        # miss what you can plainly see. Screen proximity rescues exactly that
        # case; up close the ray above has already decided.
        return _screen_pick(canvas, screen_x, screen_y, targets,
                            float(PICK_RADIUS_PX), circle=True)

    # 2D markers are drawn at a FIXED pixel size whatever the zoom, so the hit
    # test is that square — the same test the entity squares get.
    return _screen_pick(canvas, screen_x, screen_y, targets,
                        float(_MARKER_2D_HALF_PX), circle=False)


def _screen_pick(canvas, screen_x, screen_y, targets, extent_px, circle):
    """Nearest marker whose drawn footprint contains the cursor, or None."""
    project = _screen_projector(canvas)
    if project is None:
        return None
    best, best_d = None, float("inf")
    near_tgt, near_d, near_at = None, float("inf"), None
    for tgt in targets:
        sp = project(*tgt["world"])
        if sp is None:
            continue
        dx, dy = sp[0] - screen_x, sp[1] - screen_y
        d = math.hypot(dx, dy)
        if d < near_d:
            near_d, near_tgt, near_at = d, tgt, sp
        inside = (d <= extent_px if circle
                  else (abs(dx) <= extent_px and abs(dy) <= extent_px))
        if inside and d < best_d:
            best_d, best = d, tgt
    if best is None and near_tgt is not None:
        # Say WHAT you nearly hit and where it is on screen — "nearest 53 px"
        # alone can't tell a near miss from aiming at the wrong thing entirely.
        # ASCII only: a cp1252 console raises UnicodeEncodeError on fancy
        # glyphs, and this print sits in the click path.
        print("[seq] missed by %.0f px - nearest is node %s %s at (%.0f, %.0f)"
              % (near_d, near_tgt["node_id"],
                 "rest marker" if near_tgt["kind"] == "node"
                 else "key %d" % near_tgt["index"],
                 near_at[0], near_at[1]))
    return best


def _select_backing_entity(canvas, node_id) -> bool:
    """Select the world entity the node drives, exactly as clicking it would.

    Clicking a handle should behave like clicking the object: the entity gets
    the selection AND the gizmo, so it can be moved the ordinary way (which
    drags the whole path along via SequenceLink). No-op for a node whose entity
    this level does not have -- there the marker itself is the only handle.
    """
    mw = getattr(canvas, "main_window", None)
    md = getattr(mw, "movie_data", None) if mw else None
    nd = md.node_defs.get(node_id) if md is not None else None
    if nd is None:
        return False
    ent = next((e for e in (getattr(canvas, "entities", None) or [])
                if e.id == nd.entity_id), None)
    if ent is None:
        return False
    try:
        if hasattr(canvas, "select_entity_with_children"):
            canvas.selected = canvas.select_entity_with_children(ent)
        else:
            canvas.selected = [ent]
        canvas.selected_entity = ent
        if hasattr(canvas, "gizmo_renderer"):
            canvas.gizmo_renderer.update_gizmo_for_entity(ent)
        if hasattr(canvas, "gizmo_3d"):
            canvas.gizmo_3d.move_to(ent)
        if hasattr(canvas, "entitySelected"):
            canvas.entitySelected.emit(ent)
        canvas.selection_modified = True
    except Exception as exc:
        print(f"[seq] selecting the node's entity failed: {exc}")
        return False
    return True


def _highlight_in_tree(mw, node_id):
    """Move the Sequences tab's selection to the node just clicked.

    Signals are blocked: `selected_movie_node_id` is already set by the caller,
    and re-entering `_on_sequence_selected` would only redo that work. This is
    purely so "selected" is VISIBLE somewhere when you pick a marker in the
    viewport.
    """
    tree = getattr(mw, "sequences_tree", None)
    seq_name = getattr(mw, "selected_movie_sequence", None)
    if tree is None or not seq_name:
        return
    try:
        from PyQt5.QtCore import Qt
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            if top.data(0, Qt.UserRole) != seq_name:
                continue
            for j in range(top.childCount()):
                child = top.child(j)
                if child.data(0, Qt.UserRole + 1) == node_id:
                    was = tree.blockSignals(True)
                    tree.setCurrentItem(child)
                    tree.blockSignals(was)
                    return
    except Exception as exc:
        print(f"[seq] tree highlight skipped: {exc}")


def begin_keyframe_drag(canvas, screen_x, screen_y) -> bool:
    """Grab a sequence handle if one is under the cursor.

    Selects the node (and its entity, when the level has one) and arms a drag.
    True when the click was consumed, so normal selection must not run.
    """
    hit = keyframe_at(canvas, screen_x, screen_y)
    if hit is None:
        return False
    mw = canvas.main_window
    mw.selected_movie_node_id = hit["node_id"]
    mw.dragging_keyframe = hit
    picked_entity = _select_backing_entity(canvas, hit["node_id"])
    _highlight_in_tree(mw, hit["node_id"])
    if hit["kind"] == "node":
        print("[seq] grabbed node %s (rest marker) - the whole path follows"
              % hit["node_id"])
    else:
        print("[seq] grabbed keyframe %d (t=%.2f) of node %s%s"
              % (hit["index"], hit["time"], hit["node_id"],
                 " (entity selected - gizmo is on it)" if picked_entity else ""))
    canvas.update()
    return True


def _drag_world(canvas, event, anchor):
    """Cursor position in world space for a drag anchored at `anchor`.

    2D unprojects the cursor straight through the top-down mapping. 3D
    intersects the view ray with the HORIZONTAL plane through the anchor, so
    the handle slides under the cursor at its own height instead of snapping
    down to the ground (a camera flight path is rarely on the terrain).
    """
    try:
        p = event.localPos()
        sx, sy = p.x(), p.y()
    except Exception:
        return None

    if not _is_3d(canvas):
        return _cursor_world(canvas, event)

    mats = _gl_matrices(canvas)
    if mats is None:
        return None
    viewport, modelview, projection, dpr = mats
    from OpenGL.GLU import gluUnProject
    vph = float(viewport[3])
    px, py = sx * dpr, vph - sy * dpr
    try:
        near = gluUnProject(px, py, 0.0, modelview, projection, viewport)
        far  = gluUnProject(px, py, 1.0, modelview, projection, viewport)
    except Exception:
        return None
    if near is None or far is None:
        return None

    return _ray_plane_world(near, far, float(anchor[2]))   # world Z is GL Y


def _ray_plane_world(near, far, plane_y):
    """Where a GL view ray crosses the horizontal plane y = plane_y, in WORLD
    coords. GL (gx, gy, gz) maps back to world (gx, -gz, gy) — the inverse of
    the world(x, y, z) -> gl(x, z, -y) the renderers use."""
    dy = far[1] - near[1]
    if abs(dy) < 1e-9:                  # ray parallel to the plane
        return None
    t = (plane_y - near[1]) / dy
    if t < 0:                           # plane is behind the camera
        return None
    gx = near[0] + t * (far[0] - near[0])
    gz = near[2] + t * (far[2] - near[2])
    return (float(gx), float(-gz), float(plane_y))


def _snap_height(canvas, x, y):
    """Terrain height at (x, y) when snapping is on, else None."""
    mw = getattr(canvas, "main_window", None)
    want = (getattr(mw, "pending_sequence_snap", False)
            or (_is_3d(canvas) and getattr(canvas, "terrain_snap_enabled", False)))
    if not want:
        return None
    getter = getattr(canvas, "get_terrain_height_at", None)
    if not callable(getter):
        return None
    try:
        return float(getter(x, y))
    except Exception:
        return None


def update_keyframe_drag(canvas, event) -> bool:
    mw = getattr(canvas, "main_window", None)
    hit = getattr(mw, "dragging_keyframe", None) if mw else None
    if not hit:
        return False
    world = _drag_world(canvas, event, hit["world"])
    if world is None:
        return False

    link = getattr(mw, "sequence_link", None)
    seq_name = getattr(mw, "selected_movie_sequence", None)
    if link is None or not seq_name:
        return False

    entity_id = _entity_for_node(mw, hit["node_id"])
    if not entity_id:
        return False

    # Keep the handle's own height unless terrain snapping is on.
    z = _snap_height(canvas, world[0], world[1])
    if z is None:
        z = hit["world"][2]
    target = (world[0], world[1], z)

    if hit["kind"] == "node":
        # The rest marker carries the whole shot: same rigid follow an entity
        # move gets. Measured from the LAST cursor position, so re-anchor.
        link.on_entity_moved(entity_id, hit["world"], target)
        _shift_node_in_memory(mw, hit["node_id"],
                              (target[0] - hit["world"][0],
                               target[1] - hit["world"][1],
                               target[2] - hit["world"][2]))
        hit["world"] = target
    else:
        link.move_keyframe(entity_id, seq_name, hit["index"], target)
        _set_key_in_memory(mw, seq_name, hit["node_id"], hit["index"], target)
    canvas.update()
    return True


# The renderers draw from main_window.movie_data while the writes go through
# SequenceLink's own ElementTree, so the drag has to touch both -- otherwise the
# path only jumps to its new shape after the post-drag reload.

def _set_key_in_memory(mw, seq_name, node_id, index, pos):
    md = getattr(mw, "movie_data", None)
    seq = md.get_sequence(seq_name) if md is not None else None
    node = seq.node_by_id(node_id) if seq is not None else None
    keys = node.all_pos_keys() if node is not None else []
    if 0 <= index < len(keys):
        k = keys[index]
        k.x, k.y, k.z = float(pos[0]), float(pos[1]), float(pos[2])


def _shift_node_in_memory(mw, node_id, delta):
    md = getattr(mw, "movie_data", None)
    if md is None:
        return
    dx, dy, dz = delta
    nd = md.node_defs.get(node_id)
    if nd is not None:
        nd.pos = (nd.pos[0] + dx, nd.pos[1] + dy, nd.pos[2] + dz)
    for seq in md.sequences:          # on_entity_moved shifts every sequence
        node = seq.node_by_id(node_id)
        if node is None:
            continue
        for k in node.all_pos_keys():
            k.x += dx
            k.y += dy
            k.z += dz


def end_keyframe_drag(canvas) -> bool:
    mw = getattr(canvas, "main_window", None)
    hit = getattr(mw, "dragging_keyframe", None) if mw else None
    if not hit:
        return False
    mw.dragging_keyframe = None
    link = getattr(mw, "sequence_link", None)
    if link is not None and getattr(link, "dirty", False):
        link.save()
        print("[seq] keyframe move saved")
        md = getattr(mw, "movie_data", None)
        if md is not None and getattr(md, "source_path", None):
            try:
                from movie_data import MovieData
                mw.movie_data = MovieData.load(md.source_path)
            except Exception:
                pass
    canvas.update()
    return True


def _entity_for_node(main_window, node_id):
    md = getattr(main_window, "movie_data", None)
    if md is None:
        return None
    nd = md.node_defs.get(node_id)
    return nd.entity_id if nd is not None else None


# ── commit ─────────────────────────────────────────────────────────────────────

def commit(canvas, group) -> dict:
    """Write the placement: rebase the bundle, merge it, create the entities.

    Entity creation is delegated to the caller-provided hook
    `main_window.sequence_commit_hook(group)` when present, so this module never
    duplicates the entity importer. Without a hook the sequence is still merged
    and rebased -- the entities just have to be placed separately.
    """
    mw = getattr(canvas, "main_window", None)
    hook = getattr(mw, "sequence_commit_hook", None)
    if callable(hook):
        try:
            result = hook(group)
        except Exception as exc:
            print(f"   WARNING: sequence commit hook failed: {exc}")
            result = {"error": str(exc)}
    else:
        # No importer wired up: rebase the bundle in place so the merge that
        # happens later lands in the right spot.
        try:
            import sequence_export_import as sx
            sx.rebase_bundle(group.bundle, group.origin)
            result = {"rebased": True, "entities": "not created (no hook)"}
        except Exception as exc:
            result = {"error": str(exc)}

    group.committed = True
    if mw is not None:
        mw.pending_sequence = None
    return result
