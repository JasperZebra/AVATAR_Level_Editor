"""
pak_ui.py — Qt front-end for :mod:`pak_archive`.

Two user-facing flows:

* **Load a .pak as the patch folder** — pick an archive, unpack it to a folder,
  then hand that folder to the ordinary patch-folder machinery.  Nothing
  downstream knows or cares that it came from an archive.
* **Repack the patch folder back to a .pak** — either the whole folder, or only
  the files that differ from what was extracted (a small, layerable mod pak).

Threading note
--------------
Both flows run the blocking work on a ``QThread`` and pump
:class:`EnhancedProgressDialog` from a **top-level** busy-wait — the same
pattern as the patch-folder scanner and the entitylibrary conversion.  Worker
threads never touch widgets; they append to a lock-guarded message list that
the main thread drains.  Do NOT move ``QApplication.processEvents()`` into a
signal handler here: nesting it inside a handler that was itself invoked by
``processEvents`` is the documented stack-overflow footgun.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, List, Optional, Tuple

from PyQt5.QtCore import QThread, Qt
from PyQt5.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QDialog, QDialogButtonBox,
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QRadioButton, QVBoxLayout, QWidget,
)

import pak_archive as pak

PAK_FILTER = "PAK archives (*.pak);;All files (*)"


# --------------------------------------------------------------------------
# Worker plumbing
# --------------------------------------------------------------------------

class _Job(QThread):
    """Runs ``fn(job)`` off the GUI thread, buffering log/progress for the UI."""

    def __init__(self, fn: Callable[["_Job"], object]):
        super().__init__()
        self._fn = fn
        self.result = None
        self.error: Optional[BaseException] = None
        self.finished_flag = False
        self.cancelled = False
        self.progress: Tuple[int, int] = (0, 0)
        self._messages: List[str] = []
        self._lock = threading.Lock()

    # -- called FROM the worker thread -------------------------------------
    def log(self, message: str) -> None:
        with self._lock:
            self._messages.append(str(message))

    def report(self, done: int, total: int) -> None:
        self.progress = (done, total)

    def is_cancelled(self) -> bool:
        return self.cancelled

    # -- called FROM the GUI thread ----------------------------------------
    def drain(self) -> List[str]:
        with self._lock:
            out = self._messages[:]
            self._messages.clear()
        return out

    def run(self):                                   # noqa: D102
        try:
            self.result = self._fn(self)
        except BaseException as exc:                 # noqa: BLE001 — surfaced to the UI
            self.error = exc
        finally:
            self.finished_flag = True


def _run_job(parent, title: str, fn: Callable[[_Job], object],
             game_mode: str = "avatar") -> Tuple[object, Optional[BaseException], bool]:
    """Run ``fn`` behind a progress dialog.  Returns ``(result, error, cancelled)``."""
    from simplified_map_editor import EnhancedProgressDialog

    dialog = EnhancedProgressDialog(title, _as_parent(parent), game_mode=game_mode)
    job = _Job(fn)
    dialog.cancelled.connect(lambda: setattr(job, 'cancelled', True))
    dialog.set_status(title)
    dialog.show()
    QApplication.processEvents()

    job.start()
    last_pct = -1
    while not job.finished_flag:
        for msg in job.drain():
            dialog.append_log(msg)
        done, total = job.progress
        if total:
            pct = int(done * 100 / total)
            if pct != last_pct:
                dialog.set_progress(pct)
                dialog.set_status(f"{title}  —  {done:,} / {total:,}")
                last_pct = pct
        QApplication.processEvents()
        time.sleep(0.03)

    job.wait()
    for msg in job.drain():
        dialog.append_log(msg)
    dialog.set_progress(100)
    dialog.mark_complete()
    dialog.stop_icon()
    dialog.close()
    return job.result, job.error, job.cancelled


def _game_mode(main_window) -> str:
    return getattr(main_window, 'game_mode', 'avatar')


def _as_parent(obj):
    """A QWidget suitable as a dialog parent, or None.

    Callers always pass the main window in practice, but Qt raises TypeError
    rather than ignoring a non-widget, so normalise instead of trusting it.
    """
    return obj if isinstance(obj, QWidget) else None


def _reject_fc2(parent, main_window) -> bool:
    """Guard: PAK is an Avatar container.  True means "stop, already warned".

    The menu items and buttons are disabled in FC2 mode; this is the belt-and-
    braces check so a stray programmatic call can't point an FC2 patch folder
    at Avatar data.
    """
    if _game_mode(main_window) != 'farcry2':
        return False
    QMessageBox.information(
        _as_parent(parent), "Not Supported for Far Cry 2",
        "PAK archives are an Avatar container.\n\n"
        "Far Cry 2 ships its data as .fat/.dat (Dunia FAT) archives, which the "
        "editor cannot read or write yet. Use an unpacked folder for FC2.")
    return True


# --------------------------------------------------------------------------
# Load a .pak as the patch folder
# --------------------------------------------------------------------------

def _choose_destination(parent, pak_path: str) -> Optional[str]:
    """Confirm (or redirect) the folder a .pak unpacks into."""
    default = pak.default_extract_dir(pak_path)
    box = QMessageBox(parent)
    box.setWindowTitle("Unpack Location")
    box.setIcon(QMessageBox.Question)
    box.setText("Where should this archive be unpacked?")
    box.setInformativeText(
        f"Archive:\n{pak_path}\n\nProposed folder:\n{default}\n\n"
        "The editor will use that folder as the patch folder.")
    here = box.addButton("Unpack Here", QMessageBox.AcceptRole)
    other = box.addButton("Choose Folder...", QMessageBox.ActionRole)
    box.addButton("Cancel", QMessageBox.RejectRole)
    box.exec()

    clicked = box.clickedButton()
    if clicked is here:
        return default
    if clicked is other:
        start = os.path.dirname(pak_path)
        chosen = QFileDialog.getExistingDirectory(parent, "Select Unpack Folder", start)
        return chosen or None
    return None


def _confirm_existing_folder(parent, dest: str,
                             pak_path: Optional[str] = None) -> Optional[str]:
    """Decide what to do about an existing destination.

    Returns ``'reuse'``, ``'extract'`` or None (cancel).  Never silently
    overwrites: a folder holding local edits is the one thing this feature
    could destroy irrecoverably.
    """
    if not os.path.isdir(dest) or not os.listdir(dest):
        return 'extract'

    changes = pak.describe_local_changes(dest)

    box = QMessageBox(parent)
    box.setWindowTitle("Folder Already Exists")
    box.setIcon(QMessageBox.Warning)

    # Default destinations can't collide (one folder per .pak name), but
    # "Choose Folder..." lets a second archive be aimed at an existing
    # extraction.  Say so plainly rather than quietly overwriting it.
    manifest = pak.read_manifest(dest)
    other = manifest.get('source_pak') if manifest else None
    if (other and pak_path
            and os.path.normcase(os.path.abspath(other))
            != os.path.normcase(os.path.abspath(pak_path))):
        edits = ''
        if changes and changes.total:
            edits = (f"\n\nIt also holds {changes.total:,} locally changed "
                     "file(s), which would be lost.")
        box.setText("This folder holds a different archive.")
        box.setInformativeText(
            f"{dest}\n\nIt was unpacked from:\n{other}\n\n"
            f"You are opening:\n{pak_path}{edits}\n\n"
            "Unpack here to replace it, or choose another folder.")
        reuse = box.addButton("Use Folder As-Is", QMessageBox.AcceptRole)
        again = box.addButton("Replace It", QMessageBox.DestructiveRole)
        box.setDefaultButton(reuse)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is reuse:
            return 'reuse'
        if clicked is again:
            return 'extract'
        return None

    if changes is None:
        box.setText("That folder already contains files.")
        box.setInformativeText(
            f"{dest}\n\nIt was not unpacked by this editor, so its contents "
            "cannot be checked against the archive.\n\n"
            "Unpacking will overwrite any file the archive also contains.")
        reuse = box.addButton("Use Folder As-Is", QMessageBox.AcceptRole)
        again = box.addButton("Unpack Anyway", QMessageBox.DestructiveRole)
    elif changes.total == 0:
        box.setIcon(QMessageBox.Question)
        box.setText("This archive is already unpacked here.")
        box.setInformativeText(
            f"{dest}\n\nNo local edits were found, so unpacking again would "
            "produce the same files.")
        reuse = box.addButton("Use Existing Files", QMessageBox.AcceptRole)
        again = box.addButton("Unpack Again", QMessageBox.ActionRole)
    else:
        bits = []
        if changes.modified:
            bits.append(f"{len(changes.modified):,} modified")
        if changes.added:
            bits.append(f"{len(changes.added):,} added")
        if changes.missing:
            bits.append(f"{len(changes.missing):,} deleted")
        box.setText("This folder contains local edits.")
        box.setInformativeText(
            f"{dest}\n\nFound {', '.join(bits)} file(s) since it was unpacked.\n\n"
            "Unpacking again will overwrite your edits.")
        reuse = box.addButton("Keep My Edits", QMessageBox.AcceptRole)
        again = box.addButton("Discard and Unpack", QMessageBox.DestructiveRole)
        box.setDefaultButton(reuse)

    box.addButton("Cancel", QMessageBox.RejectRole)
    box.exec()

    clicked = box.clickedButton()
    if clicked is reuse:
        return 'reuse'
    if clicked is again:
        return 'extract'
    return None


def load_patch_folder_from_pak(main_window, pak_path: Optional[str] = None) -> Optional[str]:
    """Pick a ``.pak``, unpack it, and return the folder to use as patch folder.

    Returns None when the user cancels or the archive can't be read.
    """
    parent = _as_parent(main_window)
    if _reject_fc2(parent, main_window):
        return None
    if not pak_path:
        start = ''
        for attr in ('patch_folder', 'resource_folder'):
            v = getattr(main_window, attr, None)
            if v:
                start = os.path.dirname(v)
                break
        pak_path, _ = QFileDialog.getOpenFileName(
            parent, "Select a PAK Archive (e.g. patch.pak)", start, PAK_FILTER)
        if not pak_path:
            return None

    if not pak.is_pak_file(pak_path):
        QMessageBox.critical(parent, "Not a PAK Archive",
                             f"This file is not a PAK archive:\n{pak_path}")
        return None

    try:
        index = pak.read_index(pak_path)
    except pak.PakError as exc:
        QMessageBox.critical(parent, "Unreadable Archive",
                             f"Could not read the archive:\n{pak_path}\n\n{exc}")
        return None

    dest = _choose_destination(parent, pak_path)
    if not dest:
        return None

    action = _confirm_existing_folder(parent, dest, pak_path)
    if action is None:
        return None

    if action == 'extract':
        def _work(job: _Job):
            return pak.extract(pak_path, dest, log=job.log, progress=job.report,
                               cancel=job.is_cancelled)

        result, error, cancelled = _run_job(
            parent, f"Unpacking {os.path.basename(pak_path)}", _work, _game_mode(main_window))

        if error is not None:
            QMessageBox.critical(parent, "Unpack Failed",
                                 f"Could not unpack the archive:\n\n{error}")
            return None
        if cancelled:
            QMessageBox.information(
                parent, "Unpack Cancelled",
                "Unpacking was cancelled. The folder holds a partial extraction.")
            return None
        if result is not None and result.failed:
            QMessageBox.warning(
                parent, "Unpacked With Errors",
                f"{len(result.failed)} of {result.total} file(s) failed:\n\n"
                + "\n".join(result.failed[:8]))

    _remember_source_pak(main_window, dest, pak_path)

    QMessageBox.information(
        parent, "Patch Folder Ready",
        f"Using this folder as the patch folder:\n{dest}\n\n"
        f"{len(index):,} files from {os.path.basename(pak_path)}.\n\n"
        "When you are finished editing, use File ▸ Repack Patch Folder "
        "to build a .pak again.")
    return dest


def _remember_source_pak(main_window, folder: str, pak_path: str) -> None:
    """Persist which archive a patch folder came from, per game."""
    try:
        import json
        from set_patch_folder import PATCH_CONFIG_FILE
        cfg = {}
        if os.path.exists(PATCH_CONFIG_FILE):
            with open(PATCH_CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
        game = _game_mode(main_window)
        cfg[f"{game}_patch_source_pak"] = os.path.abspath(pak_path)
        cfg[f"{game}_patch_folder"] = folder
        with open(PATCH_CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=2)
    except Exception as exc:                          # noqa: BLE001 — non-fatal
        print(f"Could not record source pak: {exc}")


def source_pak_for(main_window, folder: Optional[str] = None) -> Optional[str]:
    """The archive a patch folder was unpacked from, if known.

    Prefers the folder's own manifest (authoritative — it travels with the
    folder) and falls back to the per-game config key.
    """
    if folder:
        manifest = pak.read_manifest(folder)
        if manifest and manifest.get('source_pak'):
            return manifest['source_pak']
    try:
        import json
        from set_patch_folder import PATCH_CONFIG_FILE
        if os.path.exists(PATCH_CONFIG_FILE):
            with open(PATCH_CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
            return cfg.get(f"{_game_mode(main_window)}_patch_source_pak")
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------
# Repack
# --------------------------------------------------------------------------

class RepackDialog(QDialog):
    """Choose what to pack and where to write it."""

    def __init__(self, parent, folder: str, default_target: str,
                 has_manifest: bool):
        super().__init__(parent)
        self.setWindowTitle("Repack Patch Folder")
        self.setMinimumWidth(560)
        self._folder = folder

        layout = QVBoxLayout(self)

        head = QLabel(f"<b>Folder:</b><br>{folder}")
        head.setWordWrap(True)
        head.setTextFormat(Qt.RichText)
        layout.addWidget(head)
        layout.addSpacing(6)

        self.full_radio = QRadioButton("Everything in the folder")
        self.full_radio.setToolTip(
            "Rebuild a complete archive from every file in the folder.")
        self.changed_radio = QRadioButton("Only files changed since unpacking")
        self.changed_radio.setToolTip(
            "Build a small archive holding just your edits. The game layers it "
            "over the original archives, so nothing else needs shipping.")

        group = QButtonGroup(self)
        group.addButton(self.full_radio)
        group.addButton(self.changed_radio)

        if has_manifest:
            self.changed_radio.setChecked(True)
        else:
            self.full_radio.setChecked(True)
            self.changed_radio.setEnabled(False)
            self.changed_radio.setText(
                "Only files changed since unpacking  (unavailable — "
                "this folder was not unpacked by the editor)")

        layout.addWidget(self.full_radio)
        layout.addWidget(self.changed_radio)
        layout.addSpacing(6)

        row = QHBoxLayout()
        row.addWidget(QLabel("Save as:"))
        self.target_edit = QLineEdit(default_target)
        row.addWidget(self.target_edit, 1)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        layout.addLayout(row)

        self.compress_check = QCheckBox("Compress (LZO) — uncheck to write faster, larger")
        self.compress_check.setChecked(True)
        if not pak.have_lzo_compression():
            self.compress_check.setChecked(False)
            self.compress_check.setEnabled(False)
            self.compress_check.setText(
                "Compress (LZO) — unavailable, minilzo DLL not found; "
                "chunks will be stored uncompressed")
        layout.addWidget(self.compress_check)

        note = QLabel(
            "Editor scratch files (<code>*.fcb.converted.xml</code>, "
            "<code>*.bak</code>) are never packed. An existing archive at the "
            "target is backed up to <code>.bak</code> first.")
        note.setWordWrap(True)
        note.setTextFormat(Qt.RichText)
        note.setStyleSheet("color: #999;")
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Repack")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self):
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Save PAK Archive As", self.target_edit.text(), PAK_FILTER)
        if chosen:
            self.target_edit.setText(chosen)

    def values(self):
        return (self.target_edit.text().strip(),
                self.changed_radio.isChecked(),
                self.compress_check.isChecked())


def repack_patch_folder(main_window) -> bool:
    """Tools action: rebuild a ``.pak`` from the current patch folder."""
    parent = _as_parent(main_window)
    if _reject_fc2(parent, main_window):
        return False
    folder = getattr(main_window, 'patch_folder', None)
    if not folder:
        manager = getattr(main_window, 'patch_manager', None)
        folder = getattr(manager, 'patch_folder', None) if manager else None
    if not folder or not os.path.isdir(folder):
        QMessageBox.warning(
            parent, "No Patch Folder",
            "Set a patch folder first (File ▸ Set Patch Folder, or load a "
            ".pak archive).")
        return False

    manifest = pak.read_manifest(folder)
    source = source_pak_for(main_window, folder)
    default_target = source or (folder.rstrip('\\/') + '.pak')

    dialog = RepackDialog(parent, folder, default_target, manifest is not None)
    if dialog.exec() != QDialog.Accepted:
        return False
    target, changed_only, compress = dialog.values()

    if not target:
        QMessageBox.warning(parent, "No Target", "Choose where to save the archive.")
        return False
    target_dir = os.path.dirname(os.path.abspath(target))
    if target_dir and not os.path.isdir(target_dir):
        QMessageBox.warning(parent, "Invalid Target",
                            f"This folder does not exist:\n{target_dir}")
        return False
    if os.path.abspath(target).lower().startswith(os.path.abspath(folder).lower() + os.sep):
        QMessageBox.warning(
            parent, "Invalid Target",
            "The archive cannot be written inside the folder being packed.")
        return False

    def _work(job: _Job):
        only = None
        if changed_only and manifest is not None:
            job.log("Comparing folder against the unpacked archive...")
            changes = pak.scan_changes(folder, manifest, progress=job.report)
            only = changes.changed_paths()
            job.log(f"{len(changes.modified):,} modified, {len(changes.added):,} added, "
                    f"{len(changes.missing):,} deleted")
            if not only:
                return ('nochanges', None)
            job.report(0, 0)
        return ('packed', pak.pack(folder, target, only=only, manifest=manifest,
                                   compress=compress, log=job.log,
                                   progress=job.report, cancel=job.is_cancelled))

    result, error, cancelled = _run_job(
        parent, f"Repacking to {os.path.basename(target)}", _work, _game_mode(main_window))

    if cancelled:
        QMessageBox.information(parent, "Repack Cancelled",
                                "Repacking was cancelled. The existing archive is untouched.")
        return False
    if error is not None:
        QMessageBox.critical(parent, "Repack Failed",
                             f"Could not build the archive:\n\n{error}")
        return False

    kind, res = result if result else (None, None)
    if kind == 'nochanges':
        QMessageBox.information(
            parent, "Nothing Changed",
            "No files differ from the archive that was unpacked, so there is "
            "nothing to pack.")
        return False

    QMessageBox.information(
        parent, "Repack Complete",
        f"Wrote {os.path.basename(res.path)}\n\n"
        f"{res.file_count:,} file(s), {res.bytes_written / 1e6:.1f} MB\n"
        + (f"{res.skipped_artifacts:,} editor scratch file(s) excluded\n"
           if res.skipped_artifacts else "")
        + f"\n{res.path}")
    return True
