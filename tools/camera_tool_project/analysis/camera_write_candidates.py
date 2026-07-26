#!/usr/bin/env python3
"""
Narrow the 4x4 matrix write sites down to the ones the camera can actually reach.

find_matrix_copies.py yields ~428 matrix write sites across Dunia.dll. Most
belong to physics, animation, rendering, particles -- anything with transforms.
This script keeps only those inside functions reachable from known camera code.

Method, entirely offline:
  1. Parse the decompile into functions and a call graph (callee addresses are
     just FUN_xxxxxxxx tokens appearing in each body).
  2. Map every matrix write site to its containing function.
  3. BFS forward from camera seed functions to a bounded depth.
  4. Report matrix writers that fall inside the reachable set, nearest first.

    python camera_write_candidates.py
    python camera_write_candidates.py --depth 4
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict, deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECOMPILE = HERE.parents[1] / "Avatar_Dunia_Retail_1.02_decrypted.dll_FULL_DECOMPILE.txt"

HEADER_RE = re.compile(r"^###\s+(\S+)\s+@\s+([0-9a-f]{8})")
CALL_RE = re.compile(r"FUN_([0-9a-f]{8})")

# Camera code established in NOTES.md.
SEEDS = {
    0x10248cd0: "CCameraComponent descriptor accessor",
    0x10249540: "camera stack: activate/push entity camera",
    0x10249d00: "camera stack: reset path",
    0x10249b00: "fetches live camera object, virtual call +0x80",
    0x1024a000: "contains the only matrix write in the camera region",
    0x10a88680: "SwitchCamera",
    0x104cac80: "CCameraFreeComponent descriptor accessor",
}


def parse_decompile():
    """-> (sorted function addresses, {addr: set(callee addrs)})"""
    funcs = []
    calls = defaultdict(set)
    current = None
    with DECOMPILE.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = HEADER_RE.match(line)
            if m:
                current = int(m.group(2), 16)
                funcs.append(current)
                continue
            if current is not None:
                for hit in CALL_RE.findall(line):
                    target = int(hit, 16)
                    if target != current:
                        calls[current].add(target)
    return sorted(funcs), calls


def containing(funcs, addr):
    """Function containing `addr` (last function starting at or before it)."""
    lo, hi = 0, len(funcs) - 1
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if funcs[mid] <= addr:
            best = funcs[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def matrix_sites():
    """Run find_matrix_copies.py and collect the site addresses."""
    out = subprocess.run(
        [sys.executable, str(HERE / "find_matrix_copies.py"),
         "--min-pairs", "4", "--limit", "100000"],
        capture_output=True, text=True, timeout=2400)
    sites = []
    for line in out.stdout.splitlines():
        m = re.match(r"^  (0x[0-9a-f]+)\s+\d+ pairs", line)
        if m:
            sites.append(int(m.group(1), 16))
    return sites


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--depth", type=int, default=3)
    args = ap.parse_args()

    print("parsing decompile...")
    funcs, calls = parse_decompile()
    print(f"  {len(funcs):,} functions, "
          f"{sum(len(v) for v in calls.values()):,} call edges")

    print("scanning for matrix writes (this takes a few minutes)...")
    sites = matrix_sites()
    print(f"  {len(sites)} matrix write sites")

    writers = defaultdict(list)
    for s in sites:
        fn = containing(funcs, s)
        if fn is not None:
            writers[fn].append(s)
    print(f"  in {len(writers)} distinct functions\n")

    # BFS out from the camera seeds.
    depth_of = {}
    q = deque()
    for seed in SEEDS:
        depth_of[seed] = 0
        q.append(seed)
    while q:
        fn = q.popleft()
        d = depth_of[fn]
        if d >= args.depth:
            continue
        for callee in calls.get(fn, ()):
            if callee not in depth_of:
                depth_of[callee] = d + 1
                q.append(callee)
    print(f"{len(depth_of):,} functions reachable from camera seeds "
          f"within depth {args.depth}\n")

    found = [(depth_of[fn], fn, s) for fn, s in writers.items() if fn in depth_of]
    found.sort()

    if not found:
        print("no matrix writers reachable from the camera seeds.")
        print("try --depth 4, or the write is reached via a virtual call")
        print("(the call graph cannot follow vtable dispatch).")
        return

    print(f"{len(found)} matrix-writing function(s) reachable from camera code:\n")
    for d, fn, s in found:
        via = ""
        if fn in SEEDS:
            via = f"  <-- SEED: {SEEDS[fn]}"
        print(f"  depth {d}  FUN_{fn:08x}{via}")
        print(f"            writes at: " + ", ".join(f"{x:#010x}" for x in s))


if __name__ == "__main__":
    main()
