"""Modal dialog that asks the candidate clarifying questions when evidence
coverage is below threshold.

Each question maps to a small ``_QuestionWidget`` whose layout depends on the
``answer_type`` returned by the AI:

* ``yes_no`` / ``single_choice`` - one radio per option *plus* an extra
  "Other - type your own answer" radio that reveals a free-text editor.
* ``multi_choice`` - one checkbox per option, the same "Other" free-text fall
  through, plus the ability to combine multiple selections.
* ``short_text`` (or anything else) - a plain :class:`QLineEdit`.

The user can therefore always express something the AI did not anticipate.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QLineEdit,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..i18n import t
from ..models.match import (
    AnswersBundle,
    ClarifyingAnswer,
    ClarifyingQuestion,
)
from .theme import Tokens


_OTHER_KEY = "__other__"


def _classify_text(text: str) -> str:
    """Best-effort mapping of free-text answers to the ``treat_as`` enum."""
    lowered = (text or "").strip().lower()
    if not lowered:
        return "omit"
    if any(tok in lowered for tok in ("ne ", "ne,", "ne.", "nemam", "nemám", " no ", "no,", "no.", "nope", "never")):
        # Bare "no" / Czech "ne" anywhere in the text is treated as omit.
        return "omit"
    if any(
        tok in lowered
        for tok in (
            "learning", "ucim", "učím", "studuju", "studuji", "in progress",
            "v procesu", "začínám", "zacinam", "kurz", "course", "tutorial",
            "self-study", "samostudium",
        )
    ):
        return "learning_in_progress"
    return "practical_experience"


def _radio_choice_to_treat(text: str) -> str:
    lowered = text.lower()
    if "no" in lowered or "ne" in lowered or "omit" in lowered:
        return "omit"
    if "learning" in lowered or "in progress" in lowered or "uč" in lowered or "studu" in lowered:
        return "learning_in_progress"
    return "practical_experience"


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
            why = QLabel(t("questions.why_prefix", reason=question.why_it_matters))
            why.setWordWrap(True)
            why.setStyleSheet(f"color: {Tokens.text_muted}; font-size: 11px;")
            layout.addWidget(why)

        self._radio_group: QButtonGroup | None = None
        self._radio_options: list[QRadioButton] = []
        self._check_options: list[QCheckBox] = []
        self._line_input: QLineEdit | None = None
        self._other_radio: QRadioButton | None = None
        self._other_check: QCheckBox | None = None
        self._other_input: QLineEdit | None = None
        self._mode: str = "text"

        if question.answer_type in {"single_choice", "yes_no"} and question.options:
            self._mode = "radio"
            self._radio_group = QButtonGroup(self)
            for i, option in enumerate(question.options):
                radio = QRadioButton(option)
                self._radio_group.addButton(radio, id=i)
                self._radio_options.append(radio)
                layout.addWidget(radio)
            self._other_radio = QRadioButton(t("questions.other"))
            self._radio_group.addButton(self._other_radio, id=len(question.options))
            layout.addWidget(self._other_radio)
            self._other_input = QLineEdit()
            self._other_input.setPlaceholderText(t("questions.other_placeholder"))
            self._other_input.setEnabled(False)
            self._other_radio.toggled.connect(self._other_input.setEnabled)
            self._other_radio.toggled.connect(
                lambda checked: checked and self._other_input.setFocus()
            )
            layout.addWidget(self._other_input)
        elif question.answer_type == "multi_choice" and question.options:
            self._mode = "multi"
            for option in question.options:
                cb = QCheckBox(option)
                self._check_options.append(cb)
                layout.addWidget(cb)
            self._other_check = QCheckBox(t("questions.other"))
            layout.addWidget(self._other_check)
            self._other_input = QLineEdit()
            self._other_input.setPlaceholderText(t("questions.other_placeholder"))
            self._other_input.setEnabled(False)
            self._other_check.toggled.connect(self._other_input.setEnabled)
            self._other_check.toggled.connect(
                lambda checked: checked and self._other_input.setFocus()
            )
            layout.addWidget(self._other_input)
        else:
            self._mode = "text"
            self._line_input = QLineEdit()
            self._line_input.setPlaceholderText(t("questions.short_text_placeholder"))
            layout.addWidget(self._line_input)

    def value(self) -> tuple[str, str]:
        """Return ``(answer_text, treat_as)`` for the AnswersBundle."""
        if self._mode == "radio" and self._radio_group is not None:
            btn = self._radio_group.checkedButton()
            if btn is None:
                return "", "omit"
            if btn is self._other_radio and self._other_input is not None:
                text = self._other_input.text().strip()
                return text, _classify_text(text)
            return btn.text(), _radio_choice_to_treat(btn.text())

        if self._mode == "multi":
            picks = [cb.text() for cb in self._check_options if cb.isChecked()]
            if self._other_check is not None and self._other_check.isChecked():
                other_text = (self._other_input.text().strip()
                              if self._other_input is not None else "")
                if other_text:
                    picks.append(other_text)
            if not picks:
                return "", "omit"
            joined = "; ".join(picks)
            return joined, _classify_text(joined)

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
        self.setWindowTitle(t("questions.title"))
        self.setModal(True)
        self.resize(600, 540)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 16)
        outer.setSpacing(12)

        title = QLabel(t("questions.heading"))
        title.setStyleSheet(
            f"color: {Tokens.text}; font-size: 18px; font-weight: 600;"
        )
        outer.addWidget(title)

        intro = QLabel(t("questions.intro"))
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
            host_layout.addWidget(QLabel(t("questions.empty")))
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
        ok_btn.setText(t("questions.continue"))
        ok_btn.setProperty("variant", "primary")
        ok_btn.style().unpolish(ok_btn)
        ok_btn.style().polish(ok_btn)
        cancel_btn = buttons.button(QDialogButtonBox.Cancel)
        cancel_btn.setText(t("questions.cancel"))
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
