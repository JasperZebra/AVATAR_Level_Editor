#!/usr/bin/env python3
"""
Per-pixel GLSL material shader for XBG models (Phase 2) WITH HARDWARE INSTANCING.

Each unique model is drawn for ALL its instances in ONE glDrawElementsInstanced
call — the per-instance transform (position / euler rotation / scale) and the
selection overlay come from per-instance vertex attributes, so the renderer no
longer issues one draw + matrix-stack push per object. That collapses tens of
thousands of PyOpenGL calls/frame into a few thousand, which is what made fly-
around in 3D usable.

Why the transform is done in the shader (not as a CPU matrix):
  * The legacy per-instance transform was the fixed-function sequence
        glTranslatef(pos) · glRotatef(-90,X) · glRotatef(-rz,Z) ·
        glRotatef(rx,X) · glRotatef(ry,Y) · glScalef(s)
    The vertex shader's modelRot() replicates that EXACTLY from the raw
    pos/rot/scale attributes — no column-major matrix juggling on the CPU, so
    there's nothing to get subtly wrong. (Verified numerically against the
    glRotatef order.)
  * The fixed-function matrix stack now carries the VIEW only (gluLookAt), so
    gl_ModelViewMatrix = view and gl_ModelViewProjectionMatrix = proj·view; the
    shader applies the per-instance model transform on top.

GLSL 1.20 (compatibility) + ARB_instanced_arrays (glVertexAttribDivisor) +
glDrawElementsInstanced. If any of that is unavailable / fails to compile, the
caller falls back to the fixed-function display-list renderer, so the worst case
is "slow but works", never a blank viewport.
"""

import OpenGL.GL as gl

# Per-vertex attribute locations.
ATTR_POSITION = 0
ATTR_NORMAL = 1
ATTR_UV = 2
ATTR_TANGENT = 3
# Per-INSTANCE attribute locations (divisor 1).
ATTR_INST_POS = 4      # vec3 world position
ATTR_INST_ROT = 5      # vec3 euler (rx, ry, rz) degrees
ATTR_INST_SCALE = 6    # float uniform scale
ATTR_INST_OVERLAY = 7  # float selection overlay (0..1)

INSTANCE_STRIDE = 32   # 8 float32 per instance (pos3, rot3, scale1, overlay1)

# Shared instance-transform GLSL — used VERBATIM by BOTH the material vertex
# shader and the depth-prepass vertex shader. Sharing the source (not copying)
# guarantees the two passes compute gl_Position identically, which (with the
# `invariant gl_Position` below) lets the color pass use GL_LEQUAL/GL_EQUAL early-Z
# against the prepass depth without z-fighting. Verified equal to the legacy
# glRotatef order to 2e-13.
_ROT_GLSL = """
vec3 rotX(vec3 p, float d){ float a=radians(d), c=cos(a), s=sin(a); return vec3(p.x, c*p.y - s*p.z, s*p.y + c*p.z); }
vec3 rotY(vec3 p, float d){ float a=radians(d), c=cos(a), s=sin(a); return vec3(c*p.x + s*p.z, p.y, -s*p.x + c*p.z); }
vec3 rotZ(vec3 p, float d){ float a=radians(d), c=cos(a), s=sin(a); return vec3(c*p.x - s*p.y, s*p.x + c*p.y, p.z); }
// Rotation part of the legacy transform: Rx(-90) . Rz(-rz) . Rx(rx) . Ry(ry).
vec3 modelRot(vec3 p, vec3 rot){
    p = rotY(p, rot.y);
    p = rotX(p, rot.x);
    p = rotZ(p, -rot.z);
    p = rotX(p, -90.0);
    return p;
}
"""

