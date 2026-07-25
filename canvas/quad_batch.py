#!/usr/bin/env python3
"""
Instanced screen-space square renderer for 2D mode.

Every entity in the 2D top-down view is the SAME shape — a small axis-aligned
square with a black outline. The old path built one `QRectF` Python object per
entity per frame, grouped them by (colour, outline width), and issued one
`painter.drawRects()` per group with a pen/brush change between groups. That is
O(N) Qt object allocation plus K state changes every single frame, which is what
capped 2D mode's usable entity count.

This draws ALL of them with ONE `glDrawArraysInstanced`: a static 4-vertex unit
quad plus a per-frame instance buffer. The square geometry ("the model") exists
once; the instance buffer carries per-entity centre, half-size, rotation and
colour. The outline is done in the fragment shader from the quad's local
coordinates, so it costs no extra geometry and no second pass.

Coordinates are QPainter's: logical pixels, origin top-left, +y DOWN. The shader
converts to NDC using the logical widget size passed to `render()`, so the result
is correct at any devicePixelRatio (NDC is resolution-independent and Qt has
already set the device-pixel viewport).

Call it between `QPainter.beginNativePainting()` / `endNativePainting()`.

All GL is guarded; on any failure `_failed` is set and the caller falls back to
the QPainter path. Needs GL 3.3 (instanced arrays).
"""

import ctypes

import numpy as np
from OpenGL.GL import *

# Per-instance layout: cx, cy, half, rot(radians), r, g, b, border_px  = 8 floats
INSTANCE_FLOATS = 8
_STRIDE = INSTANCE_FLOATS * 4

_QUAD_VS = """
#version 330 compatibility
layout(location=0) in vec2 a_corner;    // unit quad corner, -1..+1 (per-vertex)
layout(location=1) in vec4 a_xyhr;      // cx, cy, half, rot   (per-instance)
layout(location=2) in vec4 a_colb;      // r, g, b, border_px  (per-instance)
uniform vec2 u_viewport;                // logical widget size in px
out vec3 v_color;
out vec2 v_local;                       // -1..+1 across the square
out float v_border;                     // border thickness as a 0..1 fraction
void main(){
    v_color = a_colb.rgb;
    v_local = a_corner;
    float half_px = max(a_xyhr.z, 0.5);
    v_border = clamp(a_colb.a / half_px, 0.0, 1.0);

    vec2 p = a_corner * half_px;
    float r = a_xyhr.w;
    if (r != 0.0) {
        float c = cos(r), s = sin(r);
        p = vec2(p.x * c - p.y * s, p.x * s + p.y * c);
    }
    vec2 px = a_xyhr.xy + p;                       // logical pixels, y down
    vec2 ndc = vec2(2.0 * px.x / u_viewport.x - 1.0,
                    1.0 - 2.0 * px.y / u_viewport.y);
    gl_Position = vec4(ndc, 0.0, 1.0);
}
"""

_QUAD_FS = """
#version 330 compatibility
in vec3 v_color;
in vec2 v_local;
in float v_border;
void main(){
    // Black outline: the outer v_border fraction of the square, matching the
    // QPen(Qt.black, w) the QPainter path drew around every rect.
    float edge = max(abs(v_local.x), abs(v_local.y));
    vec3 c = (edge > 1.0 - v_border) ? vec3(0.0) : v_color;
    gl_FragColor = vec4(c, 1.0);
}
"""

# Unit quad as a triangle strip: (-1,-1) (1,-1) (-1,1) (1,1)
_QUAD = np.asarray([[-1.0, -1.0], [1.0, -1.0], [-1.0, 1.0], [1.0, 1.0]],
                   dtype=np.float32)


