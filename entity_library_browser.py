"""
Entity Library Browser / FCB editor — for entitylibrary.fcb.converted.xml files.
Left panel  : Library → Prototype tree with search.
Right panel : Simple tab (editable QTreeWidget) + XML tab (editable raw XML).

Editing model (matches the entity editor's philosophy):
- Simple tab: click a field's Value cell to edit it in place. The edit updates
  BOTH the cosmetic `value-*` attribute AND the authoritative BinHex text —
  the native FCB converter reads the BinHex, so without that sync an edit
  would silently not make it into the regenerated .fcb.
- XML tab: free-text editing + "Apply Changes". On apply the edited XML is
  parsed and every simple field's BinHex is REGENERATED from its `value-*`
  attribute (the friendly value wins; hand-edited hex on such fields is
  overwritten). Structural fields (child elements / __rawhex) are untouched.
- Save writes the whole tree back to the loaded file (first save keeps a .bak).
  Reconverting to .fcb stays with the Tools-menu entitylibrary converter.

Encodings ground-truthed against retail files (Aug 2026): value-ComputeHash32
stores CRC-32 of the (case-sensitive) string; Hash32/UInt32/Enum are LE uint32
of the shown integer; String is null-terminated ASCII; Float32/Vector2/3/4 are
LE floats; Boolean is one byte 01/00; Id64 is LE uint64.

Performance notes:
- File parsing runs in a QThread to keep the UI responsive.
- Simple tab uses QTreeWidget (virtualised rows) instead of dynamic widgets.
- XML tab writes text directly; deepcopy/indent are skipped for large prototypes.
- Syntax highlighter is applied lazily by Qt as blocks scroll into view.
"""

import os
import struct
import zlib
import xml.etree.ElementTree as ET

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem,
    QTabWidget, QWidget, QLabel, QLineEdit, QPushButton, QPlainTextEdit,
    QMessageBox, QFileDialog, QApplication, QProgressBar, QHeaderView,
    QAbstractItemView,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QTextCharFormat, QSyntaxHighlighter


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


def _make_backup(path):
    """Copy path → path.bak once (never overwrite an existing backup)."""
    bak = path + '.bak'
    if not os.path.exists(bak):
        import shutil
        shutil.copy2(path, bak)
        return True
    return False


class _SaveWorker(QThread):
    """Serialise + write the edited library off the GUI thread (these files can
    be tens of MB). The tree is not mutated while saving — the dialog disables
    Save until the worker reports back."""
    done  = pyqtSignal(bool)     # backup_made
    error = pyqtSignal(str)

    def __init__(self, root, path, make_backup=True):
        super().__init__()
        self._root = root
        self._path = path
        self._make_backup = make_backup

    def run(self):
        try:
            backed_up = _make_backup(self._path) if self._make_backup else False
            ET.ElementTree(self._root).write(
                self._path, encoding='utf-8', xml_declaration=True)
            self.done.emit(backed_up)
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# XML syntax highlighter (applied lazily by Qt — no lag on large files)
# ---------------------------------------------------------------------------

# Syntax + tree item colors per theme (VS Code-ish dark; darker ink on light).
_SYNTAX = {
    True:  {'tag': '#4EC9B0', 'attr': '#9CDCFE', 'val': '#CE9178',
            'comment': '#6A9955', 'hex': '#666666'},
    False: {'tag': '#0B7261', 'attr': '#0451A5', 'val': '#A31515',
            'comment': '#008000', 'hex': '#999999'},
}
_ITEM_COLORS = {
    True:  {'obj': '#4EC9B0', 'obj2': '#B5CEA8', 'name': '#9CDCFE',
            'val': '#d4d4d4', 'ro': '#8a8a8a', 'dim': '#666666'},
    False: {'obj': '#0B7261', 'obj2': '#4B7A2F', 'name': '#0451A5',
            'val': '#1e1e1e', 'ro': '#777777', 'dim': '#999999'},
}


