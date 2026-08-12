"""
Ship match records from the game machine to our stats server.

Runs as a SEPARATE process, not inside the game.  That is the whole point:

  * A blocking HTTP POST on the game thread at match end would hitch or hang
    the game, and the console DLL runs on hooked engine threads.
  * The server being down, slow or unreachable then becomes a game bug.
  * The DLL stays free of network code, which matters for a thing that already
    has to explain itself to antivirus (see console_dll DISTRIBUTION.md).

So the DLL's only job is: append one JSON line per match to a file, and close
it.  This process does everything that can fail.

Delivery is at-least-once, deduplicated server-side by match_id -- retrying a
POST we already sent is safe and expected.  Progress is a byte offset in a
state file, so a restart resumes rather than re-uploading the season.

Usage:
    python stats_uploader.py --file  <matches.jsonl> \
                             --url   https://stats.example/api/matches \
                             [--token SECRET] [--once] [--interval 15]

stdlib only, so it runs anywhere Python does with no pip install.
"""
import argparse, json, os, sys, time, urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from match_record import iter_file  # noqa: E402

DEFAULT_INTERVAL = 15.0
MAX_BACKOFF = 300.0
TIMEOUT = 20.0


def log(msg):
    print('%s  %s' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg), flush=True)


def load_state(path):
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {'offset': 0, 'sent': 0, 'failed': 0}


def save_state(path, state):
    """Write via a temp file + replace so a kill mid-write cannot corrupt it.

    Losing this file is not fatal -- it re-uploads, and the server dedupes --
    but a truncated one that parses as offset 0 would silently do exactly that
    on every restart.
    """
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(state, fh)
    os.replace(tmp, path)


def post(url, token, rec):
    """POST one record.  Returns (ok, permanent_failure, detail).

    A 4xx other than 408/429 is permanent -- the record is malformed or
    rejected, and retrying forever would wedge the queue behind it.  Anything
    else is worth another go.
    """
    body = json.dumps(rec).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Idempotency-Key', rec['match_id'])
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return True, False, '%s' % resp.status
    except urllib.error.HTTPError as e:
        permanent = 400 <= e.code < 500 and e.code not in (408, 429)
        return False, permanent, 'HTTP %s' % e.code
    except (urllib.error.URLError, OSError) as e:
        return False, False, '%s' % (getattr(e, 'reason', None) or e)


def drain(args, state):
    """Send everything new in the file.  Returns True if fully drained."""
    if not os.path.isfile(args.file):
        return True                     # nothing written yet; not an error

    size = os.path.getsize(args.file)
    if size < state['offset']:
        log('file shrank (%d < %d) -- rotated or recreated, starting over'
            % (size, state['offset']))
        state['offset'] = 0

    for end_off, rec, raw in iter_file(args.file, state['offset']):
        if rec is None:
            log('SKIP malformed line at offset %d: %.120s' % (end_off, raw))
            state['offset'] = end_off
            state['failed'] += 1
            save_state(args.state, state)
            continue

        ok, permanent, detail = post(args.url, args.token, rec)
        if ok:
            state['offset'] = end_off
            state['sent'] += 1
            save_state(args.state, state)
            log('sent %s (%d players) [%s]'
                % (rec['match_id'], len(rec['players']), detail))
        elif permanent:
            # Do not block the queue on a record the server will never accept.
            state['offset'] = end_off
            state['failed'] += 1
            save_state(args.state, state)
            log('REJECTED %s [%s] -- skipping permanently'
                % (rec['match_id'], detail))
        else:
            log('retry later: %s [%s]' % (rec['match_id'], detail))
            return False                # keep the offset; try this one again
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('--file', required=True, help='matches.jsonl the game writes')
    ap.add_argument('--url', required=True, help='POST endpoint')
    ap.add_argument('--token', default=os.environ.get('AVATAR_STATS_TOKEN'),
                    help='bearer token (or set AVATAR_STATS_TOKEN)')
    ap.add_argument('--state', default=None, help='progress file')
    ap.add_argument('--interval', type=float, default=DEFAULT_INTERVAL)
    ap.add_argument('--once', action='store_true',
                    help='drain and exit instead of watching')
    args = ap.parse_args(argv)
    if args.state is None:
        args.state = args.file + '.uploaded'

    state = load_state(args.state)
    log('watching %s from offset %d -> %s' % (args.file, state['offset'], args.url))

    backoff = args.interval
    while True:
        try:
            drained = drain(args, state)
        except OSError as e:
            log('read error: %s' % e)
            drained = False

        if args.once:
            log('done: %d sent, %d failed, offset %d'
                % (state['sent'], state['failed'], state['offset']))
            return 0 if drained else 1

        if drained:
            backoff = args.interval
        else:
            backoff = min(backoff * 2, MAX_BACKOFF)
            log('backing off %.0fs' % backoff)
        time.sleep(backoff)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
