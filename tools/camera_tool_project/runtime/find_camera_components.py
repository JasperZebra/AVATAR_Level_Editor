#!/usr/bin/env python3
"""
Find live camera component instances in the running game. Read-only.

Every entity component holds a pointer to its class descriptor. The descriptor
globals are known (NOTES.md), so scanning the process for the descriptor's
*value* finds every object that points at it -- i.e. the live instances.

This answers the question SwitchCamera can't: does the loaded level actually
contain a Camera.Free entity, or is the prototype merely defined in the entity
library and never instantiated?

    python find_camera_components.py
"""

from __future__ import annotations

import struct
import sys

from dunia_process import DuniaProcess, ProcessNotFound

# Component descriptor accessor globals, from the decompile (NOTES.md).
DESCRIPTORS = {
    "CCameraFreeComponent":    0x11221b30,
    "CCameraGhostComponent":   0x11221b64,
    "CCameraNetworkComponent": 0x11221b18,
    # Controls: these MUST be live during normal gameplay. If they also scan as
    # zero, the scan technique is wrong and a zero result proves nothing.
    "CCameraThirdComponent":   0x11221bdc,
    "CCameraPawnComponent":    0x11221ba0,
    "CCameraComponent":        0x111e87c8,
}

# Skip the module's own image when reporting -- a pointer to the descriptor
# inside Dunia.dll's data is the registry, not an instance.
def main():
    try:
        proc = DuniaProcess.attach()
    except ProcessNotFound as exc:
        sys.exit(f"{exc} -- start the game and load a level first")

    with proc:
        dunia_base = proc.dunia_base
        dunia_end = dunia_base + proc.modules()["Dunia.dll"][1]

        targets = {}
        for name, global_va in DESCRIPTORS.items():
            value = proc.read_u32(proc.to_runtime(global_va))
            targets[value] = name
            print(f"{name:<26} descriptor global {global_va:#010x} -> {value:#010x}"
                  + ("   (NULL -- class never registered this session)"
                     if value == 0 else ""))
        targets.pop(0, None)
        if not targets:
            sys.exit("\nno descriptors registered -- is a level loaded?")

        print("\nscanning committed memory for pointers to those descriptors...")
        wanted = {struct.pack("<I", v): n for v, n in targets.items()}
        hits = {n: [] for n in targets.values()}
        scanned = 0

        for base, size, _protect in proc.regions():
            chunk = proc.try_read(base, size)
            if not chunk:
                continue
            scanned += size
            for needle, name in wanted.items():
                start = 0
                while True:
                    idx = chunk.find(needle, start)
                    if idx < 0:
                        break
                    hits[name].append(base + idx)
                    start = idx + 4

        print(f"scanned {scanned / 1024 / 1024:,.0f} MB\n")
        for name, addrs in hits.items():
            in_module = [a for a in addrs if dunia_base <= a < dunia_end]
            on_heap = [a for a in addrs if not (dunia_base <= a < dunia_end)]
            print(f"{name}")
            print(f"  {len(in_module)} reference(s) inside Dunia.dll (registry/static)")
            print(f"  {len(on_heap)} reference(s) on the heap  <-- live instances")
            for a in on_heap[:10]:
                # A component's descriptor pointer usually sits at a fixed offset
                # in the object; show a little context to help identify it.
                ctx = proc.try_read(max(a - 16, 0), 48)
                ctx_hex = ctx.hex(" ") if ctx else "<unreadable>"
                print(f"    {a:#010x}  ctx {ctx_hex}")
            if len(on_heap) > 10:
                print(f"    ... and {len(on_heap) - 10} more")
            print()


if __name__ == "__main__":
    main()
