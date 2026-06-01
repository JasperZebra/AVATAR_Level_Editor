"""
MP Spawn Point Creator
Creates a LeftForDeadTrigger (worldsector) + NPCSpawnPointCollection (mapsdata) pair.
"""

import os
import re
import json
import math
import time
import random
import struct
import copy
import xml.etree.ElementTree as ET

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox,
    QPushButton, QScrollArea, QWidget, QMessageBox, QLineEdit,
    QFrame, QSizePolicy, QListWidget, QListWidgetItem, QDialogButtonBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QCompleter
from PyQt6.QtGui import QFont

from entity_editor import (
    string_to_binhex, int32_to_binhex, int64_to_binhex,
    float_to_binhex, vector3_to_binhex, boolean_to_binhex,
    enum_to_binhex, compute_hash32_to_binhex,
)
from data_models import Entity

# ── Fixed XML fragments (enum option blocks) ─────────────────────────────────

_ENUM_TERRITORY_XML = """<object hash="453BB77B" name="enumSpecificToTerritoryController">
    <object hash="0EBEAE51" name="enum">
      <field hash="DCB67730" name="Value" value-String="Corp" type="BinHex">436F727000</field>
      <field hash="06794001" name="CustomValue" value-Int32="1" type="BinHex">01000000</field>
    </object>
    <object hash="0EBEAE51" name="enum">
      <field hash="DCB67730" name="Value" value-String="Navi" type="BinHex">4E61766900</field>
      <field hash="06794001" name="CustomValue" value-Int32="2" type="BinHex">02000000</field>
    </object>
    <object hash="0EBEAE51" name="enum">
      <field hash="DCB67730" name="Value" value-Int32="7105601" type="BinHex">416C6C00</field>
      <field hash="06794001" name="CustomValue" value-Int32="6" type="BinHex">06000000</field>
    </object>
  </object>"""

_ENUM_COLLISION_XML = """<object hash="90827668" name="enumCollisionShape">
        <object hash="0EBEAE51" name="enum">
          <field hash="DCB67730" name="Value" value-Int32="7892802" type="BinHex">426F7800</field>
        </object>
        <object hash="0EBEAE51" name="enum">
          <field hash="DCB67730" name="Value" value-String="Cylinder" type="BinHex">43796C696E64657200</field>
        </object>
      </object>"""

_ENUM_USABLEBY_XML = """<object hash="40AC22CF" name="enumUsableBy">
        <object hash="0EBEAE51" name="enum">
          <field hash="DCB67730" name="Value" value-String="AIAndPlayer" type="BinHex">4149416E64506C6179657200</field>
        </object>
        <object hash="0EBEAE51" name="enum">
          <field hash="DCB67730" name="Value" value-String="AIOnly" type="BinHex">41494F6E6C7900</field>
        </object>
        <object hash="0EBEAE51" name="enum">
          <field hash="DCB67730" name="Value" value-String="PlayerOnly" type="BinHex">506C617965724F6E6C7900</field>
        </object>
      </object>"""

_ENUM_LOCOMOTION_XML = """<object hash="9FED5361" name="enumLocomotionFilter">
        <object hash="0EBEAE51" name="enum">
          <field hash="DCB67730" name="Value" value-String="NoFilter" type="BinHex">4E6F46696C74657200</field>
        </object>
        <object hash="0EBEAE51" name="enum">
          <field hash="DCB67730" name="Value" value-String="MustBeInVehicle" type="BinHex">4D7573744265496E56656869636C6500</field>
        </object>
        <object hash="0EBEAE51" name="enum">
          <field hash="DCB67730" name="Value" value-String="MustNotBeInVehicle" type="BinHex">4D7573744E6F744265496E56656869636C6500</field>
        </object>
      </object>"""

_ENUM_PERSIST_XML = """<object hash="A2AF95CE" name="enumLevel">
        <object hash="0EBEAE51" name="enum">
          <field hash="DCB67730" name="Value" value-String="None" type="BinHex">4E6F6E6500</field>
        </object>
        <object hash="0EBEAE51" name="enum">
          <field hash="DCB67730" name="Value" value-String="Limited" type="BinHex">4C696D6974656400</field>
        </object>
        <object hash="0EBEAE51" name="enum">
          <field hash="DCB67730" name="Value" value-String="Full" type="BinHex">46756C6C00</field>
        </object>
        <object hash="0EBEAE51" name="enum">
          <field hash="DCB67730" name="Value" value-String="Critical" type="BinHex">437269746963616C00</field>
        </object>
      </object>"""


# ── XML helpers ───────────────────────────────────────────────────────────────

def _el(tag, **attribs):
    e = ET.Element(tag)
    for k, v in attribs.items():
        e.set(k.replace('_', '-'), str(v))
    return e


def _field(hash_, name, binhex, **extras):
    e = _el('field', hash=hash_, name=name, type='BinHex')
    for k, v in extras.items():
        e.set(k.replace('_', '-'), str(v))
    e.text = binhex
    return e


