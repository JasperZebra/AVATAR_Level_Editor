"""theme.py - the RTE tool's look, in one place.

Two palettes, dark and light, and one stylesheet builder. Kept out of rte_tool
so the window file stays about behaviour.

The base greys are #2b2b2b / #f0f0f0 on purpose: those are the level editor's
own window colours (tests/test_dialog_theme.py pins them), so this tool reads as
part of the same suite rather than a stray utility. The accent is Pandora teal.
"""

DARK = {
    "name": "dark",
    "bg": "#2b2b2b",          # the editor's window colour
    "panel": "#333333",
    "card": "#3a3a3a",
    "raised": "#454545",
    "border": "#4a4a4a",
    "text": "#e8e8e8",
    "dim": "#9a9a9a",
    "accent": "#2ec4b6",
    "accent_dim": "#1f8b81",
    "accent_text": "#0e1a19",
    "ok": "#4caf50",
    "warn": "#e0a030",
    "bad": "#e05a5a",
    "sel": "#2ec4b6",
    "sel_text": "#0e1a19",
}

LIGHT = {
    "name": "light",
    "bg": "#f0f0f0",          # the editor's light window colour
    "panel": "#e8e8e8",
    "card": "#ffffff",
    "raised": "#fbfbfb",
    "border": "#c8c8c8",
    "text": "#1e1e1e",
    "dim": "#6a6a6a",
    "accent": "#128c80",
    "accent_dim": "#0d6b61",
    "accent_text": "#ffffff",
    "ok": "#2e7d32",
    "warn": "#a86b0a",
    "bad": "#c0392b",
    "sel": "#128c80",
    "sel_text": "#ffffff",
}


