"""
fbx_mesh.py — minimal reader for FBX *binary* files: pulls the mesh geometry (vertices +
triangles, merged across all Geometry nodes) so the editor can render an FBX model in GL.
Only what we need — no materials/animation. FBX binary is a node-record format with optionally
zlib-compressed property arrays (format documented by the community).
"""
import struct, zlib
import numpy as np

_MAGIC = b'Kaydara FBX Binary  \x00'


def _read(data):
    if data[:len(_MAGIC)] != _MAGIC:
        raise ValueError('not an FBX binary file')
    version = struct.unpack_from('<I', data, 23)[0]
    use64 = version >= 7500
    hdr = struct.Struct('<QQQ') if use64 else struct.Struct('<III')

    def read_prop(p):
        t = chr(data[p]); p += 1
        if t == 'Y': return struct.unpack_from('<h', data, p)[0], p + 2
        if t == 'C': return bool(data[p]), p + 1
        if t == 'I': return struct.unpack_from('<i', data, p)[0], p + 4
        if t == 'F': return struct.unpack_from('<f', data, p)[0], p + 4
        if t == 'D': return struct.unpack_from('<d', data, p)[0], p + 8
        if t == 'L': return struct.unpack_from('<q', data, p)[0], p + 8
        if t in 'fdlib':                                  # arrays
            length, enc, comp = struct.unpack_from('<III', data, p); p += 12
            raw = data[p:p + comp]; p += comp
            if enc == 1: raw = zlib.decompress(raw)
            fmt = {'f': 'f', 'd': 'd', 'l': 'q', 'i': 'i', 'b': 'b'}[t]
            sz = {'f': 4, 'd': 8, 'l': 8, 'i': 4, 'b': 1}[t]
            return np.frombuffer(raw[:length * sz], dtype='<' + fmt), p
        if t in 'SR':
            n = struct.unpack_from('<I', data, p)[0]; p += 4
            return data[p:p + n], p + n
        raise ValueError('unknown FBX prop type %r' % t)

    def read_node(p):
        end, nprops, _plen = hdr.unpack_from(data, p); p += hdr.size
        nlen = data[p]; p += 1
        if end == 0:                                      # null record terminates a list
            return None, p
        name = data[p:p + nlen].decode('latin1'); p += nlen
        props = []
        for _ in range(nprops):
            v, p = read_prop(p); props.append(v)
        children = []
        while p < end:
            child, p = read_node(p)
            if child is None: break
            children.append(child)
        return {'name': name, 'props': props, 'children': children}, end

    nodes = []; p = 27
    while p < len(data) - 13:
        node, p = read_node(p)
        if node is None: break
        nodes.append(node)
    return nodes


def _find(nodes, name):
    for n in nodes:
        if n['name'] == name:
            yield n
        yield from _find(n['children'], name)


def _euler_xyz(rx, ry, rz):
    """3x3 rotation from FBX Lcl Rotation (degrees, eEulerXYZ): R = Rz @ Ry @ Rx."""
    rx, ry, rz = np.radians([rx, ry, rz])
    cx, sx = np.cos(rx), np.sin(rx); cy, sy = np.cos(ry), np.sin(ry); cz, sz = np.cos(rz), np.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def _model_transforms(nodes):
    """id -> 4x4 local matrix (T*R*S) for every Model node, plus the connections child->parent."""
    models = {}
    for n in _find(nodes, 'Model'):
        mid = n['props'][0]
        t = [0., 0., 0.]; r = [0., 0., 0.]; s = [1., 1., 1.]
        for P in _find(n['children'], 'P'):
            if not P['props']: continue
            nm = P['props'][0]
            if nm == b'Lcl Translation': t = [float(x) for x in P['props'][-3:]]
            elif nm == b'Lcl Rotation':  r = [float(x) for x in P['props'][-3:]]
            elif nm == b'Lcl Scaling':   s = [float(x) for x in P['props'][-3:]]
        M = np.eye(4); M[:3, :3] = _euler_xyz(*r) @ np.diag(s); M[:3, 3] = t
        models[mid] = M
    parent = {}
    for conn in _find(nodes, 'Connections'):
        for c in conn['children']:
            if c['name'] == 'C' and len(c['props']) >= 3 and c['props'][0] == b'OO':
                parent[c['props'][1]] = c['props'][2]
    return models, parent


def load_fbx_mesh(path):
    """Return (verts Nx3 float32, tris Mx3 int32, norms Nx3 float32) — the whole model assembled
    by applying each part's hierarchical Model transform. Y-up source; raw coords (caller orients)."""
    nodes = _read(open(path, 'rb').read())
    models, parent = _model_transforms(nodes)

    def world_matrix(oid, _depth=0):
        M = models.get(oid, np.eye(4))
        p = parent.get(oid)
        if p is not None and p in models and _depth < 64:
            return world_matrix(p, _depth + 1) @ M
        return M

    all_v = []; all_t = []; base = 0
    for geo in _find(nodes, 'Geometry'):
        gid = geo['props'][0] if geo['props'] else None
        verts = idx = None
        for c in geo['children']:
            if c['name'] == 'Vertices' and c['props']:
                verts = np.asarray(c['props'][0], dtype=np.float64).reshape(-1, 3)
            elif c['name'] == 'PolygonVertexIndex' and c['props']:
                idx = np.asarray(c['props'][0], dtype=np.int64)
        if verts is None or idx is None:
            continue
        # place the part: a Geometry connects to its Model -> compose the parent chain
        mdl = parent.get(gid)
        W = world_matrix(mdl) if mdl is not None else np.eye(4)
        verts = (np.c_[verts, np.ones(len(verts))] @ W.T)[:, :3]
        poly = []
        for i in idx:
            if i < 0:
                poly.append(int(~i))
                for k in range(1, len(poly) - 1):
                    all_t.append((base + poly[0], base + poly[k], base + poly[k + 1]))
                poly = []
            else:
                poly.append(int(i))
        all_v.append(verts); base += len(verts)
    if not all_v:
        return None
    V = np.concatenate(all_v).astype(np.float32)
    T = np.array(all_t, dtype=np.int32) if all_t else np.zeros((0, 3), np.int32)
    # smooth-ish vertex normals
    N = np.zeros_like(V)
    for t in T:
        n = np.cross(V[t[1]] - V[t[0]], V[t[2]] - V[t[0]])
        for j in t: N[j] += n
    ln = np.linalg.norm(N, axis=1, keepdims=True); ln[ln == 0] = 1
    return V, T, (N / ln).astype(np.float32)


if __name__ == '__main__':
    import sys
    r = load_fbx_mesh(sys.argv[1])
    if not r: print('no mesh'); raise SystemExit
    V, T, N = r
    print(f"verts={len(V)} tris={len(T)}  bbox {V.min(0).round(2).tolist()}..{V.max(0).round(2).tolist()}")
