"""
Entity Library Browser — viewer for entitylibrary.fcb.converted.xml files.
Left panel  : Library → Prototype tree with search.
Right panel : Simple tab (QTreeWidget, fast) + XML tab (raw XML with search/copy).

Performance notes:
- File parsing runs in a QThread to keep the UI responsive.
- Simple tab uses QTreeWidget (virtualised rows) instead of dynamic widgets.
- XML tab writes text directly; deepcopy/indent are skipped for large prototypes.
- Syntax highlighter is applied lazily by Qt as blocks scroll into view.
"""

import os
import xml.etree.ElementTree as ET

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem,
    QTabWidget, QWidget, QLabel, QLineEdit, QPushButton, QPlainTextEdit,
    QMessageBox, QFileDialog, QApplication, QProgressBar, QHeaderView,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QTextCharFormat, QSyntaxHighlighter


# ---------------------------------------------------------------------------
# Background file loader
# ---------------------------------------------------------------------------

class _LoadWorker(QThread):
    done  = pyqtSignal(object)   # ET root element
    error = pyqtSignal(str)

    def __init__(self, path):
        super().__init__()
        self._path = path

    def run(self):
        try:
            root = ET.parse(self._path).getroot()
            self.done.emit(root)
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# XML syntax highlighter (applied lazily by Qt — no lag on large files)
# ---------------------------------------------------------------------------

class _XmlHighlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)
        import re
        _tag     = QTextCharFormat(); _tag.setForeground(QColor("#4EC9B0"))
        _attr    = QTextCharFormat(); _attr.setForeground(QColor("#9CDCFE"))
        _val     = QTextCharFormat(); _val.setForeground(QColor("#CE9178"))
        _comment = QTextCharFormat(); _comment.setForeground(QColor("#6A9955"))
        _hex     = QTextCharFormat(); _hex.setForeground(QColor("#666666"))
        self._rules = [
            (re.compile(r'<!--.*?-->', re.DOTALL), _comment),
            (re.compile(r'</?[\w:.-]+'),            _tag),
            (re.compile(r'\s[\w:.-]+='),             _attr),
            (re.compile(r'"[^"]*"'),                 _val),
            (re.compile(r'>[0-9A-Fa-f]{8,}<'),       _hex),
        ]

    def highlightBlock(self, text):
        for pat, fmt in self._rules:
            for m in pat.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _field_value(field_elem):
    for attr in ('value-String', 'value-Int32', 'value-Float32', 'value-Boolean',
                 'value-Vector3', 'value-Hash32', 'value-ComputeHash32',
                 'value-Id64', 'value-Enum'):
        v = field_elem.get(attr)
        if v is not None:
            return v
    for attr in field_elem.attrib:
        if attr.startswith('value-'):
            return field_elem.get(attr)
    return ""


def _field_type(field_elem):
    for attr in field_elem.attrib:
        if attr.startswith('value-'):
            return attr[6:]
    return ""


def _add_elem_to_tree(elem, parent_item, depth=0):
    """Recursively add an FCB <object> and its children to a QTreeWidget item."""
    title = elem.get('name') or elem.get('hash', 'object')
    obj_item = QTreeWidgetItem(parent_item, [title, ""])
    obj_item.setExpanded(depth < 2)
    obj_item.setForeground(0, QColor("#4EC9B0") if depth == 0 else QColor("#B5CEA8"))

    for field in elem.findall("field"):
        name  = field.get('name') or field.get('hash', '?')
        value = _field_value(field)
        ftype = _field_type(field)
        fi = QTreeWidgetItem(obj_item, [name, value])
        fi.setForeground(0, QColor("#9CDCFE"))
        fi.setForeground(1, QColor("#d4d4d4"))
        if ftype:
            fi.setToolTip(1, f"Type: {ftype}")

    if depth < 5:
        for child in elem.findall("object"):
            _add_elem_to_tree(child, obj_item, depth + 1)
    else:
        children = elem.findall("object")
        if children:
            note = QTreeWidgetItem(obj_item, [f"… {len(children)} nested object(s)", ""])
            note.setForeground(0, QColor("#666"))


