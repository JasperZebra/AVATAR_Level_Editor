"""
movie_data.py — Parser and data model for Avatar moviedata.xml files.

moviedata.xml contains:
  NodeData      — registry mapping integer node IDs to world entities (by EntityId)
  SequenceData  — named cinematic sequences with per-node animation tracks

Track ParamIds:
  1 = Position  (X, Y, Z keyframes)
  2 = Rotation  (quaternion W, X, Y, Z keyframes)
  4 = Event track (particle start/stop events)
  5 = Animation state triggers (keys have no value — ignored for rendering)
  7 = Sound event track (one-shot triggers)
  8 = Ambient / loop sound track
"""

import xml.etree.ElementTree as ET
import os
import math
from io import BytesIO
from dataclasses import dataclass, field
from typing import Optional


# ── Key types ──────────────────────────────────────────────────────────────────

@dataclass
class PosKey:
    time: float
    x: float
    y: float
    z: float


@dataclass
class RotKey:
    time: float
    w: float
    x: float
    y: float
    z: float


@dataclass
class EventKey:
    time: float
    event: str


@dataclass
class SoundKey:
    time: float
    sound_id: str
    sound_type: int


# ── Track ──────────────────────────────────────────────────────────────────────

@dataclass
class MovieTrack:
    param_id: int
    flags: int
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    pos_keys: list = field(default_factory=list)    # list[PosKey]
    rot_keys: list = field(default_factory=list)    # list[RotKey]
    event_keys: list = field(default_factory=list)  # list[EventKey]
    sound_keys: list = field(default_factory=list)  # list[SoundKey]


# ── Sequence node ──────────────────────────────────────────────────────────────

class MovieSeqNode:
    def __init__(self, node_id: int):
        self.node_id: int = node_id
        self.tracks: dict = {}  # param_id (int) -> MovieTrack

    def pos_at(self, t: float):
        """Linear-interpolated position (x, y, z) at time t. Returns None if no pos track."""
        track = self.tracks.get(1)
        if not track or not track.pos_keys:
            return None
        keys = track.pos_keys
        if t <= keys[0].time:
            k = keys[0]
            return (k.x, k.y, k.z)
        if t >= keys[-1].time:
            k = keys[-1]
            return (k.x, k.y, k.z)
        for i in range(len(keys) - 1):
            k0, k1 = keys[i], keys[i + 1]
            if k0.time <= t <= k1.time:
                a = (t - k0.time) / (k1.time - k0.time)
                return (
                    k0.x + (k1.x - k0.x) * a,
                    k0.y + (k1.y - k0.y) * a,
                    k0.z + (k1.z - k0.z) * a,
                )
        return None

    def rot_at(self, t: float):
        """Slerp-interpolated rotation (w, x, y, z) at time t. Returns None if no rot track."""
        track = self.tracks.get(2)
        if not track or not track.rot_keys:
            return None
        keys = track.rot_keys
        if t <= keys[0].time:
            k = keys[0]
            return (k.w, k.x, k.y, k.z)
        if t >= keys[-1].time:
            k = keys[-1]
            return (k.w, k.x, k.y, k.z)
        for i in range(len(keys) - 1):
            k0, k1 = keys[i], keys[i + 1]
            if k0.time <= t <= k1.time:
                a = (t - k0.time) / (k1.time - k0.time)
                return _slerp(
                    (k0.w, k0.x, k0.y, k0.z),
                    (k1.w, k1.x, k1.y, k1.z),
                    a,
                )
        return None

    def all_pos_keys(self):
        """Return the list of PosKeys for convenient path rendering."""
        track = self.tracks.get(1)
        return track.pos_keys if track else []


# ── Sequence ───────────────────────────────────────────────────────────────────

@dataclass
class MovieSequence:
    name: str
    flags: int
    start_time: float
    end_time: float
    nodes: list = field(default_factory=list)  # list[MovieSeqNode]

    def duration(self) -> float:
        return self.end_time - self.start_time

    def node_by_id(self, node_id: int) -> Optional['MovieSeqNode']:
        for n in self.nodes:
            if n.node_id == node_id:
                return n
        return None


