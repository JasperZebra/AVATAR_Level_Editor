#!/usr/bin/env python3
"""
Directional (sun) shadow mapping for the day/night system.

Stage 1: a single depth shadow map rendered from the sun's direction. Casters
render their depth into it (the GPU-driven models do this via an MDI depth pass);
receivers (the model fragment shaders) project the fragment's world position into
light space and PCF-compare against the stored depth → a 0..1 shadow factor that
attenuates the SUN light only (ambient + sky fill stay).

The ortho light frustum follows the camera (a box of `half_size` around a point
in front of the camera) so shadows stay crisp where you're looking.

Matrices are built row-major (numpy) and uploaded with transpose=GL_TRUE, so the
math reads normally here and in the shaders.

All GL is guarded; on any failure `_failed` is set and the caller renders without
shadows (never a hard error / blank).
"""

import math
import numpy as np
from OpenGL.GL import *


def _normalize(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _look_at(eye, center, up):
    f = _normalize((center[0] - eye[0], center[1] - eye[1], center[2] - eye[2]))
    s = _normalize(_cross(f, up))
    u = _cross(s, f)
    def d(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    return np.array([
        [s[0],  s[1],  s[2],  -d(s, eye)],
        [u[0],  u[1],  u[2],  -d(u, eye)],
        [-f[0], -f[1], -f[2],  d(f, eye)],
        [0.0,   0.0,   0.0,    1.0]], dtype=np.float32)


def _ortho(l, r, b, t, n, f):
    return np.array([
        [2.0 / (r - l), 0.0, 0.0, -(r + l) / (r - l)],
        [0.0, 2.0 / (t - b), 0.0, -(t + b) / (t - b)],
        [0.0, 0.0, -2.0 / (f - n), -(f + n) / (f - n)],
        [0.0, 0.0, 0.0, 1.0]], dtype=np.float32)


class ShadowMap:
    # 4096 (was 2048): the coverage box is now sized to the whole level (AM3D
    # parity — everything casts), so a bigger box needs more texels to stay sharp.
    SIZE = 4096

    def __init__(self, half_size=220.0):
        self._failed = False
        self._built = False
        self.fbo = 0
        self.tex = 0
        self.half_size = half_size
        self.light_vp = np.eye(4, dtype=np.float32)
        self.depth_range = 1.0   # far-near of the ortho light frustum; for bias scaling

    def _build(self):
        if self._failed:
            return False
        try:
            self.tex = int(glGenTextures(1))
            glBindTexture(GL_TEXTURE_2D, self.tex)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT24, self.SIZE, self.SIZE,
                         0, GL_DEPTH_COMPONENT, GL_FLOAT, None)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER)
            glTexParameterfv(GL_TEXTURE_2D, GL_TEXTURE_BORDER_COLOR, [1.0, 1.0, 1.0, 1.0])
            self.fbo = int(glGenFramebuffers(1))
            glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_TEXTURE_2D, self.tex, 0)
            glDrawBuffer(GL_NONE)
            glReadBuffer(GL_NONE)
            ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE
            glBindFramebuffer(GL_FRAMEBUFFER, 0)
            if not ok:
                print("[shadow] depth FBO incomplete")
                self._failed = True
                return False
            glBindTexture(GL_TEXTURE_2D, 0)
            self._built = True
            print(f"[shadow] {self.SIZE}x{self.SIZE} depth map ready")
            return True
        except Exception as e:
            print(f"[shadow] build failed ({e}) — shadows off")
            self._failed = True
            return False

    def update_light_vp(self, cam_pos, cam_fwd, sun_dir):
        """Fit the ortho light frustum to a box in front of the camera, looking
        along the sun direction. sun_dir = direction the light comes FROM."""
        S = self.half_size
        # Centre the box a bit in front of the camera (where you're looking).
        c = (cam_pos[0] + cam_fwd[0] * S * 0.5,
             cam_pos[1] + cam_fwd[1] * S * 0.5,
             cam_pos[2] + cam_fwd[2] * S * 0.5)
        sd = _normalize(sun_dir)
        dist = S * 2.5
        eye = (c[0] + sd[0] * dist, c[1] + sd[1] * dist, c[2] + sd[2] * dist)
        up = (0.0, 1.0, 0.0)
        if abs(sd[1]) > 0.95:           # sun near vertical → avoid degenerate up
            up = (0.0, 0.0, 1.0)
        view = _look_at(eye, c, up)
        far = dist * 2.0 + S * 2.0
        proj = _ortho(-S, S, -S, S, 1.0, far)
        self.light_vp = (proj @ view).astype(np.float32)
        self.depth_range = float(far - 1.0)   # for world→normalized bias scaling
        return self.light_vp

    def shadow_bias(self, receiver='model'):
        """Normalized depth bias whose WORLD size stays ~constant as the box grows
        (so shadows don't detach / peter-pan when half_size spans a whole level).

        Split by receiver because their acne risk differs:
        - 'terrain' NEVER casts into the map, so it can't self-shadow → NO acne
          risk. Use a tiny bias so object shadows sit tight on the ground instead
          of floating through it (the big-box bias was making grounded objects
          lose their contact shadow entirely).
        - 'model' meshes cast AND receive, so they self-shadow → need enough bias
          to avoid acne stripes on curved surfaces.
        """
        texel_world = 2.0 * self.half_size / float(self.SIZE)
        if receiver == 'terrain':
            world_bias = 0.25 + 1.0 * texel_world
        else:
            world_bias = 1.5 + 2.0 * texel_world
        return world_bias / max(self.depth_range, 1.0)

    def begin(self):
        """Bind the shadow FBO for the depth (cast) pass. Returns light_vp."""
        if not self._built and not self._build():
            return None
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        glViewport(0, 0, self.SIZE, self.SIZE)
        glClear(GL_DEPTH_BUFFER_BIT)
        glEnable(GL_DEPTH_TEST); glDepthFunc(GL_LESS); glDepthMask(GL_TRUE)
        # Front-face cull during the cast reduces self-shadow acne ("peter-panning"
        # trade) for closed meshes; plus a small polygon offset.
        glEnable(GL_POLYGON_OFFSET_FILL)
        glPolygonOffset(2.0, 4.0)
        return self.light_vp

    def end(self, default_fbo, vw, vh):
        glDisable(GL_POLYGON_OFFSET_FILL)
        glBindFramebuffer(GL_FRAMEBUFFER, int(default_fbo))
        glViewport(0, 0, int(vw), int(vh))
