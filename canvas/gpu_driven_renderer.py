#!/usr/bin/env python3
"""
GPU-driven model renderer — GL 4.3+ MultiDrawIndirect + (optional) bindless textures.

WHY: the PyOpenGL instanced path is CPU-bound on draw submission (~45k GL calls /
frame ≈ 84 ms for a dense level; the GPU then sits idle). This renderer collapses
all opaque model draws into ONE glMultiDrawElementsIndirect call — the GPU pulls
geometry, per-instance transforms, and per-draw material/texture data from buffers,
so the CPU submits almost nothing.

TIERED / WORKS-ON-ALL-GPUS: this is the *fast lane*. ModelLoader only uses it when
`GPUDrivenRenderer.detect_support()` says the context has the needed features
(MultiDrawIndirect, SSBO, and either bindless textures or — later — texture arrays).
On anything older/integrated it returns unsupported and ModelLoader keeps using its
universal instanced path, so the editor still runs everywhere.

BUILD STAGES (each independently checkable so nothing ships blind):
  1. consolidate_geometry()   — pack every mesh into shared vertex/index arrays +
     a per-mesh draw table (baseVertex/firstIndex/count). GPU-FREE, unit-tested
     in __main__ below.                                              ← THIS STAGE
  2. upload shared GL buffers; build the bindless texture-handle table (SSBO).
  3. per-frame: build the indirect draw-command buffer + per-instance transform/
     material SSBO for the visible set.
  4. the single glMultiDrawElementsIndirect + the GLSL 4.60 shaders.

Stage 1 is pure data-shaping: correctness here = "for every mesh, reading
shared_index[firstIndex : firstIndex+count] and adding baseVertex indexes exactly
the same vertices the original mesh did." That's what the self-test asserts.
"""

import numpy as np


# DrawElementsIndirectCommand is 5 x uint32 (std layout the GPU reads):
#   count, instanceCount, firstIndex, baseVertex, baseInstance
DRAW_CMD_DTYPE = np.dtype([
    ('count', np.uint32),
    ('instanceCount', np.uint32),
    ('firstIndex', np.uint32),
    ('baseVertex', np.uint32),    # uint here; GL treats the field as int — values are non-negative for us
    ('baseInstance', np.uint32),
])

# Per-material record, std430 layout (must match `struct Material` in the shader):
#   4 × uvec2 bindless handles (8 B each → 0,8,16,24) then 4 × vec4 (16 B → 32,48,64,80) = 96 B.
# numpy packs structured dtypes tightly (no padding), matching std430 here exactly.
MAT_DTYPE = np.dtype([
    ('hDiffuse',  np.uint32, 2),
    ('hNormal',   np.uint32, 2),
    ('hSpecular', np.uint32, 2),
    ('hEmission', np.uint32, 2),
    ('tint',     np.float32, 4),   # rgb, w = alpha_mode (0 opaque / 1 mask / 2 blend)
    ('emissive', np.float32, 4),   # rgb, w = alpha_cutoff
    ('specShin', np.float32, 4),   # rgb spec colour, w = shininess
    ('hasflags', np.float32, 4),   # has_diffuse, has_normal, has_specular, has_emission (0/1)
    ('anim',     np.float32, 4),   # anim_type, uspeed, vspeed, _  (animated-UV scroll)
])  # 112 B, std430


def _ver_ge(ver_str, major, minor):
    """Is the GL version string (e.g. '4.6.0 NVIDIA 595.79') >= major.minor?"""
    try:
        head = ver_str.strip().split()[0]
        a, b = head.split('.')[:2]
        return (int(a), int(b)) >= (major, minor)
    except Exception:
        return False


def detect_support():
    """Probe the CURRENT GL context and pick the rendering tier.

    Returns (mode, info_str):
        'bindless' — GL 4.3+ MDI + SSBO + ARB_bindless_texture (best; e.g. NVIDIA)
        'texarray' — GL 4.3+ MDI + SSBO, no bindless (AMD/Intel → texture arrays)
        None       — caller MUST use the universal PyOpenGL fallback path.

    Cheap + read-only; safe to call once after the context is current.
    """
    import OpenGL.GL as g
    try:
        ver = g.glGetString(g.GL_VERSION).decode(errors='replace')
    except Exception:
        return None, 'no GL context'
    exts = set()
    try:
        from OpenGL.GL import glGetStringi
        for k in range(int(g.glGetIntegerv(g.GL_NUM_EXTENSIONS))):
            exts.add(glGetStringi(g.GL_EXTENSIONS, k).decode(errors='replace'))
    except Exception:
        try:
            exts = set(g.glGetString(g.GL_EXTENSIONS).decode(errors='replace').split())
        except Exception:
            pass
    has_mdi = hasattr(g, 'glMultiDrawElementsIndirect') and \
        ('GL_ARB_multi_draw_indirect' in exts or _ver_ge(ver, 4, 3))
    has_ssbo = 'GL_ARB_shader_storage_buffer_object' in exts or _ver_ge(ver, 4, 3)
    if not (has_mdi and has_ssbo):
        return None, f'GL {ver}: no MDI/SSBO → fallback'
    if 'GL_ARB_bindless_texture' in exts:
        return 'bindless', f'GL {ver}: MDI + bindless'
    return 'texarray', f'GL {ver}: MDI, no bindless → texture arrays'


class MeshEntry:
    """One drawable sub-mesh located inside the shared buffers."""
    __slots__ = ('model_path', 'mesh_index', 'material_index',
                 'base_vertex', 'first_index', 'count',
                 'has_normals', 'has_uvs', 'has_tangents',
                 'global_mat_id', 'render_group')

    def __init__(self, model_path, mesh_index, material_index,
                 base_vertex, first_index, count,
                 has_normals, has_uvs, has_tangents):
        self.model_path = model_path
        self.mesh_index = mesh_index
        self.material_index = material_index
        self.base_vertex = base_vertex
        self.first_index = first_index
        self.count = count
        self.has_normals = has_normals
        self.has_uvs = has_uvs
        self.has_tangents = has_tangents
        self.global_mat_id = 0   # assigned during GPU build (material table index)
        self.render_group = 0    # 0=opaque cull, 1=opaque two-sided, 2=blend


