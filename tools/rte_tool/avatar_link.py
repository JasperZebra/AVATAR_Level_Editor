"""avatar_link.py - client for the live editor link in avatar_console.dll.

Transport only: no Qt, no GUI, no game knowledge beyond the wire format. Import
this from anything; run it directly for a self-test against a live game.

THE PROTOCOL, derived from the server (avatar_console.c, LinkThread / LinkTick).
There is no separate spec, so every rule below cites the code it came from.

  pipe      \\.\pipe\avatar_editor
            CreateNamedPipeA(PIPE_ACCESS_DUPLEX,
                             PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_NOWAIT,
                             1, 64K, 64K)                      [LinkThread]
            BYTE mode, not MESSAGE mode - so a "read one reply" is a read until
            the sentinel, never a single ReadFile.

  request   one line, `verb arg arg...\n`, ASCII.
            '\r' is skipped by the server, empty lines are ignored, and the
            literal `bye` closes the session cleanly.          [LinkThread]
            Max 512 bytes including the NUL (LNK_REQ_MAX), split on whitespace
            into at most 8 argv slots - so at most 7 arguments.

  reply     JSON Lines, terminated by a line carrying an "end" key.
            Failure is {"ok":false,"cmd":..,"error":..} then {"end":..}.
                                                               [LnkFail]

  THREE TRAPS, each of which will hang or corrupt a naive client:

  1. `poslist` rows are NOT JSON. The verb's own comment says so - it is the one
     path where readability loses to cost. You get one JSON header line, then
     `HI:LO x y z` as plain text per entity, then the JSON end line. A client
     that json.loads() every line dies on row one. We keep raw rows separately.

  2. THE TIMEOUT REPLY ENDS WITH {"end":"?"}, NOT with your verb. When the frame
     loop does not answer within 4 s (a world change is modal for seconds), the
     server writes a canned busy block whose cmd and end are both the literal
     "?".                                                      [LinkThread]
     So the read loop must stop on "an object with an 'end' key", never on
     'end' == the verb it asked for. That would hang for ever on every world
     load.

  3. THE END SENTINEL CAN BE DROPPED ON A BIG REPLY. LnkPut refuses to append
     once the buffer is within 600 bytes of LNK_OUT_MAX (1 MB):
         if (len >= LNK_OUT_MAX - 600) return;
     That guard rejects the write rather than truncating it, and it applies to
     the final {"end":...} line exactly as it does to a data row. So a reply
     that reaches the cap loses its terminator and a client reading until the
     sentinel blocks for ever.
     Defence, both halves needed:
       - always pass a `cap` on list/listx/poslist (all three accept one), and
       - always read against a deadline, which is what recv_deadline does here.
     Reported upstream; until it is fixed in the DLL this is the client's job.

  COST. These calls run INSIDE the game's per-frame detour, on its main thread.
  Numbers measured by the DLL author, not guessed:
      poslist  ~24 ms      listx  ~95 ms for 1,251 entities
      bones    ~438 ms for 8 characters
  Poll on demand and keep a slow heartbeat. A 30 Hz refresh would eat the frame
  budget outright - `poslist` exists precisely because `listx` at 15 Hz was 143%
  of a 60 FPS frame.

  ONE CLIENT AT A TIME - CreateNamedPipe is called with nMaxInstances = 1. If
  another tool holds the pipe, connect() raises Busy. That is the whole reason
  the error is its own class.
"""

import ctypes
import ctypes.wintypes as wt
import json
import time

PIPE_PREFIX = "\\\\.\\pipe\\"
PIPE_NAME = PIPE_PREFIX + "avatar_editor"

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE = ctypes.c_void_p(-1).value
ERROR_PIPE_BUSY = 231
ERROR_FILE_NOT_FOUND = 2

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = wt.HANDLE
_k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p,
                             wt.DWORD, wt.DWORD, wt.HANDLE]
_k32.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD,
                          ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
_k32.WriteFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD,
                           ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
_k32.PeekNamedPipe.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD,
                               ctypes.POINTER(wt.DWORD), ctypes.POINTER(wt.DWORD),
                               ctypes.POINTER(wt.DWORD)]
_k32.CloseHandle.argtypes = [wt.HANDLE]


