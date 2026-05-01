"""Build the right :class:`BaseAIProvider` from :class:`Settings`.

The factory always returns a working provider:

* If the user set ``AI_PROVIDER=openai_compatible`` (or any compatible alias)
  AND provided ``AI_API_KEY``, we try to construct
  :class:`OpenAICompatibleProvider`. If that raises (bad URL, missing key,
  etc.) we log the reason and fall back to :class:`FakeAIProvider`.
* Otherwise we return :class:`FakeAIProvider` with a clear ``reason`` string
  the GUI can show in its demo-mode banner.
"""
from __future__ import annotations

import logging

from ..config import Settings
from .base import BaseAIProvider
from .fake_provider import FakeAIProvider

logger = logging.getLogger(__name__)


def build_provider(settings: Settings) -> BaseAIProvider:
    if settings.ai_provider == "fake":
        return FakeAIProvider(reason="AI_PROVIDER=fake (default)")

    if not settings.ai_api_key:
        return FakeAIProvider(
            reason="AI_API_KEY is empty - falling back to demo provider."
        )

    try:
        # Local import keeps tests free of the requests dependency at module
        # load time (still required transitively for installs).
        from .openai_compatible_provider import (
            OpenAICompatibleProvider,
            OpenAIProviderError,
        )

        provider = OpenAICompatibleProvider(settings)
        logger.info(
            "Real AI provider initialised: base_url=%s model=%s",
            settings.ai_base_url,
            settings.ai_model,
        )
        return provider
    except OpenAIProviderError as exc:
        logger.warning("Real AI provider failed to init, falling back: %s", exc)
        return FakeAIProvider(reason=f"Real provider init failed: {exc}")
    except Exception as exc:  # pragma: no cover - defensive catch-all
        logger.exception("Unexpected error initialising real provider.")
        return FakeAIProvider(reason=f"Unexpected init error: {exc}")


__all__ = ["build_provider"]
