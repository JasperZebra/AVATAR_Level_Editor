#!/usr/bin/env python3
"""
Direct XBG → in-memory model loader (no GLTF / .bin intermediates).

This replaces the old offline pipeline (xbg2gltf.py → .gltf/.bin → _parse_gltf)
with a direct parse: an .xbg is read straight into the same GLTFModel / GLTFMesh
structures the renderer already consumes. Materials (XBM) and textures (XBT) are
resolved on demand by ModelLoader._load_xbg_textures (which needs an OpenGL
context); this module is intentionally **GL-free** so it can run on the parallel
level-load worker threads exactly like _parse_gltf used to.

Why this is geometry-identical to the old gltf path:
  * GLTFExporter wrote XBG vertex/UV data RAW (no coordinate transform — the
    -90°X correction lives in the render-time glRotatef(-90,1,0,0)), so feeding
    mesh.vert_pos_list / vert_uv_list straight into GLTFMesh produces the same
    numbers the gltf round-trip produced.
  * Each XBG Mesh primitive (material group) became one gltf primitive → one
    GLTFMesh; we reproduce that 1:1, sharing the mesh's vertex/normal/uv arrays
    across its primitives and keying material_index by the XBG material index
    (GLTFExporter mapped these 1:1).

Static geometry only — bone weights / skeleton are ignored (per project scope).
"""

import json
import os
import numpy as np

# canvas/ is on sys.path at runtime, so these resolve like the rest of the package
from xbg_parser import XBGParser

# ── Mounted-weapon attachments (dove turret, FC2 jeep .50cal, …) ─────────────
# canvas/assets/<game>/vehicle_attachments.json maps a vehicle model basename
# to child models (turret mount, gun) with a baked game-space 4x4 relative to
# the vehicle origin (see bake_vehicle_attachments.py — data recovered from
# the games' entity libraries + the engine's seat/mount attach rule). The
# attachment meshes are merged straight into the vehicle's GLTFModel here, so
# armed vehicles render complete on every path (GDR, classic, CS preview,
# thumbnails) with no renderer changes.
_attachments_table = None


def _get_attachments_table():
    global _attachments_table
    if _attachments_table is None:
        table = {}
        assets = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
        for game in ('avatar', 'fc2'):
            p = os.path.join(assets, game, 'vehicle_attachments.json')
            try:
                if os.path.exists(p):
                    with open(p, 'r', encoding='utf-8') as f:
                        table.update({k.lower(): v for k, v in json.load(f).items()})
            except Exception as e:
                print(f"[attachments] failed to read {p}: {e}")
        _attachments_table = table
    return _attachments_table


