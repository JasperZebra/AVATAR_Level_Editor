"""
launch_game.py — start the game from the editor.

One menu item, one job: run the game's executable.  The user picks the .exe the
first time, it is remembered per game, and every launch after that is a single
click — the whole point being to shorten edit → repack → play.

Deliberately NOT in :mod:`pak_ui`.  Launching has nothing to do with archives;
the only thing the two share is living on the File menu next to each other.

Design notes
------------
*Working directory.*  The game is started with its own folder as the cwd, not
the editor's.  Dunia games resolve their data relative to the working directory,
and the ``dinput8.dll`` console mod is loaded by the OS from the exe's folder —
launching from the wrong cwd gives you a game that starts and then can't find
itself.

*No wait, no handle kept.*  The editor stays usable and the game outlives it.
Nothing stops you launching twice either, which is deliberate: two instances is
how the multiplayer work gets tested.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Optional

from PyQt5.QtWidgets import QFileDialog, QMessageBox, QWidget

try:                                                  # keep the import cheap
    from set_patch_folder import PATCH_CONFIG_FILE
except Exception:                                     # noqa: BLE001
    PATCH_CONFIG_FILE = "patch_config.json"

EXE_FILTER = "Game executable (*.exe);;All files (*)"

# Only used to aim the file dialog at the right folder on the first run.  A
# wrong guess costs the user one extra click, so these are hints, not a
# whitelist -- whatever they pick is what gets launched.
_EXE_HINT = {'avatar': 'Avatar.exe', 'farcry2': 'FarCry2.exe'}


def _game_mode(main_window) -> str:
    return getattr(main_window, 'game_mode', 'avatar')


def _as_parent(obj):
    """A QWidget suitable as a dialog parent, or None (Qt raises on non-widgets)."""
    return obj if isinstance(obj, QWidget) else None


def _config_key(main_window) -> str:
    return f"{_game_mode(main_window)}_game_exe"


def _read_config() -> dict:
    try:
        if os.path.exists(PATCH_CONFIG_FILE):
            with open(PATCH_CONFIG_FILE, 'r') as f:
                return json.load(f)
    except Exception as exc:                          # noqa: BLE001
        print(f"Could not read {PATCH_CONFIG_FILE}: {exc}")
    return {}


def saved_exe(main_window) -> Optional[str]:
    """The remembered executable for this game, or None if it isn't usable.

    A path that no longer exists is treated as unset rather than as an error:
    games get moved and reinstalled, and re-asking is the whole recovery.
    """
    path = _read_config().get(_config_key(main_window))
    return path if path and os.path.isfile(path) else None


def _remember_exe(main_window, path: str) -> None:
    """Merge the choice into patch_config.json, preserving every other key."""
    try:
        cfg = _read_config()
        cfg[_config_key(main_window)] = os.path.abspath(path)
        with open(PATCH_CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=2)
    except Exception as exc:                          # noqa: BLE001 — non-fatal
        print(f"Could not remember the game executable: {exc}")


def _guess_start_dir(main_window) -> str:
    """Where to open the file dialog.

    The patch folder is usually a few levels under the game root, so walk up
    looking for a ``bin`` holding the expected exe.  Finding it means the user
    lands in the right folder with the file already in front of them.
    """
    hint = _EXE_HINT.get(_game_mode(main_window), '')
    seeds = [getattr(main_window, 'patch_folder', None),
             getattr(main_window, 'resource_folder', None)]
    manager = getattr(main_window, 'patch_manager', None)
    if manager is not None:
        seeds.append(getattr(manager, 'patch_folder', None))

    for seed in seeds:
        if not seed or not os.path.isdir(seed):
            continue
        cur = os.path.abspath(seed)
        for _ in range(5):                            # game root is never far up
            candidate = os.path.join(cur, 'bin')
            if hint and os.path.isfile(os.path.join(candidate, hint)):
                return candidate
            parent = os.path.dirname(cur)
            if parent == cur:                         # hit the drive root
                break
            cur = parent
        return os.path.abspath(seed)                  # no bin/ found, start here

    return os.path.expanduser('~')


def choose_game_exe(main_window, prompt: Optional[str] = None) -> Optional[str]:
    """Ask for the game executable and remember it.  None means cancelled."""
    parent = _as_parent(main_window)
    start = _guess_start_dir(main_window)
    hint = _EXE_HINT.get(_game_mode(main_window), '')
    if hint and os.path.isdir(start):
        start = os.path.join(start, hint)             # pre-fills the name box

    chosen, _ = QFileDialog.getOpenFileName(
        parent, prompt or "Select the game executable", start, EXE_FILTER)
    if not chosen:
        return None

    if os.name == 'nt' and not chosen.lower().endswith('.exe'):
        QMessageBox.warning(
            parent, "Not an Executable",
            f"This is not a program the editor can start:\n{chosen}\n\n"
            "Pick the game's .exe — for Avatar that is bin\\Avatar.exe.")
        return None

    _remember_exe(main_window, chosen)
    return os.path.abspath(chosen)


def launch_game(main_window) -> bool:
    """File action: run the game.  Asks for the .exe once, then never again."""
    parent = _as_parent(main_window)

    exe = saved_exe(main_window)
    if exe is None:
        exe = choose_game_exe(main_window)
        if exe is None:
            return False

    return _run(main_window, parent, exe)


def _run(main_window, parent, exe: str) -> bool:
    """Start ``exe`` detached, from its own folder."""
    workdir = os.path.dirname(exe) or None

    flags = 0
    if os.name == 'nt':
        # No inherited console, and Ctrl+C in the editor's terminal must not
        # reach the game.
        flags = (getattr(subprocess, 'DETACHED_PROCESS', 0) |
                 getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))

    try:
        subprocess.Popen([exe], cwd=workdir, creationflags=flags, close_fds=True)
    except OSError as exc:                            # noqa: BLE001
        if getattr(exc, 'winerror', None) == 740:     # ERROR_ELEVATION_REQUIRED
            QMessageBox.critical(
                parent, "Needs Administrator",
                f"{os.path.basename(exe)} requires administrator rights, so the "
                "editor cannot start it.\n\nRun the editor as administrator, or "
                "start the game yourself.")
            return False
        # Anything else is most likely the wrong file, so offer the picker
        # again rather than leaving a bad path saved forever.
        answer = QMessageBox.question(
            parent, "Could Not Launch",
            f"Could not start:\n{exe}\n\n{exc}\n\nPick a different executable?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            return False
        other = choose_game_exe(main_window, "Select the game executable")
        return _run(main_window, parent, other) if other else False

    # No success dialog on purpose -- a popup to dismiss would undo the point of
    # the button.  The status bar says it happened and gets out of the way.
    bar = getattr(main_window, 'status_bar', None)
    if bar is not None:
        bar.showMessage(f"Launched {os.path.basename(exe)}", 5000)
    print(f"Launched {exe} (cwd {workdir})")
    return True
