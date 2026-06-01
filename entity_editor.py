"""
Entity Editor for Avatar Map Editor
Single-pass XML renderer — no duplicate sections, shows all data.
"""

import sys
import os
import math
import struct
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QLabel, QLineEdit, QPushButton, QCheckBox, QScrollArea,
                             QWidget, QFrame, QGroupBox, QMessageBox, QApplication,
                             QSizePolicy, QComboBox, QTabWidget, QPlainTextEdit, QTextEdit,
                             QDoubleSpinBox)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import (QFont, QDoubleValidator, QIntValidator,
                         QRegularExpressionValidator, QTextCharFormat, QColor,
                         QKeySequence, QShortcut, QTextDocument)
from PyQt6.QtCore import QRegularExpression
from ui_style_utils import apply_checkbox_style

# ---------------------------------------------------------------------------
# Import BinHexConvert from tools/ (canonical conversion reference).
# Falls back to inline functions if tools/ isn't importable (frozen build, etc.)
# ---------------------------------------------------------------------------
_tools_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools')
try:
    if _tools_dir not in sys.path:
        sys.path.insert(0, _tools_dir)
    from binhex_convertor import BinHexConvert, BinHexConversions
    _BINHEX_IMPORT_OK = True
except Exception:
    _BINHEX_IMPORT_OK = False

# ============================================================================
# BINHEX CONVERSION METHODS
# ============================================================================

def string_to_binhex(text):
    """Convert a string to BinHex — null-terminated ASCII (matches binhex_convertor.py)."""
    if not text:
        return "00"
    return (text + '\x00').encode('ascii', errors='replace').hex().upper()

def compute_hash32(text):
    """Compute a 32-bit hash for a string (returns integer)"""
    hash_value = 0
    for char in text:
        hash_value = ((hash_value << 5) + hash_value) + ord(char)
        hash_value = hash_value & 0xFFFFFFFF
    return hash_value

def compute_hash32_to_binhex(text):
    """Compute a 32-bit hash for a string and return as BinHex (little-endian)"""
    hash_value = compute_hash32(text)
    return struct.pack('<I', hash_value).hex().upper()

def float_to_binhex(float_val):
    """Convert a float to BinHex (little-endian)"""
    try:
        return struct.pack('<f', float(float_val)).hex().upper()
    except (ValueError, struct.error):
        return "0000803F"  # Default to 1.0

def int64_to_binhex(int_val):
    """Convert a 64-bit integer to BinHex (little-endian)"""
    try:
        return struct.pack('<Q', int(int_val)).hex().upper()
    except (ValueError, struct.error):
        return "0000000000000000"

def int32_to_binhex(int_val):
    """Convert a 32-bit integer to BinHex (little-endian)"""
    try:
        return struct.pack('<i', int(int_val)).hex().upper()
    except (ValueError, struct.error):
        return "00000000"

def uint32_to_binhex(uint_val):
    """Convert an unsigned 32-bit integer to BinHex (little-endian)"""
    try:
        uint_value = int(uint_val)
        if uint_value < 0 or uint_value > 4294967295:
            return "00000000"
        return struct.pack('<I', uint_value).hex().upper()
    except (ValueError, struct.error):
        return "00000000"

def vector3_to_binhex(x, y, z):
    """Convert Vector3 components to BinHex (little-endian floats)"""
    try:
        return struct.pack('<fff', float(x), float(y), float(z)).hex().upper()
    except (ValueError, struct.error):
        return "000000000000000000000000"

def hash32_value_to_binhex(hash_val):
    """Convert a Hash32 integer value to BinHex (little-endian)"""
    try:
        return struct.pack('<I', int(hash_val)).hex().upper()
    except (ValueError, struct.error):
        return "00000000"

def hash64_to_binhex(hash_val):
    """Convert a Hash64 integer to BinHex (little-endian)"""
    try:
        return struct.pack('<Q', int(hash_val)).hex().upper()
    except (ValueError, struct.error):
        return "0000000000000000"

def boolean_to_binhex(bool_val):
    """Convert a boolean to BinHex"""
    if isinstance(bool_val, bool):
        return "01" if bool_val else "00"
    if isinstance(bool_val, str):
        bool_str_lower = bool_val.lower()
        if bool_str_lower in ['true', '1', 'yes']:
            return '01'
        else:
            return '00'
    return "00"

def byte_to_binhex(byte_val):
    """Convert a byte value (0-255) to BinHex"""
    try:
        byte_value = int(byte_val)
        if byte_value < 0 or byte_value > 255:
            return "00"
        return format(byte_value, '02X')
    except (ValueError, struct.error):
        return "00"

def enum_to_binhex(enum_val):
    """Convert an enum integer to BinHex (little-endian 32-bit)"""
    try:
        return struct.pack('<I', int(enum_val)).hex().upper()
    except (ValueError, struct.error):
        return "00000000"

# ============================================================================
# BINHEX DISPATCH — maps data_type strings to BinHexConversions enum
# ============================================================================

_TYPE_TO_BINHEX: dict = {}
if _BINHEX_IMPORT_OK:
    _TYPE_TO_BINHEX = {
        'string':         BinHexConversions.STRING,
        'compute_hash32': BinHexConversions.HASH32,
        'float32':        BinHexConversions.FLOAT,
        'id64':           BinHexConversions.INT64,
        'int32':          BinHexConversions.INT32,
        'vector3':        BinHexConversions.VECTOR3,
        'hash32':         BinHexConversions.HASH32_INT,
        'byte':           BinHexConversions.BYTE,
        'boolean':        BinHexConversions.BOOLEAN,
        'uint32':         BinHexConversions.UINT32,
        'enum':           BinHexConversions.ENUM,
    }


def _to_binhex(data_type: str, value: str) -> str:
    """Convert value → BinHex string.
    Uses BinHexConvert (tools/binhex_convertor.py) when available; falls back
    to inline struct.pack implementations if the import failed.
    """
    if _BINHEX_IMPORT_OK and data_type in _TYPE_TO_BINHEX:
        return BinHexConvert(_TYPE_TO_BINHEX[data_type]).convert(value)
    # --- fallbacks ---
    if data_type == 'string':
        return string_to_binhex(value)
    if data_type == 'compute_hash32':
        return compute_hash32_to_binhex(value)
    if data_type == 'float32':
        return float_to_binhex(value)
    if data_type == 'id64':
        return int64_to_binhex(value)
    if data_type == 'int32':
        return int32_to_binhex(value)
    if data_type == 'vector3':
        parts = list(map(float, value.split(',')))
        while len(parts) < 3:
            parts.append(0.0)
        return vector3_to_binhex(*parts[:3])
    if data_type == 'hash32':
        return hash32_value_to_binhex(value)
    if data_type == 'hash64':
        return struct.pack('<Q', int(value) & 0xFFFFFFFFFFFFFFFF).hex().upper()
    if data_type == 'byte':
        return byte_to_binhex(value)
    if data_type == 'boolean':
        return boolean_to_binhex(value)
    if data_type == 'uint32':
        return uint32_to_binhex(value)
    if data_type == 'enum':
        return enum_to_binhex(value)
    return string_to_binhex(value)


# ============================================================================
# SCALE/HASH32-FLOAT CONVERSION (for hidScale fields)
# ============================================================================

def hash32_to_float(hash32_val):
    """Convert a Hash32 (uint32) to its float representation"""
    try:
        uint32_val = int(hash32_val) if isinstance(hash32_val, str) else hash32_val
        bytes_val = struct.pack('<I', uint32_val)
        return struct.unpack('<f', bytes_val)[0]
    except (ValueError, struct.error):
        return 1.0

def float_to_hash32(float_val):
    """Convert a float to its Hash32 (uint32) representation"""
    try:
        float_val = float(float_val) if isinstance(float_val, str) else float_val
        bytes_val = struct.pack('<f', float_val)
        return struct.unpack('<I', bytes_val)[0]
    except (ValueError, struct.error):
        return 1065353216  # 1.0 as uint32


# ============================================================================
# INPUT WIDGET CLASSES
# ============================================================================

class ScaleInput(QLineEdit):
    """Float input that stores as Hash32 in XML"""
    changed = pyqtSignal()

    def __init__(self, parent, get_value, set_value, min_val=0.0, max_val=100.0):
        super().__init__(parent)
        self.get_value = get_value
        self.set_value = set_value
        self.min_val = min_val
        self.max_val = max_val
        self.setValidator(QDoubleValidator(min_val, max_val, 6, self))
        self.textChanged.connect(self.on_text_changed)

    def update_value(self):
        try:
            hash32_val = self.get_value()
            float_val = hash32_to_float(hash32_val)
            self.blockSignals(True)
            self.setText(f"{float_val:.6f}".rstrip('0').rstrip('.'))
            self.blockSignals(False)
        except Exception:
            self.setText("1.0")

    def on_text_changed(self, text):
        try:
            if text.strip():
                float_val = max(self.min_val, min(self.max_val, float(text)))
                self.set_value(float_to_hash32(float_val))
                self.changed.emit()
        except ValueError:
            pass


class DecimalInput(QLineEdit):
    """Decimal input with mouse drag support"""
    changed = pyqtSignal()

    def __init__(self, parent, get_value, set_value, min_val=-math.inf, max_val=math.inf):
        super().__init__(parent)
        self.get_value = get_value
        self.set_value = set_value
        self.min_val = min_val
        self.max_val = max_val
        self.setValidator(QDoubleValidator(min_val, max_val, 6, self))
        self.textChanged.connect(self.on_text_changed)
        self.drag_start_x = None
        self.drag_start_value = None
        self.scaling_factor = 1.0

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start_x = event.position().x()
            try:
                self.drag_start_value = self.get_value()
            except Exception:
                self.drag_start_value = 0.0
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_start_x is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.position().x() - self.drag_start_x
            scale = 0.01 if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
            new_value = self.drag_start_value + delta * self.scaling_factor * scale
            new_value = max(self.min_val, min(self.max_val, new_value))
            self.setText(f"{new_value:.6f}")
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag_start_x = None
        self.drag_start_value = None
        super().mouseReleaseEvent(event)

    def update_value(self):
        try:
            val = self.get_value()
            self.blockSignals(True)
            if isinstance(val, (int, float)):
                if val != int(val):
                    self.setText(f"{val:.6f}".rstrip('0').rstrip('.'))
                else:
                    self.setText(str(int(val)))
            else:
                self.setText(str(val))
            self.blockSignals(False)
        except Exception:
            self.setText("0")

    def on_text_changed(self, text):
        try:
            if text.strip():
                val = max(self.min_val, min(self.max_val, float(text)))
                self.set_value(val)
                self.changed.emit()
        except ValueError:
            pass


class IntegerInput(QLineEdit):
    """Integer input with validation"""
    changed = pyqtSignal()

    def __init__(self, parent, get_value, set_value, min_val=None, max_val=None):
        super().__init__(parent)
        self.get_value = get_value
        self.set_value = set_value
        self.min_val = min_val
        self.max_val = max_val
        if min_val is not None and max_val is not None:
            # QIntValidator only supports signed 32-bit range; use regex for uint32
            if min_val >= -2147483648 and max_val <= 2147483647:
                self.setValidator(QIntValidator(min_val, max_val, self))
            else:
                self.setValidator(QRegularExpressionValidator(
                    QRegularExpression(r'-?\d{0,20}'), self))
        self.textChanged.connect(self.on_text_changed)

    def update_value(self):
        try:
            self.blockSignals(True)
            self.setText(str(int(self.get_value())))
            self.blockSignals(False)
        except Exception:
            self.setText("0")

    def on_text_changed(self, text):
        try:
            if text.strip():
                val = int(text)
                if self.min_val is not None:
                    val = max(self.min_val, val)
                if self.max_val is not None:
                    val = min(self.max_val, val)
                self.set_value(val)
                self.changed.emit()
        except ValueError:
            pass


class StringInput(QLineEdit):
    """String input field"""
    changed = pyqtSignal()

    def __init__(self, parent, get_value, set_value):
        super().__init__(parent)
        self.get_value = get_value
        self.set_value = set_value
        self.textChanged.connect(self.on_text_changed)

    def update_value(self):
        try:
            val = self.get_value()
            self.blockSignals(True)
            self.setText(str(val) if val is not None else "")
            self.blockSignals(False)
        except Exception:
            self.setText("")

    def on_text_changed(self, text):
        try:
            self.set_value(text)
            self.changed.emit()
        except Exception:
            pass


# ============================================================================
# ENTITY EDITOR WINDOW
# ============================================================================