_VERT_SRC = """
#version 120
attribute vec3  a_position;
attribute vec3  a_normal;
attribute vec2  a_uv;
attribute vec3  a_tangent;
attribute vec3  a_inst_pos;
attribute vec3  a_inst_rot;
attribute float a_inst_scale;
attribute float a_inst_overlay;

uniform vec2 u_uv_offset;   // animated-UV scroll (per material)

varying vec3  v_posES;
varying vec3  v_normalES;
varying vec3  v_tangentES;
varying vec2  v_uv;
varying float v_overlay;

invariant gl_Position;      // bit-identical depth vs the prepass (early-Z safety)
""" + _ROT_GLSL + """
void main(){
    vec3 wp = modelRot(a_position * a_inst_scale, a_inst_rot) + a_inst_pos;
    v_posES     = vec3(gl_ModelViewMatrix * vec4(wp, 1.0));
    v_normalES  = gl_NormalMatrix * modelRot(a_normal,  a_inst_rot);
    v_tangentES = gl_NormalMatrix * modelRot(a_tangent, a_inst_rot);
    v_uv        = a_uv + u_uv_offset;
    v_overlay   = a_inst_overlay;
    gl_Position = gl_ModelViewProjectionMatrix * vec4(wp, 1.0);
}
"""

# Depth-only prepass: same transform (shared _ROT_GLSL + invariant), no lighting/
# textures except the alpha-mask discard so masked materials carve the same
# silhouette into depth that the color pass expects.
_DEPTH_VERT_SRC = """
#version 120
attribute vec3  a_position;
attribute vec2  a_uv;
attribute vec3  a_inst_pos;
attribute vec3  a_inst_rot;
attribute float a_inst_scale;
uniform vec2 u_uv_offset;
varying vec2 v_uv;
invariant gl_Position;
""" + _ROT_GLSL + """
void main(){
    vec3 wp = modelRot(a_position * a_inst_scale, a_inst_rot) + a_inst_pos;
    v_uv = a_uv + u_uv_offset;
    gl_Position = gl_ModelViewProjectionMatrix * vec4(wp, 1.0);
}
"""

_DEPTH_FRAG_SRC = """
#version 120
uniform sampler2D u_diffuse;
uniform int   u_alpha_mode;     // 1 = mask (discard); else opaque (no work)
uniform float u_alpha_cutoff;
varying vec2 v_uv;
void main(){
    if (u_alpha_mode == 1) {
        if (texture2D(u_diffuse, v_uv).a < u_alpha_cutoff) discard;
    }
    gl_FragColor = vec4(0.0);   // color writes are masked off anyway
}
"""