def consolidate_geometry(models):
    """Pack every mesh of every model into single shared arrays for MultiDrawIndirect.

    Args:
        models: iterable of (model_path, model) where model.meshes have
                .vertices (N,3) / .normals / .uvs (N,2) / .tangents / .indices.

    Returns a dict:
        positions (V,3) f32, normals (V,3) f32, uvs (V,2) f32, tangents (V,3) f32,
        indices (I,) u32   — per-mesh-local indices (NOT globally offset; the draw
                             command's baseVertex relocates them, the MDI way),
        table  : list[MeshEntry] (one per drawable sub-mesh, in pack order),
        by_model : dict[model_path -> list[MeshEntry]] for per-frame command build.

    GPU-FREE — safe to run on a worker thread / unit-test without a context.
    """
    pos, nrm, uv, tan, idx = [], [], [], [], []
    table = []
    base_vertex = 0
    first_index = 0

    for model_path, model in models:
        for mi, mesh in enumerate(getattr(model, 'meshes', []) or []):
            verts = getattr(mesh, 'vertices', None)
            inds = getattr(mesh, 'indices', None)
            if verts is None or inds is None:
                continue
            v = np.ascontiguousarray(verts, dtype=np.float32).reshape(-1, 3)
            nv = v.shape[0]
            if nv == 0:
                continue
            ix = np.ascontiguousarray(inds, dtype=np.uint32).ravel()
            if ix.size == 0:
                continue

            has_n = getattr(mesh, 'normals', None) is not None
            has_u = getattr(mesh, 'uvs', None) is not None
            has_t = getattr(mesh, 'tangents', None) is not None

            pos.append(v)
            nrm.append(np.ascontiguousarray(mesh.normals, np.float32).reshape(-1, 3)
                       if has_n else np.zeros((nv, 3), np.float32))
            uv.append(np.ascontiguousarray(mesh.uvs, np.float32).reshape(-1, 2)
                      if has_u else np.zeros((nv, 2), np.float32))
            tan.append(np.ascontiguousarray(mesh.tangents, np.float32).reshape(-1, 3)
                       if has_t else np.zeros((nv, 3), np.float32))
            idx.append(ix)

            # material_index can be None (mesh with no assigned material) — coerce
            # to 0 so we never crash; the material-table lookup falls back to this
            # model's first material if (path, 0) isn't a real key.
            _mat_idx = getattr(mesh, 'material_index', 0)
            entry = MeshEntry(model_path, mi, int(_mat_idx) if _mat_idx is not None else 0,
                              base_vertex, first_index, int(ix.size),
                              has_n, has_u, has_t)
            table.append(entry)
            base_vertex += nv
            first_index += int(ix.size)

    def _cat(parts, cols, dt):
        return (np.concatenate(parts) if parts
                else np.zeros((0, cols), dt)).astype(dt, copy=False)

    by_model = {}
    for e in table:
        by_model.setdefault(e.model_path, []).append(e)

    return {
        'positions': _cat(pos, 3, np.float32),
        'normals':   _cat(nrm, 3, np.float32),
        'uvs':       _cat(uv, 2, np.float32),
        'tangents':  _cat(tan, 3, np.float32),
        'indices':   (np.concatenate(idx) if idx else np.zeros((0,), np.uint32)).astype(np.uint32, copy=False),
        'table':     table,
        'by_model':  by_model,
        'vertex_count': base_vertex,
        'index_count':  first_index,
    }


# ───────────────────── vectorised frame assembly (GPU-free) ─────────────────────
# These three functions are the per-frame hot path of the GPU-driven renderer in
# array mode. They are pure numpy (no GL) so they can be unit-tested without a
# context — tests/test_gdr_frame_assembly.py asserts they match a naive loop.

def assemble_frame(row_ent, row_slot, row_rot, row_scale, row_overlay,
                   positions, ent_visible_mask, n_slots):
    """Build the per-frame instance array + per-model-slot counts/offsets.

    Rows are the static (entity, model-slot) pairs built once per level (one row
    per model an entity contributes — kit parts add extra rows). Per frame we
    mask rows by entity visibility, group them by model slot, and gather the
    instance data with numpy fancy indexing — zero Python-level per-entity work.

    Args:
        row_ent     (R,)  int32  — index into the canvas's _valid_entities_3d
        row_slot    (R,)  int32  — model slot id (dense, 0..n_slots-1)
        row_rot     (R,3) f32    — rotation per row
        row_scale   (R,)  f32    — scale per row
        row_overlay (R,)  f32    — selection overlay per row (0 or 0.35)
        positions   (N,3) f32    — GL-space entity positions (canvas _positions_3d)
        ent_visible_mask (N,) bool — entity visibility from the frustum cull
        n_slots     int          — number of model slots

    Returns (inst (M,8) f32 contiguous, counts (n_slots,) i64, offsets (n_slots,) i64)
    where inst rows are grouped by model slot in slot order:
    [pos.xyz, scale, rot.xyz, overlay] — matching the shader's Inst struct.
    """
    row_mask = ent_visible_mask[row_ent]
    rows = np.nonzero(row_mask)[0]
    counts = np.bincount(row_slot[rows], minlength=n_slots).astype(np.int64)
    offsets = np.zeros(n_slots, np.int64)
    if n_slots > 1:
        np.cumsum(counts[:-1], out=offsets[1:])
    if rows.size == 0:
        return np.zeros((0, 8), np.float32), counts, offsets
    order = np.argsort(row_slot[rows], kind='stable')
    rs = rows[order]
    inst = np.empty((rs.size, 8), np.float32)
    inst[:, 0:3] = positions[row_ent[rs]]
    inst[:, 3] = row_scale[rs]
    inst[:, 4:7] = row_rot[rs]
    inst[:, 7] = row_overlay[rs]
    return np.ascontiguousarray(inst), counts, offsets


def build_group_templates(table, slot_of_path):
    """Static per-render-group command templates, built once per geometry build.

    For each render group (0 opaque / 1 two-sided / 2 blend) packs the constant
    columns of every mesh's draw command (count/firstIndex/baseVertex/matId) plus
    the model slot each command instances from. Meshes whose model_path has no
    slot (model not in the entity row tables) are dropped — they can never have
    instances in array mode.
    """
    out = []
    for grp in (0, 1, 2):
        ents = [e for e in table
                if e.render_group == grp and slot_of_path.get(e.model_path, -1) >= 0]
        out.append({
            'count': np.array([e.count for e in ents], np.uint32),
            'first': np.array([e.first_index for e in ents], np.uint32),
            'basev': np.array([e.base_vertex for e in ents], np.uint32),
            'mat':   np.array([e.global_mat_id for e in ents], np.uint32),
            'slot':  np.array([slot_of_path[e.model_path] for e in ents], np.int64),
        })
    return out


