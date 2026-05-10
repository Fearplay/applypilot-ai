"""Tests for the ``additional_notes`` integration in the prompt builders.

These guard the user-authoritative semantics of the free-text notes box
on the Setup page. The notes are typed (or pasted from a TXT/PDF/DOCX
file) on the GUI and must reach EVERY downstream prompt verbatim so the
AI can honour clarifications like "did not finish bachelor's" or
"available only part-time" in both Czech and English outputs.
"""
from __future__ import annotations

from src.ai import prompts
from src.models.candidate import CandidateProfile
from src.models.documents import (
    CoverLetter,
    ResumeBullet,
    ResumeSection,
    TailoredResume,
)
from src.models.job import JobPosting
from src.models.match import AnswersBundle


# ---------------------------------------------------------------------------
# analyze_candidate_user_prompt: notes block + verbatim copy directive
# ---------------------------------------------------------------------------
def test_analyze_candidate_prompt_includes_notes_block_when_provided():
    notes = "Vysokou školu jsem ukončil v roce 2023 bez titulu bakaláře."
    body = prompts.analyze_candidate_user_prompt(
        cv_text="Some CV", linkedin_text="", github_username=None,
        github_projects=[], additional_notes=notes,
    )

    assert "ADDITIONAL CANDIDATE NOTES" in body
    assert "USER-AUTHORITATIVE" in body
    # The verbatim text must reach the model, otherwise the override
    # semantics are meaningless.
    assert notes in body
    # And the prompt must explicitly demand the notes be copied back into
    # the structured profile so downstream prompts see them.
    assert "additional_notes" in body
    assert "VERBATIM" in body or "verbatim" in body


def test_analyze_candidate_prompt_omits_notes_block_when_empty():
    body = prompts.analyze_candidate_user_prompt(
        cv_text="Some CV", linkedin_text="", github_username=None,
        github_projects=[], additional_notes="   ",
    )
    # When the user typed nothing, the giant USER-AUTHORITATIVE notes
    # rule is just noise and should be elided to save tokens.
    assert "ADDITIONAL CANDIDATE NOTES" not in body


def test_analyze_candidate_prompt_supports_english_notes():
    notes = (
        "I'm very interested in this position, but I'd like to start "
        "part-time because I plan a career change soon."
    )
    body = prompts.analyze_candidate_user_prompt(
        cv_text="cv", linkedin_text="", github_username=None,
        github_projects=[], additional_notes=notes,
    )

    assert notes in body
    assert "Czech, English or" in body  # bilingual rule


# ---------------------------------------------------------------------------
# Downstream prompts: notes block surfaces in every generator
# ---------------------------------------------------------------------------
_CZECH_NOTES = (
    "O tuto pozici mám velký zájem, ale chci nastoupit na part-time, "
    "protože brzy plánuji změnu kariérní cesty."
)
_ENGLISH_NOTES = (
    "I finished college in 2023 without earning the bachelor's title."
)


def _candidate_with_notes(notes: str) -> CandidateProfile:
    return CandidateProfile(
        full_name="Test Candidate",
        technical_skills=["Python"],
        additional_notes=notes,
    )


def test_match_report_prompt_surfaces_notes_in_czech():
    body = prompts.match_report_user_prompt(
        JobPosting(title="QA"),
        _candidate_with_notes(_CZECH_NOTES),
        AnswersBundle(),
        evidence=[],
        output_language="cs",
    )

    assert "CANDIDATE ADDITIONAL NOTES" in body
    assert _CZECH_NOTES in body
    assert "ADDITIONAL NOTES IMPACT" in body
    assert "OUTPUT_LANGUAGE: Czech." in body


def test_resume_prompt_surfaces_notes_in_english():
    body = prompts.resume_user_prompt(
        JobPosting(title="QA"),
        _candidate_with_notes(_ENGLISH_NOTES),
        AnswersBundle(),
        evidence=[],
        output_language="en",
    )

    assert "CANDIDATE ADDITIONAL NOTES" in body
    assert _ENGLISH_NOTES in body
    assert "ADDITIONAL NOTES IMPACT" in body
    assert "OUTPUT_LANGUAGE: English." in body


def test_cover_letter_prompt_surfaces_notes_for_motivation_paragraph():
    body = prompts.cover_letter_user_prompt(
        JobPosting(title="QA"),
        _candidate_with_notes(_CZECH_NOTES),
        AnswersBundle(),
        output_language="cs",
    )

    assert "CANDIDATE ADDITIONAL NOTES" in body
    assert _CZECH_NOTES in body
    # The cover-letter prompt must explicitly tell the AI to surface
    # the motivation / availability constraint in one paragraph.
    assert "ADDITIONAL NOTES IMPACT" in body
    assert "part-time" in body.lower() or "career change" in body.lower()


def test_clarifying_questions_prompt_surfaces_notes():
    body = prompts.clarifying_questions_user_prompt(
        JobPosting(title="QA"),
        _candidate_with_notes(_ENGLISH_NOTES),
        output_language="en",
    )
    assert "CANDIDATE ADDITIONAL NOTES" in body
    assert _ENGLISH_NOTES in body


def test_interview_questions_prompt_surfaces_notes_for_rehearsal():
    body = prompts.interview_questions_user_prompt(
        JobPosting(title="QA"),
        _candidate_with_notes(_CZECH_NOTES),
        output_language="cs",
    )
    assert "CANDIDATE ADDITIONAL NOTES" in body
    assert _CZECH_NOTES in body


def test_refine_resume_prompt_surfaces_notes():
    body = prompts.refine_resume_user_prompt(
        current_resume=TailoredResume(
            name="Test",
            professional_summary="Stub",
            technical_skills=["Python"],
            experience=[
                ResumeSection(
                    title="Engineer", subtitle="Acme", period="2020-2023",
                    bullets=[ResumeBullet(text="Did things.", keywords=[])],
                )
            ],
        ),
        feedback="add a project",
        job=JobPosting(title="QA"),
        candidate=_candidate_with_notes(_CZECH_NOTES),
        answers=AnswersBundle(),
        evidence=[],
        output_language="cs",
    )

    assert "CANDIDATE ADDITIONAL NOTES" in body
    assert _CZECH_NOTES in body


def test_refine_cover_letter_prompt_surfaces_notes():
    body = prompts.refine_cover_letter_user_prompt(
        current_cover_letter=CoverLetter(
            salutation="Dear hiring team,",
            paragraphs=["Body."],
            closing="Best regards,",
            signature="Test Candidate",
        ),
        feedback="mention my interest",
        job=JobPosting(title="QA"),
        candidate=_candidate_with_notes(_ENGLISH_NOTES),
        answers=AnswersBundle(),
        output_language="en",
    )

    assert "CANDIDATE ADDITIONAL NOTES" in body
    assert _ENGLISH_NOTES in body


# ---------------------------------------------------------------------------
# Downstream prompts: empty notes are silent (no token waste, no scolding)
# ---------------------------------------------------------------------------
def test_match_report_prompt_omits_notes_block_when_empty():
    body = prompts.match_report_user_prompt(
        JobPosting(title="QA"),
        CandidateProfile(full_name="Test"),
        AnswersBundle(),
        evidence=[],
        output_language="en",
    )
    assert "CANDIDATE ADDITIONAL NOTES" not in body


def test_resume_prompt_omits_notes_block_when_empty():
    body = prompts.resume_user_prompt(
        JobPosting(title="QA"),
        CandidateProfile(full_name="Test"),
        AnswersBundle(),
        evidence=[],
        output_language="en",
    )
    assert "CANDIDATE ADDITIONAL NOTES" not in body
