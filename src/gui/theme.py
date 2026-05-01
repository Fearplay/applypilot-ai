"""Centralised dark theme for ApplyPilot AI.

The theme is intentionally minimal and modern: pure-black background, slim
borders, calm typography. Inline ``setStyleSheet`` calls in pages should be
removed in favour of the QSS rules below + dynamic properties such as
``button.setProperty("variant", "primary")``.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication


# ---------------------------------------------------------------------------
# Colour tokens
# ---------------------------------------------------------------------------
class Tokens:
    """Single source of truth for the colour palette."""

    bg = "#0a0a0a"
    surface = "#141414"
    surface_alt = "#1a1a1a"
    surface_hover = "#1f1f1f"
    border = "#262626"
    border_strong = "#3a3a3a"

    text = "#ededf0"
    text_muted = "#7d7d87"
    text_dim = "#5a5a63"

    accent = "#3b82f6"
    accent_hover = "#4f8df7"
    accent_pressed = "#2f6fd8"

    success = "#22c55e"
    warn = "#f59e0b"
    danger = "#ef4444"

    chip_demo_bg = "#2a200a"
    chip_demo_fg = "#f59e0b"
    chip_live_bg = "#0d2818"
    chip_live_fg = "#22c55e"
    chip_idle_bg = "#1a1a1a"
    chip_idle_fg = "#7d7d87"
    chip_active_bg = "#10243f"
    chip_active_fg = "#3b82f6"
    chip_done_bg = "#0d2818"
    chip_done_fg = "#22c55e"


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------
def _stylesheet() -> str:
    t = Tokens
    return f"""
/* ---------------------------- base ---------------------------- */
QMainWindow, QDialog, QWidget {{
    background-color: {t.bg};
    color: {t.text};
    font-size: 13px;
}}

QStatusBar {{
    background-color: {t.bg};
    color: {t.text_muted};
    border-top: 1px solid {t.border};
    padding: 2px 10px;
}}

QMenuBar {{
    background-color: {t.bg};
    color: {t.text};
    border-bottom: 1px solid {t.border};
    padding: 2px 4px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 6px 10px;
    border-radius: 4px;
}}
QMenuBar::item:selected {{
    background: {t.surface_hover};
}}
QMenu {{
    background-color: {t.surface};
    color: {t.text};
    border: 1px solid {t.border};
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 18px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: {t.surface_hover};
}}

/* ---------------------------- labels -------------------------- */
QLabel {{
    color: {t.text};
    background: transparent;
}}
QLabel[role="muted"] {{
    color: {t.text_muted};
}}
QLabel[role="dim"] {{
    color: {t.text_dim};
    font-size: 11px;
}}
QLabel[role="title"] {{
    color: {t.text};
    font-size: 22px;
    font-weight: 600;
}}
QLabel[role="subtitle"] {{
    color: {t.text_muted};
    font-size: 13px;
}}
QLabel[role="section-label"] {{
    color: {t.text_muted};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.2px;
}}
QLabel[role="card-title"] {{
    color: {t.text};
    font-size: 15px;
    font-weight: 600;
}}
QLabel[role="card-subtitle"] {{
    color: {t.text_muted};
    font-size: 12px;
}}

/* ---------------------------- buttons ------------------------- */
QPushButton {{
    background-color: {t.surface};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {t.surface_hover};
    border-color: {t.border_strong};
}}
QPushButton:pressed {{
    background-color: {t.surface_alt};
}}
QPushButton:disabled {{
    background-color: {t.surface_alt};
    color: {t.text_dim};
    border-color: {t.border};
}}

QPushButton[variant="primary"] {{
    background-color: {t.accent};
    color: white;
    border: 1px solid {t.accent};
    font-weight: 600;
    padding: 8px 18px;
}}
QPushButton[variant="primary"]:hover {{
    background-color: {t.accent_hover};
    border-color: {t.accent_hover};
}}
QPushButton[variant="primary"]:pressed {{
    background-color: {t.accent_pressed};
    border-color: {t.accent_pressed};
}}
QPushButton[variant="primary"]:disabled {{
    background-color: {t.surface_alt};
    color: {t.text_dim};
    border-color: {t.border};
}}

QPushButton[variant="ghost"] {{
    background-color: transparent;
    color: {t.text_muted};
    border: 1px solid transparent;
    padding: 6px 12px;
}}
QPushButton[variant="ghost"]:hover {{
    color: {t.text};
    background-color: {t.surface};
}}

QPushButton[variant="danger"] {{
    background-color: transparent;
    color: {t.danger};
    border: 1px solid {t.border};
}}
QPushButton[variant="danger"]:hover {{
    background-color: rgba(239, 68, 68, 0.08);
    border-color: {t.danger};
}}

/* ---------------------------- inputs -------------------------- */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: {t.surface};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 6px;
    padding: 7px 10px;
    selection-background-color: {t.accent};
    selection-color: white;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {t.accent};
}}
QLineEdit:disabled, QPlainTextEdit:disabled {{
    color: {t.text_dim};
    background-color: {t.surface_alt};
}}

