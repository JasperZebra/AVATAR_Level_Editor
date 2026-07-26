"""
sequence_import_dialog.py — step-by-step import/export UI for cinematic sequences.

Mirrors entity_export_import.py's dialogs on purpose: same folder-based
collections, same list-then-configure shape, same place on disk. A sequence
bundle IS an entity collection with two extra files, so the two systems sit
side by side rather than competing.

The import wizard walks four steps:

    1. Pick a bundle          which sequence, what it drives, how long
    2. Choose the mode        cutscene (takes the camera) or scripted event
                              (no camera takeover, like Hell's Gate flyovers)
    3. Trigger + script       graph name, trigger entity, once-only or repeating
    4. Place it               hands a PlacementGroup to the canvas; the sequence
                              follows the cursor and you click to drop it

Nothing is written until step 4's drop. Cancel at any point costs nothing.
"""

from __future__ import annotations

import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMessageBox,
                             QPushButton, QTextEdit, QVBoxLayout, QWidget)

import sequence_export_import as sx
import sequence_link as sl
import sequence_placement


SEQUENCES_DIRNAME = "sequences"


def sequences_folder() -> str:
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, SEQUENCES_DIRNAME)
    os.makedirs(path, exist_ok=True)
    return path


# ── export ─────────────────────────────────────────────────────────────────────

class SequenceExportDialog(QDialog):
    """Pick a sequence from the loaded level and write it out as a bundle."""

    def __init__(self, parent):
        super().__init__(parent)
        self.editor = parent
        self.setWindowTitle("Export Cinematic Sequence")
        self.setModal(True)
        self.resize(620, 520)
        self._build()
        self._load_sequences()

    def _build(self):
        layout = QVBoxLayout(self)
        title = QLabel("Export a sequence from the current level")
        title.setFont(QFont("Arial", 12, QFont.Bold))
        layout.addWidget(title)

        box = QGroupBox("Sequences in this level")
        bl = QVBoxLayout(box)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_pick)
        bl.addWidget(self.list)
        layout.addWidget(box)

        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(150)
        layout.addWidget(self.details)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        form.addRow("Save as:", self.name_edit)
        layout.addLayout(form)

        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        self.ok = QPushButton("Export"); self.ok.clicked.connect(self._export)
        self.ok.setEnabled(False)
        row.addWidget(cancel); row.addWidget(self.ok)
        layout.addLayout(row)

    def _moviedata_path(self):
        md = getattr(self.editor, "movie_data", None)
        return getattr(md, "source_path", None) if md else None

    def _load_sequences(self):
        md = getattr(self.editor, "movie_data", None)
        if md is None or not getattr(md, "sequences", None):
            self.details.setPlainText(
                "No moviedata loaded for this level.\n\n"
                "Load a level that has generated/moviedata.xml first.")
            return
        for seq in md.sequences:
            item = QListWidgetItem(f"{seq.name}   ({seq.duration():g}s, "
                                   f"{len(seq.nodes)} nodes)")
            item.setData(Qt.UserRole, seq.name)
            self.list.addItem(item)

    def _on_pick(self, cur, _prev):
        if cur is None:
            return
        name = cur.data(Qt.UserRole)
        self.name_edit.setText(name)
        self.ok.setEnabled(True)
        md = self.editor.movie_data
        seq = md.get_sequence(name)
        lines = [f"{name}", f"  duration: {seq.duration():g}s",
                 f"  nodes: {len(seq.nodes)}", ""]
        cams = 0
        for sn in seq.nodes:
            nd = md.node_defs.get(sn.node_id)
            nm = nd.name if nd else f"<id {sn.node_id}>"
            if nd and (nm.startswith("CameraCinematic") or "Camera.Cinematic" in nm):
                cams += 1
            keys = sum(len(t.pos_keys) + len(t.rot_keys)
                       for t in sn.tracks.values())
            lines.append(f"    {nm}   ({keys} keys)")
        lines.append("")
        lines.append(f"  cinematic cameras: {cams}"
                     + ("  — can be stripped on import to make a scripted event"
                        if cams else "  — already a scripted event"))
        self.details.setPlainText("\n".join(lines))

    def _export(self):
        item = self.list.currentItem()
        if item is None:
            return
        seq_name = item.data(Qt.UserRole)
        folder_name = (self.name_edit.text().strip() or seq_name)
        safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in folder_name)
        out = os.path.join(sequences_folder(), safe)

        md_path = self._moviedata_path()
        if not md_path:
            QMessageBox.warning(self, "Export", "Could not find moviedata.xml on disk.")
            return

        worldsectors = os.path.join(os.path.dirname(md_path), "worldsectors")
        try:
            result = sx.export_sequence_with_entities(
                md_path, seq_name, worldsectors, out)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return

        msg = [f"Exported '{seq_name}' to:", out, "",
               f"entities included: {len(result['entities_exported'])}"]
        if result["entities_missing"]:
            msg += ["", "NOT found in converted worldsectors (the sequence will "
                        "still import, but these nodes have no entity to drive):"]
            msg += [f"  • {m}" for m in result["entities_missing"]]
        QMessageBox.information(self, "Export complete", "\n".join(msg))
        self.accept()


# ── import ─────────────────────────────────────────────────────────────────────

