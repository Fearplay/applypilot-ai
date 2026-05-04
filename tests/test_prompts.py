"""Tests for prompt builders.

The original bug: ``_dump`` only handled a single Pydantic model, so passing
``list[EvidenceItem]`` blew up with ``TypeError: Object of type EvidenceItem
is not JSON serializable`` when the match report was generated. The tests
below pin that fix and also confirm we don't ship the bulky
``JobPosting.raw_text`` to the AI on every downstream call.
"""
from __future__ import annotations

import json

from src.ai import prompts
from src.models.candidate import CandidateProfile
from src.models.evidence import EvidenceItem
from src.models.job import JobPosting
from src.models.match import (
    AnswersBundle,
    CategoryScores,
    ClarifyingAnswer,
    MatchReport,
)


def _evidence_items() -> list[EvidenceItem]:
    return [
        EvidenceItem(
            claim="Used Python in production",
            skill="Python",
            source_type="cv",
            source_name="cv.pdf",
            evidence_text="Wrote pytest suites for backend services.",
            confidence="high",
        ),
        EvidenceItem(
            claim="Has Selenium experience",
            skill="Selenium",
            source_type="github",
            source_name="github:fearplay/selenium-tests",
            evidence_text="Repo contains 12 Selenium tests.",
            confidence="medium",
        ),
    ]


def test_dump_handles_list_of_pydantic_models():
    items = _evidence_items()

    payload = prompts._dump(items)

    parsed = json.loads(payload)
    assert isinstance(parsed, list)
    assert len(parsed) == 2
    assert parsed[0]["claim"] == "Used Python in production"
    assert parsed[0]["skill"] == "Python"
    assert parsed[1]["source_name"] == "github:fearplay/selenium-tests"


def test_dump_handles_none():
    assert prompts._dump(None) == "null"


def test_dump_handles_single_pydantic_model():
    item = _evidence_items()[0]

    payload = prompts._dump(item)

    parsed = json.loads(payload)
    assert parsed["claim"] == "Used Python in production"


def test_dump_job_strips_raw_text_to_save_tokens():
    job = JobPosting(
        title="QA Automation Engineer",
        company="DemoCorp",
        required_skills=["Python", "Playwright"],
        raw_text="A" * 5000,
    )

    payload = prompts._dump_job(job)

    assert "raw_text" not in payload
    assert "QA Automation Engineer" in payload


def test_match_report_user_prompt_serializes_evidence_list():
    """Regression test for the EvidenceItem JSON serialisation bug."""
    job = JobPosting(title="QA Engineer", required_skills=["Python"])
    candidate = CandidateProfile(
        full_name="Test Candidate", technical_skills=["Python"]
    )
    answers = AnswersBundle(
        answers=[
            ClarifyingAnswer(question_id="q1", skill="Python", answer="Yes")
        ]
    )
    evidence = _evidence_items()

    body = prompts.match_report_user_prompt(job, candidate, answers, evidence)

    assert "EVIDENCE:" in body
    assert "Used Python in production" in body
    assert "Has Selenium experience" in body
    assert "raw_text" not in body


def test_resume_user_prompt_serializes_evidence_list():
    job = JobPosting(title="Backend Developer", raw_text="lorem ipsum " * 200)
    candidate = CandidateProfile(full_name="Test Candidate")
    answers = AnswersBundle()
    evidence = _evidence_items()

    body = prompts.resume_user_prompt(job, candidate, answers, evidence)

    assert "EVIDENCE:" in body
    assert "Used Python in production" in body
    assert "lorem ipsum " not in body


# ---------------------------------------------------------------------------
# OUTPUT_LANGUAGE policy
# ---------------------------------------------------------------------------
def test_resume_prompt_appends_czech_directive():
    job = JobPosting(title="QA")
    candidate = CandidateProfile(full_name="Candidate")
    body = prompts.resume_user_prompt(
        job, candidate, AnswersBundle(), [], output_language="cs"
    )

    assert "OUTPUT_LANGUAGE: Czech." in body
    assert "Write every human-facing string in Czech." in body


def test_match_report_prompt_appends_english_directive_by_default():
    job = JobPosting(title="QA")
    candidate = CandidateProfile(full_name="Candidate")
    body = prompts.match_report_user_prompt(
        job, candidate, AnswersBundle(), []
    )

    assert "OUTPUT_LANGUAGE: English." in body


def test_clarifying_questions_prompt_includes_language_directive():
    job = JobPosting(title="QA")
    candidate = CandidateProfile(full_name="Candidate")
    body = prompts.clarifying_questions_user_prompt(
        job, candidate, output_language="cs"
    )

    assert body.strip().endswith("Write every human-facing string in Czech.")


