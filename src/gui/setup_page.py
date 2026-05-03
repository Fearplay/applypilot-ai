"""Unified Setup page that replaces Welcome + Job input + Candidate input.

The page hosts three :class:`SectionCard` widgets stacked vertically inside
a scroll area:

1. **Job posting** - URL fetch + plain-text description editor.
2. **Resume & profile** - CV (required) + LinkedIn (optional) drop zones.
3. **GitHub & links** - one **GitHub profile URL** field (or check
   *Skip GitHub*). When a URL is provided we extract the username and call
   the public GitHub REST API in the background to fetch the candidate's
   repositories (uses ``GITHUB_TOKEN`` if set in ``.env``).

A single bottom action bar fires the whole pipeline (job parse + GitHub
fetch + profile build) in one click.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
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
from ..config import Settings
from ..i18n import t
from ..models.candidate import CandidateProfile, GitHubProject
from ..models.job import JobPosting
from ..services.github_analyzer import GitHubError, extract_username, fetch_github_projects
from ..services.job_parser import parse_job
from ..services.job_url_fetcher import fetch_job_text
from ..services.linkedin_parser import parse_linkedin_export
from ..services.profile_builder import build_candidate_profile
from ..services.resume_parser import parse_resume_file
from .theme import Tokens
from .widgets.file_drop_zone import FileDropZone
from .widgets.section_card import SectionCard
from .workers import run_in_background

logger = logging.getLogger(__name__)


class SetupPage(QWidget):
    """All inputs on a single scrollable page."""

    job_parsed = Signal(object)            # JobPosting
    profile_built = Signal(object)          # CandidateProfile
    analysis_started = Signal()
    analysis_failed = Signal(str)

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
        self._current_url: str | None = None
        self._parsed_job: JobPosting | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll, stretch=1)

        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(36, 30, 36, 24)
        host_layout.setSpacing(20)
        scroll.setWidget(host)

        # ----- header
        title = QLabel(t("setup.heading"))
        title.setStyleSheet(
            f"color: {Tokens.text}; font-size: 24px; font-weight: 700;"
        )
        host_layout.addWidget(title)

        subtitle = QLabel(t("setup.subheading"))
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"color: {Tokens.text_muted}; font-size: 13px;")
        host_layout.addWidget(subtitle)

        # ----- card 1: job posting
        host_layout.addWidget(self._build_job_card())

        # ----- card 2: resume / linkedin
        host_layout.addWidget(self._build_profile_card())

        # ----- card 3: github
        host_layout.addWidget(self._build_github_card())

        host_layout.addStretch(1)

        # ----- action bar (fixed at bottom of the page)
        bar = QFrame()
        bar.setStyleSheet(
            f"background-color: {Tokens.bg};"
            f" border-top: 1px solid {Tokens.border};"
        )
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(36, 14, 36, 14)
        bar_layout.setSpacing(10)

        self._sample_btn = QPushButton(t("setup.try_sample"))
        self._sample_btn.setProperty("variant", "ghost")
        bar_layout.addWidget(self._sample_btn)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(
            f"color: {Tokens.text_muted}; font-size: 12px;"
        )
        bar_layout.addWidget(self._status_lbl, stretch=1)

        self._run_btn = QPushButton(t("setup.run"))
        self._run_btn.setProperty("variant", "primary")
        self._run_btn.setMinimumWidth(180)
        self._run_btn.clicked.connect(self._on_run_clicked)
        bar_layout.addWidget(self._run_btn)
        outer.addWidget(bar)

    # ----------------------------------------------------------- builders
    def _build_job_card(self) -> SectionCard:
        card = SectionCard(
            title=t("setup.job.title"),
            subtitle=t("setup.job.subtitle"),
            eyebrow=t("setup.step1"),
        )

        url_row = QHBoxLayout()
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText(t("setup.job.url_placeholder"))
        url_row.addWidget(self._url_input, stretch=1)
        self._fetch_btn = QPushButton(t("setup.job.fetch"))
        self._fetch_btn.clicked.connect(self._on_fetch_clicked)
        url_row.addWidget(self._fetch_btn)
        card.add_layout(url_row)

        self._desc = QPlainTextEdit()
        self._desc.setPlaceholderText(t("setup.job.text_placeholder"))
        self._desc.setMinimumHeight(180)
        self._desc.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        card.add_widget(self._desc)
        return card

    def _build_profile_card(self) -> SectionCard:
        card = SectionCard(
            title=t("setup.profile.title"),
            subtitle=t("setup.profile.subtitle"),
            eyebrow=t("setup.step2"),
        )
        self._cv_drop = FileDropZone(
            t("setup.profile.cv_label"),
            extensions=(".pdf", ".docx", ".txt", ".html", ".htm"),
        )
        card.add_widget(self._cv_drop)
        self._li_drop = FileDropZone(
            t("setup.profile.linkedin_label"),
            extensions=(".pdf", ".txt", ".html", ".htm"),
        )
        card.add_widget(self._li_drop)
        return card

    def _build_github_card(self) -> SectionCard:
        card = SectionCard(
            title=t("setup.github.title"),
            subtitle=t("setup.github.subtitle"),
            eyebrow=t("setup.step3"),
        )

        self._gh_url = QLineEdit()
        self._gh_url.setPlaceholderText(t("setup.github.url_placeholder"))
        card.add_widget(self._gh_url)

        self._gh_skip = QCheckBox(t("setup.github.skip"))
        card.add_widget(self._gh_skip)

        self._gh_hint = QLabel(t("setup.github.hint_html"))
        self._gh_hint.setTextFormat(Qt.RichText)
        self._gh_hint.setOpenExternalLinks(True)
        self._gh_hint.setWordWrap(True)
        self._gh_hint.setStyleSheet(
            f"color: {Tokens.text_dim}; font-size: 11px; font-style: italic;"
        )
        card.add_widget(self._gh_hint)
        return card

    # ----------------------------------------------------------- public
    def set_provider(self, provider: BaseAIProvider) -> None:
        self._provider = provider

    def connect_sample_handler(self, handler) -> None:
        self._sample_btn.clicked.connect(handler)

    def preset_inputs(
        self,
        job_text: str | None = None,
        job_url: str | None = None,
        cv: Path | str | None = None,
        linkedin: Path | str | None = None,
        github_profile_url: str | None = None,
    ) -> None:
        if job_text is not None:
            self._desc.setPlainText(job_text)
        if job_url is not None:
            self._url_input.setText(job_url)
            self._current_url = job_url
        if cv:
            self._cv_drop.set_path(cv)
        if linkedin:
            self._li_drop.set_path(linkedin)
        if github_profile_url:
            self._gh_url.setText(github_profile_url)
            self._gh_skip.setChecked(False)

    def set_status(self, text: str) -> None:
        self._status_lbl.setText(text)

    def set_busy(self, busy: bool) -> None:
        self._run_btn.setEnabled(not busy)
        self._sample_btn.setEnabled(not busy)
        self._fetch_btn.setEnabled(not busy)

    # ----------------------------------------------------------- handlers
    def _on_fetch_clicked(self) -> None:
        url = self._url_input.text().strip()
        if not url:
            QMessageBox.warning(
                self, t("setup.error.no_url.title"), t("setup.error.no_url.body")
            )
            return
        self._fetch_btn.setEnabled(False)
        self.set_status(t("setup.status.fetching", url=url))

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
        self.set_status(
            t(
                "setup.status.fetched",
                method=result.method,
                chars=len(result.text),
            )
        )

    def _on_fetch_failed(self, message: str) -> None:
        self._fetch_btn.setEnabled(True)
        self.set_status(t("setup.status.fetch_failed"))
        QMessageBox.warning(
            self,
            t("setup.error.fetch.title"),
            t("setup.error.fetch.body", message=message),
        )

    def _resolve_github_username(self) -> str:
        if self._gh_skip.isChecked():
            return ""
        return extract_username(self._gh_url.text())

    def _on_run_clicked(self) -> None:
        text = self._desc.toPlainText().strip()
        if not text:
            QMessageBox.warning(
                self,
                t("setup.error.no_jd.title"),
                t("setup.error.no_jd.body"),
            )
            return
        cv_path = self._cv_drop.current_path
        li_path = self._li_drop.current_path
        gh_user = self._resolve_github_username()
        if not (cv_path or li_path or gh_user):
            QMessageBox.warning(
                self,
                t("setup.error.no_candidate.title"),
                t("setup.error.no_candidate.body"),
            )
            return

        self.set_busy(True)
        self.set_status(t("setup.status.analysing"))
        self.analysis_started.emit()

        provider = self._provider
        url = self._url_input.text().strip() or self._current_url

        def work():
            return parse_job(provider, text, source_url=url or None)

        run_in_background(
            self._pool,
            work,
            on_finished=lambda job: self._on_job_parsed(job, cv_path, li_path, gh_user),
            on_failed=self._on_pipeline_failed,
        )

    def _on_job_parsed(self, job: JobPosting, cv_path, li_path, gh_user: str) -> None:
        self._parsed_job = job
        self.job_parsed.emit(job)
        self.set_status(
            t(
                "setup.status.job_parsed",
                title=job.title,
                role=job.role_type,
            )
        )

        provider = self._provider
        token = self._settings.github_token or None

        def work():
            cv_text = parse_resume_file(cv_path) if cv_path else ""
            li_text = parse_linkedin_export(li_path) if li_path else ""
            projects: list[GitHubProject] = []
            if gh_user:
                try:
                    projects = list(
                        fetch_github_projects(gh_user, token, job=job)
                    )
                except GitHubError as exc:
                    logger.warning("GitHub fetch failed: %s", exc)
            return build_candidate_profile(
                provider,
                cv_text=cv_text,
                linkedin_text=li_text,
                github_username=gh_user or None,
                github_projects=projects,
            )

        run_in_background(
            self._pool,
            work,
            on_finished=self._on_profile_done,
            on_failed=self._on_pipeline_failed,
        )

    def _on_profile_done(self, profile: CandidateProfile) -> None:
        self.set_busy(False)
        self.set_status(
            t(
                "setup.status.profile_ready",
                name=profile.full_name or "Anonymous",
                skills=len(profile.technical_skills),
                projects=len(profile.projects),
            )
        )
        self.profile_built.emit(profile)

    def _on_pipeline_failed(self, message: str) -> None:
        self.set_busy(False)
        self.set_status(t("setup.status.failed"))
        self.analysis_failed.emit(message)
        QMessageBox.critical(self, t("setup.error.pipeline.title"), message)


__all__ = ["SetupPage"]
