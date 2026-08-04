"""Where is Avatar.exe stuck? Sample its threads from OUTSIDE, read-only.

WHY THIS EXISTS. An infinite loading screen gives you nothing: the game has not
crashed, so the DLL's crash reporter never fires, and it is still pumping
messages, so the watchdog may not either. Guessing at the cause from the data
on disk is how you end up generating 1,800 files to fix something else.

This does what the in-process crash reporter does, from another process and
without a rebuild: for every thread of Avatar.exe it takes the register context
and scans the stack for return addresses inside Dunia.dll, then resolves them
against ENGINE_MAP so you get function names rather than hex.

READ-ONLY AND NON-INVASIVE by construction. It needs SUSPEND to read a
register context - that is what GetThreadContext requires of a running thread -
and every thread is resumed in a `finally`, so an exception cannot leave the
game frozen. It writes nothing, allocates nothing in the target, and installs
no hooks.

    python stackprobe.py            sample once
    python stackprobe.py 5          five samples, 1 s apart

Reading the SAME function across samples is what tells you it is stuck rather
than merely busy.
"""
import bisect
import ctypes
import ctypes.wintypes as w
import os
import sqlite3
import sys
import time

ENGINE_DB = r"C:\Test\Tools\Decompiled DLL's\Avatar\PC\ENGINE_MAP\dunia.db"
PREFERRED_BASE = 0x10000000

TH32CS_SNAPTHREAD = 0x00000004
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
THREAD_GET_CONTEXT = 0x0008
THREAD_SUSPEND_RESUME = 0x0002
THREAD_QUERY_INFORMATION = 0x0040
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
CONTEXT_CONTROL_32 = 0x00010001
CONTEXT_INTEGER_32 = 0x00010002

k = ctypes.windll.kernel32


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD),
                ("th32ThreadID", w.DWORD), ("th32OwnerProcessID", w.DWORD),
                ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long),
                ("dwFlags", w.DWORD)]


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("th32ModuleID", w.DWORD),
                ("th32ProcessID", w.DWORD), ("GlblcntUsage", w.DWORD),
                ("ProccntUsage", w.DWORD), ("modBaseAddr", ctypes.c_void_p),
                ("modBaseSize", w.DWORD), ("hModule", w.HMODULE),
                ("szModule", ctypes.c_char * 256),
                ("szExePath", ctypes.c_char * 260)]


class WOW64_FLOATING_SAVE_AREA(ctypes.Structure):
    _fields_ = [("ControlWord", w.DWORD), ("StatusWord", w.DWORD),
                ("TagWord", w.DWORD), ("ErrorOffset", w.DWORD),
                ("ErrorSelector", w.DWORD), ("DataOffset", w.DWORD),
                ("DataSelector", w.DWORD), ("RegisterArea", ctypes.c_byte * 80),
                ("Cr0NpxState", w.DWORD)]


class WOW64_CONTEXT(ctypes.Structure):
    _fields_ = [("ContextFlags", w.DWORD), ("Dr0", w.DWORD), ("Dr1", w.DWORD),
                ("Dr2", w.DWORD), ("Dr3", w.DWORD), ("Dr6", w.DWORD),
                ("Dr7", w.DWORD), ("FloatSave", WOW64_FLOATING_SAVE_AREA),
                ("SegGs", w.DWORD), ("SegFs", w.DWORD), ("SegEs", w.DWORD),
                ("SegDs", w.DWORD), ("Edi", w.DWORD), ("Esi", w.DWORD),
                ("Ebx", w.DWORD), ("Edx", w.DWORD), ("Ecx", w.DWORD),
                ("Eax", w.DWORD), ("Ebp", w.DWORD), ("Eip", w.DWORD),
                ("SegCs", w.DWORD), ("EFlags", w.DWORD), ("Esp", w.DWORD),
                ("SegSs", w.DWORD), ("ExtendedRegisters", ctypes.c_byte * 512)]


def find_pid(name="Avatar.exe"):
    import subprocess
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + name, "/FO",
                          "CSV", "/NH"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].lower() == name.lower():
            return int(parts[1])
    return None


def dunia_range(pid):
    snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32,
                                      pid)
    if snap == -1:
        return None, 0
    me = MODULEENTRY32()
    me.dwSize = ctypes.sizeof(me)
    base, size = None, 0
    if k.Module32First(snap, ctypes.byref(me)):
        while True:
            if me.szModule.decode("latin1").lower() == "dunia.dll":
                base, size = int(me.modBaseAddr or 0), int(me.modBaseSize)
                break
            if not k.Module32Next(snap, ctypes.byref(me)):
                break
    k.CloseHandle(snap)
    return base, size


def threads_of(pid):
    snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    te = THREADENTRY32()
    te.dwSize = ctypes.sizeof(te)
    out = []
    if k.Thread32First(snap, ctypes.byref(te)):
        while True:
            if te.th32OwnerProcessID == pid:
                out.append(te.th32ThreadID)
            if not k.Thread32Next(snap, ctypes.byref(te)):
                break
    k.CloseHandle(snap)
    return out


