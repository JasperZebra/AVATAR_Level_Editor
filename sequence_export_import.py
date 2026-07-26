"""
sequence_export_import.py — export a cinematic sequence from one level and
import it into another, with coordinate rebasing and trigger generation.

A playable cutscene in Avatar is THREE things, and all three must line up or
nothing happens:

  1. The animation      <level>/generated/moviedata.xml
                        - <NodeData>     registry: node Id -> EntityId + rest pose
                        - <SequenceData> the keyframed tracks
  2. The world entities the sequence drives, which must exist in a worldsector
     with EntityIds matching the NodeData entries.
  3. A Domino script    domino/user/levels/<level>/<doc>.<graph>.lua
     that triggers it — AND a matching registration inside
     worlds/<world>/generated/<world>_depload.xml, without which the game
     never loads the script at all.

Two facts learned the hard way, both encoded here:

  * Keyframe values are ABSOLUTE WORLD COORDINATES. The first Position key of
    a node equals that node's rest Pos. Importing a sequence unchanged into a
    different level plays it at the original coordinates — usually inside
    terrain or off the map. Every Position key must be rebased.

  * depload.xml entries are keyed by `crc_ID`, which is plain CRC32 of the
    lowercase backslash path. Verified against four shipped entries.

The Domino runtime API this generates against (read out of the shipped system
boxes, not guessed):

    SwitchCamera(1, "<entityId>")                       -- switch to a camera entity
    SwitchCamera(0, "0")                                -- back to gameplay camera
    CMovieSystem_GetInstance():CommandSequence("play", "<name>")
"""

from __future__ import annotations

import json
import math
import os
import shutil
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field


BUNDLE_INFO = "sequence_info.json"
BUNDLE_XML = "sequence.xml"
BUNDLE_VERSION = 1

# A sequence bundle is deliberately a SUPERSET of an entity collection, so the
# existing entity importer can consume the same folder:
#
#   my_cutscene/
#       collection_info.json     <- entity_export_import.py reads this
#       Camera_Cinematic_01.xml  <- the entities the sequence drives
#       Samson_Pilotable.xml
#       sequence_info.json       <- this module reads these two
#       sequence.xml
#
# Import is therefore two passes over one folder, matching how model import
# already works:
#
#   1. EntityImportDialog places the entities and returns its cross-reference
#      map, {old_entity_id_str: new_entity_id_int} (_build_cross_ref_id_map).
#   2. remap_entity_ids() applies that same map to the sequence's NodeData, so
#      the tracks drive the entities that were just created.
#
# The pivot the entity importer computes (_compute_group_pivot) is the same
# concept as this module's anchor -- pass it straight to rebase_bundle() and the
# sequence lands wherever the entities did.
COLLECTION_INFO = "collection_info.json"


# ── path hashing ───────────────────────────────────────────────────────────────

def dunia_crc32(path: str) -> int:
    """The crc_ID used throughout depload.xml.

    Plain CRC32 of the lowercase, backslash-separated path. Verified against
    shipped entries:
        domino\\user\\levels\\sp_sebastien_rb_02\\riverbank_seb.main.lua
            -> 4248667351
        domino\\system\\settimeofday.lua
            -> 3887919595
    """
    norm = path.replace("/", "\\").lower()
    return zlib.crc32(norm.encode("utf-8")) & 0xFFFFFFFF


# ── bundle model ───────────────────────────────────────────────────────────────

@dataclass
class SequenceBundle:
    """A sequence lifted out of one level, ready to drop into another."""
    name: str
    source_level: str = ""
    anchor: tuple = (0.0, 0.0, 0.0)      # reference point the keys are relative to
    sequence_elem: ET.Element = None     # <Sequence> subtree
    folder: str = ""                     # bundle folder; entity XMLs sit here
    node_defs: list = field(default_factory=list)   # list[ET.Element] <Node>
    duration: float = 0.0

    def entity_ids(self) -> list:
        return [n.get("EntityId", "") for n in self.node_defs]

    def summary(self) -> str:
        lines = [f"{self.name}  ({self.duration:g}s, {len(self.node_defs)} nodes)"]
        for n in self.node_defs:
            lines.append(f"    {n.get('Name','?')}   EntityId={n.get('EntityId','?')}")
        return "\n".join(lines)


# ── vector helpers ─────────────────────────────────────────────────────────────

def _vec3(s: str) -> list:
    return [float(x) for x in s.split(",")[:3]]


def _fmt_vec(vals) -> str:
    # Match the game's own formatting: shortest repr that round-trips.
    return ",".join(f"{v:g}" for v in vals)


# ── quaternion helpers ─────────────────────────────────────────────────────────
#
# moviedata stores rotations as (w, x, y, z). Per movie_data.quat_to_editor_angles
# (verified there against 333 NodeDef<->entity pairs), game space is Z-up and the
# rotation decomposes as Rz(az)*Rx(ax)*Ry(ay) -- so HEADING is rotation about Z.
# "Face the other way" therefore means composing a yaw quaternion about Z.

def _quat_mul(a, b) -> tuple:
    """Hamilton product, (w,x,y,z). a*b applies b first, then a."""
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw)


