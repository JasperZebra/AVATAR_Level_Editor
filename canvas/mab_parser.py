#!/usr/bin/env python3
"""Native .mab (Dunia skeletal animation) decoder — port of the XBG Importer
v3 addon's `import_mab_avatar.py` decode path (the FC2 decoder is the same
codec; ONE module serves both games).

Avatar: The Game and Far Cry 2 clips use codec version byte 0x4C:
    duration f32 @ 0x84, 9-entry section table @ 0x88.
ALL section offsets stored in the file are relative to byte 16 (SKIP).

Decoded content:
- Routing masks @ 0x10 (constant bones) and @ 0x24 (animated bones): 20 bytes
  each, LSB-first, one bit per animation-skeleton (LKS) bone. Track t of the
  keyframe stream belongs to the LKS bone at the t-th set anim bit. There is
  NO name hashing for skeletal tracks — routing is positional.
- Keyframes: the "smallest-three" compressed quaternion bitstream. 6 bytes
  per quat (two 15-bit unsigned + one SIGNED 16-bit component, scale
  4.315969e-05, bias 1/sqrt(2); FW/SW bit-15 pick which component was
  dropped). Groups of 8 frames: [N primary quats][N mask bytes, even-padded]
  [secondary quats per bone, contiguous]. Mask bit7 = sub-frame 0 (the
  primary, always present); bit(7-sf) = sub-frame sf — flagged keys land at
  bit-position + 1, NOT bit-position (the addon's timing fix).
- RootRot: constant (non-identity, non-animated) bone rotations.
- UnkSec1/UnkSec2: dense per-frame root rotation / world translation;
  Offsets: root local offset in the rotated frame, composed as
  pos = UnkSec2 + R(UnkSec1) @ Offsets_track0.

Output spaces: bone rotations are ABSOLUTE bone-LOCAL (parent-relative)
orientations — not deltas from bind. To pose a model, run FK through the
skeleton (world = parent_world @ local), substituting decoded locals for
animated bones. Twist/helper bones appear in NEITHER mask and carry no data
(the engine drives them procedurally) — leave them at rest.

fps is not stored for the body clip; it is derived as max_frame / duration.

GL-free and bpy-free on purpose.
"""

import math
import os
import struct
from typing import Dict, List, Optional, Tuple

SKIP = 16
QSCALE = 4.315969e-05
QBIAS = 0.7071068

SECTION_LABELS = ('UnkSec2', 'UnkSec1', 'RootRot', 'Keyframes', 'UnkSec3',
                  'Offsets', 'Events', 'UnkSec4', 'UnkSec5')

# version byte -> (animlen_offset, sections_offset)
_VERSIONS = {
    0x4C: (0x84, 0x88),   # Far Cry 2 / Avatar: The Game  (the supported path)
    0x61: (0xC4, 0xC8),   # FC3
    0x62: (0xC4, 0xC8),   # FC3:BD
    0x81: (0xC4, 0xC8),   # FC4
    0x82: (0xC4, 0xC8),   # Primal
    0xB0: (0xC4, 0xC8),   # FC5/ND
}


def unpack_quaternion(d: bytes, p: int) -> Optional[Tuple[float, float, float, float]]:
    """Decode one 6-byte smallest-three quaternion at offset p -> (x,y,z,w).

    Returns None for invalid/sentinel packs (reconstruction under the root).
    The third word is SIGNED (the engine uses movsx) — reading it unsigned is
    a known bug in other community ports.
    """
    fw, sw = struct.unpack_from('<2H', d, p)
    tw = struct.unpack_from('<h', d, p + 4)[0]
    f1 = (fw & 0x7FFF) * QSCALE - QBIAS
    f2 = (sw & 0x7FFF) * QSCALE - QBIAS
    f3 = tw * QSCALE - QBIAS
    s = 1.0 - f1 * f1 - f2 * f2 - f3 * f3
    if s < 0.0:
        return None
    f4 = math.sqrt(s)
    hi1 = (fw >> 15) & 1
    hi2 = (sw >> 15) & 1
    if hi1 == 0 and hi2 == 0:
        return (f4, f1, f2, f3)
    if hi1 == 1 and hi2 == 0:
        return (f1, f4, f2, f3)
    if hi1 == 0 and hi2 == 1:
        return (f1, f2, f4, f3)
    return (f1, f2, f3, f4)


class MabTrack:
    """One animated bone track: sparse absolute-local rotation keys."""
    __slots__ = ('track_index', 'bone_bit', 'bone_name', 'rot_keys')

    def __init__(self, track_index: int, bone_bit: int):
        self.track_index = track_index
        self.bone_bit = bone_bit          # LKS bone index (anim-mask bit pos)
        self.bone_name: Optional[str] = None
        self.rot_keys: List[Tuple[int, Tuple[float, float, float, float]]] = []


