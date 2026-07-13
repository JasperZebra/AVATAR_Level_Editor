"""Renders level VEGETATION (trees, bushes, grass, shrooms) in the 3D view.

Vegetation is stored in the `landmarkfar_*.data.fcb` files (which the normal
sector loader skips) as VegetationData -> VegetationZoneData objects. Each zone
holds instance positions + a list of RealTree `.rtx` model resources (referenced
by a CRC32 of the model path). This module:

  1. parses the landmark converted-XMLs for vegetation zones + instances,
  2. resolves each resource CRC to an actual `.rtx` file (reverse CRC table),
  3. loads the `.rtx` geometry via canvas/rtx_loader,
  4. draws every instance at its world position/orientation/scale.

Self-contained + guarded like water_plane_renderer: any failure just means no
vegetation is drawn, never a broken viewport. CPU parsing happens at level-load
time (parse_level); GL buffers upload lazily on first render.
"""

import os
import glob
import zlib
import struct
import xml.etree.ElementTree as ET

from OpenGL.GL import *
import numpy as np
import ctypes

from rtx_loader import load_rtx

# FCB object/field hashes (CRC32 of the name) for the vegetation structures.
H_VEGDATA = "114CFEE7"          # VegetationData object
H_VEGZONE = "A18C8484"          # VegetationZoneData object
H_BBOXMIN = "17E7C62E"
H_BBOXMAX = "2BEAF977"
H_RESLIST = "89C8C095"          # resourceList : uint32 count + count*uint32 hashes
H_RESCLUS = "58AD43E2"          # resClustersCntList
H_CLUSINS = "798C33D5"          # clustersInstancesCntList
H_POSXY = "D28100C0"            # posXYList : count + count*(u16 x, u16 y)
H_POSZ = "8E2752CA"             # posZList  : count + count*f32
H_ORIENT = "560A5378"           # orientDataList


def _crc32(s):
    return zlib.crc32(s.encode("latin-1", "ignore")) & 0xFFFFFFFF


