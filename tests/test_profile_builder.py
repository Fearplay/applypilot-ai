"""Tests for profile_builder + linkedin/resume parsers."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.models.candidate import GitHubProject
from src.services.profile_builder import build_candidate_profile
from src.services.resume_parser import ResumeParseError, parse_resume_file


def test_build_profile_uses_only_provided_data(fake_provider, sample_cv_text):
    profile = build_candidate_profile(
        fake_provider,
        cv_text=sample_cv_text,
        github_username="octocat",
        github_projects=[
            GitHubProject(
                name="api-tests",
                url="https://github.com/octocat/api-tests",
                primary_language="Python",
                detected_technologies=["python", "pytest", "requests"],
            )
        ],
    )
    assert profile.full_name.startswith("Jane")
    assert "Python" in profile.technical_skills
    assert profile.github_username == "octocat"
    assert profile.projects and profile.projects[0].name == "api-tests"


def test_build_profile_handles_empty_inputs(fake_provider):
    profile = build_candidate_profile(fake_provider)
    assert profile.full_name == "Anonymous Candidate"
    assert "No CV" in profile.summary or profile.summary


def test_resume_parser_handles_txt(tmp_path: Path):
    f = tmp_path / "cv.txt"
    f.write_text("John Doe\nPython, Selenium", encoding="utf-8")
    text = parse_resume_file(f)
    assert "John Doe" in text


def test_resume_parser_rejects_unknown_extension(tmp_path: Path):
    f = tmp_path / "cv.bin"
    f.write_bytes(b"\x00\x01\x02")
    with pytest.raises(ResumeParseError):
        parse_resume_file(f)


def test_resume_parser_rejects_missing_file(tmp_path: Path):
    with pytest.raises(ResumeParseError):
        parse_resume_file(tmp_path / "missing.txt")
