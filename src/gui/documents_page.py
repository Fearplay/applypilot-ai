"""Step 5: show generated documents in tabs, allow editing and export."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..models.documents import (
    CoverLetter,
    InterviewQuestion,
    SkillGap,
    TailoredResume,
)
from ..models.evidence import EvidenceItem
from ..models.match import MatchReport
from ..models.package import GeneratedApplicationPackage
from ..services.export_service import (
    cover_letter_to_markdown,
    evidence_report_to_dict,
    interview_questions_to_markdown,
    match_report_to_markdown,
    resume_to_markdown,
    skill_gap_to_markdown,
)

logger = logging.getLogger(__name__)


class DocumentsPage(QWidget):
    save_analysis_clicked = Signal()
    back_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(10)

        layout.addWidget(QLabel("<h2>Step 5 - Generated documents</h2>"))
        layout.addWidget(QLabel(
            "Review and tweak the text in each tab. The exporters use the text "
            "exactly as shown here."
        ))

        self._tabs = QTabWidget()
        self._resume_edit = self._make_editor()
        self._cover_edit = self._make_editor()
        self._match_edit = self._make_editor(read_only=True)
        self._interview_edit = self._make_editor()
        self._gap_edit = self._make_editor()
        self._evidence_edit = self._make_editor(read_only=True)
        self._tabs.addTab(self._resume_edit, "Tailored Resume")
        self._tabs.addTab(self._cover_edit, "Cover Letter")
        self._tabs.addTab(self._match_edit, "Match Report")
        self._tabs.addTab(self._interview_edit, "Interview Prep")
        self._tabs.addTab(self._gap_edit, "Skill Gap Plan")
        self._tabs.addTab(self._evidence_edit, "Evidence (read-only)")
        layout.addWidget(self._tabs, stretch=1)

        button_row = QHBoxLayout()
        back = QPushButton("<- Back")
        back.clicked.connect(self.back_clicked.emit)
        button_row.addWidget(back)

        button_row.addStretch(1)

        self._export_md_btn = QPushButton("Export current tab as Markdown...")
        self._export_md_btn.clicked.connect(self._export_current_md)
        button_row.addWidget(self._export_md_btn)

        self._export_html_btn = QPushButton("Export current tab as HTML...")
        self._export_html_btn.clicked.connect(self._export_current_html)
        button_row.addWidget(self._export_html_btn)

        self._export_docx_btn = QPushButton("Export current tab as DOCX...")
        self._export_docx_btn.clicked.connect(self._export_current_docx)
        button_row.addWidget(self._export_docx_btn)

        self._save_btn = QPushButton("Save full analysis")
        self._save_btn.setMinimumWidth(180)
        self._save_btn.setStyleSheet(
            "QPushButton { background: #1f6feb; color: white; border: none;"
            " border-radius: 6px; padding: 8px 14px; font-weight: 600; }"
        )
        self._save_btn.clicked.connect(self.save_analysis_clicked.emit)
        button_row.addWidget(self._save_btn)
        layout.addLayout(button_row)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #a8a8b3;")
        layout.addWidget(self._status)

    @staticmethod
    def _make_editor(read_only: bool = False) -> QPlainTextEdit:
        e = QPlainTextEdit()
        e.setReadOnly(read_only)
        font = e.font()
        font.setStyleHint(font.StyleHint.TypeWriter)
        font.setFamily("Cascadia Mono")
        e.setFont(font)
        return e

    # ----------------------------------------------------------- public
    def load_package(self, package: GeneratedApplicationPackage) -> None:
        self._resume_edit.setPlainText(resume_to_markdown(package.tailored_resume))
        self._cover_edit.setPlainText(cover_letter_to_markdown(package.cover_letter))
        self._match_edit.setPlainText(
            match_report_to_markdown(package.match_report, role_label=package.job_posting.title)
        )
        self._interview_edit.setPlainText(
            interview_questions_to_markdown(package.interview_questions)
        )
        self._gap_edit.setPlainText(skill_gap_to_markdown(package.skill_gap_plan))
        self._evidence_edit.setPlainText(
            json.dumps(evidence_report_to_dict(package.evidence), ensure_ascii=False, indent=2)
        )
        self._status.setText(
            f"Loaded {len(package.evidence)} evidence items - score "
            f"{package.match_report.overall_score} / 100"
        )

    def set_status(self, message: str) -> None:
        self._status.setText(message)

    def current_text(self) -> str:
        return self._tabs.currentWidget().toPlainText()

    def current_tab_name(self) -> str:
        return self._tabs.tabText(self._tabs.currentIndex())

    # ----------------------------------------------------------- exporters
    def _export_current_md(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export {self.current_tab_name()} as Markdown",
            f"{self.current_tab_name().lower().replace(' ', '_')}.md",
            "Markdown (*.md);;All files (*)",
        )
        if not path:
            return
        try:
            Path(path).write_text(self.current_text(), encoding="utf-8")
            self._status.setText(f"Saved to {path}")
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def _export_current_html(self) -> None:
        try:
            import markdown as md_lib
        except ImportError as exc:  # pragma: no cover
            QMessageBox.critical(self, "Missing dependency", str(exc))
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export {self.current_tab_name()} as HTML",
            f"{self.current_tab_name().lower().replace(' ', '_')}.html",
            "HTML (*.html);;All files (*)",
        )
        if not path:
            return
        body = md_lib.markdown(self.current_text(), extensions=["extra"])
        html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{self.current_tab_name()}</title></head><body>{body}</body></html>"
        )
        try:
            Path(path).write_text(html, encoding="utf-8")
            self._status.setText(f"Saved to {path}")
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def _export_current_docx(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export {self.current_tab_name()} as DOCX",
            f"{self.current_tab_name().lower().replace(' ', '_')}.docx",
            "Word documents (*.docx);;All files (*)",
        )
        if not path:
            return
        try:
            from docx import Document
            doc = Document()
            for line in self.current_text().splitlines():
                if line.startswith("# "):
                    doc.add_heading(line[2:], level=1)
                elif line.startswith("## "):
                    doc.add_heading(line[3:], level=2)
                elif line.startswith("### "):
                    doc.add_heading(line[4:], level=3)
                elif line.startswith("- "):
                    doc.add_paragraph(line[2:], style="List Bullet")
                else:
                    doc.add_paragraph(line)
            doc.save(path)
            self._status.setText(f"Saved to {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))


__all__ = ["DocumentsPage"]
