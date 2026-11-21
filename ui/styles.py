"""Themes: colour palettes, Qt stylesheet and palette application."""

from __future__ import annotations

import tempfile
from pathlib import Path
from string import Template

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from app.signals import signals

FONT_FAMILY = '"Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue", sans-serif'

PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#0E1015", "sidebar": "#12151B", "card": "#181C24", "card_alt": "#1F242E",
        "input": "#11141A", "border": "#272D39", "hover": "#222836",
        "text": "#E9ECF2", "text_dim": "#9BA4B5",
        "accent": "#4C8DFF", "accent_hover": "#6A9FFF", "accent_press": "#3A7AEB",
        "accent_soft": "rgba(76,141,255,0.16)", "on_accent": "#FFFFFF",
        "danger": "#FF6B7A", "danger_soft": "rgba(255,107,122,0.14)",
        "success": "#3DD68C", "success_soft": "rgba(61,214,140,0.14)",
        "chip": "#222836", "scroll": "#2E3544", "scroll_hover": "#3B4458",
        "disabled_bg": "#232836", "disabled_text": "#5E6678",
        "toggle_off": "#3A4152", "thumb_bg": "#12151B",
    },
    "light": {
        "bg": "#F2F4F8", "sidebar": "#FAFBFD", "card": "#FFFFFF", "card_alt": "#F3F5F9",
        "input": "#F7F8FB", "border": "#E0E4EC", "hover": "#ECEFF5",
        "text": "#171B24", "text_dim": "#5D687B",
        "accent": "#2F6FED", "accent_hover": "#4A82F2", "accent_press": "#255DD0",
        "accent_soft": "rgba(47,111,237,0.12)", "on_accent": "#FFFFFF",
        "danger": "#D6334A", "danger_soft": "rgba(214,51,74,0.10)",
        "success": "#17935B", "success_soft": "rgba(23,147,91,0.12)",
        "chip": "#EEF1F6", "scroll": "#C9CFDB", "scroll_hover": "#B3BBCB",
        "disabled_bg": "#E6E9F0", "disabled_text": "#9AA3B2",
        "toggle_off": "#C4CAD6", "thumb_bg": "#E9ECF3",
    },
}

_current: str = "dark"


def current_theme() -> str:
    """Name of the theme currently applied."""
    return _current


def get_palette(theme: str | None = None) -> dict[str, str]:
    """Colour tokens for ``theme`` (defaults to the active theme)."""
    return PALETTES[theme or _current]


_QSS = Template(
    """
QWidget { font-family: $font; font-size: 13px; color: $text; }
QWidget#Root { background: $bg; }
QDialog, QMessageBox { background: $bg; }
QToolTip { background: $card; color: $text; border: 1px solid $border; padding: 6px 8px; border-radius: 6px; }

/* ---- sidebar ---- */
QFrame#Sidebar { background: $sidebar; border: none; border-right: 1px solid $border; }
QLabel#BrandName { font-size: 16px; font-weight: 700; }
QLabel#BrandSub { font-size: 11px; color: $text_dim; }
QLabel#SidebarFooter { font-size: 11px; color: $text_dim; padding-left: 6px; }
QPushButton#NavButton {
    text-align: left; padding: 11px 14px; border: none; border-radius: 10px;
    background: transparent; color: $text_dim; font-weight: 500;
}
QPushButton#NavButton:hover { background: $hover; color: $text; }
QPushButton#NavButton:checked { background: $accent_soft; color: $accent; font-weight: 600; }

/* ---- typography ---- */
QLabel#Title { font-size: 26px; font-weight: 700; }
QLabel#Subtitle { font-size: 13px; color: $text_dim; }
QLabel#CardTitle { font-size: 15px; font-weight: 600; }
QLabel#RowTitle { font-size: 13px; font-weight: 600; }
QLabel#Dim { font-size: 12px; color: $text_dim; }
QLabel#MediaTitle { font-size: 18px; font-weight: 700; }
QLabel#Error { color: $danger; font-size: 12px; }
QLabel#Dim[state="bad"] { color: $danger; }
QLabel#Dim[state="ok"] { color: $success; }
QLabel[state="ok"] { color: $success; }
QLabel[state="bad"] { color: $danger; }
QLabel#Chip {
    background: $chip; color: $text_dim; border-radius: 8px;
    padding: 4px 10px; font-size: 12px; font-weight: 600;
}
QLabel#Chip[state="ok"] { background: $success_soft; color: $success; }
QLabel#Chip[state="bad"] { background: $danger_soft; color: $danger; }

/* ---- surfaces ---- */
QFrame#Card { background: $card; border: 1px solid $border; border-radius: 14px; }
QFrame#Banner { background: $accent_soft; border: 1px solid $accent; border-radius: 12px; }
QFrame#Divider { background: $border; border: none; min-height: 1px; max-height: 1px; }
QScrollArea { background: transparent; border: none; }
QWidget#ScrollContent { background: transparent; }

/* ---- inputs ---- */
QLineEdit {
    background: $input; border: 1px solid $border; border-radius: 10px;
    padding: 10px 14px; selection-background-color: $accent; selection-color: $on_accent;
}
QLineEdit:focus { border: 1px solid $accent; }
QLineEdit:read-only { color: $text_dim; }
QComboBox {
    background: $input; border: 1px solid $border; border-radius: 10px;
    padding: 8px 12px; min-height: 20px;
}
QComboBox:hover, QComboBox:focus { border: 1px solid $accent; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox::down-arrow { image: url($chevron); width: 12px; height: 12px; }
QComboBox QAbstractItemView {
    background: $card; border: 1px solid $border; outline: 0; padding: 4px;
    selection-background-color: $accent_soft; selection-color: $text;
}
QComboBox QAbstractItemView::item { padding: 7px 10px; min-height: 22px; border-radius: 6px; }

/* ---- buttons ---- */
QPushButton {
    background: $card_alt; border: 1px solid $border; border-radius: 10px;
    padding: 9px 18px; font-weight: 600;
}
QPushButton:hover { background: $hover; }
QPushButton:disabled { color: $disabled_text; }
QPushButton#Primary { background: $accent; color: $on_accent; border: none; }
QPushButton#Primary:hover { background: $accent_hover; }
QPushButton#Primary:pressed { background: $accent_press; }
QPushButton#Primary:disabled { background: $disabled_bg; color: $disabled_text; }
QPushButton#Ghost { background: transparent; color: $text_dim; border: none; }
QPushButton#Ghost:hover { background: $hover; color: $text; }
QPushButton#IconOnly { background: transparent; border: none; padding: 6px; }
QPushButton#IconOnly:hover { background: $hover; }
QPushButton#NavButton { border: none; }

QPushButton#Segment {
    background: transparent; border: none; border-radius: 8px; padding: 6px 18px; color: $text_dim;
}
QPushButton#Segment:hover { color: $text; }
QPushButton#Segment:checked { background: $accent; color: $on_accent; }
QPushButton#Segment:disabled { color: $disabled_text; }
QFrame#SegmentBar { background: $input; border: 1px solid $border; border-radius: 11px; }
QPushButton#DangerGhost { background: transparent; color: $danger; border: none; }
QPushButton#DangerGhost:hover { background: $danger_soft; }

/* ---- progress ---- */
QProgressBar { background: $chip; border: none; border-radius: 4px; min-height: 8px; max-height: 8px; }
QProgressBar::chunk { background: $accent; border-radius: 4px; }
QProgressBar[state="ok"]::chunk { background: $success; }
QProgressBar[state="bad"]::chunk { background: $danger; }
QProgressBar[state="idle"]::chunk { background: $text_dim; }

/* ---- scrollbars ---- */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $scroll; border-radius: 4px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: $scroll_hover; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: $scroll; border-radius: 4px; min-width: 32px; }
QScrollBar::handle:horizontal:hover { background: $scroll_hover; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
"""
)