def test_cover_letter_prompt_appends_language_directive():
    job = JobPosting(title="QA")
    candidate = CandidateProfile(full_name="Candidate")
    body = prompts.cover_letter_user_prompt(
        job, candidate, AnswersBundle(), output_language="cs"
    )

    assert "OUTPUT_LANGUAGE: Czech." in body


def test_unknown_language_falls_back_to_english():
    job = JobPosting(title="QA")
    report = MatchReport(
        overall_score=50,
        category_scores=CategoryScores(
            technical_skills=50, experience=50, tools=50, qa_process=50
        ),
    )
    body = prompts.skill_gap_user_prompt(report, job, output_language="de")

    assert "OUTPUT_LANGUAGE: English." in body


# ---------------------------------------------------------------------------
# Resume prompt: dedup, employment_type, project ranking, no hallucination
# ---------------------------------------------------------------------------
def test_resume_prompt_includes_dedup_rule():
    """The resume prompt must explicitly forbid emitting twin entries."""
    job = JobPosting(title="QA")
    candidate = CandidateProfile(full_name="Candidate")

    body = prompts.resume_user_prompt(job, candidate, AnswersBundle(), [])

    assert "DEDUPLICATION" in body
    assert "same company" in body.lower() or "company and overlapping" in body.lower()
    assert "never emit twins" in body.lower() or "emit one tailoredresume.experience" in body.lower()


def test_resume_prompt_mentions_employment_type_subtitle():
    job = JobPosting(title="QA")
    candidate = CandidateProfile(full_name="Candidate")

    body = prompts.resume_user_prompt(job, candidate, AnswersBundle(), [])

    assert "employment_type" in body
    assert "Internship" in body
    assert "Stáž" in body  # Czech translation reminder


def test_resume_prompt_caps_projects_to_five_and_ranks_by_overlap():
    job = JobPosting(title="QA")
    candidate = CandidateProfile(full_name="Candidate")

    body = prompts.resume_user_prompt(job, candidate, AnswersBundle(), [])

    assert "AT MOST 5" in body
    assert "detected_technologies" in body
    assert "required_skills" in body
    assert "ats_keywords" in body


def test_resume_prompt_forbids_invented_metrics():
    job = JobPosting(title="QA")
    candidate = CandidateProfile(full_name="Candidate")

    body = prompts.resume_user_prompt(job, candidate, AnswersBundle(), [])

    assert "NO HALLUCINATION" in body
    assert "never invent" in body.lower() or "do not invent" in body.lower()


def test_global_rules_forbid_duplicate_facts_across_languages():
    """The cross-language dedup rule is applied to every prompt via _GLOBAL_RULES."""
    rules = prompts._GLOBAL_RULES
    assert "MERGE" in rules
    assert "Czech" in rules and "English" in rules


def test_analyze_candidate_prompt_requires_source_and_employment_type():
    body = prompts.analyze_candidate_user_prompt(
        cv_text="John Doe\nQA Engineer at Acme 2020-2022",
        linkedin_text="John Doe\nQA Engineer Acme 2020 - 2022",
        github_username=None,
        github_projects=[],
    )

    assert "source" in body.lower()
    assert "employment_type" in body
    assert "Stáž" in body
    assert "Internship" in body
    assert "DEDUPLICATION" in body


# ---------------------------------------------------------------------------
# Resume prompt: education must have institution, no cross-language bullets
# ---------------------------------------------------------------------------
def test_resume_prompt_requires_institution_for_education_rows():
    """Pin the new HARD RULE that forbids 'Informatika studies' rows
    with no school name."""
    job = JobPosting(title="QA")
    candidate = CandidateProfile(full_name="Candidate")

    body = prompts.resume_user_prompt(job, candidate, AnswersBundle(), [])

    assert "EDUCATION" in body
    assert "INSTITUTION REQUIRED" in body
    # The example we cite is the actual offending pattern from the bug
    # report so a future maintainer recognises it on sight.
    assert "Informatika studies" in body
    assert "OMIT" in body or "omit" in body


def test_resume_prompt_requires_one_language_per_bullet_list():
    """The cross-language bullet rule must be loud enough that the AI
    stops emitting English fragments next to Czech bullets."""
    job = JobPosting(title="QA")
    candidate = CandidateProfile(full_name="Candidate")

    body = prompts.resume_user_prompt(job, candidate, AnswersBundle(), [])

    assert "ONE LANGUAGE PER BULLET LIST" in body
    assert "OUTPUT_LANGUAGE" in body


# ---------------------------------------------------------------------------
# Resume prompt: LinkedIn-absence guard
# ---------------------------------------------------------------------------
def test_resume_prompt_includes_linkedin_absence_block_when_no_linkedin():
    """When the candidate has no LinkedIn data, the prompt must tell
    the AI to never reference LinkedIn anywhere in the output."""
    job = JobPosting(title="QA")
    candidate = CandidateProfile(
        full_name="Candidate",
        raw_cv_text="just a CV",
    )

    body = prompts.resume_user_prompt(job, candidate, AnswersBundle(), [])

    assert "LINKEDIN ABSENCE" in body
    assert "MUST NOT" in body or "must not" in body.lower()


