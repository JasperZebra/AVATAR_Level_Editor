#!/usr/bin/env python3
"""CS (cutscene) camera POV preview — right-panel dock widget.

Modeled on the Battalion Wars level editor's camera previewer: a small view
that renders the level THROUGH a cutscene camera's lens, with a camera picker
and play/scrub transport. Works for both games (moviedata.xml is the same
format in Avatar and FC2).

Camera pose comes from the moviedata sequence tracks (position keys +
quaternion rotation keys, falling back to the NodeDef rest pose). The
quaternion convention was determined empirically across 101 real cutscene
cameras: **camera forward = +Y in game space** (mean cos 0.58 toward the
sequence's action vs ~0 for every other axis), up = +Z (game world up).

Rendering is done by the MAIN canvas GL context via
map_canvas_gpu.render_camera_preview() (offscreen FBO → QImage) — no second
GL context, so every already-loaded resource (terrain VBOs, model VBOs,
textures) is reused directly.
"""

import math
import time

import numpy as np
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QImage, QPixmap
from PyQt5.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton,
                             QSizePolicy, QSlider, QVBoxLayout, QWidget)

DEFAULT_FOV = 55.0        # moviedata carries no FOV track; game-plausible default
PREVIEW_MAX_W = 640       # FBO cap — the label scales the image up if docked wide
TICK_MS = 50              # 20 fps playback/refresh


# ── Pose math (pure, unit-testable) ───────────────────────────────────────────

def quat_rotate(q, v):
    """Rotate vector v by quaternion q = (w, x, y, z). Active rotation."""
    w, x, y, z = q
    u = np.array([x, y, z], dtype=float)
    v = np.asarray(v, dtype=float)
    return 2.0 * np.dot(u, v) * u + (w * w - np.dot(u, u)) * v + 2.0 * w * np.cross(u, v)


def game_to_gl_point(p):
    """Game world (x, y, z; z-up) → editor GL space (x, z, -y)."""
    return (float(p[0]), float(p[2]), float(-p[1]))


def game_to_gl_dir(d):
    """Direction version of game_to_gl_point (no translation semantics)."""
    return (float(d[0]), float(d[2]), float(-d[1]))


def camera_nodes(movie_data, seq):
    """[(node_id, display_name)] of viewable cameras for a sequence.

    Three tiers (survey across all 106 moviedata files of both games: only
    156 of 568 sequences have a camera among their OWN animated nodes —
    many are filmed by STATIC cameras that live in NodeData but are not
    sequence nodes, and object-only sequences have no camera at all):
      1. camera-named nodes animated IN the sequence,
      2. every other camera-named NodeDef in the whole moviedata (static —
         rest pose; camera_pose_at already falls back to it),
      3. if there are STILL none, the sequence's own nodes ("(node)") so
         the user can at least view from a participant.
    Camera naming: case-insensitive 'cam' in the NodeDef name.
    """
    out = []
    if movie_data is None or seq is None:
        return out
    seen = set()
    for sn in seq.nodes:
        nd = movie_data.node_defs.get(sn.node_id)
        if nd is None:
            continue
        if 'cam' in (nd.name or '').lower():
            out.append((sn.node_id, nd.name or f'Camera {sn.node_id}'))
            seen.add(sn.node_id)
    for nid, nd in sorted(movie_data.node_defs.items(),
                          key=lambda kv: (kv[1].name or '')):
        if nid in seen:
            continue
        if 'cam' in (nd.name or '').lower():
            out.append((nid, f"{nd.name or nid} (static)"))
            seen.add(nid)
    if not out:
        for sn in seq.nodes:
            nd = movie_data.node_defs.get(sn.node_id)
            if nd is not None:
                out.append((sn.node_id, f"{nd.name or sn.node_id} (node)"))
    return out


