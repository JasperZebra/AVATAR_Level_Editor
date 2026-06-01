"""
Terrain Renderer for MapCanvas - FIXED VERSION
Matches the working Water test.py implementation exactly.

Key fixes:
1. Heightmap: Simple bottom-left sequential (0,1,2...left-to-right, bottom-to-top)
2. Textures: 2x2 blocks with 1↔2 swap, top-left origin, vertical stacking  
3. Final 90° CCW rotation applied to complete texture assembly
"""

import numpy as np
from PyQt6.QtGui import QPainter, QImage, QPixmap, QTransform
from PyQt6.QtCore import Qt
import io
import os
import glob
import struct
import tempfile
from PIL import Image
from io import BytesIO


class WaterData:
    """Container for water info per sector"""
    def __init__(self, sector_num):
        self.sector_num = sector_num
        self.has_water = False
        self.water_flag = 0       # byte at 0xA8 — game's authoritative render flag
        self.water_height = 0.0
        self.material_path = None
        self.hex_offset_height = None
        self.hex_offset_material = None
        self.file_path = None
        self.file_name = None


class TerrainRenderer:
    """Handles terrain rendering in 2D canvas"""

    def __init__(self, game_mode: str = "avatar"):
        self.game_mode = game_mode
        self.grid_size = 65
        self.sectors_data = {}
        self.combined_heightmap = None
        self.terrain_image = None
        self.terrain_pixmap = None
        self.sdat_path = None
        self.show_terrain = True
        self.terrain_opacity = 1.0
        self.sectors_x = 16
        self.sectors_y = 16
        self.terrain_offset_x = 0
        self.terrain_offset_y = 0
        self.terrain_scale = 10
        self.terrain_world_min_x = 0
        self.terrain_world_min_y = 0
        self.terrain_world_max_x = 0
        self.terrain_world_max_y = 0
        # True world extent = sectors * (grid_size-1) = 16*64 = 1024
        # Set explicitly so rendering never derives it from pixmap.width()-1
        self.terrain_world_w = 0
        self.terrain_world_h = 0
        self.current_directory = None
        self.texture_layer = None
        self.atlas_mapping = {}
        self.sector_to_path = {}

        # Water data storage
        self.water_data = {}  # sector_num -> WaterData

        # Multi-cell terrain support (FC2 5×5 grid)
        # Each entry: (QPixmap, world_x, world_y, world_w, world_h)
        self.terrain_pixmap_cells = []

        # FC2 remap info — set by load_sdat_folder when global sector IDs are remapped to local.
        self._fc2_sector_base = 0
        self._fc2_row_stride = 80
        self._fc2_secs_per_row = 16

        # Per-game terrain offsets
        # Avatar: .csdat, terrain at 708, water height at 0xB0
        # FC2:    .sdat,  terrain at 592, water above-ground flag at 52, water height at 60
        if game_mode == "farcry2":
            self._file_ext = ".sdat"
            self._terrain_offset = 592
            self._water_flag_offset = 52       # 1 byte: 0 = no water above ground
            self._water_height_offset = 60     # 4-byte float
        else:
            self._file_ext = ".csdat"
            self._terrain_offset = 708
            self._water_flag_offset = None     # Avatar uses a different detection scheme
            self._water_height_offset = 0xB0  # 4-byte float

    # ----------------------------
    # SDAT Loading
    # ----------------------------
    def load_sdat_folder(self, sdat_path: str) -> bool:
        """Load all sector files from the sdat folder and generate textured terrain.
        Supports both Avatar (.csdat) and Far Cry 2 (.sdat) formats."""
        if not os.path.isdir(sdat_path):
            print(f"Invalid sdat path: {sdat_path}")
            return False

        self.sdat_path = sdat_path
        self.current_directory = sdat_path
        self.sectors_data = {}
        self.water_data = {}
        self.atlas_mapping = {}   # must rebuild per folder so each cell uses its own textures
        self.sector_to_path = {}
        self.terrain_pixmap = None   # clear so stale image from previous cell can't leak
        self.terrain_image = None

        # Set default texture layer if not set
        if not self.texture_layer:
            class Dummy:
                def get(self_inner):
                    return "diffuse"
            self.texture_layer = Dummy()

        # Load sector files for the current game (*.csdat or *.sdat)
        files = glob.glob(os.path.join(sdat_path, f"*{self._file_ext}"))
        if not files:
            print(f"No {self._file_ext} files found in {sdat_path}")
            return False

        print(f"Loading {self.game_mode} terrain data from {len(files)} {self._file_ext} files...")
        
        water_count = 0
        for file_path in files:
            filename = os.path.basename(file_path)
            try:
                # Parse sector number
                name = filename.rsplit('.', 1)[0]
                if name.startswith('sd'):
                    sector_num = int(name[2:])
                elif '_' in name:
                    sector_num = int(name.split('_')[-1])
                else:
                    sector_num = int(name)

                height_data = self._load_single_sector(file_path)
                if height_data is not None:
                    self.sectors_data[sector_num] = height_data
                    
                    # Parse water data from this sector
                    water = self.parse_water_from_sector(file_path, sector_num)
                    self.water_data[sector_num] = water
                    if water.has_water:
                        water_count += 1

            except (ValueError, IndexError) as e:
                print(f"Could not parse sector number from {filename}: {e}")

        num_sectors = len(self.sectors_data)
        print(f"Loaded {num_sectors} terrain sectors")
        
        if water_count > 0:
            print(f"Found {water_count} sectors with water")

        if num_sectors > 0:
            # FC2: sector files use global world-level indices (e.g. 2592-3807 for cell w1_c_3).
            # Remap them to local 0-based indices so grid_size comes out correct (16x16 not 62x62).
            if self.game_mode == "farcry2":
                sorted_nums = sorted(self.sectors_data.keys())
                min_s = sorted_nums[0]
                if min_s > 0:
                    # Find row stride: first gap > 1 in consecutive sector numbers.
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
                        remapped_s, remapped_w = {}, {}
                        for sn in sorted_nums:
                            diff = sn - min_s
                            local_idx = (diff // row_stride) * secs_per_row + (diff % row_stride)
                            if sn in self.sectors_data:
                                remapped_s[local_idx] = self.sectors_data[sn]
                            if sn in self.water_data:
                                remapped_w[local_idx] = self.water_data[sn]
                        self.sectors_data = remapped_s
                        self.water_data = remapped_w
                        self._fc2_sector_base = min_s
                        self._fc2_row_stride = row_stride
                        self._fc2_secs_per_row = secs_per_row
                        print(f"[Terrain] FC2 remap: {len(remapped_s)} sectors, "
                              f"global[{min_s}..{sorted_nums[-1]}] → local[0..{max(remapped_s)}], "
                              f"row_stride={row_stride}, secs_per_row={secs_per_row}")
            else:
                # Avatar multi-part: sectors may start above 0 (e.g. l2 has sd256-sd511).
                # Remap to 0-based so grid_size is correct and the image renders as a full 16x16 tile.
                sorted_nums = sorted(self.sectors_data.keys())
                min_s = sorted_nums[0]
                if min_s > 0:
                    remapped_s, remapped_w = {}, {}
                    for sn in sorted_nums:
                        local_idx = sn - min_s
                        remapped_s[local_idx] = self.sectors_data[sn]
                        if sn in self.water_data:
                            remapped_w[local_idx] = self.water_data[sn]
                    self.sectors_data = remapped_s
                    self.water_data = remapped_w
                    print(f"[Terrain] Avatar remap: global[{min_s}..{sorted_nums[-1]}] "
                          f"→ local[0..{max(remapped_s)}]")

            max_sector = max(self.sectors_data.keys())
            grid_size = int(np.ceil(np.sqrt(max_sector + 1)))
            self.sectors_x = grid_size
            self.sectors_y = grid_size
            print(f"Detected terrain grid: {self.sectors_x}x{self.sectors_y}")

            # Generate terrain image
            self._generate_terrain_image()

            print(f"✓ Terrain loaded from {sdat_path}")
            return True

        return False

    def merge_sdat_folder(self, sdat_path: str) -> bool:
        """Merge additional Avatar sdat sectors into existing terrain data (for multi-part levels).
        Does not reset sectors_data — new sector numbers are added alongside existing ones."""
        if not os.path.isdir(sdat_path):
            print(f"Invalid sdat path: {sdat_path}")
            return False

        if not self.sectors_data:
            return self.load_sdat_folder(sdat_path)

        files = glob.glob(os.path.join(sdat_path, f"*{self._file_ext}"))
        if not files:
            print(f"No {self._file_ext} files found in {sdat_path}")
            return False

        print(f"Merging {len(files)} {self._file_ext} files from {os.path.basename(sdat_path)}...")
        added = 0
        for file_path in files:
            filename = os.path.basename(file_path)
            try:
                name = filename.rsplit('.', 1)[0]
                if name.startswith('sd'):
                    sector_num = int(name[2:])
                elif '_' in name:
                    sector_num = int(name.split('_')[-1])
                else:
                    sector_num = int(name)

                if sector_num not in self.sectors_data:
                    height_data = self._load_single_sector(file_path)
                    if height_data is not None:
                        self.sectors_data[sector_num] = height_data
                        water = self.parse_water_from_sector(file_path, sector_num)
                        self.water_data[sector_num] = water
                        added += 1
            except (ValueError, IndexError) as e:
                print(f"Could not parse sector number from {filename}: {e}")

        if added == 0:
            print(f"No new sectors added from {os.path.basename(sdat_path)}")
            return False

        print(f"Merged {added} new sectors; total now {len(self.sectors_data)}")
        max_sector = max(self.sectors_data.keys())
        # Preserve the row width (sectors_x) established by the original load —
        # the new sectors are additional rows, not extra columns.
        if self.sectors_x > 0:
            self.sectors_y = int(np.ceil((max_sector + 1) / self.sectors_x))
        else:
            sq = int(np.ceil(np.sqrt(max_sector + 1)))
            self.sectors_x = sq
            self.sectors_y = sq
        step = self.grid_size - 1
        self.terrain_world_w = float(self.sectors_x * step)
        self.terrain_world_h = float(self.sectors_y * step)
        print(f"Updated terrain grid: {self.sectors_x}x{self.sectors_y} "
              f"({self.terrain_world_w}x{self.terrain_world_h} world units)")
        self._generate_terrain_image()
        return True

    def load_sdat_cell(self, sdat_path: str, world_x: float, world_y: float) -> bool:
        """Load one terrain cell and store its pixmap with world offset (for FC2 multi-cell)."""
        if not self.load_sdat_folder(sdat_path):
            return False
        if self.terrain_pixmap is None:
            return False
        step = self.grid_size - 1
        world_w = float(self.sectors_x * step) if self.terrain_world_w == 0 else self.terrain_world_w
        world_h = float(self.sectors_y * step) if self.terrain_world_h == 0 else self.terrain_world_h
        self.terrain_pixmap_cells.append(
            (self.terrain_pixmap, float(world_x), float(world_y), world_w, world_h)
        )
        return True

    def _load_single_sector(self, file_path: str):
        try:
            with open(file_path, 'rb') as f:
                f.seek(self._terrain_offset)
                terrain_data = io.BytesIO(f.read(16900))

            height_array = np.zeros((self.grid_size, self.grid_size), dtype=np.float32)
            for y in range(self.grid_size):
                for x in range(self.grid_size):
                    data = terrain_data.read(2)
                    if len(data) < 2:
                        break
                    height = int.from_bytes(data, 'little') / 128
                    height_array[y, x] = height
                    terrain_data.read(2)
            return height_array

        except Exception as e:
            print(f"Error loading {file_path}: {e}")
            return None

    # ----------------------------
    # Water Parsing
    # ----------------------------
    def parse_water_from_sector(self, file_path, sector_num):
        """Parse water data from a sector file (.csdat or .sdat)"""
        water = WaterData(sector_num)
        water.file_path = file_path
        water.file_name = os.path.basename(file_path)

        try:
            with open(file_path, 'rb') as f:
                data = f.read()

            height_offset = self._water_height_offset

            if len(data) < height_offset + 4:
                return water

            height_bytes = data[height_offset:height_offset + 4]

            try:
                water.water_height = struct.unpack('<f', height_bytes)[0]
                water.hex_offset_height = height_offset

                # FC2: water only exists above ground if flag byte at offset 52 is non-zero
                # Avatar: flag byte at 0xA8 is the authoritative "render water" indicator;
                #         height can be non-zero even for sectors without visible water.
                if self.game_mode == "farcry2":
                    if self._water_flag_offset is not None and len(data) > self._water_flag_offset:
                        flag = data[self._water_flag_offset]
                        water.water_flag = flag
                        water.has_water = (flag != 0 and water.water_height != 0.0)
                    else:
                        water.has_water = False
                else:
                    if len(data) > 0xA8:
                        water.water_flag = data[0xA8]
                        water.has_water = (water.water_flag != 0)

                    water_patterns = [
                        b'graphics\\_materials\\editor\\water_',
                        b'graphics_materials\\editor\\water_'
                    ]
                    
                    graphics_pos = -1
                    for pattern in water_patterns:
                        pos = data.find(pattern)
                        if pos != -1:
                            graphics_pos = pos
                            break
                    
                    if graphics_pos != -1:
                        material_start = graphics_pos
                        material_end = data.find(b'\x00', material_start)
                        if material_end != -1:
                            water.material_path = data[material_start:material_end].decode('latin-1', errors='ignore')
                            water.hex_offset_material = material_start
                        else:
                            water.material_path = data[material_start:material_start+100].decode('latin-1', errors='ignore')
                            water.hex_offset_material = material_start
                    
                    if water.has_water:
                        print(f"Water found in sector {sector_num}:")
                        if water.material_path:
                            print(f"  Material path: {water.material_path}")
                            if water.hex_offset_material is not None:
                                print(f"  Material at offset: 0x{water.hex_offset_material:08X}")
                        print(f"  Water height: {water.water_height:.2f}")
                        if water.hex_offset_height is not None:
                            print(f"  Height at offset: 0x{water.hex_offset_height:08X}")
                    
            except Exception as e:
                print(f"  Could not read water height: {e}")
                water.water_height = 0.0
                
        except Exception as e:
            print(f"Error parsing water from {file_path}: {e}")
        
        return water

    # ----------------------------
    # Sector Indexing - FIXED TO MATCH WORKING CODE
    # ----------------------------
    def get_sector_index_from_position(self, display_row, col, sectors_x, sectors_y):
        """
        Avatar Game Layout (2x2 blocks, vertical) - MATCHES WORKING IMPLEMENTATION
        
        This is the TEXTURE indexing pattern. Heightmaps use simple bottom-left sequential.
        
        Key points from working code:
        - 2x2 blocks stack vertically (8 blocks down = 32 sectors per column)
        - Within each block: swap positions 1↔2
        - Standard: TL=0, TR=1, BL=2, BR=3
        - Avatar:   TL=0, TR=2, BL=1, BR=3 (swap 1↔2)
        """
        # Calculate which 2x2 block this position belongs to
        block_col = col // 2
        block_row = display_row // 2
        
        # Position within the 2x2 block
        within_block_col = col % 2
        within_block_row = display_row % 2
        
        # Blocks stack vertically (going DOWN first, then across)
        blocks_per_column = sectors_y // 2  # 8 for 16x16 grid
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
        
        return base_sector + offset

    # ----------------------------
    # Height Sampling
    # ----------------------------
    def get_height_at_world(self, world_x: float, world_y: float,
                             offset_x: float = None, offset_y: float = None) -> float:
        """Return the terrain height (Z) at world position (world_x, world_y).

        offset_x/y: world coords of the terrain's bottom-left corner.
        Falls back to self.terrain_offset_x/y when not provided.
        Returns 0.0 when the position is outside the terrain or no heightmap is loaded.
        """
        if self.combined_heightmap is None:
            return 0.0

        ox = offset_x if offset_x is not None else self.terrain_offset_x
        oy = offset_y if offset_y is not None else self.terrain_offset_y

        h_px, w_px = self.combined_heightmap.shape
        world_w = float(w_px - 1)
        world_h = float(h_px - 1)

        if world_w <= 0 or world_h <= 0:
            return 0.0

        nx = (world_x - ox) / world_w   # 0 = left edge, 1 = right edge
        ny = (world_y - oy) / world_h   # 0 = bottom, 1 = top

        if nx < 0.0 or nx > 1.0 or ny < 0.0 or ny > 1.0:
            return 0.0

        # Row 0 of the heightmap image = top = maximum world Y
        px = nx * (w_px - 1)
        py = (1.0 - ny) * (h_px - 1)

        x0, y0 = int(px), int(py)
        x1 = min(x0 + 1, w_px - 1)
        y1 = min(y0 + 1, h_px - 1)
        fx = px - x0
        fy = py - y0

        h00 = float(self.combined_heightmap[y0, x0])
        h10 = float(self.combined_heightmap[y0, x1])
        h01 = float(self.combined_heightmap[y1, x0])
        h11 = float(self.combined_heightmap[y1, x1])

        return h00 * (1 - fx) * (1 - fy) + h10 * fx * (1 - fy) \
             + h01 * (1 - fx) * fy       + h11 * fx * fy

    # ----------------------------
    # Terrain Image Generation - FIXED
    # ----------------------------
    def _generate_terrain_image(self):
        """Generate terrain image using XBT/atlas textures if available, else procedural"""
        if not self.sectors_data:
            return

        # Auto-detect and build atlas mapping if possible
        if (not self.atlas_mapping or len(self.atlas_mapping) == 0) and self.current_directory and self.texture_layer:
            self.build_atlas_mapping()
            if self.atlas_mapping:
                print(f"Detected atlas mapping with {len(self.atlas_mapping)} sectors")

        if self.atlas_mapping:
            self._generate_terrain_image_textured()
        else:
            self._generate_terrain_image_procedural()

    def _generate_terrain_image_procedural(self):
        """Generate procedural heightmap visualization - BOTTOM-LEFT SEQUENTIAL"""
        step = self.grid_size - 1   # 64 — sectors share edge pixels
        total_width  = self.sectors_x * step + 1   # 1025 for 16×16
        total_height = self.sectors_y * step + 1
        combined_map = np.zeros((total_height, total_width), dtype=np.float32)

        # HEIGHTMAP uses simple bottom-left sequential ordering
        # Sector 0 = bottom-left, proceeds right, then up
        for display_row in range(self.sectors_y):
            for col in range(self.sectors_x):
                # Bottom-left sequential
                sector_row = self.sectors_y - 1 - display_row  # 0 = bottom
                sector_index = sector_row * self.sectors_x + col

                if sector_index in self.sectors_data:
                    start_y = display_row * step
                    start_x = col * step

                    # Flip vertically for display (matches working code)
                    combined_map[start_y:start_y+self.grid_size, start_x:start_x+self.grid_size] = np.flipud(
                        self.sectors_data[sector_index]
                    )

        self.combined_heightmap = combined_map
        min_h, max_h = np.min(combined_map), np.max(combined_map)
        norm = (combined_map - min_h) / (max_h - min_h) if max_h > min_h else np.zeros_like(combined_map)

        # Colorize heightmap
        rgb_image = np.zeros((total_height, total_width, 3), dtype=np.uint8)
        water_mask = norm < 0.2
        low_mask = (norm >= 0.2) & (norm < 0.4)
        mid_mask = (norm >= 0.4) & (norm < 0.7)
        high_mask = norm >= 0.7

        rgb_image[water_mask] = np.stack([
            (norm[water_mask] * 50).astype(np.uint8),
            (norm[water_mask] * 100 + 50).astype(np.uint8),
            (norm[water_mask] * 155 + 100).astype(np.uint8)
        ], axis=-1)
        rgb_image[low_mask] = np.stack([
            (norm[low_mask] * 50).astype(np.uint8),
            (norm[low_mask] * 180 + 50).astype(np.uint8),
            (norm[low_mask] * 50).astype(np.uint8)
        ], axis=-1)
        rgb_image[mid_mask] = np.stack([
            (norm[mid_mask] * 160 + 80).astype(np.uint8),
            (norm[mid_mask] * 120 + 60).astype(np.uint8),
            (norm[mid_mask] * 60).astype(np.uint8)
        ], axis=-1)
        rgb_image[high_mask] = np.stack([
            (norm[high_mask] * 200 + 55).astype(np.uint8),
            (norm[high_mask] * 200 + 55).astype(np.uint8),
            (norm[high_mask] * 200 + 55).astype(np.uint8)
        ], axis=-1)

        self.terrain_image = QImage(
            rgb_image.data,
            total_width,
            total_height,
            total_width * 3,
            QImage.Format.Format_RGB888
        )
        self.terrain_pixmap = QPixmap.fromImage(self.terrain_image)
        step = self.grid_size - 1
        self.terrain_world_w = float(self.sectors_x * step)
        self.terrain_world_h = float(self.sectors_y * step)
        print(f"Generated procedural terrain image: {total_width}x{total_height}")

    def _generate_terrain_image_textured(self):
        """Generate terrain using atlas/DDS textures - MATCHES WORKING CODE"""
        if not self.sectors_data:
            return

        total_width = self.sectors_x * self.grid_size
        total_height = self.sectors_y * self.grid_size
        combined_image = QImage(total_width, total_height, QImage.Format.Format_RGB888)
        combined_image.fill(Qt.GlobalColor.black)

        if not self.atlas_mapping:
            self.build_atlas_mapping()

        painter = QPainter(combined_image)

        for display_row in range(self.sectors_y):
            for col in range(self.sectors_x):
                sector_index = self.get_sector_index_from_position(display_row, col,
                                                                   self.sectors_x, self.sectors_y)

                if sector_index not in self.sectors_data:
                    continue

                sector_texture = None

                # Load texture from atlas mapping
                if self.atlas_mapping and sector_index in self.atlas_mapping:
                    atlas_path, sub_sector = self.atlas_mapping[sector_index]
                    try:
                        img = Image.open(atlas_path).convert("RGB")
                        img_array = np.array(img)
                        h, w = img_array.shape[:2]
                        half_h, half_w = h // 2, w // 2

                        # Extract correct quadrant (STANDARD 2x2 layout from atlas file)
                        # The swap happens in get_sector_index_from_position, not here
                        if sub_sector == 0:  # Top-left
                            sub_img = img_array[0:half_h, 0:half_w]
                        elif sub_sector == 1:  # Top-right
                            sub_img = img_array[0:half_h, half_w:w]
                        elif sub_sector == 2:  # Bottom-left
                            sub_img = img_array[half_h:h, 0:half_w]
                        else:  # Bottom-right (3)
                            sub_img = img_array[half_h:h, half_w:w]

                        pil_img = Image.fromarray(sub_img)
                        pil_img = pil_img.resize((self.grid_size, self.grid_size), 
                                                Image.Resampling.LANCZOS)
                        sector_texture = self.pil_image_to_qimage(pil_img)
                    except Exception as e:
                        print(f"Error loading atlas {atlas_path}: {e}")
                        sector_texture = None

                # Procedural fallback
                if sector_texture is None:
                    heights = np.flipud(self.sectors_data[sector_index])
                    norm = (heights - heights.min()) / (heights.max() - heights.min() + 1e-5)
                    rgb_array = np.stack([norm * 255] * 3, axis=-1).astype(np.uint8)
                    sector_texture = QImage(rgb_array.data, self.grid_size, self.grid_size, 
                                           self.grid_size * 3, QImage.Format.Format_RGB888)

                start_x = col * self.grid_size
                start_y = display_row * self.grid_size
                painter.drawImage(start_x, start_y, sector_texture)

        painter.end()

        # Apply 90° CCW rotation — same for Avatar and FC2.
        transform = QTransform()
        transform.rotate(-90)
        final_image = combined_image.transformed(transform)

        # FC2 needs one additional 90° CCW rotation on the whole finished terrain.
        if self.game_mode == "farcry2":
            transform2 = QTransform()
            transform2.rotate(-90)
            final_image = final_image.transformed(transform2)

        self.terrain_image = final_image
        self.terrain_pixmap = QPixmap.fromImage(final_image)
        self.combined_heightmap = None
        step = self.grid_size - 1
        self.terrain_world_w = float(self.sectors_x * step)
        self.terrain_world_h = float(self.sectors_y * step)
        print(f"[Terrain] Generated terrain: {final_image.width()}x{final_image.height()}")

    # ----------------------------
    # Atlas/XBT Mapping - STANDARD SEQUENTIAL
    # ----------------------------
    def build_atlas_mapping(self):
        """Build mapping from local sector index → (atlas_image_path, sub_sector).

        Avatar: sequential counter — atlas0 covers local sectors 0,1,2,3; atlas2 covers 4,5,6,7; etc.
        FC2:    each atlas covers a 2×2 block of local sectors determined by the atlas's
                global sector number.  atlas{N} sub_sectors: TL→(row,col), TR→(row,col+1),
                BL→(row+1,col), BR→(row+1,col+1) where row/col are the local sector positions.
        """
        if not self.current_directory:
            return

        self.atlas_mapping = {}
        temp_folder = os.path.join(tempfile.gettempdir(), "terrain_textures")
        os.makedirs(temp_folder, exist_ok=True)

        layer = self.texture_layer.get() if self.texture_layer else "diffuse"

        # Collect all atlas files — try every suffix variant so we work regardless of
        # whether the game uses _diffuse, _d, _color, or bare atlas numbering.
        atlas_files = []
        for ext in ['.xbt', '.dds', '.png', '.tga']:
            for suffix in [f'_{layer}', '_d', '_color']:
                atlas_files.extend(
                    glob.glob(os.path.join(self.current_directory, f"atlas*{suffix}{ext}"))
                )

        # De-duplicate
        atlas_files = list(dict.fromkeys(atlas_files))

        if not atlas_files:
            # Last resort: bare atlas* (no suffix).  Only use when nothing else matched
            # so we don't accidentally include normal/specular atlases alongside diffuse ones.
            for ext in ['.xbt', '.dds', '.png', '.tga']:
                atlas_files.extend(
                    glob.glob(os.path.join(self.current_directory, f"atlas*{ext}"))
                )
            atlas_files = list(dict.fromkeys(atlas_files))

        if not atlas_files:
            print(f"No atlas files found in {self.current_directory}")
            return

        # Extract atlas numbers and sort
        atlas_numbers = set()
        for filepath in atlas_files:
            filename = os.path.basename(filepath)
            try:
                # Strip extension, then strip everything after the first '_' (suffix)
                base = os.path.splitext(filename)[0]
                num_part = base.split('_')[0]  # "atlas123"
                num = int(num_part.replace('atlas', ''))
                atlas_numbers.add(num)
            except (ValueError, IndexError):
                continue

        atlas_numbers = sorted(list(atlas_numbers))
        print(f"Found {len(atlas_numbers)} atlas files: {atlas_numbers[:10]}...")

        def _load_atlas(atlas_num):
            """Return ready-to-use path for atlas_num, extracting XBT → DDS if needed."""
            for ext in ['.xbt', '.dds', '.png', '.tga']:
                for suffix in [f'_{layer}', '_d', '_color', '']:
                    test_path = os.path.join(
                        self.current_directory, f"atlas{atlas_num}{suffix}{ext}")
                    if os.path.exists(test_path):
                        if ext == '.xbt':
                            self.load_xbt_as_dds_tempfile(test_path, temp_folder=temp_folder)
                            return os.path.join(
                                temp_folder,
                                os.path.basename(test_path).replace('.xbt', '.dds'))
                        return test_path
            return None

        # Sequential counter — same layout for both Avatar and FC2.
        # Each atlas covers 4 consecutive sector indices: atlas[i] → sectors i*4 … i*4+3.
        sector_counter = 0
        for atlas_num in atlas_numbers:
            atlas_path = _load_atlas(atlas_num)
            if not atlas_path:
                continue
            for sub_sector in range(4):
                self.atlas_mapping[sector_counter] = (atlas_path, sub_sector)
                sector_counter += 1

        print(f"Mapped {len(self.atlas_mapping)} sectors to atlas textures")

    def load_xbt_as_dds_tempfile(self, xbt_path, temp_folder=None):
        """Extract DDS from XBT file"""
        try:
            with open(xbt_path, 'rb') as f:
                data = f.read()

            dds_offset = data.find(b'DDS ')
            if dds_offset < 0:
                print(f"DDS magic not found in {xbt_path}")
                return None

            dds_data = data[dds_offset:]

            if temp_folder is None:
                temp_folder = tempfile.gettempdir()
            os.makedirs(temp_folder, exist_ok=True)

            base_name = os.path.basename(xbt_path)
            temp_dds_path = os.path.join(temp_folder, base_name.replace('.xbt', '.dds'))

            with open(temp_dds_path, 'wb') as tmp_file:
                tmp_file.write(dds_data)

            img = Image.open(temp_dds_path)
            img.load()
            return img

        except Exception as e:
            print(f"Failed to load XBT {xbt_path}: {e}")
            return None

    # ----------------------------
    # Utilities
    # ----------------------------
    def pil_image_to_qimage(self, pil_img):
        if pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")
        return QImage(
            pil_img.tobytes(),
            pil_img.width,
            pil_img.height,
            3 * pil_img.width,
            QImage.Format.Format_RGB888
        )

    def render_terrain_2d(self, painter: QPainter, canvas):
        if not self.show_terrain:
            return
        try:
            painter.save()
            painter.setOpacity(self.terrain_opacity)

            if self.terrain_pixmap_cells:
                # Multi-cell mode (FC2 5×5 grid): each cell has its own pixmap + world offset.
                for pixmap, world_x, world_y, world_w, world_h in self.terrain_pixmap_cells:
                    screen_x_min, screen_y_max = canvas.world_to_screen(world_x, world_y)
                    screen_x_max, screen_y_min = canvas.world_to_screen(
                        world_x + world_w, world_y + world_h)
                    painter.drawPixmap(
                        int(screen_x_min), int(screen_y_min),
                        int(screen_x_max - screen_x_min), int(screen_y_max - screen_y_min),
                        pixmap
                    )
            elif self.terrain_pixmap is not None:
                # Single-cell mode (Avatar / single FC2 cell).
                step = self.grid_size - 1
                terrain_world_width  = self.terrain_world_w if self.terrain_world_w > 0 else float(self.sectors_x * step)
                terrain_world_height = self.terrain_world_h if self.terrain_world_h > 0 else float(self.sectors_y * step)
                ox = getattr(canvas, 'terrain_world_offset_x', getattr(self, 'terrain_offset_x', 0))
                oy = getattr(canvas, 'terrain_world_offset_y', getattr(self, 'terrain_offset_y', 0))
                screen_x_min, screen_y_max = canvas.world_to_screen(ox, oy)
                screen_x_max, screen_y_min = canvas.world_to_screen(
                    ox + terrain_world_width, oy + terrain_world_height)
                painter.drawPixmap(
                    int(screen_x_min), int(screen_y_min),
                    int(screen_x_max - screen_x_min), int(screen_y_max - screen_y_min),
                    self.terrain_pixmap
                )

            painter.restore()
        except Exception as e:
            print(f"Error rendering terrain: {e}")
            import traceback
            traceback.print_exc()

    def toggle_terrain(self):
        self.show_terrain = not self.show_terrain
        print(f"Terrain visibility: {self.show_terrain}")

    def set_opacity(self, opacity: float):
        self.terrain_opacity = max(0.0, min(1.0, opacity))
        print(f"Terrain opacity: {self.terrain_opacity}")

    def load_folder(self, folder_path, is_fc2=False):
        # is_fc2 kept for backward compat; game_mode set at construction time
        return self.load_sdat_folder(folder_path)

    def update_from_heightmap(self, combined_array: np.ndarray):
        """Regenerate terrain display from an externally-modified combined heightmap.
        Used by the terrain editor for live preview — does not re-read any files."""
        if combined_array is None:
            return
        self.combined_heightmap = combined_array
        total_height, total_width = combined_array.shape

        min_h = float(np.min(combined_array))
        max_h = float(np.max(combined_array))
        span  = max_h - min_h if max_h > min_h else 1.0
        norm  = ((combined_array - min_h) / span).astype(np.float32)

        rgb = np.zeros((total_height, total_width, 3), dtype=np.uint8)
        wm = norm < 0.2
        lm = (norm >= 0.2) & (norm < 0.4)
        mm = (norm >= 0.4) & (norm < 0.7)
        hm = norm >= 0.7

        rgb[wm, 0] = (norm[wm] * 50).astype(np.uint8)
        rgb[wm, 1] = (norm[wm] * 100 + 50).astype(np.uint8)
        rgb[wm, 2] = (norm[wm] * 155 + 100).astype(np.uint8)
        rgb[lm, 0] = (norm[lm] * 50).astype(np.uint8)
        rgb[lm, 1] = (norm[lm] * 180 + 50).astype(np.uint8)
        rgb[lm, 2] = (norm[lm] * 50).astype(np.uint8)
        rgb[mm, 0] = (norm[mm] * 160 + 80).astype(np.uint8)
        rgb[mm, 1] = (norm[mm] * 120 + 60).astype(np.uint8)
        rgb[mm, 2] = (norm[mm] * 60).astype(np.uint8)
        rgb[hm, 0] = (norm[hm] * 200 + 55).astype(np.uint8)
        rgb[hm, 1] = (norm[hm] * 200 + 55).astype(np.uint8)
        rgb[hm, 2] = (norm[hm] * 200 + 55).astype(np.uint8)

        from PyQt6.QtGui import QImage, QPixmap
        img = QImage(rgb.data, total_width, total_height,
                     total_width * 3, QImage.Format.Format_RGB888)
        self.terrain_pixmap = QPixmap.fromImage(img)

    def set_world_bounds(self, grid_config):
        if grid_config is None or self.combined_heightmap is None:
            return
        sector_size = grid_config.sector_granularity
        self.terrain_world_min_x = 0
        self.terrain_world_min_y = 0
        self.terrain_world_max_x = self.sectors_x * sector_size * self.grid_size
        self.terrain_world_max_y = self.sectors_y * sector_size * self.grid_size
        print(f"Terrain world bounds: ({self.terrain_world_min_x}, {self.terrain_world_min_y}) "
              f"to ({self.terrain_world_max_x}, {self.terrain_world_max_y})")