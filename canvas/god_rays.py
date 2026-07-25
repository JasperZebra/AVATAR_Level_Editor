#!/usr/bin/env python3
"""
Screen-space god rays (crepuscular light shafts) for the day/night cycle.

Ported from the Battalion Wars editor's lib/render/god_rays.py (2026-07) into the
Avatar/FC2 editor. Classic radial-blur technique (GPU Gems 3, "Volumetric Light
Scattering as a Post-Process"):

  1. Occlusion pass: into a small offscreen buffer (colour + depth), render the
     scene's DEPTH from the camera (terrain + models), then draw the bright sun
     disc on top with depth-testing on. Where geometry sits between the camera and
     the sun the disc fails the depth test and stays black — so the buffer holds
     the sun with the scene's silhouettes cut out of it.
  2. Composite pass: a fullscreen shader marches each pixel toward the sun's
     screen position, accumulating the occlusion buffer with decaying weights, and
     ADDS the result to the frame — light shafts streaming past objects.

Key difference from the BW port: BW draws its occluders in pure black (it has a
dedicated black terrain/model shader). Avatar's GPU-driven model path has no flat-
black mode, so instead we give the occlusion buffer a real DEPTH attachment,
render the existing camera-space depth of terrain+models into it, and let the sun
disc depth-test against that. Same silhouette result, no new model shader needed.

All GL is guarded; any failure disables the effect (never a blank viewport).
"""

import math
import numpy as np
from OpenGL.GL import *


_VERT = """
#version 330
layout(location = 0) in vec2 vert;
void main(void)
{
    gl_Position = vec4(vert, 0.0, 1.0);
}
"""

_FRAG = """
#version 330
out vec4 finalColor;

uniform sampler2D occtex;
uniform vec2 sunpos;        // sun position in 0..1 screen uv
uniform vec2 screensize;
uniform vec3 raycolor;
uniform float intensity;

const int NUM_SAMPLES = 96;
const float DENSITY = 1.0;
const float DECAY = 0.997;

void main(void)
{
    vec2 uv = gl_FragCoord.xy / screensize;
    vec2 delta = (uv - sunpos) * (DENSITY / float(NUM_SAMPLES));
    vec2 coord = uv;
    float illum = 0.0;
    float decay = 1.0;
    for (int i = 0; i < NUM_SAMPLES; i++) {
        coord -= delta;
        vec3 s = texture(occtex, coord).rgb;
        illum += dot(s, vec3(0.333)) * decay;
        decay *= DECAY;
    }
    illum /= float(NUM_SAMPLES);
    // Slight contrast curve: darkens half-shadowed ray paths so shafts cut
    // by object silhouettes stay visible instead of washing out.
    illum = illum * illum * 1.2 + illum * 0.25;
    finalColor = vec4(raycolor * illum * intensity, 1.0);
}
"""


def _compile(src, stage, label):
    sid = glCreateShader(stage)
    glShaderSource(sid, src)
    glCompileShader(sid)
    if glGetShaderiv(sid, GL_COMPILE_STATUS) != GL_TRUE:
        log = glGetShaderInfoLog(sid)
        if isinstance(log, bytes):
            log = log.decode('utf-8', 'replace')
        print(f'[god-rays] {label} compile FAILED:\n{log}')
        glDeleteShader(sid)
        return 0
    return sid


def _link(vs_src, fs_src):
    vs = _compile(vs_src, GL_VERTEX_SHADER, 'vs')
    if not vs:
        return 0
    fs = _compile(fs_src, GL_FRAGMENT_SHADER, 'fs')
    if not fs:
        glDeleteShader(vs)
        return 0
    prog = glCreateProgram()
    glAttachShader(prog, vs); glAttachShader(prog, fs)
    glLinkProgram(prog)
    glDeleteShader(vs); glDeleteShader(fs)
    if glGetProgramiv(prog, GL_LINK_STATUS) != GL_TRUE:
        log = glGetProgramInfoLog(prog)
        if isinstance(log, bytes):
            log = log.decode('utf-8', 'replace')
        print(f'[god-rays] link FAILED:\n{log}')
        glDeleteProgram(prog)
        return 0
    return int(prog)


# Distance the sun disc is placed along the light direction from the camera. Well
# inside the 3D far plane (10000) so its projected depth stays < the cleared
# far-depth (1.0) and it passes the depth test over open sky, but is occluded by
# any nearer terrain/model geometry.
_SUN_DISTANCE = 4000.0
_SEGMENTS = 24