_FRAG_SRC = """
#version 120
// The 3D rig enables only GL_LIGHT0 (sun) + GL_LIGHT1 (sky fill); GL_LIGHT2 is
// always disabled (map_canvas_gpu lines ~3014/5288/5396). Looping to 3 ran the
// full per-pixel lighting math for a dead light on every fragment — wasted ALU.
// Constant bound (not a uniform) so the loop stays unrollable on old drivers.
#define NUM_LIGHTS 2
uniform sampler2D u_diffuse;
uniform sampler2D u_normal;
uniform sampler2D u_specular;
uniform sampler2D u_emission;
uniform int   u_has_diffuse;
uniform int   u_has_normal;
uniform int   u_has_specular;
uniform int   u_has_emission;

uniform vec3  u_tint;
uniform vec3  u_emissive;
uniform vec3  u_spec_color;
uniform float u_shininess;
uniform int   u_alpha_mode;    // 0 opaque, 1 mask, 2 blend
uniform float u_alpha_cutoff;
uniform vec3  u_overlay_color;
uniform int   u_unlit;         // debug A/B: 1 = skip the per-light loop (ambient only)
uniform float u_night;         // bioluminescence: emission scaled by this (1=normal/day-off, night→glow)
uniform int   u_flip_green;    // debug: 1 = flip normal-map green (Y) channel
uniform int   u_flip_normal;   // debug: 1 = flip the base geometry normal

varying vec3  v_posES;
varying vec3  v_normalES;
varying vec3  v_tangentES;
varying vec2  v_uv;
varying float v_overlay;

void main() {
    vec4 diff = (u_has_diffuse == 1) ? texture2D(u_diffuse, v_uv) : vec4(1.0);
    float alpha = diff.a;
    if (u_alpha_mode == 1 && alpha < u_alpha_cutoff) discard;

    vec3 base = diff.rgb * u_tint;

    vec3 N = normalize(v_normalES);
    if (u_flip_normal == 1) N = -N;
    if (u_has_normal == 1) {
        // TBN from screen-space derivatives (Schüler) — handedness is automatic,
        // so mirrored-UV regions don't invert (no precomputed-tangent dependency).
        vec3 dp1 = dFdx(v_posES), dp2 = dFdy(v_posES);
        vec2 du1 = dFdx(v_uv),    du2 = dFdy(v_uv);
        vec3 dp2p = cross(dp2, N), dp1p = cross(N, dp1);
        vec3 T = dp2p * du1.x + dp1p * du2.x;
        vec3 B = dp2p * du1.y + dp1p * du2.y;
        float im = inversesqrt(max(dot(T, T), dot(B, B)));
        vec3 nTS = texture2D(u_normal, v_uv).rgb * 2.0 - 1.0;
        if (u_flip_green == 1) nTS.y = -nTS.y;
        N = normalize(mat3(T * im, B * im, N) * nTS);
    }
    vec3 V = normalize(-v_posES);
    if (dot(N, V) < 0.0) N = -N;

    vec3 specMap = (u_has_specular == 1) ? texture2D(u_specular, v_uv).rgb : vec3(1.0);

    vec3 color = gl_LightModel.ambient.rgb * base;
    if (u_unlit == 0) {
        for (int i = 0; i < NUM_LIGHTS; i++) {
            vec4 lp = gl_LightSource[i].position;
            vec3 L = normalize(lp.xyz - v_posES * lp.w);
            float ndl = max(dot(N, L), 0.0);
            color += base * gl_LightSource[i].diffuse.rgb * ndl;
            if (ndl > 0.0) {
                vec3 H = normalize(L + V);
                float s = pow(max(dot(N, H), 0.0), max(u_shininess, 1.0));
                color += gl_LightSource[i].specular.rgb * u_spec_color * specMap * s;
            }
        }
    }

    if (u_has_emission == 1) color += texture2D(u_emission, v_uv).rgb * u_emissive * u_night;
    else                     color += u_emissive * u_night;

    color = mix(color, u_overlay_color, v_overlay);

    float out_a = (u_alpha_mode == 2) ? alpha : 1.0;
    gl_FragColor = vec4(color, out_a);
}
"""

_UNIFORMS = (
    'u_diffuse', 'u_normal', 'u_specular', 'u_emission',
    'u_has_diffuse', 'u_has_normal', 'u_has_specular', 'u_has_emission',
    'u_tint', 'u_emissive', 'u_spec_color', 'u_shininess',
    'u_alpha_mode', 'u_alpha_cutoff', 'u_overlay_color', 'u_uv_offset', 'u_unlit', 'u_night',
    'u_flip_green', 'u_flip_normal',
)


