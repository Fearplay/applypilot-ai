"""Match report screen: score badge, category bars, lists and evidence."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..i18n import t
from ..models.match import MatchReport
from .theme import Tokens
from .widgets.evidence_card import EvidenceCard
from .widgets.score_badge import ScoreBadge


class _CategoryBar(QFrame):
    """Mini card with a label and a progress bar for a single category."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{"
            f"  background-color: {Tokens.surface_alt};"
            f"  border: 1px solid {Tokens.border};"
            f"  border-radius: 8px;"
            f"}}"
            f"QLabel {{ background: transparent; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(6)

        head = QHBoxLayout()
        self._label = QLabel(label)
        self._label.setStyleSheet(
            f"color: {Tokens.text_muted}; font-size: 11px;"
            f" font-weight: 600; letter-spacing: 0.4px;"
        )
        head.addWidget(self._label, stretch=1)
        self._value = QLabel("- / 100")
        self._value.setStyleSheet(
            f"color: {Tokens.text}; font-size: 13px; font-weight: 600;"
        )
        head.addWidget(self._value, alignment=Qt.AlignRight)
        layout.addLayout(head)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        self._bar.setStyleSheet(
            f"QProgressBar {{"
            f"  background-color: {Tokens.surface_hover};"
            f"  border-radius: 3px;"
            f"  border: none;"
            f"}}"
            f"QProgressBar::chunk {{"
            f"  background-color: {Tokens.accent};"
            f"  border-radius: 3px;"
            f"}}"
        )
        layout.addWidget(self._bar)

    def set_value(self, value: int) -> None:
        self._bar.setValue(max(0, min(value, 100)))
        self._value.setText(f"{value} / 100")


