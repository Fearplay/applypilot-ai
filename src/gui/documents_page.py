"""Generated documents screen: tabbed editors and exporters."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..models.package import GeneratedApplicationPackage
from ..services.export_service import (
    cover_letter_to_markdown,
    evidence_report_to_dict,
    interview_questions_to_markdown,
    match_report_to_markdown,
    resume_to_markdown,
    skill_gap_to_markdown,
    tailored_resume_to_styled_html,
)
from .theme import Tokens

logger = logging.getLogger(__name__)

# Optional Chromium-based renderer for the Modern Resume tab. Falls back to
# QTextBrowser (which only renders a simplified subset of HTML/CSS) when the
# QtWebEngine extension is not installed.
try:  # pragma: no cover - dependent on user's PySide6 install
    from PySide6.QtWebEngineWidgets import QWebEngineView  # type: ignore[import-not-found]
    _HAS_WEB_ENGINE = True
except ImportError:  # pragma: no cover - lighter envs
    QWebEngineView = None  # type: ignore[assignment]
    _HAS_WEB_ENGINE = False


class DocumentsPage(QWidget):
    save_analysis_clicked = Signal()
    back_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(36, 24, 36, 18)
        body_layout.setSpacing(12)
        outer.addWidget(body, stretch=1)

        hint = QLabel(
            "Review and tweak each document. Exporters use the text exactly as shown."
        )
        hint.setStyleSheet(f"color: {Tokens.text_muted}; font-size: 12px;")
        body_layout.addWidget(hint)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._resume_edit = self._make_editor()
        self._modern_resume = self._build_modern_resume_tab()
        self._cover_edit = self._make_editor()
        self._match_edit = self._make_editor(read_only=True)
        self._interview_edit = self._make_editor()
        self._gap_edit = self._make_editor()
        self._evidence_edit = self._make_editor(read_only=True)
        self._tabs.addTab(self._resume_edit, "Tailored Resume")
        self._tabs.addTab(self._modern_resume, "Modern Resume")
        self._tabs.addTab(self._cover_edit, "Cover Letter")
        self._tabs.addTab(self._match_edit, "Match Report")
        self._tabs.addTab(self._interview_edit, "Interview Prep")
        self._tabs.addTab(self._gap_edit, "Skill Gap Plan")
        self._tabs.addTab(self._evidence_edit, "Evidence (read-only)")
        body_layout.addWidget(self._tabs, stretch=1)
        self._modern_resume_html: str = ""

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {Tokens.text_muted}; font-size: 12px;")
        body_layout.addWidget(self._status)

        bar = QFrame()
        bar.setStyleSheet(
            f"background-color: {Tokens.bg};"
            f" border-top: 1px solid {Tokens.border};"
        )
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(36, 12, 36, 12)
        bar_layout.setSpacing(8)
        back = QPushButton("Back to match")
        back.setProperty("variant", "ghost")
        back.clicked.connect(self.back_clicked.emit)
        bar_layout.addWidget(back)
        bar_layout.addStretch(1)

        self._export_md_btn = QPushButton("Export MD")
        self._export_md_btn.clicked.connect(self._export_current_md)
        bar_layout.addWidget(self._export_md_btn)
        self._export_html_btn = QPushButton("Export HTML")
        self._export_html_btn.clicked.connect(self._export_current_html)
        bar_layout.addWidget(self._export_html_btn)
        self._export_docx_btn = QPushButton("Export DOCX")
        self._export_docx_btn.clicked.connect(self._export_current_docx)
        bar_layout.addWidget(self._export_docx_btn)

        self._save_btn = QPushButton("Save full analysis")
        self._save_btn.setProperty("variant", "primary")
        self._save_btn.setMinimumWidth(180)
        self._save_btn.clicked.connect(self.save_analysis_clicked.emit)
        bar_layout.addWidget(self._save_btn)
        outer.addWidget(bar)

    @staticmethod
    def _make_editor(read_only: bool = False) -> QPlainTextEdit:
        e = QPlainTextEdit()
        e.setReadOnly(read_only)
        font = QFont()
        font.setStyleHint(QFont.Monospace)
        font.setFamily("Cascadia Mono")
        font.setPointSize(10)
        e.setFont(font)
        return e

    def _build_modern_resume_tab(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        if _HAS_WEB_ENGINE:
            self._modern_view: QTextBrowser | "QWebEngineView" = QWebEngineView()  # type: ignore[assignment]
        else:
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)
            browser.setStyleSheet(
                "QTextBrowser { background: #F8FAFC; color: #0F172A; "
                "border: 1px solid #E2E8F0; border-radius: 8px; }"
            )
            self._modern_view = browser
        layout.addWidget(self._modern_view, stretch=1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        info = QLabel(
            "Printable A4 preview. Use 'Open in browser' for a pixel-perfect "
            "render or 'Export styled HTML' to save the file."
            if _HAS_WEB_ENGINE
            else "Simplified preview - QtWebEngine not available. Open in browser "
            "for the full styled layout."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {Tokens.text_muted}; font-size: 11px;")
        actions.addWidget(info, stretch=1)

        open_browser = QPushButton("Open in browser")
        open_browser.clicked.connect(self._open_modern_resume_in_browser)
        actions.addWidget(open_browser)

        save_html = QPushButton("Export styled HTML")
        save_html.clicked.connect(self._export_modern_resume_html)
        actions.addWidget(save_html)

        layout.addLayout(actions)
        return wrap

    def _set_modern_resume_html(self, doc: str) -> None:
        self._modern_resume_html = doc
        if _HAS_WEB_ENGINE and isinstance(self._modern_view, QWebEngineView):  # type: ignore[arg-type]
            self._modern_view.setHtml(doc, QUrl("about:blank"))
        else:
            self._modern_view.setHtml(doc)  # type: ignore[union-attr]

    def _open_modern_resume_in_browser(self) -> None:
        if not self._modern_resume_html:
            QMessageBox.information(
                self, "Nothing to preview", "Generate a resume first."
            )
            return
        try:
            import tempfile
            tmp = Path(tempfile.gettempdir()) / "applypilot_resume_preview.html"
            tmp.write_text(self._modern_resume_html, encoding="utf-8")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(tmp)))
        except OSError as exc:
            QMessageBox.warning(self, "Open failed", str(exc))

    def _export_modern_resume_html(self) -> None:
        if not self._modern_resume_html:
            QMessageBox.information(
                self, "Nothing to export", "Generate a resume first."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export styled resume HTML",
            "tailored_resume.html",
            "HTML (*.html);;All files (*)",
        )
        if not path:
            return
        try:
            Path(path).write_text(self._modern_resume_html, encoding="utf-8")
            self._status.setText(f"Saved styled HTML to {path}")
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    # ----------------------------------------------------------- public
    def load_package(self, package: GeneratedApplicationPackage) -> None:
        self._resume_edit.setPlainText(resume_to_markdown(package.tailored_resume))
        self._set_modern_resume_html(
            tailored_resume_to_styled_html(
                package.tailored_resume, package.candidate_profile
            )
        )
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
        self._save_btn.setEnabled(True)
        self._save_btn.setToolTip("")
        self._status.setText(
            f"Loaded {len(package.evidence)} evidence items - score "
            f"{package.match_report.overall_score} / 100"
        )

    def load_from_stored_analysis(self, payload) -> None:
        """Populate the editors from a :class:`StoredAnalysis` payload.

        Used when re-opening a past analysis from the History page. We
        disable *Save full analysis* because there is no in-memory
        ``GeneratedApplicationPackage`` and we don't want to overwrite
        the existing folder.
        """
        self._resume_edit.setPlainText(payload.resume_md)
        self._cover_edit.setPlainText(payload.cover_letter_md)
        self._match_edit.setPlainText(payload.match_report_md)
        self._interview_edit.setPlainText(payload.interview_md)
        self._gap_edit.setPlainText(payload.skill_gap_md)
        self._evidence_edit.setPlainText(payload.evidence_json)
        # Prefer the stored styled HTML (full layout); fall back to the
        # markdown-rendered application_summary if absent.
        self._set_modern_resume_html(
            payload.styled_resume_html or payload.summary_html or ""
        )
        self._save_btn.setEnabled(False)
        self._save_btn.setToolTip(
            "Read-only view of an existing analysis. Run a fresh analysis "
            "to enable saving."
        )
        ev_count = 0
        if isinstance(payload.evidence, dict):
            items = payload.evidence.get("items")
            if isinstance(items, list):
                ev_count = len(items)
        self._status.setText(
            f"Loaded analysis from {payload.folder.name} ({ev_count} evidence items)."
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
