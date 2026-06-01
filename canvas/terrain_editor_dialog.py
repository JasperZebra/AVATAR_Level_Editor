"""
Terrain Editor for Avatar: The Game Level Editor.
2D heightmap painting + 3D orbit preview with live canvas updates.
Avatar .csdat only (terrain at offset 708, 65x65 samples, uint16/128).
"""

import os
import io
import math
import struct
import numpy as np

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton, QLabel,
    QSlider, QGroupBox, QSizePolicy, QFileDialog, QMessageBox,
    QFrame, QWidget, QLineEdit, QButtonGroup, QToolButton
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen, QImage, QPixmap, QFont, QCursor
from PyQt6.QtOpenGLWidgets import QOpenGLWidget

try:
    from OpenGL.GL import (
        glClear, glClearColor, glEnable, glDisable, glDepthFunc,
        glMatrixMode, glLoadIdentity, glViewport, glShadeModel,
        glEnableClientState, glDisableClientState,
        glVertexPointer, glColorPointer, glDrawElements,
        glBegin, glEnd, glVertex3f, glColor3f, glLineWidth,
        GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_DEPTH_TEST,
        GL_LEQUAL, GL_SMOOTH, GL_PROJECTION, GL_MODELVIEW,
        GL_FLOAT, GL_UNSIGNED_INT, GL_TRIANGLES, GL_LINE_LOOP, GL_LINES,
        GL_VERTEX_ARRAY, GL_COLOR_ARRAY,
    )
    from OpenGL.GLU import gluPerspective, gluLookAt
    _GL = True
except ImportError:
    _GL = False

_TERRAIN_OFFSET = 708
_GRID_SIZE = 65
_PREVIEW_STRIDE = 2   # downsample combined map for 3D mesh (1040/2 = 520 verts/side)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_elevation_image(combined: np.ndarray) -> QImage:
    """Convert a float32 combined heightmap array to a coloured QImage."""
    h, w = combined.shape
    min_v, max_v = float(combined.min()), float(combined.max())
    span = max_v - min_v if max_v > min_v else 1.0
    norm = ((combined - min_v) / span).astype(np.float32)

    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    wm = norm < 0.2
    lm = (norm >= 0.2) & (norm < 0.4)
    mm = (norm >= 0.4) & (norm < 0.7)
    hm = norm >= 0.7

    rgb[wm, 0] = (norm[wm] * 50).astype(np.uint8)
    rgb[wm, 1] = (norm[wm] * 100 + 50).astype(np.uint8)
    rgb[wm, 2] = (norm[wm] * 155 + 100).astype(np.uint8)

    rgb[lm, 0] = (norm[lm] * 50).astype(np.uint8)
    rgb[lm, 1] = (norm[lm] * 180 + 50).astype(np.uint8)
    rgb[lm, 2] = (norm[lm] * 50).astype(np.uint8)

    rgb[mm, 0] = (norm[mm] * 160 + 80).astype(np.uint8)
    rgb[mm, 1] = (norm[mm] * 120 + 60).astype(np.uint8)
    rgb[mm, 2] = (norm[mm] * 60).astype(np.uint8)

    rgb[hm, 0] = (norm[hm] * 200 + 55).astype(np.uint8)
    rgb[hm, 1] = (norm[hm] * 200 + 55).astype(np.uint8)
    rgb[hm, 2] = (norm[hm] * 200 + 55).astype(np.uint8)

    img = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
    return img.copy()   # deep-copy so numpy buffer can be freed


def _elevation_colors_3d(norm_flat: np.ndarray) -> np.ndarray:
    """Return (N,3) float32 RGB colours from normalised heights."""
    r = np.zeros_like(norm_flat)
    g = np.zeros_like(norm_flat)
    b = np.zeros_like(norm_flat)

    wm = norm_flat < 0.2
    lm = (norm_flat >= 0.2) & (norm_flat < 0.4)
    mm = (norm_flat >= 0.4) & (norm_flat < 0.7)
    hm = norm_flat >= 0.7

    r[wm] = norm_flat[wm] * (50/255);  g[wm] = norm_flat[wm]*(100/255)+(50/255);  b[wm] = norm_flat[wm]*(155/255)+(100/255)
    r[lm] = norm_flat[lm] * (50/255);  g[lm] = norm_flat[lm]*(180/255)+(50/255);  b[lm] = norm_flat[lm]*(50/255)
    r[mm] = norm_flat[mm]*(160/255)+(80/255); g[mm] = norm_flat[mm]*(120/255)+(60/255); b[mm] = norm_flat[mm]*(60/255)
    r[hm] = norm_flat[hm]*(200/255)+(55/255); g[hm] = norm_flat[hm]*(200/255)+(55/255); b[hm] = norm_flat[hm]*(200/255)+(55/255)

    return np.stack([r, g, b], axis=1).astype(np.float32)


# ---------------------------------------------------------------------------
# TerrainData — in-memory state
# ---------------------------------------------------------------------------

