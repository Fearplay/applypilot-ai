"""Step 6: history of past analyses, loaded from history.json."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings
from ..services.history_service import load_history

logger = logging.getLogger(__name__)


class HistoryPage(QWidget):
    open_folder_requested = Signal(str)

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(10)

        layout.addWidget(QLabel("<h2>History</h2>"))
        layout.addWidget(QLabel(
            f"Loaded from <code>{Path(settings.output_dir) / 'history.json'}</code>"
        ))

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Date", "Company", "Role", "Score", "Folder"]
        )
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self._table, stretch=1)

        button_row = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        button_row.addWidget(refresh)
        button_row.addStretch(1)
        open_btn = QPushButton("Open selected folder")
        open_btn.clicked.connect(self._on_open_clicked)
        button_row.addWidget(open_btn)
        layout.addLayout(button_row)

    # ----------------------------------------------------------- public
    def refresh(self) -> None:
        entries = load_history(self._settings.output_dir)
        self._table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            self._table.setItem(row, 0, QTableWidgetItem(entry.date.replace("T", " ")[:19]))
            self._table.setItem(row, 1, QTableWidgetItem(entry.company))
            self._table.setItem(row, 2, QTableWidgetItem(entry.role))
            score_item = QTableWidgetItem(str(entry.match_score))
            score_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, 3, score_item)
            self._table.setItem(row, 4, QTableWidgetItem(entry.output_folder))

    def _on_open_clicked(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        item = self._table.item(row, 4)
        if not item:
            return
        path = item.text()
        if path:
            self.open_folder_requested.emit(path)
            try:
                from PySide6.QtCore import QUrl
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            except Exception as exc:  # pragma: no cover
                logger.warning("Could not open folder: %s", exc)


__all__ = ["HistoryPage"]
