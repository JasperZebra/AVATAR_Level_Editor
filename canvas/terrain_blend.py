"""
Terrain splat compositor — shared by the 2D map (terrain_renderer) and the 3D
viewport (terrain_to_gltf) so both show the in-game terrain look instead of the
flat baked-diffuse atlas.

Per sector the engine stores, in <world>/generated/sdat:
  atlas*_mask.xbt    128x128  RGB splat weights (R+G+B ~= 255, partition of unity)
  atlas*_diffuse.xbt 128x128  a baked, low-frequency blended terrain colour
  atlas*_color.xbt   128x128  a near-neutral tint / lighting map
  sd*_shadow.xbt     64x64    baked shadow / AO

The detail textures themselves live per <Layer> in the map's .game.xml
(<Layers> block): each layer has a diffuse Texture (…_d.xbt) and a Tiling count.

We reconstruct the close-up look:
  weights = normalize(mask.rgb)                       # 3-way splat
  detail  = Σ weight_i * layer_i( uv * Tiling_i )     # high-freq tiled textures
  out     = detail * (color * gain) * shadow          # baked tint + AO

Mask channel → layer mapping is by <Layers> order (R→0, G→1, B→2); the base
ground layer (index 0) also fills any weight the mask leaves unassigned. Pure
numpy, fully vectorised, no Qt/GL — callable from the CPU 2D path and the GLTF
bake path alike.
"""

import os
import re
import numpy as np

# Tunables (kept here so both renderers share one look)
DEFAULT_DETAIL_STRENGTH = 0.85   # 0 → baked diffuse only; 1 → detail fully recolours
DEFAULT_BRIGHTNESS = 1.2
DEFAULT_TILING_SCALE = 1.0       # multiplies each layer's Tiling (repeats per sector)
MAX_MASK_LAYERS = 3              # mask carries 3 usable channels (A is unused/DXT1)


def _to_float_rgb(arr):
    """(H,W,{3,4}) uint8/float -> (H,W,3) float32 0..1."""
    a = np.asarray(arr)
    if a.dtype != np.float32 and a.dtype != np.float64:
        a = a.astype(np.float32) / 255.0
    else:
        a = a.astype(np.float32)
        if a.max() > 1.5:
            a = a / 255.0
    if a.ndim == 2:
        a = np.stack([a, a, a], axis=-1)
    return a[:, :, :3]


