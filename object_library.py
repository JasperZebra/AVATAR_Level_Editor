"""
object_library.py — Object Library: drop a brand-new entity into the loaded level
by referencing an archetype that already lives in the level's entitylibrary
(loaded via ``archetype_library``).

Nothing is imported/copied — the game merges the full archetype at runtime — so
"placing" an object just writes the **minimal instance entity** into the correct
worldsector ``MissionLayer``. The minimal shape (smallest real one found in the
game's worldsectors) is:

    <object name="Entity">
      <field name="tplCreatureType" .../>   ← the archetype LINK (= archetype's inner Entity/hidName)
      <field name="hidName" .../>           ← new instance name
      <field name="disEntityId" .../>       ← new unique id
      <field name="hidPos" .../>            ← position
      <field name="hidAngles" .../>         ← rotation
      <field name="hidPos_precise" .../>
      <object name="Components">
        <object name="CEventComponent"><object name="hidLinks"/></object>
      </object>
    </object>

v1 places at the current view centre; the user then drags it with the gizmo.
A cursor-ghost / click-to-place mode can layer on top later.
"""

import xml.etree.ElementTree as ET

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QListWidget, QLabel, QPushButton,
)

from entity_editor import string_to_binhex, int64_to_binhex, vector3_to_binhex
from canvas.mp_spawn_creator import _generate_id, _collect_existing_ids


# Field/object hashes — taken verbatim from a real minimal placed worldsector entity.
_H_ENTITY      = '0984415E'
_H_TPL         = '346AAB33'
_H_HIDNAME     = 'B9295CC7'
_H_ID          = '052A103F'
_H_POS         = '32D620A2'
_H_ANGLES      = '6553B60B'
_H_POS_PRECISE = '7D7860C6'
_H_COMPONENTS  = 'A115F62D'
_H_EVENTCOMP   = 'B3A99CB8'
_H_HIDLINKS    = '3D06591C'


# --------------------------------------------------------------------------- #
# XML builders
# --------------------------------------------------------------------------- #

def _obj(hash_, name):
    e = ET.Element('object')
    e.set('hash', hash_)
    e.set('name', name)
    return e


def _field(hash_, name, binhex, **value_attrs):
    e = ET.Element('field')
    e.set('hash', hash_)
    e.set('name', name)
    e.set('type', 'BinHex')
    for k, v in value_attrs.items():
        e.set(k.replace('_', '-'), str(v))
    e.text = binhex
    return e


def _v3s(x, y, z):
    return f"{x},{y},{z}"


def build_minimal_entity(tpl_creature_type, hid_name, entity_id, x, y, z,
                         angles=(0.0, 0.0, 0.0)):
    """Build the minimal placed-entity XML element that references an archetype."""
    e = _obj(_H_ENTITY, 'Entity')
    e.append(_field(_H_TPL, 'tplCreatureType',
                    string_to_binhex(tpl_creature_type),
                    **{'value-String': tpl_creature_type}))
    e.append(_field(_H_HIDNAME, 'hidName',
                    string_to_binhex(hid_name),
                    **{'value-String': hid_name}))
    e.append(_field(_H_ID, 'disEntityId',
                    int64_to_binhex(entity_id),
                    **{'value-Id64': str(entity_id)}))
    e.append(_field(_H_POS, 'hidPos',
                    vector3_to_binhex(x, y, z),
                    **{'value-Vector3': _v3s(x, y, z)}))
    ax, ay, az = angles
    e.append(_field(_H_ANGLES, 'hidAngles',
                    vector3_to_binhex(ax, ay, az),
                    **{'value-Vector3': _v3s(ax, ay, az)}))
    e.append(_field(_H_POS_PRECISE, 'hidPos_precise',
                    vector3_to_binhex(x, y, z),
                    **{'value-Vector3': _v3s(x, y, z)}))
    comps = _obj(_H_COMPONENTS, 'Components')
    ev = _obj(_H_EVENTCOMP, 'CEventComponent')
    ev.append(_obj(_H_HIDLINKS, 'hidLinks'))
    comps.append(ev)
    e.append(comps)
    return e


# --------------------------------------------------------------------------- #
# Placement helpers
# --------------------------------------------------------------------------- #

