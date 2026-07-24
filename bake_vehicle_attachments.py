#!/usr/bin/env python3
"""Bake vehicle mounted-weapon attachments into canvas/assets/<game>/vehicle_attachments.json.

Dev-time tool (run manually when game data or the rule changes):
    python bake_vehicle_attachments.py <entitylibrary_full.fcb.converted.xml> [more.xml ...]
        --game avatar|fc2 --data-root <extracted data root with graphics/>

The attach rule (recovered from the retail engine decompile + verified in the
prototype data — see AGENTS.md "mounted-weapons layer"):
  vehicle prototype
    ├─ MountedWeapons/MountedWeaponEntry.archMountedWeapon → turret prototype
    ├─ Seat with hidSeatType == 2 (gunner) → BoneName = the VEHICLE bone the
    │   mounted weapon chain sits on (e.g. GUNNER_POSITION)
    └─ turret prototype → GraphicComponent .xbg  +  archWeapon → gun prototype
        └─ gun .xbg attaches at the TURRET-model bone whose name matches the
           gun model's ROOT bone name (e.g. Dove_Mounted_Weapon)

Output entries are FLATTENED to one game-space 4x4 (rotation rows + position)
per attachment, relative to the vehicle model origin, composed from the bind
skeletons of the vehicle and turret .xbg files. The editor merges these
models into the vehicle's GLTFModel at load (xbg_direct_loader), so vehicles
render complete on every path with no renderer changes.
"""

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'canvas'))


# ── streaming prototype extraction ────────────────────────────────────────────

def iter_prototypes(xml_path):
    """Yield <object name="EntityPrototype"> elements one at a time (246MB
    files — iterparse with element clearing keeps memory flat)."""
    context = ET.iterparse(xml_path, events=('start', 'end'))
    _, root = next(context)
    depth = 0
    for event, elem in context:
        if event == 'start':
            if elem.tag == 'object' and elem.get('name') == 'EntityPrototype':
                depth += 1
        elif event == 'end':
            if elem.tag == 'object' and elem.get('name') == 'EntityPrototype':
                depth -= 1
                if depth == 0:
                    yield elem
                    root.clear()   # drop processed subtree


def _field(elem, name):
    f = elem.find(f".//field[@name='{name}']")
    if f is None:
        return None
    return f.get('value-String') or f.get('value-ComputeHash32')


def extract_prototype(elem):
    """Pull the fields the attach rule needs from one EntityPrototype."""
    name = None
    for f in elem.iter('field'):
        if f.get('name') == 'Name':
            name = f.get('value-String')
            break
    if not name:
        return None
    p = {'name': name, 'model': None, 'mounted': [], 'gunner_bones': [],
         'arch_weapon': None}

    for r in elem.iter('resource'):
        fn = r.get('fileName', '')
        if fn.lower().endswith('.xbg') and p['model'] is None:
            p['model'] = fn.replace('\\', '/')

    for obj in elem.iter('object'):
        oname = obj.get('name')
        if oname == 'MountedWeaponEntry':
            arch = _field(obj, 'archMountedWeapon')
            if arch:
                p['mounted'].append(arch)
        elif oname == 'Seat':
            st = obj.find("./field[@name='hidSeatType']")
            if st is not None and st.get('value-Int32') == '2':
                bn = obj.find("./field[@name='text_BoneName']")
                if bn is not None and bn.get('value-String'):
                    p['gunner_bones'].append(bn.get('value-String'))

    for f in elem.iter('field'):
        if f.get('name') == 'archWeapon' and f.get('value-String'):
            p['arch_weapon'] = f.get('value-String')
            break
    return p


# ── skeleton lookups ──────────────────────────────────────────────────────────

def load_skeleton(data_root, rel_model):
    from xbg_parser import XBGParser
    import io
    from contextlib import redirect_stdout
    path = os.path.join(data_root, rel_model.replace('/', os.sep))
    if not os.path.exists(path):
        # extracted packs sometimes flatten case
        low = os.path.join(data_root, rel_model.lower().replace('/', os.sep))
        if os.path.exists(low):
            path = low
        else:
            return None, None
    buf = io.StringIO()
    with redirect_stdout(buf):
        data = XBGParser(path).parse(0, skip_skeleton=True)
    return data.skeleton, path


def bone_matrix(skeleton, bone_name):
    """4x4 (row-major nested lists) world bind matrix of a bone, or None."""
    if skeleton is None or not bone_name:
        return None
    want = bone_name.lower()
    for b in skeleton.bones:
        if b.name and b.name.lower() == want and b.world_matrix is not None:
            return [list(row) for row in b.world_matrix.matrix]
    return None


def root_bone_name(skeleton):
    for b in skeleton.bones:
        if b.parent_id is None or b.parent_id < 0:
            return b.name
    return skeleton.bones[0].name if skeleton.bones else None


def gun_mount_matrix(turret_skel, gun_skel):
    """Where the gun sits on the turret mount. Candidates, in priority order:
      1. a turret bone named exactly like the GUN's root bone
         (Avatar: dove_turret has 'Dove_Mounted_Weapon' = gun root),
      2. the generic mount-point names FC2 turrets use
         ('GunMount', 'WeaponPos', 'WeaponPlacement', 'Weapon_Position'),
      3. any bone containing 'weapon'."""
    if turret_skel is None:
        return None
    if gun_skel is not None:
        m = bone_matrix(turret_skel, root_bone_name(gun_skel))
        if m is not None:
            return m
    for cand in ('GunMount', 'WeaponPos', 'WeaponPlacement', 'Weapon_Position'):
        m = bone_matrix(turret_skel, cand)
        if m is not None:
            return m
    for b in turret_skel.bones:
        if b.name and 'weapon' in b.name.lower() and b.world_matrix is not None:
            return [list(row) for row in b.world_matrix.matrix]
    return None


def mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)]
            for i in range(4)]


IDENT = [[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]]


# ── main bake ─────────────────────────────────────────────────────────────────

def bake(xml_paths, game, data_root, out_path):
    protos = {}
    for xp in xml_paths:
        print(f"scanning {xp} ...")
        n = 0
        for elem in iter_prototypes(xp):
            p = extract_prototype(elem)
            if not p:
                continue
            prev = protos.get(p['name'])
            if prev is None:
                protos[p['name']] = p
                n += 1
            else:
                # Names collide across prototype KINDS (e.g. the WeaponProperties
                # record for DoveTurretGun precedes the actual entity) — merge,
                # preferring whichever side carries real data.
                for k in ('model', 'arch_weapon'):
                    if prev[k] is None and p[k] is not None:
                        prev[k] = p[k]
                prev['mounted'] = prev['mounted'] or p['mounted']
                prev['gunner_bones'] = prev['gunner_bones'] or p['gunner_bones']
        print(f"  {n} new prototypes ({len(protos)} total)")

    # index prototypes by the trailing archetype name too
    # (archMountedWeapon strings look like "weapons.Avatar_MountedWeapons.DoveTurret";
    #  prototype Names look like "Avatar_MountedWeapons.DoveTurret")
    by_suffix = {}
    for name, p in protos.items():
        by_suffix.setdefault(name.lower(), p)

    def resolve(arch):
        if not arch:
            return None
        a = arch.lower()
        hit = by_suffix.get(a)
        if hit:
            return hit
        for name, p in by_suffix.items():
            if a.endswith('.' + name) or name.endswith('.' + a) or a == name:
                return p
        # match on trailing dotted suffix
        parts = a.split('.')
        for k in range(1, len(parts)):
            cand = '.'.join(parts[k:])
            if cand in by_suffix:
                return by_suffix[cand]
        return None

    out = {}
    n_veh = n_att = 0
    for p in protos.values():
        if not p['mounted'] or not p['model']:
            continue
        veh_skel, veh_path = load_skeleton(data_root, p['model'])
        if veh_skel is None:
            print(f"  [skip] vehicle model missing: {p['model']}")
            continue
        veh_key = os.path.basename(p['model']).lower()
        attachments = out.setdefault(veh_key, [])
        seat_bones = p['gunner_bones'] or []
        for i, arch in enumerate(p['mounted']):
            wp = resolve(arch)
            if wp is None or not wp['model']:
                print(f"  [skip] {p['name']}: unresolved mounted weapon {arch}")
                continue
            seat_bone = seat_bones[min(i, len(seat_bones) - 1)] if seat_bones else None
            m_vehicle = bone_matrix(veh_skel, seat_bone) or IDENT
            if m_vehicle is IDENT and seat_bone:
                print(f"  [warn] {p['name']}: seat bone {seat_bone!r} not in "
                      f"{veh_key} skeleton — attaching at origin")
            # Dedupe per (kind, attach matrix): vehicle archetype variants
            # (Rover.M249 / Rover.Browning / Rover.Mk19) mount different gun
            # models at the same point — rendering all of them would stack
            # three guns on one jeep. First variant wins per attach point.
            def _add(model, matrix, via, kind):
                nonlocal n_att
                if any(e['kind'] == kind and e['matrix'] == matrix
                       for e in attachments):
                    return
                attachments.append({'model': model, 'matrix': matrix,
                                    'via': via, 'kind': kind})
                n_att += 1

            _add(wp['model'], m_vehicle,
                 f"{p['name']} -> {arch}" + (f" @ {seat_bone}" if seat_bone else ""),
                 'mount')

            # the gun on the turret
            gun = resolve(wp.get('arch_weapon'))
            if gun and gun.get('model'):
                t_skel, _ = load_skeleton(data_root, wp['model'])
                g_skel, _ = load_skeleton(data_root, gun['model'])
                m_gun_local = gun_mount_matrix(t_skel, g_skel)
                m_gun = mat_mul(m_vehicle, m_gun_local) if m_gun_local else m_vehicle
                _add(gun['model'], m_gun,
                     f"{wp['name']} -> {gun['name']}", 'gun')
        if attachments:
            n_veh += 1

    out = {k: v for k, v in out.items() if v}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=1)
    print(f"\nwrote {out_path}: {len(out)} vehicles, {n_att} attachments")
    for k, v in sorted(out.items()):
        print(f"  {k}: " + ", ".join(os.path.basename(e['model']) for e in v))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('xml', nargs='+', help='entitylibrary_full converted XMLs')
    ap.add_argument('--game', choices=('avatar', 'fc2'), required=True)
    ap.add_argument('--data-root', required=True,
                    help='extracted data root containing graphics/')
    args = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, 'canvas', 'assets', args.game,
                       'vehicle_attachments.json')
    bake(args.xml, args.game, args.data_root, out)


if __name__ == '__main__':
    main()