def _obj(hash_, name):
    e = ET.Element('object')
    e.set('hash', hash_)
    e.set('name', name)
    return e


def _append_xml_fragment(parent, xml_str):
    child = ET.fromstring(xml_str)
    parent.append(child)


def _vec3_str(x, y, z):
    def _fmt(v):
        return f"{v:g}" if v == int(v) else str(v)
    return f"{_fmt(x)},{_fmt(y)},{_fmt(z)}"


# ── ID generation ─────────────────────────────────────────────────────────────

def _generate_id(existing_ids):
    base = int(time.time() * 1_000_000)
    for attempt in range(10_000):
        candidate = base + random.randint(1000, 999_999) + attempt
        if candidate > 9_223_372_036_854_775_807:
            candidate = random.randint(10**18, 9 * 10**18)
        if candidate not in existing_ids:
            return candidate
    return max(existing_ids) + 1 if existing_ids else 10**18


def _collect_existing_ids(editor):
    ids = set()
    for entity in getattr(editor, 'entities', []):
        try:
            ids.add(int(entity.id))
        except Exception:
            pass
    return ids


# ── XML builders ──────────────────────────────────────────────────────────────

def _build_spawn_point_xml(entity_id, name, x, y, z, territory_enum, radius=10.0):
    root = _obj('0984415E', 'Entity')

    root.append(_field('B9295CC7', 'hidName',
                        string_to_binhex(name),
                        **{'value-String': name}))
    root.append(_field('052A103F', 'disEntityId',
                        int64_to_binhex(entity_id),
                        **{'value-Id64': str(entity_id)}))
    root.append(_field('D2B3429E', 'text_hidEntityClass',
                        string_to_binhex('CBasicShapeEntity'),
                        **{'value-String': 'CBasicShapeEntity'}))
    # Hash hardcoded from game files — compute_hash32 uses a different algorithm variant
    root.append(_field('1875AE89', 'hidEntityClass',
                        'E6026070',
                        **{'value-ComputeHash32': 'CBasicShapeEntity'}))
    root.append(_field('ADC3BD93', 'hidResourceCount',
                        int32_to_binhex(0),
                        **{'value-Int32': '0'}))

    vec_binhex = vector3_to_binhex(x, y, z)
    vec_str = _vec3_str(x, y, z)
    root.append(_field('32D620A2', 'hidPos', vec_binhex, **{'value-Vector3': vec_str}))
    root.append(_field('6553B60B', 'hidAngles',
                        vector3_to_binhex(0, 0, 0),
                        **{'value-Vector3': '0,0,0'}))
    root.append(_field('00C2DD80', 'hidScale',
                        '0000803F',
                        **{'value-Hash32': '1065353216'}))
    root.append(_field('7D7860C6', 'hidPos_precise', vec_binhex, **{'value-Vector3': vec_str}))

    const = _field('B554978A', 'hidConstEntity', '00')
    root.append(const)

    root.append(_field('DE5F232E', 'selSpecificToTerritoryController',
                        enum_to_binhex(territory_enum),
                        **{'value-Enum': str(territory_enum)}))

    # hidShapePoints — circle of 8 points around centre
    pts = _el('field', hash='4073DD31', name='hidShapePoints')
    n = 8
    for i in range(n):
        angle = 2 * math.pi * i / n
        px = x + radius * math.cos(angle)
        py = y + radius * math.sin(angle)
        pt = ET.SubElement(pts, 'Point')
        pt.text = _vec3_str(px, py, z)
    root.append(pts)

    _append_xml_fragment(root, _ENUM_TERRITORY_XML)

    comps = _obj('A115F62D', 'Components')
    ev = _obj('B3A99CB8', 'CEventComponent')
    ev.append(_obj('3D06591C', 'hidLinks'))
    comps.append(ev)
    root.append(comps)

    return root


def _build_wave_xml(num_spawn, cooldown, archetype, spawn_id, is_persistent):
    wave = _obj('A1B00798', 'HordeWaveInfos')
    wave.append(_field('692092BC', 'NumOfSpawn',
                        int32_to_binhex(num_spawn),
                        **{'value-Int32': str(num_spawn)}))
    wave.append(_field('6B5100F5', 'CoolDownTime',
                        int32_to_binhex(cooldown),
                        **{'value-Int32': str(cooldown)}))
    wave.append(_field('0D1E1AA3', 'archNPCArchetypeName',
                        string_to_binhex(archetype),
                        **{'value-String': archetype}))
    wave.append(_field('BA59DA31', 'entSpawnPoints',
                        int64_to_binhex(spawn_id),
                        **{'value-Id64': str(spawn_id)}))
    wave.append(_field('A52C1BA1', 'isPersistant',
                        boolean_to_binhex(is_persistent),
                        **{'value-Boolean': str(is_persistent)}))
    return wave


