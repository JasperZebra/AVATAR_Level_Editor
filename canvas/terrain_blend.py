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

Layer SELECTION (which layer applies where) is reconstructed from each
<Layer>'s own MinSlope/MaxSlope/AltStart/AltEnd rule, evaluated against the
REAL sector heightmap — not by guessing a mask-channel<->layer mapping.
Confirmed via a Ghidra decompile of the retail engine binary (see AGENTS.md
"Tiling fix" section): the runtime never reads MinSlope/MaxSlope/AltStart/
AltEnd/ProjAxis/Smooth (zero literal occurrences in ~61k functions) — these
are bake-time-only concepts the ORIGINAL exporter used once to build the
mask/diffuse atlas. So we redo that same bake-time computation ourselves
against the map's own .game.xml + its own heightmap, which is unambiguous,
instead of assuming mask R/G/B map to the first 3 <Layers> in document order
(which is not documented anywhere and was very likely wrong — visible as
"layers on top of ones they shouldn't be" reports). Layers whose rule allows
them EVERYWHERE (e.g. two different "flat ground" layers with identical
full-range rules) can't be told apart by rules alone; for that subgroup only,
the painted mask still breaks the tie. Pure numpy, fully vectorised, no
Qt/GL — callable from the CPU 2D path and the GLTF bake path alike.
"""

import os
import re
import numpy as np

# Tunables (kept here so both renderers share one look)
# NOTE: these were previously dead (composite_sector had its own separate
# hardcoded defaults, 0.8/1.0, that nothing overrode — see AGENTS.md "dark
# spots" fix). The look the user actually approved of was produced by THOSE
# values, not by tuning attempts made while the dead-constant bug was still
# live. Keep these matched to that approved look; only the per-layer self-
# normalisation in composite_sector (not a brightness bump) should fix uneven
# darkness — a global brightness increase on top made everything look washed
# out/"fake" instead.
DEFAULT_DETAIL_STRENGTH = 0.8    # 0 → baked diffuse only; 1 → detail fully recolours
DEFAULT_BRIGHTNESS = 1.0
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


def _resize_smooth(a, size):
    """Bilinear resize (float, (H,W,3)) via PIL — smooth splat/colour transitions
    so layer boundaries don't come out blocky/harsh."""
    try:
        from PIL import Image
        im = Image.fromarray(np.clip(a * 255.0, 0, 255).astype(np.uint8))
        im = im.resize((size, size), Image.BILINEAR)
        return np.asarray(im).astype(np.float32) / 255.0
    except Exception:
        return _resize_nn(a, size)


def _resize_1ch(a, size, lo, hi):
    """Bilinear resize a single-channel float array (e.g. slope in degrees,
    altitude 0..255) to size×size, preserving its original value range."""
    rng = max(hi - lo, 1e-6)
    norm = np.clip((a - lo) / rng, 0.0, 1.0)
    rgb = np.stack([norm, norm, norm], axis=-1)
    out = _resize_smooth(rgb, size)[:, :, 0]
    return out * rng + lo


_TILE_PREFILTER_CACHE = {}
# Never collapse a tiled detail texture's swatch below this many pixels (keeps
# some real grain instead of homogenising to a flat blob — see _tile_sample).
# Was 64: at production tile size that made high-Tiling layers show fewer,
# much LARGER repeats than nominal — big enough to read as blotchy/chunky
# "rough" patches rather than fine ground texture. Lowered to 24 — still well
# above naive collapse-to-one-pixel-per-repeat, but small enough that the
# grain stays fine at the scale we actually bake at.
_MIN_TILE_SWATCH_PX = 24


