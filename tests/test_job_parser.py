"""Tests for the job parser orchestrator + role detector."""
from __future__ import annotations

import pytest

from src.ai.role_detector import detect_role_type
from src.services.job_parser import parse_job


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Software QA Engineer", "software_qa_engineer"),
        ("Senior QA Engineer", "software_qa_engineer"),
        ("QA Automation Engineer", "qa_automation_engineer"),
        ("SDET (Software Development Engineer in Test)", "qa_automation_engineer"),
        ("Manual QA Tester", "manual_qa_tester"),
        ("Test Engineer", "test_engineer"),
        ("Junior Python Developer", "junior_python_developer"),
        ("Junior Software Engineer", "junior_software_engineer"),
        ("Junior AI Engineer", "junior_ai_engineer"),
        ("Junior GenAI Engineer", "junior_ai_engineer"),
        ("Data Analyst", "data_analyst"),
        ("Frontend Developer", "frontend_developer"),
        ("Backend Developer", "backend_developer"),
        ("Fullstack Developer", "fullstack_developer"),
        ("DevOps Engineer", "devops_engineer"),
        ("SRE", "site_reliability_engineer"),
        ("Cloud Engineer", "cloud_engineer"),
        ("Mobile Developer", "mobile_developer"),
        ("Security Engineer", "security_engineer"),
        ("Machine Learning Engineer", "machine_learning_engineer"),
        # New AI / SWE role types added in the cs-localisation pass.
        # AI Software Engineer must NOT fall through to ML engineer or
        # other_it - it has its own persona with shipping-AI-features focus.
        ("AI Software Engineer", "ai_software_engineer"),
        ("Senior AI Software Engineer", "ai_software_engineer"),
        ("ML Software Engineer", "ai_software_engineer"),
        ("AI Platform Engineer", "ai_software_engineer"),
        # GenAI / LLM engineer flavour - prompts, RAG, agents.
        ("GenAI Engineer", "genai_engineer"),
        ("LLM Engineer", "genai_engineer"),
        ("Generative AI Engineer", "genai_engineer"),
        ("Prompt Engineer", "genai_engineer"),
        ("AI Agent Engineer", "genai_engineer"),
        # Generic mid/senior software engineer (lowest-priority bucket so
        # the more specific titles above always win).
        ("Software Engineer", "software_engineer"),
        ("Senior Software Engineer", "software_engineer"),
        ("Staff Software Engineer", "software_engineer"),
        ("Principal Software Engineer", "software_engineer"),
        ("Tech Lead", "software_engineer"),
        ("Marketing Manager", "other"),
    ],
)
def test_role_detector_titles(title: str, expected: str) -> None:
    assert detect_role_type(title) == expected


def test_role_detector_falls_back_to_other_it_when_only_description_helps() -> None:
    # Title is generic but description is clearly IT.
    role = detect_role_type(
        "Specialist",
        "Looking for someone comfortable with Python, REST APIs and Git.",
    )
    assert role in {"other_it", "junior_python_developer", "junior_software_engineer"}


def test_parse_job_round_trip(fake_provider, sample_job_text) -> None:
    job = parse_job(fake_provider, sample_job_text, source_url="https://example.com/job")
    assert job.title
    # raw_text is whitespace-normalised, so compare on a few salient phrases.
    assert "QA Automation Engineer" in job.raw_text
    assert "DemoCorp" in job.raw_text
    assert "Playwright" in job.raw_text
    assert job.source_url == "https://example.com/job"


def test_parse_job_rejects_empty(fake_provider) -> None:
    with pytest.raises(ValueError):
        parse_job(fake_provider, "")