def _resolve_attachment_path(vehicle_xbg_path, rel_model):
    """Data-relative 'graphics/...' path → absolute, anchored at the data root
    that contains the vehicle model (case-flattened fallback included)."""
    norm = vehicle_xbg_path.replace('\\', '/')
    i = norm.lower().rfind('/graphics/')
    candidates = []
    if i >= 0:
        root = vehicle_xbg_path[:i]
        candidates.append(os.path.join(root, rel_model.replace('/', os.sep)))
        candidates.append(os.path.join(root, rel_model.lower().replace('/', os.sep)))
    # same-folder fallback (dove keeps its turret next to the vehicle)
    candidates.append(os.path.join(os.path.dirname(vehicle_xbg_path),
                                   os.path.basename(rel_model)))
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def build_xbg_model(xbg_path, GLTFModel, GLTFMesh, lod_level=0,
                    _no_attachments=False):
    """Parse an .xbg into a populated (but texture-less) GLTFModel.

    GL-free: fills model.meshes (vertices/normals/uvs/indices/material_index),
    model.bounds_min/max, and stashes model.xbg_material_names for the texture
    pass. Does NOT create GL textures or display lists — callers do that with a
    live GL context (ModelLoader._load_xbg_textures + _create_opengl_resources).

    GLTFModel / GLTFMesh are passed in to avoid importing model_loader (which
    pulls in OpenGL at import time).

    Returns the GLTFModel, or raises on a hard parse failure.
    """
    parser = XBGParser(xbg_path)
    # Static geometry only — skip the skeleton parse + bone-transform compute and
    # the skin-index remap. (Re-enabling skip_skeleton=False corrupted model
    # scale/rotation on reload — the skeleton/skin parse path has a side effect on
    # the static vertex assembly — and it doesn't change static rendering anyway,
    # since nothing deforms the mesh here. Reverted.)
    xbg = parser.parse(lod_level, skip_skeleton=True)   # already LOD-filtered

    model = GLTFModel(os.path.basename(xbg_path), xbg_path)
    # Material *names*, indexed by XBG material index. The texture pass keys
    # model.textures/alpha_modes/etc. by this same index.
    model.xbg_material_names = list(getattr(xbg, 'materials', []) or [])

    bmin = [float('inf')] * 3
    bmax = [float('-inf')] * 3
    have_bounds = False

    for src in xbg.meshes:
        # Prefer the numpy fast-path arrays the parser produced; fall back to the
        # (legacy) Python lists. Avoids re-parsing millions of floats per level.
        _parr = getattr(src, 'vert_pos_arr', None)
        if _parr is not None and len(_parr):
            verts = np.ascontiguousarray(_parr, dtype=np.float32)
        elif src.vert_pos_list:
            verts = np.asarray(src.vert_pos_list, dtype=np.float32)
        else:
            continue
        if verts.ndim != 2 or verts.shape[1] != 3 or verts.shape[0] == 0:
            continue
        _nverts = verts.shape[0]

        # Whole-model bounds (the old gltf path stored only the LAST mesh's
        # accessor min/max into model.bounds — a latent bug; computing the true
        # union here makes ray-AABB picking correct for multi-mesh models).
        vmin = verts.min(axis=0)
        vmax = verts.max(axis=0)
        for i in range(3):
            if vmin[i] < bmin[i]:
                bmin[i] = float(vmin[i])
            if vmax[i] > bmax[i]:
                bmax[i] = float(vmax[i])
        have_bounds = True

        norms = None
        _narr = getattr(src, 'vert_normal_arr', None)
        if _narr is not None and len(_narr) == _nverts:
            norms = np.ascontiguousarray(_narr, dtype=np.float32)
        else:
            nlist = getattr(src, 'vert_normal_list', None)
            if nlist is not None and len(nlist) == _nverts:
                norms = np.asarray(nlist, dtype=np.float32)

        uvs = None
        _uarr = getattr(src, 'vert_uv_arr', None)
        if _uarr is not None and len(_uarr) == _nverts:
            uvs = np.ascontiguousarray(_uarr, dtype=np.float32)
        elif src.vert_uv_list and len(src.vert_uv_list) == _nverts:
            uvs = np.asarray(src.vert_uv_list, dtype=np.float32)

        # Authored tangents (decoded from the vertex buffer's D3DCOLOR TANGENT
        # component) — preferred over the UV-derived computation when present.
        tans = None
        _tarr = getattr(src, 'vert_tangent_arr', None)
        if _tarr is not None and len(_tarr) == _nverts:
            tans = np.ascontiguousarray(_tarr, dtype=np.float32)

        # Vertex colour = the engine's `vertexMask` (aaa.fx). Kept as raw uint8
        # RGBA and normalised by GL, so it costs 4 bytes/vertex, not 16.
        cols = None
        _carr = getattr(src, 'vert_color_arr', None)
        if _carr is not None and len(_carr) == _nverts:
            cols = np.ascontiguousarray(_carr, dtype=np.uint8)

        # One GLTFMesh per primitive (material group), sharing the vertex arrays.
        primitives = list(getattr(src, 'primitives', []) or [])
        if primitives:
            for prim in primitives:
                if not prim.indices:
                    continue
                gm = _make_gltfmesh(GLTFMesh, verts, norms, uvs,
                                    prim.indices, prim.material_index, tans, cols)
                model.meshes.append(gm)
        elif src.face_list:
            flat = []
            for face in src.face_list:
                flat.extend(face)
            if flat:
                gm = _make_gltfmesh(GLTFMesh, verts, norms, uvs, flat, 0, tans, cols)
                model.meshes.append(gm)

    if have_bounds:
        model.bounds_min = bmin
        model.bounds_max = bmax

    if not _no_attachments:
        try:
            _merge_attachments(xbg_path, model, GLTFModel, GLTFMesh, lod_level)
        except Exception as e:
            print(f"[attachments] merge failed for {os.path.basename(xbg_path)}: {e}")

    return model


