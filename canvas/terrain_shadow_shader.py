"""
terrain_shadow_shader.py — per-pixel terrain shader that RECEIVES the sun shadow map.

Ported from the Army Men (AM3D) editor's gl_shader.py terrain path (2026-07),
adapted for this editor's terrain draw. Avatar/FC2 terrain is drawn fixed-function
(client arrays / VBO + a bound diffuse texture on unit 0, GL_LIGHTING on). A
fixed-function surface can't sample the shadow depth map, so — even though the
model path already casts sun shadows — the GROUND never showed a shadow. This
program makes the terrain a shadow RECEIVER: it reproduces the existing
fixed-function sun/fill/ambient lighting per-pixel and multiplies ONLY the sun
term by a 3x3 PCF shadow factor, so objects (and hills) cast onto the terrain.

Design (same as the AM3D port): legacy `#version 120` reading the existing
fixed-function state — the GL matrix stacks (`gl_ModelViewProjectionMatrix`,
`gl_NormalMatrix`), the light rig (`gl_LightSource[i]`, `gl_LightModel.ambient`,
driven per-frame by _render_3d_opengl / _apply_day_night), the bound texture,
and the vertex/normal/texcoord CLIENT ARRAYS. So it drops in around the existing
draw with NO VBO/matrix/light replumbing — just bind the program, set a few
uniforms, and draw. Any compile/link failure returns 0 and the caller falls back
to the fixed-function path (never a hard error / blank ground).

Key adaptation vs AM3D: AM3D terrain verts ARE world coords (v_world = gl_Vertex).
Here terrain is drawn per-tile with glTranslatef(tx, 0, -ty) and local mesh verts,
so the shadow-space world position is `gl_Vertex.xyz + u_tile_offset` where
u_tile_offset = (tx, 0, -ty) matches the translate. The view matrix (gluLookAt)
has no mirror/scale, so this world frame equals the one camera_3d.position (and
therefore ShadowMap.light_vp) live in — terrain shadows align with model shadows.
"""
from OpenGL.GL import *


def _compile_stage(src, stage, label):
    sid = glCreateShader(stage)
    glShaderSource(sid, src)
    glCompileShader(sid)
    if glGetShaderiv(sid, GL_COMPILE_STATUS) != GL_TRUE:
        log = glGetShaderInfoLog(sid)
        if isinstance(log, bytes):
            log = log.decode('utf-8', 'replace')
        print(f'[terrain-shadow] {label} compile FAILED:\n{log}')
        glDeleteShader(sid)
        return 0
    return sid


def compile_program(vs_src, fs_src, label='terrain-shadow'):
    """Compile+link a vertex/fragment program. Returns the GL program id, or 0 on
    any failure (caller falls back). Detaches+deletes the shader objects after link."""
    try:
        vs = _compile_stage(vs_src, GL_VERTEX_SHADER, f'{label}.vs')
        if not vs:
            return 0
        fs = _compile_stage(fs_src, GL_FRAGMENT_SHADER, f'{label}.fs')
        if not fs:
            glDeleteShader(vs)
            return 0
        prog = glCreateProgram()
        glAttachShader(prog, vs); glAttachShader(prog, fs)
        glLinkProgram(prog)
        glDetachShader(prog, vs); glDetachShader(prog, fs)
        glDeleteShader(vs); glDeleteShader(fs)
        if glGetProgramiv(prog, GL_LINK_STATUS) != GL_TRUE:
            log = glGetProgramInfoLog(prog)
            if isinstance(log, bytes):
                log = log.decode('utf-8', 'replace')
            print(f'[terrain-shadow] {label} link FAILED:\n{log}')
            glDeleteProgram(prog)
            return 0
        print(f'[terrain-shadow] compiled OK (prog {int(prog)})')
        return int(prog)
    except Exception as e:
        print(f'[terrain-shadow] build error: {e}')
        return 0


TERRAIN_VS = """
#version 120
uniform vec3 u_tile_offset;      // per-tile world translate (tx, 0, -ty); matches glTranslatef
varying vec3 v_normal_eye;
varying vec3 v_world;
void main() {
    gl_Position   = gl_ModelViewProjectionMatrix * gl_Vertex;
    v_normal_eye  = gl_NormalMatrix * gl_Normal;
    v_world       = gl_Vertex.xyz + u_tile_offset;   // shadow-space world position
    gl_TexCoord[0] = gl_MultiTexCoord0;
}
"""

