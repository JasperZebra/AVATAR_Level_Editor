"""gamepath.py - find the game, get the mod into it, remember where it is.

No Qt. The GUI asks this module questions and shows the answers.

WHY THIS EXISTS, and what it does NOT do
----------------------------------------
The link pipe is a fixed kernel object name, \\\\.\\pipe\\avatar_editor. Connecting
to it needs no path, no port and no install location - so knowing where the game
lives does nothing whatsoever for `connect`.

What the path IS needed for is the step before: getting avatar_console.dll into
the process at all. The pipe only exists because the DLL is loaded and serving
it. So a failed connect nearly always means "the mod is not in the game", and
the fix is an install or an injection, both of which need the install folder.

install.bat hardcodes D:\\Games\\Avatar The Game and takes an override argument.
That is fine for its author and wrong for everybody else, which is exactly the
case this module handles: ask once, remember, and never guess.

DELIBERATELY NO AUTO-DETECTION. No registry sweep, no scanning every drive for
Avatar.exe. Retail, Uplay, GOG and a copied folder all look different, a scan is
slow and can hit network drives, and a wrong guess here writes a DLL into a
folder the user did not choose. Asking is one dialog, once.

THE TWO LOAD PATHS ARE MUTUALLY EXCLUSIVE. dinput8.dll in bin\\ and an injected
avatar_console.dll are the same binary under two names; both loaded at once
means two sets of hooks on one vtable slot, which the project's own docs call
"not survivable". inject.py refuses when it sees the proxy, and so does this.
"""

import ctypes
import ctypes.wintypes as wt
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "rte_config.json")
DIST = os.path.normpath(os.path.join(HERE, "..", "console_dll", "console_dll",
                                     "dist"))
PROXY_NAME = "dinput8.dll"
INJECT_NAME = "avatar_console.dll"

CREATE_NO_WINDOW = 0x08000000
TH32CS_SNAPPROCESS = 0x2


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_char * 260)]


