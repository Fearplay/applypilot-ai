"""Step 3 (optional): clarifying questions for missing evidence."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
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


class _QuestionWidget(QFrame):
    def __init__(self, question: ClarifyingQuestion) -> None:
        super().__init__()
        self.question = question
        self.setObjectName("QCard")
        self.setStyleSheet(
            "#QCard { background: #2a2d35; border-radius: 8px; padding: 12px;"
            " border: 1px solid #3a3d45; }"
            "QLabel { color: #e8e8ee; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel(f"<b>{question.question}</b>")
        title.setWordWrap(True)
        layout.addWidget(title)

        if question.why_it_matters:
            why = QLabel(f"<i>Why we ask: {question.why_it_matters}</i>")
            why.setWordWrap(True)
            why.setStyleSheet("color: #a8a8b3;")
            layout.addWidget(why)

        self._radio_group: QButtonGroup | None = None
        self._line_input: QLineEdit | None = None

        if question.answer_type in {"single_choice", "yes_no"} and question.options:
            self._radio_group = QButtonGroup(self)
            for i, option in enumerate(question.options):
                radio = QRadioButton(option)
                radio.setStyleSheet("QRadioButton { color: #e8e8ee; }")
                self._radio_group.addButton(radio, id=i)
                layout.addWidget(radio)
        else:
            self._line_input = QLineEdit()
            self._line_input.setPlaceholderText("Type your answer here...")
            layout.addWidget(self._line_input)

    def value(self) -> tuple[str, str]:
        """Return (answer_text, treat_as)."""
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


class QuestionsPage(QWidget):
    answered = Signal(object)  # AnswersBundle

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._question_widgets: list[_QuestionWidget] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.setSpacing(12)
        outer.addWidget(QLabel("<h2>Step 3 - Clarifying questions</h2>"))
        outer.addWidget(QLabel(
            "We could not find clear evidence for some required skills. Tell us "
            "which apply so the resume can use them honestly."
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll, stretch=1)

        host = QWidget()
        scroll.setWidget(host)
        self._host_layout = QVBoxLayout(host)
        self._host_layout.setContentsMargins(2, 2, 2, 2)
        self._host_layout.setSpacing(10)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._continue_btn = QPushButton("Continue analysis ->")
        self._continue_btn.setMinimumWidth(200)
        self._continue_btn.clicked.connect(self._on_continue)
        self._continue_btn.setStyleSheet(
            "QPushButton { background: #1f6feb; color: white; border: none;"
            " border-radius: 6px; padding: 8px 14px; font-weight: 600; }"
            "QPushButton:disabled { background: #3a3d45; color: #888; }"
        )
        button_row.addWidget(self._continue_btn)
        outer.addLayout(button_row)

    # ----------------------------------------------------------- public
    def load_questions(self, questions: list[ClarifyingQuestion]) -> None:
        # Clear previous
        while self._host_layout.count():
            item = self._host_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._question_widgets.clear()

        if not questions:
            self._host_layout.addWidget(
                QLabel("No clarifying questions needed - you can continue.")
            )
            return
        for q in questions:
            qw = _QuestionWidget(q)
            self._question_widgets.append(qw)
            self._host_layout.addWidget(qw)
        self._host_layout.addStretch(1)

    def _on_continue(self) -> None:
        answers = AnswersBundle(
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
        self.answered.emit(answers)


__all__ = ["QuestionsPage"]
