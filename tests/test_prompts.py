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
from src.models.match import AnswersBundle, ClarifyingAnswer


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
