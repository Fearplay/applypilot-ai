"""Shared pytest fixtures.

The test suite is hermetic: it never touches the network and never calls a
real AI provider. The :func:`block_real_ai` autouse fixture replaces
``requests.post`` with a function that fails the test loudly if anything
ever tries to POST to a real endpoint.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.ai.fake_provider import FakeAIProvider

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SAMPLES = _REPO_ROOT / "sample_data"


# ---------------------------------------------------------------------------
# Autouse safety net
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def block_real_ai(monkeypatch):
    """Fail any test that tries to make a real HTTP POST.

    Tests that need to exercise the OpenAI-compatible HTTP client must
    monkeypatch ``requests.post`` themselves with a controlled stub.
    """
    import requests

    def _forbidden(*args, **kwargs):
        raise AssertionError(
            "requests.post() was called from a test - this would cost money "
            "and is forbidden. Use FakeAIProvider or monkeypatch a stub."
        )

    monkeypatch.setattr(requests, "post", _forbidden)
    yield


# ---------------------------------------------------------------------------
# Common fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_provider() -> FakeAIProvider:
    return FakeAIProvider(reason="test")


@pytest.fixture
def sample_cv_text() -> str:
    return (_SAMPLES / "sample_cv.txt").read_text(encoding="utf-8")


@pytest.fixture
def sample_linkedin_text() -> str:
    return (_SAMPLES / "sample_linkedin_export.txt").read_text(encoding="utf-8")


@pytest.fixture
def sample_job_text() -> str:
    return (_SAMPLES / "sample_job_description.txt").read_text(encoding="utf-8")


@pytest.fixture
def sample_github_username() -> str:
    return (_SAMPLES / "sample_github_username.txt").read_text(encoding="utf-8").strip()