_XML_DISPLAY_LIMIT = 300_000   # chars; beyond this the XML tab shows a notice


# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------

class EntityLibraryBrowserDialog(QDialog):
    """Browse entitylibrary.fcb.converted.xml files."""

    def __init__(self, parent=None, file_path=None):
        super().__init__(parent)
        self.setWindowTitle("Entity Library Browser")
        self.resize(1350, 860)

        self._xml_root        = None
        self._proto_items     = {}   # id(QTreeWidgetItem) → (proto_elem, entity_elem, proto_name, lib_name)
        self._load_worker     = None
        self._filter_matches  = []   # list of visible prototype QTreeWidgetItems
        self._filter_index    = -1   # current position in _filter_matches

        self._setup_ui()

        if file_path and os.path.exists(file_path):
            self._start_load(file_path)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # ── Top bar ──────────────────────────────────────────────────────
        top = QHBoxLayout()
        open_btn = QPushButton("Open File…")
        open_btn.setFixedWidth(90)
        open_btn.clicked.connect(self._browse_file)

        self._file_label = QLabel("No file loaded")
        self._file_label.setStyleSheet("color: #888; font-size: 10px;")

        self._count_label = QLabel("")
        self._count_label.setStyleSheet("color: #666; font-size: 10px;")

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedWidth(120)
        self._progress.setFixedHeight(14)
        self._progress.setVisible(False)

        top.addWidget(open_btn)
        top.addWidget(self._file_label, 1)
        top.addWidget(self._progress)
        top.addWidget(self._count_label)
        root.addLayout(top)

        # ── Splitter ─────────────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: entity tree + search
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(2)

        # Search row with next/prev navigation
        search_row = QHBoxLayout()
        search_row.setSpacing(2)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter prototypes…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._filter_entity_tree)
        self._search.returnPressed.connect(lambda: self._step_filter(+1))

        _btn_style = (
            "QPushButton { background: #2a3a4a; color: #aaa; border: 1px solid #3a4a5a;"
            " border-radius: 3px; font-size: 10px; padding: 1px 4px; }"
            "QPushButton:hover { background: #3a4a5a; }"
            "QPushButton:disabled { color: #555; }"
        )
        self._prev_btn = QPushButton("▲")
        self._prev_btn.setFixedSize(22, 22)
        self._prev_btn.setToolTip("Previous match")
        self._prev_btn.setStyleSheet(_btn_style)
        self._prev_btn.clicked.connect(lambda: self._step_filter(-1))
        self._prev_btn.setEnabled(False)

        self._next_btn = QPushButton("▼")
        self._next_btn.setFixedSize(22, 22)
        self._next_btn.setToolTip("Next match")
        self._next_btn.setStyleSheet(_btn_style)
        self._next_btn.clicked.connect(lambda: self._step_filter(+1))
        self._next_btn.setEnabled(False)

        self._match_label = QLabel("")
        self._match_label.setStyleSheet("color: #888; font-size: 9px;")
        self._match_label.setFixedWidth(52)
        self._match_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        search_row.addWidget(self._search, 1)
        search_row.addWidget(self._prev_btn)
        search_row.addWidget(self._next_btn)
        search_row.addWidget(self._match_label)
        ll.addLayout(search_row)

        # Expand / Collapse All buttons
        expand_row = QHBoxLayout()
        expand_row.setSpacing(2)
        expand_all_btn = QPushButton("Expand All")
        expand_all_btn.setStyleSheet(_btn_style)
        expand_all_btn.setFixedHeight(20)
        expand_all_btn.clicked.connect(lambda: self._entity_tree.expandAll())
        collapse_all_btn = QPushButton("Collapse All")
        collapse_all_btn.setStyleSheet(_btn_style)
        collapse_all_btn.setFixedHeight(20)
        collapse_all_btn.clicked.connect(lambda: self._entity_tree.collapseAll())
        expand_row.addWidget(expand_all_btn)
        expand_row.addWidget(collapse_all_btn)
        ll.addLayout(expand_row)

        self._entity_tree = QTreeWidget()
        self._entity_tree.setHeaderLabel("Library / Prototype")
        self._entity_tree.setUniformRowHeights(True)
        self._entity_tree.itemClicked.connect(self._on_item_clicked)
        ll.addWidget(self._entity_tree, 1)

        splitter.addWidget(left)

        # Right: header + tabs
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        self._header = QLabel("Select a prototype from the list")
        self._header.setStyleSheet(
            "font-weight: bold; font-size: 12px; color: #ccc;"
            " padding: 5px 8px; background: #1e2a38; border-bottom: 1px solid #333;")
        rl.addWidget(self._header)

        self._tabs = QTabWidget()
        self._tabs.currentChanged.connect(self._on_tab_changed)
        rl.addWidget(self._tabs, 1)

        self._tabs.addTab(self._build_simple_tab_ui(), "Simple")
        self._tabs.addTab(self._build_xml_tab_ui(),    "XML")

        splitter.addWidget(right)
        splitter.setSizes([280, 1070])
        root.addWidget(splitter, 1)

        # Track current selection for lazy XML load
        self._current_proto_elem = None

    def _build_simple_tab_ui(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        _btn_style = (
            "QPushButton { background: #2a3a4a; color: #aaa; border: 1px solid #3a4a5a;"
            " border-radius: 3px; font-size: 10px; padding: 1px 4px; }"
            "QPushButton:hover { background: #3a4a5a; }"
            "QPushButton:disabled { color: #555; }"
        )

        # Toolbar row: search + nav + expand/collapse
        srow = QHBoxLayout()
        srow.setContentsMargins(4, 4, 4, 2)
        srow.setSpacing(3)

        lbl = QLabel("Search:")
        lbl.setStyleSheet("color: #888; font-size: 10px;")
        lbl.setFixedWidth(42)

        self._simple_search = QLineEdit()
        self._simple_search.setPlaceholderText("Filter fields and components…")
        self._simple_search.setClearButtonEnabled(True)
        self._simple_search.setStyleSheet("font-size: 10px;")
        self._simple_search.textChanged.connect(self._filter_simple_tree)
        self._simple_search.returnPressed.connect(lambda: self._step_simple(+1))

        self._simple_prev = QPushButton("▲")
        self._simple_prev.setFixedSize(22, 22)
        self._simple_prev.setToolTip("Previous match")
        self._simple_prev.setStyleSheet(_btn_style)
        self._simple_prev.setEnabled(False)
        self._simple_prev.clicked.connect(lambda: self._step_simple(-1))

        self._simple_next = QPushButton("▼")
        self._simple_next.setFixedSize(22, 22)
        self._simple_next.setToolTip("Next match")
        self._simple_next.setStyleSheet(_btn_style)
        self._simple_next.setEnabled(False)
        self._simple_next.clicked.connect(lambda: self._step_simple(+1))

        self._simple_match_label = QLabel("")
        self._simple_match_label.setStyleSheet("color: #888; font-size: 9px;")
        self._simple_match_label.setFixedWidth(52)
        self._simple_match_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        sep = QLabel("|")
        sep.setStyleSheet("color: #444; font-size: 10px;")

        expand_btn = QPushButton("Expand All")
        expand_btn.setStyleSheet(_btn_style)
        expand_btn.setFixedHeight(22)
        expand_btn.clicked.connect(lambda: self._simple_tree.expandAll())

        collapse_btn = QPushButton("Collapse All")
        collapse_btn.setStyleSheet(_btn_style)
        collapse_btn.setFixedHeight(22)
        collapse_btn.clicked.connect(lambda: self._simple_tree.collapseAll())

        srow.addWidget(lbl)
        srow.addWidget(self._simple_search, 1)
        srow.addWidget(self._simple_prev)
        srow.addWidget(self._simple_next)
        srow.addWidget(self._simple_match_label)
        srow.addWidget(sep)
        srow.addWidget(expand_btn)
        srow.addWidget(collapse_btn)
        layout.addLayout(srow)

        # QTreeWidget — virtualised, handles thousands of rows without lag
        self._simple_tree = QTreeWidget()
        self._simple_tree.setColumnCount(2)
        self._simple_tree.setHeaderLabels(["Field / Component", "Value"])
        self._simple_tree.setUniformRowHeights(True)
        self._simple_tree.setAlternatingRowColors(True)
        self._simple_tree.setRootIsDecorated(True)
        self._simple_tree.setWordWrap(False)
        header = self._simple_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._simple_tree.setColumnWidth(0, 240)
        layout.addWidget(self._simple_tree, 1)

        # Internal state for simple-tab navigation
        self._simple_matches = []   # flat list of matching QTreeWidgetItems
        self._simple_index   = -1

        return tab

    def _build_xml_tab_ui(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        _btn_style = (
            "QPushButton { background: #2a3a4a; color: #aaa; border: 1px solid #3a4a5a;"
            " border-radius: 3px; font-size: 10px; padding: 1px 4px; }"
            "QPushButton:hover { background: #3a4a5a; }"
            "QPushButton:disabled { color: #555; }"
        )

        toolbar = QHBoxLayout()
        toolbar.setSpacing(3)

        self._xml_status = QLabel("")
        self._xml_status.setStyleSheet("color: #888; font-size: 10px;")

        find_lbl = QLabel("Find:")
        find_lbl.setStyleSheet("color: #888; font-size: 10px;")
        find_lbl.setFixedWidth(28)

        self._xml_find = QLineEdit()
        self._xml_find.setPlaceholderText("Search XML…")
        self._xml_find.setClearButtonEnabled(True)
        self._xml_find.setStyleSheet("font-size: 10px;")
        self._xml_find.setFixedWidth(160)
        self._xml_find.textChanged.connect(self._on_xml_find_changed)
        self._xml_find.returnPressed.connect(lambda: self._step_xml(+1))

        self._xml_prev = QPushButton("▲")
        self._xml_prev.setFixedSize(22, 22)
        self._xml_prev.setToolTip("Previous match")
        self._xml_prev.setStyleSheet(_btn_style)
        self._xml_prev.setEnabled(False)
        self._xml_prev.clicked.connect(lambda: self._step_xml(-1))

        self._xml_next = QPushButton("▼")
        self._xml_next.setFixedSize(22, 22)
        self._xml_next.setToolTip("Next match")
        self._xml_next.setStyleSheet(_btn_style)
        self._xml_next.setEnabled(False)
        self._xml_next.clicked.connect(lambda: self._step_xml(+1))

        self._xml_match_label = QLabel("")
        self._xml_match_label.setStyleSheet("color: #888; font-size: 9px;")
        self._xml_match_label.setFixedWidth(52)
        self._xml_match_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        copy_btn = QPushButton("Copy XML")
        copy_btn.setFixedWidth(75)
        copy_btn.setStyleSheet(_btn_style)
        copy_btn.clicked.connect(self._copy_xml)

        toolbar.addWidget(self._xml_status)
        toolbar.addStretch()
        toolbar.addWidget(find_lbl)
        toolbar.addWidget(self._xml_find)
        toolbar.addWidget(self._xml_prev)
        toolbar.addWidget(self._xml_next)
        toolbar.addWidget(self._xml_match_label)
        toolbar.addWidget(copy_btn)
        layout.addLayout(toolbar)

        self._xml_view = QPlainTextEdit()
        self._xml_view.setFont(QFont("Consolas", 9))
        self._xml_view.setReadOnly(True)
        self._xml_view.setStyleSheet(
            "QPlainTextEdit { background: #1a1a1a; color: #d4d4d4;"
            " border: 1px solid #333; font-family: Consolas, monospace; }")
        self._xml_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        _XmlHighlighter(self._xml_view.document())
        layout.addWidget(self._xml_view, 1)

        # Internal XML-find state
        self._xml_cursors = []   # list of QTextCursor for each match
        self._xml_find_index = -1

        return tab

    # ------------------------------------------------------------------
    # File loading (background thread)
    # ------------------------------------------------------------------

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Entity Library XML", "",
            "Entity Library XML (*.xml);;All Files (*)")
        if path:
            self._start_load(path)

    def _start_load(self, file_path):
        # Kill any previous worker
        if self._load_worker and self._load_worker.isRunning():
            self._load_worker.quit()
            self._load_worker.wait()

        self._file_label.setText(f"Loading {os.path.basename(file_path)}…")
        self._progress.setVisible(True)
        self._entity_tree.clear()
        self._proto_items = {}
        self._filter_matches = []
        self._filter_index = -1
        self._match_label.setText("")
        self._prev_btn.setEnabled(False)
        self._next_btn.setEnabled(False)
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._simple_tree.clear()
        self._xml_view.setPlainText("")
        self._current_proto_elem = None
        self._header.setText("Loading…")

        self._load_worker = _LoadWorker(file_path)
        self._load_worker.done.connect(lambda root: self._on_loaded(root, file_path))
        self._load_worker.error.connect(self._on_load_error)
        self._load_worker.start()

    def _on_loaded(self, root, file_path):
        self._progress.setVisible(False)
        self._xml_root = root
        self._file_label.setText(os.path.basename(file_path))
        self._header.setText("Select a prototype from the list")
        self._populate_entity_tree()

    def _on_load_error(self, msg):
        self._progress.setVisible(False)
        self._file_label.setText("Load failed")
        QMessageBox.warning(self, "Entity Library Browser", f"Failed to load file:\n{msg}")

    # ------------------------------------------------------------------
    # Entity tree population
    # ------------------------------------------------------------------

    def _populate_entity_tree(self):
        self._entity_tree.clear()
        self._proto_items = {}
        total = 0

        libs = self._xml_root.findall("object[@name='EntityLibrary']")
        for lib_elem in libs:
            nf = lib_elem.find("field[@name='Name']")
            lib_name = nf.get('value-String', 'Library') if nf is not None else 'Library'

            lib_item = QTreeWidgetItem(self._entity_tree, [lib_name])
            lib_item.setExpanded(True)
            lib_item.setFlags(lib_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            f = lib_item.font(0); f.setBold(True); lib_item.setFont(0, f)
            lib_item.setForeground(0, QColor("#4EC9B0"))

            for proto_elem in lib_elem.findall("object[@name='EntityPrototype']"):
                pf = proto_elem.find("field[@name='Name']")
                proto_name = pf.get('value-String', 'Unknown') if pf is not None else 'Unknown'
                entity_elem = proto_elem.find("object[@name='Entity']")

                proto_item = QTreeWidgetItem(lib_item, [proto_name])
                key = id(proto_item)
                self._proto_items[key] = (proto_elem, entity_elem, proto_name, lib_name)
                proto_item.setData(0, Qt.ItemDataRole.UserRole, key)
                total += 1

        self._count_label.setText(f"{total} prototypes")

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_item_clicked(self, item, _col):
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if key is None or key not in self._proto_items:
            return
        proto_elem, entity_elem, proto_name, lib_name = self._proto_items[key]
        self._current_proto_elem = proto_elem
        self._header.setText(f"{lib_name}  ›  {proto_name}")
        self._simple_search.blockSignals(True)
        self._simple_search.clear()
        self._simple_search.blockSignals(False)
        self._simple_matches = []
        self._simple_index = -1
        self._simple_match_label.setText("")
        self._simple_prev.setEnabled(False)
        self._simple_next.setEnabled(False)
        self._xml_cursors = []
        self._xml_find_index = -1
        self._xml_match_label.setText("")
        self._xml_prev.setEnabled(False)
        self._xml_next.setEnabled(False)
        self._xml_view.setPlainText("")   # will lazy-load when tab is switched
        self._refresh_simple_tab(entity_elem)
        # Only render XML if that tab is visible — avoids serialising huge elements
        if self._tabs.currentIndex() == 1:
            self._refresh_xml_tab(proto_elem)

    def _on_tab_changed(self, index):
        # Lazy-load XML tab when the user switches to it
        if index == 1 and self._current_proto_elem is not None:
            if not self._xml_view.toPlainText():
                self._refresh_xml_tab(self._current_proto_elem)

    # ------------------------------------------------------------------
    # Simple tab — QTreeWidget, no dynamic widgets
    # ------------------------------------------------------------------

    def _refresh_simple_tab(self, entity_elem):
        self._simple_tree.setUpdatesEnabled(False)
        self._simple_tree.clear()

        if entity_elem is None:
            self._simple_tree.setUpdatesEnabled(True)
            return

        # Properties group — direct <field> children of Entity
        direct_fields = entity_elem.findall("field")
        if direct_fields:
            props_item = QTreeWidgetItem(self._simple_tree, ["Properties", ""])
            props_item.setExpanded(True)
            f = props_item.font(0); f.setBold(True); props_item.setFont(0, f)
            props_item.setForeground(0, QColor("#aaaaaa"))
            for field in direct_fields:
                name  = field.get('name') or field.get('hash', '?')
                value = _field_value(field)
                ftype = _field_type(field)
                fi = QTreeWidgetItem(props_item, [name, value])
                fi.setForeground(0, QColor("#9CDCFE"))
                fi.setForeground(1, QColor("#d4d4d4"))
                if ftype:
                    fi.setToolTip(1, f"Type: {ftype}")

        # Components
        components_elem = entity_elem.find("object[@name='Components']")
        if components_elem is not None:
            for comp in components_elem:
                if comp.tag == 'object':
                    _add_elem_to_tree(comp, self._simple_tree)

        # Other direct child objects
        for child in entity_elem.findall("object"):
            if child.get('name') != 'Components':
                _add_elem_to_tree(child, self._simple_tree)

        self._simple_tree.setUpdatesEnabled(True)

    def _filter_simple_tree(self, text):
        text = text.lower().strip()
        self._simple_matches = []
        self._simple_index = -1

        root = self._simple_tree.invisibleRootItem()
        for i in range(root.childCount()):
            top = root.child(i)
            if not text:
                top.setHidden(False)
                self._set_subtree_hidden(top, False)
                continue
            matched = self._collect_matches(top, text, self._simple_matches)
            top.setHidden(not matched)

        n = len(self._simple_matches)
        has = bool(text)
        self._simple_prev.setEnabled(has and n > 1)
        self._simple_next.setEnabled(has and n > 1)
        if not has:
            self._simple_match_label.setText("")
        elif n == 0:
            self._simple_match_label.setText("0")
        else:
            self._simple_index = 0
            self._jump_simple(0)

    def _collect_matches(self, item, text, out):
        """Recursively collect items that directly contain text; returns True if any match in subtree."""
        self_match = any(text in item.text(c).lower() for c in range(item.columnCount()))
        child_match = any(self._collect_matches(item.child(i), text, out)
                          for i in range(item.childCount()))
        if self_match:
            out.append(item)
        return self_match or child_match

    def _step_simple(self, direction):
        n = len(self._simple_matches)
        if n == 0:
            return
        self._simple_index = (self._simple_index + direction) % n
        self._jump_simple(self._simple_index)

    def _jump_simple(self, index):
        n = len(self._simple_matches)
        if n == 0:
            return
        item = self._simple_matches[index]
        self._simple_tree.setCurrentItem(item)
        self._simple_tree.scrollToItem(item)
        self._simple_match_label.setText(f"{index + 1}/{n}")

    def _subtree_matches(self, item, text):
        for col in range(item.columnCount()):
            if text in item.text(col).lower():
                return True
        for i in range(item.childCount()):
            if self._subtree_matches(item.child(i), text):
                return True
        return False

    def _set_subtree_hidden(self, item, hidden):
        item.setHidden(hidden)
        for i in range(item.childCount()):
            self._set_subtree_hidden(item.child(i), hidden)

    # ------------------------------------------------------------------
    # XML tab
    # ------------------------------------------------------------------

    def _refresh_xml_tab(self, proto_elem):
        if proto_elem is None:
            self._xml_view.setPlainText("")
            self._xml_status.setText("")
            return
        try:
            text = ET.tostring(proto_elem, encoding='unicode')
            if len(text) > _XML_DISPLAY_LIMIT:
                shown = text[:_XML_DISPLAY_LIMIT]
                self._xml_view.setPlainText(
                    shown + f"\n\n… truncated — {len(text):,} chars total"
                    " (use Copy XML to get the full content)")
                self._xml_status.setText(
                    f"{len(text):,} chars (showing first {_XML_DISPLAY_LIMIT:,})")
            else:
                self._xml_view.setPlainText(text)
                self._xml_status.setText(f"{len(text):,} chars")
        except Exception as exc:
            self._xml_view.setPlainText(f"Error: {exc}")

    def _copy_xml(self):
        if self._current_proto_elem is None:
            return
        try:
            text = ET.tostring(self._current_proto_elem, encoding='unicode')
            QApplication.clipboard().setText(text)
        except Exception as exc:
            QMessageBox.warning(self, "Copy XML", f"Failed:\n{exc}")

    def _on_xml_find_changed(self, text):
        """Rebuild the list of all match cursors and jump to the first one."""
        from PyQt6.QtGui import QTextDocument
        self._xml_cursors = []
        self._xml_find_index = -1

        if not text:
            cur = self._xml_view.textCursor()
            cur.clearSelection()
            self._xml_view.setTextCursor(cur)
            self._xml_match_label.setText("")
            self._xml_prev.setEnabled(False)
            self._xml_next.setEnabled(False)
            return

        doc = self._xml_view.document()
        cursor = doc.find(text)
        while not cursor.isNull():
            self._xml_cursors.append(cursor)
            cursor = doc.find(text, cursor)

        n = len(self._xml_cursors)
        self._xml_prev.setEnabled(n > 1)
        self._xml_next.setEnabled(n > 1)
        if n == 0:
            self._xml_match_label.setText("0")
        else:
            self._xml_find_index = 0
            self._jump_xml(0)

    def _step_xml(self, direction):
        n = len(self._xml_cursors)
        if n == 0:
            return
        self._xml_find_index = (self._xml_find_index + direction) % n
        self._jump_xml(self._xml_find_index)

    def _jump_xml(self, index):
        n = len(self._xml_cursors)
        if n == 0:
            return
        self._xml_view.setTextCursor(self._xml_cursors[index])
        self._xml_match_label.setText(f"{index + 1}/{n}")

    # ------------------------------------------------------------------
    # Entity tree filter + next/prev navigation
    # ------------------------------------------------------------------

    def _filter_entity_tree(self, text):
        text = text.lower().strip()
        self._filter_matches = []

        for i in range(self._entity_tree.topLevelItemCount()):
            lib_item = self._entity_tree.topLevelItem(i)
            any_vis = False
            for j in range(lib_item.childCount()):
                proto_item = lib_item.child(j)
                match = not text or text in proto_item.text(0).lower()
                proto_item.setHidden(not match)
                if match:
                    any_vis = True
                    self._filter_matches.append(proto_item)
            lib_item.setHidden(not any_vis and bool(text))

        n = len(self._filter_matches)
        has_filter = bool(text)
        self._prev_btn.setEnabled(has_filter and n > 1)
        self._next_btn.setEnabled(has_filter and n > 1)

        if not has_filter:
            self._filter_index = -1
            self._match_label.setText("")
        elif n == 0:
            self._filter_index = -1
            self._match_label.setText("0")
        else:
            # Auto-select the first match
            self._filter_index = 0
            self._jump_to_match(0)

    def _step_filter(self, direction):
        """Move to next (+1) or previous (-1) match."""
        n = len(self._filter_matches)
        if n == 0:
            return
        self._filter_index = (self._filter_index + direction) % n
        self._jump_to_match(self._filter_index)

    def _jump_to_match(self, index):
        n = len(self._filter_matches)
        if n == 0:
            return
        item = self._filter_matches[index]
        self._entity_tree.setCurrentItem(item)
        self._entity_tree.scrollToItem(item)
        self._match_label.setText(f"{index + 1}/{n}")
        # Load the prototype into the right panel
        self._on_item_clicked(item, 0)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        if self._load_worker and self._load_worker.isRunning():
            self._load_worker.quit()
            self._load_worker.wait()
        super().closeEvent(event)
