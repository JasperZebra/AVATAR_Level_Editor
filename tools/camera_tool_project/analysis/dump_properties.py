#!/usr/bin/env python3
"""
Dump Dunia's reflected class properties WITH THEIR BYTE OFFSETS, offline.

Dunia registers every serialisable field through a per-class RegisterProperties
routine that allocates a small record and fills it in literally:

    push 0x14                     ; sizeof(property record)
    call operator_new
    mov  [esi],      0x11014c1c   ; record vtable
    push 0x1103d6f8               ; -> "fCameraBlendTime"
    mov  [esi+4],    0x1103d6f8   ; name pointer
    call hash_name
    mov  [esi],      0x110d8a2c   ; TYPE descriptor (float, bool, vec3, ...)
    mov  [esi+0xc],  0x54         ; <<< BYTE OFFSET OF THE FIELD IN THE OBJECT
    push esi
    push 0x111e8804               ; the class's property-list global
    call add_property

So the compiled binary contains a complete, exact field map for every reflected
class -- no guessing, no runtime scanning, no debugger. This recovers it.

    python dump_properties.py --class-filter Camera
    python dump_properties.py --list 0x111e8804
    python dump_properties.py --around 0x1024b860

Output groups properties by the property-list global they register into, which
is the per-class identity. Cross-reference that global against the class
descriptors in NOTES.md to name the class.
"""

from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

import capstone
import pefile

DEFAULT_DLL = Path(r"C:\Users\sambe\Downloads\Dunia DLL's\Dunia_Retail_1.02_decrypted.dll")

# Known type-descriptor globals, learned by reading registrations whose types
# are obvious from the XML (entitylibrary) side.
TYPE_NAMES = {
    0x110d8a2c: "float",
    0x1103e004: "bool",
    0x11014c1c: "<record vtable>",
    0x11042090: "enum/complex",
}


def build_string_index(pe, data):
    """VA -> string, for every printable C string in the read-only sections."""
    base = pe.OPTIONAL_HEADER.ImageBase
    out = {}
    for sec in pe.sections:
        name = sec.Name.rstrip(b"\x00")
        if name not in (b".rdata", b".data"):
            continue
        raw = data[sec.PointerToRawData:sec.PointerToRawData + sec.SizeOfRawData]
        for m in re.finditer(rb"[ -~]{3,127}\x00", raw):
            va = base + sec.VirtualAddress + m.start()
            out[va] = m.group()[:-1].decode("ascii", "replace")
    return out


def disassemble_text(pe, data):
    base = pe.OPTIONAL_HEADER.ImageBase
    sec = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
    code = data[sec.PointerToRawData:sec.PointerToRawData + sec.SizeOfRawData]
    start = base + sec.VirtualAddress
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    insns, off = [], 0
    while off < len(code):
        chunk = list(md.disasm(code[off:], start + off))
        if chunk:
            insns.extend(chunk)
            off += (chunk[-1].address + chunk[-1].size) - (start + off)
        off += 1        # skip the byte that stalled the decoder
    return insns


# capstone renders displacements in hex above 9 and decimal below, so both
# forms must be accepted -- "[esi + 4]" and "[esi + 0xc]" are equally common.
NUM = r"(?:0x[0-9a-f]+|\d+)"
IMM_RE = re.compile(
    rf"(?:dword ptr \[(\w+)(?:\s*\+\s*({NUM}))?\]|(\w+)),\s*({NUM})$")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dll", type=Path, default=DEFAULT_DLL)
    ap.add_argument("--class-filter", default=None,
                    help="only show property lists containing this substring")
    ap.add_argument("--list", type=lambda s: int(s, 0), default=None,
                    help="only show one property-list global")
    ap.add_argument("--window", type=int, default=40,
                    help="instructions to associate a name with an offset")
    args = ap.parse_args()

    data = args.dll.read_bytes()
    pe = pefile.PE(str(args.dll), fast_load=True)

    print(f"{args.dll.name}: indexing strings...", file=sys.stderr)
    strings = build_string_index(pe, data)
    print(f"  {len(strings):,} strings", file=sys.stderr)
    print("disassembling .text...", file=sys.stderr)
    insns = disassemble_text(pe, data)
    print(f"  {len(insns):,} instructions\n", file=sys.stderr)

    # Walk instructions collecting (name, type, offset, list_global) tuples.
    props = collections.defaultdict(list)   # list_global -> [(offset, name, type)]
    for i, ins in enumerate(insns):
        # Anchor on the name-pointer store: mov [reg+4], <string VA>
        if ins.mnemonic != "mov":
            continue
        m = IMM_RE.search(ins.op_str)
        if not m:
            continue
        imm = int(m.group(4), 0)
        name = strings.get(imm)
        if not name or not re.match(r"^[a-z]{1,4}[A-Z]", name):
            continue      # engine field names are hungarian: fFoo, bBar, selBaz
        # Scan forward for the offset store and the list global.
        offset = typ = listg = None
        for j in range(i + 1, min(i + args.window, len(insns))):
            nxt = insns[j]
            if nxt.mnemonic == "mov":
                m2 = IMM_RE.search(nxt.op_str)
                if m2:
                    val = int(m2.group(4), 0)
                    disp = m2.group(2)
                    if disp and int(disp, 0) == 0xc and offset is None:
                        offset = val
                    elif disp is None and val in TYPE_NAMES and typ is None:
                        typ = val
                    elif not disp and val > 0x11000000 and typ is None:
                        typ = val
            elif nxt.mnemonic == "push":
                try:
                    v = int(nxt.op_str, 0)
                except ValueError:
                    continue
                if 0x11000000 < v < 0x11400000 and v not in strings:
                    listg = v
            elif nxt.mnemonic == "call" and listg is not None:
                break
        if offset is not None and listg is not None:
            props[listg].append((offset, name, TYPE_NAMES.get(typ, hex(typ) if typ else "?")))

    print(f"recovered properties for {len(props)} class property-lists\n")

    for listg, items in sorted(props.items()):
        names = " ".join(n for _, n, _ in items)
        if args.list is not None and listg != args.list:
            continue
        if args.class_filter and args.class_filter.lower() not in names.lower():
            continue
        seen = set()
        uniq = []
        for off, name, typ in sorted(items):
            if name in seen:
                continue
            seen.add(name)
            uniq.append((off, name, typ))
        print(f"=== property list {listg:#010x}   ({len(uniq)} fields) ===")
        prev_end = None
        for off, name, typ in uniq:
            gap = ""
            if prev_end is not None and off > prev_end:
                gap = f"   <-- {off - prev_end} byte gap"
            print(f"  +{off:#06x}  {name:<38} {typ}{gap}")
            prev_end = off + 4
        print()


if __name__ == "__main__":
    main()