class EntityEditorWindow(QDialog):
    """Entity editor — single-pass XML renderer, no duplicate sections."""

    def __init__(self, parent, canvas):
        super().__init__(parent)
        self.canvas = canvas
        self.current_entity = None
        self.auto_save_enabled = True
        self.auto_update_enabled = True

        self.auto_save_timer = QTimer()
        self.auto_save_timer.setSingleShot(True)
        self.auto_save_timer.timeout.connect(self.auto_save)

        self.setup_ui()
        self.setup_connections()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def setup_ui(self):
        self.setWindowTitle("Entity Editor")
        self.setMinimumSize(700, 500)
        self.resize(950, 800)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        self._build_header(root)

        # ── Tab widget ──────────────────────────────────────────────────
        self.tab_widget = QTabWidget(self)

        # Tab 0 — Editor (existing scroll area)
        editor_tab = QWidget()
        editor_tab_layout = QVBoxLayout(editor_tab)
        editor_tab_layout.setContentsMargins(0, 0, 0, 0)
        editor_tab_layout.setSpacing(0)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.content_layout.setSpacing(3)
        self.content_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll_area.setWidget(self.content_widget)

        # Search bar — always visible at the top of the Editor tab
        editor_search_row = QWidget(editor_tab)
        esr = QHBoxLayout(editor_search_row)
        esr.setContentsMargins(2, 2, 2, 2)
        esr.setSpacing(4)
        esr_lbl = QLabel("Search:", editor_tab)
        esr_lbl.setStyleSheet("color: #888; font-size: 10px;")
        esr_lbl.setFixedWidth(42)
        self._editor_search = QLineEdit(editor_tab)
        self._editor_search.setPlaceholderText("Filter sections and fields…")
        self._editor_search.setClearButtonEnabled(True)
        self._editor_search.setStyleSheet("font-size: 10px;")
        self._editor_search.textChanged.connect(self._apply_editor_search)
        esr.addWidget(esr_lbl)
        esr.addWidget(self._editor_search)
        editor_tab_layout.addWidget(editor_search_row)
        editor_tab_layout.addWidget(self.scroll_area)
        self.tab_widget.addTab(editor_tab, "Editor")

        # Tab 1 — XML view/edit
        xml_tab = QWidget()
        xml_tab_layout = QVBoxLayout(xml_tab)
        xml_tab_layout.setContentsMargins(4, 4, 4, 4)
        xml_tab_layout.setSpacing(4)

        xml_toolbar = QHBoxLayout()
        self._xml_status_label = QLabel("", self)
        self._xml_status_label.setStyleSheet("color: #888; font-size: 10px;")
        apply_btn = QPushButton("Apply XML", self)
        apply_btn.setFixedWidth(80)
        apply_btn.setToolTip("Parse the XML and apply changes to the entity")
        apply_btn.clicked.connect(self._apply_xml_changes)
        xml_toolbar.addWidget(self._xml_status_label)
        xml_toolbar.addStretch()
        xml_toolbar.addWidget(apply_btn)
        xml_tab_layout.addLayout(xml_toolbar)

        # Find bar — hidden by default, shown with Ctrl+F
        self._xml_find_bar = QWidget(xml_tab)
        xfb = QHBoxLayout(self._xml_find_bar)
        xfb.setContentsMargins(0, 0, 0, 0)
        xfb.setSpacing(4)
        xfb_lbl = QLabel("Find:", self)
        xfb_lbl.setStyleSheet("color: #888; font-size: 10px;")
        xfb_lbl.setFixedWidth(28)
        self._xml_find_input = QLineEdit(self)
        self._xml_find_input.setPlaceholderText("Search XML…")
        self._xml_find_input.setClearButtonEnabled(True)
        self._xml_find_input.setStyleSheet("font-size: 10px;")
        self._xml_find_input.textChanged.connect(self._apply_xml_find)
        self._xml_find_input.returnPressed.connect(lambda: self._xml_find_navigate(forward=True))
        self._xml_find_count = QLabel("", self)
        self._xml_find_count.setStyleSheet("color: #888; font-size: 9px;")
        self._xml_find_count.setFixedWidth(70)
        _prev_btn = QPushButton("▲", self)
        _prev_btn.setFixedSize(22, 22)
        _prev_btn.setToolTip("Previous match (Shift+Enter)")
        _prev_btn.clicked.connect(lambda: self._xml_find_navigate(forward=False))
        _next_btn = QPushButton("▼", self)
        _next_btn.setFixedSize(22, 22)
        _next_btn.setToolTip("Next match (Enter)")
        _next_btn.clicked.connect(lambda: self._xml_find_navigate(forward=True))
        _close_btn = QPushButton("✕", self)
        _close_btn.setFixedSize(22, 22)
        _close_btn.setToolTip("Clear search (Esc)")
        _close_btn.clicked.connect(self._hide_xml_find)
        for btn in (_prev_btn, _next_btn, _close_btn):
            btn.setStyleSheet(
                "QPushButton { background: #2a3a4a; color: #aaa; border: 1px solid #3a4a5a;"
                " border-radius: 3px; font-size: 10px; }"
                "QPushButton:hover { background: #3a4a5a; }"
            )
        xfb.addWidget(xfb_lbl)
        xfb.addWidget(self._xml_find_input)
        xfb.addWidget(self._xml_find_count)
        xfb.addWidget(_prev_btn)
        xfb.addWidget(_next_btn)
        xfb.addWidget(_close_btn)
        xml_tab_layout.addWidget(self._xml_find_bar)

        self.xml_editor = QPlainTextEdit(self)
        self.xml_editor.setFont(QFont("Consolas", 9))
        self.xml_editor.setStyleSheet(
            "QPlainTextEdit { background: #1a1a1a; color: #d4d4d4;"
            " border: 1px solid #333; font-family: Consolas, monospace; }"
        )
        self.xml_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        # Debounce timer — parse XML 1.5 s after the user stops typing
        self._xml_debounce = QTimer()
        self._xml_debounce.setSingleShot(True)
        self._xml_debounce.timeout.connect(self._apply_xml_changes)
        self.xml_editor.textChanged.connect(
            lambda: None if self._xml_tab_refreshing else self._xml_debounce.start(1500)
        )
        self._xml_tab_refreshing = False   # guard against re-entrant refresh
        xml_tab_layout.addWidget(self.xml_editor)
        self.tab_widget.addTab(xml_tab, "XML")

        # Connect AFTER all tabs and attributes are set up so the signal
        # doesn't fire mid-construction before _xml_debounce exists.
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        # Ctrl+F — activate the appropriate search bar for the current tab
        _find_sc = QShortcut(QKeySequence.StandardKey.Find, self)
        _find_sc.activated.connect(self._activate_search)

        root.addWidget(self.tab_widget)

    # ------------------------------------------------------------------
    # Search — Editor tab
    # ------------------------------------------------------------------

    def _activate_search(self):
        """Ctrl+F: focus the search bar for the active tab."""
        if self.tab_widget.currentIndex() == 0:
            self._editor_search.setFocus()
            self._editor_search.selectAll()
        else:
            self._xml_find_input.setFocus()
            self._xml_find_input.selectAll()

    def _apply_editor_search(self, text):
        """Show/hide QGroupBox sections whose title or field labels match *text*."""
        q = text.strip().lower()
        for i in range(self.content_layout.count()):
            item = self.content_layout.itemAt(i)
            if not item:
                continue
            w = item.widget()
            if not w:
                continue
            if not isinstance(w, QGroupBox):
                w.setVisible(True)
                continue
            if not q:
                w.setVisible(True)
                continue
            # Check title
            if q in w.title().lower():
                w.setVisible(True)
                continue
            # Check QLabel texts (field names) and QPushButton texts (archetype add buttons)
            matched = any(
                q in child.text().strip().lower()
                for cls in (QLabel, QPushButton)
                for child in w.findChildren(cls)
                if child.text().strip() and len(child.text().strip()) < 120
            )
            w.setVisible(matched)

    # ------------------------------------------------------------------
    # Search — XML tab
    # ------------------------------------------------------------------

    def _hide_xml_find(self):
        self._xml_find_input.clear()
        self.xml_editor.setExtraSelections([])
        self._xml_find_count.setText("")

    def _apply_xml_find(self, text):
        """Highlight all occurrences of *text* in the XML editor."""
        self.xml_editor.setExtraSelections([])
        self._xml_find_count.setText("")
        if not text:
            return

        fmt = QTextCharFormat()
        fmt.setBackground(QColor(255, 200, 0, 120))
        fmt.setForeground(QColor(0, 0, 0))

        doc = self.xml_editor.document()
        cursor = doc.find(text)
        selections = []
        while not cursor.isNull():
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format = fmt
            selections.append(sel)
            cursor = doc.find(text, cursor)

        self.xml_editor.setExtraSelections(selections)
        n = len(selections)
        self._xml_find_count.setText(f"{n} match{'es' if n != 1 else ''}" if n else "no matches")
        self._xml_find_count.setStyleSheet(
            "color: #888; font-size: 9px;" if n else "color: #c87e7e; font-size: 9px;"
        )

        # Jump to first match
        if selections:
            self.xml_editor.setTextCursor(selections[0].cursor)
            self.xml_editor.ensureCursorVisible()

    def _xml_find_navigate(self, forward=True):
        text = self._xml_find_input.text()
        if not text:
            return
        flag = QTextDocument.FindFlag(0) if forward else QTextDocument.FindFlag.FindBackward
        found = self.xml_editor.find(text, flag)
        if not found:
            # Wrap around
            cur = self.xml_editor.textCursor()
            cur.movePosition(
                cur.MoveOperation.Start if forward else cur.MoveOperation.End
            )
            self.xml_editor.setTextCursor(cur)
            self.xml_editor.find(text, flag)

    def _build_header(self, parent_layout):
        frame = QFrame(self)
        frame.setFrameStyle(QFrame.Shape.StyledPanel)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(8, 6, 8, 6)
        fl.setSpacing(3)

        # Entity name
        self.entity_name_label = QLabel("No entity selected", self)
        f = QFont()
        f.setBold(True)
        f.setPointSize(12)
        self.entity_name_label.setFont(f)
        fl.addWidget(self.entity_name_label)

        # Class + ID
        row2 = QHBoxLayout()
        self.entity_class_label = QLabel("", self)
        self.entity_class_label.setStyleSheet("color: #888;")
        self.entity_id_label = QLabel("", self)
        self.entity_id_label.setStyleSheet("color: #888; font-family: monospace; font-size: 10px;")
        row2.addWidget(self.entity_class_label)
        row2.addStretch()
        row2.addWidget(self.entity_id_label)
        fl.addLayout(row2)

        # Position (live-updating display)
        self.entity_pos_label = QLabel("", self)
        self.entity_pos_label.setStyleSheet("color: #888; font-size: 10px;")
        fl.addWidget(self.entity_pos_label)

        # Controls
        ctrl = QHBoxLayout()
        self.auto_update_checkbox = QCheckBox("Auto-update", self)
        self.auto_update_checkbox.setChecked(True)
        self.auto_update_checkbox.toggled.connect(self.toggle_auto_update)
        apply_checkbox_style(self.auto_update_checkbox)

        self.auto_save_checkbox = QCheckBox("Auto-save", self)
        self.auto_save_checkbox.setChecked(True)
        self.auto_save_checkbox.toggled.connect(self.toggle_auto_save)
        apply_checkbox_style(self.auto_save_checkbox)

        self.refresh_btn = QPushButton("Refresh", self)
        self.refresh_btn.setFixedWidth(70)
        self.refresh_btn.clicked.connect(self.refresh_data)

        self.save_btn = QPushButton("Save", self)
        self.save_btn.setFixedWidth(60)
        self.save_btn.clicked.connect(self.manual_save)

        self.status_label = QLabel("Ready", self)
        self.status_label.setStyleSheet("color: gray; font-size: 10px;")

        ctrl.addWidget(self.auto_update_checkbox)
        ctrl.addWidget(self.auto_save_checkbox)
        ctrl.addStretch()
        ctrl.addWidget(self.status_label)
        ctrl.addWidget(self.refresh_btn)
        ctrl.addWidget(self.save_btn)
        fl.addLayout(ctrl)

        parent_layout.addWidget(frame)

    def _update_header(self, entity):
        if entity is None:
            self.entity_name_label.setText("No entity selected")
            self.entity_class_label.setText("")
            self.entity_id_label.setText("")
            self.entity_pos_label.setText("")
            return

        display_name = entity.name
        if (not display_name or display_name in ("Unnamed", "Unnamed Object")) and hasattr(entity, 'xml_element') and entity.xml_element is not None:
            name_f = entity.xml_element.find("./field[@name='hidName']")
            if name_f is not None:
                display_name = (name_f.get('value-String') or name_f.get('strVal') or "").strip()
            if not display_name:
                ct_f = entity.xml_element.find("./field[@name='tplCreatureType']")
                if ct_f is not None:
                    display_name = (ct_f.get('value-String') or ct_f.get('strVal') or "").strip()
            if not display_name:
                display_name = "Unnamed"
        self.entity_name_label.setText(display_name)

        cls_text = ""
        id_text = ""
        if hasattr(entity, 'xml_element') and entity.xml_element is not None:
            cls_f = entity.xml_element.find(".//field[@name='text_hidEntityClass']")
            if cls_f is not None:
                cls_text = cls_f.get('value-String') or cls_f.get('strVal') or ''
            id_f = entity.xml_element.find(".//field[@name='disEntityId']")
            if id_f is not None:
                id_text = f"ID: {id_f.get('value-Id64', '')}"

        self.entity_class_label.setText(f"Class: {cls_text}" if cls_text else "")
        self.entity_id_label.setText(id_text)
        self.entity_pos_label.setText(
            f"Pos:  X {entity.x:.3f}   Y {entity.y:.3f}   Z {entity.z:.3f}"
        )

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        # Esc: clear the XML find bar
        if key == Qt.Key.Key_Escape:
            if hasattr(self, '_xml_find_input') and self._xml_find_input.text():
                self._hide_xml_find()
                return
        # Shift+Enter inside the XML find bar: navigate backward
        if (key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and mods & Qt.KeyboardModifier.ShiftModifier
                and hasattr(self, '_xml_find_bar') and self._xml_find_bar.isVisible()):
            self._xml_find_navigate(forward=False)
            return
        super().keyPressEvent(event)

    def setup_connections(self):
        if hasattr(self.canvas, 'entitySelected'):
            self.canvas.entitySelected.connect(self.on_entity_selected)

    # ------------------------------------------------------------------
    # Entity management
    # ------------------------------------------------------------------

    def toggle_auto_update(self, enabled):
        self.auto_update_enabled = enabled

    def toggle_auto_save(self, enabled):
        self.auto_save_enabled = enabled

    def on_entity_selected(self, entity):
        if self.auto_update_enabled and entity != self.current_entity:
            self.set_entity(entity)

    def set_entity(self, entity):
        if entity == self.current_entity:
            return
        if self.current_entity and self.auto_save_enabled:
            self.auto_save()
        self.current_entity = entity
        self.populate_all_views()

    def clear_all_views(self):
        self._update_header(None)
        self._clear_content()

    def _clear_content(self):
        for i in reversed(range(self.content_layout.count())):
            w = self.content_layout.itemAt(i).widget()
            if w:
                w.setParent(None)

    # ------------------------------------------------------------------
    # Content building — single pass, no duplicates
    # ------------------------------------------------------------------

    def populate_all_views(self):
        # If the XML tab is currently showing, refresh it and bail — the editor
        # tab will re-populate when the user switches back to it.
        if hasattr(self, 'tab_widget') and self.tab_widget.currentIndex() == 1:
            self._update_header(self.current_entity)
            self._refresh_xml_tab()
            return

        self._clear_content()
        entity = self.current_entity
        self._update_header(entity)

        if entity is None:
            return

        # Editable position widget (entity.x / y / z)
        self._add_position_group(entity)

        if not hasattr(entity, 'xml_element') or entity.xml_element is None:
            return

        # "Add Rotation" button — only shown when hidAngles is absent
        if entity.xml_element.find(".//field[@name='hidAngles']") is None:
            btn = QPushButton("+ Add Rotation", self)
            btn.setToolTip("Insert a hidAngles field (0, -0, 0) after hidPos")
            btn.clicked.connect(self.add_rotation_field)
            self.content_layout.addWidget(btn)

        xml = entity.xml_element
        direct_fields = xml.findall("field")
        direct_objects = xml.findall("object")

        # Find sel*/enum* companions at the entity root level
        sel_enum_map, hidden_obj_names = self._find_sel_enum_companions(
            direct_fields, direct_objects
        )

        # Entity-level properties
        if direct_fields:
            self._add_fields_group("Properties", direct_fields, sel_enum_map)

        # Each component inside <object name="Components">
        # Pass components_elem as list_parent so every component gets a × Remove button.
        components_elem = xml.find("object[@name='Components']")
        if components_elem is not None:
            for comp in components_elem:
                if comp.tag == 'object':
                    try:
                        self._render_object_as_group(self.content_layout, comp,
                                                     list_parent=components_elem)
                    except Exception as _e:
                        print(f"[EntityEditor] failed to render component "
                              f"{comp.get('name','?')}: {_e}")

        # Other direct <object> children — skip Components and enum companions
        for child in direct_objects:
            child_name = child.get('name', '')
            if child_name != 'Components' and child_name not in hidden_obj_names:
                try:
                    self._render_object_as_group(self.content_layout, child)
                except Exception as _e:
                    print(f"[EntityEditor] failed to render object "
                          f"{child_name}: {_e}")

        # "Add from archetype" panel — shows components in the archetype missing from entity
        try:
            self._add_archetype_components_panel(self.content_layout, entity)
        except Exception as _e:
            print(f"[EntityEditor] archetype components panel failed: {_e}")

        self.status_label.setText(f"Loaded: {entity.name}")
        # Re-apply the editor search filter after a full rebuild
        if hasattr(self, '_editor_search'):
            self._apply_editor_search(self._editor_search.text())

    def _load_archetype_root(self):
        """Parse and return the root XML element for this entity's archetype file, or None.

        Lookup strategy (in order):
        1. hidName field  — strip trailing _NN, then try each dot-separated suffix
           shortest-first so 'Avatar_SE.00_SCRIPTED.Samson_Scripted_01' resolves to
           '00_SCRIPTED.Samson_Scripted_1.xml' before trying 'Samson_Scripted_1.xml'.
        2. tplCreatureType field — same suffix-stripping logic, as a fallback.

        For each candidate name the search order is:
          a. Exact filename in entities/
          b. Glob  *<name>_1.xml  (handles prefix like 00_SCRIPTED_ACHETYPES.)
        """
        import re, os, glob, xml.etree.ElementTree as ET

        def _find_in_entities(name, entities_dir):
            """Strip trailing _N, then try dot-suffix variants. Returns path or None."""
            base = re.sub(r'_\d+$', '', name.strip())
            if not base:
                return None
            parts = base.split('.')
            # Try suffixes from longest (full) down to shortest (last segment)
            for i in range(len(parts)):
                suffix = '.'.join(parts[i:])
                filename = suffix + '_1.xml'
                exact = os.path.join(entities_dir, filename)
                if os.path.exists(exact):
                    return exact
                matches = glob.glob(os.path.join(entities_dir, '*' + filename))
                if matches:
                    return matches[0]
            return None

        try:
            xml_elem = getattr(self.current_entity, 'xml_element', None)
            if xml_elem is None:
                return None

            entities_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'entities')

            # 1. Try hidName
            hid_field = xml_elem.find(".//field[@name='hidName']")
            if hid_field is not None:
                hid_name = hid_field.get('value-String', '').strip()
                if hid_name:
                    path = _find_in_entities(hid_name, entities_dir)
                    if path:
                        return ET.parse(path).getroot()

            # 2. Fall back to tplCreatureType
            ct_field = xml_elem.find(".//field[@name='tplCreatureType']")
            if ct_field is not None:
                ct_val = (ct_field.get('value-String') or ct_field.get('strVal') or '').strip()
                if ct_val:
                    path = _find_in_entities(ct_val, entities_dir)
                    if path:
                        return ET.parse(path).getroot()

            return None
        except Exception:
            return None

    def _get_archetype_seat_bones(self):
        """Return list of seat-bone name strings from the entity's archetype file, or []."""
        try:
            root = self._load_archetype_root()
            if root is None:
                return []
            initial_users = root.find(".//object[@name='InitialUsers']")
            if initial_users is None:
                return []
            names = []
            for entry in initial_users.findall('object'):
                tbf = entry.find("field[@name='text_SeatBone']")
                names.append(tbf.get('value-String', '') if tbf is not None else '')
            return names
        except Exception:
            return []

    def _add_archetype_components_panel(self, parent_layout, entity):
        """Show 'Add from archetype' buttons for components present in the archetype
        but missing from the entity's current Components section.
        """
        import copy, xml.etree.ElementTree as ET

        arch_root = self._load_archetype_root()
        if arch_root is None:
            return

        arch_components = arch_root.find(".//object[@name='Components']")
        if arch_components is None:
            # Archetype root itself may be the components container
            arch_components = arch_root

        entity_components = entity.xml_element.find("object[@name='Components']")

        # Build set of component names already in the entity
        existing_names = set()
        if entity_components is not None:
            for comp in entity_components:
                n = comp.get('name', '')
                if n:
                    existing_names.add(n)

        # Find components in archetype that are missing from entity
        missing = []
        for arch_comp in arch_components:
            n = arch_comp.get('name', '')
            if n and n not in existing_names:
                missing.append(arch_comp)

        if not missing:
            return

        group = QGroupBox("Add from archetype", self)
        group.setStyleSheet(
            "QGroupBox { font-size: 10px; color: #8ab4d4; border: 1px solid #2a4a6a;"
            " border-radius: 4px; margin-top: 6px; padding: 6px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 6px; }"
        )
        vl = QVBoxLayout(group)
        vl.setContentsMargins(6, 10, 6, 6)
        vl.setSpacing(4)

        info = QLabel("These components exist in the archetype but not in this entity:", self)
        info.setStyleSheet("color: #888; font-size: 9px;")
        info.setWordWrap(True)
        vl.addWidget(info)

        def _make_add(arch_elem):
            def _add(_checked=False, ae=arch_elem):
                nonlocal entity_components
                if entity_components is None:
                    # Create the Components container
                    entity_components = ET.SubElement(entity.xml_element, 'object')
                    entity_components.set('hash', 'A115F62D')
                    entity_components.set('name', 'Components')
                    entity_components.text = '\n        '
                    entity_components.tail = '\n      '

                new_elem = self._xml_deepcopy(ae)
                # Adopt indentation from existing siblings if possible
                siblings = list(entity_components)
                if siblings:
                    new_elem.tail = siblings[-1].tail
                    siblings[-1].tail = entity_components.text or '\n        '
                else:
                    new_elem.tail = '\n      '
                entity_components.append(new_elem)
                self.schedule_auto_save()
                self.populate_all_views()
            return _add

        for arch_comp in missing:
            comp_name = arch_comp.get('name', arch_comp.get('hash', '?'))
            btn = QPushButton(f"+ Add  {comp_name}", self)
            btn.setStyleSheet(
                "QPushButton { background: #1e2e3e; color: #8ab4d4; border: 1px solid #2a4a6a;"
                " border-radius: 3px; padding: 3px 10px; font-size: 10px; text-align: left; }"
                "QPushButton:hover { background: #2a3e52; }"
            )
            btn.setFixedHeight(24)
            btn.clicked.connect(_make_add(arch_comp))
            vl.addWidget(btn)

        parent_layout.addWidget(group)

    def _add_archetype_subobjects_panel(self, parent_layout, entity_elem):
        """Show 'Add' buttons for everything in the matching archetype element that is
        missing from entity_elem — fields, child objects, and recursively into child
        objects that exist in both but have missing content.
        """
        import copy

        comp_name = entity_elem.get('name', '')
        if not comp_name:
            return

        arch_root = self._load_archetype_root()
        if arch_root is None:
            return

        arch_elem = arch_root.find(f".//object[@name='{comp_name}']")
        if arch_elem is None:
            return

        _SKIP_OBJECTS = {'InitialUsers'}

        def _append_child(parent_entity_elem, new_child):
            new_elem = self._xml_deepcopy(new_child)
            siblings = list(parent_entity_elem)
            if siblings:
                new_elem.tail = siblings[-1].tail
                siblings[-1].tail = parent_entity_elem.text or '\n          '
            else:
                new_elem.tail = parent_entity_elem.tail or '\n        '
            parent_entity_elem.append(new_elem)
            self.schedule_auto_save()
            self.populate_all_views()

        def _build_diff_panel(parent_layout, ent_elem, arch_e, indent=0):
            """Render missing fields + objects from arch_e not in ent_elem.
            Recurses into child objects that exist in both but have missing content.
            Returns True if anything was added to parent_layout.
            """
            added_anything = False

            # ── Missing direct fields ────────────────────────────────────────
            existing_field_names = {
                f.get('name', '') for f in ent_elem.findall('field') if f.get('name')
            }
            missing_fields = [
                f for f in arch_e.findall('field')
                if f.get('name') and f.get('name') not in existing_field_names
            ]
            for af in missing_fields:
                fname = af.get('name', af.get('hash', '?'))
                fval = (af.get('value-String') or af.get('value-Int32') or
                        af.get('value-Float32') or af.get('value-Boolean') or
                        af.get('value-Vector3') or '')
                label = f"+ field: {fname}" + (f"  =  {fval}" if fval else "")
                btn = QPushButton(label, self)
                btn.setStyleSheet(
                    "QPushButton { background: #1e2a1e; color: #7ec87e; border: 1px solid #2a4a2a;"
                    " border-radius: 3px; padding: 2px 8px; font-size: 9px; text-align: left; }"
                    "QPushButton:hover { background: #283828; }"
                )
                btn.setFixedHeight(22)
                btn.clicked.connect(
                    (lambda ee=ent_elem, af=af: lambda _=False: _append_child(ee, af))()
                )
                parent_layout.addWidget(btn)
                added_anything = True

            # ── Missing direct child objects ─────────────────────────────────
            existing_obj_names = {
                c.get('name', '') for c in ent_elem if c.tag == 'object' and c.get('name')
            }
            missing_objs = [
                c for c in arch_e
                if c.tag == 'object'
                and c.get('name')
                and c.get('name') not in existing_obj_names
                and c.get('name') not in _SKIP_OBJECTS
            ]
            for ao in missing_objs:
                oname = ao.get('name', ao.get('hash', '?'))
                btn = QPushButton(f"+ object: {oname}", self)
                btn.setStyleSheet(
                    "QPushButton { background: #1a2a3a; color: #7aaac8; border: 1px solid #253a50;"
                    " border-radius: 3px; padding: 2px 8px; font-size: 9px; text-align: left; }"
                    "QPushButton:hover { background: #243448; }"
                )
                btn.setFixedHeight(22)
                btn.clicked.connect(
                    (lambda ee=ent_elem, ao=ao: lambda _=False: _append_child(ee, ao))()
                )
                parent_layout.addWidget(btn)
                added_anything = True

            # ── Recurse into child objects present in both ───────────────────
            for ent_child in ent_elem:
                if ent_child.tag != 'object':
                    continue
                child_name = ent_child.get('name', '')
                if not child_name or child_name in _SKIP_OBJECTS:
                    continue
                arch_child = arch_e.find(f"object[@name='{child_name}']")
                if arch_child is None:
                    continue
                # Build sub-panel only if there's something missing inside
                sub_w = QWidget(self)
                sub_vl = QVBoxLayout(sub_w)
                sub_vl.setContentsMargins(0, 0, 0, 0)
                sub_vl.setSpacing(2)
                if _build_diff_panel(sub_vl, ent_child, arch_child, indent + 1):
                    lbl = QLabel(f"  ↳ {child_name}:", self)
                    lbl.setStyleSheet("color: #666; font-size: 8px;")
                    parent_layout.addWidget(lbl)
                    parent_layout.addWidget(sub_w)
                    added_anything = True
                else:
                    sub_w.deleteLater()

            return added_anything

        # Build the panel — only show the group box if there's anything to add
        probe_w = QWidget(self)
        probe_vl = QVBoxLayout(probe_w)
        probe_vl.setContentsMargins(0, 0, 0, 0)
        probe_vl.setSpacing(3)

        if not _build_diff_panel(probe_vl, entity_elem, arch_elem):
            probe_w.deleteLater()
            return

        group = QGroupBox(f"Add to {comp_name} from archetype", self)
        group.setStyleSheet(
            "QGroupBox { font-size: 9px; color: #8ab4d4; border: 1px dashed #2a4a6a;"
            " border-radius: 3px; margin-top: 4px; padding: 4px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 6px; }"
        )
        vl = QVBoxLayout(group)
        vl.setContentsMargins(6, 12, 6, 4)
        vl.setSpacing(3)
        vl.addWidget(probe_w)
        parent_layout.addWidget(group)

    def _render_initial_users(self, parent_layout, armed_vehicle):
        """Render the InitialUsers section — hidSize, per-seat SeatBone + entUser, Add/Remove.
        Called from _render_object_as_group when processing CArmedVehicle or CVehicle.
        """
        import xml.etree.ElementTree as ET

        container = armed_vehicle.find("object[@name='InitialUsers']")

        # ── Auto-populate seats to hidSize if entries are missing ─────────────
        if container is not None:
            _size_f = container.find("field[@name='hidSize']")
            if _size_f is not None:
                try:
                    _max = int(_size_f.get('value-Int32', '0'))
                except (ValueError, TypeError):
                    _max = 0
                _existing = container.findall('object')
                _missing = _max - len(_existing)
                if _missing > 0:
                    _archetype_seats = self._get_archetype_seat_bones()
                    _entry_indent = container.text or '\n            '
                    _all_c = list(container)
                    _pre_close = _all_c[-1].tail if _all_c else _entry_indent
                    for _k in range(_missing):
                        _idx = len(_existing) + _k
                        if _idx < len(_archetype_seats) and _archetype_seats[_idx]:
                            _seat_name = _archetype_seats[_idx]
                        elif _idx == 0:
                            _seat_name = 'Pilot_SitPoint_01'
                        else:
                            _seat_name = f'SITPOINT{_idx:02d}'
                        if _all_c:
                            _all_c[-1].tail = _entry_indent
                        _e = ET.SubElement(container, 'object')
                        _e.set('hash', 'F11D51B2')
                        _e.tail = _pre_close
                        _fi = _entry_indent + '  '
                        _e.text = _fi
                        _tb = ET.SubElement(_e, 'field')
                        _tb.set('hash', 'AA8D91B9')
                        _tb.set('name', 'text_SeatBone')
                        _tb.set('value-String', _seat_name)
                        _tb.set('type', 'BinHex')
                        _tb.text = string_to_binhex(_seat_name)
                        _tb.tail = _fi
                        _sb = ET.SubElement(_e, 'field')
                        _sb.set('hash', '1CCF1DAB')
                        _sb.set('name', 'SeatBone')
                        _sb.set('value-ComputeHash32', _seat_name)
                        _sb.set('type', 'BinHex')
                        _sb.text = compute_hash32_to_binhex(_seat_name)
                        _sb.tail = _fi
                        _uf = ET.SubElement(_e, 'field')
                        _uf.set('hash', '76AB3272')
                        _uf.set('name', 'entUser')
                        _uf.set('type', 'BinHex')
                        _uf.text = 'FFFFFFFFFFFFFFFF'
                        _uf.tail = _entry_indent
                        _all_c.append(_e)

        group = QGroupBox("Initial Users (Pilots / Drivers)", self)
        vl = QVBoxLayout(group)
        vl.setContentsMargins(8, 6, 8, 6)
        vl.setSpacing(4)

        def _rebuild():
            self.schedule_auto_save()
            self.populate_all_views()

        # ── hidSize row ──────────────────────────────────────────────────────
        if container is not None:
            size_field = container.find("field[@name='hidSize']")
            if size_field is not None:
                size_row = QWidget(self)
                sr = QHBoxLayout(size_row)
                sr.setContentsMargins(0, 0, 0, 4)
                sr.setSpacing(6)
                sr.addWidget(QLabel("Max Seats (hidSize):", self))
                current_size = size_field.get('value-Int32', '0')
                size_inp = QLineEdit(current_size, self)
                size_inp.setFixedWidth(60)
                size_inp.setValidator(QIntValidator(0, 255, self))
                def _on_size_changed(text, sf=size_field):
                    try:
                        val = int(text) if text.strip() else 0
                        sf.set('value-Int32', str(val))
                        sf.text = struct.pack('<i', val).hex().upper()
                        self.schedule_auto_save()
                    except (ValueError, struct.error):
                        pass
                size_inp.textChanged.connect(_on_size_changed)
                sr.addWidget(size_inp)
                sr.addStretch()
                vl.addWidget(size_row)

                sep = QFrame(self)
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setStyleSheet("color: #444;")
                vl.addWidget(sep)

        def _get_max_seats():
            if container is None:
                return None
            sf = container.find("field[@name='hidSize']")
            if sf is None:
                return None
            try:
                return int(sf.get('value-Int32', '0'))
            except (ValueError, TypeError):
                return None

        def _update_add_btn():
            max_s = _get_max_seats()
            if max_s is None:
                add_btn.setEnabled(True)
                add_btn.setToolTip("")
                return
            current = len(container.findall('object')) if container is not None else 0
            if current >= max_s:
                add_btn.setEnabled(False)
                add_btn.setToolTip(f"Max seats ({max_s}) reached — increase hidSize to add more")
            else:
                add_btn.setEnabled(True)
                add_btn.setToolTip(f"{current}/{max_s} seats used")

        def _add_user():
            nonlocal container, armed_vehicle
            if armed_vehicle is None:
                return

            # Enforce hidSize cap
            max_s = _get_max_seats()
            if max_s is not None and container is not None:
                current = len(container.findall('object'))
                if current >= max_s:
                    return

            if container is None:
                av_children = list(armed_vehicle)
                inter = armed_vehicle.text or '\n          '
                pre_close = av_children[-1].tail if av_children else inter
                if av_children:
                    av_children[-1].tail = inter
                container = ET.SubElement(armed_vehicle, 'object')
                container.set('hash', 'DA330543')
                container.set('name', 'InitialUsers')
                container.text = inter + '  '
                container.tail = pre_close

                # Add hidSize field when creating a fresh container
                size_f = ET.SubElement(container, 'field')
                size_f.set('hash', '10CA06AB')
                size_f.set('name', 'hidSize')
                size_f.set('value-Int32', '1')
                size_f.set('type', 'BinHex')
                size_f.text = '01000000'
                size_f.tail = container.text

            # Update hidSize to match new count
            size_field = container.find("field[@name='hidSize']")

            # --- add one seat entry ---
            c_children = [c for c in container if c.tag == 'object']
            entry_indent = container.text or '\n            '
            all_c = list(container)
            pre_close_c = all_c[-1].tail if all_c else entry_indent
            if all_c:
                all_c[-1].tail = entry_indent

            # Pick a seat name for the new entry — prefer archetype data
            seat_idx = len(c_children)
            archetype_seats = self._get_archetype_seat_bones()
            if seat_idx < len(archetype_seats) and archetype_seats[seat_idx]:
                seat_name = archetype_seats[seat_idx]
            elif seat_idx == 0:
                seat_name = 'Pilot_SitPoint_01'
            else:
                seat_name = f'SITPOINT{seat_idx:02d}'
            entry_hash = 'F11D51B2'

            entry = ET.SubElement(container, 'object')
            entry.set('hash', entry_hash)
            entry.tail = pre_close_c
            field_indent = entry_indent + '  '
            entry.text = field_indent

            text_bone_f = ET.SubElement(entry, 'field')
            text_bone_f.set('hash', 'AA8D91B9')
            text_bone_f.set('name', 'text_SeatBone')
            text_bone_f.set('value-String', seat_name)
            text_bone_f.set('type', 'BinHex')
            text_bone_f.text = string_to_binhex(seat_name)
            text_bone_f.tail = field_indent

            bone_f = ET.SubElement(entry, 'field')
            bone_f.set('hash', '1CCF1DAB')
            bone_f.set('name', 'SeatBone')
            bone_f.set('value-ComputeHash32', seat_name)
            bone_f.set('type', 'BinHex')
            bone_f.text = compute_hash32_to_binhex(seat_name)
            bone_f.tail = field_indent

            ent_f = ET.SubElement(entry, 'field')
            ent_f.set('hash', '76AB3272')
            ent_f.set('name', 'entUser')
            ent_f.set('type', 'BinHex')
            ent_f.text = 'FFFFFFFFFFFFFFFF'
            ent_f.tail = entry_indent

            # Sync hidSize to total seat count
            if size_field is not None:
                new_count = len([c for c in container if c.tag == 'object'])
                size_field.set('value-Int32', str(new_count))
                size_field.text = struct.pack('<i', new_count).hex().upper()

            _rebuild()

        # ── Per-seat rows ────────────────────────────────────────────────────
        if container is not None:
            entries = container.findall('object')
            for i, entry in enumerate(entries):
                text_bone_field = entry.find("field[@name='text_SeatBone']")
                bone_field      = entry.find("field[@name='SeatBone']")
                ent_field       = entry.find("field[@name='entUser']")

                # Repair: FCBConverter may type SeatBone as value-Float32 because
                # it can't tell the difference from a 4-byte hash.  Fix it here
                # in-memory so saves write the correct attribute.
                if bone_field is not None and bone_field.get('value-ComputeHash32') is None:
                    seat_name = (text_bone_field.get('value-String', '')
                                 if text_bone_field is not None else '')
                    if not seat_name:
                        seat_name = bone_field.get('value-Float32', '') or ''
                    # Remove all stale value-* attrs; replace with value-ComputeHash32
                    for _attr in [a for a in bone_field.attrib if a.startswith('value-')]:
                        del bone_field.attrib[_attr]
                    bone_field.set('value-ComputeHash32', seat_name)
                    bone_field.text = compute_hash32_to_binhex(seat_name) if seat_name else '00000000'

                seat_label = (text_bone_field.get('value-String', f'Seat {i+1}')
                              if text_bone_field is not None else f'Seat {i+1}')

                seat_frame = QGroupBox(f"Seat {i+1}: {seat_label}", self)
                seat_frame.setStyleSheet(
                    "QGroupBox { font-size: 9px; color: #aaa; border: 1px solid #3a3a3a;"
                    " border-radius: 3px; margin-top: 4px; padding: 4px; }"
                    "QGroupBox::title { subcontrol-origin: margin; left: 6px; }"
                )
                sf_vl = QVBoxLayout(seat_frame)
                sf_vl.setContentsMargins(6, 10, 6, 4)
                sf_vl.setSpacing(3)

                # text_SeatBone row
                bone_row = QWidget(self)
                bone_hl = QHBoxLayout(bone_row)
                bone_hl.setContentsMargins(0, 0, 0, 0)
                bone_hl.setSpacing(6)
                bone_hl.addWidget(QLabel("SeatBone:", self))
                bone_txt = QLineEdit(
                    text_bone_field.get('value-String', '') if text_bone_field is not None else '',
                    self)
                bone_txt.setPlaceholderText("e.g. Pilot_SitPoint_01")

                def _on_bone_name(text, tbf=text_bone_field, bf=bone_field, sf=seat_frame, idx=i):
                    if tbf is not None:
                        tbf.set('value-String', text)
                        tbf.text = string_to_binhex(text)
                    if bf is not None:
                        bf.set('value-ComputeHash32', text)
                        bf.text = compute_hash32_to_binhex(text)
                    sf.setTitle(f"Seat {idx+1}: {text}")
                    self.schedule_auto_save()

                bone_txt.textChanged.connect(_on_bone_name)
                bone_hl.addWidget(bone_txt, 1)
                sf_vl.addWidget(bone_row)

                # entUser row
                user_row = QWidget(self)
                user_hl = QHBoxLayout(user_row)
                user_hl.setContentsMargins(0, 0, 0, 0)
                user_hl.setSpacing(6)
                user_hl.addWidget(QLabel("entUser (Id64):", self))

                raw_val = ent_field.get('value-Id64', '') if ent_field is not None else ''
                # FFFFFFFFFFFFFFFF means "no user" — show as blank / 0
                if not raw_val or raw_val.upper() == 'FFFFFFFFFFFFFFFF':
                    raw_val = ''
                id_inp = QLineEdit(raw_val, self)
                id_inp.setPlaceholderText("Entity ID (blank = none)")

                def _on_id_changed(text, f=ent_field):
                    if f is None:
                        return
                    try:
                        if text.strip():
                            val = int(text)
                            f.set('value-Id64', str(val))
                            f.text = struct.pack('<Q', val & 0xFFFFFFFFFFFFFFFF).hex().upper()
                        else:
                            f.attrib.pop('value-Id64', None)
                            f.text = 'FFFFFFFFFFFFFFFF'
                        self.schedule_auto_save()
                    except (ValueError, struct.error):
                        pass

                id_inp.textChanged.connect(_on_id_changed)
                user_hl.addWidget(id_inp, 1)

                rm_btn = QPushButton("× Remove Seat", self)
                rm_btn.setStyleSheet(
                    "QPushButton { background: #3a2020; color: #c87e7e;"
                    " border: 1px solid #5a3030; border-radius: 3px;"
                    " padding: 2px 8px; font-size: 9px; }"
                    "QPushButton:hover { background: #4a2525; }"
                )
                rm_btn.setFixedHeight(20)

                def _remove_entry(_checked=False, c=container, e=entry, av=armed_vehicle):
                    siblings = list(c)
                    idx = siblings.index(e)
                    was_last = (idx == len(siblings) - 1)
                    c.remove(e)
                    remaining = list(c)
                    if was_last and remaining:
                        remaining[-1].tail = e.tail
                    if not remaining and av is not None:
                        av_siblings = list(av)
                        c_idx = av_siblings.index(c)
                        was_last_av = (c_idx == len(av_siblings) - 1)
                        av.remove(c)
                        av_remaining = list(av)
                        if was_last_av and av_remaining:
                            av_remaining[-1].tail = c.tail
                    else:
                        # Sync hidSize
                        sf2 = c.find("field[@name='hidSize']")
                        if sf2 is not None:
                            new_count = len([ch for ch in c if ch.tag == 'object'])
                            sf2.set('value-Int32', str(new_count))
                            sf2.text = struct.pack('<i', new_count).hex().upper()
                    _rebuild()

                rm_btn.clicked.connect(_remove_entry)
                user_hl.addWidget(rm_btn)
                sf_vl.addWidget(user_row)

                vl.addWidget(seat_frame)

        add_btn = QPushButton("+ Add Seat", self)
        add_btn.setStyleSheet(
            "QPushButton { background: #2a3a2a; color: #7ec87e; border: 1px solid #3a5a3a;"
            " border-radius: 3px; padding: 3px 10px; font-size: 10px; }"
            "QPushButton:hover { background: #3a4a3a; }"
            "QPushButton:disabled { background: #2a2a2a; color: #555; border-color: #333; }"
        )
        add_btn.setFixedHeight(24)
        add_btn.clicked.connect(_add_user)
        vl.addWidget(add_btn)
        _update_add_btn()

        parent_layout.addWidget(group)

    def _render_skin_component(self, parent_layout, skin_elem):
        """Render the MaterialOverrides section of CAvatarSkinComponent with editable XBM paths."""
        import xml.etree.ElementTree as ET

        mat_overrides = skin_elem.find("object[@name='MaterialOverrides']")

        group = QGroupBox("Material Overrides", self)
        group.setStyleSheet(
            "QGroupBox { font-size: 10px; color: #c8d4e4; border: 1px solid #3a4a5a;"
            " border-radius: 4px; margin-top: 6px; padding: 6px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 6px; }"
        )
        vl = QVBoxLayout(group)
        vl.setContentsMargins(8, 6, 8, 6)
        vl.setSpacing(4)

        def _rebuild():
            self.schedule_auto_save()
            self.populate_all_views()

        if mat_overrides is not None:
            materials = mat_overrides.findall("object[@name='Material']")
            for i, mat in enumerate(materials):
                f_orig_str  = mat.find("field[@hash='DD2929AC']")
                f_orig_hash = mat.find("field[@hash='E1C0931D']")
                f_over_str  = mat.find("field[@hash='148E2F84']")
                f_over_hash = mat.find("field[@hash='28679535']")

                slot_frame = QFrame(self)
                slot_frame.setFrameShape(QFrame.Shape.StyledPanel)
                slot_frame.setStyleSheet("QFrame { border: 1px solid #3a4a5a; border-radius: 3px; }")
                sf_vl = QVBoxLayout(slot_frame)
                sf_vl.setContentsMargins(6, 4, 6, 4)
                sf_vl.setSpacing(3)

                slot_lbl = QLabel(f"Slot {i}", self)
                slot_lbl.setStyleSheet("color: #8ab4d4; font-size: 9px; font-weight: bold;")
                sf_vl.addWidget(slot_lbl)

                def _make_path_row(row_label, fs, fh):
                    row = QWidget(self)
                    rl = QHBoxLayout(row)
                    rl.setContentsMargins(0, 0, 0, 0)
                    rl.setSpacing(4)
                    lbl = QLabel(row_label, self)
                    lbl.setFixedWidth(65)
                    lbl.setStyleSheet("color: #aaa; font-size: 9px;")
                    inp = QLineEdit(self)
                    inp.setStyleSheet("font-size: 9px;")
                    current = fs.get('value-String', '') if fs is not None else ''
                    inp.setText(current)
                    inp.setPlaceholderText("(none)")

                    def _on_change(text, _fs=fs, _fh=fh):
                        t = text.strip()
                        if t:
                            if _fs is not None:
                                _fs.set('value-String', t)
                                _fs.text = string_to_binhex(t)
                            if _fh is not None:
                                _fh.set('value-ComputeHash32', t)
                                _fh.text = compute_hash32_to_binhex(t)
                        else:
                            if _fs is not None:
                                _fs.attrib.pop('value-String', None)
                                _fs.text = '00'
                            if _fh is not None:
                                _fh.attrib.pop('value-ComputeHash32', None)
                                _fh.text = 'FFFFFFFF'
                        self.schedule_auto_save()

                    inp.textChanged.connect(_on_change)
                    rl.addWidget(lbl)
                    rl.addWidget(inp)
                    return row

                sf_vl.addWidget(_make_path_row("Original:", f_orig_str, f_orig_hash))
                sf_vl.addWidget(_make_path_row("Override:", f_over_str, f_over_hash))

                rm_btn = QPushButton("× Remove Slot", self)
                rm_btn.setStyleSheet(
                    "QPushButton { background: #3a2020; color: #c87e7e;"
                    " border: 1px solid #5a3030; border-radius: 3px;"
                    " padding: 2px 8px; font-size: 9px; }"
                    "QPushButton:hover { background: #4a2525; }"
                )
                rm_btn.setFixedHeight(20)

                def _remove_slot(_checked=False, mo=mat_overrides, m=mat):
                    remaining = [c for c in mo if c.get('name') == 'Material']
                    pre_close = remaining[-1].tail if remaining else None
                    mo.remove(m)
                    new_remaining = [c for c in mo if c.get('name') == 'Material']
                    if new_remaining and pre_close is not None:
                        new_remaining[-1].tail = pre_close
                    _rebuild()

                rm_btn.clicked.connect(_remove_slot)
                sf_vl.addWidget(rm_btn)
                vl.addWidget(slot_frame)

        def _add_slot():
            nonlocal mat_overrides
            if mat_overrides is None:
                mat_overrides = ET.SubElement(skin_elem, 'object')
                mat_overrides.set('hash', '0FA60B61')
                mat_overrides.set('name', 'MaterialOverrides')
                mat_overrides.text = '\n          '
                mat_overrides.tail = '\n        '

            existing = mat_overrides.findall("object[@name='Material']")
            entry_indent = mat_overrides.text or '\n          '
            pre_close = existing[-1].tail if existing else (mat_overrides.tail or '\n        ')

            mat = ET.SubElement(mat_overrides, 'object')
            mat.set('hash', '85C817C3')
            mat.set('name', 'Material')
            fi = entry_indent + '  '
            mat.text = fi

            f1 = ET.SubElement(mat, 'field')
            f1.set('hash', 'DD2929AC')
            f1.set('type', 'BinHex')
            f1.text = '00'
            f1.tail = fi

            f2 = ET.SubElement(mat, 'field')
            f2.set('hash', 'E1C0931D')
            f2.set('name', 'fileOriginalMaterial')
            f2.set('type', 'BinHex')
            f2.text = 'FFFFFFFF'
            f2.tail = fi

            f3 = ET.SubElement(mat, 'field')
            f3.set('hash', '148E2F84')
            f3.set('type', 'BinHex')
            f3.text = '00'
            f3.tail = fi

            f4 = ET.SubElement(mat, 'field')
            f4.set('hash', '28679535')
            f4.set('name', 'fileMaterialOverride')
            f4.set('type', 'BinHex')
            f4.text = 'FFFFFFFF'
            f4.tail = entry_indent

            if existing:
                existing[-1].tail = entry_indent
            mat.tail = pre_close

            _rebuild()

        add_btn = QPushButton("+ Add Material Slot", self)
        add_btn.setStyleSheet(
            "QPushButton { background: #1e2e3e; color: #7ec87e; border: 1px solid #2a5a2a;"
            " border-radius: 3px; padding: 3px 10px; font-size: 10px; }"
            "QPushButton:hover { background: #2a3e2a; }"
        )
        add_btn.setFixedHeight(24)
        add_btn.clicked.connect(_add_slot)
        vl.addWidget(add_btn)

        parent_layout.addWidget(group)

    def _add_position_group(self, entity):
        """Editable X/Y/Z position, bound to entity.x/y/z."""
        group = QGroupBox("Position", self)
        gl = QGridLayout(group)
        gl.setContentsMargins(8, 6, 8, 6)
        gl.setSpacing(4)
        gl.setColumnStretch(1, 1)

        lbl = QLabel("X / Y / Z:", self)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        gl.addWidget(lbl, 0, 0)
        gl.addWidget(self._make_position_widget(entity), 0, 1)

        self.content_layout.addWidget(group)

    def _make_position_widget(self, entity):
        w = QWidget(self)
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)
        for axis in ('x', 'y', 'z'):
            lbl = QLabel(axis.upper() + ":", self)
            lbl.setFixedWidth(18)
            inp = DecimalInput(
                self,
                lambda a=axis: getattr(entity, a),
                lambda val, a=axis: self.set_position_component(entity, a, val)
            )
            inp.changed.connect(self.on_position_changed)
            inp.update_value()
            inp.setMinimumWidth(70)
            hl.addWidget(lbl)
            hl.addWidget(inp)
        hl.addStretch()
        return w

    # ------------------------------------------------------------------
    # Field-row builder — shared by entity Properties and all components
    # ------------------------------------------------------------------

    def _build_field_rows(self, gl: QGridLayout, fields: list,
                          sel_enum_map: dict = None) -> int:
        """Populate *gl* with one row per visible field.

        Rules applied in order:
        - ``text_XYZ`` fields: editable, live-update companion ``XYZ`` hash field.
        - Companion hash fields (``XYZ``): hidden entirely.
        - ``sel_XYZ`` fields with a companion ``enum_XYZ`` object: QComboBox dropdown.
        - ``hidPos`` / ``hidPos_precise``: disabled (managed by Position editor).
        - ``value-Id64``: read-only selectable label.
        - Fields with no ``value-*`` attribute (bare BinHex): checkbox (1 byte) or
          editable hex field (multi-byte).
        - All others: normal editable input widget.
        - Column 2: live BinHex preview label, updated as the user types.

        Returns the number of rows added.
        """
        if sel_enum_map is None:
            sel_enum_map = {}

        # Identify hash companions auto-managed by a text_ sibling
        names = {f.get('name', '') for f in fields}
        hidden: set = set()
        for name in names:
            if name.startswith('text_'):
                companion = name[5:]
                if companion in names:
                    hidden.add(companion)

        companion_map = {
            f.get('name', ''): f for f in fields if f.get('name', '') in hidden
        }

        row = 0
        for field in fields:
            field_name = field.get('name', field.get('hash', '?'))

            if field_name in hidden:
                continue

            lbl = QLabel(self._fmt_name(field_name) + ":", self)
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl.setToolTip(field_name)

            if self._has_point_children(field):
                lbl.setAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop
                )
                widget = self._make_shape_points_widget(field)
                gl.addWidget(lbl, row, 0)
                gl.addWidget(widget, row, 1, 1, 2)
                row += 1
                continue

            if field_name.startswith('text_') and field_name[5:] in companion_map:
                widget = self._make_text_with_hash_widget(
                    field, companion_map[field_name[5:]]
                )
            elif field_name in sel_enum_map:
                widget = self._make_enum_dropdown(field, sel_enum_map[field_name])
            elif field_name in ('hidPos', 'hidPos_precise'):
                widget = self.create_field_input_widget(field, field_name)
                widget.setEnabled(False)
                widget.setToolTip("Managed via the Position editor above")
            elif self._is_bare_binhex(field) and self._is_entity_ref_field(field):
                widget = self._make_entity_ref_widget(field)
            elif self._is_bare_binhex(field):
                widget = self._make_bare_binhex_widget(field)
            elif self.get_value_attribute(field) == 'value-Hash32' and field_name != 'hidScale':
                widget = self._make_hash32_smart_widget(field, field_name)
            else:
                widget = self.create_field_input_widget(field, field_name)

            # Live BinHex preview label (col 2) — skipped for booleans/checkboxes
            hex_lbl = QLabel(self)
            hex_lbl.setStyleSheet(
                "color: #484860; font-family: Consolas, monospace; font-size: 8px;"
            )
            hex_lbl.setToolTip("BinHex (updates as you type)")

            def _update_hex(fe=field, hl=hex_lbl):
                raw = (fe.text or "").strip().upper()
                # Truncate display to 16 chars (8 bytes) to keep layout tidy
                hl.setText(raw[:16] + ("…" if len(raw) > 16 else ""))

            _update_hex()

            # Connect to the widget's changed signal when available
            if hasattr(widget, 'changed'):
                widget.changed.connect(_update_hex)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(lambda _checked, fn=_update_hex: fn())

            gl.addWidget(lbl, row, 0)
            gl.addWidget(widget, row, 1)
            gl.addWidget(hex_lbl, row, 2)
            row += 1

        return row

    def _has_point_children(self, field_elem) -> bool:
        return any(child.tag == 'Point' for child in field_elem)

    def _make_shape_points_widget(self, field_elem) -> QWidget:
        """Editable list of X,Y,Z rows for fields that contain <Point> children."""
        import xml.etree.ElementTree as ET
        container = QWidget(self)
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(2)

        rows_widget = QWidget(container)
        rows_vbox = QVBoxLayout(rows_widget)
        rows_vbox.setContentsMargins(0, 0, 0, 0)
        rows_vbox.setSpacing(2)
        vbox.addWidget(rows_widget)

        def _parse(text):
            parts = (text or '0,0,0').strip().split(',')
            result = []
            for p in parts[:3]:
                try:
                    result.append(float(p))
                except ValueError:
                    result.append(0.0)
            while len(result) < 3:
                result.append(0.0)
            return result

        def _fmt(v):
            return f'{v:g}' if v == int(v) else repr(v)

        def _make_point_row(point_elem):
            px, py, pz = _parse(point_elem.text)
            row_w = QWidget()
            rl = QHBoxLayout(row_w)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(3)

            sx = QDoubleSpinBox(); sx.setRange(-999999, 999999); sx.setDecimals(6); sx.setValue(px)
            sy = QDoubleSpinBox(); sy.setRange(-999999, 999999); sy.setDecimals(6); sy.setValue(py)
            sz = QDoubleSpinBox(); sz.setRange(-999999, 999999); sz.setDecimals(6); sz.setValue(pz)

            def _update(pe=point_elem):
                pe.text = f'{_fmt(sx.value())},{_fmt(sy.value())},{_fmt(sz.value())}'
                self.schedule_auto_save()

            sx.valueChanged.connect(lambda _: _update())
            sy.valueChanged.connect(lambda _: _update())
            sz.valueChanged.connect(lambda _: _update())

            rm_btn = QPushButton('✕')
            rm_btn.setFixedWidth(26)
            rm_btn.setToolTip('Remove point')

            def _remove(pe=point_elem, rw=row_w):
                try:
                    field_elem.remove(pe)
                except ValueError:
                    pass
                rw.setParent(None)
                rw.deleteLater()
                self.schedule_auto_save()

            rm_btn.clicked.connect(_remove)

            for lbl_txt, spin in [('X:', sx), ('Y:', sy), ('Z:', sz)]:
                rl.addWidget(QLabel(lbl_txt))
                rl.addWidget(spin)
            rl.addWidget(rm_btn)
            return row_w

        for child in list(field_elem):
            if child.tag == 'Point':
                rows_vbox.addWidget(_make_point_row(child))

        add_btn = QPushButton('+ Add Point')
        add_btn.setFixedWidth(96)

        def _add_point():
            new_pt = ET.SubElement(field_elem, 'Point')
            new_pt.text = '0,0,0'
            rows_vbox.addWidget(_make_point_row(new_pt))
            self.schedule_auto_save()

        add_btn.clicked.connect(_add_point)
        vbox.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        return container

    def _make_readonly_label(self, field_elem) -> QLabel:
        """Read-only display for non-editable fields (e.g. Id64 entity IDs)."""
        value_attr = self.get_value_attribute(field_elem)
        value = field_elem.get(value_attr, field_elem.text or "")
        lbl = QLabel(str(value), self)
        lbl.setStyleSheet("color: #888; font-family: monospace; font-size: 10px;")
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return lbl

    def _make_text_with_hash_widget(self, text_field, hash_field) -> QWidget:
        """String input that live-updates the companion hash field on every keystroke."""
        value_attr = self.get_value_attribute(text_field)
        hash_value_attr = self.get_value_attribute(hash_field)

        def set_with_hash(val: str):
            # Update text field (string + BinHex)
            self.update_xml_field_with_binhex(text_field, value_attr, val, 'string')
            # Live-update companion hash field
            self.update_xml_field_with_binhex(
                hash_field, hash_value_attr, val, 'compute_hash32'
            )

        inp = StringInput(
            self,
            lambda: text_field.get(value_attr) or "",
            set_with_hash
        )
        inp.changed.connect(self.schedule_auto_save)
        inp.update_value()
        return inp

    # ------------------------------------------------------------------
    # sel*/enum* companion helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_sel_enum_companions(fields: list, objects: list):
        """Identify sel*/enum* companion pairs within the same parent element.

        ``sel{X}`` field + ``enum{X}`` object → the field becomes a QComboBox
        and the object is hidden from the group rendering.

        Returns:
            sel_enum_map  — {sel_field_name: enum_object_elem}
            hidden_obj_names — set of object names to skip in the UI
        """
        sel_names = {
            f.get('name', '') for f in fields if f.get('name', '').startswith('sel')
        }
        obj_by_name = {o.get('name', ''): o for o in objects}

        sel_enum_map = {}
        hidden_obj_names = set()
        for sel_name in sel_names:
            companion = 'enum' + sel_name[3:]   # selXYZ → enumXYZ
            if companion in obj_by_name:
                sel_enum_map[sel_name] = obj_by_name[companion]
                hidden_obj_names.add(companion)

        return sel_enum_map, hidden_obj_names

    def _make_enum_dropdown(self, field_elem, enum_obj) -> QComboBox:
        """Build a QComboBox from a companion ``enum*`` object, wired for live BinHex updates."""
        value_attr = self.get_value_attribute(field_elem)
        try:
            current_val = int(field_elem.get(value_attr, '0') or '0')
        except ValueError:
            current_val = 0

        options = self._parse_enum_options(enum_obj)
        combo = QComboBox(self)
        for display, int_val in options:
            combo.addItem(display, int_val)

        # Select the current value by matching itemData
        for i in range(combo.count()):
            if combo.itemData(i) == current_val:
                combo.setCurrentIndex(i)
                break

        def on_change(index):
            int_val = combo.itemData(index)
            if int_val is not None:
                field_elem.set(value_attr, str(int_val))
                field_elem.text = _to_binhex('enum', str(int_val))
                self.schedule_auto_save()

        combo.currentIndexChanged.connect(on_change)
        return combo

    def _parse_enum_options(self, enum_obj) -> list:
        """Extract ``[(display_str, int_value), ...]`` from an ``enum*`` companion object."""
        options = []
        for i, entry in enumerate(enum_obj.findall("object[@name='enum']")):
            val_field = entry.find("field[@name='Value']")
            custom_field = entry.find("field[@name='CustomValue']")

            if val_field is not None:
                if val_field.get('value-String') is not None:
                    display = val_field.get('value-String', f'Option {i}')
                elif val_field.get('value-Int32') is not None:
                    # Int32 encoding of ASCII string (little-endian, e.g. "Box\0")
                    display = self._int32_to_str(int(val_field.get('value-Int32', '0')))
                else:
                    display = f'Option {i}'
            else:
                display = f'Option {i}'

            if custom_field is not None:
                int_val = int(custom_field.get('value-Int32', str(i)))
            else:
                int_val = i          # 0-based index when no CustomValue

            options.append((display, int_val))
        return options

    @staticmethod
    def _int32_to_str(val: int) -> str:
        """Decode a little-endian int32 as an ASCII label (e.g. 7892802 → 'Box')."""
        try:
            b = struct.pack('<I', val & 0xFFFFFFFF)
            return b.rstrip(b'\x00').decode('ascii', errors='replace')
        except Exception:
            return str(val)

    # ------------------------------------------------------------------
    # Bare BinHex fields (no value-* attribute)
    # ------------------------------------------------------------------

    def _is_bare_binhex(self, field_elem) -> bool:
        """True when the field carries only raw BinHex text with no value-* attribute."""
        for attr in ('value-String', 'strVal', 'value-Vector3', 'value-Int32', 'value-UInt32',
                     'value-Id64', 'value-Float32', 'value-Hash32', 'value-Hash64',
                     'value-Boolean', 'value-ComputeHash32', 'value-Enum', 'value'):
            if field_elem.get(attr) is not None:
                return False
        return True

    def _make_bare_binhex_widget(self, field_elem) -> QWidget:
        """Widget for bare BinHex fields:
        - 1 byte (2 hex chars) → editable boolean checkbox
        - multi-byte             → read-only selectable hex label
        """
        binhex = (field_elem.text or "").strip().upper()
        if len(binhex) == 2:    # 1-byte field — treat as boolean
            checkbox = QCheckBox(self)
            checkbox.setChecked(binhex == "01")

            def on_toggle(checked, fe=field_elem):
                fe.text = "01" if checked else "00"
                self.schedule_auto_save()

            checkbox.toggled.connect(on_toggle)
            apply_checkbox_style(checkbox)
            return checkbox

        # Multi-byte raw hex — editable hex field
        inp = QLineEdit(binhex or "", self)
        inp.setFont(QFont("Consolas", 9))
        inp.setStyleSheet("color: #aaa;")
        inp.setPlaceholderText("hex bytes (e.g. 0A1B2C3D)")
        inp.setValidator(QRegularExpressionValidator(
            QRegularExpression(r'[0-9a-fA-F]*'), inp
        ))

        def _on_hex_changed(text, fe=field_elem):
            fe.text = text.upper()
            self.schedule_auto_save()

        inp.textChanged.connect(_on_hex_changed)
        return inp

    def _is_entity_ref_field(self, field_elem) -> bool:
        """True when a bare-BinHex field looks like an entity reference:
        name starts with 'ent' and the raw hex is exactly 16 chars (8 bytes / 64-bit).
        """
        name = field_elem.get('name', '')
        if not name.startswith('ent'):
            return False
        binhex = (field_elem.text or '').strip()
        return len(binhex) == 16

    def _make_entity_ref_widget(self, field_elem) -> QWidget:
        """Editable entity-ID field for bare BinHex ent* fields (no value-Id64 attribute).
        FFFFFFFFFFFFFFFF = no entity → shown as blank.
        On edit: writes value-Id64 attribute + recomputes BinHex.
        """
        binhex = (field_elem.text or '').strip().upper()
        if not binhex or binhex == 'FFFFFFFFFFFFFFFF':
            current = ''
        else:
            try:
                current = str(struct.unpack('<Q', bytes.fromhex(binhex))[0])
            except Exception:
                current = ''

        inp = QLineEdit(current, self)
        inp.setPlaceholderText("Entity ID (blank = none)")

        def on_changed(text, fe=field_elem):
            try:
                if text.strip():
                    val = int(text)
                    fe.set('value-Id64', str(val))
                    fe.text = struct.pack('<Q', val & 0xFFFFFFFFFFFFFFFF).hex().upper()
                else:
                    fe.attrib.pop('value-Id64', None)
                    fe.text = 'FFFFFFFFFFFFFFFF'
                self.schedule_auto_save()
            except (ValueError, struct.error):
                pass

        inp.textChanged.connect(on_changed)
        return inp

    # ------------------------------------------------------------------

    def _make_hash32_smart_widget(self, field_elem, field_name) -> QWidget:
        """Route Hash32 fields to a meaningful widget based on field name semantics."""
        value_attr = self.get_value_attribute(field_elem)
        name_lower = field_name.lower()
        if any(kw in name_lower for kw in ('color', 'colour', 'occlusion')):
            return self._make_color32_widget(field_elem, value_attr)
        if any(kw in name_lower for kw in ('height', 'width', 'depth', 'radius',
                                            'factor', 'speed', 'weight', 'mass',
                                            'dist', 'range', 'scale')):
            return self._make_float_from_hash32_widget(field_elem, value_attr)
        # True name-hash field — show a string input that hashes on the fly
        return self._make_hash_string_input(field_elem, value_attr)

    def _make_color32_widget(self, field_elem, value_attr) -> QWidget:
        """Packed ARGB color stored as uint32.
        Shows: editable '#AARRGGBB' hex string + a color swatch.
        """
        from PyQt6.QtGui import QColor
        from PyQt6.QtWidgets import QFrame

        def _raw_to_argb(raw_uint: int):
            a = (raw_uint >> 24) & 0xFF
            r = (raw_uint >> 16) & 0xFF
            g = (raw_uint >>  8) & 0xFF
            b =  raw_uint        & 0xFF
            return a, r, g, b

        def _argb_str_to_raw(text: str) -> int:
            t = text.strip().lstrip('#')
            if len(t) == 6:
                t = 'FF' + t          # assume full alpha if not given
            if len(t) != 8:
                raise ValueError("Expected AARRGGBB or RRGGBB")
            return int(t, 16)

        def _get_uint():
            raw = field_elem.get(value_attr, '0')
            try:
                return int(raw) & 0xFFFFFFFF
            except ValueError:
                return 0

        container = QWidget(self)
        hl = QHBoxLayout(container)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)

        # Editable hex entry
        entry = QLineEdit(container)
        entry.setMaxLength(9)
        entry.setFixedWidth(110)
        entry.setFont(QFont("Consolas", 9))
        entry.setPlaceholderText("#AARRGGBB")

        # Color swatch
        swatch = QFrame(container)
        swatch.setFixedSize(20, 20)
        swatch.setFrameShape(QFrame.Shape.Box)

        def _refresh_swatch(uint_val: int):
            a, r, g, b = _raw_to_argb(uint_val)
            color = QColor(r, g, b, a)
            swatch.setStyleSheet(f"background-color: rgba({r},{g},{b},{a}); border: 1px solid #555;")

        def _load():
            v = _get_uint()
            a, r, g, b = _raw_to_argb(v)
            entry.setText(f"#{v:08X}")
            _refresh_swatch(v)

        def _on_text_changed(text: str):
            try:
                raw = _argb_str_to_raw(text)
                field_elem.set(value_attr, str(raw))
                field_elem.text = struct.pack('<I', raw).hex().upper()
                _refresh_swatch(raw)
                self.schedule_auto_save()
            except ValueError:
                pass

        entry.textChanged.connect(_on_text_changed)
        _load()

        hl.addWidget(entry)
        hl.addWidget(swatch)
        hl.addStretch()
        return container

    def _make_float_from_hash32_widget(self, field_elem, value_attr) -> QWidget:
        """Hash32 field that actually stores an IEEE-754 float as its uint32 bit-pattern.
        Shows a DecimalInput with the decoded float; saves back as the uint32 bit-pattern.
        """
        def _get_float() -> float:
            raw = field_elem.get(value_attr, '0')
            try:
                uint_val = int(raw) & 0xFFFFFFFF
                return struct.unpack('<f', struct.pack('<I', uint_val))[0]
            except (ValueError, struct.error):
                return 0.0

        def _set_float(fval: float):
            try:
                packed = struct.pack('<f', fval)
                uint_val = struct.unpack('<I', packed)[0]
                field_elem.set(value_attr, str(uint_val))
                field_elem.text = packed.hex().upper()
                self.schedule_auto_save()
            except (ValueError, struct.error):
                pass

        inp = DecimalInput(self, _get_float, _set_float)
        inp.changed.connect(self.schedule_auto_save)
        inp.update_value()
        return inp

    def _make_hash_string_input(self, field_elem, value_attr) -> QWidget:
        """String input for name-reference Hash32 fields.

        Typing a string computes djb2 Hash32 and writes it back as the
        attribute value + BinHex element text.  If the stored attribute
        already looks like a human-readable string (not a bare integer) it
        is pre-filled; otherwise the hash hex is shown as placeholder text
        so the user can see the current raw value.
        """
        container = QWidget(self)
        hl = QHBoxLayout(container)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)

        inp = QLineEdit(container)
        inp.setFont(QFont("Consolas", 9))

        hash_lbl = QLabel("", container)
        hash_lbl.setStyleSheet("color: #666; font-family: monospace; font-size: 9px;")
        hash_lbl.setMinimumWidth(80)

        # Decide whether the current attribute value is a recoverable string
        current_attr = field_elem.get(value_attr, '')
        try:
            int(current_attr)
            # Attribute holds a raw integer — can't recover original string.
            # Show current BinHex as placeholder so it's not hidden.
            current_binhex = (field_elem.text or '').strip().upper()
            inp.setPlaceholderText(f"0x{current_binhex}" if current_binhex else "type name…")
        except ValueError:
            # Attribute holds the original string — pre-fill it.
            inp.setText(current_attr)

        def _on_text_changed(text: str):
            if text:
                hash_val = compute_hash32(text)
                field_elem.set(value_attr, str(hash_val))
                field_elem.text = struct.pack('<I', hash_val).hex().upper()
                hash_lbl.setText(f"→ {hash_val:08X}")
            else:
                # Empty string typed — keep placeholder, don't zero out
                hash_lbl.setText("")
            self.schedule_auto_save()

        inp.textChanged.connect(_on_text_changed)
        # Trigger once if pre-filled
        if inp.text():
            _on_text_changed(inp.text())

        hl.addWidget(inp, 1)
        hl.addWidget(hash_lbl)
        return container

    # ------------------------------------------------------------------

    def _add_fields_group(self, title: str, fields: list, sel_enum_map: dict = None):
        """Render entity-level <field> children as a titled 2-column group."""
        group = QGroupBox(title, self)
        gl = QGridLayout(group)
        gl.setContentsMargins(8, 6, 8, 6)
        gl.setSpacing(3)
        gl.setColumnMinimumWidth(0, 170)
        gl.setColumnStretch(1, 1)
        gl.setColumnMinimumWidth(2, 90)

        if self._build_field_rows(gl, fields, sel_enum_map) > 0:
            self.content_layout.addWidget(group)

    def _render_object_as_group(self, parent_layout, elem, depth=0,
                                 list_parent=None):
        """Recursively render an <object> element as a QGroupBox.

        When *list_parent* is supplied this element is one item inside a list
        container and a × Remove button is shown at the bottom of the group.
        """
        name = elem.get('name') or f"[{elem.get('hash', '?')}]"
        group = QGroupBox(name, self)
        vl = QVBoxLayout(group)
        vl.setContentsMargins(8, 6, 8, 4)
        vl.setSpacing(2)

        direct_fields = elem.findall("field")
        child_objects = elem.findall("object")

        # Find sel*/enum* companions within this element
        sel_enum_map, hidden_obj_names = self._find_sel_enum_companions(
            direct_fields, child_objects
        )

        # Direct fields grid
        if direct_fields:
            gw = QWidget(self)
            gl = QGridLayout(gw)
            gl.setContentsMargins(0, 0, 0, 0)
            gl.setSpacing(3)
            gl.setColumnMinimumWidth(0, 170)
            gl.setColumnStretch(1, 1)
            gl.setColumnMinimumWidth(2, 90)
            if self._build_field_rows(gl, direct_fields, sel_enum_map) > 0:
                vl.addWidget(gw)

        # InitialUsers / MaterialOverrides handled by dedicated panels — skip generic rendering
        hidden_obj_names.add('InitialUsers')
        if name == 'CAvatarSkinComponent':
            hidden_obj_names.add('MaterialOverrides')

        # Detect list containers: all visible children share the same tag name
        visible_children = [c for c in child_objects if c.get('name', '') not in hidden_obj_names]
        is_list_container = (
            len(visible_children) > 0
            and len({c.get('name', '') for c in visible_children}) == 1
        )

        # Child <object> elements — pass list context so items get × buttons
        for child in visible_children:
            self._render_object_as_group(
                vl, child, depth + 1,
                list_parent=elem if is_list_container else None
            )

        # "Add item" button for list containers
        if is_list_container:
            item_name = visible_children[0].get('name', 'item')
            self._add_list_item_button(vl, elem, item_name)

        # × Remove button when this is an item inside a list container
        if list_parent is not None:
            rm_btn = QPushButton("× Remove", self)
            rm_btn.setStyleSheet(
                "QPushButton { background: #3a2020; color: #c87e7e;"
                " border: 1px solid #5a3030; border-radius: 3px;"
                " padding: 2px 8px; font-size: 9px; }"
                "QPushButton:hover { background: #4a2525; }"
            )
            rm_btn.setFixedHeight(20)

            def _remove(_checked=False, lp=list_parent, el=elem):
                # Grab the actual last same-name sibling's tail before removal
                # so we can transfer the pre-close whitespace to the new last item.
                item_tag = el.get('name', '')
                siblings = [c for c in lp if c.get('name', '') == item_tag]
                pre_close_tail = siblings[-1].tail if siblings else None

                lp.remove(el)

                # Give the new last sibling the correct pre-close tail
                remaining = [c for c in lp if c.get('name', '') == item_tag]
                if remaining and pre_close_tail is not None:
                    remaining[-1].tail = pre_close_tail

                self.schedule_auto_save()
                self.populate_all_views()

            rm_btn.clicked.connect(_remove)
            vl.addWidget(rm_btn)

        # InitialUsers dedicated panel — rendered inside CArmedVehicle or CVehicle
        if elem.get('name') in ('CArmedVehicle', 'CVehicle'):
            try:
                self._render_initial_users(vl, elem)
            except Exception as _e:
                print(f"[EntityEditor] _render_initial_users failed for "
                      f"{elem.get('name','?')}: {_e}")

        # Material Overrides dedicated panel — rendered inside CAvatarSkinComponent
        if elem.get('name') == 'CAvatarSkinComponent':
            try:
                self._render_skin_component(vl, elem)
            except Exception as _e:
                print(f"[EntityEditor] _render_skin_component failed: {_e}")

        if vl.count() > 0:
            parent_layout.addWidget(group)

        # "Add from archetype" sub-objects panel — only for top-level components.
        # Added to parent_layout (not vl) so it always appears even if the
        # component group ended up empty.
        if depth == 0:
            try:
                self._add_archetype_subobjects_panel(parent_layout, elem)
            except Exception as _e:
                print(f"[EntityEditor] archetype subobjects panel failed for "
                      f"{elem.get('name','?')}: {_e}")

    @staticmethod
    def _xml_deepcopy(elem):
        """Reliable deep-copy of an ElementTree element.

        The C-accelerated ElementTree (used by default in CPython 3) does not
        support copy.deepcopy correctly — attributes are silently dropped.
        Serialise → parse is the safe alternative.
        """
        import xml.etree.ElementTree as ET
        return ET.fromstring(ET.tostring(elem, encoding='unicode'))

    def _add_list_item_button(self, parent_layout, container_elem, item_name: str):
        """Append an 'Add <item_name>' button that clones the last list entry."""
        btn = QPushButton(f"+ Add {item_name}", self)
        btn.setStyleSheet(
            "QPushButton { background: #2a3a2a; color: #7ec87e; border: 1px solid #3a5a3a;"
            " border-radius: 3px; padding: 3px 10px; font-size: 10px; }"
            "QPushButton:hover { background: #3a4a3a; }"
        )
        btn.setFixedHeight(24)

        def _add_item():
            import xml.etree.ElementTree as ET
            children = container_elem.findall(f"object[@name='{item_name}']")
            if children:
                # Always clone the FIRST child — it's the original/complete template.
                # Using the last child risks copying a previously-broken duplicate.
                # ET.tostring drops the tail of the root element, so we must set it
                # manually. The last child's tail is the "pre-close" whitespace that
                # puts the parent's </object> on its own indented line.
                # container_elem.text is the "inter-sibling" whitespace — the indent
                # that comes before each item inside the container.
                pre_close_tail = children[-1].tail
                inter_tail = container_elem.text  # e.g. "\n              "

                new_item = self._xml_deepcopy(children[0])
                new_item.tail = pre_close_tail   # new last → pre-close whitespace

                # The previous last child is now a middle sibling; give it the
                # inter-sibling indent so the next <object> starts on the right line.
                children[-1].tail = inter_tail
                # Reset field VALUES to zero/empty; preserve type attributes
                for field in new_item.iter('field'):
                    va = self.get_value_attribute(field)
                    if va == 'value-Int32':
                        field.set(va, '0')
                        field.text = '00000000'
                    elif va == 'value-UInt32':
                        field.set(va, '0')
                        field.text = '00000000'
                    elif va == 'value-Float32':
                        field.set(va, '0.0')
                        field.text = '00000000'
                    elif va in ('value-Hash32', 'value-Hash64'):
                        field.set(va, '0')
                        field.text = '00000000' if va == 'value-Hash32' else '0000000000000000'
                    elif va == 'value-ComputeHash32':
                        field.set(va, '')
                        field.text = '00000000'
                    elif va == 'value-String':
                        field.set(va, '')
                        field.text = '00'
                    elif va == 'value-Id64':
                        field.set(va, '0')
                        field.text = '0000000000000000'
                    elif va == 'value-Boolean':
                        field.set(va, 'False')
                        field.text = '00'
                    elif va == 'value-Enum':
                        field.set(va, '0')
                        field.text = '00000000'
                    # bare BinHex (no value-* attr): leave as-is
            else:
                new_item = ET.Element('object')
                new_item.set('name', item_name)

            container_elem.append(new_item)
            self.schedule_auto_save()
            self.populate_all_views()

        btn.clicked.connect(_add_item)
        parent_layout.addWidget(btn)

    def _fmt_name(self, name):
        """Strip common game-engine prefixes and insert spaces for display."""
        n = name
        for pfx in ('text_', 'hid', 'dis', 'tpl', 'sel', 'olg', 'ag'):
            if n.startswith(pfx) and len(n) > len(pfx) and n[len(pfx)].isupper():
                n = n[len(pfx):]
                break
        result = ''
        for i, ch in enumerate(n):
            if i > 0 and ch.isupper() and (n[i - 1].islower() or
                    (i + 1 < len(n) and n[i + 1].islower())):
                result += ' '
            result += ch
        return result.strip() or name

    # ------------------------------------------------------------------
    # Field widget creation
    # ------------------------------------------------------------------

    def create_field_input_widget(self, field_elem, field_name):
        """Create an appropriate input widget for a field element."""
        value_attr = self.get_value_attribute(field_elem)
        category = get_field_category(field_name, value_attr)

        if category == 'scale':
            return self.create_scale_field(field_elem, value_attr)
        elif category == 'vector':
            return self.create_vector3_field(field_elem, value_attr)
        elif category == 'id64':
            return self.create_id64_field(field_elem, value_attr)
        elif category == 'integer':
            return self.create_integer_field(field_elem, value_attr)
        elif category == 'uint32':
            return self.create_uint32_field(field_elem, value_attr)
        elif category == 'hash':
            return self.create_hash32_field(field_elem, value_attr)
        elif category == 'hash64':
            return self.create_hash64_field(field_elem, value_attr)
        elif category == 'boolean':
            return self.create_boolean_field(field_elem, value_attr)
        elif category == 'float':
            return self.create_float_field(field_elem, value_attr)
        elif category == 'compute_hash32':
            return self.create_compute_hash32_field(field_elem, value_attr)
        elif category == 'enum':
            return self.create_enum_field(field_elem, value_attr)
        else:
            return self.create_string_field(field_elem, value_attr)

    def get_value_attribute(self, field_elem):
        """Return the value-* attribute name present on this field element."""
        for attr in ['value-String', 'strVal', 'value-Vector3', 'value-Int32', 'value-UInt32',
                     'value-Id64', 'value-Float32', 'value-Hash32', 'value-Hash64',
                     'value-Boolean', 'value-ComputeHash32', 'value-Enum', 'value']:
            if field_elem.get(attr) is not None:
                return attr
        return 'value-String'

    def update_scale_field(self, field_elem, value_attr, hash32_val):
        try:
            field_elem.set(value_attr, str(int(hash32_val)))
            field_elem.text = _to_binhex('hash32', str(int(hash32_val)))
        except Exception as e:
            print(f"Error updating scale field: {e}")

    def create_scale_field(self, field_elem, value_attr):
        inp = ScaleInput(
            self,
            lambda: int(field_elem.get(value_attr) or "1065353216"),
            lambda val: self.update_scale_field(field_elem, value_attr, val)
        )
        inp.changed.connect(self.schedule_auto_save)
        inp.update_value()
        return inp

    def create_id64_field(self, field_elem, value_attr):
        name = field_elem.get('name', '')
        is_entity_ref = name.startswith('ent')

        def _get():
            val = field_elem.get(value_attr) or ''
            if is_entity_ref and (not val or val.upper() == 'FFFFFFFFFFFFFFFF'):
                return ''
            return val or '0'

        def _set(val):
            if is_entity_ref and not val.strip():
                field_elem.attrib.pop(value_attr, None)
                field_elem.text = 'FFFFFFFFFFFFFFFF'
            else:
                self.update_xml_field_with_binhex(field_elem, value_attr, val, 'id64')

        inp = StringInput(self, _get, _set)
        if is_entity_ref:
            inp.setPlaceholderText("Entity ID (blank = none)")
        inp.changed.connect(self.schedule_auto_save)
        inp.update_value()
        return inp

    def create_hash32_field(self, field_elem, value_attr):
        inp = IntegerInput(
            self,
            lambda: int(field_elem.get(value_attr) or "0"),
            lambda val: self.update_xml_field_with_binhex(field_elem, value_attr, str(val), 'hash32')
        )
        inp.changed.connect(self.schedule_auto_save)
        inp.update_value()
        return inp

    def create_boolean_field(self, field_elem, value_attr):
        checkbox = QCheckBox(self)

        def get_bool():
            val = field_elem.get(value_attr)
            if val is None:
                return (field_elem.text or "").strip().upper() == "01"
            return val.lower() in ['true', '1', 'yes']

        def set_bool(checked):
            field_elem.set(value_attr, "True" if checked else "False")
            field_elem.text = "01" if checked else "00"
            self.schedule_auto_save()

        checkbox.setChecked(get_bool())
        checkbox.toggled.connect(set_bool)
        apply_checkbox_style(checkbox)
        return checkbox

    def create_integer_field(self, field_elem, value_attr):
        inp = IntegerInput(
            self,
            lambda: int(field_elem.get(value_attr) or "0"),
            lambda val: self.update_xml_field_with_binhex(field_elem, value_attr, str(val), 'int32')
        )
        inp.changed.connect(self.schedule_auto_save)
        inp.update_value()
        return inp

    def create_float_field(self, field_elem, value_attr):
        inp = DecimalInput(
            self,
            lambda: float(field_elem.get(value_attr) or "0.0"),
            lambda val: self.update_xml_field_with_binhex(field_elem, value_attr, str(val), 'float32')
        )
        inp.changed.connect(self.schedule_auto_save)
        inp.update_value()
        return inp

    def create_string_field(self, field_elem, value_attr):
        inp = StringInput(
            self,
            lambda: field_elem.get(value_attr) or "",
            lambda val: self.update_xml_field_with_binhex(field_elem, value_attr, val, 'string')
        )
        inp.changed.connect(self.schedule_auto_save)
        inp.update_value()
        return inp

    def create_uint32_field(self, field_elem, value_attr):
        inp = IntegerInput(
            self,
            lambda: int(field_elem.get(value_attr) or "0"),
            lambda val: self.update_xml_field_with_binhex(field_elem, value_attr, str(val), 'uint32'),
            min_val=0,
            max_val=4294967295
        )
        inp.changed.connect(self.schedule_auto_save)
        inp.update_value()
        return inp

    def create_hash64_field(self, field_elem, value_attr):
        inp = StringInput(
            self,
            lambda: field_elem.get(value_attr) or "0",
            lambda val: self.update_xml_field_with_binhex(field_elem, value_attr, val, 'hash64')
        )
        inp.changed.connect(self.schedule_auto_save)
        inp.update_value()
        return inp

    def create_compute_hash32_field(self, field_elem, value_attr):
        widget = QWidget(self)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        inp = StringInput(
            self,
            lambda: field_elem.get(value_attr) or "",
            lambda val: self.update_xml_field_with_binhex(field_elem, value_attr, val, 'compute_hash32')
        )
        inp.changed.connect(self.schedule_auto_save)
        inp.update_value()

        hash_lbl = QLabel(self)
        hash_lbl.setStyleSheet("color: #888; font-family: monospace; font-size: 9px;")

        def refresh_hash():
            t = inp.text()
            hash_lbl.setText(f"→ {compute_hash32(t):08X}" if t else "")

        inp.textChanged.connect(lambda _: refresh_hash())
        refresh_hash()

        layout.addWidget(inp, 1)
        layout.addWidget(hash_lbl)
        return widget

    def create_enum_field(self, field_elem, value_attr):
        inp = IntegerInput(
            self,
            lambda: int(field_elem.get(value_attr) or "0"),
            lambda val: self.update_xml_field_with_binhex(field_elem, value_attr, str(val), 'enum')
        )
        inp.changed.connect(self.schedule_auto_save)
        inp.update_value()
        return inp

    def create_vector3_field(self, field_elem, value_attr):
        widget = QWidget(self)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        vector_str = field_elem.get(value_attr) or "0,0,0"
        try:
            x, y, z = map(float, vector_str.split(','))
        except Exception:
            x, y, z = 0.0, 0.0, 0.0

        for i, (axis, _value) in enumerate(zip(['X', 'Y', 'Z'], [x, y, z])):
            lbl = QLabel(f"{axis}:", self)
            lbl.setFixedWidth(18)
            inp = DecimalInput(
                self,
                lambda idx=i: self.get_vector_component(field_elem, value_attr, idx),
                lambda val, idx=i: self.set_vector_component(field_elem, value_attr, idx, val)
            )
            inp.changed.connect(self.schedule_auto_save)
            inp.update_value()
            inp.setMinimumWidth(65)
            layout.addWidget(lbl)
            layout.addWidget(inp)

        layout.addStretch()
        return widget

    def get_vector_component(self, field_elem, value_attr, index):
        vector_str = field_elem.get(value_attr) or "0,0,0"
        try:
            parts = list(map(float, vector_str.split(',')))
            return parts[index] if index < len(parts) else 0.0
        except Exception:
            return 0.0

    def set_vector_component(self, field_elem, value_attr, index, value):
        vector_str = field_elem.get(value_attr) or "0,0,0"
        try:
            parts = list(map(float, vector_str.split(',')))
            while len(parts) <= index:
                parts.append(0.0)
            parts[index] = value
            self.update_xml_field_with_binhex(field_elem, value_attr, ",".join(map(str, parts)), 'vector3')
        except Exception as e:
            print(f"Error setting vector component: {e}")

    def update_xml_field_with_binhex(self, field_elem, value_attr, value, data_type):
        """Update XML field attribute AND BinHex text — routes through _to_binhex
        (which uses BinHexConvert from tools/binhex_convertor.py when available)."""
        try:
            field_elem.set(value_attr, value)
            field_elem.text = _to_binhex(data_type, value)
        except Exception as e:
            print(f"Error updating XML field '{field_elem.get('name', '?')}': {e}")
            field_elem.text = "00"

    # ------------------------------------------------------------------
    # Position handling
    # ------------------------------------------------------------------

    def set_position_component(self, entity, component, value):
        setattr(entity, component, value)

    def on_position_changed(self):
        if not self.current_entity:
            return
        try:
            self.canvas.update_entity_xml(self.current_entity)
            self.canvas.update()
            e = self.current_entity
            self.entity_pos_label.setText(
                f"Pos:  X {e.x:.3f}   Y {e.y:.3f}   Z {e.z:.3f}"
            )
            self.schedule_auto_save()
        except Exception as e:
            print(f"Error handling position change: {e}")

    # ------------------------------------------------------------------
    # Add rotation / scale fields (for entities that are missing them)
    # ------------------------------------------------------------------

    def add_rotation_field(self):
        """Add hidAngles field to entity if missing."""
        if not self.current_entity:
            QMessageBox.information(self, "Add Rotation", "No entity selected.")
            return
        if not hasattr(self.current_entity, 'xml_element') or not self.current_entity.xml_element:
            QMessageBox.warning(self, "Add Rotation", "Entity has no XML data.")
            return

        if self.current_entity.xml_element.find(".//field[@name='hidAngles']") is not None:
            QMessageBox.information(self, "Add Rotation", "Entity already has hidAngles.")
            return

        try:
            from xml.etree import ElementTree as ET

            pos_field = self.current_entity.xml_element.find(".//field[@name='hidPos']")
            if pos_field is None:
                pos_field = self.current_entity.xml_element.find(".//field[@name='hidPos_precise']")
            if pos_field is None:
                QMessageBox.warning(self, "Add Rotation", "Could not find hidPos field.")
                return

            angles_field = ET.Element("field")
            angles_field.set("hash", "6553B60B")
            angles_field.set("name", "hidAngles")
            angles_field.set("value-Vector3", "0,-0,0")
            angles_field.set("type", "BinHex")
            angles_field.text = "000000000000008000000000"
            angles_field.tail = pos_field.tail
            pos_field.tail = "\n      "

            parent = None
            for element in self.current_entity.xml_element.iter():
                for child in element:
                    if child == pos_field:
                        parent = element
                        break
                if parent is not None:
                    break

            if parent is None:
                QMessageBox.warning(self, "Add Rotation", "Could not find parent element.")
                return

            parent.insert(list(parent).index(pos_field) + 1, angles_field)
            self.populate_all_views()
            self.schedule_auto_save()
            QMessageBox.information(self, "Add Rotation", "hidAngles field added successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Add Rotation Error", f"Failed: {e}")

    def add_scale_field(self):
        """Add hidScale field to entity if missing."""
        if not self.current_entity:
            QMessageBox.information(self, "Add Scale", "No entity selected.")
            return
        if not hasattr(self.current_entity, 'xml_element') or not self.current_entity.xml_element:
            QMessageBox.warning(self, "Add Scale", "Entity has no XML data.")
            return
        if self.current_entity.xml_element.find(".//field[@name='hidScale']") is not None:
            QMessageBox.information(self, "Add Scale", "Entity already has hidScale.")
            return

        try:
            from xml.etree import ElementTree as ET
            pos_precise = self.current_entity.xml_element.find(".//field[@name='hidPos_precise']")
            if pos_precise is None:
                QMessageBox.warning(self, "Add Scale", "Could not find hidPos_precise field.")
                return
            parent = None
            for element in self.current_entity.xml_element.iter():
                for child in element:
                    if child == pos_precise:
                        parent = element
                        break
                if parent is not None:
                    break
            if parent is None:
                QMessageBox.warning(self, "Add Scale", "Could not find parent element.")
                return

            scale_field = ET.Element("field")
            scale_field.set("hash", "00C2DD80")
            scale_field.set("name", "hidScale")
            scale_field.set("value-Hash32", "1065353216")
            scale_field.set("type", "BinHex")
            scale_field.text = "0000803F"
            scale_field.tail = pos_precise.tail
            pos_precise.tail = "\n      "
            parent.insert(list(parent).index(pos_precise) + 1, scale_field)

            self.populate_all_views()
            self.schedule_auto_save()
            QMessageBox.information(self, "Add Scale", "hidScale field added (default 1.0).")
        except Exception as e:
            QMessageBox.critical(self, "Add Scale Error", f"Failed: {e}")

    # ------------------------------------------------------------------
    # Save / refresh
    # ------------------------------------------------------------------

    def schedule_auto_save(self):
        if self.auto_save_enabled:
            self.auto_save_timer.stop()
            self.auto_save_timer.start(1000)
            self.status_label.setText("Unsaved changes...")

    def auto_save(self):
        if not self.current_entity:
            return
        try:
            self.canvas._auto_save_entity_changes(self.current_entity)
            if hasattr(self.canvas, 'mark_entity_modified'):
                self.canvas.mark_entity_modified(self.current_entity)
                self.canvas.update()
            from PyQt6.QtCore import QTime
            self.status_label.setText(f"Saved at {QTime.currentTime().toString('hh:mm:ss')}")
            # _auto_save_entity_changes may update entity.xml_element (position sync in
            # _update_worldsector_xml_fcb_format).  Refresh the XML tab so the display
            # stays in sync — but only when the user isn't actively typing in it.
            if (hasattr(self, 'tab_widget') and self.tab_widget.currentIndex() == 1
                    and not self._xml_debounce.isActive()):
                self._refresh_xml_tab()
        except Exception as e:
            self.status_label.setText(f"Auto-save failed: {e}")

    def manual_save(self):
        if not self.current_entity:
            QMessageBox.information(self, "Save", "No entity to save.")
            return
        try:
            self.canvas._auto_save_entity_changes(self.current_entity)
            if hasattr(self.canvas, 'mark_entity_modified'):
                self.canvas.mark_entity_modified(self.current_entity)
                self.canvas.update()
            self.status_label.setText("Saved")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def refresh_data(self):
        if self.current_entity:
            entity = self.current_entity
            self.current_entity = None
            self.set_entity(entity)

    def closeEvent(self, event):
        if self.current_entity and self.auto_save_enabled:
            self.auto_save()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # XML tab — sync helpers
    # ------------------------------------------------------------------

    def _on_tab_changed(self, index):
        if index == 1:
            # Switching to XML tab — serialise current element state
            self._refresh_xml_tab()
        elif index == 0:
            # Switching back to Editor tab — discard debounce and apply immediately
            self._xml_debounce.stop()
            self._apply_xml_changes()

    @staticmethod
    def _pretty_xml(elem) -> str:
        """Return a consistently indented XML string for *elem*.

        Works by deep-copying the element (so the live tree's whitespace tail
        nodes are never touched), stripping all existing text/tail whitespace,
        then using minidom to re-indent with 2-space indentation.
        """
        import xml.etree.ElementTree as ET
        from xml.dom import minidom

        # Deep-copy via serialise→parse so we don't mutate the live element
        copy = ET.fromstring(ET.tostring(elem, encoding='unicode'))

        # Strip existing text/tail whitespace — minidom will re-add its own
        for node in copy.iter():
            if node.text and node.text.strip() == '':
                node.text = None
            if node.tail and node.tail.strip() == '':
                node.tail = None

        raw = ET.tostring(copy, encoding='unicode')
        dom = minidom.parseString(raw)
        pretty = dom.toprettyxml(indent='  ', encoding=None)
        # Drop the <?xml …?> declaration line that minidom adds
        lines = pretty.split('\n')
        if lines and lines[0].startswith('<?xml'):
            lines = lines[1:]
        return '\n'.join(lines).strip()

    def _refresh_xml_tab(self):
        """Serialise entity.xml_element (pretty-printed) and push to the XML editor."""
        if self._xml_tab_refreshing:
            return
        entity = self.current_entity
        if entity is None or not hasattr(entity, 'xml_element') or entity.xml_element is None:
            self._xml_tab_refreshing = True
            try:
                self.xml_editor.setPlainText("")
            finally:
                self._xml_tab_refreshing = False
            return
        try:
            text = self._pretty_xml(entity.xml_element)
            self._xml_tab_refreshing = True
            self._xml_debounce.stop()
            try:
                self.xml_editor.setPlainText(text)
                self._xml_status_label.setText("")
            finally:
                self._xml_tab_refreshing = False
        except Exception as e:
            self._xml_status_label.setText(f"Serialise error: {e}")

    # value-* attribute name → _to_binhex data_type key
    _VA_TO_DTYPE = {
        'value-String':        'string',
        'strVal':              'string',
        'value-Float32':       'float32',
        'value-Int32':         'int32',
        'value-UInt32':        'uint32',
        'value-Id64':          'id64',
        'value-Boolean':       'boolean',
        'value-ComputeHash32': 'compute_hash32',
        'value-Hash32':        'hash32',
        'value-Hash64':        'hash64',
        'value-Enum':          'enum',
        'value-Vector3':       'vector3',
    }

    def _recompute_binhex_for_tree(self, elem):
        """Walk every <field> in the tree and regenerate field.text (BinHex)
        from the value-* attribute using the same conversion as the editor tab.
        Skips fields that have no recognisable value-* attribute (bare BinHex)."""
        for field in elem.iter('field'):
            va = self.get_value_attribute(field)
            dtype = self._VA_TO_DTYPE.get(va)
            if dtype is None:
                continue
            val = field.get(va, '')
            if val is None:
                val = ''
            try:
                field.text = _to_binhex(dtype, val)
            except Exception:
                pass  # leave existing BinHex if conversion fails (e.g. empty float)

    def _apply_xml_changes(self):
        """Parse the XML editor content, recompute BinHex, update entity and file."""
        if self._xml_tab_refreshing:
            return
        entity = self.current_entity
        if entity is None:
            return
        text = self.xml_editor.toPlainText().strip()
        if not text:
            return
        try:
            import xml.etree.ElementTree as ET
            new_elem = ET.fromstring(text)

            # Recompute BinHex for every field whose value-* attribute changed
            self._recompute_binhex_for_tree(new_elem)

            entity.xml_element = new_elem

            # If we're on the XML tab, refresh it in-place (preserve cursor position)
            # so the user can see the updated BinHex without losing their edit point.
            if self.tab_widget.currentIndex() == 1:
                cursor_pos = self.xml_editor.textCursor().position()
                self._refresh_xml_tab()
                # Restore cursor position as best we can
                cursor = self.xml_editor.textCursor()
                doc_len = len(self.xml_editor.toPlainText())
                cursor.setPosition(min(cursor_pos, doc_len))
                self.xml_editor.setTextCursor(cursor)
            else:
                # On editor tab — repopulate it
                self.populate_all_views()

            self.schedule_auto_save()
            self._xml_status_label.setText("")
        except ET.ParseError as e:
            self._xml_status_label.setText(f"XML error: {e}")
        except Exception as e:
            self._xml_status_label.setText(f"Error: {e}")


