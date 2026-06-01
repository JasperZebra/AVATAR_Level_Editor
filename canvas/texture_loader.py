#!/usr/bin/env python3
"""
Texture / Material loader for Avatar XBM files.

Parses the full LTMD parameter table (textures, colors, scalars, flags)
using the same structured logic as the V10 Blender add-on
(modules/materials.py).  Falls back to a heuristic byte scrape for files
that don't parse cleanly.

Returns a rich XBMMaterialData so the model loader's material pass
(model_loader._load_xbg_textures) can build a proper material with diffuse
+ normal + specular + emission textures, base color tint, emission color,
alpha mode, and double-sided flag — not just a single diffuse.

XBT → PNG conversion handles:
  - Standard DDS payloads (DXT1, DXT5, A8R8G8B8 uncompressed)
  - Normal maps stored DXT5-GA packed (X in alpha, Y in green, Z derived):
    these are unpacked to a standard tangent-space RGB normal map.
"""

import os
import struct
import base64
import re
from typing import Optional, Tuple, Dict, Any

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("WARNING: PIL/Pillow not available. Texture support disabled.")


# ──────────────────────────────────────────────────────────────────────
# XBM parameter-table parser (port of V10's modules/materials.py)
# ──────────────────────────────────────────────────────────────────────

# Texture-slot name → canonical category.  Mirrors the V10 mapping so
# the same slots show up under the same keys here.
_TEX_CATEGORY_EXACT = {
    'diffusetexture1':       'diffuse',
    'diffusetexture2':       'diffuse2',
    'diffusetexture':        'diffuse',
    'skintexture':           'diffuse',
    'masktexture0':          'mask0',
    'masktexture1':          'mask',
    'diffusemasktexture':    'diffuse_mask',
    'speculartexture1':      'specular',
    'speculartexture':       'specular',
    'normaltexture1':        'normal',
    'normaltexture':         'normal',
    'normaltexture2':        'normal2',
    'illuminationtexture':   'emission',
    'tattootexture':         'tattoo',
    'bloodtexture':          'blood',
    'rimlighttexture':       'rim',
    'reflectioncubetexture': 'reflection',
    'reflectiontexture':     'reflection',
    'realreflectiontexture': 'reflection',
    'lighttexture':          'light',
    'glowtexture':           'glow',
    'burntdiffusetexture':   'diffuse_burnt',
    'specularid':            'specular_id',
    'masktexturebroken':     'mask_broken',
    'printtexture':          'print',
    'fabrictexture':         'fabric',
}


def _categorize_texture_slot(slot_name: str) -> Optional[str]:
    k = slot_name.lower()
    if k in _TEX_CATEGORY_EXACT:
        return _TEX_CATEGORY_EXACT[k]
    # Loose fallback for unseen variants — mirrors modules/materials.py _categorize()
    if 'normal' in k:
        return 'normal2' if k.endswith('2') else 'normal'
    if 'specular' in k:
        return 'specular'
    if 'mask' in k:
        return 'mask'
    if 'illumination' in k or 'glow' in k:
        return 'emission'
    if 'reflection' in k:
        return 'reflection'
    if 'light' in k:
        return 'light'
    if 'burnt' in k:
        return 'diffuse_burnt'
    if 'diffuse' in k or 'skin' in k:
        return 'diffuse2' if k.endswith('2') else 'diffuse'
    return None


def _read_lp_string(data: bytes, p: int) -> Tuple[str, int]:
    """Read a length-prefixed string from XBM (u32 len + bytes + opt null)."""
    n = struct.unpack_from('<I', data, p)[0]
    p += 4
    if n > 4096 or p + n > len(data):
        raise ValueError("string length out of range")
    s = data[p:p + n].decode('ascii', errors='replace')
    p += n
    if p < len(data) and data[p] == 0:
        p += 1
    return s, p


