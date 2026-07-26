#!/usr/bin/env python3
"""
Find every vec3 getter/setter in Dunia.dll by byte shape, and report the member
offset each one touches.

`CEntity::GetPosition` @ 0x105dccd0 has a very distinctive encoding:

    8b 44 24 04     mov  eax, [esp+4]        ; out vec3*
    d9 41 70        fld  dword ptr [ecx+0x70]
    d9 18           fstp dword ptr [eax]
    d9 41 74        fld  dword ptr [ecx+0x74]
    d9 58 04        fstp dword ptr [eax+4]
    d9 41 78        fld  dword ptr [ecx+0x78]
    d9 58 08        fstp dword ptr [eax+8]
    c2 04 00        ret  4

Every trivial vec3 accessor the compiler emitted for this class family shares
that shape with only the displacement changing, so one pattern finds them all
along with the field offsets. That is how entity rotation gets located without
a running game.

The mirrored form (setter: reads from the argument, writes to [ecx+d]) is
matched too.

    python find_vec3_accessors.py
    python find_vec3_accessors.py --near 0x105dccd0
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pefile

DEFAULT_DLL = Path(r"C:\Users\sambe\Downloads\Dunia DLL's\Dunia_Retail_1.02_decrypted.dll")

# Byte patterns, NOT regex. Several opcode bytes collide with regex
# metacharacters -- 0x24 is '$', 0x2e is '.' -- so a bytes regex silently
# reinterprets them as anchors and wildcards and matches nothing. Match
# literally instead. "None" = wildcard, and its index is captured.
#
# getter: mov eax,[esp+4]; (fld [ecx+d]; fstp [eax+k]) x3; ret 4
GETTER = [0x8b, 0x44, 0x24, 0x04,
          0xd9, 0x41, None, 0xd9, 0x18,
          0xd9, 0x41, None, 0xd9, 0x58, 0x04,
          0xd9, 0x41, None, 0xd9, 0x58, 0x08,
          0xc2, 0x04, 0x00]

# setter: mov eax,[esp+4]; (fld [eax+k]; fstp [ecx+d]) x3; ret 4
SETTER = [0x8b, 0x44, 0x24, 0x04,
          0xd9, 0x00, 0xd9, 0x59, None,
          0xd9, 0x40, 0x04, 0xd9, 0x59, None,
          0xd9, 0x40, 0x08, 0xd9, 0x59, None,
          0xc2, 0x04, 0x00]


def scan(haystack: bytes, pattern):
    """Yield (offset, [wildcard bytes]) for each match of a wildcard pattern."""
    first = pattern[0]
    n = len(pattern)
    pos = 0
    while True:
        i = haystack.find(bytes([first]), pos)
        if i < 0 or i + n > len(haystack):
            return
        pos = i + 1
        wild = []
        for k, want in enumerate(pattern):
            got = haystack[i + k]
            if want is None:
                wild.append(got)
            elif got != want:
                break
        else:
            yield i, wild


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dll", type=Path, default=DEFAULT_DLL)
    ap.add_argument("--near", type=lambda s: int(s, 0), default=None,
                    help="only show results within 0x10000 of this address")
    args = ap.parse_args()

    pe = pefile.PE(str(args.dll), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    data = args.dll.read_bytes()
    sec = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
    text = data[sec.PointerToRawData:sec.PointerToRawData + sec.SizeOfRawData]
    start = base + sec.VirtualAddress

    for label, pat in (("GETTER", GETTER), ("SETTER", SETTER)):
        rows = []
        for off, wild in scan(text, pat):
            d0, d1, d2 = wild
            if d1 != d0 + 4 or d2 != d0 + 8:
                continue        # must be three consecutive floats
            va = start + off
            if args.near and abs(va - args.near) > 0x10000:
                continue
            rows.append((va, d0))
        print(f"=== {label}S  ({len(rows)} found) ===")
        for va, d in sorted(rows):
            note = ""
            if va == 0x105dccd0:
                note = "   <-- CEntity::GetPosition (known)"
            print(f"  {va:#010x}   vec3 at [ecx+{d:#04x}]{note}")
        print()


if __name__ == "__main__":
    main()