def stylesheet(p):
    """Build the full stylesheet from a palette dict."""
    return """
    QWidget {
        background: %(bg)s;
        color: %(text)s;
        font-family: "Segoe UI", system-ui, sans-serif;
        font-size: 10pt;
    }
    QMainWindow, QStatusBar { background: %(bg)s; }
    QStatusBar { color: %(dim)s; border-top: 1px solid %(border)s; }
    QStatusBar::item { border: none; }

    /* ---- header ---- */
    #Header {
        background: %(panel)s;
        border-bottom: 1px solid %(border)s;
    }
    #HeaderTitle { font-size: 13pt; font-weight: 600; }
    #HeaderWorld { color: %(dim)s; font-size: 10pt; }

    /* ---- connection pill ---- */
    #Pill {
        border-radius: 10px;
        padding: 3px 12px;
        font-size: 9pt;
        font-weight: 600;
        background: %(raised)s;
        color: %(dim)s;
    }
    #Pill[state="on"]   { background: %(ok)s;   color: #ffffff; }
    #Pill[state="off"]  { background: %(raised)s; color: %(dim)s; }
    #Pill[state="busy"] { background: %(warn)s; color: #ffffff; }
    #Pill[state="err"]  { background: %(bad)s;  color: #ffffff; }

    /* ---- left nav rail ---- */
    #Nav {
        background: %(panel)s;
        border: none;
        border-right: 1px solid %(border)s;
        outline: 0;
        padding: 8px 0px;
    }
    #Nav::item {
        padding: 11px 18px;
        margin: 2px 8px;
        border-radius: 6px;
        color: %(dim)s;
    }
    #Nav::item:hover    { background: %(card)s; color: %(text)s; }
    #Nav::item:selected { background: %(accent)s; color: %(accent_text)s;
                          font-weight: 600; }
    #Nav::item:disabled { color: %(border)s; }

    /* ---- cards ---- */
    QGroupBox {
        background: %(card)s;
        border: 1px solid %(border)s;
        border-radius: 8px;
        margin-top: 14px;
        padding: 14px 14px 12px 14px;
        font-weight: 600;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0px 6px;
        color: %(accent)s;
    }

    /* ---- buttons ---- */
    QPushButton {
        background: %(raised)s;
        border: 1px solid %(border)s;
        border-radius: 6px;
        padding: 7px 16px;
        min-height: 16px;
    }
    QPushButton:hover    { background: %(card)s; border-color: %(accent)s; }
    QPushButton:pressed  { background: %(accent_dim)s; color: %(accent_text)s; }
    QPushButton:disabled { color: %(border)s; background: %(panel)s;
                           border-color: %(panel)s; }
    QPushButton[accent="1"] {
        background: %(accent)s; color: %(accent_text)s;
        border-color: %(accent)s; font-weight: 600;
    }
    QPushButton[accent="1"]:hover   { background: %(accent_dim)s; }
    QPushButton[accent="1"]:disabled { background: %(panel)s; color: %(border)s;
                                       border-color: %(panel)s; }

    /* ---- inputs ---- */
    QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
        background: %(raised)s;
        border: 1px solid %(border)s;
        border-radius: 6px;
        padding: 6px 8px;
        selection-background-color: %(sel)s;
        selection-color: %(sel_text)s;
    }
    QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
    QDoubleSpinBox:focus, QComboBox:focus { border-color: %(accent)s; }
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
        color: %(border)s; background: %(panel)s;
    }
    QComboBox::drop-down { border: none; width: 18px; }

    /* ---- checkbox ---- */
    QCheckBox { spacing: 8px; }
    QCheckBox::indicator {
        width: 16px; height: 16px;
        border: 1px solid %(border)s; border-radius: 4px;
        background: %(raised)s;
    }
    QCheckBox::indicator:hover   { border-color: %(accent)s; }
    QCheckBox::indicator:checked { background: %(accent)s;
                                   border-color: %(accent)s; }

    /* ---- slider ---- */
    QSlider::groove:horizontal {
        height: 5px; border-radius: 2px; background: %(raised)s;
    }
    QSlider::sub-page:horizontal { background: %(accent)s; border-radius: 2px; }
    QSlider::handle:horizontal {
        width: 15px; height: 15px; margin: -6px 0px;
        border-radius: 8px;
        background: %(accent)s; border: 2px solid %(card)s;
    }
    QSlider::handle:horizontal:hover { background: %(accent_dim)s; }

    /* ---- table ---- */
    QTableWidget {
        background: %(raised)s;
        alternate-background-color: %(card)s;
        border: 1px solid %(border)s;
        border-radius: 6px;
        gridline-color: %(border)s;
        selection-background-color: %(sel)s;
        selection-color: %(sel_text)s;
    }
    QHeaderView::section {
        background: %(panel)s;
        color: %(dim)s;
        border: none;
        border-right: 1px solid %(border)s;
        border-bottom: 1px solid %(border)s;
        padding: 7px 8px;
        font-weight: 600;
    }
    QTableCornerButton::section { background: %(panel)s; border: none; }

    /* ---- scrollbars ---- */
    QScrollBar:vertical {
        background: transparent; width: 11px; margin: 0px;
    }
    QScrollBar::handle:vertical {
        background: %(border)s; border-radius: 5px; min-height: 28px;
    }
    QScrollBar::handle:vertical:hover { background: %(accent_dim)s; }
    QScrollBar:horizontal {
        background: transparent; height: 11px; margin: 0px;
    }
    QScrollBar::handle:horizontal {
        background: %(border)s; border-radius: 5px; min-width: 28px;
    }
    QScrollBar::handle:horizontal:hover { background: %(accent_dim)s; }
    QScrollBar::add-line, QScrollBar::sub-line { height: 0px; width: 0px; }
    QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

    /* ---- misc ---- */
    #Hint { color: %(dim)s; font-size: 9pt; }
    #Mono { font-family: Consolas, "Cascadia Mono", monospace; }
    #Value { font-family: Consolas, "Cascadia Mono", monospace;
             color: %(accent)s; font-size: 10pt; }
    """ % p
