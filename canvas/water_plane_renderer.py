"""Renders translucent per-sector water planes in the 3D view.

This is the editor's ONLY water display. Older terrain GLTFs also contained a
baked water mesh (a second, slightly transparent plane at the same height);
terrain generation no longer emits it, and `strip_baked_water` removes it from
cached terrain files at load time.
"""

from OpenGL.GL import *
import numpy as np
import ctypes
import time as _time


# ── Game-accurate water shader ──────────────────────────────────────────────
# Reproduces the look of the Dunia (Avatar/FC2) water shader on the editor's
# per-sector water planes: a rippling surface (animated normals) that reflects
# the sky, brightens into a sun-glint sparkle, and blends deep-water tint ->
# reflection by a Fresnel term — all reacting to the day/night cycle. Legacy
# #version 120 so it drops into the existing fixed-function 3D pass: it reads the
# GL matrix stack (gl_ModelViewProjectionMatrix) and the position VBO via the
# built-in gl_Vertex (the water VBO already bakes WORLD-space positions), so no
# new geometry/UV plumbing is needed. Compile failure → caller falls back to the
# old flat-blue quad (never a blank/!broken viewport).
_WATER_VS = """
#version 120
varying vec3 v_world;
varying vec3 v_deep;
void main() {
    v_world = gl_Vertex.xyz;                          // VBO holds world positions
    v_deep  = gl_Color.rgb;                           // per-sector WaterColor (xbm)
    gl_Position = gl_ModelViewProjectionMatrix * gl_Vertex;
}
"""

_WATER_FS = """
#version 120
varying vec3 v_world;
varying vec3 v_deep;       // per-sector deep-water tint (material WaterColor)
uniform float u_time;      // seconds, animates the ripples
uniform vec3  u_cam;       // camera world position
uniform vec3  u_sunDir;    // direction TOWARD the sun (normalized, world)
uniform vec3  u_sunCol;    // sun light colour (for the glint)
uniform float u_day;       // 0 night .. 1 day
uniform vec3  u_skyLo;     // reflected sky colour near the horizon
uniform vec3  u_skyHi;     // reflected sky colour near the zenith
uniform float u_choppy;    // ripple bump strength

float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p){
    vec2 i = floor(p), f = fract(p);
    float a = hash(i), b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0)), d = hash(i + vec2(1.0, 1.0));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
// Layered scrolling noise -> a height field. Two dominant drift directions at a
// few octaves reads as wind-driven ripples rather than a regular pattern.
float waves(vec2 p){
    float h = 0.0, amp = 0.5, freq = 1.0;
    vec2 d1 = vec2(1.0, 0.35), d2 = vec2(-0.45, 1.0);
    for (int i = 0; i < 4; i++){
        h += amp * noise(p * freq + d1 * u_time * 0.55 * freq);
        h += amp * noise(p * freq * 1.7 - d2 * u_time * 0.40 * freq);
        amp *= 0.5; freq *= 1.9;
    }
    return h;
}
void main(){
    vec2 uv = v_world.xz * 0.03;                      // world -> ripple scale
    float e = 0.06;
    float h  = waves(uv);
    float hx = waves(uv + vec2(e, 0.0));
    float hz = waves(uv + vec2(0.0, e));
    // Surface normal from the height gradient (up = +Y). u_choppy scales the tilt.
    vec3 N = normalize(vec3((h - hx) * u_choppy, 1.0, (h - hz) * u_choppy));

    vec3 V = normalize(u_cam - v_world);              // toward camera
    vec3 R = reflect(-V, N);                          // reflected view ray

    // Sky reflection: blend horizon->zenith by how far up the reflection points.
    float up = clamp(R.y * 0.5 + 0.5, 0.0, 1.0);
    vec3 refl = mix(u_skyLo, u_skyHi, up);

    // Fresnel: looking straight down = mostly deep-water tint; grazing = mirror.
    float fres = pow(clamp(1.0 - max(dot(N, V), 0.0), 0.0, 1.0), 5.0);
    fres = mix(0.02, 1.0, fres);

    // Sun glint: sharp specular toward the sun, day-only.
    float glint = pow(max(dot(R, normalize(u_sunDir)), 0.0), 220.0);
    vec3  sun = u_sunCol * glint * 3.0 * u_day;

    // Per-sector deep-water tint from the material's WaterColor, dimmed at night.
    vec3 deep = v_deep * (0.35 + 0.65 * u_day);
    deep.b += (1.0 - u_day) * 0.02;

    vec3 col = mix(deep, refl, fres) + sun;
    float alpha = mix(0.72, 0.96, fres);              // more opaque/mirror at grazing
    gl_FragColor = vec4(col, alpha);
}
"""