# ── NodeDef ────────────────────────────────────────────────────────────────────

@dataclass
class MovieNodeDef:
    id: int
    node_type: int
    name: str
    entity_id: str   # decimal string matching disEntityId
    pos: tuple       # (x, y, z) rest / default position
    rotate: tuple    # (w, x, y, z) rest rotation
    scale: tuple     # (sx, sy, sz)


# ── Main container ─────────────────────────────────────────────────────────────

class MovieData:
    def __init__(self):
        self.node_defs: dict = {}   # int -> MovieNodeDef
        self.sequences: list = []   # list[MovieSequence]
        self.source_path: str = None
        self._tree = None           # live ET.ElementTree for round-trip save
        self._clean_hash: str = None

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, xml_path: str) -> 'MovieData':
        md = cls()
        md.source_path = xml_path
        md._tree = ET.parse(xml_path)
        root = md._tree.getroot()

        # ── NodeData ──────────────────────────────────────────────────
        for node_elem in root.findall('./NodeData/Node'):
            nid = int(node_elem.get('Id', 0))
            nd = MovieNodeDef(
                id=nid,
                node_type=int(node_elem.get('Type', 1)),
                name=node_elem.get('Name', ''),
                entity_id=node_elem.get('EntityId', ''),
                pos=_parse_vec3(node_elem.get('Pos', '0,0,0')),
                rotate=_parse_vec4(node_elem.get('Rotate', '1,0,0,0')),
                scale=_parse_vec3(node_elem.get('Scale', '1,1,1')),
            )
            md.node_defs[nid] = nd

        # ── SequenceData ──────────────────────────────────────────────
        for seq_elem in root.findall('./SequenceData/Sequence'):
            seq = MovieSequence(
                name=seq_elem.get('Name', ''),
                flags=int(seq_elem.get('Flags', 0)),
                start_time=float(seq_elem.get('StartTime', 0)),
                end_time=float(seq_elem.get('EndTime', 0)),
            )
            for node_elem in seq_elem.findall('./Nodes/Node'):
                nid = int(node_elem.get('Id', 0))
                seq_node = MovieSeqNode(nid)
                for track_elem in node_elem.findall('Track'):
                    pid = int(track_elem.get('ParamId', 0))
                    track = MovieTrack(
                        param_id=pid,
                        flags=int(track_elem.get('Flags', 0)),
                        start_time=_maybe_float(track_elem.get('StartTime')),
                        end_time=_maybe_float(track_elem.get('EndTime')),
                    )
                    for key_elem in track_elem.findall('Key'):
                        t = float(key_elem.get('time', 0))
                        if pid == 1:
                            val = key_elem.get('value')
                            if val:
                                v = _parse_vec3(val)
                                track.pos_keys.append(PosKey(t, v[0], v[1], v[2]))
                        elif pid == 2:
                            val = key_elem.get('value')
                            if val:
                                v = _parse_vec4(val)
                                track.rot_keys.append(RotKey(t, v[0], v[1], v[2], v[3]))
                        elif pid in (7, 8):
                            track.sound_keys.append(SoundKey(
                                time=t,
                                sound_id=key_elem.get('sndSoundId', ''),
                                sound_type=int(key_elem.get('sndtpSoundType', 0)),
                            ))
                        elif pid == 4:
                            track.event_keys.append(EventKey(
                                time=t,
                                event=key_elem.get('event', ''),
                            ))
                        # param 5 keys have no value — skip
                    seq_node.tracks[pid] = track
                seq.nodes.append(seq_node)
            md.sequences.append(seq)

        md._update_hash()
        return md

    # ------------------------------------------------------------------
    def _update_hash(self):
        if self._tree is None:
            return
        buf = BytesIO()
        self._tree.write(buf, encoding='utf-8', xml_declaration=False)
        self._clean_hash = str(hash(buf.getvalue()))

    def is_dirty(self) -> bool:
        if self._tree is None:
            return False
        buf = BytesIO()
        self._tree.write(buf, encoding='utf-8', xml_declaration=False)
        return str(hash(buf.getvalue())) != self._clean_hash

    def save(self):
        """Write back to source_path if dirty."""
        if not self.source_path or self._tree is None:
            return
        try:
            ET.indent(self._tree, space='  ')
        except AttributeError:
            pass
        self._tree.write(self.source_path, encoding='utf-8', xml_declaration=True)
        self._update_hash()

    def get_sequence(self, name: str) -> Optional[MovieSequence]:
        for seq in self.sequences:
            if seq.name == name:
                return seq
        return None

    def entity_id_to_node_def(self, entity_id: str) -> Optional[MovieNodeDef]:
        for nd in self.node_defs.values():
            if nd.entity_id == entity_id:
                return nd
        return None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_vec3(s: str) -> tuple:
    parts = s.split(',')
    return tuple(float(p) for p in parts[:3])


