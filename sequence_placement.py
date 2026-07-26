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
