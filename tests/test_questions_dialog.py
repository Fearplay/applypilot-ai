"""Smoke tests for QuestionsDialog free-text "Other" answer support.

The full Qt event loop is not exercised; we only verify the widget tree is
constructed correctly and ``value()`` extracts the user's text. This test is
skipped when PySide6 cannot create an offscreen QApplication (CI runners
without a display libraries).
"""
from __future__ import annotations

import os

import pytest

# Ensure Qt picks the offscreen platform plugin BEFORE the import.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")  # noqa: N816
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.gui.questions_dialog import QuestionsDialog, _classify_text  # noqa: E402
from src.models.match import ClarifyingQuestion  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance()
    created = False
    if app is None:
        try:
            app = QApplication([])
            created = True
        except Exception as exc:  # pragma: no cover - missing GL/X server
            pytest.skip(f"Qt application unavailable: {exc}")
    yield app
    if created:
        app.quit()


def test_classify_text_marks_yes_as_practical():
    assert _classify_text("Yes I have used it for 3 years") == "practical_experience"


def test_classify_text_marks_learning():
    assert _classify_text("Currently learning, in progress") == "learning_in_progress"


def test_classify_text_marks_empty_as_omit():
    assert _classify_text("") == "omit"
    assert _classify_text("   ") == "omit"


def test_classify_text_handles_czech_no():
    # The free-text classifier should treat plain Czech "ne" as omit.
    assert _classify_text("ne, neumim") == "omit"


def test_other_radio_extracts_typed_text(qt_app):
    q = ClarifyingQuestion(
        id="q1",
        skill="Selenium",
        question="Have you used Selenium?",
        why_it_matters="The role expects automation experience.",
        options=["Yes - practical experience", "Learning in progress", "No"],
        answer_type="single_choice",
    )

    dialog = QuestionsDialog([q])
    widget = dialog._question_widgets[0]
    assert widget._other_radio is not None
    assert widget._other_input is not None

    widget._other_radio.setChecked(True)
    widget._other_input.setText("I shipped 50 Selenium tests last year.")

    text, treat = widget.value()
    assert text == "I shipped 50 Selenium tests last year."
    assert treat == "practical_experience"


def test_multi_choice_collects_all_picks(qt_app):
    q = ClarifyingQuestion(
        id="q2",
        skill="Tools",
        question="Which CI tools have you used?",
        why_it_matters="Tooling matters for the pipeline.",
        options=["GitHub Actions", "GitLab CI", "Jenkins"],
        answer_type="multi_choice",
    )

    dialog = QuestionsDialog([q])
    widget = dialog._question_widgets[0]
    widget._check_options[0].setChecked(True)
    widget._check_options[2].setChecked(True)

    text, treat = widget.value()
    assert "GitHub Actions" in text
    assert "Jenkins" in text
    assert treat == "practical_experience"


def test_multi_choice_other_text_added(qt_app):
    q = ClarifyingQuestion(
        id="q3",
        skill="Tools",
        question="Which CI tools have you used?",
        why_it_matters="-",
        options=["GitHub Actions"],
        answer_type="multi_choice",
    )

    dialog = QuestionsDialog([q])
    widget = dialog._question_widgets[0]
    widget._check_options[0].setChecked(True)
    widget._other_check.setChecked(True)
    widget._other_input.setText("Drone CI")

    text, _treat = widget.value()
    assert "GitHub Actions" in text
    assert "Drone CI" in text


def test_short_text_falls_back_to_line_edit(qt_app):
    q = ClarifyingQuestion(
        id="q4",
        skill=None,
        question="Anything else we should know?",
        why_it_matters="-",
        options=[],
        answer_type="short_text",
    )

    dialog = QuestionsDialog([q])
    widget = dialog._question_widgets[0]
    widget._line_input.setText("Open to relocation.")

    text, treat = widget.value()
    assert text == "Open to relocation."
    assert treat == "practical_experience"


def test_empty_short_text_treated_as_omit(qt_app):
    q = ClarifyingQuestion(
        id="q5",
        skill=None,
        question="Comment?",
        why_it_matters="-",
        options=[],
        answer_type="short_text",
    )

    dialog = QuestionsDialog([q])
    widget = dialog._question_widgets[0]
    text, treat = widget.value()
    assert text == ""
    assert treat == "omit"
