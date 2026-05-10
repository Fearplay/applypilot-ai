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

from dataclasses import dataclass
import logging
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, QThreadPool, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QResizeEvent
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
from ..services.job_url_fetcher import JobFetchError, fetch_job_text
from ..services.linkedin_parser import parse_linkedin_export
from ..services.profile_builder import build_candidate_profile
from ..services.resume_parser import parse_resume_file
from .theme import Tokens
from .widgets.file_drop_zone import FileDropZone
from .widgets.section_card import SectionCard
from .workers import run_in_background

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ProfileBuildResult:
    profile: CandidateProfile
    github_warning: str = ""


class _ElidedLabel(QLabel):
    """QLabel that elides on the right and never grows the parent layout.

    A plain QLabel reports ``sizeHint() == naturalTextWidth()`` on the
    horizontal axis. When the action bar status line displays a fetch
    URL like ``Stahuji https://very/long/path...``, that 600+ px hint
    propagates up the QHBoxLayout -> SetupPage -> QStackedWidget -> the
    main window and forces the whole window to widen. The user reported
    this exact behaviour: clicking *Fetch* with a long URL stretched
    the app.

    Two fixes layered together:

    * ``QSizePolicy.Ignored`` horizontally - the layout no longer
      considers our preferred width when computing the parent's minimum
      size, so the window stays put.
    * On every resize / setText we elide the visible text with
      :func:`QFontMetrics.elidedText`, dropping the middle of the URL
      into ``...``. The full untruncated text remains accessible as a
      tooltip so power users hovering still see the original value.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text: str = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def setText(self, text: str) -> None:  # type: ignore[override]
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._render_elided()

    def text(self) -> str:  # type: ignore[override]
        return self._full_text

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._render_elided()

    def _render_elided(self) -> None:
        if not self._full_text:
            super().setText("")
            return
        # Leave a small margin so the trailing "..." is never clipped.
        max_width = max(0, self.width() - 4)
        if max_width <= 0:
            super().setText("")
            return
        elided = self.fontMetrics().elidedText(
            self._full_text, Qt.ElideRight, max_width
        )
        super().setText(elided)


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
        # Set when the orchestrator gates "Run analysis" while it generates
        # clarifying questions or recomputes the match. None means "no block".
        self._block_reason: str | None = None
        # True after the first fetch attempt completed (regardless of
        # outcome). The "Wrong content" button is hidden until this flips.
        self._fetch_attempted: bool = False
        # True while a desktop-UA retry is already in flight, so the user
        # can't queue several retries with rapid clicks.
        self._retry_in_flight: bool = False

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

        # Fresh-run toggle: when ticked, the orchestrator wipes any
        # previously-collected answers / exclusion ids so the clarifying-
        # questions dialog and the removal-confirmation dialog appear
        # again on the next analysis. Without this, a re-run with the
        # same answers above 85% evidence coverage silently skips both.
        self._fresh_run_chk = QCheckBox(t("setup.fresh_run.label"))
        self._fresh_run_chk.setToolTip(t("setup.fresh_run.tip"))
        self._fresh_run_chk.setStyleSheet(
            f"QCheckBox {{ color: {Tokens.text_muted}; font-size: 11px; }}"
        )
        bar_layout.addWidget(self._fresh_run_chk)

        self._status_lbl = _ElidedLabel()
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
        self._wrong_content_btn = QPushButton(t("setup.job.wrong"))
        self._wrong_content_btn.setProperty("variant", "ghost")
        self._wrong_content_btn.setToolTip(t("setup.job.wrong.tip"))
        self._wrong_content_btn.clicked.connect(self._on_wrong_content_clicked)
        self._wrong_content_btn.setVisible(False)
        url_row.addWidget(self._wrong_content_btn)
        card.add_layout(url_row)

        self._js_hint_lbl = QLabel(t("setup.job.js_needed_hint"))
        self._js_hint_lbl.setWordWrap(True)
        self._js_hint_lbl.setStyleSheet(
            f"color: {Tokens.text_muted}; font-size: 11px; "
            "font-style: italic; padding: 2px 0px;"
        )
        self._js_hint_lbl.setVisible(False)
        card.add_widget(self._js_hint_lbl)

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

        # ----- additional candidate notes (free-text + drop file)
        # The label sits above its own subtitle so the user instantly sees
        # this is OPTIONAL, what to type, and that they can drop a file
        # which auto-fills the textarea below. The drop zone reuses the
        # CV-style file kinds via parse_resume_file so PDF, DOCX and HTML
        # exported from Notion / Word also work.
        notes_label = QLabel(t("setup.profile.additional.label"))
        notes_label.setStyleSheet(
            f"color: {Tokens.text}; font-weight: 600; font-size: 13px; "
            "padding-top: 4px;"
        )
        card.add_widget(notes_label)

        notes_subtitle = QLabel(t("setup.profile.additional.subtitle"))
        notes_subtitle.setWordWrap(True)
        notes_subtitle.setStyleSheet(
            f"color: {Tokens.text_muted}; font-size: 12px;"
        )
        card.add_widget(notes_subtitle)

        self._notes_drop = FileDropZone(
            t("setup.profile.additional.drop_label"),
            extensions=(".pdf", ".docx", ".txt", ".md", ".html", ".htm"),
        )
        # Drop / browse populates the textarea below via parse_resume_file
        # (same parser as the CV drop, supports PDF / DOCX / HTML / TXT / MD)
        # so the user always sees and can edit what the AI will read.
        self._notes_drop.file_selected.connect(self._on_notes_file_selected)
        card.add_widget(self._notes_drop)

        self._notes_edit = QPlainTextEdit()
        self._notes_edit.setPlaceholderText(
            t("setup.profile.additional.notes_placeholder")
        )
        self._notes_edit.setMinimumHeight(140)
        self._notes_edit.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        card.add_widget(self._notes_edit)
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
        additional_notes: str | None = None,
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
        if additional_notes is not None:
            self._notes_edit.setPlainText(additional_notes)

    def set_status(self, text: str) -> None:
        self._status_lbl.setText(text)

    def set_busy(self, busy: bool) -> None:
        self._sample_btn.setEnabled(not busy)
        self._fetch_btn.setEnabled(not busy and not self._retry_in_flight)
        # When externally blocked the run button stays disabled regardless.
        self._refresh_run_button_enabled(busy=busy)

    def set_analysis_blocked(self, reason: str | None) -> None:
        """Disable the *Run analysis* button while the orchestrator is busy.

        ``reason`` is shown both as a tooltip on the button and as the
        primary status line. ``None`` clears the block. The button is also
        forced into the disabled state regardless of any local "busy" flag,
        so the orchestrator's view of the world always wins.
        """
        self._block_reason = reason or None
        if reason:
            self._run_btn.setToolTip(reason)
            self.set_status(reason)
        else:
            self._run_btn.setToolTip("")
        self._refresh_run_button_enabled()

    def _refresh_run_button_enabled(self, *, busy: bool | None = None) -> None:
        if busy is None:
            # Without an explicit hint, treat anything not "ready" as busy.
            busy = not self._fetch_btn.isEnabled() and not self._retry_in_flight
        if self._block_reason:
            self._run_btn.setEnabled(False)
        else:
            self._run_btn.setEnabled(not busy)

    # ----------------------------------------------------------- handlers
    def _on_fetch_clicked(self) -> None:
        url = self._url_input.text().strip()
        if not url:
            QMessageBox.warning(
                self, t("setup.error.no_url.title"), t("setup.error.no_url.body")
            )
            return
        self._js_hint_lbl.setVisible(False)
        self._fetch_btn.setEnabled(False)
        self._wrong_content_btn.setEnabled(False)
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
        self._wrong_content_btn.setEnabled(True)
        self._desc.setPlainText(result.text)
        self._current_url = result.source_url
        self._fetch_attempted = True
        self._wrong_content_btn.setVisible(True)
        self._js_hint_lbl.setVisible(False)
        self.set_status(
            t(
                "setup.status.fetched",
                method=result.method,
                chars=len(result.text),
            )
        )

    def _on_fetch_failed(self, message: str) -> None:
        self._fetch_btn.setEnabled(True)
        self._wrong_content_btn.setEnabled(True)
        self._fetch_attempted = True
        self._wrong_content_btn.setVisible(True)
        # Pages whose only failure mode is "looks like JSON" deserve the
        # JS-hint label so the user immediately knows what to do.
        if "JSON" in message or "config blob" in message:
            self._js_hint_lbl.setVisible(True)
        self.set_status(t("setup.status.fetch_failed"))
        # Friendly two-button dialog instead of dumping the full
        # JobFetchError message on the user. Most automatic-fetch
        # failures on real career sites are JS-only pages that the
        # Playwright path handles fine, so we offer it as the default
        # action. The full error message is logged in the background.
        logger.info("Auto-fetch failed: %s", message)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle(t("setup.error.fetch.retry_title"))
        box.setText(t("setup.error.fetch.retry_body"))
        try_btn = box.addButton(
            t("setup.error.fetch.try_playwright"), QMessageBox.AcceptRole
        )
        cancel_btn = box.addButton(
            t("setup.error.fetch.cancel"), QMessageBox.RejectRole
        )
        box.setDefaultButton(try_btn)
        box.exec()
        if box.clickedButton() is try_btn:
            self._on_wrong_content_clicked()
        elif box.clickedButton() is cancel_btn:
            self.set_status(t("setup.status.fetch_failed"))

    def _on_wrong_content_clicked(self) -> None:
        url = (self._url_input.text().strip() or self._current_url or "").strip()
        if not url:
            QMessageBox.warning(
                self, t("setup.error.no_url.title"), t("setup.error.no_url.body")
            )
            return
        self._retry_in_flight = True
        self._fetch_btn.setEnabled(False)
        self._wrong_content_btn.setEnabled(False)
        self.set_status(t("setup.status.fetch_retrying"))

        def work():
            # Wrong-content retry escalates aggressively: desktop UA AND
            # the Playwright system-browser fallback. The renderer only
            # spins up if the static strategies still fail, so simple
            # pages that just needed a different UA stay fast.
            return fetch_job_text(url, force_desktop_ua=True, use_renderer=True)

        run_in_background(
            self._pool,
            work,
            on_finished=self._on_retry_done,
            on_failed=self._on_retry_failed,
        )

    def _on_retry_done(self, result) -> None:
        self._retry_in_flight = False
        self._fetch_btn.setEnabled(True)
        self._wrong_content_btn.setEnabled(True)
        self._desc.setPlainText(result.text)
        self._current_url = result.source_url
        self._js_hint_lbl.setVisible(False)
        self.set_status(
            t(
                "setup.status.fetched",
                method=result.method,
                chars=len(result.text),
            )
        )

    def _on_retry_failed(self, message: str) -> None:
        self._retry_in_flight = False
        self._fetch_btn.setEnabled(True)
        self._wrong_content_btn.setEnabled(True)
        self._js_hint_lbl.setVisible(True)
        self.set_status(t("setup.status.fetch_failed"))
        self._show_fallback_dialog(message)

    def _show_fallback_dialog(self, message: str) -> None:
        url = (self._current_url or self._url_input.text().strip()).strip()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(t("setup.job.fallback.title"))
        body = t("setup.job.fallback.body")
        if message:
            body = f"{body}\n\n{message}"
        box.setText(body)
        open_btn = box.addButton(
            t("setup.job.fallback.open_browser"), QMessageBox.AcceptRole
        )
        copy_btn = box.addButton(
            t("setup.job.fallback.copy"), QMessageBox.ActionRole
        )
        cancel_btn = box.addButton(
            t("setup.job.fallback.cancel"), QMessageBox.RejectRole
        )
        box.setDefaultButton(open_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is open_btn and url:
            QDesktopServices.openUrl(QUrl(url))
            self.set_status(t("setup.job.fallback.opened"))
        elif clicked is copy_btn and url:
            clipboard = QGuiApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(url)
                self.set_status(t("setup.job.fallback.copied"))
        elif clicked is cancel_btn:
            self.set_status(t("setup.status.fetch_failed"))

    def is_fresh_run_requested(self) -> bool:
        """Return True when the user ticked 'Re-ask clarifying questions'.

        The orchestrator polls this just before kicking off a new
        analysis - if true, it wipes ``state.answers`` /
        ``state.excluded_entry_ids`` / ``state.ai_removal_reasons`` so the
        clarifying-questions and removal-confirmation dialogs reappear.
        After consuming the signal the caller should call
        :meth:`acknowledge_fresh_run` to untick the checkbox so the next
        run defaults to the cheaper 'reuse previous answers' path.
        """
        return self._fresh_run_chk.isChecked()

    def acknowledge_fresh_run(self) -> None:
        """Untick the fresh-run checkbox after the orchestrator consumed it."""
        self._fresh_run_chk.setChecked(False)

    def _resolve_github_username(self) -> str:
        if self._gh_skip.isChecked():
            return ""
        return extract_username(self._gh_url.text())

    def _on_notes_file_selected(self, path: Path) -> None:
        """Parse the dropped notes file in the background and fill the textarea.

        Reuses :func:`parse_resume_file` so PDF / DOCX / HTML / TXT / MD all
        work, mirroring the CV drop zone. The file is just a SOURCE of text -
        whatever lands in ``self._notes_edit`` is the single source of truth
        the AI eventually sees, so the user can freely edit / extend the
        parsed text after the drop. Parse failures surface in the status bar
        instead of blocking the run; the user can still type manually.
        """
        self.set_status(t("setup.profile.additional.parsing", name=path.name))

        def work() -> str:
            return parse_resume_file(path)

        def on_done(text: str) -> None:
            cleaned = (text or "").strip()
            if not cleaned:
                self.set_status(
                    t(
                        "setup.profile.additional.parse_failed",
                        name=path.name,
                        error="empty document",
                    )
                )
                return
            self._notes_edit.setPlainText(cleaned)
            self.set_status(
                t(
                    "setup.profile.additional.parsed",
                    name=path.name,
                    chars=len(cleaned),
                )
            )

        def on_failed(message: str) -> None:
            logger.warning("Failed to parse additional notes file: %s", message)
            self.set_status(
                t(
                    "setup.profile.additional.parse_failed",
                    name=path.name,
                    error=message,
                )
            )

        run_in_background(
            self._pool,
            work,
            on_finished=on_done,
            on_failed=on_failed,
        )

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
        # Capture the user-typed notes verbatim. They feed every downstream
        # AI prompt (analyze_candidate, match report, resume, cover letter,
        # refine) via CandidateProfile.additional_notes so a one-line
        # clarification like "didn't finish bachelor's" is honoured by every
        # generator without needing a clarifying-question round-trip.
        notes_text = self._notes_edit.toPlainText().strip()

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
            on_finished=lambda job: self._on_job_parsed(
                job, cv_path, li_path, gh_user, notes_text
            ),
            on_failed=self._on_pipeline_failed,
        )

    def _on_job_parsed(
        self,
        job: JobPosting,
        cv_path,
        li_path,
        gh_user: str,
        additional_notes: str = "",
    ) -> None:
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
            github_warning = ""
            if gh_user:
                try:
                    projects = list(
                        fetch_github_projects(gh_user, token, job=job)
                    )
                except GitHubError as exc:
                    github_warning = str(exc)
                    logger.warning("GitHub fetch failed: %s", exc)
            profile = build_candidate_profile(
                provider,
                cv_text=cv_text,
                linkedin_text=li_text,
                github_username=gh_user or None,
                github_projects=projects,
                additional_notes=additional_notes,
            )
            return _ProfileBuildResult(profile=profile, github_warning=github_warning)

        run_in_background(
            self._pool,
            work,
            on_finished=self._on_profile_done,
            on_failed=self._on_pipeline_failed,
        )

    def _on_profile_done(self, result) -> None:
        if isinstance(result, _ProfileBuildResult):
            profile = result.profile
            github_warning = result.github_warning
        else:
            # Backwards compatibility for any older worker result still in flight.
            profile = result
            github_warning = ""
        self.set_busy(False)
        self.set_status(
            t(
                "setup.status.profile_ready",
                name=profile.full_name or "Anonymous",
                skills=len(profile.technical_skills),
                projects=len(profile.projects),
            )
        )
        if github_warning:
            QMessageBox.warning(
                self,
                t("setup.github.warning.title"),
                t("setup.github.warning.body", message=github_warning),
            )
        self.profile_built.emit(profile)

    def _on_pipeline_failed(self, message: str) -> None:
        self.set_busy(False)
        self.set_status(t("setup.status.failed"))
        self.analysis_failed.emit(message)
        QMessageBox.critical(self, t("setup.error.pipeline.title"), message)


__all__ = ["SetupPage"]
