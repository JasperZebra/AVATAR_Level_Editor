"""Standalone cloud overlay — draws the shared cloud layer over the sky EVERY
frame (day AND night), so the clouds are always present instead of vanishing
with the day-only atmosphere. A fullscreen pass: reconstruct the world view ray
per pixel from the current GL matrices, sample the shared cloud_layer, adapt the
lighting for night (moonlit blue-grey), and alpha-blend over the frame. Written
with no depth so the later scene geometry draws over it (clouds stay a backdrop).
All GL guarded — any failure disables it, never a blank sky."""
import numpy as np
from OpenGL.GL import *

try:
    from cloud_common import CLOUD_GLSL
except Exception:
    CLOUD_GLSL = ""

_VS = """
#version 330
layout(location = 0) in vec2 vert;
void main(void){ gl_Position = vec4(vert, 0.0, 1.0); }
"""

_FS = """
#version 330
out vec4 frag;
uniform mat4  u_view;
uniform mat4  u_proj;
uniform vec2  u_res;
uniform vec3  u_sun;        // sun direction in world (points at the sun)
uniform float u_time;
uniform float u_cover;
uniform float u_day;        // 1 daytime .. 0 night (drives cloud lighting)
//__CLOUD_GLSL__//
void main(void)
{
    vec2 ndc = (gl_FragCoord.xy / u_res) * 2.0 - 1.0;
    mat4 invVP = inverse(u_proj * u_view);
    vec4 pn = invVP * vec4(ndc, -1.0, 1.0);
    vec4 pf = invVP * vec4(ndc,  1.0, 1.0);
    vec3 ray = normalize(pf.xyz / pf.w - pn.xyz / pn.w);
    vec4 cl = cloud_layer(ray, u_sun, u_time, u_cover);
    if (cl.a <= 0.001) discard;
    // NIGHT: keep the clouds visible but moonlit — dim blue-grey, form kept
    float lum = dot(cl.rgb, vec3(0.333));
    vec3 night = mix(vec3(0.09, 0.11, 0.17), vec3(0.24, 0.27, 0.34),
                     smoothstep(0.30, 0.90, lum));
    vec3 lit = mix(night, cl.rgb, clamp(u_day, 0.0, 1.0));
    frag = vec4(lit, cl.a * 0.94);
}
"""
_FS = _FS.replace("//__CLOUD_GLSL__//", CLOUD_GLSL)


class CloudSky:
    def __init__(self):
        self._prog = None
        self._vao = None
        self._failed = False

    def _build(self):
        if self._failed:
            return False
        try:
            from god_rays import _link          # reuse the guarded compile/link
            self._prog = _link(_VS, _FS)
            if not self._prog:
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
            print(f"[clouds] overlay ready (prog {self._prog})")
            return True
        except Exception as e:
            print(f"[clouds] overlay build failed ({e}) — clouds off")
            self._failed = True
            return False

    def render(self, res, sun_world, t, cover, day):
        """Blend the clouds over the frame. Camera GL matrices must be current
        (read straight from GL, matching the scene). No FBO change — draws to
        whatever is bound."""
        if cover <= 0.001 or self._failed:
            return
        if self._prog is None and not self._build():
            return
        try:
            mv = np.ascontiguousarray(glGetFloatv(GL_MODELVIEW_MATRIX), dtype=np.float32)
            proj = np.ascontiguousarray(glGetFloatv(GL_PROJECTION_MATRIX), dtype=np.float32)
            glUseProgram(self._prog)
            p = self._prog
            glUniformMatrix4fv(glGetUniformLocation(p, b'u_view'), 1, GL_FALSE, mv)
            glUniformMatrix4fv(glGetUniformLocation(p, b'u_proj'), 1, GL_FALSE, proj)
            glUniform2f(glGetUniformLocation(p, b'u_res'), float(res[0]), float(res[1]))
            glUniform3f(glGetUniformLocation(p, b'u_sun'), *[float(v) for v in sun_world])
            glUniform1f(glGetUniformLocation(p, b'u_time'), float(t))
            glUniform1f(glGetUniformLocation(p, b'u_cover'), float(cover))
            glUniform1f(glGetUniformLocation(p, b'u_day'), float(day))
            glDisable(GL_DEPTH_TEST); glDepthMask(GL_FALSE)
            glDisable(GL_CULL_FACE)
            glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glBindVertexArray(self._vao)
            glDrawArrays(GL_TRIANGLES, 0, 3)
            glBindVertexArray(0)
            glUseProgram(0)
            glDisable(GL_BLEND); glDepthMask(GL_TRUE); glEnable(GL_DEPTH_TEST)
        except Exception as e:
            print(f"[clouds] overlay render error ({e}) — disabling")
            self._failed = True
