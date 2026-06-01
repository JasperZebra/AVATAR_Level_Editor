#!/usr/bin/env python3
"""
Avatar Terrain to GLTF Exporter with Texture Support - FIXED VERSION
Reads CSDAT heightmap files and XBT textures to create 3D terrain in GLTF format

FIXES:
1. Removed custom normals by default (prevents dark mesh in Blender)
2. Atlas texture extraction matches the viewer script
3. Texture orientation consistent with heightmap

Usage:
  terrain_to_gltf.py i-[input_path] o-[output_path] r-[resolution] s-[scale]
  
Example:
  terrain_to_gltf.py i-D:\Games\Avatar The Game\Data_Win32\Data\levels\sp_hellsgate_01_l o-C:\Test\3D terrain r-25000 s-1.0
  
Parameters:
  i- : Input path (level directory)
  o- : Output path (where to save GLTF)
  r- : Resolution in triangles (default: 25000)
  s- : Meters per coordinate scale (default: 1.0)
"""

import sys
import os
import struct
import io
import glob
import json
import base64
import math
import tempfile
from pathlib import Path

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("WARNING: PIL/Pillow not available. Texture support will be limited.")

import numpy as np


class TerrainExporter:
    def __init__(self, input_path, output_path, resolution, meters_per_coordinate=1.0, game_mode="avatar"):
        self.input_path = Path(input_path)
        self.output_path = Path(output_path)
        self.resolution = resolution
        self.meters_per_coordinate = meters_per_coordinate
        self.game_mode = game_mode
        self.grid_size = 65  # Each sector is 65x65
        self.sectors_data = {}
        self.sectors_textures = {}
        self.atlas_mapping = {}
        self._sector_file_paths = {}  # local_idx (or global_id before remap) → file_path

        # Per-game format settings
        if game_mode == "farcry2":
            self._file_ext = ".sdat"
            self._terrain_offset = 592
        else:
            self._file_ext = ".csdat"
            self._terrain_offset = 708

        # Find sdat directory - try multiple possible locations
        self.sdat_path = self._find_sdat_directory()
        if self.sdat_path is None:
            raise FileNotFoundError(
                f"SDAT directory not found!\n"
                f"Searched in:\n"
                f"  - {self.input_path / 'generated' / 'sdat'}\n"
                f"  - {self.input_path / 'sdat'}\n"
                f"  - {self.input_path}\n"
                f"\nPlease ensure the input path contains sd*{self._file_ext} files."
            )
        
        print(f"Input path: {self.input_path}")
        print(f"SDAT path: {self.sdat_path}")
        print(f"Output path: {self.output_path}")
        print(f"Target resolution: {self.resolution} triangles")
        print(f"Scale: {self.meters_per_coordinate} meters per coordinate")
    
    def _find_sdat_directory(self):
        """Find the sdat directory by searching in multiple locations"""
        possible_paths = [
            self.input_path / "generated" / "sdat",
            self.input_path / "sdat",
            self.input_path
        ]

        for path in possible_paths:
            if path.exists():
                test_pattern = str(path / f"sd*{self._file_ext}")
                if glob.glob(test_pattern):
                    print(f"Found {self._file_ext} files in: {path}")
                    return path

        return None
    
    def load_heightmap_from_csdat(self, file_path):
        """Load heightmap data from a sector file (.csdat or .sdat)"""
        try:
            heightmap = []
            with open(file_path, 'rb') as f:
                f.seek(self._terrain_offset)
                terrain_data = io.BytesIO(f.read())
            
            for y in range(self.grid_size):
                row = []
                for x in range(self.grid_size):
                    # Read only first 2 bytes (little-endian)
                    bytes_data = terrain_data.read(2)
                    if len(bytes_data) < 2:
                        height = 0
                    else:
                        # Divide by 128 to get correct scale (same as Blender importer)
                        height = struct.unpack('<H', bytes_data)[0] / 128
                    
                    row.append(height)
                    
                    # Skip remaining 2 bytes (we ignore them)
                    terrain_data.read(2)
                
                heightmap.append(row)
            
            return np.array(heightmap)
        except Exception as e:
            print(f"Error loading heightmap from {file_path}: {e}")
            return None
    
    def extract_dds_from_xbt(self, xbt_data):
        """Extract DDS data from XBT container"""
        try:
            # Check for TBX header
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
            
            # Verify DDS signature
            if len(dds_data) >= 4 and dds_data[:4] == b'DDS ':
                return dds_data
            
            # Try alternate header sizes
            for header_size in [64, 128, 256]:
                if len(xbt_data) > header_size:
                    test_data = xbt_data[header_size:]
                    if len(test_data) >= 4 and test_data[:4] == b'DDS ':
                        return test_data
        
        except Exception as e:
            print(f"Error extracting DDS: {e}")
        
        return None
    
    def load_xbt_as_dds(self, xbt_path):
        """Load .xbt file by extracting DDS data after the header"""
        if not PIL_AVAILABLE:
            return None
        
        try:
            with open(xbt_path, 'rb') as f:
                xbt_data = f.read()
            
            dds_data = self.extract_dds_from_xbt(xbt_data)
            if not dds_data:
                return None
            
            # Save to temp file and load with PIL
            with tempfile.NamedTemporaryFile(suffix='.dds', delete=False) as temp_dds:
                temp_dds.write(dds_data)
                temp_dds_path = temp_dds.name
            
            try:
                with Image.open(temp_dds_path) as img:
                    img.load()
                    img_copy = img.convert('RGB')
                return img_copy
            finally:
                try:
                    os.unlink(temp_dds_path)
                except:
                    pass
        
        except Exception as e:
            print(f"Error loading XBT {xbt_path}: {e}")
        
        return None
    
    def build_atlas_mapping(self):
        """Build mapping between atlas files and sectors
        
        Standard mapping: Each atlas contains 4 sectors in sequential order.
        Atlas N contains 4 sectors arranged in a 2x2 grid:
        
        Grid layout in each atlas image:
        [0][1]  (top row)
        [2][3]  (bottom row)
        
        This matches the viewer script's "Standard" pattern.
        """
        self.atlas_mapping = {}
        
        # Find all diffuse atlas files
        atlas_files = []
        for ext in ['.xbt', '.dds']:
            pattern = f'atlas*_d{ext}'
            files = glob.glob(str(self.sdat_path / pattern))
            atlas_files.extend(files)
            
            # Also try without _d suffix
            pattern = f'atlas*_diffuse{ext}'
            files = glob.glob(str(self.sdat_path / pattern))
            atlas_files.extend(files)
            
            # And try just atlas* for color
            pattern = f'atlas*_color{ext}'
            files = glob.glob(str(self.sdat_path / pattern))
            atlas_files.extend(files)
        
        # Extract unique atlas numbers
        atlas_numbers = set()
        for filepath in atlas_files:
            filename = os.path.basename(filepath)
            try:
                # Extract number from "atlas123_d.xbt" -> 123
                parts = filename.split('_')[0]
                num = int(parts.replace('atlas', ''))
                atlas_numbers.add(num)
            except (ValueError, IndexError):
                continue
        
        atlas_numbers = sorted(list(atlas_numbers))
        
        if atlas_numbers:
            print(f"\nFound {len(atlas_numbers)} texture atlas files")
            
            # Map each atlas to its 4 sectors (standard sequential mapping)
            for atlas_index, atlas_num in enumerate(atlas_numbers):
                base_sector = atlas_index * 4
                for sub_sector in range(4):
                    sector_num = base_sector + sub_sector
                    self.atlas_mapping[sector_num] = (atlas_num, sub_sector)
            
            print(f"Mapped {len(self.atlas_mapping)} sectors to atlas files")
        else:
            print("\nNo texture atlas files found")
    
    def load_sector_texture(self, sector_num):
        """Load texture for a sector from atlas
        
        Standard extraction pattern (matches viewer script):
        - sub_sector 0 = Top-Left (TL)
        - sub_sector 1 = Top-Right (TR)
        - sub_sector 2 = Bottom-Left (BL)
        - sub_sector 3 = Bottom-Right (BR)
        """
        if sector_num not in self.atlas_mapping:
            return None
        
        atlas_num, sub_sector = self.atlas_mapping[sector_num]
        
        # Try to find the atlas file
        patterns = [
            f"atlas{atlas_num}_d.xbt",
            f"atlas{atlas_num}_diffuse.xbt",
            f"atlas{atlas_num}_color.xbt",
            f"atlas{atlas_num}_d.dds",
            f"atlas{atlas_num}_diffuse.dds",
            f"atlas{atlas_num}_color.dds",
        ]
        
        for pattern in patterns:
            texture_path = self.sdat_path / pattern
            if texture_path.exists():
                try:
                    if str(texture_path).endswith('.xbt'):
                        img = self.load_xbt_as_dds(texture_path)
                        if img is None:
                            continue
                    else:
                        img = Image.open(texture_path)
                        img = img.convert('RGB')
                    
                    img_array = np.array(img)
                    
                    # Extract quadrant (2x2 grid)
                    # Standard layout: TL=0, TR=1, BL=2, BR=3
                    height, width = img_array.shape[:2]
                    half_h = height // 2
                    half_w = width // 2
                    
                    if sub_sector == 0:  # Top-Left
                        sub_texture = img_array[0:half_h, 0:half_w]
                    elif sub_sector == 1:  # Top-Right
                        sub_texture = img_array[0:half_h, half_w:width]
                    elif sub_sector == 2:  # Bottom-Left
                        sub_texture = img_array[half_h:height, 0:half_w]
                    else:  # sub_sector == 3, Bottom-Right
                        sub_texture = img_array[half_h:height, half_w:width]
                    
                    # Resize to match sector grid size
                    sub_img = Image.fromarray(sub_texture)
                    sub_img = sub_img.resize((self.grid_size, self.grid_size), Image.Resampling.LANCZOS)
                    
                    return np.array(sub_img)
                except Exception as e:
                    print(f"Error loading texture from {texture_path}: {e}")
        
        return None
    
    def load_all_sectors(self):
        """Load all sector heightmap files (.csdat or .sdat)"""
        pattern = str(self.sdat_path / f"sd*{self._file_ext}")
        files = glob.glob(pattern)

        print(f"\nLoading {self.game_mode} sectors ({self._file_ext})...")
        loaded_count = 0
        ext_len = len(self._file_ext)  # e.g. 6 for .csdat, 5 for .sdat
        # Keep global_id → file_path so water-data loading can use real file names
        # after the FC2 local-index remap (which changes sectors_data keys but not files).
        self._sector_file_paths = {}  # global_sector_num → file_path

        for file_path in files:
            filename = os.path.basename(file_path)
            try:
                # Strip leading "sd" and trailing extension to get the sector number
                sector_num = int(filename[2:-ext_len])
                heightmap = self.load_heightmap_from_csdat(file_path)

                if heightmap is not None:
                    self.sectors_data[sector_num] = heightmap
                    self._sector_file_paths[sector_num] = file_path
                    loaded_count += 1
                    print(f"  Loaded sector {sector_num}")
            except ValueError:
                continue

        print(f"Loaded {loaded_count} sectors")

        # FC2: sector files use global world-level indices (e.g. 2592-3807).
        # Remap to local 0-based so calculate_grid_dimensions works correctly.
        if loaded_count > 0 and self.game_mode == "farcry2":
            sorted_nums = sorted(self.sectors_data.keys())
            min_s = sorted_nums[0]
            if min_s > 0:
                gap_found = False
                secs_per_row = len(sorted_nums)
                row_stride = secs_per_row
                for i in range(1, len(sorted_nums)):
                    if sorted_nums[i] - sorted_nums[i - 1] > 1:
                        secs_per_row = i
                        row_stride = sorted_nums[i] - sorted_nums[0]
                        gap_found = True
                        break
                if gap_found:
                    remapped_s = {}
                    remapped_files = {}  # local_idx → file_path (parallel to remapped_s)
                    for sn in sorted_nums:
                        diff = sn - min_s
                        local_idx = (diff // row_stride) * secs_per_row + (diff % row_stride)
                        remapped_s[local_idx] = self.sectors_data[sn]
                        if sn in self._sector_file_paths:
                            remapped_files[local_idx] = self._sector_file_paths[sn]
                    self.sectors_data = remapped_s
                    self._sector_file_paths = remapped_files
                    self._fc2_sector_base = min_s
                    self._fc2_row_stride = row_stride
                    self._fc2_secs_per_row = secs_per_row
                    print(f"FC2 remap: {loaded_count} sectors, "
                          f"global[{min_s}..{sorted_nums[-1]}] → local[0..{max(remapped_s)}], "
                          f"row_stride={row_stride}, secs_per_row={secs_per_row}")

        return loaded_count > 0
    
    def load_all_textures(self):
        """Load all texture data"""
        if not PIL_AVAILABLE:
            print("\nSkipping texture loading (PIL not available)")
            return
        
        print("\nLoading textures...")
        self.build_atlas_mapping()
        
        loaded_count = 0
        for sector_num in self.sectors_data.keys():
            texture = self.load_sector_texture(sector_num)
            if texture is not None:
                self.sectors_textures[sector_num] = texture
                loaded_count += 1
        
        print(f"Loaded {loaded_count} textures")

    def get_sector_index_from_position(self, display_row, col, sectors_x, sectors_y):
        """Calculate sector index using Avatar Game Layout pattern.
        
        Avatar Game Layout:
        - 2x2 blocks are placed VERTICALLY down first, then across
        - Within each 2x2 block, positions 1 and 2 are SWAPPED:
          Standard: TL=0, TR=1, BL=2, BR=3
          Avatar:   TL=0, TR=2, BL=1, BR=3 (swap 1↔2)
        
        This matches the viewer script's default "Avatar Game Layout (2x2 blocks, vertical)" pattern.
        """
        # Calculate which 2x2 block this position belongs to
        block_col = col // 2
        block_row = display_row // 2
        
        # Position within the 2x2 block
        within_block_col = col % 2  # 0=left, 1=right
        within_block_row = display_row % 2  # 0=top, 1=bottom
        
        # Calculate which 2x2 grid this is (going DOWN first, then across)
        blocks_per_column = sectors_y // 2
        atlas_block_index = block_col * blocks_per_column + block_row
        
        # Base sector for this atlas (each atlas has 4 sectors)
        base_sector = atlas_block_index * 4
        
        # Position within the 2x2 block with Avatar's swap of positions 1 and 2
        if within_block_row == 0 and within_block_col == 0:
            offset = 0  # Top-left stays 0
        elif within_block_row == 0 and within_block_col == 1:
            offset = 2  # Top-right gets 2 (swapped from 1)
        elif within_block_row == 1 and within_block_col == 0:
            offset = 1  # Bottom-left gets 1 (swapped from 2)
        else:  # within_block_row == 1 and within_block_col == 1
            offset = 3  # Bottom-right stays 3
        
        sector_index = base_sector + offset
        return sector_index
    
    def calculate_grid_dimensions(self):
        """Calculate optimal grid dimensions based on available sectors"""
        if not self.sectors_data:
            return 1, 1
        
        max_sector = max(self.sectors_data.keys())
        total_sectors = len(self.sectors_data)
        
        # Try to detect common patterns first
        if max_sector + 1 == 256:  # 256 sectors = 16x16
            return 16, 16
        elif max_sector + 1 == 64:  # 64 sectors = 8x8
            return 8, 8
        elif max_sector + 1 == 144:  # 144 sectors = 12x12
            return 12, 12
        elif max_sector + 1 == 8:  # 8 sectors = 4x2 (4 wide, 2 tall)
            return 4, 2
        elif max_sector + 1 == 32:  # 32 sectors = 8x4
            return 8, 4
        elif max_sector + 1 == 16:  # 16 sectors = 4x4
            return 4, 4
        elif max_sector + 1 == 4:  # 4 sectors = 2x2
            return 2, 2
        else:
            # For other cases, try to find best rectangular fit
            # Prefer wider layouts (Avatar uses 2x2 blocks arranged horizontally)
            num_sectors = max_sector + 1
            
            # Try to find divisors that give us a reasonable aspect ratio
            best_width = int(math.ceil(math.sqrt(num_sectors)))
            best_height = int(math.ceil(num_sectors / best_width))
            
            # Adjust to prefer wider layouts (aspect ratio closer to 2:1 or 4:2)
            for width in range(best_width, 0, -1):
                if num_sectors % width == 0:
                    height = num_sectors // width
                    if width >= height:  # Prefer width >= height
                        return width, height
            
            # Fallback to calculated values
            return best_width, best_height
    
    def create_combined_heightmap(self, sectors_x, sectors_y):
        """Combine all sector heightmaps into one large heightmap with shared edges.

        Sectors share their border pixels so there is exactly one sample at every
        sector boundary — this matches in-game geometry and eliminates seams.
        """
        step = self.grid_size - 1   # 64 steps between shared edge pixels
        total_width  = sectors_x * step + 1   # 1025 for 16×16
        total_height = sectors_y * step + 1

        combined = np.zeros((total_height, total_width))

        print("\nAssembling heightmap with shared edges (seam-free sector boundaries)...")

        for display_row in range(sectors_y):
            for col in range(sectors_x):
                sector_row = sectors_y - 1 - display_row
                sector_index = sector_row * sectors_x + col

                if sector_index in self.sectors_data:
                    r0 = display_row * step
                    c0 = col * step
                    sector_data = self.sectors_data[sector_index]
                    combined[r0:r0+self.grid_size, c0:c0+self.grid_size] = np.flipud(sector_data)

                    if col == 0:  # Print once per row
                        print(f"  Row {display_row}: sector {sector_index} at position ({col}, {display_row})")

        return combined
    
    def create_combined_texture(self, sectors_x, sectors_y):
        """Combine all sector textures into one large texture using Avatar Game Layout
        
        Important: Textures must match the heightmap orientation!
        Both use Avatar Game Layout (2x2 blocks, vertical) with NO flip.
        """
        if not self.sectors_textures:
            return None
        
        total_width = sectors_x * self.grid_size
        total_height = sectors_y * self.grid_size
        
        combined = np.zeros((total_height, total_width, 3), dtype=np.uint8)
        
        print(f"\nCreating combined texture at full resolution: {total_width}x{total_height}")
        print("Using Avatar Game Layout (2x2 blocks, vertical)...")
        
        for display_row in range(sectors_y):
            for col in range(sectors_x):
                # Use Avatar Game Layout pattern (matches heightmap)
                sector_index = self.get_sector_index_from_position(display_row, col, sectors_x, sectors_y)
                
                if sector_index in self.sectors_textures:
                    start_y = display_row * self.grid_size
                    start_x = col * self.grid_size
                    
                    # Get texture for this sector (already 65x65)
                    texture_data = self.sectors_textures[sector_index]
                    
                    # Avatar layout: NO flip (textures match heightmap orientation)
                    combined[start_y:start_y+self.grid_size, start_x:start_x+self.grid_size] = texture_data
        
        return combined
    
    def downsample_heightmap(self, heightmap, target_resolution):
        """Downsample heightmap to target resolution"""
        height, width = heightmap.shape
        
        # Calculate downsample factor based on target triangle count
        target_verts = int(math.sqrt(target_resolution / 2))
        
        factor_x = max(1, width // target_verts)
        factor_y = max(1, height // target_verts)
        factor = max(factor_x, factor_y)
        
        if factor <= 1:
            return heightmap, width, height
        
        new_width = width // factor
        new_height = height // factor
        
        print(f"Downsampling from {width}x{height} to {new_width}x{new_height} (factor: {factor})")
        
        # Use PIL for high-quality downsampling
        img = Image.fromarray(heightmap.astype(np.float32))
        img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        return np.array(img_resized), new_width, new_height
    
    def downsample_texture(self, texture, target_width, target_height):
        """Downsample texture to match heightmap dimensions"""
        if texture is None:
            return None
        
        print(f"Downsampling texture to {target_width}x{target_height}")
        img = Image.fromarray(texture)
        img_resized = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
        
        return np.array(img_resized)
    
    def texture_to_base64_png(self, texture):
        """Convert texture array to base64 PNG"""
        img = Image.fromarray(texture)
        
        # Save to bytes
        png_buffer = io.BytesIO()
        img.save(png_buffer, format='PNG')
        png_data = png_buffer.getvalue()
        
        # Encode as base64
        base64_string = base64.b64encode(png_data).decode('ascii')
        
        return base64_string
    
    def create_gltf(self, heightmap, width, height, texture=None, sectors_x=1, sectors_y=1, water_texture=None):
        """Create GLTF file from heightmap data with optional texture and water planes
        
        FIXED: No custom normals by default - Blender will calculate smooth normals automatically.
        This prevents the "dark mesh" issue caused by custom normal attributes.
        """
        print("\nGenerating GLTF mesh...")
        print("NOTE: Custom normals disabled - Blender will auto-smooth for proper lighting")
        
        # Calculate real-world dimensions (step-based: sectors share edge pixels)
        step = self.grid_size - 1   # 64
        real_width  = sectors_x * step * self.meters_per_coordinate
        real_height = sectors_y * step * self.meters_per_coordinate

        print(f"Real-world dimensions: {real_width}m x {real_height}m")
        print(f"Grid layout: {sectors_x}x{sectors_y} sectors")

        # Calculate where sector 0 is positioned in world space
        sector_0_display_row = sectors_y - 1
        sector_0_col = 0
        sector_0_world_x = sector_0_col * step * self.meters_per_coordinate
        sector_0_world_z = sectors_y * step * self.meters_per_coordinate
        
        print(f"Sector 0 at grid position (col={sector_0_col}, display_row={sector_0_display_row})")
        print(f"Sector 0 BOTTOM-LEFT corner offset: X={sector_0_world_x:.2f}m, Z={sector_0_world_z:.2f}m")
        
        # Create terrain vertices
        vertices = []
        uvs = []
        indices = []
        
        scale_z = 1.0
        
        # Generate terrain vertices
        for y in range(height):
            for x in range(width):
                norm_x = x / (width - 1) if width > 1 else 0.5
                norm_y = y / (height - 1) if height > 1 else 0.5
                
                px = norm_x * real_width - sector_0_world_x
                pz = norm_y * real_height - sector_0_world_z
                py = heightmap[y, x] * scale_z
                
                vertices.extend([px, py, pz])
                
                # UV coordinates - rotated 90 degrees counter-clockwise
                u = x / (width - 1)
                v = y / (height - 1)
                rotated_u = 1 - v
                rotated_v = u
                uvs.extend([rotated_u, rotated_v])
        
        # Generate terrain indices
        for y in range(height - 1):
            for x in range(width - 1):
                i0 = y * width + x
                i1 = y * width + (x + 1)
                i2 = (y + 1) * width + x
                i3 = (y + 1) * width + (x + 1)
                
                indices.extend([i0, i2, i1])
                indices.extend([i1, i2, i3])
        
        print(f"Generated {len(vertices) // 3} vertices, {len(indices) // 3} triangles")
        
        # Generate water planes
        water_planes = self.create_water_planes(sectors_x, sectors_y)
        water_mesh_data = self.create_water_mesh_data(water_planes, sectors_x, sectors_y) if water_planes else None
        
        # Convert to binary buffers - TERRAIN
        vertices_bytes = struct.pack(f'{len(vertices)}f', *vertices)
        uvs_bytes = struct.pack(f'{len(uvs)}f', *uvs)
        indices_bytes = struct.pack(f'{len(indices)}I', *indices)
        
        # Calculate terrain buffer offsets
        terrain_vertices_offset = 0
        terrain_uvs_offset = len(vertices_bytes)
        terrain_indices_offset = terrain_uvs_offset + len(uvs_bytes)
        
        # Start building buffer
        buffer_data = vertices_bytes + uvs_bytes + indices_bytes
        
        # Add water mesh data if exists
        water_vertices_offset = 0
        water_uvs_offset = 0
        water_indices_offset = 0
        
        if water_mesh_data:
            water_vertices_bytes = struct.pack(f'{len(water_mesh_data["vertices"])}f', *water_mesh_data["vertices"])
            water_uvs_bytes = struct.pack(f'{len(water_mesh_data["uvs"])}f', *water_mesh_data["uvs"])
            water_indices_bytes = struct.pack(f'{len(water_mesh_data["indices"])}I', *water_mesh_data["indices"])
            
            water_vertices_offset = len(buffer_data)
            buffer_data += water_vertices_bytes
            
            water_uvs_offset = len(buffer_data)
            buffer_data += water_uvs_bytes
            
            water_indices_offset = len(buffer_data)
            buffer_data += water_indices_bytes
        
        # Find min/max for bounding box
        min_x = min_y = min_z = float('inf')
        max_x = max_y = max_z = float('-inf')
        
        for i in range(0, len(vertices), 3):
            min_x = min(min_x, vertices[i])
            max_x = max(max_x, vertices[i])
            min_y = min(min_y, vertices[i + 1])
            max_y = max(max_y, vertices[i + 1])
            min_z = min(min_z, vertices[i + 2])
            max_z = max(max_z, vertices[i + 2])
        
        min_x = float(min_x)
        max_x = float(max_x)
        min_y = float(min_y)
        max_y = float(max_y)
        min_z = float(min_z)
        max_z = float(max_z)
        
        # Build accessors list
        accessors = [
            {  # 0: Terrain POSITION
                "bufferView": 0,
                "componentType": 5126,
                "count": len(vertices) // 3,
                "type": "VEC3",
                "min": [min_x, min_y, min_z],
                "max": [max_x, max_y, max_z]
            },
            {  # 1: Terrain TEXCOORD_0
                "bufferView": 1,
                "componentType": 5126,
                "count": len(uvs) // 2,
                "type": "VEC2"
            },
            {  # 2: Terrain INDICES
                "bufferView": 2,
                "componentType": 5125,
                "count": len(indices),
                "type": "SCALAR"
            }
        ]
        
        # Build buffer views list
        buffer_views = [
            {  # 0: Terrain POSITION
                "buffer": 0,
                "byteOffset": terrain_vertices_offset,
                "byteLength": len(vertices_bytes),
                "target": 34962
            },
            {  # 1: Terrain TEXCOORD_0
                "buffer": 0,
                "byteOffset": terrain_uvs_offset,
                "byteLength": len(uvs_bytes),
                "target": 34962
            },
            {  # 2: Terrain INDICES
                "buffer": 0,
                "byteOffset": terrain_indices_offset,
                "byteLength": len(indices_bytes),
                "target": 34963
            }
        ]
        
        # Build meshes list
        meshes = [
            {  # Terrain mesh
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": 0,
                            "TEXCOORD_0": 1
                        },
                        "indices": 2,
                        "mode": 4
                    }
                ],
                "name": "TerrainMesh"
            }
        ]
        
        # Build nodes list
        nodes = [
            {
                "mesh": 0,
                "name": "Terrain"
            }
        ]
        
        # Add water mesh if exists
        if water_mesh_data:
            # Add water accessors
            water_vertex_count = len(water_mesh_data["vertices"]) // 3
            water_index_count = len(water_mesh_data["indices"])
            
            accessors.extend([
                {  # 3: Water POSITION
                    "bufferView": 3,
                    "componentType": 5126,
                    "count": water_vertex_count,
                    "type": "VEC3"
                },
                {  # 4: Water TEXCOORD_0
                    "bufferView": 4,
                    "componentType": 5126,
                    "count": water_vertex_count,
                    "type": "VEC2"
                },
                {  # 5: Water INDICES
                    "bufferView": 5,
                    "componentType": 5125,
                    "count": water_index_count,
                    "type": "SCALAR"
                }
            ])
            
            # Add water buffer views
            buffer_views.extend([
                {  # 3: Water POSITION
                    "buffer": 0,
                    "byteOffset": water_vertices_offset,
                    "byteLength": len(water_vertices_bytes),
                    "target": 34962
                },
                {  # 4: Water TEXCOORD_0
                    "buffer": 0,
                    "byteOffset": water_uvs_offset,
                    "byteLength": len(water_uvs_bytes),
                    "target": 34962
                },
                {  # 5: Water INDICES
                    "buffer": 0,
                    "byteOffset": water_indices_offset,
                    "byteLength": len(water_indices_bytes),
                    "target": 34963
                }
            ])
            
            # Add water mesh
            meshes.append({
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": 3,
                            "TEXCOORD_0": 4
                        },
                        "indices": 5,
                        "mode": 4,
                        "material": 1  # Water material
                    }
                ],
                "name": "WaterMesh"
            })
            
            # Add water node
            nodes.append({
                "mesh": 1,
                "name": "Water"
            })
        
        # Create GLTF structure
        gltf = {
            "asset": {
                "version": "2.0",
                "generator": "Avatar Terrain Exporter (with Water)"
            },
            "scene": 0,
            "scenes": [
                {
                    "nodes": list(range(len(nodes)))
                }
            ],
            "nodes": nodes,
            "meshes": meshes,
            "accessors": accessors,
            "bufferViews": buffer_views,
            "buffers": [
                {
                    "byteLength": len(buffer_data),
                    "uri": "terrain.bin"
                }
            ]
        }
        
        # Add textures and materials
        images = []
        textures = []
        materials = []
        
        # Add terrain texture
        if texture is not None:
            print("Adding terrain texture to GLTF...")
            base64_texture = self.texture_to_base64_png(texture)
            
            images.append({
                "uri": f"data:image/png;base64,{base64_texture}",
                "name": "TerrainTexture"
            })
            
            textures.append({
                "source": 0
            })
            
            materials.append({
                "name": "TerrainMaterial",
                "pbrMetallicRoughness": {
                    "baseColorTexture": {
                        "index": 0
                    },
                    "metallicFactor": 0.0,
                    "roughnessFactor": 1.0
                }
            })
            
            # Add terrain material to mesh
            gltf["meshes"][0]["primitives"][0]["material"] = 0
        
        # Add water texture and material
        if water_texture is not None and water_mesh_data:
            print("Adding water texture to GLTF...")
            base64_water_texture = self.texture_to_base64_png(water_texture)
            
            images.append({
                "uri": f"data:image/png;base64,{base64_water_texture}",
                "name": "WaterTexture"
            })
            
            textures.append({
                "source": len(images) - 1
            })
            
            materials.append({
                "name": "WaterMaterial",
                "pbrMetallicRoughness": {
                    "baseColorTexture": {
                        "index": len(textures) - 1
                    },
                    "baseColorFactor": [0.118, 0.565, 1.0, 0.7],  # Blue with transparency
                    "metallicFactor": 0.8,
                    "roughnessFactor": 0.2
                },
                "alphaMode": "BLEND"
            })
        
        if images:
            gltf["images"] = images
            gltf["textures"] = textures
            gltf["materials"] = materials
        
        return gltf, buffer_data

    def create_water_texture(self):
        """Create a simple blue water texture"""
        if not PIL_AVAILABLE:
            print("PIL not available, skipping water texture")
            return None
        
        print("\nCreating water texture...")
        
        # Create a 64x64 blue texture
        size = 64
        water_color = (30, 144, 255)  # Dodger blue
        
        water_img = Image.new('RGB', (size, size), water_color)
        
        # Add some subtle variation for visual interest
        pixels = np.array(water_img)
        
        # Add subtle noise/variation
        noise = np.random.randint(-10, 10, (size, size, 3))
        pixels = np.clip(pixels + noise, 0, 255).astype(np.uint8)
        
        water_img = Image.fromarray(pixels)
        
        print(f"Water texture created: {size}x{size}")
        
        return np.array(water_img)

    def create_water_planes(self, sectors_x, sectors_y):
        """
        Create flat water planes for sectors with water data.
        Returns list of water plane meshes with their positions and heights.
        """
        water_planes = []
        
        print("\nProcessing water data from sectors...")
        
        for sector_num in self.sectors_data.keys():
            # Use the stored file path (handles FC2 remap where sector_num is local 0-based
            # but actual files use global IDs like sd64.sdat, sd1279.sdat).
            sector_file_paths = getattr(self, '_sector_file_paths', {})
            if sector_num in sector_file_paths:
                csdat_file = sector_file_paths[sector_num]
            else:
                pattern = str(self.sdat_path / f"sd{sector_num}{self._file_ext}")
                sector_files = glob.glob(pattern)
                if not sector_files:
                    continue
                csdat_file = sector_files[0]
            water_height = self.extract_water_height(csdat_file)
            
            if water_height != 0.0:
                # Calculate sector position in grid
                # Use Bottom-Left Sequential layout (same as heightmap)
                sector_row = sector_num // sectors_x
                sector_col = sector_num % sectors_x
                
                # Display row (flipped for rendering)
                display_row = sectors_y - 1 - sector_row
                
                # Calculate world position of sector's bottom-left corner (step-based)
                step = self.grid_size - 1
                world_x = sector_col * step * self.meters_per_coordinate
                world_y = display_row * step * self.meters_per_coordinate

                water_planes.append({
                    'sector_num': sector_num,
                    'height': water_height,
                    'world_x': world_x,
                    'world_y': world_y,
                    'size': step * self.meters_per_coordinate
                })
                
                print(f"  Water in sector {sector_num}: height={water_height:.2f}m at ({world_x:.1f}, {world_y:.1f})")
        
        print(f"Found {len(water_planes)} sectors with water")
        return water_planes

    def extract_water_height(self, csdat_file):
        """Extract water height from CSDAT file at offset 0xB0"""
        try:
            with open(csdat_file, 'rb') as f:
                f.seek(0xB0)  # Water height offset
                water_bytes = f.read(4)
                if len(water_bytes) == 4:
                    water_height = struct.unpack('<f', water_bytes)[0]
                    return water_height
        except Exception as e:
            print(f"  Error reading water height from {csdat_file}: {e}")
        
        return 0.0

    def create_water_mesh_data(self, water_planes, sectors_x, sectors_y):
        """Create mesh data for all water planes"""
        if not water_planes:
            return None
        
        all_vertices = []
        all_uvs = []
        all_indices = []
        
        # Calculate sector 0 offset (same as terrain, step-based)
        step = self.grid_size - 1
        sector_0_display_row = sectors_y - 1
        sector_0_col = 0
        sector_0_world_x = sector_0_col * step * self.meters_per_coordinate
        sector_0_world_z = sectors_y * step * self.meters_per_coordinate
        
        current_vertex_offset = 0
        
        for plane in water_planes:
            # Create a flat quad for this water plane
            size = plane['size']
            height = plane['height']
            
            # Offset by sector 0's position (matching terrain)
            x = plane['world_x'] - sector_0_world_x
            z = plane['world_y'] - sector_0_world_z
            
            # Create quad vertices (flat plane at water height)
            vertices = [
                x, height, z,              # Bottom-left
                x + size, height, z,       # Bottom-right
                x + size, height, z + size,# Top-right
                x, height, z + size        # Top-left
            ]
            
            # UVs for the quad
            uvs = [
                0.0, 0.0,  # Bottom-left
                1.0, 0.0,  # Bottom-right
                1.0, 1.0,  # Top-right
                0.0, 1.0   # Top-left
            ]
            
            # Indices for two triangles - FLIPPED WINDING ORDER
            # Counter-clockwise winding so normals face UP
            indices = [
                current_vertex_offset + 0,
                current_vertex_offset + 2,  # Swapped with next line
                current_vertex_offset + 1,  # Swapped with previous line
                current_vertex_offset + 0,
                current_vertex_offset + 3,  # Swapped with next line
                current_vertex_offset + 2   # Swapped with previous line
            ]
            
            all_vertices.extend(vertices)
            all_uvs.extend(uvs)
            all_indices.extend(indices)
            
            current_vertex_offset += 4
        
        print(f"Created water mesh: {len(all_vertices) // 3} vertices, {len(all_indices) // 3} triangles")
        
        return {
            'vertices': all_vertices,
            'uvs': all_uvs,
            'indices': all_indices
        }

    def export(self):
        """Main export function"""
        print("\n=== Avatar Terrain to GLTF Exporter (FIXED) ===\n")
        
        # Load all sectors
        if not self.load_all_sectors():
            print("ERROR: No sectors loaded!")
            return False
        
        # Load all textures
        self.load_all_textures()
        
        # Calculate grid dimensions
        sectors_x, sectors_y = self.calculate_grid_dimensions()
        print(f"\nUsing grid layout: {sectors_x}x{sectors_y} sectors")
        print(f"Total terrain size: {sectors_x * (self.grid_size - 1) * self.meters_per_coordinate}m x {sectors_y * (self.grid_size - 1) * self.meters_per_coordinate}m")
        
        # Create combined heightmap
        print("\nCombining heightmaps...")
        combined_heightmap = self.create_combined_heightmap(sectors_x, sectors_y)
        
        # Create combined texture at FULL resolution (don't downsample)
        combined_texture = self.create_combined_texture(sectors_x, sectors_y)
        
        # NEW: Downsample texture if too large
        if combined_texture is not None and hasattr(self, 'max_texture_size'):
            texture_height, texture_width = combined_texture.shape[:2]
            max_dim = max(texture_width, texture_height)
            
            if max_dim > self.max_texture_size:
                print(f"Downsampling texture from {texture_width}x{texture_height} to max {self.max_texture_size}x{self.max_texture_size}")
                scale_factor = self.max_texture_size / max_dim
                new_width = int(texture_width * scale_factor)
                new_height = int(texture_height * scale_factor)
                
                img = Image.fromarray(combined_texture)
                img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                combined_texture = np.array(img_resized)
                print(f"Texture downsampled to {new_width}x{new_height}")
        
        # Downsample heightmap if needed
        heightmap, width, height = self.downsample_heightmap(combined_heightmap, self.resolution)
        
        # Keep texture at current resolution
        texture = combined_texture
        
        # Create water texture
        water_texture = self.create_water_texture()
        
        # Create GLTF
        gltf_data, buffer_data = self.create_gltf(
            heightmap, width, height, 
            texture, 
            sectors_x, sectors_y,
            water_texture=water_texture
        )
        
        # Create output directory if needed
        self.output_path.mkdir(parents=True, exist_ok=True)
        
        # Save GLTF file
        gltf_file = self.output_path / "terrain.gltf"
        bin_file = self.output_path / "terrain.bin"
        
        print(f"\nSaving files...")
        print(f"  GLTF: {gltf_file}")
        print(f"  BIN: {bin_file}")
        
        with open(gltf_file, 'w') as f:
            json.dump(gltf_data, f, indent=2)
        
        with open(bin_file, 'wb') as f:
            f.write(buffer_data)
        
        print(f"\n✓ Export complete!")
        print(f"  Mesh resolution: {width}x{height} vertices")
        print(f"  Real dimensions: {sectors_x * (self.grid_size - 1) * self.meters_per_coordinate}m x {sectors_y * (self.grid_size - 1) * self.meters_per_coordinate}m")
        print(f"  Scale: {self.meters_per_coordinate} meters per coordinate")
        print(f"  Triangles: {len(buffer_data) // 12 // 2}")
        print(f"  Texture: {'Yes' if texture is not None else 'No'}")
        print(f"  Water: {'Yes' if water_texture is not None else 'No'}")
        print(f"  Custom Normals: No (Blender will auto-smooth)")
        
        return True

