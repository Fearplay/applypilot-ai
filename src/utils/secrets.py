"""Cross-platform secret store for the API keys ApplyPilot needs at runtime.

Two backends, in priority order:

1. **OS keyring** via the ``keyring`` package - Windows Credential Manager,
   macOS Keychain, Linux Secret Service / kwallet. Encrypted at rest by
   the OS, never written as plain text.
2. **JSON fallback** - ``~/.applypilot/secrets.json`` chmodded to ``0o600``
   (no-op on Windows). Only used when the keyring backend raises an
   exception (typical on headless CI / minimal Linux desktops without a
   running secret-service daemon).

We **never** write to ``.env`` even when explicit. The user reported that
``.env`` is their hand-curated source of truth and the app must keep its
hands off; the strict guard at the bottom of :func:`_json_path` enforces
that contract.

Public API:

* ``get_secret(name) -> str``
* ``set_secret(name, value) -> None``
* ``delete_secret(name) -> bool``
* ``is_keyring_available() -> bool``
"""
from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

# Service name shown in OS credential vaults so the user can see / revoke
# the entry. Hyphens make the row easier to spot in Windows Credential
# Manager and macOS Keychain Access.
_KEYRING_SERVICE = "ApplyPilot AI"

# Whitelist of secret names the app understands. Anything outside the
# whitelist is rejected so a typo never silently fans out to a new
# keyring row.
KNOWN_SECRETS: frozenset[str] = frozenset({"AI_API_KEY", "GITHUB_TOKEN"})


def _json_path() -> Path:
    """Path to the JSON fallback file. Strict guard: must NEVER end in .env."""
    path = Path.home() / ".applypilot" / "secrets.json"
    # Insurance against a future refactor pointing this at .env by accident.
    # The user explicitly forbade us from touching their .env.
    assert not str(path).lower().endswith(".env"), (
        "secrets.py must never read or write .env"
    )
    return path


def _load_json_store() -> dict[str, str]:
    path = _json_path()
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError) as exc:
        logger.warning("Could not read secrets fallback %s: %s", path, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: str(v) for k, v in data.items() if isinstance(v, str)}


def _save_json_store(store: dict[str, str]) -> None:
    path = _json_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        # 0o600 = owner read/write only. Windows ignores the mode but
        # we set it anyway so the same code path works everywhere.
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            logger.debug("chmod 0o600 not supported on this platform; ignoring")
    except OSError as exc:
        logger.warning("Could not write secrets fallback %s: %s", path, exc)


def _try_keyring() -> object | None:
    """Return the keyring module if available and a backend is reachable.

    Some Linux installs have ``keyring`` available but no secret-service
    daemon, in which case ``get_password`` raises ``KeyringError``. We
    do a one-time read against a sentinel key to detect that.
    """
    try:
        import keyring  # type: ignore[import-not-found]
        from keyring.errors import KeyringError  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        keyring.get_password(_KEYRING_SERVICE, "_probe")
    except KeyringError as exc:
        logger.info(
            "keyring backend unavailable (%s); falling back to JSON store", exc
        )
        return None
    return keyring


def is_keyring_available() -> bool:
    """``True`` when the OS keyring is reachable. Used by the GUI to decide
    whether the 'Delete from keyring' button can claim full coverage."""
    return _try_keyring() is not None


def get_secret(name: str) -> str:
    """Return the secret value for ``name`` or empty string when absent."""
    if name not in KNOWN_SECRETS:
        return ""
    keyring_mod = _try_keyring()
    if keyring_mod is not None:
        try:
            value = keyring_mod.get_password(_KEYRING_SERVICE, name)  # type: ignore[attr-defined]
            if value:
                return value
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("keyring.get_password(%s) failed: %s", name, exc)
    return _load_json_store().get(name, "") or ""


def set_secret(name: str, value: str) -> None:
    """Persist ``value`` under ``name`` in the most secure backend available.

    Empty / whitespace-only values are interpreted as "delete the
    existing entry" so the GUI can wire the same handler to both Save
    and Clear.
    """
    if name not in KNOWN_SECRETS:
        raise ValueError(f"Unknown secret name: {name}")
    cleaned = (value or "").strip()
    if not cleaned:
        delete_secret(name)
        return
    keyring_mod = _try_keyring()
    if keyring_mod is not None:
        try:
            keyring_mod.set_password(_KEYRING_SERVICE, name, cleaned)  # type: ignore[attr-defined]
            # Mirror to JSON store removed once keyring succeeds, so the
            # user's "Delete" button only has to clear keyring on the
            # next call.
            store = _load_json_store()
            if name in store:
                store.pop(name)
                _save_json_store(store)
            return
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "keyring.set_password(%s) failed; falling back to JSON: %s",
                name, exc,
            )
    store = _load_json_store()
    store[name] = cleaned
    _save_json_store(store)


def delete_secret(name: str) -> bool:
    """Wipe ``name`` from BOTH backends. Returns True if anything was removed."""
    if name not in KNOWN_SECRETS:
        return False
    removed = False
    keyring_mod = _try_keyring()
    if keyring_mod is not None:
        try:
            from keyring.errors import PasswordDeleteError  # type: ignore[import-not-found]
        except ImportError:
            PasswordDeleteError = Exception  # type: ignore[assignment]
        try:
            keyring_mod.delete_password(_KEYRING_SERVICE, name)  # type: ignore[attr-defined]
            removed = True
        except PasswordDeleteError:
            # Already absent - that's success too.
            pass
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "keyring.delete_password(%s) failed: %s", name, exc
            )
    store = _load_json_store()
    if name in store:
        store.pop(name)
        _save_json_store(store)
        removed = True
    return removed


__all__ = [
    "KNOWN_SECRETS",
    "get_secret",
    "set_secret",
    "delete_secret",
    "is_keyring_available",
]
