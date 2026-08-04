"""gen_catalog.py - build catalog.py from the DevAccess docs and the DLL source.

    python gen_catalog.py

Reads, and does not modify:
    ../DevAccess/COMMANDS.md                     engine commands + CVars
    ../console_dll/console_dll/avatar_console.c  the DLL's own dispatch chain

Writes:
    catalog.py

WHY GENERATE RATHER THAN HAND-MAINTAIN. COMMANDS.md is itself generated - its own
header says "Do not hand-edit - re-run the scripts" - and it carries 195 commands
and ~270 prefixed CVars. Retyping any of that would be wrong within a week, and
the failure would be silent: a command listed in the tool that the engine does
not have looks broken, and one the engine has that the tool omits is invisible.
This is the same argument check_cmds.py makes for the DLL's four lists, and the
same answer: derive it, do not duplicate it.

WHAT "RUNNABLE" MEANS HERE, and why most of the catalog is not
--------------------------------------------------------------
The only writing verb on the pipe is `cvar <name> <value>`, and the server
validates that the name is a bare identifier and the value is numeric so that a
second command cannot be smuggled in behind either. It then builds "<name>
<value>" and hands it to CConsole::ExecuteLine.

Two consequences that decide every entry's `runnable` field:

  * The server never checks that <name> is really a CVar. So `cvar` runs ANY
    engine console command whose form is `name <one number>` - set_health 50,
    hit_me 10, stats 3, draw_method 1. That is a much larger surface than the
    verb's name suggests, and it is the reason this page is useful today.

  * `cvar` calls RunConsoleLine, which is ExecuteLine. It does NOT go through
    TryModCommand - that dispatcher is only consulted in hkUpdateUI, on lines
    popped from the hotkey queue. So none of the DLL's own 76 commands (warp,
    spawn, freecam, drive...) can be reached through the pipe at all, however
    they are spelled. They are catalogued here with runnable="mod" so the tool
    can show them and say why they are greyed out, rather than pretend they do
    not exist.

`runnable` values:
    "yes"     name + one numeric argument -> works today through `cvar`
    "noargs"  takes no arguments -> `cvar` needs a value, so UNVERIFIED
    "args"    needs a string or several arguments -> needs a `cmd` verb
    "mod"     a DLL command -> needs a `cmd` verb that runs TryModCommand first
"""

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COMMANDS_MD = os.path.join(HERE, "..", "DevAccess", "COMMANDS.md")
CONSOLE_C = os.path.join(HERE, "..", "console_dll", "console_dll",
                         "avatar_console.c")
OUT = os.path.join(HERE, "catalog.py")

# Argument names that are numbers. Taken from the usage strings themselves, not
# invented: "Usage: set_health value", "Usage: stats 3", "Usage: AddDiamonds
# <nbOfDiamonds>". Anything not in here is treated as a string, which is the
# safe direction - a command wrongly marked "args" is merely greyed out, while
# one wrongly marked "yes" offers a Run button that cannot work.
NUMERIC_WORDS = {
    "value", "ammount", "amount", "number", "num", "n", "level", "fov",
    "nboftimes", "nbofdiamonds", "state", "speed", "regenspeed", "dt", "wf",
    "sicknesslevel", "reliability", "0-175", "seconds", "time", "scale",
    "factor", "count", "index", "id", "flag", "mode", "size", "ratio",
}
NUMERIC_RE = re.compile(r"^[<\[]?-?[\d.]+[>\]]?$")


def read(path):
    with io.open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def split_row(line):
    """One markdown table row -> its cells, with backticks stripped."""
    if not line.startswith("|"):
        return None
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return [c.strip("`").strip() for c in cells]


