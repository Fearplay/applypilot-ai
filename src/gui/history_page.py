"""History screen: table of past analyses with empty state and refresh."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings
from ..i18n import t
from ..services.history_service import load_history
from .theme import Tokens

logger = logging.getLogger(__name__)


class HistoryPage(QWidget):
    open_in_app_requested = Signal(str)  # output_folder absolute path

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 24, 36, 24)
        layout.setSpacing(14)

        head = QLabel(
            t("history.loaded_from", path=Path(settings.output_dir) / "history.json")
        )
        head.setTextFormat(Qt.RichText)
        head.setStyleSheet(f"color: {Tokens.text_muted}; font-size: 12px;")
        layout.addWidget(head)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack, stretch=1)

        # ----- table view
        table_wrap = QFrame()
        table_wrap.setStyleSheet(
            f"QFrame {{ background-color: {Tokens.surface};"
            f" border: 1px solid {Tokens.border}; border-radius: 10px; }}"
        )
        twl = QVBoxLayout(table_wrap)
        twl.setContentsMargins(8, 8, 8, 8)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            [
                t("history.col.date"),
                t("history.col.company"),
                t("history.col.role"),
                t("history.col.score"),
                t("history.col.folder"),
            ]
        )
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        twl.addWidget(self._table)
        self._stack.addWidget(table_wrap)

        # ----- empty state
        empty = QFrame()
        empty.setStyleSheet(
            f"QFrame {{ background-color: {Tokens.surface};"
            f" border: 1px dashed {Tokens.border_strong}; border-radius: 10px; }}"
        )
        ev = QVBoxLayout(empty)
        ev.setContentsMargins(40, 60, 40, 60)
        ev.setSpacing(8)
        ev.addStretch(1)
        title = QLabel(t("history.empty.title"))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"color: {Tokens.text}; font-size: 16px; font-weight: 600;"
        )
        ev.addWidget(title)
        sub = QLabel(t("history.empty.body"))
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {Tokens.text_muted}; font-size: 12px;")
        ev.addWidget(sub)
        ev.addStretch(1)
        self._stack.addWidget(empty)

        # ----- actions
        bar = QHBoxLayout()
        bar.setSpacing(8)
        refresh = QPushButton(t("history.refresh"))
        refresh.clicked.connect(self.refresh)
        bar.addWidget(refresh)
        bar.addStretch(1)
        open_folder_btn = QPushButton(t("history.open_folder"))
        open_folder_btn.clicked.connect(self._on_open_clicked)
        bar.addWidget(open_folder_btn)
        open_in_app_btn = QPushButton(t("history.open_in_app"))
        open_in_app_btn.setProperty("variant", "primary")
        open_in_app_btn.setToolTip(t("history.open_in_app.tip"))
        open_in_app_btn.clicked.connect(self._on_open_in_app_clicked)
        bar.addWidget(open_in_app_btn)
        layout.addLayout(bar)

    # ----------------------------------------------------------- public
    def refresh(self) -> None:
        entries = load_history(self._settings.output_dir)
        if not entries:
            self._stack.setCurrentIndex(1)
            return
        self._stack.setCurrentIndex(0)
        self._table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            self._table.setItem(row, 0, QTableWidgetItem(entry.date.replace("T", " ")[:19]))
            self._table.setItem(row, 1, QTableWidgetItem(entry.company))
            self._table.setItem(row, 2, QTableWidgetItem(entry.role))
            score_item = QTableWidgetItem(str(entry.match_score))
            score_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, 3, score_item)
            self._table.setItem(row, 4, QTableWidgetItem(entry.output_folder))

    def _selected_folder(self) -> str | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 4)
        if not item:
            return None
        path = item.text()
        return path or None

    def _on_open_clicked(self) -> None:
        path = self._selected_folder()
        if not path:
            return
        try:
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as exc:  # pragma: no cover
            logger.warning("Could not open folder: %s", exc)

    def _on_open_in_app_clicked(self) -> None:
        path = self._selected_folder()
        if not path:
            return
        if not Path(path).exists():
            logger.warning("History entry points to a missing folder: %s", path)
            return
        self.open_in_app_requested.emit(path)


__all__ = ["HistoryPage"]
