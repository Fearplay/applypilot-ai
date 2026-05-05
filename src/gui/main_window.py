"""Main window: slim sidebar nav, modern header chip, modal questions."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
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
from ..ai.pricing import lookup_pricing
from ..config import Settings
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
from ..services.cover_letter_generator import (
    generate_cover_letter,
    refine_cover_letter,
)
from ..services.export_service import export_package
from ..services.gap_plan_generator import generate_skill_gap_plan
from ..services.history_service import append_history, load_package_files
from ..services.interview_generator import generate_interview_questions
from ..services.match_engine import compute_match, needs_clarifying_questions
from ..services.profile_dedup import (
    apply_structural_choice,
    excluded_ids_from_answers,
    filter_profile_entries,
)
from ..services.question_generator import generate_questions
from ..services.resume_generator import generate_tailored_resume, refine_tailored_resume
from ..utils.preferences import set_preference
from ..utils.restart import restart_app
from .documents_page import DocumentsPage
from .history_page import HistoryPage
from .match_report_page import MatchReportPage
from .output_language_dialog import OutputLanguageDialog
from .questions_dialog import QuestionsDialog
from .refine_confirm_dialog import RefineConfirmDialog
from .settings_dialog import SettingsDialog
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
    #: Visual theme slug picked in :class:`OutputLanguageDialog`. The dialog
    #: returns either ``random`` (sentinel) or a concrete slug from
    #: :data:`src.services.document_themes.RESUME_THEMES`. The window
    #: resolves the random sentinel to a real slug before storing so every
    #: subsequent renderer call uses the same look (preview, save, export).
    docs_theme: str = "teal_sidebar"
    #: Profile entry ids (experience / education) the user picked 'No - skip
    #: it' on inside a discrepancy clarifying question. Filtered out of the
    #: candidate profile right before resume / cover / interview / gap calls
    #: so excluded rows never reach the AI.
    excluded_entry_ids: set[str] = field(default_factory=set)
    #: AI-suggested removal candidates (entry_id -> human-friendly reason)
    #: produced by the match-report pass. The user still has to tick them in
    #: :class:`SectionRemovalConfirmDialog` for the row to actually drop, so
    #: this map only feeds the *display* of why a row is in the dialog.
    ai_removal_reasons: dict[str, str] = field(default_factory=dict)
    #: Profile entry ids the user already saw in the removal-confirm dialog
    #: and explicitly chose to KEEP (left the checkbox unticked). Subsequent
    #: runs filter these out before showing the dialog so the user is not
    #: re-prompted about the same row over and over - they already answered
    #: "keep" once. Reset by ``_reset_workflow_for_fresh_run`` so the
    #: 'Re-ask clarifying questions' checkbox brings the dialog back.
    kept_entry_ids: set[str] = field(default_factory=set)
    #: The ``explanation`` string the AI returned in the previous refine
    #: round. Threaded into the next refine call so the model can
    #: interpret short affirmations ('ano', 'yes') as agreement with the
    #: suggestion it made earlier - without this context, a bare 'ano'
    #: arrives at the AI as a no-op feedback. Reset whenever the resume
    #: is regenerated from scratch (new package) so the previous round's
    #: context never bleeds into a different analysis.
    last_refine_explanation: str = ""
    #: ``True`` once the user ticks "Don't ask again this session" in
    #: :class:`RefineConfirmDialog`. Reset on app restart so the safer
    #: default returns next time. Settings.ai_confirm_refine still wins:
    #: when the env flag is False the modal never shows in the first
    #: place regardless of this field.
    skip_refine_confirm: bool = False


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
    """Modal listing rows the AI / discrepancy-flow flagged for removal.

    Shown right before document generation so the user gets a final
    "do you actually want to remove these?" loop. Two checkbox defaults:

    * Rows the user already explicitly told us to skip in the discrepancy
      questions (their ids appear in ``pre_checked_ids``) come in
      **default-checked** with a small badge - the user said "skip" once
      and we honour that. Unticking the box brings the row back into the
      resume.
    * Rows the AI suggested removing (single-source / off-topic) come in
      default-unchecked. The user has to actively tick them to delete.

    This split fixes the bug where a row marked 'No - skip it' in the
    discrepancy step survived because the second dialog defaulted every
    box to unchecked, and clicking Continue silently re-included the
    row in the exported resume.
    """

    def __init__(
        self,
        candidates: list[_RemovalCandidate],
        pre_checked_ids: set[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("dedup.confirm.title"))
        self.setModal(True)
        self.setMinimumWidth(640)

        pre_checked = set(pre_checked_ids or set())

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

        # Inline hint banner shown only when at least one row is pre-
        # checked, so the user immediately understands why some boxes
        # are already ticked. Hidden otherwise to avoid noise.
        if pre_checked & {c.entry_id for c in candidates}:
            hint = QLabel(t("dedup.confirm.preselected_hint"))
            hint.setWordWrap(True)
            hint.setStyleSheet(
                f"color: {Tokens.text}; font-size: 12px; "
                f"background-color: {Tokens.surface_alt}; "
                f"border: 1px solid {Tokens.border}; "
                "border-radius: 6px; padding: 8px 10px;"
            )
            layout.addWidget(hint)

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
                cb = QCheckBox(f"{t('dedup.confirm.remove_action')} - {cand.label}")
                # Pre-check rows the user already said 'skip' on so
                # ticking Continue actually honours their earlier
                # decision. Anything else stays unchecked = stays in.
                cb.setChecked(cand.entry_id in pre_checked)
                cb.setStyleSheet(
                    f"QCheckBox {{ color: {Tokens.text}; font-size: 13px; }}"
                )
                self._checkboxes[cand.entry_id] = cb
                row_layout.addWidget(cb)
                if cand.entry_id in pre_checked:
                    badge = QLabel(t("dedup.confirm.preselected_badge"))
                    badge.setStyleSheet(
                        f"color: {Tokens.text}; font-size: 11px; "
                        f"background-color: {Tokens.bg}; "
                        "border-radius: 4px; padding: 2px 6px; "
                        "margin-left: 22px; font-weight: 600;"
                    )
                    badge.setMaximumWidth(220)
                    row_layout.addWidget(badge)
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

    def remove_ids(self) -> set[str]:
        """Return the set of entry ids the user actively ticked for removal.

        Anything not ticked stays in the resume - the safe default is to keep
        every row even if it was originally on the AI's removal proposal.
        """
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
        self._docs_page.refine_requested.connect(self._on_refine_requested)
        self._docs_page.change_layout_clicked.connect(self._on_change_layout)
        self._docs_page.change_colour_clicked.connect(self._on_change_colour)
        self._stack.addWidget(self._docs_page)

        self._history_page = HistoryPage(self._settings)
        self._history_page.open_in_app_requested.connect(self._on_open_history_in_app)
        self._stack.addWidget(self._history_page)

        # The live AI session counter used to live in the status bar,
        # but the user complained it was too easy to miss inside the
        # ephemeral status messages. The primary cost surface is now the
        # SESSION COST block directly above the activity row in the
        # sidebar (see :class:`Sidebar`); the status bar stays clean for
        # transient workflow messages so the cost block can never get
        # visually clobbered.
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
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

    def _set_provider_trigger(self, trigger: str) -> None:
        """Best-effort tag for the next AI call. Skips fake providers."""
        setter = getattr(self._provider, "set_trigger", None)
        if callable(setter):
            try:
                setter(trigger)
            except Exception:  # pragma: no cover - audit must not break flow
                logger.debug("set_trigger failed", exc_info=True)

    def _estimate_refine_cost(self) -> float | None:
        """Rough $ estimate shown in :class:`RefineConfirmDialog`.

        Uses the current resume size as a proxy for the prompt + a
        baseline 1500 token completion. Better than nothing - the actual
        per-call price prints in the audit log right after the request.
        Returns ``None`` when the model has no entry in the pricing
        table (Custom / Ollama / unknown alias).
        """
        pricing = lookup_pricing(self._settings.ai_model)
        if pricing.input_per_million == 0.0 and pricing.output_per_million == 0.0:
            return None
        resume_chars = 0
        if self._state.resume is not None:
            try:
                resume_chars = len(
                    self._state.resume.model_dump_json()
                )
            except Exception:
                resume_chars = 0
        # ~4 chars per token on average; pad for the system prompt and
        # candidate context (~6k tokens for a typical CV+JD bundle).
        prompt_tokens = max(2000, (resume_chars // 4) + 6000)
        completion_tokens = 1500
        return (
            prompt_tokens * pricing.input_per_million
            + completion_tokens * pricing.output_per_million
        ) / 1_000_000.0

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
        # Honour the 'Re-ask clarifying questions' checkbox: if the user
        # ticked it before clicking Run analysis, throw away the answers
        # and skip-decisions from the previous run so the clarifying-
        # questions dialog and the removal-confirmation dialog reappear.
        # Without this reset the second analysis silently reuses prior
        # answers and the user gets a "ghost" pipeline that never asks
        # anything despite Run analysis being a fresh user intent.
        if self._setup_page.is_fresh_run_requested():
            self._reset_workflow_for_fresh_run()
            self._setup_page.acknowledge_fresh_run()
        self._sidebar.set_status("setup", t("chip.active"), "active")
        self._sidebar.set_activity(
            t("status.parsed_job", title=job.title or t("status.unknown_role"))
        )

    def _reset_workflow_for_fresh_run(self) -> None:
        """Wipe stateful inputs that survive between analyses.

        Clears clarifying-question answers, the discrepancy exclusion set
        and any AI-suggested removals so the orchestrator behaves as if
        this were the very first run. Keeps the parsed job posting and
        candidate profile because they're recomputed from the setup form
        on every run anyway.
        """
        self._state.answers = AnswersBundle()
        self._state.pending_questions = []
        self._state.excluded_entry_ids = set()
        self._state.ai_removal_reasons = {}
        # Forget the rows the user previously chose to keep so the
        # confirmation dialog asks again on the fresh run.
        self._state.kept_entry_ids = set()
        # Reset docs_language so the OutputLanguageDialog defaults follow
        # the current UI language again instead of the previous run's
        # picked language.
        self._state.docs_language = get_language()
        # Wipe the previous round's refine context so a fresh analysis
        # never inherits an 'ano' continuation that belongs to the
        # earlier resume.
        self._state.last_refine_explanation = ""

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
        self._set_provider_trigger("MainWindow._start_match")

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
        self._capture_ai_removal_reasons(report)
        self.statusBar().clearMessage()
        if needs_clarifying_questions(self._state.job, evidence):
            self._fetch_clarifying_questions()
        else:
            self._show_match_report()

    def _capture_ai_removal_reasons(self, report) -> None:
        """Cache ``report.suggested_removals`` as ``entry_id -> reason`` so the
        pre-generation confirmation dialog can show WHY each row was flagged.

        Filters out suggestions whose ``entry_id`` doesn't actually exist on
        the current candidate profile - protects against stale ids when the
        AI hallucinates one or when the user re-ran the analysis with a
        different exclusion set."""
        candidate = self._state.candidate
        if candidate is None or report is None:
            self._state.ai_removal_reasons = {}
            return
        valid_ids: set[str] = set()
        for entry in candidate.experience:
            if entry.id:
                valid_ids.add(entry.id)
        for entry in candidate.education:
            if entry.id:
                valid_ids.add(entry.id)
        reasons: dict[str, str] = {}
        for s in getattr(report, "suggested_removals", None) or []:
            entry_id = getattr(s, "entry_id", "") or ""
            if not entry_id or entry_id not in valid_ids:
                continue
            reasons[entry_id] = (getattr(s, "reason", "") or "").strip()
        self._state.ai_removal_reasons = reasons

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
        self._set_provider_trigger("MainWindow._fetch_clarifying_questions")

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
            # Apply structural-mismatch decisions FIRST. These can drop CV or
            # LinkedIn rows referenced by the rest of the answer set, so we
            # mutate the candidate profile before computing the exclusion
            # ids that get fed to the resume / cover / interview / gap
            # generators downstream.
            self._apply_structural_answers()
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

    def _apply_structural_answers(self) -> None:
        """Mutate ``self._state.candidate`` based on every ``discrepancy:struct:``
        answer the user just gave.

        Idempotent: applying the same answers twice is a no-op the second
        time around because the relevant rows are already gone after the
        first pass. Safe to call when no structural questions exist.
        """
        candidate = self._state.candidate
        if candidate is None:
            return
        for ans in self._state.answers.answers:
            qid = ans.question_id or ""
            if not qid.startswith("discrepancy:struct:"):
                continue
            cv_entry_id = qid.split("discrepancy:struct:", 1)[-1]
            if not cv_entry_id:
                continue
            apply_structural_choice(candidate, cv_entry_id, ans.answer or "")

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
        self._set_provider_trigger("MainWindow._start_match_after_answers")

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
        self._capture_ai_removal_reasons(report)
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

        # Ask the user which language + visual theme the documents should be
        # in. Default to the previously chosen language (or the UI language on
        # first run); the dialog persists the theme via preferences so the
        # next run pre-selects the same look.
        default_lang = self._state.docs_language or get_language()
        dlg = OutputLanguageDialog(
            default=default_lang,
            default_theme=self._state.docs_theme,
            parent=self,
        )
        if dlg.exec() != QDialog.Accepted:
            return
        docs_lang = dlg.selected_language()
        self._state.docs_language = docs_lang
        # Resolve the random sentinel right here so every downstream
        # consumer (preview, save, export) renders with the same theme.
        from ..services.document_themes import RANDOM_THEME_SLUG, resolve_theme

        picked_theme = dlg.selected_theme()
        if picked_theme == RANDOM_THEME_SLUG:
            resolved = resolve_theme(RANDOM_THEME_SLUG)
            self._state.docs_theme = resolved.slug
        else:
            self._state.docs_theme = resolve_theme(picked_theme).slug

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
        self._match_page.set_generation_enabled(False)
        self._set_provider_trigger("MainWindow._start_document_generation")

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
        """Show a confirmation modal listing rows the AI / discrepancy flow
        suggested for removal.

        Returns ``True`` if the user wants to proceed with document
        generation and ``False`` if they cancelled. Side effect: mutates
        ``self._state.excluded_entry_ids`` to be the FINAL set of ids that
        should be dropped from the candidate profile - i.e. only the rows
        the user actively ticked in the dialog.

        When there are no candidates to display (no exclusions and no
        AI-suggested removals) we skip the dialog entirely and return ``True``.
        """
        excluded_ids = set(self._state.excluded_entry_ids or set())
        ai_reasons = dict(self._state.ai_removal_reasons or {})
        kept_ids = set(self._state.kept_entry_ids or set())
        review_ids = excluded_ids | set(ai_reasons.keys())
        # Drop rows the user already explicitly chose to keep in an earlier
        # round of the same workflow. Excluded rows still show up because
        # their pre-checked default lets the user re-confirm "yes, skip"
        # quickly; rows the user actively unticked stay invisible until the
        # 'Re-ask clarifying questions' fresh-run reset.
        review_ids -= (kept_ids - excluded_ids)
        if not review_ids:
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

        def _reason_for(entry_id: str) -> str:
            ai_reason = ai_reasons.get(entry_id)
            if ai_reason:
                return t(
                    "dedup.confirm.reason.unrelated", reason=ai_reason
                )
            answer = answer_lookup.get(entry_id)
            if answer:
                return answer
            return t("dedup.confirm.reason.single_source")

        for entry in candidate.experience:
            if not entry.id or entry.id not in review_ids:
                continue
            label_bits = [entry.title or "Role"]
            if entry.company:
                label_bits.append(f"@ {entry.company}")
            if entry.period:
                label_bits.append(f"({entry.period})")
            candidates.append(
                _RemovalCandidate(
                    entry_id=entry.id,
                    section="experience",
                    label=" ".join(label_bits),
                    reason=_reason_for(entry.id),
                )
            )

        for entry in candidate.education:
            if not entry.id or entry.id not in review_ids:
                continue
            label_bits = [entry.degree or "Studies"]
            if entry.institution:
                label_bits.append(f"@ {entry.institution}")
            if entry.period:
                label_bits.append(f"({entry.period})")
            candidates.append(
                _RemovalCandidate(
                    entry_id=entry.id,
                    section="education",
                    label=" ".join(label_bits),
                    reason=_reason_for(entry.id),
                )
            )

        if not candidates:
            return True

        # Rows the user already explicitly said 'skip' on (via the
        # discrepancy clarifying questions) come in pre-checked so the
        # final dialog honours their earlier decision by default. AI-
        # suggested removals stay default-unchecked - the user has to
        # actively confirm those.
        dlg = SectionRemovalConfirmDialog(
            candidates,
            pre_checked_ids=excluded_ids,
            parent=self,
        )
        result = dlg.exec()
        if result != QDialog.Accepted:
            return False
        # Final exclusion set = exactly what the user has ticked in the
        # dialog. Untouched pre-checked rows stay in (the user accepted the
        # default), unticked rows the user previously skipped come back
        # into the resume by their explicit choice here.
        removed = dlg.remove_ids()
        self._state.excluded_entry_ids = removed
        # Remember rows the user explicitly chose to KEEP so the next run
        # in the same workflow does not re-prompt about them. Excluded
        # rows are intentionally NOT added to ``kept_entry_ids`` because
        # they are not "kept" - the user actively decided to drop them.
        shown_ids = {c.entry_id for c in candidates}
        self._state.kept_entry_ids |= (shown_ids - removed)
        return True

    def _on_documents_done(self, result) -> None:
        resume, cover, interview, gaps = result
        self._match_page.set_generation_enabled(True)
        self._state.resume = resume
        self._state.cover_letter = cover
        self._state.interview = interview
        self._state.gaps = gaps
        # The freshly generated resume has no prior refine context. Reset
        # the carry-over so the very next refine round sees an empty
        # ``previous_explanation`` (the AI never made a suggestion yet).
        self._state.last_refine_explanation = ""
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
            output_theme=self._state.docs_theme or "teal_sidebar",
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
        theme_slug = self._state.docs_theme or package.output_theme or "teal_sidebar"

        def work():
            summary = export_package(package, self._settings.output_dir, theme=theme_slug)
            entry = append_history(self._settings.output_dir, package)
            return summary, entry

        self.statusBar().showMessage(t("status.exporting"))

        def on_done(result):
            summary, entry = result
            paths = summary.paths
            self.statusBar().clearMessage()
            # Surface the PDF-skipped warning inline in the docs page
            # status bar so the user knows the markdown / docx still
            # shipped but PDFs need Chrome / Edge to be reachable.
            if summary.pdf_skipped:
                self._docs_page.set_status(
                    t("docs.pdf.skipped", path=paths.folder)
                )
            else:
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

    def _on_change_layout(self) -> None:
        """Rotate the resume's layout (structure) without changing the palette.

        The user explicitly asked for this to be SEPARATE from the
        colour swap because the previous "Change style" button only
        ever rotated the palette. We resolve the current theme, walk
        :func:`pick_different_layout` to land on a theme with a
        different ``layout_slug``, persist the new slug on the
        package, and rerender just the modern preview so the user
        instantly sees the structural change without a full reload.
        """
        self._rotate_theme_axis(axis="layout")

    def _on_change_colour(self) -> None:
        """Rotate the resume's palette without changing the layout."""
        self._rotate_theme_axis(axis="colour")

    def _rotate_theme_axis(self, *, axis: str) -> None:
        from ..services.document_themes import (
            pick_different_layout,
            pick_different_palette,
            resolve_theme,
        )

        package = self._state.package
        if package is None:
            QMessageBox.information(
                self,
                t("docs.modern.nothing_to_restyle.title"),
                t("docs.modern.nothing_to_restyle.body"),
            )
            return
        current_slug = (
            self._state.docs_theme
            or package.output_theme
            or "teal_sidebar"
        )
        current_theme = resolve_theme(current_slug)
        if axis == "layout":
            new_theme = pick_different_layout(current_theme)
        else:
            new_theme = pick_different_palette(current_theme)
        # Persist the new slug on BOTH the package (so save / export use
        # it) and the workflow state (so future regenerations honour
        # the user's latest pick). The resolve_theme cache holds the
        # synthetic combos so the slug round-trips on subsequent calls.
        package.output_theme = new_theme.slug
        self._state.docs_theme = new_theme.slug
        # Re-render just the modern-resume preview - no need to rewrite
        # the markdown editors which are theme-agnostic.
        self._docs_page.update_modern_resume_theme(package, new_theme)
        # Surface a friendly inline note so the user sees confirmation.
        if axis == "layout":
            self._docs_page.set_status(
                t(
                    "docs.modern.changed_layout",
                    name=new_theme.display_name(self._state.docs_language or "en"),
                )
            )
        else:
            self._docs_page.set_status(
                t(
                    "docs.modern.changed_colour",
                    name=new_theme.display_name(self._state.docs_language or "en"),
                )
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

    def _on_refine_requested(self, feedback: str, target: str = "resume") -> None:
        """Handle the 'Refine with AI' button from the documents page.

        ``target`` is set by :meth:`DocumentsPage._resolve_refine_target`
        from the active tab: ``"resume"`` for the markdown + modern
        resume tabs and ``"cover_letter"`` for the cover-letter tab.
        Other tabs are blocked at the documents-page level so this
        method never has to deal with them.
        """
        state = self._state
        # Both branches need a job + candidate, plus the target document
        # itself. Bail early so we never call AI without the data the
        # prompt needs to be coherent.
        if not state.job or not state.candidate:
            self._docs_page.set_refine_enabled(True)
            return
        if target == "cover_letter" and not state.cover_letter:
            self._docs_page.set_refine_enabled(True)
            return
        if target == "resume" and not state.resume:
            self._docs_page.set_refine_enabled(True)
            return

        # Confirm-before-spending modal: the user complained about
        # feeling charged "while AFK" - the actual fix is to make every
        # refine call require an active confirmation by default. The
        # checkbox in the dialog suppresses the prompt for the rest of
        # the session, the env flag (AI_CONFIRM_REFINE) suppresses it
        # globally, but the safe default after restart is to ask again.
        if (
            self._settings.ai_confirm_refine
            and not state.skip_refine_confirm
        ):
            estimated = self._estimate_refine_cost()
            confirm = RefineConfirmDialog(
                model=self._settings.ai_model,
                estimated_usd=estimated,
                parent=self,
            )
            if confirm.exec() != QDialog.Accepted:
                self._docs_page.set_refine_enabled(True)
                return
            if confirm.dont_ask_again():
                state.skip_refine_confirm = True

        provider = self._provider
        job = state.job
        # Mirror the filtering applied at initial generation so the
        # refine safety net never re-injects rows the user already
        # excluded via the discrepancy questions or the section-removal
        # dialog. Without this, ``ensure_experience_section`` would walk
        # the FULL ``state.candidate`` and silently bring back e.g.
        # 'IT Tester @ Trask Solutions' even when the user opted to drop
        # it, undoing their decision on every refine pass.
        candidate = filter_profile_entries(
            state.candidate, state.excluded_entry_ids
        )
        answers = state.answers
        docs_lang = state.docs_language or get_language()
        # Capture the AI's previous explanation so the refine prompt can
        # interpret a bare 'ano' / 'yes' as agreement with the suggestion
        # the model made in that note. The state field is updated AFTER
        # ``on_done`` so the same value is used by exactly one round and
        # the next round's "previous" is always the explanation the user
        # actually saw in the GUI before typing.
        previous_explanation = state.last_refine_explanation

        # The status message + the audit-log trigger now both record
        # WHICH document is being refined so the audit trail can answer
        # "did I burn tokens on the cover letter or the resume?".
        if target == "cover_letter":
            status_msg = t("docs.refine.status.cover_letter")
        else:
            status_msg = t("docs.refine.status.resume")
        self._docs_page.set_status(status_msg)
        self.statusBar().showMessage(status_msg)

        feedback_preview = (feedback or "").strip().replace("\n", " ")[:120]
        trigger = (
            "MainWindow._on_refine_requested "
            f"target={target!r} feedback={feedback_preview!r}"
        )
        self._set_provider_trigger(trigger)

        if target == "cover_letter":
            current_cover = state.cover_letter

            def work():
                return refine_cover_letter(
                    provider, current_cover, feedback,
                    job, candidate, answers,
                    output_language=docs_lang,
                    previous_explanation=previous_explanation,
                )

            def on_done(refined):
                # ``refine_cover_letter`` returns a ``RefinedCoverLetter``
                # with the updated cover letter AND a 1-3 sentence
                # ``explanation`` (in the docs language) we surface inline
                # so the user knows what changed.
                updated = refined.cover_letter
                state.cover_letter = updated
                state.last_refine_explanation = (
                    refined.explanation or ""
                ).strip()
                if state.package:
                    state.package.cover_letter = updated
                    # Reload via load_package so the cover-letter editor
                    # AND the modern-resume preview both refresh
                    # consistently with the new package state.
                    self._docs_page.load_package(state.package)
                self._docs_page.set_refine_enabled(True)
                inline_message = (
                    refined.explanation.strip() or t("docs.refine.done")
                )
                self._docs_page.set_status(inline_message)
                self.statusBar().clearMessage()

        else:
            current_resume = state.resume
            evidence_items = (
                list(state.evidence.items) if state.evidence else []
            )

            def work():
                return refine_tailored_resume(
                    provider, current_resume, feedback,
                    job, candidate, answers, evidence_items,
                    output_language=docs_lang,
                    previous_explanation=previous_explanation,
                )

            def on_done(refined):
                # ``refine_tailored_resume`` returns a ``RefinedResume`` with
                # the updated resume AND a 1-3 sentence ``explanation`` (in
                # the docs language) we surface inline so the user knows what
                # changed without opening the modern preview.
                updated_resume = refined.resume
                state.resume = updated_resume
                state.last_refine_explanation = (
                    refined.explanation or ""
                ).strip()
                if state.package:
                    state.package.tailored_resume = updated_resume
                    self._docs_page.load_package(state.package)
                self._docs_page.set_refine_enabled(True)
                inline_message = (
                    refined.explanation.strip() or t("docs.refine.done")
                )
                self._docs_page.set_status(inline_message)
                self.statusBar().clearMessage()

        def on_failed(message):
            self._docs_page.set_refine_enabled(True)
            self._docs_page.set_status(t("docs.refine.error", error=message))
            self.statusBar().clearMessage()

        run_in_background(
            self._pool, work,
            on_finished=on_done,
            on_failed=on_failed,
        )

    def _on_workflow_failed(self, message: str) -> None:
        self.statusBar().clearMessage()
        self._sidebar.set_activity(t("status.workflow_error"))
        self._match_page.set_generation_enabled(True)
        # Make sure the Run analysis button always recovers when the
        # background pipeline crashes; otherwise the user is stranded
        # with a permanently disabled primary action.
        self._setup_page.set_analysis_blocked(None)
        QMessageBox.critical(self, t("status.workflow_error"), message)


__all__ = ["MainWindow"]
