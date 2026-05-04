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
# Hermetic preferences + secrets
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def isolate_user_state(monkeypatch, tmp_path):
    """Redirect ``~/.applypilot`` to a per-test tmp dir.

    Without this every test that calls ``load_settings`` would inherit
    whatever the developer last clicked in the in-app Settings dialog
    (provider, base URL, model, API key) - a flaky, environment-dependent
    failure. Isolating the prefs file + the secrets fallback keeps the
    suite hermetic.
    """
    from src import config as config_mod
    from src.utils import preferences as prefs_mod
    from src.utils import secrets as secrets_mod

    fake_dir = tmp_path / ".applypilot"
    monkeypatch.setattr(prefs_mod, "_DEFAULT_DIR", fake_dir)
    monkeypatch.setattr(prefs_mod, "_DEFAULT_FILE", fake_dir / "state.json")
    # Redirect the JSON secrets fallback to a per-test path and force the
    # OS keyring lookup to report unavailable. Together this guarantees
    # ``get_secret`` returns "" unless the test wrote to the fake store
    # itself, so no test inherits the developer's real API keys.
    fake_secrets = fake_dir / "secrets.json"
    monkeypatch.setattr(secrets_mod, "_json_path", lambda: fake_secrets)
    monkeypatch.setattr(secrets_mod, "_try_keyring", lambda: None)
    # Also short-circuit ``load_dotenv`` so the developer's local .env
    # (with a real OpenAI key) never leaks into a test that intentionally
    # deletes AI_API_KEY via monkeypatch. Without this the .env values
    # silently win against ``monkeypatch.delenv`` and tests get a real
    # provider instead of the FakeAIProvider they expect.
    monkeypatch.setattr(config_mod, "load_dotenv", lambda *args, **kwargs: False)
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
