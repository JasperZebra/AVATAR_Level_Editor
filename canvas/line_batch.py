#!/usr/bin/env python3
"""
Batched wireframe-overlay renderer (lines + points).

The 3D view drew trigger boxes, primitive volumes and shape-point polygons with
per-entity immediate-mode glBegin/glEnd (~10 ms CPU across the prims/triggers/
shape stages). This accumulates every overlay's world-space line segments and
points into two buffers and draws them in ONE glDrawArrays(GL_LINES) + ONE
glDrawArrays(GL_POINTS).

Geometry that has a per-entity transform (trigger/primitive wireframe cubes) is
transformed to world space on the CPU with `overlay_matrix`, which replicates the
exact glTranslate · glRotate(-90,X) · glRotate(-rz,Z) · glRotate(rx,X) ·
glRotate(ry,Y) · glScale sequence the old code used (verified GPU-free).

Uses gl_ModelViewProjectionMatrix (compatibility profile) so the caller just
leaves the camera matrices set. All GL guarded; on failure `_failed` is set and
the caller falls back to immediate mode. Needs GL 3.3.
"""

import math
import ctypes
import numpy as np
from OpenGL.GL import *

_LINE_VS = """
#version 330 compatibility
layout(location=0) in vec3 a_pos;
layout(location=1) in vec3 a_color;
out vec3 v_color;
void main(){
    v_color = a_color;
    gl_Position = gl_ModelViewProjectionMatrix * vec4(a_pos, 1.0);
}
"""
_LINE_FS = """
#version 330 compatibility
in vec3 v_color;
void main(){ gl_FragColor = vec4(v_color, 1.0); }
"""


# ── transform + geometry helpers (GPU-free, unit-testable) ──
def _rx(deg):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]], np.float64)

def _ry(deg):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]], np.float64)

def _rz(deg):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], np.float64)


def overlay_matrix(px, py, pz, rx, ry, rz, sx, sy, sz):
    """4×4 world matrix matching the old GL sequence:
        glTranslate(px,py,pz); glRotate(-90,X); glRotate(-rz,Z);
        glRotate(rx,X); glRotate(ry,Y); glScale(sx,sy,sz)
    Applied to a column vertex, that's T·Rx(-90)·Rz(-rz)·Rx(rx)·Ry(ry)·S·v."""
    T = np.eye(4); T[0, 3] = px; T[1, 3] = py; T[2, 3] = pz
    S = np.diag([sx, sy, sz, 1.0])
    return T @ _rx(-90.0) @ _rz(-rz) @ _rx(rx) @ _ry(ry) @ S


def transform_points(local_xyz, M):
    """Apply 4×4 M to an (N,3) array of local verts → (N,3) world (float32)."""
    v = np.asarray(local_xyz, np.float64)
    world = v @ M[:3, :3].T + M[:3, 3]
    return world.astype(np.float32)


def wire_cube_segments():
    """12 edges (24 verts) of the unit cube [-1,1]³, matching _draw_wireframe_cube."""
    V = np.array([
        [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],   # 0-3 front
        [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]],       # 4-7 back
        np.float64)
    edges = [(0, 1), (1, 2), (2, 3), (3, 0),      # front face
             (4, 5), (5, 6), (6, 7), (7, 4),      # back face
             (0, 4), (1, 5), (2, 6), (3, 7)]      # connecting
    seg = np.empty((len(edges) * 2, 3), np.float64)
    for i, (a, b) in enumerate(edges):
        seg[2 * i] = V[a]; seg[2 * i + 1] = V[b]
    return seg


def loop_to_segments(pts):
    """(N,3) closed polygon → (2N,3) GL_LINES segment pairs (incl. closing edge)."""
    p = np.asarray(pts, np.float32)
    n = p.shape[0]
    if n < 2:
        return np.zeros((0, 3), np.float32)
    seg = np.empty((n * 2, 3), np.float32)
    seg[0::2] = p
    seg[1::2] = np.roll(p, -1, axis=0)
    return seg


