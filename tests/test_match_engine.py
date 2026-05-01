"""Tests for compute_match + needs_clarifying_questions."""
from __future__ import annotations

from src.models.candidate import CandidateProfile
from src.models.evidence import EvidenceCheckResult
from src.models.job import JobPosting
from src.models.match import AnswersBundle
from src.services.match_engine import compute_match, needs_clarifying_questions


def test_compute_match_returns_report_and_evidence(fake_provider, sample_job_text, sample_cv_text):
    job = fake_provider.analyze_job(sample_job_text)
    candidate = fake_provider.analyze_candidate(cv_text=sample_cv_text)
    report, evidence = compute_match(fake_provider, job, candidate, AnswersBundle())

    assert 0 <= report.overall_score <= 100
    assert isinstance(evidence, EvidenceCheckResult)
    assert report.category_scores.technical_skills >= 0


def test_needs_clarifying_questions_true_when_missing():
    job = JobPosting(title="QA Engineer", required_skills=["Playwright"])
    evidence = EvidenceCheckResult(missing_evidence_skills=["Playwright"])
    assert needs_clarifying_questions(job, evidence)


def test_needs_clarifying_questions_false_when_full_coverage():
    job = JobPosting(title="QA Engineer", required_skills=["Python", "Git"])
    evidence = EvidenceCheckResult(evidenced_skills=["Python", "Git"])
    assert not needs_clarifying_questions(job, evidence)


def test_needs_clarifying_questions_false_for_empty_required():
    job = JobPosting(title="QA Engineer", required_skills=[])
    evidence = EvidenceCheckResult()
    assert not needs_clarifying_questions(job, evidence)