class XBMMaterialData:
    """Full material description read from an .xbm file."""

    def __init__(self):
        self.name: str = ""
        self.template: str = ""                  # 'Generic', 'Flesh', 'Cloth', etc.

        # Categorised textures: keys are canonical names like
        # 'diffuse', 'normal', 'specular', 'emission', 'mask', etc.
        # Values are engine-relative texture paths (graphics\...\foo_d.xbt).
        self.textures: Dict[str, str] = {}

        # Raw slot-key → path (preserved for round-trip / debug).
        self.texture_slots: Dict[str, str] = {}

        # Full parameter dict (key → value).  Float groups give tuples,
        # int group gives plain ints, texture group gives path strings.
        self.properties: Dict[str, Any] = {}

        # ── Derived convenience fields (pre-extracted so callers don't
        # need to crawl `properties` again) ────────────────────────────
        self.diffuse_color = (1.0, 1.0, 1.0)        # DiffuseColor1.rgb
        self.diffuse_color_base = (1.0, 1.0, 1.0)   # DiffuseColorBase.rgb
        self.specular_color = (0.5, 0.5, 0.5)       # SpecularColor1.rgb
        self.illumination_color = None              # (r, g, b) when emission present
        self.illumination_always_on = True          # alpha == 0.0 means always-on
        self.specular_power = 16.0                  # Blinn-Phong exponent
        self.alpha_test_enabled = False
        self.alpha_blend_enabled = False
        self.two_sided = False
        self.vertex_color_enabled = False


def _parse_xbm_structured(data: bytes) -> Optional[XBMMaterialData]:
    """Parse the LTMD chunk and populate an XBMMaterialData.  Returns
    None if the file isn't a valid LTMD-bearing XBM."""
    ltmd = data.find(b'LTMD')
    if ltmd < 0:
        return None
    try:
        # 16-byte chunk header + 9-byte material preamble (zeros).
        p = ltmd + 16 + 9

        result = XBMMaterialData()
        result.name, p = _read_lp_string(data, p)
        result.template, p = _read_lp_string(data, p)

        # Group 0: textures — (value, key) string pairs
        count = struct.unpack_from('<I', data, p)[0]
        p += 4
        if count > 256:
            return None
        for _ in range(count):
            value, p = _read_lp_string(data, p)
            key, p = _read_lp_string(data, p)
            result.properties[key] = value
            result.texture_slots[key] = value
            cat = _categorize_texture_slot(key)
            if cat and cat not in result.textures:
                result.textures[cat] = value

        # Groups 1..4: float properties (1, 2, 3, 4 components)
        for ncomp in (1, 2, 3, 4):
            count = struct.unpack_from('<I', data, p)[0]
            p += 4
            if count > 1024:
                return None
            for _ in range(count):
                key, p = _read_lp_string(data, p)
                vals = struct.unpack_from('<%df' % ncomp, data, p)
                p += 4 * ncomp
                result.properties[key] = vals if ncomp > 1 else vals[0]

        # Group 5: int / bool properties
        count = struct.unpack_from('<I', data, p)[0]
        p += 4
        if count > 1024:
            return None
        for _ in range(count):
            key, p = _read_lp_string(data, p)
            result.properties[key] = struct.unpack_from('<I', data, p)[0]
            p += 4

        # Populate convenience fields from properties
        _derive_material_fields(result)
        return result if result.name else None
    except Exception as e:
        print(f"  WARNING: structured XBM parse failed: {e}")
        return None