def yaw_quat(degrees: float) -> tuple:
    """Rotation of `degrees` about the world Z axis (the game's up axis)."""
    half = math.radians(degrees) * 0.5
    return (math.cos(half), 0.0, 0.0, math.sin(half))


def rotate_point_z(x: float, y: float, z: float, degrees: float,
                   pivot) -> tuple:
    """Rotate a point about a vertical axis through `pivot`. Z is unchanged."""
    rad = math.radians(degrees)
    c, s = math.cos(rad), math.sin(rad)
    dx, dy = x - pivot[0], y - pivot[1]
    return (pivot[0] + dx * c - dy * s,
            pivot[1] + dx * s + dy * c,
            z)


def _parse_quat(s: str) -> tuple:
    parts = [float(v) for v in s.split(",")[:4]]
    while len(parts) < 4:
        parts.append(0.0)
    return tuple(parts)


def _auto_anchor(node_defs) -> tuple:
    """Centroid of the nodes' rest positions -- a sane default rebase origin."""
    pts = [_vec3(n.get("Pos", "0,0,0")) for n in node_defs]
    if not pts:
        return (0.0, 0.0, 0.0)
    n = len(pts)
    return (sum(p[0] for p in pts) / n,
            sum(p[1] for p in pts) / n,
            sum(p[2] for p in pts) / n)


# ── export ─────────────────────────────────────────────────────────────────────

