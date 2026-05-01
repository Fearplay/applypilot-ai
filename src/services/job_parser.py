"""Turn raw job posting text into a structured :class:`JobPosting`."""
from __future__ import annotations

import logging

from ..ai.base import BaseAIProvider
from ..models.job import JobPosting
from ..utils.text_cleaning import normalize_whitespace

logger = logging.getLogger(__name__)


def parse_job(
    provider: BaseAIProvider,
    raw_text: str,
    source_url: str | None = None,
) -> JobPosting:
    """Clean the input text and ask the AI provider to structure it.

    The provider may be the FakeAIProvider (offline) or the real OpenAI-
    compatible one. Either way, the returned ``raw_text`` field is guaranteed
    to contain the cleaned input so the user can scroll through it later.
    """
    cleaned = normalize_whitespace(raw_text)
    if not cleaned:
        raise ValueError("Job description is empty.")
    if len(cleaned) < 80:
        logger.warning(
            "Job text is very short (%d chars) - parsing quality will suffer.",
            len(cleaned),
        )
    posting = provider.analyze_job(cleaned, source_url=source_url)
    if not posting.raw_text:
        # Some providers ignore the field; ensure it is populated for the UI.
        object.__setattr__(posting, "raw_text", cleaned)
    if source_url and not posting.source_url:
        object.__setattr__(posting, "source_url", source_url)
    return posting


__all__ = ["parse_job"]
