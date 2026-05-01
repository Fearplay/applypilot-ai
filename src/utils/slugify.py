"""ASCII-friendly slugifier used for output folder names."""
from __future__ import annotations

import re
import unicodedata

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 60, fallback: str = "untitled") -> str:
    """Produce a filesystem-safe slug from arbitrary text."""
    if not text:
        return fallback
    normalised = unicodedata.normalize("NFKD", text)
    ascii_text = normalised.encode("ascii", errors="ignore").decode("ascii")
    slug = _NON_SLUG.sub("-", ascii_text.lower()).strip("-")
    if not slug:
        return fallback
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or fallback


__all__ = ["slugify"]