def test_resume_prompt_omits_linkedin_block_when_linkedin_present():
    """Counter-test: when the user supplied LinkedIn, no scolding block."""
    job = JobPosting(title="QA")
    candidate = CandidateProfile(
        full_name="Candidate",
        raw_linkedin_text="LinkedIn export contents.",
    )

    body = prompts.resume_user_prompt(job, candidate, AnswersBundle(), [])

    assert "LINKEDIN ABSENCE" not in body


# ---------------------------------------------------------------------------
# Refine prompt: user-is-authoritative + previous_explanation + linkedin
# ---------------------------------------------------------------------------
def test_refine_prompt_includes_user_is_authoritative_rule():
    """The refine prompt must elevate user feedback above any general
    canonicalization or 'preserve original' policies."""
    job = JobPosting(title="QA")
    candidate = CandidateProfile(full_name="Candidate")
    body = prompts.refine_resume_user_prompt(
        current_resume=None,
        feedback="change A2 to B2",
        job=job,
        candidate=candidate,
        answers=AnswersBundle(),
        evidence=[],
        output_language="cs",
    )

    assert "USER IS AUTHORITATIVE" in body
    assert "DIRECT TEXT REPLACEMENT" in body
    # Concrete examples must reach the AI verbatim so the model has
    # something to pattern-match against.
    assert "Java backend development" in body
    assert "Java backend v\u00fdvoj" in body
    assert "LANGUAGE LEVEL CHANGES" in body
    assert "n\u011bm\u010dina A2" in body or "n\u011bm\u010dina" in body


def test_refine_prompt_includes_previous_explanation_when_provided():
    """The previous AI explanation must reach the model so it can
    interpret 'ano' / 'yes' as agreement with its own suggestion."""
    job = JobPosting(title="QA")
    candidate = CandidateProfile(full_name="Candidate")
    body = prompts.refine_resume_user_prompt(
        current_resume=None,
        feedback="ano",
        job=job,
        candidate=candidate,
        answers=AnswersBundle(),
        evidence=[],
        output_language="cs",
        previous_explanation="Mohu sma\u017eat pozici Junior Developer @ OldCorp?",
    )

    assert "PREVIOUS_AI_EXPLANATION" in body
    assert "Mohu sma\u017eat pozici Junior Developer" in body
    assert "AFFIRMATION INTERPRETATION (HARD RULE)" in body


def test_refine_prompt_omits_previous_explanation_block_when_empty():
    """When the caller passes no previous explanation, the
    AFFIRMATION INTERPRETATION block must NOT appear - we'd be
    instructing the AI to interpret an empty context, which is noise.
    The standalone block is gated behind a non-empty explanation; an
    inline reference to the rule inside the USER IS AUTHORITATIVE
    block is fine because it can be read on its own.
    """
    job = JobPosting(title="QA")
    candidate = CandidateProfile(full_name="Candidate")
    body = prompts.refine_resume_user_prompt(
        current_resume=None,
        feedback="zm\u011b\u0148 toto na tamto",
        job=job,
        candidate=candidate,
        answers=AnswersBundle(),
        evidence=[],
        output_language="cs",
    )

    assert "PREVIOUS_AI_EXPLANATION" not in body
    # The full standalone block header has the (HARD RULE) suffix - the
    # USER IS AUTHORITATIVE inline reference does not, so this is a
    # precise gate on whether the block itself rendered.
    assert "AFFIRMATION INTERPRETATION (HARD RULE)" not in body


def test_refine_prompt_includes_linkedin_absence_block_when_no_linkedin():
    """Same LinkedIn-absence guard in the refine prompt."""
    job = JobPosting(title="QA")
    candidate = CandidateProfile(full_name="Candidate", raw_cv_text="cv only")
    body = prompts.refine_resume_user_prompt(
        current_resume=None,
        feedback="polish summary",
        job=job,
        candidate=candidate,
        answers=AnswersBundle(),
        evidence=[],
        output_language="en",
    )

    assert "LINKEDIN ABSENCE" in body


def test_refine_prompt_omits_linkedin_block_when_linkedin_present():
    job = JobPosting(title="QA")
    candidate = CandidateProfile(
        full_name="Candidate",
        raw_linkedin_text="LinkedIn export.",
    )
    body = prompts.refine_resume_user_prompt(
        current_resume=None,
        feedback="polish summary",
        job=job,
        candidate=candidate,
        answers=AnswersBundle(),
        evidence=[],
        output_language="en",
    )

    assert "LINKEDIN ABSENCE" not in body
