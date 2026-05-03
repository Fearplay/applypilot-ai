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
