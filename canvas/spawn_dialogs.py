"""
spawn_dialogs.py — Creature Spawn Point and War Battle creators.

Two one-click generators built on ``canvas/spawn_builder.py``:

* **Creature Spawn Point** — drops an ``AvatarNPCSpawnPoint`` (+ its roam area)
  for any wildlife archetype.
* **War Battle** — drops a complete two-sided endless fight: two spawn areas,
  two converging ``BtzOmniTagPoint`` rush markers, and N spawners per side.

Both are AVATAR ONLY (see the Rule 8 note in ``spawn_builder``); callers must
gate on ``game_mode``.

Everything is written into the loaded level's IN-MEMORY trees — mapsdata via
``editor.xml_tree``, omnis via ``editor.omnis_tree``.  Save Level then picks the
change up through the existing hash-gated dirty detection, so nothing here
touches the disk.
"""

import os
import traceback
import xml.etree.ElementTree as ET

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QLabel,
    QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox, QPushButton, QLineEdit,
    QMessageBox, QDialogButtonBox, QWidget, QCompleter, QScrollArea,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from data_models import Entity
from theme_settings import apply_dialog_theme

from canvas import spawn_builder as SB
from canvas.spawn_builder import (
    TERRITORY_CORP, TERRITORY_NAVI, TERRITORY_ALL,
    plan_creature_spawn, plan_war_battle, DEFAULT_TAG_GAP,
)

# ── Curated fallbacks, taken from real Avatar levels ─────────────────────────
# Used when the level's entitylibrary has not loaded (archetype-driven UI is
# empty by design in that case — see AGENTS.md "Archetype library").

FALLBACK_CREATURES = [
    'Animals.Avatar.Viperwolf',
    'Animals.Avatar.Viperwolf.BlackViperwolf',
    'Animals.Avatar.Viperwolf.Galactonotus',
    'Animals.Avatar.Viperwolf.NoLoot.WaveAttack',
    'Animals.Avatar.Hexapede',
    'Animals.Avatar.Hexapede.Hexapede_Prey',
    'Animals.Avatar.Direhorse.Direhorse_MapNavi',
    'Animals.Avatar.Direhorse.Direhorse_MapCorp',
    'Animals.Avatar.Sturmbeest.Sturmbeest_Sick',
    'Animals.Avatar.Tapirus.Female',
]

# WarZone_2.0's actual loadout — the "Corp vs Na'vi, mixed infantry" preset.
PRESET_CORP = {
    'label': 'Corp',
    'territory': TERRITORY_CORP,
    'archetype': 'enemy_archetypes.Avatar.Corporation1.Female.Soldier.Grenade Launcher',
    'extra_archetypes': [
        'enemy_archetypes.Avatar.Corporation1.Female.Soldier.Assault Rifle',
        'enemy_archetypes.Avatar.Corporation1.Male.Soldier.M60',
        'enemy_archetypes.Avatar.Corporation1.Male.Commando.Shotgun',
        'enemy_archetypes.Avatar.Corporation1.Female.Elite Unit.Assault Rifle',
    ],
    'max_amount': 5,
    'level': 13,
    'spawn_frequency': 16.0,
    'blind_rush': False,
}

PRESET_NAVI = {
    'label': 'Navi',
    'territory': TERRITORY_NAVI,
    'archetype': 'enemy_archetypes.Avatar.Navi1.Female.Elite Bodyguard.Dual Blades',
    'extra_archetypes': [
        'enemy_archetypes.Avatar.Navi1.Male.Warrior.Axe',
        'enemy_archetypes.Avatar.Navi1.Female.Hunter.Bow',
        'enemy_archetypes.Avatar.Navi1.Female.Feral.Dual Blades',
        'enemy_archetypes.Avatar.Navi1.Female.Elite Bodyguard.Fighting Staff',
    ],
    'max_amount': 5,
    'level': 13,
    'spawn_frequency': 13.0,
    'blind_rush': True,
}


# ── Archetype discovery ──────────────────────────────────────────────────────

def _library_names(prefix=None):
    """Archetype names from the loaded level's entitylibrary, optionally
    filtered by prefix.  Empty list if no library is loaded."""
    try:
        from archetype_library import get_library
        names = get_library().all_names() or []
    except Exception:
        return []
    if prefix:
        p = prefix.lower()
        names = [n for n in names if (n or '').lower().startswith(p)]
    return sorted(set(names))


