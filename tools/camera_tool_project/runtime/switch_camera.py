#!/usr/bin/env python3
"""
Call Dunia's own SwitchCamera in the live game.

    SwitchCamera(int cameraType, EntityId entity)      cdecl, EntityId is 64-bit

Derived by tracing the stack through the prologue at 0x10a88680:

    sub esp, 8 / push esi / push edi / ... / pop edi

leaves the arguments at [esp+0x10] (cameraType) and [esp+0x14] / [esp+0x18]
(the low and high dwords of EntityId). So on the stack, cdecl order:

    push entityId_hi
    push entityId_lo
    push cameraType
    call SwitchCamera
    add  esp, 0xC

The camera entities ship in the game's own entity library with fixed IDs
(see NOTES.md) -- Camera.Free is 262.

    python switch_camera.py free
    python switch_camera.py 262 --type 1
    python switch_camera.py free --dry-run      # show shellcode, execute nothing

*** THIS EXECUTES CODE INSIDE THE GAME PROCESS. ***

Two known risks, neither hypothetical:

  1. The call runs on a NEW thread, not the engine's main thread. Dunia is not
     obviously thread-safe here; touching the camera stack concurrently with a
     frame update can corrupt it. A crash is a plausible outcome.
  2. The entity IDs below are *entity library prototype* IDs. Whether the
     runtime EntityId matches has NOT been verified. A wrong handle may resolve
     to garbage.

Save your game first. Treat a crash as information, not failure.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import sys

from dunia_process import DuniaProcess, ProcessNotFound, k32

# Static VA of SwitchCamera, from the retail-1.02 decompile. Translated through
# the ASLR slide before use.
SWITCH_CAMERA_VA = 0x10a88680

# First 8 bytes of SwitchCamera: mov eax,[0x111e61f8] ; sub esp,8
SWITCH_CAMERA_SIG = bytes.fromhex("a1f8611e1183ec08")

# Camera entity prototype IDs, read out of the shipped entitylibrary.fcb.
CAMERAS = {
    "animatedtoken": 255, "bone": 256, "cinematic": 257, "editor": 258,
    "first": 259, "firstavatar": 260, "firstcorp": 261, "free": 262,
    "freeorbital": 263, "ghost": 264, "marketing": 265, "planet": 266,
    "spectator": 267, "third": 268, "thirdavatar": 269, "thirdcorp": 270,
}

MEM_COMMIT_RESERVE = 0x3000
PAGE_EXECUTE_READWRITE = 0x40
MEM_RELEASE = 0x8000
INFINITE = 0xFFFFFFFF

k32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                               wt.DWORD, wt.DWORD]
k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.VirtualFreeEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD]
k32.VirtualFreeEx.restype = wt.BOOL
k32.CreateRemoteThread.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                   ctypes.c_void_p, ctypes.c_void_p, wt.DWORD,
                                   ctypes.POINTER(wt.DWORD)]
k32.CreateRemoteThread.restype = wt.HANDLE
k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
k32.WaitForSingleObject.restype = wt.DWORD
k32.GetExitCodeThread.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
k32.GetExitCodeThread.restype = wt.BOOL


def build_stub(fn: int, camera_type: int, entity_id: int) -> bytes:
    """x86 stub that performs the cdecl call and exits the thread cleanly."""
    lo = entity_id & 0xFFFFFFFF
    hi = (entity_id >> 32) & 0xFFFFFFFF
    return b"".join([
        b"\x68" + struct.pack("<I", hi),          # push hi
        b"\x68" + struct.pack("<I", lo),          # push lo
        b"\x68" + struct.pack("<I", camera_type), # push cameraType
        b"\xB8" + struct.pack("<I", fn),          # mov  eax, SwitchCamera
        b"\xFF\xD0",                              # call eax
        b"\x83\xC4\x0C",                          # add  esp, 0xC   (cdecl cleanup)
        b"\x31\xC0",                              # xor  eax, eax   (exit code 0)
        b"\xC2\x04\x00",                          # ret  4          (stdcall ThreadProc)
    ])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("camera", help="camera name (%s) or a numeric entity id"
                                   % ", ".join(sorted(CAMERAS)))
    ap.add_argument("--type", type=int, default=1,
                    help="cameraType argument; 0 reverts to the default camera")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the stub and exit without touching the game")
    args = ap.parse_args()

    key = args.camera.lower()
    if key in CAMERAS:
        entity_id = CAMERAS[key]
    elif args.camera.isdigit():
        entity_id = int(args.camera)
    else:
        sys.exit(f"unknown camera {args.camera!r}; known: {', '.join(sorted(CAMERAS))}")

    try:
        proc = DuniaProcess.attach(write=True)
    except ProcessNotFound as exc:
        sys.exit(f"{exc} -- start the game and load a level first")

    with proc:
        fn = proc.to_runtime(SWITCH_CAMERA_VA)

        # Refuse to run against a binary that is not the one we analysed.
        head = proc.try_read(fn, len(SWITCH_CAMERA_SIG))
        if head is None:
            sys.exit(f"cannot read {fn:#x} -- Dunia.dll not loaded as expected")
        if head != SWITCH_CAMERA_SIG:
            sys.exit(f"signature mismatch at {fn:#x}\n"
                     f"  expected {SWITCH_CAMERA_SIG.hex(' ')}\n"
                     f"  found    {head.hex(' ')}\n"
                     f"The loaded Dunia.dll differs from the analysed one; "
                     f"re-derive the address before calling.")

        stub = build_stub(fn, args.type, entity_id)
        print(f"Dunia.dll base   {proc.dunia_base:#010x}  (slide {proc.slide:+#x})")
        print(f"SwitchCamera     {fn:#010x}  signature verified")
        print(f"call             SwitchCamera(type={args.type}, entity={entity_id})")
        print(f"stub             {stub.hex(' ')}")

        if args.dry_run:
            print("\ndry run -- nothing executed")
            return

        remote = k32.VirtualAllocEx(proc.handle, None, len(stub),
                                    MEM_COMMIT_RESERVE, PAGE_EXECUTE_READWRITE)
        if not remote:
            sys.exit(f"VirtualAllocEx failed: {ctypes.get_last_error()}")
        try:
            proc.write(remote, stub)
            tid = wt.DWORD(0)
            thread = k32.CreateRemoteThread(proc.handle, None, 0,
                                            ctypes.c_void_p(remote), None, 0,
                                            ctypes.byref(tid))
            if not thread:
                sys.exit(f"CreateRemoteThread failed: {ctypes.get_last_error()}")
            print(f"\nremote thread    tid={tid.value} at {remote:#010x}")
            waited = k32.WaitForSingleObject(thread, 5000)
            if waited == 0:
                code = wt.DWORD(0)
                k32.GetExitCodeThread(thread, ctypes.byref(code))
                print(f"returned         exit code {code.value}")
                print("\nlook at the game -- did the view change?")
            else:
                print("thread did not finish within 5s (still running or blocked)")
            k32.CloseHandle(thread)
        finally:
            k32.VirtualFreeEx(proc.handle, ctypes.c_void_p(remote), 0, MEM_RELEASE)


if __name__ == "__main__":
    main()
