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

PICK_RADIUS_PX = 8          # floor: a distant marker is still an 8 px target
_MAX_PICK_PX = 90.0         # ceiling: a marker under your nose can't own the view

# World-space radius of each handle's DRAWN marker (movie_renderer sizes: ghost
# cube 1.5, camera key cube 1.2, diamond 0.8 — all full extents), so the pick
# area tracks what you can see. Without this the marker filling half the screen
# was only clickable within 8 px of its centre, which reads as "not clickable".
_MARKER_RADIUS = {"key": 0.75, "node": 0.9}

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


def _pick_targets(canvas, movie_data, seq):
    """Everything grabbable in `seq`, as (kind, node_id, index, time, world).

    Mirrors what the renderers actually DRAW: only the selected node when one
    is picked in the Sequences tab, and a node's rest marker only when its
    entity is missing from the level (otherwise the entity itself is the
    handle, and moving it already drags the path along).
    """
    mw = getattr(canvas, "main_window", None)
    only = getattr(mw, "selected_movie_node_id", None)
    loaded = {e.id for e in (getattr(canvas, "entities", None) or [])}

    out = []
    for seq_node in seq.nodes:
        if only is not None and seq_node.node_id != only:
            continue
        for i, k in enumerate(seq_node.all_pos_keys()):
            out.append(("key", seq_node.node_id, i, k.time, (k.x, k.y, k.z)))
        nd = movie_data.node_defs.get(seq_node.node_id)
        if nd is not None and nd.entity_id not in loaded:
            out.append(("node", seq_node.node_id, -1, 0.0, tuple(nd.pos)))
    return out


def keyframe_at(canvas, screen_x, screen_y):
    """Which sequence handle is under the cursor?

    Returns {'kind', 'node_id', 'index', 'time', 'world'} or None -- 'kind' is
    'key' for a keyframe diamond, 'node' for a node's rest marker. Only the
    sequence currently selected in the Sequences tab is considered, so paths
    you are not working on cannot be grabbed by accident.
    """
    movie_data, seq_name = _selected_sequence(canvas)
    if movie_data is None or not seq_name:
        return None
    seq = movie_data.get_sequence(seq_name)
    if seq is None:
        return None
    project = _screen_projector(canvas)
    if project is None:
        return None

    best = None
    best_score = 1.0            # normalised: distance / this marker's radius
    nearest = None              # for the miss diagnostic
    for kind, node_id, index, t, world in _pick_targets(canvas, movie_data, seq):
        sp = project(*world)
        if sp is None:
            continue
        d = math.hypot(sp[0] - screen_x, sp[1] - screen_y)
        if nearest is None or d < nearest:
            nearest = d
        r = _marker_radius_px(project, world, sp,
                              _MARKER_RADIUS.get(kind, 0.75))
        score = d / r
        if score <= best_score:
            best_score = score
            best = {"kind": kind, "node_id": node_id, "index": index,
                    "time": t, "world": world}
    if best is None and nearest is not None:
        print("[seq] no cutscene handle under the cursor (nearest %.0f px)"
              % nearest)
    return best


def _marker_radius_px(project, world, screen_pos, world_radius):
    """On-screen radius of a marker of `world_radius` sitting at `world`.

    The markers are drawn at a fixed WORLD size, so their screen size swings
    with distance -- a fixed pixel radius makes a close-up marker unclickable
    everywhere except its centre. Projecting one world-radius offset per axis
    and taking the largest gives the marker's actual screen extent.
    """
    biggest = 0.0
    for off in ((world_radius, 0.0, 0.0),
                (0.0, world_radius, 0.0),
                (0.0, 0.0, world_radius)):
        p = project(world[0] + off[0], world[1] + off[1], world[2] + off[2])
        if p is None:
            continue
        biggest = max(biggest, math.hypot(p[0] - screen_pos[0],
                                          p[1] - screen_pos[1]))
    return max(float(PICK_RADIUS_PX), min(biggest, _MAX_PICK_PX))


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
