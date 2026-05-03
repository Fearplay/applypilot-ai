"""Unit tests for the text-cleaning helpers, especially `strip_ai_tells`.

The scrubber is what keeps em/en dashes, smart quotes and zero-width
characters from leaking into exported documents - those are the most
visible "this was written by an AI" tells, so we pin every replacement
that ever caused user-visible noise.
"""
from __future__ import annotations

from src.utils.text_cleaning import (
    html_to_text,
    normalize_whitespace,
    strip_ai_tells,
)


def test_strip_ai_tells_replaces_em_and_en_dash_with_plain_hyphen():
    assert strip_ai_tells("a \u2014 b") == "a - b"  # em dash
    assert strip_ai_tells("a \u2013 b") == "a - b"  # en dash
    assert strip_ai_tells("a \u2212 b") == "a - b"  # minus sign


def test_strip_ai_tells_replaces_smart_quotes_with_straight_quotes():
    assert strip_ai_tells("\u201chello\u201d") == '"hello"'
    assert strip_ai_tells("\u2018hello\u2019") == "'hello'"
    # Czech-style low-9 + high-9 quotes used by some Word installs.
    assert strip_ai_tells("\u201elow\u201cup") == '"low"up'


def test_strip_ai_tells_replaces_unicode_ellipsis_with_three_dots():
    assert strip_ai_tells("loading\u2026") == "loading..."


def test_strip_ai_tells_normalises_exotic_whitespace():
    # Non-breaking, narrow no-break, thin space all become a regular space.
    assert strip_ai_tells("a\u00A0b\u202Fc\u2009d") == "a b c d"


def test_strip_ai_tells_drops_zero_width_characters():
    # Zero-width space, non-joiner, joiner and BOM all disappear.
    assert strip_ai_tells("a\u200Bb\u200Cc\u200Dd\uFEFFe") == "abcde"


def test_strip_ai_tells_is_idempotent():
    """Running the scrubber twice must yield the same result as once."""
    text = "Mixed \u2014 quotes \u201chere\u201d \u2026 done."
    once = strip_ai_tells(text)
    twice = strip_ai_tells(once)
    assert once == twice


def test_strip_ai_tells_passes_plain_ascii_through_unchanged():
    text = 'Plain ASCII - "quotes" - 2021-2024 - hello.'
    assert strip_ai_tells(text) == text


def test_strip_ai_tells_handles_empty_input():
    assert strip_ai_tells("") == ""
    assert strip_ai_tells(None) is None  # type: ignore[arg-type]


def test_normalize_whitespace_collapses_horizontal_runs():
    assert normalize_whitespace("a   b\tc") == "a b c"


def test_normalize_whitespace_keeps_double_newlines_but_caps_them():
    assert normalize_whitespace("a\n\n\n\nb") == "a\n\nb"


def test_html_to_text_drops_tags_and_entities():
    assert html_to_text("<p>Hello&nbsp;<b>world</b>!</p>") == "Hello world !"