def _creature_choices():
    names = _library_names('animals.')
    return names or list(FALLBACK_CREATURES)


def _enemy_choices():
    names = _library_names('enemy_archetypes.')
    return names or sorted(set(
        [PRESET_CORP['archetype']] + PRESET_CORP['extra_archetypes'] +
        [PRESET_NAVI['archetype']] + PRESET_NAVI['extra_archetypes']))


# ── Insertion ────────────────────────────────────────────────────────────────

_MISSION_LAYER_HASH = '494C09F2'
_TEXT_PATHID_HASH = 'C56F9204'
_PATHID_HASH = 'D0E30BF7'


def _find_or_create_layer(root, path_id):
    """Return the ``<object name="MissionLayer">`` whose ``text_PathId`` is
    ``path_id``, creating it if absent.

    The structural container and the entity's own
    ``text_hidMissionLayerPath`` must agree or the game ignores the entity —
    see AGENTS.md "Omnis/mapsdata entity structural placement".  Retail keeps
    every component-less always-on entity in the ``main`` container.
    """
    for ml in root.findall(".//object[@name='MissionLayer']"):
        f = ml.find("./field[@name='text_PathId']")
        if f is not None and (f.get('value-String') or '') == path_id:
            return ml

    ml = ET.SubElement(root, 'object')
    ml.set('hash', _MISSION_LAYER_HASH)
    ml.set('name', 'MissionLayer')

    t = ET.SubElement(ml, 'field')
    t.set('hash', _TEXT_PATHID_HASH)
    t.set('name', 'text_PathId')
    t.set('value-String', path_id)
    t.set('type', 'BinHex')
    t.text = SB.string_to_binhex(path_id)

    p = ET.SubElement(ml, 'field')
    p.set('hash', _PATHID_HASH)
    p.set('name', 'PathId')
    p.set('value-ComputeHash32', path_id)
    p.set('type', 'BinHex')
    p.text = SB.compute_hash32_crc_binhex(path_id)
    return ml


def commit_plan(editor, plan):
    """Insert a plan's entities into the loaded level.

    Returns ``(created_entities, [error, ...])``.  Raises nothing: a per-entity
    failure is collected and the rest still land.
    """
    created, errors = [], []
    touched = set()

    for pe in plan:
        try:
            if pe.target == 'omnis':
                tree = getattr(editor, 'omnis_tree', None)
                path = editor._find_tree_file_path('omnis') \
                    if hasattr(editor, '_find_tree_file_path') else None
                src = 'omnis'
            else:
                tree = getattr(editor, 'xml_tree', None)
                path = getattr(editor, 'xml_file_path', None)
                src = 'mapsdata'

            if tree is None:
                errors.append('%s: no %s tree loaded (is a level open?)'
                              % (pe.name, src))
                continue

            root = tree.getroot()
            layer = _find_or_create_layer(root, pe.layer)
            # Re-parse so the tree owns its own element, not the plan's.
            elem = ET.fromstring(ET.tostring(pe.xml, encoding='unicode'))
            layer.append(elem)

            ent = Entity(id=str(pe.entity_id), name=pe.name,
                         x=pe.x, y=pe.y, z=pe.z, xml_element=elem)
            ent.source_file = src
            ent.source_file_path = path
            ent.source_layer = pe.layer
            if hasattr(editor, 'entities'):
                editor.entities.append(ent)
            created.append(ent)
            touched.add(src)

        except Exception as e:
            errors.append('%s: %s' % (pe.name, e))
            traceback.print_exc()

    # Normalise whitespace once per touched tree, then flag it dirty.  The
    # editor's hash-gated save writes the file; we deliberately do not.
    for src in touched:
        tree = getattr(editor, 'omnis_tree' if src == 'omnis' else 'xml_tree', None)
        if tree is None:
            continue
        try:
            ET.indent(tree, space='  ')
        except AttributeError:
            pass
        if src == 'omnis':
            editor.omnis_tree_modified = True
        else:
            editor.xml_tree_modified = True

    _refresh(editor, created)
    return created, errors


def _refresh(editor, created):
    """Rebuild the caches/UI that a new entity must appear in."""
    canvas = getattr(editor, 'canvas', None)
    if canvas is not None:
        for fn in ('invalidate_position_cache', 'invalidate_entity_caches'):
            try:
                getattr(canvas, fn)()
            except Exception:
                pass
        try:
            canvas.set_entities(editor.entities, center_view=False)
        except Exception:
            try:
                canvas.entities = editor.entities
            except Exception:
                pass
        try:
            canvas.update()
        except Exception:
            pass
    for fn in ('update_entity_tree', 'update_entity_statistics'):
        try:
            getattr(editor, fn)()
        except Exception:
            pass