def build_group_commands(tmpl, counts, offsets):
    """Per-frame indirect command buffer for one render group — pure numpy.

    Selects the template rows whose model slot has visible instances and fills
    instanceCount/baseInstance from the frame's counts/offsets. Replaces the old
    per-mesh Python loop + per-row structured-array fill (the second-biggest
    CPU cost of the GPU-driven frame after prepare_batches).

    Returns (cmd_arr structured DRAW_CMD_DTYPE, drawmat uint32 array).
    """
    slot = tmpl['slot']
    ic = counts[slot] if slot.size else np.zeros(0, np.int64)
    act = ic > 0
    n = int(act.sum())
    cmd = np.empty(n, dtype=DRAW_CMD_DTYPE)
    if n:
        cmd['count'] = tmpl['count'][act]
        cmd['instanceCount'] = ic[act]
        cmd['firstIndex'] = tmpl['first'][act]
        cmd['baseVertex'] = tmpl['basev'][act]
        cmd['baseInstance'] = offsets[slot][act]
    return cmd, (tmpl['mat'][act] if n else np.zeros(0, np.uint32))


_GDR_VERT = """
#version 460 compatibility
layout(location=0) in vec3 a_position;
layout(location=1) in vec3 a_normal;
layout(location=2) in vec2 a_uv;
layout(location=3) in vec3 a_tangent;
struct Inst { vec4 posScale; vec4 rotOverlay; };   // xyz=pos w=scale ; xyz=rot w=overlay
layout(std430, binding=0) readonly buffer Instances { Inst insts[]; };
layout(std430, binding=1) readonly buffer DrawMat  { uint drawMat[]; };  // per-draw material id (gl_DrawID)
out vec3 v_posES;
out vec3 v_normalES;
out vec3 v_tangentES;
out vec2 v_uv;
out float v_overlay;
out vec3 v_wp;
flat out uint v_mat;
invariant gl_Position;   // bit-identical depth vs the depth-prepass program (early-Z)
vec3 rotX(vec3 p,float d){float a=radians(d),c=cos(a),s=sin(a);return vec3(p.x,c*p.y-s*p.z,s*p.y+c*p.z);}
vec3 rotY(vec3 p,float d){float a=radians(d),c=cos(a),s=sin(a);return vec3(c*p.x+s*p.z,p.y,-s*p.x+c*p.z);}
vec3 rotZ(vec3 p,float d){float a=radians(d),c=cos(a),s=sin(a);return vec3(c*p.x-s*p.y,s*p.x+c*p.y,p.z);}
vec3 modelRot(vec3 p, vec3 r){ p=rotY(p,r.y); p=rotX(p,r.x); p=rotZ(p,-r.z); p=rotX(p,-90.0); return p; }
void main(){
    Inst I = insts[gl_BaseInstance + gl_InstanceID];
    vec3 wp = modelRot(a_position * I.posScale.w, I.rotOverlay.xyz) + I.posScale.xyz;
    v_wp        = wp;
    v_posES     = vec3(gl_ModelViewMatrix * vec4(wp, 1.0));
    v_normalES  = gl_NormalMatrix * modelRot(a_normal,  I.rotOverlay.xyz);
    v_tangentES = gl_NormalMatrix * modelRot(a_tangent, I.rotOverlay.xyz);
    v_uv        = a_uv;
    v_overlay   = I.rotOverlay.w;
    v_mat       = drawMat[gl_DrawID];
    gl_Position = gl_ModelViewProjectionMatrix * vec4(wp, 1.0);
}
"""

_GDR_FRAG = """
#version 460 compatibility
#extension GL_ARB_bindless_texture : require
struct Material {
    uvec2 hDiffuse; uvec2 hNormal; uvec2 hSpecular; uvec2 hEmission;
    vec4 tint;      // rgb, w = alpha_mode (0/1/2)
    vec4 emissive;  // rgb, w = alpha_cutoff
    vec4 specShin;  // rgb spec, w = shininess
    vec4 hasflags;  // has_diffuse, has_normal, has_specular, has_emission
    vec4 anim;      // anim_type, uspeed, vspeed, _
};
layout(std430, binding=2) readonly buffer Materials { Material mats[]; };
uniform float u_time;    // seconds, for animated-UV scroll
uniform float u_night;   // bioluminescence: emission scaled by this (1=day/off, night→glow)
uniform int   u_flip_green;   // debug: 1 = flip normal-map green (Y)
uniform int   u_flip_normal;  // debug: 1 = flip base geometry normal
uniform int   u_shadows_on;   // 1 = sample the sun shadow map
uniform mat4  u_light_vp;     // world -> sun light clip space
uniform sampler2D u_shadow_tex;
in vec3 v_posES;
in vec3 v_normalES;
in vec3 v_tangentES;
in vec2 v_uv;
in float v_overlay;
in vec3 v_wp;
flat in uint v_mat;

// 0 = fully shadowed, 1 = fully lit. PCF 3x3 with slope-scaled bias.
float sunVisibility(vec3 N, vec3 L) {
    if (u_shadows_on == 0) return 1.0;
    vec4 lc = u_light_vp * vec4(v_wp, 1.0);
    vec3 p = lc.xyz / lc.w * 0.5 + 0.5;
    if (p.z > 1.0 || p.x < 0.0 || p.x > 1.0 || p.y < 0.0 || p.y > 1.0) return 1.0;
    float bias = max(0.0030 * (1.0 - dot(N, L)), 0.0010);
    vec2 tx = 1.0 / vec2(textureSize(u_shadow_tex, 0));
    float s = 0.0;
    for (int x = -1; x <= 1; x++)
      for (int y = -1; y <= 1; y++)
        s += (p.z - bias > texture(u_shadow_tex, p.xy + vec2(x, y) * tx).r) ? 0.0 : 1.0;
    return s / 9.0;
}
void main(){
    Material m = mats[v_mat];
    // Animated UV (Unlit/FX scroll), matching the universal shader's u_uv_offset.
    float at = m.anim.x, us = m.anim.y, vs = m.anim.z;
    vec2 uvoff = vec2(0.0);
    if (at == 3.0)                         uvoff = vec2(cos(u_time) * us, sin(u_time) * vs);
    else if (at != 0.0 || us != 0.0 || vs != 0.0) uvoff = vec2(us * u_time, vs * u_time);
    vec2 uv = v_uv + uvoff;

    vec4 diff = (m.hasflags.x > 0.5) ? texture(sampler2D(m.hDiffuse), uv) : vec4(1.0);
    float alpha = diff.a;
    if (int(m.tint.w) == 1 && alpha < m.emissive.w) discard;   // alpha-mask
    vec3 base = diff.rgb * m.tint.rgb;

    vec3 N = normalize(v_normalES);
    if (u_flip_normal == 1) N = -N;
    if (m.hasflags.y > 0.5) {
        // TBN from screen-space derivatives (Schüler) — handedness automatic,
        // no mirrored-UV inversion, no precomputed-tangent dependency.
        vec3 dp1 = dFdx(v_posES), dp2 = dFdy(v_posES);
        vec2 du1 = dFdx(uv),      du2 = dFdy(uv);
        vec3 dp2p = cross(dp2, N), dp1p = cross(N, dp1);
        vec3 T = dp2p * du1.x + dp1p * du2.x;
        vec3 B = dp2p * du1.y + dp1p * du2.y;
        float im = inversesqrt(max(dot(T, T), dot(B, B)));
        vec3 nTS = texture(sampler2D(m.hNormal), uv).rgb * 2.0 - 1.0;
        if (u_flip_green == 1) nTS.y = -nTS.y;
        N = normalize(mat3(T * im, B * im, N) * nTS);
    }
    vec3 V = normalize(-v_posES);
    if (dot(N, V) < 0.0) N = -N;

    vec3 specMap = (m.hasflags.z > 0.5) ? texture(sampler2D(m.hSpecular), uv).rgb : vec3(1.0);
    vec3 color = gl_LightModel.ambient.rgb * base;
    for (int i = 0; i < 2; i++) {
        vec4 lp = gl_LightSource[i].position;
        vec3 L = normalize(lp.xyz - v_posES * lp.w);
        float ndl = max(dot(N, L), 0.0);
        float vis = (i == 0) ? sunVisibility(N, L) : 1.0;   // only the sun (light 0) casts
        color += base * gl_LightSource[i].diffuse.rgb * ndl * vis;
        if (ndl > 0.0) {
            vec3 H = normalize(L + V);
            float s = pow(max(dot(N, H), 0.0), max(m.specShin.w, 1.0));
            color += gl_LightSource[i].specular.rgb * m.specShin.rgb * specMap * s * vis;
        }
    }
    if (m.hasflags.w > 0.5) color += texture(sampler2D(m.hEmission), uv).rgb * m.emissive.rgb * u_night;

    color = mix(color, vec3(0.35, 0.50, 1.0), v_overlay);
    float outA = (int(m.tint.w) == 2) ? alpha : 1.0;   // blend materials keep diffuse alpha
    gl_FragColor = vec4(color, outA);
}
"""


