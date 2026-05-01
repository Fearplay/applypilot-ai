"""Main window: navigation, workflow state, demo banner, settings dialog."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..ai.base import BaseAIProvider
from ..ai.provider_factory import build_provider
from ..config import Settings, load_settings
from ..models.candidate import CandidateProfile
from ..models.documents import (
    CoverLetter,
    InterviewQuestion,
    SkillGap,
    TailoredResume,
)
from ..models.evidence import EvidenceCheckResult, EvidenceItem
from ..models.job import JobPosting
from ..models.match import AnswersBundle, ClarifyingQuestion, MatchReport
from ..models.package import GeneratedApplicationPackage
from ..services.cover_letter_generator import generate_cover_letter
from ..services.export_service import export_package
from ..services.gap_plan_generator import generate_skill_gap_plan
from ..services.history_service import append_history
from ..services.interview_generator import generate_interview_questions
from ..services.match_engine import compute_match, needs_clarifying_questions
from ..services.question_generator import generate_questions
from ..services.resume_generator import generate_tailored_resume
from .candidate_input_page import CandidateInputPage
from .documents_page import DocumentsPage
from .history_page import HistoryPage
from .job_input_page import JobInputPage
from .match_report_page import MatchReportPage
from .questions_page import QuestionsPage
from .welcome_page import WelcomePage
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


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------
class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI provider settings")
        self.setMinimumWidth(520)

        self._settings = settings

        layout = QVBoxLayout(self)
        info = QLabel(
            "Adjust the active AI provider for this session. To make the change "
            "permanent, also update <code>.env</code> in the project root."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self._provider_combo = QComboBox()
        self._provider_combo.addItem("fake (offline demo, default)", "fake")
        self._provider_combo.addItem("openai_compatible (any compatible HTTP endpoint)",
                                     "openai_compatible")
        if settings.ai_provider == "openai_compatible":
            self._provider_combo.setCurrentIndex(1)
        form.addRow("Provider:", self._provider_combo)

        self._base_url = QLineEdit(settings.ai_base_url)
        form.addRow("Base URL:", self._base_url)

        self._api_key = QLineEdit(settings.ai_api_key)
        self._api_key.setEchoMode(QLineEdit.Password)
        form.addRow("API key:", self._api_key)

        self._model = QLineEdit(settings.ai_model)
        form.addRow("Model:", self._model)
        layout.addLayout(form)

        hint = QLabel(
            "<b>Examples</b>: <br>"
            "&bull; OpenAI: <code>https://api.openai.com/v1</code> "
            "<code>gpt-4o-mini</code><br>"
            "&bull; Groq: <code>https://api.groq.com/openai/v1</code> "
            "<code>llama-3.3-70b-versatile</code><br>"
            "&bull; Mistral: <code>https://api.mistral.ai/v1</code> "
            "<code>mistral-small-latest</code><br>"
            "&bull; Ollama (local): <code>http://localhost:11434/v1</code> "
            "<code>llama3.1</code>"
        )
        hint.setTextFormat(Qt.RichText)
        hint.setStyleSheet("color: #a8a8b3;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accepted_settings(self) -> Settings:
        os.environ["AI_PROVIDER"] = self._provider_combo.currentData()
        os.environ["AI_BASE_URL"] = self._base_url.text().strip()
        os.environ["AI_API_KEY"] = self._api_key.text().strip()
        os.environ["AI_MODEL"] = self._model.text().strip()
        return load_settings()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
_STEPS = [
    ("Welcome", "Start here"),
    ("1. Job input", "Paste URL or text"),
    ("2. Candidate", "CV / LinkedIn / GitHub"),
    ("3. Questions", "Clarifying answers"),
    ("4. Match report", "Scores & evidence"),
    ("5. Documents", "Resume + cover + export"),
    ("6. History", "Past analyses"),
]


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, provider: BaseAIProvider) -> None:
        super().__init__()
        self.setWindowTitle("ApplyPilot AI")
        self.resize(1200, 800)
        self._settings = settings
        self._provider = provider
        self._state = WorkflowState()
        self._pool = QThreadPool.globalInstance()

        self._build_ui()
        self._refresh_provider_banner()
        self._stack.setCurrentIndex(0)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._banner = QLabel("")
        self._banner.setObjectName("ProviderBanner")
        self._banner.setStyleSheet(
            "#ProviderBanner { padding: 8px 14px; font-weight: 600; }"
        )
        self._banner.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(self._banner)

        splitter = QSplitter(Qt.Horizontal)
        outer.addWidget(splitter, stretch=1)

        self._nav = QListWidget()
        self._nav.setMaximumWidth(220)
        self._nav.setStyleSheet(
            "QListWidget { background: #20232a; color: #c2c5cf; border: none; }"
            "QListWidget::item { padding: 12px 14px; }"
            "QListWidget::item:selected { background: #1f6feb; color: white; }"
        )
        for title, subtitle in _STEPS:
            it = QListWidgetItem(f"{title}\n  {subtitle}")
            it.setSizeHint(it.sizeHint())
            self._nav.addItem(it)
        self._nav.currentRowChanged.connect(self._on_nav_changed)
        splitter.addWidget(self._nav)

        self._stack = QStackedWidget()
        splitter.addWidget(self._stack)
        splitter.setStretchFactor(1, 1)

        # Pages
        self._welcome = WelcomePage()
        self._welcome.start_clicked.connect(lambda: self._goto(1))
        self._welcome.load_sample_clicked.connect(self._on_load_sample)
        self._welcome.open_settings_clicked.connect(self._open_settings)
        self._stack.addWidget(self._welcome)

        self._job_page = JobInputPage(self._provider)
        self._job_page.job_parsed.connect(self._on_job_parsed)
        self._stack.addWidget(self._job_page)

        self._cand_page = CandidateInputPage(self._provider, self._settings)
        self._cand_page.profile_built.connect(self._on_profile_built)
        self._stack.addWidget(self._cand_page)

        self._questions_page = QuestionsPage()
        self._questions_page.answered.connect(self._on_questions_answered)
        self._stack.addWidget(self._questions_page)

        self._match_page = MatchReportPage()
        self._match_page.back_clicked.connect(lambda: self._goto(2))
        self._match_page.generate_clicked.connect(self._start_document_generation)
        self._stack.addWidget(self._match_page)

        self._docs_page = DocumentsPage()
        self._docs_page.back_clicked.connect(lambda: self._goto(4))
        self._docs_page.save_analysis_clicked.connect(self._on_save_analysis)
        self._stack.addWidget(self._docs_page)

        self._history_page = HistoryPage(self._settings)
        self._stack.addWidget(self._history_page)

        # Status bar + menu
        self.setStatusBar(QStatusBar())
        self._build_menu()

    def _build_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("&File")
        open_settings = QAction("AI provider &settings...", self)
        open_settings.setShortcut(QKeySequence("Ctrl+,"))
        open_settings.triggered.connect(self._open_settings)
        file_menu.addAction(open_settings)
        load_sample = QAction("Load &sample data", self)
        load_sample.setShortcut(QKeySequence("Ctrl+L"))
        load_sample.triggered.connect(self._on_load_sample)
        file_menu.addAction(load_sample)
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = menu.addMenu("&Help")
        about = QAction("&About ApplyPilot AI", self)
        about.triggered.connect(self._show_about)
        help_menu.addAction(about)

    # ----------------------------------------------------------- helpers
    def _goto(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._nav.blockSignals(True)
        self._nav.setCurrentRow(index)
        self._nav.blockSignals(False)
        if index == 6:
            self._history_page.refresh()

    def _on_nav_changed(self, row: int) -> None:
        if row >= 0:
            self._stack.setCurrentIndex(row)
            if row == 6:
                self._history_page.refresh()

    def _refresh_provider_banner(self) -> None:
        if self._provider.is_demo:
            self._banner.setStyleSheet(
                "#ProviderBanner { background: #d29922; color: #1a1a1a;"
                " padding: 8px 14px; font-weight: 600; }"
            )
            self._banner.setText(
                f"DEMO MODE - using FakeAIProvider ({self._provider.reason}). "
                "Outputs are deterministic placeholders. Open File > Settings to "
                "switch to a real AI provider."
            )
        else:
            self._banner.setStyleSheet(
                "#ProviderBanner { background: #1f8a3a; color: white;"
                " padding: 8px 14px; font-weight: 600; }"
            )
            self._banner.setText(
                f"REAL AI PROVIDER ACTIVE - {self._provider.name} "
                f"({self._provider.reason}). Each generation calls your AI provider."
            )

    def _replace_provider(self, settings: Settings) -> None:
        self._settings = settings
        self._provider = build_provider(settings)
        self._job_page.set_provider(self._provider)
        self._cand_page.set_provider(self._provider)
        self._refresh_provider_banner()

    # ----------------------------------------------------------- handlers
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._settings, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._replace_provider(dlg.accepted_settings())

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About ApplyPilot AI",
            "<h3>ApplyPilot AI</h3>"
            "<p>Job URL to Tailored Resume &amp; Cover Letter</p>"
            "<p>Provider-agnostic GenAI desktop assistant. MIT licensed.</p>"
            "<p><a href='https://github.com/Fearplay/applypilot-ai'>"
            "github.com/Fearplay/applypilot-ai</a></p>",
        )

    def _on_load_sample(self) -> None:
        sample_dir = self._settings.sample_data_dir
        jd_path = sample_dir / "sample_job_description.txt"
        cv_path = sample_dir / "sample_cv.txt"
        li_path = sample_dir / "sample_linkedin_export.txt"
        gh_path = sample_dir / "sample_github_username.txt"

        if not jd_path.exists():
            QMessageBox.information(
                self,
                "Sample data missing",
                f"Could not find {jd_path}. Sample data will be added in the next commit.",
            )
            return
        try:
            jd = jd_path.read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Could not read sample", str(exc))
            return
        self._job_page.load_text(jd)
        self._cand_page.preset_paths(
            cv=cv_path if cv_path.exists() else None,
            linkedin=li_path if li_path.exists() else None,
            github_username=gh_path.read_text(encoding="utf-8").strip()
            if gh_path.exists() else None,
        )
        self._goto(1)
        self.statusBar().showMessage(
            "Sample data loaded - click 'Analyze job' to continue.", 5000
        )

    # ----------------------------------------------------------- workflow
    def _on_job_parsed(self, job: JobPosting) -> None:
        self._state.job = job
        self._cand_page.set_job(job)
        self._goto(2)

    def _on_profile_built(self, profile: CandidateProfile) -> None:
        self._state.candidate = profile
        if self._state.job is None:
            QMessageBox.warning(self, "No job", "Please go back and analyze a job first.")
            return
        self._start_match()

    def _start_match(self) -> None:
        provider = self._provider
        job = self._state.job
        candidate = self._state.candidate
        answers = self._state.answers
        assert job is not None and candidate is not None

        self.statusBar().showMessage("Computing match score...")

        def work():
            return compute_match(provider, job, candidate, answers)

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

        self.statusBar().showMessage("Generating clarifying questions...")

        def work():
            return generate_questions(provider, job, candidate, answers)

        run_in_background(
            self._pool, work,
            on_finished=self._on_questions_loaded,
            on_failed=self._on_workflow_failed,
        )

    def _on_questions_loaded(self, questions: list[ClarifyingQuestion]) -> None:
        self.statusBar().clearMessage()
        self._state.pending_questions = questions
        if not questions:
            self._show_match_report()
            return
        self._questions_page.load_questions(questions)
        self._goto(3)

    def _on_questions_answered(self, answers: AnswersBundle) -> None:
        self._state.answers = answers
        # Recompute the match with the new answers, then jump to the report.
        self._start_match_after_answers()

    def _start_match_after_answers(self) -> None:
        provider = self._provider
        job = self._state.job
        candidate = self._state.candidate
        answers = self._state.answers

        self.statusBar().showMessage("Recomputing match with your answers...")

        def work():
            return compute_match(provider, job, candidate, answers)

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
        self._show_match_report()

    def _show_match_report(self) -> None:
        assert self._state.match_report is not None
        self._match_page.set_report(self._state.match_report)
        self._goto(4)

    def _start_document_generation(self) -> None:
        provider = self._provider
        job = self._state.job
        candidate = self._state.candidate
        answers = self._state.answers
        match_report = self._state.match_report
        evidence = self._state.evidence
        assert job and candidate and match_report and evidence

        self.statusBar().showMessage("Generating tailored resume, cover letter, interview prep and gap plan...")

        def work():
            resume = generate_tailored_resume(provider, job, candidate, answers, evidence.items)
            cover = generate_cover_letter(provider, job, candidate, answers)
            interview = generate_interview_questions(provider, job, candidate)
            gaps = generate_skill_gap_plan(provider, match_report, job)
            return (resume, cover, interview, gaps)

        run_in_background(
            self._pool, work,
            on_finished=self._on_documents_done,
            on_failed=self._on_workflow_failed,
        )

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
        )
        self._state.package = package
        self._docs_page.load_package(package)
        self.statusBar().clearMessage()
        self._goto(5)

    def _on_save_analysis(self) -> None:
        if not self._state.package:
            QMessageBox.warning(self, "Nothing to save", "Generate documents first.")
            return
        package = self._state.package

        def work():
            paths = export_package(package, self._settings.output_dir)
            entry = append_history(self._settings.output_dir, package)
            return paths, entry

        self.statusBar().showMessage("Exporting full analysis to disk...")

        def on_done(result):
            paths, entry = result
            self.statusBar().clearMessage()
            self._docs_page.set_status(f"Saved to {paths.folder}")
            QMessageBox.information(
                self,
                "Analysis saved",
                f"Saved 9 files to:\n{paths.folder}\n\n"
                f"History updated (entry score: {entry.match_score} / 100).",
            )

        run_in_background(
            self._pool, work,
            on_finished=on_done,
            on_failed=self._on_workflow_failed,
        )

    def _on_workflow_failed(self, message: str) -> None:
        self.statusBar().clearMessage()
        QMessageBox.critical(self, "Workflow error", message)


__all__ = ["MainWindow"]
