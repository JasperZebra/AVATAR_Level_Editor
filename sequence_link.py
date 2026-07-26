"""
sequence_link.py — keeps moviedata.xml in sync when you move a cinematic entity.

A cinematic sequence animates entities by EntityId, and every Position keyframe
is an ABSOLUTE world coordinate. So dragging a cinematic camera in the editor is
only half a move: the entity goes to the new place, and its whole animated path
stays behind in moviedata.xml. The shot silently breaks.

This module closes that gap. It binds entities to their moviedata nodes and,
whenever one moves, shifts that node's keyframes by the same delta -- exactly
how moving a group of entities already offsets them all together.

Two levels of use:

    link = SequenceLink.for_level(moviedata_path)
    link.on_entity_moved(entity_id, old_pos, new_pos)   # rigid path follow
    link.save()

    link.attach(editor)      # hook the editor's existing autosave path

Placement groups (the "ghost preview" import flow) use the same delta logic:
the whole imported set is one pending group that moves rigidly until committed,
then behaves like any other entity.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


def _vec3(s: str) -> list:
    return [float(x) for x in s.split(",")[:3]]


def _fmt(vals) -> str:
    return ",".join(f"{v:g}" for v in vals)


# ── the link ───────────────────────────────────────────────────────────────────

class SequenceLink:
    """Binds world entities to moviedata nodes and keeps their tracks in sync."""

    def __init__(self, moviedata_path: str):
        self.path = moviedata_path
        self.tree = ET.parse(moviedata_path)
        self.root = self.tree.getroot()
        self.dirty = False

        # EntityId -> the <Node> registry element
        self.by_entity: dict = {}
        # node Id -> [<Node> elements inside sequences]
        self.seq_nodes: dict = {}

        for n in self.root.findall("./NodeData/Node"):
            eid = n.get("EntityId")
            if eid:
                self.by_entity[eid] = n
        for seq in self.root.findall("./SequenceData/Sequence"):
            for sn in seq.findall("./Nodes/Node"):
                self.seq_nodes.setdefault(sn.get("Id"), []).append((seq, sn))

    @classmethod
    def for_level(cls, level_generated_folder: str) -> "SequenceLink | None":
        p = os.path.join(level_generated_folder, "moviedata.xml")
        return cls(p) if os.path.exists(p) else None

    # -- queries ------------------------------------------------------------

    def is_cinematic_entity(self, entity_id) -> bool:
        return str(entity_id) in self.by_entity

    def sequences_for(self, entity_id) -> list:
        """Names of the sequences that animate this entity."""
        node = self.by_entity.get(str(entity_id))
        if node is None:
            return []
        return [seq.get("Name", "?")
                for seq, _sn in self.seq_nodes.get(node.get("Id"), [])]

    def keyframe_count(self, entity_id) -> int:
        node = self.by_entity.get(str(entity_id))
        if node is None:
            return 0
        total = 0
        for _seq, sn in self.seq_nodes.get(node.get("Id"), []):
            for track in sn.findall("Track"):
                total += len(track.findall("Key"))
        return total

    # -- mutation -----------------------------------------------------------

    def on_entity_moved(self, entity_id, old_pos, new_pos) -> int:
        """Shift this entity's animated path by the same delta it just moved.

        Returns the number of keyframes moved. This is the rigid-follow
        behaviour: the shot keeps its shape, it just happens somewhere else.
        """
        node = self.by_entity.get(str(entity_id))
        if node is None:
            return 0

        dx = new_pos[0] - old_pos[0]
        dy = new_pos[1] - old_pos[1]
        dz = new_pos[2] - old_pos[2]
        if dx == dy == dz == 0:
            return 0

        # rest pose in the registry
        p = _vec3(node.get("Pos", "0,0,0"))
        node.set("Pos", _fmt((p[0] + dx, p[1] + dy, p[2] + dz)))

        moved = 0
        for _seq, sn in self.seq_nodes.get(node.get("Id"), []):
            for track in sn.findall("Track"):
                if track.get("ParamId") != "1":       # 1 = Position
                    continue
                for key in track.findall("Key"):
                    val = key.get("value")
                    if not val:
                        continue
                    k = _vec3(val)
                    key.set("value", _fmt((k[0] + dx, k[1] + dy, k[2] + dz)))
                    moved += 1
        self.dirty = True
        return moved

    def set_node_rest_pose(self, entity_id, pos, rot=None) -> bool:
        """Update only the rest pose, leaving keyframes alone.

        Use when the entity is repositioned but its animation is authored
        elsewhere (or is about to be re-authored).
        """
        node = self.by_entity.get(str(entity_id))
        if node is None:
            return False
        node.set("Pos", _fmt(pos))
        if rot is not None:
            node.set("Rotate", _fmt(rot))
        self.dirty = True
        return True

    def move_keyframe(self, entity_id, sequence_name, key_index, new_pos) -> bool:
        """Move ONE Position keyframe -- the per-keyframe editing case."""
        node = self.by_entity.get(str(entity_id))
        if node is None:
            return False
        for seq, sn in self.seq_nodes.get(node.get("Id"), []):
            if seq.get("Name") != sequence_name:
                continue
            for track in sn.findall("Track"):
                if track.get("ParamId") != "1":
                    continue
                keys = track.findall("Key")
                if 0 <= key_index < len(keys):
                    keys[key_index].set("value", _fmt(new_pos))
                    self.dirty = True
                    return True
        return False

    def path_points(self, entity_id, sequence_name=None) -> list:
        """The animated path as [(time, x, y, z)] -- for drawing it in the viewport."""
        node = self.by_entity.get(str(entity_id))
        if node is None:
            return []
        out = []
        for seq, sn in self.seq_nodes.get(node.get("Id"), []):
            if sequence_name and seq.get("Name") != sequence_name:
                continue
            for track in sn.findall("Track"):
                if track.get("ParamId") != "1":
                    continue
                for key in track.findall("Key"):
                    val = key.get("value")
                    if val:
                        x, y, z = _vec3(val)
                        out.append((float(key.get("time", 0)), x, y, z))
        out.sort(key=lambda k: k[0])
        return out

    # -- persistence --------------------------------------------------------

    def save(self) -> bool:
        if not self.dirty:
            return False
        try:
            ET.indent(self.tree, space="\t")
        except AttributeError:
            pass
        self.tree.write(self.path, encoding="utf-8", xml_declaration=True)
        self.dirty = False
        return True

    # -- editor integration -------------------------------------------------

    def attach(self, canvas):
        """Wrap the canvas's autosave so entity moves also sync moviedata.

        Non-invasive: the original method still does everything it did, this
        just runs afterwards. Safe to call twice -- it refuses to double-wrap.
        """
        if getattr(canvas, "_sequence_link_attached", False):
            return False
        original = canvas._auto_save_entity_changes
        link = self

        def wrapped(entity):
            before = getattr(entity, "_seq_last_pos", None)
            result = original(entity)
            try:
                eid = str(getattr(entity, "id", ""))
                pos = (float(entity.position[0]), float(entity.position[1]),
                       float(entity.position[2]))
                if before is not None and link.is_cinematic_entity(eid):
                    n = link.on_entity_moved(eid, before, pos)
                    if n:
                        link.save()
                        print(f"   [seq] moved {n} keyframe(s) with "
                              f"{getattr(entity, 'name', eid)}")
                entity._seq_last_pos = pos
            except Exception as exc:      # never break the user's save
                print(f"   WARNING: sequence sync skipped: {exc}")
            return result

        canvas._auto_save_entity_changes = wrapped
        canvas._sequence_link_attached = True
        canvas.sequence_link = link
        return True


# ── pending placement group (the "ghost preview" import) ───────────────────────

@dataclass
class PlacementGroup:
    """An imported sequence held as a movable preview BEFORE anything is created.

    The preview is drawn straight from the bundle, so no entities exist and
    nothing is written until commit(). Cancelling is genuinely free -- there is
    nothing to undo.

    Typical flow:
        group = PlacementGroup.from_bundle(bundle)
        group.move_to(cursor_world_pos)     # every mouse move, cheap
        ...
        group.commit(...)                   # or just drop the object to cancel
    """
    name: str
    bundle: object = None                 # SequenceBundle, for preview geometry
    entities: list = field(default_factory=list)   # populated only on commit
    link: SequenceLink = None
    origin: tuple = (0.0, 0.0, 0.0)       # where the group currently sits
    base_origin: tuple = (0.0, 0.0, 0.0)  # where the bundle's own coords sit
    committed: bool = False

    @classmethod
    def from_bundle(cls, bundle) -> "PlacementGroup":
        anchor = tuple(getattr(bundle, "anchor", (0.0, 0.0, 0.0)))
        return cls(name=bundle.name, bundle=bundle,
                   origin=anchor, base_origin=anchor)

    # -- preview ------------------------------------------------------------

    @property
    def delta(self) -> tuple:
        return (self.origin[0] - self.base_origin[0],
                self.origin[1] - self.base_origin[1],
                self.origin[2] - self.base_origin[2])

    def move_to(self, new_origin) -> None:
        """Rigidly move the whole group. Preview only -- nothing is written.

        Cheap enough to call on every mouse-move: it only updates one tuple,
        and preview geometry is offset at draw time.
        """
        self.origin = (float(new_origin[0]), float(new_origin[1]),
                       float(new_origin[2]))
        if self.entities:      # already committed -- keep real entities in step
            dx, dy, dz = self.delta
            for ent in self.entities:
                base = getattr(ent, "_seq_base_pos", ent.position)
                ent.position = (base[0] + dx, base[1] + dy, base[2] + dz)

    def preview_paths(self) -> list:
        """Live preview geometry, offset to the current origin.

        Returns [{'name', 'is_camera', 'points': [(t, x, y, z), ...]}] -- one
        entry per animated node, ready for the 2D and 3D renderers.
        """
        if self.bundle is None or self.bundle.sequence_elem is None:
            return []
        dx, dy, dz = self.delta
        registry = {n.get("Id"): n for n in self.bundle.node_defs}
        out = []
        for sn in self.bundle.sequence_elem.findall("./Nodes/Node"):
            nd = registry.get(sn.get("Id"))
            name = nd.get("Name", sn.get("Id")) if nd is not None else sn.get("Id")
            pts = []
            for track in sn.findall("Track"):
                if track.get("ParamId") != "1":
                    continue
                for key in track.findall("Key"):
                    val = key.get("value")
                    if not val:
                        continue
                    x, y, z = _vec3(val)
                    pts.append((float(key.get("time", 0)),
                                x + dx, y + dy, z + dz))
            pts.sort(key=lambda k: k[0])
            out.append({
                "name": name,
                "is_camera": name.startswith("CameraCinematic")
                             or "Camera.Cinematic" in name,
                "points": pts,
            })
        return out

    def preview_nodes(self) -> list:
        """Rest positions of every node, offset -- for drawing ghost markers."""
        dx, dy, dz = self.delta
        out = []
        for nd in (self.bundle.node_defs if self.bundle else []):
            p = _vec3(nd.get("Pos", "0,0,0"))
            name = nd.get("Name", "")
            out.append({
                "name": name,
                "entity_id": nd.get("EntityId", ""),
                "pos": (p[0] + dx, p[1] + dy, p[2] + dz),
                "is_camera": name.startswith("CameraCinematic")
                             or "Camera.Cinematic" in name,
            })
        return out

    def bounds(self) -> tuple:
        """(min, max) of the previewed geometry -- for framing the view."""
        pts = [p for path in self.preview_paths() for p in path["points"]]
        if not pts:
            return (self.origin, self.origin)
        xs = [p[1] for p in pts]; ys = [p[2] for p in pts]; zs = [p[3] for p in pts]
        return ((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))

    # -- commit -------------------------------------------------------------

    def commit(self, canvas=None, entities=None) -> dict:
        """Fix the group in place.

        `entities` are the real entity objects created by the entity importer.
        Their rest poses are written back to the moviedata nodes and the file is
        saved. Everything before this point was preview only.
        """
        if self.committed:
            return {"already": True}
        self.entities = entities or self.entities
        synced = 0
        for ent in self.entities:
            eid = str(getattr(ent, "id", ""))
            ent._seq_base_pos = tuple(ent.position)
            ent._seq_last_pos = tuple(ent.position)
            if self.link and self.link.is_cinematic_entity(eid):
                self.link.set_node_rest_pose(eid, ent.position)
                synced += 1
            if canvas and hasattr(canvas, "_auto_save_entity_changes"):
                canvas._auto_save_entity_changes(ent)
        if self.link:
            self.link.save()
        self.committed = True
        return {"entities": len(self.entities), "nodes_synced": synced,
                "sequence": self.name, "origin": self.origin}
