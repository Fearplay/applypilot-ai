"""Tests for the evidence-based skill bucketing."""
from __future__ import annotations

from src.models.candidate import CandidateProfile, GitHubProject
from src.models.job import JobPosting
from src.models.match import (
    AnswersBundle,
    ClarifyingAnswer,
)
from src.services.evidence_checker import _clean_snippet, check_evidence


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


def test_clean_snippet_strips_separator_lines():
    raw = (
        "Technical Skills\n"
        "================\n"
        "Languages: Python, JavaScript\n"
        "Tools: pytest, Selenium"
    )
    cleaned = _clean_snippet(raw)
    assert "================" not in cleaned
    assert "====" not in cleaned
    assert "Languages: Python, JavaScript" in cleaned


def test_clean_snippet_collapses_multiple_blank_lines():
    raw = "Line one\n\n\n\nLine two\n\n\nLine three"
    cleaned = _clean_snippet(raw)
    assert "\n\n" not in cleaned
    assert cleaned.count("\n") == 2


def test_clean_snippet_trims_to_limit_at_word_boundary():
    raw = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda"
    cleaned = _clean_snippet(raw, limit=20)
    assert len(cleaned) <= 25  # 20 + 3 ellipsis + a tiny grace margin
    assert cleaned.endswith("...")
    # Should not chop a word in half.
    assert " " in cleaned[:-3]


def test_clean_snippet_handles_empty_input():
    assert _clean_snippet("") == ""
    assert _clean_snippet(None) == ""  # type: ignore[arg-type]


def test_evidence_text_no_longer_contains_separator_lines():
    job = _make_job(["Python"])
    candidate = CandidateProfile(
        full_name="Jane",
        raw_cv_text=(
            "Skills\n"
            "======\n"
            "Languages: Python, SQL\n"
        ),
    )
    result = check_evidence(job, candidate)
    python_items = [item for item in result.items if item.skill == "Python"]
    assert python_items, "Python skill must produce an evidence item"
    assert all("======" not in item.evidence_text for item in python_items)
