"""
Copy environment preset Templates between maps so a cross-map preset chosen in
the World Editor actually resolves in-game.

A map's .game.xml Environment slot stores a preset GUID that is a foreign key
into that map's managers DataBaseItemManager. Each preset is a self-contained
``<object name="Template">`` inside the ``<object name="Templates">`` container.
To make a preset from ANOTHER map work here, we copy that Template subtree into
this map's managers.xml and rebuild managers.fcb (what the game reads).

FCB rebuild: `fcb_convert.xml_to_fcb` normally replays a byte-exact dedup
decision stream recorded in a leading ``<!--fcb_meta-->`` comment — that stream
is tied to the ORIGINAL tree and cannot survive an edit. ElementTree drops the
comment on round-trip, so `xml_to_fcb` falls back to encoding the (modified)
tree from scratch — a valid, if not byte-identical, FCB. Verified: a rebuilt
managers.fcb reads back with the added preset present.
"""

import os
import copy
import shutil
import xml.etree.ElementTree as ET


def _container(root):
    """The DataBaseItemManager's <object name="Templates"> that holds presets."""
    for o in root.iter('object'):
        if o.get('name') == 'Templates' and any(
                c.tag == 'object' and c.get('name') == 'Template' for c in o):
            return o
    return None


def _guid(tmpl):
    for f in tmpl:
        if f.tag == 'field' and f.get('name') == 'text_Template':
            return f.get('value-String')
    return None


def _templates(cont):
    return [o for o in cont if o.tag == 'object' and o.get('name') == 'Template']


def index_managers(search_roots):
    """{map_name: managers.xml path} for every managers.xml under the roots
    (os.walk so FC2's '...MODDING' dot-dir is traversed). First hit wins."""
    idx = {}
    for root in search_roots:
        if not root or not os.path.isdir(root):
            continue
        for dp, _dirs, files in os.walk(root):
            for fn in files:
                low = fn.lower()
                if low.endswith('.managers.xml'):
                    name = fn[:-len('.managers.xml')]
                    idx.setdefault(name, os.path.join(dp, fn))
    return idx


def copy_presets(current_managers_xml, guid_to_maps, search_roots,
                 rebuild_fcb=True, log=print):
    """Copy the named preset GUIDs into *current_managers_xml* from their source
    maps, then rebuild the sibling managers.fcb.

    guid_to_maps : {guid: [candidate source map names]} (from the catalog).
    Returns {ok, copied:[(guid,srcmap)], missing:[guid], skipped:[guid], fcb, error?}.
    """
    try:
        tree = ET.parse(current_managers_xml)
    except Exception as e:
        return {'ok': False, 'error': f'parse failed: {e}',
                'copied': [], 'missing': [], 'skipped': []}
    root = tree.getroot()
    cont = _container(root)
    if cont is None:
        return {'ok': False, 'error': 'no Templates container in this map',
                'copied': [], 'missing': [], 'skipped': []}

    have = {_guid(t) for t in _templates(cont)}
    copied, missing, skipped = [], [], []

    idx = index_managers(search_roots)
    src_tree_cache = {}

    def _src_container(map_name):
        p = idx.get(map_name)
        if not p:
            return None
        if map_name not in src_tree_cache:
            try:
                src_tree_cache[map_name] = _container(ET.parse(p).getroot())
            except Exception:
                src_tree_cache[map_name] = None
        return src_tree_cache[map_name]

    for guid, maps in guid_to_maps.items():
        if guid in have:
            skipped.append(guid)
            continue
        tmpl = used = None
        for m in maps:
            sc = _src_container(m)
            if sc is None:
                continue
            for st in _templates(sc):
                if _guid(st) == guid:
                    tmpl, used = copy.deepcopy(st), m
                    break
            if tmpl is not None:
                break
        if tmpl is None:
            missing.append(guid)
            continue
        cont.append(tmpl)
        have.add(guid)
        copied.append((guid, used))
        log(f"  copied {guid} from {used}")

    result = {'ok': True, 'copied': copied, 'missing': missing,
              'skipped': skipped, 'fcb': None}
    if copied:
        if not os.path.isfile(current_managers_xml + '.bak'):
            shutil.copy2(current_managers_xml, current_managers_xml + '.bak')
        tree.write(current_managers_xml, encoding='utf-8', xml_declaration=True)
        if rebuild_fcb:
            try:
                result['fcb'] = _rebuild_fcb(root, current_managers_xml, log=log)
            except Exception as e:
                result['ok'] = False
                result['error'] = f'FCB rebuild failed: {e}'
    return result


def _rebuild_fcb(root, managers_xml_path, log=print):
    """Encode the modified tree to <map>.managers.fcb (encode-from-scratch)."""
    import sys
    tools = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools')
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import fcb_convert

    # ET.tostring has no fcb_meta comment → xml_to_fcb encodes from scratch,
    # which (unlike the dedup stream) tolerates our added Template.
    xml_text = ET.tostring(root, encoding='unicode')
    data = fcb_convert.xml_to_fcb(xml_text)

    fcb_path = managers_xml_path[:-len('.xml')] + '.fcb'  # .managers.xml → .managers.fcb
    if os.path.isfile(fcb_path) and not os.path.isfile(fcb_path + '.bak'):
        shutil.copy2(fcb_path, fcb_path + '.bak')
    with open(fcb_path, 'wb') as f:
        f.write(data)
    log(f"  rebuilt {os.path.basename(fcb_path)} ({len(data):,} bytes)")
    return fcb_path
