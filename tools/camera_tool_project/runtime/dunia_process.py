#!/usr/bin/env python3
"""
Live process access for Avatar's Dunia.dll.

Read-only by default. Everything here is plain ctypes against kernel32 -- no
third-party dependency, and a 64-bit Python can drive the 32-bit game fine
since every address in the target fits in 32 bits.

The single most important service this provides is the ASLR slide. Every
address in NOTES.md is a *static* VA assuming Dunia.dll's preferred image base
0x10000000. At runtime the DLL lands wherever the loader put it, so static
addresses must be translated before use:

    proc = DuniaProcess.attach()
    live = proc.to_runtime(0x10a88680)      # SwitchCamera

Usage:
    python dunia_process.py              # attach and report
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
PROCESS_QUERY_INFORMATION = 0x0400

# Dunia.dll's preferred base. Static addresses in NOTES.md assume this.
PREFERRED_BASE = 0x10000000

MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_char * 260),
    ]


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("GlblcntUsage", wt.DWORD), ("ProccntUsage", wt.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)), ("modBaseSize", wt.DWORD),
        ("hModule", wt.HMODULE), ("szModule", ctypes.c_char * 256),
        ("szExePath", ctypes.c_char * 260),
    ]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wt.DWORD), ("RegionSize", ctypes.c_size_t),
        ("State", wt.DWORD), ("Protect", wt.DWORD), ("Type", wt.DWORD),
    ]


# Explicit prototypes. Without these ctypes marshals handles as C int, which
# truncates on 64-bit -- it happens to work while handle values stay small, but
# it is a latent crash. Declare everything.
k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.Process32First.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
k32.Process32First.restype = wt.BOOL
k32.Process32Next.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
k32.Process32Next.restype = wt.BOOL
k32.Module32First.argtypes = [wt.HANDLE, ctypes.POINTER(MODULEENTRY32)]
k32.Module32First.restype = wt.BOOL
k32.Module32Next.argtypes = [wt.HANDLE, ctypes.POINTER(MODULEENTRY32)]
k32.Module32Next.restype = wt.BOOL
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenProcess.restype = wt.HANDLE
k32.CloseHandle.argtypes = [wt.HANDLE]
k32.CloseHandle.restype = wt.BOOL
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype = wt.BOOL
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.WriteProcessMemory.restype = wt.BOOL
k32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p,
                               ctypes.POINTER(MEMORY_BASIC_INFORMATION),
                               ctypes.c_size_t]
k32.VirtualQueryEx.restype = ctypes.c_size_t


class ProcessNotFound(RuntimeError):
    pass


class DuniaProcess:
    """An attached Avatar game process."""

    def __init__(self, pid: int, handle: int):
        self.pid = pid
        self.handle = handle
        self._modules: dict[str, tuple[int, int]] = {}

    # -- attach ----------------------------------------------------------

    @classmethod
    def find_pid(cls, name: str = "Avatar.exe") -> int:
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == INVALID_HANDLE_VALUE:
            raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
        try:
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            wanted = name.lower().encode()
            if not k32.Process32First(snap, ctypes.byref(entry)):
                raise ProcessNotFound(f"no processes enumerable")
            while True:
                if entry.szExeFile.lower() == wanted:
                    return entry.th32ProcessID
                if not k32.Process32Next(snap, ctypes.byref(entry)):
                    raise ProcessNotFound(f"{name} is not running")
        finally:
            k32.CloseHandle(snap)

    @classmethod
    def attach(cls, name: str = "Avatar.exe", write: bool = False) -> "DuniaProcess":
        pid = cls.find_pid(name)
        access = PROCESS_VM_READ | PROCESS_QUERY_INFORMATION
        if write:
            access |= PROCESS_VM_WRITE | PROCESS_VM_OPERATION
        handle = k32.OpenProcess(access, False, pid)
        if not handle:
            err = ctypes.get_last_error()
            hint = " (try running as administrator)" if err == 5 else ""
            raise OSError(err, f"OpenProcess failed for pid {pid}{hint}")
        return cls(pid, handle)

    def close(self):
        if self.handle:
            k32.CloseHandle(self.handle)
            self.handle = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- modules ---------------------------------------------------------

    def modules(self) -> dict[str, tuple[int, int]]:
        """name -> (base, size). Cached after the first call."""
        if self._modules:
            return self._modules
        snap = k32.CreateToolhelp32Snapshot(
            TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, self.pid)
        if snap == INVALID_HANDLE_VALUE:
            raise OSError(ctypes.get_last_error(), "module snapshot failed")
        try:
            entry = MODULEENTRY32()
            entry.dwSize = ctypes.sizeof(MODULEENTRY32)
            if not k32.Module32First(snap, ctypes.byref(entry)):
                raise OSError(ctypes.get_last_error(), "Module32First failed")
            while True:
                base = ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value or 0
                self._modules[entry.szModule.decode(errors="replace")] = (
                    base, entry.modBaseSize)
                if not k32.Module32Next(snap, ctypes.byref(entry)):
                    break
        finally:
            k32.CloseHandle(snap)
        return self._modules

    @property
    def dunia_base(self) -> int:
        mods = self.modules()
        for name, (base, _size) in mods.items():
            if name.lower() == "dunia.dll":
                return base
        raise RuntimeError("Dunia.dll is not loaded in this process")

    @property
    def slide(self) -> int:
        """Runtime base minus the preferred base recorded in NOTES.md."""
        return self.dunia_base - PREFERRED_BASE

    def to_runtime(self, static_va: int) -> int:
        """Translate a NOTES.md static address into a live address."""
        return static_va + self.slide

    def to_static(self, runtime_va: int) -> int:
        """Inverse of to_runtime -- for reporting addresses back into NOTES.md."""
        return runtime_va - self.slide

    # -- memory ----------------------------------------------------------

    def read(self, address: int, size: int) -> bytes:
        # Callers routinely pass numpy integers from scan results; ctypes will
        # not coerce those, so normalise here rather than at every call site.
        address, size = int(address), int(size)
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t(0)
        ok = k32.ReadProcessMemory(self.handle, ctypes.c_void_p(address),
                                   buf, size, ctypes.byref(got))
        if not ok:
            raise OSError(ctypes.get_last_error(),
                          f"ReadProcessMemory failed at {address:#x}")
        return buf.raw[:got.value]

    def try_read(self, address: int, size: int) -> bytes | None:
        """read() that returns None instead of raising, for probing."""
        try:
            return self.read(address, size)
        except OSError:
            return None

    def write(self, address: int, data: bytes) -> int:
        address = int(address)
        wrote = ctypes.c_size_t(0)
        ok = k32.WriteProcessMemory(self.handle, ctypes.c_void_p(address),
                                    data, len(data), ctypes.byref(wrote))
        if not ok:
            raise OSError(ctypes.get_last_error(),
                          f"WriteProcessMemory failed at {address:#x}")
        return wrote.value

    def read_u32(self, address: int) -> int:
        return struct.unpack("<I", self.read(address, 4))[0]

    def read_f32(self, address: int) -> float:
        return struct.unpack("<f", self.read(address, 4))[0]

    def read_vec3(self, address: int) -> tuple[float, float, float]:
        return struct.unpack("<3f", self.read(address, 12))

    def read_cstring(self, address: int, limit: int = 128) -> str:
        raw = self.try_read(address, limit) or b""
        return raw.split(b"\x00")[0].decode("utf-8", errors="replace")

    # -- region walk -----------------------------------------------------

    def regions(self):
        """Yield (base, size, protect) for committed, readable regions."""
        mbi = MEMORY_BASIC_INFORMATION()
        address = 0
        max_address = 0x7FFF0000  # 32-bit user space ceiling
        while address < max_address:
            got = k32.VirtualQueryEx(self.handle, ctypes.c_void_p(address),
                                     ctypes.byref(mbi), ctypes.sizeof(mbi))
            if not got:
                break
            base = mbi.BaseAddress or 0
            size = mbi.RegionSize
            if size == 0:
                break
            readable = (mbi.State == MEM_COMMIT
                        and not (mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS)))
            if readable:
                yield base, size, mbi.Protect
            address = base + size


def main():
    if sys.platform != "win32":
        sys.exit("windows only")

    try:
        proc = DuniaProcess.attach()
    except ProcessNotFound as exc:
        sys.exit(f"{exc} -- start the game first, then re-run")

    with proc:
        base = proc.dunia_base
        print(f"attached to Avatar.exe   pid={proc.pid}")
        print(f"Dunia.dll base           {base:#010x}")
        print(f"ASLR slide               {proc.slide:+#x}"
              f"{'  (loaded at preferred base)' if proc.slide == 0 else ''}")
        print()

        # Sanity check: the first bytes of SwitchCamera should match what the
        # on-disk decompile showed -- mov eax, [abs32] is 'A1'.
        switch_camera = proc.to_runtime(0x10a88680)
        head = proc.try_read(switch_camera, 8)
        print(f"SwitchCamera             {switch_camera:#010x}")
        if head is None:
            print("  !! unreadable -- wrong module or bad slide")
        else:
            print(f"  first bytes            {head.hex(' ')}")
            print(f"  expected               a1 f8 61 1e 11 83 ec 08")
            print("  MATCH" if head.hex() == "a1f8611e1183ec08"
                  else "  MISMATCH -- the loaded DLL differs from the analysed one")

        print()
        print("loaded modules:")
        for name, (mbase, size) in sorted(proc.modules().items(),
                                          key=lambda kv: kv[1][0]):
            print(f"  {name:<28} {mbase:#010x}  {size / 1024:>9,.0f} KB")


if __name__ == "__main__":
    main()