def camera_pose_at(movie_data, seq, node_id, t):
    """(eye_gl, look_gl, up_gl) for a camera node at sequence time t.

    Position/rotation come from the node's animation tracks, falling back to
    the NodeDef rest pose. Returns None when the node is unknown.
    """
    nd = movie_data.node_defs.get(node_id) if movie_data else None
    if nd is None:
        return None
    sn = seq.node_by_id(node_id) if seq is not None else None

    pos = sn.pos_at(t) if sn is not None else None
    if pos is None:
        pos = nd.pos
    rot = sn.rot_at(t) if sn is not None else None
    if rot is None:
        rot = nd.rotate

    pos = np.asarray(pos, dtype=float)
    fwd = quat_rotate(rot, (0.0, 1.0, 0.0))    # +Y = camera forward (empirical)
    ln = np.linalg.norm(fwd)
    fwd = fwd / ln if ln > 1e-9 else np.array([0.0, 1.0, 0.0])
    up = quat_rotate(rot, (0.0, 0.0, 1.0))     # +Z = camera up (game world up)

    eye = game_to_gl_point(pos)
    look = game_to_gl_point(pos + fwd * 10.0)
    return eye, look, game_to_gl_dir(up)


# ── Widget ─────────────────────────────────────────────────────────────────────

