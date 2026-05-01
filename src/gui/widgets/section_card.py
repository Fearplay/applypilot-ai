"""Reusable rounded card with title, subtitle and a content area."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..theme import Tokens


class SectionCard(QFrame):
    """A bordered card used to group related controls on the Setup page."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        eyebrow: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("role", "card")
        self.setStyleSheet(
            f"QFrame[role='card'] {{"
            f"  background-color: {Tokens.surface};"
            f"  border: 1px solid {Tokens.border};"
            f"  border-radius: 12px;"
            f"}}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(14)

        header = QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)

        if eyebrow:
            eyebrow_lbl = QLabel(eyebrow.upper())
            eyebrow_lbl.setStyleSheet(
                f"color: {Tokens.accent}; font-size: 10px; font-weight: 700;"
                f" letter-spacing: 1.2px;"
            )
            header.addWidget(eyebrow_lbl)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {Tokens.text}; font-size: 16px; font-weight: 600;"
        )
        header.addWidget(title_lbl)

        if subtitle:
            sub_lbl = QLabel(subtitle)
            sub_lbl.setWordWrap(True)
            sub_lbl.setStyleSheet(
                f"color: {Tokens.text_muted}; font-size: 12px;"
            )
            header.addWidget(sub_lbl)

        outer.addLayout(header)

        self._body_layout = QVBoxLayout()
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(10)
        outer.addLayout(self._body_layout)

    # ------------------------------------------------------------ public
    def add_widget(self, widget: QWidget) -> None:
        self._body_layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        self._body_layout.addLayout(layout)

    @property
    def body_layout(self) -> QVBoxLayout:
        return self._body_layout


__all__ = ["SectionCard"]