def game_is_running(exe_name="avatar.exe"):
    """Toolhelp rather than `tasklist`: no subprocess, no console flash, and it
    is the same mechanism inject.py uses to find the pid."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == wt.HANDLE(-1).value:
        return False
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(entry)
    found = False
    try:
        if k32.Process32First(snap, ctypes.byref(entry)):
            while True:
                name = entry.szExeFile.decode("mbcs", "ignore").lower()
                if name == exe_name:
                    found = True
                    break
                if not k32.Process32Next(snap, ctypes.byref(entry)):
                    break
    finally:
        k32.CloseHandle(snap)
    return found


class GameInstall(object):
    """The user's Avatar install, remembered between runs."""

    def __init__(self):
        self.exe = self._load()

    # -- config ------------------------------------------------------------

    def _load(self):
        try:
            with io.open(CONFIG, encoding="utf-8") as f:
                path = json.load(f).get("avatar_exe") or ""
        except (IOError, ValueError):
            return ""
        return path if self.validate(path)[0] else ""

    def save(self):
        try:
            with io.open(CONFIG, "w", encoding="utf-8") as f:
                f.write(json.dumps({"avatar_exe": self.exe}, indent=2))
            return True
        except IOError:
            return False

    # -- validation --------------------------------------------------------

    @staticmethod
    def validate(exe):
        """-> (ok, message). Accepts the exe itself or the folder holding it.

        Checked rather than assumed, because everything downstream writes into
        the folder this returns.
        """
        if not exe:
            return False, "no path set"
        exe = os.path.normpath(exe)
        if os.path.isdir(exe):
            for cand in (os.path.join(exe, "Avatar.exe"),
                         os.path.join(exe, "bin", "Avatar.exe")):
                if os.path.isfile(cand):
                    exe = cand
                    break
            else:
                return False, "no Avatar.exe in that folder (or its bin\\)"
        if not os.path.isfile(exe):
            return False, "that file does not exist"
        if os.path.basename(exe).lower() != "avatar.exe":
            return False, "that is not Avatar.exe"
        return True, exe

    def set_path(self, exe):
        ok, result = self.validate(exe)
        if not ok:
            return False, result
        self.exe = result
        self.save()
        return True, result

    # -- derived locations -------------------------------------------------

    @property
    def bin_dir(self):
        return os.path.dirname(self.exe) if self.exe else ""

    @property
    def proxy_path(self):
        return os.path.join(self.bin_dir, PROXY_NAME) if self.exe else ""

    @property
    def log_path(self):
        return (os.path.join(self.bin_dir, "avatar_console_dll.log")
                if self.exe else "")

    @staticmethod
    def built_proxy():
        return os.path.join(DIST, PROXY_NAME)

    @staticmethod
    def built_injectable():
        return os.path.join(DIST, INJECT_NAME)

    @staticmethod
    def injector():
        return os.path.join(DIST, "inject.py")

    # -- status ------------------------------------------------------------

    def status(self):
        """Everything the Setup card shows, in one read."""
        ok, _ = self.validate(self.exe)
        return {
            "configured": ok,
            "exe": self.exe,
            "bin": self.bin_dir,
            "log_path": self.log_path,
            "installed": bool(self.exe) and os.path.isfile(self.proxy_path),
            "running": game_is_running(),
            "have_build": os.path.isfile(self.built_proxy()),
            "dist": DIST,
        }

    # -- actions -----------------------------------------------------------

    def install(self):
        """Copy dist\\dinput8.dll into bin\\. -> (ok, message)

        Refuses while the game is up. The copy would fail with a sharing
        violation anyway, but Windows reports that as something that reads like
        a permissions problem, which sends people looking in the wrong place -
        install.bat makes the same call for the same reason.
        """
        ok, msg = self.validate(self.exe)
        if not ok:
            return False, msg
        src = self.built_proxy()
        if not os.path.isfile(src):
            return False, ("dinput8.dll is not built. Run build.bat in\n%s"
                           % os.path.dirname(DIST))
        if game_is_running():
            return False, ("Avatar.exe is running. Close the game first - a "
                           "loaded DLL cannot be overwritten.")
        try:
            with open(src, "rb") as f:
                data = f.read()
            with open(self.proxy_path, "wb") as f:
                f.write(data)
        except IOError as exc:
            return False, "could not write %s\n%s" % (self.proxy_path, exc)
        return True, ("Installed:\n%s\n\nStart the game normally. The mod arms "
                      "itself once a level loads - not at the main menu, "
                      "because the engine does not build the console object "
                      "until then." % self.proxy_path)

    def uninstall(self):
        ok, msg = self.validate(self.exe)
        if not ok:
            return False, msg
        if not os.path.isfile(self.proxy_path):
            return True, "nothing installed"
        if game_is_running():
            return False, "Avatar.exe is running. Close the game first."
        try:
            os.remove(self.proxy_path)
        except OSError as exc:
            return False, "could not delete %s\n%s" % (self.proxy_path, exc)
        return True, "Removed %s\nThat is the whole uninstall - nothing else " \
                     "was ever written." % self.proxy_path

    def inject(self):
        """Run dist\\inject.py against the live game. -> (ok, output)

        Shelling out to the existing script rather than reimplementing it: it is
        the tested path, it already parses the target's own 32-bit kernel32
        export table (this Python is very likely 64-bit), and it already refuses
        when the drop-in proxy is loaded. Two implementations of that logic would
        be two things to keep right.
        """
        if not game_is_running():
            return False, "Avatar.exe is not running - launch it and load a save."
        script = self.injector()
        if not os.path.isfile(script):
            return False, "inject.py not found at %s" % script
        if not os.path.isfile(self.built_injectable()):
            return False, ("avatar_console.dll is not built. Run build.bat in\n%s"
                           % os.path.dirname(DIST))
        try:
            proc = subprocess.Popen(
                [sys.executable, script], cwd=DIST,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW)
            out, _ = proc.communicate(timeout=60)
        except Exception as exc:
            return False, "could not run inject.py: %s" % exc
        text = out.decode("utf-8", "replace").strip()
        ok = "INJECTED" in text or "already injected" in text
        if not ok and "OpenProcess failed" in text:
            text += "\n\nTry starting this tool as Administrator."
        return ok, text


def _selftest():
    g = GameInstall()
    st = g.status()
    print("config file : %s" % CONFIG)
    print("dist folder : %s" % st["dist"])
    print("built proxy : %s" % ("present" if st["have_build"] else "MISSING"))
    print("configured  : %s" % (st["exe"] or "no - the tool will ask"))
    if st["configured"]:
        print("bin         : %s" % st["bin"])
        print("mod dropped : %s" % ("yes" if st["installed"] else "no"))
    print("game running: %s" % ("yes" if st["running"] else "no"))
    return 0


if __name__ == "__main__":
    sys.exit(_selftest())
