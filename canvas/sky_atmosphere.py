#!/usr/bin/env python3
"""
Daytime atmosphere sky — real-time port of fgarlin's spectral sky
(canvas/Night Sky/Shader toy/): physically-based Rayleigh + aerosol + ozone +
multiple scattering, spectral (4 wavelengths) → sRGB.

Pipeline (same as the ShaderToy, adapted to desktop GL + the editor camera):
  1. Transmittance LUT  (Buffer A) — sun-independent, computed ONCE → FBO float tex.
  2. Sky-view LUT       (Buffer B) — depends on the sun; recomputed per frame → FBO.
  3. Composite          — fullscreen background pass: build the world view ray from
     the editor camera, map to (elevation, azimuth-relative-to-sun), sample the
     sky-view LUT, ACES tonemap. The physics darkens the sky by itself as the sun
     sets, so it crossfades naturally into the night-sky dome.

The GLSL sources are EMBEDDED in canvas/sky_shader_sources.py (they used to be
read from loose `canvas/Night Sky/Shader toy/*.txt` files, which were never in
git and got lost once — and needed separate bundling for frozen builds). They
are wrapped at runtime exactly as before (ShaderToy `mainImage` → `main`,
`iResolution`/`iChannel0` → uniforms, `get_sun_direction` → `u_sun_dir`), so we
run the author's exact maths. Any failure (no float FBO, compile error, …)
sets `_failed` and the caller falls back to the gradient sky — never a hard error.
"""

import math
import ctypes
import numpy as np
from OpenGL.GL import *

_FULLSCREEN_VS = """
#version 460
void main() {
    // Single fullscreen triangle from gl_VertexID (no vertex buffer needed).
    vec2 p = vec2((gl_VertexID == 2) ? 3.0 : -1.0,
                  (gl_VertexID == 1) ? 3.0 : -1.0);
    gl_Position = vec4(p, 0.0, 1.0);
}
"""

_COMPOSITE_FS = """
#version 460
uniform sampler2D iChannel0;        // sky-view LUT (Buffer B)
uniform vec2  u_res;
uniform mat4  u_view;                // GL MODELVIEW (gluLookAt) — exact render view
uniform mat4  u_proj;                // GL PROJECTION (gluPerspective)
uniform vec3  u_sun_world;           // sun direction in world (normalized)
uniform float u_sun_az, u_exposure;
out vec4 _out;

const float PI = 3.14159265358979;

const mat3 aces_input_mat = mat3(
    0.59719, 0.07600, 0.02840,
    0.35458, 0.90834, 0.13383,
    0.04823, 0.01566, 0.83777);
const mat3 aces_output_mat = mat3(
     1.60475, -0.10208, -0.00327,
    -0.53108,  1.10813, -0.07276,
    -0.07367, -0.00605,  1.07602);
vec3 rrt_and_odt_fit(vec3 v){ vec3 a=v*(v+0.0245786)-0.000090537; vec3 b=v*(0.983729*v+0.4329510)+0.238081; return a/b; }
vec3 aces_fitted(vec3 c){ c=aces_input_mat*c; c=rrt_and_odt_fit(c); c=aces_output_mat*c; return clamp(c,0.0,1.0); }
vec3 gamma_correct(vec3 c){ vec3 a=12.92*c; vec3 b=1.055*pow(c,vec3(1.0/2.4))-0.055; vec3 s=step(vec3(0.0031308),c); return mix(a,b,s); }

void main() {
    vec2 ndc = (gl_FragCoord.xy / u_res) * 2.0 - 1.0;
    // World-space view ray straight from the GL matrices the scene renders with
    // (no reliance on a separate camera basis → the sky is locked to the world).
    mat4 invVP = inverse(u_proj * u_view);
    vec4 pn = invVP * vec4(ndc, -1.0, 1.0);
    vec4 pf = invVP * vec4(ndc,  1.0, 1.0);
    vec3 ray = normalize(pf.xyz / pf.w - pn.xyz / pn.w);
    float elev = asin(clamp(ray.y, -1.0, 1.0));
    float view_az = atan(ray.z, ray.x);
    float rel = view_az - u_sun_az;
    // Buffer B places the sun at azimuth PI; sample relative to it.
    float lut_az = mod(PI + rel, 2.0 * PI) / (2.0 * PI);
    float lut_el = sqrt(abs(elev) / (PI * 0.5)) * sign(elev) * 0.5 + 0.5;
    vec3 col = texture(iChannel0, vec2(lut_az, lut_el)).rgb;
    col *= exp2(u_exposure);
    col = aces_fitted(col);
    col = clamp(gamma_correct(col), 0.0, 1.0);

    // Sun: an ADDITIVE bright disk + halo (so it reads as a light source over the
    // bright sky, not a low-contrast tint). Faded out below the horizon.
    float cd = dot(ray, normalize(u_sun_world));
    float above = smoothstep(-0.10, 0.05, u_sun_world.y);
    float disk = smoothstep(0.99986, 0.99996, cd);        // crisp disk (~0.5-1°)
    float halo = smoothstep(0.985, 1.0, cd); halo *= halo; // tight soft aureole
    vec3 sun_col = vec3(1.0, 0.96, 0.88);
    col += above * (disk * 1.6 + halo * 0.25) * sun_col;
    col = clamp(col, 0.0, 1.0);

    _out = vec4(col, 1.0);
}
"""


