"""Abstract base class every AI provider must implement."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from ..models.candidate import CandidateProfile, GitHubProject
from ..models.documents import (
    CoverLetter,
    InterviewQuestion,
    SkillGap,
    TailoredResume,
)
from ..models.evidence import EvidenceItem
from ..models.job import JobPosting
from ..models.match import AnswersBundle, ClarifyingQuestion, MatchReport


class BaseAIProvider(ABC):
    """Provider-agnostic interface for every AI capability used by the app."""

    #: Short identifier ("fake", "openai_compatible", ...)
    name: str = "base"
    #: True when this provider runs without any external API call.
    is_demo: bool = False
    #: Optional human-readable reason explaining why this provider is active.
    reason: str = ""

    # ------------------------------------------------------------------ job
    @abstractmethod
    def analyze_job(
        self, raw_text: str, source_url: str | None = None
    ) -> JobPosting:
        """Parse a raw job description into a structured :class:`JobPosting`."""

    # -------------------------------------------------------------- candidate
    @abstractmethod
    def analyze_candidate(
        self,
        cv_text: str = "",
        linkedin_text: str = "",
        github_username: str | None = None,
        github_projects: Sequence[GitHubProject] = (),
    ) -> CandidateProfile:
        """Merge raw candidate inputs into a structured CandidateProfile.

        ``github_projects`` should be the result of
        :func:`src.services.github_analyzer.fetch_github_projects` (already
        fetched, structured metadata). Providers must not invent additional
        repositories - only the items in this list exist.
        """

    # --------------------------------------------------------- clarifying Q
    @abstractmethod
    def generate_clarifying_questions(
        self,
        job: JobPosting,
        candidate: CandidateProfile,
        output_language: str = "en",
    ) -> list[ClarifyingQuestion]:
        """Return clarifying questions for the human-in-the-loop step.

        ``output_language`` is the language the *user* will read - the
        clarifying-question step is part of the in-app conversation, so it
        usually matches the UI language rather than the final document
        language. ``"en"`` and ``"cs"`` are recognised today.
        """

    # ------------------------------------------------------------ match
    @abstractmethod
    def generate_match_report(
        self,
        job: JobPosting,
        candidate: CandidateProfile,
        answers: AnswersBundle,
        evidence: Sequence[EvidenceItem] = (),
        output_language: str = "en",
    ) -> MatchReport:
        """Compute the structured match report."""

    # ------------------------------------------------------------ resume
    @abstractmethod
    def generate_resume(
        self,
        job: JobPosting,
        candidate: CandidateProfile,
        answers: AnswersBundle,
        evidence: Sequence[EvidenceItem] = (),
        output_language: str = "en",
    ) -> TailoredResume:
        """Generate the tailored ATS-friendly resume."""

    # ----------------------------------------------------------- cover ltr
    @abstractmethod
    def generate_cover_letter(
        self,
        job: JobPosting,
        candidate: CandidateProfile,
        answers: AnswersBundle,
        output_language: str = "en",
    ) -> CoverLetter:
        """Generate a tailored cover letter."""

    # --------------------------------------------------------- interview Q
    @abstractmethod
    def generate_interview_questions(
        self,
        job: JobPosting,
        candidate: CandidateProfile,
        output_language: str = "en",
    ) -> list[InterviewQuestion]:
        """Generate likely interview questions with prep notes."""

    # ------------------------------------------------------------ gaps
    @abstractmethod
    def generate_skill_gap_plan(
        self,
        match_report: MatchReport,
        job: JobPosting,
        output_language: str = "en",
    ) -> list[SkillGap]:
        """Generate a structured skill-gap plan."""


__all__ = ["BaseAIProvider"]
