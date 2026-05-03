"""Main window: slim sidebar nav, modern header chip, modal questions."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..ai.base import BaseAIProvider
from ..ai.provider_factory import build_provider
from ..config import Settings, load_settings
from ..i18n import get_language, register_listener, set_language, t
from ..models.candidate import CandidateProfile
from ..models.documents import (
    CoverLetter,
    InterviewQuestion,
    SkillGap,
    TailoredResume,
)
from ..models.evidence import EvidenceCheckResult
from ..models.job import JobPosting
from ..models.match import AnswersBundle, ClarifyingQuestion, MatchReport
from ..models.package import GeneratedApplicationPackage
from ..services.cover_letter_generator import generate_cover_letter
from ..services.export_service import export_package
from ..services.gap_plan_generator import generate_skill_gap_plan
from ..services.history_service import append_history, load_package_files
from ..services.interview_generator import generate_interview_questions
from ..services.match_engine import compute_match, needs_clarifying_questions
from ..services.profile_dedup import (
    excluded_ids_from_answers,
    filter_profile_entries,
)
from ..services.question_generator import generate_questions
from ..services.resume_generator import generate_tailored_resume
from ..utils.preferences import set_preference
from ..utils.restart import restart_app
from .documents_page import DocumentsPage
from .history_page import HistoryPage
from .match_report_page import MatchReportPage
from .output_language_dialog import OutputLanguageDialog
from .questions_dialog import QuestionsDialog
from .setup_page import SetupPage
from .theme import Tokens
from .widgets.sidebar import Sidebar, SidebarItem
from .widgets.status_chip import StatusChip
from .workers import run_in_background

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Workflow state
# ---------------------------------------------------------------------------
@dataclass
class WorkflowState:
    job: JobPosting | None = None
    candidate: CandidateProfile | None = None
    answers: AnswersBundle = field(default_factory=AnswersBundle)
    pending_questions: list[ClarifyingQuestion] = field(default_factory=list)
    evidence: EvidenceCheckResult | None = None
    match_report: MatchReport | None = None
    resume: TailoredResume | None = None
    cover_letter: CoverLetter | None = None
    interview: list[InterviewQuestion] = field(default_factory=list)
    gaps: list[SkillGap] = field(default_factory=list)
    package: GeneratedApplicationPackage | None = None
    #: Language for the resume / cover letter / interview / gap plan. Picked
    #: by the user via :class:`OutputLanguageDialog` right before document
    #: generation. Defaults to the UI language until the dialog asks.
    docs_language: str = "en"
    #: Profile entry ids (experience / education) the user picked 'No - skip
    #: it' on inside a discrepancy clarifying question. Filtered out of the
    #: candidate profile right before resume / cover / interview / gap calls
    #: so excluded rows never reach the AI.
    excluded_entry_ids: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------
class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("settings.title"))
        self.setMinimumWidth(560)

        self._settings = settings

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        title = QLabel(t("settings.section"))
        title.setStyleSheet(
            f"color: {Tokens.text}; font-size: 18px; font-weight: 600;"
        )
        layout.addWidget(title)

        info = QLabel(t("settings.tip_html"))
        info.setTextFormat(Qt.RichText)
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color: {Tokens.text}; font-size: 12px;"
            f" background-color: {Tokens.surface_alt};"
            f" border: 1px solid {Tokens.border};"
            f" border-radius: 8px; padding: 10px 12px;"
        )
        layout.addWidget(info)

        form = QFormLayout()
        form.setSpacing(10)
        self._provider_combo = QComboBox()
        self._provider_combo.addItem(t("settings.provider.fake"), "fake")
        self._provider_combo.addItem(
            t("settings.provider.openai"),
            "openai_compatible",
        )
        self._provider_combo.setItemData(
            0,
            t("settings.provider.fake_tip"),
            Qt.ToolTipRole,
        )
        self._provider_combo.setItemData(
            1,
            t("settings.provider.openai_tip"),
            Qt.ToolTipRole,
        )
        if settings.ai_provider == "openai_compatible":
            self._provider_combo.setCurrentIndex(1)
        form.addRow(t("settings.provider"), self._provider_combo)

        self._base_url = QLineEdit(settings.ai_base_url)
        form.addRow(t("settings.base_url"), self._base_url)

        self._api_key = QLineEdit(settings.ai_api_key)
        self._api_key.setEchoMode(QLineEdit.Password)
        form.addRow(t("settings.api_key"), self._api_key)

        self._model = QLineEdit(settings.ai_model)
        form.addRow(t("settings.model"), self._model)
        layout.addLayout(form)

        hint = QLabel(t("settings.examples_html"))
        hint.setTextFormat(Qt.RichText)
        hint.setStyleSheet(f"color: {Tokens.text_muted}; font-size: 11px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.Ok)
        ok_btn.setProperty("variant", "primary")
        ok_btn.style().unpolish(ok_btn)
        ok_btn.style().polish(ok_btn)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, alignment=Qt.AlignRight)

    def accepted_settings(self) -> Settings:
        os.environ["AI_PROVIDER"] = self._provider_combo.currentData()
        os.environ["AI_BASE_URL"] = self._base_url.text().strip()
        os.environ["AI_API_KEY"] = self._api_key.text().strip()
        os.environ["AI_MODEL"] = self._model.text().strip()
        return load_settings()


# ---------------------------------------------------------------------------
# Pre-deletion confirmation dialog
# ---------------------------------------------------------------------------
@dataclass
class _RemovalCandidate:
    """Single row the user is about to drop from the tailored resume."""

    entry_id: str
    section: str  # one of dedup.confirm.section.* keys (without the prefix)
    label: str
    reason: str


class SectionRemovalConfirmDialog(QDialog):
    """Modal that lists rows the user already marked as 'skip'.

    Shown right before document generation so the user gets a final
    "are you SURE you want to remove these?" loop. Each row is rendered
    with a *Keep this entry* checkbox defaulting to **checked**, i.e. the
    safe default keeps the row. Unchecking the box keeps it on the
    exclusion list.
    """

    def __init__(
        self,
        candidates: list[_RemovalCandidate],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("dedup.confirm.title"))
        self.setModal(True)
        self.setMinimumWidth(640)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QLabel(t("dedup.confirm.title"))
        title.setStyleSheet(
            f"color: {Tokens.text}; font-size: 17px; font-weight: 600;"
        )
        layout.addWidget(title)

        body = QLabel(t("dedup.confirm.body"))
        body.setWordWrap(True)
        body.setStyleSheet(f"color: {Tokens.text_muted}; font-size: 12px;")
        layout.addWidget(body)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(10)
        scroll.setWidget(host)
        layout.addWidget(scroll, stretch=1)

        self._checkboxes: dict[str, QCheckBox] = {}

        # Group candidates by section so the user has a clean overview.
        groups: dict[str, list[_RemovalCandidate]] = {}
        for cand in candidates:
            groups.setdefault(cand.section, []).append(cand)

        for section, items in groups.items():
            header = QLabel(t(f"dedup.confirm.section.{section}"))
            header.setStyleSheet(
                f"color: {Tokens.text}; font-size: 13px; font-weight: 600; "
                "padding-top: 6px;"
            )
            host_layout.addWidget(header)
            for cand in items:
                row = QFrame()
                row.setStyleSheet(
                    f"QFrame {{ background-color: {Tokens.surface_alt}; "
                    f"border: 1px solid {Tokens.border}; border-radius: 8px; "
                    "padding: 8px 10px; }}"
                )
                row_layout = QVBoxLayout(row)
                row_layout.setContentsMargins(10, 8, 10, 8)
                row_layout.setSpacing(4)
                cb = QCheckBox(f"{t('dedup.confirm.keep')} - {cand.label}")
                cb.setChecked(True)
                cb.setStyleSheet(
                    f"QCheckBox {{ color: {Tokens.text}; font-size: 13px; }}"
                )
                self._checkboxes[cand.entry_id] = cb
                row_layout.addWidget(cb)
                reason = QLabel(t("dedup.confirm.reason", reason=cand.reason))
                reason.setWordWrap(True)
                reason.setStyleSheet(
                    f"color: {Tokens.text_muted}; font-size: 11px; "
                    "padding-left: 22px; font-style: italic;"
                )
                row_layout.addWidget(reason)
                host_layout.addWidget(row)

        host_layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.button(QDialogButtonBox.Ok).setText(t("dedup.confirm.continue"))
        buttons.button(QDialogButtonBox.Ok).setProperty("variant", "primary")
        buttons.button(QDialogButtonBox.Cancel).setText(t("dedup.confirm.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, alignment=Qt.AlignRight)

    def kept_ids(self) -> set[str]:
        """Return the set of entry ids the user un-checked, i.e. wants to KEEP."""
        return {eid for eid, cb in self._checkboxes.items() if cb.isChecked()}


# ---------------------------------------------------------------------------
# Header bar
# ---------------------------------------------------------------------------
class _HeaderBar(QFrame):
    """Slim top header: page title on the left, status chip on the right."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "header")
        self.setStyleSheet(
            f"QFrame[role='header'] {{"
            f"  background-color: {Tokens.bg};"
            f"  border-bottom: 1px solid {Tokens.border};"
            f"}}"
        )
        self.setFixedHeight(54)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(28, 0, 18, 0)
        layout.setSpacing(10)

        self._title = QLabel(t("sidebar.setup.title"))
        self._title.setStyleSheet(
            f"color: {Tokens.text}; font-size: 17px; font-weight: 600;"
        )
        layout.addWidget(self._title)

        layout.addStretch(1)

        self._provider_chip = StatusChip(t("chip.demo"), variant="demo", parent=self)
        layout.addWidget(self._provider_chip)

    def set_title(self, text: str) -> None:
        self._title.setText(text)

    def set_provider_chip(self, text: str, variant: str) -> None:
        self._provider_chip.set_variant(variant, text=text)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