# ============================================================================
# MODULE-LEVEL UTILITIES
# ============================================================================

def create_enhanced_entity_editor(parent, canvas):
    return EntityEditorWindow(parent, canvas)


def get_entity_type_info(entity):
    info = {
        'name': entity.name,
        'type': 'Unknown',
        'creature_type': None,
        'is_vehicle': False,
        'is_static': False,
        'components': []
    }
    if not hasattr(entity, 'xml_element') or not entity.xml_element:
        return info
    creature_field = entity.xml_element.find(".//field[@name='tplCreatureType']")
    if creature_field is not None:
        ct = creature_field.get('value-String') or creature_field.get('strVal') or ''
        info['creature_type'] = ct
        info['is_vehicle'] = 'vehicle' in ct.lower()
    class_field = entity.xml_element.find(".//field[@name='text_hidEntityClass']")
    if class_field is not None:
        ec = class_field.get('value-String') or class_field.get('strVal') or ''
        info['type'] = ec
        info['is_static'] = ec == 'CEntity'
    components = entity.xml_element.find(".//object[@name='Components']")
    if components is not None:
        for comp in components.findall(".//object[@name]"):
            cn = comp.get('name', '')
            if cn != 'Components':
                info['components'].append(cn)
    return info


def format_entity_summary(entity):
    info = get_entity_type_info(entity)
    summary = f"Entity: {info['name']}\nType: {info['type']}\n"
    if info['creature_type']:
        summary += f"Creature Type: {info['creature_type']}\n"
    if info['is_vehicle']:
        summary += "Category: Vehicle\n"
    elif info['is_static']:
        summary += "Category: Static Object\n"
    summary += f"Position: ({entity.x:.3f}, {entity.y:.3f}, {entity.z:.3f})\n"
    if info['components']:
        summary += f"Components: {', '.join(info['components'][:5])}"
        if len(info['components']) > 5:
            summary += f" (+{len(info['components']) - 5} more)"
        summary += "\n"
    return summary