# Per-material WaterColor (the `WaterColor` float property inside each water `.xbm`
# material), extracted from the real Avatar + FC2 material files. Keyed by the
# material file basename (lowercase, no extension) so it matches whatever `.mlm`/
# `.xbm` path a sector stores. This is what gives each water material its own tint
# (swamp murky, riverbank teal, rainforest green, ...) instead of one flat colour.
_WATER_COLORS = {
    # Far Cry 2
    'water_default_top':                 (0.1490, 0.1569, 0.1137),
    'waterriver_default_top':            (0.1490, 0.1569, 0.1176),
    'water_moss_low_fishingvillage_top': (0.1490, 0.1569, 0.1098),
    # Avatar
    'df_water_default_top':              (0.6745, 0.3922, 0.3922),
    'water_av_openfield':                (0.0745, 0.0745, 0.0588),
    'water_av_rainforest':               (0.1255, 0.1608, 0.0941),
    'water_av_rainforest_prolemuris_noreflection': (0.1961, 0.2471, 0.1529),
    'water_av_riverbank':                (0.0863, 0.1725, 0.1294),
    'water_av_swamp':                    (0.1059, 0.1059, 0.0706),
    'water_riverbank_polluted_top':      (0.1451, 0.1333, 0.1137),
    'water_riverbank_pollutedmix_top':   (0.1451, 0.1216, 0.0941),
    'waterriver_av_riverbankriver':      (0.0863, 0.1451, 0.1216),
}
# Fallback for a material we don't have a WaterColor for (neutral murky teal).
_WATER_DEFAULT = (0.1176, 0.1451, 0.1098)


def _water_color_for(material_path):
    """WaterColor RGB for a sector's stored water-material path. Matches by file
    basename so `.mlm`/`.xbm`/case differences don't matter; unknown → default."""
    if not material_path:
        return _WATER_DEFAULT
    base = str(material_path).replace('\\', '/').rsplit('/', 1)[-1]
    base = base.rsplit('.', 1)[0].lower()
    return _WATER_COLORS.get(base, _WATER_DEFAULT)


def _compile_water_program():
    """Compile the water shader; return the GL program id, or 0 on any failure."""
    def _stage(src, kind):
        sid = glCreateShader(kind)
        glShaderSource(sid, src)
        glCompileShader(sid)
        if glGetShaderiv(sid, GL_COMPILE_STATUS) != GL_TRUE:
            log = glGetShaderInfoLog(sid)
            if isinstance(log, bytes):
                log = log.decode('utf-8', 'replace')
            print(f'[WaterPlane] shader compile FAILED:\n{log}')
            glDeleteShader(sid)
            return 0
        return sid
    try:
        vs = _stage(_WATER_VS, GL_VERTEX_SHADER)
        if not vs:
            return 0
        fs = _stage(_WATER_FS, GL_FRAGMENT_SHADER)
        if not fs:
            glDeleteShader(vs)
            return 0
        prog = glCreateProgram()
        glAttachShader(prog, vs); glAttachShader(prog, fs)
        glLinkProgram(prog)
        glDeleteShader(vs); glDeleteShader(fs)
        if glGetProgramiv(prog, GL_LINK_STATUS) != GL_TRUE:
            log = glGetProgramInfoLog(prog)
            if isinstance(log, bytes):
                log = log.decode('utf-8', 'replace')
            print(f'[WaterPlane] shader link FAILED:\n{log}')
            glDeleteProgram(prog)
            return 0
        print(f'[WaterPlane] water shader ready (prog {int(prog)})')
        return int(prog)
    except Exception as e:
        print(f'[WaterPlane] shader build error: {e}')
        return 0


