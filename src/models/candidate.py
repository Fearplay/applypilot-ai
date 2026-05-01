"""Models describing the candidate profile (parsed from CV, LinkedIn, GitHub)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class WorkExperience(BaseModel):
    """A single work-history entry."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    title: str
    company: str = ""
    period: str = Field(default="", description="Free-text date range, e.g. 'Jan 2023 - Present'.")
    location: str = ""
    bullets: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class EducationEntry(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    institution: str
    degree: str = ""
    period: str = ""
    notes: str | None = None


class CertificationEntry(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str
    issuer: str | None = None
    year: str | None = None


class GitHubProject(BaseModel):
    """A repository fetched from the GitHub REST API and analysed."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str
    url: str
    description: str | None = None
    primary_language: str | None = None
    languages: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    stars: int = 0
    forks: int = 0
    last_updated: str | None = None
    readme_excerpt: str | None = Field(
        default=None,
        description="Up to ~5 KB of the README used to detect tech and signal.",
    )
    detected_technologies: list[str] = Field(default_factory=list)
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    relevance_reason: str | None = None


class CandidateProfile(BaseModel):
    """Unified candidate profile aggregated from CV, LinkedIn and GitHub."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    full_name: str = ""
    headline: str = Field(
        default="",
        description="Short professional headline (LinkedIn-style).",
    )
    contact_email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None

    summary: str = ""
    technical_skills: list[str] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    spoken_languages: list[str] = Field(default_factory=list)

    experience: list[WorkExperience] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    certifications: list[CertificationEntry] = Field(default_factory=list)
    projects: list[GitHubProject] = Field(default_factory=list)

    raw_cv_text: str = Field(default="", description="Verbatim text extracted from CV.")
    raw_linkedin_text: str = Field(default="", description="Verbatim text from LinkedIn export.")
    github_username: str | None = None
    github_repo_urls: list[str] = Field(
        default_factory=list,
        description="Public GitHub repo URLs the candidate provided manually (no REST API).",
    )


__all__ = [
    "WorkExperience",
    "EducationEntry",
    "CertificationEntry",
    "GitHubProject",
    "CandidateProfile",
]
