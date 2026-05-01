"""Models for AI-generated documents (resume, cover letter, interview, gaps)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

InterviewCategory = Literal["technical", "behavioural", "process", "culture"]
GapImportance = Literal["critical", "important", "nice_to_have"]


class ResumeBullet(BaseModel):
    """A single resume bullet, kept atomic so the GUI can edit it inline."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    text: str
    keywords: list[str] = Field(default_factory=list)


class ResumeSection(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    title: str
    subtitle: str = Field(
        default="",
        description="Optional second line, e.g. company + period for an experience entry.",
    )
    bullets: list[ResumeBullet] = Field(default_factory=list)


class TailoredResume(BaseModel):
    """ATS-friendly tailored resume."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str
    contact_line: str = Field(
        default="",
        description="One-line 'email | phone | location' style contact string.",
    )
    linkedin: str | None = None
    github: str | None = None
    portfolio: str | None = None

    professional_summary: str
    technical_skills: list[str] = Field(default_factory=list)
    projects: list[ResumeSection] = Field(default_factory=list)
    experience: list[ResumeSection] = Field(default_factory=list)
    education: list[ResumeSection] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)

    role_targeted_for: str = Field(
        default="",
        description="Human-readable role this resume was tailored for.",
    )


class CoverLetter(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    salutation: str = "Dear Hiring Manager,"
    paragraphs: list[str] = Field(default_factory=list)
    closing: str = "Best regards,"
    signature: str = ""
    company: str = ""
    role: str = ""


class InterviewQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    question: str
    why_asked: str = ""
    suggested_answer: str = ""
    category: InterviewCategory = "technical"


class SkillGap(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    skill: str
    importance: GapImportance = "important"
    rationale: str = ""
    learning_path: list[str] = Field(default_factory=list)
    suggested_project: str = ""


__all__ = [
    "InterviewCategory",
    "GapImportance",
    "ResumeBullet",
    "ResumeSection",
    "TailoredResume",
    "CoverLetter",
    "InterviewQuestion",
    "SkillGap",
]
