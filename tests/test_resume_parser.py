"""Tests for resume_parser - especially the HTML CV input path."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.services.resume_parser import ResumeParseError, parse_resume_file


_HTML_CV = """<!doctype html>
<html lang="cs">
<head>
  <meta charset="utf-8">
  <title>Jana Novakova - QA</title>
  <style>body { color: red; } .skill { font-weight: bold; }</style>
  <script>console.log('should never appear in extracted text');</script>
</head>
<body>
  <h1>Jana Novakova</h1>
  <p class="role">Senior QA Engineer</p>
  <h2>Pracovni zkusenosti</h2>
  <ul>
    <li><strong>Senior QA Engineer</strong> - Gen Digital, 2023 - dosud</li>
    <li>Junior QA - Avast Software, 2021 - 2023</li>
  </ul>
  <h2>Tech Stack</h2>
  <p>Python, Playwright, Selenium, pytest, Docker, Jenkins.</p>
</body>
</html>
"""


def test_parse_resume_file_reads_html(tmp_path: Path):
    cv = tmp_path / "cv.html"
    cv.write_text(_HTML_CV, encoding="utf-8")

    text = parse_resume_file(cv)

    assert "Jana Novakova" in text
    assert "Senior QA Engineer" in text
    assert "Playwright" in text
    # Style and script blocks must be stripped.
    assert "color: red" not in text
    assert "console.log" not in text
    # Sections preserve the candidate's text.
    assert "Pracovni zkusenosti" in text


def test_parse_resume_file_reads_htm_extension(tmp_path: Path):
    cv = tmp_path / "cv.htm"
    cv.write_text(_HTML_CV, encoding="utf-8")
    assert "Jana Novakova" in parse_resume_file(cv)


def test_parse_resume_file_rejects_unsupported_extension(tmp_path: Path):
    bad = tmp_path / "cv.xyz"
    bad.write_text("anything", encoding="utf-8")
    with pytest.raises(ResumeParseError):
        parse_resume_file(bad)


def test_parse_resume_file_missing_path_raises(tmp_path: Path):
    with pytest.raises(ResumeParseError):
        parse_resume_file(tmp_path / "does_not_exist.html")


def test_parse_resume_file_html_with_no_text_raises(tmp_path: Path):
    cv = tmp_path / "empty.html"
    cv.write_text(
        "<html><head><style>body{}</style></head><body></body></html>",
        encoding="utf-8",
    )
    with pytest.raises(ResumeParseError):
        parse_resume_file(cv)
