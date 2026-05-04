"""Process-wide AI usage counter the GUI subscribes to.

The :class:`OpenAICompatibleProvider` records every reply via
:func:`record_call`; the status bar widget (see ``MainWindow``) reads the
current totals on each Qt timer tick to render
``AI: 8 calls - 24.3k tokens - ~$0.18 this session``.

Implementation note: kept as a tiny module-level singleton instead of a
class hierarchy because the GUI is single-process and we never need to
attribute spend to multiple users in the same run.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from .pricing import estimate_cost_usd


@dataclass(frozen=True)
class SessionTotals:
    """Snapshot of AI usage since the process started."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


_lock = threading.Lock()
_state = SessionTotals()
_listeners: list[Callable[[SessionTotals], None]] = []


def get_totals() -> SessionTotals:
    """Return the current snapshot. Cheap, lock-protected."""
    with _lock:
        return _state


def record_call(
    model: str, prompt_tokens: int, completion_tokens: int
) -> SessionTotals:
    """Bump the global counters and notify subscribers.

    ``model`` is just used for the per-call cost lookup; the totals stay
    aggregated across models so the user sees ONE number even when their
    pipeline mixes calls (e.g. analyze on gpt-4o-mini, refine on gpt-4o).
    """
    global _state
    cost = estimate_cost_usd(model, prompt_tokens, completion_tokens)
    with _lock:
        _state = SessionTotals(
            calls=_state.calls + 1,
            prompt_tokens=_state.prompt_tokens + max(0, prompt_tokens or 0),
            completion_tokens=_state.completion_tokens
            + max(0, completion_tokens or 0),
            estimated_usd=_state.estimated_usd + cost,
        )
        snapshot = _state
        listeners = list(_listeners)
    for cb in listeners:
        try:
            cb(snapshot)
        except Exception:
            # Listeners must never break the AI request loop.
            pass
    return snapshot


def reset() -> None:
    """Reset all counters to zero. Used in tests."""
    global _state
    with _lock:
        _state = SessionTotals()
        listeners = list(_listeners)
    for cb in listeners:
        try:
            cb(_state)
        except Exception:
            pass


def register_listener(callback: Callable[[SessionTotals], None]) -> None:
    """Subscribe ``callback`` to every counter update."""
    with _lock:
        if callback not in _listeners:
            _listeners.append(callback)


def unregister_listener(callback: Callable[[SessionTotals], None]) -> None:
    with _lock:
        if callback in _listeners:
            _listeners.remove(callback)


__all__ = [
    "SessionTotals",
    "get_totals",
    "record_call",
    "reset",
    "register_listener",
    "unregister_listener",
]
