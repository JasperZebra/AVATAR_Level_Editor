"""Parser tests for avatar_link - the three traps that hang a naive client.

No game and no pipe: `_pump` and `_write` are replaced with a scripted byte
feed, so these run anywhere. What is under test is the reply reader, which is
the only part of the client that can hang or silently mis-parse.

The three traps come from the server source (avatar_console.c) and are quoted in
avatar_link's module docstring:
  1. poslist rows are NOT JSON
  2. the 4 s busy reply ends with {"end":"?"}, not with the verb you sent
  3. a reply that hits the 1 MB cap loses its end sentinel entirely
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from avatar_link import AvatarLink, Timeout  # noqa: E402


def scripted(chunks):
    """An AvatarLink whose reads come from `chunks` and whose writes are kept."""
    link = AvatarLink()
    link._h = 1                      # non-None so the guards pass
    link.sent = []
    pending = list(chunks)

    def fake_write(data):
        link.sent.append(data)

    def fake_pump():
        if not pending:
            return 0
        link._buf += pending.pop(0)
        return 1

    link._write = fake_write
    link._pump = fake_pump
    return link


def test_poslist_rows_are_not_json():
    """Trap 1. The rows between the header and the end line are plain text.

    A client that json.loads() every line dies on row one; this one must route
    them to .raw and still find the sentinel.
    """
    link = scripted([
        b'{"ok":true,"cmd":"poslist","count":2,"frame":9}\n'
        b'0000000A:0000000B 1.00 2.00 3.00\n'
        b'0000000C:0000000D -4.50 5.25 6.00\n'
        b'{"end":"poslist"}\n'
    ])
    r = link.request("poslist 2")

    assert r.ok
    assert r.rows == []                      # nothing JSON between the ends
    assert len(r.raw) == 2
    assert r.positions() == [
        ("0000000A:0000000B", 1.0, 2.0, 3.0),
        ("0000000C:0000000D", -4.5, 5.25, 6.0),
    ]


def test_busy_reply_ends_with_question_mark():
    """Trap 2. The 4 s frame-loop timeout answers with cmd and end both "?".

    Matching `end == verb` would hang here for ever - and this fires on every
    world load, which is exactly when a user is watching.
    """
    link = scripted([
        b'{"ok":false,"cmd":"?","error":"the game\'s frame loop did not answer '
        b'- is it paused or loading?"}\n'
        b'{"end":"?"}\n'
    ])
    r = link.request("listx 100")

    assert r.busy is True                    # told apart from a real failure
    assert r.ok is False
    assert "frame loop" in r.error


def test_a_real_failure_is_not_reported_as_busy():
    """The busy test keys on cmd == "?", so a genuine verb failure must not trip
    it - otherwise a retry loop would spin on an error that will never clear."""
    link = scripted([
        b'{"ok":false,"cmd":"move","error":"id not present in the live world"}\n'
        b'{"end":"move"}\n'
    ])
    r = link.request("move 1:2 0 0 0")

    assert r.ok is False
    assert r.busy is False
    assert r.error == "id not present in the live world"


def test_missing_end_sentinel_times_out_instead_of_hanging():
    """Trap 3. LnkPut refuses to append once the buffer is within 600 bytes of
    LNK_OUT_MAX, and that guard drops the final {"end":...} line as readily as a
    data row. The client must give up, not block."""
    link = scripted([
        b'{"ok":true,"cmd":"list","count":1}\n'
        b'{"id":"1:2","n":"x","c":"y","p":[0,0,0]}\n'
        # no end line - the reply was truncated at the cap
    ])
    with pytest.raises(Timeout):
        link.request("list 9999", timeout=0.25)


def test_rows_and_header_are_kept_apart():
    link = scripted([
        b'{"ok":true,"cmd":"listx","count":2,"world":"sp_hometree"}\n'
        b'{"id":"A:B","n":"one","c":"C","p":[1,2,3]}\n'
        b'{"id":"C:D","n":"two","c":"C","p":[4,5,6]}\n'
        b'{"end":"listx"}\n'
    ])
    r = link.request("listx 2")

    assert r.head["world"] == "sp_hometree"
    assert [row["n"] for row in r.rows] == ["one", "two"]


def test_stale_bytes_are_dropped_before_a_new_request():
    """A timed-out reply leaves bytes in the buffer. If they survived into the
    next request they would be parsed as its answer, and every request after a
    single timeout would return the wrong thing."""
    link = scripted([b'{"ok":true,"cmd":"hello","proto":1}\n{"end":"hello"}\n'])
    link._buf = b'{"leftover":true}\n'

    r = link.request("hello")

    assert r.head.get("cmd") == "hello"
    assert not any(row.get("leftover") for row in r.rows)


def test_request_is_one_newline_terminated_line():
    link = scripted([b'{"ok":true,"cmd":"hello"}\n{"end":"hello"}\n'])
    link.request("  hello  ")
    assert link.sent == [b"hello\n"]         # trimmed, single \n, no \r


def test_cvar_rejects_what_the_server_would_reject():
    """The server requires a bare identifier and a numeric value so a second
    command cannot ride in behind either. Checking it here turns a round trip
    into an immediate, legible error."""
    from avatar_link import LinkError

    link = scripted([])
    with pytest.raises(LinkError):
        link.cvar("env_Hour; quit", 12)
    with pytest.raises(LinkError):
        link.cvar("env_Hour", "12 && something")
    assert link.sent == []                   # nothing reached the pipe
