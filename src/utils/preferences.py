"""Tiny on-disk store for user preferences that should outlive a single run.

Currently used to persist the chosen UI language so the menu choice is sticky
across restarts even when ``.env`` does not pin ``APPLYPILOT_UI_LANGUAGE``.

The file is JSON, lives at ``~/.applypilot/state.json`` and degrades silently
if it cannot be read or written - the GUI must keep working in either case.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path.home() / ".applypilot"
_DEFAULT_FILE = _DEFAULT_DIR / "state.json"


def _path(file: str | Path | None = None) -> Path:
    return Path(file) if file else _DEFAULT_FILE


def load_preferences(file: str | Path | None = None) -> dict[str, Any]:
    """Return the preferences dict, or an empty dict on error / missing file."""
    p = _path(file)
    if not p.exists():
        return {}
    try:
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError) as exc:
        logger.warning("Could not read %s: %s", p, exc)
        return {}
    return data if isinstance(data, dict) else {}


def save_preferences(prefs: dict[str, Any], file: str | Path | None = None) -> None:
    """Write ``prefs`` atomically, creating the parent directory if needed."""
    p = _path(file)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)
    except OSError as exc:
        logger.warning("Could not write %s: %s", p, exc)


def get_preference(key: str, default: Any = None, file: str | Path | None = None) -> Any:
    return load_preferences(file).get(key, default)


def set_preference(key: str, value: Any, file: str | Path | None = None) -> None:
    prefs = load_preferences(file)
    prefs[key] = value
    save_preferences(prefs, file)


__all__ = [
    "load_preferences",
    "save_preferences",
    "get_preference",
    "set_preference",
]
