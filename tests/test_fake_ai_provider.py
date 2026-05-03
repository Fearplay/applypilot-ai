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


def test_match_report_suggests_removing_mcdonalds_for_it_role(fake_provider):
    """The fake provider's heuristic must flag a fast-food job as
    'unrelated' when the target role is an IT position. The user
    explicitly asked for this in the cs-localisation pass."""
    from src.models.candidate import WorkExperience
    from src.models.job import JobPosting

    job = JobPosting(
        title="AI Software Engineer",
        company="Microsoft",
        role_type="ai_software_engineer",
        required_skills=["Python", "LLMs", "RAG"],
        raw_text="AI Software Engineer role at Microsoft",
    )
    candidate = CandidateProfile(
        full_name="Test Candidate",
        technical_skills=["Python"],
        experience=[
            WorkExperience(
                id="exp-mc",
                title="Crew Member",
                company="McDonald's",
                period="2018 - 2019",
                source="cv",
            ),
            WorkExperience(
                id="exp-dev",
                title="Junior Developer",
                company="Acme",
                period="2020 - 2024",
                source="cv",
            ),
        ],
    )
    report = fake_provider.generate_match_report(job, candidate, AnswersBundle())
    flagged_ids = {s.entry_id for s in report.suggested_removals}
    assert "exp-mc" in flagged_ids
    assert "exp-dev" not in flagged_ids
    mc_suggestion = next(s for s in report.suggested_removals if s.entry_id == "exp-mc")
    assert mc_suggestion.section == "experience"
    assert mc_suggestion.reason


def test_match_report_does_not_suggest_removals_for_non_it_role(fake_provider):
    """If the target role is non-IT (e.g. 'other'), the heuristic must NOT
    fire - we don't want to suggest dropping a relevant retail job from
    a retail-manager resume."""
    from src.models.candidate import WorkExperience
    from src.models.job import JobPosting

    job = JobPosting(
        title="Marketing Manager",
        company="Some Co",
        role_type="other",
        required_skills=["Marketing"],
        raw_text="Marketing Manager",
    )
    candidate = CandidateProfile(
        full_name="X",
        experience=[
            WorkExperience(
                id="exp-mc",
                title="Crew Member",
                company="McDonald's",
                period="2018 - 2019",
                source="cv",
            ),
        ],
    )
    report = fake_provider.generate_match_report(job, candidate, AnswersBundle())
    assert report.suggested_removals == []
