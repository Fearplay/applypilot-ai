"""Big circular score badge (0-100) used on the match report page."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..theme import Tokens


def _color_for(score: int) -> QColor:
    if score >= 80:
        return QColor(Tokens.success)
    if score >= 60:
        return QColor(Tokens.accent)
    if score >= 40:
        return QColor(Tokens.warn)
    return QColor(Tokens.danger)


class ScoreBadge(QWidget):
    """Circular widget that shows a 0-100 score with a coloured ring."""

    def __init__(
        self,
        score: int = 0,
        label: str = "Match",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._score = max(0, min(int(score), 100))
        self._label = label
        self.setMinimumSize(180, 180)

    def set_score(self, score: int, label: str | None = None) -> None:
        self._score = max(0, min(int(score), 100))
        if label is not None:
            self._label = label
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        size = min(self.width(), self.height()) - 12
        x = (self.width() - size) // 2
        y = (self.height() - size) // 2
        rect = (x, y, size, size)

        track_pen = QPen(QColor(Tokens.border), 9, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(track_pen)
        painter.drawArc(*rect, 0, 360 * 16)

        if self._score > 0:
            arc_pen = QPen(_color_for(self._score), 9, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(arc_pen)
            painter.drawArc(*rect, 90 * 16, -int(360 * 16 * self._score / 100))

        painter.setPen(QColor(Tokens.text))
        font = QFont()
        font.setFamily("Segoe UI")
        font.setPointSize(30)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, str(self._score))

        if self._label:
            painter.setPen(QColor(Tokens.text_muted))
            font.setPointSize(9)
            font.setWeight(QFont.Normal)
            painter.setFont(font)
            painter.drawText(
                self.rect().adjusted(0, size // 2 + 16, 0, 0),
                Qt.AlignHCenter | Qt.AlignTop,
                self._label,
            )


__all__ = ["ScoreBadge"]
