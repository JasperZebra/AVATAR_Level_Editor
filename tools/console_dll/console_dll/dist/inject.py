"""Inject avatar_console.dll into the running Avatar.exe.

    python inject.py            inject (auto-finds pid and the dll next to this file)
    python inject.py --status   just report what is loaded, inject nothing

Why this is more involved than the usual snippet: Avatar.exe is 32-bit (WOW64) and
this script is very likely 64-bit Python, so
`GetProcAddress(GetModuleHandle("kernel32"), "LoadLibraryA")` would hand back the
*64-bit* address, which is meaningless in the target. Instead we locate the
target's own 32-bit kernel32.dll via a Toolhelp module snapshot and parse its
export directory straight out of the target's memory.

Injecting via LoadLibraryA on a remote thread is safe: it runs the Windows loader,
not engine code. The DLL then does all of its engine work from a vtable detour on
the game's main thread - which is the part that matters, and the part an earlier
CreateRemoteThread-into-the-dispatcher attempt got wrong.

There is now a second way in that needs no script at all: build.bat also writes
dinput8.dll, the same binary under the name Dunia.dll imports.  Copy it into
<install>\bin and the game loads the mod itself at startup.  See DISTRIBUTION.md.
This script stays for the build-test-build loop, where injecting into a running
game beats restarting it.

Files next to this script:
    avatar_console.dll   the mod - the only one that is required
    console_cmds.txt     OPTIONAL.  An additive Tab-completion cache; the same
                         722 names are compiled into the DLL (console_cmds_seed.h)
                         so deleting it costs nothing.
    avatar_cmds.txt      OPTIONAL, the lines F11 runs.  Yours to write.
"""
import ctypes
import ctypes.wintypes as wt
import os
import struct
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

TH32CS_SNAPPROCESS = 0x2
TH32CS_SNAPMODULE = 0x8
TH32CS_SNAPMODULE32 = 0x10
MEM_COMMIT_RESERVE = 0x3000
PAGE_READWRITE = 0x04
MEM_RELEASE = 0x8000
ACCESS = 0x0002 | 0x0400 | 0x0008 | 0x0020 | 0x0010


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_char * 260)]


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("GlblcntUsage", wt.DWORD), ("ProccntUsage", wt.DWORD),
                ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)), ("modBaseSize", wt.DWORD),
                ("hModule", wt.HMODULE), ("szModule", ctypes.c_char * 256),
                ("szExePath", ctypes.c_char * 260)]


k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
k32.ReadProcessMemory.restype = wt.BOOL
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.WriteProcessMemory.restype = wt.BOOL
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.CreateRemoteThread.restype = wt.HANDLE
k32.CreateRemoteThread.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                   ctypes.c_void_p, ctypes.c_void_p, wt.DWORD,
                                   ctypes.POINTER(wt.DWORD)]
k32.WaitForSingleObject.restype = wt.DWORD
k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
k32.GetExitCodeThread.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]


def find_pid(name="avatar.exe"):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    e = PROCESSENTRY32()
    e.dwSize = ctypes.sizeof(e)
    pid = None
    if k32.Process32First(snap, ctypes.byref(e)):
        while True:
            if e.szExeFile.decode(errors="ignore").lower() == name:
                pid = e.th32ProcessID
                break
            if not k32.Process32Next(snap, ctypes.byref(e)):
                break
    k32.CloseHandle(snap)
    return pid


def modules(pid):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap == wt.HANDLE(-1).value:
        return []
    m = MODULEENTRY32()
    m.dwSize = ctypes.sizeof(m)
    out = []
    if k32.Module32First(snap, ctypes.byref(m)):
        while True:
            out.append((m.szModule.decode(errors="ignore"),
                        ctypes.cast(m.modBaseAddr, ctypes.c_void_p).value or 0,
                        m.modBaseSize,
                        m.szExePath.decode(errors="ignore")))
            if not k32.Module32Next(snap, ctypes.byref(m)):
                break
    k32.CloseHandle(snap)
    return out


