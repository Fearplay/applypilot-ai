"""Combine CV / LinkedIn / GitHub inputs into a unified CandidateProfile."""
from __future__ import annotations

import logging
from collections.abc import Sequence

from ..ai.base import BaseAIProvider
from ..models.candidate import CandidateProfile, GitHubProject

logger = logging.getLogger(__name__)


def build_candidate_profile(
    provider: BaseAIProvider,
    cv_text: str = "",
    linkedin_text: str = "",
    github_username: str | None = None,
    github_projects: Sequence[GitHubProject] = (),
) -> CandidateProfile:
    """Delegate to the AI provider, with sensible defaults if everything is empty."""
    if not any([cv_text.strip(), linkedin_text.strip(), github_username, list(github_projects)]):
        logger.warning("All candidate inputs were empty - returning a stub profile.")
        return CandidateProfile(
            full_name="Anonymous Candidate",
            summary=(
                "No CV, LinkedIn export or GitHub username was provided. "
                "Add inputs to get a tailored analysis."
            ),
        )
    return provider.analyze_candidate(
        cv_text=cv_text,
        linkedin_text=linkedin_text,
        github_username=github_username,
        github_projects=github_projects,
    )


__all__ = ["build_candidate_profile"]
