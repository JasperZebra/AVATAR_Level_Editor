"""
create_sector.py

GUI tool — creates a new empty worldsectorN.data.fcb for any sector
that currently has no entity data, then patches sectorsdep.xml so the
engine knows the sector exists.

Single-sector steps:
  1. Write worldsectorN.data.fcb.converted.xml  (empty WorldSector shell)
  2. FCBConverter converts it → worldsectorN.data_new.fcb → renamed to .fcb
  3. Add HasMainSectorData to the sector's CWorldSector entry in sectorsdep.xml
  4. Convert patched sectorsdep.xml back to sectorsdep.fcb

Bulk mode (Create All Missing):
  - Scans sectorsdep.xml for every CWorldSector that lacks a worldsectorN.data.fcb
  - Creates all missing XMLs, batch-converts to FCB, patches sectorsdep once,
    then converts sectorsdep to FCB once.
"""

import os
import re
import sys
import glob
import struct
import subprocess
import shutil
import xml.etree.ElementTree as ET

# PyQt5, NOT PyQt6: this module is exec'd INSIDE the editor's process
# (simplified_map_editor.py -> open_create_sector), and the editor runs on
# PyQt5. Importing PyQt6 here loads Qt6 DLLs next to the already-loaded Qt5
# ones, which hard-crashes the whole editor the moment a widget is created.
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLineEdit, QLabel, QFileDialog,
    QPlainTextEdit, QSpinBox, QProgressBar
)
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QFont

FCB_CONVERTER = os.path.join(os.path.dirname(__file__), "FCBConverter.exe")

# Global sector-grid stride per game (mirrors sector_grid_stride in
# simplified_map_editor.py): Avatar worlds are one 16x16 grid (IDs 0-255);
# FC2 worlds are an 80x80 GLOBAL grid (5x5 cells x 16 sectors, IDs like 2592)
# and each cell folder owns one 16x16 block of it. Ground-truthed against
# retail world1: worldsector2592 has Id=2592, X=32, Y=32 (32*80+32) and the
# same field hashes as Avatar.
GRID_STRIDE = {'avatar': 16, 'farcry2': 80}
CELL_SPAN = 16   # a folder of sectors is 16x16 in BOTH games

# ---------------------------------------------------------------------------
# FCB conversion — native converter first, legacy exe as fallback
# ---------------------------------------------------------------------------
# The editor replaced FCBConverter.exe with the native tools/fcb_convert.py
# (June 2026) and no longer ships the exe, so subprocess calls silently did
# nothing. Route through file_converter._native_fcbconvert (a drop-in for the
# exe's CLI) when importable — it is whenever this script runs inside the
# editor process — and only fall back to the exe for standalone use.

def _native_engine():
    try:
        import sys as _sys
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in _sys.path:
            _sys.path.insert(0, root)
        from file_converter import _native_fcbconvert
        return _native_fcbconvert
    except Exception:
        return None


def _apply_editor_theme(widget):
    """Style the window to the editor's Light/Dark preference. Guarded exactly
    like _native_engine(): theme_settings is importable whenever this script
    runs inside the editor process (project root inserted into sys.path);
    standalone use falls back gracefully to the system palette (no styling)."""
    try:
        import sys as _sys
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in _sys.path:
            _sys.path.insert(0, root)
        from theme_settings import apply_dialog_theme
        apply_dialog_theme(widget)
    except Exception:
        pass


def converter_available() -> bool:
    return _native_engine() is not None or os.path.exists(FCB_CONVERTER)


