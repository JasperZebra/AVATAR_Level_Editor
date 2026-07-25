#!/usr/bin/env python3
"""
Extract the Lua-registered script API from Avatar's Dunia.dll decompile.

The engine registers every script-callable function through a single
registrar helper, one call per function:

    FUN_100de5f0(0,"SwitchCamera",&LAB_10a89720);
    FUN_100de5f0(0,"TeleportEntity",&LAB_10a8a520);

The third argument is the address of the Lua thunk -- the
GenericScriptStaticFunctionArgN<...> wrapper that pops arguments off the
lua_State and forwards them to the real engine function. Those thunk
addresses are the call targets a freecam mod needs.

READ-ONLY POLICY (inherited from Avatar_FC2_CrossReference_NOTES.txt):
this script never edits the decompile. It reads and writes a separate
output file.
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

DECOMPILE = Path(__file__).resolve().parents[2] / \
    "Avatar_Dunia_Retail_1.02_decrypted.dll_FULL_DECOMPILE.txt"

OUT_DIR = Path(__file__).resolve().parent / "out"

# FUN_100de5f0(0,"Name",&LAB_10a89720);  /  ...,FUN_10a8a560);
REGISTER_RE = re.compile(
    r'(FUN_[0-9a-f]{8})\s*\(\s*(\d+)\s*,\s*"([A-Za-z_][A-Za-z0-9_]*)"\s*,\s*'
    r'&?((?:LAB|FUN)_[0-9a-f]{8})\s*\)'
)

# Ghidra function header emitted by the decompile dump: "### FUN_xxxxxxxx  @ xxxxxxxx"
HEADER_RE = re.compile(r'^###\s+(\S+)\s+@\s+([0-9a-f]{8})')


def main():
    if not DECOMPILE.exists():
        sys.exit(f"decompile not found: {DECOMPILE}")

    # registrar address -> list of (name, thunk, containing_function)
    by_registrar = defaultdict(list)
    current_fn = "<top-level>"
    scanned = 0

    with DECOMPILE.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            scanned += 1
            header = HEADER_RE.match(line)
            if header:
                current_fn = header.group(1)
                continue
            for registrar, flag, name, thunk in REGISTER_RE.findall(line):
                by_registrar[registrar].append((name, thunk, flag, current_fn))

    if not by_registrar:
        sys.exit("no registration calls matched -- has the decompile format changed?")

    # The real script registrar is whichever helper is called the most times;
    # a handful of unrelated 3-arg functions will also match the shape.
    main_registrar = max(by_registrar, key=lambda k: len(by_registrar[k]))
    entries = by_registrar[main_registrar]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "avatar_lua_api.txt"

    with out_path.open("w", encoding="utf-8") as out:
        out.write("Avatar (Dunia) Lua script API -- extracted from the retail 1.02 decompile\n")
        out.write(f"source    : {DECOMPILE.name}\n")
        out.write(f"registrar : {main_registrar}\n")
        out.write(f"functions : {len(entries)}\n")
        out.write("=" * 78 + "\n\n")
        for name, thunk, flag, container in sorted(entries):
            out.write(f"{name:<44} {thunk}   flag={flag}  in {container}\n")

    print(f"scanned {scanned:,} lines")
    print(f"registrar {main_registrar} -> {len(entries)} script functions")
    for registrar, hits in sorted(by_registrar.items(), key=lambda kv: -len(kv[1])):
        if registrar != main_registrar and len(hits) > 1:
            print(f"  (also saw {registrar} with {len(hits)} matches -- probably unrelated)")
    print(f"wrote {out_path}")

    # Surface the camera/position primitives immediately -- these are the ones
    # the freecam work actually cares about.
    interesting = [e for e in entries
                   if re.search(r'camera|teleport|entitypos|player|actionmap',
                                e[0], re.I)]
    if interesting:
        print("\ncamera / position / input primitives:")
        for name, thunk, _flag, container in sorted(interesting):
            print(f"  {name:<40} {thunk}  in {container}")


if __name__ == "__main__":
    main()
