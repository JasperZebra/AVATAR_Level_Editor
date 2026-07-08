"""
Water Editor Dialog for the Avatar / Far Cry 2 Level Editor
PyQt5 implementation that integrates with the existing map editor.

Both games store per-sector water in the terrain sector file (Avatar .csdat,
FC2 .sdat), but at different offsets and with slightly different semantics:

  Avatar (.csdat)                     FC2 (.sdat)
  ---------------                     -----------
  0xA8  render flag (1 byte)          0x34 (52) still-water flag  (1 byte)
                                      0x38 (56) river-water flag  (1 byte)
  0xB0  water height (f32)            0x3C (60) water height (f32)
  0xB9  material path (null-term)     0x44 (68) material path (null-term)
  0x21  6 "fix" bytes                 (no fix-byte slot — real data there)

FC2 has two water render types (the engine exposes distinct Water / WaterRiver
passes — confirmed in the Dunia decompile). A sector renders water when EITHER
flag is set; open-world river cells set the river flag, sea/pond cells set the
still flag. The dialog exposes a Still/River selector in FC2 mode.

All Avatar offsets/behaviour are preserved exactly; the game-specific bits live
in WaterFormat so the two games share one code path.
"""

import os
import glob
import struct
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSlider, QLineEdit, QComboBox, QFrame, QMessageBox, QGroupBox, QCheckBox
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QPainter, QColor, QPen, QBrush
from ui_style_utils import apply_checkbox_style


# ── Per-game water material lists — (display_name, full_path_bytes) ──────────
AVATAR_WATER_MATERIALS = [
    ("Default",                     b"graphics\\_materials\\editor\\df_water_default_top.mlm"),
    ("Open Field",                  b"graphics\\_materials\\editor\\water_av_openfield.mlm"),
    ("Rainforest",                  b"graphics\\_materials\\editor\\water_av_rainforest.mlm"),
    ("Rainforest (no reflection)",  b"graphics\\_materials\\editor\\water_av_rainforest_prolemuris_noreflection.mlm"),
    ("Riverbank",                   b"graphics\\_materials\\editor\\water_av_riverbank.mlm"),
    ("Swamp",                       b"graphics\\_materials\\editor\\water_av_swamp.mlm"),
    ("Polluted",                    b"graphics\\_materials\\editor\\water_riverbank_polluted_top.mlm"),
    ("Polluted Mix",                b"graphics\\_materials\\editor\\water_riverbank_pollutedmix_top.mlm"),
]

# FC2 material paths seen across the retail worlds/MP maps (Fortune's Edition).
FC2_WATER_MATERIALS = [
    ("Default",                     b"graphics\\_materials\\editor\\water_default_top.mlm"),
    ("River (default)",             b"graphics\\_materials\\editor\\waterriver_default_top.mlm"),
    ("Moss (low)",                  b"graphics\\_materials\\editor\\Water_Moss_Low_Top.mlm"),
    ("Moss (low, fishing village)", b"graphics\\_materials\\editor\\water_moss_low_fishingvillage_top.mlm"),
    ("Moss (high)",                 b"graphics\\_materials\\editor\\water_moss_high_top.mlm"),
    ("Moss (very high)",            b"graphics\\_materials\\editor\\water_moss_veryhigh_top.mlm"),
    ("No reflection (dirty)",       b"graphics\\_materials\\editor\\water_noreflection_dirty_top.mlm"),
    ("Dust (low)",                  b"graphics\\_materials\\editor\\Water_Dust_Dust_Low.mlm"),
]


class WaterFormat:
    """Per-game byte layout + material list for the sector water block."""

    def __init__(self, game_mode="avatar"):
        self.game_mode = game_mode
        if game_mode == "farcry2":
            self.ext = ".sdat"
            self.flag_off = 52          # still-water flag
            self.river_flag_off = 56    # river-water flag
            self.height_off = 60
            self.mat_off = 68
            # Material region [68, 192): longest known path ends at 132; the next
            # real header data never resumes before 329, so this range is padding.
            self.mat_region_end = 192
            self.fix_bytes = None       # FC2 has no fix-byte slot (0x21 is real data)
            self.fix_off = None
            self.materials = FC2_WATER_MATERIALS
            self.has_river = True
            self.default_material = FC2_WATER_MATERIALS[0][1]
        else:
            self.ext = ".csdat"
            self.flag_off = 0xA8
            self.river_flag_off = None
            self.height_off = 0xB0
            self.mat_off = 0xB9
            self.mat_region_end = 0x1C0  # 0xB9..0x1BF inclusive
            self.fix_bytes = bytes.fromhex("C0E440FFFFFF")
            self.fix_off = 0x21
            self.materials = AVATAR_WATER_MATERIALS
            self.has_river = False
            self.default_material = AVATAR_WATER_MATERIALS[4][1]  # riverbank

    @property
    def mat_max_len(self):
        return self.mat_region_end - self.mat_off

    @property
    def min_size(self):
        """Smallest file length that can hold the whole water block."""
        return self.mat_region_end