def strip_baked_water(model):
    """Remove the baked water mesh from a terrain GLTF model (if present).

    Older generated terrain embedded per-sector water quads as a 'Water' node
    (see the removed create_water_planes in terrain_to_gltf.py) — a duplicate
    of the procedural planes this module draws. Identified exactly the way
    water_mesh_editor finds it: a GLTF node named 'Water' pointing at a mesh.
    MUST run before _create_opengl_resources so the rebuilt display list
    excludes the water geometry. GPU-free; returns the number of meshes removed.
    """
    try:
        gltf = getattr(model, 'gltf_data', None)
        meshes = getattr(model, 'meshes', None)
        if not gltf or not meshes or 'nodes' not in gltf:
            return 0
        water_idx = {n.get('mesh') for n in gltf['nodes']
                     if n.get('name') == 'Water' and n.get('mesh') is not None}
        if not water_idx:
            return 0
        kept = [m for i, m in enumerate(meshes) if i not in water_idx]
        removed = len(meshes) - len(kept)
        if removed:
            model.meshes = kept
            print(f"[WaterPlane] stripped {removed} baked water mesh(es) from terrain "
                  f"(procedural water planes are the single source now)")
        return removed
    except Exception as e:
        print(f"[WaterPlane] baked-water strip failed (harmless): {e}")
        return 0


