"""
Water Editor Dialog for Avatar: The Game Level Editor
PyQt6 implementation that integrates with the existing map editor
"""

import os
import struct
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSlider, QLineEdit, QComboBox, QFrame, QMessageBox, QGroupBox, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPainter, QColor, QPen, QBrush
from ui_style_utils import apply_checkbox_style


# Water configuration constants
WATER_FLAG_OFFSET = 0xA8   # 1 byte: 1=render water, 0=no water
WATER_HEIGHT_OFFSET = 0xB0
WATER_PATH_OFFSET = 0xB9
WATER_PATH_MAX_OFFSET = 0x1BF
FIX_BYTES = bytes.fromhex("C0E440FFFFFF")
FIX_OFFSET_START = 0x21

# Water material paths — (display_name, full_path_bytes)
WATER_MATERIALS = [
    ("Default",                     b"graphics\\_materials\\editor\\df_water_default_top.mlm"),
    ("Open Field",                  b"graphics\\_materials\\editor\\water_av_openfield.mlm"),
    ("Rainforest",                  b"graphics\\_materials\\editor\\water_av_rainforest.mlm"),
    ("Rainforest (no reflection)",  b"graphics\\_materials\\editor\\water_av_rainforest_prolemuris_noreflection.mlm"),
    ("Riverbank",                   b"graphics\\_materials\\editor\\water_av_riverbank.mlm"),
    ("Swamp",                       b"graphics\\_materials\\editor\\water_av_swamp.mlm"),
    ("Polluted",                    b"graphics\\_materials\\editor\\water_riverbank_polluted_top.mlm"),
    ("Polluted Mix",                b"graphics\\_materials\\editor\\water_riverbank_pollutedmix_top.mlm"),
]

WATER_PATHS_BYTES = [path for _, path in WATER_MATERIALS]
WATER_PATHS_STR   = [path.decode('ascii') for path in WATER_PATHS_BYTES]


class SectorGridWidget(QFrame):
    """Interactive 16x16 sector grid for selecting sectors"""
    
    sector_selected = pyqtSignal(int)  # Emits sector index when clicked
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 480)
        self.setMaximumSize(480, 480)
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Sunken)
        self.setLineWidth(2)
        
        self.sdat_folder = None
        self.current_sector = None
        self.selected_sectors = set()    # all Ctrl+clicked sectors
        self.water_sectors = set()       # flag=1: water is rendered
        self.water_data_sectors = set()  # flag=0 but has height/material data

    def set_sdat_folder(self, folder_path):
        """Set the SDAT folder and scan for water"""
        self.sdat_folder = folder_path
        self.scan_water_sectors()
        self.update()

    def scan_water_sectors(self):
        """Scan all sectors to find which have water (flag=1) or data-only (flag=0 + height)."""
        self.water_sectors.clear()
        self.water_data_sectors.clear()

        if not self.sdat_folder:
            return

        for sector_idx in range(256):
            file_path = os.path.join(self.sdat_folder, f'sd{sector_idx}.csdat')
            if not os.path.isfile(file_path):
                continue
            flag, has_data = self._read_water_state(file_path)
            if flag:
                self.water_sectors.add(sector_idx)
            elif has_data:
                self.water_data_sectors.add(sector_idx)

        print(f"Found {len(self.water_sectors)} active water sectors, "
              f"{len(self.water_data_sectors)} data-only sectors")

    def _read_water_state(self, file_path):
        """Return (flag: bool, has_data: bool) for a sector file."""
        try:
            with open(file_path, 'rb') as f:
                data = f.read()
            if len(data) <= WATER_FLAG_OFFSET:
                return False, False
            flag = data[WATER_FLAG_OFFSET] != 0
            height = struct.unpack_from('<f', data, WATER_HEIGHT_OFFSET)[0] if len(data) >= WATER_HEIGHT_OFFSET + 4 else 0.0
            has_path = len(data) > WATER_PATH_OFFSET and data[WATER_PATH_OFFSET] != 0
            return flag, (height != 0.0 or has_path)
        except Exception:
            return False, False

    def sector_has_water(self, file_path):
        """Check if a sector has visible water using the flag byte at 0xA8."""
        flag, _ = self._read_water_state(file_path)
        return flag
        
    def set_current_sector(self, sector_idx):
        """Set the currently selected sector"""
        self.current_sector = sector_idx
        self.update()
        
    def paintEvent(self, event):
        """Draw the 16x16 grid"""
        super().paintEvent(event)
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        cell_size = 30
        
        for y in range(16):
            for x in range(16):
                sector_index = y * 16 + x
                display_x = x * cell_size
                display_y = (15 - y) * cell_size  # Flip Y axis
                
                # Determine cell color
                if sector_index == self.current_sector:
                    fill_color = QColor(255, 107, 107)
                    border_color = QColor(255, 50, 50)
                elif sector_index in self.selected_sectors:
                    fill_color = QColor(220, 140, 0)
                    border_color = QColor(180, 110, 0)
                elif sector_index in self.water_sectors:
                    # flag=1: active water
                    fill_color = QColor(30, 136, 229)
                    border_color = QColor(20, 100, 200)
                elif sector_index in self.water_data_sectors:
                    # flag=0 but data present (configured but not rendering)
                    fill_color = QColor(40, 70, 110)
                    border_color = QColor(50, 80, 120)
                else:
                    fill_color = QColor(42, 42, 62)
                    border_color = QColor(64, 64, 80)

                # Draw cell
                painter.setPen(QPen(border_color, 1))
                painter.setBrush(QBrush(fill_color))
                painter.drawRect(display_x, display_y, cell_size, cell_size)

                # Draw sector number for non-empty cells
                show_num = (sector_index == self.current_sector
                            or sector_index in self.selected_sectors
                            or sector_index in self.water_sectors
                            or sector_index in self.water_data_sectors)
                if show_num:
                    painter.setPen(QPen(QColor(255, 255, 255), 1))
                    font = QFont("Arial", 7)
                    painter.setFont(font)
                    painter.drawText(display_x + 2, display_y + 10, str(sector_index))
                    
    def mousePressEvent(self, event):
        """Handle mouse clicks on the grid"""
        if not self.sdat_folder:
            return
            
        cell_size = 30
        col = event.pos().x() // cell_size
        row = event.pos().y() // cell_size
        row = 15 - row  # Flip Y axis
        
        if 0 <= col <= 15 and 0 <= row <= 15:
            sector_index = row * 16 + col

            # Check if file exists
            file_path = os.path.join(self.sdat_folder, f'sd{sector_index}.csdat')
            if os.path.isfile(file_path):
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    # Ctrl+click: toggle in multi-selection without changing primary sector
                    if sector_index in self.selected_sectors:
                        self.selected_sectors.discard(sector_index)
                    else:
                        self.selected_sectors.add(sector_index)
                else:
                    # Regular click: single-select and load into UI
                    self.selected_sectors = {sector_index}
                    self.current_sector = sector_index
                    self.sector_selected.emit(sector_index)
                self.update()