def _feather_seam_edges(small, margin_frac=0.15, h_target=None, v_target=None):
    """Blend a swatch's edges toward a target profile so PLAIN (non-mirrored)
    wraparound tiling doesn't show a hard seam.

    For each axis, the outer `margin_frac` band on BOTH edges is cross-faded
    toward a target value, tapering back to the original content inward — so
    the two edge columns/rows converge to nearly the same value right at the
    boundary (where tile N's right edge meets tile N+1's left edge), while
    the interior is untouched. This is the standard "make seamless" texture
    trick (offset-and-blend, done here directly on the edges since we don't
    need the interior seam moved).

    `h_target`/`v_target` (each (h,3)/(w,3), or None): the per-row/per-column
    value edges converge toward. Pass None for the classic single-swatch case
    (converge toward THIS swatch's own left/right or top/bottom average).
    Pass a SHARED profile (computed once, e.g. from a reference swatch) when
    feathering multiple variants of the same layer — this is required for
    `_variant_tile` to mix different variants adjacently without a seam:
    two variants that each converge toward their OWN average would meet at
    a MISMATCHED boundary (different crops → different average colour);
    converging toward one shared profile makes every variant's edge equal
    the same value, so any pair of variants tiles seamlessly.

    Why not mirror-tiling (the previous approach): mirror-tiling GUARANTEES
    a seamless border only via strictly ALTERNATING flip states between
    neighbours — that alternation is structurally required, not incidental,
    and it makes every 2x2 group of tiles perfectly mirror-symmetric about
    its center. That symmetry is highly perceptible as a kaleidoscope/grid
    pattern to the human eye regardless of how much real detail is inside
    each tile (reported as "I can see a pattern in the terrain"). A
    seamless-edged swatch tiled PLAINLY has no such forced symmetry.
    """
    h, w = small.shape[:2]
    out = small.astype(np.float32).copy()

    ht = h_target if h_target is not None else 0.5 * (out[:, 0, :] + out[:, w - 1, :])
    mx = max(1, int(round(w * margin_frac)))
    for i in range(mx):
        t = (i + 1) / (mx + 1)
        out[:, i, :] = out[:, i, :] * t + ht * (1 - t)
        out[:, w - 1 - i, :] = out[:, w - 1 - i, :] * t + ht * (1 - t)

    vt = v_target if v_target is not None else 0.5 * (out[0, :, :] + out[h - 1, :, :])
    my = max(1, int(round(h * margin_frac)))
    for j in range(my):
        t = (j + 1) / (my + 1)
        out[j, :, :] = out[j, :, :] * t + vt * (1 - t)
        out[h - 1 - j, :, :] = out[h - 1 - j, :, :] * t + vt * (1 - t)

    return np.clip(out, 0, 255)


def _plain_tile(small, reps):
    """Tile (h,w,3) *reps* times per axis via plain wraparound (np.tile) — safe
    to use once `small`'s own edges have been made seamless by
    `_feather_seam_edges`; unlike mirror-tiling this introduces no forced
    kaleidoscope symmetry between neighbouring copies."""
    return np.tile(small, (reps, reps, 1))


_NUM_TILE_VARIANTS = 6   # distinct swatches sourced per layer — see _variant_tile.
# Swept 1/3/6/9 side by side: 1->3 already breaks up the worst uniformity, 3->6
# adds meaningfully more organic variety, 6->9 was diminishing returns. 6 is
# the balance point.


def _variant_tile(variants, reps):
    """Assemble a reps×reps grid where each cell picks one of `variants`
    (each already made edge-seamless) via a fixed non-alternating hash of its
    (row,col) — NOT a checkerboard, so no two cells are forced into a
    periodic relationship the eye can lock onto. Any variant can sit next to
    any other because every variant's OWN edges already match every other
    variant's edges (they all converge to the same per-edge running average
    inside `_feather_seam_edges`), so plain adjacency stays seamless."""
    n = len(variants)
    rows = []
    for r in range(reps):
        row_tiles = [variants[(r * 2654435761 + c * 40503) % n] for c in range(reps)]
        rows.append(np.concatenate(row_tiles, axis=1))
    return np.concatenate(rows, axis=0)