class MabClip:
    def __init__(self):
        self.path: str = ''
        self.version: int = 0
        self.duration: float = 0.0        # seconds (animlen @ 0x84)
        self.frame_count: int = 0         # fc (Keyframes header)
        self.fps: float = 30.0            # derived: max_frame / duration
        self.tracks: List[MabTrack] = []  # animated bones, stream order
        self.const_tracks: List[Tuple[int, Tuple[float, float, float, float]]] = []
        #                     ^ (LKS bone index, quat) from RootRot
        self.root_rot_keys: List[Tuple[int, Tuple[float, float, float, float]]] = []
        self.root_pos_keys: List[Tuple[int, Tuple[float, float, float]]] = []
        self.sections: Dict[str, int] = {}   # absolute offsets (0 = absent)
        self.section_sizes: Dict[str, int] = {}

    def resolve_bone_names(self, lks_bone_names: List[str]):
        """Attach bone names once the animation skeleton's (LKS) ordered bone
        list is known. Track routing is positional on that list."""
        for t in self.tracks:
            if 0 <= t.bone_bit < len(lks_bone_names):
                t.bone_name = lks_bone_names[t.bone_bit]

    def time_of_frame(self, frame: int) -> float:
        return frame / self.fps if self.fps > 0 else 0.0


def _mask_bits(d: bytes, off: int, nbytes: int = 20) -> List[int]:
    """Set bit positions of an LSB-first bitmask."""
    out = []
    for i in range(nbytes * 8):
        if (d[off + i // 8] >> (i % 8)) & 1:
            out.append(i)
    return out


def parse_mab(path: str, data: Optional[bytes] = None) -> MabClip:
    """Decode a .mab clip. Raises ValueError on unsupported codec versions."""
    d = data if data is not None else open(path, 'rb').read()
    clip = MabClip()
    clip.path = path
    clip.version = d[0]
    layout = _VERSIONS.get(clip.version)
    if layout is None:
        layout = _VERSIONS[0x4C]
    animlen_off, sections_off = layout
    if layout != (0x84, 0x88):
        raise ValueError(f"unsupported .mab codec 0x{clip.version:02X} "
                         f"(FC3+ layout) — Avatar/FC2 clips are 0x4C")
    if len(d) < sections_off + 36:
        raise ValueError("file too small for a .mab header")

    clip.duration = struct.unpack_from('<f', d, animlen_off)[0]
    raw_sections = struct.unpack_from('<9i', d, sections_off)
    for label, raw in zip(SECTION_LABELS, raw_sections):
        clip.sections[label] = (raw + SKIP) if raw > 0 else 0

    # Section sizes: gaps between sorted present raw offsets; last runs to EOF.
    present = sorted(r for r in raw_sections if r > 0)
    for label, raw in zip(SECTION_LABELS, raw_sections):
        if raw <= 0:
            clip.section_sizes[label] = 0
            continue
        nxt = next((p for p in present if p > raw), len(d) - SKIP)
        clip.section_sizes[label] = nxt - raw

    kf = clip.sections.get('Keyframes', 0)
    if kf:
        _decode_keyframes(d, kf, clip)

    rr = clip.sections.get('RootRot', 0)
    if rr and clip.section_sizes['RootRot'] >= 8:
        cnt = struct.unpack_from('<i', d, rr)[0]
        cbits = _mask_bits(d, 0x10)
        if 0 <= cnt <= len(cbits):
            for j in range(cnt):
                q = unpack_quaternion(d, rr + 8 + j * 6)
                if q is not None:
                    clip.const_tracks.append((cbits[j], q))

    _decode_root_motion(d, clip)

    # fps: derived — the body stream stores no rate. Addon rule: fps =
    # max DECODED frame / duration (falls back to fc-1 with no keys).
    max_frame = 0
    for t in clip.tracks:
        if t.rot_keys:
            max_frame = max(max_frame, t.rot_keys[-1][0])
    for f, _q in clip.root_rot_keys[-1:]:
        max_frame = max(max_frame, f)
    if max_frame == 0:
        max_frame = max(clip.frame_count - 1, 0)
    if clip.duration > 1e-6 and max_frame > 0:
        clip.fps = max_frame / clip.duration
    return clip


def _decode_keyframes(d: bytes, kf: int, clip: MabClip):
    """The DLL-accurate multi-bone group decoder (addon decode_full_keyframes).

    Group g covers frames g*8+0..7. Block layout:
        [N primary quats (6B)] [N mask bytes, even-padded] [secondary quats]
    Mask bit7 = sub-frame 0 (primary, always emitted); bit(7-sf) = sub-frame
    sf for sf=1..7 (MSB-first) — i.e. flagged keys land at bit-position+1.
    Secondary quats are contiguous PER BONE in bone order.
    """
    n, fc = struct.unpack_from('<2H', d, kf)
    clip.frame_count = fc
    if n == 0 or fc == 0:
        return
    anim_bits = _mask_bits(d, 0x24)
    ngroups = ((max(1, fc) - 1) >> 3) + 1
    offsets = struct.unpack_from('<%di' % (ngroups + 1), d, kf + 8)

    tracks = [MabTrack(i, anim_bits[i] if i < len(anim_bits) else -1)
              for i in range(n)]
    bmsize = (n + 1) & ~1

    for g in range(ngroups):
        block = kf + offsets[g]
        end = kf + offsets[g + 1]
        if block < kf or end > len(d) or block >= end:
            continue
        bm = block + 6 * n
        sec = bm + bmsize
        if sec > end:
            continue
        base_frame = g * 8
        for i in range(n):
            q = unpack_quaternion(d, block + i * 6)
            if q is not None and base_frame < fc:
                tracks[i].rot_keys.append((base_frame, q))
            mask = d[bm + i]
            for sf in range(1, 8):
                if (mask >> (7 - sf)) & 1:
                    if sec + 6 > end:
                        break
                    q = unpack_quaternion(d, sec)
                    sec += 6
                    frame = base_frame + sf
                    if q is not None and frame < fc:
                        tracks[i].rot_keys.append((frame, q))
    clip.tracks = tracks


def _decode_root_motion(d: bytes, clip: MabClip):
    """UnkSec1 (rotation) / UnkSec2 (translation) + Offsets composition.

    Both share an 8-byte header (u16 unk, u16 fc, u32 unk); then fc+1 dense
    samples: 6-byte quats (UnkSec1) / 3xf32 (UnkSec2). Offsets adds the root's
    local bob/sway in the rotated frame: pos = trans + R(rot) @ off_track0.
    """
    s1 = clip.sections.get('UnkSec1', 0)
    s2 = clip.sections.get('UnkSec2', 0)
    rot_keys, pos_keys = [], []
    n = 0
    if s1 and clip.section_sizes['UnkSec1'] >= 8:
        fc1 = struct.unpack_from('<H', d, s1 + 2)[0]
        n = fc1 + 1
        avail = (clip.section_sizes['UnkSec1'] - 8) // 6
        for f in range(min(n, avail)):
            q = unpack_quaternion(d, s1 + 8 + f * 6)
            if q is not None:
                rot_keys.append((f, q))
    if s2 and clip.section_sizes['UnkSec2'] >= 8:
        fc2 = struct.unpack_from('<H', d, s2 + 2)[0]
        n2 = fc2 + 1
        avail = (clip.section_sizes['UnkSec2'] - 8) // 12
        for f in range(min(n2, avail)):
            pos_keys.append((f, struct.unpack_from('<3f', d, s2 + 8 + f * 12)))

    # Offsets: u16 tracks, u16 fc, u32 fps, then (fc+1) x tracks x vec3,
    # frame-major. Track 0 composes onto the root translation.
    so = clip.sections.get('Offsets', 0)
    if so and clip.section_sizes['Offsets'] >= 8 and pos_keys and rot_keys:
        tr, fco = struct.unpack_from('<2H', d, so)
        if tr > 0:
            rot_by_frame = dict(rot_keys)
            stride = tr * 12
            navail = (clip.section_sizes['Offsets'] - 8) // stride if stride else 0
            composed = []
            for f, pos in pos_keys:
                if f < navail:
                    off = struct.unpack_from('<3f', d, so + 8 + f * stride)
                    q = rot_by_frame.get(f)
                    if q is not None and any(abs(c) > 1e-9 for c in off):
                        off = _quat_rotate(q, off)
                    pos = (pos[0] + off[0], pos[1] + off[1], pos[2] + off[2])
                composed.append((f, pos))
            pos_keys = composed

    clip.root_rot_keys = rot_keys
    clip.root_pos_keys = pos_keys


def _quat_rotate(q, v):
    """Rotate vec3 v by quat (x, y, z, w)."""
    x, y, z, w = q
    ux, uy, uz = x, y, z
    dot2 = 2.0 * (ux * v[0] + uy * v[1] + uz * v[2])
    ww = w * w - (ux * ux + uy * uy + uz * uz)
    cx = uy * v[2] - uz * v[1]
    cy = uz * v[0] - ux * v[2]
    cz = ux * v[1] - uy * v[0]
    return (dot2 * ux + ww * v[0] + 2.0 * w * cx,
            dot2 * uy + ww * v[1] + 2.0 * w * cy,
            dot2 * uz + ww * v[2] + 2.0 * w * cz)