class WaterEditorDialog(QDialog):
    """Water Editor Dialog for the level editor"""
    
    def __init__(self, parent=None, terrain_renderer=None, canvas=None):
        super().__init__(parent)
        
        self.terrain_renderer = terrain_renderer
        self.canvas = canvas  # For live 3D preview updates
        self.sdat_folder = None
        self.current_sector = None
        
        self.setWindowTitle("🌊 Water Editor - Avatar: The Game")
        self.setMinimumSize(900, 650)
        
        self.setup_ui()
        
        # If terrain renderer is provided, load from it
        if terrain_renderer and terrain_renderer.sdat_path:
            self.load_sdat_folder(terrain_renderer.sdat_path)
            
    def setup_ui(self):
        """Create the user interface"""
        layout = QVBoxLayout()
        
        # Header
        header = QLabel("🌊 Water Editor")
        header.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)
        
        # Main content area
        content_layout = QHBoxLayout()
        
        # Left panel - Controls
        left_panel = self.create_controls_panel()
        content_layout.addWidget(left_panel)
        
        # Right panel - Grid
        right_panel = self.create_grid_panel()
        content_layout.addWidget(right_panel)
        
        layout.addLayout(content_layout)
        
        # Status bar at bottom
        self.status_label = QLabel("No folder loaded")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        
        self.setLayout(layout)
        
    def create_controls_panel(self):
        """Create the left control panel"""
        panel = QGroupBox("Water Controls")
        layout = QVBoxLayout()

        # Load folder button
        self.load_btn = QPushButton("Load SDAT Folder")
        self.load_btn.clicked.connect(self.browse_sdat_folder)
        layout.addWidget(self.load_btn)

        layout.addSpacing(10)

        # Enable water button (replaces old "Add Water Block")
        self.add_water_btn = QPushButton("Enable Water on Sector")
        self.add_water_btn.clicked.connect(self.add_water_block)
        self.add_water_btn.setEnabled(False)
        self.add_water_btn.setToolTip("Write default water data to this sector, then adjust settings and save.")
        layout.addWidget(self.add_water_btn)

        layout.addSpacing(12)

        # Water visible flag checkbox
        self.water_visible_chk = QCheckBox("Water Rendered (flag active)")
        self.water_visible_chk.setEnabled(False)
        self.water_visible_chk.setToolTip(
            "Controls byte 0xA8 in the sector file.\n"
            "Uncheck to store water settings without rendering them."
        )
        apply_checkbox_style(self.water_visible_chk)
        layout.addWidget(self.water_visible_chk)

        layout.addSpacing(16)

        # Water height control
        height_label = QLabel("Water Height")
        height_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        layout.addWidget(height_label)

        # Slider  (0–2000 maps to 0.0–200.0 world units)
        self.height_slider = QSlider(Qt.Orientation.Horizontal)
        self.height_slider.setMinimum(0)
        self.height_slider.setMaximum(2000)
        self.height_slider.setValue(0)
        self.height_slider.valueChanged.connect(self.on_height_slider_changed)
        layout.addWidget(self.height_slider)

        # Text entry + step buttons
        entry_layout = QHBoxLayout()

        self.height_down_btn = QPushButton("▼")
        self.height_down_btn.setMaximumWidth(40)
        self.height_down_btn.setToolTip("Decrease by 1.0")
        self.height_down_btn.clicked.connect(self.decrease_height)
        entry_layout.addWidget(self.height_down_btn)

        self.height_entry = QLineEdit("0.00")
        self.height_entry.setMaximumWidth(100)
        self.height_entry.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.height_entry.textChanged.connect(self.on_height_entry_changed)
        entry_layout.addWidget(self.height_entry)

        self.height_up_btn = QPushButton("▲")
        self.height_up_btn.setMaximumWidth(40)
        self.height_up_btn.setToolTip("Increase by 1.0")
        self.height_up_btn.clicked.connect(self.increase_height)
        entry_layout.addWidget(self.height_up_btn)

        layout.addLayout(entry_layout)

        layout.addSpacing(16)

        # Water material dropdown — short display names, full path as tooltip
        material_label = QLabel("Water Material")
        material_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        layout.addWidget(material_label)

        self.path_dropdown = QComboBox()
        self.path_dropdown.addItem("(None)", userData=None)
        for display_name, path_bytes in WATER_MATERIALS:
            self.path_dropdown.addItem(display_name, userData=path_bytes)
            self.path_dropdown.setItemData(
                self.path_dropdown.count() - 1,
                path_bytes.decode('ascii'),
                Qt.ItemDataRole.ToolTipRole
            )
        layout.addWidget(self.path_dropdown)

        layout.addSpacing(20)

        # Save / Reset buttons
        self.save_btn = QPushButton("Save Sector")
        self.save_btn.clicked.connect(self.save_current_sector)
        self.save_btn.setEnabled(False)
        layout.addWidget(self.save_btn)

        self.apply_btn = QPushButton("Apply to Selected Sectors")
        self.apply_btn.clicked.connect(self.apply_to_selected)
        self.apply_btn.setEnabled(False)
        self.apply_btn.setToolTip("Apply current settings to all Ctrl+clicked sectors")
        layout.addWidget(self.apply_btn)

        self.reset_btn = QPushButton("Reset Sector (Clear Water)")
        self.reset_btn.clicked.connect(self.reset_current_sector)
        self.reset_btn.setEnabled(False)
        layout.addWidget(self.reset_btn)

        layout.addSpacing(20)

        # Sector info display
        self.sector_info = QLabel("Select a sector to edit")
        self.sector_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sector_info.setWordWrap(True)
        layout.addWidget(self.sector_info)

        layout.addStretch()

        panel.setLayout(layout)
        return panel
        
    def create_grid_panel(self):
        """Create the right grid panel"""
        panel = QGroupBox("Sector Map (16x16)")
        layout = QVBoxLayout()
        
        # Sector grid
        self.sector_grid = SectorGridWidget()
        self.sector_grid.sector_selected.connect(self.on_sector_selected)
        layout.addWidget(self.sector_grid)
        
        # Legend
        legend_layout = QHBoxLayout()
        legend_layout.addStretch()
        
        # Empty
        legend_layout.addWidget(self.create_legend_item(QColor(42, 42, 62), "Empty"))
        legend_layout.addSpacing(12)

        # Data only (flag=0, but height/material present)
        legend_layout.addWidget(self.create_legend_item(QColor(40, 70, 110), "Data Only"))
        legend_layout.addSpacing(12)

        # Water active (flag=1)
        legend_layout.addWidget(self.create_legend_item(QColor(30, 136, 229), "Water Active"))
        legend_layout.addSpacing(12)

        # Primary selected
        legend_layout.addWidget(self.create_legend_item(QColor(255, 107, 107), "Selected"))
        legend_layout.addSpacing(12)

        # Multi-selected
        legend_layout.addWidget(self.create_legend_item(QColor(220, 140, 0), "Multi-Selected"))
        
        legend_layout.addStretch()
        layout.addLayout(legend_layout)
        
        panel.setLayout(layout)
        return panel
        
    def create_legend_item(self, color, text):
        """Create a legend item"""
        widget = QFrame()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Color box
        color_box = QFrame()
        color_box.setFixedSize(20, 20)
        color_box.setStyleSheet(f"background-color: rgb({color.red()}, {color.green()}, {color.blue()}); border: 1px solid #888;")
        layout.addWidget(color_box)
        
        # Label
        label = QLabel(text)
        layout.addWidget(label)
        
        widget.setLayout(layout)
        return widget
        
    def browse_sdat_folder(self):
        """Browse for SDAT folder"""
        from PyQt6.QtWidgets import QFileDialog
        
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select SDAT Folder",
            "",
            QFileDialog.Option.ShowDirsOnly
        )
        
        if folder:
            self.load_sdat_folder(folder)
            
    def load_sdat_folder(self, folder_path):
        """Load SDAT folder"""
        if not os.path.isdir(folder_path):
            QMessageBox.warning(self, "Invalid Folder", f"Invalid folder path: {folder_path}")
            return
            
        # Check for .csdat files
        csdat_files = [f for f in os.listdir(folder_path) if f.endswith('.csdat')]
        if not csdat_files:
            QMessageBox.warning(self, "No CSDAT Files", f"No .csdat files found in {folder_path}")
            return
            
        self.sdat_folder = folder_path
        self.sector_grid.set_sdat_folder(folder_path)
        
        self.status_label.setText(f"Loaded: {folder_path} ({len(csdat_files)} sectors)")
        self.add_water_btn.setEnabled(True)
        self.apply_btn.setEnabled(True)
        
        print(f"Water Editor: Loaded {len(csdat_files)} sectors from {folder_path}")
        
    def on_sector_selected(self, sector_idx):
        """Handle sector selection from grid"""
        self.current_sector = sector_idx
        self.load_sector_into_ui(sector_idx)
        
    def load_sector_into_ui(self, sector_idx):
        """Load sector data into UI controls"""
        file_path = os.path.join(self.sdat_folder, f'sd{sector_idx}.csdat')

        if not os.path.isfile(file_path):
            self.current_sector = None
            self.update_sector_info()
            return

        try:
            with open(file_path, 'rb') as f:
                data = f.read()

            # Read water flag (byte 0xA8)
            flag = data[WATER_FLAG_OFFSET] != 0 if len(data) > WATER_FLAG_OFFSET else False

            # Read water height
            if len(data) >= WATER_HEIGHT_OFFSET + 4:
                height = struct.unpack_from('<f', data, WATER_HEIGHT_OFFSET)[0]
            else:
                height = 0.0

            # Read water path — extract null-terminated bytes then match against userData
            found_path_bytes = None
            if len(data) > WATER_PATH_OFFSET:
                raw = data[WATER_PATH_OFFSET:]
                null_idx = raw.find(b'\x00')
                if null_idx > 0:
                    found_path_bytes = bytes(raw[:null_idx])

            # Update flag checkbox
            self.water_visible_chk.blockSignals(True)
            self.water_visible_chk.setChecked(flag)
            self.water_visible_chk.blockSignals(False)
            self.water_visible_chk.setEnabled(True)

            # Update slider (clamp to max 2000)
            slider_val = min(int(height * 10), 2000)
            self.height_slider.blockSignals(True)
            self.height_slider.setValue(slider_val)
            self.height_slider.blockSignals(False)
            self.height_entry.setText(f"{height:.2f}")

            # Match material by userData (path bytes), not string index
            matched_idx = 0
            if found_path_bytes:
                for i in range(1, self.path_dropdown.count()):
                    item_data = self.path_dropdown.itemData(i)
                    if item_data == found_path_bytes:
                        matched_idx = i
                        break
            self.path_dropdown.setCurrentIndex(matched_idx)

            self.save_btn.setEnabled(True)
            self.reset_btn.setEnabled(True)
            self.update_sector_info()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load sector {sector_idx}: {e}")
            
    def on_height_slider_changed(self, value):
        """Handle slider changes - UPDATE 3D PREVIEW IN REAL TIME"""
        height = value / 10.0
        self.height_entry.setText(f"{height:.1f}")
        self._update_live_water_height(height)

    def on_height_entry_changed(self):
        """Handle manual height entry - UPDATE 3D PREVIEW IN REAL TIME"""
        try:
            height = float(self.height_entry.text())
            height = max(0.0, min(200.0, height))
            self.height_slider.blockSignals(True)
            self.height_slider.setValue(int(height * 10))
            self.height_slider.blockSignals(False)
            self._update_live_water_height(height)
        except ValueError:
            pass

    def _update_live_water_height(self, height):
        """Update water_data height in memory for instant 3D preview (no file write)."""
        if self.current_sector is None or not self.canvas:
            return
        # Update terrain_renderer water_data so WaterPlaneRenderer picks it up immediately
        if self.terrain_renderer:
            wd = self.terrain_renderer.water_data.get(self.current_sector)
            if wd is not None:
                wd.water_height = height
                wd.has_water = True
            else:
                # Sector not yet in water_data — create a minimal entry for preview
                from canvas.terrain_renderer import WaterData
                wd = WaterData(self.current_sector)
                wd.water_height = height
                wd.has_water = True
                self.terrain_renderer.water_data[self.current_sector] = wd
        if hasattr(self.canvas, 'update'):
            self.canvas.update()

    def increase_height(self):
        """Increase water height by 1.0"""
        try:
            current = float(self.height_entry.text())
            new_value = round(current + 1.0, 1)
            if new_value <= 200.0:
                self.height_entry.setText(f"{new_value:.2f}")
                self.auto_save_current_sector()
        except ValueError:
            pass

    def decrease_height(self):
        """Decrease water height by 1.0"""
        try:
            current = float(self.height_entry.text())
            new_value = round(current - 1.0, 1)
            if new_value >= 0.0:
                self.height_entry.setText(f"{new_value:.2f}")
                self.auto_save_current_sector()
        except ValueError:
            pass

    def update_live_preview(self):
        """Update 3D water plane preview in real-time"""
        if not self.canvas or self.current_sector is None:
            return
        
        try:
            # Get current height from UI
            height = float(self.height_entry.text())
            
            # Update the water data in terrain renderer
            if self.terrain_renderer and self.current_sector in self.terrain_renderer.water_data:
                water_data = self.terrain_renderer.water_data[self.current_sector]
                water_data.water_height = height
                
                # Force update the water plane renderer if it exists
                if hasattr(self.canvas, 'water_plane_renderer'):
                    self.canvas.water_plane_renderer.force_update_sector(
                        self.current_sector,
                        self.terrain_renderer
                    )
                
                # Trigger canvas redraw
                if hasattr(self.canvas, 'update'):
                    self.canvas.update()
                    
        except (ValueError, AttributeError):
            pass  # Silently ignore errors during live preview
            
    def add_water_block(self):
        """Add water block to selected sector"""
        if self.current_sector is None or self.sdat_folder is None:
            QMessageBox.warning(self, "No Sector", "Select a sector first.")
            return
            
        target_path = os.path.join(self.sdat_folder, f'sd{self.current_sector}.csdat')
        if not os.path.isfile(target_path):
            QMessageBox.critical(self, "Missing File", f'File not found: sd{self.current_sector}.csdat')
            return
            
        try:
            with open(target_path, 'rb') as f:
                target_data = bytearray(f.read())

            # Write only the water-specific bytes — leave all other sector header bytes
            # untouched so we don't corrupt level-specific terrain metadata.
            #
            # Water structure confirmed by binary analysis:
            #   0xA8:        flag byte  (1 = render water)
            #   0xA9–0xAF:  7 zero bytes (padding)
            #   0xB0–0xB3:  float32 height  (default 1.0)
            #   0xB4–0xB8:  5 zero bytes (padding)
            #   0xB9..null: material path string

            min_size = WATER_PATH_MAX_OFFSET + 1
            if len(target_data) < min_size:
                target_data.extend(b'\x00' * (min_size - len(target_data)))

            target_data[WATER_FLAG_OFFSET] = 0x01
            target_data[WATER_HEIGHT_OFFSET:WATER_HEIGHT_OFFSET+4] = struct.pack('<f', 1.0)
            default_path = WATER_PATHS_BYTES[4]  # water_av_riverbank.mlm
            max_len = WATER_PATH_MAX_OFFSET - WATER_PATH_OFFSET + 1
            path_bytes = default_path + b'\x00' + b'\x00' * (max_len - len(default_path) - 1)
            target_data[WATER_PATH_OFFSET:WATER_PATH_MAX_OFFSET+1] = path_bytes

            # Write back
            with open(target_path, 'wb') as f:
                f.write(target_data)
                f.flush()
                os.fsync(f.fileno())

            # Reload UI and grid
            self.load_sector_into_ui(self.current_sector)
            self.sector_grid.scan_water_sectors()
            self.sector_grid.update()

            QMessageBox.information(self, "Success", f"Water block added to sector {self.current_sector}!\nNow adjust settings and click Save.")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to add water block: {e}")
            
    def save_current_sector(self):
        """Save current sector water data"""
        if self.current_sector is None or self.sdat_folder is None:
            QMessageBox.warning(self, "No Sector", "Select a sector first.")
            return
            
        target_path = os.path.join(self.sdat_folder, f'sd{self.current_sector}.csdat')
        if not os.path.isfile(target_path):
            QMessageBox.critical(self, "Missing File", f'File not found: sd{self.current_sector}.csdat')
            return
            
        try:
            with open(target_path, 'rb') as f:
                target_data = bytearray(f.read())
                
            # Write water flag — honour the checkbox
            if len(target_data) <= WATER_FLAG_OFFSET:
                target_data.extend(b'\x00' * (WATER_FLAG_OFFSET + 1 - len(target_data)))
            target_data[WATER_FLAG_OFFSET] = 0x01 if self.water_visible_chk.isChecked() else 0x00

            # Write water height
            if len(target_data) < WATER_HEIGHT_OFFSET + 4:
                target_data.extend(b'\x00' * ((WATER_HEIGHT_OFFSET + 4) - len(target_data)))
            height = float(self.height_entry.text())
            target_data[WATER_HEIGHT_OFFSET:WATER_HEIGHT_OFFSET+4] = struct.pack('<f', height)

            # Write water path — use userData bytes from dropdown
            max_len = WATER_PATH_MAX_OFFSET - WATER_PATH_OFFSET + 1
            path_idx = self.path_dropdown.currentIndex()
            encoded = self.path_dropdown.itemData(path_idx) if path_idx > 0 else None

            if not encoded:
                path_bytes = b'\x00' * max_len
            else:
                if len(encoded) >= max_len:
                    path_bytes = encoded[:max_len-1] + b'\x00'
                else:
                    path_bytes = encoded + b'\x00' + b'\x00' * (max_len - len(encoded) - 1)

            if len(target_data) < WATER_PATH_MAX_OFFSET + 1:
                target_data.extend(b'\x00' * ((WATER_PATH_MAX_OFFSET + 1) - len(target_data)))
            target_data[WATER_PATH_OFFSET:WATER_PATH_MAX_OFFSET+1] = path_bytes

            # Write FIX_BYTES
            fix_end = FIX_OFFSET_START + len(FIX_BYTES)
            if len(target_data) < fix_end:
                target_data.extend(b'\x00' * (fix_end - len(target_data)))
            target_data[FIX_OFFSET_START:fix_end] = FIX_BYTES

            # Write back
            with open(target_path, 'wb') as f:
                f.write(target_data)
                f.flush()
                os.fsync(f.fileno())

            # Update grid
            self.sector_grid.scan_water_sectors()
            self.sector_grid.update()
            self.update_sector_info()

            # If terrain renderer exists, reload water data and store it
            if self.terrain_renderer:
                wd = self.terrain_renderer.parse_water_from_sector(target_path, self.current_sector)
                self.terrain_renderer.water_data[self.current_sector] = wd

            # Refresh 3D view so water plane appears/updates immediately
            if self.canvas and hasattr(self.canvas, 'update'):
                self.canvas.update()

            QMessageBox.information(self, "Saved", f"Sector {self.current_sector} saved successfully!")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {e}")
    
    def auto_save_current_sector(self):
        """Auto-save current sector water data (silent, no message boxes)"""
        if self.current_sector is None or self.sdat_folder is None:
            return
            
        target_path = os.path.join(self.sdat_folder, f'sd{self.current_sector}.csdat')
        if not os.path.isfile(target_path):
            return
            
        try:
            with open(target_path, 'rb') as f:
                target_data = bytearray(f.read())

            # Write water flag — honour the checkbox
            if len(target_data) <= WATER_FLAG_OFFSET:
                target_data.extend(b'\x00' * (WATER_FLAG_OFFSET + 1 - len(target_data)))
            target_data[WATER_FLAG_OFFSET] = 0x01 if self.water_visible_chk.isChecked() else 0x00

            # Write water height
            if len(target_data) < WATER_HEIGHT_OFFSET + 4:
                target_data.extend(b'\x00' * ((WATER_HEIGHT_OFFSET + 4) - len(target_data)))
            height = float(self.height_entry.text())
            target_data[WATER_HEIGHT_OFFSET:WATER_HEIGHT_OFFSET+4] = struct.pack('<f', height)

            # Write water path — use userData bytes from dropdown
            max_len = WATER_PATH_MAX_OFFSET - WATER_PATH_OFFSET + 1
            path_idx = self.path_dropdown.currentIndex()
            encoded = self.path_dropdown.itemData(path_idx) if path_idx > 0 else None

            if not encoded:
                path_bytes = b'\x00' * max_len
            else:
                if len(encoded) >= max_len:
                    path_bytes = encoded[:max_len-1] + b'\x00'
                else:
                    path_bytes = encoded + b'\x00' + b'\x00' * (max_len - len(encoded) - 1)

            if len(target_data) < WATER_PATH_MAX_OFFSET + 1:
                target_data.extend(b'\x00' * ((WATER_PATH_MAX_OFFSET + 1) - len(target_data)))
            target_data[WATER_PATH_OFFSET:WATER_PATH_MAX_OFFSET+1] = path_bytes

            # Write FIX_BYTES
            fix_end = FIX_OFFSET_START + len(FIX_BYTES)
            if len(target_data) < fix_end:
                target_data.extend(b'\x00' * (fix_end - len(target_data)))
            target_data[FIX_OFFSET_START:fix_end] = FIX_BYTES

            # Write back
            with open(target_path, 'wb') as f:
                f.write(target_data)
                f.flush()
                os.fsync(f.fileno())

            # Update grid silently
            self.sector_grid.scan_water_sectors()
            self.sector_grid.update()

        except Exception:
            pass  # Silent failure for auto-save

    def reload_current_sector_in_editor(self):
        """Reload the current sector in the 3D editor without reloading the whole level"""
        if self.current_sector is None or self.sdat_folder is None:
            return
            
        target_path = os.path.join(self.sdat_folder, f'sd{self.current_sector}.csdat')
        if not os.path.isfile(target_path):
            return
            
        try:
            # Reload water data in terrain renderer and store it
            if self.terrain_renderer:
                wd = self.terrain_renderer.parse_water_from_sector(target_path, self.current_sector)
                self.terrain_renderer.water_data[self.current_sector] = wd

                # Get the new water height
                water_data = self.terrain_renderer.water_data.get(self.current_sector)
                if water_data and hasattr(water_data, 'water_height'):
                    new_height = water_data.water_height
                else:
                    new_height = 0.0
                
                # Update the water mesh in 3D view
                if self.canvas and hasattr(self.canvas, 'water_mesh_editor'):
                    self.canvas.water_mesh_editor.update_sector_water_height(
                        self.current_sector,
                        new_height,
                        self.terrain_renderer
                    )
                    
                    # Trigger canvas redraw
                    if hasattr(self.canvas, 'update'):
                        self.canvas.update()
                        
        except Exception as e:
            print(f"Error reloading sector: {e}")

    def reset_current_sector(self):
        """Reset (clear) water from current sector"""
        if self.current_sector is None or self.sdat_folder is None:
            QMessageBox.warning(self, "No Sector", "Select a sector first.")
            return
            
        reply = QMessageBox.question(
            self,
            "Confirm Reset",
            f"Are you sure you want to clear water from sector {self.current_sector}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
            
        target_path = os.path.join(self.sdat_folder, f'sd{self.current_sector}.csdat')
        if not os.path.isfile(target_path):
            QMessageBox.critical(self, "Missing File", f'File not found: sd{self.current_sector}.csdat')
            return
            
        try:
            with open(target_path, 'rb') as f:
                data = bytearray(f.read())

            # Clear water flag (0 = no water)
            if len(data) <= WATER_FLAG_OFFSET:
                data.extend(b'\x00' * (WATER_FLAG_OFFSET + 1 - len(data)))
            data[WATER_FLAG_OFFSET] = 0x00

            # Reset height
            if len(data) < WATER_HEIGHT_OFFSET + 4:
                data.extend(b'\x00' * ((WATER_HEIGHT_OFFSET + 4) - len(data)))
            data[WATER_HEIGHT_OFFSET:WATER_HEIGHT_OFFSET+4] = struct.pack('<f', 0.0)

            # Reset path region
            max_len = WATER_PATH_MAX_OFFSET - WATER_PATH_OFFSET + 1
            if len(data) < WATER_PATH_MAX_OFFSET + 1:
                data.extend(b'\x00' * ((WATER_PATH_MAX_OFFSET + 1) - len(data)))
            data[WATER_PATH_OFFSET:WATER_PATH_MAX_OFFSET+1] = b'\x00' * max_len

            # Write fix bytes
            fix_end = FIX_OFFSET_START + len(FIX_BYTES)
            if len(data) < fix_end:
                data.extend(b'\x00' * (fix_end - len(data)))
            data[FIX_OFFSET_START:fix_end] = FIX_BYTES

            # Write back
            with open(target_path, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())

            # Reload UI and grid
            self.load_sector_into_ui(self.current_sector)
            self.sector_grid.scan_water_sectors()
            self.sector_grid.update()

            # If terrain renderer exists, reload water data and store it
            if self.terrain_renderer:
                wd = self.terrain_renderer.parse_water_from_sector(target_path, self.current_sector)
                self.terrain_renderer.water_data[self.current_sector] = wd

            QMessageBox.information(self, "Reset", f"Sector {self.current_sector} water cleared successfully!")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to reset: {e}")
            
    def _write_water_settings_to_file(self, file_path):
        """Write current UI water settings (flag, height, material) to a sector file."""
        with open(file_path, 'rb') as f:
            data = bytearray(f.read())

        min_size = WATER_PATH_MAX_OFFSET + 1
        if len(data) < min_size:
            data.extend(b'\x00' * (min_size - len(data)))

        data[WATER_FLAG_OFFSET] = 0x01 if self.water_visible_chk.isChecked() else 0x00
        height = float(self.height_entry.text())
        data[WATER_HEIGHT_OFFSET:WATER_HEIGHT_OFFSET+4] = struct.pack('<f', height)

        max_len = WATER_PATH_MAX_OFFSET - WATER_PATH_OFFSET + 1
        path_idx = self.path_dropdown.currentIndex()
        encoded = self.path_dropdown.itemData(path_idx) if path_idx > 0 else None
        if not encoded:
            path_bytes = b'\x00' * max_len
        else:
            path_bytes = encoded[:max_len-1] + b'\x00' if len(encoded) >= max_len else encoded + b'\x00' + b'\x00' * (max_len - len(encoded) - 1)
        data[WATER_PATH_OFFSET:WATER_PATH_MAX_OFFSET+1] = path_bytes

        fix_end = FIX_OFFSET_START + len(FIX_BYTES)
        if len(data) < fix_end:
            data.extend(b'\x00' * (fix_end - len(data)))
        data[FIX_OFFSET_START:fix_end] = FIX_BYTES

        with open(file_path, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

    def apply_to_selected(self):
        """Apply current water settings to all selected sectors."""
        selected = self.sector_grid.selected_sectors
        if not selected or self.sdat_folder is None:
            QMessageBox.warning(self, "No Selection", "Ctrl+click sectors on the grid to select them first.")
            return

        failed = []
        for sector_idx in sorted(selected):
            file_path = os.path.join(self.sdat_folder, f'sd{sector_idx}.csdat')
            if not os.path.isfile(file_path):
                failed.append(sector_idx)
                continue
            try:
                self._write_water_settings_to_file(file_path)
                if self.terrain_renderer:
                    wd = self.terrain_renderer.parse_water_from_sector(file_path, sector_idx)
                    self.terrain_renderer.water_data[sector_idx] = wd
            except Exception:
                failed.append(sector_idx)

        self.sector_grid.scan_water_sectors()
        self.sector_grid.update()
        if self.canvas and hasattr(self.canvas, 'update'):
            self.canvas.update()

        n = len(selected)
        if failed:
            QMessageBox.warning(self, "Partial Apply", f"Applied to {n - len(failed)}/{n} sectors.\nFailed: {failed}")
        else:
            QMessageBox.information(self, "Applied", f"Water settings applied to {n} sector(s).")

    def update_sector_info(self):
        """Update the sector info label"""
        if self.current_sector is None:
            self.sector_info.setText("Select a sector to edit\nCtrl+click to multi-select")
        else:
            has_water = self.current_sector in self.sector_grid.water_sectors
            status = "💧 Has water" if has_water else "⚪ No water"
            n = len(self.sector_grid.selected_sectors)
            multi = f"\n{n} sectors selected" if n > 1 else ""
            self.sector_info.setText(f"Sector {self.current_sector}\n{status}{multi}")


# Convenience function for opening the dialog
def show_water_editor(parent=None, terrain_renderer=None, canvas=None):
    """
    Show the water editor dialog
    
    Args:
        parent: Parent widget
        terrain_renderer: TerrainRenderer instance (optional)
        canvas: MapCanvas instance for live 3D preview (optional)
    """
    dialog = WaterEditorDialog(parent, terrain_renderer, canvas)
    dialog.exec()
    
    return dialog