# Depth-only cast program: same instance transform as the main vertex shader
# (modelRot MUST stay identical so cast geometry aligns with rendered geometry),
# projected by the sun's light_vp. No material, empty fragment.
_GDR_DEPTH_VS = """
#version 460 compatibility
layout(location=0) in vec3 a_position;
struct Inst { vec4 posScale; vec4 rotOverlay; };
layout(std430, binding=0) readonly buffer Instances { Inst insts[]; };
uniform mat4 u_light_vp;
vec3 rotX(vec3 p,float d){float a=radians(d),c=cos(a),s=sin(a);return vec3(p.x,c*p.y-s*p.z,s*p.y+c*p.z);}
vec3 rotY(vec3 p,float d){float a=radians(d),c=cos(a),s=sin(a);return vec3(c*p.x+s*p.z,p.y,-s*p.x+c*p.z);}
vec3 rotZ(vec3 p,float d){float a=radians(d),c=cos(a),s=sin(a);return vec3(c*p.x-s*p.y,s*p.x+c*p.y,p.z);}
vec3 modelRot(vec3 p, vec3 r){ p=rotY(p,r.y); p=rotX(p,r.x); p=rotZ(p,-r.z); p=rotX(p,-90.0); return p; }
void main(){
    Inst I = insts[gl_BaseInstance + gl_InstanceID];
    vec3 wp = modelRot(a_position * I.posScale.w, I.rotOverlay.xyz) + I.posScale.xyz;
    gl_Position = u_light_vp * vec4(wp, 1.0);
}
"""
_GDR_DEPTH_FS = """
#version 460 compatibility
void main(){ }
"""

# Camera-space depth-prepass program (early-Z occlusion). Same transform as the
# main vertex shader but projected by the CAMERA matrix; `invariant gl_Position`
# guarantees its depth is bit-identical so the color pass can run GL_LEQUAL with
# depth writes off. A full depth prepass lays the nearest depth for every pixel,
# so fragments of objects hidden behind a wall are early-Z-rejected before the
# (expensive) material shader runs — regardless of MDI draw order.
_GDR_CAMDEPTH_VS = """
#version 460 compatibility
layout(location=0) in vec3 a_position;
layout(location=2) in vec2 a_uv;
struct Inst { vec4 posScale; vec4 rotOverlay; };
layout(std430, binding=0) readonly buffer Instances { Inst insts[]; };
layout(std430, binding=1) readonly buffer DrawMat  { uint drawMat[]; };
out vec2 v_uv;
flat out uint v_mat;
vec3 rotX(vec3 p,float d){float a=radians(d),c=cos(a),s=sin(a);return vec3(p.x,c*p.y-s*p.z,s*p.y+c*p.z);}
vec3 rotY(vec3 p,float d){float a=radians(d),c=cos(a),s=sin(a);return vec3(c*p.x+s*p.z,p.y,-s*p.x+c*p.z);}
vec3 rotZ(vec3 p,float d){float a=radians(d),c=cos(a),s=sin(a);return vec3(c*p.x-s*p.y,s*p.x+c*p.y,p.z);}
vec3 modelRot(vec3 p, vec3 r){ p=rotY(p,r.y); p=rotX(p,r.x); p=rotZ(p,-r.z); p=rotX(p,-90.0); return p; }
invariant gl_Position;
void main(){
    Inst I = insts[gl_BaseInstance + gl_InstanceID];
    vec3 wp = modelRot(a_position * I.posScale.w, I.rotOverlay.xyz) + I.posScale.xyz;
    v_uv  = a_uv;
    v_mat = drawMat[gl_DrawID];
    gl_Position = gl_ModelViewProjectionMatrix * vec4(wp, 1.0);
}
"""
# Prepass fragment: alpha-test masked materials with the SAME cutoff as the color
# pass, so cutout holes (foliage/grates) don't write depth — otherwise objects
# behind the holes would be wrongly early-Z-rejected. Opaque materials just write.
_GDR_CAMDEPTH_FS = """
#version 460 compatibility
#extension GL_ARB_bindless_texture : require
struct Material {
    uvec2 hDiffuse; uvec2 hNormal; uvec2 hSpecular; uvec2 hEmission;
    vec4 tint; vec4 emissive; vec4 specShin; vec4 hasflags; vec4 anim;
};
layout(std430, binding=2) readonly buffer Materials { Material mats[]; };
in vec2 v_uv;
flat in uint v_mat;
void main(){
    Material m = mats[v_mat];
    if (int(m.tint.w) == 1 && m.hasflags.x > 0.5) {          // alpha-masked
        if (texture(sampler2D(m.hDiffuse), v_uv).a < m.emissive.w) discard;
    }
}
"""