def _read(name):
    """Return an embedded GLSL source by its historical file name.

    Sources live in canvas/sky_shader_sources.py (no runtime file dependency —
    works identically in dev and frozen builds)."""
    try:
        from canvas import sky_shader_sources as _sss
    except ImportError:
        import sky_shader_sources as _sss   # flat import (canvas dir on sys.path)
    return _sss.SOURCES[name]


def _adapt_common(src):
    """Make the ShaderToy Common compile on desktop GL 4.60 + take a uniform sun."""
    src = src.replace('1e-4f', '1e-4').replace('1e-4F', '1e-4')
    # Replace the body of get_sun_direction(...) with a uniform lookup.
    import re
    src = re.sub(r'vec3\s+get_sun_direction\s*\([^)]*\)\s*\{.*?\n\}',
                 'uniform vec3 u_sun_dir;\nvec3 get_sun_direction(float time){ return u_sun_dir; }',
                 src, count=1, flags=re.DOTALL)
    return src


def _wrap_buffer(common_src, buffer_src, extra_uniforms=''):
    """ShaderToy buffer → a full fragment program."""
    return ("#version 460\n"
            "uniform vec3 iResolution;\n"
            "uniform float iTime;\n"
            + extra_uniforms + "\n"
            + common_src + "\n"
            + buffer_src + "\n"
            "out vec4 _frag;\n"
            "void main(){ vec4 c; mainImage(c, gl_FragCoord.xy); _frag = c; }\n")


