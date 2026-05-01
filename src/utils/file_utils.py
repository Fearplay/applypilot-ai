"""Small filesystem helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

FileKind = Literal["pdf", "docx", "txt", "md", "json", "html", "unknown"]


def detect_file_kind(path: str | Path) -> FileKind:
    """Return a coarse file kind from the extension."""
    ext = Path(path).suffix.lower()
    return {
        ".pdf": "pdf",
        ".docx": "docx",
        ".doc": "docx",
        ".txt": "txt",
        ".md": "md",
        ".json": "json",
        ".html": "html",
        ".htm": "html",
    }.get(ext, "unknown")


def ensure_dir(path: str | Path) -> Path:
    """``mkdir -p`` for the given path (creates parents, idempotent)."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_read_text(path: str | Path, max_bytes: int = 5 * 1024 * 1024) -> str:
    """Read a text file as UTF-8 with replacement and a hard size cap."""
    p = Path(path)
    raw = p.read_bytes()[:max_bytes]
    return raw.decode("utf-8", errors="replace")


__all__ = ["FileKind", "detect_file_kind", "ensure_dir", "safe_read_text"]