def generate_terrain_for_level(level_sdat_path, output_dir=None, resolution=500000, scale=1.0, game_mode="avatar"):
    """
    Generate terrain GLTF for a specific level on-demand.

    Args:
        level_sdat_path: Path to the level's sdat folder
        output_dir: Optional output directory (defaults to temp dir)
        resolution: Triangle resolution
        scale: Meters per coordinate
        game_mode: "avatar" or "farcry2"

    Returns:
        Tuple of (gltf_path, bin_path) or (None, None) on failure
    """
    import tempfile

    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="terrain_")

    try:
        exporter = TerrainExporter(level_sdat_path, output_dir, resolution, scale, game_mode=game_mode)
        success = exporter.export()
        
        if success:
            gltf_path = os.path.join(output_dir, "terrain.gltf")
            bin_path = os.path.join(output_dir, "terrain.bin")
            
            if os.path.exists(gltf_path) and os.path.exists(bin_path):
                return gltf_path, bin_path
        
        return None, None
        
    except Exception as e:
        print(f"Error generating terrain: {e}")
        import traceback
        traceback.print_exc()
        return None, None

def parse_arguments():
    """Parse command line arguments"""
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    
    input_path = None
    output_path = None
    resolution = 25000
    meters_per_coordinate = 1.0
    
    for arg in sys.argv[1:]:
        if arg.startswith('i-'):
            input_path = arg[2:]
        elif arg.startswith('o-'):
            output_path = arg[2:]
        elif arg.startswith('r-'):
            try:
                resolution = int(arg[2:])
            except ValueError:
                print(f"ERROR: Invalid resolution value: {arg[2:]}")
                sys.exit(1)
        elif arg.startswith('s-'):
            try:
                meters_per_coordinate = float(arg[2:])
            except ValueError:
                print(f"ERROR: Invalid scale value: {arg[2:]}")
                sys.exit(1)
    
    if not input_path or not output_path:
        print("ERROR: Both input (i-) and output (o-) paths are required!")
        print(__doc__)
        sys.exit(1)
    
    return input_path, output_path, resolution, meters_per_coordinate


def main():
    """Main entry point"""
    try:
        input_path, output_path, resolution, meters_per_coordinate = parse_arguments()
        
        exporter = TerrainExporter(input_path, output_path, resolution, meters_per_coordinate)
        success = exporter.export()
        
        sys.exit(0 if success else 1)
    
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()