def discover(prefix="avatar_editor"):
    """-> every Avatar link pipe currently being served, canonical one first.

    More than one game can be running now that the single-instance gate can be
    opened. The DLL serves `avatar_editor` to whichever instance starts first
    and `avatar_editor_<pid>` to the rest, so a client that only ever opens the
    canonical name would silently always talk to instance one.

    \\\\.\\pipe\\ is enumerable as a directory - FindFirstFile over it lists the
    live pipe objects, which is the only way to see them (there is no registry
    of names and a pipe that is not being served does not exist at all).
    """
    import glob
    names = []
    for path in glob.glob(r"\\.\pipe\*"):
        name = path.rsplit("\\", 1)[-1]
        if name == prefix or name.startswith(prefix + "_"):
            names.append(name)
    names.sort(key=lambda n: (n != prefix, n))     # canonical first
    return names


class LinkError(Exception):
    """Any failure of the link itself (not a failure reported BY the game)."""


class NotConnected(LinkError):
    pass


class Busy(LinkError):
    """Another client holds the pipe. The server allows exactly one."""


class Timeout(LinkError):
    """No complete reply inside the deadline. See trap 3 in the module docstring."""


class Reply(object):
    """One request's answer, already split by kind.

    ok      the server's own verdict, from the header line's "ok" field.
    head    the first JSON object (the header), or {} if there wasn't one.
    rows    every JSON object between header and end - list/listx entity lines,
            bones matrices, addr pointers.
    raw     every NON-JSON line, in order. Only `poslist` produces these.
    error   the "error" string when ok is False, else None.
    busy    True when this is the server's 4 s frame-loop-did-not-answer reply,
            which is a different thing from a verb failing. Callers that retry
            should retry on this and not on a real error.
    """

    __slots__ = ("ok", "head", "rows", "raw", "error", "busy", "verb", "seconds")

    def __init__(self, verb):
        self.verb = verb
        self.ok = False
        self.head = {}
        self.rows = []
        self.raw = []
        self.error = None
        self.busy = False
        self.seconds = 0.0

    def positions(self):
        """poslist's raw rows as (id, x, y, z). Ignores anything malformed."""
        out = []
        for line in self.raw:
            parts = line.split()
            if len(parts) != 4:
                continue
            try:
                out.append((parts[0], float(parts[1]), float(parts[2]),
                            float(parts[3])))
            except ValueError:
                continue
        return out

    def __repr__(self):
        if self.busy:
            return "<Reply %s BUSY>" % self.verb
        if not self.ok:
            return "<Reply %s FAILED %r>" % (self.verb, self.error)
        return "<Reply %s ok rows=%d raw=%d %.0fms>" % (
            self.verb, len(self.rows), len(self.raw), self.seconds * 1000.0)


