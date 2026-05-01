"""Compact card widget that shows a single :class:`EvidenceItem`."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from ...models.evidence import EvidenceItem


_COLOURS = {
    "high": "#1f8a3a",
    "medium": "#d29922",
    "low": "#a23a3a",
}


class EvidenceCard(QFrame):
    def __init__(self, item: EvidenceItem, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("EvidenceCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "#EvidenceCard { background: #2a2d35; border-radius: 8px; "
            "padding: 10px; border: 1px solid #3a3d45; }"
            "#EvidenceCard QLabel { color: #e8e8ee; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)

        title = QLabel(f"<b>{item.skill or item.claim}</b>")
        title.setWordWrap(True)
        layout.addWidget(title)

        meta_color = _COLOURS.get(item.confidence, "#a8a8b3")
        meta = QLabel(
            f"<span style='color:{meta_color};'>"
            f"{item.confidence.upper()}</span> "
            f"&nbsp;&nbsp; {item.source_type} &middot; {item.source_name}"
        )
        meta.setTextFormat(Qt.RichText)
        layout.addWidget(meta)

        body = QLabel(item.evidence_text)
        body.setWordWrap(True)
        body.setStyleSheet("color: #c2c5cf;")
        layout.addWidget(body)


__all__ = ["EvidenceCard"]
