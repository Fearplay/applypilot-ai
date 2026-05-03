"""Models describing the parsed job posting."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

WorkArrangement = Literal["onsite", "remote", "hybrid", "unknown"]
SeniorityLevel = Literal["intern", "junior", "mid", "senior", "lead", "unknown"]

#: Stable role identifiers the application understands. ``other`` is used as a
#: catch-all when the title cannot be confidently classified.
RoleType = Literal[
    "software_qa_engineer",
    "qa_automation_engineer",
    "manual_qa_tester",
    "test_engineer",
    "junior_python_developer",
    "junior_software_engineer",
    "junior_ai_engineer",
    "data_analyst",
    "frontend_developer",
    "backend_developer",
    "fullstack_developer",
    "devops_engineer",
    "data_engineer",
    "machine_learning_engineer",
    "ai_software_engineer",
    "genai_engineer",
    "software_engineer",
    "mobile_developer",
    "site_reliability_engineer",
    "security_engineer",
    "cloud_engineer",
    "other_it",
    "other",
]

#: Human-friendly labels for :data:`RoleType` values. Used in prompts and UI.
ROLE_TYPE_LABELS: dict[str, str] = {
    "software_qa_engineer": "Software QA Engineer",
    "qa_automation_engineer": "QA Automation Engineer",
    "manual_qa_tester": "Manual QA Tester",
    "test_engineer": "Test Engineer",
    "junior_python_developer": "Junior Python Developer",
    "junior_software_engineer": "Junior Software Engineer",
    "junior_ai_engineer": "Junior AI / GenAI Engineer",
    "data_analyst": "Data Analyst",
    "frontend_developer": "Frontend Developer",
    "backend_developer": "Backend Developer",
    "fullstack_developer": "Fullstack Developer",
    "devops_engineer": "DevOps Engineer",
    "data_engineer": "Data Engineer",
    "machine_learning_engineer": "Machine Learning Engineer",
    "ai_software_engineer": "AI Software Engineer",
    "genai_engineer": "GenAI / LLM Engineer",
    "software_engineer": "Software Engineer (Mid / Senior)",
    "mobile_developer": "Mobile Developer",
    "site_reliability_engineer": "Site Reliability Engineer",
    "security_engineer": "Security Engineer",
    "cloud_engineer": "Cloud Engineer",
    "other_it": "Other IT role",
    "other": "Unknown / Non-IT role",
}


class JobPosting(BaseModel):
    """Structured representation of a parsed job posting."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    title: str = Field(..., description="Job title as advertised.")
    company: str = Field(default="", description="Hiring company name.")
    location: str = Field(default="", description="Free-text location or 'Remote'.")
    work_arrangement: WorkArrangement = Field(default="unknown")
    seniority: SeniorityLevel = Field(default="unknown")
    role_type: RoleType = Field(
        default="other",
        description=(
            "Coarse categorisation of the role used to pick the right HR/recruiter "
            "persona for AI prompts."
        ),
    )

    responsibilities: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    ats_keywords: list[str] = Field(
        default_factory=list,
        description="High-signal ATS keywords ranked by importance, most important first.",
    )

    tone: str = Field(
        default="professional",
        description="Overall tone of the posting (e.g. 'startup', 'corporate', 'casual').",
    )
    priorities: list[str] = Field(
        default_factory=list,
        description="What the posting emphasises most (e.g. 'communication', 'automation').",
    )

    raw_text: str = Field(default="", description="Original posting text used for parsing.")
    source_url: str | None = Field(default=None)


__all__ = [
    "WorkArrangement",
    "SeniorityLevel",
    "RoleType",
    "ROLE_TYPE_LABELS",
    "JobPosting",
]
