"""Step 2: upload CV / LinkedIn export and optional GitHub username."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..ai.base import BaseAIProvider
from ..config import Settings
from ..models.candidate import CandidateProfile
from ..models.job import JobPosting
from ..services.github_analyzer import GitHubError, fetch_github_projects
from ..services.linkedin_parser import parse_linkedin_export
from ..services.profile_builder import build_candidate_profile
from ..services.resume_parser import ResumeParseError, parse_resume_file
from .widgets.file_drop_zone import FileDropZone
from .workers import run_in_background

logger = logging.getLogger(__name__)


class CandidateInputPage(QWidget):
    profile_built = Signal(object)  # CandidateProfile

    def __init__(
        self,
        provider: BaseAIProvider,
        settings: Settings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._provider = provider
        self._settings = settings
        self._pool = QThreadPool.globalInstance()
        self._job: JobPosting | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(14)

        layout.addWidget(QLabel("<h2>Step 2 - Candidate inputs</h2>"))
        layout.addWidget(QLabel(
            "Provide as much as you have - the app will only use information that "
            "appears in these inputs (no invented experience)."
        ))

        self._cv_drop = FileDropZone("CV (PDF / DOCX / TXT) - required",
                                     extensions=(".pdf", ".docx", ".txt"))
        layout.addWidget(self._cv_drop)

        self._li_drop = FileDropZone(
            "LinkedIn export (PDF / TXT) - optional",
            extensions=(".pdf", ".txt"),
        )
        layout.addWidget(self._li_drop)

        gh_row = QHBoxLayout()
        gh_row.addWidget(QLabel("GitHub username (optional):"))
        self._gh_input = QLineEdit()
        self._gh_input.setPlaceholderText("e.g. fearplay")
        gh_row.addWidget(self._gh_input, stretch=1)
        layout.addLayout(gh_row)

        if not settings.github_token:
            hint = QLabel(
                "<i>Tip: set GITHUB_TOKEN in .env to lift the GitHub rate limit "
                "from 60 to 5000 requests per hour.</i>"
            )
            hint.setStyleSheet("color: #a8a8b3;")
            layout.addWidget(hint)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #a8a8b3;")
        layout.addWidget(self._status)

        layout.addStretch(1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._analyze_btn = QPushButton("Analyze profile ->")
        self._analyze_btn.setMinimumWidth(200)
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

    def set_job(self, job: JobPosting | None) -> None:
        self._job = job

    def preset_paths(
        self,
        cv: Path | str | None = None,
        linkedin: Path | str | None = None,
        github_username: str | None = None,
    ) -> None:
        if cv:
            self._cv_drop.set_path(cv)
        if linkedin:
            self._li_drop.set_path(linkedin)
        if github_username:
            self._gh_input.setText(github_username)

    # ----------------------------------------------------------- handlers
    def _on_analyze_clicked(self) -> None:
        cv_path = self._cv_drop.current_path
        li_path = self._li_drop.current_path
        gh_user = self._gh_input.text().strip() or None

        if not (cv_path or li_path or gh_user):
            QMessageBox.warning(
                self,
                "Need at least one input",
                "Please provide a CV, LinkedIn export or GitHub username.",
            )
            return

        self._analyze_btn.setEnabled(False)
        self._status.setText("Reading inputs...")

        provider = self._provider
        token = self._settings.github_token or None
        job = self._job

        def work() -> CandidateProfile:
            cv_text = parse_resume_file(cv_path) if cv_path else ""
            li_text = parse_linkedin_export(li_path) if li_path else ""
            projects = []
            if gh_user:
                try:
                    projects = fetch_github_projects(gh_user, token, job=job)
                except GitHubError as exc:
                    logger.warning("GitHub fetch failed: %s", exc)
            return build_candidate_profile(
                provider,
                cv_text=cv_text,
                linkedin_text=li_text,
                github_username=gh_user,
                github_projects=projects,
            )

        run_in_background(
            self._pool,
            work,
            on_finished=self._on_done,
            on_failed=self._on_failed,
        )

    def _on_done(self, profile: CandidateProfile) -> None:
        self._analyze_btn.setEnabled(True)
        self._status.setText(
            f"Profile ready: {profile.full_name or 'Anonymous'} - "
            f"{len(profile.technical_skills)} skills, {len(profile.projects)} projects."
        )
        self.profile_built.emit(profile)

    def _on_failed(self, message: str) -> None:
        self._analyze_btn.setEnabled(True)
        self._status.setText("Analysis failed.")
        if "ResumeParseError" in message:
            QMessageBox.critical(self, "CV parse failed", message)
        else:
            QMessageBox.critical(self, "Profile analysis failed", message)


__all__ = ["CandidateInputPage"]
