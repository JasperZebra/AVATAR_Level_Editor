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

import os
import numpy as np

# canvas/ is on sys.path at runtime, so these resolve like the rest of the package
from xbg_parser import XBGParser


def build_xbg_model(xbg_path, GLTFModel, GLTFMesh, lod_level=0):
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

        # One GLTFMesh per primitive (material group), sharing the vertex arrays.
        primitives = list(getattr(src, 'primitives', []) or [])
        if primitives:
            for prim in primitives:
                if not prim.indices:
                    continue
                gm = _make_gltfmesh(GLTFMesh, verts, norms, uvs,
                                    prim.indices, prim.material_index)
                model.meshes.append(gm)
        elif src.face_list:
            flat = []
            for face in src.face_list:
                flat.extend(face)
            if flat:
                gm = _make_gltfmesh(GLTFMesh, verts, norms, uvs, flat, 0)
                model.meshes.append(gm)

    if have_bounds:
        model.bounds_min = bmin
        model.bounds_max = bmax

    return model


def _make_gltfmesh(GLTFMesh, verts, norms, uvs, indices, material_index):
    gm = GLTFMesh()
    gm.vertices = verts
    gm.normals = norms
    gm.uvs = uvs
    # uint32 indices — the display-list path converts to uint32 anyway, and this
    # makes the immediate-mode / glow paths (which pass mesh.indices straight to
    # glDrawElements as GL_UNSIGNED_INT) correct too. The old gltf path stored
    # indices as float32, which only worked because the display-list path
    # re-cast them.
    idx = np.asarray(indices, dtype=np.uint32)
    gm.indices = idx
    gm.material_index = int(material_index)
    # Per-vertex tangents (for the GLSL normal-mapping pass). Needs UVs + normals;
    # harmless when absent (the shader's u_has_normal flag gates normal mapping).
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