class TerrainData:
    """Holds all terrain state for the editor session."""

    _MAX_UNDO = 20

    def __init__(self):
        self.sdat_path: str = ""
        self.sectors_x: int = 16
        self.sectors_y: int = 16
        self.grid_size: int = _GRID_SIZE
        self.sectors_data: dict = {}        # sector_num → (65,65) float32
        self.combined: np.ndarray = None    # (sy*65, sx*65) float32, display order
        self.dirty_sectors: set = set()
        self._undo: list = []
        self._redo: list = []

    # -- Loading -------------------------------------------------------------

    def load(self, sdat_path: str) -> bool:
        import glob
        files = glob.glob(os.path.join(sdat_path, "sd*.csdat"))
        if not files:
            return False

        self.sdat_path = sdat_path
        self.sectors_data = {}

        for fp in files:
            name = os.path.basename(fp)
            try:
                num = int(name[2:-6])   # strip "sd" prefix and ".csdat"
                arr = self._read_sector(fp)
                if arr is not None:
                    self.sectors_data[num] = arr
            except (ValueError, IndexError):
                continue

        if not self.sectors_data:
            return False

        max_s = max(self.sectors_data)
        g = int(math.ceil(math.sqrt(max_s + 1)))
        self.sectors_x = g
        self.sectors_y = g
        self._rebuild_combined()
        self.dirty_sectors.clear()
        self._undo.clear()
        self._redo.clear()
        return True

    def _read_sector(self, fp: str):
        try:
            with open(fp, 'rb') as f:
                f.seek(_TERRAIN_OFFSET)
                raw = io.BytesIO(f.read(_GRID_SIZE * _GRID_SIZE * 4))
            arr = np.zeros((_GRID_SIZE, _GRID_SIZE), dtype=np.float32)
            for y in range(_GRID_SIZE):
                for x in range(_GRID_SIZE):
                    data = raw.read(2)
                    if len(data) < 2:
                        break
                    arr[y, x] = int.from_bytes(data, 'little') / 128.0
                    raw.read(2)
            return arr
        except Exception as e:
            print(f"[TerrainEditor] Error reading {fp}: {e}")
            return None

    def _rebuild_combined(self):
        sx, sy = self.sectors_x, self.sectors_y
        gs = self.grid_size   # 65 samples per side
        step = gs - 1         # 64 steps — sectors share edge pixels
        combined = np.zeros((sy * step + 1, sx * step + 1), dtype=np.float32)
        for dr in range(sy):
            for col in range(sx):
                sr = sy - 1 - dr
                idx = sr * sx + col
                if idx in self.sectors_data:
                    r0 = dr * step
                    c0 = col * step
                    combined[r0:r0+gs, c0:c0+gs] = np.flipud(self.sectors_data[idx])
        self.combined = combined

    # -- Undo / Redo ---------------------------------------------------------

    def push_undo(self):
        if self.combined is None:
            return
        self._undo.append(self.combined.copy())
        if len(self._undo) > self._MAX_UNDO:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self) -> bool:
        if not self._undo or self.combined is None:
            return False
        self._redo.append(self.combined.copy())
        self.combined = self._undo.pop()
        self.dirty_sectors = set(range(self.sectors_x * self.sectors_y))
        return True

    def redo(self) -> bool:
        if not self._redo or self.combined is None:
            return False
        self._undo.append(self.combined.copy())
        self.combined = self._redo.pop()
        self.dirty_sectors = set(range(self.sectors_x * self.sectors_y))
        return True

    # -- Save ----------------------------------------------------------------

    def save_dirty_sectors(self) -> tuple:
        written = failed = 0
        for sector_idx in list(self.dirty_sectors):
            sx, sy, gs = self.sectors_x, self.sectors_y, self.grid_size
            step = gs - 1
            sr = sector_idx // sx
            col = sector_idx % sx
            dr = sy - 1 - sr
            r0 = dr * step
            c0 = col * step
            region = np.flipud(self.combined[r0:r0+gs, c0:c0+gs])   # back to file order
            fp = os.path.join(self.sdat_path, f"sd{sector_idx}.csdat")
            if not os.path.isfile(fp):
                continue
            if self._write_sector(fp, region):
                written += 1
            else:
                failed += 1
        self.dirty_sectors.clear()
        return written, failed

    def _write_sector(self, fp: str, height_data: np.ndarray) -> bool:
        try:
            with open(fp, 'rb') as f:
                data = bytearray(f.read())

            section_size = _GRID_SIZE * _GRID_SIZE * 4
            terrain_raw = np.frombuffer(
                bytes(data[_TERRAIN_OFFSET:_TERRAIN_OFFSET + section_size]),
                dtype=np.uint8
            ).reshape(_GRID_SIZE * _GRID_SIZE, 4).copy()

            new_u16 = np.clip(height_data.flatten() * 128, 0, 65535).astype(np.uint16)
            terrain_raw[:, 0:2] = new_u16.astype('<u2').view(np.uint8).reshape(-1, 2)
            data[_TERRAIN_OFFSET:_TERRAIN_OFFSET + section_size] = bytes(terrain_raw.flatten())

            with open(fp, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            return True
        except Exception as e:
            print(f"[TerrainEditor] Write failed {fp}: {e}")
            return False

    # -- Dirty sector marking ------------------------------------------------

    def mark_dirty_from_brush(self, cx: int, cy: int, radius: int):
        gs = self.grid_size
        step = gs - 1   # 64 steps between shared edges
        sx, sy = self.sectors_x, self.sectors_y
        dr0 = max(0, (cy - radius) // step)
        dr1 = min(sy - 1, (cy + radius) // step)
        c0  = max(0, (cx - radius) // step)
        c1  = min(sx - 1, (cx + radius) // step)
        for dr in range(dr0, dr1 + 1):
            for col in range(c0, c1 + 1):
                sr = sy - 1 - dr
                self.dirty_sectors.add(sr * sx + col)


# ---------------------------------------------------------------------------
# HeightmapEditor2D — left panel
# ---------------------------------------------------------------------------

class HeightmapEditor2D(QWidget):
    stroke_at  = pyqtSignal(int, int)   # heightmap pixel coords
    stroke_end = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(300, 300)

        self._pixmap: QPixmap = None
        self._map_w = 0
        self._map_h = 0

        # View state (pan + zoom)
        self._zoom  = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._mid_drag = False
        self._last_mid: QPoint = None

        # WASD movement
        self._keys_held: set = set()
        self._move_timer = QTimer(self)
        self._move_timer.setInterval(16)
        self._move_timer.timeout.connect(self._tick_movement)

        # Brush state
        self._brush_radius = 20    # in heightmap pixels
        self._pressing = False
        self._mouse_map: tuple = None   # current (mx, my) in map pixels

    def set_image(self, qimage: QImage, map_w: int, map_h: int):
        self._pixmap = QPixmap.fromImage(qimage)
        self._map_w  = map_w
        self._map_h  = map_h
        self._zoom   = 1.0
        self._pan_x  = 0.0
        self._pan_y  = 0.0
        self.update()

    def update_image(self, qimage: QImage):
        self._pixmap = QPixmap.fromImage(qimage)
        self.update()

    def set_brush_radius(self, r: int):
        self._brush_radius = max(1, r)
        self.update()

    # -- Coordinate helpers --------------------------------------------------

    def _fit_scale(self) -> float:
        if not self._map_w or not self._map_h:
            return 1.0
        return min(self.width() / self._map_w, self.height() / self._map_h)

    def _display_scale(self) -> float:
        return self._fit_scale() * self._zoom

    def _img_origin(self):
        s = self._display_scale()
        ox = (self.width()  - self._map_w * s) / 2 + self._pan_x
        oy = (self.height() - self._map_h * s) / 2 + self._pan_y
        return ox, oy

    def _to_map(self, wx: float, wy: float):
        ox, oy = self._img_origin()
        s = self._display_scale()
        if s == 0:
            return 0, 0
        mx = int((wx - ox) / s)
        my = int((wy - oy) / s)
        mx = max(0, min(self._map_w - 1, mx))
        my = max(0, min(self._map_h - 1, my))
        return mx, my

    # -- Paint ---------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(20, 20, 30))

        if self._pixmap is None:
            painter.setPen(QColor(120, 120, 120))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No terrain loaded")
            return

        s = self._display_scale()
        ox, oy = self._img_origin()
        dw = int(self._map_w * s)
        dh = int(self._map_h * s)
        painter.drawPixmap(int(ox), int(oy), dw, dh, self._pixmap)

        # Sector grid lines (every _GRID_SIZE map pixels)
        gs_px = _GRID_SIZE * s
        if gs_px >= 4:
            painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
            x = ox
            while x <= ox + dw + 1:
                painter.drawLine(int(x), int(oy), int(x), int(oy + dh))
                x += gs_px
            y = oy
            while y <= oy + dh + 1:
                painter.drawLine(int(ox), int(y), int(ox + dw), int(y))
                y += gs_px

        # Brush cursor
        if self._mouse_map is not None:
            mx, my = self._mouse_map
            cx = int(ox + mx * s)
            cy = int(oy + my * s)
            r_px = int(self._brush_radius * s)
            painter.setPen(QPen(QColor(255, 255, 0, 200), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(cx - r_px, cy - r_px, r_px * 2, r_px * 2)
            painter.setPen(QPen(QColor(255, 255, 0, 200), 1))
            painter.drawLine(cx - 4, cy, cx + 4, cy)
            painter.drawLine(cx, cy - 4, cx, cy + 4)

    # -- Mouse ---------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._mid_drag = True
            self._last_mid = event.position().toPoint()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._pixmap is not None:
            self._pressing = True
            mx, my = self._to_map(event.position().x(), event.position().y())
            self._mouse_map = (mx, my)
            self.stroke_at.emit(mx, my)
            self.update()

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._mid_drag and self._last_mid is not None:
            dp = pos.toPoint() - self._last_mid
            self._pan_x += dp.x()
            self._pan_y += dp.y()
            self._last_mid = pos.toPoint()
            self.update()
            return
        mx, my = self._to_map(pos.x(), pos.y())
        self._mouse_map = (mx, my)
        if self._pressing and self._pixmap is not None:
            self.stroke_at.emit(mx, my)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._mid_drag = False
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressing = False
            self.stroke_end.emit()

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        pos = event.position()
        s_old = self._display_scale()
        # Map coord under cursor before zoom
        ox_old = (self.width()  - self._map_w * s_old) / 2 + self._pan_x
        oy_old = (self.height() - self._map_h * s_old) / 2 + self._pan_y
        mx = (pos.x() - ox_old) / s_old
        my = (pos.y() - oy_old) / s_old
        self._zoom = max(0.1, min(20.0, self._zoom * factor))
        s_new = self._display_scale()
        # Recompute pan so the same map point stays under the cursor
        self._pan_x = pos.x() - (self.width()  - self._map_w * s_new) / 2 - mx * s_new
        self._pan_y = pos.y() - (self.height() - self._map_h * s_new) / 2 - my * s_new
        self.update()

    def leaveEvent(self, event):
        self._mouse_map = None
        self.update()

    def keyPressEvent(self, event):
        self._keys_held.add(event.key())
        if not self._move_timer.isActive():
            self._move_timer.start()
        event.accept()

    def keyReleaseEvent(self, event):
        self._keys_held.discard(event.key())
        if not self._keys_held:
            self._move_timer.stop()
        event.accept()

    def _tick_movement(self):
        speed = 15.0
        moved = False
        if Qt.Key.Key_W in self._keys_held:
            self._pan_y += speed;  moved = True
        if Qt.Key.Key_S in self._keys_held:
            self._pan_y -= speed;  moved = True
        if Qt.Key.Key_A in self._keys_held:
            self._pan_x += speed;  moved = True
        if Qt.Key.Key_D in self._keys_held:
            self._pan_x -= speed;  moved = True
        if moved:
            self.update()


# ---------------------------------------------------------------------------
# TerrainPreview3D — FPS camera (matches main level editor 3D view)
# ---------------------------------------------------------------------------

class TerrainPreview3D(QOpenGLWidget):

    stroke_at  = pyqtSignal(int, int)
    stroke_end = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(300, 300)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self._td: TerrainData = None
        self._verts  = None
        self._colors = None
        self._indices = None

        # FPS camera — same convention as Camera3D in map_canvas_gpu.py
        self._cam_pos   = np.array([520.0, 400.0, 520.0], dtype=float)
        self._cam_yaw   = -90.0
        self._cam_pitch = -30.0
        self._cam_fwd   = np.zeros(3)
        self._cam_right = np.zeros(3)
        self._cam_up    = np.zeros(3)
        self._update_camera_vectors()

        # Movement flags
        self._move = {'FORWARD': False, 'BACKWARD': False,
                      'LEFT': False, 'RIGHT': False,
                      'UP': False, 'DOWN': False}
        self._shift_held = False

        # Mouse look (right-click capture + warp, same as main editor)
        self._mouse_captured = False
        self._mouse_anchor   = None   # global QPoint

        # Brush painting
        self._brush_radius = 20
        self._pressing     = False
        self._hit_pos      = None   # (wx, wy, wz) world hit point
        self._hit_map      = None   # (hx, hy) heightmap pixel coords

        # 16 ms movement tick
        self._move_timer = QTimer(self)
        self._move_timer.setInterval(16)
        self._move_timer.timeout.connect(self._tick_movement)

    # -- Camera helpers -------------------------------------------------------

    def _update_camera_vectors(self):
        yr = math.radians(self._cam_yaw)
        pr = math.radians(self._cam_pitch)
        fwd = np.array([math.cos(pr) * math.cos(yr),
                        math.sin(pr),
                        math.cos(pr) * math.sin(yr)])
        self._cam_fwd = fwd / np.linalg.norm(fwd)
        world_up = np.array([0.0, 1.0, 0.0])
        right = np.cross(world_up, self._cam_fwd)
        r_len = np.linalg.norm(right)
        self._cam_right = right / r_len if r_len > 1e-6 else np.array([1.0, 0.0, 0.0])
        up = np.cross(self._cam_fwd, self._cam_right)
        self._cam_up = up / np.linalg.norm(up)

    def _position_camera_at_terrain(self):
        if self._td is None or self._td.combined is None:
            return
        h, w = self._td.combined.shape
        mid_y = float(np.median(self._td.combined))
        self._cam_pos   = np.array([w / 2.0, mid_y + max(w, h) * 0.6, h / 2.0])
        self._cam_yaw   = -90.0
        self._cam_pitch = -35.0
        self._update_camera_vectors()

    # -- Terrain data ---------------------------------------------------------

    def set_terrain(self, td: TerrainData):
        self._td = td
        if self.isValid():
            self.makeCurrent()
            self._build_mesh()
            self.doneCurrent()
        self._position_camera_at_terrain()
        self.update()

    def rebuild_mesh(self):
        if not self.isValid():
            return
        self.makeCurrent()
        self._build_mesh()
        self.doneCurrent()
        self.update()

    def _build_mesh(self):
        if self._td is None or self._td.combined is None:
            return
        td = self._td
        s  = _PREVIEW_STRIDE
        sampled = td.combined[::s, ::s].astype(np.float32)
        nz, nx  = sampled.shape

        x_lin = np.linspace(0, td.combined.shape[1], nx, dtype=np.float32)
        z_lin = np.linspace(0, td.combined.shape[0], nz, dtype=np.float32)
        xx, zz = np.meshgrid(x_lin, z_lin)

        self._verts = np.ascontiguousarray(
            np.stack([xx.flatten(), sampled.flatten(), zz.flatten()], axis=1),
            dtype=np.float32)

        min_h = float(td.combined.min())
        max_h = float(td.combined.max())
        norm  = (sampled - min_h) / (max_h - min_h + 1e-6)
        self._colors = np.ascontiguousarray(_elevation_colors_3d(norm.flatten()), dtype=np.float32)

        ri = np.arange(nz - 1, dtype=np.uint32)
        ci = np.arange(nx - 1, dtype=np.uint32)
        rr, cc = np.meshgrid(ri, ci, indexing='ij')
        tl = (rr * nx + cc).flatten()
        tr = tl + 1
        bl = ((rr + 1) * nx + cc).flatten()
        br = bl + 1
        self._indices = np.ascontiguousarray(
            np.column_stack([tl, bl, tr, tr, bl, br]).flatten(), dtype=np.uint32)

    # -- OpenGL ---------------------------------------------------------------

    def initializeGL(self):
        if not _GL:
            return
        glClearColor(0.15, 0.15, 0.20, 1.0)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        glShadeModel(GL_SMOOTH)
        if self._td and self._td.combined is not None:
            self._build_mesh()
            self._position_camera_at_terrain()

    def resizeGL(self, w, h):
        if _GL:
            glViewport(0, 0, w, max(1, h))

    def paintGL(self):
        if not _GL:
            return
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        if self._verts is None or len(self._verts) == 0:
            return

        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(50.0, self.width() / max(1, self.height()), 0.1, 500000.0)

        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        look = self._cam_pos + self._cam_fwd
        gluLookAt(self._cam_pos[0], self._cam_pos[1], self._cam_pos[2],
                  look[0], look[1], look[2],
                  0.0, 1.0, 0.0)

        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_COLOR_ARRAY)
        glVertexPointer(3, GL_FLOAT, 0, self._verts)
        glColorPointer(3,  GL_FLOAT, 0, self._colors)
        glDrawElements(GL_TRIANGLES, len(self._indices), GL_UNSIGNED_INT, self._indices)
        glDisableClientState(GL_VERTEX_ARRAY)
        glDisableClientState(GL_COLOR_ARRAY)

        if self._hit_pos is not None:
            self._draw_brush_gizmo(*self._hit_pos, self._brush_radius)

    # -- Brush gizmo ----------------------------------------------------------

    def set_brush_radius(self, r: int):
        self._brush_radius = max(1, r)

    def _ray_terrain_hit(self, sx: float, sy: float):
        """Cast ray through screen pixel → (wx, wy, wz, hx, hy) or None."""
        if self._td is None or self._td.combined is None:
            return None

        yr = math.radians(self._cam_yaw)
        pr = math.radians(self._cam_pitch)
        fx = math.cos(pr) * math.cos(yr)
        fy = math.sin(pr)
        fz = math.cos(pr) * math.sin(yr)

        # Camera right/up basis
        rx = -fz;  rz = fx
        rm = math.sqrt(rx*rx + rz*rz)
        if rm > 1e-6: rx /= rm;  rz /= rm
        ux = -rz * fy;  uy = rz * fx - rx * fz;  uz = rx * fy
        um = math.sqrt(ux*ux + uy*uy + uz*uz)
        if um > 1e-6: ux /= um;  uy /= um;  uz /= um

        ndcx = 2.0 * sx / max(1, self.width())  - 1.0
        ndcy = 1.0 - 2.0 * sy / max(1, self.height())
        ht   = math.tan(math.radians(25.0))   # half-FOV of 50°
        asp  = self.width() / max(1, self.height())

        rdx = fx + ndcx * ht * asp * rx + ndcy * ht * ux
        rdy = fy + ndcx * ht * asp * 0  + ndcy * ht * uy
        rdz = fz + ndcx * ht * asp * rz + ndcy * ht * uz
        rm2  = math.sqrt(rdx*rdx + rdy*rdy + rdz*rdz)
        if rm2 > 1e-6: rdx /= rm2;  rdy /= rm2;  rdz /= rm2

        combined = self._td.combined
        ch, cw = combined.shape
        ox, oy, oz = self._cam_pos

        step     = 8.0
        max_dist = max(cw, ch) * 4.0
        prev_t   = 0.0
        t        = step

        while t < max_dist:
            px = ox + rdx * t
            pz = oz + rdz * t
            py = oy + rdy * t
            ix = int(px);  iz = int(pz)
            if 0 <= ix < cw and 0 <= iz < ch:
                if py <= float(combined[iz, ix]):
                    # Binary search between prev_t and t
                    lo, hi = prev_t, t
                    for _ in range(10):
                        mid = (lo + hi) * 0.5
                        mx = ox + rdx * mid;  my = oy + rdy * mid;  mz = oz + rdz * mid
                        mix = int(np.clip(mx, 0, cw - 1))
                        miz = int(np.clip(mz, 0, ch - 1))
                        if my <= float(combined[miz, mix]):
                            hi = mid
                        else:
                            lo = mid
                    mid = (lo + hi) * 0.5
                    hx  = int(np.clip(ox + rdx * mid, 0, cw - 1))
                    hz  = int(np.clip(oz + rdz * mid, 0, ch - 1))
                    wy  = float(combined[hz, hx])
                    return (ox + rdx * mid, wy, oz + rdz * mid, hx, hz)
            prev_t = t
            t += step

        return None

    def _draw_brush_gizmo(self, wx: float, wy: float, wz: float, radius: int):
        """Draw a terrain-conforming yellow circle at the hit point."""
        if not _GL or self._td is None or self._td.combined is None:
            return
        combined = self._td.combined
        ch, cw = combined.shape

        glDisable(GL_DEPTH_TEST)
        glLineWidth(2.0)
        glColor3f(1.0, 1.0, 0.0)

        N = 64
        glBegin(GL_LINE_LOOP)
        for i in range(N):
            angle = 2.0 * math.pi * i / N
            px = wx + radius * math.cos(angle)
            pz = wz + radius * math.sin(angle)
            ix = int(np.clip(px, 0, cw - 1))
            iz = int(np.clip(pz, 0, ch - 1))
            py = float(combined[iz, ix]) + 2.0
            glVertex3f(px, py, pz)
        glEnd()

        # Cross-hair dot
        glBegin(GL_LINES)
        glVertex3f(wx - 4, wy + 2, wz);  glVertex3f(wx + 4, wy + 2, wz)
        glVertex3f(wx, wy + 2, wz - 4);  glVertex3f(wx, wy + 2, wz + 4)
        glEnd()

        glLineWidth(1.0)
        glEnable(GL_DEPTH_TEST)

    # -- Movement tick --------------------------------------------------------

    def _tick_movement(self):
        speed = 20.0 if self._shift_held else 4.0
        m = self._move
        moved = False
        if m['FORWARD']:  self._cam_pos += self._cam_fwd   * speed;  moved = True
        if m['BACKWARD']: self._cam_pos -= self._cam_fwd   * speed;  moved = True
        if m['LEFT']:     self._cam_pos += self._cam_right * speed;  moved = True
        if m['RIGHT']:    self._cam_pos -= self._cam_right * speed;  moved = True
        if m['UP']:       self._cam_pos += self._cam_up    * speed;  moved = True
        if m['DOWN']:     self._cam_pos -= self._cam_up    * speed;  moved = True
        if moved:
            self.update()

    # -- Mouse ----------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._mouse_captured = True
            self.setCursor(Qt.CursorShape.BlankCursor)
            self._mouse_anchor = self.mapToGlobal(event.position().toPoint())
        elif event.button() == Qt.MouseButton.LeftButton:
            self._pressing = True
            if self._hit_map is not None:
                self.stroke_at.emit(self._hit_map[0], self._hit_map[1])
        self.setFocus()

    def mouseMoveEvent(self, event):
        pos = event.position()

        if self._mouse_captured and self._mouse_anchor is not None:
            cur = self.mapToGlobal(pos.toPoint())
            dx = cur.x() - self._mouse_anchor.x()
            dy = cur.y() - self._mouse_anchor.y()
            if dx != 0 or dy != 0:
                self._cam_yaw   += dx * 0.2
                self._cam_pitch -= dy * 0.2
                self._cam_pitch  = max(-89.0, min(89.0, self._cam_pitch))
                self._update_camera_vectors()
                QCursor.setPos(self._mouse_anchor)
                self._hit_pos = None
                self._hit_map = None
                self.update()
            return

        result = self._ray_terrain_hit(pos.x(), pos.y())
        if result:
            self._hit_pos = (result[0], result[1], result[2])
            self._hit_map = (result[3], result[4])
            if self._pressing:
                self.stroke_at.emit(result[3], result[4])
        else:
            self._hit_pos = None
            self._hit_map = None
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._mouse_captured = False
            self.unsetCursor()
        elif event.button() == Qt.MouseButton.LeftButton:
            self._pressing = False
            self.stroke_end.emit()

    def leaveEvent(self, event):
        self._hit_pos = None
        self._hit_map = None
        self.update()

    # -- Keyboard -------------------------------------------------------------

    def keyPressEvent(self, event):
        from canvas.opengl_utils import movement_action
        k = event.key()
        if k == Qt.Key.Key_Shift:
            self._shift_held = True
        action = movement_action(event)
        if action:
            self._move[action] = True
            if not self._move_timer.isActive():
                self._move_timer.start()
        event.accept()

    def keyReleaseEvent(self, event):
        from canvas.opengl_utils import movement_action
        k = event.key()
        if k == Qt.Key.Key_Shift:
            self._shift_held = False
        action = movement_action(event)
        if action:
            self._move[action] = False
            if not any(self._move.values()):
                self._move_timer.stop()
        event.accept()


# ---------------------------------------------------------------------------
# TerrainEditorDialog — main window
# ---------------------------------------------------------------------------

class TerrainEditorDialog(QDialog):

    def __init__(self, parent=None, terrain_renderer=None, canvas=None):
        super().__init__(parent)
        self.setWindowTitle("Terrain Editor — Avatar: The Game")
        self.setMinimumSize(1100, 700)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)

        self._terrain_renderer = terrain_renderer
        self._canvas = canvas
        self._td = TerrainData()
        self._active_tool = 'raise'
        self._stroking = False

        # Debounce main-canvas updates (100 ms) so live brush doesn't stall the main window
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(100)
        self._flush_timer.timeout.connect(self._flush_main_canvas)

        self._setup_ui()

        # Auto-load if terrain renderer already has a path
        if terrain_renderer and terrain_renderer.sdat_path:
            self.load_terrain(terrain_renderer.sdat_path)

    # -- UI construction -----------------------------------------------------

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        root.addWidget(self._build_toolbar())

        self._preview_3d = TerrainPreview3D()
        root.addWidget(self._preview_3d, stretch=1)

        root.addWidget(self._build_tools_panel())

        self._status = QLabel("No terrain loaded — use 'Load Terrain' to open a csdat folder")
        self._status.setFont(QFont("Consolas", 8))
        root.addWidget(self._status)

        self._preview_3d.stroke_at.connect(self._on_stroke_at)
        self._preview_3d.stroke_end.connect(self._on_stroke_end)

    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setFrameStyle(QFrame.Shape.StyledPanel)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(6)

        load_btn = QPushButton("Load Terrain")
        load_btn.setToolTip("Open a folder containing sd*.csdat files")
        load_btn.clicked.connect(self._browse_folder)
        lay.addWidget(load_btn)

        save_btn = QPushButton("Save to CSDAT")
        save_btn.setToolTip("Write all modified sectors back to disk")
        save_btn.clicked.connect(self._save_terrain)
        lay.addWidget(save_btn)

        lay.addSpacing(12)

        undo_btn = QPushButton("↩ Undo")
        undo_btn.setShortcut("Ctrl+Z")
        undo_btn.clicked.connect(self._undo)
        lay.addWidget(undo_btn)

        redo_btn = QPushButton("↪ Redo")
        redo_btn.setShortcut("Ctrl+Y")
        redo_btn.clicked.connect(self._redo)
        lay.addWidget(redo_btn)

        lay.addStretch()

        self._dirty_label = QLabel("")
        self._dirty_label.setStyleSheet("color: #f0a040;")
        lay.addWidget(self._dirty_label)

        return bar

    def _build_tools_panel(self) -> QWidget:
        panel = QGroupBox("Brush Tools")
        vlay = QVBoxLayout(panel)
        vlay.setSpacing(4)
        vlay.setContentsMargins(6, 6, 6, 6)

        # ── Top row: Size and Strength ──────────────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(8)

        # Brush size
        top.addWidget(QLabel("Size:"))
        sz_dec = QPushButton("−")
        sz_dec.setFixedWidth(24)
        top.addWidget(sz_dec)
        self._size_slider = QSlider(Qt.Orientation.Horizontal)
        self._size_slider.setRange(1, 150)
        self._size_slider.setValue(20)
        self._size_slider.setFixedWidth(110)
        self._size_slider.valueChanged.connect(self._on_size_changed)
        top.addWidget(self._size_slider)
        sz_inc = QPushButton("+")
        sz_inc.setFixedWidth(24)
        top.addWidget(sz_inc)
        self._size_lbl = QLabel("20 px")
        self._size_lbl.setFixedWidth(42)
        top.addWidget(self._size_lbl)
        sz_dec.clicked.connect(lambda: self._size_slider.setValue(self._size_slider.value() - 1))
        sz_inc.clicked.connect(lambda: self._size_slider.setValue(self._size_slider.value() + 1))

        top.addSpacing(20)

        # Strength
        top.addWidget(QLabel("Strength:"))
        str_dec = QPushButton("−")
        str_dec.setFixedWidth(24)
        top.addWidget(str_dec)
        self._str_slider = QSlider(Qt.Orientation.Horizontal)
        self._str_slider.setRange(1, 100)
        self._str_slider.setValue(30)
        self._str_slider.setFixedWidth(110)
        top.addWidget(self._str_slider)
        str_inc = QPushButton("+")
        str_inc.setFixedWidth(24)
        top.addWidget(str_inc)
        self._str_lbl = QLabel("30 %")
        self._str_lbl.setFixedWidth(38)
        self._str_slider.valueChanged.connect(
            lambda v: self._str_lbl.setText(f"{v} %"))
        top.addWidget(self._str_lbl)
        str_dec.clicked.connect(lambda: self._str_slider.setValue(self._str_slider.value() - 1))
        str_inc.clicked.connect(lambda: self._str_slider.setValue(self._str_slider.value() + 1))

        top.addStretch()
        vlay.addLayout(top)

        # ── Bottom row: Tool buttons + Target H ────────────────────────────
        bot = QHBoxLayout()
        bot.setSpacing(8)

        self._tool_btns: dict = {}
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        for name, label, tip in [
            ('raise',   '▲ Raise',   'Raise terrain within brush radius'),
            ('lower',   '▼ Lower',   'Lower terrain within brush radius'),
            ('flatten', '═ Flatten', 'Blend terrain toward target height'),
            ('smooth',  '~ Smooth',  'Average terrain within brush radius'),
        ]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setToolTip(tip)
            btn.setMinimumWidth(90)
            self._tool_group.addButton(btn)
            self._tool_btns[name] = btn
            bot.addWidget(btn)
        self._tool_btns['raise'].setChecked(True)
        self._tool_group.buttonClicked.connect(self._on_tool_clicked)

        bot.addSpacing(16)

        # Target height
        bot.addWidget(QLabel("Target H:"))
        self._target_h = QLineEdit("100.0")
        self._target_h.setFixedWidth(70)
        self._target_h.setToolTip("Target height for Flatten and Set tools")
        self._target_h.textChanged.connect(self._on_target_h_changed)
        bot.addWidget(self._target_h)

        bot.addStretch()
        vlay.addLayout(bot)

        return panel

    # -- Slots ---------------------------------------------------------------

    def _on_tool_clicked(self, btn):
        for name, b in self._tool_btns.items():
            if b is btn:
                self._active_tool = name
                break

    def _on_target_h_changed(self, text):
        try:
            v = float(text)
            if self._canvas and hasattr(self._canvas, '_te_target_h'):
                self._canvas._te_target_h = max(0.0, min(511.0, v))
                self._canvas.update()
        except ValueError:
            pass

    def _on_size_changed(self, v):
        self._size_lbl.setText(f"{v} px")
        self._preview_3d.set_brush_radius(v)

    def _on_stroke_at(self, hx: int, hy: int):
        if not self._stroking:
            self._td.push_undo()
            self._stroking = True
        self._apply_brush(hx, hy)
        self._refresh_local_views()
        self._flush_timer.start()

    def _on_stroke_end(self):
        self._stroking = False
        self._update_dirty_label()

    # -- External brush API (called by main canvas terrain edit mode) --------

    def apply_brush_external(self, hx: int, hy: int, first_in_stroke: bool = False):
        """Apply the active brush at heightmap pixel (hx, hy).
        Call with first_in_stroke=True on the first sample of a new stroke."""
        if self._td.combined is None:
            return
        if first_in_stroke and not self._stroking:
            self._td.push_undo()
            self._stroking = True
        self._apply_brush(hx, hy)
        self._refresh_local_views()
        self._flush_timer.start()

    def end_stroke_external(self):
        """Notify the dialog that the current terrain stroke has ended."""
        self._stroking = False
        self._update_dirty_label()

    def sync_brush_params(self, tool: str, size: int, strength: int, target_h: float = None):
        """Sync brush parameters from the main canvas terrain edit overlay."""
        self._active_tool = tool
        btn = self._tool_btns.get(tool)
        if btn and not btn.isChecked():
            btn.setChecked(True)
        if self._size_slider.value() != size:
            self._size_slider.blockSignals(True)
            self._size_slider.setValue(size)
            self._size_slider.blockSignals(False)
            self._size_lbl.setText(f"{size} px")
            self._preview_3d.set_brush_radius(size)
        if self._str_slider.value() != strength:
            self._str_slider.blockSignals(True)
            self._str_slider.setValue(strength)
            self._str_slider.blockSignals(False)
        if target_h is not None:
            current = self._target_h.text()
            new_txt = f"{target_h:.1f}"
            if current != new_txt:
                self._target_h.blockSignals(True)
                self._target_h.setText(new_txt)
                self._target_h.blockSignals(False)

    # -- Brush application ---------------------------------------------------

    def _apply_brush(self, cx: int, cy: int):
        if self._td.combined is None:
            return
        c = self._td.combined
        radius   = self._size_slider.value()
        strength = self._str_slider.value() / 100.0
        tool     = self._active_tool

        try:
            target_h = float(self._target_h.text())
        except ValueError:
            target_h = 100.0

        x0 = max(0, cx - radius);  x1 = min(c.shape[1] - 1, cx + radius)
        y0 = max(0, cy - radius);  y1 = min(c.shape[0] - 1, cy + radius)
        if x0 > x1 or y0 > y1:
            return

        xs = np.arange(x0, x1 + 1, dtype=np.float32)
        ys = np.arange(y0, y1 + 1, dtype=np.float32)
        xx, yy = np.meshgrid(xs, ys)
        dist2   = (xx - cx) ** 2 + (yy - cy) ** 2
        sigma   = max(1.0, radius / 3.0)
        falloff = np.exp(-dist2 / (2 * sigma ** 2)).astype(np.float32)
        mask    = (dist2 <= radius ** 2).astype(np.float32)
        alpha   = (strength * falloff * mask).astype(np.float32)

        sl_y = slice(y0, y1 + 1)
        sl_x = slice(x0, x1 + 1)
        region = c[sl_y, sl_x].copy()

        if tool == 'raise':
            region += alpha * 5.0
        elif tool == 'lower':
            region -= alpha * 5.0
        elif tool == 'flatten':
            region += (target_h - region) * alpha
        elif tool == 'smooth':
            pad = np.pad(region, 1, mode='edge')
            smoothed = (
                pad[:-2, :-2] + pad[:-2, 1:-1] + pad[:-2, 2:] +
                pad[1:-1, :-2] + pad[1:-1, 1:-1] + pad[1:-1, 2:] +
                pad[2:, :-2] + pad[2:, 1:-1] + pad[2:, 2:]
            ) / 9.0
            region = region * (1 - alpha) + smoothed * alpha

        c[sl_y, sl_x] = np.clip(region, 0.0, 511.99)
        self._td.mark_dirty_from_brush(cx, cy, radius)

    # -- View refresh --------------------------------------------------------

    def _refresh_local_views(self):
        if self._td.combined is None:
            return
        self._preview_3d.rebuild_mesh()

    def _flush_main_canvas(self):
        if self._terrain_renderer and self._td.combined is not None:
            self._terrain_renderer.update_from_heightmap(self._td.combined)
        if self._canvas:
            self._canvas.update()

    def _update_dirty_label(self):
        n = len(self._td.dirty_sectors)
        self._dirty_label.setText(f"{n} unsaved sector(s)" if n else "")

    # -- Load / Save ---------------------------------------------------------

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select CSDAT Folder", self._td.sdat_path or "",
            QFileDialog.Option.ShowDirsOnly
        )
        if folder:
            self.load_terrain(folder)

    def load_terrain(self, sdat_path: str):
        self._status.setText(f"Loading {sdat_path} …")
        self.repaint()

        if not self._td.load(sdat_path):
            QMessageBox.warning(self, "Load Failed",
                                f"No sd*.csdat files found in:\n{sdat_path}")
            self._status.setText("Load failed — no csdat files found")
            return

        td = self._td
        count = len(td.sectors_data)
        mw = td.sectors_x * td.grid_size
        mh = td.sectors_y * td.grid_size

        self._preview_3d.set_terrain(td)
        self._dirty_label.setText("")
        self._status.setText(
            f"Loaded {count} sectors | {td.sectors_x}×{td.sectors_y} grid | "
            f"{mw}×{mh} px | {sdat_path}"
        )

    def _save_terrain(self):
        if self._td.combined is None:
            QMessageBox.warning(self, "No Terrain", "Load a terrain first.")
            return
        n = len(self._td.dirty_sectors)
        if n == 0:
            QMessageBox.information(self, "Nothing to Save", "No unsaved changes.")
            return
        reply = QMessageBox.question(
            self, "Save Terrain",
            f"Write {n} modified sector(s) to disk?\n\nThis overwrites the .csdat files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        written, failed = self._td.save_dirty_sectors()
        self._update_dirty_label()
        # Push final update to main canvas after save
        self._flush_main_canvas()
        if self._terrain_renderer and self._canvas:
            if hasattr(self._canvas, 'terrain_renderer'):
                # Re-read files so main canvas has canonical data
                self._canvas.terrain_renderer.load_sdat_folder(self._td.sdat_path)
                self._canvas.update()
        msg = f"Saved {written} sector(s)."
        if failed:
            msg += f"\n{failed} sector(s) failed to write."
        QMessageBox.information(self, "Save Complete", msg)

    # -- Undo / Redo ---------------------------------------------------------

    def _undo(self):
        if self._td.undo():
            self._refresh_local_views()
            self._flush_main_canvas()
            self._update_dirty_label()

    def _redo(self):
        if self._td.redo():
            self._refresh_local_views()
            self._flush_main_canvas()
            self._update_dirty_label()


# ---------------------------------------------------------------------------
# Convenience opener
# ---------------------------------------------------------------------------

def show_terrain_editor(parent=None, terrain_renderer=None, canvas=None, sdat_path=None):
    dlg = TerrainEditorDialog(parent, terrain_renderer=terrain_renderer, canvas=canvas)
    dlg.show()
    if sdat_path:
        dlg.load_terrain(sdat_path)
    return dlg