class _XmlHighlighter(QSyntaxHighlighter):
    def __init__(self, doc, dark=True):
        super().__init__(doc)
        self._rules = []
        self.set_dark(dark)

    def set_dark(self, dark):
        import re
        c = _SYNTAX[bool(dark)]
        def _fmt(color):
            f = QTextCharFormat(); f.setForeground(QColor(color)); return f
        self._rules = [
            (re.compile(r'<!--.*?-->', re.DOTALL), _fmt(c['comment'])),
            (re.compile(r'</?[\w:.-]+'),            _fmt(c['tag'])),
            (re.compile(r'\s[\w:.-]+='),             _fmt(c['attr'])),
            (re.compile(r'"[^"]*"'),                 _fmt(c['val'])),
            (re.compile(r'>[0-9A-Fa-f]{8,}<'),       _fmt(c['hex'])),
        ]
        self.rehighlight()

    def highlightBlock(self, text):
        for pat, fmt in self._rules:
            for m in pat.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ---------------------------------------------------------------------------
# Value ↔ BinHex encoding (verified against retail converted XML)
# ---------------------------------------------------------------------------

def _enc_floats(value, n):
    parts = [float(v) for v in str(value).replace(' ', '').split(',') if v != '']
    if len(parts) != n:
        raise ValueError(f"expected {n} comma-separated numbers")
    return struct.pack('<' + 'f' * n, *parts).hex().upper()


_BINHEX_ENCODERS = {
    'String':         lambda v: (str(v) + '\x00').encode('ascii', 'replace').hex().upper(),
    'ComputeHash32':  lambda v: struct.pack('<I', zlib.crc32(str(v).encode('utf-8'))).hex().upper(),
    'Hash32':         lambda v: struct.pack('<I', int(v) & 0xFFFFFFFF).hex().upper(),
    'UInt32':         lambda v: struct.pack('<I', int(v)).hex().upper(),
    'Enum':           lambda v: struct.pack('<I', int(v)).hex().upper(),
    'Int32':          lambda v: struct.pack('<i', int(v)).hex().upper(),
    'Id64':           lambda v: struct.pack('<Q', int(v)).hex().upper(),
    'Float32':        lambda v: struct.pack('<f', float(v)).hex().upper(),
    'Boolean':        lambda v: '01' if str(v).strip().lower() in ('true', '1', 'yes') else '00',
    'Vector2':        lambda v: _enc_floats(v, 2),
    'Vector3':        lambda v: _enc_floats(v, 3),
    'Vector4':        lambda v: _enc_floats(v, 4),
}

_BOOL_NORMALIZE = {'Boolean': lambda v: 'True' if str(v).strip().lower() in ('true', '1', 'yes') else 'False'}


def _field_value_attr(field_elem):
    """The field's single value-* attribute name, or None."""
    attrs = [a for a in field_elem.attrib if a.startswith('value-')]
    return attrs[0] if len(attrs) == 1 else None


def _field_is_editable(field_elem):
    """Simple scalar fields only: one supported value-* attr, no child elements,
    no authoritative __rawhex (structural RML fields — editing their text would
    be ignored or corrupt the re-encode)."""
    if field_elem.get('__rawhex') is not None or len(field_elem) > 0:
        return False
    attr = _field_value_attr(field_elem)
    return attr is not None and attr[6:] in _BINHEX_ENCODERS


def _apply_field_edit(field_elem, new_value):
    """Write `new_value` into the field: value-* attribute (cosmetic display)
    AND regenerated BinHex text (what the FCB converter actually reads).
    Returns the normalized display value. Raises ValueError on bad input."""
    attr = _field_value_attr(field_elem)
    if attr is None or not _field_is_editable(field_elem):
        raise ValueError("field is not editable")
    suffix = attr[6:]
    try:
        hexstr = _BINHEX_ENCODERS[suffix](new_value)
    except (ValueError, OverflowError, struct.error) as exc:
        raise ValueError(f"invalid {suffix} value: {exc}")
    shown = _BOOL_NORMALIZE.get(suffix, lambda v: str(v))(new_value)
    field_elem.set(attr, shown)
    field_elem.text = hexstr
    return shown


