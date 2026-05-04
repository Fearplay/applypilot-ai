"""Tests for the lightweight i18n helper."""
from __future__ import annotations

import pytest

from src import i18n


@pytest.fixture(autouse=True)
def _reset_language():
    """Restore the runtime language after every test - it is module-global."""
    saved = i18n.get_language()
    yield
    i18n.set_language(saved)


def test_t_returns_english_by_default():
    i18n.set_language("en")
    assert i18n.t("setup.run") == "Run analysis"


def test_t_returns_czech_when_language_is_cs():
    i18n.set_language("cs")
    assert i18n.t("setup.run") == "Spustit analýzu"


def test_t_falls_back_to_english_when_key_missing_in_cs(monkeypatch):
    monkeypatch.setitem(i18n._STRINGS["cs"], "test.key.cs", "")
    # Wipe the Czech entry so it falls through to English.
    i18n._STRINGS["cs"].pop("test.key.cs", None)
    monkeypatch.setitem(i18n._STRINGS["en"], "test.key.cs", "english only")

    i18n.set_language("cs")
    assert i18n.t("test.key.cs") == "english only"


def test_t_falls_back_to_key_when_missing_everywhere():
    i18n.set_language("cs")
    assert i18n.t("non.existent.key") == "non.existent.key"


def test_set_language_updates_runtime_choice():
    i18n.set_language("en")
    assert i18n.get_language() == "en"
    i18n.set_language("cs")
    assert i18n.get_language() == "cs"


def test_set_language_with_unknown_code_falls_back_to_english(caplog):
    i18n.set_language("en")
    i18n.set_language("xx")
    assert i18n.get_language() == "en"


def test_set_language_notifies_listeners():
    called: list[str] = []

    def listener(code: str) -> None:
        called.append(code)

    i18n.set_language("en")
    i18n.register_listener(listener)
    try:
        i18n.set_language("cs")
        assert called == ["cs"]
    finally:
        i18n.unregister_listener(listener)


def test_set_language_does_not_notify_when_already_active():
    called: list[str] = []
    i18n.set_language("en")

    def listener(code: str) -> None:
        called.append(code)

    i18n.register_listener(listener)
    try:
        i18n.set_language("en")
    finally:
        i18n.unregister_listener(listener)
    assert called == []


def test_t_supports_format_placeholders():
    i18n.set_language("en")
    assert i18n.t("status.match_score", score=87) == "Match score: 87 / 100"
    i18n.set_language("cs")
    assert i18n.t("status.match_score", score=87) == "Skóre shody: 87 / 100"


def test_t_returns_text_when_format_key_missing():
    i18n.set_language("en")
    # ``status.match_score`` expects ``score``; missing kwarg returns the raw text.
    raw = i18n.t("status.match_score")
    assert "{score}" in raw


# ---------------------------------------------------------------------------
# Issue 4: UI language is loaded ONLY from the saved preference now.
# The deprecated ``APPLYPILOT_UI_LANGUAGE`` env override has been removed;
# these tests pin the new ordering down so a future refactor cannot quietly
# bring the env override back.
# ---------------------------------------------------------------------------


def test_resolve_ui_language_reads_saved_preference(monkeypatch):
    """A saved 'cs' preference wins over the implicit default."""
    from src import config as config_module
    from src.utils import preferences as prefs_module

    monkeypatch.delenv("APPLYPILOT_UI_LANGUAGE", raising=False)

    def fake_get(key, default=None):
        if key == "ui_language":
            return "cs"
        return default

    monkeypatch.setattr(prefs_module, "get_preference", fake_get)
    assert config_module._resolve_ui_language() == "cs"


def test_resolve_ui_language_ignores_env_override(monkeypatch):
    """Even with the legacy env variable set, only the preference matters."""
    from src import config as config_module
    from src.utils import preferences as prefs_module

    monkeypatch.setenv("APPLYPILOT_UI_LANGUAGE", "cs")

    def fake_get(key, default=None):
        if key == "ui_language":
            return "en"
        return default

    monkeypatch.setattr(prefs_module, "get_preference", fake_get)
    assert config_module._resolve_ui_language() == "en"


def test_resolve_ui_language_defaults_to_english_when_no_preference(monkeypatch):
    """First-time users get a predictable English UI."""
    from src import config as config_module
    from src.utils import preferences as prefs_module

    monkeypatch.delenv("APPLYPILOT_UI_LANGUAGE", raising=False)

    def fake_get(key, default=None):
        return default

    monkeypatch.setattr(prefs_module, "get_preference", fake_get)
    assert config_module._resolve_ui_language() == "en"
