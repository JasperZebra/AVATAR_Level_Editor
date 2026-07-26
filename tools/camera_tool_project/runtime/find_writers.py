#!/usr/bin/env python3
"""
"Find what writes to this address" -- hardware breakpoints via the debug registers.

This is the tool Cheat Engine uses for the same job, and the one thing the
scanner cannot do. It answers the question that matters for a freecam: which
instruction produces the camera matrix?

How it works: attach as a debugger, program DR0 on every thread with a
write-watch on the target address, then catch the resulting single-step
exceptions. EIP at the exception is the instruction *after* the write, so the
writing instruction ends just before it. Both are reported, translated back to
Dunia static addresses so they can be looked up in the decompile.

    python find_writers.py 0x0c3cc950
    python find_writers.py 0x0c3cc950 --seconds 8 --len 4

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!! DO NOT RUN THIS YET -- IT IS STRONGLY SUSPECTED OF CRASHING THE GAME.     !!
!!                                                                           !!
!! 2026-07-25: two runs, two dead games. First run reported a clean detach    !!
!! and the game closed moments later; second run crashed it outright. Both    !!
!! runs ALSO caught zero writes -- including on a player-position address     !!
!! that is written every frame -- so the breakpoints were probably never      !!
!! actually armed, meaning we took all of the risk and none of the benefit.   !!
!!                                                                           !!
!! Before ever running this again:                                           !!
!!   1. Verify DR0/DR7 actually stick (readback added below; if DR0 reads     !!
!!      back as 0 the whole approach is dead on this target).                 !!
!!   2. Test against a THROWAWAY process, never the game.                     !!
!!   3. Prefer static analysis of the decompile -- it is free and safe.       !!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

Attaching a debugger pauses the game on every hit. DebugSetProcessKillOnExit is
disabled first, so the game *should* survive detach -- but observed behaviour
says otherwise. Treat detach as unsafe on this title.

The target must be 4-byte aligned for a 4-byte watch (x86 requirement).
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import collections
import sys
import time

from dunia_process import DuniaProcess, ProcessNotFound, k32

TH32CS_SNAPTHREAD = 0x00000004
THREAD_ALL_ACCESS = 0x1F03FF
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

WOW64_CONTEXT_i386 = 0x00010000
WOW64_CONTEXT_CONTROL = WOW64_CONTEXT_i386 | 0x1
WOW64_CONTEXT_INTEGER = WOW64_CONTEXT_i386 | 0x2
WOW64_CONTEXT_DEBUG_REGISTERS = WOW64_CONTEXT_i386 | 0x10
WOW64_CONTEXT_FULL_DEBUG = (WOW64_CONTEXT_CONTROL | WOW64_CONTEXT_INTEGER
                            | WOW64_CONTEXT_DEBUG_REGISTERS)

EXCEPTION_DEBUG_EVENT = 1
CREATE_THREAD_DEBUG_EVENT = 2
CREATE_PROCESS_DEBUG_EVENT = 3
EXIT_THREAD_DEBUG_EVENT = 4
EXCEPTION_SINGLE_STEP = 0x80000004
EXCEPTION_BREAKPOINT = 0x80000003
DBG_CONTINUE = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                ("th32ThreadID", wt.DWORD), ("th32OwnerProcessID", wt.DWORD),
                ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long),
                ("dwFlags", wt.DWORD)]


class WOW64_FLOATING_SAVE_AREA(ctypes.Structure):
    _fields_ = [("ControlWord", wt.DWORD), ("StatusWord", wt.DWORD),
                ("TagWord", wt.DWORD), ("ErrorOffset", wt.DWORD),
                ("ErrorSelector", wt.DWORD), ("DataOffset", wt.DWORD),
                ("DataSelector", wt.DWORD), ("RegisterArea", ctypes.c_byte * 80),
                ("Cr0NpxState", wt.DWORD)]


class WOW64_CONTEXT(ctypes.Structure):
    _fields_ = [
        ("ContextFlags", wt.DWORD),
        ("Dr0", wt.DWORD), ("Dr1", wt.DWORD), ("Dr2", wt.DWORD),
        ("Dr3", wt.DWORD), ("Dr6", wt.DWORD), ("Dr7", wt.DWORD),
        ("FloatSave", WOW64_FLOATING_SAVE_AREA),
        ("SegGs", wt.DWORD), ("SegFs", wt.DWORD), ("SegEs", wt.DWORD),
        ("SegDs", wt.DWORD),
        ("Edi", wt.DWORD), ("Esi", wt.DWORD), ("Ebx", wt.DWORD),
        ("Edx", wt.DWORD), ("Ecx", wt.DWORD), ("Eax", wt.DWORD),
        ("Ebp", wt.DWORD), ("Eip", wt.DWORD), ("SegCs", wt.DWORD),
        ("EFlags", wt.DWORD), ("Esp", wt.DWORD), ("SegSs", wt.DWORD),
        ("ExtendedRegisters", ctypes.c_byte * 512),
    ]


class EXCEPTION_RECORD32(ctypes.Structure):
    _fields_ = [("ExceptionCode", wt.DWORD), ("ExceptionFlags", wt.DWORD),
                ("ExceptionRecord", ctypes.c_void_p),
                ("ExceptionAddress", ctypes.c_void_p),
                ("NumberParameters", wt.DWORD),
                ("ExceptionInformation", ctypes.c_void_p * 15)]


class EXCEPTION_DEBUG_INFO(ctypes.Structure):
    _fields_ = [("ExceptionRecord", EXCEPTION_RECORD32),
                ("dwFirstChance", wt.DWORD)]


class DEBUG_EVENT_UNION(ctypes.Union):
    _fields_ = [("Exception", EXCEPTION_DEBUG_INFO),
                ("_pad", ctypes.c_byte * 256)]


class DEBUG_EVENT(ctypes.Structure):
    _fields_ = [("dwDebugEventCode", wt.DWORD), ("dwProcessId", wt.DWORD),
                ("dwThreadId", wt.DWORD), ("u", DEBUG_EVENT_UNION)]


k32.DebugActiveProcess.argtypes = [wt.DWORD]
k32.DebugActiveProcess.restype = wt.BOOL
k32.DebugActiveProcessStop.argtypes = [wt.DWORD]
k32.DebugActiveProcessStop.restype = wt.BOOL
k32.DebugSetProcessKillOnExit.argtypes = [wt.BOOL]
k32.DebugSetProcessKillOnExit.restype = wt.BOOL
k32.WaitForDebugEvent.argtypes = [ctypes.POINTER(DEBUG_EVENT), wt.DWORD]
k32.WaitForDebugEvent.restype = wt.BOOL
k32.ContinueDebugEvent.argtypes = [wt.DWORD, wt.DWORD, wt.DWORD]
k32.ContinueDebugEvent.restype = wt.BOOL
k32.OpenThread.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenThread.restype = wt.HANDLE
k32.Wow64GetThreadContext.argtypes = [wt.HANDLE, ctypes.POINTER(WOW64_CONTEXT)]
k32.Wow64GetThreadContext.restype = wt.BOOL
k32.Wow64SetThreadContext.argtypes = [wt.HANDLE, ctypes.POINTER(WOW64_CONTEXT)]
k32.Wow64SetThreadContext.restype = wt.BOOL
k32.SuspendThread.argtypes = [wt.HANDLE]
k32.ResumeThread.argtypes = [wt.HANDLE]
k32.Thread32First.argtypes = [wt.HANDLE, ctypes.POINTER(THREADENTRY32)]
k32.Thread32First.restype = wt.BOOL
k32.Thread32Next.argtypes = [wt.HANDLE, ctypes.POINTER(THREADENTRY32)]
k32.Thread32Next.restype = wt.BOOL


def thread_ids(pid: int):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if snap == INVALID_HANDLE_VALUE:
        raise OSError(ctypes.get_last_error(), "thread snapshot failed")
    out = []
    try:
        e = THREADENTRY32()
        e.dwSize = ctypes.sizeof(THREADENTRY32)
        if k32.Thread32First(snap, ctypes.byref(e)):
            while True:
                if e.th32OwnerProcessID == pid:
                    out.append(e.th32ThreadID)
                if not k32.Thread32Next(snap, ctypes.byref(e)):
                    break
    finally:
        k32.CloseHandle(snap)
    return out


def dr7_for_write(length: int) -> int:
    """DR7 enabling breakpoint 0 as a data-write watch of `length` bytes."""
    len_bits = {1: 0b00, 2: 0b01, 4: 0b11, 8: 0b10}[length]
    rw_write = 0b01
    return (1 << 0) | (rw_write << 16) | (len_bits << 18)


def set_breakpoint(tid: int, address: int, length: int, enable: bool) -> bool:
    h = k32.OpenThread(THREAD_ALL_ACCESS, False, tid)
    if not h:
        return False
    try:
        k32.SuspendThread(h)
        ctx = WOW64_CONTEXT()
        ctx.ContextFlags = WOW64_CONTEXT_DEBUG_REGISTERS
        if not k32.Wow64GetThreadContext(h, ctypes.byref(ctx)):
            return False
        if enable:
            ctx.Dr0 = address & 0xFFFFFFFF
            ctx.Dr7 = dr7_for_write(length)
        else:
            ctx.Dr0 = 0
            ctx.Dr7 = 0
        ctx.Dr6 = 0
        ctx.ContextFlags = WOW64_CONTEXT_DEBUG_REGISTERS
        ok = bool(k32.Wow64SetThreadContext(h, ctypes.byref(ctx)))
        return ok
    finally:
        k32.ResumeThread(h)
        k32.CloseHandle(h)


def read_eip(tid: int):
    h = k32.OpenThread(THREAD_ALL_ACCESS, False, tid)
    if not h:
        return None
    try:
        ctx = WOW64_CONTEXT()
        ctx.ContextFlags = WOW64_CONTEXT_FULL_DEBUG
        if not k32.Wow64GetThreadContext(h, ctypes.byref(ctx)):
            return None
        return ctx
    finally:
        k32.CloseHandle(h)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("address", type=lambda s: int(s, 0))
    ap.add_argument("--len", type=int, default=4, choices=[1, 2, 4])
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--process", default="Avatar.exe")
    args = ap.parse_args()

    if args.address % args.len:
        sys.exit(f"address must be {args.len}-byte aligned for a {args.len}-byte watch")

    try:
        proc = DuniaProcess.attach(args.process)
    except ProcessNotFound as exc:
        sys.exit(str(exc))

    pid = proc.pid
    slide = proc.slide
    dbase, dsize = proc.modules()["Dunia.dll"]
    preview = proc.try_read(args.address, args.len)
    print(f"watching writes to {args.address:#010x} "
          f"(currently {preview.hex(' ') if preview else '??'})")
    proc.close()

    if not k32.DebugActiveProcess(pid):
        sys.exit(f"DebugActiveProcess failed: {ctypes.get_last_error()} "
                 f"(already debugged, or needs admin)")
    k32.DebugSetProcessKillOnExit(False)
    print("attached as debugger -- the game will stutter while this runs\n")

    hits = collections.Counter()
    contexts = {}
    armed = set()
    events = collections.Counter()
    exceptions = collections.Counter()
    evt = DEBUG_EVENT()
    deadline = time.time() + args.seconds

    try:
        all_tids = thread_ids(pid)
        failed = 0
        for tid in all_tids:
            if set_breakpoint(tid, args.address, args.len, True):
                armed.add(tid)
            else:
                failed += 1
        print(f"armed DR0 on {len(armed)}/{len(all_tids)} thread(s)"
              + (f", {failed} failed" if failed else ""))

        # Verify the write actually took -- Wow64SetThreadContext can report
        # success without the debug registers sticking.
        if armed:
            probe = next(iter(armed))
            h = k32.OpenThread(THREAD_ALL_ACCESS, False, probe)
            if h:
                c = WOW64_CONTEXT()
                c.ContextFlags = WOW64_CONTEXT_DEBUG_REGISTERS
                if k32.Wow64GetThreadContext(h, ctypes.byref(c)):
                    print(f"readback tid {probe}: Dr0={c.Dr0:#010x} Dr7={c.Dr7:#010x} "
                          f"(want Dr0={args.address:#010x} "
                          f"Dr7={dr7_for_write(args.len):#010x})")
                    if c.Dr0 != (args.address & 0xFFFFFFFF):
                        print("  !! DR0 DID NOT STICK -- breakpoints are not armed")
                k32.CloseHandle(h)

        while time.time() < deadline:
            if not k32.WaitForDebugEvent(ctypes.byref(evt), 200):
                continue
            status = DBG_CONTINUE
            code = evt.dwDebugEventCode

            if code == EXCEPTION_DEBUG_EVENT:
                exc = evt.u.Exception.ExceptionRecord.ExceptionCode
                if exc == EXCEPTION_SINGLE_STEP:
                    ctx = read_eip(evt.dwThreadId)
                    if ctx:
                        hits[ctx.Eip] += 1
                        contexts.setdefault(ctx.Eip, ctx)
                elif exc == EXCEPTION_BREAKPOINT:
                    pass                      # initial attach breakpoint
                else:
                    status = DBG_EXCEPTION_NOT_HANDLED
            elif code in (CREATE_THREAD_DEBUG_EVENT, CREATE_PROCESS_DEBUG_EVENT):
                # New threads start with clean debug registers -- arm them too.
                if evt.dwThreadId not in armed:
                    if set_breakpoint(evt.dwThreadId, args.address, args.len, True):
                        armed.add(evt.dwThreadId)
            elif code == EXIT_THREAD_DEBUG_EVENT:
                armed.discard(evt.dwThreadId)

            k32.ContinueDebugEvent(evt.dwProcessId, evt.dwThreadId, status)
    finally:
        for tid in list(armed):
            set_breakpoint(tid, args.address, args.len, False)
        k32.DebugActiveProcessStop(pid)
        print("detached\n")

    if not hits:
        print("no writes caught. either nothing wrote it in that window,")
        print("or the address is stale -- re-run the scan and try again.")
        return

    print(f"{sum(hits.values())} write(s) from {len(hits)} distinct site(s):\n")
    for eip, n in hits.most_common(12):
        in_dunia = dbase <= eip < dbase + dsize
        static = eip - slide if in_dunia else None
        where = f"Dunia static {static:#010x}" if in_dunia else "outside Dunia"
        print(f"  EIP {eip:#010x}  x{n:<5}  ({where})")
        print(f"      the writing instruction ends just before this address")
        c = contexts[eip]
        print(f"      eax={c.Eax:#010x} ecx={c.Ecx:#010x} edx={c.Edx:#010x} "
              f"esi={c.Esi:#010x} edi={c.Edi:#010x}")
        if in_dunia:
            print(f"      look up FUN_ containing {static:#010x} in the decompile")
        print()


if __name__ == "__main__":
    main()