def _derive_material_fields(m: XBMMaterialData) -> None:
    """Pull convenience-field values out of the parsed properties dict."""
    p = m.properties

    def _rgb(key, default):
        v = p.get(key)
        if isinstance(v, (tuple, list)) and len(v) >= 3:
            return (float(v[0]), float(v[1]), float(v[2]))
        return default

    def _scalar(key, default):
        v = p.get(key)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, (tuple, list)) and v:
            return float(v[0])
        return default

    def _bool(key):
        v = p.get(key)
        if isinstance(v, (int, float)):
            return bool(int(v))
        return False

    m.diffuse_color = _rgb('DiffuseColor1', m.diffuse_color)
    m.diffuse_color_base = _rgb('DiffuseColorBase', m.diffuse_color_base)
    m.specular_color = _rgb('SpecularColor1', m.specular_color)
    m.specular_power = _scalar('SpecularPower', m.specular_power)
    m.alpha_test_enabled = _bool('AlphaTestEnabled')
    m.alpha_blend_enabled = _bool('AlphaBlendEnabled')
    m.two_sided = _bool('TwoSided')
    m.vertex_color_enabled = _bool('VertexColorEnabled')

    # IlluminationColor1 is float4: (r, g, b, a).  Alpha encodes day/night:
    #   0.0 → emission always visible
    #   1.0 → emission only at night (BioLightIntensity-driven)
    ic = p.get('IlluminationColor1')
    if isinstance(ic, (tuple, list)) and len(ic) >= 3:
        r, g, b = float(ic[0]), float(ic[1]), float(ic[2])
        m.illumination_color = (r, g, b)
        if len(ic) >= 4:
            m.illumination_always_on = float(ic[3]) < 0.5


def _parse_xbm_heuristic(data: bytes, result: XBMMaterialData) -> None:
    """Fallback: scrape texture paths via regex when structured parse fails.

    Same approach the old XBG2GLTF used, but populates the same
    XBMMaterialData so the rest of the pipeline doesn't care which path
    produced the data.
    """
    found = {}
    base_textures = []
    for match in re.finditer(rb'graphics[/\\][^\x00]{10,200}\.xbt', data):
        try:
            path = match.group().decode('ascii', errors='ignore')
            bname = os.path.basename(path).lower()
            is_mip0 = '_mip0.xbt' in bname
            tex_type = None
            if '_d.xbt' in bname or '_d_mip0.xbt' in bname:
                tex_type = 'diffuse'
            elif '_n.xbt' in bname or '_n_mip0.xbt' in bname:
                tex_type = 'normal'
            elif '_s.xbt' in bname or '_s_mip0.xbt' in bname:
                tex_type = 'specular'
            elif '_m.xbt' in bname or '_m_mip0.xbt' in bname:
                tex_type = 'emission'
            else:
                base_textures.append((path, is_mip0))
                continue
            if tex_type not in found:
                found[tex_type] = {'mip0': None, 'regular': None}
            found[tex_type]['mip0' if is_mip0 else 'regular'] = path
        except Exception:
            continue
    if 'diffuse' not in found and base_textures:
        mip0_base = [t for t in base_textures if t[1]]
        regular_base = [t for t in base_textures if not t[1]]
        if mip0_base:
            found['diffuse'] = {'mip0': mip0_base[0][0], 'regular': None}
        elif regular_base:
            found['diffuse'] = {'mip0': None, 'regular': regular_base[0][0]}
    for tex_type, versions in found.items():
        result.textures[tex_type] = versions['mip0'] or versions['regular']


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────