def _status(editor, msg):
    try:
        editor.statusBar().showMessage(msg, 8000)
    except Exception:
        pass
    print(f"[ObjectLibrary] {msg}")


def _viewport_center(canvas):
    try:
        return canvas.screen_to_world(canvas.width() / 2, canvas.height() / 2)
    except Exception:
        return (0.0, 0.0)


def _terrain_z(canvas, x, y):
    try:
        h = canvas.get_terrain_height_at(x, y)
        if h is not None:
            return float(h)
    except Exception:
        pass
    return 0.0


def _is_worldsector_path(path):
    import os
    return os.path.basename(path).lower().startswith('worldsector')


def _sector_id_of(root):
    idf = root.find("field[@name='Id']")
    if idf is None:
        idf = root.find(".//field[@name='Id']")
    if idf is not None:
        try:
            return int(idf.get('value-Int32'))
        except (TypeError, ValueError):
            pass
    return None


def _find_sector(editor, sid):
    """Return {'sid', 'path', 'root', 'tree'} for the worldsector with Id==sid, or None."""
    for path, tree in getattr(editor, 'worldsectors_trees', {}).items():
        if not _is_worldsector_path(path):
            continue
        root = tree.getroot()
        if _sector_id_of(root) == sid:
            return {'sid': sid, 'path': path, 'root': root, 'tree': tree}
    return None


def _any_sector(editor):
    for path, tree in getattr(editor, 'worldsectors_trees', {}).items():
        if not _is_worldsector_path(path):
            continue
        root = tree.getroot()
        s = _sector_id_of(root)
        if s is not None:
            return {'sid': s, 'path': path, 'root': root, 'tree': tree}
    return None


def _pick_layer(root):
    """Pick a MissionLayer to place into — prefer 'main', else the first. Returns
    (layer_element, layer_name) or (None, 'main')."""
    layers = root.findall(".//object[@name='MissionLayer']")
    for ml in layers:
        pid = ml.find("field[@name='text_PathId']")
        if pid is not None and (pid.get('value-String') or '') == 'main':
            return ml, 'main'
    if layers:
        ml = layers[0]
        pid = ml.find("field[@name='text_PathId']")
        return ml, ((pid.get('value-String') if pid is not None else 'main') or 'main')
    return None, 'main'


def _unique_name(editor, base):
    existing = {getattr(e, 'name', '') for e in getattr(editor, 'entities', [])}
    n = 1
    while f"{base}_{n}" in existing:
        n += 1
    return f"{base}_{n}"


def _archetype_tpl(arch_root, fallback):
    """tplCreatureType to write = the archetype's inner Entity/hidName."""
    if arch_root is not None:
        ent = arch_root.find("object[@name='Entity']")
        if ent is None:
            ent = arch_root.find(".//object[@name='Entity']")
        if ent is not None:
            hidf = ent.find("field[@name='hidName']")
            if hidf is not None:
                v = (hidf.get('value-String') or '').strip()
                if v:
                    return v
    return fallback


# --------------------------------------------------------------------------- #
# Public placement entry point
# --------------------------------------------------------------------------- #

