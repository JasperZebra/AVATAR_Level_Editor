"""
Simplified Water Mesh Editor - Modifies Terrain Model Directly
Edits the water mesh that's already in the terrain model's display list
"""

import numpy as np
from OpenGL.GL import *
import struct


class ImprovedWaterMeshEditor:
    """Edits water plane heights by modifying terrain model directly"""
    
    def __init__(self):
        self.gltf_model = None
        self.terrain_model = None
        self.water_mesh_idx = None
        self.original_vertices = None
        
        self.grid_size = 65
        self.sectors_x = 16
        self.sectors_y = 16
        self.meters_per_coordinate = 1.0
        
        # Track per-sector water heights
        self.sector_water_heights = {}
        # Changed to list of ranges per sector to handle multiple quads per sector
        self.sector_vertex_ranges = {}
        
        # Flag to trigger display list regeneration on next frame
        self.needs_regeneration = False
        
    def initialize_from_gltf_model(self, gltf_model):
        """
        Initialize from a GLTFModel object and find the water mesh
        
        Args:
            gltf_model: GLTFModel object from model_loader
        
        Returns:
            bool: True if water mesh was found and initialized
        """
        if not gltf_model or not hasattr(gltf_model, 'gltf_data'):
            print("Invalid GLTF model provided")
            return False
        
        self.terrain_model = gltf_model
        gltf = gltf_model.gltf_data
        
        # Find the Water node in the GLTF structure
        if 'nodes' not in gltf:
            print("No nodes in GLTF data")
            return False
        
        water_node_idx = None
        water_mesh_idx = None
        
        # Find node named "Water"
        for idx, node in enumerate(gltf['nodes']):
            if node.get('name') == 'Water':
                water_node_idx = idx
                water_mesh_idx = node.get('mesh')
                print(f"Found Water node at index {idx}, mesh index: {water_mesh_idx}")
                break
        
        if water_node_idx is None or water_mesh_idx is None:
            print("No Water node found in GLTF (this is normal if terrain has no water)")
            return False
        
        self.water_mesh_idx = water_mesh_idx
        
        # Find the corresponding GLTFMesh in the model's meshes list
        # The water mesh should be at index water_mesh_idx
        if water_mesh_idx >= len(gltf_model.meshes):
            print(f"Water mesh index {water_mesh_idx} out of range")
            return False
        
        # Cache the water mesh vertices
        water_mesh = gltf_model.meshes[water_mesh_idx]
        if water_mesh.vertices is None:
            print("Water mesh has no vertices")
            return False
        
        self.original_vertices = np.copy(water_mesh.vertices)
        print(f"✓ Cached {len(self.original_vertices)} water vertices")
        
        # Build sector vertex ranges
        self._build_sector_vertex_ranges()
        
        print("✓ Water mesh editor initialized - will modify terrain display list directly")
        return True
    
    def _build_sector_vertex_ranges(self):
        """Build a mapping of sector numbers to vertex index ranges"""
        if self.original_vertices is None:
            return
        
        # Each water quad has 4 vertices, so we process in groups of 4
        num_quads = len(self.original_vertices) // 4
        
        print(f"\n=== Water Vertex Coordinate Analysis ===")
        print(f"Grid size: {self.grid_size}, Sectors: {self.sectors_x}x{self.sectors_y}")
        print(f"Sector size: {self.grid_size * self.meters_per_coordinate} units")
        
        # Show first few vertices to understand coordinate system
        print(f"\nFirst 5 quads:")
        for quad_idx in range(min(5, num_quads)):
            v = self.original_vertices[quad_idx * 4]
            print(f"  Quad {quad_idx}: x={v[0]:.2f}, z={v[2]:.2f}")
        
        # GLTF is exported at scale=1.0 with shared edges, so sector width = (grid_size-1) * 1.0 = 64
        scale = 1.0
        size = (self.grid_size - 1) * scale
        sector_0_world_z = self.sectors_y * size

        print(f"\nSector 0 offset: x=0, z={sector_0_world_z:.2f}  (size={size:.3f})")

        # Debug: track ALL quads to understand the mapping
        print(f"\n=== DETAILED SECTOR MAPPING ===")
        sector_counts = {}

        for quad_idx in range(num_quads):
            vertex_start = quad_idx * 4
            vertex_end = vertex_start + 4

            # Use quad centre (average of all 4 corners) — more robust than first vertex
            quad_verts = self.original_vertices[vertex_start:vertex_end]
            vx = float(np.mean(quad_verts[:, 0]))
            vz = float(np.mean(quad_verts[:, 2]))
            first_vertex = self.original_vertices[vertex_start]

            # Convert to world coordinates and assign sector via plain floor (no offset)
            world_x = vx
            world_z = vz + sector_0_world_z

            sector_col = int(np.floor(world_x / size))
            sector_row_world = int(np.floor(world_z / size))
            
            # Flip the row to match UI numbering (UI has row 0 at bottom, coords have row 0 at top)
            # World row 15 = UI row 0, World row 0 = UI row 15
            sector_row_ui = (self.sectors_y - 1) - sector_row_world
            
            # Calculate sector number using UI row
            sector_num = sector_row_ui * self.sectors_x + sector_col
            
            # Track this for debugging
            if sector_num not in sector_counts:
                sector_counts[sector_num] = 0
            sector_counts[sector_num] += 1
            
            # Print first few quads with all calculation details
            if quad_idx < 10:
                print(f"  Quad {quad_idx}: vx={vx:.2f}, vz={vz:.2f} -> world=({world_x:.2f}, {world_z:.2f}) -> col={sector_col}, world_row={sector_row_world}, ui_row={sector_row_ui} -> sector={sector_num}")
            
            # Clamp to valid range
            if 0 <= sector_num < 256:
                # Initialize list if not exists
                if sector_num not in self.sector_vertex_ranges:
                    self.sector_vertex_ranges[sector_num] = []
                
                # Append this vertex range to the sector's list
                self.sector_vertex_ranges[sector_num].append((vertex_start, vertex_end))
                
                # Also cache the initial height
                initial_height = first_vertex[1]
                self.sector_water_heights[sector_num] = initial_height
        
        # Print summary
        print(f"\n=== SECTOR SUMMARY ===")
        print(f"Found quads in sectors: {sorted(sector_counts.keys())}")
        for sector in sorted(sector_counts.keys())[:20]:  # First 20 sectors
            print(f"  Sector {sector}: {sector_counts[sector]} quads")
        print(f"Total: {len(sector_counts)} unique sectors with water")
        
        print(f"\nBuilt vertex ranges for {len(self.sector_vertex_ranges)} water sectors")
        print("="*50 + "\n")

    def update_sector_water_height(self, sector_num, new_height, terrain_renderer=None):
        """
        Update water height for a specific sector - modifies terrain model directly
        
        Args:
            sector_num: Sector index (0-255)
            new_height: New water height value
            terrain_renderer: Optional terrain renderer (not used)
            
        Returns:
            bool: True if successful
        """
        if self.original_vertices is None or self.terrain_model is None:
            print("Water mesh not initialized")
            return False
        
        # Check if we have vertex ranges for this sector
        if sector_num not in self.sector_vertex_ranges:
            print(f"ℹ️  Sector {sector_num} has water data in CSDAT file but no 3D water mesh geometry")
            print(f"   Available water mesh sectors: {sorted(self.sector_vertex_ranges.keys())}")
            return False
        
        # Get all vertex ranges for this sector
        vertex_ranges = self.sector_vertex_ranges[sector_num]
        
        # Get the actual water mesh from the terrain model
        water_mesh = self.terrain_model.meshes[self.water_mesh_idx]
        
        # Update vertices in the mesh (Y component only) for all ranges
        vertices_updated = 0
        for vertex_start, vertex_end in vertex_ranges:
            for i in range(vertex_start, vertex_end):
                water_mesh.vertices[i][1] = new_height
                self.original_vertices[i][1] = new_height
                vertices_updated += 1
        
        # Cache the new height
        self.sector_water_heights[sector_num] = new_height
        
        print(f"✓ Updated {vertices_updated} vertices across {len(vertex_ranges)} quad(s) in sector {sector_num} to height {new_height:.2f}")
        
        # Mark that display list needs regeneration (will happen on next frame)
        self.needs_regeneration = True
        
        return True
    
    def _regenerate_display_list(self):
        """Regenerate the terrain model's display list with updated water vertices"""
        if not self.terrain_model or not self.terrain_model.meshes:
            return
        
        try:
            # Delete old display list
            if self.terrain_model.display_list:
                glDeleteLists(self.terrain_model.display_list, 1)
            
            # Create new display list with updated vertices
            self.terrain_model.display_list = glGenLists(1)
            glNewList(self.terrain_model.display_list, GL_COMPILE)
            
            for mesh in self.terrain_model.meshes:
                if mesh.vertices is None:
                    continue
                
                has_uvs = mesh.uvs is not None and len(mesh.uvs) > 0
                has_texture = mesh.material_index is not None and mesh.material_index in self.terrain_model.textures
                
                # Enable texture if available
                if has_texture:
                    glEnable(GL_TEXTURE_2D)
                    glBindTexture(GL_TEXTURE_2D, self.terrain_model.textures[mesh.material_index])
                    glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
                    glColor4f(1.0, 1.0, 1.0, 1.0)
                else:
                    glDisable(GL_TEXTURE_2D)
                    glColor4f(0.7, 0.7, 0.7, 1.0)
                
                glEnableClientState(GL_VERTEX_ARRAY)
                glVertexPointer(3, GL_FLOAT, 0, mesh.vertices)
                
                if mesh.normals is not None:
                    glEnableClientState(GL_NORMAL_ARRAY)
                    glNormalPointer(GL_FLOAT, 0, mesh.normals)
                
                if has_uvs and has_texture:
                    glEnableClientState(GL_TEXTURE_COORD_ARRAY)
                    glTexCoordPointer(2, GL_FLOAT, 0, mesh.uvs)
                
                # Draw the mesh
                if mesh.indices is not None and len(mesh.indices) > 0:
                    # Make sure indices are contiguous numpy array
                    indices = np.ascontiguousarray(mesh.indices, dtype=np.uint32)
                    glDrawElements(GL_TRIANGLES, len(indices), GL_UNSIGNED_INT, indices)
                else:
                    glDrawArrays(GL_TRIANGLES, 0, len(mesh.vertices))
                
                glDisableClientState(GL_VERTEX_ARRAY)
                if mesh.normals is not None:
                    glDisableClientState(GL_NORMAL_ARRAY)
                if has_uvs and has_texture:
                    glDisableClientState(GL_TEXTURE_COORD_ARRAY)
                
                if has_texture:
                    glBindTexture(GL_TEXTURE_2D, 0)
                    glDisable(GL_TEXTURE_2D)
            
            glEndList()
            
            print(f"✓ Regenerated terrain display list")
        
        except Exception as e:
            print(f"Error regenerating display list: {e}")
            import traceback
            traceback.print_exc()
    
    def remove_sector_water(self, sector_num, terrain_renderer=None):
        """Remove water from a sector by moving its vertices to Y=0"""
        return self.update_sector_water_height(sector_num, 0.0, terrain_renderer)
    
    def get_sector_water_height(self, sector_num):
        """Get the current water height for a sector"""
        return self.sector_water_heights.get(sector_num, 0.0)
    
    def bulk_update_water_heights(self, sector_height_dict):
        """
        Update multiple sectors at once
        
        Args:
            sector_height_dict: Dictionary of {sector_num: height}
        """
        if self.original_vertices is None or self.terrain_model is None:
            return False
        
        water_mesh = self.terrain_model.meshes[self.water_mesh_idx]
        total_updated = 0
        
        # Update all sectors
        for sector_num, new_height in sector_height_dict.items():
            if sector_num in self.sector_vertex_ranges:
                # Get all vertex ranges for this sector
                vertex_ranges = self.sector_vertex_ranges[sector_num]
                
                for vertex_start, vertex_end in vertex_ranges:
                    for i in range(vertex_start, vertex_end):
                        water_mesh.vertices[i][1] = new_height
                        self.original_vertices[i][1] = new_height
                        total_updated += 1
                
                self.sector_water_heights[sector_num] = new_height
        
        print(f"✓ Bulk updated {total_updated} vertices across {len(sector_height_dict)} sectors")
        
        # Mark that display list needs regeneration
        self.needs_regeneration = True
        
        return True
    
    def regenerate_if_needed(self):
        """Check if display list needs regeneration and do it if safe"""
        if self.needs_regeneration:
            self._regenerate_display_list()
            self.needs_regeneration = False