class WaterPlaneRenderer:
    """Draws a flat translucent quad for every sector whose water flag is active.

    The single water display: rich translucent blue matching the look of the
    old baked GLTF water (dodger-blue texture at ~0.7 alpha) that it replaced.
    glPolygonOffset keeps the plane in front of terrain at near-equal depth.
    """

    def force_update_sector(self, sector_num, terrain_renderer):
        """Drop cached submerged-cell geometry so the next frame re-clips against
        the (edited) heightmap / water height. Cache keys are (cell, sector) so
        just clear the whole cache — water edits are infrequent. Also bumps the
        geometry version so the baked display list rebuilds."""
        cache = getattr(self, '_geom_cache', None)
        if cache is not None:
            cache.clear()
        self._geom_version = getattr(self, '_geom_version', 0) + 1

    def _get_submerged_geometry(self, hm, um, wy, is_fc2, cache_key):
        """Return the water geometry for one sector, clipped to where the game
        would actually show water: terrain height < water height, per cell
        (AGENTS.md: '.csdat' header — 'Water shape is implicitly terrain height
        < water height, per sector'; NO polygon is stored). `hm` is the sector's
        heightmap (direct rule, both games), `um` the byte[3] underwater mask
        (Avatar fallback when heights are unavailable), `wy` the water height.

        Returns one of:
          'FULL'  — whole sector submerged, draw the single flat quad (fast)
          'SKIP'  — no cell submerged (water assigned but nothing below the
                    line → the 'floating water that isn't in-game' case)
          [(u0,u1,v0,v1), ...] — normalized spans of submerged cells to draw

        Cached per `cache_key` (=(cell_index, sector_num)) and only recomputed
        when the heightmap object or the water height changes (both rare)."""
        cache = getattr(self, '_geom_cache', None)
        if cache is None:
            cache = self._geom_cache = {}

        if hm is not None:
            key = ('h', id(hm), round(wy, 4))
        elif um is not None:
            key = ('u', id(um))
        else:
            return 'FULL'  # no per-vertex data (old cache / short file) — keep old behaviour

        cached = cache.get(cache_key)
        if cached is not None and cached[0] == key:
            return cached[1]

        # Boolean per-vertex "underwater" grid (n x n).
        sub = (hm < wy) if hm is not None else um
        n = sub.shape[0]
        if n < 2:
            geom = 'FULL'
            cache[cache_key] = (key, geom)
            return geom

        # A cell (between 4 vertices) is water if ANY of its corners is
        # underwater — inclusive at the shoreline so water reaches the bank.
        cell = sub[:-1, :-1] | sub[1:, :-1] | sub[:-1, 1:] | sub[1:, 1:]

        # byte[3] underwater mask (key 'u') is Avatar ground truth — trust SKIP.
        # Heightmap clipping (key 'h') is authoritative on Avatar too, but on FC2
        # we haven't ground-truthed that .sdat heights share units with the
        # water-height field, so never let it fully HIDE a flagged sector there
        # (a unit mismatch would read as all-dry). Clipping floating-over-hills
        # still applies; only the all-dry -> hidden case is vetoed for FC2.
        fc2_heightclip = (key[0] == 'h' and is_fc2)

        if not cell.any():
            geom = 'FULL' if fc2_heightclip else 'SKIP'
        elif cell.all():
            geom = 'FULL'
        else:
            inv = float(n - 1)
            H, W = cell.shape
            spans = []
            for i in range(H):
                r = cell[i]
                j = 0
                while j < W:
                    if r[j]:
                        k = j + 1
                        while k < W and r[k]:
                            k += 1
                        spans.append((j / inv, k / inv, i / inv, (i + 1) / inv))
                        j = k
                    else:
                        j += 1
            geom = spans

        cache[cache_key] = (key, geom)
        return geom

    def _iter_cells(self, terrain_renderer, canvas):
        """Yield one render bundle per terrain tile. Stacked Avatar levels (e.g.
        Tantalus l1+l2) load each tile via load_sdat_cell, which snapshots its
        own water_data/sectors_data/offset into terrain_renderer.water_cells —
        the shared top-level dicts otherwise keep ONLY the last tile, so without
        this the other tile's water is lost and this tile's water renders at the
        wrong tile's origin (the reported Tantalus floating water). Single-cell
        levels have no water_cells, so we synthesize one bundle from the live
        dicts (identical to the old single-tile path)."""
        cells = getattr(terrain_renderer, 'water_cells', None)
        if cells:
            for i, c in enumerate(cells):
                yield i, c
            return
        combined = terrain_renderer.combined_heightmap
        if combined is None and canvas is not None:
            td = getattr(canvas, '_terrain_data', None)
            if td is not None:
                combined = td.combined
        yield 0, {
            'water_data': terrain_renderer.water_data,
            'sectors_data': getattr(terrain_renderer, 'sectors_data', {}) or {},
            'sectors_underwater': getattr(terrain_renderer, 'sectors_underwater', {}) or {},
            'combined': combined,
            'sectors_x': getattr(terrain_renderer, 'sectors_x', 16),
            'sectors_y': getattr(terrain_renderer, 'sectors_y', 16),
            # single-tile: the "cell offset" is just terrain_offset (usually 0),
            # reproducing the old x=ox+..., z=-(oy+...) math exactly.
            'world_x': getattr(terrain_renderer, 'terrain_offset_x', 0.0),
            'world_y': getattr(terrain_renderer, 'terrain_offset_y', 0.0),
        }

    def _emit_cell(self, cell_idx, cell, is_fc2, out, cols):
        """Append GL_QUADS vertices (flat x,y,z floats) for one terrain tile's
        water into `out`, and the matching per-vertex RGB (each sector's material
        WaterColor) into `cols`, clipped per sector and translated by the tile's
        world offset (matching the terrain mesh, drawn with
        glTranslatef(world_x, 0, -world_y)). Geometry is collected into a numpy
        array and uploaded to a VBO once — NOT submitted per frame."""
        wd = cell.get('water_data') or {}
        sdd = cell.get('sectors_data') or {}
        umm = cell.get('sectors_underwater') or {}
        sx = cell.get('sectors_x', 16) or 16
        sy = cell.get('sectors_y', 16) or 16
        combined = cell.get('combined')
        if combined is not None:
            h_px, w_px = combined.shape
            sector_w = float(w_px - 1) / max(sx, 1)
            sector_h = float(h_px - 1) / max(sy, 1)
        else:
            sector_w = sector_h = 64.0
        wx = float(cell.get('world_x', 0.0))
        wy_off = float(cell.get('world_y', 0.0))

        for sector_num, wdi in wd.items():
            if not getattr(wdi, 'has_water', False):
                continue
            hm = sdd.get(sector_num)
            um = umm.get(sector_num)
            wy = float(getattr(wdi, 'water_height', 0.0))
            geom = self._get_submerged_geometry(hm, um, wy, is_fc2, (cell_idx, sector_num))
            if geom == 'SKIP':
                continue

            # This sector's water tint = its material's WaterColor (from the xbm).
            wc = _water_color_for(getattr(wdi, 'material_path', None))

            col = sector_num % sx
            row = sector_num // sx   # 0 = bottom of map
            # Tile-local position + tile world offset (mesh translate: x+wx, z-wy).
            x0 = col * sector_w + wx
            x1 = (col + 1) * sector_w + wx
            z0 = -(row * sector_h) - wy_off
            z1 = -((row + 1) * sector_h) - wy_off
            y = wy
            dx = x1 - x0
            dz = z1 - z0

            if geom == 'FULL':
                out.extend((x0, y, z0, x1, y, z0, x1, y, z1, x0, y, z1))
                cols.extend(wc * 4)                       # 4 verts, same tint
            else:
                # geom = normalized (u0,u1,v0,v1) submerged spans. u -> x across
                # the sector, v -> z (south->north); no flip, matching the
                # linear+flipud heightmap assembly.
                for u0, u1, v0, v1 in geom:
                    xa = x0 + u0 * dx
                    xb = x0 + u1 * dx
                    za = z0 + v0 * dz
                    zb = z0 + v1 * dz
                    out.extend((xa, y, za, xb, y, za, xb, y, zb, xa, y, zb))
                    cols.extend(wc * 4)

    def _bind_water_shader(self, canvas):
        """Compile (once) and bind the water shader with day/night-driven uniforms.
        Returns True if bound (caller then draws the quads and unbinds); False if
        unavailable, so the caller falls back to the flat-blue quad."""
        if getattr(self, '_water_shader_failed', False):
            return False
        prog = getattr(self, '_water_prog', None)
        if not prog:
            prog = _compile_water_program()
            self._water_prog = prog
            if not prog:
                self._water_shader_failed = True
                return False
            self._water_uloc = {n: glGetUniformLocation(prog, n) for n in (
                'u_time', 'u_cam', 'u_sunDir', 'u_sunCol', 'u_day',
                'u_skyLo', 'u_skyHi', 'u_choppy')}

        # ── Derive uniforms from the canvas' day/night state ──────────────────
        day = 1.0
        cam = (0.0, 500.0, 0.0)
        sun = (0.3, 0.85, 0.3)
        try:
            if canvas is not None:
                if getattr(canvas, 'day_night_enabled', False) and hasattr(canvas, '_daynight_factors'):
                    day = canvas._daynight_factors()[2]
                c = canvas.camera_3d.position
                cam = (float(c[0]), float(c[1]), float(c[2]))
                sun = getattr(canvas, '_sun_dir_world', sun)
        except Exception:
            pass
        # Reflected sky: horizon band from the canvas sky colour, a deeper-blue
        # zenith; both already fade to near-black at night, so the water darkens.
        sky = (0.45, 0.62, 0.85)
        try:
            if canvas is not None and hasattr(canvas, '_sky_color'):
                sky = canvas._sky_color()
        except Exception:
            pass
        sky_lo = sky
        sky_hi = (sky[0] * 0.55, sky[1] * 0.72, min(1.0, sky[2] * 1.05))
        # (Deep-water tint is now per-sector, supplied via the colour array from
        # each material's WaterColor — no single u_deep uniform.)
        sun_col = (1.0, 0.96, 0.88)

        glUseProgram(prog)
        u = self._water_uloc
        glUniform1f(u['u_time'], float(_time.perf_counter()))
        glUniform3f(u['u_cam'], *cam)
        glUniform3f(u['u_sunDir'], float(sun[0]), float(sun[1]), float(sun[2]))
        glUniform3f(u['u_sunCol'], *sun_col)
        glUniform1f(u['u_day'], float(day))
        glUniform3f(u['u_skyLo'], float(sky_lo[0]), float(sky_lo[1]), float(sky_lo[2]))
        glUniform3f(u['u_skyHi'], float(sky_hi[0]), float(sky_hi[1]), float(sky_hi[2]))
        # Ripple strength: how much the wave height tilts the surface normal. Low
        # (0.45, was 2.2) = mostly FLAT, near-mirror water with only faint ripples —
        # matching the calm look of the game's water. Raise for choppier seas.
        glUniform1f(u['u_choppy'], 0.45)
        return True

    def render_water_planes(self, terrain_renderer, canvas=None, water_mesh_editor=None):
        if not terrain_renderer:
            return
        cells_ref = getattr(terrain_renderer, 'water_cells', None)
        if not terrain_renderer.water_data and not cells_ref:
            return

        is_fc2 = getattr(terrain_renderer, 'game_mode', None) == 'farcry2'

        try:
            glDisable(GL_LIGHTING)
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glDisable(GL_CULL_FACE)
            glEnable(GL_DEPTH_TEST)
            # WRITE depth, like the old baked water mesh did. Water draws before
            # entities; without the depth write, submerged models painted OVER
            # the surface (looked "inside out"). With it, anything below the
            # plane is correctly hidden under the water.
            glDepthMask(GL_TRUE)
            # Pull the planes in front of terrain at near-equal depth (shoreline)
            glEnable(GL_POLYGON_OFFSET_FILL)
            glPolygonOffset(-1.0, -1.0)
            # Appearance is produced by the water SHADER (bound per-draw below),
            # which ripples + reflects the sky + sun-glints per the day/night cycle.
            # The flat glColor is only the fallback if the shader failed to compile.

            # The water geometry is STATIC frame-to-frame (it only changes on
            # level load or a water edit), so build the quad vertices ONCE and
            # upload them to a GPU-resident VBO — then each frame is a single
            # glDrawArrays with NO per-frame CPU->GPU transfer and NO Python
            # per-vertex loop (which is what made stacked levels drop FPS). A VBO
            # (not a display list) is used deliberately: it is reliably GPU-
            # resident on ALL drivers incl. AMD, where compat-profile display
            # lists may just replay commands. Rebuild only when the signature
            # changes: tile set identity, geom version (force_update_sector), or a
            # cheap content hash (watered count + height sum) so the water
            # editor's live in-memory toggles/height changes still refresh.
            def _content_sig():
                n = 0
                s = 0.0
                mats = 0
                buckets = ([c.get('water_data') or {} for c in cells_ref]
                           if cells_ref else [terrain_renderer.water_data])
                for wd in buckets:
                    for v in wd.values():
                        if getattr(v, 'has_water', False):
                            n += 1
                            s += float(getattr(v, 'water_height', 0.0))
                            mp = getattr(v, 'material_path', None)
                            if mp:
                                mats ^= hash(mp) & 0xffffffff   # rebuild on recolour
                return (n, round(s, 2), mats)

            sig = (id(cells_ref) if cells_ref else id(terrain_renderer.water_data),
                   getattr(self, '_geom_version', 0), _content_sig())
            if getattr(self, '_water_vbo_sig', None) != sig or not getattr(self, '_water_vbo', None):
                out, cols = [], []
                for cell_idx, cell in self._iter_cells(terrain_renderer, canvas):
                    self._emit_cell(cell_idx, cell, is_fc2, out, cols)
                verts = np.asarray(out, dtype=np.float32)
                colarr = np.asarray(cols, dtype=np.float32)
                self._water_vcount = len(verts) // 3
                if not getattr(self, '_water_vbo', None):
                    self._water_vbo = int(glGenBuffers(1))
                glBindBuffer(GL_ARRAY_BUFFER, self._water_vbo)
                glBufferData(GL_ARRAY_BUFFER,
                             verts.nbytes if verts.size else 0,
                             verts if verts.size else None,
                             GL_STATIC_DRAW)
                # Parallel per-vertex colour buffer (each sector's material WaterColor).
                if not getattr(self, '_water_cvbo', None):
                    self._water_cvbo = int(glGenBuffers(1))
                glBindBuffer(GL_ARRAY_BUFFER, self._water_cvbo)
                glBufferData(GL_ARRAY_BUFFER,
                             colarr.nbytes if colarr.size else 0,
                             colarr if colarr.size else None,
                             GL_STATIC_DRAW)
                glBindBuffer(GL_ARRAY_BUFFER, 0)
                self._water_vbo_sig = sig

            if getattr(self, '_water_vcount', 0):
                used_shader = self._bind_water_shader(canvas)
                glBindBuffer(GL_ARRAY_BUFFER, self._water_vbo)
                glEnableClientState(GL_VERTEX_ARRAY)
                glVertexPointer(3, GL_FLOAT, 0, ctypes.c_void_p(0))
                # Feed the per-sector WaterColor via the colour array (shader reads
                # it as gl_Color). Fallback path uses a single flat blue instead.
                use_colors = bool(used_shader and getattr(self, '_water_cvbo', None))
                if use_colors:
                    glBindBuffer(GL_ARRAY_BUFFER, self._water_cvbo)
                    glEnableClientState(GL_COLOR_ARRAY)
                    glColorPointer(3, GL_FLOAT, 0, ctypes.c_void_p(0))
                else:
                    glColor4f(0.09, 0.45, 0.95, 0.50)   # fallback flat blue
                glDrawArrays(GL_QUADS, 0, self._water_vcount)
                if use_colors:
                    glDisableClientState(GL_COLOR_ARRAY)
                glDisableClientState(GL_VERTEX_ARRAY)
                glBindBuffer(GL_ARRAY_BUFFER, 0)
                if used_shader:
                    glUseProgram(0)

        except Exception as e:
            print(f"[WaterPlane] Render error: {e}")
            try:
                glUseProgram(0)
            except Exception:
                pass
        finally:
            glDisable(GL_POLYGON_OFFSET_FILL)
            glDepthMask(GL_TRUE)
            glDisable(GL_BLEND)
            glEnable(GL_LIGHTING)
            glEnable(GL_CULL_FACE)
