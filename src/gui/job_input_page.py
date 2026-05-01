"""Step 1: enter a job URL or paste the description text."""
from __future__ import annotations

import logging

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..ai.base import BaseAIProvider
from ..models.job import JobPosting
from ..services.job_parser import parse_job
from ..services.job_url_fetcher import JobFetchError, fetch_job_text
from .workers import run_in_background

logger = logging.getLogger(__name__)


class JobInputPage(QWidget):
    job_parsed = Signal(object)  # JobPosting

    def __init__(self, provider: BaseAIProvider, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._provider = provider
        self._pool = QThreadPool.globalInstance()
        self._current_url: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(12)

        layout.addWidget(QLabel("<h2>Step 1 - Job posting</h2>"))
        layout.addWidget(QLabel(
            "Paste the URL of the job posting and click <b>Fetch</b>, or paste "
            "the description text directly into the box below."
        ))

        url_row = QHBoxLayout()
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("https://example.com/jobs/qa-engineer")
        url_row.addWidget(self._url_input, stretch=1)
        self._fetch_btn = QPushButton("Fetch")
        self._fetch_btn.clicked.connect(self._on_fetch_clicked)
        url_row.addWidget(self._fetch_btn)
        layout.addLayout(url_row)

        layout.addWidget(QLabel("Job description (auto-filled by Fetch, or paste manually):"))
        self._desc = QPlainTextEdit()
        self._desc.setPlaceholderText("Paste the job description text here...")
        self._desc.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._desc.setMinimumHeight(220)
        layout.addWidget(self._desc, stretch=1)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #a8a8b3;")
        layout.addWidget(self._status)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._analyze_btn = QPushButton("Analyze job ->")
        self._analyze_btn.setMinimumWidth(180)
        self._analyze_btn.clicked.connect(self._on_analyze_clicked)
        self._analyze_btn.setStyleSheet(
            "QPushButton { background: #1f6feb; color: white; border: none;"
            " border-radius: 6px; padding: 8px 14px; font-weight: 600; }"
            "QPushButton:disabled { background: #3a3d45; color: #888; }"
        )
        button_row.addWidget(self._analyze_btn)
        layout.addLayout(button_row)

    # ----------------------------------------------------------- public
    def set_provider(self, provider: BaseAIProvider) -> None:
        self._provider = provider

    def load_text(self, text: str, source_url: str | None = None) -> None:
        self._desc.setPlainText(text)
        if source_url is not None:
            self._url_input.setText(source_url)
            self._current_url = source_url

    # ----------------------------------------------------------- handlers
    def _on_fetch_clicked(self) -> None:
        url = self._url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Missing URL", "Please enter a job URL first.")
            return
        self._fetch_btn.setEnabled(False)
        self._status.setText(f"Fetching {url}...")

        def work():
            return fetch_job_text(url)

        run_in_background(
            self._pool,
            work,
            on_finished=self._on_fetch_done,
            on_failed=self._on_fetch_failed,
        )

    def _on_fetch_done(self, result) -> None:
        self._fetch_btn.setEnabled(True)
        self._desc.setPlainText(result.text)
        self._current_url = result.source_url
        self._status.setText(
            f"Fetched via {result.method}. {len(result.text)} chars - review and click "
            f"'Analyze job' below."
        )

    def _on_fetch_failed(self, message: str) -> None:
        self._fetch_btn.setEnabled(True)
        self._status.setText("Fetch failed - paste the text manually below.")
        if "JobFetchError" in message or "HTTP" in message:
            QMessageBox.warning(
                self,
                "Could not fetch URL",
                "Could not auto-fetch the page. Please paste the description text "
                "manually below.\n\n" + message,
            )
        else:
            QMessageBox.warning(self, "Fetch failed", message)

    def _on_analyze_clicked(self) -> None:
        text = self._desc.toPlainText().strip()
        if not text:
            QMessageBox.warning(
                self,
                "No description",
                "Please fetch a URL or paste the job description text first.",
            )
            return
        self._analyze_btn.setEnabled(False)
        self._status.setText("Analyzing job posting...")

        provider = self._provider
        url = self._url_input.text().strip() or self._current_url

        def work():
            return parse_job(provider, text, source_url=url or None)

        run_in_background(
            self._pool,
            work,
            on_finished=self._on_analyze_done,
            on_failed=self._on_analyze_failed,
        )

    def _on_analyze_done(self, posting: JobPosting) -> None:
        self._analyze_btn.setEnabled(True)
        self._status.setText(
            f"Detected role: {posting.role_type} - {posting.title} "
            f"({posting.company or 'unknown company'})"
        )
        self.job_parsed.emit(posting)

    def _on_analyze_failed(self, message: str) -> None:
        self._analyze_btn.setEnabled(True)
        self._status.setText("Analysis failed.")
        QMessageBox.critical(self, "Analysis failed", message)


__all__ = ["JobInputPage"]