class AvatarLink(object):
    """A connection to the live editor link. Not thread-safe by design.

    One request is in flight at a time - that is the server's state machine
    (IDLE -> REQ -> DONE), not a limitation of this class. Drive it from a
    single worker thread; see rte_tool.LinkWorker.
    """

    def __init__(self, pipe_name=None):
        """pipe_name None means "pick one": the canonical link if it is being
        served, else the first pid-suffixed one. Pass a name from discover() to
        target a specific game when several are running."""
        self.pipe_name = pipe_name or PIPE_NAME
        self.requested = pipe_name
        self._h = None
        self._buf = b""

    # -- lifecycle ---------------------------------------------------------

    @property
    def connected(self):
        return self._h is not None

    def connect(self):
        if self._h is not None:
            return
        # Only auto-pick when the caller did not name one. Resolving every time
        # would silently move an explicit target.
        if self.requested is None:
            found = discover()
            if found:
                self.pipe_name = PIPE_PREFIX + found[0]
        h = _k32.CreateFileW(self.pipe_name, GENERIC_READ | GENERIC_WRITE,
                             0, None, OPEN_EXISTING, 0, None)
        if h == INVALID_HANDLE or h is None:
            err = ctypes.get_last_error()
            if err == ERROR_PIPE_BUSY:
                raise Busy("another client already holds %s - the DLL allows "
                           "exactly one at a time" % self.pipe_name)
            if err == ERROR_FILE_NOT_FOUND:
                raise NotConnected(
                    "%s does not exist. The game must be running with the mod "
                    "loaded AND a level loaded - the link only listens once the "
                    "console object exists. Check for '[link] listening on' in "
                    "avatar_console_dll.log." % self.pipe_name)
            raise LinkError("CreateFile on %s failed, error %d"
                            % (self.pipe_name, err))
        self._h = h
        self._buf = b""

    def close(self):
        """Say `bye` if we can, then drop the handle either way.

        `bye` is the server's own clean-exit token; without it the session ends
        when PeekNamedPipe notices the handle is gone, which is equally fine but
        logs as a disconnect rather than a close.
        """
        if self._h is None:
            return
        try:
            self._write(b"bye\n")
        except LinkError:
            pass
        try:
            _k32.CloseHandle(self._h)
        finally:
            self._h = None
            self._buf = b""

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    # -- raw io ------------------------------------------------------------

    def _write(self, data):
        if self._h is None:
            raise NotConnected("not connected")
        wrote = wt.DWORD(0)
        off = 0
        while off < len(data):
            chunk = data[off:]
            if not _k32.WriteFile(self._h, chunk, len(chunk),
                                  ctypes.byref(wrote), None):
                raise LinkError("WriteFile failed, error %d"
                                % ctypes.get_last_error())
            if wrote.value == 0:
                raise LinkError("pipe accepted no bytes - the game is gone")
            off += wrote.value

    def _pump(self):
        """Move whatever is already in the pipe into our buffer. Never blocks.

        PeekNamedPipe first, exactly as the server does on its side: ReadFile on
        a byte-mode pipe blocks until at least one byte arrives, and a blocking
        read is what makes a timeout impossible to honour.
        """
        avail = wt.DWORD(0)
        if not _k32.PeekNamedPipe(self._h, None, 0, None,
                                  ctypes.byref(avail), None):
            raise LinkError("the game closed the link (PeekNamedPipe error %d)"
                            % ctypes.get_last_error())
        if not avail.value:
            return 0
        buf = ctypes.create_string_buffer(avail.value)
        got = wt.DWORD(0)
        if not _k32.ReadFile(self._h, buf, avail.value, ctypes.byref(got), None):
            raise LinkError("ReadFile failed, error %d" % ctypes.get_last_error())
        self._buf += buf.raw[:got.value]
        return got.value

    # -- request / response ------------------------------------------------

    def request(self, line, timeout=8.0):
        """Send one request line, return its Reply.

        `timeout` is a real deadline, not a hint: it covers trap 3 (a dropped
        end sentinel on an oversized reply) as well as an ordinary hang. Keep it
        comfortably above the server's own 4 s frame-loop timeout, or a world
        load will look like a client failure - the server WILL eventually answer
        that case, with busy=True.
        """
        if self._h is None:
            raise NotConnected("not connected")
        line = line.strip()
        if not line:
            raise LinkError("empty request")
        if len(line) >= 511:
            raise LinkError("request too long - the server's buffer is 512 bytes")

        verb = line.split()[0]
        # Anything still in the buffer belongs to a previous, abandoned reply.
        # Dropping it here is what stops one timeout from desynchronising every
        # request after it.
        self._buf = b""
        self._write(line.encode("ascii", "replace") + b"\n")

        started = time.time()
        deadline = started + timeout
        reply = Reply(verb)
        while True:
            nl = self._buf.find(b"\n")
            if nl < 0:
                if time.time() >= deadline:
                    raise Timeout(
                        "no end sentinel for %r after %.1fs. Either the frame "
                        "loop is stopped, or the reply hit the 1 MB cap and its "
                        "terminator was dropped - pass a smaller cap."
                        % (verb, timeout))
                if self._pump() == 0:
                    time.sleep(0.002)
                continue
            raw = self._buf[:nl]
            self._buf = self._buf[nl + 1:]
            text = raw.decode("utf-8", "replace").rstrip("\r")
            if not text:
                continue

            if not text.startswith("{"):
                reply.raw.append(text)          # trap 1: poslist rows
                continue
            try:
                obj = json.loads(text)
            except ValueError:
                reply.raw.append(text)
                continue

            if "end" in obj:                    # trap 2: match the KEY, not its value
                reply.seconds = time.time() - started
                return reply
            if not reply.head:
                reply.head = obj
                reply.ok = bool(obj.get("ok", False))
                reply.error = obj.get("error")
                # The canned 4 s reply is the only one whose cmd is "?" when we
                # did not ask "?" - that is how it is told apart from a verb
                # that genuinely failed.
                if not reply.ok and obj.get("cmd") == "?" and verb != "?":
                    reply.busy = True
            else:
                reply.rows.append(obj)

    # -- verbs -------------------------------------------------------------
    # One method per server verb. Each validates locally what the server would
    # reject anyway, so a mistake is a Python error with a useful message rather
    # than a round trip that comes back "unknown verb".

    def hello(self):
        return self.request("hello")

    def player(self):
        return self.request("player")

    def list_entities(self, cap=2000):
        return self.request("list %d" % int(cap))

    def listx(self, cap=2000, timeout=20.0):
        """listx is the expensive one - ~95 ms for 1,251 entities, on the game's
        main thread. Its default timeout is longer for that reason."""
        return self.request("listx %d" % int(cap), timeout=timeout)

    def poslist(self, cap=4000):
        return self.request("poslist %d" % int(cap))

    def get(self, ent_id):
        return self.request("get %s" % ent_id)

    def select(self, ent_id):
        return self.request("select %s" % ent_id)

    def move(self, ent_id, x, y, z):
        return self.request("move %s %.4f %.4f %.4f" % (ent_id, x, y, z))

    def bones(self, ent_id, slot=None, timeout=20.0):
        req = "bones %s" % ent_id
        if slot:
            req += " %s" % slot
        return self.request(req, timeout=timeout)

    def addr(self, timeout=20.0):
        return self.request("addr", timeout=timeout)

    def cvar(self, name, value):
        """Set one engine CVar through the game's own CConsole::ExecuteLine.

        The server validates that the name is a bare identifier and the value is
        numeric, and its comment explains why: this is deliberately NOT an exec
        verb, so that a level load or a quit cannot be smuggled through the pipe.
        We check the same two rules here so the failure is immediate and legible
        instead of a round trip.
        """
        name = str(name)
        if not name or not all(c.isalnum() or c == "_" for c in name):
            raise LinkError("cvar name must be a bare identifier: %r" % name)
        value = str(value)
        if not value or not all(c.isdigit() or c in ".-+" for c in value):
            raise LinkError("cvar value must be numeric: %r" % value)
        return self.request("cvar %s %s" % (name, value))


