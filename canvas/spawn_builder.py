"""
spawn_builder.py — GUI-free builders for Avatar NPC spawn entities.

Everything here is pure stdlib + the BinHex helpers from ``entity_editor``:
no Qt, no OpenGL, no file IO.  That keeps it unit-testable and lets the two
dialogs in ``canvas/spawn_dialogs.py`` stay thin.

WHAT THIS BUILDS (ground-truthed against retail Avatar data — see
AGENTS.md "Creature spawns and WarZone battles"):

* ``AvatarNPCSpawnPoint``      COmniMapTickedEntity + CNPCSpawnerComponent
                               — the thing that actually spawns NPCs.
* ``NPCSpawnPointCollection``  CBasicShapeEntity with a ``hidShapePoints``
                               polygon — the area a spawner scatters into.
* ``BtzOmniTagPoint``          CBtzOmniTagPoint — a bare position marker used
                               as a spawner's ``entRushPoint``.

AND THE WAR MECHANIC, which is simply:

    Two opposing spawner sets each rush their OWN tag point, and the two tag
    points are placed a short distance apart in the middle.  Both armies
    converge on that contested ground and fight; ``bRespawnWhenDead`` +
    ``iNPCMaximumRespawns = -1`` keeps it going forever.

Retail Plains of Goliath tag pairs sit 17–62 m apart (``WarZone_1..4``), which
is where ``DEFAULT_TAG_GAP`` comes from.

AVATAR ONLY.  Far Cry 2 ships none of these components — a scan of all 16,238
converted FC2 worldsector XMLs found zero occurrences of
``CNPCSpawnerComponent``, ``CBtzOmniTagPoint``, ``NPCSpawnPointCollection``,
``archNPCArchetype`` or ``entRushPoint``.  This is a documented Rule 8
exception, the same one MP Spawn Creator carries; callers must gate on
``game_mode``.
"""

import math
import struct
import time
import random
import zlib
import xml.etree.ElementTree as ET
from collections import namedtuple

from entity_editor import (
    string_to_binhex, int32_to_binhex, int64_to_binhex,
    float_to_binhex, vector3_to_binhex, boolean_to_binhex,
    enum_to_binhex,
)

# ── Territory controller enum ────────────────────────────────────────────────
TERRITORY_CORP = 1
TERRITORY_NAVI = 2
TERRITORY_ALL = 6

# ── selSpawnerType enum ──────────────────────────────────────────────────────
SPAWNER_SINGLE = 0
SPAWNER_RANDOM = 1
SPAWNER_CYCLE = 2
SPAWNER_MOUNTED = 3
SPAWNER_GROUP = 4

# Retail WarZone_1..4 Corp/Navi tag points are 17.7–62.5 m apart; the armies
# meet between them.  Too small and they spawn on top of each other, too large
# and each side reaches its tag without ever meeting the other.
DEFAULT_TAG_GAP = 30.0

# The mission-layer folder retail uses for these; only written in the
# script-gated (non self-starting) mode.
WARZONE_LAYER_PREFIX = 'ld_spawners'


# ── ComputeHash32 ────────────────────────────────────────────────────────────

def compute_hash32_crc(text):
    """``value-ComputeHash32`` is CRC-32 of the case-sensitive string.

    NOT the djb2 variant in ``entity_editor.compute_hash32``.  Verified against
    retail Plains of Goliath: COmniMapTickedEntity -> 7773ED6B,
    CBasicShapeEntity -> E6026070, CBtzOmniTagPoint -> 7DBB5B45,
    COmniMapEntity -> B2648188, CNavMeshGenComponent -> DF3CCB94, and
    ``ld_spawners\\warzone_2`` -> 65D2895E.  All six match CRC-32 and none
    match djb2 — which is why ``mp_spawn_creator`` had to hardcode its hashes.
    """
    return zlib.crc32(text.encode('ascii', errors='replace')) & 0xFFFFFFFF


def compute_hash32_crc_binhex(text):
    """CRC-32 ComputeHash32 as little-endian BinHex."""
    return struct.pack('<I', compute_hash32_crc(text)).hex().upper()


# ── XML primitives ───────────────────────────────────────────────────────────

def _obj(hash_, name):
    e = ET.Element('object')
    e.set('hash', hash_)
    e.set('name', name)
    return e


