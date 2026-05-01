"""Pydantic data models for ApplyPilot AI.

All models live here so they can be imported with::

    from src.models import JobPosting, CandidateProfile, MatchReport
"""
from __future__ import annotations

from .candidate import (
    CandidateProfile,
    CertificationEntry,
    EducationEntry,
    GitHubProject,
    WorkExperience,
)
from .documents import (
    CoverLetter,
    GapImportance,
    InterviewCategory,
    InterviewQuestion,
    ResumeBullet,
    ResumeSection,
    SkillGap,
    TailoredResume,
)
from .evidence import (
    EvidenceCheckResult,
    EvidenceConfidence,
    EvidenceItem,
    EvidenceSourceType,
)
from .job import (
    ROLE_TYPE_LABELS,
    JobPosting,
    RoleType,
    SeniorityLevel,
    WorkArrangement,
)
from .match import (
    AnswersBundle,
    CategoryScores,
    ClarifyingAnswer,
    ClarifyingAnswerType,
    ClarifyingQuestion,
    MatchReport,
)
from .package import GeneratedApplicationPackage

__all__ = [
    # job
    "JobPosting",
    "RoleType",
    "ROLE_TYPE_LABELS",
    "SeniorityLevel",
    "WorkArrangement",
    # candidate
    "CandidateProfile",
    "WorkExperience",
    "EducationEntry",
    "CertificationEntry",
    "GitHubProject",
    # evidence
    "EvidenceItem",
    "EvidenceCheckResult",
    "EvidenceConfidence",
    "EvidenceSourceType",
    # match
    "MatchReport",
    "CategoryScores",
    "ClarifyingQuestion",
    "ClarifyingAnswer",
    "ClarifyingAnswerType",
    "AnswersBundle",
    # documents
    "TailoredResume",
    "ResumeSection",
    "ResumeBullet",
    "CoverLetter",
    "InterviewQuestion",
    "InterviewCategory",
    "SkillGap",
    "GapImportance",
    # package
    "GeneratedApplicationPackage",
]
