"""Modal dialog that asks the candidate clarifying questions when evidence
coverage is below threshold. Replaces the old standalone Questions page.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..models.match import (
    AnswersBundle,
    ClarifyingAnswer,
    ClarifyingQuestion,
)
from .theme import Tokens


class _QuestionWidget(QFrame):
    def __init__(self, question: ClarifyingQuestion) -> None:
        super().__init__()
        self.question = question
        self.setObjectName("QCard")
        self.setStyleSheet(
            f"#QCard {{"
            f"  background-color: {Tokens.surface_alt};"
            f"  border: 1px solid {Tokens.border};"
            f"  border-radius: 10px;"
            f"}}"
            f"#QCard QLabel {{ color: {Tokens.text}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        title = QLabel(question.question)
        title.setWordWrap(True)
        title.setStyleSheet(
            f"color: {Tokens.text}; font-weight: 600; font-size: 13px;"
        )
        layout.addWidget(title)

        if question.why_it_matters:
            why = QLabel(f"Why we ask: {question.why_it_matters}")
            why.setWordWrap(True)
            why.setStyleSheet(f"color: {Tokens.text_muted}; font-size: 11px;")
            layout.addWidget(why)

        self._radio_group: QButtonGroup | None = None
        self._line_input: QLineEdit | None = None

        if question.answer_type in {"single_choice", "yes_no"} and question.options:
            self._radio_group = QButtonGroup(self)
            for i, option in enumerate(question.options):
                radio = QRadioButton(option)
                self._radio_group.addButton(radio, id=i)
                layout.addWidget(radio)
        else:
            self._line_input = QLineEdit()
            self._line_input.setPlaceholderText("Type your answer here...")
            layout.addWidget(self._line_input)

    def value(self) -> tuple[str, str]:
        if self._radio_group is not None:
            btn = self._radio_group.checkedButton()
            if not btn:
                return "", "omit"
            text = btn.text()
            lowered = text.lower()
            if "no" in lowered or "omit" in lowered:
                treat = "omit"
            elif "learning" in lowered or "in progress" in lowered:
                treat = "learning_in_progress"
            else:
                treat = "practical_experience"
            return text, treat
        if self._line_input is not None:
            text = self._line_input.text().strip()
            return text, "practical_experience" if text else "omit"
        return "", "omit"


class QuestionsDialog(QDialog):
    """Modal dialog that collects clarifying answers and returns an AnswersBundle."""

    def __init__(
        self,
        questions: list[ClarifyingQuestion],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Clarifying questions")
        self.setModal(True)
        self.resize(600, 540)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 16)
        outer.setSpacing(12)

        title = QLabel("Tell us what counts as real experience")
        title.setStyleSheet(
            f"color: {Tokens.text}; font-size: 18px; font-weight: 600;"
        )
        outer.addWidget(title)

        intro = QLabel(
            "We could not find clear evidence for some required skills. "
            "Pick the option that matches reality so the resume can use them honestly."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {Tokens.text_muted}; font-size: 12px;")
        outer.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll, stretch=1)

        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 4, 0)
        host_layout.setSpacing(10)

        self._question_widgets: list[_QuestionWidget] = []
        if not questions:
            host_layout.addWidget(
                QLabel("No clarifying questions needed - you can continue.")
            )
        else:
            for q in questions:
                qw = _QuestionWidget(q)
                self._question_widgets.append(qw)
                host_layout.addWidget(qw)
        host_layout.addStretch(1)
        scroll.setWidget(host)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.Ok)
        ok_btn.setText("Continue analysis")
        ok_btn.setProperty("variant", "primary")
        ok_btn.style().unpolish(ok_btn)
        ok_btn.style().polish(ok_btn)
        cancel_btn = buttons.button(QDialogButtonBox.Cancel)
        cancel_btn.setProperty("variant", "ghost")
        cancel_btn.style().unpolish(cancel_btn)
        cancel_btn.style().polish(cancel_btn)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons, alignment=Qt.AlignRight)

    def answers(self) -> AnswersBundle:
        return AnswersBundle(
            answers=[
                ClarifyingAnswer(
                    question_id=qw.question.id,
                    skill=qw.question.skill,
                    answer=text,
                    treat_as=treat,  # type: ignore[arg-type]
                )
                for qw in self._question_widgets
                for text, treat in [qw.value()]
            ]
        )


__all__ = ["QuestionsDialog"]
