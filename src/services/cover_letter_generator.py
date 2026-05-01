"""Cover letter generator."""
from __future__ import annotations

from ..ai.base import BaseAIProvider
from ..models.candidate import CandidateProfile
from ..models.documents import CoverLetter
from ..models.job import JobPosting
from ..models.match import AnswersBundle


def generate_cover_letter(
    provider: BaseAIProvider,
    job: JobPosting,
    candidate: CandidateProfile,
    answers: AnswersBundle | None = None,
) -> CoverLetter:
    answers = answers or AnswersBundle()
    return provider.generate_cover_letter(job, candidate, answers)


__all__ = ["generate_cover_letter"]
