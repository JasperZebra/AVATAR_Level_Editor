#!/usr/bin/env python3
"""
Disassemble Avatar's Dunia.dll at a virtual address.

Needed because Ghidra's decompile dump only contains addresses it turned into
functions. Script thunks like SwitchCamera's LAB_10a89720 are referenced by the
registration table but were never promoted to functions, so they have no
decompiled body -- we have to read the bytes ourselves.

Usage:
    python disasm_at.py 0x10a89720
    python disasm_at.py 0x10a89720 --count 60
    python disasm_at.py 0x10a89720 --dll "C:/path/to/Dunia.dll"

Call targets are annotated with the matching "### FUN_xxxxxxxx" header from the
decompile when one exists, so you can jump straight back into the pseudo-C.
"""

import argparse
import re
import sys
from functools import lru_cache
from pathlib import Path

try:
    import capstone
    import pefile
except ImportError as exc:  # pragma: no cover
    sys.exit(f"missing dependency: {exc} (need capstone + pefile)")

TOOLS_DIR = Path(__file__).resolve().parents[2]
DECOMPILE = TOOLS_DIR / "Avatar_Dunia_Retail_1.02_decrypted.dll_FULL_DECOMPILE.txt"

# The decompile was produced from this exact file, so addresses line up 1:1.
# The DRM-stripped Dunia.dll the game actually loads may have a shifted section
# layout -- do not assume file offsets carry over to it without re-checking.
DEFAULT_DLL = Path(r"C:\Users\sambe\Downloads\Dunia DLL's\Dunia_Retail_1.02_decrypted.dll")


@lru_cache(maxsize=1)
def decompiled_functions():
    """Set of VAs that exist as functions in the decompile dump."""
    if not DECOMPILE.exists():
        return frozenset()
    header = re.compile(r'^###\s+\S+\s+@\s+([0-9a-f]{8})')
    found = set()
    with DECOMPILE.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = header.match(line)
            if m:
                found.add(int(m.group(1), 16))
    return frozenset(found)


def va_to_offset(pe, va):
    """Translate a virtual address to a file offset, or None if unmapped."""
    rva = va - pe.OPTIONAL_HEADER.ImageBase
    if rva < 0:
        return None
    for section in pe.sections:
        start = section.VirtualAddress
        end = start + max(section.Misc_VirtualSize, section.SizeOfRawData)
        if start <= rva < end:
            delta = rva - start
            if delta >= section.SizeOfRawData:
                return None  # inside a virtual-only tail (e.g. .bss)
            return section.PointerToRawData + delta, section.Name.rstrip(b"\x00").decode()
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("address", help="virtual address, e.g. 0x10a89720")
    ap.add_argument("--count", type=int, default=40, help="instructions to show")
    ap.add_argument("--dll", type=Path, default=DEFAULT_DLL)
    args = ap.parse_args()

    va = int(args.address, 0)
    if not args.dll.exists():
        sys.exit(f"DLL not found: {args.dll}")

    pe = pefile.PE(str(args.dll), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase

    located = va_to_offset(pe, va)
    if located is None:
        sys.exit(f"{va:#x} is not inside a mapped, raw-backed section")
    offset, section_name = located

    with args.dll.open("rb") as fh:
        fh.seek(offset)
        code = fh.read(args.count * 16)

    known = decompiled_functions()

    print(f"{args.dll.name}  imagebase={base:#x}")
    print(f"{va:#x}  ->  file offset {offset:#x}  (section {section_name})")
    print("-" * 72)

    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = False
    shown = 0
    for insn in md.disasm(code, va):
        note = ""
        if insn.mnemonic in ("call", "jmp"):
            target = insn.op_str.strip()
            if target.startswith("0x"):
                tgt = int(target, 16)
                if tgt in known:
                    note = f"   ; -> FUN_{tgt:08x} (decompiled)"
                else:
                    note = "   ; -> no decompiled body"
        print(f"  {insn.address:08x}  {insn.mnemonic:<7} {insn.op_str}{note}")
        shown += 1
        if shown >= args.count:
            break
        if insn.mnemonic == "ret":
            print("  --- ret ---")
            break


if __name__ == "__main__":
    main()