def _selftest():
    print("connecting to %s" % PIPE_NAME)
    with AvatarLink() as link:
        r = link.hello()
        if not r.ok:
            print("  hello failed: %s" % r.error)
            return 1
        h = r.head
        print("  proto %s  pid %s" % (h.get("proto"), h.get("pid")))
        print("  dll   %s" % h.get("dll"))
        print("  world %r  frame %s  level=%s"
              % (h.get("world"), h.get("frames"), h.get("level")))
        print("  round trip %.1f ms" % (r.seconds * 1000.0))

        if not h.get("level"):
            print("\n  No level loaded - the entity verbs will refuse. "
                  "Load a save and re-run.")
            return 0

        r = link.player()
        if r.ok:
            print("  player %r at %s" % (r.head.get("n"), r.head.get("p")))
        else:
            print("  player: %s" % r.error)

        r = link.poslist(cap=50)
        print("  poslist -> %d rows in %.1f ms"
              % (len(r.positions()), r.seconds * 1000.0))
        for row in r.positions()[:5]:
            print("      %s  %8.2f %8.2f %8.2f" % row)

        r = link.listx(cap=50)
        print("  listx   -> %d rows in %.1f ms"
              % (len(r.rows), r.seconds * 1000.0))
        for row in r.rows[:5]:
            print("      %s  %-28s %s" % (row.get("id"), row.get("n", "")[:28],
                                          row.get("p")))
    print("done.")
    return 0


if __name__ == "__main__":
    import sys
    try:
        sys.exit(_selftest())
    except LinkError as exc:
        print("\nLINK ERROR: %s" % exc)
        sys.exit(1)