# ── Shared dialog helpers ────────────────────────────────────────────────────

def _combo(items, editable=True, current=None):
    c = QComboBox()
    c.setEditable(editable)
    c.addItems(items)
    if editable:
        comp = QCompleter(items, c)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        c.setCompleter(comp)
    if current:
        idx = c.findText(current)
        if idx >= 0:
            c.setCurrentIndex(idx)
        else:
            c.setEditText(current)
    return c


def _dspin(lo, hi, val, step=1.0, dec=2, suffix=''):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(dec)
    s.setValue(val)
    if suffix:
        s.setSuffix(suffix)
    return s


def _ispin(lo, hi, val):
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(val)
    return s


def _as_parent(obj):
    """Qt raises TypeError on a non-widget parent rather than ignoring it, and a
    parentless modal segfaults on the offscreen platform — so resolve a usable
    parent or None.  Same convention as ``pak_ui._as_parent``."""
    return obj if isinstance(obj, QWidget) else None


def _existing_ids(editor):
    ids = set()
    for e in getattr(editor, 'entities', []) or []:
        try:
            ids.add(int(e.id))
        except Exception:
            pass
    return ids


# ── Creature Spawn Point ─────────────────────────────────────────────────────

class CreatureSpawnDialog(QDialog):
    """Create one wildlife spawn point (+ optional roam area)."""

    def __init__(self, editor, x, y, z=0.0, parent=None):
        super().__init__(_as_parent(parent) or _as_parent(editor))
        self.editor = editor
        self.setWindowTitle('Add Creature Spawn Point')
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)

        head = QLabel('Creature Spawn Point')
        f = QFont(); f.setBold(True); f.setPointSize(11)
        head.setFont(f)
        root.addWidget(head)
        root.addWidget(QLabel(
            'Drops an AvatarNPCSpawnPoint that spawns wildlife, plus the '
            'NPCSpawnPointCollection area it scatters them into.'))

        # -- what --
        g = QGroupBox('Creature')
        fl = QFormLayout(g)
        self.name = QLineEdit(self._next_name())
        fl.addRow('Name suffix:', self.name)
        self.arch = _combo(_creature_choices(),
                           current='Animals.Avatar.Hexapede')
        fl.addRow('Archetype:', self.arch)
        self.count = _ispin(1, 32, 2)
        fl.addRow('Alive at once:', self.count)
        self.level = _ispin(1, 30, 1)
        fl.addRow('Level:', self.level)
        root.addWidget(g)

        # -- where --
        g2 = QGroupBox('Placement')
        fl2 = QFormLayout(g2)
        self.px = _dspin(-100000, 100000, float(x), 1.0, 3)
        self.py = _dspin(-100000, 100000, float(y), 1.0, 3)
        self.pz = _dspin(-100000, 100000, float(z), 1.0, 3)
        for lbl, w in (('X:', self.px), ('Y:', self.py), ('Z (height):', self.pz)):
            fl2.addRow(lbl, w)
        self.use_area = QCheckBox('Give it a roam area (recommended)')
        self.use_area.setChecked(True)
        self.use_area.setToolTip(
            '134 of 152 wildlife spawners in the retail game own a spawn area.')
        fl2.addRow('', self.use_area)
        self.radius = _dspin(1.0, 200.0, 8.0, 1.0, 1, ' m')
        fl2.addRow('Area radius:', self.radius)
        root.addWidget(g2)

        # -- behaviour --
        g3 = QGroupBox('Behaviour')
        fl3 = QFormLayout(g3)
        self.respawn = QCheckBox('Respawn forever when killed')
        self.respawn.setChecked(True)
        fl3.addRow('', self.respawn)
        self.freq = _dspin(1.0, 3600.0, 120.0, 5.0, 1, ' s')
        fl3.addRow('Respawn delay:', self.freq)
        self.active = QCheckBox('Active on load (spawns immediately)')
        self.active.setChecked(True)
        self.active.setToolTip(
            'Uncheck to write bActive=False, which waits for mission '
            'scripting to switch it on.')
        fl3.addRow('', self.active)
        root.addWidget(g3)

        self.status = QLabel('')
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText('Create')
        bb.accepted.connect(self._create)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        try:
            apply_dialog_theme(self)
        except Exception:
            pass

    def _next_name(self):
        used = {getattr(e, 'name', '') or '' for e in getattr(self.editor, 'entities', []) or []}
        n = 1
        while ('AvatarNPCSpawnPoint_Creature_%02d' % n) in used:
            n += 1
        return 'Creature_%02d' % n

    def _create(self):
        try:
            arch = (self.arch.currentText() or '').strip()
            if not arch:
                QMessageBox.warning(self, 'Creature Spawn Point',
                                    'Pick an archetype first.')
                return
            name = (self.name.text() or '').strip() or 'Creature'
            plan = plan_creature_spawn(
                _existing_ids(self.editor), name,
                self.px.value(), self.py.value(), self.pz.value(), arch,
                radius=self.radius.value(), max_amount=self.count.value(),
                level=self.level.value(), spawn_frequency=self.freq.value(),
                respawn=self.respawn.isChecked(),
                use_area=self.use_area.isChecked(),
                active=self.active.isChecked())
            created, errors = commit_plan(self.editor, plan)
            if errors:
                QMessageBox.warning(
                    self, 'Creature Spawn Point',
                    'Created %d entities, but:\n\n%s'
                    % (len(created), '\n'.join(errors[:8])))
                if not created:
                    return
            QMessageBox.information(
                self, 'Creature Spawn Point',
                'Created %d entities:\n\n%s\n\nSave Level to write them out.'
                % (len(created), '\n'.join('  ' + e.name for e in created)))
            self.accept()
        except Exception as e:
            traceback.print_exc()
            QMessageBox.warning(self, 'Creature Spawn Point',
                                'Could not create the spawn point:\n%s' % e)