def _field(hash_, name, binhex, **extras):
    e = ET.Element('field')
    e.set('hash', hash_)
    if name:
        e.set('name', name)
    e.set('type', 'BinHex')
    for k, v in extras.items():
        e.set(k.replace('_', '-'), str(v))
    e.text = binhex
    return e


def _fmt(v):
    """Match the game's own float rendering (6 significant digits, no exponent
    for ordinary map coordinates)."""
    s = '%g' % round(float(v), 6)
    return s


def vec3_str(x, y, z):
    return '%s,%s,%s' % (_fmt(x), _fmt(y), _fmt(z))


def _append_fragment(parent, xml_str):
    parent.append(ET.fromstring(xml_str))


# ── Fixed enum blocks (verbatim from retail files) ───────────────────────────

_ENUM_TERRITORY = """<object hash="453BB77B" name="enumSpecificToTerritoryController">
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

_ENUM_SPAWNERTYPE = """<object hash="07988E71" name="enumSpawnerType">
  <object hash="0EBEAE51" name="enum">
    <field hash="DCB67730" name="Value" value-String="Single" type="BinHex">53696E676C6500</field>
  </object>
  <object hash="0EBEAE51" name="enum">
    <field hash="DCB67730" name="Value" value-String="Random" type="BinHex">52616E646F6D00</field>
  </object>
  <object hash="0EBEAE51" name="enum">
    <field hash="DCB67730" name="Value" value-String="Cycle" type="BinHex">4379636C6500</field>
  </object>
  <object hash="0EBEAE51" name="enum">
    <field hash="DCB67730" name="Value" value-String="Mounted" type="BinHex">4D6F756E74656400</field>
  </object>
  <object hash="0EBEAE51" name="enum">
    <field hash="DCB67730" name="Value" value-String="Group" type="BinHex">47726F757000</field>
  </object>
</object>"""

# hidSize=3 then three (text, hash) pairs — copied byte-for-byte from retail
# spawners.  The engine expects the slot to exist even when unused.
_STP_SUBTYPES = """<object hash="8752221C" name="sNPCSupportedSTPSubtypes">
  <field hash="10CA06AB" name="hidSize" value-Int32="3" type="BinHex">03000000</field>
  <field hash="64D33A00" type="BinHex">00</field>
  <field hash="6934F823" type="BinHex">FFFFFFFF</field>
  <field hash="13D40A96" type="BinHex">00</field>
  <field hash="1E33C8B5" type="BinHex">FFFFFFFF</field>
  <field hash="8ADD5B2C" type="BinHex">00</field>
  <field hash="873A990F" type="BinHex">FFFFFFFF</field>
</object>"""

_SPAWNED_VEHICLES = """<object hash="33F0D285" name="SpawnedVehiclesOverrides">
  <field hash="4003810F" name="bNoAdvancedAmmo" value-Boolean="False" type="BinHex">00</field>
  <field hash="8DAE7BF7" name="bDespawnOnPlayerDeath" value-Boolean="False" type="BinHex">00</field>
</object>"""

_SOUNDS = """<object hash="F68F03C7" name="Sounds">
  <field hash="398B9FF3" name="sndNPCSpawnedStartSound" value-String="0xFFFFFFFF" type="BinHex">3078464646464646464600</field>
  <field hash="0BFF2BD8" name="sndNPCSpawnedStopSound" value-String="0xFFFFFFFF" type="BinHex">3078464646464646464600</field>
  <field hash="61C94706" name="sndActivatedSound" value-String="0xFFFFFFFF" type="BinHex">3078464646464646464600</field>
  <field hash="F78005C5" name="sndDeactivatedSound" value-String="0xFFFFFFFF" type="BinHex">3078464646464646464600</field>
  <field hash="8FE662AD" name="sndtpSoundType" value-UInt32="4294967295" type="BinHex">FFFFFFFF</field>
</object>"""

_FCXAI_COMPONENT = """<object hash="D771A22C" name="CFCXAIComponent">
  <field hash="2B928622" name="text_Type" value-String="CNavMeshGenComponent" type="BinHex">434E61764D65736847656E436F6D706F6E656E7400</field>
  <field hash="2CECF817" name="Type" value-ComputeHash32="CNavMeshGenComponent" type="BinHex">DF3CCB94</field>
  <field hash="DB65A9C9" name="bIgnoreAISecto" value-Boolean="False" type="BinHex">00</field>
  <object hash="4F4522C9" name="AIObject">
    <object hash="94CB3CDF" name="CNavMeshGenComponent" />
  </object>