class GPUDrivenRenderer:
    """One glMultiDrawElementsIndirect for ALL opaque model instances.

    v1 = flat-lit (no textures) on purpose: it validates the hard core
    (consolidated buffers + indirect draw + per-instance transform via SSBO,
    indexed by gl_BaseInstance+gl_InstanceID) on real hardware BEFORE bindless/
    texture-array material handling is added. Lives behind ModelLoader's
    force_render_tier toggle (F2/F3); the universal path stays the fallback.
    """

    def __init__(self, model_loader):
        self.ml = model_loader
        self._built = False
        self._failed = False
        self._build_key = None
        self.program = 0
        self.depth_program = 0      # depth-only cast program for shadow mapping
        self.camdepth_program = 0   # camera-space depth-prepass program (early-Z occlusion)
        self._frame = None       # cached per-frame (insts, gcmds, gmat) shared by cast+draw
        self.vao = 0
        self.bufs = []           # all GL buffer ids to free
        self.inst_ssbo = 0
        self.cmd_buf = 0
        self.mat_ssbo = 0        # material table (bindless handles + params), built once
        self.drawmat_buf = 0     # per-draw material id (indexed by gl_DrawID), per frame
        self.by_model = {}
        self._resident = set()   # bindless handles we've made resident
        self.u_time_loc = -1     # u_time uniform location (animated UV)
        self.u_night_loc = -1    # u_night uniform location (bioluminescence)
        self._uloc = {}          # cached uniform locations for the main program
        self._table = None       # MeshEntry list from the last geometry build
        self.group_templates = None      # static per-group command templates (array mode)
        self._tmpl_slots_version = None  # ml._gdr_slots_version the templates were built for

    def _gl(self):
        import OpenGL.GL as g
        return g

    def render(self, anim_t, shadow_tex=0, light_vp=None, shadows_on=False):
        """Returns True if it drew (caller skips the fallback), False to fall back."""
        if self._failed:
            return False
        try:
            if not self._ensure_built():
                self._failed = True
                return False
            return self._draw(anim_t, shadow_tex, light_vp, shadows_on)
        except Exception as e:
            import traceback
            print(f"[gpu-driven] runtime error -> fallback: {e}")
            traceback.print_exc()
            self._failed = True
            try:
                self._gl().glUseProgram(0); self._gl().glBindVertexArray(0)
            except Exception:
                pass
            return False

    def _ensure_built(self):
        ml = self.ml
        # Rebuild if the set of loaded models changed (e.g. a new level).
        key = len(ml.models_cache)
        if self._built and key == self._build_key:
            return True
        g = self._gl()
        import ctypes
        if self.program == 0:
            self.program = _compile_program(g, _GDR_VERT, _GDR_FRAG)
            if not self.program:
                return False
            self.u_time_loc = g.glGetUniformLocation(self.program, b'u_time')
            self.u_night_loc = g.glGetUniformLocation(self.program, b'u_night')
            # Cache the rest once — glGetUniformLocation per frame is wasted CPU.
            self._uloc = {n: g.glGetUniformLocation(self.program, n) for n in
                          (b'u_flip_green', b'u_flip_normal', b'u_shadows_on',
                           b'u_light_vp', b'u_shadow_tex')}
        if self.depth_program == 0:
            # Non-fatal: if it fails, cast() no-ops and the scene renders unshadowed.
            self.depth_program = _compile_program(g, _GDR_DEPTH_VS, _GDR_DEPTH_FS)
        if self.camdepth_program == 0:
            # Non-fatal: if it fails, the depth prepass is skipped (color pass still draws).
            self.camdepth_program = _compile_program(g, _GDR_CAMDEPTH_VS, _GDR_CAMDEPTH_FS)
        # (Re)consolidate geometry from currently-loaded models.
        self._free_buffers(g)
        models = [(p, m) for p, m in ml.models_cache.items() if getattr(m, 'loaded', False)]
        geo = consolidate_geometry(models)
        self.by_model = geo['by_model']
        self._table = geo['table']
        self.group_templates = None      # geometry changed → rebuild templates lazily
        self._tmpl_slots_version = None
        if geo['index_count'] == 0:
            return False

        def _vbo(arr):
            b = int(g.glGenBuffers(1)); self.bufs.append(b)
            g.glBindBuffer(g.GL_ARRAY_BUFFER, b)
            a = np.ascontiguousarray(arr, np.float32)
            g.glBufferData(g.GL_ARRAY_BUFFER, a.nbytes, a, g.GL_STATIC_DRAW)
            return b
        pos = _vbo(geo['positions']); nrm = _vbo(geo['normals'])
        uvb = _vbo(geo['uvs']); tanb = _vbo(geo['tangents'])
        idx = np.ascontiguousarray(geo['indices'], np.uint32)
        ibo = int(g.glGenBuffers(1)); self.bufs.append(ibo)
        g.glBindBuffer(g.GL_ELEMENT_ARRAY_BUFFER, ibo)
        g.glBufferData(g.GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx, g.GL_STATIC_DRAW)

        self.vao = int(g.glGenVertexArrays(1))
        g.glBindVertexArray(self.vao)
        _z = ctypes.c_void_p(0)
        for loc, buf, comps in ((0, pos, 3), (1, nrm, 3), (2, uvb, 2), (3, tanb, 3)):
            g.glBindBuffer(g.GL_ARRAY_BUFFER, buf)
            g.glEnableVertexAttribArray(loc)
            g.glVertexAttribPointer(loc, comps, g.GL_FLOAT, g.GL_FALSE, 0, _z)
        g.glBindBuffer(g.GL_ELEMENT_ARRAY_BUFFER, ibo)
        g.glBindVertexArray(0)
        g.glBindBuffer(g.GL_ARRAY_BUFFER, 0)

        # Material table: bindless texture handles + params, one per (model, material).
        if not self._build_material_table(g, geo['table'], dict(models)):
            return False

        if self.inst_ssbo == 0:
            self.inst_ssbo = int(g.glGenBuffers(1))
        if self.cmd_buf == 0:
            self.cmd_buf = int(g.glGenBuffers(1))
        if self.drawmat_buf == 0:
            self.drawmat_buf = int(g.glGenBuffers(1))
        self._built = True
        self._build_key = key
        print(f"[gpu-driven] built: {len(geo['table'])} meshes, "
              f"{geo['vertex_count']} verts, {geo['index_count']} indices")
        return True

    def _build_material_table(self, g, table, models_by_path):
        """Make every material's textures bindless-resident and pack a Material[]
        SSBO; assign each MeshEntry its global material id. NVIDIA bindless path."""
        try:
            from OpenGL.GL import glGetTextureHandleARB, glMakeTextureHandleResidentARB
        except Exception:
            try:
                from OpenGL.GL.ARB.bindless_texture import (
                    glGetTextureHandleARB, glMakeTextureHandleResidentARB)
            except Exception as e:
                print(f"[gpu-driven] bindless funcs unavailable ({e}) — cannot texture (needs texarray path)")
                return False

        def handle(texid):
            if not texid:
                return (0, 0), 0.0
            h = int(glGetTextureHandleARB(int(texid)))
            if h == 0:
                return (0, 0), 0.0
            if h not in self._resident:
                glMakeTextureHandleResidentARB(h)
                self._resident.add(h)
            return (h & 0xFFFFFFFF, (h >> 32) & 0xFFFFFFFF), 1.0

        key_to_id = {}
        key_to_group = {}
        records = []
        for path, model in models_by_path.items():
            mt = getattr(model, 'mat_textures', None) or {}
            mp = getattr(model, 'mat_params', None) or {}
            for mat_idx, slots in mt.items():
                p = mp.get(mat_idx, {})
                hd, fd = handle(slots.get('diffuse'))
                hn, fn = handle(slots.get('normal'))
                hs, fs = handle(slots.get('specular'))
                he, fe = handle(slots.get('emission'))
                tint = p.get('tint', [1.0, 1.0, 1.0])
                emis = p.get('emissive', [0.0, 0.0, 0.0])
                spec = p.get('spec_color', [0.3, 0.3, 0.3])
                alpha_mode = int(p.get('alpha_mode', 0))
                two_sided = bool(p.get('two_sided', False))
                rec = np.zeros(1, dtype=MAT_DTYPE)
                rec['hDiffuse'] = hd; rec['hNormal'] = hn
                rec['hSpecular'] = hs; rec['hEmission'] = he
                rec['tint'] = (tint[0], tint[1], tint[2], float(alpha_mode))
                rec['emissive'] = (emis[0], emis[1], emis[2], float(p.get('alpha_cutoff', 0.5)))
                rec['specShin'] = (spec[0], spec[1], spec[2], float(p.get('shininess', 32.0)))
                rec['hasflags'] = (fd, fn, fs, fe)
                rec['anim'] = (float(p.get('anim_type', 0)), float(p.get('uspeed', 0.0)),
                               float(p.get('vspeed', 0.0)), 0.0)
                # render group: 2=blend, else 1 if two-sided (foliage/grates), else 0.
                group = 2 if alpha_mode == 2 else (1 if two_sided else 0)
                key_to_id[(path, mat_idx)] = len(records)
                key_to_group[(path, mat_idx)] = group
                records.append(rec)
        if not records:
            return False
        mat_arr = np.concatenate(records)
        # First material id per model — fallback for meshes whose material_index
        # is missing/None (coerced to 0 in consolidate), so they borrow THIS
        # model's first material rather than some other model's global #0.
        model_first_id = {}
        model_first_grp = {}
        for (path, midx), gid in key_to_id.items():
            model_first_id.setdefault(path, gid)
            model_first_grp.setdefault(path, key_to_group[(path, midx)])
        ngrp = [0, 0, 0]
        for e in table:
            gid = key_to_id.get((e.model_path, e.material_index))
            if gid is None:
                gid = model_first_id.get(e.model_path, 0)
            grp = key_to_group.get((e.model_path, e.material_index))
            if grp is None:
                grp = model_first_grp.get(e.model_path, 0)
            e.global_mat_id = gid
            e.render_group = grp
            ngrp[e.render_group] += 1
        print(f"[gpu-driven] render groups: {ngrp[0]} opaque, {ngrp[1]} two-sided, {ngrp[2]} blend")

        if self.mat_ssbo == 0:
            self.mat_ssbo = int(g.glGenBuffers(1))
        g.glBindBuffer(g.GL_SHADER_STORAGE_BUFFER, self.mat_ssbo)
        g.glBufferData(g.GL_SHADER_STORAGE_BUFFER, mat_arr.nbytes, mat_arr, g.GL_STATIC_DRAW)
        g.glBindBuffer(g.GL_SHADER_STORAGE_BUFFER, 0)
        print(f"[gpu-driven] material table: {len(records)} materials, "
              f"{len(self._resident)} bindless textures resident")
        return True

    def _collect_frame(self):
        """Build this frame's instance array + per-render-group command/material
        lists from the frustum-culled visible batches. Shared by cast() + _draw()
        so they use the IDENTICAL instance layout (shadow aligns with rendered geo).
        Returns (inst_arr, gcmds, gmat) or None if nothing is visible.
          group 0 = opaque single-sided ; 1 = opaque two-sided ; 2 = blend"""
        ml = self.ml
        insts = []
        gcmds = ([], [], [])
        gmat = ([], [], [])
        for model_path, instances in ml.instance_batches.items():
            if not instances:
                continue
            entries = self.by_model.get(model_path)
            if not entries:
                continue
            base_instance = len(insts)
            for it in instances:
                insts.append((it[1], it[2], it[3], it[7],          # pos.xyz, scale
                              it[4], it[5], it[6], 0.35 if it[8] else 0.0))  # rot.xyz, overlay
            n = len(instances)
            for e in entries:
                grp = e.render_group
                gcmds[grp].append((e.count, n, e.first_index, e.base_vertex, base_instance))
                gmat[grp].append(e.global_mat_id)
        if not (gcmds[0] or gcmds[1] or gcmds[2]):
            return None
        return (np.asarray(insts, np.float32), gcmds, gmat)

    def _upload_instances(self, g, inst_arr):
        g.glBindBuffer(g.GL_SHADER_STORAGE_BUFFER, self.inst_ssbo)         # binding 0: transforms
        g.glBufferData(g.GL_SHADER_STORAGE_BUFFER, inst_arr.nbytes, inst_arr, g.GL_DYNAMIC_DRAW)
        g.glBindBufferBase(g.GL_SHADER_STORAGE_BUFFER, 0, self.inst_ssbo)

    def _rebuild_templates(self):
        """(Re)build the static per-group command templates against the model
        loader's current slot mapping. Cheap Python loop over the mesh table —
        runs only when geometry or the slot list actually changes, never per frame."""
        paths = getattr(self.ml, '_gdr_model_paths', None)
        if not paths or self._table is None:
            self.group_templates = None
            return
        slot_of = {p: i for i, p in enumerate(paths)}
        self.group_templates = build_group_templates(self._table, slot_of)
        self._tmpl_slots_version = getattr(self.ml, '_gdr_slots_version', None)

    def _build_frame(self):
        """Unified per-frame data: (inst_arr, [(cmd_arr, drawmat_arr) × 3 groups]).

        FAST PATH (array mode): the model loader's prepare_gpu_frame() left
        {inst, counts, offsets} in ml._gdr_frame — derive the command buffers
        with pure numpy (build_group_commands), no per-mesh Python loop.

        LEGACY PATH: fall back to _collect_frame()'s per-instance walk over
        instance_batches (used when prepare_batches ran instead — e.g. picking
        rebuilds, or array assembly unavailable).
        Returns None if nothing is visible."""
        fr = getattr(self.ml, '_gdr_frame', None)
        if fr is not None:
            if (self.group_templates is None
                    or self._tmpl_slots_version != getattr(self.ml, '_gdr_slots_version', None)):
                self._rebuild_templates()
            if self.group_templates is not None:
                counts, offsets = fr['counts'], fr['offsets']
                groups = [build_group_commands(self.group_templates[grp], counts, offsets)
                          for grp in (0, 1, 2)]
                if not any(len(c) for c, _ in groups):
                    return None
                return (fr['inst'], groups)
        legacy = self._collect_frame()
        if legacy is None:
            return None
        inst_arr, gcmds, gmat = legacy
        groups = []
        for grp in (0, 1, 2):
            cmds = gcmds[grp]
            cmd_arr = np.zeros(len(cmds), dtype=DRAW_CMD_DTYPE)
            for i, c in enumerate(cmds):
                cmd_arr[i] = c
            groups.append((cmd_arr, np.asarray(gmat[grp], np.uint32)))
        return (inst_arr, groups)

    def cast(self, light_vp):
        """Depth-only MDI of opaque + two-sided groups into the currently-bound
        shadow FBO (caller binds it via ShadowMap.begin()). Caches the frame so
        the following render() reuses the same instance layout. True if it drew."""
        if self._failed or not self.depth_program:
            return False
        try:
            if not self._ensure_built():
                return False
            g = self._gl()
            import ctypes
            frame = self._build_frame()
            self._frame = frame
            if frame is None:
                return False
            inst_arr, groups = frame
            g.glUseProgram(self.depth_program)
            g.glUniformMatrix4fv(g.glGetUniformLocation(self.depth_program, b'u_light_vp'),
                                 1, g.GL_TRUE, np.ascontiguousarray(light_vp, np.float32))
            g.glBindVertexArray(self.vao)
            self._upload_instances(g, inst_arr)
            g.glEnable(g.GL_DEPTH_TEST); g.glDepthMask(g.GL_TRUE); g.glDepthFunc(g.GL_LESS)
            g.glDisable(g.GL_BLEND); g.glDisable(g.GL_CULL_FACE)   # two-sided foliage casts too
            for grp in (0, 1):                                    # skip 2 (transparent/FX)
                cmd_arr, _dm = groups[grp]
                if not len(cmd_arr):
                    continue
                g.glBindBuffer(g.GL_DRAW_INDIRECT_BUFFER, self.cmd_buf)
                g.glBufferData(g.GL_DRAW_INDIRECT_BUFFER, cmd_arr.nbytes, cmd_arr, g.GL_DYNAMIC_DRAW)
                g.glMultiDrawElementsIndirect(g.GL_TRIANGLES, g.GL_UNSIGNED_INT,
                                              ctypes.c_void_p(0), len(cmd_arr), 0)
            g.glBindBuffer(g.GL_DRAW_INDIRECT_BUFFER, 0)
            g.glBindBuffer(g.GL_SHADER_STORAGE_BUFFER, 0)
            g.glBindVertexArray(0); g.glUseProgram(0)
            return True
        except Exception as e:
            print(f"[gpu-driven] shadow cast failed: {e}")
            self._frame = None
            return False

    def _draw(self, anim_t=0.0, shadow_tex=0, light_vp=None, shadows_on=False):
        g = self._gl()
        import ctypes
        # Reuse the frame cast() just built (identical instance layout); else build.
        #   group 0 = opaque, single-sided   → cull back, depth write, no blend
        #   group 1 = opaque, two-sided       → no cull,  depth write, no blend
        #   group 2 = blend (glass/FX)        → no cull,  depth test only, blend, after opaque
        frame = self._frame if self._frame is not None else self._build_frame()
        self._frame = None
        if frame is None:
            return True
        inst_arr, groups = frame

        g.glUseProgram(self.program)
        if self.u_time_loc != -1:
            g.glUniform1f(self.u_time_loc, float(anim_t))   # animated-UV scroll
        if self.u_night_loc != -1:
            g.glUniform1f(self.u_night_loc, float(getattr(self.ml, 'night_factor', 1.0)))
        g.glUniform1i(self._uloc[b'u_flip_green'],
                      1 if getattr(self.ml, 'dbg_flip_green', False) else 0)
        g.glUniform1i(self._uloc[b'u_flip_normal'],
                      1 if getattr(self.ml, 'dbg_flip_normal', False) else 0)
        # Shadow receive (sun = light 0 only). Depth map → unit 4; material
        # textures are bindless so there's no texture-unit conflict.
        use_shadow = 1 if (shadows_on and shadow_tex and light_vp is not None) else 0
        g.glUniform1i(self._uloc[b'u_shadows_on'], use_shadow)
        if use_shadow:
            g.glUniformMatrix4fv(self._uloc[b'u_light_vp'],
                                 1, g.GL_TRUE, np.ascontiguousarray(light_vp, np.float32))
            g.glActiveTexture(g.GL_TEXTURE4)
            g.glBindTexture(g.GL_TEXTURE_2D, int(shadow_tex))
            g.glUniform1i(self._uloc[b'u_shadow_tex'], 4)
            g.glActiveTexture(g.GL_TEXTURE0)
        g.glBindVertexArray(self.vao)
        self._upload_instances(g, inst_arr)
        g.glBindBufferBase(g.GL_SHADER_STORAGE_BUFFER, 2, self.mat_ssbo)   # binding 2: material table
        g.glEnable(g.GL_DEPTH_TEST)
        g.glFrontFace(g.GL_CW); g.glCullFace(g.GL_BACK)

        def _pass(grp):
            cmd_arr, dm = groups[grp]
            if not len(cmd_arr):
                return
            # binding 1: per-draw material id, indexed by gl_DrawID (per MDI call).
            g.glBindBuffer(g.GL_SHADER_STORAGE_BUFFER, self.drawmat_buf)
            g.glBufferData(g.GL_SHADER_STORAGE_BUFFER, dm.nbytes, dm, g.GL_DYNAMIC_DRAW)
            g.glBindBufferBase(g.GL_SHADER_STORAGE_BUFFER, 1, self.drawmat_buf)
            g.glBindBuffer(g.GL_DRAW_INDIRECT_BUFFER, self.cmd_buf)
            g.glBufferData(g.GL_DRAW_INDIRECT_BUFFER, cmd_arr.nbytes, cmd_arr, g.GL_DYNAMIC_DRAW)
            g.glMultiDrawElementsIndirect(g.GL_TRIANGLES, g.GL_UNSIGNED_INT,
                                          ctypes.c_void_p(0), len(cmd_arr), 0)

        # ── Depth prepass (early-Z occlusion, F8) ──
        # Lay the nearest depth for every opaque/two-sided pixel FIRST so the
        # color pass shades only visible fragments — objects hidden behind a wall
        # get early-Z-rejected before the (expensive) material shader, regardless
        # of MDI draw order. Skipped if its program failed or the toggle is off.
        prepass = bool(self.camdepth_program
                       and getattr(self.ml, 'gpu_depth_prepass', True)
                       and (len(groups[0][0]) or len(groups[1][0])))
        if prepass:
            # _pass() binds the per-draw material ids (binding 1) the prepass FS
            # needs for its alpha test; the camdepth program reads bindings 0/1/2.
            g.glUseProgram(self.camdepth_program)
            g.glColorMask(g.GL_FALSE, g.GL_FALSE, g.GL_FALSE, g.GL_FALSE)
            g.glDepthMask(g.GL_TRUE); g.glDepthFunc(g.GL_LESS); g.glDisable(g.GL_BLEND)
            g.glEnable(g.GL_CULL_FACE)
            _pass(0)
            g.glDisable(g.GL_CULL_FACE)
            _pass(1)
            g.glColorMask(g.GL_TRUE, g.GL_TRUE, g.GL_TRUE, g.GL_TRUE)
            g.glUseProgram(self.program)   # uniforms set earlier persist on this program

        # Color-pass depth state: with a prepass, test GL_LEQUAL and don't rewrite
        # depth (it's already laid); without, ordinary GL_LESS + depth write.
        _cf = g.GL_LEQUAL if prepass else g.GL_LESS
        _cm = g.GL_FALSE if prepass else g.GL_TRUE

        # Pass 0: opaque, single-sided.
        g.glDepthMask(_cm); g.glDepthFunc(_cf); g.glDisable(g.GL_BLEND)
        g.glEnable(g.GL_CULL_FACE)
        _pass(0)
        # Pass 1: opaque, two-sided (foliage/grates) — no backface cull.
        g.glDisable(g.GL_CULL_FACE)
        _pass(1)
        # Pass 2: blend (glass/FX) — after all opaque, blended, no depth write.
        g.glEnable(g.GL_BLEND); g.glBlendFunc(g.GL_SRC_ALPHA, g.GL_ONE_MINUS_SRC_ALPHA)
        g.glDepthMask(g.GL_FALSE); g.glDepthFunc(g.GL_LEQUAL)
        _pass(2)

        # Restore so the fixed-function passes (terrain/cubes/glow) are unaffected.
        g.glDisable(g.GL_BLEND); g.glDepthMask(g.GL_TRUE); g.glDepthFunc(g.GL_LESS)
        g.glBindBuffer(g.GL_SHADER_STORAGE_BUFFER, 0)
        g.glBindBuffer(g.GL_DRAW_INDIRECT_BUFFER, 0)
        g.glBindVertexArray(0)
        g.glUseProgram(0)
        g.glDisable(g.GL_CULL_FACE)
        return True

    def _free_buffers(self, g):
        try:
            if self.bufs:
                g.glDeleteBuffers(len(self.bufs), self.bufs)
            if self.vao:
                g.glDeleteVertexArrays(1, [self.vao]); self.vao = 0
        except Exception:
            pass
        self.bufs = []