def classify(name, usage):
    """-> ("yes"|"noargs"|"args", arg_hint)

    Derived from the command's own `Usage:` block. Where there is no usage text
    the answer is "args" - unknown is treated as not-runnable, so the tool never
    offers a Run button it cannot honour.
    """
    if not usage:
        return "args", ""
    text = usage.strip()
    text = re.sub(r"^Usage\s*:\s*", "", text, flags=re.I)
    # Usage lines often carry prose after the real form ("stats 3 - Toggles the
    # first 3 levels"). Cut at the first dash-with-spaces or full stop.
    text = re.split(r"\s+-\s+|\.\s|,\s", text)[0].strip()
    parts = text.split()
    if not parts:
        return "args", ""
    if parts[0].lower() != name.lower():
        # The usage block names a different command (several do - AddDiamonds'
        # block is quoted under Cheat_AddDiamonds). Do not guess from it.
        return "args", text
    args = parts[1:]
    if not args:
        return "noargs", ""
    if len(args) > 1:
        return "args", " ".join(args)
    token = args[0].strip("<>[]").lower()
    if token in NUMERIC_WORDS or NUMERIC_RE.match(args[0]):
        return "yes", args[0]
    return "args", args[0]


def parse_commands(md):
    """Sections 1.1, 1.2 and 1.4 - five columns, `command | impl | help | usage | VA`."""
    out = []
    section = None
    for line in md.splitlines():
        m = re.match(r"^###\s+(1\.\d)\s", line)
        if m:
            section = m.group(1)
            continue
        if re.match(r"^##\s+2\.", line):
            break
        if section is None or not line.startswith("|"):
            continue
        cells = split_row(line)
        if not cells or len(cells) < 5:
            continue
        name = cells[0]
        if not name or name in ("command", "---") or set(name) <= set("-"):
            continue
        impl, help_, usage = cells[1], cells[2], cells[3]
        runnable, hint = classify(name, usage)
        out.append({
            "name": name, "group": "command", "section": section,
            "help": help_, "usage": usage, "impl": impl,
            "runnable": runnable, "arg": hint,
        })
    return out


def parse_cvars(md):
    """Section 2's per-prefix subsections - `CVar | ConsoleHelp | VA`.

    Every CVar is a reflected config field, so every one takes a value and is
    runnable today. That is the bulk of what this page can actually do.
    """
    out = []
    prefix = None
    in_two = False
    for line in md.splitlines():
        if re.match(r"^##\s+2\.", line):
            in_two = True
            continue
        if re.match(r"^##\s+3\.", line):
            break
        if not in_two:
            continue
        m = re.match(r"^###\s+2\.\s+`([^`]+)`", line)
        if m:
            prefix = m.group(1)
            continue
        if prefix is None or not line.startswith("|"):
            continue
        cells = split_row(line)
        if not cells or len(cells) < 3:
            continue
        name = cells[0]
        if not name or name in ("CVar",) or set(name) <= set("-"):
            continue
        out.append({
            "name": name, "group": prefix, "section": "2",
            "help": cells[1], "usage": "", "impl": "",
            "runnable": "yes", "arg": "value",
        })
    return out


def parse_batch_files(md):
    """Section 3 - the .console batch files that SHIP with the game.

    Worth parsing separately because it is a different KIND of evidence. Section
    2 is static reconstruction from the binary and the doc admits its limits:
    6371 reflected fields had no resolvable prefix, so the tables are known to be
    incomplete. Section 3 is data - lines Ubisoft wrote and shipped, each one a
    command that demonstrably existed.

    gfx_ShowFPS is the proof this pass is needed: it is quoted all over the
    DevAccess docs, it is in two shipped batch files, and it is NOT in the 171-row
    gfx_ table. Without this it would be missing from a catalogue claiming to
    list everything.
    """
    out = []
    in_three = False
    in_block = False
    for line in md.splitlines():
        if re.match(r"^##\s+3\.", line):
            in_three = True
            continue
        if in_three and re.match(r"^##\s+\d", line):
            break
        if not in_three:
            continue
        if line.startswith("```"):
            in_block = not in_block
            continue
        if not in_block:
            continue
        text = line.strip()
        if not text or text.startswith(";"):      # ';' is the comment marker
            continue
        parts = text.split()
        name = parts[0]
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            continue
        args = parts[1:]
        if not args:
            runnable, hint = "noargs", ""
        elif len(args) == 1 and NUMERIC_RE.match(args[0]):
            runnable, hint = "yes", args[0]
        else:
            runnable, hint = "args", " ".join(args)
        prefix = name.split("_")[0] + "_" if "_" in name else "command"
        out.append({
            "name": name, "group": prefix, "section": "3",
            "help": "", "usage": "shipped: %s" % text, "impl": "",
            "runnable": runnable, "arg": hint,
        })
    return out