class TextureLoader:
    """Load + parse XBM materials and convert XBT textures for GLTF embedding."""

    def __init__(self, materials_path: str):
        """
        Args:
            materials_path: Path to the game's graphics/_materials folder
        """
        self.materials_path = materials_path
        self._material_cache: Dict[str, XBMMaterialData] = {}
        self._xbt_cache: Dict[Tuple[str, bool], Tuple[str, int, int]] = {}  # (path, is_normal) → (b64 png, w, h)
        print(f"Texture loader initialized with path: {materials_path}")

    # ── New: full material loader ─────────────────────────────────────

    def load_material(self, material_name: str) -> Optional[XBMMaterialData]:
        """Load and parse an XBM file by material name.

        Returns full XBMMaterialData (textures, colors, scalars, flags),
        or None if the .xbm file can't be found / parsed.
        """
        # Strip path + extension if present
        if '\\' in material_name or '/' in material_name:
            material_name = os.path.basename(material_name)
        if material_name.lower().endswith('.xbm'):
            material_name = material_name[:-4]
        if material_name.lower().endswith('.mat'):
            material_name = material_name[:-4]

        if material_name in self._material_cache:
            return self._material_cache[material_name]

        xbm_path = self._find_material_file(material_name)
        if not xbm_path:
            print(f"  [SKIP] Material XBM file not found for '{material_name}'")
            self._material_cache[material_name] = None
            return None

        try:
            with open(xbm_path, 'rb') as f:
                xbm_bytes = f.read()
        except Exception as e:
            print(f"  [SKIP] Failed reading XBM '{xbm_path}': {e}")
            self._material_cache[material_name] = None
            return None

        result = _parse_xbm_structured(xbm_bytes)
        if result is None:
            # Fall back to heuristic scrape — fills only the textures dict.
            print(f"  Structured XBM parse failed for {material_name!r}; using heuristic fallback.")
            result = XBMMaterialData()
            result.name = material_name
            _parse_xbm_heuristic(xbm_bytes, result)

        # Resolve missing textures from filesystem (companion files like
        # foo_n.xbt that aren't in the LTMD but exist on disk next to the
        # diffuse texture).
        self._fill_missing_textures_from_disk(result, xbm_path)
        # Final guarantee: every slot uses its high-res '<name>_mip0.xbt' sibling
        # when present (the engine's full-resolution top mip), matching the add-on.
        self._prefer_mip0_textures(result, xbm_path)

        if result.textures:
            tex_summary = ', '.join(f'{k}={os.path.basename(v)}' for k, v in result.textures.items())
            print(f"  [OK]   {material_name}: template={result.template!r}, textures: {tex_summary}")
        self._material_cache[material_name] = result
        return result

    # ── Back-compat ───────────────────────────────────────────────────

    def find_diffuse_texture(self, material_name: str) -> Optional[str]:
        """Locate the diffuse XBT for a material on disk (legacy API)."""
        mat = self.load_material(material_name)
        if not mat or 'diffuse' not in mat.textures:
            return None
        rel = mat.textures['diffuse']
        xbm_path = self._find_material_file(self._clean_material_name(material_name))
        if not xbm_path:
            return None
        full = self._resolve_texture_path(rel, xbm_path)
        if not os.path.exists(full):
            return None
        return full

    # ── Texture path resolution ───────────────────────────────────────

    def resolve_xbt_full_path(self, rel_path: str, material_name: str) -> Optional[str]:
        """Convert an engine-relative texture path to an absolute path."""
        xbm_path = self._find_material_file(self._clean_material_name(material_name))
        if not xbm_path:
            return None
        full = self._resolve_texture_path(rel_path, xbm_path)
        return full if os.path.exists(full) else None

    def _clean_material_name(self, name: str) -> str:
        if '\\' in name or '/' in name:
            name = os.path.basename(name)
        if name.lower().endswith('.xbm'):
            name = name[:-4]
        if name.lower().endswith('.mat'):
            name = name[:-4]
        return name

    def _find_material_file(self, material_name: str) -> Optional[str]:
        """Find the .xbm material file by name (recursive search)."""
        xbm_file = f"{material_name}.xbm"
        xbm_path = os.path.join(self.materials_path, xbm_file)
        if os.path.exists(xbm_path):
            return xbm_path
        # Walk subdirs
        try:
            for root, _dirs, files in os.walk(self.materials_path):
                for f in files:
                    if f.lower() == xbm_file.lower():
                        return os.path.join(root, f)
        except Exception as e:
            print(f"  Error during recursive search: {e}")
        return None

    def _fill_missing_textures_from_disk(self, result: XBMMaterialData, xbm_filepath: str) -> None:
        """Two passes over each texture slot:

        Pass 1 — upgrade: if the LTMD gave us a regular-res path (no
        '_mip0') and a high-res '_mip0' sibling exists on disk, swap in
        the mip0 path.  Mirrors the lhd=True branch of the Blender
        add-on's _find_missing_textures.

        Pass 2 — fill: for slots that are completely absent from the LTMD
        (structured-parse succeeded but the template just didn't list that
        slot), scan the disk for a companion file built from the reference
        texture's basename + the type suffix.
        """
        xbm_dir = os.path.dirname(xbm_filepath)
        data_folder = xbm_dir
        while data_folder and os.path.basename(data_folder).lower() != 'data':
            parent = os.path.dirname(data_folder)
            if parent == data_folder:
                break
            data_folder = parent
        if not data_folder or not os.path.exists(data_folder):
            return

        # Use any existing texture as the "reference" to derive the basename.
        reference = None
        for k in ('diffuse', 'normal', 'specular', 'emission'):
            if k in result.textures:
                reference = result.textures[k]
                break
        if not reference:
            return

        basename = os.path.basename(reference).lower().replace('.xbt', '')
        for suf in ('_d', '_n', '_s', '_m', '_mip0'):
            if basename.endswith(suf):
                basename = basename[:-len(suf)]
                break
        texture_dir = os.path.dirname(reference)

        def _full(rel):
            return os.path.join(data_folder,
                                rel.replace('\\', os.sep).replace('/', os.sep))

        # Mip0 suffixes per slot type
        _mip0_suffixes = {
            'diffuse':  ('_d_mip0.xbt', '_mip0.xbt'),
            'normal':   ('_n_mip0.xbt',),
            'specular': ('_s_mip0.xbt',),
            'emission': ('_m_mip0.xbt',),
        }
        # All search suffixes (mip0 first so we always prefer high-res)
        _all_suffixes = (
            ('diffuse',  ('_d_mip0.xbt', '_d.xbt', '_mip0.xbt', '.xbt')),
            ('normal',   ('_n_mip0.xbt', '_n.xbt')),
            ('specular', ('_s_mip0.xbt', '_s.xbt')),
            ('emission', ('_m_mip0.xbt', '_m.xbt')),
        )

        # Pass 1: upgrade existing regular-res paths to mip0 when available
        for tex_type, mip0_sufs in _mip0_suffixes.items():
            if tex_type not in result.textures:
                continue
            current = result.textures[tex_type]
            if '_mip0.xbt' in current.lower():
                continue  # already high-res
            for suf in mip0_sufs:
                rel = texture_dir + '/' + basename + suf
                if os.path.exists(_full(rel)):
                    result.textures[tex_type] = rel
                    print(f"  Upgraded {tex_type} to mip0: {os.path.basename(rel)}")
                    break

        # Pass 2: fill completely absent slots
        for tex_type, suffixes in _all_suffixes:
            if tex_type in result.textures:
                continue
            for suf in suffixes:
                rel = texture_dir + '/' + basename + suf
                if os.path.exists(_full(rel)):
                    result.textures[tex_type] = rel
                    print(f"  Found missing {tex_type} texture: {os.path.basename(rel)}")
                    break

    def _prefer_mip0_textures(self, result: XBMMaterialData, xbm_filepath: str) -> None:
        """For every texture slot, prefer the high-res '<name>_mip0.xbt' sibling
        when it exists on disk — the engine's full-resolution top mip. Mirrors the
        Blender add-on's `versions['mip0'] or versions['regular']` preference.

        Per-slot (each texture upgrades using its OWN name, e.g. foo_d.xbt →
        foo_d_mip0.xbt) and uses the same resolver as loading, so it works even
        when slots have different basenames or the 'data'-folder walk in
        _fill_missing_textures_from_disk didn't apply.
        """
        for tex_type in ('diffuse', 'normal', 'specular', 'emission'):
            current = result.textures.get(tex_type)
            if not current or not current.lower().endswith('.xbt'):
                continue
            if '_mip0.xbt' in current.lower():
                continue  # already the high-res mip
            mip0_rel = current[:-4] + '_mip0.xbt'   # foo_d.xbt -> foo_d_mip0.xbt
            try:
                full = self._resolve_texture_path(mip0_rel, xbm_filepath)
            except Exception:
                full = None
            if full and os.path.exists(full):
                result.textures[tex_type] = mip0_rel

    def _resolve_texture_path(self, texture_path: str, xbm_path: str) -> str:
        """Convert an engine-relative texture path to absolute filesystem path."""
        xbm_dir = os.path.dirname(xbm_path)
        data_folder = xbm_dir
        while data_folder and os.path.basename(data_folder).lower() != 'data':
            parent = os.path.dirname(data_folder)
            if parent == data_folder:
                data_folder = os.path.dirname(os.path.dirname(self.materials_path))
                break
            data_folder = parent
        texture_path = texture_path.replace('\\', os.sep).replace('/', os.sep)
        return os.path.join(data_folder, texture_path)

    # ── XBT → PNG conversion ──────────────────────────────────────────

    def convert_xbt_to_png_base64(
        self, xbt_path: str, is_normal_map: bool = False
    ) -> Optional[Tuple[str, int, int]]:
        """Convert an XBT texture to PNG and return (base64, w, h).

        Args:
            xbt_path: filesystem path to the .xbt
            is_normal_map: if True, decode DXT5-GA packed normals
                           (X from alpha, Y from green, Z reconstructed)
                           and emit a standard tangent-space RGB normal map.
        """
        if not PIL_AVAILABLE:
            return None

        cache_key = (xbt_path, is_normal_map)
        if cache_key in self._xbt_cache:
            return self._xbt_cache[cache_key]

        try:
            with open(xbt_path, 'rb') as f:
                xbt_data = f.read()
            dds_data = self._extract_dds_from_xbt(xbt_data)
            if not dds_data:
                print(f"  Failed to extract DDS from XBT: {os.path.basename(xbt_path)}")
                return None

            import tempfile, io as _io
            with tempfile.NamedTemporaryFile(suffix='.dds', delete=False) as temp_dds:
                temp_dds.write(dds_data)
                temp_dds_path = temp_dds.name
            try:
                with Image.open(temp_dds_path) as img:
                    img.load()
                    if is_normal_map:
                        img = _decode_dxt5_ga_normal_map(img)
                    elif img.mode not in ('RGB', 'RGBA'):
                        img = img.convert('RGB')
                    width, height = img.size
                    png_buffer = _io.BytesIO()
                    img.save(png_buffer, format='PNG')
                    png_data = png_buffer.getvalue()
                    base64_string = base64.b64encode(png_data).decode('ascii')
                    label = "normal-decoded " if is_normal_map else ""
                    print(f"  Converted {label}texture: {os.path.basename(xbt_path)} ({width}x{height})")
                    result = (base64_string, width, height)
                    self._xbt_cache[cache_key] = result
                    return result
            finally:
                try:
                    os.unlink(temp_dds_path)
                except OSError:
                    pass
        except Exception as e:
            print(f"  Error converting texture {os.path.basename(xbt_path)}: {e}")
            import traceback
            traceback.print_exc()
        return None

    def decode_xbt_to_rgba(self, xbt_path: str, is_normal_map: bool = False):
        """Decode an XBT straight to RGBA bytes for GL upload.

        Much faster than convert_xbt_to_png_base64: no temp .dds file, no PNG
        encode, no base64 round-trip — XBT → DDS bytes → PIL (from memory) →
        RGBA. Returns (width, height, rgba_bytes, had_alpha) or None.
        Cached separately from the PNG path (key includes 'rgba').
        """
        if not PIL_AVAILABLE:
            return None
        cache_key = (xbt_path, is_normal_map, 'rgba')
        if cache_key in self._xbt_cache:
            return self._xbt_cache[cache_key]
        try:
            with open(xbt_path, 'rb') as f:
                xbt_data = f.read()
            dds = self._extract_dds_from_xbt(xbt_data)
            if not dds:
                return None
            import io as _io
            try:
                img = Image.open(_io.BytesIO(dds))
                img.load()
            except Exception:
                # Some PIL builds need a real file for DDS — fall back to temp.
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.dds', delete=False) as tf:
                    tf.write(dds)
                    tmp = tf.name
                try:
                    img = Image.open(tmp)
                    img.load()
                finally:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
            if is_normal_map:
                img = _decode_dxt5_ga_normal_map(img)
            had_alpha = img.mode in ('RGBA', 'LA', 'PA')
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            w, h = img.size
            result = (w, h, img.tobytes(), had_alpha)
            self._xbt_cache[cache_key] = result
            return result
        except Exception as e:
            print(f"  decode_xbt_to_rgba failed ({os.path.basename(xbt_path)}): {e}")
            return None

    def _extract_dds_from_xbt(self, xbt_data: bytes) -> Optional[bytes]:
        """Strip the TBX header from an .xbt and return the DDS payload."""
        try:
            if xbt_data[:3] == b'TBX':
                if len(xbt_data) >= 12:
                    header_size = struct.unpack('<I', xbt_data[8:12])[0]
                    if 32 <= header_size <= 1024 and header_size < len(xbt_data):
                        dds_data = xbt_data[header_size:]
                    else:
                        dds_data = xbt_data[32:]
                else:
                    dds_data = xbt_data[32:]
            else:
                dds_data = xbt_data
            if len(dds_data) >= 4 and dds_data[:4] == b'DDS ':
                return dds_data
            for header_size in (64, 128, 256):
                if len(xbt_data) > header_size:
                    test_data = xbt_data[header_size:]
                    if len(test_data) >= 4 and test_data[:4] == b'DDS ':
                        return test_data
        except Exception as e:
            print(f"  Error extracting DDS: {e}")
        return None


