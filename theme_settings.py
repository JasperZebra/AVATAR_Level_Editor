# theme_settings.py
"""
Theme Settings Manager for Level Editor
Handles saving and loading user theme preferences.

Also the ONE place dialogs get their theme from: every dialog/tool window must
call `apply_dialog_theme(self)` (see below) instead of hardcoding a dark or
light look, so the whole app follows the user's Light/Dark Mode preference.
"""

import json
import os


def _safe_print(msg):
    """Console-safe print: glyphs like ✓/⚠/🌙 raise UnicodeEncodeError on a
    cp1252 stdout (and print can fail entirely under pythonw/frozen builds
    where stdout is None). Theme loading must NEVER die on a log line — it
    runs inside dialog constructors."""
    try:
        print(msg)
    except Exception:
        try:
            print(msg.encode('ascii', 'replace').decode('ascii'))
        except Exception:
            pass


class ThemeSettings:
    """Manages theme preferences with JSON persistence"""
    
    def __init__(self, config_file="editor_config.json"):
        self.config_file = config_file
        self.settings = self._load_settings()
    
    def _load_settings(self):
        """Load settings from JSON file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    settings = json.load(f)
                    _safe_print(f"✓ Loaded theme settings from {self.config_file}")
                    return settings
        except Exception as e:
            _safe_print(f"⚠ Could not load settings: {e}")
        
        # Return default settings
        return {
            'force_dark_theme': False,
            'show_welcome': True
        }
    
    def _save_settings(self):
        """Save settings to JSON file.

        Merge-writes: re-reads the file and overlays this class's keys on top,
        so keys written by other components (e.g. the canvas's 'render_tier')
        are never clobbered by this class's startup snapshot."""
        try:
            on_disk = {}
            if os.path.exists(self.config_file):
                try:
                    with open(self.config_file, 'r') as f:
                        on_disk = json.load(f) or {}
                except Exception:
                    on_disk = {}
            on_disk.update(self.settings)
            self.settings = on_disk
            with open(self.config_file, 'w') as f:
                json.dump(self.settings, f, indent=4)
            _safe_print(f"✓ Saved theme settings to {self.config_file}")
            return True
        except Exception as e:
            _safe_print(f"⚠ Could not save settings: {e}")
            return False
    
    def get_dark_theme(self):
        """Get dark theme preference"""
        return self.settings.get('force_dark_theme', False)
    
    def set_dark_theme(self, enabled):
        """Set dark theme preference and save"""
        self.settings['force_dark_theme'] = enabled
        self._save_settings()
        _safe_print(f"{'🌙' if enabled else '☀️'} Theme set to {'Dark' if enabled else 'Light'} mode")
    
    def get_show_welcome(self):
        """Get show welcome screen preference"""
        return self.settings.get('show_welcome', True)

    def set_show_welcome(self, enabled):
        """Set show welcome screen preference and save"""
        self.settings['show_welcome'] = enabled
        self._save_settings()


# ===========================================================================
# App-wide dialog theming
# ===========================================================================
# Every dialog and tool window follows the user's Light/Dark preference via
# apply_dialog_theme(self). Colors match the main window's apply_theme()
# palette (#2b2b2b dark / #f0f0f0 light) so child windows read as one app.

_DARK = {
    'bg': '#2b2b2b', 'bg2': '#353535', 'bg3': '#404040', 'edit_bg': '#1e1e1e',
    'fg': '#ffffff', 'fg_dim': '#aaaaaa', 'border': '#555555',
    'sel': '#094771', 'sel_fg': '#ffffff', 'alt': '#323232',
}
_LIGHT = {
    'bg': '#f0f0f0', 'bg2': '#ffffff', 'bg3': '#e0e0e0', 'edit_bg': '#ffffff',
    'fg': '#000000', 'fg_dim': '#555555', 'border': '#b0b0b0',
    'sel': '#cce8ff', 'sel_fg': '#000000', 'alt': '#f7f7f7',
}

_DIALOG_QSS = """
QDialog, QWidget {{ background-color: {bg}; color: {fg}; }}
QGroupBox {{
    background-color: {bg2}; border: 1px solid {border}; border-radius: 5px;
    margin-top: 10px; padding-top: 10px; color: {fg};
}}
QGroupBox::title {{ color: {fg}; subcontrol-origin: margin;
    subcontrol-position: top left; padding: 2px 5px; }}
QLabel {{ color: {fg}; background-color: transparent; }}
QPushButton {{
    background-color: {bg3}; color: {fg}; border: 1px solid {border};
    border-radius: 3px; padding: 4px 8px;
}}
QPushButton:hover {{ background-color: {sel}; }}
QPushButton:pressed {{ background-color: {bg2}; }}
QPushButton:disabled {{ color: {fg_dim}; }}
QPushButton:checked {{ background-color: #0078d7; color: #ffffff; border: 1px solid #005a9e; }}
QLineEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {edit_bg}; color: {fg}; border: 1px solid {border};
    border-radius: 3px; padding: 2px 4px; selection-background-color: {sel};
    selection-color: {sel_fg};
}}
QComboBox {{
    background-color: {edit_bg}; color: {fg}; border: 1px solid {border};
    border-radius: 3px; padding: 2px 4px;
}}
QComboBox QAbstractItemView {{
    background-color: {bg2}; color: {fg}; selection-background-color: {sel};
    selection-color: {sel_fg};
}}
QTreeWidget, QListWidget, QTableWidget {{
    background-color: {edit_bg}; alternate-background-color: {alt};
    color: {fg}; border: 1px solid {border};
    selection-background-color: {sel}; selection-color: {sel_fg};
}}
QTreeWidget::item:selected, QListWidget::item:selected {{
    background-color: {sel}; color: {sel_fg};
}}
QHeaderView::section {{
    background-color: {bg2}; color: {fg}; border: none;
    border-right: 1px solid {border}; border-bottom: 1px solid {border};
    padding: 3px 6px;
}}
QTextEdit, QPlainTextEdit {{
    background-color: {edit_bg}; color: {fg}; border: 1px solid {border};
    selection-background-color: {sel}; selection-color: {sel_fg};
}}
QTabWidget::pane {{ border: 1px solid {border}; background-color: {bg}; }}
QTabBar::tab {{
    background-color: {bg2}; color: {fg_dim}; padding: 5px 14px;
    border: 1px solid {border}; border-bottom: none;
    border-top-left-radius: 3px; border-top-right-radius: 3px;
}}
QTabBar::tab:selected {{ background-color: {bg3}; color: {fg}; }}
QTabBar::tab:hover {{ background-color: {sel}; }}
QCheckBox, QRadioButton {{ color: {fg}; background: transparent; }}
QProgressBar {{
    background-color: {bg2}; border: 1px solid {border}; border-radius: 3px;
    color: {fg}; text-align: center;
}}
QProgressBar::chunk {{ background-color: #0078d7; }}
QMenu {{ background-color: {bg}; color: {fg}; border: 1px solid {border}; }}
QMenu::item:selected {{ background-color: {sel}; color: {sel_fg}; }}
QSplitter::handle {{ background-color: {bg2}; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: {bg}; width: 12px; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 4px; min-height: 24px; }}
QScrollBar:horizontal {{ background: {bg}; height: 12px; }}
QScrollBar::handle:horizontal {{ background: {border}; border-radius: 4px; min-width: 24px; }}
"""


def is_dark_theme(widget=None):
    """The user's current theme. Prefers the live main window's
    force_dark_theme (walks up widget parents); falls back to the saved
    preference in editor_config.json."""
    w = widget
    try:
        while w is not None:
            if hasattr(w, 'force_dark_theme'):
                return bool(w.force_dark_theme)
            w = w.parent() if callable(getattr(w, 'parent', None)) else None
    except Exception:
        pass
    try:
        return ThemeSettings().get_dark_theme()
    except Exception:
        return False   # theme resolution must never crash a dialog constructor


def dialog_stylesheet(dark):
    """The app-wide dialog stylesheet for the given theme."""
    return _DIALOG_QSS.format(**(_DARK if dark else _LIGHT))


def theme_colors(dark):
    """The raw palette dict — for dialogs that need individual colors
    (e.g. per-item foregrounds in trees)."""
    return dict(_DARK if dark else _LIGHT)


def apply_dialog_theme(widget, dark=None):
    """Style a dialog/tool window to the user's theme. Call once after the
    dialog's UI is built. Tags the widget so the main window's theme toggle
    can re-theme every open window live. Returns the dark flag used."""
    if dark is None:
        dark = is_dark_theme(widget)
    widget.setStyleSheet(dialog_stylesheet(dark))
    widget._theme_dialog = True
    # Dialog-specific extra styling hook: a _retheme(dark) method is called on
    # theme changes so per-item colors etc. can follow the switch.
    if hasattr(widget, '_retheme'):
        try:
            widget._retheme(dark)
        except Exception:
            pass
    return dark


def retheme_open_windows(dark):
    """Re-apply the theme to every open themed window (main-window toggle)."""
    try:
        from PyQt5.QtWidgets import QApplication
        for w in QApplication.topLevelWidgets():
            if getattr(w, '_theme_dialog', False):
                apply_dialog_theme(w, dark)
    except Exception:
        pass
    
