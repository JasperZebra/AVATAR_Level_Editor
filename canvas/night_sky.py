#!/usr/bin/env python3
"""
Night-sky star dome — loads canvas/Night Sky/Night Sky.glb (a STARSPHERE: Milky
Way + star triangles, emissive PNG textures with black backgrounds) and renders
it as a huge camera-centered dome that glows in at night.

Self-contained (own GLB parse + fixed-function additive draw) so it doesn't touch
the entity pipeline:
  * Parsed once: geometry (position + uv + indices per primitive) → VBOs, and the
    embedded PNG emissive textures → GL textures.
  * Drawn camera-centered + scaled huge (bigger than the map) so the stars sit at
    "infinity"; ADDITIVE blend makes the black texture background transparent and
    the Milky Way / stars add their glow; no depth write (pure background), no
    lighting. Faded by the day/night `night_factor` (invisible by day).
"""

import os
import io
import json
import struct
import ctypes
import numpy as np
from OpenGL.GL import *

try:
    from PIL import Image
    _PIL = True
except Exception:
    _PIL = False

_CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16,
       5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}


def _parse_glb(path):
    """Return (gltf_json_dict, bin_bytes) from a binary .glb."""
    with open(path, 'rb') as f:
        data = f.read()
    magic, ver, length = struct.unpack('<III', data[:12])
    if magic != 0x46546C67:   # 'glTF'
        raise ValueError("not a GLB")
    off = 12
    j = binc = None
    while off < length:
        clen, ctype = struct.unpack('<II', data[off:off + 8])
        chunk = data[off + 8:off + 8 + clen]
        if ctype == 0x4E4F534A:      # 'JSON'
            j = json.loads(chunk.decode('utf-8'))
        elif ctype == 0x004E4942:    # 'BIN\0'
            binc = chunk
        off += 8 + clen
    return j, binc


def _accessor(j, binc, idx):
    """Read accessor `idx` as an (count, ncomp) numpy array (tight or strided)."""
    acc = j['accessors'][idx]
    bv = j['bufferViews'][acc['bufferView']]
    base = bv.get('byteOffset', 0) + acc.get('byteOffset', 0)
    dt = np.dtype(_CT[acc['componentType']])
    nc = _NC[acc['type']]
    count = acc['count']
    stride = bv.get('byteStride', 0)
    if not stride or stride == dt.itemsize * nc:
        arr = np.frombuffer(binc, dtype=dt, count=count * nc, offset=base)
        return arr.reshape(count, nc) if nc > 1 else arr.reshape(count, 1)
    # Interleaved: gather each element across the stride.
    out = np.empty((count, nc), dtype=dt)
    for i in range(count):
        s = base + i * stride
        out[i] = np.frombuffer(binc, dtype=dt, count=nc, offset=s)
    return out


