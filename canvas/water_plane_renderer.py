"""Renders translucent per-sector water planes in the 3D view.

This is the editor's ONLY water display. Older terrain GLTFs also contained a
baked water mesh (a second, slightly transparent plane at the same height);
terrain generation no longer emits it, and `strip_baked_water` removes it from
cached terrain files at load time.
"""

from OpenGL.GL import *


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
        """Rendering is fully dynamic — nothing to invalidate."""
        pass

    def render_water_planes(self, terrain_renderer, canvas=None, water_mesh_editor=None):
        if not terrain_renderer or not terrain_renderer.water_data:
            return

        sx = getattr(terrain_renderer, 'sectors_x', 16)
        sy = getattr(terrain_renderer, 'sectors_y', 16)
        ox = getattr(terrain_renderer, 'terrain_offset_x', 0.0)
        oy = getattr(terrain_renderer, 'terrain_offset_y', 0.0)

        # Derive sector dimensions from combined heightmap if available.
        # With shared-edge assembly (1025×1025), world extent = w_px - 1 = 1024,
        # so each of 16 sectors spans (w_px-1)/sx = 64 world units.
        combined = terrain_renderer.combined_heightmap
        if combined is None and canvas is not None:
            td = getattr(canvas, '_terrain_data', None)
            if td is not None:
                combined = td.combined

        if combined is not None:
            h_px, w_px = combined.shape
            sector_w = float(w_px - 1) / max(sx, 1)
            sector_h = float(h_px - 1) / max(sy, 1)
        else:
            # Fallback: 64 steps per sector at scale 1.0
            sector_w = 64.0
            sector_h = 64.0

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
            # Match the old baked-water look it replaced: dodger-blue at ~0.7
            # alpha (was 0.45 — too pale once the baked plane was removed).
            glColor4f(0.09, 0.45, 0.95, 0.70)

            glBegin(GL_QUADS)
            for sector_num, wd in terrain_renderer.water_data.items():
                if not wd.has_water:
                    continue
                col = sector_num % sx
                row = sector_num // sx   # 0 = bottom of map

                x0 = ox + col * sector_w
                x1 = ox + (col + 1) * sector_w
                z0 = -(oy + row * sector_h)
                z1 = -(oy + (row + 1) * sector_h)
                y = float(wd.water_height)

                glVertex3f(x0, y, z0)
                glVertex3f(x1, y, z0)
                glVertex3f(x1, y, z1)
                glVertex3f(x0, y, z1)
            glEnd()

        except Exception as e:
            print(f"[WaterPlane] Render error: {e}")
        finally:
            glDisable(GL_POLYGON_OFFSET_FILL)
            glDepthMask(GL_TRUE)
            glDisable(GL_BLEND)
            glEnable(GL_LIGHTING)
            glEnable(GL_CULL_FACE)