def run_fcb_conversion(args: list) -> bool:
    """Run one FCBConverter-style command (single file or -source/-filter
    batch). Comma filters are split for the native engine (fnmatch takes one
    glob; the old exe accepted comma lists). Returns True if a converter ran."""
    native = _native_engine()
    if native is not None:
        filt = next((a for a in args if a.startswith('-filter=')), None)
        if filt and ',' in filt:
            for pat in filt[len('-filter='):].split(','):
                one = [a if not a.startswith('-filter=') else f'-filter={pat}'
                       for a in args]
                native([FCB_CONVERTER] + one)
        else:
            native([FCB_CONVERTER] + args)
        return True
    if os.path.exists(FCB_CONVERTER):
        subprocess.run([FCB_CONVERTER] + args,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def int32_le_hex(n: int) -> str:
    return struct.pack('<i', n).hex().upper()


def sector_xy(sector_id: int, stride: int = 16) -> tuple[int, int]:
    return sector_id % stride, sector_id // stride


_ID_PATTERNS = (
    re.compile(r'worldsector(\d+)\.data\.fcb$'),
    re.compile(r'sector(\d+)\.desc\.fcb$'),
    re.compile(r'landmarkfar_(\d+)\.data\.fcb$'),
    re.compile(r'landmarknear(\d+)\.data\.fcb$'),
)


def cell_id_block(worldsectors_dir: str, stride: int) -> list[int] | None:
    """The 256 sector IDs this worldsectors folder owns.

    Avatar: always 0-255 (one folder per world). FC2: the folder is ONE cell of
    the 80-wide global grid — derive its 16x16 block from any sector file
    already present (retail cells always have desc/landmark files). Returns a
    sorted ID list, or None when the block can't be derived (empty FC2 folder).
    Iterating range(stride*stride) instead would try to create thousands of
    sectors belonging to OTHER cells in this folder — never do that."""
    if stride == 16:
        return list(range(256))
    found = []
    try:
        for name in os.listdir(worldsectors_dir):
            for pat in _ID_PATTERNS:
                m = pat.match(name)
                if m:
                    found.append(int(m.group(1)))
                    break
    except OSError:
        return None
    if not found:
        return None
    gx, gy = min(found) % stride, min(found) // stride
    gx0, gy0 = (gx // CELL_SPAN) * CELL_SPAN, (gy // CELL_SPAN) * CELL_SPAN
    return [(gy0 + r) * stride + (gx0 + c)
            for r in range(CELL_SPAN) for c in range(CELL_SPAN)]


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

WORLDSECTOR_TEMPLATE = """\
<?xml version="1.0" encoding="utf-8"?>
<object hash="C1CB6D9A" name="WorldSector">
  <field hash="2ABD43F2" name="Id" value-Int32="{id}" type="BinHex">{id_hex}</field>
  <field hash="B7B2364B" name="X" value-Int32="{x}" type="BinHex">{x_hex}</field>
  <field hash="C0B506DD" name="Y" value-Int32="{y}" type="BinHex">{y_hex}</field>
  <object hash="494C09F2" name="MissionLayer">
    <field hash="C56F9204" name="text_PathId" value-String="main" type="BinHex">6D61696E00</field>
    <field hash="D0E30BF7" name="PathId" value-ComputeHash32="main" type="BinHex">64CD28BF</field>
  </object>
</object>
"""


def create_worldsector_xml(worldsectors_dir: str, sector_id: int,
                           stride: int = 16) -> tuple[bool, str]:
    """Write the empty worldsectorN.data.fcb.converted.xml. Returns (ok, message)."""
    x, y = sector_xy(sector_id, stride)
    xml_name = f"worldsector{sector_id}.data.fcb.converted.xml"
    xml_path = os.path.join(worldsectors_dir, xml_name)

    if os.path.exists(xml_path):
        return False, f"Already exists: {xml_name}"

    content = WORLDSECTOR_TEMPLATE.format(
        id=sector_id,  id_hex=int32_le_hex(sector_id),
        x=x,           x_hex=int32_le_hex(x),
        y=y,           y_hex=int32_le_hex(y),
    )
    try:
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True, f"Created {xml_name}  (Id={sector_id}, X={x}, Y={y})"
    except OSError as e:
        return False, f"Write failed: {e}"


def _ensure_main_mission_layer(root) -> bool:
    """Add a minimal 'main' MissionLayer to the Default NativeResources category if missing.
    Returns True if a layer was inserted."""
    for cat in root.findall('.//object[@name="Category"]'):
        text_id = cat.find('field[@name="text_Id"]')
        if text_id is None or text_id.get('value-String') != 'Default':
            continue
        for ml in cat.findall('object[@name="MissionLayer"]'):
            tp = ml.find('field[@name="text_PathId"]')
            if tp is not None and tp.get('value-String') == 'main':
                return False
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
    return False


def patch_sector_desc_main_layer(worldsectors_dir: str, sector_id: int) -> tuple[bool, str]:
    """Ensure sectorN.desc.fcb has a 'main' MissionLayer in its Default NativeResources category.

    Converts FCB→XML if the converted XML isn't already present, patches, converts back.
    Returns (was_modified, message).
    """
    desc_fcb = os.path.join(worldsectors_dir, f"sector{sector_id}.desc.fcb")
    desc_xml = desc_fcb + ".converted.xml"

    if not os.path.exists(desc_fcb) and not os.path.exists(desc_xml):
        return False, f"sector{sector_id}.desc.fcb not found — skipping"

    # Convert FCB → XML if the XML isn't already present
    if not os.path.exists(desc_xml):
        if not run_fcb_conversion([desc_fcb, '-fc2']):
            return False, "No FCB converter available — cannot read desc.fcb"
        if not os.path.exists(desc_xml):
            return False, f"Conversion did not produce {os.path.basename(desc_xml)}"

    try:
        tree = ET.parse(desc_xml)
    except ET.ParseError as e:
        return False, f"XML parse error: {e}"

    if not _ensure_main_mission_layer(tree.getroot()):
        return False, f"sector{sector_id}.desc: no Default category, or main already present"

    ET.indent(tree, space="  ")
    tree.write(desc_xml, encoding="utf-8", xml_declaration=True)

    # Convert the patched XML back to FCB
    new_fcb = desc_fcb.replace(".fcb", "_new.fcb")  # sectorN.desc_new.fcb
    if os.path.exists(new_fcb):
        os.remove(new_fcb)

    if not run_fcb_conversion([desc_xml, '-fc2']):
        return True, f"sector{sector_id}.desc: main layer added (XML only — no converter)"

    if not os.path.exists(new_fcb):
        return True, f"sector{sector_id}.desc: main layer added to XML; FCB conversion failed"

    if os.path.exists(desc_fcb):
        os.remove(desc_fcb)
    os.rename(new_fcb, desc_fcb)
    return True, f"sector{sector_id}.desc: main MissionLayer added and FCB updated"


def convert_to_fcb(worldsectors_dir: str, sector_id: int) -> tuple[bool, str]:
    """Convert the new XML to FCB → rename _new.fcb to final name."""
    xml_path  = os.path.join(worldsectors_dir, f"worldsector{sector_id}.data.fcb.converted.xml")
    base_name = os.path.splitext(os.path.basename(xml_path.replace(".converted.xml", "")))[0]
    # base_name = "worldsector34.data"
    new_fcb   = os.path.join(worldsectors_dir, base_name + "_new.fcb")
    final_fcb = os.path.join(worldsectors_dir, f"worldsector{sector_id}.data.fcb")

    if os.path.exists(new_fcb):
        os.remove(new_fcb)

    if not run_fcb_conversion([xml_path, '-fc2']):
        return False, "No FCB converter available — skipping FCB conversion"

    if not os.path.exists(new_fcb):
        return False, f"Conversion did not produce {os.path.basename(new_fcb)}"

    if os.path.exists(final_fcb):
        os.remove(final_fcb)
    os.rename(new_fcb, final_fcb)
    return True, f"Converted → {os.path.basename(final_fcb)}"


# landmarkfar_{N}.data.fcb   (note: underscore before N)
# landmarknear{N}.data.fcb   (note: no underscore before N)

def _landmark_xml_name(sector_id: int, kind: str) -> str:
    if kind == "far":
        return f"landmarkfar_{sector_id}.data.fcb.converted.xml"
    return f"landmarknear{sector_id}.data.fcb.converted.xml"


def _landmark_final_fcb_name(sector_id: int, kind: str) -> str:
    if kind == "far":
        return f"landmarkfar_{sector_id}.data.fcb"
    return f"landmarknear{sector_id}.data.fcb"


def create_landmark_xml(worldsectors_dir: str, sector_id: int, kind: str,
                        stride: int = 16) -> tuple[bool, str]:
    """Write an empty landmarkfar/landmarknear WorldSector XML. Returns (ok, message)."""
    x, y = sector_xy(sector_id, stride)
    xml_name = _landmark_xml_name(sector_id, kind)
    xml_path = os.path.join(worldsectors_dir, xml_name)
    if os.path.exists(xml_path):
        return False, f"Already exists: {xml_name}"
    content = WORLDSECTOR_TEMPLATE.format(
        id=sector_id, id_hex=int32_le_hex(sector_id),
        x=x,          x_hex=int32_le_hex(x),
        y=y,          y_hex=int32_le_hex(y),
    )
    try:
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True, f"Created {xml_name}"
    except OSError as e:
        return False, f"Write failed: {e}"


def convert_landmark_to_fcb(worldsectors_dir: str, sector_id: int, kind: str) -> tuple[bool, str]:
    """Convert a landmark XML to FCB → rename _new.fcb to final name."""
    xml_name  = _landmark_xml_name(sector_id, kind)
    xml_path  = os.path.join(worldsectors_dir, xml_name)
    base_name = os.path.splitext(os.path.basename(xml_path.replace(".converted.xml", "")))[0]
    new_fcb   = os.path.join(worldsectors_dir, base_name + "_new.fcb")
    final_name = _landmark_final_fcb_name(sector_id, kind)
    final_fcb  = os.path.join(worldsectors_dir, final_name)

    if os.path.exists(new_fcb):
        os.remove(new_fcb)

    if not run_fcb_conversion([xml_path, '-fc2']):
        return False, "No FCB converter available — skipping FCB conversion"

    if not os.path.exists(new_fcb):
        return False, f"Conversion did not produce {os.path.basename(new_fcb)}"

    if os.path.exists(final_fcb):
        os.remove(final_fcb)
    os.rename(new_fcb, final_fcb)
    return True, f"Converted → {final_name}"


def convert_sectorsdep_to_fcb(worlds_generated_dir: str) -> tuple[bool, str]:
    """Convert the patched *.sectorsdep.xml back to .fcb so the game reads the changes.

    FCBConverter only accepts .converted.xml for XML→FCB.  We temporarily copy
    the .sectorsdep.xml to .sectorsdep.fcb.converted.xml, convert, then clean up.
    """
    if not converter_available():
        return False, "No FCB converter available — sectorsdep FCB not updated"

    matches = glob.glob(os.path.join(worlds_generated_dir, "*.sectorsdep.xml"))
    if not matches:
        return False, "No *.sectorsdep.xml found — cannot convert to FCB"
    xml_path = matches[0]

    # e.g. z_dev_orouleau.sectorsdep
    stem = os.path.splitext(os.path.basename(xml_path))[0]

    # FCBConverter needs .fcb.converted.xml to produce <stem>_new.fcb
    tmp_xml   = os.path.join(worlds_generated_dir, stem + ".fcb.converted.xml")
    new_fcb   = os.path.join(worlds_generated_dir, stem + "_new.fcb")
    final_fcb = os.path.join(worlds_generated_dir, stem + ".fcb")

    shutil.copy2(xml_path, tmp_xml)

    if os.path.exists(new_fcb):
        os.remove(new_fcb)

    try:
        run_fcb_conversion([tmp_xml, '-fc2'])
    finally:
        if os.path.exists(tmp_xml):
            os.remove(tmp_xml)

    if not os.path.exists(new_fcb):
        return False, f"Conversion did not produce {os.path.basename(new_fcb)}"

    if os.path.exists(final_fcb):
        os.remove(final_fcb)
    os.rename(new_fcb, final_fcb)
    return True, f"Converted → {os.path.basename(final_fcb)}"


def patch_sectorsdep(worlds_generated_dir: str, sector_id: int) -> tuple[bool, str]:
    """Add HasMainSectorData, HasLandmarkNear, HasLandmarkFar to sector_id's CWorldSector entry."""
    matches = glob.glob(os.path.join(worlds_generated_dir, "*.sectorsdep.xml"))
    if not matches:
        return False, "No *.sectorsdep.xml found in worlds/generated folder"
    sdep_path = matches[0]

    try:
        tree = ET.parse(sdep_path)
    except ET.ParseError as e:
        return False, f"Parse error in {os.path.basename(sdep_path)}: {e}"

    root = tree.getroot()
    HAS_DESC_HASH          = "93880D75"
    HAS_MAIN_HASH          = "346F3F63"
    HAS_LANDMARK_NEAR_HASH = "97C2E974"
    HAS_LANDMARK_FAR_HASH  = "F19B593D"

    target = None
    for ws in root.iter("object"):
        if ws.get("name") != "CWorldSector":
            continue
        for field in ws:
            if field.get("name") == "SectorId" and field.get("value-Int32") == str(sector_id):
                target = ws
                break
        if target is not None:
            break

    if target is None:
        return False, f"SectorId={sector_id} not found in {os.path.basename(sdep_path)}"

    existing_hashes = {f.get("hash") for f in target}

    # Flags to insert in order: HasMainSectorData → HasLandmarkNear → HasLandmarkFar
    flags_to_add = [
        (HAS_MAIN_HASH,          "HasMainSectorData"),
        (HAS_LANDMARK_NEAR_HASH, "HasLandmarkNear"),
        (HAS_LANDMARK_FAR_HASH,  "HasLandmarkFar"),
    ]
    flags_to_add = [(h, n) for h, n in flags_to_add if h not in existing_hashes]

    if not flags_to_add:
        return True, f"All sector flags already present in sector {sector_id} — no change"

    # Insert after HasDescriptor if present, otherwise after position 0
    insert_pos = 1
    for i, child in enumerate(list(target)):
        if child.get("hash") == HAS_DESC_HASH:
            insert_pos = i + 1
            break

    for hash_val, name in flags_to_add:
        new_field = ET.Element("field")
        new_field.set("hash", hash_val)
        new_field.set("name", name)
        new_field.set("type", "BinHex")
        new_field.text = "01"
        target.insert(insert_pos, new_field)
        insert_pos += 1

    added_names = ", ".join(n for _, n in flags_to_add)
    ET.indent(tree, space="  ")
    tree.write(sdep_path, encoding="utf-8", xml_declaration=True)
    return True, f"Patched {os.path.basename(sdep_path)} — added {added_names} to sector {sector_id}"


def set_all_sectors_accessible(worlds_generated_dir: str) -> tuple[int, str]:
    """Set isSectorAccessible=True on every CWorldSector entry in *.sectorsdep.xml."""
    matches = glob.glob(os.path.join(worlds_generated_dir, "*.sectorsdep.xml"))
    if not matches:
        return 0, "No *.sectorsdep.xml found — skipping isSectorAccessible"
    sdep_path = matches[0]

    try:
        tree = ET.parse(sdep_path)
    except ET.ParseError as e:
        return 0, f"Parse error in {os.path.basename(sdep_path)}: {e}"

    root = tree.getroot()
    count = 0
    for ws in root.iter("object"):
        if ws.get("name") != "CWorldSector":
            continue
        field = None
        for f in ws:
            if f.get("name") == "isSectorAccessible":
                field = f
                break
        if field is None:
            field = ET.SubElement(ws, "field")
            field.set("name", "isSectorAccessible")
        field.set("value-Boolean", "True")
        count += 1

    ET.indent(tree, space="  ")
    tree.write(sdep_path, encoding="utf-8", xml_declaration=True)
    return count, f"Set isSectorAccessible=True on {count} sectors in {os.path.basename(sdep_path)}"


def find_missing_sectors(worldsectors_dir: str, worlds_generated_dir: str,
                         cell_ids: list[int] | None = None) -> tuple[list[int], list[int]]:
    """Return (missing_sector_ids, skipped_ids).

    missing = has CWorldSector entry in sectorsdep.xml but no worldsectorN.data.fcb.
    skipped = no CWorldSector entry in sectorsdep.xml (we can't safely create these).
    `cell_ids` is the ID set this folder owns (FC2: the cell's 16x16 block of
    the 80-wide global grid; Avatar: 0-255). Defaults to 0-255.
    """
    # Collect all sector IDs that have CWorldSector entries
    matches = glob.glob(os.path.join(worlds_generated_dir, "*.sectorsdep.xml"))
    known_ids: set[int] = set()
    if matches:
        try:
            root = ET.parse(matches[0]).getroot()
            for ws in root.iter("object"):
                if ws.get("name") != "CWorldSector":
                    continue
                for field in ws:
                    if field.get("name") == "SectorId":
                        try:
                            known_ids.add(int(field.get("value-Int32", -1)))
                        except ValueError:
                            pass
        except ET.ParseError:
            pass

    missing = []
    skipped = []
    for sid in (cell_ids if cell_ids is not None else range(256)):
        fcb_path = os.path.join(worldsectors_dir, f"worldsector{sid}.data.fcb")
        if os.path.exists(fcb_path):
            continue  # already has a file
        if sid in known_ids:
            missing.append(sid)
        else:
            skipped.append(sid)

    return missing, skipped


def patch_sectorsdep_bulk(worlds_generated_dir: str, sector_ids: list[int]) -> tuple[int, int, str]:
    """Patch HasMainSectorData, HasLandmarkNear, HasLandmarkFar for all sector_ids in one parse+save.
    Returns (patched_count, already_count, error_or_empty).
    """
    matches = glob.glob(os.path.join(worlds_generated_dir, "*.sectorsdep.xml"))
    if not matches:
        return 0, 0, "No *.sectorsdep.xml found"
    sdep_path = matches[0]

    try:
        tree = ET.parse(sdep_path)
    except ET.ParseError as e:
        return 0, 0, f"Parse error: {e}"

    root = tree.getroot()
    HAS_DESC_HASH          = "93880D75"
    HAS_MAIN_HASH          = "346F3F63"
    HAS_LANDMARK_NEAR_HASH = "97C2E974"
    HAS_LANDMARK_FAR_HASH  = "F19B593D"
    ALL_NEW_FLAGS = [
        (HAS_MAIN_HASH,          "HasMainSectorData"),
        (HAS_LANDMARK_NEAR_HASH, "HasLandmarkNear"),
        (HAS_LANDMARK_FAR_HASH,  "HasLandmarkFar"),
    ]

    # Build a quick lookup: sector_id → CWorldSector element
    sector_map: dict[int, ET.Element] = {}
    for ws in root.iter("object"):
        if ws.get("name") != "CWorldSector":
            continue
        for field in ws:
            if field.get("name") == "SectorId":
                try:
                    sector_map[int(field.get("value-Int32", -1))] = ws
                except ValueError:
                    pass

    patched = 0
    already = 0
    for sid in sector_ids:
        target = sector_map.get(sid)
        if target is None:
            continue

        existing_hashes = {f.get("hash") for f in target}
        flags_to_add = [(h, n) for h, n in ALL_NEW_FLAGS if h not in existing_hashes]

        if not flags_to_add:
            already += 1
            continue

        insert_pos = 1
        for i, child in enumerate(list(target)):
            if child.get("hash") == HAS_DESC_HASH:
                insert_pos = i + 1
                break

        for hash_val, name in flags_to_add:
            new_field = ET.Element("field")
            new_field.set("hash", hash_val)
            new_field.set("name", name)
            new_field.set("type", "BinHex")
            new_field.text = "01"
            target.insert(insert_pos, new_field)
            insert_pos += 1

        patched += 1

    if patched > 0:
        ET.indent(tree, space="  ")
        tree.write(sdep_path, encoding="utf-8", xml_declaration=True)

    return patched, already, ""


def find_missing_landmarks(worldsectors_dir: str,
                           cell_ids: list[int] | None = None) -> list[tuple[int, list[str]]]:
    """Return list of (sector_id, [missing_kinds]) for the folder's sectors
    missing landmark files. Checks both 'far' and 'near' for every ID in
    `cell_ids` (defaults to Avatar's 0-255)."""
    result = []
    for sid in (cell_ids if cell_ids is not None else range(256)):
        missing = []
        if not os.path.exists(os.path.join(worldsectors_dir, f"landmarkfar_{sid}.data.fcb")):
            missing.append("far")
        if not os.path.exists(os.path.join(worldsectors_dir, f"landmarknear{sid}.data.fcb")):
            missing.append("near")
        if missing:
            result.append((sid, missing))
    return result


def patch_sectorsdep_landmarks_bulk(
    worlds_generated_dir: str, sector_ids: list[int]
) -> tuple[int, int, str]:
    """Add HasLandmarkNear and HasLandmarkFar to all sector_ids in one parse+save.

    Does NOT add HasMainSectorData — use this when creating landmark files for
    sectors that already have (or don't need) worldsector data.
    Returns (patched_count, already_count, error_or_empty).
    """
    matches = glob.glob(os.path.join(worlds_generated_dir, "*.sectorsdep.xml"))
    if not matches:
        return 0, 0, "No *.sectorsdep.xml found"
    sdep_path = matches[0]

    try:
        tree = ET.parse(sdep_path)
    except ET.ParseError as e:
        return 0, 0, f"Parse error: {e}"

    root = tree.getroot()
    HAS_DESC_HASH          = "93880D75"
    HAS_LANDMARK_NEAR_HASH = "97C2E974"
    HAS_LANDMARK_FAR_HASH  = "F19B593D"
    LANDMARK_FLAGS = [
        (HAS_LANDMARK_NEAR_HASH, "HasLandmarkNear"),
        (HAS_LANDMARK_FAR_HASH,  "HasLandmarkFar"),
    ]

    sector_map: dict[int, ET.Element] = {}
    for ws in root.iter("object"):
        if ws.get("name") != "CWorldSector":
            continue
        for field in ws:
            if field.get("name") == "SectorId":
                try:
                    sector_map[int(field.get("value-Int32", -1))] = ws
                except ValueError:
                    pass

    patched = 0
    already = 0
    for sid in sector_ids:
        target = sector_map.get(sid)
        if target is None:
            continue

        existing_hashes = {f.get("hash") for f in target}
        flags_to_add = [(h, n) for h, n in LANDMARK_FLAGS if h not in existing_hashes]

        if not flags_to_add:
            already += 1
            continue

        insert_pos = 1
        for i, child in enumerate(list(target)):
            if child.get("hash") == HAS_DESC_HASH:
                insert_pos = i + 1
                break

        for hash_val, name in flags_to_add:
            new_field = ET.Element("field")
            new_field.set("hash", hash_val)
            new_field.set("name", name)
            new_field.set("type", "BinHex")
            new_field.text = "01"
            target.insert(insert_pos, new_field)
            insert_pos += 1

        patched += 1

    if patched > 0:
        ET.indent(tree, space="  ")
        tree.write(sdep_path, encoding="utf-8", xml_declaration=True)

    return patched, already, ""


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

class Worker(QThread):
    log      = pyqtSignal(str)
    finished = pyqtSignal(bool)

    def __init__(self, sector_id: int, worldsectors_dir: str, worlds_generated_dir: str,
                 stride: int = 16):
        super().__init__()
        self.sector_id            = sector_id
        self.worldsectors_dir     = worldsectors_dir
        self.worlds_generated_dir = worlds_generated_dir
        self.stride               = stride

    def run(self):
        sid = self.sector_id
        x, y = sector_xy(sid, self.stride)
        self.log.emit(f"Creating sector {sid}  (X={x}, Y={y})\n")

        # Step 1 — write worldsector XML
        self.log.emit("Step 1 — Writing worldsector XML…")
        ok, msg = create_worldsector_xml(self.worldsectors_dir, sid, self.stride)
        already_exists = "Already exists" in msg
        self.log.emit(f"  {'[OK]' if ok else '[SKIP]' if already_exists else '[FAIL]'}  {msg}")
        if not ok and not already_exists:
            self.finished.emit(False)
            return

        # Step 1a — write landmarkfar XML
        self.log.emit("\nStep 1a — Writing landmarkfar XML…")
        ok, msg = create_landmark_xml(self.worldsectors_dir, sid, "far", self.stride)
        already_exists = "Already exists" in msg
        self.log.emit(f"  {'[OK]' if ok else '[SKIP]' if already_exists else '[FAIL]'}  {msg}")

        # Step 1b — write landmarknear XML
        self.log.emit("\nStep 1b — Writing landmarknear XML…")
        ok, msg = create_landmark_xml(self.worldsectors_dir, sid, "near", self.stride)
        already_exists = "Already exists" in msg
        self.log.emit(f"  {'[OK]' if ok else '[SKIP]' if already_exists else '[FAIL]'}  {msg}")

        # Step 2 — convert worldsector XML → FCB
        self.log.emit("\nStep 2 — Converting worldsector XML → FCB…")
        ok, msg = convert_to_fcb(self.worldsectors_dir, sid)
        self.log.emit(f"  {'[OK]' if ok else '[WARN]'}  {msg}")

        # Step 2a — convert landmarkfar XML → FCB
        self.log.emit("\nStep 2a — Converting landmarkfar XML → FCB…")
        ok, msg = convert_landmark_to_fcb(self.worldsectors_dir, sid, "far")
        self.log.emit(f"  {'[OK]' if ok else '[WARN]'}  {msg}")

        # Step 2b — convert landmarknear XML → FCB
        self.log.emit("\nStep 2b — Converting landmarknear XML → FCB…")
        ok, msg = convert_landmark_to_fcb(self.worldsectors_dir, sid, "near")
        self.log.emit(f"  {'[OK]' if ok else '[WARN]'}  {msg}")

        # Step 2c — ensure sectorN.desc.fcb has a main MissionLayer
        self.log.emit("\nStep 2c — Patching sector desc (main MissionLayer)…")
        ok, msg = patch_sector_desc_main_layer(self.worldsectors_dir, sid)
        self.log.emit(f"  {'[OK]' if ok else '[INFO]'}  {msg}")

        # Step 3 — patch sectorsdep.xml (HasMainSectorData + HasLandmarkNear + HasLandmarkFar)
        self.log.emit("\nStep 3 — Patching sectorsdep.xml…")
        ok, msg = patch_sectorsdep(self.worlds_generated_dir, sid)
        self.log.emit(f"  {'[OK]' if ok else '[FAIL]'}  {msg}")
        if not ok:
            self.finished.emit(False)
            return

        # Step 3b — set isSectorAccessible=True on all sectors
        count, msg = set_all_sectors_accessible(self.worlds_generated_dir)
        self.log.emit(f"  [OK]  {msg}")

        # Step 4 — convert patched sectorsdep.xml back to FCB
        self.log.emit("\nStep 4 — Converting sectorsdep.xml → FCB…")
        ok, msg = convert_sectorsdep_to_fcb(self.worlds_generated_dir)
        self.log.emit(f"  {'[OK]' if ok else '[WARN]'}  {msg}")

        self.log.emit("\nDone.")
        self.finished.emit(True)


class BulkWorker(QThread):
    log      = pyqtSignal(str)
    progress = pyqtSignal(int)   # 0..total
    total    = pyqtSignal(int)   # emitted once at start
    finished = pyqtSignal(str)   # summary message
    created_ids: list[int]       # populated before finished is emitted

    def __init__(self, worldsectors_dir: str, worlds_generated_dir: str,
                 stride: int = 16):
        super().__init__()
        self.worldsectors_dir     = worldsectors_dir
        self.worlds_generated_dir = worlds_generated_dir
        self.stride               = stride
        self.created_ids          = []

    def run(self):
        ws = self.worldsectors_dir
        wg = self.worlds_generated_dir

        # ── Phase 0: scan ───────────────────────────────────────────────────
        self.log.emit("Scanning for missing sectors and landmark files…")
        cell_ids = cell_id_block(ws, self.stride)
        if cell_ids is None:
            # FC2 with an empty folder — the cell's 16x16 block of the 80-wide
            # global grid can't be derived, and iterating all 6400 IDs would
            # dump other cells' sectors into this folder.
            self.finished.emit(
                "Aborted — cannot determine which sector IDs this FC2 cell "
                "folder owns (no existing sector/landmark files to derive the "
                "cell's block from).")
            return
        if self.stride != 16:
            self.log.emit(f"  FC2 cell block: IDs {cell_ids[0]}–{cell_ids[-1]} "
                          f"(16x16 of the {self.stride}-wide global grid)")
        missing, skipped = find_missing_sectors(ws, wg, cell_ids)
        all_missing_lm   = find_missing_landmarks(ws, cell_ids)

        missing_set = set(missing)
        # Sectors that already have a worldsector file but are missing landmarks
        lm_only = [(sid, kinds) for sid, kinds in all_missing_lm if sid not in missing_set]

        if skipped:
            self.log.emit(f"  {len(skipped)} sector(s) have no sectorsdep.xml entry — skipping them")

        if not missing and not all_missing_lm:
            self.finished.emit("Nothing to do — all sectors already have worldsector and landmark files.")
            return

        if missing:
            self.log.emit(f"  Missing worldsector files: {len(missing)}  {missing}")
        if lm_only:
            self.log.emit(f"  Existing sectors missing landmark files: {len(lm_only)}")
        self.log.emit("")
        self.total.emit(len(missing) + len(lm_only))

        # ── Phase 1: write XMLs ─────────────────────────────────────────────
        self.log.emit("Phase 1/3 — Writing XMLs…")
        xml_ok = xml_skip = xml_fail = 0
        progress_counter = 0

        # New sectors: worldsector + both landmark files
        for sid in missing:
            for create_fn, args in [
                (create_worldsector_xml, (ws, sid, self.stride)),
                (create_landmark_xml,    (ws, sid, "far", self.stride)),
                (create_landmark_xml,    (ws, sid, "near", self.stride)),
            ]:
                ok, msg = create_fn(*args)
                if ok:
                    xml_ok += 1
                elif "Already exists" in msg:
                    xml_skip += 1
                else:
                    xml_fail += 1
                    self.log.emit(f"  [FAIL] {msg}")
            progress_counter += 1
            self.progress.emit(progress_counter)

        # Existing sectors: only the missing landmark kind(s)
        for sid, kinds in lm_only:
            for kind in kinds:
                ok, msg = create_landmark_xml(ws, sid, kind, self.stride)
                if ok:
                    xml_ok += 1
                elif "Already exists" in msg:
                    xml_skip += 1
                else:
                    xml_fail += 1
                    self.log.emit(f"  [FAIL] {msg}")
            progress_counter += 1
            self.progress.emit(progress_counter)

        self.log.emit(f"  XMLs written: {xml_ok}  skipped: {xml_skip}  failed: {xml_fail}\n")

        # ── Phase 2: batch FCB conversion (all three file types at once) ────
        self.log.emit("Phase 2/3 — Converting XMLs → FCB (batch)…")
        fcb_ok = fcb_fail = 0

        if not converter_available():
            self.log.emit("  [WARN] No FCB converter available — skipping FCB conversion")
        else:
            # Convert ONLY the XMLs this run wrote. A wildcard batch would also
            # reconvert every pre-existing .converted.xml in the folder (the
            # editor leaves hundreds after loading a level) and litter _new.fcb
            # files the rename loop below never picks up.
            to_convert = []
            for sid in missing:
                to_convert += [
                    os.path.join(ws, f"worldsector{sid}.data.fcb.converted.xml"),
                    os.path.join(ws, _landmark_xml_name(sid, "far")),
                    os.path.join(ws, _landmark_xml_name(sid, "near")),
                ]
            for sid, kinds in lm_only:
                to_convert += [os.path.join(ws, _landmark_xml_name(sid, k)) for k in kinds]
            for path in to_convert:
                if os.path.exists(path):
                    run_fcb_conversion([path, "-fc2"])
            self.log.emit(f"  Converted {len(to_convert)} new XML(s).")

            # Rename _new.fcb → .fcb for newly created sectors (all three files)
            for sid in missing:
                rename_pairs = [
                    (f"worldsector{sid}.data_new.fcb",    f"worldsector{sid}.data.fcb"),
                    (f"landmarkfar_{sid}.data_new.fcb",   f"landmarkfar_{sid}.data.fcb"),
                    (f"landmarknear{sid}.data_new.fcb",   f"landmarknear{sid}.data.fcb"),
                ]
                for new_name, final_name in rename_pairs:
                    new_fcb   = os.path.join(ws, new_name)
                    final_fcb = os.path.join(ws, final_name)
                    if os.path.exists(new_fcb):
                        if os.path.exists(final_fcb):
                            os.remove(final_fcb)
                        os.rename(new_fcb, final_fcb)
                        fcb_ok += 1
                    else:
                        fcb_fail += 1
                        self.log.emit(f"  [SKIP] No new FCB for {new_name} (may already exist)")

            # Rename _new.fcb → .fcb for existing sectors with missing landmarks
            for sid, kinds in lm_only:
                for kind in kinds:
                    if kind == "far":
                        new_name   = f"landmarkfar_{sid}.data_new.fcb"
                        final_name = f"landmarkfar_{sid}.data.fcb"
                    else:
                        new_name   = f"landmarknear{sid}.data_new.fcb"
                        final_name = f"landmarknear{sid}.data.fcb"
                    new_fcb   = os.path.join(ws, new_name)
                    final_fcb = os.path.join(ws, final_name)
                    if os.path.exists(new_fcb):
                        if os.path.exists(final_fcb):
                            os.remove(final_fcb)
                        os.rename(new_fcb, final_fcb)
                        fcb_ok += 1
                    else:
                        fcb_fail += 1
                        self.log.emit(f"  [SKIP] No new FCB for {new_name}")

        self.log.emit(f"  FCB files created: {fcb_ok}  skipped/existing: {fcb_fail}\n")

        # ── Phase 2b: add main MissionLayer to each new sector's desc.fcb ───
        if missing:
            self.log.emit("Phase 2b — Patching sector desc files (main MissionLayer)…")
            desc_patched = 0
            for sid in missing:
                ok, msg = patch_sector_desc_main_layer(ws, sid)
                if ok:
                    desc_patched += 1
                self.log.emit(f"  {'[OK]' if ok else '[INFO]'}  {msg}")
            self.log.emit(f"  Desc files patched: {desc_patched}/{len(missing)}\n")
        else:
            desc_patched = 0

        # ── Phase 3: patch sectorsdep.xml ───────────────────────────────────
        self.log.emit("Phase 3/3 — Patching sectorsdep.xml…")

        # New sectors get all three flags (HasMainSectorData + both landmarks)
        patched = already = 0
        if missing:
            patched, already, err = patch_sectorsdep_bulk(wg, missing)
            if err:
                self.log.emit(f"  [FAIL] {err}")
            else:
                self.log.emit(f"  New sectors — patched: {patched}  already had flags: {already}")

        # Existing sectors get only the landmark flags (no HasMainSectorData)
        lm_patched = lm_already = 0
        if lm_only:
            lm_sids = [sid for sid, _ in lm_only]
            lm_patched, lm_already, err = patch_sectorsdep_landmarks_bulk(wg, lm_sids)
            if err:
                self.log.emit(f"  [FAIL] {err}")
            else:
                self.log.emit(f"  Existing sectors (landmarks only) — patched: {lm_patched}  already had flags: {lm_already}")

        # Set isSectorAccessible=True on all sectors while sectorsdep.xml is open
        count, msg = set_all_sectors_accessible(wg)
        self.log.emit(f"  {msg}")

        self.log.emit("\nConverting sectorsdep.xml → FCB…")
        ok, msg = convert_sectorsdep_to_fcb(wg)
        self.log.emit(f"  {'[OK]' if ok else '[WARN]'}  {msg}")

        # Record which sectors actually got their FCB created
        self.created_ids = [
            sid for sid in missing
            if os.path.exists(os.path.join(ws, f"worldsector{sid}.data.fcb"))
        ]

        summary = (
            f"Done.\n"
            f"  New sectors created         : {len(missing)}\n"
            f"  Existing sectors (lm only)  : {len(lm_only)}\n"
            f"  XMLs written                : {xml_ok}  (failed: {xml_fail})\n"
            f"  FCBs created                : {fcb_ok}  (failed: {fcb_fail})\n"
            f"  Desc main layers added      : {desc_patched}\n"
            f"  sectorsdep new sectors      : {patched} patched  ({already} already had flags)\n"
            f"  sectorsdep lm-only sectors  : {lm_patched} patched  ({lm_already} already had flags)\n"
            f"  isSectorAccessible          : {count} sectors set to True\n"
            f"  sectorsdep FCB              : {'updated' if ok else 'WARN — ' + msg}"
        )
        self.finished.emit(summary)



# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class CreateSectorWindow(QWidget):
    # Emitted with the list of sector IDs that were successfully created
    sectors_created = pyqtSignal(list)

    def __init__(self, worldsectors_dir: str = "", worlds_generated_dir: str = "",
                 game_mode: str = "avatar"):
        super().__init__()
        self.game_mode = game_mode
        self.stride = GRID_STRIDE.get(game_mode, 16)
        title = "Create New Sector" + (" — Far Cry 2" if self.stride != 16 else "")
        self.setWindowTitle(title)
        self.setMinimumWidth(620)
        self._worker = None
        self._build_ui(worldsectors_dir, worlds_generated_dir)
        # Follow the editor's Light/Dark preference (no-op when standalone)
        _apply_editor_theme(self)

    def _build_ui(self, worldsectors_dir: str, worlds_generated_dir: str):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        form = QFormLayout()
        form.setSpacing(6)

        # Sector ID — FC2 sector IDs are GLOBAL on the 80-wide grid (a cell
        # like w1_c_3 owns 2592-2607, 2672-2687, ... — its 16x16 block).
        max_id = self.stride * self.stride - 1
        self.sector_spin = QSpinBox()
        self.sector_spin.setRange(0, max_id)
        # Default to the folder's own block when it can be derived, so the FC2
        # dialog doesn't open on an ID belonging to a different cell.
        block = cell_id_block(worldsectors_dir, self.stride) if worldsectors_dir else None
        self.sector_spin.setValue(block[0] if (block and self.stride != 16) else 34)
        self.sector_spin.valueChanged.connect(self._update_xy_label)
        form.addRow(f"Sector ID (0–{max_id}):", self.sector_spin)

        self.xy_label = QLabel()
        self._update_xy_label()
        form.addRow("Grid position:", self.xy_label)

        root.addLayout(form)

        # Worldsectors folder
        root.addSpacing(4)
        root.addWidget(QLabel("Worldsectors folder  (levels/…/generated/worldsectors):"))
        row1 = QHBoxLayout()
        self.ws_edit = QLineEdit(worldsectors_dir)
        self.ws_edit.setPlaceholderText("Path to …/generated/worldsectors")
        row1.addWidget(self.ws_edit)
        b1 = QPushButton("Browse…")
        b1.setFixedWidth(80)
        b1.clicked.connect(lambda: self._browse(self.ws_edit))
        row1.addWidget(b1)
        root.addLayout(row1)

        # Worlds/generated folder
        root.addWidget(QLabel("Worlds generated folder  (worlds/…/generated):"))
        row2 = QHBoxLayout()
        self.wg_edit = QLineEdit(worlds_generated_dir)
        self.wg_edit.setPlaceholderText("Path to worlds/…/generated")
        row2.addWidget(self.wg_edit)
        b2 = QPushButton("Browse…")
        b2.setFixedWidth(80)
        b2.clicked.connect(lambda: self._browse(self.wg_edit))
        row2.addWidget(b2)
        root.addLayout(row2)

        # FCB converter status — native fcb_convert first, legacy exe fallback.
        # Semantic green/orange, in shades readable on both editor themes.
        if _native_engine() is not None:
            lbl = QLabel("FCB converter: native (fcb_convert)")
            lbl.setStyleSheet("color: #2e7d32;")
        elif os.path.exists(FCB_CONVERTER):
            lbl = QLabel("FCB converter: FCBConverter.exe")
            lbl.setStyleSheet("color: #2e7d32;")
        else:
            lbl = QLabel("FCB converter: NOT found — FCB step will be skipped")
            lbl.setStyleSheet("color: #b45f06;")
        root.addWidget(lbl)

        # Buttons row — create sector
        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Create Sector")
        self.run_btn.setFixedHeight(32)
        self.run_btn.clicked.connect(self._run_single)
        btn_row.addWidget(self.run_btn)

        self.bulk_btn = QPushButton("Create All Missing Sectors")
        self.bulk_btn.setFixedHeight(32)
        self.bulk_btn.clicked.connect(self._run_bulk)
        btn_row.addWidget(self.bulk_btn)
        root.addLayout(btn_row)


        # Progress bar (hidden until bulk run starts)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        # Log
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFont(QFont("Consolas", 9))
        self.log_box.setMinimumHeight(220)
        root.addWidget(self.log_box)

    def _update_xy_label(self):
        sid = self.sector_spin.value()
        x, y = sector_xy(sid, self.stride)
        self.xy_label.setText(f"X={x}, Y={y}  —  world bounds [{x*64}–{(x+1)*64}) × [{y*64}–{(y+1)*64})")

    def _browse(self, line_edit: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "Select folder")
        if path:
            line_edit.setText(path)

    def _validate_paths(self) -> tuple[str, str] | None:
        ws = self.ws_edit.text().strip()
        wg = self.wg_edit.text().strip()
        if not ws or not os.path.isdir(ws):
            self.log_box.appendPlainText("ERROR: Worldsectors folder not found.")
            return None
        if not wg or not os.path.isdir(wg):
            self.log_box.appendPlainText("ERROR: Worlds generated folder not found.")
            return None
        return ws, wg

    def _set_buttons_enabled(self, enabled: bool):
        self.run_btn.setEnabled(enabled)
        self.bulk_btn.setEnabled(enabled)

    def _run_single(self):
        paths = self._validate_paths()
        if paths is None:
            return
        ws, wg = paths
        sid = self.sector_spin.value()
        # FC2: the folder is one cell of the global grid — refuse IDs that
        # belong to a different cell (the files would land in the wrong folder
        # with X/Y the engine never streams there).
        if self.stride != 16:
            block = cell_id_block(ws, self.stride)
            if block is not None and sid not in block:
                self.log_box.appendPlainText(
                    f"ERROR: sector {sid} does not belong to this cell folder "
                    f"(it owns IDs {block[0]}–{block[-1]}, in 16-wide rows).")
                return
        self.log_box.clear()
        self.progress_bar.setVisible(False)
        self._set_buttons_enabled(False)

        self._worker = Worker(sid, ws, wg, stride=self.stride)
        self._worker.log.connect(self.log_box.appendPlainText)
        self._worker.finished.connect(self._on_single_finished)
        self._worker.start()

    def _on_single_finished(self, ok: bool):
        self._set_buttons_enabled(True)
        if ok:
            self.sectors_created.emit([self.sector_spin.value()])

    def _run_bulk(self):
        paths = self._validate_paths()
        if paths is None:
            return
        ws, wg = paths
        self.log_box.clear()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self._set_buttons_enabled(False)

        self._worker = BulkWorker(ws, wg, stride=self.stride)
        self._worker.log.connect(self.log_box.appendPlainText)
        self._worker.total.connect(self._on_bulk_total)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.finished.connect(self._on_bulk_finished)
        self._worker.start()

    def _on_bulk_total(self, n: int):
        self.progress_bar.setRange(0, n)

    def _on_bulk_finished(self, summary: str):
        self.log_box.appendPlainText(summary)
        self._set_buttons_enabled(True)
        if isinstance(self._worker, BulkWorker) and self._worker.created_ids:
            self.sectors_created.emit(self._worker.created_ids)



if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = CreateSectorWindow(
        worldsectors_dir=(
            r"C:\Users\sambe\Desktop\____AVATAR_STUFF"
            r"\__GameFilesPC\TESTING_HG\patch\levels"
            r"\z_dev_orouleau_l\generated\worldsectors"
        ),
        worlds_generated_dir=(
            r"C:\Users\sambe\Desktop\____AVATAR_STUFF"
            r"\__GameFilesPC\TESTING_HG\patch\worlds"
            r"\z_dev_orouleau\generated"
        ),
    )
    win.show()
    sys.exit(app.exec_())
