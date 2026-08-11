"""
Build a global catalog of Environment preset GUIDs across every map/world.

A map's .game.xml Environment slots (Sky/Sun/Lighting/Fog/…) store a GUID that
is a foreign key into that map's managers.xml DataBaseItemManager. Each map only
carries a COPY of the presets it uses — so to reuse a sky from another map you
need to know that map's preset GUIDs. This tool scans every converted
<map>.managers.xml (both games), pulls out every CEnvironment* Template
(name + GUID + class + which maps define it), dedupes by GUID and writes a single
JSON catalog the World Editor loads so its slot dropdowns can offer presets from
ANY map, grouped by category (class).

Run:  python tools/build_env_preset_catalog.py [--out env_preset_catalog.json] [root ...]
Defaults scan the known Avatar + FC2 unpacked data roots.
"""

import os
import re
import sys
import json
import argparse


def find_managers(root):
    """All *.managers.xml under root. os.walk (not glob) so dot-directories
    like FC2's '...MODDING' are traversed."""
    hits = []
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if fn.lower().endswith('.managers.xml'):
                hits.append(os.path.join(dirpath, fn))
    return hits

DEFAULT_ROOTS = [
    (r"C:\Users\sambe\Desktop\____AVATAR_STUFF\__GameFilesPC", "avatar"),
    (r"C:\Users\sambe\Desktop\____AVATAR_STUFF\Far Cry 2 Fortune's Edition", "farcry2"),
]

RE_NAME = re.compile(r'name="text_NameId" value-String="([^"]*)"')
RE_TMPL = re.compile(r'name="text_Template" value-String="(\{[0-9A-Fa-f-]+\})"')
RE_CLS = re.compile(r'name="text_hid_DTCTH_ClassName" value-String="([^"]*)"')


def scan_managers(path):
    """Yield (classname, nameid, guid) for every CEnvironment* Template."""
    last_name = None
    pending = None
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                m = RE_NAME.search(line)
                if m:
                    last_name = m.group(1)
                    continue
                m = RE_TMPL.search(line)
                if m:
                    pending = (m.group(1), last_name)
                    continue
                m = RE_CLS.search(line)
                if m and pending:
                    cls = m.group(1)
                    if cls.startswith('CEnvironment'):
                        yield cls, (pending[1] or '(unnamed)'), pending[0]
                    pending = None
    except OSError as e:
        print(f"  ! {path}: {e}")


def build(roots, out_path):
    # guid -> record
    by_guid = {}
    maps_scanned = 0
    for root, game in roots:
        files = find_managers(root)
        print(f"{game}: {len(files)} managers.xml under {root}")
        for fp in files:
            map_name = os.path.basename(fp)[:-len('.managers.xml')]
            maps_scanned += 1
            n = 0
            for cls, name, guid in scan_managers(fp):
                rec = by_guid.get(guid)
                if rec is None:
                    by_guid[guid] = rec = {
                        'name': name, 'class': cls, 'game': game, 'maps': []
                    }
                if map_name not in rec['maps']:
                    rec['maps'].append(map_name)
                # prefer a non-"(unnamed)" name if we later find one
                if rec['name'] in ('(unnamed)', '') and name:
                    rec['name'] = name
                n += 1
            if n:
                print(f"    {map_name}: {n} env presets")

    # group by class
    categories = {}
    for guid, rec in by_guid.items():
        categories.setdefault(rec['class'], []).append({
            'name': rec['name'], 'guid': guid, 'game': rec['game'],
            'maps': sorted(rec['maps']),
        })
    for cls in categories:
        categories[cls].sort(key=lambda e: (e['name'].lower(), e['guid']))

    catalog = {
        'categories': categories,
        'stats': {
            'maps_scanned': maps_scanned,
            'unique_presets': len(by_guid),
            'by_class': {c: len(v) for c, v in sorted(categories.items())},
        },
    }
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(catalog, f, indent=1, ensure_ascii=False)
    print(f"\nWrote {out_path}")
    print(f"  {maps_scanned} maps scanned, {len(by_guid)} unique presets")
    for c, n in sorted(catalog['stats']['by_class'].items()):
        print(f"    {c:34} {n}")
    return catalog


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('roots', nargs='*', help='extra data roots to scan (avatar game assumed)')
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument('--out', default=os.path.join(repo, 'env_preset_catalog.json'))
    args = ap.parse_args()
    roots = list(DEFAULT_ROOTS) + [(r, 'avatar') for r in args.roots]
    roots = [(r, g) for r, g in roots if os.path.isdir(r)]
    if not roots:
        print("No data roots found — pass one as an argument.")
        return 1
    build(roots, args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