class AtmosphereSky:
    TRANS_W, TRANS_H = 256, 64       # transmittance LUT (sun-independent)
    SKY_W, SKY_H = 200, 120          # sky-view LUT (per sun position)

    def __init__(self):
        self._built = False
        self._failed = False
        self._trans_done = False
        self.prog_trans = self.prog_sky = self.prog_comp = 0
        self.fbo_trans = self.tex_trans = 0
        self.fbo_sky = self.tex_sky = 0
        self.vao = 0
        self.exposure = -4.0

    # ---- build ----
    def _build(self):
        if self._failed:
            return False
        try:
            common = _adapt_common(_read('Common.txt'))
            trans_fs = _wrap_buffer(common, _read('Buffer A.txt'))
            sky_fs = _wrap_buffer(common, _read('Buffer B.txt'),
                                  'uniform sampler2D iChannel0;')
            self.prog_trans = _compile(_FULLSCREEN_VS, trans_fs, 'transmittance')
            self.prog_sky = _compile(_FULLSCREEN_VS, sky_fs, 'sky-view')
            self.prog_comp = _compile(_FULLSCREEN_VS, _COMPOSITE_FS, 'composite')
            if not (self.prog_trans and self.prog_sky and self.prog_comp):
                self._failed = True
                return False
            self.fbo_trans, self.tex_trans = _make_float_fbo(self.TRANS_W, self.TRANS_H)
            self.fbo_sky, self.tex_sky = _make_float_fbo(self.SKY_W, self.SKY_H)
            if not (self.fbo_trans and self.fbo_sky):
                self._failed = True
                return False
            self.vao = int(glGenVertexArrays(1))   # empty VAO for the fullscreen triangle
            self._built = True
            print("[atmosphere] spectral sky compiled (transmittance LUT builds on first frame)")
            return True
        except Exception as e:
            import traceback
            print(f"[atmosphere] build failed ({e}) — gradient sky fallback")
            traceback.print_exc()
            self._failed = True
            return False

    def _render_to(self, fbo, w, h, prog, sun_dir=None, bind_trans=False):
        glBindFramebuffer(GL_FRAMEBUFFER, fbo)
        glViewport(0, 0, w, h)
        glUseProgram(prog)
        glUniform3f(glGetUniformLocation(prog, b'iResolution'), float(w), float(h), 0.0)
        loc_t = glGetUniformLocation(prog, b'iTime')
        if loc_t != -1:
            glUniform1f(loc_t, 0.0)
        if sun_dir is not None:
            loc = glGetUniformLocation(prog, b'u_sun_dir')
            if loc != -1:
                glUniform3f(loc, sun_dir[0], sun_dir[1], sun_dir[2])
        if bind_trans:
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, self.tex_trans)
            glUniform1i(glGetUniformLocation(prog, b'iChannel0'), 0)
        glDisable(GL_DEPTH_TEST); glDepthMask(GL_FALSE); glDisable(GL_BLEND); glDisable(GL_CULL_FACE)
        glBindVertexArray(self.vao)
        glDrawArrays(GL_TRIANGLES, 0, 3)
        glBindVertexArray(0)
        # NB: leave the FBO bound; render() rebinds the widget's default FBO at the end.

    # ---- per-frame ----
    def render(self, cam, sun_elev_sin, sun_az, screen_w, screen_h,
               default_fbo=0, sun_world=(0.0, 1.0, 0.0), fov_deg=50.0):
        """Draw the sky as a fullscreen background to the widget's default FBO.
        cam: object with .forward/.right/.up (world). sun_elev_sin: sin(sun elevation)
        (>0 day, <0 night). sun_az: sun azimuth in editor world (atan2(z,x)).
        default_fbo: QOpenGLWidget.defaultFramebufferObject() — NOT 0 (Qt renders to
        its own FBO; binding 0 would render to nowhere)."""
        if self._failed:
            return False
        if not self._built and not self._build():
            return False
        try:
            # Capture the real viewport (device pixels — correct under high-DPI) to
            # restore for the composite after the small-viewport LUT passes.
            vp = glGetIntegerv(GL_VIEWPORT)
            vx, vy, vw, vh = int(vp[0]), int(vp[1]), int(vp[2]), int(vp[3])
            if vw <= 0 or vh <= 0:
                vw, vh = int(screen_w), int(screen_h)
                vx = vy = 0

            # Capture the EXACT view + projection the scene renders with (glGet
            # returns column-major; pass straight to glUniformMatrix4fv transpose=
            # GL_FALSE — round-trips correctly). The LUT passes below don't touch
            # the fixed-function matrix stacks, so these stay valid for the composite.
            mv = np.ascontiguousarray(glGetFloatv(GL_MODELVIEW_MATRIX), dtype=np.float32)
            proj = np.ascontiguousarray(glGetFloatv(GL_PROJECTION_MATRIX), dtype=np.float32)

            # Sun in the atmosphere model frame (z-up): SUN_DIR = (-cos, 0, sin(elev)).
            e = max(-1.0, min(1.0, float(sun_elev_sin)))
            sun_model = (-math.sqrt(max(0.0, 1.0 - e * e)), 0.0, e)

            # Transmittance LUT is sun-independent → render it once (now that we're
            # in a frame and can restore the default FBO afterwards).
            if not self._trans_done:
                self._render_to(self.fbo_trans, self.TRANS_W, self.TRANS_H, self.prog_trans)
                self._trans_done = True

            # 1) sky-view LUT for this sun position
            self._render_to(self.fbo_sky, self.SKY_W, self.SKY_H, self.prog_sky,
                            sun_dir=sun_model, bind_trans=True)

            # 2) composite to the widget's default framebuffer (background; depth off)
            glBindFramebuffer(GL_FRAMEBUFFER, int(default_fbo))
            glViewport(vx, vy, vw, vh)
            glUseProgram(self.prog_comp)
            p = self.prog_comp
            glUniform2f(glGetUniformLocation(p, b'u_res'), float(vw), float(vh))
            glUniformMatrix4fv(glGetUniformLocation(p, b'u_view'), 1, GL_FALSE, mv)
            glUniformMatrix4fv(glGetUniformLocation(p, b'u_proj'), 1, GL_FALSE, proj)
            glUniform1f(glGetUniformLocation(p, b'u_sun_az'), float(sun_az))
            glUniform1f(glGetUniformLocation(p, b'u_exposure'), float(self.exposure))
            sw = _v3(sun_world)
            glUniform3f(glGetUniformLocation(p, b'u_sun_world'), *sw)
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, self.tex_sky)
            glUniform1i(glGetUniformLocation(p, b'iChannel0'), 0)
            glDisable(GL_DEPTH_TEST); glDepthMask(GL_FALSE); glDisable(GL_BLEND); glDisable(GL_CULL_FACE)
            glBindVertexArray(self.vao)
            glDrawArrays(GL_TRIANGLES, 0, 3)
            glBindVertexArray(0)
            glUseProgram(0)
            glDepthMask(GL_TRUE); glEnable(GL_DEPTH_TEST)
            return True
        except Exception as e:
            print(f"[atmosphere] render error ({e}) — disabling")
            self._failed = True
            return False


