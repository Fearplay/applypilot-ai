"""Tailored resume generator (delegates to the AI provider)."""
from __future__ import annotations

from collections.abc import Sequence

from ..ai.base import BaseAIProvider
from ..models.candidate import CandidateProfile
from ..models.documents import TailoredResume
from ..models.evidence import EvidenceItem
from ..models.job import JobPosting
from ..models.match import AnswersBundle


def generate_tailored_resume(
    provider: BaseAIProvider,
    job: JobPosting,
    candidate: CandidateProfile,
    answers: AnswersBundle | None = None,
    evidence: Sequence[EvidenceItem] = (),
) -> TailoredResume:
    answers = answers or AnswersBundle()
    return provider.generate_resume(job, candidate, answers, evidence)


__all__ = ["generate_tailored_resume"]
