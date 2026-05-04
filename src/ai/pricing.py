"""Per-model token-cost estimates so the GUI can warn the user about spend.

Numbers are USD per **million** tokens, sourced from the public pricing pages
of each provider (OpenAI, Groq, Mistral, OpenRouter aggregator, DeepSeek,
Anthropic, Google) as of 2026-05. Treat the result as an order-of-magnitude
estimate, not a billing source of truth - the actual provider invoice wins.

The matcher is intentionally permissive: we look up by the model alias the
user typed in Settings (``gpt-4o-mini``, ``llama-3.3-70b-versatile``, ...),
fall back to a substring match against the table, and finally to the
``unknown`` row which costs $0 and renders as ``~$? per call`` in the UI.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    """Token cost in USD per million prompt / completion tokens."""

    input_per_million: float
    output_per_million: float


_UNKNOWN = ModelPricing(0.0, 0.0)

# Lowercase model name (or unique substring) -> pricing.
# Keep the list short and recent - obscure aliases fall through to substring
# matching, which is fine because the user picks from a curated dropdown in
# the new Settings dialog.
_MODEL_PRICING: dict[str, ModelPricing] = {
    # OpenAI
    "gpt-4o-mini": ModelPricing(0.15, 0.60),
    "gpt-4o": ModelPricing(2.50, 10.00),
    "gpt-4.1-mini": ModelPricing(0.40, 1.60),
    "gpt-4.1-nano": ModelPricing(0.10, 0.40),
    "gpt-4.1": ModelPricing(2.00, 8.00),
    "o3-mini": ModelPricing(1.10, 4.40),
    "o4-mini": ModelPricing(1.10, 4.40),
    "gpt-5-mini": ModelPricing(0.25, 2.00),
    "gpt-5.4-mini": ModelPricing(0.25, 2.00),  # treated as 5-mini-class
    "gpt-5": ModelPricing(2.50, 10.00),
    # Anthropic (via OpenAI-compat)
    "claude-3-5-haiku": ModelPricing(0.80, 4.00),
    "claude-3-5-sonnet": ModelPricing(3.00, 15.00),
    "claude-3-7-sonnet": ModelPricing(3.00, 15.00),
    "claude-sonnet-4": ModelPricing(3.00, 15.00),
    "claude-opus-4": ModelPricing(15.00, 75.00),
    # Mistral
    "mistral-small": ModelPricing(0.20, 0.60),
    "mistral-medium": ModelPricing(0.40, 2.00),
    "mistral-large": ModelPricing(2.00, 6.00),
    # DeepSeek
    "deepseek-chat": ModelPricing(0.14, 0.28),
    "deepseek-coder": ModelPricing(0.14, 0.28),
    "deepseek-reasoner": ModelPricing(0.55, 2.19),
    # Groq (typically free tier; bill if exceeded)
    "llama-3.3-70b": ModelPricing(0.59, 0.79),
    "llama-3.1-8b": ModelPricing(0.05, 0.08),
    "llama-3.1-70b": ModelPricing(0.59, 0.79),
    "mixtral-8x7b": ModelPricing(0.24, 0.24),
    # OpenRouter passthrough names (a few common ones)
    "anthropic/claude-3.5-sonnet": ModelPricing(3.00, 15.00),
    "openai/gpt-4o-mini": ModelPricing(0.15, 0.60),
    # Google Gemini (OpenAI-compat endpoint)
    "gemini-1.5-flash": ModelPricing(0.075, 0.30),
    "gemini-1.5-pro": ModelPricing(1.25, 5.00),
    "gemini-2.0-flash": ModelPricing(0.10, 0.40),
    # Local providers always cost $0.
    "ollama": _UNKNOWN,
    "lm-studio": _UNKNOWN,
    "local": _UNKNOWN,
}


def _normalise(model: str) -> str:
    return (model or "").strip().lower()


def lookup_pricing(model: str) -> ModelPricing:
    """Return the best-guess pricing for ``model``, or ``_UNKNOWN``.

    Tries an exact match first, then a substring match against the table
    keys (so ``gpt-4o-mini-2024-07-18`` still resolves to ``gpt-4o-mini``).
    """
    name = _normalise(model)
    if not name:
        return _UNKNOWN
    direct = _MODEL_PRICING.get(name)
    if direct is not None:
        return direct
    # Substring fallback - longest key first so 'gpt-4o-mini' beats 'gpt-4o'.
    for key in sorted(_MODEL_PRICING, key=len, reverse=True):
        if key in name:
            return _MODEL_PRICING[key]
    return _UNKNOWN


def estimate_cost_usd(
    model: str, prompt_tokens: int, completion_tokens: int
) -> float:
    """USD cost estimate; returns ``0.0`` when pricing is unknown."""
    p = lookup_pricing(model)
    if p.input_per_million == 0.0 and p.output_per_million == 0.0:
        return 0.0
    return (
        prompt_tokens * p.input_per_million
        + completion_tokens * p.output_per_million
    ) / 1_000_000.0


__all__ = [
    "ModelPricing",
    "lookup_pricing",
    "estimate_cost_usd",
]