class NightSky:
    """Lazily loads + renders the star dome. render() is a no-op until night."""

    def __init__(self, glb_path):
        self.glb_path = glb_path
        self._built = False
        self._failed = False
        self.prims = []          # list of dict(vbo_pos, vbo_uv, ibo, count, tex)
        self.scale = 8000.0      # dome radius in world units (bigger than the map)

    def _build(self):
        if self._failed:
            return False
        if not _PIL:
            print("[night-sky] PIL unavailable — cannot decode star textures")
            self._failed = True
            return False
        try:
            j, binc = _parse_glb(self.glb_path)
        except Exception as e:
            print(f"[night-sky] GLB parse failed: {e}")
            self._failed = True
            return False
        try:
            # Decode the embedded PNG images (bufferView-backed) → GL textures.
            img_tex = {}
            for i, im in enumerate(j.get('images', [])):
                bv = j['bufferViews'][im['bufferView']]
                b = binc[bv.get('byteOffset', 0): bv.get('byteOffset', 0) + bv['byteLength']]
                pil = Image.open(io.BytesIO(b)).convert('RGBA')
                w, h = pil.size
                tid = glGenTextures(1)
                glBindTexture(GL_TEXTURE_2D, tid)
                glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA,
                             GL_UNSIGNED_BYTE, pil.tobytes())
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
                glGenerateMipmap(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, 0)
                img_tex[i] = int(tid)

            # material index → image index (emissive texture)
            mat_img = {}
            for mi, m in enumerate(j.get('materials', [])):
                et = m.get('emissiveTexture')
                if et is not None:
                    tex = j['textures'][et['index']]
                    mat_img[mi] = tex.get('source', 0)

            # Build a VBO per primitive. Normalise positions to self.scale radius.
            maxr = 1.0
            mesh = j['meshes'][0]
            prim_data = []
            for prim in mesh['primitives']:
                attrs = prim['attributes']
                pos = _accessor(j, binc, attrs['POSITION']).astype(np.float32)
                uv = (_accessor(j, binc, attrs['TEXCOORD_0']).astype(np.float32)
                      if 'TEXCOORD_0' in attrs else np.zeros((pos.shape[0], 2), np.float32))
                idx = (_accessor(j, binc, prim['indices']).astype(np.uint32).ravel()
                       if 'indices' in prim else
                       np.arange(pos.shape[0], dtype=np.uint32))
                maxr = max(maxr, float(np.max(np.linalg.norm(pos, axis=1)) or 1.0))
                prim_data.append((pos, uv, idx, mat_img.get(prim.get('material', -1))))

            norm = self.scale / maxr   # scale so the dome radius ≈ self.scale
            for pos, uv, idx, tex_src in prim_data:
                pos = pos * norm
                vp = glGenBuffers(1); glBindBuffer(GL_ARRAY_BUFFER, vp)
                glBufferData(GL_ARRAY_BUFFER, pos.nbytes, np.ascontiguousarray(pos), GL_STATIC_DRAW)
                vu = glGenBuffers(1); glBindBuffer(GL_ARRAY_BUFFER, vu)
                glBufferData(GL_ARRAY_BUFFER, uv.nbytes, np.ascontiguousarray(uv), GL_STATIC_DRAW)
                ib = glGenBuffers(1); glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ib)
                glBufferData(GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, np.ascontiguousarray(idx), GL_STATIC_DRAW)
                self.prims.append({'pos': int(vp), 'uv': int(vu), 'ibo': int(ib),
                                   'count': int(idx.size),
                                   'tex': img_tex.get(tex_src, 0)})
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0)
            self._built = True
            print(f"[night-sky] loaded {len(self.prims)} primitives, "
                  f"{len(img_tex)} textures (dome radius {self.scale:.0f})")
            return True
        except Exception as e:
            import traceback
            print(f"[night-sky] build failed: {e}")
            traceback.print_exc()
            self._failed = True
            return False

    def render(self, cam_pos, night_factor):
        """Draw the star dome, camera-centered, additive, faded by night_factor.
        cam_pos = (x, y, z) world camera position."""
        if night_factor <= 0.01 or self._failed:
            return
        if not self._built and not self._build():
            return
        _z = ctypes.c_void_p(0)
        glPushAttrib(GL_ENABLE_BIT | GL_DEPTH_BUFFER_BIT | GL_CURRENT_BIT | GL_TEXTURE_BIT)
        try:
            glUseProgram(0)
            glMatrixMode(GL_MODELVIEW)
            glPushMatrix()
            # Follow the camera so the stars stay at "infinity"; match the model
            # game→editor orientation (-90° X like the rest of the world).
            glTranslatef(float(cam_pos[0]), float(cam_pos[1]), float(cam_pos[2]))
            glRotatef(-90.0, 1.0, 0.0, 0.0)

            glDisable(GL_LIGHTING)
            glDisable(GL_CULL_FACE)
            glDepthMask(GL_FALSE)            # background — don't occlude the scene
            glDisable(GL_DEPTH_TEST)
            glEnable(GL_BLEND)
            glBlendFunc(GL_ONE, GL_ONE)      # additive → black texels add nothing
            glEnable(GL_TEXTURE_2D)
            glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
            nf = float(night_factor)
            glColor4f(nf, nf, nf, 1.0)       # fade with night

            glEnableClientState(GL_VERTEX_ARRAY)
            glEnableClientState(GL_TEXTURE_COORD_ARRAY)
            for p in self.prims:
                glBindTexture(GL_TEXTURE_2D, p['tex'])
                glBindBuffer(GL_ARRAY_BUFFER, p['pos'])
                glVertexPointer(3, GL_FLOAT, 0, _z)
                glBindBuffer(GL_ARRAY_BUFFER, p['uv'])
                glTexCoordPointer(2, GL_FLOAT, 0, _z)
                glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, p['ibo'])
                glDrawElements(GL_TRIANGLES, p['count'], GL_UNSIGNED_INT, _z)
            glDisableClientState(GL_VERTEX_ARRAY)
            glDisableClientState(GL_TEXTURE_COORD_ARRAY)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0)
            glBindTexture(GL_TEXTURE_2D, 0)
        finally:
            glPopMatrix()
            glPopAttrib()
