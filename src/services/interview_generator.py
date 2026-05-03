"""Interview question generator."""
from __future__ import annotations

from ..ai.base import BaseAIProvider
from ..models.candidate import CandidateProfile
from ..models.documents import InterviewQuestion
from ..models.job import JobPosting


def generate_interview_questions(
    provider: BaseAIProvider,
    job: JobPosting,
    candidate: CandidateProfile,
    output_language: str = "en",
) -> list[InterviewQuestion]:
    return provider.generate_interview_questions(
        job, candidate, output_language=output_language
    )


__all__ = ["generate_interview_questions"]
