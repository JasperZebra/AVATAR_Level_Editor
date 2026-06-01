"""Shared UI style helpers for the level editor."""

_CHECKBOX_X_PATH = "temp_checkbox_x.png"
_x_icon_ready = False


def _ensure_x_icon():
    global _x_icon_ready
    if _x_icon_ready:
        return
    try:
        from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor
        from PyQt6.QtCore import Qt
        pix = QPixmap(18, 18)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255), 3, Qt.PenStyle.SolidLine))
        p.drawLine(4, 4, 14, 14)
        p.drawLine(14, 4, 4, 14)
        p.end()
        pix.save(_CHECKBOX_X_PATH)
        _x_icon_ready = True
    except Exception:
        pass


def checkbox_style(dark=None):
    """Return QSS for a custom checkbox with a white X on blue when checked.

    Pass dark=True/False to force a theme; omit to read from editor_config.json.
    """
    if dark is None:
        try:
            from theme_settings import ThemeSettings
            dark = ThemeSettings().get_dark_theme()
        except Exception:
            dark = False
    _ensure_x_icon()
    border = "#ffffff" if dark else "#000000"
    bg = "#2b2b2b" if dark else "#ffffff"
    return (
        "QCheckBox { font-size: 12px; spacing: 5px; }"
        f"QCheckBox::indicator {{ width: 18px; height: 18px;"
        f" border: 2px solid {border}; border-radius: 3px;"
        f" background-color: {bg}; }}"
        f"QCheckBox::indicator:checked {{ background-color: #0078d7;"
        f" border: 2px solid #0078d7; image: url({_CHECKBOX_X_PATH}); }}"
    )


def apply_checkbox_style(checkbox, dark=None):
    """Apply the custom X-mark style to a QCheckBox."""
    checkbox.setStyleSheet(checkbox_style(dark))
