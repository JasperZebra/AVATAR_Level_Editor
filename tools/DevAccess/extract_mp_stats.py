"""
Extract every multiplayer stat from gamemodesconfig.xml, resolve inheritance
(parent=), and emit a machine-readable table with the CRC-32 keys the engine
uses at runtime.

The engine never stores the stat NAME. CStringID is a hash, and the string
"kills" does not appear anywhere in Dunia.dll -- so anything reading stats out
of memory has to match on the hash and map back to the name with this table.

Usage:
    python extract_mp_stats.py [path\to\gamemodesconfig.xml] [out.json]

The default path is where the game's data sits on the author's machine; pass
your own unpacked data folder's copy if it differs.  Far Cry 2 ships the same
file with a different (larger) stat list -- give it a different output name, or
it lands on top of the Avatar table:

    python extract_mp_stats.py "...\Far Cry 2...\gamemodesconfig.xml" mp_stats_fc2.json

Avatar's patch copy is Dunia BINARY xml, not text.  It decodes to the same
schema as the loose data/ copy (verified), so the text one is what this reads.
Decode the binary one with tools/convert_avatar_xml.py if you need to re-check.
"""
import json, os, sys, zlib
import xml.etree.ElementTree as ET

DEFAULT_XML = (r"C:\Users\sambe\Desktop\____AVATAR_STUFF\__GameFilesPC"
               r"\data\engine\gamemodes\gamemodesconfig.xml")
XML = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_XML
OUT = os.path.dirname(os.path.abspath(__file__))
DST = os.path.join(OUT, sys.argv[2] if len(sys.argv) > 2 else 'mp_stats.json')

if not os.path.isfile(XML):
    raise SystemExit(
        "gamemodesconfig.xml not found:\n  %s\n"
        "Pass the path to your unpacked copy as the first argument." % XML)


def crc32(s):
    return zlib.crc32(s.encode('ascii')) & 0xFFFFFFFF


root = ET.parse(XML).getroot()
svc = root.find('.//GameStatsService')

# ---- collect each game mode's own lists -----------------------------------
modes = {}
for mode in svc:
    ent = {'parent': mode.get('parent'), 'stats': {}, 'gamestats': {}}
    for listname, key in (('StatsList', 'stats'), ('GameStatsList', 'gamestats')):
        lst = mode.find(listname)
        if lst is None:
            continue
        for st in lst:
            rec = {
                'name': st.get('name'),
                'kind': st.tag,                      # Stat / StatRatio / StatDiff
                'live': st.get('livereplication') == '1',
                'displayable': st.get('displayable') == '1',
                'reset': st.get('reset') == '1',
                'default': st.get('defaultValue'),
                'topStat': st.get('topStat'), 'subStat': st.get('subStat'),
                'statA': st.get('statA'), 'statB': st.get('statB'),
                'modifiers': {m.get('name'): int(m.get('value'))
                              for m in st.findall('Modifier')},
            }
            ent[key][st.get('name')] = {k: v for k, v in rec.items() if v not in (None, {}, False)}
    modes[mode.tag] = ent


# ---- resolve parent= inheritance (child overrides win) --------------------
def resolve(name, seen=()):
    if name in seen:
        raise RuntimeError('parent cycle at %s' % name)
    m = modes[name]
    out = {'stats': {}, 'gamestats': {}}
    if m['parent']:
        base = resolve(m['parent'], seen + (name,))
        out['stats'].update(base['stats'])
        out['gamestats'].update(base['gamestats'])
    for k in ('stats', 'gamestats'):
        for sn, sv in m[k].items():
            merged = dict(out[k].get(sn, {}))
            merged.update(sv)
            out[k][sn] = merged
    return out


resolved = {n: resolve(n) for n in modes}

# ---- the union of every stat name, with hashes ---------------------------
allnames = set()
for r in resolved.values():
    allnames |= set(r['stats']) | set(r['gamestats'])

table = []
for n in sorted(allnames):
    table.append({
        'name': n,
        'crc32': '%08X' % crc32(n),
        'crc32_lower': '%08X' % crc32(n.lower()),
        'in_modes': sorted(m for m, r in resolved.items()
                           if n in r['stats'] or n in r['gamestats']),
    })

# collision check -- a hash table is only usable if the keys are unique
for field in ('crc32', 'crc32_lower'):
    seen = {}
    for t in table:
        seen.setdefault(t[field], []).append(t['name'])
    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    print('%-12s collisions: %s' % (field, dupes or 'none'))

print('\ngame modes with stat lists : %d' % len(modes))
print('distinct stat names        : %d' % len(allnames))
mp = [m for m in resolved if m != 'FCXSingle']
mpnames = set()
for m in mp:
    mpnames |= set(resolved[m]['stats']) | set(resolved[m]['gamestats'])
print('multiplayer stat names     : %d' % len(mpnames))
print('live-replicated (any mode) : %d' % len(
    {s['name'] for r in resolved.values() for s in r['stats'].values() if s.get('live')}))

json.dump({'source': XML, 'modes': resolved, 'names': table},
          open(DST, 'w'), indent=2)
print('\nwrote %s' % os.path.basename(DST))

print('\nper-mode totals:')
for m in sorted(resolved):
    r = resolved[m]
    print('  %-22s %3d player stats, %d game stats%s'
          % (m, len(r['stats']), len(r['gamestats']),
             '   (parent=%s)' % modes[m]['parent'] if modes[m]['parent'] else ''))
