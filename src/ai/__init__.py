"""AI provider abstraction.

Public API::

    from src.ai import build_provider, BaseAIProvider, FakeAIProvider
"""
from __future__ import annotations

from .base import BaseAIProvider
from .fake_provider import FakeAIProvider
from .provider_factory import build_provider
from .role_detector import detect_role_type

__all__ = [
    "BaseAIProvider",
    "FakeAIProvider",
    "build_provider",
    "detect_role_type",
]