def _parse_vec4(s: str) -> tuple:
    parts = s.split(',')
    return tuple(float(p) for p in parts[:4])


def _maybe_float(s) -> Optional[float]:
    try:
        return float(s) if s is not None else None
    except (ValueError, TypeError):
        return None


def _slerp(q1: tuple, q2: tuple, t: float) -> tuple:
    """Quaternion SLERP. Components are (w, x, y, z)."""
    dot = sum(a * b for a, b in zip(q1, q2))
    if dot < 0.0:
        q2 = tuple(-v for v in q2)
        dot = -dot
    dot = min(1.0, dot)
    if dot > 0.9995:
        result = tuple(a + t * (b - a) for a, b in zip(q1, q2))
        n = math.sqrt(sum(v * v for v in result))
        return tuple(v / n for v in result) if n > 0 else result
    theta0 = math.acos(dot)
    theta = theta0 * t
    s0 = math.sin(theta0)
    s1 = math.cos(theta) - dot * math.sin(theta) / s0
    s2 = math.sin(theta) / s0
    return tuple(s1 * a + s2 * b for a, b in zip(q1, q2))


def find_moviedata_xml(level_info: dict,
                       resource_folder: str = None) -> Optional[str]:
    """
    Locate moviedata.xml for a loaded level.

    Search order:
      1. levels_path/generated/moviedata.xml         (patch folder — modified copy)
      2. Each entry in levels_paths/generated/       (multi-part levels)
      3. worlds_path/generated/moviedata.xml         (worlds folder)
      4. resource_folder/data/levels/<name>/generated/moviedata.xml  (original game data)
      5. Walk up from levels_path looking for data/levels/<name>/    (common layout)
    """
    name = level_info.get('name', '')

    # ── 1. Patch folder — primary levels_path ────────────────────────────────
    lpath = level_info.get('levels_path', '')
    if lpath:
        candidate = os.path.join(lpath, 'generated', 'moviedata.xml')
        if os.path.isfile(candidate):
            return candidate

    # ── 2. Multi-part level paths ─────────────────────────────────────────────
    for lp in level_info.get('levels_paths') or []:
        candidate = os.path.join(lp, 'generated', 'moviedata.xml')
        if os.path.isfile(candidate):
            return candidate

    # ── 3. worlds_path/generated/ ────────────────────────────────────────────
    worlds_path = level_info.get('worlds_path', '')
    if worlds_path:
        candidate = os.path.join(worlds_path, 'generated', 'moviedata.xml')
        if os.path.isfile(candidate):
            return candidate

    # ── 4. resource_folder/data/levels/<name>/generated/ ─────────────────────
    if resource_folder and name:
        candidate = os.path.join(resource_folder, 'data', 'levels', name,
                                 'generated', 'moviedata.xml')
        if os.path.isfile(candidate):
            return candidate

    # ── 5. Walk ancestors of levels_path looking for data/levels/<name>/ ──────
    # Handles layouts like: .../ATGE/patch/levels/<name>  →  .../data/levels/<name>
    if lpath and name:
        root = lpath
        for _ in range(6):   # walk up at most 6 levels
            root = os.path.dirname(root)
            if not root or root == os.path.dirname(root):
                break
            candidate = os.path.join(root, 'data', 'levels', name,
                                     'generated', 'moviedata.xml')
            if os.path.isfile(candidate):
                return candidate

    return None
