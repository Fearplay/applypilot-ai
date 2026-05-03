"""Tailored resume generator (delegates to the AI provider)."""
from __future__ import annotations

import logging
from collections.abc import Sequence

from ..ai.base import BaseAIProvider
from ..models.candidate import CandidateProfile, GitHubProject
from ..models.documents import ResumeBullet, ResumeSection, TailoredResume
from ..models.evidence import EvidenceItem
from ..models.job import JobPosting
from ..models.match import AnswersBundle

logger = logging.getLogger(__name__)


def _pick_fallback_project(projects: Sequence[GitHubProject]) -> GitHubProject | None:
    """Return the most resume-worthy project from ``projects`` or ``None``.

    Ranking is deterministic: highest ``relevance_score`` first, then most
    stars, then longest description / readme so the choice is stable across
    runs. ``None`` when the input is empty.
    """
    if not projects:
        return None
    return max(
        projects,
        key=lambda p: (
            p.relevance_score or 0.0,
            p.stars or 0,
            len(p.description or "") + len((p.readme_excerpt or "")[:200]),
        ),
    )


def _project_to_section(project: GitHubProject) -> ResumeSection:
    """Build a single ``ResumeSection`` for ``project`` using only facts the
    GitHub fetcher already collected. Conservative on text: at most one
    bullet so the AI's nicer wording wins on the next regeneration."""
    subtitle_bits: list[str] = []
    if project.primary_language:
        subtitle_bits.append(project.primary_language)
    if project.stars:
        subtitle_bits.append(f"★ {project.stars}")
    if project.url:
        subtitle_bits.append(project.url)

    bullet_text = (
        project.description
        or project.relevance_reason
        or (project.readme_excerpt or "").split("\n", 1)[0][:200]
        or "Personal GitHub project."
    )
    return ResumeSection(
        title=project.name,
        subtitle=" | ".join(subtitle_bits),
        bullets=[ResumeBullet(text=bullet_text)],
    )


def ensure_projects_section(
    resume: TailoredResume, candidate: CandidateProfile
) -> TailoredResume:
    """Mutate ``resume`` so the Projects section has at least one entry when
    the candidate's GitHub data has any projects to draw from.

    Returns the same resume for fluent chaining. No-op when:

    * ``resume.projects`` is already non-empty (the AI delivered something), OR
    * ``candidate.projects`` is empty (no GitHub repos were fetched).

    Logs at INFO when it injects a fallback so the user can grep for it.
    """
    if resume.projects:
        return resume
    fallback = _pick_fallback_project(candidate.projects)
    if fallback is None:
        return resume
    resume.projects = [_project_to_section(fallback)]
    logger.info(
        "ensure_projects_section: injected fallback project '%s' "
        "(stars=%s, relevance=%.2f) - AI returned an empty Projects section.",
        fallback.name,
        fallback.stars,
        fallback.relevance_score or 0.0,
    )
    return resume


def generate_tailored_resume(
    provider: BaseAIProvider,
    job: JobPosting,
    candidate: CandidateProfile,
    answers: AnswersBundle | None = None,
    evidence: Sequence[EvidenceItem] = (),
    output_language: str = "en",
) -> TailoredResume:
    answers = answers or AnswersBundle()
    resume = provider.generate_resume(
        job, candidate, answers, evidence, output_language=output_language
    )
    return ensure_projects_section(resume, candidate)


__all__ = ["generate_tailored_resume", "ensure_projects_section"]