class LineBatch:
    """Accumulate world-space coloured lines + points across a frame, draw each
    in one call. begin() → add_*() → flush()."""

    def __init__(self):
        self._failed = False
        self._built = False
        self.prog = 0
        self.vao = 0
        self.vbo = 0
        self._lines = []   # list of (pos (M,3) f32, color (3,) or (M,3))
        self._points = []
        self._point_size = 7.0

    def _build(self):
        try:
            self.prog = _compile(_LINE_VS, _LINE_FS)
            if not self.prog:
                self._failed = True
                return False
            self.vao = int(glGenVertexArrays(1))
            glBindVertexArray(self.vao)
            self.vbo = int(glGenBuffers(1))
            glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(0))
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(12))
            glBindVertexArray(0)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            self._built = True
            print("[line-batch] batched overlay renderer ready")
            return True
        except Exception as e:
            print(f"[line-batch] build failed ({e}) — falling back to immediate mode")
            self._failed = True
            return False

    def begin(self):
        self._lines = []
        self._points = []

    def add_lines(self, seg_xyz, color):
        """seg_xyz: (2K,3) GL_LINES pairs. color: (3,) applied to all, or (2K,3)."""
        if len(seg_xyz):
            self._lines.append((np.asarray(seg_xyz, np.float32), color))

    def add_points(self, pts_xyz, colors):
        """pts_xyz: (K,3). colors: (3,) or (K,3)."""
        if len(pts_xyz):
            self._points.append((np.asarray(pts_xyz, np.float32), colors))

    def has_data(self):
        return bool(self._lines or self._points)

    @staticmethod
    def _pack(items):
        pos_parts, col_parts = [], []
        for pos, col in items:
            pos = np.ascontiguousarray(pos, np.float32)
            col = np.asarray(col, np.float32)
            if col.ndim == 1:
                col = np.broadcast_to(col, (pos.shape[0], 3))
            pos_parts.append(pos)
            col_parts.append(col)
        P = np.concatenate(pos_parts)
        C = np.concatenate(col_parts).astype(np.float32, copy=False)
        inter = np.empty((P.shape[0], 6), np.float32)
        inter[:, 0:3] = P
        inter[:, 3:6] = C
        return inter

    def snapshot(self):
        """Pack the accumulated lines/points into reusable (N,6) arrays so the
        caller can cache them across frames (overlay geometry is world-space =
        camera-independent). Returns (lines_arr|None, points_arr|None)."""
        lines = self._pack(self._lines) if self._lines else None
        points = self._pack(self._points) if self._points else None
        return lines, points

    def flush_packed(self, lines, points):
        """Draw pre-packed arrays from snapshot() — the cached-overlay fast path.
        Returns True if it ran (incl. nothing-to-draw); False on GL failure."""
        if self._failed:
            return False
        if (lines is None or not len(lines)) and (points is None or not len(points)):
            return True
        if not self._built and not self._build():
            return False
        try:
            glUseProgram(self.prog)
            glBindVertexArray(self.vao)
            glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
            glEnable(GL_DEPTH_TEST)
            if lines is not None and len(lines):
                glBufferData(GL_ARRAY_BUFFER, lines.nbytes, lines, GL_DYNAMIC_DRAW)
                glDrawArrays(GL_LINES, 0, lines.shape[0])
            if points is not None and len(points):
                glBufferData(GL_ARRAY_BUFFER, points.nbytes, points, GL_DYNAMIC_DRAW)
                glPointSize(self._point_size)
                glDrawArrays(GL_POINTS, 0, points.shape[0])
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            glBindVertexArray(0)
            glUseProgram(0)
            return True
        except Exception as e:
            print(f"[line-batch] flush_packed failed ({e}) — fallback next frame")
            self._failed = True
            try:
                glUseProgram(0); glBindVertexArray(0)
            except Exception:
                pass
            return False

    def flush(self):
        """Draw all accumulated lines + points. Returns True if it ran (incl. the
        empty case); False means the caller should have used the fallback."""
        if self._failed:
            return False
        if not (self._lines or self._points):
            return True
        if not self._built and not self._build():
            return False
        try:
            glUseProgram(self.prog)
            glBindVertexArray(self.vao)
            glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
            glEnable(GL_DEPTH_TEST)
            if self._lines:
                data = self._pack(self._lines)
                glBufferData(GL_ARRAY_BUFFER, data.nbytes, data, GL_DYNAMIC_DRAW)
                glDrawArrays(GL_LINES, 0, data.shape[0])
            if self._points:
                data = self._pack(self._points)
                glBufferData(GL_ARRAY_BUFFER, data.nbytes, data, GL_DYNAMIC_DRAW)
                glPointSize(self._point_size)
                glDrawArrays(GL_POINTS, 0, data.shape[0])
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            glBindVertexArray(0)
            glUseProgram(0)
            return True
        except Exception as e:
            print(f"[line-batch] flush failed ({e}) — fallback next frame")
            self._failed = True
            try:
                glUseProgram(0); glBindVertexArray(0)
            except Exception:
                pass
            return False


def _compile(vsrc, fsrc):
    def stage(kind, src):
        sh = glCreateShader(kind)
        glShaderSource(sh, src)
        glCompileShader(sh)
        if glGetShaderiv(sh, GL_COMPILE_STATUS) != GL_TRUE:
            print(f"[line-batch] shader compile failed: {glGetShaderInfoLog(sh)}")
            glDeleteShader(sh)
            return 0
        return sh
    vs = stage(GL_VERTEX_SHADER, vsrc)
    fs = stage(GL_FRAGMENT_SHADER, fsrc)
    if not vs or not fs:
        return 0
    p = glCreateProgram()
    glAttachShader(p, vs); glAttachShader(p, fs)
    glLinkProgram(p)
    glDeleteShader(vs); glDeleteShader(fs)
    if glGetProgramiv(p, GL_LINK_STATUS) != GL_TRUE:
        print(f"[line-batch] link failed: {glGetProgramInfoLog(p)}")
        glDeleteProgram(p)
        return 0
    return p