def rd(h, va, n):
    b = ctypes.create_string_buffer(n)
    g = ctypes.c_size_t(0)
    if k32.ReadProcessMemory(h, ctypes.c_void_p(va), b, n, ctypes.byref(g)):
        return b.raw[:g.value]
    return b""


def remote_export(h, base, want):
    """Resolve an export by parsing the target module's PE headers in its memory."""
    dos = rd(h, base, 0x40)
    if len(dos) < 0x40 or dos[:2] != b"MZ":
        return None
    e_lfanew = struct.unpack_from("<I", dos, 0x3C)[0]
    nt = rd(h, base + e_lfanew, 0x108)
    if nt[:4] != b"PE\0\0":
        return None
    magic = struct.unpack_from("<H", nt, 0x18)[0]
    exp_rva_off = 0x78 if magic == 0x10B else 0x88          # PE32 vs PE32+
    exp_rva = struct.unpack_from("<I", nt, exp_rva_off)[0]
    if not exp_rva:
        return None
    ed = rd(h, base + exp_rva, 0x28)
    n_names = struct.unpack_from("<I", ed, 0x18)[0]
    a_funcs = struct.unpack_from("<I", ed, 0x1C)[0]
    a_names = struct.unpack_from("<I", ed, 0x20)[0]
    a_ords = struct.unpack_from("<I", ed, 0x24)[0]
    names = rd(h, base + a_names, 4 * n_names)
    ords = rd(h, base + a_ords, 2 * n_names)
    for i in range(n_names):
        nrva = struct.unpack_from("<I", names, 4 * i)[0]
        nm = rd(h, base + nrva, 64)
        z = nm.find(b"\x00")
        if z > 0 and nm[:z] == want:
            o = struct.unpack_from("<H", ords, 2 * i)[0]
            frva = struct.unpack_from("<I", rd(h, base + a_funcs + 4 * o, 4), 0)[0]
            return base + frva
    return None


here = os.path.dirname(os.path.abspath(__file__))
dll = os.path.join(here, "avatar_console.dll")
status_only = "--status" in sys.argv

pid = find_pid()
if not pid:
    print("Avatar.exe is not running - launch the game and load a save first.")
    sys.exit(1)
print("Avatar.exe pid %d" % pid)

h = k32.OpenProcess(ACCESS, False, pid)
if not h:
    print("OpenProcess failed err=%d - try an elevated terminal." % ctypes.get_last_error())
    sys.exit(1)

mods = modules(pid)
loaded = [m for m in mods if m[0].lower() == "avatar_console.dll"]
dunia = [m for m in mods if m[0].lower() == "dunia.dll"]

# THE PROXY IS THE SAME MOD UNDER ANOTHER NAME.  dinput8.dll dropped into the
# game's bin folder is a byte-for-byte copy of avatar_console.dll that decides
# from its own file name to auto-load, so a process that already has it does not
# want a second copy: two sets of vtable detours, two overlay windows, two
# editor-link pipes fighting over one name.  The give-away is the PATH - every
# machine has a dinput8.dll loaded from SysWOW64, and that one is the real
# system DLL sitting behind ours.  Only a copy loaded from the game's own folder
# is the mod.
game_dir = os.path.dirname(dunia[0][3]).lower() if dunia else ""
proxy = [m for m in mods
         if m[0].lower() == "dinput8.dll"
         and game_dir and os.path.dirname(m[3]).lower() == game_dir]

print("modules visible: %d" % len(mods))
if dunia:
    print("  Dunia.dll base 0x%08X %s" % (dunia[0][1],
          "(preferred base, decompile addresses map 1:1)" if dunia[0][1] == 0x10000000 else
          "(NOT the preferred base - hardcoded addresses would be wrong!)"))
print("  avatar_console.dll: %s" % ("LOADED" if loaded else "not loaded"))
print("  dinput8.dll proxy : %s" % (proxy[0][3] if proxy else "not installed"))

if status_only:
    sys.exit(0)
