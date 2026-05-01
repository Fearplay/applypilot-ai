"""Compute the structured match between a candidate and a job posting."""
from __future__ import annotations

import logging

from ..ai.base import BaseAIProvider
from ..models.candidate import CandidateProfile
from ..models.evidence import EvidenceCheckResult
from ..models.job import JobPosting
from ..models.match import AnswersBundle, MatchReport
from .evidence_checker import check_evidence

logger = logging.getLogger(__name__)


def compute_match(
    provider: BaseAIProvider,
    job: JobPosting,
    candidate: CandidateProfile,
    answers: AnswersBundle | None = None,
) -> tuple[MatchReport, EvidenceCheckResult]:
    """Run the evidence checker first, then ask the AI to score the match.

    Returns both the :class:`MatchReport` and the :class:`EvidenceCheckResult`
    so the GUI can show evidence cards next to the score.
    """
    answers = answers or AnswersBundle()
    evidence = check_evidence(job, candidate, answers)
    report = provider.generate_match_report(job, candidate, answers, evidence.items)

    # Ensure the AI report's evidence list is at least as rich as ours.
    if not report.evidence:
        report.evidence.extend(evidence.items)
    return report, evidence


def needs_clarifying_questions(
    job: JobPosting, evidence: EvidenceCheckResult, threshold: float = 0.85
) -> bool:
    """Return True when too many required skills lack evidence.

    Defaults: trigger the clarifying step if the evidence coverage of
    ``required_skills`` falls below ``threshold`` OR if any required skill is
    fully missing.
    """
    required = job.required_skills
    if not required:
        return False

    missing = [s for s in required if s in evidence.missing_evidence_skills]
    if missing:
        return True

    covered = sum(1 for s in required if s in evidence.evidenced_skills)
    coverage = covered / len(required)
    return coverage < threshold


__all__ = ["compute_match", "needs_clarifying_questions"]
