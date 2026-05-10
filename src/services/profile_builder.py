"""Combine CV / LinkedIn / GitHub inputs into a unified CandidateProfile."""
from __future__ import annotations

import logging
from collections.abc import Sequence

from ..ai.base import BaseAIProvider
from ..models.candidate import CandidateProfile, GitHubProject
from .profile_dedup import dedup_profile

logger = logging.getLogger(__name__)


def build_candidate_profile(
    provider: BaseAIProvider,
    cv_text: str = "",
    linkedin_text: str = "",
    github_username: str | None = None,
    github_projects: Sequence[GitHubProject] = (),
    additional_notes: str = "",
) -> CandidateProfile:
    """Delegate to the AI provider, then run a Python dedup safety net.

    The dedup pass collapses experience / education rows that the AI emitted
    twice because the CV and LinkedIn export described the same fact in
    different languages. It also fills in stable per-entry ids that the
    GUI uses to track which rows the user skipped via discrepancy questions.

    ``additional_notes`` is the free-text the user typed (or pasted from a
    notes file) on the Setup page. It is forwarded verbatim to the provider
    AND restored on the returned profile after dedup, so a quirky model
    that drops the field still ends up with the user's clarifications
    persisted on :attr:`CandidateProfile.additional_notes` for every
    downstream prompt.
    """
    cleaned_notes = (additional_notes or "").strip()
    if not any(
        [
            cv_text.strip(),
            linkedin_text.strip(),
            github_username,
            list(github_projects),
            cleaned_notes,
        ]
    ):
        logger.warning("All candidate inputs were empty - returning a stub profile.")
        return CandidateProfile(
            full_name="Anonymous Candidate",
            summary=(
                "No CV, LinkedIn export or GitHub profile was provided. "
                "Add inputs to get a tailored analysis."
            ),
        )
    profile = provider.analyze_candidate(
        cv_text=cv_text,
        linkedin_text=linkedin_text,
        github_username=github_username,
        github_projects=github_projects,
        additional_notes=cleaned_notes,
    )
    deduped = dedup_profile(profile)
    # Safety net: dedup_profile preserves whatever the provider emitted on
    # ``additional_notes`` (it doesn't touch the field), but we still defend
    # against a model that silently dropped the user's text by restoring
    # the original wording when the post-dedup profile lost it. Stays a no-op
    # when notes were empty.
    if cleaned_notes and not (deduped.additional_notes or "").strip():
        object.__setattr__(deduped, "additional_notes", cleaned_notes)
    return deduped


__all__ = ["build_candidate_profile"]
