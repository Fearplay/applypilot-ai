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


def test_build_profile_forwards_additional_notes(fake_provider, sample_cv_text):
    """The free-text notes the user typed in Setup must reach the
    CandidateProfile so every downstream prompt re-reads them."""
    notes = (
        "Vysokou \u0161kolu jsem ukon\u010dil v roce 2023 bez titulu "
        "bakal\u00e1\u0159e. Cht\u011bl bych nastoupit na part-time."
    )

    profile = build_candidate_profile(
        fake_provider,
        cv_text=sample_cv_text,
        additional_notes=notes,
    )

    # Verbatim copy: any whitespace-trimmed mismatch would mean a
    # downstream prompt sees a paraphrase, not the user's own words.
    assert profile.additional_notes == notes.strip()


def test_build_profile_handles_only_notes(fake_provider):
    """Notes alone (no CV / LinkedIn / GitHub) must NOT trip the
    'all inputs empty' guard. The pipeline must reach the provider
    so the user's clarifications survive on the returned profile,
    rather than short-circuiting to the 'No CV / LinkedIn / GitHub'
    stub that would also nuke the notes."""
    notes = "I'm a junior Python developer looking for QA roles."
    profile = build_candidate_profile(
        fake_provider,
        additional_notes=notes,
    )

    assert profile.additional_notes == notes
    # The 'all inputs empty' early-return path leaves a hardcoded
    # "No CV, LinkedIn export or GitHub profile was provided." summary;
    # if we see that string here, the guard fired and we lost the notes.
    assert "No CV, LinkedIn export or GitHub profile" not in profile.summary


def test_build_profile_safety_net_restores_dropped_notes(sample_cv_text):
    """Even if a quirky AI provider drops the additional_notes field on
    the returned profile, build_candidate_profile re-injects the user's
    text so downstream prompts never lose context."""
    from src.ai.fake_provider import FakeAIProvider
    from src.models.candidate import CandidateProfile

    class _DroppingProvider(FakeAIProvider):
        def analyze_candidate(self, **kwargs) -> CandidateProfile:  # type: ignore[override]
            profile = super().analyze_candidate(**kwargs)
            object.__setattr__(profile, "additional_notes", "")
            return profile

    notes = "Plánuji změnu kariéry do QA, mám 3 roky Pythonu."
    profile = build_candidate_profile(
        _DroppingProvider(),
        cv_text=sample_cv_text,
        additional_notes=notes,
    )

    assert profile.additional_notes == notes.strip()


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