# ============================================================================
# FIELD TYPE MAPPINGS
# ============================================================================

FIELD_TYPE_MAPPINGS = {
    'vector_fields': [
        'hidAngles', 'vectorQ0', 'vectorQ1', 'vectorQ2', 'vectorQ3', 'vectorQ4',
        'vectorQ5', 'vectorQ6', 'vectorNeutral', 'hidPos', 'hidPos_precise', 'vInitialPos'
    ],
    'integer_fields': [
        'hidResourceCount', 'hidRigidbodyIndex', 'hidGraphicIndex', 'hidPartId',
        'olgLightGroup', 'agAmbientGroup', 'hidIndex', 'nVehicleColor',
        'hidResourceIndex', 'CustomValue'
    ],
    'uint32_fields': [],
    'hash_fields': [
        'hidSkyOcclusion0', 'hidSkyOcclusion1', 'hidSkyOcclusion2', 'hidSkyOcclusion3',
        'hidGroundColor', 'hidRigidbodyName', 'objModel', 'hidResourceId',
        'fileName', 'hidMissionLayerPath', 'hidCategory', 'hidEntityClass'
    ],
    'hash64_fields': [],
    'scale_fields': ['hidScale'],
    'boolean_fields': [
        'bAllowCullBySize', 'bForcePPU', 'hidHasAmbientValues', 'bCastShadow',
        'bReceiveShadow', 'bCastAmbientShadow', 'bShowInReflection',
        'bAlwaysShowInReflection', 'bBehaveLikeAPickup', 'bUseMaxTerrainSlope',
        'bIgnoreInExplosions', 'bAnimateable', 'bLargeEntity', 'bNeedExplosionInfo',
        'hidConstEntity', 'ForceMerge', 'bCanBePickedUp'
    ],
    'float_fields': [
        'fCameraRotationFactor', 'fDustFactor', 'fDirtFactor', 'fMaxRollAngle'
    ],
    'id64_fields': ['disEntityId'],
    'compute_hash32_fields': [],
    'enum_fields': [],
    'string_fields': [
        'tplCreatureType', 'hidName', 'text_hidEntityClass', 'text_fileName',
        'text_objModel', 'text_hidResourceId', 'text_hidRigidbodyName',
        'text_hidMissionLayerPath', 'text_hidCategory', 'Value'
    ]
}