def _resync_binhex(root_elem):
    """Regenerate BinHex from the value-* attribute on every editable field
    under root_elem (used after a raw-XML edit — the friendly value wins).
    Returns the number of fields whose hex actually changed."""
    changed = 0
    for field in root_elem.iter('field'):
        if not _field_is_editable(field):
            continue
        attr = _field_value_attr(field)
        try:
            hexstr = _BINHEX_ENCODERS[attr[6:]](field.get(attr))
        except (ValueError, OverflowError, struct.error):
            continue   # unparsable display value — leave the existing hex alone
        if (field.text or '').strip().upper() != hexstr:
            field.text = hexstr
            changed += 1
    return changed


# ---------------------------------------------------------------------------
# Theming — the dialog follows the user's Light/Dark preference via
# theme_settings.apply_dialog_theme (it used to hardcode a dark stylesheet,
# and before that no stylesheet at all — white-on-white on the light palette).
# Tree item + syntax colors switch with the theme through _retheme().
# ---------------------------------------------------------------------------

from theme_settings import apply_dialog_theme

# Compact toolbar buttons: size only — colors come from the dialog theme.
_BTN_COMPACT = "QPushButton { font-size: 10px; padding: 1px 4px; }"

_HEADER_STYLE = {
    True:  ("font-weight: bold; font-size: 12px; color: #ccc;"
            " padding: 5px 8px; background: #1e2a38; border-bottom: 1px solid #333;"),
    False: ("font-weight: bold; font-size: 12px; color: #1e2a38;"
            " padding: 5px 8px; background: #d6e4f0; border-bottom: 1px solid #b0c4d8;"),
}


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


_FIELD_ROLE = Qt.UserRole + 1   # simple-tree items: the backing <field> element


def _make_field_item(parent_item, field, colors):
    """One field row: shows name/value, carries the backing element, and is
    flagged editable (value column) when the field is a simple scalar."""
    name  = field.get('name') or field.get('hash', '?')
    value = _field_value(field)
    ftype = _field_type(field)
    fi = QTreeWidgetItem(parent_item, [name, value])
    fi.setForeground(0, QColor(colors['name']))
    if _field_is_editable(field):
        fi.setData(0, _FIELD_ROLE, field)
        fi.setFlags(fi.flags() | Qt.ItemIsEditable)
        fi.setForeground(1, QColor(colors['val']))
        tip = f"Type: {ftype} — click to edit (BinHex updates automatically)"
    else:
        fi.setForeground(1, QColor(colors['ro']))
        tip = (f"Type: {ftype} — read-only (structural field)" if ftype
               else "read-only (structural field)")
    fi.setToolTip(1, tip)
    return fi


