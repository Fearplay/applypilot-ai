"""Hard guard: a real AI provider must never be created or called in tests.

The autouse ``block_real_ai`` fixture in conftest.py replaces ``requests.post``
with a function that fails. This file adds higher-level checks that exercise
the provider factory and the OpenAI-compatible class without ever talking
to a real endpoint.
"""
from __future__ import annotations

import pytest

from src.ai.fake_provider import FakeAIProvider
from src.ai.openai_compatible_provider import (
    OpenAICompatibleProvider,
    OpenAIProviderError,
)
from src.ai.provider_factory import build_provider
from src.config import load_settings


def test_default_factory_returns_fake(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    provider = build_provider(load_settings())
    assert isinstance(provider, FakeAIProvider)
    assert provider.is_demo


def test_factory_falls_back_when_key_missing(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai_compatible")
    monkeypatch.setenv("AI_API_KEY", "")
    provider = build_provider(load_settings())
    assert isinstance(provider, FakeAIProvider)
    assert "AI_API_KEY" in provider.reason


def test_real_provider_constructor_requires_key(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai_compatible")
    monkeypatch.setenv("AI_API_KEY", "")
    settings = load_settings()
    with pytest.raises(OpenAIProviderError):
        OpenAICompatibleProvider(settings)


def test_real_provider_post_is_blocked_by_safety_net(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai_compatible")
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("AI_MODEL", "test-model")
    settings = load_settings()
    provider = OpenAICompatibleProvider(settings)

    # If anything attempted to hit the network, the autouse safety-net would
    # convert it into an AssertionError, failing this test loudly.
    with pytest.raises(AssertionError, match="forbidden"):
        provider.analyze_job("Junior Python Developer")
