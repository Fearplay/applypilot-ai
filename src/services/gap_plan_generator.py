"""Skill-gap plan generator."""
from __future__ import annotations

from ..ai.base import BaseAIProvider
from ..models.documents import SkillGap
from ..models.job import JobPosting
from ..models.match import MatchReport


def generate_skill_gap_plan(
    provider: BaseAIProvider,
    match_report: MatchReport,
    job: JobPosting,
) -> list[SkillGap]:
    return provider.generate_skill_gap_plan(match_report, job)


__all__ = ["generate_skill_gap_plan"]