def _build_blank_wave_xml():
    """Blank sentinel wave appended after user waves."""
    wave = _obj('A1B00798', 'HordeWaveInfos')
    wave.append(_field('692092BC', 'NumOfSpawn', int32_to_binhex(0), **{'value-Int32': '0'}))
    wave.append(_field('6B5100F5', 'CoolDownTime', int32_to_binhex(0), **{'value-Int32': '0'}))
    wave.append(_field('0D1E1AA3', 'archNPCArchetypeName', string_to_binhex(''), **{'value-String': ''}))
    wave.append(_field('BA59DA31', 'entSpawnPoints', int64_to_binhex(0), **{'value-Id64': '0'}))
    wave.append(_field('A52C1BA1', 'isPersistant', '00', **{'value-Boolean': 'False'}))
    return wave


def _build_trigger_xml(
    entity_id, trigger_idx,
    x, y, z,
    territory_enum,
    vec_x, vec_y, vec_z,
    is_static,
    collision_shape,
    loco_filter,
    npc_level,
    is_last_trigger,
    last_trigger_timer,
    waves,          # list of (num_spawn, cooldown, archetype, spawn_id, is_persistent)
):
    name = f'LeftForDeadTrigger_{trigger_idx}'
    root = _obj('0984415E', 'Entity')

    root.append(_field('B9295CC7', 'hidName', string_to_binhex(name), **{'value-String': name}))
    root.append(_field('052A103F', 'disEntityId', int64_to_binhex(entity_id), **{'value-Id64': str(entity_id)}))
    root.append(_field('D2B3429E', 'text_hidEntityClass', string_to_binhex('CEntity'), **{'value-String': 'CEntity'}))
    root.append(_field('1875AE89', 'hidEntityClass', '60CB79CE', **{'value-ComputeHash32': 'CEntity'}))
    root.append(_field('ADC3BD93', 'hidResourceCount', int32_to_binhex(0), **{'value-Int32': '0'}))

    vec_binhex = vector3_to_binhex(x, y, z)
    vec_str = _vec3_str(x, y, z)
    root.append(_field('32D620A2', 'hidPos', vec_binhex, **{'value-Vector3': vec_str}))
    root.append(_field('6553B60B', 'hidAngles', vector3_to_binhex(0, -0.0, 0), **{'value-Vector3': '0,-0,0'}))
    root.append(_field('00C2DD80', 'hidScale', '0000803F', **{'value-Hash32': '1065353216'}))
    root.append(_field('7D7860C6', 'hidPos_precise', vec_binhex, **{'value-Vector3': vec_str}))
    root.append(_field('B554978A', 'hidConstEntity', '00'))
    root.append(_field('DE5F232E', 'selSpecificToTerritoryController',
                        enum_to_binhex(territory_enum), **{'value-Enum': str(territory_enum)}))
    _append_xml_fragment(root, _ENUM_TERRITORY_XML)

    comps = _obj('A115F62D', 'Components')

    # CTriggerComponent
    trig = _obj('8679517E', 'CTriggerComponent')
    trig.append(_field('80C02825', 'static', boolean_to_binhex(is_static)))
    trig.append(_field('67743E36', 'selCollisionShape',
                        enum_to_binhex(collision_shape), **{'value-Enum': str(collision_shape)}))
    _append_xml_fragment(trig, _ENUM_COLLISION_XML)
    comps.append(trig)

    # CProximityTriggerComponent
    prox = _obj('5458A825', 'CProximityTriggerComponent')
    prox.append(_field('F5C425C9', 'bEnabled', '01', **{'value-Boolean': 'True'}))
    prox.append(_field('446C504A', 'vectorSize',
                        vector3_to_binhex(vec_x, vec_y, vec_z),
                        **{'value-Vector3': _vec3_str(vec_x, vec_y, vec_z)}))
    prox.append(_field('5F2DBFBD', 'bUsable', '00', **{'value-Boolean': 'False'}))
    prox.append(_field('3A885A63', 'bExclusiveUser', '00', **{'value-Boolean': 'False'}))
    prox.append(_field('B5B85233', 'selUsableBy', enum_to_binhex(2), **{'value-Enum': '2'}))
    prox.append(_field('C3D21DEF', 'selLocomotionFilter',
                        enum_to_binhex(loco_filter), **{'value-Enum': str(loco_filter)}))
    prox.append(_field('5CFE93AD', 'sUsageString', '00'))
    _append_xml_fragment(prox, _ENUM_USABLEBY_XML)
    _append_xml_fragment(prox, _ENUM_LOCOMOTION_XML)
    restrictions = _obj('EB53023D', 'UseRestrictions')
    restrictions.append(_field('04FB57A5', 'bLookAtCheck', '01', **{'value-Boolean': 'True'}))
    restrictions.append(_field('25E3CBB1', 'fMaxDifLookAt',
                               float_to_binhex(0.3), **{'value-Float32': '0.3'}))
    restrictions.append(_field('738ACD6D', 'bAngleCheck', '00', **{'value-Boolean': 'False'}))
    prox.append(restrictions)
    comps.append(prox)

    # CPersistComponent (always Critical=3)
    persist = _obj('7273EBB0', 'CPersistComponent')
    persist.append(_field('7C4CF173', 'selLevel', enum_to_binhex(3), **{'value-Enum': '3'}))
    _append_xml_fragment(persist, _ENUM_PERSIST_XML)
    comps.append(persist)

    # CHordeSpawnerComponent
    horde = _obj('B007ADE5', 'CHordeSpawnerComponent')
    horde.append(_field('431FD549', 'm_iNPCLevel', int32_to_binhex(npc_level), **{'value-Int32': str(npc_level)}))
    horde.append(_field('041988E9', 'MapTriggerIndex', int32_to_binhex(trigger_idx), **{'value-Int32': str(trigger_idx)}))
    horde.append(_field('9E3FA893', 'isLastTrigger',
                         boolean_to_binhex(is_last_trigger),
                         **{'value-Boolean': str(is_last_trigger)}))
    horde.append(_field('9C9318B8', 'LastTiggerTimer',
                         int32_to_binhex(last_trigger_timer),
                         **{'value-Int32': str(last_trigger_timer)}))

    entries = _obj('9A871B6A', 'HordeEntries')
    outer_waves = _obj('A1B00798', 'HordeWaveInfos')
    for w in waves:
        outer_waves.append(_build_wave_xml(*w))
    outer_waves.append(_build_blank_wave_xml())
    entries.append(outer_waves)
    horde.append(entries)
    comps.append(horde)

    ev = _obj('B3A99CB8', 'CEventComponent')
    ev.append(_obj('3D06591C', 'hidLinks'))
    comps.append(ev)

    root.append(comps)
    return root


