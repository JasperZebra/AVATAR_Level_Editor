#!/usr/bin/env python3
"""
Volumetric sun rays (light shafts in the air), visible from ANY camera angle.

Ported from the Battalion Wars editor's lib/render/volumetric_rays.py (2026-07)
into the Avatar/FC2 editor, adapted from Z-up to this editor's Y-up world.

Unlike the screen-space god rays (canvas/god_rays.py, which need the sun on
screen), this marches each pixel's view ray through the air and samples the sun
SHADOW MAP at every step: air the sun reaches glows, air in shadow stays dark —
producing true light shafts through gaps between buildings/hills/foliage no
matter where the camera looks. Because it reads the same shadow map the scene
uses (which alpha-tests foliage/grate cutouts), shafts stream through the gaps in
trees for free.

Passes:
  1. Camera depth pass — terrain + models rendered depth-only from the camera into
     a depth texture (so the march knows where each ray hits geometry).
  2. Fullscreen march — reconstruct each pixel's world position from depth, step
     from the camera toward it, accumulate sun visibility from the shadow map
     weighted by a height-based fog density, and add the result over the frame.

Requires the sun shadow map of the same frame (the shadow pass must have run).
All GL is guarded; failures disable the effect.
"""

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

# Y-up adaptation: height is world .y (BW used .z). MAXDIST / fog height come in as
# uniforms so they can be scaled to this editor's world units.
_FRAG = """
#version 330
out vec4 finalColor;

uniform sampler2D depthtex;
uniform sampler2DShadow shadowtex;
uniform mat4 inv_mvp;
uniform mat4 light_vp;
uniform vec3 campos;
uniform vec3 sundir;         // direction TOWARD the sun (world, Y-up)
uniform vec3 raycolor;
uniform float intensity;
uniform float shadow_bias;
uniform float maxdist;       // how far along each ray to march (world units)
uniform float fogheight;     // air density e-fold height (world units)
uniform float groundy;       // terrain reference height (fog is densest here)
uniform vec2 screensize;

const int STEPS = 32;

float sun_visibility(vec3 pos)
{
    vec4 lp = light_vp * vec4(pos, 1.0);
    vec3 pc = lp.xyz / lp.w * 0.5 + 0.5;
    if (pc.x < 0.0 || pc.x > 1.0 || pc.y < 0.0 || pc.y > 1.0 || pc.z > 1.0)
        return 1.0;
    return texture(shadowtex, vec3(pc.xy, pc.z - shadow_bias));
}

void main(void)
{
    vec2 uv = gl_FragCoord.xy / screensize;
    float depth = texture(depthtex, uv).r;

    // World position of the surface under this pixel.
    vec4 ndc = vec4(uv * 2.0 - 1.0, depth * 2.0 - 1.0, 1.0);
    vec4 wp4 = inv_mvp * ndc;
    vec3 wp = wp4.xyz / wp4.w;

    vec3 ray = wp - campos;
    float raylen = min(length(ray), maxdist);
    vec3 dir = normalize(ray);

    // Dithered start offset hides step banding.
    float jitter = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453);
    float stepsize = raylen / float(STEPS);
    vec3 pos = campos + dir * stepsize * (0.5 + jitter);

    float accum = 0.0;
    for (int i = 0; i < STEPS; i++) {
        float vis = sun_visibility(pos);
        // Fog density: densest at the terrain height (groundy), thinning upward.
        // Referenced to groundy — NOT absolute 0 — so a level whose terrain sits at
        // a large world-Y offset still glows near the ground (the absolute-y version
        // collapsed to ~0 and the shafts vanished).
        float fog = exp(-max(pos.y - groundy, 0.0) / fogheight);
        accum += vis * fog;
        pos += dir * stepsize;
    }
    // Softer distance weighting (sqrt, not linear) so shafts stay visible even when
    // nearby geometry shortens the ray, instead of fading toward nothing.
    accum = accum / float(STEPS) * sqrt(clamp(raylen / maxdist, 0.0, 1.0));

    // Phase function with a HIGH floor: shafts read clearly from EVERY direction
    // (the user wants them always on, not only when facing the sun), and brighten
    // further when looking toward the sun.
    float cosang = dot(dir, normalize(sundir));
    float phase = 0.7 + 0.5 * pow(max(cosang, 0.0), 2.0);

    finalColor = vec4(raycolor * accum * phase * intensity, 1.0);
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
        print(f'[volumetric] {label} compile FAILED:\n{log}')
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
        print(f'[volumetric] link FAILED:\n{log}')
        glDeleteProgram(prog)
        return 0
    return int(prog)


class VolumetricRays:
    def __init__(self):
        self._failed = False
        self.fbo = 0
        self.tex = 0
        self.width = 0
        self.height = 0
        self.program = None
        self._vao = None

    def _ensure(self, width, height):
        if self._failed:
            return False
        width, height = max(int(width), 16), max(int(height), 16)
        if self.fbo and width == self.width and height == self.height:
            return True
        try:
            if not self.tex:
                self.tex = int(glGenTextures(1))
            glBindTexture(GL_TEXTURE_2D, self.tex)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT24, width, height,
                         0, GL_DEPTH_COMPONENT, GL_FLOAT, None)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_COMPARE_MODE, GL_NONE)
            glBindTexture(GL_TEXTURE_2D, 0)

            if not self.fbo:
                self.fbo = int(glGenFramebuffers(1))
            glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                                   GL_TEXTURE_2D, self.tex, 0)
            glDrawBuffer(GL_NONE)
            glReadBuffer(GL_NONE)
            ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE
            glBindFramebuffer(GL_FRAMEBUFFER, 0)
            if not ok:
                print("[volumetric] depth FBO incomplete — volumetric rays off")
                self._failed = True
                return False

            if self.program is None:
                self.program = _link(_VERT, _FRAG)
                if not self.program:
                    self._failed = True
                    return False
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
                print("[volumetric] light-shaft renderer ready")

            self.width, self.height = width, height
            return True
        except Exception as e:
            print(f"[volumetric] build failed ({e}) — volumetric rays off")
            self._failed = True
            return False

    def begin_depth(self, width, height):
        """Bind the camera depth buffer; caller draws terrain + models depth-only
        with the camera matrices. Returns False if unavailable."""
        if not self._ensure(width, height):
            return False
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        glViewport(0, 0, self.width, self.height)
        glClear(GL_DEPTH_BUFFER_BIT)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LESS)
        glDepthMask(GL_TRUE)
        return True

    def end_depth(self, default_fbo, vw, vh):
        glBindFramebuffer(GL_FRAMEBUFFER, int(default_fbo))
        glViewport(0, 0, int(vw), int(vh))

    def composite(self, inv_mvp, light_vp, campos, sundir, raycolor, intensity,
                  shadow_tex, shadow_bias, maxdist, fogheight, groundy, vw, vh):
        if self.program is None:
            return
        glPushAttrib(GL_ENABLE_BIT | GL_DEPTH_BUFFER_BIT | GL_COLOR_BUFFER_BIT
                     | GL_TEXTURE_BIT)
        try:
            glUseProgram(self.program)
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, self.tex)
            glActiveTexture(GL_TEXTURE1)
            glBindTexture(GL_TEXTURE_2D, int(shadow_tex))
            glActiveTexture(GL_TEXTURE0)
            glUniform1i(glGetUniformLocation(self.program, "depthtex"), 0)
            glUniform1i(glGetUniformLocation(self.program, "shadowtex"), 1)
            glUniformMatrix4fv(glGetUniformLocation(self.program, "inv_mvp"), 1, GL_TRUE,
                               np.ascontiguousarray(inv_mvp, dtype=np.float32))
            glUniformMatrix4fv(glGetUniformLocation(self.program, "light_vp"), 1, GL_TRUE,
                               np.ascontiguousarray(light_vp, dtype=np.float32))
            glUniform3f(glGetUniformLocation(self.program, "campos"), *campos)
            glUniform3f(glGetUniformLocation(self.program, "sundir"), *sundir)
            glUniform3f(glGetUniformLocation(self.program, "raycolor"), *raycolor)
            glUniform1f(glGetUniformLocation(self.program, "intensity"), float(intensity))
            glUniform1f(glGetUniformLocation(self.program, "shadow_bias"), float(shadow_bias))
            glUniform1f(glGetUniformLocation(self.program, "maxdist"), float(maxdist))
            glUniform1f(glGetUniformLocation(self.program, "fogheight"), float(fogheight))
            glUniform1f(glGetUniformLocation(self.program, "groundy"), float(groundy))
            glUniform2f(glGetUniformLocation(self.program, "screensize"), float(vw), float(vh))

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
            glActiveTexture(GL_TEXTURE1)
            glBindTexture(GL_TEXTURE_2D, 0)
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, 0)
            glPopAttrib()
