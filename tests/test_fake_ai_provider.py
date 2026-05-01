"""FakeAIProvider must return valid Pydantic models for every method."""
from __future__ import annotations

import pytest

from src.models import (
    AnswersBundle,
    CandidateProfile,
    ClarifyingQuestion,
    CoverLetter,
    InterviewQuestion,
    JobPosting,
    MatchReport,
    SkillGap,
    TailoredResume,
)


def test_analyze_job_returns_jobposting(fake_provider, sample_job_text):
    job = fake_provider.analyze_job(sample_job_text, source_url="https://x/job")
    assert isinstance(job, JobPosting)
    assert job.title
    assert job.role_type in {"qa_automation_engineer", "software_qa_engineer", "test_engineer"}
    assert job.required_skills, "fake provider should populate required_skills"
    assert job.raw_text  # raw text preserved
    assert job.source_url == "https://x/job"


def test_analyze_candidate_returns_profile(fake_provider, sample_cv_text):
    profile = fake_provider.analyze_candidate(cv_text=sample_cv_text)
    assert isinstance(profile, CandidateProfile)
    assert profile.full_name.startswith("Jane")
    assert "Python" in profile.technical_skills


def test_clarifying_questions_have_unique_ids(fake_provider, sample_job_text, sample_cv_text):
    job = fake_provider.analyze_job(sample_job_text)
    candidate = fake_provider.analyze_candidate(cv_text=sample_cv_text)
    questions = fake_provider.generate_clarifying_questions(job, candidate)
    assert all(isinstance(q, ClarifyingQuestion) for q in questions)
    ids = [q.id for q in questions]
    assert len(ids) == len(set(ids)), f"Duplicate question ids: {ids}"


def test_match_report_in_range(fake_provider, sample_job_text, sample_cv_text):
    job = fake_provider.analyze_job(sample_job_text)
    candidate = fake_provider.analyze_candidate(cv_text=sample_cv_text)
    report = fake_provider.generate_match_report(job, candidate, AnswersBundle())
    assert isinstance(report, MatchReport)
    assert 0 <= report.overall_score <= 100
    for value in (
        report.category_scores.technical_skills,
        report.category_scores.experience,
        report.category_scores.tools,
        report.category_scores.qa_process,
    ):
        assert 0 <= value <= 100


def test_resume_uses_real_candidate_data(fake_provider, sample_job_text, sample_cv_text):
    job = fake_provider.analyze_job(sample_job_text)
    candidate = fake_provider.analyze_candidate(cv_text=sample_cv_text)
    resume = fake_provider.generate_resume(job, candidate, AnswersBundle())
    assert isinstance(resume, TailoredResume)
    assert resume.name.startswith("Jane")
    assert resume.role_targeted_for
    # Resume must reference at least one real skill, not invent something.
    assert any(s in resume.technical_skills for s in candidate.technical_skills)


def test_cover_letter_mentions_company(fake_provider, sample_job_text, sample_cv_text):
    job = fake_provider.analyze_job(sample_job_text)
    candidate = fake_provider.analyze_candidate(cv_text=sample_cv_text)
    letter = fake_provider.generate_cover_letter(job, candidate, AnswersBundle())
    assert isinstance(letter, CoverLetter)
    assert letter.paragraphs
    assert letter.role


def test_interview_questions_exactly_ten(fake_provider, sample_job_text, sample_cv_text):
    job = fake_provider.analyze_job(sample_job_text)
    candidate = fake_provider.analyze_candidate(cv_text=sample_cv_text)
    questions = fake_provider.generate_interview_questions(job, candidate)
    assert len(questions) == 10
    assert all(isinstance(q, InterviewQuestion) for q in questions)
    assert {q.category for q in questions}.issubset(
        {"technical", "behavioural", "process", "culture"}
    )


def test_skill_gap_plan_for_missing_only(fake_provider, sample_job_text, sample_cv_text):
    job = fake_provider.analyze_job(sample_job_text)
    candidate = fake_provider.analyze_candidate(cv_text=sample_cv_text)
    report = fake_provider.generate_match_report(job, candidate, AnswersBundle())
    plan = fake_provider.generate_skill_gap_plan(report, job)
    assert all(isinstance(g, SkillGap) for g in plan)
    for gap in plan:
        assert gap.learning_path
        assert gap.suggested_project
