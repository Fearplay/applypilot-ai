"""Step 4: show the match report and a slice of the evidence preview."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..models.match import MatchReport
from .widgets.evidence_card import EvidenceCard
from .widgets.score_badge import ScoreBadge


class MatchReportPage(QWidget):
    generate_clicked = Signal()
    back_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(12)

        layout.addWidget(QLabel("<h2>Step 4 - Match report</h2>"))

        top = QHBoxLayout()
        self._badge = ScoreBadge(0, "Overall match")
        self._badge.setMinimumSize(180, 180)
        top.addWidget(self._badge)

        cat_box = QWidget()
        cat_layout = QGridLayout(cat_box)
        cat_layout.setHorizontalSpacing(20)
        cat_layout.setVerticalSpacing(6)
        cat_layout.addWidget(QLabel("<b>Technical skills</b>"), 0, 0)
        self._tech_lbl = QLabel("- / 100")
        cat_layout.addWidget(self._tech_lbl, 0, 1)
        cat_layout.addWidget(QLabel("<b>Experience</b>"), 1, 0)
        self._exp_lbl = QLabel("- / 100")
        cat_layout.addWidget(self._exp_lbl, 1, 1)
        cat_layout.addWidget(QLabel("<b>Tools</b>"), 2, 0)
        self._tools_lbl = QLabel("- / 100")
        cat_layout.addWidget(self._tools_lbl, 2, 1)
        cat_layout.addWidget(QLabel("<b>Process / QA</b>"), 3, 0)
        self._proc_lbl = QLabel("- / 100")
        cat_layout.addWidget(self._proc_lbl, 3, 1)
        for lbl in (self._tech_lbl, self._exp_lbl, self._tools_lbl, self._proc_lbl):
            lbl.setStyleSheet("color: #e8e8ee;")
        top.addWidget(cat_box, stretch=1)
        layout.addLayout(top)

        lists = QHBoxLayout()
        lists.setSpacing(12)

        matched_box = QVBoxLayout()
        matched_box.addWidget(QLabel("<b>Matched requirements</b>"))
        self._matched_list = QListWidget()
        matched_box.addWidget(self._matched_list)
        lists.addLayout(matched_box, stretch=1)

        missing_box = QVBoxLayout()
        missing_box.addWidget(QLabel("<b>Missing requirements / risky gaps</b>"))
        self._missing_list = QListWidget()
        missing_box.addWidget(self._missing_list)
        lists.addLayout(missing_box, stretch=1)

        ats_box = QVBoxLayout()
        ats_box.addWidget(QLabel("<b>ATS keywords</b>"))
        self._ats_list = QListWidget()
        ats_box.addWidget(self._ats_list)
        lists.addLayout(ats_box, stretch=1)

        layout.addLayout(lists, stretch=1)

        layout.addWidget(QLabel("<b>Evidence preview</b>"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._evidence_host = QWidget()
        self._evidence_layout = QVBoxLayout(self._evidence_host)
        self._evidence_layout.setContentsMargins(2, 2, 2, 2)
        self._evidence_layout.setSpacing(6)
        scroll.setWidget(self._evidence_host)
        scroll.setMinimumHeight(160)
        layout.addWidget(scroll, stretch=1)

        button_row = QHBoxLayout()
        back = QPushButton("<- Back")
        back.clicked.connect(self.back_clicked.emit)
        button_row.addWidget(back)
        button_row.addStretch(1)
        self._gen_btn = QPushButton("Generate documents ->")
        self._gen_btn.setMinimumWidth(220)
        self._gen_btn.clicked.connect(self.generate_clicked.emit)
        self._gen_btn.setStyleSheet(
            "QPushButton { background: #1f6feb; color: white; border: none;"
            " border-radius: 6px; padding: 8px 14px; font-weight: 600; }"
        )
        button_row.addWidget(self._gen_btn)
        layout.addLayout(button_row)

    # ----------------------------------------------------------- public
    def set_report(self, report: MatchReport) -> None:
        self._badge.set_score(report.overall_score, "Overall match")
        cs = report.category_scores
        self._tech_lbl.setText(f"{cs.technical_skills} / 100")
        self._exp_lbl.setText(f"{cs.experience} / 100")
        self._tools_lbl.setText(f"{cs.tools} / 100")
        self._proc_lbl.setText(f"{cs.qa_process} / 100")

        self._matched_list.clear()
        for r in report.matched_requirements:
            self._matched_list.addItem(r)

        self._missing_list.clear()
        for r in report.missing_requirements:
            self._missing_list.addItem(r)
        for r in report.risky_gaps:
            self._missing_list.addItem(f"[risky] {r}")

        self._ats_list.clear()
        for r in report.ats_keywords_present:
            self._ats_list.addItem(f"+ {r}")
        for r in report.ats_keywords_missing:
            self._ats_list.addItem(f"- {r}")

        # Evidence cards
        while self._evidence_layout.count():
            item = self._evidence_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for ev in report.evidence[:12]:
            self._evidence_layout.addWidget(EvidenceCard(ev))
        self._evidence_layout.addStretch(1)


__all__ = ["MatchReportPage"]