def _decode_dxt5_ga_normal_map(img: 'Image.Image') -> 'Image.Image':
    """Convert a DXT5-GA packed normal map to a standard tangent-space RGB map.

    Avatar's engine (normalmap.inc.fx) reads:
        n.x = alpha channel  (255 = +1, 0 = -1)
        n.y = green channel
        n.z = sqrt(1 - n.x^2 - n.y^2)   (reconstructed)

    GLTF / standard normal maps expect:
        R = X    G = Y    B = Z   (all 0..255 with 128 ≈ 0)

    Works for any input mode; we ensure RGBA then re-pack.
    """
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    if not PIL_AVAILABLE:
        return img
    try:
        # Fast path with numpy if available, else pure-Python
        import numpy as np
        arr = np.asarray(img, dtype=np.uint8).copy()
        # n.xy in [-1, +1]
        nx = arr[..., 3].astype(np.float32) / 255.0 * 2.0 - 1.0
        ny = arr[..., 1].astype(np.float32) / 255.0 * 2.0 - 1.0
        nz = np.sqrt(np.clip(1.0 - nx * nx - ny * ny, 0.0, 1.0))
        # Re-pack as RGB
        out = np.zeros((arr.shape[0], arr.shape[1], 3), dtype=np.uint8)
        out[..., 0] = np.clip((nx + 1.0) * 0.5 * 255.0 + 0.5, 0, 255).astype(np.uint8)
        out[..., 1] = np.clip((ny + 1.0) * 0.5 * 255.0 + 0.5, 0, 255).astype(np.uint8)
        out[..., 2] = np.clip((nz + 1.0) * 0.5 * 255.0 + 0.5, 0, 255).astype(np.uint8)
        return Image.fromarray(out, mode='RGB')
    except ImportError:
        # Pure-Python fallback (slow on large textures)
        from math import sqrt
        w, h = img.size
        src = img.load()
        out = Image.new('RGB', (w, h))
        dst = out.load()
        for y in range(h):
            for x in range(w):
                r, g, b, a = src[x, y]
                nx = a / 255.0 * 2.0 - 1.0
                ny = g / 255.0 * 2.0 - 1.0
                nz2 = 1.0 - nx * nx - ny * ny
                nz = sqrt(nz2) if nz2 > 0 else 0.0
                dst[x, y] = (
                    int(max(0, min(255, (nx + 1.0) * 127.5 + 0.5))),
                    int(max(0, min(255, (ny + 1.0) * 127.5 + 0.5))),
                    int(max(0, min(255, (nz + 1.0) * 127.5 + 0.5))),
                )
        return out
