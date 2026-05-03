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
