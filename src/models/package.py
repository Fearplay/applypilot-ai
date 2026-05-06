"""Bundle model that ties together everything produced for one application."""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from .candidate import CandidateProfile
from .documents import CoverLetter, InterviewQuestion, SkillGap, TailoredResume
from .evidence import EvidenceItem
from .job import JobPosting
from .match import AnswersBundle, MatchReport


class GeneratedApplicationPackage(BaseModel):
    """All artefacts generated for a single job application."""

    model_config = ConfigDict(extra="ignore")

    job_posting: JobPosting
    candidate_profile: CandidateProfile
    answers: AnswersBundle = Field(default_factory=AnswersBundle)
    match_report: MatchReport
    tailored_resume: TailoredResume
    cover_letter: CoverLetter
    interview_questions: list[InterviewQuestion] = Field(default_factory=list)
    skill_gap_plan: list[SkillGap] = Field(default_factory=list)
    candidate_questions_for_company: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    output_dir: str = ""
    output_language: str = Field(
        default="en",
        description=(
            "Language the user picked for the generated documents (`en` / "
            "`cs`). The exporters use this directly so labels and diacritics "
            "stay consistent regardless of the source CV/LinkedIn language mix."
        ),
    )
    output_theme: str = Field(
        default="teal_sidebar",
        description=(
            "Slug of the visual theme picked for the styled resume / cover "
            "letter HTML + PDF (one of "
            "`src.services.document_themes.RESUME_THEMES`). The user can ask "
            "for `random` in the dialog; that gets resolved to a concrete "
            "slug at save time so the package always remembers a real theme."
        ),
    )
    translate_positions: bool = Field(
        default=True,
        description=(
            "Whether role titles + company subtitles are translated into "
            "`output_language` (default ``True``, historical behaviour) or "
            "kept verbatim from the candidate input (``False``). Bullets, "
            "summary, periods and education rows always follow "
            "`output_language` regardless. Toggled via the "
            "``Translate position titles`` checkbox in the output-language "
            "dialog."
        ),
    )


__all__ = ["GeneratedApplicationPackage"]
