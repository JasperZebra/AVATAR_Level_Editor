"""
World Editor — edit a level's ``<name>.game.xml`` (the WorldDescriptor).

The .game.xml is plain-text UTF-8 XML that the Dunia engine reads directly (no
binary/FCB form — verified on disk and in the engine decompile), so this editor
just parses, edits, and writes XML: no external tools needed. Works for both
Avatar and Far Cry 2 (identical file structure).

The four top-level sections are surfaced as tabs:
  <Environment>  -> Environment   (Corp/Na'vi preset slots + inline atmosphere)
  <Layers>       -> Terrain Layers (per-layer detail texture + tiling + rules)
  <Grids>        -> Grids          (world/sector grid layout)
  <MissionsDef>  -> Missions       (game-mode / mission layer definitions)
plus a raw XML tab for power users.

Environment preset slots (Sky/Sun/Lighting/Fog/…) hold GUIDs that reference
preset objects defined in the sibling ``<name>.managers.xml`` (inside the
DataBaseItemManager). This editor reads that catalog and offers each slot as a
dropdown of the presets of the matching class, instead of a raw GUID string.

UI/architecture mirrors entity_editor.py (dark theme, scroll area, search,
debounced auto-save).
"""

import os
import re
import glob
import shutil
import xml.etree.ElementTree as ET

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QLineEdit, QComboBox,
    QCheckBox, QPushButton, QScrollArea, QTabWidget, QGroupBox, QGridLayout,
    QColorDialog, QFileDialog, QPlainTextEdit, QMessageBox, QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QImage, QPixmap

# Layer texture slots that get an XBT thumbnail preview: (attr, caption, is_normal)
_TEX_SLOTS = [('Texture', 'Diffuse', False), ('NormalMap', 'Normal', True),
              ('SpecularMap', 'Specular', False), ('HeightMap', 'Height', False)]
_THUMB_PX = 96

GUID_RE = re.compile(
    r'^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-'
    r'[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$')
ZERO_GUID = "{00000000-0000-0000-0000-000000000000}"
COLOR_RE = re.compile(r'^\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*$')

# Environment slot attribute name -> the CEnvironment* preset class it references
SLOT_CLASS = {
    'Cloud': 'CEnvironmentCloud', 'SkyA': 'CEnvironmentSky', 'SkyB': 'CEnvironmentSky',
    'Sun': 'CEnvironmentSun', 'Lighting': 'CEnvironmentLighting',
    'AdaptiveBloom': 'CEnvironmentAdaptiveBloom', 'DepthOfField': 'CEnvironmentDepthOfField',
    'Fog': 'CEnvironmentFog', 'Wind': 'CEnvironmentWind',
    'AtmosphericScattering': 'CEnvironmentAtmosphericScattering',
    'Intensity': 'CEnvironmentWeather', 'LightingTransition': 'CEnvironmentTransition',
    'CloudTransition': 'CEnvironmentTransition', 'FogTransition': 'CEnvironmentTransition',
}

# 0/1 attributes rendered as a checkbox
BOOL_ATTRS = {
    'Enabled', 'InUse', 'Hidden', 'Frozen', 'External', 'Exportable', 'MissionLayer',
    'MissionLayerActiveDflt', 'IsCategory', 'Projected', 'Smooth', 'Underground',
}

_TAB_FOR_SECTION = [
    ('Environment', 'Environment', '🌤'),
    ('Layers', 'Terrain Layers', '🏔'),
    ('Grids', 'Grids', '🗺'),
    ('MissionsDef', 'Missions', '🎯'),
]

# Dunia binary-XML codec (tools/convert_avatar_xml.py). Some .game.xml files
# ship decoded as text (Avatar's unpacked data) and some ship compiled as the
# binary "00 00" format (Far Cry 2). We decode/encode transparently so both
# games round-trip.
_CODEC = None