def _chevron_file(theme: str) -> str:
    """Write (once per run) a small chevron PNG for combo boxes and return its path for QSS."""
    folder = Path(tempfile.gettempdir()) / "QuanttumDownloader"
    path = folder / f"chevron_{theme}.png"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        pm = QPixmap(24, 24)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(PALETTES[theme]["text_dim"]), 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(5, 9), QPointF(12, 16), QPointF(19, 9)])
        p.end()
        pm.save(str(path), "PNG")
    except OSError:
        return ""
    return path.as_posix()


def build_stylesheet(theme: str) -> str:
    """Render the application stylesheet for ``theme``."""
    return _QSS.safe_substitute(PALETTES[theme], font=FONT_FAMILY, chevron=_chevron_file(theme))


def _build_qpalette(theme: str) -> QPalette:
    p = PALETTES[theme]
    pal = QPalette()
    role = QPalette.ColorRole
    pal.setColor(role.Window, QColor(p["bg"]))
    pal.setColor(role.WindowText, QColor(p["text"]))
    pal.setColor(role.Base, QColor(p["input"]))
    pal.setColor(role.AlternateBase, QColor(p["card"]))
    pal.setColor(role.Text, QColor(p["text"]))
    pal.setColor(role.Button, QColor(p["card_alt"]))
    pal.setColor(role.ButtonText, QColor(p["text"]))
    pal.setColor(role.ToolTipBase, QColor(p["card"]))
    pal.setColor(role.ToolTipText, QColor(p["text"]))
    pal.setColor(role.Highlight, QColor(p["accent"]))
    pal.setColor(role.HighlightedText, QColor(p["on_accent"]))
    pal.setColor(role.PlaceholderText, QColor(p["text_dim"]))
    pal.setColor(role.Link, QColor(p["accent"]))
    group = QPalette.ColorGroup.Disabled
    pal.setColor(group, role.Text, QColor(p["disabled_text"]))
    pal.setColor(group, role.ButtonText, QColor(p["disabled_text"]))
    pal.setColor(group, role.WindowText, QColor(p["disabled_text"]))
    return pal


def apply_theme(app: QApplication, theme: str) -> None:
    """Apply ``theme`` to the whole application and notify listeners."""
    global _current
    if theme not in PALETTES:
        theme = "dark"
    _current = theme
    app.setStyle("Fusion")
    app.setPalette(_build_qpalette(theme))
    app.setStyleSheet(build_stylesheet(theme))
    signals.theme_changed.emit(theme)
