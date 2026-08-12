"""
A reference receiver -- the smallest server that correctly accepts what
stats_uploader.py sends.

This is NOT the production stats site.  It exists so the game-side and
uploader can be exercised end to end before the real server exists, and so the
real server has an unambiguous statement of the contract it has to honour:

  POST <endpoint>
    Content-Type:    application/json
    Idempotency-Key: <match_id>
    Authorization:   Bearer <token>      (only if a token is configured)

  201  stored
  200  already had it -- same match_id seen before  (NOT an error)
  400  malformed / failed validation                (permanent, do not retry)
  401  bad or missing token                         (permanent)
  5xx  our problem                                  (retry)

The 200-vs-201 split is the whole reason delivery can be at-least-once: the
uploader may resend a record it already sent, and that must be boring.

Usage:
    python stats_receiver.py --port 8778 --store matches/ [--token SECRET]
"""
import argparse, json, os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from match_record import BadRecord, validate  # noqa: E402

MAX_BODY = 4 * 1024 * 1024          # a match record is a few KB; refuse absurdity
_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server_version = 'AvatarStats/1.0'
    store = None
    token = None

    def _reply(self, code, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *a):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % a))

    def do_GET(self):
        """A tiny summary, so you can see it working in a browser."""
        if self.path.rstrip('/') not in ('', '/matches'):
            return self._reply(404, {'error': 'not found'})
        with _lock:
            names = sorted(os.listdir(self.store)) if os.path.isdir(self.store) else []
        return self._reply(200, {'stored': len(names), 'match_ids':
                                 [n[:-5] for n in names if n.endswith('.json')][:200]})

    def do_POST(self):
        if self.token:
            got = self.headers.get('Authorization', '')
            if got != 'Bearer ' + self.token:
                return self._reply(401, {'error': 'bad token'})

        try:
            n = int(self.headers.get('Content-Length', 0))
        except ValueError:
            return self._reply(400, {'error': 'bad Content-Length'})
        if n <= 0 or n > MAX_BODY:
            return self._reply(400, {'error': 'body size %d rejected' % n})

        try:
            rec = validate(json.loads(self.rfile.read(n).decode('utf-8')))
        except BadRecord as e:
            return self._reply(400, {'error': 'invalid record: %s' % e})
        except (UnicodeDecodeError, ValueError) as e:
            return self._reply(400, {'error': 'not JSON: %s' % e})

        # match_id comes from the game and lands in a filename -- never trust it
        # as a path.  Anything but [A-Za-z0-9._-] is rejected outright rather
        # than sanitised, so a weird id is visible instead of silently renamed.
        mid = rec['match_id']
        if not all(c.isalnum() or c in '._-' for c in mid) or mid.startswith('.'):
            return self._reply(400, {'error': 'unsafe match_id'})

        path = os.path.join(self.store, mid + '.json')
        with _lock:
            if os.path.exists(path):
                return self._reply(200, {'status': 'duplicate', 'match_id': mid})
            os.makedirs(self.store, exist_ok=True)
            tmp = path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(rec, fh, indent=2, sort_keys=True)
            os.replace(tmp, path)
        return self._reply(201, {'status': 'stored', 'match_id': mid,
                                 'players': len(rec['players'])})


def main(argv=None):
    ap = argparse.ArgumentParser(description='reference stats receiver')
    ap.add_argument('--port', type=int, default=8778)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--store', default='matches')
    ap.add_argument('--token', default=os.environ.get('AVATAR_STATS_TOKEN'))
    args = ap.parse_args(argv)

    Handler.store = os.path.abspath(args.store)
    Handler.token = args.token
    os.makedirs(Handler.store, exist_ok=True)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print('receiver on http://%s:%d  -> %s%s'
          % (args.host, args.port, Handler.store,
             '  (token required)' if args.token else '  (NO token -- dev only)'),
          flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