class CSCameraPreviewWidget(QWidget):
    """Header + camera picker + POV image + transport. Lives in a right dock."""

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self._seq_name = None
        self._cam_node_id = None
        self._t = 0.0
        self._playing = False
        self._play_wall = None
        self._last_render_key = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.camera_box = QComboBox()
        self.camera_box.setToolTip("Cutscene camera to look through")
        self.camera_box.currentIndexChanged.connect(self._on_camera_changed)
        layout.addWidget(self.camera_box)

        self.image_label = QLabel("Select a sequence in the Sequences tab")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setWordWrap(True)
        # Ignored horizontal policy: a QLabel's minimum width otherwise
        # follows its pixmap/text width, which forced the whole right panel
        # wider than the dock (= the horizontal scrollbar the user reported).
        self.image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.image_label.setMinimumSize(120, 150)
        self.image_label.setStyleSheet(
            "background-color: #101418; color: #8899aa; border: 1px solid #2a3036;")
        layout.addWidget(self.image_label, 1)

        transport = QHBoxLayout()
        transport.setSpacing(4)
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(28)
        self.play_btn.setToolTip("Play the sequence through this camera "
                                 "(entities animate in the main view too)")
        self.play_btn.clicked.connect(self.toggle_play)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setToolTip("Scrub the sequence")
        self.slider.sliderMoved.connect(self._on_scrub)
        self.time_label = QLabel("--.- / --.-s")
        self.time_label.setFont(QFont("Consolas", 8))
        transport.addWidget(self.play_btn)
        transport.addWidget(self.slider, 1)
        transport.addWidget(self.time_label)
        layout.addLayout(transport)

        # Status line: last render outcome / error — so failures are never
        # silent (a blank preview with no explanation is undebuggable).
        self.status = QLabel("")
        self.status.setFont(QFont("Consolas", 7))
        self.status.setStyleSheet("color: #7f8c99;")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
        layout.addWidget(self.status)

        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self._set_enabled(False)

    # ── state ──────────────────────────────────────────────────────────────

    def _movie(self):
        md = getattr(self.editor, 'movie_data', None)
        seq = md.get_sequence(self._seq_name) if (md and self._seq_name) else None
        return md, seq

    def _set_enabled(self, on):
        self.play_btn.setEnabled(on)
        self.slider.setEnabled(on)
        self.camera_box.setEnabled(on)

    def set_sequence(self, seq_name):
        """Called by the editor when the Sequences-tab selection changes."""
        self.stop_play()
        self._seq_name = seq_name
        self._t = 0.0
        self._last_render_key = None
        self.camera_box.blockSignals(True)
        self.camera_box.clear()
        md, seq = self._movie()
        cams = camera_nodes(md, seq)
        for node_id, name in cams:
            self.camera_box.addItem(name, node_id)
        self.camera_box.blockSignals(False)
        if cams:
            self._cam_node_id = cams[0][0]
            self._set_enabled(True)
            self._render_frame()
        else:
            self._cam_node_id = None
            self._set_enabled(False)
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(
                "No camera node in this sequence" if seq_name
                else "Select a sequence in the Sequences tab")

    def _on_camera_changed(self, index):
        self._cam_node_id = self.camera_box.itemData(index)
        self._last_render_key = None
        self._render_frame()

    # ── transport ──────────────────────────────────────────────────────────

    def toggle_play(self):
        if self._playing:
            self.stop_play()
            return
        md, seq = self._movie()
        if seq is None or self._cam_node_id is None:
            return
        self._playing = True
        self._play_wall = time.time() - self._t   # resume from scrub position
        self.play_btn.setText("■")
        # Animate the entities in the main viewport too (shared clock).
        try:
            starter = getattr(self.editor, '_movie_preview_start', None)
            if starter and not self._editor_preview_active():
                starter()
                # Align the editor's clock with ours so both views agree.
                if getattr(self.editor, '_movie_preview_start_wall', None) is not None:
                    self.editor._movie_preview_start_wall = self._play_wall
        except Exception:
            pass

    def stop_play(self):
        if not self._playing:
            return
        self._playing = False
        self._play_wall = None
        self.play_btn.setText("▶")
        try:
            stopper = getattr(self.editor, '_movie_preview_stop', None)
            if stopper and self._editor_preview_active():
                stopper(restore=True)
        except Exception:
            pass

    def _editor_preview_active(self):
        t = getattr(self.editor, '_movie_preview_timer', None)
        return bool(t is not None and t.isActive())

    def _on_scrub(self, value):
        md, seq = self._movie()
        if seq is None:
            return
        if self._playing:
            self.stop_play()
        self._t = (value / 1000.0) * max(seq.end_time, 1e-6)
        # Move the entities to time t in the main view as well.
        try:
            apply_time = getattr(self.editor, '_movie_apply_time', None)
            if apply_time:
                apply_time(self._t)
        except Exception:
            pass
        self._render_frame()

    # ── ticking / rendering ────────────────────────────────────────────────

    def _tick(self):
        # Self-syncing link: follow the editor's Sequences-tab selection even
        # if the explicit set_sequence hook never fired (creation-order or
        # swallowed-exception proofing — the preview can't be "disconnected").
        ed_seq = getattr(self.editor, 'selected_movie_sequence', None)
        if ed_seq != self._seq_name:
            self.set_sequence(ed_seq)
        if not self.isVisible() or self._cam_node_id is None:
            return
        md, seq = self._movie()
        if seq is None:
            return
        if self._playing:
            # Follow the editor's clock when its preview drives the entities;
            # otherwise use our own.
            wall = getattr(self.editor, '_movie_preview_start_wall', None)
            base = wall if (self._editor_preview_active() and wall is not None) \
                else self._play_wall
            self._t = time.time() - base if base is not None else 0.0
            if self._t >= seq.end_time:
                self._t = seq.end_time
                self.stop_play()
        elif self._editor_preview_active():
            # Sequences-tab Preview is playing — follow it.
            wall = getattr(self.editor, '_movie_preview_start_wall', None)
            if wall is not None:
                self._t = min(time.time() - wall, seq.end_time)
        self._update_transport(seq)
        self._render_frame()

    def _update_transport(self, seq):
        dur = max(seq.end_time, 1e-6)
        self.slider.blockSignals(True)
        self.slider.setValue(int(min(self._t / dur, 1.0) * 1000))
        self.slider.blockSignals(False)
        self.time_label.setText(f"{self._t:5.1f} / {seq.end_time:.1f}s")

    def _render_frame(self):
        md, seq = self._movie()
        if seq is None or self._cam_node_id is None:
            return
        canvas = getattr(self.editor, 'canvas', None)
        if canvas is None or not hasattr(canvas, 'render_camera_preview'):
            self.status.setText("3D canvas not ready")
            return
        w = min(max(self.image_label.width(), 160), PREVIEW_MAX_W)
        h = max(int(w * 9 / 16), 90)
        key = (self._seq_name, self._cam_node_id, round(self._t, 3), w, h,
               id(getattr(self.editor, 'entities', None)))
        if key == self._last_render_key and not self._playing \
                and not self._editor_preview_active():
            return   # nothing changed — skip the (relatively) expensive pass
        pose = camera_pose_at(md, seq, self._cam_node_id, self._t)
        if pose is None:
            self.status.setText("camera node has no pose data")
            return
        eye, look, up = pose
        try:
            img = canvas.render_camera_preview(eye, look, up, DEFAULT_FOV, w, h)
        except Exception as e:
            self.status.setText(f"render error: {e}")
            import traceback
            traceback.print_exc()
            return
        if img is None or img.isNull():
            self.status.setText("render failed — see console log")
            return
        self._last_render_key = key
        pm = QPixmap.fromImage(img).scaled(
            self.image_label.width(), self.image_label.height(),
            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(pm)
        self.status.setText(
            f"cam ({eye[0]:.0f}, {eye[1]:.0f}, {eye[2]:.0f})  t={self._t:.1f}s  {w}x{h}")
