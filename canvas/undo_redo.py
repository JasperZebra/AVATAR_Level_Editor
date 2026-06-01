"""Undo/Redo system for entity move and rotation operations (100-edit history)"""

from collections import deque


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_gizmo(canvas):
    if hasattr(canvas, 'gizmo_renderer') and canvas.gizmo_renderer:
        return canvas.gizmo_renderer.rotation_gizmo
    return None


def _apply_entity_state(entity, state, canvas):
    """Apply a saved (x, y, z) or (x, y, z, rotation) state to an entity."""
    entity.x, entity.y, entity.z = state[0], state[1], state[2]
    if len(state) >= 4:
        gizmo = _get_gizmo(canvas)
        if gizmo:
            gizmo.update_entity_rotation(entity, state[3])
    if hasattr(canvas, 'update_entity_xml'):
        canvas.update_entity_xml(entity)
    if hasattr(canvas, 'mark_entity_modified'):
        canvas.mark_entity_modified(entity)
    if hasattr(canvas, 'entity_renderer') and canvas.entity_renderer:
        canvas.entity_renderer.invalidate_entity_cache(entity)


def _post_op(canvas):
    """Refresh display after undo/redo."""
    if hasattr(canvas, 'invalidate_position_cache'):
        canvas.invalidate_position_cache()
    if hasattr(canvas, 'selected_entity') and canvas.selected_entity:
        if hasattr(canvas, 'gizmo_renderer'):
            canvas.gizmo_renderer.update_gizmo_for_entity(canvas.selected_entity)
        if hasattr(canvas, 'position_update'):
            e = canvas.selected_entity
            canvas.position_update.emit(e, (e.x, e.y, e.z))
    canvas.update()


# ---------------------------------------------------------------------------
# Command classes
# ---------------------------------------------------------------------------

class MoveCommand:
    """Records a position change for one or more entities.

    before / after: list of (entity, x, y, z) tuples.
    """

    def __init__(self, before, after):
        self.before = before  # [(entity, x, y, z), ...]
        self.after = after

    def undo(self, canvas):
        for entity, x, y, z in self.before:
            _apply_entity_state(entity, (x, y, z), canvas)

    def redo(self, canvas):
        for entity, x, y, z in self.after:
            _apply_entity_state(entity, (x, y, z), canvas)


class RotateCommand:
    """Records a rotation (and optional position) change for one or more entities.

    before / after: list of (entity, x, y, z, rotation) tuples.
    Positions are included because group rotation moves entities around a centre.
    """

    def __init__(self, before, after):
        self.before = before  # [(entity, x, y, z, rotation), ...]
        self.after = after

    def undo(self, canvas):
        for item in self.before:
            entity, x, y, z, rotation = item
            _apply_entity_state(entity, (x, y, z, rotation), canvas)

    def redo(self, canvas):
        for item in self.after:
            entity, x, y, z, rotation = item
            _apply_entity_state(entity, (x, y, z, rotation), canvas)


class ShapePointCommand:
    """Records a hidShapePoints drag (move one or all points on an entity).

    before / after: dicts with keys:
        entity  – the Entity object
        points  – list of (x, y, z) tuples (one per <Point> element)
        ex, ey, ez – entity.x/y/z at snapshot time (only differs for pt0 drags)
    """

    def __init__(self, before, after):
        self.before = before
        self.after = after

    def _apply(self, snap, canvas):
        entity = snap['entity']
        entity.x, entity.y, entity.z = snap['ex'], snap['ey'], snap['ez']
        if hasattr(entity, 'xml_element') and entity.xml_element is not None:
            field = entity.xml_element.find("field[@name='hidShapePoints']")
            if field is not None:
                pts = field.findall('Point')
                for i, (px, py, pz) in enumerate(snap['points']):
                    if i < len(pts):
                        pts[i].text = f"{px},{py},{pz}"
        if hasattr(canvas, 'update_entity_xml'):
            canvas.update_entity_xml(entity)
        if hasattr(canvas, 'mark_entity_modified'):
            canvas.mark_entity_modified(entity)
        er = getattr(canvas, 'entity_renderer', None)
        if er:
            er.invalidate_entity_cache(entity)
        if hasattr(canvas, '_auto_save_entity_changes'):
            canvas._auto_save_entity_changes(entity)

    def undo(self, canvas):
        self._apply(self.before, canvas)

    def redo(self, canvas):
        self._apply(self.after, canvas)


class Rotate3DCommand:
    """Records a 3-axis rotation change made by the 3-D gizmo.

    before / after: list of (entity, ax, ay, az) tuples (game-coord hidAngles).
    """

    def __init__(self, before, after):
        self.before = before
        self.after  = after

    def _apply(self, states, canvas):
        from .gizmo_3d import Gizmo3D
        for entity, ax, ay, az in states:
            Gizmo3D._write_angles(entity, ax, ay, az, canvas)
            if hasattr(canvas, 'update_entity_xml'):
                canvas.update_entity_xml(entity)
        _post_op(canvas)

    def undo(self, canvas):
        self._apply(self.before, canvas)

    def redo(self, canvas):
        self._apply(self.after, canvas)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class UndoRedoManager:
    """Manages a 100-edit undo/redo history for entity operations."""

    MAX_HISTORY = 100

    def __init__(self):
        self._undo_stack = deque(maxlen=self.MAX_HISTORY)
        self._redo_stack = deque(maxlen=self.MAX_HISTORY)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def push(self, command):
        """Push a new command.  Clears redo history."""
        self._undo_stack.append(command)
        self._redo_stack.clear()

    def undo(self, canvas):
        if not self._undo_stack:
            print("Undo: nothing to undo")
            return False
        command = self._undo_stack.pop()
        command.undo(canvas)
        self._redo_stack.append(command)
        _post_op(canvas)
        print(f"Undo: {type(command).__name__} ({len(self._undo_stack)} left in stack)")
        return True

    def redo(self, canvas):
        if not self._redo_stack:
            print("Redo: nothing to redo")
            return False
        command = self._redo_stack.pop()
        command.redo(canvas)
        self._undo_stack.append(command)
        _post_op(canvas)
        print(f"Redo: {type(command).__name__} ({len(self._undo_stack)} in stack)")
        return True

    def can_undo(self):
        return len(self._undo_stack) > 0

    def can_redo(self):
        return len(self._redo_stack) > 0

    def clear(self):
        self._undo_stack.clear()
        self._redo_stack.clear()

    # ------------------------------------------------------------------
    # Snapshot helpers (called by canvas/input/gizmo code)
    # ------------------------------------------------------------------

    @staticmethod
    def snapshot_positions(entities):
        """Return [(entity, x, y, z), ...] for the given entity list."""
        return [(e, e.x, e.y, e.z) for e in entities if hasattr(e, 'x')]

    @staticmethod
    def snapshot_rotations(entities, canvas):
        """Return [(entity, x, y, z, rotation), ...] including current positions."""
        gizmo = _get_gizmo(canvas)
        result = []
        for e in entities:
            if not hasattr(e, 'x'):
                continue
            rotation = 0.0
            if gizmo:
                rotation = gizmo.extract_entity_rotation(e)
            result.append((e, e.x, e.y, e.z, rotation))
        return result
