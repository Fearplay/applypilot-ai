"""Evidence-tracking models.

Every important claim that ends up in the tailored resume must be backed
by an :class:`EvidenceItem`. If no evidence exists, the claim is moved to
``ClarifyingQuestion`` (asked to the user) or to ``SkillGap`` (in the
skill-gap plan). This is the foundation of the "no hallucinated experience"
policy.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EvidenceConfidence = Literal["high", "medium", "low"]
EvidenceSourceType = Literal["cv", "linkedin", "github", "user_answer", "job_posting"]


class EvidenceItem(BaseModel):
    """A single piece of evidence supporting a candidate claim."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    claim: str = Field(..., description="Short statement that this evidence supports.")
    skill: str | None = Field(
        default=None,
        description="The skill/keyword the claim relates to, if any.",
    )
    source_type: EvidenceSourceType = Field(
        ..., description="Where the evidence was found."
    )
    source_name: str = Field(
        ...,
        description=(
            "Human-readable source name, e.g. 'cv.pdf', "
            "'github:fearplay/api-testing-pytest', 'linkedin export'."
        ),
    )
    evidence_text: str = Field(
        ...,
        description="Verbatim or paraphrased excerpt that supports the claim.",
    )
    confidence: EvidenceConfidence = Field(
        default="medium",
        description="How strongly the evidence supports the claim.",
    )


class EvidenceCheckResult(BaseModel):
    """Result of running the evidence checker over a candidate profile."""

    model_config = ConfigDict(extra="ignore")

    evidenced_skills: list[str] = Field(default_factory=list)
    weak_evidence_skills: list[str] = Field(default_factory=list)
    missing_evidence_skills: list[str] = Field(default_factory=list)
    items: list[EvidenceItem] = Field(default_factory=list)


__all__ = [
    "EvidenceConfidence",
    "EvidenceSourceType",
    "EvidenceItem",
    "EvidenceCheckResult",
]