def _tile_sample(img, size, repeats):
    """Sample (h,w,3) float 0..1 tiled *repeats* times across a size×size output.

    A real in-game terrain samples the tiled detail texture per-pixel with full
    GPU mipmapping; our 2D map and 3D bake are single static images, so at a
    high Tiling value (e.g. 16-20 repeats crammed into a ~160px sector tile,
    ~8-10px per repeat) naive nearest-neighbour indexing aliases into a harsh,
    blotchy pattern — it discards almost all of the source texture's pixels.

    Fix: BOX-downsample (true area average — no ringing) the source to a
    swatch size, make the swatch's own edges seamless (`_feather_seam_edges`),
    THEN tile it PLAINLY (`_plain_tile`). Two things had to be solved:

    1. The swatch is NOT simply size/repeats (one cell per nominal repeat).
       Collapsing the source all the way down to a near-uniform per-repeat
       blob homogenises away all real texture variation — floor the swatch
       size well above the nominal per-repeat size (`_MIN_TILE_SWATCH_PX`) so
       it keeps real detail. This means very high Tiling values show FEWER,
       LARGER, more detailed repeats than the nominal count (a deliberate
       trade-off: looks like real repeated ground texture, not a flat blob).
    2. A raw crop's opposite edges don't match, so naive wraparound tiling
       shows a hard seam. The first fix for that was mirror-tiling — but
       mirror-tiling only guarantees a seamless border via strictly
       ALTERNATING flip states between neighbours, and that forced
       alternation makes every 2x2 group of tiles perfectly mirror-symmetric
       about its center — highly perceptible to the eye as a kaleidoscope/
       grid pattern no matter how much detail is inside each tile (reported
       as "I can see a pattern in the terrain"). `_feather_seam_edges` blends
       the swatch's own opposite edges toward each other instead, so plain
       (non-mirrored) tiling has no seam AND no forced symmetry.
    3. Even seamless, a SINGLE swatch repeated identically is still very
       perceptible as tiling once the repeat count is low (e.g. Tiling=6 —
       only ~6 identical copies span a sector; reported as "some spots are
       too rough looking, like they are not tiled correct"). No amount of
       extra resolution fixes this — it is genuinely the same content 6
       times. Fix: derive `_NUM_TILE_VARIANTS` swatches from DIFFERENT crop
       offsets of the source (real spatial variation, not the same content
       re-filtered), each feathered toward ONE SHARED edge profile (see
       `_feather_seam_edges` h_target/v_target — required so any pair of
       variants can sit adjacent without a seam, since each converging to
       its OWN average would leave mismatched brightness between crops), and
       assemble via `_variant_tile`'s non-alternating placement. Breaks "one
       tile repeated in a perfect grid" into "a short, non-periodic mix of a
       few different tiles" — reads as organic repetition instead of a
       graphic pattern.
    """
    from PIL import Image
    h, w = img.shape[:2]
    cell = max(2, int(round(size / max(repeats, 0.001))))
    cell = max(cell, min(_MIN_TILE_SWATCH_PX, max(h, w)))
    cell = min(cell, max(h, w))  # never upsample past native resolution

    key = (id(img), h, w, cell)
    variants = _TILE_PREFILTER_CACHE.get(key)
    if variants is None:
        src_u8 = np.clip(img * 255.0, 0, 255).astype(np.uint8)
        n = _NUM_TILE_VARIANTS if min(h, w) >= cell * 2 else 1  # tiny sources: one variant only
        boxed_all = []
        for k in range(n):
            oy = (k * h) // max(n, 1)
            ox = (k * w) // max(n, 1)
            rolled = np.roll(np.roll(src_u8, -oy, axis=0), -ox, axis=1)
            boxed_all.append(np.asarray(Image.fromarray(rolled).resize((cell, cell), Image.BOX)))
        ref = boxed_all[0].astype(np.float32)
        h_target = 0.5 * (ref[:, 0, :] + ref[:, -1, :])
        v_target = 0.5 * (ref[0, :, :] + ref[-1, :, :])
        variants = [
            _feather_seam_edges(b, h_target=h_target, v_target=v_target).astype(np.uint8)
            for b in boxed_all
        ]
        if len(_TILE_PREFILTER_CACHE) > 64:
            _TILE_PREFILTER_CACHE.clear()
        _TILE_PREFILTER_CACHE[key] = variants

    reps = (size // cell) + 2
    tiled = (_plain_tile(variants[0], reps) if len(variants) == 1
             else _variant_tile(variants, reps))[:size, :size]
    return tiled.astype(np.float32) / 255.0


def _smooth_gate(x, lo, hi, feather, full_range):
    """Soft step: ~1 where lo<=x<=hi, fading to 0 over *feather* outside each
    bound. A bound at the natural extreme (lo<=0, or hi>=full_range) is treated
    as 'no gate on that side' — e.g. MinSlope=0,MaxSlope=90 is fully unrestricted."""
    w = np.ones_like(x, dtype=np.float32)
    fw = max(feather, 1e-3)
    if lo > 0:
        w = w * np.clip((x - (lo - feather)) / fw, 0.0, 1.0)
    if hi < full_range:
        w = w * np.clip(((hi + feather) - x) / fw, 0.0, 1.0)
    return w


def _layer_is_unrestricted(layer):
    """True if the layer's rule allows it everywhere (no real slope/altitude
    gate) — such layers can only be told apart from each other by the mask."""
    return (layer.get('min_slope', 0) <= 0 and layer.get('max_slope', 90) >= 90
            and layer.get('alt_start', 0) <= 0 and layer.get('alt_end', 255) >= 255)


def rule_weights(heightmap, layers, out_size, world_min_h, world_max_h,
                 meters_per_step=1.0, mask=None, underwater_mask=None):
    """Per-texel, per-layer weight in [0,1] (NOT yet normalised) derived from
    each layer's own MinSlope/MaxSlope/AltStart/AltEnd rule evaluated against
    the sector's real heightmap — see module docstring for why this replaces
    guessing a mask-channel<->layer mapping. `Smooth` narrows/widens the
    transition feather (Smooth="0" layers, e.g. cliffs, cut in faster).

    `underwater_mask` (optional (H,W) bool, native heightmap resolution): the
    REAL per-vertex "underwater / at water level" flag recovered from the
    sector's own .csdat file (byte[3] — a clean bimodal split, 0-95 dry land
    vs 224-239 underwater, confirmed 99.3-99.9% agreement with
    height<=water_height on real sectors; see AGENTS.md "byte3 deep dive").
    For any layer whose rule is clearly "underwater/beach" (AltEnd<=10, e.g.
    Underwater_Z's AltStart=0,AltEnd=0), this REPLACES the synthetic global-
    height-range altitude gate — the real signal is computed by the original
    exporter per-sector against that sector's OWN water body, so unlike a
    single global min/max normalisation it correctly handles multiple water
    bodies sitting at different absolute elevations across one map.

    Layers that are unrestricted (apply everywhere) are further weighted, among
    themselves only, by the painted splat mask (channel order) — their rule
    alone can't distinguish e.g. two different "flat ground" layers.

    Returns (out_size,out_size,len(layers)) float32.
    """
    hm = np.asarray(heightmap, dtype=np.float32)
    gy, gx = np.gradient(hm, max(meters_per_step, 1e-3))
    slope_deg = np.degrees(np.arctan(np.sqrt(gx * gx + gy * gy)))
    rng = max(world_max_h - world_min_h, 1e-3)
    alt = np.clip((hm - world_min_h) / rng * 255.0, 0.0, 255.0)

    o = int(out_size)
    slope_r = _resize_1ch(slope_deg, o, 0.0, 90.0)
    alt_r = _resize_1ch(alt, o, 0.0, 255.0)
    underwater_r = (_resize_1ch(underwater_mask.astype(np.float32), o, 0.0, 1.0)
                    if underwater_mask is not None else None)

    weights = np.zeros((o, o, len(layers)), np.float32)
    unrestricted = []
    for i, lay in enumerate(layers):
        # Even Smooth="0" layers (cliffs) still need a real transition band —
        # too narrow a feather reads as an unblended hard graphic edge where
        # the layer boundary happens to fall (looked like an abrupt dark/light
        # seam rather than a natural cliff line).
        smooth = lay.get('smooth', True)
        sf = 6.0 if smooth else 3.5
        af = 14.0 if smooth else 8.0
        w_slope = _smooth_gate(slope_r, lay.get('min_slope', 0), lay.get('max_slope', 90), sf, 90.0)
        if underwater_r is not None and lay.get('alt_end', 255) <= 10:
            w_alt = underwater_r
        else:
            w_alt = _smooth_gate(alt_r, lay.get('alt_start', 0), lay.get('alt_end', 255), af, 255.0)
        weights[:, :, i] = w_slope * w_alt
        if _layer_is_unrestricted(lay):
            unrestricted.append(i)

    # Triplanar siblings: two layers with the SAME slope/altitude rule that
    # differ only by ProjAxis 0 (X) vs 1 (Y) — e.g. mridge's Rock_X/Rock_Y,
    # both MinSlope=55..90, same texture, different cliff-face UV projection
    # — are alternate projections of ONE material, not independently
    # mask-competing layers (confirmed: a sector's .csdat file's byte[2]
    # matches the standard-encoded tangent-space normal X component computed
    # from this same heightmap gradient almost exactly, corr=0.979, mean
    # error 5.8/255 — so the engine really does have a per-pixel surface-
    # facing direction to pick a projection axis with; byte[3] turned out to
    # be a SEPARATE per-vertex underwater flag, see `underwater_mask` above).
    # Blending both unconditionally (the old behaviour, since they share one
    # rule) mixed two different UV orientations of the same rock texture
    # everywhere both were active — read as blurry/incoherent, not a clean
    # cliff face. Select one via whichever axis the LOCAL normal faces more.
    by_rule = {}
    for i, lay in enumerate(layers):
        rule_key = (lay.get('min_slope', 0), lay.get('max_slope', 90),
                   lay.get('alt_start', 0), lay.get('alt_end', 255))
        by_rule.setdefault(rule_key, []).append(i)
    for rule_key, idxs in by_rule.items():
        x_idxs = [i for i in idxs if layers[i].get('proj_axis') == 0]
        y_idxs = [i for i in idxs if layers[i].get('proj_axis') == 1]
        if x_idxs and y_idxs:
            norm3 = np.sqrt(gx * gx + gy * gy + 1.0)
            nx_r = _resize_1ch(-gx / norm3, o, -1.0, 1.0)
            ny_r = _resize_1ch(-gy / norm3, o, -1.0, 1.0)
            ax, ay = np.abs(nx_r), np.abs(ny_r)
            fx = ax / (ax + ay + 1e-6)
            fy = 1.0 - fx
            for i in x_idxs:
                weights[:, :, i] = weights[:, :, i] * fx
            for i in y_idxs:
                weights[:, :, i] = weights[:, :, i] * fy

    if len(unrestricted) > 1:
        if mask is not None:
            m = _resize_smooth(_to_float_rgb(mask), o)
            s = m.sum(axis=2, keepdims=True)
            m = np.divide(m, s, out=m.copy(), where=s > 1e-3)
            for k, i in enumerate(unrestricted[:3]):
                weights[:, :, i] = weights[:, :, i] * m[:, :, k]
        # The mask has only 3 usable channels (R,G,B — see module docstring),
        # so at most 3 unrestricted layers can be told apart at all. Beyond
        # that there is NO real per-texel signal to place them; leaving them
        # at flat full weight everywhere would just blend in arbitrary noise
        # across the whole map (this is what maps with many same-range layers,
        # e.g. FC2 jungle maps, would otherwise hit) — drop them instead.
        for i in unrestricted[3:]:
            weights[:, :, i] = 0.0

    return weights


def composite_sector(mask, color, shadow, layers, out_size, *,
                     diffuse=None, detail_strength=DEFAULT_DETAIL_STRENGTH,
                     tiling_scale=DEFAULT_TILING_SCALE, brightness=DEFAULT_BRIGHTNESS,
                     heightmap=None, world_min_h=0.0, world_max_h=1.0,
                     meters_per_step=1.0, underwater_mask=None):
    """Composite one sector's in-game-look tile.

    The baked *diffuse* atlas is the colour/brightness anchor (it is the game's
    own low-frequency terrain colour); the tiled detail textures only add
    high-frequency variation on top, so the result keeps correct large-scale
    colour and can't drift far even if the mask→layer mapping is imperfect:

        detail = Σ normalize(mask)_i · layer_i(uv · Tiling_i)     # high-freq
        out    = base · ((1-s) + s · detail / mean(detail)) · shadow · brightness

    where base = diffuse (preferred) or color, and s = *detail_strength*
    (0 → just the baked look; 1 → detail fully recolours).

    Layer SELECTION: when *heightmap* is given, weights come from each layer's
    own rule (MinSlope/MaxSlope/AltStart/AltEnd) evaluated against the real
    heightmap via `rule_weights()` — ALL layers participate (not capped at 3),
    since we're no longer limited to 3 mask channels. Without a heightmap
    (legacy/defensive path), falls back to treating mask R/G/B as weights for
    the first 3 layers in document order.

    mask/color/shadow/diffuse : (H,W,3) atlas quadrants (uint8/float) or None.
    layers : list of {'img','tiling','min_slope','max_slope','alt_start',
             'alt_end','smooth'} from `load_layers()`.
    Returns (out_size, out_size, 3) uint8.
    """
    o = int(out_size)
    base = diffuse if diffuse is not None else color
    base_f = _resize_smooth(_to_float_rgb(base), o) if base is not None else None

    if not layers:
        if base_f is None:
            return np.zeros((o, o, 3), np.uint8)
        out = base_f * brightness
        if shadow is not None:
            out = out * _resize_nn(_to_float_rgb(shadow), o)
        return np.clip(out * 255.0, 0, 255).astype(np.uint8)

    if heightmap is not None:
        active = layers
        weights = rule_weights(heightmap, active, o, world_min_h, world_max_h,
                               meters_per_step, mask=mask, underwater_mask=underwater_mask)
        s = weights.sum(axis=2, keepdims=True)
        w = np.divide(weights, s, out=np.zeros_like(weights), where=s > 1e-3)
        no_layer = (s[:, :, 0] <= 1e-3)
        if no_layer.any():
            w[no_layer, 0] = 1.0   # nothing matched (shouldn't happen) -> base layer
    else:
        active = layers[:MAX_MASK_LAYERS]
        if mask is not None:
            # smooth (bilinear) so splat weights blend across layer boundaries
            w = _resize_smooth(_to_float_rgb(mask), o)
            s = w.sum(axis=2, keepdims=True)
            w = np.divide(w, s, out=w.copy(), where=s > 1e-3)
        else:
            w = np.zeros((o, o, 3), np.float32)
            w[:, :, 0] = 1.0

    imgs = [_to_float_rgb(l['img']) for l in active]
    tilings = [max(1.0, float(l.get('tiling', 1)) * tiling_scale) for l in active]

    detail = np.zeros((o, o, 3), np.float32)
    for i, (img, tl) in enumerate(zip(imgs, tilings)):
        wi = w[:, :, i:i + 1]
        if wi.max() <= 1e-4:
            continue   # this layer's rule never matches in this sector — skip its tile
        tile = _tile_sample(img, o, tl)
        # Normalise EACH layer to its OWN mean before blending — a texture
        # that's locally darker than its neighbours (e.g. a rock cliff patch
        # sitting in mostly-grass) must be compared to ITS OWN brightness, not
        # a mismatched whole-tile average dominated by a different, lighter
        # texture. Comparing against a shared global mean crushed the darker
        # layer toward the modulation floor wherever it was a minority in the
        # tile — showing up as unwanted dark patches with a harsh cutoff at
        # the layer boundary (looked "not blended").
        tile_mean = tile.reshape(-1, 3).mean(axis=0) + 1e-4
        detail += wi * (tile / tile_mean)

    if base_f is None:
        out = detail
    else:
        # Each layer's contribution already averages ~1 (self-normalised
        # above), so the weighted sum stays near 1 without a further global
        # divide. Still clamp so extremes can't blow out the baked colour.
        dn = np.clip(detail, 0.5, 1.6)
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


DEFAULT_MAX_LAYERS = 12   # bound bake time on maps with many layers (FC2: up to 44)


def load_layers(game_xml_path, data_roots, max_layers=DEFAULT_MAX_LAYERS, size=256):
    """Load up to *max_layers* terrain detail textures + their placement RULES
    from a map's .game.xml <Layers> block (text or FC2-binary), resolving each
    Texture path against *data_roots*.

    Returns an ordered list of dicts: {'img','tiling','name','min_slope',
    'max_slope','alt_start','alt_end','smooth'} — consumed by rule_weights()
    to decide WHERE each layer applies (see module docstring). A layer whose
    texture can't be resolved on disk is skipped (no mask-channel alignment to
    preserve now that selection is rule-based, not channel-order-based).
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
                 if (l.get('Texture') or '').lower().endswith('.xbt')]
    if not layer_els:
        return []

    def _f(lay, name, default):
        try:
            return float(lay.get(name, default))
        except (TypeError, ValueError):
            return float(default)

    out = []
    skipped = 0
    for lay in layer_els[:max_layers]:
        p = _resolve_texture(lay.get('Texture'), data_roots)
        img = _load_xbt_rgb(p, size) if p else None
        if img is None:
            skipped += 1
            continue
        tiling = _f(lay, 'Tiling', 16.0)
        out.append({
            'img': img, 'tiling': tiling if tiling > 0 else 16.0,
            'name': lay.get('Name') or '?',
            'min_slope': _f(lay, 'MinSlope', 0.0), 'max_slope': _f(lay, 'MaxSlope', 90.0),
            'alt_start': _f(lay, 'AltStart', 0.0), 'alt_end': _f(lay, 'AltEnd', 255.0),
            'smooth': lay.get('Smooth', '1') != '0',
            'proj_axis': int(_f(lay, 'ProjAxis', 2)),
        })
    if len(layer_els) > max_layers:
        print(f"[terrain_blend] {len(layer_els)} layers defined in {os.path.basename(game_xml_path)}; "
              f"using the first {max_layers}")
    if skipped:
        print(f"[terrain_blend] {skipped} layer texture(s) could not be resolved on disk — skipped")
    return out


def load_meters_per_step(game_xml_path, grid_size=65, default=1.0):
    """World meters per heightmap grid step, from <Grids><GridMapSectors
    Granularity=.../> (sector world size) — needed to compute a real slope
    ANGLE from the heightmap gradient. Falls back to *default* (1.0, matching
    the common Granularity=64 / grid_size=65 case) if unavailable."""
    root = _parse_game_xml(game_xml_path)
    if root is None:
        return default
    grids = root.find('Grids')
    if grids is None:
        return default
    gm = grids.find('GridMapSectors')
    if gm is None or not gm.get('Granularity'):
        return default
    try:
        granularity = float(gm.get('Granularity'))
        return granularity / max(grid_size - 1, 1)
    except ValueError:
        return default


def compute_height_range(heightmaps):
    """(min,max) world height across an iterable of (h,w) heightmap arrays —
    the altitude-rule normalisation reference. (0.0, 1.0) if none are usable."""
    lo = hi = None
    for hm in heightmaps:
        if hm is None or getattr(hm, 'size', 0) == 0:
            continue
        mn, mx = float(np.min(hm)), float(np.max(hm))
        lo = mn if lo is None else min(lo, mn)
        hi = mx if hi is None else max(hi, mx)
    if lo is None:
        return 0.0, 1.0
    return lo, hi


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
    """2x2 quadrant: 0=TL 1=TR 2=BL 3=BR.

    NOTE: tried adding a per-quadrant mirror+rot90 here based on a slope-vs-
    mask correlation measurement (individual sectors did correlate better in
    isolation — e.g. sector 0 went -0.10 -> +0.63). REVERTED: rendering the
    full map with it showed every sector visibly disconnected from its
    neighbours — ridgelines that previously flowed continuously across
    sector boundaries fragmented into a hard checkerboard. The per-sector
    correlation test optimised something real but too narrow (one sector's
    alignment to ITS OWN heightmap) while ignoring the thing that actually
    matters for a coherent map: adjacent sectors' crops staying mutually
    consistent. The untransformed crop is what actually tiles seamlessly —
    keep it as-is unless a future fix demonstrably preserves cross-sector
    continuity, not just single-sector slope correlation.
    """
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
    ndarray) the caller owns for the life of a bake. Pass `heightmap=`,
    `world_min_h=`, `world_max_h=`, `meters_per_step=` (forwarded via **kw to
    composite_sector) to select layers by their real MinSlope/MaxSlope/
    AltStart/AltEnd rule instead of the legacy mask-channel-order guess.
    Returns (out,out,3) uint8, or None to signal 'fall back to the old
    diffuse-only path'."""
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