# ── War Battle ───────────────────────────────────────────────────────────────

class _SideBox(QGroupBox):
    """One faction's settings."""

    def __init__(self, preset, choices, parent=None):
        super().__init__("%s side" % preset['label'], parent)
        fl = QFormLayout(self)
        self.preset = preset
        self.arch = _combo(choices, current=preset['archetype'])
        fl.addRow('Archetype:', self.arch)
        self.variety = QCheckBox('Mixed unit types (uses the extra archetypes)')
        self.variety.setChecked(True)
        fl.addRow('', self.variety)
        self.count = _ispin(1, 32, preset['max_amount'])
        fl.addRow('Alive at once:', self.count)
        self.level = _ispin(1, 30, preset['level'])
        fl.addRow('Level:', self.level)
        self.freq = _dspin(1.0, 600.0, preset['spawn_frequency'], 1.0, 1, ' s')
        fl.addRow('Respawn delay:', self.freq)

    def data(self):
        d = dict(self.preset)
        d['archetype'] = (self.arch.currentText() or '').strip() or self.preset['archetype']
        d['max_amount'] = self.count.value()
        d['level'] = self.level.value()
        d['spawn_frequency'] = self.freq.value()
        if not self.variety.isChecked():
            d['extra_archetypes'] = []
        return d