class _ListColumn(QFrame):
    """Card containing a small heading + a borderless QListWidget."""

    def __init__(
        self,
        title: str,
        tooltip: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{"
            f"  background-color: {Tokens.surface};"
            f"  border: 1px solid {Tokens.border};"
            f"  border-radius: 10px;"
            f"}}"
            f"QLabel {{ background: transparent; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        head = QLabel(title.upper())
        head.setStyleSheet(
            f"color: {Tokens.text_muted}; font-size: 10px;"
            f" font-weight: 700; letter-spacing: 1.2px;"
        )
        if tooltip:
            head.setToolTip(tooltip)
            self.setToolTip(tooltip)
        layout.addWidget(head)

        self._list = QListWidget()
        self._list.setStyleSheet(
            f"QListWidget {{"
            f"  background: transparent;"
            f"  border: none;"
            f"  outline: none;"
            f"  color: {Tokens.text};"
            f"}}"
            f"QListWidget::item {{ padding: 6px 4px; border-radius: 4px; }}"
            f"QListWidget::item:hover {{ background: {Tokens.surface_alt}; }}"
        )
        layout.addWidget(self._list, stretch=1)

    def clear(self) -> None:
        self._list.clear()

    def add(self, text: str, accent: str | None = None) -> None:
        item = QListWidgetItem(text)
        if accent == "warn":
            item.setForeground(Qt.GlobalColor.yellow)
        layout_color: dict[str, str] = {
            "ok":   Tokens.success,
            "warn": Tokens.warn,
            "bad":  Tokens.danger,
        }
        if accent and accent in layout_color:
            from PySide6.QtGui import QColor
            item.setForeground(QColor(layout_color[accent]))
        self._list.addItem(item)


class MatchReportPage(QWidget):
    generate_clicked = Signal()
    back_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll, stretch=1)

        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(36, 30, 36, 24)
        layout.setSpacing(20)
        scroll.setWidget(host)

        # Top: badge + 4 category bars
        top = QHBoxLayout()
        top.setSpacing(20)

        badge_box = QFrame()
        badge_box.setStyleSheet(
            f"QFrame {{ background-color: {Tokens.surface};"
            f" border: 1px solid {Tokens.border}; border-radius: 12px; }}"
        )
        badge_layout = QVBoxLayout(badge_box)
        badge_layout.setContentsMargins(20, 18, 20, 18)
        badge_layout.setSpacing(10)
        badge_head = QLabel(t("match.overall"))
        badge_head.setStyleSheet(
            f"color: {Tokens.text_muted}; font-size: 10px;"
            f" font-weight: 700; letter-spacing: 1.4px;"
        )
        badge_layout.addWidget(badge_head)
        self._badge = ScoreBadge(0, "")
        self._badge.setMinimumSize(180, 180)
        badge_layout.addWidget(self._badge, alignment=Qt.AlignCenter)
        top.addWidget(badge_box)

        cats_box = QVBoxLayout()
        cats_box.setSpacing(10)
        self._tech = _CategoryBar(t("match.cat.tech"))
        self._exp = _CategoryBar(t("match.cat.experience"))
        self._tools = _CategoryBar(t("match.cat.tools"))
        self._proc = _CategoryBar(t("match.cat.process"))
        for w in (self._tech, self._exp, self._tools, self._proc):
            cats_box.addWidget(w)
        cats_wrap = QFrame()
        cats_wrap.setStyleSheet("QFrame { background: transparent; }")
        cats_wrap.setLayout(cats_box)
        top.addWidget(cats_wrap, stretch=1)
        layout.addLayout(top)

        # Three list columns
        lists_legend = QLabel(t("match.legend"))
        lists_legend.setWordWrap(True)
        lists_legend.setStyleSheet(
            f"color: {Tokens.text_dim}; font-size: 11px; font-style: italic;"
        )
        layout.addWidget(lists_legend)

        lists = QHBoxLayout()
        lists.setSpacing(12)
        self._matched = _ListColumn(
            t("match.col.matched"),
            tooltip=t("match.col.matched.tip"),
        )
        self._missing = _ListColumn(
            t("match.col.missing"),
            tooltip=t("match.col.missing.tip"),
        )
        self._ats = _ListColumn(
            t("match.col.ats"),
            tooltip=t("match.col.ats.tip"),
        )
        for col in (self._matched, self._missing, self._ats):
            lists.addWidget(col, stretch=1)
        layout.addLayout(lists)

        # Evidence header + scrollable cards
        ev_head = QLabel(t("match.evidence_header"))
        ev_head.setStyleSheet(
            f"color: {Tokens.text_muted}; font-size: 10px;"
            f" font-weight: 700; letter-spacing: 1.4px; padding-top: 6px;"
        )
        layout.addWidget(ev_head)

        ev_scroll = QScrollArea()
        ev_scroll.setWidgetResizable(True)
        ev_scroll.setFrameShape(QScrollArea.NoFrame)
        ev_scroll.setMinimumHeight(220)
        self._ev_host = QWidget()
        self._ev_layout = QVBoxLayout(self._ev_host)
        self._ev_layout.setContentsMargins(0, 0, 4, 0)
        self._ev_layout.setSpacing(8)
        ev_scroll.setWidget(self._ev_host)
        layout.addWidget(ev_scroll)

        # Action bar
        bar = QFrame()
        bar.setStyleSheet(
            f"background-color: {Tokens.bg};"
            f" border-top: 1px solid {Tokens.border};"
        )
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(36, 14, 36, 14)
        back = QPushButton(t("match.back"))
        back.setProperty("variant", "ghost")
        back.clicked.connect(self.back_clicked.emit)
        bar_layout.addWidget(back)
        bar_layout.addStretch(1)
        self._gen_btn = QPushButton(t("match.generate"))
        self._gen_btn.setProperty("variant", "primary")
        self._gen_btn.setMinimumWidth(200)
        self._gen_btn.clicked.connect(self.generate_clicked.emit)
        bar_layout.addWidget(self._gen_btn)
        outer.addWidget(bar)

    # ----------------------------------------------------------- public
    def set_generation_enabled(self, enabled: bool) -> None:
        """Enable / disable the document-generation action."""
        self._gen_btn.setEnabled(enabled)
        self._gen_btn.setText(
            t("match.generate") if enabled else t("match.generate.busy")
        )

    def set_report(self, report: MatchReport) -> None:
        self.set_generation_enabled(True)
        self._badge.set_score(report.overall_score, "")
        cs = report.category_scores
        self._tech.set_value(cs.technical_skills)
        self._exp.set_value(cs.experience)
        self._tools.set_value(cs.tools)
        self._proc.set_value(cs.qa_process)

        self._matched.clear()
        for r in report.matched_requirements:
            self._matched.add(r, accent="ok")

        self._missing.clear()
        for r in report.missing_requirements:
            self._missing.add(r, accent="bad")
        for r in report.risky_gaps:
            self._missing.add(f"[risky] {r}", accent="warn")

        self._ats.clear()
        for r in report.ats_keywords_present:
            self._ats.add(f"+ {r}", accent="ok")
        for r in report.ats_keywords_missing:
            self._ats.add(f"- {r}", accent="bad")

        while self._ev_layout.count():
            item = self._ev_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for ev in report.evidence[:12]:
            self._ev_layout.addWidget(EvidenceCard(ev))
        self._ev_layout.addStretch(1)


__all__ = ["MatchReportPage"]
