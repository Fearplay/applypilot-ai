"""Tiny helpers for cleaning user/job/HTML text before parsing."""
from __future__ import annotations

import re

_WHITESPACE_RE = re.compile(r"[ \t\f\v]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_ENTITY_RE = re.compile(r"&[a-zA-Z]+;|&#\d+;")


def normalize_whitespace(text: str) -> str:
    """Collapse repeated horizontal whitespace, normalise line endings."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE_RE.sub(" ", text)
    return _BLANK_LINES_RE.sub("\n\n", text).strip()


def html_to_text(html: str) -> str:
    """Very small HTML -> text helper used as a fallback when trafilatura fails."""
    if not html:
        return ""
    cleaned = _HTML_TAG_RE.sub(" ", html)
    cleaned = _HTML_ENTITY_RE.sub(" ", cleaned)
    return normalize_whitespace(cleaned)


__all__ = ["normalize_whitespace", "html_to_text"]