class WarBattleDialog(QDialog):
    """Create a complete two-sided endless battle."""

    def __init__(self, editor, x, y, z=0.0, parent=None):
        super().__init__(_as_parent(parent) or _as_parent(editor))
        self.editor = editor
        self.setWindowTitle('Create War Battle')
        self.setMinimumWidth(640)

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        root = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        head = QLabel('War Battle')
        f = QFont(); f.setBold(True); f.setPointSize(11)
        head.setFont(f)
        root.addWidget(head)
        blurb = QLabel(
            'Two armies, each spawning in its own camp and charging its own '
            'rush marker. The two markers sit a short distance apart, so the '
            'sides collide in the middle and fight — forever.\n'
            'This is how Plains of Goliath builds WarZone_1 through WarZone_4.')
        blurb.setWordWrap(True)
        root.addWidget(blurb)

        g = QGroupBox('Battle')
        fl = QFormLayout(g)
        self.zone = QLineEdit(self._next_zone())
        fl.addRow('Zone name:', self.zone)
        self.px = _dspin(-100000, 100000, float(x), 1.0, 3)
        self.py = _dspin(-100000, 100000, float(y), 1.0, 3)
        self.pz = _dspin(-100000, 100000, float(z), 1.0, 3)
        for lbl, w in (('Centre X:', self.px), ('Centre Y:', self.py),
                       ('Centre Z (height):', self.pz)):
            fl.addRow(lbl, w)
        self.heading = _dspin(0.0, 359.0, 0.0, 15.0, 1, '\u00b0')
        self.heading.setToolTip('Direction the two camps face off along.')
        fl.addRow('Battle axis:', self.heading)
        self.separation = _dspin(10.0, 600.0, 60.0, 5.0, 1, ' m')
        self.separation.setToolTip('Distance between the two camps.')
        fl.addRow('Camp separation:', self.separation)
        self.gap = _dspin(2.0, 200.0, DEFAULT_TAG_GAP, 1.0, 1, ' m')
        self.gap.setToolTip(
            'Distance between the two rush markers. Retail WarZones use '
            '17-62 m. Smaller means a tighter brawl; too large and the sides '
            'may never meet.')
        fl.addRow('Rush-marker gap:', self.gap)
        self.per_side = _ispin(1, 8, 1)
        fl.addRow('Spawners per side:', self.per_side)
        self.area = _dspin(1.0, 100.0, 8.0, 1.0, 1, ' m')
        fl.addRow('Camp radius:', self.area)
        root.addWidget(g)

        choices = _enemy_choices()
        self.side_a = _SideBox(PRESET_CORP, choices)
        self.side_b = _SideBox(PRESET_NAVI, choices)
        root.addWidget(self.side_a)
        root.addWidget(self.side_b)

        g3 = QGroupBox('Activation')
        fl3 = QFormLayout(g3)
        self.self_start = QCheckBox('Start on load (no mission scripting needed)')
        self.self_start.setChecked(True)
        self.self_start.setToolTip(
            'Checked: bActive=True in the "main" layer, which is how retail '
            'PacificZones are shipped — the fight runs as soon as the map '
            'loads.\n'
            'Unchecked: the retail WarZone shape (bActive=False inside '
            'ld_spawners\\<zone>), which needs mission scripting to start, so '
            'nothing will spawn on its own.')
        fl3.addRow('', self.self_start)
        root.addWidget(g3)

        self.status = QLabel('')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        root.addStretch(1)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText('Create Battle')
        bb.accepted.connect(self._create)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)

        try:
            apply_dialog_theme(self)
        except Exception:
            pass

    def _next_zone(self):
        used = {(getattr(e, 'name', '') or '') for e in getattr(self.editor, 'entities', []) or []}
        n = 1
        while any(('_WarZone_%02d_' % n) in u for u in used):
            n += 1
        return 'WarZone_%02d' % n

    def _create(self):
        try:
            zone = (self.zone.text() or '').strip() or 'WarZone_01'
            a, b = self.side_a.data(), self.side_b.data()
            if not a['archetype'] or not b['archetype']:
                QMessageBox.warning(self, 'War Battle',
                                    'Both sides need an archetype.')
                return
            if self.gap.value() >= self.separation.value():
                QMessageBox.warning(
                    self, 'War Battle',
                    'The rush-marker gap (%.1f m) must be smaller than the camp '
                    'separation (%.1f m), or each side\'s marker lands behind '
                    'the other army and they will not meet.'
                    % (self.gap.value(), self.separation.value()))
                return

            plan = plan_war_battle(
                _existing_ids(self.editor), zone,
                self.px.value(), self.py.value(), self.pz.value(),
                a, b,
                separation=self.separation.value(), tag_gap=self.gap.value(),
                spawners_per_side=self.per_side.value(),
                area_radius=self.area.value(),
                self_starting=self.self_start.isChecked(),
                heading_deg=self.heading.value())

            created, errors = commit_plan(self.editor, plan)
            if errors:
                QMessageBox.warning(
                    self, 'War Battle',
                    'Created %d entities, but:\n\n%s'
                    % (len(created), '\n'.join(errors[:8])))
                if not created:
                    return

            note = ''
            if not self.self_start.isChecked():
                note = ('\n\nNOTE: you chose the retail script-gated shape, so '
                        'these spawners are bActive=False in the mission layer '
                        '"ld_spawners\\%s". Nothing will spawn until mission '
                        'scripting activates that layer.' % zone.lower())
            QMessageBox.information(
                self, 'War Battle',
                'Created %d entities for %s:\n\n%s\n\nSave Level to write them '
                'out.%s'
                % (len(created), zone,
                   '\n'.join('  ' + e.name for e in created), note))
            self.accept()
        except Exception as e:
            traceback.print_exc()
            QMessageBox.warning(self, 'War Battle',
                                'Could not create the battle:\n%s' % e)