def get_field_category(field_name, value_attr):
    """Determine the widget category for a field."""
    if field_name == 'hidScale':
        return 'scale'

    # Primary: detect from value-* attribute
    type_map = {
        'value-Vector3': 'vector',
        'value-Int32': 'integer',
        'value-UInt32': 'uint32',
        'value-Id64': 'id64',
        'value-Float32': 'float',
        'value-Hash32': 'hash',
        'value-Hash64': 'hash64',
        'value-Boolean': 'boolean',
        'value-ComputeHash32': 'compute_hash32',
        'value-Enum': 'enum',
        'value-String': 'string',
        'strVal': 'string',
        'value': 'string',
    }
    if value_attr in type_map:
        return type_map[value_attr]

    # Fallback: check name against mappings
    for category, fields in FIELD_TYPE_MAPPINGS.items():
        if field_name in fields:
            return category.replace('_fields', '')

    return 'string'


COMPONENT_DESCRIPTIONS = {
    'CGraphicComponent': 'Visual rendering, shadows, and graphics properties',
    'CStaticPhysComponent': 'Static physics collision',
    'CVehicleWheeledPhysComponent': 'Wheeled vehicle physics',
    'CVehicle': 'Vehicle behaviour and controls',
    'CEventComponent': 'Event system links',
    'CMissionComponent': 'Mission system integration',
    'CFileDescriptorComponent': 'File resource management',
    'CVehicleMaterialComponent': 'Vehicle material and visual effects',
    'CMapIntelligence': 'AI pathfinding and navigation data',
    'CCollectionComponent': 'Vegetation / collection data',
    'CCollectionIgnitorComponent': 'Fire / burn zone data',
    'CPersistComponent': 'Persistence and streaming level',
    'CSimplePrimitiveComponent': 'Geometric primitive (cube, sphere, cylinder)',
}


def get_component_description(component_name):
    return COMPONENT_DESCRIPTIONS.get(component_name, f"Component: {component_name}")