def _codec():
    global _CODEC
    if _CODEC is not None:
        return _CODEC or None
    try:
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'tools', 'convert_avatar_xml.py')
        spec = importlib.util.spec_from_file_location('convert_avatar_xml', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _CODEC = mod
    except Exception:
        _CODEC = False
    return _CODEC or None


def _meta_attr_names():
    c = _codec()
    try:
        return set(c._META_ATTRS) if c else {'avx_type'}
    except Exception:
        return {'avx_type'}


def _read_manager_presets(managers_xml_path):
    """Return {classname: [(nameid, guid), ...]} from a managers.xml, keyed by
    the environment class. Streaming regex (the file is large)."""
    catalog = {}
    if not managers_xml_path or not os.path.isfile(managers_xml_path):
        return catalog
    re_name = re.compile(r'name="text_NameId" value-String="([^"]*)"')
    re_tmpl = re.compile(r'name="text_Template" value-String="(\{[0-9A-Fa-f-]+\})"')
    re_cls = re.compile(r'name="text_hid_DTCTH_ClassName" value-String="([^"]*)"')
    last_name = None
    pending = None
    try:
        with open(managers_xml_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                m = re_name.search(line)
                if m:
                    last_name = m.group(1)
                    continue
                m = re_tmpl.search(line)
                if m:
                    pending = (m.group(1), last_name)
                    continue
                m = re_cls.search(line)
                if m and pending:
                    cls = m.group(1)
                    catalog.setdefault(cls, []).append((pending[1] or '(unnamed)', pending[0]))
                    pending = None
    except OSError:
        pass
    for cls in catalog:
        catalog[cls] = sorted(set(catalog[cls]), key=lambda t: t[0].lower())
    return catalog


class WorldEditorWindow(QDialog):
    """Editor for a level's WorldDescriptor (.game.xml)."""

    AUTOSAVE_MS = 900

    def __init__(self, parent, game_xml_path, managers_xml_path=None,
                 game_mode='avatar', canvas=None):
        super().__init__(parent)
        self.canvas = canvas
        self.game_mode = game_mode
        self.game_xml_path = game_xml_path
        if managers_xml_path is None and game_xml_path:
            managers_xml_path = game_xml_path.replace('.game.xml', '.managers.xml')
        self.managers_xml_path = managers_xml_path

        self.tree = None
        self.root = None
        self.presets = {}
        self._binary = False       # source was Dunia binary-XML (FC2) vs text (Avatar)
        self._ai_rml = False       # AI/rml variant of the binary format
        self._meta_attrs = _meta_attr_names()
        self._tex_loader = None     # lazy canvas.texture_loader.TextureLoader
        self._thumb_cache = {}      # (rel, is_normal, size) -> QPixmap|None
        self._dirty = False
        self._rows = []      # (search_text, label, widget, group)
        self._groups = []
        self._backup_made = False

        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.timeout.connect(self.save)

        self.setWindowTitle("World Editor")
        self.setMinimumSize(760, 560)
        self.resize(1000, 820)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setStyleSheet(
            "QDialog { background: #1e1e28; }"
            "QLabel { color: #c8c8d4; }"
            "QGroupBox { color: #9aa4d0; border: 1px solid #34344a; border-radius: 4px;"
            " margin-top: 8px; font-weight: bold; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
            "QLineEdit, QComboBox, QPlainTextEdit { background: #262633; color: #e0e0ea;"
            " border: 1px solid #3a3a4e; border-radius: 3px; padding: 2px 4px; font-size: 11px; }"
            "QComboBox QAbstractItemView { background: #262633; color: #e0e0ea;"
            " selection-background-color: #0078d7; }"
            "QPushButton { background: #2a3a4a; color: #cfe0f0; border: 1px solid #3a4a5a;"
            " border-radius: 3px; padding: 4px 10px; }"
            "QPushButton:hover { background: #35506a; }"
            "QTabBar::tab { background: #23232f; color: #b8b8c8; padding: 5px 12px; }"
            "QTabBar::tab:selected { background: #2f2f45; color: #ffffff; }"
        )

        self._build_ui()
        if game_xml_path:
            self.load(game_xml_path)

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(5)

        # Header
        header = QHBoxLayout()
        self._title = QLabel("No world file loaded")
        self._title.setFont(QFont("Arial", 12, QFont.Bold))
        self._status = QLabel("")
        self._status.setStyleSheet("color: #7a7a90; font-size: 10px;")
        load_btn = QPushButton("Open .game.xml…")
        load_btn.clicked.connect(self._browse)
        self._save_btn = QPushButton("Save")
        self._save_btn.clicked.connect(self.save)
        header.addWidget(self._title)
        header.addStretch()
        header.addWidget(self._status)
        header.addWidget(load_btn)
        header.addWidget(self._save_btn)
        root.addLayout(header)

        # Search
        search_row = QHBoxLayout()
        s_lbl = QLabel("Search:")
        s_lbl.setStyleSheet("color: #888; font-size: 10px;")
        s_lbl.setFixedWidth(46)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter fields across all tabs…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_search)
        search_row.addWidget(s_lbl)
        search_row.addWidget(self._search)
        root.addLayout(search_row)

        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs, 1)

    # ------------------------------------------------------------------ load

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open WorldDescriptor", "", "Game XML (*.game.xml);;All files (*)")
        if path:
            self.managers_xml_path = path.replace('.game.xml', '.managers.xml')
            self.load(path)

    def load(self, path):
        self._binary = False
        self._ai_rml = False
        try:
            with open(path, 'rb') as f:
                data = f.read()
            codec = _codec()
            is_ai = bool(codec and hasattr(codec, 'is_ai_rml') and codec.is_ai_rml(data))
            if codec and (is_ai or data[:2] == b'\x00\x00'):
                # compiled Dunia binary-XML (Far Cry 2 ships these)
                if is_ai:
                    self.root = codec.decode_ai_rml(data)
                    self._ai_rml = True
                else:
                    self.root = codec.decode(data)
                self._binary = True
                self.tree = ET.ElementTree(self.root)
            else:
                # plain-text XML (Avatar's unpacked data)
                self.tree = ET.parse(path)
                self.root = self.tree.getroot()
        except Exception as e:
            QMessageBox.critical(self, "Parse error", f"Could not read:\n{path}\n\n{e}")
            return
        self.game_xml_path = path
        self._backup_made = False
        self.presets = _read_manager_presets(self.managers_xml_path)
        npresets = sum(len(v) for v in self.presets.values())
        fmt = "binary" if self._binary else "text"
        self._title.setText(f"🌍 {os.path.basename(path)}")
        mgr = os.path.basename(self.managers_xml_path) if self.managers_xml_path and os.path.isfile(self.managers_xml_path) else "none"
        self._set_status(f"{fmt} · {npresets} presets from {mgr}")
        self._rebuild_tabs()

    def _rebuild_tabs(self):
        self.tabs.clear()
        self._rows = []
        self._groups = []
        for tag, label, icon in _TAB_FOR_SECTION:
            el = self.root.find(tag) if self.root is not None else None
            if el is None:
                continue
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            body = QWidget()
            vbox = QVBoxLayout(body)
            vbox.setAlignment(Qt.AlignTop)
            vbox.setContentsMargins(6, 6, 6, 6)
            vbox.setSpacing(4)
            self._render_element(vbox, el, top=True)
            vbox.addStretch()
            scroll.setWidget(body)
            self.tabs.addTab(scroll, f"{icon} {label}")

        # Raw XML tab
        raw = QWidget()
        rl = QVBoxLayout(raw)
        rl.setContentsMargins(6, 6, 6, 6)
        self._raw = QPlainTextEdit()
        self._raw.setFont(QFont("Consolas", 9))
        self._raw.setPlainText(self._serialize())
        apply_row = QHBoxLayout()
        apply_row.addStretch()
        apply_btn = QPushButton("Apply raw XML")
        apply_btn.setToolTip("Parse the text above and replace the form contents")
        apply_btn.clicked.connect(self._apply_raw)
        apply_row.addWidget(apply_btn)
        rl.addWidget(self._raw, 1)
        rl.addLayout(apply_row)
        self.tabs.addTab(raw, "＜／＞ Raw XML")

    # -------------------------------------------------------- form rendering

    def _render_element(self, vbox, elem, top=False):
        """Render one element as a titled group: its attributes become rows,
        its child elements recurse into nested groups."""
        title = elem.tag
        name_attr = elem.get('Name') or elem.get('name')
        if name_attr:
            title = f"{elem.tag} — {name_attr}"

        group = QGroupBox(title)
        gv = QVBoxLayout(group)
        gv.setContentsMargins(8, 6, 8, 8)
        gv.setSpacing(3)

        # Terrain Layer -> live XBT thumbnail previews at the top of the group
        tex_targets = {}
        if elem.tag == 'Layer':
            tex_targets = self._build_layer_previews(gv, elem)

        attrs = [(k, v) for k, v in elem.attrib.items()
                 if k not in self._meta_attrs]
        if attrs:
            grid = QGridLayout()
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(3)
            grid.setColumnStretch(1, 1)
            r = 0
            for name, value in attrs:
                lbl = QLabel(self._fmt(name) + ":")
                lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                lbl.setToolTip(name)
                lbl.setStyleSheet("font-size: 11px;")
                widget = self._make_widget(elem, name, value)
                # editing a texture path live-refreshes its thumbnail
                if name in tex_targets and isinstance(widget, QLineEdit):
                    self._wire_texture_live(widget, *tex_targets[name])
                grid.addWidget(lbl, r, 0)
                grid.addWidget(widget, r, 1)
                self._rows.append((f"{name} {value}".lower(), lbl, widget, group))
                r += 1
            gv.addLayout(grid)

        for child in list(elem):
            self._render_element(gv, child)

        vbox.addWidget(group)
        self._groups.append(group)

    def _make_widget(self, elem, name, value):
        # Environment preset slot -> dropdown of presets of the mapped class.
        # ONLY for known environment slot names holding a GUID (or the zero
        # GUID). Other GUID-valued attributes (Mission GUID, layer ids, PathId)
        # are left as plain text — they are not environment presets.
        cls = SLOT_CLASS.get(name)
        if cls and (GUID_RE.match(value) or value == ZERO_GUID):
            return self._make_preset_combo(elem, name, value, cls)
        # 0/1 boolean -> checkbox
        if name in BOOL_ATTRS and value in ('0', '1'):
            cb = QCheckBox()
            cb.setChecked(value == '1')
            cb.stateChanged.connect(
                lambda st, e=elem, n=name: self._set(e, n, '1' if st else '0'))
            return cb
        # r,g,b color -> swatch button + text
        if COLOR_RE.match(value):
            return self._make_color_widget(elem, name, value)
        # default: text
        le = QLineEdit(value)
        le.textChanged.connect(lambda t, e=elem, n=name: self._set(e, n, t))
        return le

    def _make_preset_combo(self, elem, name, value, cls):
        combo = QComboBox()
        combo.addItem("(none)", ZERO_GUID)
        options = self.presets.get(cls, []) if cls else []
        if not options and not cls:
            # unknown slot class: offer every preset, labelled by class
            for c, items in sorted(self.presets.items()):
                for nm, g in items:
                    combo.addItem(f"[{c[11:]}] {nm}", g)
        else:
            for nm, g in options:
                combo.addItem(nm, g)
        # select current
        idx = combo.findData(value)
        if idx < 0:
            combo.addItem(f"(unknown) {value}", value)
            idx = combo.count() - 1
        combo.setCurrentIndex(idx)
        combo.currentIndexChanged.connect(
            lambda _i, e=elem, n=name, c=combo: self._set(e, n, c.currentData()))
        combo.setToolTip(f"{name}: preset GUID (class {cls or '?'})")
        return combo

    def _make_color_widget(self, elem, name, value):
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        swatch = QPushButton()
        swatch.setFixedSize(24, 20)
        le = QLineEdit(value)
        le.setToolTip("r,g,b (0-255)")

        def _parse(v):
            try:
                r, g, b = [max(0, min(255, int(x))) for x in v.split(',')[:3]]
                return r, g, b
            except Exception:
                return 128, 128, 128

        def _paint(v):
            r, g, b = _parse(v)
            swatch.setStyleSheet(
                f"background: rgb({r},{g},{b}); border: 1px solid #555; border-radius: 3px;")

        def _pick():
            r, g, b = _parse(le.text())
            col = QColorDialog.getColor(QColor(r, g, b), self, "Pick color")
            if col.isValid():
                le.setText(f"{col.red()},{col.green()},{col.blue()}")

        def _changed(t):
            _paint(t)
            self._set(elem, name, t)

        swatch.clicked.connect(_pick)
        le.textChanged.connect(_changed)
        _paint(value)
        h.addWidget(swatch)
        h.addWidget(le, 1)
        return wrap

    # --------------------------------------------------- terrain XBT previews

    def _build_layer_previews(self, gv, elem):
        """Add a row of XBT thumbnails for a <Layer>. Returns
        {attr_name: (thumb_label, is_normal)} for live refresh wiring."""
        present = [(n, cap, isn) for n, cap, isn in _TEX_SLOTS
                   if (elem.get(n) or '').strip().lower().endswith('.xbt')]
        if not present:
            return {}
        targets = {}
        row = QHBoxLayout()
        row.setSpacing(10)
        row.setContentsMargins(2, 2, 2, 4)
        for name, cap, is_normal in present:
            col = QVBoxLayout()
            col.setSpacing(2)
            thumb = QLabel()
            thumb.setFixedSize(_THUMB_PX, _THUMB_PX)
            thumb.setAlignment(Qt.AlignCenter)
            thumb.setStyleSheet(
                "background: #15151e; border: 1px solid #34344a; border-radius: 4px;"
                " color: #666; font-size: 9px;")
            self._refresh_thumb(thumb, elem.get(name), is_normal)
            cap_lbl = QLabel(cap)
            cap_lbl.setAlignment(Qt.AlignCenter)
            cap_lbl.setStyleSheet("color: #8a9a8a; font-size: 9px; font-weight: normal;")
            col.addWidget(thumb, 0, Qt.AlignCenter)
            col.addWidget(cap_lbl)
            row.addLayout(col)
            targets[name] = (thumb, is_normal)
        row.addStretch()
        gv.addLayout(row)
        return targets

    def _wire_texture_live(self, line_edit, thumb, is_normal):
        """Debounced: re-render *thumb* from *line_edit*'s text as the user edits."""
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(400)
        timer.timeout.connect(
            lambda: self._refresh_thumb(thumb, line_edit.text(), is_normal))
        line_edit.textChanged.connect(lambda _t: timer.start())
        thumb._we_timer = timer  # keep a ref so it isn't GC'd

    def _refresh_thumb(self, thumb, rel, is_normal):
        pix = self._texture_pixmap(rel, is_normal, _THUMB_PX)
        if pix is not None and not pix.isNull():
            thumb.setPixmap(pix)
            thumb.setToolTip(self._resolve_texture(rel) or rel)
        else:
            thumb.setPixmap(QPixmap())
            thumb.setText("not found" if (rel or '').strip() else "—")
            thumb.setToolTip(rel or "")

    def _texture_pixmap(self, rel, is_normal, size):
        key = (rel, is_normal, size)
        if key in self._thumb_cache:
            return self._thumb_cache[key]
        pix = None
        path = self._resolve_texture(rel)
        if path:
            try:
                tl = self._texloader()
                dec = tl.decode_xbt_to_rgba(path, is_normal_map=is_normal) if tl else None
                if dec:
                    w, h, rgba, _ = dec
                    img = QImage(bytes(rgba), w, h, QImage.Format_RGBA8888)
                    pix = QPixmap.fromImage(img).scaled(
                        size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            except Exception:
                pix = None
        self._thumb_cache[key] = pix
        return pix

    def _texloader(self):
        if self._tex_loader is not None:
            return self._tex_loader or None
        try:
            from canvas.texture_loader import TextureLoader
            root = next(iter(self._candidate_roots()), '') or ''
            self._tex_loader = TextureLoader(os.path.join(root, 'graphics', '_materials'))
        except Exception:
            self._tex_loader = False
        return self._tex_loader or None

    def _candidate_roots(self):
        """Directories to try as the base for a `graphics\\...\\x.xbt` path:
        the canvas' game data path, then every ancestor of the .game.xml."""
        roots = []
        if self.canvas is not None:
            for a in ('game_data_path', 'patch_folder', 'worlds_folder'):
                v = getattr(self.canvas, a, None)
                if v:
                    roots.append(v)
        d = os.path.dirname(os.path.abspath(self.game_xml_path or '.'))
        for _ in range(8):
            roots.append(d)
            nd = os.path.dirname(d)
            if nd == d:
                break
            d = nd
        seen, out = set(), []
        for r in roots:
            if r and r not in seen:
                seen.add(r)
                out.append(r)
        return out

    def _resolve_texture(self, rel):
        if not rel:
            return None
        rel = rel.strip().replace('\\', '/').lstrip('/')
        if not rel.lower().endswith('.xbt'):
            return None
        parts = rel.split('/')
        for root in self._candidate_roots():
            cand = os.path.join(root, *parts)
            if os.path.isfile(cand):
                return cand
        return None

    # ------------------------------------------------------------- edit/save

    def _set(self, elem, name, value):
        elem.set(name, value)
        self._touch()

    def _touch(self):
        self._dirty = True
        self._set_status("● unsaved", warn=True)
        self._autosave.start(self.AUTOSAVE_MS)

    def _serialize(self):
        try:
            ET.indent(self.root, space='  ')
        except Exception:
            pass
        return ET.tostring(self.root, encoding='unicode')

    def save(self):
        if self.root is None or not self.game_xml_path:
            return
        try:
            if not self._backup_made and os.path.isfile(self.game_xml_path):
                bak = self.game_xml_path + '.bak'
                if not os.path.isfile(bak):
                    shutil.copy2(self.game_xml_path, bak)
                self._backup_made = True
            xml_text = self._serialize()
            if self._binary:
                # re-compile to Dunia binary-XML (FC2). encode() ignores element
                # text/tail, so our pretty-print indentation is harmless.
                codec = _codec()
                if codec is None:
                    raise RuntimeError("binary codec (convert_avatar_xml) unavailable")
                blob = codec.encode_ai_rml(self.root) if self._ai_rml else codec.encode(self.root)
                with open(self.game_xml_path, 'wb') as f:
                    f.write(blob)
            else:
                # BOM + UTF-8, no <?xml?> declaration (matches Avatar's own files)
                with open(self.game_xml_path, 'wb') as f:
                    f.write(b'\xef\xbb\xbf' + xml_text.encode('utf-8'))
            self._dirty = False
            if hasattr(self, '_raw'):
                self._raw.blockSignals(True)
                self._raw.setPlainText(xml_text)
                self._raw.blockSignals(False)
            self._set_status("✓ saved (binary)" if self._binary else "✓ saved")
        except Exception as e:
            self._set_status(f"save failed: {e}", warn=True)

    def _apply_raw(self):
        try:
            new_root = ET.fromstring(self._raw.toPlainText())
        except Exception as e:
            QMessageBox.warning(self, "Invalid XML", f"Could not parse the raw XML:\n{e}")
            return
        self.root = new_root
        self.tree = ET.ElementTree(new_root)
        self._touch()
        self._rebuild_tabs()

    # --------------------------------------------------------------- search

    def _apply_search(self, text):
        q = text.strip().lower()
        for search_text, lbl, widget, group in self._rows:
            show = (q in search_text) if q else True
            lbl.setVisible(show)
            widget.setVisible(show)
        for group in self._groups:
            any_visible = any(
                w.isVisible() for st, l, w, g in self._rows if g is group)
            # keep groups with child-only content visible when query empty
            group.setVisible(any_visible or not q)

    # ---------------------------------------------------------------- misc

    @staticmethod
    def _fmt(name):
        s = re.sub(r'(?<!^)(?=[A-Z])', ' ', name)
        return s[:1].upper() + s[1:]

    def _set_status(self, text, warn=False):
        self._status.setText(text)
        self._status.setStyleSheet(
            "color: %s; font-size: 10px;" % ('#e0a030' if warn else '#7a7a90'))

    def closeEvent(self, event):
        if self._dirty:
            self.save()
        super().closeEvent(event)


def show_world_editor(parent, game_xml_path, managers_xml_path=None,
                      game_mode='avatar', canvas=None):
    dlg = WorldEditorWindow(parent, game_xml_path, managers_xml_path,
                            game_mode=game_mode, canvas=canvas)
    dlg.show()
    return dlg
