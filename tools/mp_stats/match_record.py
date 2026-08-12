"""
The match record -- the one thing the game side and the server side must agree
on.

Deliberately a plain dict with a version tag, serialised as JSON Lines: one
complete match per line, appended, never rewritten.  That format is chosen for
the writer, not the reader -- the DLL appends a line and closes, so a crash
mid-match costs at most the line being written, and a half-written last line is
skipped by the reader instead of corrupting the file.

Stat names are exactly as they appear in gamemodesconfig.xml, case included.
See tools/DevAccess/MP_STATS.md -- the engine keys them by CRC-32 of the
exact-case string, so "headshotKills" is the name, not "headshotkills".
"""
import json

SCHEMA = 1

# Filled in by the game side.  Everything is optional except match_id and
# players, because a half-known match is still worth having.
TEMPLATE = {
    'schema': SCHEMA,
    'match_id': None,        # stable unique id -- the upload key, see below
    'recorded_utc': None,    # ISO-8601, when the record was written
    'map': None,             # e.g. "mp_...";  net_GetCurrentMapName
    'gamemode': None,        # e.g. "FCXTeamDeathMatch"
    'duration_s': None,
    'host': None,            # net_GetHostName, if we can get it
    'players': [],           # [{name, team, stats:{...}}]
    'game_stats': {},        # redTeamScore / blueTeamScore / gameCancelled / ...
}


class BadRecord(ValueError):
    pass


def validate(rec):
    """Raise BadRecord if this could not safely be sent to the server.

    Kept strict about the two fields the server keys on and lenient about
    everything else -- a match missing its map name is still worth storing;
    a match with no id cannot be deduplicated and must not be sent.
    """
    if not isinstance(rec, dict):
        raise BadRecord('not an object: %r' % type(rec).__name__)
    if rec.get('schema') != SCHEMA:
        raise BadRecord('schema %r, expected %r' % (rec.get('schema'), SCHEMA))
    mid = rec.get('match_id')
    if not isinstance(mid, str) or not mid.strip():
        raise BadRecord('match_id missing or empty')
    players = rec.get('players')
    if not isinstance(players, list):
        raise BadRecord('players is not a list')
    for i, p in enumerate(players):
        if not isinstance(p, dict):
            raise BadRecord('player %d is not an object' % i)
        if not isinstance(p.get('name'), str) or not p['name']:
            raise BadRecord('player %d has no name' % i)
        st = p.get('stats', {})
        if not isinstance(st, dict):
            raise BadRecord('player %d stats is not an object' % i)
        for k, v in st.items():
            # The engine stores stats as float (CStatServiceAdapter::GetStatInfo
            # hands back a float&), so do not insist on int here.
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise BadRecord('player %d stat %r is %r, not a number'
                                % (i, k, type(v).__name__))
    return rec


def dumps(rec):
    """One record -> one line.  No embedded newlines, ever."""
    validate(rec)
    return json.dumps(rec, separators=(',', ':'), sort_keys=True)


def iter_file(path, start_offset=0):
    """Yield (end_offset, record_or_None, raw_line) for each complete line.

    A trailing partial line -- the writer was mid-append -- is NOT yielded, and
    the offset stays before it so the next pass picks it up whole.  This is the
    whole reason the reader tracks a byte offset rather than a line count.
    """
    with open(path, 'rb') as fh:
        fh.seek(start_offset)
        buf = fh.read()
    off = start_offset
    for raw in buf.splitlines(keepends=True):
        if not raw.endswith((b'\n', b'\r')):
            break                      # partial trailing line -- leave it
        off += len(raw)
        text = raw.decode('utf-8', errors='replace').strip()
        if not text:
            continue
        try:
            rec = validate(json.loads(text))
        except (ValueError, BadRecord):
            rec = None                 # malformed: report, skip, keep going
        yield off, rec, text
