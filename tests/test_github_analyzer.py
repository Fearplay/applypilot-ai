"""Pure-Python tests for github_analyzer helpers (no network calls).

The autouse safety net in conftest.py blocks ``requests.post``; we never
exercise ``fetch_github_projects`` here because it would call ``requests.get``
which is not blocked - tests for the network call live in a separate, opt-in
test file (not yet shipped).
"""
from __future__ import annotations

import pytest

from src.services.github_analyzer import extract_username


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("octocat", "octocat"),
        ("@octocat", "octocat"),
        ("https://github.com/octocat", "octocat"),
        ("https://github.com/octocat/", "octocat"),
        ("http://github.com/Octocat", "Octocat"),
        ("https://www.github.com/octocat?tab=repos", "octocat"),
        ("https://github.com/octocat/some-repo", "octocat"),
        ("HTTPS://GitHub.com/Octocat", "Octocat"),
    ],
)
def test_extract_username_accepts_common_formats(raw: str, expected: str) -> None:
    assert extract_username(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "not a url with spaces",
        "user/with/slash",
    ],
)
def test_extract_username_returns_empty_for_invalid_input(raw: str) -> None:
    assert extract_username(raw) == ""