class QuadBatch:
    """One instanced draw for every 2D entity square.

    render(inst_data, width, height) takes an (N, 8) float32 array of
    [cx, cy, half, rot, r, g, b, border_px] rows in logical pixels.
    """

    def __init__(self):
        self._failed = False
        self._built = False
        self.prog = 0
        self.vao = 0
        self.geo_vbo = 0
        self.inst_vbo = 0
        self._u_viewport = -1
        self._cap = 0            # current instance-buffer capacity in bytes

    def _build(self):
        try:
            self.prog = _compile(_QUAD_VS, _QUAD_FS)
            if not self.prog:
                self._failed = True
                return False
            self._u_viewport = glGetUniformLocation(self.prog, "u_viewport")

            self.vao = int(glGenVertexArrays(1))
            glBindVertexArray(self.vao)

            self.geo_vbo = int(glGenBuffers(1))
            glBindBuffer(GL_ARRAY_BUFFER, self.geo_vbo)
            glBufferData(GL_ARRAY_BUFFER, _QUAD.nbytes, _QUAD, GL_STATIC_DRAW)
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, ctypes.c_void_p(0))
            glVertexAttribDivisor(0, 0)                  # per-vertex

            self.inst_vbo = int(glGenBuffers(1))
            glBindBuffer(GL_ARRAY_BUFFER, self.inst_vbo)
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, _STRIDE, ctypes.c_void_p(0))
            glVertexAttribDivisor(1, 1)                  # per-instance
            glEnableVertexAttribArray(2)
            glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, _STRIDE, ctypes.c_void_p(16))
            glVertexAttribDivisor(2, 1)

            glBindVertexArray(0)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            self._built = True
            print("[quad-batch] instanced 2D square renderer ready")
            return True
        except Exception as e:
            print(f"[quad-batch] build failed ({e}) — falling back to QPainter")
            self._failed = True
            return False

    def render(self, inst_data, width, height):
        """Draw every row of inst_data as one instanced call. Returns True if it
        drew (an empty array counts as drawn — there was nothing to do)."""
        if self._failed:
            return False
        if not self._built and not self._build():
            return False
        arr = np.ascontiguousarray(inst_data, dtype=np.float32)
        if arr.ndim != 2 or arr.shape[1] != INSTANCE_FLOATS:
            return False
        n = arr.shape[0]
        if n == 0:
            return True
        if width <= 0 or height <= 0:
            return False
        try:
            glUseProgram(self.prog)
            glBindVertexArray(self.vao)
            glBindBuffer(GL_ARRAY_BUFFER, self.inst_vbo)
            # orphan-and-refill only when the buffer needs to grow; otherwise
            # overwrite in place so a steady pan doesn't reallocate every frame
            if arr.nbytes > self._cap:
                glBufferData(GL_ARRAY_BUFFER, arr.nbytes, arr, GL_DYNAMIC_DRAW)
                self._cap = arr.nbytes
            else:
                glBufferSubData(GL_ARRAY_BUFFER, 0, arr.nbytes, arr)

            glUniform2f(self._u_viewport, float(width), float(height))
            # 2D overlay: flat, opaque, painter's order — no depth, no blend.
            glDisable(GL_DEPTH_TEST)
            glDisable(GL_BLEND)
            glDisable(GL_CULL_FACE)
            glDrawArraysInstanced(GL_TRIANGLE_STRIP, 0, 4, n)

            glBindBuffer(GL_ARRAY_BUFFER, 0)
            glBindVertexArray(0)
            glUseProgram(0)
            return True
        except Exception as e:
            print(f"[quad-batch] render failed ({e}) — falling back to QPainter")
            self._failed = True
            try:
                glBindBuffer(GL_ARRAY_BUFFER, 0)
                glBindVertexArray(0)
                glUseProgram(0)
            except Exception:
                pass
            return False


def _compile(vsrc, fsrc):
    def stage(kind, src):
        sh = glCreateShader(kind)
        glShaderSource(sh, src)
        glCompileShader(sh)
        if glGetShaderiv(sh, GL_COMPILE_STATUS) != GL_TRUE:
            print(f"[quad-batch] shader compile failed: {glGetShaderInfoLog(sh)}")
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
        print(f"[quad-batch] link failed: {glGetProgramInfoLog(p)}")
        glDeleteProgram(p)
        return 0
    return p


def build_instances(sx, sy, half, rot, rgb, border):
    """Assemble the (N,8) instance array from per-entity numpy columns.

    Pure numpy + unit-testable: no GL, no Qt. sx/sy/half/rot/border are (N,)
    and rgb is (N,3); every one is broadcast against the others so scalars work.
    """
    sx = np.asarray(sx, dtype=np.float32).ravel()
    n = sx.shape[0]
    out = np.empty((n, INSTANCE_FLOATS), dtype=np.float32)
    out[:, 0] = sx
    out[:, 1] = np.asarray(sy, dtype=np.float32).ravel()
    out[:, 2] = half
    out[:, 3] = rot
    out[:, 4:7] = np.asarray(rgb, dtype=np.float32).reshape(-1, 3)
    out[:, 7] = border
    return out
