"""Tests for the tailored-resume generator and its `ensure_projects_section`
fallback. The user reported that GitHub-fetched projects were sometimes
silently dropped from the final resume - the fallback guarantees at least
one project survives whenever the candidate has any GitHub data to draw
from.
"""
from __future__ import annotations

from src.models.candidate import CandidateProfile, GitHubProject
from src.models.documents import ResumeBullet, ResumeSection, TailoredResume
from src.services.resume_generator import ensure_projects_section


def _make_resume(projects: list[ResumeSection] | None = None) -> TailoredResume:
    return TailoredResume(
        name="Test Candidate",
        professional_summary="Software engineer.",
        technical_skills=["Python"],
        projects=projects or [],
        role_targeted_for="Backend Developer",
    )


def test_ensure_projects_section_is_noop_when_resume_already_has_projects():
    existing = ResumeSection(
        title="My App",
        subtitle="Python",
        bullets=[ResumeBullet(text="Existing bullet.")],
    )
    resume = _make_resume([existing])
    candidate = CandidateProfile(
        full_name="X",
        projects=[
            GitHubProject(
                name="other-repo",
                url="https://github.com/x/other-repo",
                description="Should NOT be injected because we already have one.",
                stars=10,
            ),
        ],
    )
    out = ensure_projects_section(resume, candidate)
    assert out is resume
    assert len(out.projects) == 1
    assert out.projects[0].title == "My App"


def test_ensure_projects_section_is_noop_when_no_github_projects():
    resume = _make_resume([])
    candidate = CandidateProfile(full_name="X")
    out = ensure_projects_section(resume, candidate)
    assert out.projects == []


def test_ensure_projects_section_injects_highest_relevance_project():
    """When the AI returned an empty Projects section but the candidate has
    GitHub repos, we inject ONE fallback project ranked by
    (relevance, stars, description length)."""
    resume = _make_resume([])
    high_rel = GitHubProject(
        name="ai-resume-tool",
        url="https://github.com/x/ai-resume-tool",
        description="Tailored resume generator using OpenAI.",
        primary_language="Python",
        stars=2,
        relevance_score=0.85,
    )
    high_stars = GitHubProject(
        name="popular-cli",
        url="https://github.com/x/popular-cli",
        description="Tiny CLI tool.",
        primary_language="Go",
        stars=120,
        relevance_score=0.1,
    )
    candidate = CandidateProfile(full_name="X", projects=[high_stars, high_rel])
    out = ensure_projects_section(resume, candidate)
    assert len(out.projects) == 1
    section = out.projects[0]
    assert section.title == "ai-resume-tool"
    # Subtitle should include language + stars + url for transparency.
    assert "Python" in section.subtitle
    assert "https://github.com/x/ai-resume-tool" in section.subtitle
    assert section.bullets and section.bullets[0].text


def test_ensure_projects_section_falls_back_to_stars_then_description():
    """With equal relevance, the one with more stars wins. With equal stars,
    the one with the longer description wins."""
    resume = _make_resume([])
    short = GitHubProject(
        name="short",
        url="https://github.com/x/short",
        description="Short.",
        stars=5,
        relevance_score=0.3,
    )
    long = GitHubProject(
        name="long",
        url="https://github.com/x/long",
        description="A much longer and richer description that gives the AI more to work with.",
        stars=5,
        relevance_score=0.3,
    )
    candidate = CandidateProfile(full_name="X", projects=[short, long])
    out = ensure_projects_section(resume, candidate)
    assert out.projects[0].title == "long"
