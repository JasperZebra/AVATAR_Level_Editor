"""Renders translucent per-sector water planes in the 3D view."""

from OpenGL.GL import *


class WaterPlaneRenderer:
    """Draws a flat translucent quad for every sector whose water flag is active.

    Renders ALL active sectors procedurally regardless of whether the GLTF
    terrain model also contains a baked water mesh. glPolygonOffset ensures the
    procedural plane wins the depth test when the two overlap at the same height,
    eliminating Z-fighting flicker.
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
            glDepthMask(GL_FALSE)
            # Pull procedural planes in front of baked GLTF water at the same depth
            glEnable(GL_POLYGON_OFFSET_FILL)
            glPolygonOffset(-1.0, -1.0)
            glColor4f(0.05, 0.35, 0.90, 0.45)

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