class SequenceImportDialog(QDialog):
    """Four-step import: pick bundle -> mode -> trigger -> place."""

    def __init__(self, parent):
        super().__init__(parent)
        self.editor = parent
        self.bundle = None
        self.setWindowTitle("Import Cinematic Sequence")
        self.setModal(True)
        self.resize(660, 640)
        self._build()
        self._load_bundles()

    def _build(self):
        layout = QVBoxLayout(self)
        title = QLabel("Import a sequence into this level")
        title.setFont(QFont("Arial", 12, QFont.Bold))
        layout.addWidget(title)

        # Step 1
        s1 = QGroupBox("1 — Sequence bundle")
        l1 = QVBoxLayout(s1)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_pick)
        l1.addWidget(self.list)
        self.details = QTextEdit(); self.details.setReadOnly(True)
        self.details.setMaximumHeight(120)
        l1.addWidget(self.details)
        layout.addWidget(s1)

        # Step 2
        s2 = QGroupBox("2 — How should it play?")
        l2 = QVBoxLayout(s2)
        self.mode = QComboBox()
        self.mode.addItem("Cutscene — takes the camera, player watches",
                          sx.MODE_CUTSCENE)
        self.mode.addItem("Scripted event — no camera, player keeps control",
                          sx.MODE_SCRIPTED)
        self.mode.currentIndexChanged.connect(self._on_mode)
        l2.addWidget(self.mode)
        self.strip_note = QLabel("")
        self.strip_note.setWordWrap(True)
        l2.addWidget(self.strip_note)
        layout.addWidget(s2)

        # Step 3
        s3 = QGroupBox("3 — Trigger and script")
        f3 = QFormLayout(s3)
        self.graph_name = QLineEdit()
        self.graph_name.setPlaceholderText("my_custom_cutscene")
        f3.addRow("Lua graph name:", self.graph_name)
        self.doc_name = QLineEdit("custom")
        f3.addRow("Document prefix:", self.doc_name)
        self.trigger_id = QLineEdit()
        self.trigger_id.setPlaceholderText("EntityId of the trigger volume")
        f3.addRow("Trigger entity:", self.trigger_id)
        self.once = QCheckBox("Play once only"); self.once.setChecked(True)
        f3.addRow("", self.once)
        self.snap = QCheckBox("Snap to terrain height while placing")
        self.snap.setChecked(True)
        f3.addRow("", self.snap)
        layout.addWidget(s3)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        row = QHBoxLayout(); row.addStretch()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        self.ok = QPushButton("4 — Place in level…")
        self.ok.clicked.connect(self._start_placement)
        self.ok.setEnabled(False)
        row.addWidget(cancel); row.addWidget(self.ok)
        layout.addLayout(row)

    def _load_bundles(self):
        folder = sequences_folder()
        found = 0
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if os.path.isdir(path) and os.path.exists(
                    os.path.join(path, sx.BUNDLE_INFO)):
                item = QListWidgetItem(name)
                item.setData(Qt.UserRole, path)
                self.list.addItem(item)
                found += 1
        if not found:
            self.details.setPlainText(
                f"No sequence bundles found in:\n{folder}\n\n"
                "Export one from a level first (Sequences → Export).")

    def _on_pick(self, cur, _prev):
        if cur is None:
            return
        try:
            self.bundle = sx.load_bundle(cur.data(Qt.UserRole))
        except Exception as exc:
            self.details.setPlainText(f"Could not read bundle: {exc}")
            self.bundle = None
            self.ok.setEnabled(False)
            return
        b = self.bundle
        cams = sx.camera_nodes(b)
        self.details.setPlainText(
            f"{b.name}\n  from: {b.source_level}\n"
            f"  duration: {b.duration:g}s\n"
            f"  nodes: {len(b.node_defs)}  (cinematic cameras: {len(cams)})")
        self.graph_name.setText(
            "".join(c.lower() if c.isalnum() else "_" for c in b.name))
        self.ok.setEnabled(True)
        self._on_mode()

    def _on_mode(self):
        if self.bundle is None:
            return
        cams = sx.camera_nodes(self.bundle)
        if self.mode.currentData() == sx.MODE_SCRIPTED and cams:
            self.strip_note.setText(
                f"The {len(cams)} cinematic camera(s) will be removed. Everything "
                f"else keeps its exact animation — this is how Hell's Gate flies "
                f"its Samsons overhead without taking the camera.")
        elif self.mode.currentData() == sx.MODE_CUTSCENE and not cams:
            self.strip_note.setText(
                "⚠ This bundle has no cinematic camera, so there is nothing to "
                "switch to. Choose 'Scripted event' instead.")
        else:
            self.strip_note.setText("")

    def _start_placement(self):
        if self.bundle is None:
            return
        mode = self.mode.currentData()
        cams = sx.camera_nodes(self.bundle)

        if mode == sx.MODE_CUTSCENE and not cams:
            QMessageBox.warning(self, "No camera",
                                "This bundle has no cinematic camera. Pick "
                                "'Scripted event' instead.")
            return
        if not self.graph_name.text().strip():
            QMessageBox.warning(self, "Name needed",
                                "Give the Lua graph a name.")
            return
        if mode == sx.MODE_SCRIPTED and cams:
            sx.strip_camera_nodes(self.bundle)

        group = sl.PlacementGroup.from_bundle(self.bundle)
        group.import_options = {
            "mode": mode,
            "graph_name": self.graph_name.text().strip(),
            "doc_name": self.doc_name.text().strip() or "custom",
            "trigger_id": self.trigger_id.text().strip(),
            "once_only": self.once.isChecked(),
            "camera_id": (cams[0].get("EntityId") if cams and
                          mode == sx.MODE_CUTSCENE else None),
        }
        sequence_placement.begin(self.editor, group,
                                 snap_to_terrain=self.snap.isChecked())
        self.accept()


# ── entry points, matching entity_export_import's naming ───────────────────────

def show_sequence_export_dialog(editor):
    SequenceExportDialog(editor).exec_()


def show_sequence_import_dialog(editor):
    SequenceImportDialog(editor).exec_()
