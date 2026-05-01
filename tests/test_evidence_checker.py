"""Tests for the evidence-based skill bucketing."""
from __future__ import annotations

from src.models.candidate import CandidateProfile, GitHubProject
from src.models.job import JobPosting
from src.models.match import (
    AnswersBundle,
    ClarifyingAnswer,
)
from src.services.evidence_checker import check_evidence


def _make_job(required, nice=None) -> JobPosting:
    return JobPosting(
        title="Software QA Engineer",
        role_type="software_qa_engineer",
        required_skills=required,
        nice_to_have_skills=nice or [],
        ats_keywords=[],
    )


def test_evidenced_skills_come_from_cv_text():
    job = _make_job(["Python", "Selenium", "Jira"])
    candidate = CandidateProfile(
        full_name="Jane",
        raw_cv_text="Skills: Python and Selenium and pytest.",
        technical_skills=["Python", "Selenium"],
    )
    result = check_evidence(job, candidate)
    assert "Python" in result.evidenced_skills
    assert "Selenium" in result.evidenced_skills
    assert "Jira" in result.missing_evidence_skills


def test_user_answer_can_supply_evidence():
    job = _make_job(["Playwright"])
    candidate = CandidateProfile(full_name="Jane", raw_cv_text="Skills: Python.")
    answers = AnswersBundle(answers=[
        ClarifyingAnswer(
            question_id="q_playwright",
            skill="Playwright",
            answer="Yes - automated checkout flow",
            treat_as="practical_experience",
            confidence="high",
        )
    ])
    result = check_evidence(job, candidate, answers)
    assert "Playwright" in result.evidenced_skills


def test_learning_in_progress_is_not_evidence():
    job = _make_job(["Playwright"])
    candidate = CandidateProfile(full_name="Jane", raw_cv_text="")
    answers = AnswersBundle(answers=[
        ClarifyingAnswer(
            question_id="q_pw", skill="Playwright",
            answer="Currently learning",
            treat_as="learning_in_progress",
        )
    ])
    result = check_evidence(job, candidate, answers)
    assert "Playwright" in result.missing_evidence_skills


def test_github_project_text_counts_as_evidence():
    job = _make_job(["pytest"])
    project = GitHubProject(
        name="api-testing-pytest",
        url="https://x",
        readme_excerpt="A small REST API testing harness using pytest and requests.",
        languages=["Python"],
        detected_technologies=["pytest"],
    )
    candidate = CandidateProfile(full_name="Jane", projects=[project])
    result = check_evidence(job, candidate)
    assert "pytest" in result.evidenced_skills
    assert any(item.source_type == "github" for item in result.items)


def test_skill_only_in_skills_section_is_low_confidence():
    job = _make_job(["Postman"])
    candidate = CandidateProfile(full_name="Jane", technical_skills=["Postman"])
    result = check_evidence(job, candidate)
    # Listed-only skills become low-confidence items, so they end up in
    # weak_evidence (no high/medium item exists).
    assert "Postman" in result.weak_evidence_skills
    assert all(item.confidence == "low" for item in result.items if item.skill == "Postman")