def _resize_nn(a, size):
    """Nearest-neighbour resize of (H,W,C) to (size,size,C) — no SciPy/PIL."""
    h, w = a.shape[:2]
    yi = (np.arange(size) * h // size).clip(0, h - 1)
    xi = (np.arange(size) * w // size).clip(0, w - 1)
    return a[np.ix_(yi, xi)]


def _tile_sample(img, size, repeats):
    """Sample (h,w,3) tiled *repeats* times across a size×size output."""
    h, w = img.shape[:2]
    t = np.arange(size, dtype=np.float32) / size * repeats
    frac = t - np.floor(t)
    yi = (frac * h).astype(np.int32) % h
    xi = (frac * w).astype(np.int32) % w
    return img[np.ix_(yi, xi)]


def composite_sector(mask, color, shadow, layers, out_size, *,
                     diffuse=None, detail_strength=0.8,
                     tiling_scale=DEFAULT_TILING_SCALE, brightness=1.0):
    """Composite one sector's in-game-look tile.

    The baked *diffuse* atlas is the colour/brightness anchor (it is the game's
    own low-frequency terrain colour); the tiled detail textures only add
    high-frequency variation on top, so the result keeps correct large-scale
    colour and can't drift far even if the mask→layer mapping is imperfect:

        detail = Σ normalize(mask)_i · layer_i(uv · Tiling_i)     # high-freq
        out    = base · ((1-s) + s · detail / mean(detail)) · shadow · brightness

    where base = diffuse (preferred) or color, and s = *detail_strength*
    (0 → just the baked look; 1 → detail fully recolours).

    mask/color/shadow/diffuse : (H,W,3) atlas quadrants (uint8/float) or None.
    layers : list of {'img': (h,w,3), 'tiling': float} ordered by <Layers>;
             index 0 is the base ground layer. Up to MAX_MASK_LAYERS blend.
    Returns (out_size, out_size, 3) uint8.
    """
    o = int(out_size)
    base = diffuse if diffuse is not None else color
    base_f = _resize_nn(_to_float_rgb(base), o) if base is not None else None

    if not layers:
        if base_f is None:
            return np.zeros((o, o, 3), np.uint8)
        out = base_f * brightness
        if shadow is not None:
            out = out * _resize_nn(_to_float_rgb(shadow), o)
        return np.clip(out * 255.0, 0, 255).astype(np.uint8)

    imgs = [_to_float_rgb(l['img']) for l in layers[:MAX_MASK_LAYERS]]
    tilings = [max(1.0, float(l.get('tiling', 1)) * tiling_scale)
               for l in layers[:MAX_MASK_LAYERS]]

    if mask is not None:
        w = _resize_nn(_to_float_rgb(mask), o)
        s = w.sum(axis=2, keepdims=True)
        w = np.where(s > 1e-3, w / s, w)
    else:
        w = np.zeros((o, o, 3), np.float32)
        w[:, :, 0] = 1.0

    detail = np.zeros((o, o, 3), np.float32)
    for i, (img, tl) in enumerate(zip(imgs, tilings)):
        detail += w[:, :, i:i + 1] * _tile_sample(img, o, tl)

    if base_f is None:
        out = detail
    else:
        # detail normalised to mean 1 per channel → modulates the baked colour
        dmean = detail.reshape(-1, 3).mean(axis=0) + 1e-4
        dn = detail / dmean
        out = base_f * ((1.0 - detail_strength) + detail_strength * dn)

    out = out * brightness
    if shadow is not None:
        out = out * _resize_nn(_to_float_rgb(shadow), o)
    return np.clip(out * 255.0, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Data loading — shared by the 2D renderer and the 3D GLTF bake
# ---------------------------------------------------------------------------

def _codec():
    """Lazily load tools/convert_avatar_xml.py (FC2 ships .game.xml as binary)."""
    try:
        import importlib.util
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(repo, 'tools', 'convert_avatar_xml.py')
        spec = importlib.util.spec_from_file_location('convert_avatar_xml', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def _parse_game_xml(path):
    import xml.etree.ElementTree as ET
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError:
        return None
    if data[:2] == b'\x00\x00':
        c = _codec()
        if c is None:
            return None
        try:
            return c.decode(data)
        except Exception:
            return None
    try:
        return ET.fromstring(data)
    except Exception:
        return None


def _resolve_texture(rel, data_roots):
    if not rel:
        return None
    rel = rel.strip().replace('\\', '/').lstrip('/')
    if not rel.lower().endswith('.xbt'):
        return None
    parts = rel.split('/')
    for root in data_roots:
        if not root:
            continue
        cand = os.path.join(root, *parts)
        if os.path.isfile(cand):
            return cand
    return None


def _load_xbt_rgb(path, size=None):
    """Load an atlas image to (H,W,3) uint8. Handles .xbt (TBX→DDS→PIL), and
    plain .dds/.png/.tga via PIL directly. Optional resize. None on failure."""
    if not path:
        return None
    try:
        with open(path, 'rb') as f:
            head = f.read(4)
    except OSError:
        return None
    img = None
    if head[:3] == b'TBX':
        try:
            from terrain_texture_painter import _load_xbt, _dds_to_pil
        except Exception:
            from canvas.terrain_texture_painter import _load_xbt, _dds_to_pil
        dds, _ = _load_xbt(path)
        if dds is not None:
            img = _dds_to_pil(dds)
    else:
        from PIL import Image
        try:
            img = Image.open(path)
            img.load()
        except Exception:
            img = None
    if img is None:
        return None
    img = img.convert('RGB')
    if size:
        from PIL import Image
        img = img.resize((size, size), Image.LANCZOS)
    return np.asarray(img)


def load_layers(game_xml_path, data_roots, max_layers=MAX_MASK_LAYERS, size=256):
    """Load the first *max_layers* terrain detail textures from a map's
    .game.xml <Layers> block (text or FC2-binary), resolving each Texture path
    against *data_roots*. Returns an ordered list of {'img','tiling','name'};
    index i aligns with mask channel i (R,G,B). A layer whose texture can't be
    found becomes a neutral-grey placeholder so channel alignment is preserved.
    Returns [] if nothing usable."""
    if not game_xml_path or not os.path.isfile(game_xml_path):
        return []
    root = _parse_game_xml(game_xml_path)
    if root is None:
        return []
    lys = root.find('Layers')
    if lys is None:
        return []
    layer_els = [l for l in lys.findall('Layer')
                 if (l.get('Texture') or '').lower().endswith('.xbt')][:max_layers]
    if not layer_els:
        return []
    out = []
    for lay in layer_els:
        p = _resolve_texture(lay.get('Texture'), data_roots)
        img = _load_xbt_rgb(p, size) if p else None
        if img is None:
            img = np.full((8, 8, 3), 128, np.uint8)  # placeholder keeps alignment
        try:
            tiling = float(lay.get('Tiling', 16) or 16)
        except ValueError:
            tiling = 16.0
        out.append({'img': img, 'tiling': tiling, 'name': lay.get('Name') or '?'})
    # if every layer was a placeholder, blending adds nothing
    if all(l['img'].shape[0] == 8 for l in out):
        return []
    return out


def _atlas_sibling(diffuse_path, suffix):
    """Given .../atlasN_<something>.xbt, find the sibling atlasN_<suffix>.xbt."""
    d = os.path.dirname(diffuse_path)
    m = re.match(r'(atlas\d+)', os.path.basename(diffuse_path), re.IGNORECASE)
    if not m:
        return None
    for ext in ('.xbt', '.dds'):
        cand = os.path.join(d, f"{m.group(1)}_{suffix}{ext}")
        if os.path.isfile(cand):
            return cand
    return None


def _crop_quad(a, sub):
    """2x2 quadrant: 0=TL 1=TR 2=BL 3=BR."""
    h, w = a.shape[:2]
    hh, hw = h // 2, w // 2
    r, c = sub // 2, sub % 2
    return a[r * hh:(r + 1) * hh, c * hw:(c + 1) * hw]


def _find_atlas(sdat_dir, atlas_num, suffixes):
    for suf in suffixes:
        for ext in ('.xbt', '.dds', '.png', '.tga'):
            p = os.path.join(sdat_dir, f"atlas{atlas_num}_{suf}{ext}")
            if os.path.isfile(p):
                return p
    return None


def build_sector_tile(sdat_dir, atlas_num, sub_sector, layers, out_size, cache,
                      **kw):
    """Composite one sector's in-game tile from the original sdat atlas files.

    Loads atlas{N}_{diffuse,mask,color}.xbt from *sdat_dir*, crops the sector
    quadrant, and blends the detail *layers*. *cache* is a dict (path -> RGB
    ndarray) the caller owns for the life of a bake. Returns (out,out,3) uint8,
    or None to signal 'fall back to the old diffuse-only path'."""
    if not layers or not sdat_dir:
        return None

    def _atlas(path):
        if path is None:
            return None
        if path not in cache:
            cache[path] = _load_xbt_rgb(path)
        return cache[path]

    diff = _atlas(_find_atlas(sdat_dir, atlas_num, ('diffuse', 'd', 'color')))
    if diff is None:
        return None
    mask = _atlas(_find_atlas(sdat_dir, atlas_num, ('mask',)))
    color = _atlas(_find_atlas(sdat_dir, atlas_num, ('color',)))
    d = _crop_quad(diff, sub_sector)
    m = _crop_quad(mask, sub_sector) if mask is not None else None
    c = _crop_quad(color, sub_sector) if color is not None else None
    return composite_sector(m, c, None, layers, out_size, diffuse=d, **kw)
