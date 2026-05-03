"""Tiny helpers for cleaning user/job/HTML text before parsing."""
from __future__ import annotations

import re

_WHITESPACE_RE = re.compile(r"[ \t\f\v]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_ENTITY_RE = re.compile(r"&[a-zA-Z]+;|&#\d+;")


# Mapping used by :func:`strip_ai_tells`. Listed once so we keep both the
# regex and any future per-character logic in sync. Order matters only for
# the multi-character ellipsis -> "..." entry (handled separately below).
_AI_TELL_REPLACEMENTS: dict[str, str] = {
    "\u2014": "-",   # em dash
    "\u2013": "-",   # en dash
    "\u2212": "-",   # minus sign (sometimes used as dash by AI)
    "\u2018": "'",   # left single quote
    "\u2019": "'",   # right single quote (also Czech apostrophe in some fonts)
    "\u201A": "'",   # single low-9 quote
    "\u201B": "'",   # single high-reversed-9 quote
    "\u201C": '"',   # left double quote
    "\u201D": '"',   # right double quote
    "\u201E": '"',   # double low-9 quote (Czech opening quote)
    "\u201F": '"',   # double high-reversed-9 quote
    "\u00AB": '"',   # left guillemet
    "\u00BB": '"',   # right guillemet
    "\u2032": "'",   # prime
    "\u2033": '"',   # double prime
    "\u00A0": " ",   # non-breaking space
    "\u202F": " ",   # narrow no-break space
    "\u2009": " ",   # thin space
    "\u200B": "",    # zero-width space (invisible AI artefact)
    "\u200C": "",    # zero-width non-joiner
    "\u200D": "",    # zero-width joiner
    "\uFEFF": "",    # BOM that sometimes leaks into AI output
}

# Character class for the dict above so we can do a single fast pass.
_AI_TELL_CHARS_RE = re.compile(
    "[" + re.escape("".join(_AI_TELL_REPLACEMENTS)) + "]"
)


def normalize_whitespace(text: str) -> str:
    """Collapse repeated horizontal whitespace, normalise line endings."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE_RE.sub(" ", text)
    return _BLANK_LINES_RE.sub("\n\n", text).strip()


def strip_ai_tells(text: str) -> str:
    """Replace the smart punctuation that screams "AI generated".

    Common AI tells we scrub:

    * em-dash (``—``) and en-dash (``–``) -> plain hyphen ``-``
    * curly quotes (``'`` ``'`` ``"`` ``"``) -> straight quotes ``'`` / ``"``
    * Czech-style low-9 quotes (``„`` ``"``) -> straight ``"``
    * unicode ellipsis (``…``) -> three dots ``...``
    * non-breaking and other exotic whitespace -> regular space (or empty
      for zero-width characters)

    Applied to every exported document so even if the model ignores the
    "use plain hyphen" rule in the prompt, the user-facing output stays
    typographically boring and human-looking.
    """
    if not text:
        return text
    # Multi-char ellipsis first - simple replace is fine, no overlap with
    # the single-character class below.
    out = text.replace("\u2026", "...")
    out = _AI_TELL_CHARS_RE.sub(
        lambda m: _AI_TELL_REPLACEMENTS[m.group(0)], out
    )
    return out


def html_to_text(html: str) -> str:
    """Very small HTML -> text helper used as a fallback when trafilatura fails."""
    if not html:
        return ""
    cleaned = _HTML_TAG_RE.sub(" ", html)
    cleaned = _HTML_ENTITY_RE.sub(" ", cleaned)
    return normalize_whitespace(cleaned)


__all__ = ["normalize_whitespace", "html_to_text", "strip_ai_tells"]
