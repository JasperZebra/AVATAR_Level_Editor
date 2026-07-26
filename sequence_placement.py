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


# ── picking keyframes in the viewport ──────────────────────────────────────────
#
# A sequence node whose entity exists in the level is selected by clicking that
# entity -- it is an ordinary entity and moving it already drags its keyframes
# along (sequence_link). What is NOT otherwise reachable is the KEYFRAMES
# themselves: the diamonds along a path are drawn but have nothing behind them.
# These make them clickable and draggable.

PICK_RADIUS_PX = 8


def _selected_sequence(canvas):
    mw = getattr(canvas, "main_window", None)
    if mw is None:
        return None, None
    return getattr(mw, "movie_data", None), getattr(mw, "selected_movie_sequence", None)


def keyframe_at(canvas, screen_x, screen_y):
    """Which keyframe is under the cursor?

    Returns {'node_id', 'index', 'time', 'world'} or None. Only considers the
    sequence currently selected in the Sequences tab, so paths you are not
    working on cannot be grabbed by accident.
    """
    movie_data, seq_name = _selected_sequence(canvas)
    if movie_data is None or not seq_name:
        return None
    seq = movie_data.get_sequence(seq_name)
    if seq is None:
        return None
    if not hasattr(canvas, "world_to_screen"):
        return None

    best = None
    best_d2 = float(PICK_RADIUS_PX) ** 2
    for seq_node in seq.nodes:
        keys = seq_node.all_pos_keys()
        for i, k in enumerate(keys):
            try:
                sx, sy = canvas.world_to_screen(k.x, k.y)
            except Exception:
                continue
            d2 = (sx - screen_x) ** 2 + (sy - screen_y) ** 2
            if d2 <= best_d2:
                best_d2 = d2
                best = {"node_id": seq_node.node_id, "index": i,
                        "time": k.time, "world": (k.x, k.y, k.z)}
    return best


def begin_keyframe_drag(canvas, screen_x, screen_y) -> bool:
    """Grab a keyframe if one is under the cursor. True if a drag started."""
    hit = keyframe_at(canvas, screen_x, screen_y)
    if hit is None:
        return False
    mw = canvas.main_window
    mw.dragging_keyframe = hit
    mw.selected_movie_node_id = hit["node_id"]
    print("[seq] grabbed keyframe %d (t=%.2f) of node %s"
          % (hit["index"], hit["time"], hit["node_id"]))
    canvas.update()
    return True


def update_keyframe_drag(canvas, event) -> bool:
    mw = getattr(canvas, "main_window", None)
    hit = getattr(mw, "dragging_keyframe", None) if mw else None
    if not hit:
        return False
    world = _cursor_world(canvas, event)
    if world is None:
        return False

    link = getattr(mw, "sequence_link", None)
    seq_name = getattr(mw, "selected_movie_sequence", None)
    if link is None or not seq_name:
        return False

    # Keep the keyframe's own height unless terrain snapping is on.
    z = world[2] if getattr(mw, "pending_sequence_snap", False) else hit["world"][2]
    entity_id = _entity_for_node(mw, hit["node_id"])
    if entity_id:
        link.move_keyframe(entity_id, seq_name, hit["index"],
                           (world[0], world[1], z))
    canvas.update()
    return True


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
