"""Terrain texture painter — loads Avatar diffuse atlas XBT files, stitches them
into a combined RGBA texture, handles paint strokes, and saves back to XBT."""

import os
import sys
import glob
import struct
import subprocess
import tempfile
import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# XBT helpers
# ---------------------------------------------------------------------------

def _find_texconv():
    """Locate texconv.exe in the tools/ directory."""
    candidates = [
        os.path.join(os.path.dirname(__file__), '..', 'tools', 'texconv.exe'),
        os.path.join(os.path.dirname(sys.executable), 'tools', 'texconv.exe'),
    ]
    for p in candidates:
        p = os.path.normpath(p)
        if os.path.exists(p):
            return p
    return None


def _load_xbt(path):
    """Read an XBT file. Returns (dds_bytes, header_bytes) or (None, None)."""
    try:
        with open(path, 'rb') as f:
            data = f.read()
        if data[:4] != b'TBX\x00':
            return None, None
        dds_start = data.find(b'DDS ')
        if dds_start == -1:
            return None, None
        return data[dds_start:], data[:dds_start]
    except Exception as e:
        print(f"[TexturePaint] Failed to read {path}: {e}")
        return None, None


def _fourcc_from_dds(dds_bytes):
    """Read DXT FourCC from DDS header at offset 84 (4 bytes)."""
    if len(dds_bytes) >= 88:
        try:
            cc = dds_bytes[84:88].decode('ascii').rstrip('\x00')
            return cc if cc else 'DXT1'
        except Exception:
            pass
    return 'DXT1'


def _dds_dims(dds_bytes):
    """Read (width, height) from DDS header bytes (offsets 16 and 12)."""
    if len(dds_bytes) >= 20:
        h = struct.unpack_from('<I', dds_bytes, 12)[0]
        w = struct.unpack_from('<I', dds_bytes, 16)[0]
        if w > 0 and h > 0:
            return w, h
    return None, None


def _dds_to_pil(dds_bytes):
    """Convert raw DDS bytes to a PIL Image."""
    import io
    try:
        img = Image.open(io.BytesIO(dds_bytes))
        img.load()
        return img.convert('RGBA')
    except Exception:
        pass
    # Fallback: write to temp file then load
    try:
        with tempfile.NamedTemporaryFile(suffix='.dds', delete=False) as f:
            f.write(dds_bytes)
            tmp = f.name
        img = Image.open(tmp)
        img.load()
        img = img.convert('RGBA')
        os.unlink(tmp)
        return img
    except Exception as e:
        print(f"[TexturePaint] DDS load failed: {e}")
        return None