QComboBox {{
    background-color: {t.surface};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 6px;
    padding: 6px 10px;
}}
QComboBox:hover {{
    border-color: {t.border_strong};
}}
QComboBox QAbstractItemView {{
    background-color: {t.surface};
    color: {t.text};
    border: 1px solid {t.border};
    selection-background-color: {t.surface_hover};
    selection-color: {t.text};
    outline: none;
}}

QRadioButton, QCheckBox {{
    color: {t.text};
    background: transparent;
    spacing: 8px;
}}
QRadioButton::indicator, QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 7px;
    border: 1px solid {t.border_strong};
    background: {t.surface};
}}
QCheckBox::indicator {{
    border-radius: 3px;
}}
QRadioButton::indicator:checked, QCheckBox::indicator:checked {{
    background: {t.accent};
    border-color: {t.accent};
}}

/* ---------------------------- lists --------------------------- */
QListWidget {{
    background-color: {t.surface};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 6px;
    padding: 4px;
    outline: none;
}}
QListWidget::item {{
    padding: 6px 8px;
    border-radius: 4px;
}}
QListWidget::item:hover {{
    background: {t.surface_hover};
}}
QListWidget::item:selected {{
    background: {t.surface_hover};
    color: {t.text};
}}

QTableWidget {{
    background-color: {t.surface};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 6px;
    gridline-color: {t.border};
    selection-background-color: {t.surface_hover};
    selection-color: {t.text};
    alternate-background-color: {t.surface_alt};
    outline: none;
}}
QTableWidget::item {{
    padding: 8px;
    border: none;
}}
QHeaderView::section {{
    background-color: {t.bg};
    color: {t.text_muted};
    border: none;
    border-bottom: 1px solid {t.border};
    padding: 8px;
    font-weight: 600;
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.6px;
}}

/* ---------------------------- tabs ---------------------------- */
QTabWidget::pane {{
    border: 1px solid {t.border};
    border-radius: 8px;
    background: {t.surface};
    top: -1px;
}}
QTabBar {{
    background: transparent;
    qproperty-drawBase: 0;
}}
QTabBar::tab {{
    background: transparent;
    color: {t.text_muted};
    padding: 8px 16px;
    margin-right: 4px;
    border: 1px solid transparent;
    border-radius: 6px;
    font-weight: 500;
}}
QTabBar::tab:hover {{
    color: {t.text};
    background: {t.surface};
}}
QTabBar::tab:selected {{
    color: {t.text};
    background: {t.surface};
    border: 1px solid {t.border};
}}

/* ---------------------------- scroll -------------------------- */
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {t.border_strong};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t.text_dim};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {t.border_strong};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {t.text_dim};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ---------------------------- frames -------------------------- */
QFrame[role="card"] {{
    background-color: {t.surface};
    border: 1px solid {t.border};
    border-radius: 12px;
}}
QFrame[role="card-inner"] {{
    background-color: {t.surface_alt};
    border: 1px solid {t.border};
    border-radius: 8px;
}}
QFrame[role="header"] {{
    background-color: {t.bg};
    border-bottom: 1px solid {t.border};
}}
QFrame[role="sidebar"] {{
    background-color: {t.bg};
    border-right: 1px solid {t.border};
}}
QFrame[role="separator"] {{
    background-color: {t.border};
    max-height: 1px;
}}

/* ---------------------------- splitter ------------------------ */
QSplitter::handle {{
    background-color: {t.border};
    width: 1px;
}}

/* ---------------------------- tooltip ------------------------- */
QToolTip {{
    background-color: {t.surface};
    color: {t.text};
    border: 1px solid {t.border};
    padding: 6px 8px;
    border-radius: 4px;
}}
"""


def apply_theme(app: QApplication) -> None:
    """Apply the centralised dark theme to the running ``QApplication``."""
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(Tokens.bg))
    palette.setColor(QPalette.WindowText, QColor(Tokens.text))
    palette.setColor(QPalette.Base, QColor(Tokens.surface))
    palette.setColor(QPalette.AlternateBase, QColor(Tokens.surface_alt))
    palette.setColor(QPalette.Text, QColor(Tokens.text))
    palette.setColor(QPalette.Button, QColor(Tokens.surface))
    palette.setColor(QPalette.ButtonText, QColor(Tokens.text))
    palette.setColor(QPalette.Highlight, QColor(Tokens.accent))
    palette.setColor(QPalette.HighlightedText, QColor("white"))
    palette.setColor(QPalette.PlaceholderText, QColor(Tokens.text_dim))
    palette.setColor(QPalette.ToolTipBase, QColor(Tokens.surface))
    palette.setColor(QPalette.ToolTipText, QColor(Tokens.text))
    palette.setColor(QPalette.Link, QColor(Tokens.accent))
    app.setPalette(palette)

    base_font = QFont()
    base_font.setFamily("Segoe UI")
    base_font.setPointSize(10)
    app.setFont(base_font)

    app.setStyleSheet(_stylesheet())


__all__ = ["Tokens", "apply_theme"]