_SECTION_KEYS: list[str] = ["setup", "match", "documents", "history"]
_SECTION_INDEX: dict[str, int] = {k: i for i, k in enumerate(_SECTION_KEYS)}


def _build_sections() -> list[SidebarItem]:
    """Construct the sidebar item list using the active i18n strings."""
    return [
        SidebarItem(
            key=k,
            title=t(f"sidebar.{k}.title"),
            subtitle=t(f"sidebar.{k}.subtitle"),
        )
        for k in _SECTION_KEYS
    ]


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, provider: BaseAIProvider) -> None:
        super().__init__()
        # Make sure the i18n module reflects the resolved settings before any
        # widget pulls its strings via t().
        set_language(settings.ui_language)
        self.setWindowTitle(t("app.title"))
        self.resize(1280, 820)
        self._settings = settings
        self._provider = provider
        self._state = WorkflowState(docs_language=settings.ui_language)
        self._pool = QThreadPool.globalInstance()
        self._language_actions: dict[str, QAction] = {}

        self._build_ui()
        self._refresh_provider_chip()
        self._goto("setup")
        register_listener(self._on_language_changed)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._sections = _build_sections()
        self._sidebar = Sidebar(self._sections, title="ApplyPilot")
        self._sidebar.section_clicked.connect(self._goto)
        outer.addWidget(self._sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        outer.addWidget(right, stretch=1)

        self._header = _HeaderBar()
        right_layout.addWidget(self._header)

        self._stack = QStackedWidget()
        right_layout.addWidget(self._stack, stretch=1)

        self._setup_page = SetupPage(self._provider, self._settings)
        self._setup_page.connect_sample_handler(self._on_load_sample)
        self._setup_page.job_parsed.connect(self._on_job_parsed)
        self._setup_page.profile_built.connect(self._on_profile_built)
        self._stack.addWidget(self._setup_page)

        self._match_page = MatchReportPage()
        self._match_page.back_clicked.connect(lambda: self._goto("setup"))
        self._match_page.generate_clicked.connect(self._start_document_generation)
        self._stack.addWidget(self._match_page)

        self._docs_page = DocumentsPage()
        self._docs_page.back_clicked.connect(lambda: self._goto("match"))
        self._docs_page.save_analysis_clicked.connect(self._on_save_analysis)
        self._stack.addWidget(self._docs_page)

        self._history_page = HistoryPage(self._settings)
        self._history_page.open_in_app_requested.connect(self._on_open_history_in_app)
        self._stack.addWidget(self._history_page)

        self.setStatusBar(QStatusBar())
        self._build_menu()

    def _build_menu(self) -> None:
        menu = self.menuBar()
        menu.clear()
        self._file_menu = menu.addMenu(t("menu.file"))
        self._action_settings = QAction(t("menu.settings"), self)
        self._action_settings.setShortcut(QKeySequence("Ctrl+,"))
        self._action_settings.triggered.connect(self._open_settings)
        self._file_menu.addAction(self._action_settings)
        self._action_sample = QAction(t("menu.load_sample"), self)
        self._action_sample.setShortcut(QKeySequence("Ctrl+L"))
        self._action_sample.triggered.connect(self._on_load_sample)
        self._file_menu.addAction(self._action_sample)
        self._file_menu.addSeparator()

        self._language_menu = self._file_menu.addMenu(t("menu.language"))
        self._language_group = QActionGroup(self)
        self._language_group.setExclusive(True)
        self._language_actions = {}
        for code, label_key in (("en", "menu.language.english"), ("cs", "menu.language.czech")):
            action = QAction(t(label_key), self, checkable=True)
            action.setData(code)
            action.triggered.connect(lambda _checked, c=code: self._on_language_action(c))
            self._language_group.addAction(action)
            self._language_menu.addAction(action)
            self._language_actions[code] = action
        active = get_language()
        if active in self._language_actions:
            self._language_actions[active].setChecked(True)

        self._file_menu.addSeparator()
        self._action_quit = QAction(t("menu.quit"), self)
        self._action_quit.setShortcut(QKeySequence("Ctrl+Q"))
        self._action_quit.triggered.connect(self.close)
        self._file_menu.addAction(self._action_quit)

        self._help_menu = menu.addMenu(t("menu.help"))
        self._action_about = QAction(t("menu.about"), self)
        self._action_about.triggered.connect(self._show_about)
        self._help_menu.addAction(self._action_about)

    # ----------------------------------------------------------- helpers
    def _goto(self, key: str) -> None:
        index = _SECTION_INDEX.get(key)
        if index is None:
            return
        self._stack.setCurrentIndex(index)
        self._sidebar.set_active(key)
        self._header.set_title(t(f"sidebar.{key}.title"))
        if key == "history":
            self._history_page.refresh()

    def _refresh_provider_chip(self) -> None:
        if self._provider.is_demo:
            self._header.set_provider_chip(t("chip.demo"), "demo")
        else:
            self._header.set_provider_chip(t("chip.live"), "live")

    # ----------------------------------------------------------- i18n
    def _on_language_action(self, code: str) -> None:
        if code == get_language():
            return
        set_language(code)
        try:
            set_preference("ui_language", code)
        except Exception:
            logger.warning("Could not persist UI language", exc_info=True)
        # Offer to restart immediately so menus, prompts and dialogs all
        # pick up the new locale. The live-retranslate path stays as a
        # soft fallback when the user picks "later".
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(t("restart.title"))
        box.setText(t("restart.body"))
        now_btn = box.addButton(t("restart.now"), QMessageBox.AcceptRole)
        later_btn = box.addButton(t("restart.later"), QMessageBox.RejectRole)
        box.setDefaultButton(now_btn)
        box.exec()
        if box.clickedButton() is now_btn:
            try:
                restart_app()
            except Exception:  # pragma: no cover - best-effort restart only
                logger.exception("Auto-restart failed; staying in current process")
                QMessageBox.information(
                    self, t("lang_change.title"), t("lang_change.body")
                )
        elif box.clickedButton() is later_btn:
            # Soft fallback - menus and visible widgets retranslate live but
            # some dialogs (e.g. modal QuestionsDialog already on screen)
            # cannot retroactively update.
            self.statusBar().showMessage(t("lang_change.body"), 7000)

    def _on_language_changed(self, code: str) -> None:
        """Live retranslate everything we can without rebuilding pages."""
        self.setWindowTitle(t("app.title"))
        # Update sidebar row titles and the section / activity headings.
        self._sidebar.update_row_titles(
            {k: (t(f"sidebar.{k}.title"), t(f"sidebar.{k}.subtitle")) for k in _SECTION_KEYS}
        )
        # Header title for the currently selected stack page.
        current_index = self._stack.currentIndex()
        for key, idx in _SECTION_INDEX.items():
            if idx == current_index:
                self._header.set_title(t(f"sidebar.{key}.title"))
                break
        self._refresh_provider_chip()
        # Rebuild the menu so that menu / action labels reflect the new locale.
        self._build_menu()
        # Make sure the docs language defaults follow the UI for unstarted runs.
        if self._state.match_report is None:
            self._state.docs_language = code

    def _replace_provider(self, settings: Settings) -> None:
        self._settings = settings
        self._provider = build_provider(settings)
        self._setup_page.set_provider(self._provider)
        self._refresh_provider_chip()

    # ----------------------------------------------------------- handlers
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._settings, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._replace_provider(dlg.accepted_settings())

    def _show_about(self) -> None:
        QMessageBox.about(self, t("about.title"), t("about.html"))

    def _on_load_sample(self) -> None:
        sample_dir = self._settings.sample_data_dir
        jd_path = sample_dir / "sample_job_description.txt"
        cv_path = sample_dir / "sample_cv.txt"
        li_path = sample_dir / "sample_linkedin_export.txt"
        gh_path = sample_dir / "sample_github_username.txt"

        if not jd_path.exists():
            QMessageBox.information(
                self,
                t("status.sample_missing.title"),
                t("status.sample_missing.body", path=jd_path),
            )
            return
        try:
            jd = jd_path.read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, t("status.sample_unread.title"), str(exc))
            return

        github_profile_url: str | None = None
        if gh_path.exists():
            username = gh_path.read_text(encoding="utf-8").strip()
            if username:
                github_profile_url = f"https://github.com/{username}"

        self._setup_page.preset_inputs(
            job_text=jd,
            cv=cv_path if cv_path.exists() else None,
            linkedin=li_path if li_path.exists() else None,
            github_profile_url=github_profile_url,
        )
        self._goto("setup")
        self._sidebar.set_activity(t("status.sample_loaded"))
        self.statusBar().showMessage(t("status.sample_loaded_msg"), 5000)

    # ----------------------------------------------------------- workflow
    def _on_job_parsed(self, job: JobPosting) -> None:
        self._state.job = job
        self._sidebar.set_status("setup", t("chip.active"), "active")
        self._sidebar.set_activity(
            t("status.parsed_job", title=job.title or t("status.unknown_role"))
        )

    def _on_profile_built(self, profile: CandidateProfile) -> None:
        self._state.candidate = profile
        if self._state.job is None:
            QMessageBox.warning(
                self, t("status.no_job.title"), t("status.no_job.body")
            )
            return
        self._sidebar.set_activity(t("status.computing_match"))
        self._start_match()

    def _start_match(self) -> None:
        provider = self._provider
        job = self._state.job
        candidate = self._state.candidate
        answers = self._state.answers
        ui_lang = get_language()
        assert job is not None and candidate is not None

        self.statusBar().showMessage(t("status.computing_match"))

        def work():
            return compute_match(
                provider, job, candidate, answers, output_language=ui_lang
            )

        run_in_background(
            self._pool, work,
            on_finished=self._on_match_done,
            on_failed=self._on_workflow_failed,
        )

    def _on_match_done(self, result) -> None:
        report, evidence = result
        self._state.match_report = report
        self._state.evidence = evidence
        self.statusBar().clearMessage()
        if needs_clarifying_questions(self._state.job, evidence):
            self._fetch_clarifying_questions()
        else:
            self._show_match_report()

    def _fetch_clarifying_questions(self) -> None:
        provider = self._provider
        job = self._state.job
        candidate = self._state.candidate
        answers = self._state.answers
        ui_lang = get_language()

        self.statusBar().showMessage(t("status.generating_questions"))
        self._sidebar.set_activity(t("status.generating_questions"))
        # Block "Run analysis" while the AI prepares clarifying questions
        # to prevent the user from queueing a second pipeline run on top
        # of the in-flight one.
        self._setup_page.set_analysis_blocked(
            t("setup.status.blocked.generating_questions")
        )

        def work():
            return generate_questions(
                provider, job, candidate, answers, output_language=ui_lang
            )

        run_in_background(
            self._pool, work,
            on_finished=self._on_questions_loaded,
            on_failed=self._on_workflow_failed,
        )

    def _on_questions_loaded(self, questions: list[ClarifyingQuestion]) -> None:
        self.statusBar().clearMessage()
        self._state.pending_questions = questions
        if not questions:
            self._setup_page.set_analysis_blocked(None)
            self._show_match_report()
            return
        # Keep the run button gated while the modal is open so a stray
        # click on the underlying setup page doesn't start a parallel run.
        self._setup_page.set_analysis_blocked(
            t("setup.status.blocked.questions_pending")
        )
        dlg = QuestionsDialog(questions, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._state.answers = dlg.answers()
            # Translate any 'discrepancy:<id>' answers of "No - skip it" into
            # the WorkflowState exclusion set so document generation skips
            # those rows entirely.
            self._state.excluded_entry_ids = excluded_ids_from_answers(
                self._state.answers.answers
            )
            self._start_match_after_answers()
        else:
            self._setup_page.set_analysis_blocked(None)
            self._show_match_report()

    def _start_match_after_answers(self) -> None:
        provider = self._provider
        job = self._state.job
        candidate = self._state.candidate
        answers = self._state.answers
        ui_lang = get_language()

        self.statusBar().showMessage(t("status.recomputing_match"))
        self._sidebar.set_activity(t("status.recomputing_match_short"))
        self._setup_page.set_analysis_blocked(
            t("setup.status.blocked.recomputing")
        )

        def work():
            return compute_match(
                provider, job, candidate, answers, output_language=ui_lang
            )

        run_in_background(
            self._pool, work,
            on_finished=self._on_recompute_done,
            on_failed=self._on_workflow_failed,
        )

    def _on_recompute_done(self, result) -> None:
        report, evidence = result
        self._state.match_report = report
        self._state.evidence = evidence
        self.statusBar().clearMessage()
        self._setup_page.set_analysis_blocked(None)
        self._show_match_report()

    def _show_match_report(self) -> None:
        assert self._state.match_report is not None
        self._match_page.set_report(self._state.match_report)
        self._sidebar.set_status("setup", t("chip.done"), "done")
        self._sidebar.set_status("match", t("chip.ready"), "active")
        self._sidebar.set_activity(
            t("status.match_score", score=self._state.match_report.overall_score)
        )
        # Match is on screen, the user can now safely re-run analysis.
        self._setup_page.set_analysis_blocked(None)
        self._goto("match")

    def _start_document_generation(self) -> None:
        provider = self._provider
        job = self._state.job
        candidate = self._state.candidate
        answers = self._state.answers
        match_report = self._state.match_report
        evidence = self._state.evidence
        assert job and candidate and match_report and evidence

        # Ask the user which language the documents should be in. Default to
        # the previously chosen language (or the UI language on first run).
        default_lang = self._state.docs_language or get_language()
        dlg = OutputLanguageDialog(default=default_lang, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        docs_lang = dlg.selected_language()
        self._state.docs_language = docs_lang

        # Last-chance modal: list every experience/education/certification/
        # course row currently scheduled for removal so the user can rescue
        # any they want to keep before we burn AI tokens. Cancelling here
        # aborts the whole document generation step.
        if not self._confirm_section_removals(candidate):
            return

        # Drop experience / education rows the user marked as 'No - skip it'
        # in the discrepancy questions. The original profile remains on
        # WorkflowState so re-running the pipeline with a different exclusion
        # set works without re-fetching anything.
        candidate_for_docs = filter_profile_entries(
            candidate, self._state.excluded_entry_ids
        )

        self.statusBar().showMessage(t("status.generating_docs"))
        self._sidebar.set_activity(t("status.generating_docs"))

        def work():
            resume = generate_tailored_resume(
                provider, job, candidate_for_docs, answers, evidence.items,
                output_language=docs_lang,
            )
            cover = generate_cover_letter(
                provider, job, candidate_for_docs, answers, output_language=docs_lang
            )
            interview = generate_interview_questions(
                provider, job, candidate_for_docs, output_language=docs_lang
            )
            gaps = generate_skill_gap_plan(
                provider, match_report, job, output_language=docs_lang
            )
            return (resume, cover, interview, gaps)

        run_in_background(
            self._pool, work,
            on_finished=self._on_documents_done,
            on_failed=self._on_workflow_failed,
        )

    def _confirm_section_removals(self, candidate: CandidateProfile) -> bool:
        """Show a confirmation modal listing rows about to be removed.

        Returns ``True`` if the user wants to proceed with document
        generation (regardless of which rows they kept) and ``False`` if
        they cancelled. Side effect: mutates
        ``self._state.excluded_entry_ids`` to drop any ids the user opted
        to keep, so the eventual ``filter_profile_entries`` call sees the
        final exclusion set.

        When the exclusion set is empty (and no AI-suggested removals have
        been collected) we skip the dialog entirely and return ``True``.
        """
        excluded_ids = self._state.excluded_entry_ids
        if not excluded_ids:
            return True

        candidates: list[_RemovalCandidate] = []

        # Map answers back to question ids so we can show the user *why*
        # a row is on the chopping block.
        answer_lookup: dict[str, str] = {
            a.question_id.split("discrepancy:", 1)[-1]: (a.answer or "")
            for a in self._state.answers.answers
            if a.question_id.startswith("discrepancy:")
            and not a.question_id.startswith("discrepancy:date:")
        }

        for entry in candidate.experience:
            if not entry.id or entry.id not in excluded_ids:
                continue
            label_bits = [entry.title or "Role"]
            if entry.company:
                label_bits.append(f"@ {entry.company}")
            if entry.period:
                label_bits.append(f"({entry.period})")
            label = " ".join(label_bits)
            reason = answer_lookup.get(entry.id) or t(
                "dedup.confirm.reason.single_source"
            )
            candidates.append(
                _RemovalCandidate(
                    entry_id=entry.id,
                    section="experience",
                    label=label,
                    reason=reason,
                )
            )

        for entry in candidate.education:
            if not entry.id or entry.id not in excluded_ids:
                continue
            label_bits = [entry.degree or "Studies"]
            if entry.institution:
                label_bits.append(f"@ {entry.institution}")
            if entry.period:
                label_bits.append(f"({entry.period})")
            label = " ".join(label_bits)
            reason = answer_lookup.get(entry.id) or t(
                "dedup.confirm.reason.single_source"
            )
            candidates.append(
                _RemovalCandidate(
                    entry_id=entry.id,
                    section="education",
                    label=label,
                    reason=reason,
                )
            )

        if not candidates:
            return True

        dlg = SectionRemovalConfirmDialog(candidates, parent=self)
        result = dlg.exec()
        if result != QDialog.Accepted:
            return False
        kept_ids = dlg.kept_ids()
        # Anything the user explicitly KEPT (checkbox stayed checked) drops
        # off the exclusion list - but anything they unchecked stays on it.
        if kept_ids:
            self._state.excluded_entry_ids = (
                self._state.excluded_entry_ids - kept_ids
            )
        return True

    def _on_documents_done(self, result) -> None:
        resume, cover, interview, gaps = result
        self._state.resume = resume
        self._state.cover_letter = cover
        self._state.interview = interview
        self._state.gaps = gaps
        package = GeneratedApplicationPackage(
            job_posting=self._state.job,  # type: ignore[arg-type]
            candidate_profile=self._state.candidate,  # type: ignore[arg-type]
            answers=self._state.answers,
            match_report=self._state.match_report,  # type: ignore[arg-type]
            tailored_resume=resume,
            cover_letter=cover,
            interview_questions=interview,
            skill_gap_plan=gaps,
            evidence=list(self._state.evidence.items) if self._state.evidence else [],
            generated_at=datetime.now(),
            output_language=self._state.docs_language or get_language(),
        )
        self._state.package = package
        self._docs_page.load_package(package)
        self.statusBar().clearMessage()
        self._sidebar.set_status("match", t("chip.done"), "done")
        self._sidebar.set_status("documents", t("chip.ready"), "active")
        self._sidebar.set_activity(t("status.docs_ready"))
        self._goto("documents")

    def _on_save_analysis(self) -> None:
        if not self._state.package:
            QMessageBox.warning(
                self, t("status.no_save.title"), t("status.no_save.body")
            )
            return
        package = self._state.package

        def work():
            paths = export_package(package, self._settings.output_dir)
            entry = append_history(self._settings.output_dir, package)
            return paths, entry

        self.statusBar().showMessage(t("status.exporting"))

        def on_done(result):
            paths, entry = result
            self.statusBar().clearMessage()
            self._docs_page.set_status(t("docs.saved_status", path=paths.folder))
            self._sidebar.set_status("documents", t("chip.saved"), "done")
            self._sidebar.set_activity(
                t("status.score_summary", n=9, folder=Path(paths.folder).name)
            )
            QMessageBox.information(
                self,
                t("status.analysis_saved.title"),
                t(
                    "status.analysis_saved.body",
                    folder=paths.folder,
                    score=entry.match_score,
                ),
            )

        run_in_background(
            self._pool, work,
            on_finished=on_done,
            on_failed=self._on_workflow_failed,
        )

    def _on_open_history_in_app(self, folder_path: str) -> None:
        try:
            payload = load_package_files(folder_path)
        except OSError as exc:
            QMessageBox.warning(self, t("status.history_load_failed"), str(exc))
            return
        if not (payload.resume_md or payload.cover_letter_md or payload.match_report_md):
            QMessageBox.information(
                self,
                t("status.history_empty.title"),
                t("status.history_empty.body", folder=folder_path),
            )
            return
        self._docs_page.load_from_stored_analysis(payload)
        self._sidebar.set_status("documents", t("chip.active"), "active")
        self._sidebar.set_activity(
            t("status.reopened", folder=Path(folder_path).name)
        )
        self._goto("documents")

    def _on_workflow_failed(self, message: str) -> None:
        self.statusBar().clearMessage()
        self._sidebar.set_activity(t("status.workflow_error"))
        # Make sure the Run analysis button always recovers when the
        # background pipeline crashes; otherwise the user is stranded
        # with a permanently disabled primary action.
        self._setup_page.set_analysis_blocked(None)
        QMessageBox.critical(self, t("status.workflow_error"), message)


__all__ = ["MainWindow"]