def _decompress_dds_with_texconv(dds_bytes, texconv_path):
    """Decompress DDS bytes to a PIL RGBA Image using texconv -ft png."""
    try:
        cf = 0x08000000 if sys.platform == 'win32' else 0
        with tempfile.TemporaryDirectory() as td:
            dds_in = os.path.join(td, 'in.dds')
            with open(dds_in, 'wb') as f:
                f.write(dds_bytes)
            result = subprocess.run(
                [texconv_path, '-ft', 'png', '-y', '-o', td, dds_in],
                capture_output=True, timeout=30, creationflags=cf
            )
            png_out = os.path.join(td, 'in.png')
            if os.path.exists(png_out):
                img = Image.open(png_out)
                img.load()
                return img.convert('RGBA')
            stderr = result.stderr.decode(errors='ignore')
            print(f"[TexturePaint] texconv decompress stderr: {stderr[:200]}")
    except Exception as e:
        print(f"[TexturePaint] texconv decompress failed: {e}")
    return None


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class TerrainTexturePainter:
    """Loads, displays, paints on, and saves terrain diffuse atlas XBT textures."""

    # Maximum tile size (pixels per sector side in the combined texture)
    MAX_TILE_PX = 256

    def __init__(self):
        self._sdat_dir = None
        self._sectors_x = 0
        self._sectors_y = 0
        self._tile_w = self.MAX_TILE_PX
        self._tile_h = self.MAX_TILE_PX
        self.combined_tex = None          # (H, W, 4) uint8 RGBA numpy array
        self._atlas_sorted_paths = []     # sorted by atlas file number
        self._atlas_headers = {}          # atlas_path -> raw XBT header bytes
        self._atlas_fourccs = {}          # atlas_path -> 'DXT1'/'DXT5'/etc.
        self._dirty_atlas_indices = set()
        self._tile_to_atlas = {}          # (col, display_row) -> atlas_idx
        self._painted_world_tiles = set() # tiles with actual paint strokes

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load(self, sdat_dir, sectors_x, sectors_y, force_suffix=None):
        """Discover and load atlas XBT files. Returns True on success.

        force_suffix: if given (e.g. '_mask'), only search that suffix.
        Otherwise tries '_mask', '_diffuse', '_color' in priority order.
        """
        self._sdat_dir = sdat_dir
        self._sectors_x = sectors_x
        self._sectors_y = sectors_y
        self._dirty_atlas_indices.clear()
        self._tile_to_atlas.clear()
        self._atlas_headers.clear()
        self._atlas_fourccs.clear()
        self._painted_world_tiles.clear()

        # Discover atlas files
        found = []
        search_order = [force_suffix] if force_suffix else ('_mask', '_diffuse', '_color')
        for suffix in search_order:
            for ext in ('.xbt', '.dds'):
                pattern = os.path.join(sdat_dir, f'atlas*{suffix}{ext}')
                found.extend(glob.glob(pattern))
            if found:
                break
        if not found:
            print(f"[TexturePaint] No atlas mask/diffuse/color XBT files in {sdat_dir}")
            return False

        # Sort by numeric atlas index extracted from filename
        found = sorted(set(found), key=self._atlas_num_from_path)
        self._atlas_sorted_paths = found
        print(f"[TexturePaint] Found {len(found)} atlas files")

        # -- Load all atlas images into a temporary cache -------------------
        atlas_cache = {}        # atlas_path -> PIL Image (RGBA) or None
        atlas_raw   = {}        # atlas_path -> dds_bytes (for dimension fallback)
        for path in found:
            dds_bytes, hdr = _load_xbt(path)
            if dds_bytes is None:
                atlas_cache[path] = None
                continue
            img = _dds_to_pil(dds_bytes)
            atlas_cache[path] = img
            atlas_raw[path]   = dds_bytes        # keep for tile-size fallback
            self._atlas_headers[path] = hdr
            self._atlas_fourccs[path] = _fourcc_from_dds(dds_bytes)

        # Determine tile size from the first successfully loaded atlas.
        # If PIL couldn't decode any atlas (DXT not supported), fall back to
        # reading the width/height directly from the DDS header bytes.
        tile_w = tile_h = self.MAX_TILE_PX
        for path in found:
            img = atlas_cache.get(path)
            if img is not None:
                tile_w = min(img.width  // 2, self.MAX_TILE_PX)
                tile_h = min(img.height // 2, self.MAX_TILE_PX)
                break
            raw = atlas_raw.get(path)
            if raw is not None:
                aw, ah = _dds_dims(raw)
                if aw and ah:
                    tile_w = min(aw // 2, self.MAX_TILE_PX)
                    tile_h = min(ah // 2, self.MAX_TILE_PX)
                    print(f"[TexturePaint] Tile size from DDS header: {tile_w}×{tile_h}")
                    break
        self._tile_w = tile_w
        self._tile_h = tile_h

        # Allocate combined texture
        tex_h = sectors_y * tile_h
        tex_w = sectors_x * tile_w
        self.combined_tex = np.zeros((tex_h, tex_w, 4), dtype=np.uint8)
        self.combined_tex[:, :, 3] = 255   # fully opaque default

        # Fill each world tile from its atlas
        missing = 0
        for display_row in range(sectors_y):
            for col in range(sectors_x):
                sector_idx = self._avatar_sector_index(col, display_row, sectors_y)
                atlas_idx  = sector_idx // 4
                sub_sector = sector_idx % 4

                if atlas_idx >= len(found):
                    missing += 1
                    continue

                atlas_path = found[atlas_idx]
                img = atlas_cache.get(atlas_path)
                if img is None:
                    missing += 1
                    continue

                tile = self._crop_tile(img, sub_sector, tile_w, tile_h)
                if tile is None:
                    missing += 1
                    continue

                py = display_row * tile_h
                px = col * tile_w
                self.combined_tex[py:py + tile_h, px:px + tile_w] = tile
                self._tile_to_atlas[(col, display_row)] = atlas_idx

        print(f"[TexturePaint] Combined texture {tex_w}×{tex_h} built "
              f"({sectors_x * sectors_y - missing} / {sectors_x * sectors_y} tiles)")
        return True

    def _atlas_num_from_path(self, path):
        """Extract numeric index from a filename like atlas42_diffuse.xbt."""
        base = os.path.basename(path)
        try:
            return int(''.join(c for c in base.split('_')[0] if c.isdigit()))
        except Exception:
            return 0

    def _avatar_sector_index(self, col, display_row, sectors_y):
        """Avatar Game Layout: 2×2 blocks going down columns first, with 1↔2 swap.
        Ported directly from buddy's terrain viewer (confirmed correct for Avatar)."""
        block_col = col // 2
        block_row = display_row // 2
        within_col = col % 2
        within_row = display_row % 2
        blocks_per_col = sectors_y // 2
        atlas_block = block_col * blocks_per_col + block_row
        base = atlas_block * 4

        # Avatar-specific swap: positions 1 (TR) and 2 (BL) are exchanged
        if within_row == 0 and within_col == 0:
            offset = 0           # TL → stays 0
        elif within_row == 0 and within_col == 1:
            offset = 2           # TR → gets sub_sector 2
        elif within_row == 1 and within_col == 0:
            offset = 1           # BL → gets sub_sector 1
        else:
            offset = 3           # BR → stays 3

        return base + offset

    def _crop_tile(self, img, sub_sector, tile_w, tile_h):
        """Crop one quadrant (Standard layout [0=TL,1=TR,2=BL,3=BR]) from an atlas PIL image."""
        w, h = img.width, img.height
        hw, hh = w // 2, h // 2
        origins = [(0, 0), (hw, 0), (0, hh), (hw, hh)]   # TL TR BL BR
        lx, ly = origins[sub_sector]
        tile = img.crop((lx, ly, lx + hw, ly + hh))
        if tile.width != tile_w or tile.height != tile_h:
            tile = tile.resize((tile_w, tile_h), Image.Resampling.LANCZOS)
        return np.array(tile.convert('RGBA'), dtype=np.uint8)

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paint_at(self, hx, hy, hmap_w, hmap_h, color_rgba, radius_px, strength,
                 stamp_tex=None, shape='circle', tile_size=32, channel=None, feather=0):
        """Paint at heightmap pixel (hx, hy). Returns set of dirty (col, row) tile coords.

        stamp_tex: optional (H, W, 4) uint8 RGBA array; tiles it instead of solid color.
        shape:     'circle' (default Gaussian), 'square', 'diamond', 'triangle'.
        tile_size: how many atlas pixels wide one stamp tile should appear (default 32).
        channel:   if set (0-3), only that RGBA channel is modified — others left intact.
        feather:   0-100; softens brush edges. 0=hard, 100=fully gradient from centre to edge.
        """
        if self.combined_tex is None:
            return set()
        tex_h, tex_w = self.combined_tex.shape[:2]

        # Map heightmap pixel → texture pixel.
        # Use tex_w (not tex_w-1) so that sector boundaries (e.g. hx=64 on a
        # 1025-wide shared-edge heightmap) map to exact tile boundaries in the
        # atlas (e.g. tx=256 for 256-px tiles), not one pixel short.
        scale_x = max(hmap_w - 1, 1)
        scale_y = max(hmap_h - 1, 1)
        tx = min(tex_w - 1, int(hx / scale_x * tex_w))
        ty = min(tex_h - 1, int(hy / scale_y * tex_h))

        # Scale brush radius using the same denominator for consistency
        r = max(1, int(radius_px * tex_w / scale_x))

        # Brush mask — shape determines footprint, strength scales opacity
        d = r * 2 + 1
        xs = np.arange(d, dtype=np.float32) - r
        ys = np.arange(d, dtype=np.float32) - r
        xx, yy = np.meshgrid(xs, ys)
        if shape == 'square':
            mask = np.ones((d, d), dtype=np.float32)
        elif shape == 'diamond':
            mask = np.clip(1.0 - (np.abs(xx) + np.abs(yy)) / max(r, 1), 0.0, 1.0).astype(np.float32)
        elif shape == 'triangle':
            # Upward-pointing triangle: full at bottom row, tip at top centre
            tri = (yy <= r) & (np.abs(xx) <= (r - yy))
            mask = tri.astype(np.float32)
        else:  # 'circle' — soft Gaussian
            sigma = max(r / 3.0, 1.0)
            mask = np.exp(-0.5 * ((xx**2 + yy**2) / sigma**2)).astype(np.float32)

        # Feather: smooth falloff from inner hard region to 0 at edge
        if feather > 0 and r > 1:
            dist = np.sqrt(xx ** 2 + yy ** 2) / float(r)
            inner = max(0.0, 1.0 - feather / 100.0)
            fade = np.clip(1.0 - (dist - inner) / max(1.0 - inner, 0.01), 0.0, 1.0)
            mask = mask * fade.astype(np.float32)

        mask = np.clip(mask * (strength / 100.0), 0.0, 1.0).astype(np.float32)

        # Clip region to texture bounds
        y0, y1 = ty - r, ty + r + 1
        x0, x1 = tx - r, tx + r + 1
        my0 = max(0, -y0);  my1 = d - max(0, y1 - tex_h)
        mx0 = max(0, -x0);  mx1 = d - max(0, x1 - tex_w)
        cy0 = max(0, y0);   cy1 = min(tex_h, y1)
        cx0 = max(0, x0);   cx1 = min(tex_w, x1)
        if cy1 <= cy0 or cx1 <= cx0 or my1 <= my0 or mx1 <= mx0:
            return set()

        m = mask[my0:my1, mx0:mx1, np.newaxis]  # (H, W, 1) alpha blend factor
        src = self.combined_tex[cy0:cy1, cx0:cx1].astype(np.float32)

        if stamp_tex is not None:
            sh, sw = stamp_tex.shape[:2]
            # Scale so that `tile_size` atlas pixels = one full stamp tile.
            # Use absolute atlas coords so the pattern tiles seamlessly across strokes.
            ts = max(1, tile_size)
            ty_idx = (np.arange(cy0, cy1)[:, np.newaxis] * sh // ts) % sh
            tx_idx = (np.arange(cx0, cx1)[np.newaxis, :] * sw // ts) % sw
            target = stamp_tex[ty_idx, tx_idx].astype(np.float32)
            blended = src * (1.0 - m) + target * m
        elif channel is not None:
            # Single-channel mode: only touch channel 0-3, leave all others intact
            blended = src.copy()
            ch_val = float(color_rgba[channel])
            blended[:, :, channel] = src[:, :, channel] * (1.0 - m[:, :, 0]) + ch_val * m[:, :, 0]
        else:
            target = np.broadcast_to(
                np.array(color_rgba[:4], dtype=np.float32), src.shape
            ).copy()
            blended = src * (1.0 - m) + target * m

        self.combined_tex[cy0:cy1, cx0:cx1] = np.clip(blended, 0, 255).astype(np.uint8)

        # Determine which atlas tiles were dirtied.
        # Compute atlas_idx from sector geometry so painting works even when
        # PIL couldn't load the original tiles (leaving _tile_to_atlas empty).
        dirty_tiles = set()
        tc0 = cx0 // self._tile_w;  tc1 = (cx1 - 1) // self._tile_w
        tr0 = cy0 // self._tile_h;  tr1 = (cy1 - 1) // self._tile_h
        for tr in range(tr0, tr1 + 1):
            for tc in range(tc0, tc1 + 1):
                if 0 <= tc < self._sectors_x and 0 <= tr < self._sectors_y:
                    sector_idx = self._avatar_sector_index(tc, tr, self._sectors_y)
                    atlas_idx  = sector_idx // 4
                    if atlas_idx < len(self._atlas_sorted_paths):
                        self._dirty_atlas_indices.add(atlas_idx)
                        self._painted_world_tiles.add((tc, tr))
                dirty_tiles.add((tc, tr))
        return dirty_tiles

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save(self):
        """Save all dirty atlas XBT files. Returns (saved_count, error_paths)."""
        texconv = _find_texconv()
        if texconv:
            print(f"[TexturePaint] Using texconv: {texconv}")
        else:
            print("[TexturePaint] texconv not found — saving as uncompressed DDS")

        saved, errors = 0, []
        for atlas_idx in sorted(self._dirty_atlas_indices):
            ok = self._save_atlas(atlas_idx, texconv)
            if ok:
                saved += 1
            else:
                if atlas_idx < len(self._atlas_sorted_paths):
                    errors.append(self._atlas_sorted_paths[atlas_idx])
        self._dirty_atlas_indices.clear()
        return saved, errors

    def _save_atlas(self, atlas_idx, texconv_path):
        """Reassemble one atlas image and write back to XBT."""
        if atlas_idx >= len(self._atlas_sorted_paths):
            return False
        atlas_path = self._atlas_sorted_paths[atlas_idx]
        header = self._atlas_headers.get(atlas_path)
        fourcc = self._atlas_fourccs.get(atlas_path, 'DXT1')
        if header is None:
            print(f"[TexturePaint] No cached header for {atlas_path}")
            return False

        atlas_img = self._assemble_atlas_image(atlas_idx, texconv_path)
        if atlas_img is None:
            return False

        try:
            cf = 0x08000000 if sys.platform == 'win32' else 0

            with tempfile.TemporaryDirectory() as tmpdir:
                png_path = os.path.join(tmpdir, 'atlas_in.png')
                atlas_img.save(png_path)

                dds_bytes = None

                if texconv_path and os.path.exists(texconv_path):
                    result = subprocess.run(
                        [texconv_path, '-f', fourcc, '-y', '-o', tmpdir, png_path],
                        capture_output=True, timeout=60, creationflags=cf
                    )
                    dds_out = os.path.join(tmpdir, 'atlas_in.dds')
                    if os.path.exists(dds_out):
                        with open(dds_out, 'rb') as f:
                            dds_bytes = f.read()
                    else:
                        stderr = result.stderr.decode(errors='ignore')
                        print(f"[TexturePaint] texconv error: {stderr[:200]}")

                if dds_bytes is None:
                    # Fallback: write uncompressed DDS via PIL
                    dds_fallback = os.path.join(tmpdir, 'atlas_fallback.dds')
                    atlas_img.save(dds_fallback)
                    with open(dds_fallback, 'rb') as f:
                        dds_bytes = f.read()
                    print(f"[TexturePaint] Saved uncompressed DDS for {os.path.basename(atlas_path)}")

                with open(atlas_path, 'wb') as f:
                    f.write(header)
                    f.write(dds_bytes)

            print(f"[TexturePaint] Wrote {os.path.basename(atlas_path)}")
            return True

        except Exception as e:
            print(f"[TexturePaint] Save failed for {atlas_path}: {e}")
            return False

    def _assemble_atlas_image(self, atlas_idx, texconv_path=None):
        """Build the 2×2 atlas PIL Image from combined_tex tiles for a given atlas.

        Seeds from the original file (preserving unpainted tiles), then writes
        only tiles that received actual paint strokes (_painted_world_tiles).
        Falls back to texconv decompression if PIL cannot decode the source DDS.
        """
        atlas_w = self._tile_w * 2
        atlas_h = self._tile_h * 2

        # Seed from the original file so un-painted sectors are preserved.
        # Try PIL first; if it returns None (can't decode DXT), try texconv.
        atlas_arr = None
        if atlas_idx < len(self._atlas_sorted_paths):
            dds_bytes, _ = _load_xbt(self._atlas_sorted_paths[atlas_idx])
            if dds_bytes is not None:
                orig = _dds_to_pil(dds_bytes)
                if orig is None and texconv_path:
                    print(f"[TexturePaint] PIL decode failed for seed, trying texconv …")
                    orig = _decompress_dds_with_texconv(dds_bytes, texconv_path)
                if orig is not None:
                    orig = orig.resize((atlas_w, atlas_h), Image.Resampling.NEAREST)
                    atlas_arr = np.array(orig.convert('RGBA'), dtype=np.uint8)

        if atlas_arr is None:
            print(f"[TexturePaint] WARNING: could not decode original atlas {atlas_idx}; "
                  "unpainted tiles will be black in output")
            atlas_arr = np.zeros((atlas_h, atlas_w, 4), dtype=np.uint8)
            atlas_arr[:, :, 3] = 255

        # Standard image positions for sub_sector 0-3: TL TR BL BR
        standard_origins = [
            (0,            0),
            (self._tile_w, 0),
            (0,            self._tile_h),
            (self._tile_w, self._tile_h),
        ]

        for display_row in range(self._sectors_y):
            for col in range(self._sectors_x):
                sector_idx = self._avatar_sector_index(col, display_row, self._sectors_y)
                if sector_idx // 4 != atlas_idx:
                    continue
                # Only write tiles that had actual paint strokes applied
                if (col, display_row) not in self._painted_world_tiles:
                    continue
                sub_sector = sector_idx % 4

                # Pull tile from combined texture
                py = display_row * self._tile_h
                px = col * self._tile_w
                tile = self.combined_tex[py:py + self._tile_h, px:px + self._tile_w]

                # Place at the standard sub_sector position in the atlas image
                ax, ay = standard_origins[sub_sector]
                atlas_arr[ay:ay + self._tile_h, ax:ax + self._tile_w] = tile

        return Image.fromarray(atlas_arr, 'RGBA')
