"""Application settings loaded from environment / .env files.

The :class:`Settings` dataclass is the single place that reads environment
variables; the rest of the codebase should depend on it instead of calling
``os.getenv`` directly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv

ProviderName = Literal["fake", "openai_compatible"]

# When the user picks one of these aliases in .env we still route to the
# OpenAI-compatible provider, because they all speak the same protocol.
_OPENAI_COMPATIBLE_ALIASES: frozenset[str] = frozenset(
    {
        "openai",
        "openai_compatible",
        "openai-compatible",
        "openaicompatible",
        "groq",
        "mistral",
        "openrouter",
        "together",
        "deepseek",
        "ollama",
        "lmstudio",
        "lm_studio",
        "anthropic",
        "gemini",
        "google",
    }
)


def _project_root() -> Path:
    """Return the repository root (folder that contains ``app.py``)."""
    return Path(__file__).resolve().parent.parent


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Resolved application settings."""

    project_root: Path
    output_dir: Path
    log_level: str

    ai_provider: ProviderName
    ai_provider_raw: str
    ai_base_url: str
    ai_api_key: str
    ai_model: str
    ai_timeout: int
    ai_temperature: float
    ai_request_log: bool
    ai_debug_prompts: bool
    #: When True, the GUI shows a "Refine costs ~$X - continue?" modal
    #: before every refine_resume call. Defaults to True so a stray double
    #: click never silently doubles the spend; the modal has a
    #: "Don't ask again this session" check the user can untick.
    ai_confirm_refine: bool

    ui_language: str

    github_token: str

    sample_data_dir: Path = field(default_factory=lambda: _project_root() / "sample_data")

    @property
    def has_real_ai_credentials(self) -> bool:
        """True when the user has configured a real AI provider with a key."""
        return self.ai_provider == "openai_compatible" and bool(self.ai_api_key.strip())

    @property
    def is_demo_mode(self) -> bool:
        """True when the running provider will be the FakeAIProvider."""
        return not self.has_real_ai_credentials


def _normalise_provider(raw: str) -> ProviderName:
    value = (raw or "").strip().lower()
    if value in _OPENAI_COMPATIBLE_ALIASES:
        return "openai_compatible"
    return "fake"


def load_settings(env_file: str | os.PathLike[str] | None = None) -> Settings:
    """Load environment variables and return a :class:`Settings` instance.

    The function is safe to call multiple times. ``python-dotenv`` will not
    overwrite values that already exist in the real environment.
    """
    root = _project_root()
    dotenv_path = Path(env_file) if env_file else (root / ".env")
    if dotenv_path.exists():
        load_dotenv(dotenv_path)

    # Non-secret AI defaults can also live in ~/.applypilot/state.json
    # so the in-app Settings dialog persists across restarts without
    # touching .env. Env vars still win to keep CI / power-user overrides
    # working unchanged. Secrets (API key, GitHub token) take a separate
    # keyring path further down.
    pref_provider = _read_pref_safe("ai_provider_raw")
    pref_base_url = _read_pref_safe("ai_base_url")
    pref_model = _read_pref_safe("ai_model")
    pref_confirm_refine = _read_pref_safe("ai_confirm_refine")

    raw_provider = os.getenv("AI_PROVIDER") or pref_provider or "fake"
    output_dir_raw = os.getenv("APPLYPILOT_OUTPUT_DIR", "outputs")
    output_dir = Path(output_dir_raw)
    if not output_dir.is_absolute():
        output_dir = root / output_dir

    # Secrets first: the in-app Settings dialog writes API keys to the
    # OS keyring (or ~/.applypilot/secrets.json fallback). When the same
    # name is also set via env / .env the env wins so CI / power users
    # can still override locally without touching the keyring.
    api_key_from_secrets = _read_secret_safe("AI_API_KEY")
    github_token_from_secrets = _read_secret_safe("GITHUB_TOKEN")
    base_url_default = pref_base_url or "https://api.openai.com/v1"
    model_default = pref_model or "gpt-4o-mini"
    return Settings(
        project_root=root,
        output_dir=output_dir,
        log_level=os.getenv("APPLYPILOT_LOG_LEVEL", "INFO").upper(),
        ai_provider=_normalise_provider(raw_provider),
        ai_provider_raw=raw_provider,
        ai_base_url=(os.getenv("AI_BASE_URL") or base_url_default).rstrip("/"),
        ai_api_key=(os.getenv("AI_API_KEY") or api_key_from_secrets or "").strip(),
        ai_model=(os.getenv("AI_MODEL") or model_default).strip(),
        # 180 s default (was 60 s) so analyze_candidate against a long CV
        # doesn't time out mid-stream and force a billable retry. The
        # provider already short-circuits the json_schema -> json_object
        # fallback on timeouts, but the original request can still be
        # racing the wire when we cancel.
        ai_timeout=_int_env("AI_TIMEOUT", 180),
        ai_temperature=_float_env("AI_TEMPERATURE", 0.2),
        ai_request_log=_bool_env("AI_REQUEST_LOG", True),
        ai_debug_prompts=_bool_env("AI_DEBUG_PROMPTS", False),
        ai_confirm_refine=_bool_env(
            "AI_CONFIRM_REFINE",
            pref_confirm_refine if isinstance(pref_confirm_refine, bool) else True,
        ),
        ui_language=_resolve_ui_language(),
        github_token=(os.getenv("GITHUB_TOKEN") or github_token_from_secrets or "").strip(),
    )


def _read_secret_safe(name: str) -> str:
    """Best-effort secret read; never raises so settings always load."""
    try:
        from .utils.secrets import get_secret  # noqa: PLC0415

        return get_secret(name)
    except Exception:  # pragma: no cover - keyring/JSON lookup must never block startup
        return ""


def _read_pref_safe(name: str) -> Any:
    """Best-effort preference read; never raises so settings always load."""
    try:
        from .utils.preferences import get_preference  # noqa: PLC0415

        return get_preference(name)
    except Exception:  # pragma: no cover - prefs file must never block startup
        return None


def _resolve_ui_language() -> str:
    """Pick the UI language from saved preferences with English as the default.

    The user's menu choice is persisted to ``~/.applypilot/state.json`` via
    :mod:`src.utils.preferences` and is the single source of truth across
    restarts. We deliberately do NOT honour an ``APPLYPILOT_UI_LANGUAGE``
    environment override anymore: keeping the runtime menu choice as the
    sole authority avoids the foot-gun where a stale ``.env`` value silently
    reverts the UI language after every restart.
    """
    try:
        # Imported lazily to avoid pulling utils into a possible bootstrap
        # path that runs before utils/__init__ exists.
        from .utils.preferences import get_preference  # noqa: PLC0415

        stored = get_preference("ui_language")
        if isinstance(stored, str) and stored.strip().lower() in {"en", "cs"}:
            return stored.strip().lower()
    except Exception:  # pragma: no cover - prefs file is optional
        pass

    return "en"


__all__ = ["Settings", "ProviderName", "load_settings"]
