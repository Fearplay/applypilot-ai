"""Drag-and-drop file picker with a 'Browse...' fallback."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class FileDropZone(QFrame):
    """Frame that accepts a single dropped file or opens a file dialog."""

    file_selected = Signal(Path)

    def __init__(
        self,
        label: str,
        extensions: Iterable[str] = (".pdf", ".docx", ".txt"),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._extensions = tuple(e.lower() for e in extensions)
        self._current_path: Path | None = None

        self.setObjectName("FileDropZone")
        self.setFrameShape(QFrame.StyledPanel)
        self.setAcceptDrops(True)
        self.setMinimumHeight(110)
        self._apply_style(active=False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(6)

        self._label = QLabel(label)
        self._label.setStyleSheet("color: #e8e8ee; font-weight: bold;")
        layout.addWidget(self._label)

        self._hint = QLabel(
            f"Drag &amp; drop a file ({', '.join(self._extensions)}) or browse."
        )
        self._hint.setStyleSheet("color: #a8a8b3;")
        layout.addWidget(self._hint)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._path_label = QLabel("No file selected")
        self._path_label.setStyleSheet("color: #a8a8b3;")
        row.addWidget(self._path_label, stretch=1)

        browse = QPushButton("Browse...")
        browse.clicked.connect(self._on_browse)
        row.addWidget(browse)

        clear = QPushButton("Clear")
        clear.clicked.connect(self.clear)
        row.addWidget(clear)
        layout.addLayout(row)

    # ------------------------------------------------------------ public
    @property
    def current_path(self) -> Path | None:
        return self._current_path

    def clear(self) -> None:
        self._current_path = None
        self._path_label.setText("No file selected")
        self._path_label.setStyleSheet("color: #a8a8b3;")

    def set_path(self, path: Path | str | None) -> None:
        if path is None:
            self.clear()
            return
        p = Path(path)
        if not self._allowed(p):
            self._path_label.setText(
                f"Unsupported file type: {p.suffix or '(no ext)'}"
            )
            self._path_label.setStyleSheet("color: #cf6f1c;")
            return
        self._current_path = p
        self._path_label.setText(str(p))
        self._path_label.setStyleSheet("color: #e8e8ee;")
        self.file_selected.emit(p)

    # ----------------------------------------------------------- helpers
    def _apply_style(self, active: bool) -> None:
        if active:
            self.setStyleSheet(
                "#FileDropZone { background: #2c3344; border: 2px dashed #5b8def; "
                "border-radius: 8px; }"
            )
        else:
            self.setStyleSheet(
                "#FileDropZone { background: #2a2d35; border: 2px dashed #4a4d55; "
                "border-radius: 8px; }"
            )

    def _allowed(self, path: Path) -> bool:
        return not self._extensions or path.suffix.lower() in self._extensions

    def _on_browse(self) -> None:
        filt = (
            "Supported (" + " ".join(f"*{e}" for e in self._extensions) + ");;All files (*)"
        )
        path, _ = QFileDialog.getOpenFileName(self, "Select file", "", filt)
        if path:
            self.set_path(Path(path))

    # -------------------------------------------------------------- DnD
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls() and len(event.mimeData().urls()) == 1:
            event.acceptProposedAction()
            self._apply_style(active=True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._apply_style(active=False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._apply_style(active=False)
        urls = event.mimeData().urls()
        if not urls:
            event.ignore()
            return
        local = urls[0].toLocalFile()
        if local:
            self.set_path(Path(local))
            event.acceptProposedAction()
        else:
            event.ignore()


__all__ = ["FileDropZone"]