def _compile_program(g, vsrc, fsrc):
    def stage(kind, src):
        sh = g.glCreateShader(kind)
        g.glShaderSource(sh, src)
        g.glCompileShader(sh)
        if g.glGetShaderiv(sh, g.GL_COMPILE_STATUS) != g.GL_TRUE:
            k = 'VERTEX' if kind == g.GL_VERTEX_SHADER else 'FRAGMENT'
            print(f"[gpu-driven] {k} COMPILE FAILED: {g.glGetShaderInfoLog(sh)}")
            g.glDeleteShader(sh); return 0
        return sh
    vs = stage(g.GL_VERTEX_SHADER, vsrc)
    fs = stage(g.GL_FRAGMENT_SHADER, fsrc)
    if not vs or not fs:
        return 0
    p = g.glCreateProgram()
    g.glAttachShader(p, vs); g.glAttachShader(p, fs)
    g.glLinkProgram(p)
    g.glDeleteShader(vs); g.glDeleteShader(fs)
    if g.glGetProgramiv(p, g.GL_LINK_STATUS) != g.GL_TRUE:
        print(f"[gpu-driven] LINK FAILED: {g.glGetProgramInfoLog(p)}")
        g.glDeleteProgram(p); return 0
    print("[gpu-driven] MDI program compiled + linked OK")
    return p