# ── Spawn Point Picker dialog ─────────────────────────────────────────────────

class SpawnPointPickerDialog(QDialog):
    """Create a new spawn point or pick an existing one for a wave."""

    def __init__(self, editor, default_name, default_x, default_y, default_z, default_radius=10.0, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.result_mode = None   # 'new' or 'existing'
        self.result_name = None
        self.result_x = default_x
        self.result_y = default_y
        self.result_z = default_z
        self.result_radius = default_radius
        self.result_entity_id = None  # set when picking existing

        self.setWindowTitle('Configure Spawn Point')
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        # Mode tabs
        from PyQt6.QtWidgets import QTabWidget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # ── Create New tab ───
        new_tab = QWidget()
        new_form = QFormLayout(new_tab)
        self.name_edit = QLineEdit(default_name)
        new_form.addRow('Name:', self.name_edit)
        self.sx = QDoubleSpinBox(); self.sx.setRange(-99999, 99999); self.sx.setDecimals(3); self.sx.setValue(default_x)
        self.sy = QDoubleSpinBox(); self.sy.setRange(-99999, 99999); self.sy.setDecimals(3); self.sy.setValue(default_y)
        self.sz = QDoubleSpinBox(); self.sz.setRange(-99999, 99999); self.sz.setDecimals(3); self.sz.setValue(default_z)
        new_form.addRow('X:', self.sx)
        new_form.addRow('Y:', self.sy)
        new_form.addRow('Z:', self.sz)
        self.radius_spin = QDoubleSpinBox()
        self.radius_spin.setRange(0.5, 9999)
        self.radius_spin.setDecimals(1)
        self.radius_spin.setValue(default_radius)
        self.radius_spin.setSuffix(' units')
        new_form.addRow('Spawn Radius:', self.radius_spin)
        self.tabs.addTab(new_tab, 'Create New')

        # ── Pick Existing tab ───
        pick_tab = QWidget()
        pick_layout = QVBoxLayout(pick_tab)
        pick_layout.addWidget(QLabel('Select existing NPCSpawnPointCollection:'))
        self.sp_list = QListWidget()
        self._populate_existing()
        pick_layout.addWidget(self.sp_list)
        self.tabs.addTab(pick_tab, 'Pick Existing')

        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _populate_existing(self):
        for entity in getattr(self.editor, 'entities', []):
            if 'NPCSpawnPoint' in entity.name:
                item = QListWidgetItem(f'{entity.name}  (ID: {entity.id})')
                item.setData(Qt.ItemDataRole.UserRole, entity)
                self.sp_list.addItem(item)

    def _on_ok(self):
        if self.tabs.currentIndex() == 0:
            name = self.name_edit.text().strip()
            if not name:
                QMessageBox.warning(self, 'Missing Name', 'Enter a spawn point name.')
                return
            self.result_mode = 'new'
            self.result_name = name
            self.result_x = self.sx.value()
            self.result_y = self.sy.value()
            self.result_z = self.sz.value()
            self.result_radius = self.radius_spin.value()
        else:
            item = self.sp_list.currentItem()
            if not item:
                QMessageBox.warning(self, 'No Selection', 'Select an existing spawn point.')
                return
            entity = item.data(Qt.ItemDataRole.UserRole)
            self.result_mode = 'existing'
            self.result_name = entity.name
            self.result_entity_id = int(entity.id)
        self.accept()


# ── Wave row widget ───────────────────────────────────────────────────────────

class WaveRowWidget(QWidget):
    remove_requested = pyqtSignal(object)

    def __init__(self, archetypes, row_num, default_x, default_y, default_z, trigger_idx, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.default_x = default_x
        self.default_y = default_y
        self.default_z = default_z
        self.trigger_idx = trigger_idx
        self._spawn_id = None       # int entity ID once configured
        self._spawn_name = None
        self._spawn_mode = None     # 'new' or 'existing'
        self._spawn_pos = (default_x, default_y, default_z)
        self._spawn_radius = 10.0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        lbl = QLabel(f'#{row_num}')
        lbl.setFixedWidth(24)
        layout.addWidget(lbl)

        self.num_spawn = QSpinBox()
        self.num_spawn.setRange(0, 9999)
        self.num_spawn.setValue(0)
        self.num_spawn.setFixedWidth(60)
        layout.addWidget(QLabel('Spawn:'))
        layout.addWidget(self.num_spawn)

        self.cooldown = QSpinBox()
        self.cooldown.setRange(0, 9999)
        self.cooldown.setValue(0)
        self.cooldown.setFixedWidth(60)
        layout.addWidget(QLabel('Cooldown:'))
        layout.addWidget(self.cooldown)

        self.arch_combo = QComboBox()
        self.arch_combo.setEditable(True)
        self.arch_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.arch_combo.addItems(archetypes)
        completer = QCompleter(archetypes)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.arch_combo.setCompleter(completer)
        self.arch_combo.setCurrentText('')
        self.arch_combo.setMinimumWidth(260)
        layout.addWidget(QLabel('Archetype:'))
        layout.addWidget(self.arch_combo)

        self.persist_cb = QCheckBox('Persistent')
        layout.addWidget(self.persist_cb)

        self.sp_btn = QPushButton('Set Spawn Point...')
        self.sp_btn.setFixedWidth(140)
        self.sp_btn.clicked.connect(self._pick_spawn_point)
        layout.addWidget(self.sp_btn)

        rm_btn = QPushButton('✕')
        rm_btn.setFixedWidth(28)
        rm_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(rm_btn)

    def _pick_spawn_point(self):
        default_name = f'NPCSpawnPointCollection_{self.trigger_idx}'
        dlg = SpawnPointPickerDialog(
            self.editor, default_name,
            self.default_x, self.default_y, self.default_z,
            parent=self
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._spawn_mode = dlg.result_mode
            self._spawn_name = dlg.result_name
            if dlg.result_mode == 'existing':
                self._spawn_id = dlg.result_entity_id
                self._spawn_pos = None
                self._spawn_radius = 10.0
            else:
                self._spawn_id = None  # generated later
                self._spawn_pos = (dlg.result_x, dlg.result_y, dlg.result_z)
                self._spawn_radius = dlg.result_radius
            self.sp_btn.setText(f'✓ {self._spawn_name}')
            self.sp_btn.setStyleSheet('color: #4c4;')

    def get_data(self):
        return {
            'num_spawn': self.num_spawn.value(),
            'cooldown': self.cooldown.value(),
            'archetype': self.arch_combo.currentText().strip(),
            'persistent': self.persist_cb.isChecked(),
            'spawn_mode': self._spawn_mode,
            'spawn_name': self._spawn_name,
            'spawn_id': self._spawn_id,
            'spawn_pos': self._spawn_pos,
            'spawn_radius': self._spawn_radius,
        }

    def validate(self):
        d = self.get_data()
        if not d['archetype']:
            return 'Select an archetype.'
        if d['spawn_mode'] is None:
            return 'Configure the spawn point (click "Set Spawn Point...").'
        return None


# ── Main dialog ───────────────────────────────────────────────────────────────

class MPSpawnCreatorDialog(QDialog):

    def __init__(self, editor, right_click_x, right_click_y, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.right_click_x = right_click_x
        self.right_click_y = right_click_y
        self._wave_rows = []

        self.setWindowTitle('Create MP Spawn Point')
        self.setMinimumWidth(900)
        self.setMinimumHeight(540)

        self._archetypes = self._load_archetypes()
        self._next_idx = self._auto_detect_next_index()
        self._ws_paths = self._load_worldsector_paths()

        root_layout = QVBoxLayout(self)
        root_layout.addWidget(self._build_trigger_section())

        waves_group = QGroupBox('Wave Entries (HordeWaveInfos)')
        waves_vbox = QVBoxLayout(waves_group)

        self._waves_container = QWidget()
        self._waves_vbox = QVBoxLayout(self._waves_container)
        self._waves_vbox.setSpacing(2)
        self._waves_vbox.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidget(self._waves_container)
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(180)
        waves_vbox.addWidget(scroll)

        add_btn = QPushButton('+ Add Wave')
        add_btn.clicked.connect(self._add_wave)
        waves_vbox.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        root_layout.addWidget(waves_group)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText('Create')
        btns.accepted.connect(self._on_create)
        btns.rejected.connect(self.reject)
        root_layout.addWidget(btns)

        # Start with one blank wave
        self._add_wave()

    # ── section builders ──────────────────────────────────────────────────────

    def _build_trigger_section(self):
        group = QGroupBox('Trigger Settings')
        form = QFormLayout(group)

        # Position
        pos_row = QHBoxLayout()
        self.pos_x = QDoubleSpinBox(); self.pos_x.setRange(-99999, 99999); self.pos_x.setDecimals(3)
        self.pos_y = QDoubleSpinBox(); self.pos_y.setRange(-99999, 99999); self.pos_y.setDecimals(3)
        self.pos_z = QDoubleSpinBox(); self.pos_z.setRange(-99999, 99999); self.pos_z.setDecimals(3)
        self.pos_x.setValue(self.right_click_x)
        self.pos_y.setValue(self.right_click_y)
        self.pos_z.setValue(0.0)
        for lbl, w in [('X:', self.pos_x), ('Y:', self.pos_y), ('Z:', self.pos_z)]:
            pos_row.addWidget(QLabel(lbl)); pos_row.addWidget(w)
        form.addRow('Position:', pos_row)

        # Worldsector
        self.ws_combo = QComboBox()
        if self._ws_paths:
            for p in self._ws_paths:
                self.ws_combo.addItem(os.path.basename(p), p)
            self._try_auto_select_sector()
        else:
            self.ws_combo.addItem('(no worldsectors loaded)')
        form.addRow('Target Sector:', self.ws_combo)

        # Territory
        self.territory_combo = QComboBox()
        self.territory_combo.addItem('All (6)', 6)
        self.territory_combo.addItem('Corp (1)', 1)
        self.territory_combo.addItem('Navi (2)', 2)
        form.addRow('Territory:', self.territory_combo)

        # Trigger box size
        vec_row = QHBoxLayout()
        self.vec_x = QDoubleSpinBox(); self.vec_x.setRange(0, 9999); self.vec_x.setDecimals(1); self.vec_x.setValue(5)
        self.vec_y = QDoubleSpinBox(); self.vec_y.setRange(0, 9999); self.vec_y.setDecimals(1); self.vec_y.setValue(35)
        self.vec_z = QDoubleSpinBox(); self.vec_z.setRange(0, 9999); self.vec_z.setDecimals(1); self.vec_z.setValue(5)
        for lbl, w in [('X:', self.vec_x), ('Y:', self.vec_y), ('Z:', self.vec_z)]:
            vec_row.addWidget(QLabel(lbl)); vec_row.addWidget(w)
        form.addRow('Trigger Box Size:', vec_row)

        # Static + Collision shape
        sc_row = QHBoxLayout()
        self.static_cb = QCheckBox('Static')
        self.collision_combo = QComboBox()
        self.collision_combo.addItem('Box (0)', 0)
        self.collision_combo.addItem('Cylinder (1)', 1)
        sc_row.addWidget(self.static_cb)
        sc_row.addSpacing(16)
        sc_row.addWidget(QLabel('Collision Shape:'))
        sc_row.addWidget(self.collision_combo)
        sc_row.addStretch()
        form.addRow('', sc_row)

        # Locomotion filter
        self.loco_combo = QComboBox()
        self.loco_combo.addItem('NoFilter (0)', 0)
        self.loco_combo.addItem('MustNotBeInVehicle (2)', 2)
        form.addRow('Locomotion Filter:', self.loco_combo)

        # NPC level + trigger index
        li_row = QHBoxLayout()
        self.npc_level = QSpinBox(); self.npc_level.setRange(0, 999); self.npc_level.setValue(13)
        self.trigger_idx = QSpinBox(); self.trigger_idx.setRange(0, 9999); self.trigger_idx.setValue(self._next_idx)
        li_row.addWidget(QLabel('NPC Level:')); li_row.addWidget(self.npc_level)
        li_row.addSpacing(16)
        li_row.addWidget(QLabel('Trigger Index:')); li_row.addWidget(self.trigger_idx)
        li_row.addStretch()
        form.addRow('', li_row)

        # Is Last Trigger + timer
        lt_row = QHBoxLayout()
        self.is_last_cb = QCheckBox('Is Last Trigger')
        self.last_timer = QSpinBox(); self.last_timer.setRange(0, 9999); self.last_timer.setValue(0)
        self.last_timer.setEnabled(False)
        self.is_last_cb.toggled.connect(self.last_timer.setEnabled)
        lt_row.addWidget(self.is_last_cb)
        lt_row.addSpacing(16)
        lt_row.addWidget(QLabel('Last Trigger Timer:'))
        lt_row.addWidget(self.last_timer)
        lt_row.addStretch()
        form.addRow('', lt_row)

        return group

    # ── helpers ───────────────────────────────────────────────────────────────

    def _load_archetypes(self):
        json_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'entities', 'archetype_names.json'
        )
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []

    def _auto_detect_next_index(self):
        max_idx = -1
        for entity in getattr(self.editor, 'entities', []):
            m = re.match(r'LeftForDeadTrigger_(\d+)', entity.name)
            if m:
                max_idx = max(max_idx, int(m.group(1)))
        # Also scan worldsector trees in case trigger isn't in entities list
        for tree in getattr(self.editor, 'worldsectors_trees', {}).values():
            for field in tree.getroot().iter('field'):
                if field.get('name') == 'MapTriggerIndex':
                    try:
                        max_idx = max(max_idx, int(field.get('value-Int32', -1)))
                    except Exception:
                        pass
        return max_idx + 1

    def _load_worldsector_paths(self):
        trees = getattr(self.editor, 'worldsectors_trees', {})
        return sorted(
            [p for p in trees.keys() if 'worldsector' in os.path.basename(p).lower()],
            key=lambda p: self._ws_sort_key(os.path.basename(p))
        )

    def _ws_sort_key(self, basename):
        m = re.search(r'(\d+)', basename)
        return int(m.group(1)) if m else 0

    def _try_auto_select_sector(self):
        """Pre-select the worldsector whose existing entity positions best contain the click."""
        x, y = self.right_click_x, self.right_click_y
        best_idx = 0
        best_dist = float('inf')
        for i, ws_path in enumerate(self._ws_paths):
            tree = self.editor.worldsectors_trees.get(ws_path)
            if not tree:
                continue
            positions = []
            for field in tree.getroot().iter('field'):
                if field.get('name') == 'hidPos':
                    v = field.get('value-Vector3', '')
                    parts = v.split(',')
                    if len(parts) >= 2:
                        try:
                            positions.append((float(parts[0]), float(parts[1])))
                        except ValueError:
                            pass
            if not positions:
                continue
            cx = sum(p[0] for p in positions) / len(positions)
            cy = sum(p[1] for p in positions) / len(positions)
            dist = (cx - x) ** 2 + (cy - y) ** 2
            if dist < best_dist:
                best_dist = dist
                best_idx = i
        self.ws_combo.setCurrentIndex(best_idx)

    def _add_wave(self):
        row_num = len(self._wave_rows) + 1
        row = WaveRowWidget(
            self._archetypes, row_num,
            self.right_click_x, self.right_click_y, 0.0,
            self.trigger_idx.value(),
            self.editor,
            parent=self._waves_container
        )
        row.remove_requested.connect(self._remove_wave)
        self._waves_vbox.addWidget(row)
        self._wave_rows.append(row)

    def _remove_wave(self, row):
        if row in self._wave_rows:
            self._wave_rows.remove(row)
            row.setParent(None)
            row.deleteLater()

    # ── creation logic ────────────────────────────────────────────────────────

    def _on_create(self):
        if not self._wave_rows:
            QMessageBox.warning(self, 'No Waves', 'Add at least one wave entry.')
            return
        for i, row in enumerate(self._wave_rows):
            err = row.validate()
            if err:
                QMessageBox.warning(self, f'Wave {i+1}', err)
                return

        ws_path = self.ws_combo.currentData()
        if not ws_path:
            QMessageBox.warning(self, 'No Sector', 'No worldsector selected.')
            return

        existing_ids = _collect_existing_ids(self.editor)
        territory = self.territory_combo.currentData()
        trigger_idx = self.trigger_idx.value()

        # 1. Resolve spawn point IDs — create new ones or reuse existing
        wave_data_list = []
        created_sp_entities = []

        for row in self._wave_rows:
            d = row.get_data()
            if d['spawn_mode'] == 'existing':
                spawn_id = d['spawn_id']
            else:
                # Create spawn point entity
                sp_id = _generate_id(existing_ids)
                existing_ids.add(sp_id)
                sp_name = d['spawn_name']
                sx, sy, sz = d['spawn_pos']
                sp_radius = d['spawn_radius']
                sp_xml = _build_spawn_point_xml(sp_id, sp_name, sx, sy, sz, territory, radius=sp_radius)
                created_sp_entities.append((sp_id, sp_name, sx, sy, sz, sp_xml))
                spawn_id = sp_id
            wave_data_list.append((
                d['num_spawn'], d['cooldown'], d['archetype'], spawn_id, d['persistent']
            ))

        # 2. Generate trigger ID
        trigger_id = _generate_id(existing_ids)
        existing_ids.add(trigger_id)

        # 3. Build trigger XML
        trigger_xml = _build_trigger_xml(
            entity_id=trigger_id,
            trigger_idx=trigger_idx,
            x=self.pos_x.value(), y=self.pos_y.value(), z=self.pos_z.value(),
            territory_enum=territory,
            vec_x=self.vec_x.value(), vec_y=self.vec_y.value(), vec_z=self.vec_z.value(),
            is_static=self.static_cb.isChecked(),
            collision_shape=self.collision_combo.currentData(),
            loco_filter=self.loco_combo.currentData(),
            npc_level=self.npc_level.value(),
            is_last_trigger=self.is_last_cb.isChecked(),
            last_trigger_timer=self.last_timer.value(),
            waves=wave_data_list,
        )

        errors = []

        # 4. Insert spawn point(s) into mapsdata
        for sp_id, sp_name, sx, sy, sz, sp_xml in created_sp_entities:
            ok, entity = self._insert_into_mapsdata(sp_xml, sp_id, sp_name, sx, sy, sz)
            if ok:
                self.editor.entities.append(entity)
            else:
                errors.append(f'Failed to insert spawn point {sp_name}')

        # 5. Insert trigger into worldsector
        ok = self._insert_into_worldsector(trigger_xml, ws_path)
        if ok:
            t_entity = Entity(
                id=str(trigger_id),
                name=f'LeftForDeadTrigger_{trigger_idx}',
                x=self.pos_x.value(),
                y=self.pos_y.value(),
                z=self.pos_z.value(),
                xml_element=trigger_xml,
            )
            t_entity.source_file = 'worldsector'
            t_entity.source_file_path = ws_path
            self.editor.entities.append(t_entity)
        else:
            errors.append(f'Failed to insert trigger into {os.path.basename(ws_path)}')

        if errors:
            QMessageBox.warning(self, 'Partial Failure', '\n'.join(errors))
        else:
            QMessageBox.information(
                self, 'Done',
                f'Created LeftForDeadTrigger_{trigger_idx} '
                f'with {len(wave_data_list)} wave(s) and {len(created_sp_entities)} new spawn point(s).\n'
                f'Save the level to convert to FCB.'
            )

        # Refresh canvas
        if hasattr(self.editor, 'canvas') and self.editor.canvas:
            self.editor.canvas.invalidate_position_cache()
            self.editor.canvas.update()

        self.accept()

    def _insert_into_mapsdata(self, entity_xml, entity_id, name, x, y, z):
        try:
            xml_tree = getattr(self.editor, 'xml_tree', None)
            xml_path = getattr(self.editor, 'xml_file_path', None)
            if xml_tree is None:
                return False, None

            root = xml_tree.getroot()
            container = None
            for existing in root.findall(".//object[@name='Entity']"):
                for candidate in root.iter():
                    if existing in list(candidate):
                        container = candidate
                        break
                if container is not None:
                    break
            if container is None:
                container = root

            xml_str = ET.tostring(entity_xml, encoding='unicode')
            entity_copy = ET.fromstring(xml_str)
            container.append(entity_copy)

            try:
                ET.indent(xml_tree, space='  ')
            except AttributeError:
                pass

            if xml_path:
                xml_tree.write(xml_path, encoding='utf-8', xml_declaration=True)

            self.editor.xml_tree_modified = True

            entity = Entity(id=str(entity_id), name=name, x=x, y=y, z=z, xml_element=entity_copy)
            entity.source_file = 'mapsdata'
            entity.source_file_path = xml_path
            return True, entity

        except Exception as e:
            print(f'[MPSpawnCreator] mapsdata insert error: {e}')
            import traceback; traceback.print_exc()
            return False, None

    def _insert_into_worldsector(self, trigger_xml, ws_path):
        try:
            trees = getattr(self.editor, 'worldsectors_trees', {})
            if ws_path not in trees:
                if os.path.exists(ws_path):
                    trees[ws_path] = ET.parse(ws_path)
                else:
                    return False

            tree = trees[ws_path]
            root = tree.getroot()

            mission_layers = root.findall(".//object[@name='MissionLayer']")
            if not mission_layers:
                # Create a basic 'main' MissionLayer
                from canvas.mp_spawn_creator import _obj, _field, int32_to_binhex
                ml = ET.SubElement(root, 'object')
                ml.set('hash', 'D1C1D3C2')
                ml.set('name', 'MissionLayer')
                mission_layers = [ml]

            mission_layer = mission_layers[0]

            xml_str = ET.tostring(trigger_xml, encoding='unicode')
            trigger_copy = ET.fromstring(xml_str)
            mission_layer.append(trigger_copy)

            try:
                ET.indent(tree, space='  ')
            except AttributeError:
                pass

            tree.write(ws_path, encoding='utf-8', xml_declaration=True)

            if not hasattr(self.editor, 'worldsectors_modified'):
                self.editor.worldsectors_modified = {}
            self.editor.worldsectors_modified[ws_path] = True

            return True

        except Exception as e:
            print(f'[MPSpawnCreator] worldsector insert error: {e}')
            import traceback; traceback.print_exc()
            return False
