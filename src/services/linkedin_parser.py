"""LinkedIn export parser.

LinkedIn lets you export your profile as a PDF or as a TXT-style archive
(``Profile.pdf`` / ``Profile.txt`` inside ``LinkedinDataExport.zip``). For
MVP we accept the same formats as :mod:`resume_parser`.
"""
from __future__ import annotations

from pathlib import Path

from .resume_parser import ResumeParseError, parse_resume_file


def parse_linkedin_export(path: str | Path) -> str:
    """Return the LinkedIn export text. Re-uses the resume parser."""
    return parse_resume_file(path)


__all__ = ["parse_linkedin_export", "ResumeParseError"]