# ───────────────────────── self-test (GPU-free) ─────────────────────────
if __name__ == '__main__':
    rng = np.random.default_rng(0)

    class _Mesh:
        def __init__(self, nv, ni):
            self.vertices = rng.uniform(-10, 10, (nv, 3)).astype(np.float32)
            self.normals = rng.uniform(-1, 1, (nv, 3)).astype(np.float32)
            self.uvs = rng.uniform(0, 1, (nv, 2)).astype(np.float32)
            self.tangents = rng.uniform(-1, 1, (nv, 3)).astype(np.float32)
            self.indices = rng.integers(0, nv, ni).astype(np.uint32)
            self.material_index = int(rng.integers(0, 5))

    class _Model:
        def __init__(self, k):
            self.meshes = [_Mesh(int(rng.integers(4, 50)), int(rng.integers(3, 90)) * 3)
                           for _ in range(int(rng.integers(1, 5)))]

    models = [(f'model_{k}.xbg', _Model(k)) for k in range(40)]
    out = consolidate_geometry(models)
    P, I, table = out['positions'], out['indices'], out['table']
    print(f"packed {len(table)} meshes -> {out['vertex_count']} verts, {out['index_count']} indices")

    # The key invariant: shared_index[firstIndex:firstIndex+count] + baseVertex
    # must index exactly the vertices the ORIGINAL mesh's indices selected.
    worst = 0.0
    flat = [(mp, m) for mp, mdl in models for m in mdl.meshes
            if m.vertices is not None][:0]  # rebuild lookup in pack order
    pack_i = 0
    for mp, mdl in models:
        for m in mdl.meshes:
            e = table[pack_i]; pack_i += 1
            local = I[e.first_index:e.first_index + e.count]            # 0-based, mesh-local
            shared_verts = P[e.base_vertex + local]                     # via baseVertex
            orig_verts = m.vertices[m.indices]
            worst = max(worst, float(np.max(np.abs(shared_verts - orig_verts))))
            assert e.material_index == m.material_index
    print(f"max vertex mismatch via (baseVertex+firstIndex): {worst:.2e}")
    print("PASS — consolidation reconstructs every mesh exactly"
          if worst == 0.0 else "FAIL — packing is wrong")