def _v3(v):
    return (float(v[0]), float(v[1]), float(v[2]))


def _compile(vs, fs, name):
    def stage(kind, src):
        sh = glCreateShader(kind)
        glShaderSource(sh, src)
        glCompileShader(sh)
        if glGetShaderiv(sh, GL_COMPILE_STATUS) != GL_TRUE:
            k = 'VS' if kind == GL_VERTEX_SHADER else 'FS'
            print(f"[atmosphere] {name} {k} COMPILE FAILED: {glGetShaderInfoLog(sh)}")
            glDeleteShader(sh); return 0
        return sh
    v = stage(GL_VERTEX_SHADER, vs)
    f = stage(GL_FRAGMENT_SHADER, fs)
    if not v or not f:
        return 0
    p = glCreateProgram(); glAttachShader(p, v); glAttachShader(p, f); glLinkProgram(p)
    glDeleteShader(v); glDeleteShader(f)
    if glGetProgramiv(p, GL_LINK_STATUS) != GL_TRUE:
        print(f"[atmosphere] {name} LINK FAILED: {glGetProgramInfoLog(p)}")
        glDeleteProgram(p); return 0
    return p


def _make_float_fbo(w, h):
    tex = int(glGenTextures(1))
    glBindTexture(GL_TEXTURE_2D, tex)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, w, h, 0, GL_RGBA, GL_FLOAT, None)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
    fbo = int(glGenFramebuffers(1))
    glBindFramebuffer(GL_FRAMEBUFFER, fbo)
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0)
    ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE
    glBindFramebuffer(GL_FRAMEBUFFER, 0)
    if not ok:
        print("[atmosphere] float FBO incomplete")
        return 0, 0
    return fbo, tex
