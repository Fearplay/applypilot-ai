"""Tests for the deterministic CEFR-level edit applied during refine.

The user reported that the AI's ``explanation`` said "I changed German
to B2" but the actual resume still showed A2. The deterministic
:func:`_apply_explicit_language_level_changes` rewrites the entry on
``resume.spoken_languages`` regardless of what the AI did, so the next
render reflects the user's wish.
"""
from __future__ import annotations

from src.models.documents import TailoredResume
from src.services.resume_generator import (
    _apply_explicit_language_level_changes,
    _canonical_language_name,
    _format_language_entry,
)


def _resume(languages: list[str]) -> TailoredResume:
    return TailoredResume(
        name="Test",
        professional_summary="Test.",
        spoken_languages=list(languages),
    )


def test_german_a2_to_b2_in_czech_resume_rewrites_entry():
    """Mirrors the bug-report screenshot: a Czech resume listing
    ``Němčina (A2)`` and the user typing ``"změň němčinu na B2"`` must
    end up with ``Němčina (B2)`` on the resume - not just in the
    explanation note.
    """
    resume = _resume(["Čeština (mateřský)", "Angličtina (C1)", "Němčina (A2)"])
    applied = _apply_explicit_language_level_changes(
        resume, "změň němčinu na B2", output_language="cs"
    )
    assert applied == [("German", "B2")]
    assert "Němčina (B2)" in resume.spoken_languages
    assert "Němčina (A2)" not in resume.spoken_languages


def test_english_phrasing_rewrites_entry():
    resume = _resume(["English (B1)", "Spanish (A2)"])
    applied = _apply_explicit_language_level_changes(
        resume, "Change English to C1, please.", output_language="en"
    )
    assert applied == [("English", "C1")]
    assert "English (C1)" in resume.spoken_languages
    assert "English (B1)" not in resume.spoken_languages


def test_unknown_language_is_ignored():
    """Klingon doesn't map to any canonical name -> no edits made."""
    resume = _resume(["English (C1)"])
    applied = _apply_explicit_language_level_changes(
        resume, "Set Klingon to A1", output_language="en"
    )
    assert applied == []
    assert resume.spoken_languages == ["English (C1)"]


def test_invalid_cefr_is_ignored():
    """``D3`` isn't a real CEFR code -> no edit, no append."""
    resume = _resume(["German (A2)"])
    applied = _apply_explicit_language_level_changes(
        resume, "Set German to D3", output_language="en"
    )
    assert applied == []
    assert resume.spoken_languages == ["German (A2)"]


def test_new_language_is_appended():
    resume = _resume(["English (C1)"])
    applied = _apply_explicit_language_level_changes(
        resume, "Add German B2", output_language="en"
    )
    assert applied == [("German", "B2")]
    assert "German (B2)" in resume.spoken_languages
    assert "English (C1)" in resume.spoken_languages


def test_canonical_name_handles_inflected_czech_forms():
    assert _canonical_language_name("Němčinu") == "German"
    assert _canonical_language_name("němčina") == "German"
    assert _canonical_language_name("nemecky") == "German"


def test_format_uses_localised_name_in_czech():
    assert _format_language_entry("German", "B2", "cs") == "Němčina (B2)"
    assert _format_language_entry("German", "B2", "en") == "German (B2)"