def export_sequence(moviedata_path: str, sequence_name: str, out_folder: str,
                    source_level: str = "") -> SequenceBundle:
    """Lift one sequence plus every NodeData entry it references into a folder."""
    tree = ET.parse(moviedata_path)
    root = tree.getroot()

    seq = None
    for s in root.findall("./SequenceData/Sequence"):
        if s.get("Name") == sequence_name:
            seq = s
            break
    if seq is None:
        raise KeyError(f"sequence {sequence_name!r} not found in {moviedata_path}")

    # Which nodes does it drive?
    used_ids = {n.get("Id") for n in seq.findall("./Nodes/Node")}
    registry = {n.get("Id"): n for n in root.findall("./NodeData/Node")}
    node_defs = [registry[i] for i in used_ids if i in registry]
    missing = sorted(used_ids - set(registry))

    anchor = _auto_anchor(node_defs)
    bundle = SequenceBundle(
        name=sequence_name,
        source_level=source_level or os.path.basename(os.path.dirname(moviedata_path)),
        anchor=anchor,
        sequence_elem=seq,
        node_defs=node_defs,
        duration=float(seq.get("EndTime", 0)) - float(seq.get("StartTime", 0)),
    )

    os.makedirs(out_folder, exist_ok=True)
    wrapper = ET.Element("ExportedSequence")
    nd = ET.SubElement(wrapper, "NodeData")
    for n in node_defs:
        nd.append(n)
    sd = ET.SubElement(wrapper, "SequenceData")
    sd.append(seq)
    ET.ElementTree(wrapper).write(os.path.join(out_folder, BUNDLE_XML),
                                  encoding="utf-8", xml_declaration=True)

    info = {
        "bundle_version": BUNDLE_VERSION,
        "name": sequence_name,
        "source_level": bundle.source_level,
        "duration": bundle.duration,
        "anchor": list(anchor),
        "nodes": [{"id": n.get("Id"), "name": n.get("Name"),
                   "entity_id": n.get("EntityId"), "pos": n.get("Pos")}
                  for n in node_defs],
        "missing_node_defs": missing,
    }
    with open(os.path.join(out_folder, BUNDLE_INFO), "w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=2)
    return bundle


def find_entities_by_id(worldsectors_folder: str, entity_ids) -> dict:
    """Locate the source XML for each EntityId across a level's worldsectors.

    Returns {entity_id: (sector_path, element)}. Only converted .xml sectors are
    searched -- run the editor's FCB->XML conversion first, same as any other
    entity work.
    """
    wanted = {str(e) for e in entity_ids}
    found = {}
    if not os.path.isdir(worldsectors_folder):
        return found
    for fname in sorted(os.listdir(worldsectors_folder)):
        if not fname.endswith(".converted.xml"):
            continue
        path = os.path.join(worldsectors_folder, fname)
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        for obj in root.iter("object"):
            fld = obj.find("./field[@name='disEntityId']")
            if fld is None:
                continue
            val = fld.get("value-Id64") or fld.get("value-UInt64") or ""
            if val in wanted and val not in found:
                found[val] = (path, obj)
        if len(found) == len(wanted):
            break
    return found


def export_sequence_with_entities(moviedata_path: str, sequence_name: str,
                                  worldsectors_folder: str, out_folder: str,
                                  source_level: str = "") -> dict:
    """Export a sequence AND the entities it drives, as one importable folder.

    The result doubles as an entity collection, so the existing entity importer
    can place the entities and hand back the id_map this module needs.
    """
    bundle = export_sequence(moviedata_path, sequence_name, out_folder,
                             source_level=source_level)
    located = find_entities_by_id(worldsectors_folder, bundle.entity_ids())

    exported, missing = [], []
    for node in bundle.node_defs:
        eid = node.get("EntityId", "")
        name = node.get("Name", eid)
        if eid not in located:
            missing.append(name)
            continue
        _sector, elem = located[eid]
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[:80]
        ET.ElementTree(elem).write(os.path.join(out_folder, f"{safe}.xml"),
                                   encoding="utf-8", xml_declaration=True)
        exported.append({"name": name, "entity_id": eid, "file": f"{safe}.xml"})

    # collection_info.json so entity_export_import.py recognises the folder
    with open(os.path.join(out_folder, COLLECTION_INFO), "w", encoding="utf-8") as fh:
        json.dump({
            "collection_name": sequence_name,
            "source_level": bundle.source_level,
            "entity_count": len(exported),
            "created_by": "sequence_export_import",
            "note": "Also a sequence bundle -- see sequence_info.json",
        }, fh, indent=2)

    return {"bundle": bundle, "entities_exported": exported,
            "entities_missing": missing}


def load_bundle(folder: str) -> SequenceBundle:
    with open(os.path.join(folder, BUNDLE_INFO), encoding="utf-8") as fh:
        info = json.load(fh)
    root = ET.parse(os.path.join(folder, BUNDLE_XML)).getroot()
    return SequenceBundle(
        folder=folder,
        name=info["name"],
        source_level=info.get("source_level", ""),
        anchor=tuple(info.get("anchor", (0, 0, 0))),
        sequence_elem=root.find("./SequenceData/Sequence"),
        node_defs=root.findall("./NodeData/Node"),
        duration=info.get("duration", 0.0),
    )


# ── rebasing ───────────────────────────────────────────────────────────────────

def rebase_bundle(bundle: SequenceBundle, target_anchor: tuple) -> int:
    """Shift every absolute world coordinate so `anchor` lands on `target_anchor`.

    Returns the number of values moved. Rotations are left alone -- a pure
    translation does not change orientation. (Rotating a whole shot would mean
    transforming the quaternions too, which is deliberately not done here.)
    """
    dx = target_anchor[0] - bundle.anchor[0]
    dy = target_anchor[1] - bundle.anchor[1]
    dz = target_anchor[2] - bundle.anchor[2]
    moved = 0

    for n in bundle.node_defs:
        p = _vec3(n.get("Pos", "0,0,0"))
        n.set("Pos", _fmt_vec((p[0] + dx, p[1] + dy, p[2] + dz)))
        moved += 1

    for node in bundle.sequence_elem.findall("./Nodes/Node"):
        for track in node.findall("Track"):
            if track.get("ParamId") != "1":      # 1 = Position
                continue
            for key in track.findall("Key"):
                val = key.get("value")
                if not val:
                    continue
                p = _vec3(val)
                key.set("value", _fmt_vec((p[0] + dx, p[1] + dy, p[2] + dz)))
                moved += 1

    bundle.anchor = tuple(target_anchor)
    return moved


def rotate_bundle(bundle: SequenceBundle, degrees: float, pivot=None) -> dict:
    """Spin the whole sequence about a vertical axis -- change which way it faces.

    Rotates BOTH halves of the transform, which is the part that is easy to get
    wrong: every Position key and rest pose orbits the pivot, and every Rotation
    key and rest orientation is composed with the same yaw. Doing only one gives
    a Samson that flies the new path while still pointing the old way.

    `pivot` defaults to the bundle's anchor, so the shot turns in place.
    Returns counts of what changed.
    """
    if pivot is None:
        pivot = bundle.anchor
    q_yaw = yaw_quat(degrees)
    moved = turned = 0

    for n in bundle.node_defs:
        p = _vec3(n.get("Pos", "0,0,0"))
        n.set("Pos", _fmt_vec(rotate_point_z(p[0], p[1], p[2], degrees, pivot)))
        moved += 1
        rot = n.get("Rotate")
        if rot:
            n.set("Rotate", _fmt_vec(_quat_mul(q_yaw, _parse_quat(rot))))
            turned += 1

    for node in bundle.sequence_elem.findall("./Nodes/Node"):
        for track in node.findall("Track"):
            pid = track.get("ParamId")
            if pid == "1":                      # Position
                for key in track.findall("Key"):
                    val = key.get("value")
                    if not val:
                        continue
                    p = _vec3(val)
                    key.set("value", _fmt_vec(
                        rotate_point_z(p[0], p[1], p[2], degrees, pivot)))
                    moved += 1
            elif pid == "2":                    # Rotation (quaternion)
                for key in track.findall("Key"):
                    val = key.get("value")
                    if not val:
                        continue
                    key.set("value", _fmt_vec(_quat_mul(q_yaw, _parse_quat(val))))
                    turned += 1

    # The anchor itself only moves if we spun about something else.
    if pivot != bundle.anchor:
        bundle.anchor = rotate_point_z(bundle.anchor[0], bundle.anchor[1],
                                       bundle.anchor[2], degrees, pivot)
    return {"positions_rotated": moved, "orientations_rotated": turned,
            "degrees": degrees}


def rotate_node(bundle: SequenceBundle, node_name_or_id: str, degrees: float,
                pivot=None) -> dict:
    """Rotate ONE node of the sequence, leaving the rest of the shot alone.

    Use to re-aim a single actor -- e.g. have the Samson enter facing a
    different way without disturbing the cameras. `pivot` defaults to that
    node's own rest position, so it turns on the spot.
    """
    target = None
    for n in bundle.node_defs:
        if n.get("Name") == node_name_or_id or n.get("Id") == str(node_name_or_id):
            target = n
            break
    if target is None:
        raise KeyError(f"no node named {node_name_or_id!r} in this sequence")

    if pivot is None:
        pivot = tuple(_vec3(target.get("Pos", "0,0,0")))
    q_yaw = yaw_quat(degrees)

    p = _vec3(target.get("Pos", "0,0,0"))
    target.set("Pos", _fmt_vec(rotate_point_z(p[0], p[1], p[2], degrees, pivot)))
    rot = target.get("Rotate")
    if rot:
        target.set("Rotate", _fmt_vec(_quat_mul(q_yaw, _parse_quat(rot))))

    moved = turned = 0
    for sn in bundle.sequence_elem.findall("./Nodes/Node"):
        if sn.get("Id") != target.get("Id"):
            continue
        for track in sn.findall("Track"):
            pid = track.get("ParamId")
            for key in track.findall("Key"):
                val = key.get("value")
                if not val:
                    continue
                if pid == "1":
                    q = _vec3(val)
                    key.set("value", _fmt_vec(
                        rotate_point_z(q[0], q[1], q[2], degrees, pivot)))
                    moved += 1
                elif pid == "2":
                    key.set("value", _fmt_vec(_quat_mul(q_yaw, _parse_quat(val))))
                    turned += 1
    return {"node": target.get("Name"), "positions_rotated": moved,
            "orientations_rotated": turned, "degrees": degrees}


# ── adding and removing nodes ──────────────────────────────────────────────────

def list_nodes(bundle: SequenceBundle) -> list:
    """Every node in the sequence, for a +/- list UI.

    Returns [{'id','name','entity_id','is_camera','pos_keys','rot_keys'}].
    """
    by_id = {n.get("Id"): n for n in bundle.node_defs}
    out = []
    for sn in bundle.sequence_elem.findall("./Nodes/Node"):
        nd = by_id.get(sn.get("Id"))
        pos_keys = rot_keys = 0
        for track in sn.findall("Track"):
            k = len(track.findall("Key"))
            if track.get("ParamId") == "1":
                pos_keys += k
            elif track.get("ParamId") == "2":
                rot_keys += k
        out.append({
            "id": sn.get("Id"),
            "name": nd.get("Name") if nd is not None else f"<orphan {sn.get('Id')}>",
            "entity_id": nd.get("EntityId", "") if nd is not None else "",
            "is_camera": is_camera_node(nd) if nd is not None else False,
            "pos_keys": pos_keys,
            "rot_keys": rot_keys,
        })
    return out


def remove_node(bundle: SequenceBundle, node_id: str) -> dict:
    """Drop one node from the sequence -- the '-' button.

    Removes both the registry entry and the animated tracks. Everything else
    keeps its animation exactly.
    """
    node_id = str(node_id)
    removed_name = None
    for n in list(bundle.node_defs):
        if n.get("Id") == node_id:
            removed_name = n.get("Name")
            bundle.node_defs.remove(n)
            break

    nodes_parent = bundle.sequence_elem.find("Nodes")
    dropped_tracks = 0
    if nodes_parent is not None:
        for sn in list(nodes_parent.findall("Node")):
            if sn.get("Id") == node_id:
                dropped_tracks = len(sn.findall("Track"))
                nodes_parent.remove(sn)
    if removed_name is None and dropped_tracks == 0:
        raise KeyError(f"no node {node_id!r} in this sequence")
    return {"removed": removed_name or node_id, "tracks_dropped": dropped_tracks}


def _free_node_id(bundle: SequenceBundle) -> str:
    """A node Id not already used. Shipped ids are signed 32-bit, both signs."""
    used = {n.get("Id") for n in bundle.node_defs}
    used |= {n.get("Id") for n in bundle.sequence_elem.findall("./Nodes/Node")}
    candidate = 1000000
    while str(candidate) in used:
        candidate += 1
    return str(candidate)


def add_node(bundle: SequenceBundle, name: str, entity_id: str,
             pos=(0.0, 0.0, 0.0), rot=(1.0, 0.0, 0.0, 0.0),
             keyframes=None) -> dict:
    """Add a node to the sequence -- the '+' button.

    `keyframes` is an optional [(time, x, y, z)] Position track. With none, the
    node gets a single key at t=0 holding it at `pos`, which is the useful
    default for something that should simply be present and posed (a prop, or a
    camera you are about to author a path for).
    """
    node_id = _free_node_id(bundle)

    nd = ET.Element("Node", {
        "Id": node_id,
        "Type": "1",
        "Name": name,
        "EntityId": str(entity_id),
        "Pos": _fmt_vec(pos),
        "Rotate": _fmt_vec(rot),
        "Scale": "1,1,1",
    })
    bundle.node_defs.append(nd)

    nodes_parent = bundle.sequence_elem.find("Nodes")
    if nodes_parent is None:
        nodes_parent = ET.SubElement(bundle.sequence_elem, "Nodes")
    sn = ET.SubElement(nodes_parent, "Node", {"Id": node_id})

    track = ET.SubElement(sn, "Track", {"ParamId": "1", "Flags": "0"})
    keys = keyframes or [(0.0, pos[0], pos[1], pos[2])]
    for t, x, y, z in keys:
        ET.SubElement(track, "Key", {"time": f"{float(t):g}",
                                     "value": _fmt_vec((x, y, z))})

    rtrack = ET.SubElement(sn, "Track", {"ParamId": "2", "Flags": "0"})
    ET.SubElement(rtrack, "Key", {"time": "0", "value": _fmt_vec(rot)})

    return {"added": name, "node_id": node_id, "pos_keys": len(keys)}


def duplicate_node(bundle: SequenceBundle, node_id: str, new_name: str = None,
                   entity_id: str = None, offset=(0.0, 0.0, 0.0),
                   time_shift: float = 0.0, yaw: float = 0.0) -> dict:
    """Copy a node WITH its whole animated path -- "two Samsons instead of one".

    The copy keeps the original's flight exactly, then optionally:
        offset      shifts it in space, so they fly in formation rather than
                    through each other
        time_shift  delays it, so the second one trails the first
        yaw         turns it about its own start position

    `entity_id` must be a DIFFERENT entity from the original -- two nodes
    pointing at one entity means the engine drives the same object twice and
    only the last write per frame survives. Left as None it copies the
    original's id and returns a warning saying so.
    """
    node_id = str(node_id)
    src_def = None
    for n in bundle.node_defs:
        if n.get("Id") == node_id:
            src_def = n
            break
    src_seq = None
    for sn in bundle.sequence_elem.findall("./Nodes/Node"):
        if sn.get("Id") == node_id:
            src_seq = sn
            break
    if src_def is None or src_seq is None:
        raise KeyError(f"no node {node_id!r} in this sequence")

    new_id = _free_node_id(bundle)
    warning = None
    if entity_id is None:
        entity_id = src_def.get("EntityId", "")
        warning = ("copy shares the original's EntityId -- give it a distinct "
                   "entity or both nodes will drive the same object")

    pivot = tuple(_vec3(src_def.get("Pos", "0,0,0")))
    q_yaw = yaw_quat(yaw) if yaw else None

    def _place(x, y, z):
        if q_yaw is not None:
            x, y, z = rotate_point_z(x, y, z, yaw, pivot)
        return (x + offset[0], y + offset[1], z + offset[2])

    nd = ET.Element("Node", dict(src_def.attrib))
    nd.set("Id", new_id)
    nd.set("Name", new_name or f"{src_def.get('Name','node')}_copy")
    nd.set("EntityId", str(entity_id))
    nd.set("Pos", _fmt_vec(_place(*_vec3(src_def.get("Pos", "0,0,0")))))
    if q_yaw is not None and src_def.get("Rotate"):
        nd.set("Rotate", _fmt_vec(_quat_mul(q_yaw,
                                            _parse_quat(src_def.get("Rotate")))))
    bundle.node_defs.append(nd)

    sn = ET.SubElement(bundle.sequence_elem.find("Nodes"), "Node", {"Id": new_id})
    copied = 0
    for track in src_seq.findall("Track"):
        pid = track.get("ParamId")
        nt = ET.SubElement(sn, "Track", dict(track.attrib))
        for key in track.findall("Key"):
            attrs = dict(key.attrib)
            if time_shift:
                attrs["time"] = f"{float(attrs.get('time', 0)) + time_shift:g}"
            val = attrs.get("value")
            if val and pid == "1":
                attrs["value"] = _fmt_vec(_place(*_vec3(val)))
            elif val and pid == "2" and q_yaw is not None:
                attrs["value"] = _fmt_vec(_quat_mul(q_yaw, _parse_quat(val)))
            ET.SubElement(nt, "Key", attrs)
            copied += 1

    # A delayed copy can run past the sequence's declared end, which would clip it.
    if time_shift > 0:
        end = float(bundle.sequence_elem.get("EndTime", 0))
        needed = end + time_shift
        if needed > end:
            bundle.sequence_elem.set("EndTime", f"{needed:g}")
            bundle.duration = needed

    out = {"source": src_def.get("Name"), "new_node": nd.get("Name"),
           "node_id": new_id, "keys_copied": copied}
    if warning:
        out["warning"] = warning
    return out


def add_keyframe(bundle: SequenceBundle, node_id: str, time: float,
                 pos) -> dict:
    """Insert a Position keyframe on a node, kept in time order."""
    node_id = str(node_id)
    for sn in bundle.sequence_elem.findall("./Nodes/Node"):
        if sn.get("Id") != node_id:
            continue
        track = None
        for t in sn.findall("Track"):
            if t.get("ParamId") == "1":
                track = t
                break
        if track is None:
            track = ET.SubElement(sn, "Track", {"ParamId": "1", "Flags": "0"})
        key = ET.Element("Key", {"time": f"{float(time):g}",
                                 "value": _fmt_vec(pos)})
        keys = track.findall("Key")
        idx = len(keys)
        for i, k in enumerate(keys):
            if float(k.get("time", 0)) > float(time):
                idx = i
                break
        track.insert(idx, key)
        return {"node_id": node_id, "time": time, "keys": len(keys) + 1}
    raise KeyError(f"no node {node_id!r} in this sequence")


def remove_keyframe(bundle: SequenceBundle, node_id: str, key_index: int,
                    param_id: str = "1") -> dict:
    """Delete one keyframe by index from a node's track."""
    node_id = str(node_id)
    for sn in bundle.sequence_elem.findall("./Nodes/Node"):
        if sn.get("Id") != node_id:
            continue
        for track in sn.findall("Track"):
            if track.get("ParamId") != param_id:
                continue
            keys = track.findall("Key")
            if not (0 <= key_index < len(keys)):
                raise IndexError(f"key {key_index} out of range ({len(keys)})")
            track.remove(keys[key_index])
            return {"node_id": node_id, "removed_index": key_index,
                    "keys_left": len(keys) - 1}
    raise KeyError(f"no node {node_id!r} with track {param_id}")


def remap_entity_ids(bundle: SequenceBundle, mapping: dict) -> list:
    """Point node defs at the entities that actually exist in the target level.

    `mapping` is {old_entity_id: new_entity_id}. Returns the list of node names
    left unmapped -- those will not animate and must be resolved before this is
    worth shipping.
    """
    unmapped = []
    for n in bundle.node_defs:
        old = n.get("EntityId", "")
        if old in mapping:
            n.set("EntityId", str(mapping[old]))
        else:
            unmapped.append(n.get("Name", old))
    return unmapped


# ── import ─────────────────────────────────────────────────────────────────────

def import_sequence(bundle: SequenceBundle, target_moviedata_path: str,
                    overwrite: bool = False) -> dict:
    """Merge a (already rebased/remapped) bundle into a target moviedata.xml."""
    tree = ET.parse(target_moviedata_path)
    root = tree.getroot()

    node_data = root.find("NodeData")
    if node_data is None:
        node_data = ET.SubElement(root, "NodeData")
    seq_data = root.find("SequenceData")
    if seq_data is None:
        seq_data = ET.SubElement(root, "SequenceData")

    existing_seq = {s.get("Name") for s in seq_data.findall("Sequence")}
    if bundle.name in existing_seq:
        if not overwrite:
            raise ValueError(f"sequence {bundle.name!r} already exists in target; "
                             f"pass overwrite=True to replace it")
        for s in seq_data.findall("Sequence"):
            if s.get("Name") == bundle.name:
                seq_data.remove(s)

    existing_nodes = {n.get("Id") for n in node_data.findall("Node")}
    added_nodes = 0
    for n in bundle.node_defs:
        if n.get("Id") in existing_nodes:
            continue      # id already present -- assume it is the same node
        node_data.append(n)
        added_nodes += 1

    seq_data.append(bundle.sequence_elem)

    try:
        ET.indent(tree, space="\t")
    except AttributeError:
        pass
    tree.write(target_moviedata_path, encoding="utf-8", xml_declaration=True)
    return {"nodes_added": added_nodes, "sequence": bundle.name}


# ── depload registration ───────────────────────────────────────────────────────

class DeploadRegistry:
    """Read/modify a <world>_depload.xml.

    Without an entry here the game never loads a Domino script, no matter where
    the .lua sits. Entries are <CDominoBoxResource> with a crc_ID that is CRC32
    of the lowercase backslash path.
    """

    DOMINO_TYPE = "CDominoBoxResource"
    DOMINO_TYPE_CRC = "1508605935"

    def __init__(self, path: str):
        self.path = path
        self.tree = ET.parse(path)
        self.root = self.tree.getroot()

    def has_box(self, lua_path: str) -> bool:
        crc = str(dunia_crc32(lua_path))
        return any(e.get("crc_ID") == crc
                   for e in self.root.iter(self.DOMINO_TYPE))

    def add_box(self, lua_path: str, children: list = None,
                parent_lua: str = None) -> ET.Element:
        """Register a Domino script, optionally nested under an existing one.

        `children` are the system boxes the script uses (e.g.
        "domino\\system\\sequence.lua"); the game uses them to preload
        dependencies.
        """
        children = children or []
        norm = lua_path.replace("/", "\\").lower()

        elem = ET.Element(self.DOMINO_TYPE, {
            "Type": self.DOMINO_TYPE,
            "crc_Type": self.DOMINO_TYPE_CRC,
            "ID": norm,
            "crc_ID": str(dunia_crc32(norm)),
            "IsFilename": "1",
            "Size": "0",
            "nbChildren": str(len(children)),
        })
        for child in children:
            cnorm = child.replace("/", "\\").lower()
            ET.SubElement(elem, self.DOMINO_TYPE, {
                "Type": self.DOMINO_TYPE,
                "crc_Type": self.DOMINO_TYPE_CRC,
                "ID": cnorm,
                "crc_ID": str(dunia_crc32(cnorm)),
                "IsFilename": "1",
                "Size": "0",
                "nbChildren": "0",
            })

        host = self.root
        if parent_lua:
            pcrc = str(dunia_crc32(parent_lua))
            for e in self.root.iter(self.DOMINO_TYPE):
                if e.get("crc_ID") == pcrc:
                    host = e
                    e.set("nbChildren", str(len(list(e)) + 1))
                    break
        host.append(elem)
        return elem

    def save(self, path: str = None):
        self.tree.write(path or self.path, encoding="utf-8", xml_declaration=True)


# ── Domino Lua generation ──────────────────────────────────────────────────────

# A sequence can be played two ways, and the shipped game uses BOTH:
#
#   CUTSCENE      takes the camera away from the player, plays, hands it back.
#                 Blue Lagoon's Samson_Short_Intro does this -- it drives three
#                 CameraCinematic entities and the Domino graph calls SetCamera.
#
#   SCRIPTED      no camera takeover at all. The animation just happens in the
#                 world while the player keeps control. ALL 35 sequences in
#                 Hell's Gate are this kind -- dragons flying overhead, doors
#                 opening -- and its Domino script never calls SetCamera once.
#
# The difference is entirely in the trigger graph and whether camera nodes are
# present; the sequence format itself is identical.
MODE_CUTSCENE = "cutscene"
MODE_SCRIPTED = "scripted"

# The system boxes each mode depends on. These become the depload children;
# the game preloads them.
TRIGGER_BOXES = [
    "domino\\system\\proximitytrigger.lua",
    "domino\\system\\onceonly.lua",
    "domino\\system\\setcamera.lua",
    "domino\\system\\sequence.lua",
    "domino\\system\\delay.lua",
]

SCRIPTED_BOXES = [
    "domino\\system\\proximitytrigger.lua",
    "domino\\system\\onceonly.lua",
    "domino\\system\\sequence.lua",
]


def is_camera_node(node_elem) -> bool:
    """Is this NodeData entry a cinematic camera rather than a prop/vehicle?"""
    name = (node_elem.get("Name") or "")
    return name.startswith("CameraCinematic") or "Camera.Cinematic" in name


def strip_camera_nodes(bundle: "SequenceBundle") -> list:
    """Turn a cutscene into a scripted event by removing its camera nodes.

    The animation of everything else is untouched -- the Samson still flies its
    exact path, the player just watches it from wherever they happen to be
    standing instead of being taken to a cinematic viewpoint.

    Returns the names of the removed cameras.
    """
    removed = []
    cam_ids = set()
    for n in list(bundle.node_defs):
        if is_camera_node(n):
            cam_ids.add(n.get("Id"))
            removed.append(n.get("Name", n.get("Id")))
            bundle.node_defs.remove(n)

    nodes_parent = bundle.sequence_elem.find("Nodes")
    if nodes_parent is not None:
        for sn in list(nodes_parent.findall("Node")):
            if sn.get("Id") in cam_ids:
                nodes_parent.remove(sn)
    return removed


def camera_nodes(bundle: "SequenceBundle") -> list:
    return [n for n in bundle.node_defs if is_camera_node(n)]

_LUA_TEMPLATE = '''-- Generated by Avatar Level Editor -- sequence trigger graph
--
-- Plays the cinematic sequence "{sequence}" the first time the player enters
-- trigger entity {trigger_id}.
--
-- Flow:  ProximityTrigger.Enter -> OnceOnly -> SetCamera -> Sequence.Play
--        -> Delay({duration}) -> SetCamera(nil) restores the gameplay camera
--
-- This mirrors how the shipped cutscenes are wired. Unlike the shipped files
-- this one IS meant to be edited -- it has no .domino.xml source to regenerate
-- from.

export = {{
}};

function export:LuaDependencies()
	return {{
	}};
end;

function export:Create(cbox)
	cbox:RegisterBox("Domino/System/ProximityTrigger.lua");
	cbox:RegisterBox("Domino/System/OnceOnly.lua");
	cbox:RegisterBox("Domino/System/SetCamera.lua");
	cbox:RegisterBox("Domino/System/Sequence.lua");
	cbox:RegisterBox("Domino/System/Delay.lua");

	self.Trigger = "{trigger_id}";
	self.CinematicCamera = "{camera_id}";

	self[1] = cbox:CreateBox("Domino/System/ProximityTrigger.lua");
	self[1]._graph = self;
	self[1].Enter = self._type.f_enter;
	self[1].Leave = DummyFunction;
	self[1].Use = DummyFunction;

	self[2] = cbox:CreateBox("Domino/System/OnceOnly.lua");
	self[2]._graph = self;
	self[2].Out = self._type.f_once;

	self[3] = cbox:CreateBox("Domino/System/SetCamera.lua");
	self[3]._graph = self;
	self[3].Out = self._type.f_camera_set;

	self[4] = cbox:CreateBox("Domino/System/Sequence.lua");
	self[4]._graph = self;
	self[4].Out = self._type.f_sequence_started;

	self[5] = cbox:CreateBox("Domino/System/Delay.lua");
	self[5]._graph = self;
	self[5].TimeElapsed = self._type.f_finished;

	self[6] = cbox:CreateBox("Domino/System/SetCamera.lua");
	self[6]._graph = self;
	self[6].Out = DummyFunction;
end;

function export:Init(cbox)
	self[1].Trigger = self.Trigger;
	self[1]._type.Enable(self[1]);
end;

function export:ShutDown()
end;

-- player walked into the trigger volume
function export:f_enter()
	self = self._graph;
	self[2]._type.In(self[2]);
end;

-- first time only
function export:f_once()
	self = self._graph;
	self[3].CinematicCamera = self.CinematicCamera;
	self[3]._type.In(self[3]);
end;

-- camera is live, roll the sequence
function export:f_camera_set()
	self = self._graph;
	self[4].SequenceName = "{sequence}";
	self[4]._type.Play(self[4]);
end;

-- sequence playing, wait out its duration
function export:f_sequence_started()
	self = self._graph;
	self[5].Seconds = {duration};
	self[5]._type.In(self[5]);
end;

-- hand the camera back to gameplay
function export:f_finished()
	self = self._graph;
	self[6].CinematicCamera = nil;
	self[6]._type.In(self[6]);
end;
'''


_LUA_SCRIPTED_TEMPLATE = '''-- Generated by Avatar Level Editor -- scripted event graph
--
-- Plays "{sequence}" when the player enters trigger entity {trigger_id}.
-- NO camera takeover: the animation happens in the world while the player keeps
-- full control, the way Hell's Gate flies its dragons and Samsons overhead.
--
-- Flow:  ProximityTrigger.Enter{once_comment} -> Sequence.Play

export = {{
}};

function export:LuaDependencies()
	return {{
	}};
end;

function export:Create(cbox)
	cbox:RegisterBox("Domino/System/ProximityTrigger.lua");
{once_register}	cbox:RegisterBox("Domino/System/Sequence.lua");

	self.Trigger = "{trigger_id}";

	self[1] = cbox:CreateBox("Domino/System/ProximityTrigger.lua");
	self[1]._graph = self;
	self[1].Enter = self._type.f_enter;
	self[1].Leave = DummyFunction;
	self[1].Use = DummyFunction;

{once_create}	self[3] = cbox:CreateBox("Domino/System/Sequence.lua");
	self[3]._graph = self;
	self[3].Out = DummyFunction;
end;

function export:Init(cbox)
	self[1].Trigger = self.Trigger;
	self[1]._type.Enable(self[1]);
end;

function export:ShutDown()
end;

function export:f_enter()
	self = self._graph;
{enter_body}
end;

{once_handler}function export:f_play()
	self = self._graph;
	self[3].SequenceName = "{sequence}";
	self[3]._type.Play(self[3]);
end;
'''


def generate_trigger_lua(sequence_name: str, trigger_entity_id: str,
                         camera_entity_id: str = None, duration: float = 0.0,
                         mode: str = MODE_CUTSCENE, once_only: bool = True) -> str:
    """Emit a Domino graph that plays `sequence_name` on trigger entry.

    mode=MODE_CUTSCENE  switches to `camera_entity_id` for `duration` seconds,
                        then restores the gameplay camera.
    mode=MODE_SCRIPTED  just plays it -- no camera takeover, player keeps
                        control. `camera_entity_id` and `duration` are unused.

    once_only=False (scripted mode only) lets an ambient event replay every time
    the player re-enters the volume.
    """
    if mode == MODE_CUTSCENE:
        if not camera_entity_id:
            raise ValueError("cutscene mode needs a camera_entity_id; "
                             "use mode=MODE_SCRIPTED for a camera-less event")
        return _LUA_TEMPLATE.format(
            sequence=sequence_name,
            trigger_id=trigger_entity_id,
            camera_id=camera_entity_id,
            duration=f"{duration:g}",
        )

    if once_only:
        parts = dict(
            once_comment=" -> OnceOnly",
            once_register='\tcbox:RegisterBox("Domino/System/OnceOnly.lua");\n',
            once_create=("\tself[2] = cbox:CreateBox(\"Domino/System/OnceOnly.lua\");\n"
                         "\tself[2]._graph = self;\n"
                         "\tself[2].Out = self._type.f_play;\n\n"),
            enter_body="\tself[2]._type.In(self[2]);",
            once_handler="",
        )
    else:
        # Ambient/repeating: fires every time the player enters the volume.
        parts = dict(
            once_comment="",
            once_register="",
            once_create="",
            enter_body="\tself._type.f_play(self);",
            once_handler="",
        )
    return _LUA_SCRIPTED_TEMPLATE.format(sequence=sequence_name,
                                         trigger_id=trigger_entity_id, **parts)


def boxes_for_mode(mode: str, once_only: bool = True) -> list:
    """The depload children to register for a generated graph."""
    if mode == MODE_CUTSCENE:
        return list(TRIGGER_BOXES)
    boxes = list(SCRIPTED_BOXES)
    if not once_only:
        boxes.remove("domino\\system\\onceonly.lua")
    return boxes


def lua_relative_path(level_folder: str, doc_name: str, graph_name: str) -> str:
    """The canonical in-data path for a generated graph.

    Shipped scripts are named "<document>.<graph>.lua", e.g.
    "riverbank_seb.sp_bluelagoon_rb02_cinematicpascal.lua".
    """
    return f"domino\\user\\levels\\{level_folder}\\{doc_name}.{graph_name}.lua"


def install_trigger_lua(patch_folder: str, level_folder: str, doc_name: str,
                        graph_name: str, lua_text: str) -> str:
    """Write the .lua into the patch folder, creating directories. Returns path."""
    rel = lua_relative_path(level_folder, doc_name, graph_name)
    full = os.path.join(patch_folder, rel.replace("\\", os.sep))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(lua_text)
    return full
