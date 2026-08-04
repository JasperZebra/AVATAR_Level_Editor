#!/usr/bin/env python
"""check_cmds.py - fail the build if the Tab-completion table has drifted.

WHY THIS EXISTS.  Adding a console command to avatar_console.c means touching
four independent places:

    1. the dispatch chain in TryModCommand()      <- the only one that is real
    2. kOurCmds[] in LoadCmdList()                <- what Tab completes
    3. console_cmds_seed.h                        <- generated, additive
    4. the help text in ModHelp()                 <- what the user is told

Nothing checked them against each other, and all of them had drifted:

  * eleven working commands (agentinfo, rcprobe, respawn, resurrect, revive,
    mergelib, facing, facinginfo, driveai, vehinfo, editorlink) were dispatched
    and present in NEITHER completion list, so Tab could not offer them however
    many times you pressed it;
  * `grab` was advertised in ModHelp and implemented nowhere at all;
  * `drivecam` was advertised in ModHelp, in DriveStart's own on-screen text and
    in the completion seed, and dispatched nowhere.

C cannot derive (2) from (1) across a chain of string compares, so this does the
next best thing: it reads both out of the source and fails loudly on a mismatch.
build.bat runs it before cl, so drift cannot reach a DLL.

Usage:
    python check_cmds.py [path/to/avatar_console.c]

Exit 0 = consistent.  Exit 1 = drift, with the offending names printed.
"""

import io
import os
import re
import sys


def read_source(path):
    with io.open(path, encoding="utf-8", errors="surrogateescape") as f:
        return f.read()


def dispatched_commands(src):
    """Every name TryModCommand actually answers to."""
    start = src.index("static int TryModCommand(void* console, const char* line)")
    end = src.index("static void DoPendingWarp(void)")
    body = src[start:end]
    names = set(re.findall(r'_stri?n?icmp\(p,\s*"([^"]+)"', body))
    # `warp` is the fall-through at the bottom, matched by a bare _strnicmp on a
    # variable rather than a literal in the same shape.
    names.add("warp")
    # `?` is a passthrough to the engine's own help, not a completable name.
    names.discard("?")
    return names


def completion_table(src):
    """kOurCmds[] - the DLL's own contribution to the Tab list."""
    m = re.search(r"static const char\* const kOurCmds\[\]\s*=\s*\{(.*?)\n\};", src, re.S)
    if not m:
        return None
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def modhelp_mentions(src):
    """Words at the start of a ModHelp line - what the user is told exists."""
    m = re.search(r"static void ModHelp\(void\* c\)\s*\{(.*?)\n\}", src, re.S)
    if not m:
        return set()
    out = set()
    for line in re.findall(r'P_\(c, 0, AC\s*"([^"]*)"', m.group(1)):
        w = re.match(r"([a-z_][a-z0-9_]*)", line)
        if w:
            out.add(w.group(1))
    return out


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "avatar_console.c")
    src = read_source(path)

    disp = dispatched_commands(src)
    table = completion_table(src)
    if table is None:
        print("check_cmds: FAIL - kOurCmds[] not found in %s" % path)
        print("            The completion table was renamed or removed; this")
        print("            check cannot verify anything. Fix the parser or the table.")
        return 1

    missing = sorted(disp - table)      # dispatched, not completable
    extra = sorted(table - disp)        # completable, not dispatched

    print("check_cmds: %d dispatched, %d in kOurCmds[]" % (len(disp), len(table)))

    ok = True
    if missing:
        ok = False
        print("")
        print("  DISPATCHED BUT NOT COMPLETABLE (%d):" % len(missing))
        for n in missing:
            print("      %s" % n)
        print("  -> add these to kOurCmds[] in LoadCmdList(). Tab cannot offer a")
        print("     name that is in no list, however many times it is pressed.")
    if extra:
        ok = False
        print("")
        print("  COMPLETABLE BUT NOT DISPATCHED (%d):" % len(extra))
        for n in extra:
            print("      %s" % n)
        print("  -> Tab offers these and the dispatch falls through to the engine,")
        print("     which does not know them either. Either implement them or drop")
        print("     them from kOurCmds[]. This is exactly how `drivecam` looked")
        print("     broken for as long as it did.")

    # Advisory only: ModHelp is prose, so a name can legitimately appear in a
    # sentence rather than at the start of a line. Never fails the build.
    help_words = modhelp_mentions(src)
    advertised_only = sorted(w for w in (help_words - disp) if len(w) > 3)
    if advertised_only:
        print("")
        print("  note: ModHelp lines starting with a word that is not a command:")
        print("        %s" % " ".join(advertised_only))
        print("        (advisory - most will be prose. `grab` hid here.)")

    if ok:
        print("check_cmds: OK - the dispatch and the completion table agree")
        return 0
    print("")
    print("check_cmds: FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
