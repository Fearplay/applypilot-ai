"""Compact card widget that shows a single :class:`EvidenceItem`."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from ...models.evidence import EvidenceItem
from ..theme import Tokens
from .status_chip import StatusChip


_CONFIDENCE_VARIANT: dict[str, str] = {
    "high": "done",
    "medium": "active",
    "low": "danger",
}


class EvidenceCard(QFrame):
    def __init__(self, item: EvidenceItem, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("EvidenceCard")
        self.setStyleSheet(
            f"#EvidenceCard {{"
            f"  background-color: {Tokens.surface_alt};"
            f"  border: 1px solid {Tokens.border};"
            f"  border-radius: 10px;"
            f"}}"
            f"#EvidenceCard QLabel {{ color: {Tokens.text}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title = QLabel(item.skill or item.claim)
        title.setWordWrap(True)
        title.setStyleSheet(
            f"color: {Tokens.text}; font-weight: 600; font-size: 13px;"
        )
        header.addWidget(title, stretch=1)

        chip = StatusChip(
            item.confidence.upper(),
            variant=_CONFIDENCE_VARIANT.get(item.confidence, "idle"),  # type: ignore[arg-type]
        )
        header.addWidget(chip, alignment=Qt.AlignVCenter)
        layout.addLayout(header)

        meta = QLabel(f"{item.source_type} \u00b7 {item.source_name}")
        meta.setStyleSheet(f"color: {Tokens.text_muted}; font-size: 11px;")
        layout.addWidget(meta)

        body = QLabel(item.evidence_text)
        body.setWordWrap(True)
        body.setStyleSheet(f"color: {Tokens.text_muted}; font-size: 12px;")
        layout.addWidget(body)


__all__ = ["EvidenceCard"]
