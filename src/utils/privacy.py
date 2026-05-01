"""Lightweight redaction helpers for log lines / debug dumps.

These helpers are intentionally conservative: we never want to leak the
candidate's email or phone into shared log files when ``APPLYPILOT_LOG_LEVEL``
is set to DEBUG.
"""
from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"([a-zA-Z0-9._%+-])[a-zA-Z0-9._%+-]*@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(\+?\d[\s\-]?){7,}\d")


def redact_emails(text: str) -> str:
    if not text:
        return text
    return _EMAIL_RE.sub(r"\1***@***", text)


def redact_phones(text: str) -> str:
    if not text:
        return text
    return _PHONE_RE.sub("[redacted-phone]", text)


def redact_pii(text: str) -> str:
    return redact_phones(redact_emails(text))


__all__ = ["redact_emails", "redact_phones", "redact_pii"]