def _add_elem_to_tree(elem, parent_item, depth=0, colors=None):
    """Recursively add an FCB <object> and its children to a QTreeWidget item."""
    colors = colors or _ITEM_COLORS[True]
    title = elem.get('name') or elem.get('hash', 'object')
    obj_item = QTreeWidgetItem(parent_item, [title, ""])
    obj_item.setExpanded(depth < 2)
    obj_item.setForeground(0, QColor(colors['obj'] if depth == 0 else colors['obj2']))

    for field in elem.findall("field"):
        _make_field_item(obj_item, field, colors)

    if depth < 5:
        for child in elem.findall("object"):
            _add_elem_to_tree(child, obj_item, depth + 1, colors)
    else:
        children = elem.findall("object")
        if children:
            note = QTreeWidgetItem(obj_item, [f"… {len(children)} nested object(s)", ""])
            note.setForeground(0, QColor(colors['dim']))


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
        self._file_path       = None
        self._dirty           = False
        self._backed_up       = False
        self._proto_items     = {}   # id(QTreeWidgetItem) → (proto_elem, entity_elem, proto_name, lib_name, lib_elem)
        self._load_worker     = None
        self._save_worker     = None
        self._filter_matches  = []   # list of visible prototype QTreeWidgetItems
        self._filter_index    = -1   # current position in _filter_matches
        self._suppress_item_changed = False
        self._item_colors     = _ITEM_COLORS[True]   # _retheme() re-picks

        self._setup_ui()
        # Follow the user's Light/Dark preference (also calls _retheme, which
        # sets the header/xml/item colors; retheme_open_windows re-invokes it
        # live when the main window's theme toggles).
        self._dark = True
        apply_dialog_theme(self)

        if file_path and os.path.exists(file_path):
            self._start_load(file_path)

    def _retheme(self, dark):
        """Per-theme styling beyond the shared dialog stylesheet: header bar,
        XML editor font/colors, syntax highlighter, and tree item colors
        (repopulates the visible trees so their foregrounds switch too)."""
        self._dark = bool(dark)
        self._item_colors = _ITEM_COLORS[self._dark]
        self._header.setStyleSheet(_HEADER_STYLE[self._dark])
        if self._dark:
            self._xml_view.setStyleSheet(
                "QPlainTextEdit { background: #1a1a1a; color: #d4d4d4;"
                " border: 1px solid #333; font-family: Consolas, monospace; }")
        else:
            self._xml_view.setStyleSheet(
                "QPlainTextEdit { background: #ffffff; color: #1e1e1e;"
                " border: 1px solid #b0b0b0; font-family: Consolas, monospace; }")
        self._xml_highlighter.set_dark(self._dark)
        # Refresh tree item colors for the current content.
        if self._xml_root is not None:
            self._repaint_left_tree_colors()
        key = getattr(self, '_current_item_key', None)
        if key is not None and key in self._proto_items:
            self._refresh_simple_tab(self._proto_items[key][1])

    def _repaint_left_tree_colors(self):
        for i in range(self._entity_tree.topLevelItemCount()):
            self._entity_tree.topLevelItem(i).setForeground(
                0, QColor(self._item_colors['obj']))

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

        self._save_btn = QPushButton("Save")
        self._save_btn.setFixedWidth(70)
        self._save_btn.setEnabled(False)
        self._save_btn.setToolTip(
            "Write edits back to the loaded .converted.xml (keeps a .bak on the "
            "first save). Reconvert to .fcb via Tools ▸ Convert Entity Library.")
        self._save_btn.clicked.connect(self._save_file)

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
        top.addWidget(self._save_btn)
        top.addWidget(self._file_label, 1)
        top.addWidget(self._progress)
        top.addWidget(self._count_label)
        root.addLayout(top)

        # ── Splitter ─────────────────────────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)

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

        _btn_style = _BTN_COMPACT   # colors come from the dialog theme
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
        self._match_label.setAlignment(Qt.AlignCenter)

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
        self._header.setStyleSheet(_HEADER_STYLE[True])   # _retheme() re-styles
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

        _btn_style = _BTN_COMPACT   # colors come from the dialog theme

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
        self._simple_match_label.setAlignment(Qt.AlignCenter)

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

        # QTreeWidget — virtualised, handles thousands of rows without lag.
        # Editing: NoEditTriggers + programmatic editItem from _on_simple_clicked
        # so ONLY the Value column of editable field rows opens an editor (the
        # default triggers would let the name column be edited too).
        self._simple_tree = QTreeWidget()
        self._simple_tree.setColumnCount(2)
        self._simple_tree.setHeaderLabels(["Field / Component", "Value"])
        self._simple_tree.setUniformRowHeights(True)
        # NO alternating row colors: the striping rendered as alternating
        # dark/light bands that made the field/component text hard to read
        # (user request Aug 2026) — every row keeps the single theme background.
        self._simple_tree.setAlternatingRowColors(False)
        self._simple_tree.setRootIsDecorated(True)
        self._simple_tree.setWordWrap(False)
        self._simple_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._simple_tree.itemClicked.connect(self._on_simple_clicked)
        self._simple_tree.itemChanged.connect(self._on_simple_item_changed)
        header = self._simple_tree.header()
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
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

        _btn_style = _BTN_COMPACT   # colors come from the dialog theme

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
        self._xml_match_label.setAlignment(Qt.AlignCenter)

        copy_btn = QPushButton("Copy XML")
        copy_btn.setFixedWidth(75)
        copy_btn.setStyleSheet(_btn_style)
        copy_btn.clicked.connect(self._copy_xml)

        self._xml_apply_btn = QPushButton("Apply Changes")
        self._xml_apply_btn.setFixedWidth(95)
        self._xml_apply_btn.setStyleSheet(_btn_style)
        self._xml_apply_btn.setToolTip(
            "Parse the edited XML and take it as this prototype's new content.\n"
            "Every simple field's BinHex is regenerated from its value-* "
            "attribute (the friendly value wins).")
        self._xml_apply_btn.setEnabled(False)
        self._xml_apply_btn.clicked.connect(self._apply_xml_changes)

        toolbar.addWidget(self._xml_status)
        toolbar.addStretch()
        toolbar.addWidget(find_lbl)
        toolbar.addWidget(self._xml_find)
        toolbar.addWidget(self._xml_prev)
        toolbar.addWidget(self._xml_next)
        toolbar.addWidget(self._xml_match_label)
        toolbar.addWidget(copy_btn)
        toolbar.addWidget(self._xml_apply_btn)
        layout.addLayout(toolbar)

        # Editable like the entity editor's XML tab; Apply commits + resyncs
        # BinHex. Truncated displays stay read-only (applying a cut-off dump
        # would destroy the prototype).
        self._xml_view = QPlainTextEdit()
        self._xml_view.setFont(QFont("Consolas", 9))
        self._xml_view.setReadOnly(True)
        self._xml_view.setStyleSheet(
            "QPlainTextEdit { background: #1a1a1a; color: #d4d4d4;"
            " border: 1px solid #333; font-family: Consolas, monospace; }")
        self._xml_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._xml_highlighter = _XmlHighlighter(self._xml_view.document())
        layout.addWidget(self._xml_view, 1)
        self._xml_truncated = False

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
        self._xml_view.setReadOnly(True)
        self._xml_apply_btn.setEnabled(False)
        self._current_proto_elem = None
        self._current_item_key = None
        self._dirty = False
        self._backed_up = False
        self._save_btn.setEnabled(False)
        self.setWindowTitle("Entity Library Browser")
        self._header.setText("Loading…")

        self._load_worker = _LoadWorker(file_path)
        self._load_worker.done.connect(lambda root: self._on_loaded(root, file_path))
        self._load_worker.error.connect(self._on_load_error)
        self._load_worker.start()

    def _on_loaded(self, root, file_path):
        self._progress.setVisible(False)
        self._xml_root = root
        self._file_path = file_path
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
            lib_item.setFlags(lib_item.flags() & ~Qt.ItemIsSelectable)
            f = lib_item.font(0); f.setBold(True); lib_item.setFont(0, f)
            lib_item.setForeground(0, QColor(self._item_colors['obj']))

            for proto_elem in lib_elem.findall("object[@name='EntityPrototype']"):
                pf = proto_elem.find("field[@name='Name']")
                proto_name = pf.get('value-String', 'Unknown') if pf is not None else 'Unknown'
                entity_elem = proto_elem.find("object[@name='Entity']")

                proto_item = QTreeWidgetItem(lib_item, [proto_name])
                key = id(proto_item)
                self._proto_items[key] = (proto_elem, entity_elem, proto_name,
                                          lib_name, lib_elem)
                proto_item.setData(0, Qt.UserRole, key)
                total += 1

        self._count_label.setText(f"{total} prototypes")

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_item_clicked(self, item, _col):
        key = item.data(0, Qt.UserRole)
        if key is None or key not in self._proto_items:
            return
        proto_elem, entity_elem, proto_name, lib_name, _lib_elem = self._proto_items[key]
        self._current_proto_elem = proto_elem
        self._current_item_key = key
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
        self._suppress_item_changed = True
        self._simple_tree.setUpdatesEnabled(False)
        self._simple_tree.clear()

        if entity_elem is None:
            self._simple_tree.setUpdatesEnabled(True)
            self._suppress_item_changed = False
            return

        # Properties group — direct <field> children of Entity
        colors = self._item_colors
        direct_fields = entity_elem.findall("field")
        if direct_fields:
            props_item = QTreeWidgetItem(self._simple_tree, ["Properties", ""])
            props_item.setExpanded(True)
            f = props_item.font(0); f.setBold(True); props_item.setFont(0, f)
            props_item.setForeground(0, QColor(colors['ro']))
            for field in direct_fields:
                _make_field_item(props_item, field, colors)

        # Components
        components_elem = entity_elem.find("object[@name='Components']")
        if components_elem is not None:
            for comp in components_elem:
                if comp.tag == 'object':
                    _add_elem_to_tree(comp, self._simple_tree, colors=colors)

        # Other direct child objects
        for child in entity_elem.findall("object"):
            if child.get('name') != 'Components':
                _add_elem_to_tree(child, self._simple_tree, colors=colors)

        self._simple_tree.setUpdatesEnabled(True)
        self._suppress_item_changed = False

    # ------------------------------------------------------------------
    # Simple tab — in-place editing (value column + auto-BinHex)
    # ------------------------------------------------------------------

    def _on_simple_clicked(self, item, col):
        """Open the inline editor on the Value column of editable field rows."""
        try:
            if col == 1 and item.data(0, _FIELD_ROLE) is not None:
                self._simple_tree.editItem(item, 1)
        except Exception:
            import traceback
            traceback.print_exc()

    def _on_simple_item_changed(self, item, col):
        """Commit an inline edit: value-* attribute + regenerated BinHex text.
        Bad input reverts the cell (PyQt5 aborts on escaped slot exceptions,
        so everything is guarded)."""
        if self._suppress_item_changed or col != 1:
            return
        field = item.data(0, _FIELD_ROLE)
        if field is None:
            return
        try:
            shown = _apply_field_edit(field, item.text(1))
            self._suppress_item_changed = True
            item.setText(1, shown)     # normalized display (e.g. bool → True/False)
            self._suppress_item_changed = False
            self._mark_dirty()
            self._xml_view.setPlainText("")   # stale — lazy-regenerated on tab switch
            name = field.get('name') or field.get('hash', '?')
            self._file_label.setText(
                f"{os.path.basename(self._file_path or '')} — {name} = {shown} "
                f"(BinHex {field.text})")
        except ValueError as exc:
            # Revert to the element's current (unchanged) value.
            self._suppress_item_changed = True
            item.setText(1, _field_value(field))
            self._suppress_item_changed = False
            QMessageBox.warning(self, "Edit Field", f"Value rejected:\n{exc}")
        except Exception:
            import traceback
            traceback.print_exc()
            self._suppress_item_changed = False

    def _mark_dirty(self):
        self._dirty = True
        self._save_btn.setEnabled(True)
        title = "Entity Library Browser"
        if self._file_path:
            title += f" — {os.path.basename(self._file_path)}*"
        self.setWindowTitle(title)

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
            self._xml_view.setReadOnly(True)
            self._xml_apply_btn.setEnabled(False)
            return
        try:
            text = ET.tostring(proto_elem, encoding='unicode')
            if len(text) > _XML_DISPLAY_LIMIT:
                self._xml_truncated = True
                shown = text[:_XML_DISPLAY_LIMIT]
                self._xml_view.setPlainText(
                    shown + f"\n\n… truncated — {len(text):,} chars total"
                    " (use Copy XML to get the full content)")
                self._xml_status.setText(
                    f"{len(text):,} chars (showing first {_XML_DISPLAY_LIMIT:,}) — read-only")
                self._xml_view.setReadOnly(True)
                self._xml_apply_btn.setEnabled(False)
            else:
                self._xml_truncated = False
                self._xml_view.setPlainText(text)
                self._xml_status.setText(f"{len(text):,} chars — editable")
                self._xml_view.setReadOnly(False)
                self._xml_apply_btn.setEnabled(True)
        except Exception as exc:
            self._xml_view.setPlainText(f"Error: {exc}")
            self._xml_view.setReadOnly(True)
            self._xml_apply_btn.setEnabled(False)

    def _apply_xml_changes(self):
        """Parse the edited XML, regenerate every simple field's BinHex from its
        value-* attribute, and swap the result in as this prototype's content."""
        try:
            if self._current_proto_elem is None or self._xml_truncated:
                return
            key = getattr(self, '_current_item_key', None)
            if key is None or key not in self._proto_items:
                return
            try:
                new_elem = ET.fromstring(self._xml_view.toPlainText())
            except ET.ParseError as exc:
                QMessageBox.warning(self, "Apply Changes", f"XML does not parse:\n{exc}")
                return

            synced = _resync_binhex(new_elem)

            old_elem, _entity, _name, lib_name, lib_elem = self._proto_items[key]
            children = list(lib_elem)
            if old_elem not in children:
                QMessageBox.warning(self, "Apply Changes",
                                    "Prototype no longer found in its library — reload the file.")
                return
            idx = children.index(old_elem)
            lib_elem.remove(old_elem)
            lib_elem.insert(idx, new_elem)

            pf = new_elem.find("field[@name='Name']")
            proto_name = pf.get('value-String', 'Unknown') if pf is not None else 'Unknown'
            entity_elem = new_elem.find("object[@name='Entity']")
            self._proto_items[key] = (new_elem, entity_elem, proto_name, lib_name, lib_elem)
            self._current_proto_elem = new_elem

            self._header.setText(f"{lib_name}  ›  {proto_name}")
            self._refresh_simple_tab(entity_elem)
            self._refresh_xml_tab(new_elem)   # shows the resynced BinHex
            self._mark_dirty()
            self._file_label.setText(
                f"{os.path.basename(self._file_path or '')} — applied "
                f"({synced} BinHex value(s) regenerated)")
        except Exception as exc:
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "Apply Changes", f"Apply failed:\n{exc}")

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
        from PyQt5.QtGui import QTextDocument
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
    # Saving
    # ------------------------------------------------------------------

    def _save_file(self):
        """Write the edited tree back to the loaded .converted.xml. First save
        keeps a .bak of the original. Runs in a worker thread — entitylibrary
        files can be tens of MB and serialising on the GUI thread would hang
        the app."""
        try:
            if not self._dirty or not self._file_path or self._xml_root is None:
                return
            if self._save_worker and self._save_worker.isRunning():
                return   # a save is already running
            self._save_btn.setEnabled(False)
            self._progress.setVisible(True)
            self._file_label.setText(f"Saving {os.path.basename(self._file_path)}…")
            self._save_worker = _SaveWorker(self._xml_root, self._file_path,
                                            make_backup=not self._backed_up)
            self._save_worker.done.connect(self._on_saved)
            self._save_worker.error.connect(self._on_save_error)
            self._save_worker.start()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self._progress.setVisible(False)
            QMessageBox.warning(self, "Save", f"Save failed to start:\n{exc}")

    def _on_saved(self, backed_up):
        self._progress.setVisible(False)
        self._backed_up = self._backed_up or backed_up
        self._dirty = False
        self.setWindowTitle(f"Entity Library Browser — {os.path.basename(self._file_path)}")
        self._file_label.setText(
            f"{os.path.basename(self._file_path)} — saved"
            + (" (.bak kept)" if backed_up else ""))

    def _on_save_error(self, msg):
        self._progress.setVisible(False)
        self._save_btn.setEnabled(True)
        QMessageBox.warning(self, "Save", f"Save failed:\n{msg}")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        try:
            if self._dirty:
                reply = QMessageBox.question(
                    self, "Unsaved Changes",
                    "This library has unsaved edits.\n\nSave before closing?",
                    QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                    QMessageBox.Save)
                if reply == QMessageBox.Cancel:
                    event.ignore()
                    return
                if reply == QMessageBox.Save:
                    # Synchronous save on close — the dialog is going away, so
                    # there is no event loop left for the worker to report to.
                    try:
                        if not self._backed_up:
                            _make_backup(self._file_path)
                        ET.ElementTree(self._xml_root).write(
                            self._file_path, encoding='utf-8', xml_declaration=True)
                    except Exception as exc:
                        QMessageBox.warning(self, "Save", f"Save failed:\n{exc}")
                        event.ignore()
                        return
        except Exception:
            import traceback
            traceback.print_exc()
        for w in (self._load_worker, self._save_worker):
            if w and w.isRunning():
                w.quit()
                w.wait()
        super().closeEvent(event)
