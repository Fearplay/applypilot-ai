"""Tests for CV-vs-LinkedIn source discrepancy clarifying questions."""
from __future__ import annotations

from src.models.candidate import (
    CandidateProfile,
    EducationEntry,
    WorkExperience,
)
from src.services.profile_dedup import build_source_discrepancy_questions


def _make_profile(*, experience=(), education=()) -> CandidateProfile:
    return CandidateProfile(
        full_name="Test Candidate",
        experience=list(experience),
        education=list(education),
    )


def test_cv_only_experience_yields_one_question():
    profile = _make_profile(
        experience=[
            WorkExperience(
                id="exp-1",
                title="Vývojář Python",
                company="CreatiWeb",
                period="2020",
                source="cv",
            ),
        ],
    )

    questions = build_source_discrepancy_questions(profile)

    assert len(questions) == 1
    q = questions[0]
    assert q.id == "discrepancy:exp-1"
    assert q.answer_type == "single_choice"
    # The question text must reference the role label and prompt the user.
    assert "Vývojář Python" in q.question
    assert "CreatiWeb" in q.question
    # The default options give the user a clean yes/no axis (the dialog
    # automatically appends "Other - type my own answer").
    assert any("yes" in opt.lower() for opt in q.options)
    assert any("no" in opt.lower() for opt in q.options)


def test_linkedin_only_education_yields_one_question():
    profile = _make_profile(
        education=[
            EducationEntry(
                id="edu-2",
                institution="ČZU v Praze",
                degree="Bakalář",
                period="2019 - 2022",
                source="linkedin",
            ),
        ],
    )

    questions = build_source_discrepancy_questions(profile)

    assert len(questions) == 1
    q = questions[0]
    assert q.id == "discrepancy:edu-2"
    assert "LinkedIn" in q.question


def test_entries_with_source_both_do_not_produce_questions():
    profile = _make_profile(
        experience=[
            WorkExperience(
                id="exp-7",
                title="QA Engineer",
                company="Acme",
                period="2022 - 2024",
                source="both",
            ),
        ],
        education=[
            EducationEntry(
                id="edu-7",
                institution="MIT",
                source="both",
            ),
        ],
    )

    assert build_source_discrepancy_questions(profile) == []


def test_unknown_source_does_not_produce_questions():
    """We only ask the user when we KNOW one source is missing the entry."""
    profile = _make_profile(
        experience=[
            WorkExperience(
                id="exp-x",
                title="Engineer",
                company="Acme",
                source="unknown",
            ),
        ],
    )

    assert build_source_discrepancy_questions(profile) == []


def test_max_questions_caps_output():
    profile = _make_profile(
        experience=[
            WorkExperience(
                id=f"exp-{i}",
                title=f"Role {i}",
                company=f"Company {i}",
                period="2020 - 2021",
                source="cv",
            )
            for i in range(10)
        ],
    )

    capped = build_source_discrepancy_questions(profile, max_questions=4)
    assert len(capped) == 4


def test_skips_entries_without_meaningful_label():
    profile = _make_profile(
        experience=[
            WorkExperience(id="exp-empty", title="", company="", source="cv"),
            WorkExperience(
                id="exp-real",
                title="Real Role",
                company="Real Co",
                source="cv",
            ),
        ],
        education=[
            EducationEntry(id="edu-empty", institution="", source="cv"),
        ],
    )

    questions = build_source_discrepancy_questions(profile)
    assert len(questions) == 1
    assert questions[0].id == "discrepancy:exp-real"