class Symbols(object):
    def __init__(self, db):
        self.addrs, self.names = [], {}
        if not os.path.exists(db):
            print("  (no ENGINE_MAP at %s - addresses only)" % db)
            return
        c = sqlite3.connect(db)
        for (a,) in c.execute("select addr from func"):
            try:
                self.addrs.append(int(a, 16))
            except Exception:
                pass
        self.addrs.sort()
        for a, n in c.execute("select addr,name from name"):
            try:
                self.names[int(a, 16)] = n
            except Exception:
                pass

    def at(self, decompile_addr):
        if not self.addrs:
            return None, 0
        i = bisect.bisect_right(self.addrs, decompile_addr) - 1
        if i < 0:
            return None, 0
        f = self.addrs[i]
        return (self.names.get(f) or "FUN_%08x" % f), decompile_addr - f


class FILETIME(ctypes.Structure):
    _fields_ = [("lo", w.DWORD), ("hi", w.DWORD)]


def thread_cpu(th):
    """Kernel+user time for a thread, in seconds. -> float, or None.

    WHICH THREAD MATTERS. A hung game has 20+ threads and most are parked; the
    one that is spinning is the one to read. Sorting by CPU burned says which
    that is instead of guessing from the listing order.
    """
    c, e, kt, ut = FILETIME(), FILETIME(), FILETIME(), FILETIME()
    if not k.GetThreadTimes(th, ctypes.byref(c), ctypes.byref(e),
                            ctypes.byref(kt), ctypes.byref(ut)):
        return None
    tot = ((kt.hi << 32 | kt.lo) + (ut.hi << 32 | ut.lo))
    return tot / 1e7


def busiest(pid, seconds=1.0, top=3):
    """-> [(tid, cpu_seconds_burned_in_the_window), ...], hottest first."""
    first = {}
    for tid in threads_of(pid):
        th = k.OpenThread(THREAD_QUERY_INFORMATION, False, tid)
        if th:
            first[tid] = thread_cpu(th)
            k.CloseHandle(th)
    time.sleep(seconds)
    out = []
    for tid, t0 in first.items():
        if t0 is None:
            continue
        th = k.OpenThread(THREAD_QUERY_INFORMATION, False, tid)
        if not th:
            continue
        t1 = thread_cpu(th)
        k.CloseHandle(th)
        if t1 is not None:
            out.append((tid, t1 - t0))
    out.sort(key=lambda x: -x[1])
    return out[:top]


def sample(pid, base, size, syms, depth=768, only=None):
    ph = k.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not ph:
        print("OpenProcess failed (%d)" % k.GetLastError())
        return
    rebase = (base or PREFERRED_BASE) - PREFERRED_BASE
    lo, hi = base, base + size
    buf = (ctypes.c_uint32 * depth)()
    got = ctypes.c_size_t(0)
    for tid in threads_of(pid):
        if only and tid not in only:
            continue
        th = k.OpenThread(THREAD_GET_CONTEXT | THREAD_SUSPEND_RESUME
                          | THREAD_QUERY_INFORMATION, False, tid)
        if not th:
            continue
        frames = []
        try:
            if k.Wow64SuspendThread(th) == 0xFFFFFFFF:
                continue
            try:
                ctx = WOW64_CONTEXT()
                ctx.ContextFlags = CONTEXT_CONTROL_32 | CONTEXT_INTEGER_32
                if not k.Wow64GetThreadContext(th, ctypes.byref(ctx)):
                    continue
                eip, esp = ctx.Eip, ctx.Esp
                k.ReadProcessMemory(ph, ctypes.c_void_p(esp), buf,
                                    ctypes.sizeof(buf), ctypes.byref(got))
                n = got.value // 4
                cand = []
                if lo <= eip < hi:
                    cand.append(eip)
                for i in range(n):
                    v = buf[i]
                    if lo <= v < hi:
                        cand.append(v)
                        if len(cand) >= 10:
                            break
                frames = cand
            finally:
                k.ResumeThread(th)          # ALWAYS, even on an exception
        finally:
            k.CloseHandle(th)
        if not frames:
            continue
        print("  thread %-6d" % tid)
        seen = set()
        for a in frames[:8]:
            d = a - rebase
            nm, off = syms.at(d)
            key = (nm, off // 64)
            if key in seen:
                continue
            seen.add(key)
            print("      %08X  %s+0x%X" % (d, nm or "?", off))
    k.CloseHandle(ph)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    pid = find_pid()
    if not pid:
        print("Avatar.exe is not running")
        return 1
    base, size = dunia_range(pid)
    print("Avatar.exe pid %d   Dunia.dll %08X + %08X%s\n"
          % (pid, base or 0, size,
             "" if base == PREFERRED_BASE else "  (relocated - rebased below)"))
    syms = Symbols(ENGINE_DB)
    hot = busiest(pid)
    print("busiest threads over 1 s:")
    for tid, secs in hot:
        print("   thread %-7d %.3f s CPU" % (tid, secs))
    only = set(t for t, s in hot if s > 0.02) or None
    print("   -> sampling %s\n"
          % ("the hot one(s)" if only else "every thread (none are busy)"))
    for i in range(n):
        if n > 1:
            print("---- sample %d/%d" % (i + 1, n))
        sample(pid, base, size, syms, only=only)
        if i + 1 < n:
            time.sleep(1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
