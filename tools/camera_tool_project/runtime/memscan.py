#!/usr/bin/env python3
"""
Memory scanner for the running game -- a Cheat-Engine-style iterative search.

Scan state persists to disk between invocations (each CLI run is a fresh
python process), so a search is carried out as a sequence of commands:

    # you know the value (fastest -- use editor coordinates!)
    python memscan.py new --type f32 --value 1423.7
    python memscan.py refine --value 1450.2
    python memscan.py list

    # you don't know the value: snapshot, then narrow by how it changed
    python memscan.py new --type f32 --unknown
    ...move in game...
    python memscan.py refine --changed
    ...stand still...
    python memscan.py refine --unchanged
    python memscan.py refine --decreased

    # other searches
    python memscan.py aob "a1 ?? ?? ?? ?? 83 ec 08"
    python memscan.py string CCameraFree
    python memscan.py pointers-to 0x18490668
    python memscan.py watch 0x1abc1234 0x1abc1238 --type f32 --hz 4
    python memscan.py read 0x18490668 --len 64

Types: i8 u8 i16 u16 i32 u32 i64 u64 f32 f64

By default scans skip loaded module images (code/static data) and look only at
heap and other private memory, which is where entity and camera state lives.
Pass --include-modules to scan everything.
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
import time
from pathlib import Path

import numpy as np

from dunia_process import DuniaProcess, ProcessNotFound

SESSION = Path(__file__).resolve().parent / ".scan"

DTYPES = {
    "i8": np.int8, "u8": np.uint8, "i16": np.int16, "u16": np.uint16,
    "i32": np.int32, "u32": np.uint32, "i64": np.int64, "u64": np.uint64,
    "f32": np.float32, "f64": np.float64,
}

# Floats are never compared exactly -- a position float reread a frame later
# differs in the low bits even when "unchanged".
FLOAT_EPS = {"f32": 1e-3, "f64": 1e-6}


# ---------------------------------------------------------------- session ---

def session_meta() -> dict:
    meta = SESSION / "meta.json"
    if not meta.exists():
        sys.exit("no active scan -- start one with:  memscan.py new --type f32 --value X")
    return json.loads(meta.read_text())


def write_meta(**kw):
    SESSION.mkdir(parents=True, exist_ok=True)
    (SESSION / "meta.json").write_text(json.dumps(kw, indent=2))


def reset_session():
    if SESSION.exists():
        shutil.rmtree(SESSION)
    SESSION.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- regions ---

def scan_regions(proc: DuniaProcess, include_modules: bool, max_mb: int):
    """Yield (base, data) for regions worth scanning, respecting a size cap."""
    module_spans = []
    if not include_modules:
        module_spans = [(b, b + s) for b, s in proc.modules().values()]

    total = 0
    for base, size, _protect in proc.regions():
        if any(lo <= base < hi for lo, hi in module_spans):
            continue
        if total + size > max_mb * 1024 * 1024:
            continue
        data = proc.try_read(base, size)
        if not data:
            continue
        total += len(data)
        yield base, data


def as_array(data: bytes, dtype, offset: int):
    """View a byte buffer as dtype, starting at a byte offset."""
    itemsize = np.dtype(dtype).itemsize
    usable = (len(data) - offset) // itemsize * itemsize
    if usable <= 0:
        return None
    return np.frombuffer(data, dtype=dtype, count=usable // itemsize, offset=offset)


def offsets_for(align: int, itemsize: int):
    """Byte offsets to scan at. align=4 on a 4-byte type means offset 0 only;
    align=1 means every offset 0..itemsize-1, catching unaligned values."""
    step = align if align and align > 0 else itemsize
    return range(0, itemsize, step) if step < itemsize else [0]


# ------------------------------------------------------------------ scans ---

def cmd_new(args, proc):
    dtype = DTYPES[args.type]
    itemsize = np.dtype(dtype).itemsize
    reset_session()

    if args.unknown:
        # Snapshot mode: store raw region bytes so a later pass can diff them.
        regions = []
        snap_dir = SESSION / "snap"
        snap_dir.mkdir(parents=True, exist_ok=True)
        total = 0
        for i, (base, data) in enumerate(scan_regions(proc, args.include_modules,
                                                      args.max_mb)):
            (snap_dir / f"{i}.bin").write_bytes(data)
            regions.append({"base": base, "size": len(data), "file": f"{i}.bin"})
            total += len(data)
        write_meta(stage="snapshot", type=args.type, align=args.align,
                   include_modules=args.include_modules, max_mb=args.max_mb,
                   regions=regions)
        print(f"snapshot taken: {len(regions)} regions, {total / 1024 / 1024:,.1f} MB")
        print("now change the value in game, then:  memscan.py refine --changed")
        return

    if args.value is None:
        sys.exit("give --value X or --unknown")

    target = np.array(args.value, dtype=dtype)
    addrs, vals = [], []
    for base, data in scan_regions(proc, args.include_modules, args.max_mb):
        for off in offsets_for(args.align, itemsize):
            arr = as_array(data, dtype, off)
            if arr is None:
                continue
            if args.type in FLOAT_EPS:
                hit = np.where(np.abs(arr - target) <= FLOAT_EPS[args.type])[0]
            else:
                hit = np.where(arr == target)[0]
            if hit.size:
                addrs.append(base + off + hit * itemsize)
                vals.append(arr[hit])

    save_candidates(addrs, vals, dtype)
    write_meta(stage="candidates", type=args.type, align=args.align,
               include_modules=args.include_modules, max_mb=args.max_mb)
    n = sum(a.size for a in addrs) if addrs else 0
    print(f"{n:,} candidate(s)")
    if n and n <= 20:
        show_candidates(proc, dtype)


def save_candidates(addrs, vals, dtype):
    if addrs:
        a = np.concatenate(addrs).astype(np.uint64)
        v = np.concatenate(vals).astype(dtype)
    else:
        a = np.empty(0, np.uint64)
        v = np.empty(0, dtype)
    np.save(SESSION / "addrs.npy", a)
    np.save(SESSION / "vals.npy", v)


def load_candidates(dtype):
    return (np.load(SESSION / "addrs.npy"),
            np.load(SESSION / "vals.npy").astype(dtype))


def read_at(proc, addrs, dtype):
    """Current values at the given addresses; unreadable slots come back NaN/0."""
    itemsize = np.dtype(dtype).itemsize
    out = np.zeros(len(addrs), dtype=dtype)
    ok = np.zeros(len(addrs), dtype=bool)
    for i, a in enumerate(addrs):
        raw = proc.try_read(int(a), itemsize)
        if raw and len(raw) == itemsize:
            out[i] = np.frombuffer(raw, dtype=dtype, count=1)[0]
            ok[i] = True
    return out, ok


def cmd_refine(args, proc):
    meta = session_meta()
    dtype = DTYPES[meta["type"]]
    itemsize = np.dtype(dtype).itemsize
    eps = FLOAT_EPS.get(meta["type"], 0)

    if meta["stage"] == "snapshot":
        # Diff the whole snapshot against memory as it is now.
        addrs, vals = [], []
        for r in meta["regions"]:
            old_raw = (SESSION / "snap" / r["file"]).read_bytes()
            new_raw = proc.try_read(r["base"], r["size"])
            if not new_raw or len(new_raw) != len(old_raw):
                continue
            for off in offsets_for(meta["align"], itemsize):
                old = as_array(old_raw, dtype, off)
                new = as_array(new_raw, dtype, off)
                if old is None or new is None:
                    continue
                n = min(old.size, new.size)
                old, new = old[:n], new[:n]
                hit = compare(old, new, args, eps)
                if hit.size:
                    addrs.append(r["base"] + off + hit * itemsize)
                    vals.append(new[hit])
        save_candidates(addrs, vals, dtype)
        shutil.rmtree(SESSION / "snap", ignore_errors=True)
        write_meta(stage="candidates", type=meta["type"], align=meta["align"],
                   include_modules=meta["include_modules"], max_mb=meta["max_mb"])
        n = sum(a.size for a in addrs) if addrs else 0
    else:
        addrs, old = load_candidates(dtype)
        new, ok = read_at(proc, addrs, dtype)
        hit = compare(old, new, args, eps)
        hit = hit[ok[hit]]
        save_candidates([addrs[hit]], [new[hit]], dtype)
        write_meta(**{**meta, "stage": "candidates"})
        n = hit.size

    print(f"{n:,} candidate(s) remain")
    if n and n <= 20:
        show_candidates(proc, dtype)


def compare(old, new, args, eps):
    if args.value is not None:
        t = np.array(args.value, dtype=old.dtype)
        return np.where(np.abs(new - t) <= eps if eps else new == t)[0]
    if args.changed:
        return np.where(np.abs(new - old) > eps if eps else new != old)[0]
    if args.unchanged:
        return np.where(np.abs(new - old) <= eps if eps else new == old)[0]
    if args.increased:
        return np.where(new > old)[0]
    if args.decreased:
        return np.where(new < old)[0]
    sys.exit("pick one: --changed --unchanged --increased --decreased --value X")


def show_candidates(proc, dtype):
    addrs, _ = load_candidates(dtype)
    cur, ok = read_at(proc, addrs, dtype)
    print()
    for a, v, good in zip(addrs, cur, ok):
        static = proc.to_static(int(a))
        note = f"  (Dunia static {static:#010x})" if in_dunia(proc, int(a)) else ""
        print(f"  {int(a):#010x}  {v if good else '<unreadable>'}{note}")


def in_dunia(proc, addr):
    base, size = proc.modules().get("Dunia.dll", (0, 0))
    return base <= addr < base + size


def cmd_list(args, proc):
    meta = session_meta()
    dtype = DTYPES[meta["type"]]
    if meta["stage"] == "snapshot":
        sys.exit("snapshot taken but not yet refined -- run refine first")
    addrs, _ = load_candidates(dtype)
    print(f"{len(addrs):,} candidate(s), type {meta['type']}")
    cur, ok = read_at(proc, addrs[:args.limit], dtype)
    for a, v, good in zip(addrs[:args.limit], cur, ok):
        note = f"  (Dunia static {proc.to_static(int(a)):#010x})" \
            if in_dunia(proc, int(a)) else ""
        print(f"  {int(a):#010x}  {v if good else '<unreadable>'}{note}")
    if len(addrs) > args.limit:
        print(f"  ... {len(addrs) - args.limit:,} more (--limit to show more)")


def cmd_aob(args, proc):
    """Byte-pattern search with ?? wildcards."""
    tokens = args.pattern.replace("?", "?").split()
    needle, mask = bytearray(), bytearray()
    for t in tokens:
        if t in ("??", "?"):
            needle.append(0)
            mask.append(0)
        else:
            needle.append(int(t, 16))
            mask.append(1)
    needle, mask = bytes(needle), np.array(mask, dtype=bool)

    found = 0
    for base, data in scan_regions(proc, args.include_modules, args.max_mb):
        buf = np.frombuffer(data, dtype=np.uint8)
        if buf.size < len(needle):
            continue
        # Anchor on the first non-wildcard byte to keep the candidate set small.
        anchor = int(np.argmax(mask))
        cands = np.where(buf == needle[anchor])[0] - anchor
        cands = cands[(cands >= 0) & (cands + len(needle) <= buf.size)]
        for c in cands:
            window = buf[c:c + len(needle)]
            if np.all(window[mask] == np.frombuffer(needle, np.uint8)[mask]):
                addr = base + int(c)
                note = f"  (Dunia static {proc.to_static(addr):#010x})" \
                    if in_dunia(proc, addr) else ""
                print(f"  {addr:#010x}{note}")
                found += 1
                if found >= args.limit:
                    print(f"  ... stopped at --limit {args.limit}")
                    return
    print(f"{found} match(es)")


def cmd_string(args, proc):
    for enc in ("ascii", "utf-16-le"):
        needle = args.text.encode(enc)
        print(f"--- {enc} ---")
        found = 0
        for base, data in scan_regions(proc, args.include_modules, args.max_mb):
            start = 0
            while found < args.limit:
                i = data.find(needle, start)
                if i < 0:
                    break
                addr = base + i
                note = f"  (Dunia static {proc.to_static(addr):#010x})" \
                    if in_dunia(proc, addr) else ""
                print(f"  {addr:#010x}{note}")
                found += 1
                start = i + 1
        print(f"  {found} match(es)")


def cmd_pointers_to(args, proc):
    """Find 4-byte values equal to the target address -- i.e. pointers to it."""
    target = struct.pack("<I", args.address & 0xFFFFFFFF)
    found = 0
    for base, data in scan_regions(proc, args.include_modules, args.max_mb):
        start = 0
        while found < args.limit:
            i = data.find(target, start)
            if i < 0:
                break
            addr = base + i
            note = f"  (Dunia static {proc.to_static(addr):#010x})" \
                if in_dunia(proc, addr) else ""
            print(f"  {addr:#010x}{note}")
            found += 1
            start = i + 1
    print(f"{found} pointer(s) to {args.address:#010x}")


def cmd_read(args, proc):
    data = proc.try_read(args.address, args.len)
    if not data:
        sys.exit(f"unreadable at {args.address:#x}")
    for i in range(0, len(data), 16):
        row = data[i:i + 16]
        hexs = " ".join(f"{b:02x}" for b in row)
        txt = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        words = ""
        if len(row) >= 4:
            ws = struct.unpack_from("<" + "I" * (len(row) // 4), row)
            words = "  " + " ".join(f"{w:08x}" for w in ws)
        print(f"  {args.address + i:#010x}  {hexs:<47}  {txt}{words}")


def cmd_watch(args, proc):
    dtype = DTYPES[args.type]
    addrs = np.array(args.addresses, dtype=np.uint64)
    interval = 1.0 / args.hz
    print("  ".join(f"{int(a):#010x}" for a in addrs))
    try:
        while True:
            vals, ok = read_at(proc, addrs, dtype)
            print("  ".join(f"{v:>14.4f}" if np.issubdtype(dtype, np.floating)
                            else f"{v:>14}" for v in vals))
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nstopped")


# ------------------------------------------------------------------- main ---

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--process", default="Avatar.exe")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, with_type=True):
        if with_type:
            p.add_argument("--type", default="f32", choices=sorted(DTYPES))
        p.add_argument("--include-modules", action="store_true",
                       help="also scan loaded module images (code/static data)")
        p.add_argument("--max-mb", type=int, default=2048,
                       help="cap on total bytes scanned")

    p = sub.add_parser("new", help="start a scan")
    common(p)
    p.add_argument("--value", type=float)
    p.add_argument("--unknown", action="store_true")
    p.add_argument("--align", type=int, default=4)
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("refine", help="narrow the current scan")
    p.add_argument("--value", type=float)
    for flag in ("changed", "unchanged", "increased", "decreased"):
        p.add_argument(f"--{flag}", action="store_true")
    p.set_defaults(fn=cmd_refine)

    p = sub.add_parser("list", help="show current candidates")
    p.add_argument("--limit", type=int, default=40)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("aob", help="byte pattern search, ?? = wildcard")
    p.add_argument("pattern")
    common(p, with_type=False)
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(fn=cmd_aob)

    p = sub.add_parser("string", help="search for text")
    p.add_argument("text")
    common(p, with_type=False)
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(fn=cmd_string)

    p = sub.add_parser("pointers-to", help="find pointers to an address")
    p.add_argument("address", type=lambda s: int(s, 0))
    common(p, with_type=False)
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(fn=cmd_pointers_to)

    p = sub.add_parser("read", help="hex dump")
    p.add_argument("address", type=lambda s: int(s, 0))
    p.add_argument("--len", type=int, default=64)
    p.set_defaults(fn=cmd_read)

    p = sub.add_parser("watch", help="poll addresses live")
    p.add_argument("addresses", nargs="+", type=lambda s: int(s, 0))
    p.add_argument("--type", default="f32", choices=sorted(DTYPES))
    p.add_argument("--hz", type=float, default=4)
    p.set_defaults(fn=cmd_watch)

    args = ap.parse_args()
    try:
        proc = DuniaProcess.attach(args.process)
    except ProcessNotFound as exc:
        sys.exit(f"{exc}")
    with proc:
        args.fn(args, proc)


if __name__ == "__main__":
    main()
