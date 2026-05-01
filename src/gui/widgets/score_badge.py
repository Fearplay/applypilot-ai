"""Big circular score badge (0-100) used on the match report page."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget


def _color_for(score: int) -> QColor:
    if score >= 80:
        return QColor("#1f8a3a")
    if score >= 60:
        return QColor("#d29922")
    if score >= 40:
        return QColor("#cf6f1c")
    return QColor("#a23a3a")


class ScoreBadge(QWidget):
    """Circular widget that shows a 0-100 score with a coloured ring."""

    def __init__(self, score: int = 0, label: str = "Match", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._score = max(0, min(int(score), 100))
        self._label = label
        self.setMinimumSize(160, 160)

    def set_score(self, score: int, label: str | None = None) -> None:
        self._score = max(0, min(int(score), 100))
        if label is not None:
            self._label = label
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        size = min(self.width(), self.height()) - 8
        x = (self.width() - size) // 2
        y = (self.height() - size) // 2
        rect = (x, y, size, size)

        track_pen = QPen(QColor("#3b3f48"), 10, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(track_pen)
        painter.drawArc(*rect, 0, 360 * 16)

        if self._score > 0:
            arc_pen = QPen(_color_for(self._score), 10, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(arc_pen)
            painter.drawArc(*rect, 90 * 16, -int(360 * 16 * self._score / 100))

        painter.setPen(QColor("#e8e8ee"))
        font = QFont()
        font.setPointSize(28)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, str(self._score))

        if self._label:
            painter.setPen(QColor("#a8a8b3"))
            font.setPointSize(9)
            font.setBold(False)
            painter.setFont(font)
            painter.drawText(self.rect().adjusted(0, size // 2 + 10, 0, 0),
                             Qt.AlignHCenter | Qt.AlignTop, self._label)


__all__ = ["ScoreBadge"]
