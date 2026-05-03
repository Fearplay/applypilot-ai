"""Application settings loaded from environment / .env files.

The :class:`Settings` dataclass is the single place that reads environment
variables; the rest of the codebase should depend on it instead of calling
``os.getenv`` directly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

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

    raw_provider = os.getenv("AI_PROVIDER", "fake")
    output_dir_raw = os.getenv("APPLYPILOT_OUTPUT_DIR", "outputs")
    output_dir = Path(output_dir_raw)
    if not output_dir.is_absolute():
        output_dir = root / output_dir

    return Settings(
        project_root=root,
        output_dir=output_dir,
        log_level=os.getenv("APPLYPILOT_LOG_LEVEL", "INFO").upper(),
        ai_provider=_normalise_provider(raw_provider),
        ai_provider_raw=raw_provider,
        ai_base_url=os.getenv("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        ai_api_key=os.getenv("AI_API_KEY", "").strip(),
        ai_model=os.getenv("AI_MODEL", "gpt-4o-mini").strip(),
        ai_timeout=_int_env("AI_TIMEOUT", 60),
        ai_temperature=_float_env("AI_TEMPERATURE", 0.2),
        ai_request_log=_bool_env("AI_REQUEST_LOG", True),
        ai_debug_prompts=_bool_env("AI_DEBUG_PROMPTS", False),
        github_token=os.getenv("GITHUB_TOKEN", "").strip(),
    )


__all__ = ["Settings", "ProviderName", "load_settings"]