def _merge_attachments(xbg_path, model, GLTFModel, GLTFMesh, lod_level):
    """Append mounted-weapon models (turret/gun) into a vehicle's GLTFModel,
    transformed by their baked game-space attach matrices."""
    entries = _get_attachments_table().get(os.path.basename(xbg_path).lower())
    if not entries:
        return
    for entry in entries:
        full = _resolve_attachment_path(xbg_path, entry['model'])
        if not full:
            print(f"[attachments] model not found on disk: {entry['model']}")
            continue
        sub = build_xbg_model(full, GLTFModel, GLTFMesh, lod_level,
                              _no_attachments=True)
        if not sub.meshes:
            continue
        M = np.asarray(entry['matrix'], dtype=np.float64)
        R, t = M[:3, :3], M[:3, 3]
        rotate = not np.allclose(R, np.eye(3), atol=1e-9)
        mat_base = len(model.xbg_material_names)
        model.xbg_material_names.extend(getattr(sub, 'xbg_material_names', []) or [])
        transformed = {}   # id(arr) -> transformed copy (arrays are shared across prims)
        for gm in sub.meshes:
            key = id(gm.vertices)
            if key not in transformed:
                v = np.asarray(gm.vertices, dtype=np.float64)
                v = (v @ R.T + t) if rotate else (v + t)
                transformed[key] = np.ascontiguousarray(v, dtype=np.float32)
            gm.vertices = transformed[key]
            if gm.normals is not None and rotate:
                nkey = ('n', id(gm.normals))
                if nkey not in transformed:
                    n = np.asarray(gm.normals, dtype=np.float64) @ R.T
                    ln = np.linalg.norm(n, axis=1)
                    n[ln > 1e-9] /= ln[ln > 1e-9, None]
                    transformed[nkey] = np.ascontiguousarray(n, dtype=np.float32)
                gm.normals = transformed[nkey]
            if getattr(gm, 'tangents', None) is not None and rotate:
                tkey = ('t', id(gm.tangents))
                if tkey not in transformed:
                    tn = np.asarray(gm.tangents, dtype=np.float64) @ R.T
                    transformed[tkey] = np.ascontiguousarray(tn, dtype=np.float32)
                gm.tangents = transformed[tkey]
            gm.material_index = int(gm.material_index) + mat_base
            model.meshes.append(gm)
        # widen the vehicle bounds so picking/culling covers the attachment
        allv = [v for k, v in transformed.items() if not isinstance(k, tuple)]
        if allv and getattr(model, 'bounds_min', None) is not None:
            av = np.concatenate(allv)
            vmin, vmax = av.min(axis=0), av.max(axis=0)
            model.bounds_min = [min(model.bounds_min[i], float(vmin[i])) for i in range(3)]
            model.bounds_max = [max(model.bounds_max[i], float(vmax[i])) for i in range(3)]


def _make_gltfmesh(GLTFMesh, verts, norms, uvs, indices, material_index,
                   authored_tangents=None, colors=None):
    gm = GLTFMesh()
    gm.vertices = verts
    gm.normals = norms
    gm.uvs = uvs
    gm.colors = colors
    # uint32 indices — the display-list path converts to uint32 anyway, and this
    # makes the immediate-mode / glow paths (which pass mesh.indices straight to
    # glDrawElements as GL_UNSIGNED_INT) correct too. The old gltf path stored
    # indices as float32, which only worked because the display-list path
    # re-cast them.
    idx = np.asarray(indices, dtype=np.uint32)
    gm.indices = idx
    gm.material_index = int(material_index)
    # Per-vertex tangents (for the GLSL normal-mapping pass): authored ones
    # decoded from the file when available, else derived from positions + UVs.
    # Harmless when absent (the shader's u_has_normal flag gates normal mapping).
    if authored_tangents is not None:
        gm.tangents = authored_tangents
    else:
        gm.tangents = (_compute_tangents(verts, uvs, idx)
                       if (uvs is not None and norms is not None) else None)
    return gm


def _compute_tangents(verts, uvs, idx):
    """Per-vertex tangents from positions + UVs (accumulated over triangles,
    then normalised). Vectorised with numpy so it's cheap at load time."""
    try:
        tri = idx.reshape(-1, 3)
        if tri.shape[0] == 0:
            return None
        i0, i1, i2 = tri[:, 0], tri[:, 1], tri[:, 2]
        v0, v1, v2 = verts[i0], verts[i1], verts[i2]
        w0, w1, w2 = uvs[i0], uvs[i1], uvs[i2]
        e1 = v1 - v0
        e2 = v2 - v0
        d1 = w1 - w0
        d2 = w2 - w0
        denom = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
        safe = np.abs(denom) > 1e-8
        r = np.zeros_like(denom)
        r[safe] = 1.0 / denom[safe]
        # tangent per triangle = (e1 * d2.v - e2 * d1.v) / det
        t = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) * r[:, None]
        tan = np.zeros((verts.shape[0], 3), dtype=np.float32)
        np.add.at(tan, i0, t)
        np.add.at(tan, i1, t)
        np.add.at(tan, i2, t)
        n = np.linalg.norm(tan, axis=1, keepdims=True)
        n[n < 1e-8] = 1.0
        return (tan / n).astype(np.float32)
    except Exception:
        return None
