"""
enable_all_sectors.py

GUI tool — converts all sectorN.desc.fcb → XML, modifies every sector's
neighbor list to include all others, then converts back to FCB.
Uses FCBConverter batch folder mode for speed. For testing only.

Works with both Avatar (sector IDs 0–255) and FC2 (IDs like 5120–6335).
Sector IDs are always discovered by scanning the folder — never hardcoded.
"""

import os
import sys
import re
import glob
import struct
import subprocess
import xml.etree.ElementTree as ET

# PyQt5, NOT PyQt6: this module is exec'd INSIDE the editor's process
# (simplified_map_editor.py -> open_enable_all_sectors), and the editor runs on
# PyQt5. Importing PyQt6 here loads Qt6 DLLs next to the already-loaded Qt5
# ones, which hard-crashes the whole editor the moment a widget is created.
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QFileDialog,
    QPlainTextEdit, QProgressBar
)
from PyQt5.QtWidgets import QCheckBox
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QFont

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FLAGS_INT16   = 309
FLAGS_HEX     = struct.pack('<h', FLAGS_INT16).hex().upper()  # "3501"
FCB_CONVERTER = os.path.join(os.path.dirname(__file__), "FCBConverter.exe")


def _converter():
    """The shared conversion helpers from the sibling create_sector.py
    (native fcb_convert first, legacy FCBConverter.exe fallback — the editor
    stopped shipping the exe in June 2026, so subprocess calls silently did
    nothing). Returns the module, or None if it can't be imported."""
    try:
        d = os.path.dirname(os.path.abspath(__file__))
        if d not in sys.path:
            sys.path.insert(0, d)
        import create_sector as _cs
        return _cs
    except Exception:
        return None


def _apply_editor_theme(widget):
    """Style the window to the editor's Light/Dark preference. Guarded like
    _converter(), but inserts the project ROOT (one level up from this tools
    dir) so theme_settings imports whenever this script runs inside the editor
    process; standalone use falls back gracefully to the system palette."""
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in sys.path:
            sys.path.insert(0, root)
        from theme_settings import apply_dialog_theme
        apply_dialog_theme(widget)
    except Exception:
        pass


def _converter_available() -> bool:
    cs = _converter()
    if cs is not None:
        return cs.converter_available()
    return os.path.exists(FCB_CONVERTER)