def place_archetype(editor, proto_name, world_pos=None):
    """Create + insert a minimal instance of ``proto_name`` into the loaded level.

    Returns the new ``Entity`` (and selects it) or None on failure (a status-bar
    message explains why). Placement target = the worldsector the position falls
    in (else the first loaded sector), 'main' layer if present.
    """
    from archetype_library import get_library
    from data_models import Entity

    canvas = getattr(editor, 'canvas', None)
    if canvas is None or getattr(editor, 'entities', None) is None:
        _status(editor, "Load a level before placing objects")
        return None

    arch = get_library().get_prototype_element(proto_name)
    if arch is None:
        _status(editor, f"'{proto_name}' is not in this level's entity library")
        return None
    tpl = _archetype_tpl(arch, proto_name)

    if world_pos is None:
        world_pos = _viewport_center(canvas)
    wx, wy = float(world_pos[0]), float(world_pos[1])
    wz = _terrain_z(canvas, wx, wy)

    sid = int(wy // 64) * 16 + int(wx // 64)
    target = _find_sector(editor, sid)
    if target is None:
        target = _any_sector(editor)
        if target is None:
            _status(editor, "No worldsector is loaded to place this object into")
            return None
        sid = target['sid']
    ml_elem, layer_name = _pick_layer(target['root'])
    if ml_elem is None:
        _status(editor, f"Sector {sid} has no MissionLayer to place into")
        return None

    new_id = _generate_id(_collect_existing_ids(editor))
    hid_name = _unique_name(editor, proto_name)
    ent_xml = build_minimal_entity(tpl, hid_name, new_id, wx, wy, wz)
    ml_elem.append(ent_xml)        # in-memory insert (unified save rebuilds from entities)

    ent = Entity(id=str(new_id), name=hid_name, x=wx, y=wy, z=wz,
                 xml_element=ent_xml, entity_type='Entity',
                 source_file='worldsectors', source_sector_id=sid,
                 source_layer=layer_name)
    ent.source_file_path = target['path']
    editor.entities.append(ent)

    if hasattr(canvas, 'dirty_sectors'):
        canvas.dirty_sectors.add(sid)

    try:
        from canvas.undo_redo import AddEntityCommand
        if hasattr(canvas, 'undo_redo'):
            canvas.undo_redo.push(AddEntityCommand(ent, sid, ml_elem))
    except Exception as exc:
        print(f"[ObjectLibrary] undo push failed: {exc}")

    if hasattr(canvas, 'invalidate_position_cache'):
        canvas.invalidate_position_cache()
    if hasattr(editor, 'update_entity_tree'):
        try:
            editor.update_entity_tree()
        except Exception:
            pass
    try:
        canvas.selected_entity = ent
        if hasattr(canvas, 'selected'):
            canvas.selected = [ent]
        if hasattr(editor, 'on_entity_selected'):
            editor.on_entity_selected(ent)
    except Exception:
        pass
    canvas.update()

    _status(editor, f"Placed {hid_name} in sector {sid} ({layer_name}) — "
                    f"drag to position, Ctrl+S to save")
    return ent


# --------------------------------------------------------------------------- #
# Palette dialog
# --------------------------------------------------------------------------- #

class ObjectLibraryDialog(QDialog):
    """Lists the loaded level's archetypes; double-click / Place drops one at the
    view centre. Non-modal so the user can keep working."""

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setWindowTitle("Object Library")
        self.resize(360, 560)

        v = QVBoxLayout(self)
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter archetypes…")
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(self._apply_filter)
        v.addWidget(self._filter)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _i: self._place())
        v.addWidget(self._list, 1)

        self._info = QLabel("Pick an archetype, then Place (or double-click). "
                            "It drops at the view centre — drag it where you want.")
        self._info.setWordWrap(True)
        self._info.setStyleSheet("color:#888; font-size:10px;")
        v.addWidget(self._info)

        self._place_btn = QPushButton("Place at View Center")
        self._place_btn.clicked.connect(self._place)
        v.addWidget(self._place_btn)

        self._all = []
        self._populate()

    def _populate(self):
        from archetype_library import get_library
        self._all = sorted(get_library().all_names())
        self._apply_filter(self._filter.text())
        if not self._all:
            self._info.setText("No entity library is loaded for this level — "
                               "archetypes are unavailable. (The level's patch "
                               "folder needs entitylibrary.fcb.)")

    def _apply_filter(self, text):
        text = (text or '').lower()
        self._list.clear()
        for name in self._all:
            if text in name.lower():
                self._list.addItem(name)

    def _place(self):
        item = self._list.currentItem()
        if item is None:
            self._info.setText("Select an archetype in the list first.")
            return
        ent = place_archetype(self.editor, item.text())
        if ent is not None:
            self._info.setText(f"Placed {ent.name}. Drag it into position, "
                               f"then Save Level. Place more or close.")


def open_object_library(editor):
    """Open (or re-focus) the Object Library palette for the editor."""
    existing = getattr(editor, '_object_library_dialog', None)
    if existing is not None:
        try:
            existing._populate()      # refresh list for the current level
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return existing
        except Exception:
            pass
    dlg = ObjectLibraryDialog(editor)
    editor._object_library_dialog = dlg
    dlg.show()
    return dlg