def _normalize(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def _basis(direction):
    """Right/up vectors perpendicular to the view ray toward the sun (Y-up world:
    right = dir x world-up, up = right x dir)."""
    dx, dy, dz = direction
    # dir x (0,1,0)
    rx, ry, rz = -dz, 0.0, dx
    length = math.sqrt(rx * rx + ry * ry + rz * rz)
    if length < 1e-4:                 # sun straight up/down → pick any horizontal right
        rx, ry, rz = 1.0, 0.0, 0.0
        length = 1.0
    rx, ry, rz = rx / length, ry / length, rz / length
    ux = ry * dz - rz * dy
    uy = rz * dx - rx * dz
    uz = rx * dy - ry * dx
    return (rx, ry, rz), (ux, uy, uz)


class GodRays:
    # 1024 (was 512): fine texture transparency (foliage/grate cutouts, window
    # frames) is only a few texels wide in screen space — at 512 the gaps between
    # leaves fell below one texel and the tree read as a solid silhouette, blocking
    # the shafts. 1024 keeps those gaps so the rays pass through.
    SIZE = 1024   # occlusion buffer resolution (square; screen-mapped)

    def __init__(self):
        self._failed = False
        self._built = False
        self.fbo = 0
        self.tex = 0
        self.depth = 0
        self.program = None
        self._vao = None

    def _build(self):
        if self._failed:
            return False
        try:
            # Colour attachment (the occlusion image the radial blur samples).
            self.tex = int(glGenTextures(1))
            glBindTexture(GL_TEXTURE_2D, self.tex)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, self.SIZE, self.SIZE,
                         0, GL_RGBA, GL_UNSIGNED_BYTE, None)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            # Samples outside the buffer read as black (no light).
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER)
            glTexParameterfv(GL_TEXTURE_2D, GL_TEXTURE_BORDER_COLOR, [0.0, 0.0, 0.0, 1.0])
            glBindTexture(GL_TEXTURE_2D, 0)

            # Depth attachment so scene geometry occludes the sun disc.
            self.depth = int(glGenRenderbuffers(1))
            glBindRenderbuffer(GL_RENDERBUFFER, self.depth)
            glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, self.SIZE, self.SIZE)
            glBindRenderbuffer(GL_RENDERBUFFER, 0)

            self.fbo = int(glGenFramebuffers(1))
            glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                                   GL_TEXTURE_2D, self.tex, 0)
            glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                                      GL_RENDERBUFFER, self.depth)
            ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE
            glBindFramebuffer(GL_FRAMEBUFFER, 0)
            if not ok:
                print("[god-rays] occlusion FBO incomplete — rays off")
                self._failed = True
                return False

            self.program = _link(_VERT, _FRAG)
            if not self.program:
                self._failed = True
                return False

            # Fullscreen triangle as a real VBO (attribless draws are not reliable
            # in compatibility contexts on all drivers).
            self._vao = int(glGenVertexArrays(1))
            glBindVertexArray(self._vao)
            vbo = glGenBuffers(1)
            glBindBuffer(GL_ARRAY_BUFFER, vbo)
            tri = np.array([-1.0, -1.0, 3.0, -1.0, -1.0, 3.0], dtype=np.float32)
            glBufferData(GL_ARRAY_BUFFER, tri.nbytes, tri, GL_STATIC_DRAW)
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, None)
            glBindVertexArray(0)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            self._built = True
            print(f"[god-rays] {self.SIZE}x{self.SIZE} occlusion buffer ready")
            return True
        except Exception as e:
            print(f"[god-rays] build failed ({e}) — rays off")
            self._failed = True
            return False

    def begin_occlusion(self):
        """Bind the occlusion buffer and clear it (black colour, far depth). The
        caller then renders the scene depth (camera space) and draws the sun disc.
        Returns False if unavailable."""
        if not self._built and not self._build():
            return False
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        glViewport(0, 0, self.SIZE, self.SIZE)
        glClearColor(0.0, 0.0, 0.0, 1.0)
        glClearDepth(1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LESS)
        glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)
        return True

    def draw_sun_source(self, cam_pos, sun_dir, horizon):
        """Draw the bright sun disc(s) as camera-facing world geometry at the sun's
        position, additively, depth-tested against the scene depth already in the
        buffer (so geometry carves silhouettes out of the glow). Assumes the camera
        GL_PROJECTION / GL_MODELVIEW stacks are current (matches the depth pass)."""
        sd = _normalize(sun_dir)
        right, up = _basis(sd)
        center = (cam_pos[0] + sd[0] * _SUN_DISTANCE,
                  cam_pos[1] + sd[1] * _SUN_DISTANCE,
                  cam_pos[2] + sd[2] * _SUN_DISTANCE)

        glPushAttrib(GL_ENABLE_BIT | GL_DEPTH_BUFFER_BIT | GL_CURRENT_BIT
                     | GL_TEXTURE_BIT | GL_COLOR_BUFFER_BIT)
        try:
            glUseProgram(0)
            for unit in (GL_TEXTURE3, GL_TEXTURE2, GL_TEXTURE1, GL_TEXTURE0):
                glActiveTexture(unit)
                glDisable(GL_TEXTURE_2D)
            glDisable(GL_LIGHTING)
            glDisable(GL_CULL_FACE)
            glDisable(GL_ALPHA_TEST)
            glEnable(GL_DEPTH_TEST)        # occlude the sun behind geometry
            glDepthFunc(GL_LEQUAL)
            glDepthMask(GL_FALSE)          # but don't write the sun into depth
            glEnable(GL_BLEND)
            glBlendFunc(GL_ONE, GL_ONE)    # additive

            gr = 1.0
            gg = 0.92 - 0.30 * horizon
            gb = 0.75 - 0.45 * horizon
            # Wide soft halo -> mid glow -> hot core. Radii scaled from the BW port
            # (its D=3400) to this D so the on-screen angular size matches.
            self._disc(center, right, up, 980.0, gr, gg, gb, 0.20)
            self._disc(center, right, up, 600.0, gr, gg, gb, 0.55)
            self._disc(center, right, up, 250.0, 1.0, 1.0, 0.95, 1.0)
        finally:
            glPopAttrib()

    def _disc(self, center, right, up, radius, r, g, b, core_alpha):
        """Camera-facing triangle fan: bright in the middle fading to black at the
        rim (additive → soft glow)."""
        glBegin(GL_TRIANGLE_FAN)
        glColor4f(r * core_alpha, g * core_alpha, b * core_alpha, 1.0)
        glVertex3f(*center)
        glColor4f(0.0, 0.0, 0.0, 1.0)      # additive: black adds nothing
        for i in range(_SEGMENTS + 1):
            angle = 2.0 * math.pi * i / _SEGMENTS
            ca = math.cos(angle) * radius
            sa = math.sin(angle) * radius
            glVertex3f(center[0] + right[0] * ca + up[0] * sa,
                       center[1] + right[1] * ca + up[1] * sa,
                       center[2] + right[2] * ca + up[2] * sa)
        glEnd()

    _CLOUD_VS = """
#version 330
layout(location = 0) in vec2 vert;
void main(void){ gl_Position = vec4(vert, 0.0, 1.0); }
"""
    _CLOUD_FS_TEMPLATE = """
#version 330
out vec4 frag;
uniform mat4  u_view;
uniform mat4  u_proj;
uniform vec2  u_res;
uniform float u_time;
uniform float u_cover;
//__CLOUD_GLSL__//
void main(void)
{
    vec2 ndc = (gl_FragCoord.xy / u_res) * 2.0 - 1.0;
    mat4 invVP = inverse(u_proj * u_view);
    vec4 pn = invVP * vec4(ndc, -1.0, 1.0);
    vec4 pf = invVP * vec4(ndc,  1.0, 1.0);
    vec3 ray = normalize(pf.xyz / pf.w - pn.xyz / pn.w);
    // Transmittance: 1 where the sky is clear, →0 under thick cloud. Multiplied
    // into the occlusion buffer so the shafts stream through cloud GAPS.
    float d = cloud_density(ray, u_time, u_cover);
    float tr = clamp(1.0 - d * 0.92, 0.0, 1.0);
    frag = vec4(tr, tr, tr, 1.0);
}
"""

    def occlude_with_clouds(self, t, cover):
        """Multiply the occlusion buffer by cloud transmittance.

        Ported from the SDF tool's god_rays, which bakes `cloud_density` straight
        into its occluder mask so shafts stream through cloud gaps. Our occluder
        is an FBO with real scene depth + the sun disc drawn into it, so the
        equivalent is a multiplicative fullscreen pass over that buffer using the
        SAME shared cloud function (cloud_common.CLOUD_GLSL) the sky samples — a
        cloud overhead therefore breaks the same shafts it casts.

        Must be called with the occlusion FBO still bound (between
        draw_sun_source and end_occlusion) and the camera matrices current.
        """
        if cover <= 0.001 or getattr(self, '_cloud_failed', False):
            return
        try:
            if getattr(self, '_cloud_prog', None) is None:
                try:
                    from cloud_common import CLOUD_GLSL
                except Exception:
                    CLOUD_GLSL = ""
                if not CLOUD_GLSL:
                    self._cloud_failed = True
                    return
                fs = self._CLOUD_FS_TEMPLATE.replace("//__CLOUD_GLSL__//", CLOUD_GLSL)
                self._cloud_prog = _link(self._CLOUD_VS, fs)
                if not self._cloud_prog:
                    self._cloud_failed = True
                    return
                self._cloud_vao = int(glGenVertexArrays(1))
                glBindVertexArray(self._cloud_vao)
                vbo = glGenBuffers(1)
                glBindBuffer(GL_ARRAY_BUFFER, vbo)
                tri = np.array([-1.0, -1.0, 3.0, -1.0, -1.0, 3.0], dtype=np.float32)
                glBufferData(GL_ARRAY_BUFFER, tri.nbytes, tri, GL_STATIC_DRAW)
                glEnableVertexAttribArray(0)
                glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, None)
                glBindVertexArray(0)
                glBindBuffer(GL_ARRAY_BUFFER, 0)
                print("[god-rays] cloud occluder ready")

            mv = np.ascontiguousarray(glGetFloatv(GL_MODELVIEW_MATRIX), dtype=np.float32)
            proj = np.ascontiguousarray(glGetFloatv(GL_PROJECTION_MATRIX), dtype=np.float32)
            p = self._cloud_prog
            glUseProgram(p)
            glUniformMatrix4fv(glGetUniformLocation(p, b'u_view'), 1, GL_FALSE, mv)
            glUniformMatrix4fv(glGetUniformLocation(p, b'u_proj'), 1, GL_FALSE, proj)
            glUniform2f(glGetUniformLocation(p, b'u_res'), float(self.SIZE), float(self.SIZE))
            glUniform1f(glGetUniformLocation(p, b'u_time'), float(t))
            glUniform1f(glGetUniformLocation(p, b'u_cover'), float(cover))
            glDisable(GL_DEPTH_TEST)
            glDepthMask(GL_FALSE)
            glEnable(GL_BLEND)
            glBlendFunc(GL_ZERO, GL_SRC_COLOR)     # dst *= transmittance
            glBindVertexArray(self._cloud_vao)
            glDrawArrays(GL_TRIANGLES, 0, 3)
            glBindVertexArray(0)
            glUseProgram(0)
            glDisable(GL_BLEND)
            glDepthMask(GL_TRUE)
            glEnable(GL_DEPTH_TEST)
        except Exception as e:
            print(f"[god-rays] cloud occluder failed ({e}) — rays unbroken by clouds")
            self._cloud_failed = True

    def end_occlusion(self, default_fbo, vw, vh):
        glDepthMask(GL_TRUE)
        glDepthFunc(GL_LESS)
        glEnable(GL_DEPTH_TEST)
        glBindFramebuffer(GL_FRAMEBUFFER, int(default_fbo))
        glViewport(0, 0, int(vw), int(vh))

    def composite(self, sun_uv, raycolor, intensity, vw, vh):
        """Additively blend the radial light shafts over the current frame."""
        if not self._built:
            return
        glPushAttrib(GL_ENABLE_BIT | GL_DEPTH_BUFFER_BIT | GL_COLOR_BUFFER_BIT
                     | GL_TEXTURE_BIT)
        try:
            glUseProgram(self.program)
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, self.tex)
            glUniform1i(glGetUniformLocation(self.program, "occtex"), 0)
            glUniform2f(glGetUniformLocation(self.program, "sunpos"),
                        float(sun_uv[0]), float(sun_uv[1]))
            glUniform2f(glGetUniformLocation(self.program, "screensize"),
                        float(vw), float(vh))
            glUniform3f(glGetUniformLocation(self.program, "raycolor"), *raycolor)
            glUniform1f(glGetUniformLocation(self.program, "intensity"), float(intensity))

            glDisable(GL_DEPTH_TEST)
            glDepthMask(GL_FALSE)
            glDisable(GL_ALPHA_TEST)
            glEnable(GL_BLEND)
            glBlendFunc(GL_ONE, GL_ONE)

            glBindVertexArray(self._vao)
            glDrawArrays(GL_TRIANGLES, 0, 3)
            glBindVertexArray(0)
        finally:
            glUseProgram(0)
            glBindTexture(GL_TEXTURE_2D, 0)
            glPopAttrib()