def _run_conversion(args: list) -> bool:
    """Run one FCBConverter-style command via the shared helper (which also
    splits comma filters for the native engine). Returns True if a converter ran."""
    cs = _converter()
    if cs is not None:
        return cs.run_fcb_conversion(args)
    if os.path.exists(FCB_CONVERTER):
        subprocess.run([FCB_CONVERTER] + args,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    return False


def int32_le_hex(n: int) -> str:
    return struct.pack('<i', n).hex().upper()


def scan_sector_ids(worldsectors_dir: str) -> list[int]:
    """Return sorted list of sector IDs found in the folder by scanning sector*.desc.fcb files."""
    ids = []
    for name in os.listdir(worldsectors_dir):
        m = re.fullmatch(r'sector(\d+)\.desc\.fcb', name)
        if m:
            ids.append(int(m.group(1)))
    return sorted(ids)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _ensure_main_mission_layer(root) -> bool:
    """Add a minimal 'main' MissionLayer to the Default category if one is missing.
    Returns True if a layer was added, False if already present or no Default category."""
    for cat in root.findall('.//object[@name="Category"]'):
        text_id = cat.find('field[@name="text_Id"]')
        if text_id is None or text_id.get('value-String') != 'Default':
            continue
        for ml in cat.findall('object[@name="MissionLayer"]'):
            tp = ml.find('field[@name="text_PathId"]')
            if tp is not None and tp.get('value-String') == 'main':
                return False  # already has main
        # Add minimal main MissionLayer
        ml = ET.SubElement(cat, 'object')
        ml.set('hash', '494C09F2')
        ml.set('name', 'MissionLayer')

        tp = ET.SubElement(ml, 'field')
        tp.set('hash', 'C56F9204')
        tp.set('name', 'text_PathId')
        tp.set('value-String', 'main')
        tp.set('type', 'BinHex')
        tp.text = '6D61696E00'

        pid = ET.SubElement(ml, 'field')
        pid.set('hash', 'D0E30BF7')
        pid.set('name', 'PathId')
        pid.set('value-ComputeHash32', 'main')
        pid.set('type', 'BinHex')
        pid.text = '64CD28BF'

        _MAIN_LAYER_TYPES = [
            'CMaterialResource',
            'CTextureResource',
            'CParticlesEmitterParamResource',
            'CSoundResource',
            'CAnimationResource',
            'CMovementResource',
            'CStateMachineResource',
            'CFrankensteinPoseResource',
            'CGeometryResource',
            'CParticlesSystemParamResource',
            'CResourceContainer',
            'CSkeletonResource',
            'CAnimationPackageResource',
            'CFaceAnimResource',
            'CDominoBoxResource',
            'CPhysResource',
            'CRealtreeResource',
        ]

        type_ids = ET.SubElement(ml, 'field')
        type_ids.set('hash', '24279147')
        type_ids.set('name', 'TypeIds')
        for t in _MAIN_LAYER_TYPES:
            ET.SubElement(type_ids, 'Resource').set('ID', t)

        res_ids = ET.SubElement(ml, 'field')
        res_ids.set('hash', '6F0AC77A')
        res_ids.set('name', 'ResIds')
        for _ in _MAIN_LAYER_TYPES:
            ET.SubElement(res_ids, 'Resource').set('ID', '__Unknown\\0000000000000000')

        return True
    return False  # no Default category found


def modify_xml(xml_path: str, sector_id: int, all_ids: list[int],
               add_main_layer: bool = False) -> tuple[bool, bool]:
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError:
        return False, False

    root = tree.getroot()
    sector_desc = root.find("object[@name='SectorDesc']")
    if sector_desc is None:
        return False, False

    for s in sector_desc.findall("object[@name='Sector']"):
        sector_desc.remove(s)

    # FCBConverter places SectorDesc children at the same indent as the version field.
    # Reuse its tail so each new Sector element lands on its own line at that same level.
    version_field = sector_desc.find("field[@name='version']")
    sibling_indent = version_field.tail if (version_field is not None and version_field.tail) else "\n  "

    other_ids = [i for i in all_ids if i != sector_id]
    for other_id in other_ids:
        s = ET.SubElement(sector_desc, "object")
        s.set("hash", "4C0FDCDE")
        s.set("name", "Sector")
        s.tail = sibling_indent  # one Sector per line, matching version field's indent

        id_field = ET.SubElement(s, "field")
        id_field.set("hash", "BF396750")
        id_field.set("name", "id")
        id_field.set("value-Int32", str(other_id))
        id_field.set("type", "BinHex")
        id_field.text = int32_le_hex(other_id)

        flags_field = ET.SubElement(s, "field")
        flags_field.set("hash", "CAC46EBE")
        flags_field.set("name", "Flags")
        flags_field.set("value-Int16", str(FLAGS_INT16))
        flags_field.set("type", "BinHex")
        flags_field.text = FLAGS_HEX

    main_added = False
    if add_main_layer:
        main_added = _ensure_main_mission_layer(root)
        if main_added:
            ET.indent(tree, space="  ")

    tree.write(xml_path, encoding="utf-8", xml_declaration=True)
    return True, main_added


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

class Worker(QThread):
    log      = pyqtSignal(str)
    progress = pyqtSignal(int)
    phase    = pyqtSignal(str)
    finished = pyqtSignal(str)
    total    = pyqtSignal(int)  # emitted once at start so GUI can set progress range

    def __init__(self, worldsectors_dir: str, fc2: bool, add_main_layer: bool = False):
        super().__init__()
        self.worldsectors_dir = worldsectors_dir
        self.fc2 = fc2
        self.add_main_layer = add_main_layer

    def run(self):
        d   = self.worldsectors_dir
        fc2 = self.fc2
        has_fcb = _converter_available()

        if not has_fcb:
            self.log.emit("WARNING: no FCB converter available — XML modification only.\n")

        # ── Phase 1: FCB → XML ───────────────────────────────────────────────
        if has_fcb:
            self.phase.emit("Phase 1/3 — Converting FCB → XML…")
            self.log.emit("Running batch FCB → XML…")
            args = [f'-source={d}', '-filter=sector*.fcb']
            if fc2:
                args.append('-fc2')
            if not _run_conversion(args):
                self.log.emit("[WARNING] FCB → XML conversion did not run")
            self.log.emit("FCB → XML done.\n")

        # ── Discover actual sector IDs ────────────────────────────────────────
        all_ids = scan_sector_ids(d)
        n = len(all_ids)
        if n == 0:
            self.log.emit("ERROR: No sector*.desc.fcb files found in folder.")
            self.finished.emit("\nAborted — no sectors found.")
            return

        self.log.emit(f"Found {n} sectors  (IDs {all_ids[0]}–{all_ids[-1]})\n")
        self.total.emit(n * 2)  # two halves: modify + rename

        # ── Phase 2: Modify XMLs  (progress 0 → n) ───────────────────────────
        self.phase.emit("Phase 2/3 — Modifying XMLs…")
        xml_ok = xml_err = main_added = 0

        for i, sector_id in enumerate(all_ids):
            xml_path = os.path.join(d, f"sector{sector_id}.desc.fcb.converted.xml")
            if not os.path.exists(xml_path):
                self.log.emit(f"[MISSING]  sector{sector_id}.desc.fcb.converted.xml")
                xml_err += 1
            else:
                ok, did_add = modify_xml(xml_path, sector_id, all_ids,
                                         add_main_layer=self.add_main_layer)
                if ok:
                    xml_ok += 1
                    if did_add:
                        main_added += 1
                else:
                    self.log.emit(f"[XML ERR]  sector{sector_id}")
                    xml_err += 1
            self.progress.emit(i + 1)

        if self.add_main_layer:
            self.log.emit(f"Main MissionLayer added to {main_added} sector(s).\n")

        self.log.emit(f"XML phase done: {xml_ok} modified, {xml_err} errors.\n")

        if not has_fcb:
            main_line = f"  Main layers added: {main_added}\n" if self.add_main_layer else ""
            self.finished.emit(
                f"\nDone (XML only — no FCBConverter).\n"
                f"  XML modified: {xml_ok}/{n}  ({xml_err} errors)\n"
                f"{main_line}"
            )
            return

        # ── Phase 3: XML → FCB  (progress n → 2n) ────────────────────────────
        self.phase.emit("Phase 3/3 — Converting XML → FCB…")
        self.log.emit("Running batch XML → FCB…")
        args = [f'-source={d}', '-filter=sector*.converted.xml']
        if fc2:
            args.append('-fc2')
        if not _run_conversion(args):
            self.log.emit("[WARNING] XML → FCB conversion did not run")

        renamed_ok = renamed_err = 0
        new_fcbs = sorted(glob.glob(os.path.join(d, "sector*_new.fcb")))
        for i, new_fcb in enumerate(new_fcbs):
            original = new_fcb.replace("_new.fcb", ".fcb")
            try:
                if os.path.exists(original):
                    os.remove(original)
                os.rename(new_fcb, original)
                renamed_ok += 1
            except OSError:
                renamed_err += 1
            self.progress.emit(n + i + 1)

        self.log.emit(f"Renamed {renamed_ok} FCB files  ({renamed_err} rename errors).\n")

        self.phase.emit("Done.")
        main_line = f"  Main layers added: {main_added}\n" if self.add_main_layer else ""
        self.finished.emit(
            f"\nDone.\n"
            f"  XML modified:  {xml_ok}/{n}  ({xml_err} errors)\n"
            f"{main_line}"
            f"  FCB renamed:   {renamed_ok}  ({renamed_err} errors)\n"
        )


# ---------------------------------------------------------------------------
# Convert-only worker  (XML → FCB, no sector modification)
# ---------------------------------------------------------------------------

class ConvertXmlWorker(QThread):
    log      = pyqtSignal(str)
    progress = pyqtSignal(int)
    phase    = pyqtSignal(str)
    finished = pyqtSignal(str)
    total    = pyqtSignal(int)

    def __init__(self, worldsectors_dir: str, fc2: bool):
        super().__init__()
        self.worldsectors_dir = worldsectors_dir
        self.fc2 = fc2

    def run(self):
        d = self.worldsectors_dir

        if not _converter_available():
            self.log.emit("ERROR: no FCB converter available.")
            self.finished.emit("\nAborted — no FCB converter available.")
            return

        xml_files = glob.glob(os.path.join(d, "*.fcb.converted.xml"))
        n = len(xml_files)
        if n == 0:
            self.log.emit("No .fcb.converted.xml files found in folder.")
            self.finished.emit("\nAborted — no converted XML files found.")
            return

        self.log.emit(f"Found {n} .fcb.converted.xml file(s) to convert.\n")
        self.total.emit(n + 1)  # conversion step + rename step

        # ── Convert XML → FCB ────────────────────────────────────────────────
        self.phase.emit("Converting XML → FCB…")
        self.log.emit("Running batch XML → FCB…")
        args = [f'-source={d}', '-filter=*.fcb.converted.xml']
        if self.fc2:
            args.append('-fc2')
        if not _run_conversion(args):
            self.log.emit("[WARNING] XML → FCB conversion did not run")
        self.progress.emit(n)

        # ── Rename *_new.fcb → *.fcb ─────────────────────────────────────────
        self.phase.emit("Renaming output files…")
        new_fcbs = sorted(glob.glob(os.path.join(d, "*_new.fcb")))
        renamed_ok = renamed_err = 0
        for new_fcb in new_fcbs:
            original = new_fcb.replace("_new.fcb", ".fcb")
            try:
                if os.path.exists(original):
                    os.remove(original)
                os.rename(new_fcb, original)
                renamed_ok += 1
                self.log.emit(f"  Renamed: {os.path.basename(original)}")
            except OSError as e:
                self.log.emit(f"[RENAME ERR] {os.path.basename(new_fcb)}: {e}")
                renamed_err += 1
        self.progress.emit(n + 1)

        self.phase.emit("Done.")
        self.finished.emit(
            f"\nDone.\n"
            f"  XML files found:    {n}\n"
            f"  FCB files renamed:  {renamed_ok}  ({renamed_err} errors)\n"
        )


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class EnableAllSectorsWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Enable All Sectors")
        self.setMinimumWidth(640)
        self._worker = None
        self._build_ui()
        # Follow the editor's Light/Dark preference (no-op when standalone)
        _apply_editor_theme(self)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        root.addWidget(QLabel("Worldsectors folder:"))
        row = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("Path to …/generated/worldsectors")
        row.addWidget(self.dir_edit)
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse)
        row.addWidget(browse_btn)
        root.addLayout(row)

        # fc2 is always enabled — no checkbox shown to users
        self.fc2_check = QCheckBox()
        self.fc2_check.setChecked(True)
        self.fc2_check.setVisible(False)

        self.main_layer_check = QCheckBox(
            "Add 'main' MissionLayer to Default categories that are missing one"
        )
        self.main_layer_check.setChecked(False)
        self.main_layer_check.setToolTip(
            "For each sectorN.desc.fcb whose Default NativeResources category\n"
            "has no 'main' MissionLayer, insert a minimal one (1× CGeometryResource)."
        )
        root.addWidget(self.main_layer_check)

        self.fcb_label = QLabel()
        self._refresh_fcb_label()
        root.addWidget(self.fcb_label)

        self.phase_label = QLabel("Ready.")
        root.addWidget(self.phase_label)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Run Enable All Sectors")
        self.run_btn.setFixedHeight(32)
        self.run_btn.clicked.connect(self._run)
        btn_row.addWidget(self.run_btn)

        self.convert_btn = QPushButton("Convert XML → FCB")
        self.convert_btn.setFixedHeight(32)
        self.convert_btn.setToolTip(
            "Re-convert all .fcb.converted.xml files in the folder back to FCB.\n"
            "Use this after manually editing any XML files."
        )
        self.convert_btn.clicked.connect(self._convert)
        btn_row.addWidget(self.convert_btn)
        root.addLayout(btn_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 512)  # placeholder; updated dynamically
        self.progress.setValue(0)
        root.addWidget(self.progress)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFont(QFont("Consolas", 9))
        self.log_box.setMinimumHeight(300)
        root.addWidget(self.log_box)

    def _refresh_fcb_label(self):
        # Semantic green/orange, in shades readable on both editor themes
        cs = _converter()
        if cs is not None and cs._native_engine() is not None:
            self.fcb_label.setText("FCB converter: native (fcb_convert)")
            self.fcb_label.setStyleSheet("color: #2e7d32;")
        elif os.path.exists(FCB_CONVERTER):
            self.fcb_label.setText("FCB converter: FCBConverter.exe")
            self.fcb_label.setStyleSheet("color: #2e7d32;")
        else:
            self.fcb_label.setText("FCB converter: NOT found")
            self.fcb_label.setStyleSheet("color: #b45f06;")

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "Select worldsectors folder")
        if path:
            self.dir_edit.setText(path)

    def _start_worker(self, worker):
        self.log_box.clear()
        self.progress.setValue(0)
        self.run_btn.setEnabled(False)
        self.convert_btn.setEnabled(False)
        self._worker = worker
        worker.log.connect(self.log_box.appendPlainText)
        worker.progress.connect(self.progress.setValue)
        worker.phase.connect(self.phase_label.setText)
        worker.total.connect(lambda n: self.progress.setRange(0, n))
        worker.finished.connect(self._on_finished)
        worker.start()

    def _run(self):
        d = self.dir_edit.text().strip()
        if not d:
            self.log_box.appendPlainText("ERROR: No folder selected.")
            return
        if not os.path.isdir(d):
            self.log_box.appendPlainText(f"ERROR: Folder not found:\n  {d}")
            return
        self._start_worker(Worker(d, fc2=self.fc2_check.isChecked(),
                                   add_main_layer=self.main_layer_check.isChecked()))

    def _convert(self):
        d = self.dir_edit.text().strip()
        if not d:
            self.log_box.appendPlainText("ERROR: No folder selected.")
            return
        if not os.path.isdir(d):
            self.log_box.appendPlainText(f"ERROR: Folder not found:\n  {d}")
            return
        self._start_worker(ConvertXmlWorker(d, fc2=self.fc2_check.isChecked()))

    def _on_finished(self, summary: str):
        self.log_box.appendPlainText(summary)
        self.run_btn.setEnabled(True)
        self.convert_btn.setEnabled(True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = EnableAllSectorsWindow()
    win.show()
    sys.exit(app.exec_())
