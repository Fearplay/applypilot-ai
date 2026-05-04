"""Tests for the deterministic post-pass that fixes mis-typed AI questions.

The user complained that "do you have experience with NUnit" kept arriving
as a free-text input even though the prompt says it should be a Yes/No.
The post-pass in :mod:`src.services.question_generator` rewrites those
``short_text`` questions to ``yes_no`` with localised options so the GUI
renders the right widget regardless of what the AI returned.
"""
from __future__ import annotations

import pytest

from src.models.match import ClarifyingQuestion
from src.services.question_generator import (
    _coerce_skill_questions_to_yes_no,
    _is_skill_yes_no_phrasing,
)


@pytest.mark.parametrize(
    "phrase",
    [
        "Do you have experience with xUnit?",
        "Have you worked with NUnit?",
        "Have you used Selenium?",
        "Did you ship a production CI/CD pipeline?",
        "Are you familiar with Kubernetes?",
        "Are you comfortable with hands-on debugging?",
        "Máš zkušenost s Cypressem?",
        "Pracoval jsi s Postgresem?",
        "Pou\u017eival jsi Docker?",
        "Zn\u00e1\u0161 GraphQL?",
        "Um\u00ed\u0161 angli\u010dtinu?",
    ],
)
def test_phrasing_detected_as_yes_no(phrase: str) -> None:
    assert _is_skill_yes_no_phrasing(phrase)


@pytest.mark.parametrize(
    "phrase",
    [
        "Which testing framework do you prefer?",
        "How many years of NUnit experience do you have?",
        "Briefly describe a recent CI pipeline you built.",
        "Kter\u00fd framework jsi pou\u017eil naposledy?",
    ],
)
def test_open_questions_are_not_promoted(phrase: str) -> None:
    assert not _is_skill_yes_no_phrasing(phrase)


def test_short_text_skill_question_is_promoted_to_yes_no() -> None:
    q = ClarifyingQuestion(
        id="q1",
        question="Do you have experience with xUnit?",
        answer_type="short_text",
    )
    out = _coerce_skill_questions_to_yes_no([q], output_language="en")
    assert len(out) == 1
    assert out[0].answer_type == "yes_no"
    # Localised options come from the i18n table; en uses "Yes / No" wording.
    assert out[0].options[0].lower().startswith("yes")
    assert out[0].options[1].lower().startswith("no")


def test_czech_phrasing_uses_czech_labels() -> None:
    q = ClarifyingQuestion(
        id="q2",
        question="Máš zkušenost s Cypressem?",
        answer_type="short_text",
    )
    out = _coerce_skill_questions_to_yes_no([q], output_language="cs")
    assert out[0].answer_type == "yes_no"
    assert out[0].options[0].startswith("Ano")
    assert out[0].options[1].startswith("Ne")


def test_open_question_is_left_alone() -> None:
    q = ClarifyingQuestion(
        id="q3",
        question="How many years of NUnit experience do you have?",
        answer_type="short_text",
    )
    out = _coerce_skill_questions_to_yes_no([q], output_language="en")
    assert out[0].answer_type == "short_text"
    assert out[0].options == []


def test_choice_question_without_options_falls_back_to_yes_no() -> None:
    q = ClarifyingQuestion(
        id="q4",
        question="Which testing framework do you prefer?",
        answer_type="single_choice",
    )
    out = _coerce_skill_questions_to_yes_no([q], output_language="en")
    assert out[0].answer_type == "single_choice"
    # Empty options would render an unusable widget; safety net populates them.
    assert len(out[0].options) >= 2