class ModelShader:
    """Lazily-compiled GLSL material program with instancing. compile() -> bool;
    on any failure the caller uses the fixed-function fallback."""

    def __init__(self):
        self.program = None
        self.uniforms = {}
        self._failed = False

    def compile(self):
        if self.program is not None:
            return True
        if self._failed:
            return False
        try:
            vs = self._compile_stage(gl.GL_VERTEX_SHADER, _VERT_SRC)
            fs = self._compile_stage(gl.GL_FRAGMENT_SHADER, _FRAG_SRC)
            if not vs or not fs:
                self._failed = True
                return False
            prog = gl.glCreateProgram()
            gl.glAttachShader(prog, vs)
            gl.glAttachShader(prog, fs)
            gl.glBindAttribLocation(prog, ATTR_POSITION, b'a_position')
            gl.glBindAttribLocation(prog, ATTR_NORMAL, b'a_normal')
            gl.glBindAttribLocation(prog, ATTR_UV, b'a_uv')
            gl.glBindAttribLocation(prog, ATTR_TANGENT, b'a_tangent')
            gl.glBindAttribLocation(prog, ATTR_INST_POS, b'a_inst_pos')
            gl.glBindAttribLocation(prog, ATTR_INST_ROT, b'a_inst_rot')
            gl.glBindAttribLocation(prog, ATTR_INST_SCALE, b'a_inst_scale')
            gl.glBindAttribLocation(prog, ATTR_INST_OVERLAY, b'a_inst_overlay')
            gl.glLinkProgram(prog)
            gl.glDeleteShader(vs)
            gl.glDeleteShader(fs)
            if gl.glGetProgramiv(prog, gl.GL_LINK_STATUS) != gl.GL_TRUE:
                print(f"[model_shader] LINK FAILED: {gl.glGetProgramInfoLog(prog)}")
                gl.glDeleteProgram(prog)
                self._failed = True
                return False
            self.program = prog
            for name in _UNIFORMS:
                self.uniforms[name] = gl.glGetUniformLocation(prog, name.encode('ascii'))
            print("[model_shader] GLSL instanced material program compiled + linked OK")
            return True
        except Exception as e:
            print(f"[model_shader] compile exception: {e}")
            import traceback
            traceback.print_exc()
            self._failed = True
            return False

    def _compile_stage(self, stage, src):
        sh = gl.glCreateShader(stage)
        gl.glShaderSource(sh, src)
        gl.glCompileShader(sh)
        if gl.glGetShaderiv(sh, gl.GL_COMPILE_STATUS) != gl.GL_TRUE:
            kind = 'VERTEX' if stage == gl.GL_VERTEX_SHADER else 'FRAGMENT'
            print(f"[model_shader] {kind} COMPILE FAILED: {gl.glGetShaderInfoLog(sh)}")
            gl.glDeleteShader(sh)
            return None
        return sh

    def u(self, name):
        return self.uniforms.get(name, -1)


_DEPTH_UNIFORMS = ('u_uv_offset', 'u_diffuse', 'u_alpha_mode', 'u_alpha_cutoff')


class DepthShader:
    """Depth-only prepass program (occlusion / early-Z). Shares the instancing
    transform with ModelShader (same _ROT_GLSL + `invariant gl_Position`) so the
    color pass can early-Z against this pass's depth. compile() -> bool; on any
    failure the caller simply skips the prepass (the color pass still renders
    correctly, just without the overdraw savings)."""

    def __init__(self):
        self.program = None
        self.uniforms = {}
        self._failed = False

    def compile(self):
        if self.program is not None:
            return True
        if self._failed:
            return False
        try:
            vs = ModelShader._compile_stage(self, gl.GL_VERTEX_SHADER, _DEPTH_VERT_SRC)
            fs = ModelShader._compile_stage(self, gl.GL_FRAGMENT_SHADER, _DEPTH_FRAG_SRC)
            if not vs or not fs:
                self._failed = True
                return False
            prog = gl.glCreateProgram()
            gl.glAttachShader(prog, vs)
            gl.glAttachShader(prog, fs)
            gl.glBindAttribLocation(prog, ATTR_POSITION, b'a_position')
            gl.glBindAttribLocation(prog, ATTR_UV, b'a_uv')
            gl.glBindAttribLocation(prog, ATTR_INST_POS, b'a_inst_pos')
            gl.glBindAttribLocation(prog, ATTR_INST_ROT, b'a_inst_rot')
            gl.glBindAttribLocation(prog, ATTR_INST_SCALE, b'a_inst_scale')
            gl.glLinkProgram(prog)
            gl.glDeleteShader(vs)
            gl.glDeleteShader(fs)
            if gl.glGetProgramiv(prog, gl.GL_LINK_STATUS) != gl.GL_TRUE:
                print(f"[model_shader] DEPTH LINK FAILED: {gl.glGetProgramInfoLog(prog)}")
                gl.glDeleteProgram(prog)
                self._failed = True
                return False
            self.program = prog
            for name in _DEPTH_UNIFORMS:
                self.uniforms[name] = gl.glGetUniformLocation(prog, name.encode('ascii'))
            print("[model_shader] GLSL depth-prepass program compiled + linked OK")
            return True
        except Exception as e:
            print(f"[model_shader] depth compile exception: {e}")
            self._failed = True
            return False

    def u(self, name):
        return self.uniforms.get(name, -1)
