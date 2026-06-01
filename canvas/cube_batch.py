#!/usr/bin/env python3
"""
Instanced marker-cube renderer.

The 3D view draws a small cube for every entity that has no model (spawn points,
managers, triggers, …). That was 2000+ `glPushMatrix/glTranslatef/glCallList`
draws per frame (~3.4 ms of pure CPU submission). This replaces the whole batch
with ONE `glDrawArraysInstanced`: a static unit-cube VBO + a per-frame instance
buffer (offset xyz + colour rgb).

Uses the fixed-function camera matrix via `gl_ModelViewProjectionMatrix`
(compatibility profile), so the caller just leaves the gluLookAt/perspective
matrices set as usual. A cheap per-face shade (flat normal from screen-space
derivatives) keeps the cubes reading as 3D without needing a normal attribute or
lighting state.

All GL is guarded; on any failure `_failed` is set and the caller falls back to
the display-list loop. Needs GL 3.3 (instanced arrays) — the fallback covers
anything older.
"""

import ctypes
import numpy as np
from OpenGL.GL import *

_CUBE_VS = """
#version 330 compatibility
layout(location=0) in vec3 a_pos;       // unit-cube vertex (per-vertex)
layout(location=1) in vec3 a_offset;    // instance world position (per-instance)
layout(location=2) in vec3 a_color;     // instance colour (per-instance)
out vec3 v_color;
out vec3 v_lpos;
void main(){
    v_color = a_color;
    v_lpos  = a_pos;
    gl_Position = gl_ModelViewProjectionMatrix * vec4(a_pos + a_offset, 1.0);
}
"""
_CUBE_FS = """
#version 330 compatibility
in vec3 v_color;
in vec3 v_lpos;
void main(){
    // Flat per-face normal from derivatives → soft directional shade so the
    // markers still look like 3D cubes (no lighting state, no normal attribute).
    vec3 n = normalize(cross(dFdx(v_lpos), dFdy(v_lpos)));
    float sh = 0.6 + 0.4 * max(dot(n, normalize(vec3(0.35, 0.8, 0.5))), 0.0);
    gl_FragColor = vec4(v_color * sh, 1.0);
}
"""


def _unit_cube(h):
    """36 triangle vertices (6 faces × 2) for a cube of half-extent h, matching
    _draw_cube_geometry's outward winding."""
    quads = [
        [(-h, -h, h),  (h, -h, h),  (h, h, h),   (-h, h, h)],    # front (+z)
        [(-h, -h, -h), (-h, h, -h), (h, h, -h),  (h, -h, -h)],   # back  (-z)
        [(-h, h, -h),  (-h, h, h),  (h, h, h),   (h, h, -h)],    # top   (+y)
        [(-h, -h, -h), (h, -h, -h), (h, -h, h),  (-h, -h, h)],   # bottom(-y)
        [(h, -h, -h),  (h, h, -h),  (h, h, h),   (h, -h, h)],    # right (+x)
        [(-h, -h, -h), (-h, -h, h), (-h, h, h),  (-h, h, -h)],   # left  (-x)
    ]
    verts = []
    for q in quads:
        verts += [q[0], q[1], q[2], q[0], q[2], q[3]]
    return np.asarray(verts, dtype=np.float32)


class CubeBatch:
    """One instanced draw for all marker cubes. render() takes an (N,6) float32
    array of [offset_xyz, color_rgb] rows."""

    def __init__(self, half=0.05):
        self._failed = False
        self._built = False
        self.prog = 0
        self.vao = 0
        self.geo_vbo = 0
        self.inst_vbo = 0
        self.half = half

    def _build(self):
        try:
            self.prog = _compile(_CUBE_VS, _CUBE_FS)
            if not self.prog:
                self._failed = True
                return False
            cube = _unit_cube(self.half)
            self.vao = int(glGenVertexArrays(1))
            glBindVertexArray(self.vao)

            self.geo_vbo = int(glGenBuffers(1))
            glBindBuffer(GL_ARRAY_BUFFER, self.geo_vbo)
            glBufferData(GL_ARRAY_BUFFER, cube.nbytes, cube, GL_STATIC_DRAW)
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, ctypes.c_void_p(0))
            glVertexAttribDivisor(0, 0)                  # per-vertex

            # Per-instance: interleaved offset(3) + colour(3), stride 24 bytes.
            self.inst_vbo = int(glGenBuffers(1))
            glBindBuffer(GL_ARRAY_BUFFER, self.inst_vbo)
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(0))
            glVertexAttribDivisor(1, 1)                  # per-instance
            glEnableVertexAttribArray(2)
            glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(12))
            glVertexAttribDivisor(2, 1)

            glBindVertexArray(0)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            self._built = True
            print("[cube-batch] instanced marker-cube renderer ready")
            return True
        except Exception as e:
            print(f"[cube-batch] build failed ({e}) — falling back to display list")
            self._failed = True
            return False

    def render(self, inst_data):
        """inst_data: (N,6) float32 [ox,oy,oz, r,g,b]. Returns True if it drew."""
        if self._failed:
            return False
        if not self._built and not self._build():
            return False
        arr = np.ascontiguousarray(inst_data, dtype=np.float32)
        n = arr.shape[0]
        if n == 0:
            return True
        try:
            glUseProgram(self.prog)
            glBindVertexArray(self.vao)
            glBindBuffer(GL_ARRAY_BUFFER, self.inst_vbo)
            glBufferData(GL_ARRAY_BUFFER, arr.nbytes, arr, GL_DYNAMIC_DRAW)
            glEnable(GL_DEPTH_TEST)
            glDrawArraysInstanced(GL_TRIANGLES, 0, 36, n)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            glBindVertexArray(0)
            glUseProgram(0)
            return True
        except Exception as e:
            print(f"[cube-batch] render failed ({e}) — falling back")
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
            print(f"[cube-batch] shader compile failed: {glGetShaderInfoLog(sh)}")
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
        print(f"[cube-batch] link failed: {glGetProgramInfoLog(p)}")
        glDeleteProgram(p)
        return 0
    return p
