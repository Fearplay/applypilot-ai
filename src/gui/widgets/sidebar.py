"""Slim modern sidebar with section navigation and per-section status chips.

Inspired by the ContentUploader-style left rail: small uppercase label, rows
with title + status pill, accent indicator on the active row.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from ..theme import Tokens
from .status_chip import ChipVariant, StatusChip


@dataclass(frozen=True)
class SidebarItem:
    """A single navigation entry."""

    key: str
    title: str
    subtitle: str = ""


class _SidebarRow(QFrame):
    """Internal clickable row with title, optional subtitle and status chip."""

    clicked = Signal(str)  # emits the key

    def __init__(self, item: SidebarItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._key = item.key
        self._active = False
        self.setObjectName("SidebarRow")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(56)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 8, 12, 8)
        outer.setSpacing(10)

        self._indicator = QFrame(self)
        self._indicator.setFixedWidth(3)
        self._indicator.setMinimumHeight(28)
        self._indicator.setStyleSheet("background: transparent; border-radius: 2px;")
        outer.addWidget(self._indicator)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)
        self._title = QLabel(item.title)
        self._title.setStyleSheet(
            f"color: {Tokens.text}; font-size: 13px; font-weight: 600;"
        )
        text_box.addWidget(self._title)

        if item.subtitle:
            self._subtitle = QLabel(item.subtitle)
            self._subtitle.setStyleSheet(
                f"color: {Tokens.text_dim}; font-size: 11px;"
            )
            text_box.addWidget(self._subtitle)
        else:
            self._subtitle = None
        outer.addLayout(text_box, stretch=1)

        self._chip = StatusChip("Idle", variant="idle", parent=self)
        outer.addWidget(self._chip, alignment=Qt.AlignVCenter)

        self._apply_style()

    # ---------------------------------------------------------------- API
    @property
    def key(self) -> str:
        return self._key

    def set_active(self, active: bool) -> None:
        self._active = active
        self._apply_style()

    def set_status(self, text: str, variant: ChipVariant) -> None:
        self._chip.set_variant(variant, text=text)

    # ---------------------------------------------------------------- helpers
    def _apply_style(self) -> None:
        if self._active:
            self.setStyleSheet(
                f"#SidebarRow {{ background-color: {Tokens.surface}; "
                f"border-radius: 8px; }}"
            )
            self._indicator.setStyleSheet(
                f"background: {Tokens.accent}; border-radius: 2px;"
            )
        else:
            self.setStyleSheet(
                "#SidebarRow { background-color: transparent; border-radius: 8px; }"
                "#SidebarRow:hover { background-color: " + Tokens.surface_alt + "; }"
            )
            self._indicator.setStyleSheet(
                "background: transparent; border-radius: 2px;"
            )

    # ---------------------------------------------------------------- events
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._key)
        super().mousePressEvent(event)


class Sidebar(QFrame):
    """Vertical navigation sidebar."""

    section_clicked = Signal(str)

    def __init__(
        self,
        items: list[SidebarItem],
        title: str = "ApplyPilot",
        section_label: str = "WORKFLOW",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("role", "sidebar")
        self.setMinimumWidth(232)
        self.setMaximumWidth(252)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 18, 14, 14)
        outer.setSpacing(14)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {Tokens.text}; font-size: 16px; font-weight: 700;"
            f" letter-spacing: 0.2px;"
        )
        outer.addWidget(title_lbl)

        section_lbl = QLabel(section_label)
        section_lbl.setProperty("role", "section-label")
        section_lbl.setStyleSheet(
            f"color: {Tokens.text_dim}; font-size: 10px; font-weight: 700;"
            f" letter-spacing: 1.4px; padding-top: 6px;"
        )
        outer.addWidget(section_lbl)

        self._rows: dict[str, _SidebarRow] = {}
        for item in items:
            row = _SidebarRow(item, self)
            row.clicked.connect(self.section_clicked.emit)
            outer.addWidget(row)
            self._rows[item.key] = row

        outer.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))

        footer_lbl = QLabel("Activity")
        footer_lbl.setProperty("role", "section-label")
        footer_lbl.setStyleSheet(
            f"color: {Tokens.text_dim}; font-size: 10px; font-weight: 700;"
            f" letter-spacing: 1.4px;"
        )
        outer.addWidget(footer_lbl)

        self._activity = QLabel("Ready")
        self._activity.setWordWrap(True)
        self._activity.setStyleSheet(
            f"color: {Tokens.text_muted}; font-size: 11px;"
            f" padding: 4px 4px 0 4px;"
        )
        outer.addWidget(self._activity)

    # ---------------------------------------------------------------- public
    def set_active(self, key: str) -> None:
        for row_key, row in self._rows.items():
            row.set_active(row_key == key)

    def set_status(self, key: str, text: str, variant: ChipVariant) -> None:
        row = self._rows.get(key)
        if row is not None:
            row.set_status(text, variant)

    def set_activity(self, text: str) -> None:
        self._activity.setText(text or "Ready")


__all__ = ["Sidebar", "SidebarItem"]