def _sector_num_from_name(name):
    """Parse the sector number from a sector-file basename (no extension).
    Supports 'sd123' (both games), 'foo_123' (some FC2 worlds), and '123'."""
    if name.startswith('sd'):
        return int(name[2:])
    if '_' in name:
        return int(name.split('_')[-1])
    return int(name)


def scan_sector_files(folder, fmt):
    """Return {local_idx: path} for every sector file in `folder`.

    Mirrors TerrainEditor.load / TerrainRenderer: global or multi-part sector
    numbering is remapped to local 0-based indices so the grid is 16x16 and
    live-preview keys line up with terrain_renderer.water_data.
      FC2:    global world indices, row stride ~80 (e.g. w1_c_3 = 2592..3807).
      Avatar: multi-part levels start above 0 (e.g. sd256..sd511).
    """
    files = glob.glob(os.path.join(folder, f"*{fmt.ext}"))
    by_num = {}
    for fp in files:
        name = os.path.basename(fp).rsplit('.', 1)[0]
        try:
            by_num[_sector_num_from_name(name)] = fp
        except (ValueError, IndexError):
            continue
    if not by_num:
        return {}

    sorted_nums = sorted(by_num)
    min_s = sorted_nums[0]
    if min_s <= 0:
        return dict(by_num)

    if fmt.game_mode == "farcry2":
        secs_per_row = len(sorted_nums)
        row_stride = secs_per_row
        gap_found = False
        for i in range(1, len(sorted_nums)):
            if sorted_nums[i] - sorted_nums[i - 1] > 1:
                secs_per_row = i
                row_stride = sorted_nums[i] - sorted_nums[0]
                gap_found = True
                break
        if gap_found:
            def _local(sn):
                diff = sn - min_s
                return (diff // row_stride) * secs_per_row + (diff % row_stride)
        else:
            def _local(sn):
                return sn - min_s
    else:
        def _local(sn):
            return sn - min_s

    return {_local(sn): by_num[sn] for sn in sorted_nums}


class SectorGridWidget(QFrame):
    """Interactive sector grid for selecting sectors (up to 16x16)."""

    sector_selected = pyqtSignal(int)  # Emits local sector index when clicked

    def __init__(self, parent=None, fmt=None):
        super().__init__(parent)
        self.setMinimumSize(480, 480)
        self.setMaximumSize(480, 480)
        self.setFrameStyle(QFrame.Box | QFrame.Sunken)
        self.setLineWidth(2)

        self.fmt = fmt or WaterFormat("avatar")
        self.sdat_folder = None
        self.grid_dim = 16
        self.sector_files = {}           # local idx -> path
        self.current_sector = None
        self.selected_sectors = set()    # all Ctrl+clicked sectors
        self.water_sectors = set()       # flag set: water is rendered
        self.water_data_sectors = set()  # no flag but height/material present

    def set_format(self, fmt):
        self.fmt = fmt

    def set_sdat_folder(self, folder_path):
        """Set the sector folder and scan for water."""
        self.sdat_folder = folder_path
        self.sector_files = scan_sector_files(folder_path, self.fmt)
        if self.sector_files:
            import math
            self.grid_dim = max(16, int(math.ceil(math.sqrt(max(self.sector_files) + 1))))
        self.scan_water_sectors()
        self.update()

    def file_for(self, local_idx):
        return self.sector_files.get(local_idx)

    def scan_water_sectors(self):
        """Classify every sector as water-active, data-only, or empty."""
        self.water_sectors.clear()
        self.water_data_sectors.clear()
        for idx, path in self.sector_files.items():
            flag, has_data = self._read_water_state(path)
            if flag:
                self.water_sectors.add(idx)
            elif has_data:
                self.water_data_sectors.add(idx)
        print(f"Found {len(self.water_sectors)} active water sectors, "
              f"{len(self.water_data_sectors)} data-only sectors")

    def _read_water_state(self, file_path):
        """Return (flag: bool, has_data: bool) for a sector file."""
        f = self.fmt
        try:
            with open(file_path, 'rb') as fh:
                data = fh.read()
            flag = False
            if len(data) > f.flag_off and data[f.flag_off] != 0:
                flag = True
            if f.has_river and len(data) > f.river_flag_off and data[f.river_flag_off] != 0:
                flag = True
            height = (struct.unpack_from('<f', data, f.height_off)[0]
                      if len(data) >= f.height_off + 4 else 0.0)
            has_path = len(data) > f.mat_off and data[f.mat_off] != 0
            return flag, (height != 0.0 or has_path)
        except Exception:
            return False, False

    def set_current_sector(self, sector_idx):
        self.current_sector = sector_idx
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        dim = self.grid_dim
        cell_size = max(8, int(480 / dim))

        for y in range(dim):
            for x in range(dim):
                sector_index = y * dim + x
                display_x = x * cell_size
                display_y = (dim - 1 - y) * cell_size  # Flip Y axis

                if sector_index not in self.sector_files:
                    fill_color = QColor(28, 28, 40)
                    border_color = QColor(40, 40, 52)
                elif sector_index == self.current_sector:
                    fill_color = QColor(255, 107, 107)
                    border_color = QColor(255, 50, 50)
                elif sector_index in self.selected_sectors:
                    fill_color = QColor(220, 140, 0)
                    border_color = QColor(180, 110, 0)
                elif sector_index in self.water_sectors:
                    fill_color = QColor(30, 136, 229)
                    border_color = QColor(20, 100, 200)
                elif sector_index in self.water_data_sectors:
                    fill_color = QColor(40, 70, 110)
                    border_color = QColor(50, 80, 120)
                else:
                    fill_color = QColor(42, 42, 62)
                    border_color = QColor(64, 64, 80)

                painter.setPen(QPen(border_color, 1))
                painter.setBrush(QBrush(fill_color))
                painter.drawRect(display_x, display_y, cell_size, cell_size)

                show_num = cell_size >= 24 and (
                    sector_index == self.current_sector
                    or sector_index in self.selected_sectors
                    or sector_index in self.water_sectors
                    or sector_index in self.water_data_sectors)
                if show_num:
                    painter.setPen(QPen(QColor(255, 255, 255), 1))
                    painter.setFont(QFont("Arial", 7))
                    painter.drawText(display_x + 2, display_y + 10, str(sector_index))

    def mousePressEvent(self, event):
        if not self.sdat_folder:
            return
        dim = self.grid_dim
        cell_size = max(8, int(480 / dim))
        col = event.pos().x() // cell_size
        row = event.pos().y() // cell_size
        row = (dim - 1) - row  # Flip Y axis

        if 0 <= col < dim and 0 <= row < dim:
            sector_index = row * dim + col
            if sector_index not in self.sector_files:
                return
            if event.modifiers() & Qt.ControlModifier:
                if sector_index in self.selected_sectors:
                    self.selected_sectors.discard(sector_index)
                else:
                    self.selected_sectors.add(sector_index)
            else:
                self.selected_sectors = {sector_index}
                self.current_sector = sector_index
                self.sector_selected.emit(sector_index)
            self.update()


class WaterEditorDialog(QDialog):
    """Water Editor Dialog for the level editor (Avatar + FC2)."""

    def __init__(self, parent=None, terrain_renderer=None, canvas=None, game_mode="avatar"):
        super().__init__(parent)

        self.terrain_renderer = terrain_renderer
        self.canvas = canvas  # For live 3D preview updates
        self.game_mode = game_mode
        self.fmt = WaterFormat(game_mode)
        self.sdat_folder = None
        self.current_sector = None

        game_name = "Far Cry 2" if game_mode == "farcry2" else "Avatar: The Game"
        self.setWindowTitle(f"🌊 Water Editor - {game_name}")
        self.setMinimumSize(900, 650)

        self.setup_ui()

        if terrain_renderer and terrain_renderer.sdat_path:
            self.load_sdat_folder(terrain_renderer.sdat_path)

    # -- UI ------------------------------------------------------------------

    def setup_ui(self):
        layout = QVBoxLayout()

        header = QLabel("🌊 Water Editor")
        header.setFont(QFont("Arial", 16, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        content_layout = QHBoxLayout()
        content_layout.addWidget(self.create_controls_panel())
        content_layout.addWidget(self.create_grid_panel())
        layout.addLayout(content_layout)

        self.status_label = QLabel("No folder loaded")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        self.setLayout(layout)

    def create_controls_panel(self):
        panel = QGroupBox("Water Controls")
        layout = QVBoxLayout()

        self.load_btn = QPushButton("Load SDAT Folder")
        self.load_btn.clicked.connect(self.browse_sdat_folder)
        layout.addWidget(self.load_btn)

        layout.addSpacing(10)

        self.add_water_btn = QPushButton("Enable Water on Sector")
        self.add_water_btn.clicked.connect(self.add_water_block)
        self.add_water_btn.setEnabled(False)
        self.add_water_btn.setToolTip("Write default water data to this sector, then adjust settings and save.")
        layout.addWidget(self.add_water_btn)

        layout.addSpacing(12)

        flag_label = "Water Rendered (flag active)"
        self.water_visible_chk = QCheckBox(flag_label)
        self.water_visible_chk.setEnabled(False)
        tip = ("Controls the water render flag in the sector file.\n"
               "Uncheck to store water settings without rendering them.")
        self.water_visible_chk.setToolTip(tip)
        apply_checkbox_style(self.water_visible_chk)
        layout.addWidget(self.water_visible_chk)

        # FC2 only: still vs river water type selector
        self.type_label = QLabel("Water Type")
        self.type_label.setFont(QFont("Arial", 11, QFont.Bold))
        self.type_dropdown = QComboBox()
        self.type_dropdown.addItem("Still water", userData="still")
        self.type_dropdown.addItem("River water", userData="river")
        self.type_dropdown.setToolTip(
            "FC2 has two water render types. Still sets the flag at 0x34; "
            "River sets the flag at 0x38.")
        if self.fmt.has_river:
            layout.addSpacing(10)
            layout.addWidget(self.type_label)
            layout.addWidget(self.type_dropdown)
        else:
            self.type_label.hide()
            self.type_dropdown.hide()

        layout.addSpacing(16)

        height_label = QLabel("Water Height")
        height_label.setFont(QFont("Arial", 11, QFont.Bold))
        layout.addWidget(height_label)

        self.height_slider = QSlider(Qt.Horizontal)
        self.height_slider.setMinimum(0)
        self.height_slider.setMaximum(2000)
        self.height_slider.setValue(0)
        self.height_slider.valueChanged.connect(self.on_height_slider_changed)
        layout.addWidget(self.height_slider)

        entry_layout = QHBoxLayout()
        self.height_down_btn = QPushButton("▼")
        self.height_down_btn.setMaximumWidth(40)
        self.height_down_btn.setToolTip("Decrease by 1.0")
        self.height_down_btn.clicked.connect(self.decrease_height)
        entry_layout.addWidget(self.height_down_btn)

        self.height_entry = QLineEdit("0.00")
        self.height_entry.setMaximumWidth(100)
        self.height_entry.setAlignment(Qt.AlignCenter)
        self.height_entry.textChanged.connect(self.on_height_entry_changed)
        entry_layout.addWidget(self.height_entry)

        self.height_up_btn = QPushButton("▲")
        self.height_up_btn.setMaximumWidth(40)
        self.height_up_btn.setToolTip("Increase by 1.0")
        self.height_up_btn.clicked.connect(self.increase_height)
        entry_layout.addWidget(self.height_up_btn)
        layout.addLayout(entry_layout)

        layout.addSpacing(16)

        material_label = QLabel("Water Material")
        material_label.setFont(QFont("Arial", 11, QFont.Bold))
        layout.addWidget(material_label)

        self.path_dropdown = QComboBox()
        self.path_dropdown.addItem("(None)", userData=None)
        for display_name, path_bytes in self.fmt.materials:
            self.path_dropdown.addItem(display_name, userData=path_bytes)
            self.path_dropdown.setItemData(
                self.path_dropdown.count() - 1,
                path_bytes.decode('ascii'), Qt.ToolTipRole)
        layout.addWidget(self.path_dropdown)

        layout.addSpacing(20)

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

        self.sector_info = QLabel("Select a sector to edit")
        self.sector_info.setAlignment(Qt.AlignCenter)
        self.sector_info.setWordWrap(True)
        layout.addWidget(self.sector_info)

        layout.addStretch()
        panel.setLayout(layout)
        return panel

    def create_grid_panel(self):
        panel = QGroupBox("Sector Map")
        layout = QVBoxLayout()

        self.sector_grid = SectorGridWidget(fmt=self.fmt)
        self.sector_grid.sector_selected.connect(self.on_sector_selected)
        layout.addWidget(self.sector_grid)

        legend_layout = QHBoxLayout()
        legend_layout.addStretch()
        legend_layout.addWidget(self.create_legend_item(QColor(42, 42, 62), "Empty"))
        legend_layout.addSpacing(12)
        legend_layout.addWidget(self.create_legend_item(QColor(40, 70, 110), "Data Only"))
        legend_layout.addSpacing(12)
        legend_layout.addWidget(self.create_legend_item(QColor(30, 136, 229), "Water Active"))
        legend_layout.addSpacing(12)
        legend_layout.addWidget(self.create_legend_item(QColor(255, 107, 107), "Selected"))
        legend_layout.addSpacing(12)
        legend_layout.addWidget(self.create_legend_item(QColor(220, 140, 0), "Multi-Selected"))
        legend_layout.addStretch()
        layout.addLayout(legend_layout)

        panel.setLayout(layout)
        return panel

    def create_legend_item(self, color, text):
        widget = QFrame()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        color_box = QFrame()
        color_box.setFixedSize(20, 20)
        color_box.setStyleSheet(
            f"background-color: rgb({color.red()}, {color.green()}, {color.blue()}); "
            f"border: 1px solid #888;")
        layout.addWidget(color_box)
        layout.addWidget(QLabel(text))
        widget.setLayout(layout)
        return widget

    # -- Loading -------------------------------------------------------------

    def browse_sdat_folder(self):
        from PyQt5.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(
            self, "Select SDAT Folder", "", QFileDialog.ShowDirsOnly)
        if folder:
            self.load_sdat_folder(folder)

    def load_sdat_folder(self, folder_path):
        if not os.path.isdir(folder_path):
            QMessageBox.warning(self, "Invalid Folder", f"Invalid folder path: {folder_path}")
            return

        sector_files = [f for f in os.listdir(folder_path) if f.endswith(self.fmt.ext)]
        if not sector_files:
            QMessageBox.warning(
                self, "No Sector Files",
                f"No {self.fmt.ext} files found in {folder_path}")
            return

        self.sdat_folder = folder_path
        self.sector_grid.set_sdat_folder(folder_path)

        self.status_label.setText(f"Loaded: {folder_path} ({len(sector_files)} sectors)")
        self.add_water_btn.setEnabled(True)
        self.apply_btn.setEnabled(True)
        print(f"Water Editor: Loaded {len(sector_files)} sectors from {folder_path}")

    def on_sector_selected(self, sector_idx):
        self.current_sector = sector_idx
        self.load_sector_into_ui(sector_idx)

    def _file_for(self, sector_idx):
        return self.sector_grid.file_for(sector_idx)

    def load_sector_into_ui(self, sector_idx):
        file_path = self._file_for(sector_idx)
        if not file_path or not os.path.isfile(file_path):
            self.current_sector = None
            self.update_sector_info()
            return

        f = self.fmt
        try:
            with open(file_path, 'rb') as fh:
                data = fh.read()

            flag = len(data) > f.flag_off and data[f.flag_off] != 0
            river = f.has_river and len(data) > f.river_flag_off and data[f.river_flag_off] != 0
            visible = bool(flag or river)

            height = (struct.unpack_from('<f', data, f.height_off)[0]
                      if len(data) >= f.height_off + 4 else 0.0)

            found_path_bytes = None
            if len(data) > f.mat_off:
                raw = data[f.mat_off:f.mat_region_end]
                null_idx = raw.find(b'\x00')
                if null_idx > 0:
                    found_path_bytes = bytes(raw[:null_idx])

            self.water_visible_chk.blockSignals(True)
            self.water_visible_chk.setChecked(visible)
            self.water_visible_chk.blockSignals(False)
            self.water_visible_chk.setEnabled(True)

            if f.has_river:
                # River flag wins the type when set; else Still.
                self.type_dropdown.blockSignals(True)
                self.type_dropdown.setCurrentIndex(1 if river else 0)
                self.type_dropdown.blockSignals(False)

            slider_val = min(int(height * 10), 2000)
            self.height_slider.blockSignals(True)
            self.height_slider.setValue(slider_val)
            self.height_slider.blockSignals(False)
            self.height_entry.setText(f"{height:.2f}")

            matched_idx = 0
            if found_path_bytes:
                for i in range(1, self.path_dropdown.count()):
                    if self.path_dropdown.itemData(i) == found_path_bytes:
                        matched_idx = i
                        break
            self.path_dropdown.setCurrentIndex(matched_idx)

            self.save_btn.setEnabled(True)
            self.reset_btn.setEnabled(True)
            self.update_sector_info()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load sector {sector_idx}: {e}")

    # -- Height live preview -------------------------------------------------

    def on_height_slider_changed(self, value):
        height = value / 10.0
        self.height_entry.setText(f"{height:.1f}")
        self._update_live_water_height(height)

    def on_height_entry_changed(self):
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
        if self.current_sector is None or not self.canvas:
            return
        if self.terrain_renderer:
            wd = self.terrain_renderer.water_data.get(self.current_sector)
            if wd is not None:
                wd.water_height = height
                wd.has_water = True
            else:
                from canvas.terrain_renderer import WaterData
                wd = WaterData(self.current_sector)
                wd.water_height = height
                wd.has_water = True
                self.terrain_renderer.water_data[self.current_sector] = wd
        if hasattr(self.canvas, 'update'):
            self.canvas.update()

    def increase_height(self):
        try:
            current = float(self.height_entry.text())
            new_value = round(current + 1.0, 1)
            if new_value <= 200.0:
                self.height_entry.setText(f"{new_value:.2f}")
                self.auto_save_current_sector()
        except ValueError:
            pass

    def decrease_height(self):
        try:
            current = float(self.height_entry.text())
            new_value = round(current - 1.0, 1)
            if new_value >= 0.0:
                self.height_entry.setText(f"{new_value:.2f}")
                self.auto_save_current_sector()
        except ValueError:
            pass

    # -- Byte writing --------------------------------------------------------

    def _selected_material_bytes(self):
        idx = self.path_dropdown.currentIndex()
        return self.path_dropdown.itemData(idx) if idx > 0 else None

    def _write_water_block(self, data, visible, height, material_bytes):
        """Write the water block into `data` (bytearray) per the game format.

        Preserves every non-water header byte. FC2: sets the still/river flag
        matching the type dropdown and clears the other; Avatar: single flag.
        """
        f = self.fmt
        if len(data) < f.min_size:
            data.extend(b'\x00' * (f.min_size - len(data)))

        # Flags
        if f.has_river:
            want_river = (self.type_dropdown.currentData() == "river")
            data[f.flag_off] = 0x01 if (visible and not want_river) else 0x00
            data[f.river_flag_off] = 0x01 if (visible and want_river) else 0x00
        else:
            data[f.flag_off] = 0x01 if visible else 0x00

        # Height
        data[f.height_off:f.height_off + 4] = struct.pack('<f', height)

        # Material path region (fixed, bounded — never touches later header data)
        max_len = f.mat_max_len
        if not material_bytes:
            path_bytes = b'\x00' * max_len
        elif len(material_bytes) >= max_len:
            path_bytes = material_bytes[:max_len - 1] + b'\x00'
        else:
            path_bytes = material_bytes + b'\x00' * (max_len - len(material_bytes))
        data[f.mat_off:f.mat_region_end] = path_bytes

        # Avatar-only fix bytes
        if f.fix_bytes is not None:
            fix_end = f.fix_off + len(f.fix_bytes)
            if len(data) < fix_end:
                data.extend(b'\x00' * (fix_end - len(data)))
            data[f.fix_off:fix_end] = f.fix_bytes
        return data

    def _write_settings_to_file(self, file_path, visible=None, height=None, material_bytes=None):
        with open(file_path, 'rb') as fh:
            data = bytearray(fh.read())
        if visible is None:
            visible = self.water_visible_chk.isChecked()
        if height is None:
            height = float(self.height_entry.text())
        if material_bytes is None:
            material_bytes = self._selected_material_bytes()
        self._write_water_block(data, visible, height, material_bytes)
        with open(file_path, 'wb') as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())

    def add_water_block(self):
        if self.current_sector is None or self.sdat_folder is None:
            QMessageBox.warning(self, "No Sector", "Select a sector first.")
            return
        target_path = self._file_for(self.current_sector)
        if not target_path or not os.path.isfile(target_path):
            QMessageBox.critical(self, "Missing File", "Sector file not found.")
            return
        try:
            self._write_settings_to_file(
                target_path, visible=True, height=1.0,
                material_bytes=self.fmt.default_material)
            self.load_sector_into_ui(self.current_sector)
            self.sector_grid.scan_water_sectors()
            self.sector_grid.update()
            QMessageBox.information(
                self, "Success",
                f"Water block added to sector {self.current_sector}!\n"
                f"Now adjust settings and click Save.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to add water block: {e}")

    def save_current_sector(self):
        if self.current_sector is None or self.sdat_folder is None:
            QMessageBox.warning(self, "No Sector", "Select a sector first.")
            return
        target_path = self._file_for(self.current_sector)
        if not target_path or not os.path.isfile(target_path):
            QMessageBox.critical(self, "Missing File", "Sector file not found.")
            return
        try:
            self._write_settings_to_file(target_path)
            self.sector_grid.scan_water_sectors()
            self.sector_grid.update()
            self.update_sector_info()
            if self.terrain_renderer:
                wd = self.terrain_renderer.parse_water_from_sector(target_path, self.current_sector)
                self.terrain_renderer.water_data[self.current_sector] = wd
            if self.canvas and hasattr(self.canvas, 'update'):
                self.canvas.update()
            QMessageBox.information(self, "Saved", f"Sector {self.current_sector} saved successfully!")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {e}")

    def auto_save_current_sector(self):
        if self.current_sector is None or self.sdat_folder is None:
            return
        target_path = self._file_for(self.current_sector)
        if not target_path or not os.path.isfile(target_path):
            return
        try:
            self._write_settings_to_file(target_path)
            self.sector_grid.scan_water_sectors()
            self.sector_grid.update()
        except Exception:
            pass  # Silent failure for auto-save

    def reset_current_sector(self):
        if self.current_sector is None or self.sdat_folder is None:
            QMessageBox.warning(self, "No Sector", "Select a sector first.")
            return
        reply = QMessageBox.question(
            self, "Confirm Reset",
            f"Are you sure you want to clear water from sector {self.current_sector}?",
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        target_path = self._file_for(self.current_sector)
        if not target_path or not os.path.isfile(target_path):
            QMessageBox.critical(self, "Missing File", "Sector file not found.")
            return
        try:
            self._write_settings_to_file(
                target_path, visible=False, height=0.0, material_bytes=None)
            self.load_sector_into_ui(self.current_sector)
            self.sector_grid.scan_water_sectors()
            self.sector_grid.update()
            if self.terrain_renderer:
                wd = self.terrain_renderer.parse_water_from_sector(target_path, self.current_sector)
                self.terrain_renderer.water_data[self.current_sector] = wd
            QMessageBox.information(self, "Reset", f"Sector {self.current_sector} water cleared successfully!")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to reset: {e}")

    def apply_to_selected(self):
        selected = self.sector_grid.selected_sectors
        if not selected or self.sdat_folder is None:
            QMessageBox.warning(self, "No Selection", "Ctrl+click sectors on the grid to select them first.")
            return
        failed = []
        for sector_idx in sorted(selected):
            file_path = self._file_for(sector_idx)
            if not file_path or not os.path.isfile(file_path):
                failed.append(sector_idx)
                continue
            try:
                self._write_settings_to_file(file_path)
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
        if self.current_sector is None:
            self.sector_info.setText("Select a sector to edit\nCtrl+click to multi-select")
        else:
            has_water = self.current_sector in self.sector_grid.water_sectors
            status = "💧 Has water" if has_water else "⚪ No water"
            n = len(self.sector_grid.selected_sectors)
            multi = f"\n{n} sectors selected" if n > 1 else ""
            self.sector_info.setText(f"Sector {self.current_sector}\n{status}{multi}")


# Convenience function for opening the dialog
def show_water_editor(parent=None, terrain_renderer=None, canvas=None, game_mode="avatar"):
    """
    Show the water editor dialog.

    Args:
        parent: Parent widget
        terrain_renderer: TerrainRenderer instance (optional)
        canvas: MapCanvas instance for live 3D preview (optional)
        game_mode: "avatar" or "farcry2"
    """
    dialog = WaterEditorDialog(parent, terrain_renderer, canvas, game_mode=game_mode)
    dialog.exec()
    return dialog
