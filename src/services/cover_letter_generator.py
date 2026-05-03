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
    output_language: str = "en",
) -> CoverLetter:
    answers = answers or AnswersBundle()
    return provider.generate_cover_letter(
        job, candidate, answers, output_language=output_language
    )


__all__ = ["generate_cover_letter"]