</object>"""

NULL_ID = 'FFFFFFFFFFFFFFFF'
NULL_ID_DEC = 18446744073709551615


# ── ID generation ────────────────────────────────────────────────────────────

def generate_id(existing_ids):
    """A fresh 64-bit entity id that does not collide with ``existing_ids``."""
    base = int(time.time() * 1_000_000)
    for attempt in range(10_000):
        candidate = base + random.randint(1000, 999_999) + attempt
        if candidate > 9_223_372_036_854_775_807:
            candidate = random.randint(10 ** 18, 9 * 10 ** 18)
        if candidate not in existing_ids:
            existing_ids.add(candidate)
            return candidate
    fallback = (max(existing_ids) + 1) if existing_ids else 10 ** 18
    existing_ids.add(fallback)
    return fallback


# ── Shared entity header ─────────────────────────────────────────────────────

def _entity_header(entity_id, name, entity_class, x, y, z,
                   territory=TERRITORY_ALL, angles_z=0.0):
    """The common prefix every one of these entities carries, in file order."""
    root = _obj('0984415E', 'Entity')
    root.append(_field('B9295CC7', 'hidName', string_to_binhex(name),
                       value_String=name))
    root.append(_field('052A103F', 'disEntityId', int64_to_binhex(entity_id),
                       value_Id64=str(entity_id)))
    root.append(_field('D2B3429E', 'text_hidEntityClass',
                       string_to_binhex(entity_class), value_String=entity_class))
    root.append(_field('1875AE89', 'hidEntityClass',
                       compute_hash32_crc_binhex(entity_class),
                       value_ComputeHash32=entity_class))
    root.append(_field('ADC3BD93', 'hidResourceCount', int32_to_binhex(0),
                       value_Int32='0'))

    pos_hex = vector3_to_binhex(x, y, z)
    pos_str = vec3_str(x, y, z)
    root.append(_field('32D620A2', 'hidPos', pos_hex, value_Vector3=pos_str))

    # Retail writes the middle component as negative zero (0x80000000); mirror
    # it so a round-trip of an untouched entity stays byte-identical.
    if angles_z:
        ang_hex = '00000000' + '00000080' + float_to_binhex(angles_z)
        ang_str = '0,-0,%s' % _fmt(angles_z)
    else:
        ang_hex = '000000000000008000000000'
        ang_str = '0,-0,0'
    root.append(_field('6553B60B', 'hidAngles', ang_hex, value_Vector3=ang_str))

    root.append(_field('00C2DD80', 'hidScale', '0000803F',
                       value_Hash32='1065353216'))
    root.append(_field('7D7860C6', 'hidPos_precise', pos_hex,
                       value_Vector3=pos_str))
    root.append(_field('B554978A', 'hidConstEntity', '00'))
    root.append(_field('DE5F232E', 'selSpecificToTerritoryController',
                       enum_to_binhex(territory), value_Enum=str(territory)))
    return root


def _mission_component(layer_path):
    c = _obj('D18498C8', 'CMissionComponent')
    c.append(_field('7AF1FD74', 'text_hidMissionLayerPath',
                    string_to_binhex(layer_path), value_String=layer_path))
    c.append(_field('90AF9D50', 'hidMissionLayerPath',
                    compute_hash32_crc_binhex(layer_path),
                    value_ComputeHash32=layer_path))
    c.append(_field('27B31D2E', 'text_hidCategory', '00', value_String=''))
    c.append(_field('37F59D7D', 'hidCategory', 'FFFFFFFF'))
    c.append(_field('136C40D8', 'ForceMerge', '01'))
    return c


def _event_component():
    c = _obj('B3A99CB8', 'CEventComponent')
    c.append(_obj('3D06591C', 'hidLinks'))
    return c


# ── Builders ─────────────────────────────────────────────────────────────────

def build_spawn_collection(entity_id, name, x, y, z, radius=8.0, points=5,
                           territory=TERRITORY_ALL, layer_path=None):
    """``NPCSpawnPointCollection`` — a CBasicShapeEntity whose ``hidShapePoints``
    polygon is the area the spawner scatters NPCs into.

    Retail collections carry 5 points; the first point equals ``hidPos`` (the
    editor's shape-point system relies on that invariant — see AGENTS.md
    "hidShapePoints").
    """
    root = _entity_header(entity_id, name, 'CBasicShapeEntity', x, y, z,
                          territory)

    pts = ET.Element('field')
    pts.set('hash', '4073DD31')
    pts.set('name', 'hidShapePoints')
    # Pt0 MUST equal hidPos.
    first = ET.SubElement(pts, 'Point')
    first.text = vec3_str(x, y, z)
    for i in range(max(0, points - 1)):
        ang = 2.0 * math.pi * i / max(1, points - 1)
        p = ET.SubElement(pts, 'Point')
        p.text = vec3_str(x + radius * math.cos(ang),
                          y + radius * math.sin(ang), z)
    root.append(pts)

    _append_fragment(root, _ENUM_TERRITORY)

    comps = _obj('A115F62D', 'Components')
    if layer_path:
        comps.append(_mission_component(layer_path))
    comps.append(_event_component())
    root.append(comps)
    return root


def build_tag_point(entity_id, name, x, y, z, territory=TERRITORY_ALL,
                    layer_path=None):
    """``BtzOmniTagPoint`` — the bare marker a spawner rushes toward.

    Lives in **omnis**, never mapsdata: all 51 tag points in retail Plains of
    Goliath are in ``*.omnis.xml``.
    """
    root = _entity_header(entity_id, name, 'CBtzOmniTagPoint', x, y, z,
                          territory)
    _append_fragment(root, _ENUM_TERRITORY)
    comps = _obj('A115F62D', 'Components')
    if layer_path:
        comps.append(_mission_component(layer_path))
    comps.append(_event_component())
    root.append(comps)
    return root


def build_npc_spawner(entity_id, name, x, y, z, archetype,
                      spawn_points_id=None, rush_point_id=None,
                      extra_archetypes=None,
                      active=True, spawner_type=SPAWNER_SINGLE,
                      max_amount=1, max_respawns=-1, max_dead=10,
                      spawn_frequency=30.0, corpse_despawn=60.0,
                      respawn_when_dead=True, blind_rush=False,
                      level_override=1, level_override_max=-1,
                      force_weapon_drawn=False, ignore_stp=False,
                      vision_radius=50.0, territory=TERRITORY_ALL,
                      layer_path=None):
    """``AvatarNPCSpawnPoint`` — COmniMapTickedEntity + CNPCSpawnerComponent.

    Field order mirrors retail exactly.  ``spawn_points_id`` links the
    collection to scatter into; ``rush_point_id`` links the tag point to charge
    at (this is what turns two spawner sets into a battle).

    ``active`` False is the retail WarZone shape — it waits for mission
    scripting to enable it.  True is the retail *PacificZone* shape and is what
    makes a generated fight run with no scripting at all.
    """
    root = _entity_header(entity_id, name, 'COmniMapTickedEntity', x, y, z,
                          territory)
    _append_fragment(root, _ENUM_TERRITORY)

    comps = _obj('A115F62D', 'Components')
    sp = _obj('D8C1CBCD', 'CNPCSpawnerComponent')

    def b(hash_, nm, val):
        sp.append(_field(hash_, nm, boolean_to_binhex(val),
                         value_Boolean=str(bool(val))))

    def f(hash_, nm, val):
        sp.append(_field(hash_, nm, float_to_binhex(float(val)),
                         value_Float32=_fmt(val)))

    def i(hash_, nm, val):
        sp.append(_field(hash_, nm, int32_to_binhex(int(val)),
                         value_Int32=str(int(val))))

    def link(hash_, nm, val):
        if val is None:
            sp.append(_field(hash_, nm, NULL_ID))
        else:
            sp.append(_field(hash_, nm, int64_to_binhex(int(val)),
                             value_Id64=str(val)))

    b('7C35DA25', 'bActive', active)
    b('523DF11F', 'bNoTimerOnInitialSpawn', True)
    b('310819CE', 'bFullInitialSpawn', True)
    f('BFCE7DFE', 'fSpawnFrequency', spawn_frequency)
    f('02C1FD37', 'fSecondsBeforeCorpseDespawn', corpse_despawn)
    f('48A25DE7', 'fMinSpawnDistance', 0.0)
    b('BBF3DD59', 'bRespawnWhenDead', respawn_when_dead)
    b('53A83DCA', 'bCannotSeeRespawn', True)
    b('7CA76063', 'bCanSeeFarRespawn', True)
    b('57A6943E', 'bCannotSeeDespawn', True)
    i('DD76596C', 'iNPCMaximumAmount', max_amount)
    i('8F5EFFED', 'iNPCMaximumRespawns', max_respawns)
    i('3D6FE267', 'iNPCMaximumDeadAmount', max_dead)
    b('E800C721', 'bIgnoreSTP', ignore_stp)
    i('749EB981', 'iNPCLevelOverride', level_override)
    i('677CBE18', 'iNPCLevelOverrideMax', level_override_max)
    b('42BF3779', 'bNPCForceSpawnWithWeaponDrawn', force_weapon_drawn)
    link('BA59DA31', 'entSpawnPoints', spawn_points_id)
    link('0751DF13', 'entRushPoint', rush_point_id)
    b('759F3A12', 'bBlindRush', blind_rush)
    link('C82D581F', 'entJumpPoint', None)
    sp.append(_field('8EA3A9BB', 'selSpawnerType', enum_to_binhex(spawner_type),
                     value_Enum=str(spawner_type)))
    sp.append(_field('2048B038', 'archNPCArchetype', string_to_binhex(archetype),
                     value_String=archetype))
    sp.append(_field('99C21F79', 'sNPCOverrideNameID', '00'))
    sp.append(_field('139FAB01', 'sAdditionnalMissionEventOnPlayerKill', '00'))
    sp.append(_field('5AEDF0BD', 'sAdditionnalMissionEventOnDeath', '00'))

    _append_fragment(sp, _STP_SUBTYPES)

    vps = _obj('2D223749', 'VisionPoints')
    vp = _obj('2FB2B4AA', 'VisionPoint')
    vp.append(_field('F8186C6E', 'fRadius', float_to_binhex(float(vision_radius)),
                     value_Float32=_fmt(vision_radius)))
    vp.append(_field('95FD7609', 'entEntity', NULL_ID))
    vps.append(vp)
    sp.append(vps)

    _append_fragment(sp, _ENUM_SPAWNERTYPE)
    _append_fragment(sp, _SPAWNED_VEHICLES)
    _append_fragment(sp, _SOUNDS)

    # Retail always emits the ExtraArchetypes block, and always terminates it
    # with one empty Archetype entry.
    ex = _obj('5AC4E930', 'ExtraArchetypes')
    for arch in (extra_archetypes or []):
        if not arch:
            continue
        a = _obj('63243E40', 'Archetype')
        a.append(_field('9A4BC461', 'archArchetype', string_to_binhex(arch),
                        value_String=arch))
        ex.append(a)
    blank = _obj('63243E40', 'Archetype')
    blank.append(_field('9A4BC461', 'archArchetype', '00'))
    ex.append(blank)
    sp.append(ex)

    comps.append(sp)
    _append_fragment(comps, _FCXAI_COMPONENT)
    if layer_path:
        comps.append(_mission_component(layer_path))
    comps.append(_event_component())
    root.append(comps)
    return root


# ── Plans ────────────────────────────────────────────────────────────────────

# target: 'mapsdata' | 'omnis'   layer: structural MissionLayer text_PathId
PlannedEntity = namedtuple(
    'PlannedEntity', 'target layer xml entity_id name x y z')


def plan_creature_spawn(existing_ids, name, x, y, z, archetype,
                        radius=8.0, max_amount=2, level=1,
                        spawn_frequency=120.0, respawn=True,
                        extra_archetypes=None, use_area=True,
                        active=True, layer_path=None):
    """One creature spawn point (+ its roam area).

    134 of 152 retail animal spawners own a collection, so ``use_area``
    defaults True.  With ``use_area`` False the NPCs spawn on the marker.
    """
    layer = layer_path or 'main'
    out = []

    coll_id = None
    if use_area:
        coll_id = generate_id(existing_ids)
        coll_name = 'NPCSpawnPointCollection_%s' % name
        out.append(PlannedEntity(
            'mapsdata', layer,
            build_spawn_collection(coll_id, coll_name, x, y, z, radius=radius,
                                   layer_path=layer_path),
            coll_id, coll_name, x, y, z))

    sp_id = generate_id(existing_ids)
    sp_name = 'AvatarNPCSpawnPoint_%s' % name
    out.append(PlannedEntity(
        'mapsdata', layer,
        build_npc_spawner(sp_id, sp_name, x, y, z, archetype,
                          spawn_points_id=coll_id, rush_point_id=None,
                          extra_archetypes=extra_archetypes,
                          active=active, spawner_type=SPAWNER_SINGLE,
                          max_amount=max_amount, max_respawns=-1 if respawn else 0,
                          spawn_frequency=spawn_frequency,
                          respawn_when_dead=respawn,
                          level_override=level, level_override_max=-1,
                          layer_path=layer_path),
        sp_id, sp_name, x, y, z))
    return out


def plan_war_battle(existing_ids, zone_name, x, y, z,
                    side_a, side_b,
                    separation=60.0, tag_gap=DEFAULT_TAG_GAP,
                    spawners_per_side=1, area_radius=8.0,
                    self_starting=True, heading_deg=0.0):
    """A complete two-sided battle centred on ``(x, y, z)``.

    ``side_a`` / ``side_b`` are dicts::

        {'label': 'Corp', 'territory': 1, 'archetype': '...',
         'extra_archetypes': [...], 'max_amount': 5, 'level': 13,
         'spawn_frequency': 16.0, 'blind_rush': False}

    Geometry (mirrors retail WarZone_1..4):

        A camp ......... separation/2 back along the axis
        A tag .......... tag_gap/2 back from centre   <- A charges here
        B tag .......... tag_gap/2 forward of centre  <- B charges here
        B camp ......... separation/2 forward along the axis

    Both sides therefore run at each other and collide in the middle.

    ``self_starting`` True writes ``bActive=True`` and no mission layer (the
    retail PacificZone shape) so the fight runs on load.  False writes the
    retail WarZone shape: ``bActive=False`` inside
    ``ld_spawners\\<zone_name>``, which needs mission scripting to start.
    """
    layer_path = None if self_starting else '%s\\%s' % (WARZONE_LAYER_PREFIX,
                                                        zone_name.lower())
    layer = layer_path or 'main'

    ang = math.radians(heading_deg)
    ux, uy = math.cos(ang), math.sin(ang)

    def at(dist):
        return (x + ux * dist, y + uy * dist, z)

    out = []
    half_sep = separation / 2.0
    half_gap = tag_gap / 2.0

    # -A end .. -gap/2 | centre | +gap/2 .. +B end
    for side, sign in ((side_a, -1.0), (side_b, +1.0)):
        label = side.get('label', 'Side')
        territory = side.get('territory', TERRITORY_ALL)

        cx, cy, cz = at(sign * half_sep)
        tx, ty, tz = at(sign * half_gap)

        coll_id = generate_id(existing_ids)
        coll_name = 'NPCSpawnPointCollection_%s_%s' % (zone_name, label)
        out.append(PlannedEntity(
            'mapsdata', layer,
            build_spawn_collection(coll_id, coll_name, cx, cy, cz,
                                   radius=area_radius, territory=territory,
                                   layer_path=layer_path),
            coll_id, coll_name, cx, cy, cz))

        # The tag point is on the side's OWN half, short of the middle — each
        # side charges its own marker and they meet in between.
        tag_id = generate_id(existing_ids)
        tag_name = 'BtzOmniTagPoint_%s_%s' % (zone_name, label)
        out.append(PlannedEntity(
            'omnis', layer,
            build_tag_point(tag_id, tag_name, tx, ty, tz, territory=territory,
                            layer_path=layer_path),
            tag_id, tag_name, tx, ty, tz))

        for n in range(max(1, spawners_per_side)):
            # Fan multiple spawners out perpendicular to the battle axis.
            off = (n - (spawners_per_side - 1) / 2.0) * 6.0
            sx = cx + (-uy) * off
            sy = cy + (ux) * off
            sp_id = generate_id(existing_ids)
            sp_name = 'AvatarNPCSpawnPoint_%s_%s_%02d' % (zone_name, label, n + 1)
            out.append(PlannedEntity(
                'mapsdata', layer,
                build_npc_spawner(
                    sp_id, sp_name, sx, sy, cz,
                    side.get('archetype', ''),
                    spawn_points_id=coll_id, rush_point_id=tag_id,
                    extra_archetypes=side.get('extra_archetypes'),
                    active=bool(self_starting),
                    spawner_type=SPAWNER_RANDOM if side.get('extra_archetypes')
                    else SPAWNER_SINGLE,
                    max_amount=side.get('max_amount', 5),
                    max_respawns=-1,
                    spawn_frequency=side.get('spawn_frequency', 16.0),
                    respawn_when_dead=True,
                    blind_rush=bool(side.get('blind_rush', False)),
                    level_override=side.get('level', 13),
                    level_override_max=side.get('level', 13),
                    force_weapon_drawn=True,
                    ignore_stp=True,
                    territory=territory,
                    layer_path=layer_path),
                sp_id, sp_name, sx, sy, cz))
    return out
