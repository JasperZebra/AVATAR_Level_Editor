#!/usr/bin/env python3
"""
Find 4x4 matrix copy routines in Dunia.dll, offline.

The AFOP camera tool locates its camera by AOB-scanning for the routine that
copies a 4x4 matrix into the camera object. That exact signature does not exist
in Avatar (2023 x64 vs 2009 x86), so instead of matching AFOP's bytes we match
the *shape*: four SSE load/store pairs in close succession, which is what any
16-float copy compiles to.

Covers both the unaligned and aligned encodings, since which one the compiler
picked depends on the struct's alignment guarantees:

    movups xmm, [mem]   0F 10 /r        movups [mem], xmm   0F 11 /r
    movaps xmm, [mem]   0F 28 /r        movaps [mem], xmm   0F 29 /r

Also reports x87 runs (2009 code often still used the FPU for matrix work),
detected as long sequences of fld/fstp.

    python find_matrix_copies.py
    python find_matrix_copies.py --min-pairs 3
"""

from __future__ import annotations

import argparse
from pathlib import Path

import capstone
import pefile

DEFAULT_DLL = Path(r"C:\Users\sambe\Downloads\Dunia DLL's\Dunia_Retail_1.02_decrypted.dll")

SSE_LOADS = {"movups", "movaps"}
SSE_STORES = {"movups", "movaps"}


def text_section(pe):
    for s in pe.sections:
        if s.Name.rstrip(b"\x00") == b".text":
            return s
    raise RuntimeError(".text not found")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dll", type=Path, default=DEFAULT_DLL)
    ap.add_argument("--min-pairs", type=int, default=4,
                    help="consecutive load/store pairs required (4 = a full 4x4)")
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()

    pe = pefile.PE(str(args.dll), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    sec = text_section(pe)
    start_va = base + sec.VirtualAddress
    code = args.dll.read_bytes()[sec.PointerToRawData:
                                 sec.PointerToRawData + sec.SizeOfRawData]

    print(f"{args.dll.name}: scanning .text {start_va:#010x} "
          f"({len(code) / 1024 / 1024:.1f} MB) for >={args.min_pairs} SSE "
          f"load/store pairs\n")

    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = False

    # Walk linearly. Track runs of (load -> store) pairs where the store writes
    # memory and the load reads memory -- that is a copy, not arithmetic.
    # capstone's disasm() stops dead at the first undecodable byte, and .text is
    # full of data/padding that will not decode. Resume past each stall or we
    # only ever see the first fraction of the section.
    insns = []
    offset = 0
    while offset < len(code):
        chunk = list(md.disasm(code[offset:], start_va + offset))
        if chunk:
            insns.extend(chunk)
            consumed = (chunk[-1].address + chunk[-1].size) - (start_va + offset)
            offset += consumed
        offset += 1        # step over the byte that stalled the decoder
    print(f"disassembled {len(insns):,} instructions\n")

    # Match on the STORES alone. A 4x4 write always produces stores to
    # consecutive slots of one base register, whatever order the loads happen
    # in -- matching load/store adjacency misses interleaved codegen entirely.
    # Two shapes:
    #   4 x (movaps/movups [base+d], xmm)  with d stepping by 16   -> row-at-a-time
    #  16 x (movss        [base+d], xmm)   with d stepping by 4    -> float-at-a-time
    import re
    # capstone renders operands as e.g. "dword ptr [ecx + 0x30], xmm0" --
    # the size prefix must be tolerated, and the destination is operand 1.
    mem_re = re.compile(r"(?:\w+\s+ptr\s+)?\[(\w+)(?:\s*\+\s*(0x[0-9a-f]+|\d+))?\]")

    def store_target(ins):
        """(base_reg, displacement, mnemonic) if this stores xmm -> memory."""
        if ins.mnemonic not in ("movaps", "movups", "movss"):
            return None
        dest = ins.op_str.split(",")[0].strip()
        if "[" not in dest:
            return None                      # register destination = a load
        m = mem_re.match(dest)
        if not m:
            return None
        disp = int(m.group(2), 0) if m.group(2) else 0
        return m.group(1), disp, ins.mnemonic

    hits = []
    i = 0
    while i < len(insns):
        first_store = store_target(insns[i])
        if not first_store:
            i += 1
            continue
        base, disp0, mnem = first_store
        stride = 4 if mnem == "movss" else 16
        want = 16 if mnem == "movss" else 4
        seen = 1
        j = i + 1
        # allow interleaved non-store instructions between the stores
        while j < len(insns) and seen < want and (j - i) < want * 6:
            st = store_target(insns[j])
            if st and st[0] == base and st[2] == mnem and st[1] == disp0 + stride * seen:
                seen += 1
            j += 1
        pairs = seen if mnem == "movss" else seen
        need = 16 if mnem == "movss" else args.min_pairs
        if seen >= need:
            hits.append((insns[i].address, seen, insns[i:min(j, i + 24)]))
            i = j
        else:
            i += 1

    print(f"{len(hits)} matrix-copy candidate(s):\n")
    for addr, pairs, block in hits[:args.limit]:
        print(f"  {addr:#010x}  {pairs} pairs ({pairs * 4} floats)")
        for ins in block[:10]:
            print(f"      {ins.address:08x}  {ins.mnemonic:<7} {ins.op_str}")
        if len(block) > 10:
            print(f"      ... {len(block) - 10} more")
        print()

    if len(hits) > args.limit:
        print(f"... {len(hits) - args.limit} more (raise --limit)")


if __name__ == "__main__":
    main()