def parse_mod_commands(src):
    """The DLL's own dispatch chain, read the same way check_cmds.py reads it."""
    start = src.index("static int TryModCommand(void* console, const char* line)")
    end = src.index("static void DoPendingWarp(void)")
    body = src[start:end]
    names = []
    for n in re.findall(r'_strn?icmp\(p,\s*"([^"]+)"', body):
        if n not in names:
            names.append(n)
    return [{
        "name": n, "group": "mod", "section": "dll",
        "help": "", "usage": "", "impl": "",
        "runnable": "mod", "arg": "",
    } for n in names]


def main():
    md = read(COMMANDS_MD)
    src = read(CONSOLE_C)

    entries = (parse_commands(md) + parse_cvars(md) + parse_batch_files(md)
               + parse_mod_commands(src))

    # A name can appear both as a section-1.4 literal and as a section-2 CVar
    # (cheat_UnlimitedAmmo does). Keep the richer record: prefer one with help
    # text, then one that is runnable.
    best = {}
    for e in entries:
        key = e["name"].lower()
        cur = best.get(key)
        if cur is None:
            best[key] = e
            continue
        score = (bool(e["help"]), e["runnable"] == "yes", bool(e["usage"]))
        cur_score = (bool(cur["help"]), cur["runnable"] == "yes",
                     bool(cur["usage"]))
        if score > cur_score:
            best[key] = e
    entries = sorted(best.values(), key=lambda e: (e["group"], e["name"].lower()))

    groups = {}
    for e in entries:
        groups[e["group"]] = groups.get(e["group"], 0) + 1
    counts = {}
    for e in entries:
        counts[e["runnable"]] = counts.get(e["runnable"], 0) + 1

    lines = [
        '"""catalog.py - GENERATED by gen_catalog.py. Do not hand-edit.',
        "",
        "Every console command and CVar known for Avatar: The Game PC retail 1.02,",
        "from DevAccess/COMMANDS.md (itself generated from the binary) plus the",
        "console DLL's own dispatch chain.",
        "",
        "Re-run gen_catalog.py after either source changes.",
        "",
        "runnable:",
        '    "yes"     name + one number -> works today through the pipe\'s `cvar`',
        '    "noargs"  takes no arguments -> `cvar` needs a value, so UNVERIFIED',
        '    "args"    needs a string or several arguments -> needs a `cmd` verb',
        '    "mod"     a DLL command -> `cvar` bypasses TryModCommand, so',
        "              unreachable from the pipe until a `cmd` verb exists",
        '"""',
        "",
        "ENTRIES = [",
    ]
    for e in entries:
        lines.append("    %r," % (e,))
    lines.append("]")
    lines.append("")
    lines.append("GROUPS = %r" % (sorted(groups),))
    lines.append("GROUP_COUNTS = %r" % (groups,))
    lines.append("RUNNABLE_COUNTS = %r" % (counts,))
    lines.append("")

    with io.open(OUT, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines))

    print("catalog.py written: %d entries" % len(entries))
    print("  by group   : %s" % ", ".join(
        "%s=%d" % (k, v) for k, v in sorted(groups.items())))
    print("  by runnable: %s" % ", ".join(
        "%s=%d" % (k, v) for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