if proxy:
    print("\nThe mod is ALREADY IN THIS PROCESS, auto-loaded as:\n    %s"
          "\n\nInjecting a second copy would install a second set of hooks on the\n"
          "same vtable slot and is not survivable. Nothing was injected.\n"
          "Delete that file and restart the game if you want the inject.py\n"
          "workflow back." % proxy[0][3])
    sys.exit(1)
if loaded:
    print("\nalready injected - press End in-game to unload it first.")
    sys.exit(0)
if not os.path.exists(dll):
    print("\n%s not found - run build.bat first." % dll)
    sys.exit(1)

k32mod = [m for m in mods if m[0].lower() == "kernel32.dll"]
if not k32mod:
    print("could not find kernel32.dll in the target")
    sys.exit(1)
lla = remote_export(h, k32mod[0][1], b"LoadLibraryA")
if not lla:
    print("could not resolve LoadLibraryA in the target's kernel32")
    sys.exit(1)
print("  target LoadLibraryA @ 0x%08X" % lla)

payload = dll.encode("ascii") + b"\x00"
mem = k32.VirtualAllocEx(h, None, len(payload), MEM_COMMIT_RESERVE, PAGE_READWRITE)
w = ctypes.c_size_t(0)
k32.WriteProcessMemory(h, ctypes.c_void_p(mem), payload, len(payload), ctypes.byref(w))

tid = wt.DWORD(0)
th = k32.CreateRemoteThread(h, None, 0, ctypes.c_void_p(lla), ctypes.c_void_p(mem), 0,
                            ctypes.byref(tid))
if not th:
    print("CreateRemoteThread failed err=%d" % ctypes.get_last_error())
    sys.exit(1)
k32.WaitForSingleObject(th, 10000)
code = wt.DWORD(0)
k32.GetExitCodeThread(th, ctypes.byref(code))
k32.VirtualFreeEx(h, ctypes.c_void_p(mem), 0, MEM_RELEASE)
k32.CloseHandle(th)
k32.CloseHandle(h)

KEYS = """
  F9          console on/off          Shift+F9  block game input while typing
  F7          text overlay on/off     F10       dump scrollback, refresh Tab list
  F8          noclip / free-fly       F11       run avatar_cmds.txt
  F12         self-test               End       unload the DLL
  Pause       RESCUE - force noclip off, close the console, give the mouse back.
              Works even if the game has stopped rendering.
  Tab         complete a command      Up/Down   command history
  PgUp/PgDn   console closed: fly speed    console open: scroll back

  flying:     W A S D along the camera, Space up, Left Ctrl down,
              Shift 4x, Alt quarter
"""

COMMANDS = """
  modhelp             list everything the DLL adds (also shown by '?')
  ?                   engine commands + ours
  spawn <archetype>   create an entity in front of you
  spawn_list <text>   search archetype names
  tp <x> <y> <z>      move the player there (Z is up)
  fixinput            reload the input bindings, if you have lost control
  warp <world> yes    load a world directly - EXPERIMENTAL, can crash
"""

if code.value:
    print("\nINJECTED - module handle 0x%08X" % code.value)
    print("  log:  %s" % os.path.join(here, "avatar_console_dll.log"))
    print(KEYS)
    print("  Console commands:")
    print(COMMANDS)
    # NOTHING IS CHECKED FOR HERE ANY MORE, and that is the point.
    # This used to warn about console_cmds.txt ("Tab completion will be almost
    # empty") and spawn_names.txt ("spawn_list will find nothing"). Both warnings
    # are now false. The full 722-name completion list is compiled into the DLL,
    # and spawn_list reads the LIVE archetype table rather than a file - the
    # file-based version could only offer names from the full library, most of
    # which do not exist on any given map. The DLL has no required data file.
    print("  spawn: the spawnable set is PER LEVEL. Most names in spawn_names.txt")
    print("         come from the full library and will not exist on a given map;")
    print("         a name that is absent prints an error, it does not crash.")
else:
    print("\nLoadLibraryA returned 0 - the DLL failed to load "
          "(wrong architecture? check it is 32-bit).")