# Shadow sampling shared with the model path. Projects a world position into the
# sun's light space and PCF-compares against the depth map → 0 (fully shadowed)
# .. 1 (lit). Guarded to 1.0 outside the light frustum. Matches ShadowMap (SIZE
# 2048, standard [0,1] depth, GL_LESS cast) and the light_vp convention
# (row-major, uploaded transpose=GL_TRUE).
_SHADOW_GLSL = """
uniform sampler2DShadow u_shadow;   // hardware depth-compare sampler (LINEAR = bilinear PCF)
uniform mat4  u_light_vp;      // world -> sun light clip
uniform float u_shadow_on;     // 0..1 shadow STRENGTH (day/night synced); 0 = fully lit
uniform float u_shadow_bias;   // normalized depth bias (scaled to the box size)
float sun_shadow(vec3 world) {
    if (u_shadow_on < 0.003) return 1.0;
    vec4 lp = u_light_vp * vec4(world, 1.0);
    if (lp.w <= 0.0) return 1.0;
    vec3 pc = lp.xyz / lp.w * 0.5 + 0.5;               // -> [0,1]
    if (pc.x < 0.0 || pc.x > 1.0 || pc.y < 0.0 || pc.y > 1.0 || pc.z > 1.0) return 1.0;
    float ref = pc.z - u_shadow_bias;
    float tx = 1.0 / 4096.0;                            // ShadowMap.SIZE (keep in sync)
    // 3x3 grid of hardware-PCF taps. Each shadow2D() is a bilinear-filtered
    // depth compare (4 sub-taps), so 9 calls = 36 effective samples -> smooth,
    // non-pixelated edges instead of the old blocky NEAREST compare.
    float s = 0.0;
    for (int i = -1; i <= 1; i++)
        for (int j = -1; j <= 1; j++)
            s += shadow2D(u_shadow, vec3(pc.xy + vec2(float(i), float(j)) * tx, ref)).r;
    return s / 9.0;
}
"""

TERRAIN_FS = """
#version 120
uniform sampler2D u_tex;
varying vec3 v_normal_eye;
varying vec3 v_world;
__SHADOW__
void main() {
    vec3 N = normalize(v_normal_eye);
    if (!gl_FrontFacing) N = -N;                        // terrain is single-sided but be safe
    // Directional lights (w=0) set after gluLookAt → their .position is already an
    // EYE-space direction. Same rig the fixed-function terrain used, so lighting
    // matches; we only ADD the shadow factor on the sun term.
    vec3 L0 = normalize(gl_LightSource[0].position.xyz);   // sun
    vec3 L1 = normalize(gl_LightSource[1].position.xyz);   // sky fill (straight up)
    float d0 = max(dot(N, L0), 0.0);
    float d1 = max(dot(N, L1), 0.0);
    float sh = sun_shadow(v_world);            // 0 shadowed .. 1 lit (sun term only)
    vec3 lit = gl_LightModel.ambient.rgb
             + gl_LightSource[0].diffuse.rgb * d0 * sh
             + gl_LightSource[1].diffuse.rgb * d1;
    vec4 tex = texture2D(u_tex, gl_TexCoord[0].xy);
    // Deepen the shadow so object shadows read clearly on the ground: darken the
    // WHOLE colour where the sun is blocked (not just drop the sun highlight). A
    // shadowed patch goes to SHADOW_DARK of its lit brightness AT FULL STRENGTH;
    // near dawn/dusk u_shadow_on eases the darkness back toward 1.0 (no shadow),
    // so the shadow fades in/out with the sun instead of snapping on.
    float darkAmt = mix(1.0, SHADOW_DARK, u_shadow_on);
    float shade = mix(darkAmt, 1.0, sh);
    gl_FragColor = vec4(tex.rgb * lit * shade, tex.a);
}
""".replace('__SHADOW__', _SHADOW_GLSL).replace('SHADOW_DARK', '0.25')


# Uniform names the caller looks up (kept together so map_canvas_gpu stays tidy).
UNIFORMS = ('u_tex', 'u_shadow', 'u_light_vp', 'u_shadow_on', 'u_tile_offset', 'u_shadow_bias')


def build():
    """Compile the terrain shadow-receiver program and return (prog, {uniform: loc}).
    prog == 0 on failure (caller falls back to fixed-function)."""
    prog = compile_program(TERRAIN_VS, TERRAIN_FS)
    if not prog:
        return 0, {}
    locs = {}
    for name in UNIFORMS:
        locs[name] = glGetUniformLocation(prog, name)
    return prog, locs


# ── Terrain depth-CAST program (makes the terrain a solid shadow occluder) ──────
# AM3D casts its terrain chunks into the shadow map so the ground is a real
# occluder (hills cast, terrain self-shadows, objects are shadowed by terrain
# between them and the sun). Avatar's terrain was invisible to the shadow pass —
# it only received. This depth-only program writes the terrain's depth into the
# map using the SAME world position as the receiver (gl_Vertex + tile offset),
# projected by the sun's light_vp. Empty fragment = depth only. Polygon offset
# (set by ShadowMap.begin) keeps it from self-shadow-acne'ing the terrain.
TERRAIN_DEPTH_VS = """
#version 120
uniform mat4 u_light_vp;
uniform vec3 u_tile_offset;
void main() {
    gl_Position = u_light_vp * vec4(gl_Vertex.xyz + u_tile_offset, 1.0);
}
"""
TERRAIN_DEPTH_FS = """
#version 120
void main() { }
"""
DEPTH_UNIFORMS = ('u_light_vp', 'u_tile_offset')


def build_depth():
    """Compile the terrain depth-cast program. Returns (prog, {uniform: loc});
    prog == 0 on failure (caller simply skips terrain casting)."""
    prog = compile_program(TERRAIN_DEPTH_VS, TERRAIN_DEPTH_FS, label='terrain-depth')
    if not prog:
        return 0, {}
    return prog, {n: glGetUniformLocation(prog, n) for n in DEPTH_UNIFORMS}
