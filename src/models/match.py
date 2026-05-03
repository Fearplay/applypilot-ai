"""Models for match reports and clarifying questions."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .evidence import EvidenceConfidence, EvidenceItem

ClarifyingAnswerType = Literal["yes_no", "short_text", "single_choice", "multi_choice"]


class CategoryScores(BaseModel):
    model_config = ConfigDict(extra="ignore")

    technical_skills: int = Field(ge=0, le=100, default=0)
    experience: int = Field(ge=0, le=100, default=0)
    tools: int = Field(ge=0, le=100, default=0)
    qa_process: int = Field(
        ge=0,
        le=100,
        default=0,
        description="QA / engineering process maturity score (still useful for non-QA roles as 'process score').",
    )


class SuggestedRemoval(BaseModel):
    """An entry the AI thinks is unrelated to the target role.

    The user has the final say - everything in this list is surfaced inside
    :class:`SectionRemovalConfirmDialog` with the box UNTICKED, so nothing
    actually gets dropped from the resume unless the user actively confirms.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    entry_id: str = Field(
        ...,
        description=(
            "Stable id of the WorkExperience / EducationEntry the AI thinks is "
            "unrelated. Must match an existing entry id on the candidate "
            "profile - unknown ids are ignored downstream."
        ),
    )
    section: Literal["experience", "education"] = Field(
        default="experience",
        description="Which section of the candidate profile the entry lives in.",
    )
    reason: str = Field(
        default="",
        description=(
            "Short, user-facing rationale for why this entry feels unrelated "
            "(e.g. 'McDonald's crew member doesn't relate to a Python "
            "backend role'). Shown verbatim in the confirmation dialog."
        ),
    )


class MatchReport(BaseModel):
    """Report produced by the match engine comparing job vs candidate."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    overall_score: int = Field(ge=0, le=100)
    category_scores: CategoryScores
    matched_requirements: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    risky_gaps: list[str] = Field(
        default_factory=list,
        description="Gaps that would make the candidate unlikely to pass a screen.",
    )
    ats_keywords_present: list[str] = Field(default_factory=list)
    ats_keywords_missing: list[str] = Field(default_factory=list)
    recommended_improvements: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    summary: str = Field(default="", description="Short narrative summary of the match.")
    suggested_removals: list[SuggestedRemoval] = Field(
        default_factory=list,
        description=(
            "Profile entries the AI judged as unrelated to the target role "
            "(e.g. fast-food crew job for an IT position). Surfaced to the "
            "user as DEFAULT-UNTICKED proposals in the pre-generation "
            "confirmation dialog - never deleted automatically."
        ),
    )


class ClarifyingQuestion(BaseModel):
    """A question shown to the user when the AI lacks evidence for a skill."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id: str = Field(..., description="Stable ID used to attach the answer back.")
    skill: str | None = Field(
        default=None,
        description="The skill or topic this question relates to (used for evidence updates).",
    )
    question: str
    why_it_matters: str = ""
    options: list[str] = Field(
        default_factory=list,
        description="Optional answer options for choice-based questions.",
    )
    answer_type: ClarifyingAnswerType = "short_text"


class ClarifyingAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    question_id: str
    skill: str | None = None
    answer: str = ""
    confidence: EvidenceConfidence = "medium"
    treat_as: Literal["practical_experience", "learning_in_progress", "omit"] = "practical_experience"


class AnswersBundle(BaseModel):
    """Container for all clarifying answers in one workflow run."""

    model_config = ConfigDict(extra="ignore")

    answers: list[ClarifyingAnswer] = Field(default_factory=list)

    def get(self, question_id: str) -> ClarifyingAnswer | None:
        for a in self.answers:
            if a.question_id == question_id:
                return a
        return None


__all__ = [
    "ClarifyingAnswerType",
    "CategoryScores",
    "MatchReport",
    "SuggestedRemoval",
    "ClarifyingQuestion",
    "ClarifyingAnswer",
    "AnswersBundle",
]