class VegetationRenderer:
    def __init__(self):
        self._parsed = False
        self._instances = []      # list of dict(rtx, x, y, z, yaw, scale)  (x,y,z GAME space, z-up)
        self._meshes = {}         # rtx_path -> RtxMesh (cpu)
        self._gl = {}             # rtx_path -> dict(vbo, nverts) or False (failed)
        self._crc_table = None    # {crc:int -> relpath}
        self._data_root = None

    # ────────────────────────────────────────────────────────────────────
    # CPU: build the reverse CRC table for .rtx models
    # ────────────────────────────────────────────────────────────────────
    def _build_crc_table(self, data_root):
        table = {}
        for dp, _dirs, files in os.walk(data_root):
            for f in files:
                if f.lower().endswith(".rtx"):
                    rel = os.path.relpath(os.path.join(dp, f), data_root)
                    table[_crc32(rel.replace("/", "\\").lower())] = rel
        return table

    def _resolve_data_root(self, canvas):
        tr = getattr(canvas, "terrain_renderer", None)
        for r in (getattr(tr, "blend_data_roots", None) or []):
            if r and os.path.isdir(os.path.join(r, "graphics")):
                return r
        ml = getattr(canvas, "model_loader", None)
        md = getattr(ml, "materials_directory", None) if ml else None
        if md:  # <root>/graphics/_materials -> <root>
            root = os.path.dirname(os.path.dirname(md.rstrip("/\\")))
            if os.path.isdir(os.path.join(root, "graphics")):
                return root
        gd = getattr(ml, "models_directory", None) if ml else None
        if gd:
            root = os.path.dirname(gd.rstrip("/\\"))
            if os.path.isdir(os.path.join(root, "graphics")):
                return root
        return None

    # ────────────────────────────────────────────────────────────────────
    # CPU: parse landmark XMLs -> instances
    # ────────────────────────────────────────────────────────────────────
    @staticmethod
    def _field(obj, hsh):
        for fe in obj.findall("field"):
            if fe.get("hash", "").upper() == hsh:
                return fe
        return None

    @staticmethod
    def _raw(obj, hsh):
        fe = VegetationRenderer._field(obj, hsh)
        if fe is None or not (fe.text and fe.text.strip()):
            return None
        try:
            return bytes.fromhex(fe.text.strip())
        except ValueError:
            return None

    @staticmethod
    def _vec3(obj, hsh):
        fe = VegetationRenderer._field(obj, hsh)
        if fe is None:
            return None
        v = fe.get("value-Vector3")
        if v:
            try:
                return tuple(float(x) for x in v.split(","))
            except ValueError:
                pass
        b = VegetationRenderer._raw(obj, hsh)
        if b and len(b) >= 12:
            return struct.unpack_from("<fff", b, 0)
        return None

    @staticmethod
    def _u32_list(b):
        if not b or len(b) < 4:
            return []
        cnt = struct.unpack_from("<I", b, 0)[0]
        return [struct.unpack_from("<I", b, 4 + i * 4)[0] for i in range(cnt) if 4 + i * 4 + 4 <= len(b)]

    def _parse_zone(self, zone, crc_table, bbmin, bbmax):
        # bboxMin/bboxMax live on the parent VegetationData; a zone may also carry
        # its own, so prefer the zone's when present.
        bbmin = self._vec3(zone, H_BBOXMIN) or bbmin
        bbmax = self._vec3(zone, H_BBOXMAX) or bbmax
        res_b = self._raw(zone, H_RESLIST)
        posxy_b = self._raw(zone, H_POSXY)
        posz_b = self._raw(zone, H_POSZ)
        if not (bbmin and bbmax and res_b and posxy_b and posz_b):
            return
        resources = self._u32_list(res_b)                        # model CRC hashes
        rtx_paths = [crc_table.get(h) for h in resources]        # -> relpaths (or None)

        ninst = struct.unpack_from("<I", posxy_b, 0)[0]
        nz = struct.unpack_from("<I", posz_b, 0)[0]
        ninst = min(ninst, nz)
        if ninst <= 0:
            return

        # Map each instance -> resource via the cluster nesting, when it decodes
        # cleanly (sum of per-cluster instance counts == instance count); else
        # fall back to spreading instances across the resources evenly.
        inst_res = self._instance_resource_map(zone, resources, ninst)

        dx = bbmax[0] - bbmin[0]
        dy = bbmax[1] - bbmin[1]
        for i in range(ninst):
            xoff = 4 + i * 4
            xu = struct.unpack_from("<H", posxy_b, xoff)[0]
            yu = struct.unpack_from("<H", posxy_b, xoff + 2)[0]
            wx = bbmin[0] + (xu / 65535.0) * dx
            wy = bbmin[1] + (yu / 65535.0) * dy
            wz = struct.unpack_from("<f", posz_b, 4 + i * 4)[0]
            ridx = inst_res[i] if i < len(inst_res) else 0
            rtx = rtx_paths[ridx] if 0 <= ridx < len(rtx_paths) else None
            if not rtx:
                # any resolvable resource in this zone
                rtx = next((p for p in rtx_paths if p), None)
            if not rtx:
                continue
            self._instances.append(dict(rtx=rtx, x=wx, y=wy, z=wz, yaw=0.0, scale=1.0))

    def _instance_resource_map(self, zone, resources, ninst):
        try:
            resclus = self._u32_list(self._raw(zone, H_RESCLUS))        # clusters per resource
            clusins = self._u32_list(self._raw(zone, H_CLUSINS))        # instances per cluster
            if resclus and clusins and sum(clusins) == ninst:
                # cluster -> resource
                clus_res = []
                for ridx, ncl in enumerate(resclus):
                    clus_res.extend([ridx] * ncl)
                # instance -> cluster -> resource
                inst_res = []
                for cidx, ncount in enumerate(clusins):
                    r = clus_res[cidx] if cidx < len(clus_res) else 0
                    inst_res.extend([r] * ncount)
                if len(inst_res) == ninst:
                    return inst_res
        except Exception:
            pass
        # fallback: even spread across resources
        nres = max(1, len(resources))
        return [(i * nres) // max(1, ninst) for i in range(ninst)]

    def parse_level(self, editor):
        """Parse all landmark XMLs for vegetation. Safe to call on any thread
        (CPU/file only). Returns the number of instances found."""
        self._parsed = True
        self._instances = []
        canvas = getattr(editor, "canvas", None)
        if canvas is None:
            return 0
        data_root = self._resolve_data_root(canvas)
        if not data_root:
            print("[Vegetation] data root not found — skipping vegetation")
            return 0
        self._data_root = data_root

        folders = list(getattr(editor, "_all_worldsectors_paths", None) or [])
        wp = getattr(editor, "worldsectors_path", None)
        if wp and wp not in folders:
            folders.append(wp)
        folders = [f for f in folders if f and os.path.isdir(f)]
        if not folders:
            return 0

        if self._crc_table is None:
            self._crc_table = self._build_crc_table(data_root)
        print(f"[Vegetation] {len(self._crc_table)} .rtx models indexed")

        nfiles = 0
        for folder in folders:
            for xmlf in glob.glob(os.path.join(folder, "landmark*.data.fcb.converted.xml")):
                nfiles += 1
                try:
                    root = ET.parse(xmlf).getroot()
                except Exception:
                    continue
                for veg in root.iter("object"):
                    if veg.get("hash", "").upper() != H_VEGDATA:
                        continue
                    bbmin = self._vec3(veg, H_BBOXMIN)
                    bbmax = self._vec3(veg, H_BBOXMAX)
                    for zone in veg.findall("object"):
                        if zone.get("hash", "").upper() == H_VEGZONE:
                            try:
                                self._parse_zone(zone, self._crc_table, bbmin, bbmax)
                            except Exception as e:
                                print(f"[Vegetation] zone parse error: {e}")

        # Load the unique rtx meshes (CPU geometry) now.
        want = {ins["rtx"] for ins in self._instances}
        loaded = 0
        for rel in want:
            full = os.path.join(data_root, rel)
            m = load_rtx(full)
            if m:
                self._meshes[rel] = m
                loaded += 1
        # drop instances whose mesh failed to load
        self._instances = [i for i in self._instances if i["rtx"] in self._meshes]
        print(f"[Vegetation] {nfiles} landmark files -> {len(self._instances)} instances, "
              f"{loaded}/{len(want)} models loaded")
        return len(self._instances)

    # ────────────────────────────────────────────────────────────────────
    # GL: upload a mesh (baked into editor GL space) and draw
    # ────────────────────────────────────────────────────────────────────
    def _mesh_gl(self, rel):
        """Per-model triangle vertices baked into editor GL space (Y-up), as an
        (N,6) float array of [px,py,pz, nx,ny,nz] — computed once and reused for
        every instance of the model."""
        arr = self._meshes_gl.get(rel) if hasattr(self, "_meshes_gl") else None
        if arr is not None:
            return arr
        if not hasattr(self, "_meshes_gl"):
            self._meshes_gl = {}
        mesh = self._meshes.get(rel)
        if not mesh:
            self._meshes_gl[rel] = False
            return False
        P = np.asarray(mesh.positions, dtype=np.float32)
        # game (x,y,z z-up) -> GL (x, z, -y)
        Pgl = np.column_stack((P[:, 0], P[:, 2], -P[:, 1]))
        tris = np.asarray(mesh.triangles, dtype=np.int64)
        a = Pgl[tris[:, 0]]; b = Pgl[tris[:, 1]]; c = Pgl[tris[:, 2]]
        nrm = np.cross(b - a, c - a)
        ln = np.linalg.norm(nrm, axis=1, keepdims=True); ln[ln == 0] = 1.0
        nrm = nrm / ln
        # interleave 3 verts per triangle with the shared face normal
        verts = np.empty((len(tris) * 3, 6), dtype=np.float32)
        for k, corner in enumerate((a, b, c)):
            verts[k::3, 0:3] = corner
            verts[k::3, 3:6] = nrm
        self._meshes_gl[rel] = verts
        return verts

    def _ensure_batch(self, rel, insts):
        """Bake EVERY instance of a model into one big VBO (positions+normals in
        world GL space). Static vegetation -> built once, drawn in one call."""
        g = self._gl.get(rel)
        if g is not None:
            return g
        base = self._mesh_gl(rel)
        if base is False or base is None:
            self._gl[rel] = False
            return False
        try:
            import math
            chunks = []
            bpos = base[:, 0:3]; bnrm = base[:, 3:6]
            for ins in insts:
                s = ins["scale"]; yaw = ins["yaw"]
                p = bpos
                nn = bnrm
                if s != 1.0:
                    p = p * s
                if yaw:
                    r = math.radians(yaw); cs = math.cos(r); sn = math.sin(r)
                    # rotate about GL up-axis (Y)
                    px = p[:, 0] * cs + p[:, 2] * sn
                    pz = -p[:, 0] * sn + p[:, 2] * cs
                    p = np.column_stack((px, p[:, 1], pz))
                    nx = nn[:, 0] * cs + nn[:, 2] * sn
                    nz = -nn[:, 0] * sn + nn[:, 2] * cs
                    nn = np.column_stack((nx, nn[:, 1], nz))
                world = np.empty((base.shape[0], 6), dtype=np.float32)
                world[:, 0] = p[:, 0] + ins["x"]
                world[:, 1] = p[:, 1] + ins["z"]      # game Z (height) -> GL Y
                world[:, 2] = p[:, 2] - ins["y"]      # game Y -> GL -Z
                world[:, 3:6] = nn
                chunks.append(world)
            allv = np.concatenate(chunks, axis=0) if chunks else np.zeros((0, 6), np.float32)
            vbo = int(glGenBuffers(1))
            glBindBuffer(GL_ARRAY_BUFFER, vbo)
            glBufferData(GL_ARRAY_BUFFER, allv.nbytes, allv, GL_STATIC_DRAW)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            g = {"vbo": vbo, "nverts": allv.shape[0]}
            self._gl[rel] = g
            return g
        except Exception as e:
            print(f"[Vegetation] batch build failed for {rel}: {e}")
            self._gl[rel] = False
            return False

    def render(self, canvas):
        if not self._instances:
            return
        try:
            if not hasattr(self, "_by_mesh"):
                from collections import defaultdict
                bm = defaultdict(list)
                for ins in self._instances:
                    bm[ins["rtx"]].append(ins)
                self._by_mesh = dict(bm)
            glEnable(GL_DEPTH_TEST)
            glDepthMask(GL_TRUE)
            glDisable(GL_CULL_FACE)          # foliage is two-sided
            glEnable(GL_LIGHTING)
            glEnableClientState(GL_VERTEX_ARRAY)
            glEnableClientState(GL_NORMAL_ARRAY)
            glColor3f(0.28, 0.44, 0.19)      # leafy green, lit by the scene rig
            stride = 6 * 4
            for rel, insts in self._by_mesh.items():
                g = self._ensure_batch(rel, insts)
                if not g or not g["nverts"]:
                    continue
                glBindBuffer(GL_ARRAY_BUFFER, g["vbo"])
                glVertexPointer(3, GL_FLOAT, stride, ctypes.c_void_p(0))
                glNormalPointer(GL_FLOAT, stride, ctypes.c_void_p(12))
                glDrawArrays(GL_TRIANGLES, 0, g["nverts"])
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            glDisableClientState(GL_VERTEX_ARRAY)
            glDisableClientState(GL_NORMAL_ARRAY)
        except Exception as e:
            print(f"[Vegetation] render error: {e}")
        finally:
            glEnable(GL_CULL_FACE)
