"""Tests for :mod:`src.services.job_url_fetcher`.

Network access is forbidden in the test suite, so we focus on the unit-
testable parts:

1. The JSON / config-blob detector that lets the fetcher fall through to
   the next strategy when a SPA career site (Microsoft, Workday, etc.)
   returns its bootstrap config instead of the human-readable description.
2. The ``JobFetchError`` carries enough context (URL, status, method,
   preview) for the GUI to build a useful error message.
3. The ``use_renderer=True`` path actually invokes the Playwright fallback
   when the static strategies see a config blob, and returns the rendered
   text on success.
"""
from __future__ import annotations

import pytest

from src.services import job_url_fetcher
from src.services.job_url_fetcher import (
    JobFetchError,
    _looks_like_config_dump,
    fetch_job_text,
)


# A trimmed-down copy of the actual response captured from the Microsoft
# Careers SPA (see ``careers-0.md`` in the user's upload). The first line
# is a tracking id followed by a JSON config blob with the trademarked
# ``"themeOptions"`` / ``"customTheme"`` keys we use as fast-path markers.
_MS_CAREERS_BLOB = (
    "654c6aaa25ad4751986d2b4fdcf3da6f-b7d405fc-078f-42fd-99cf-e21de3479349-7421\n"
    '{"themeOptions": {"customTheme": {"varTheme": {'
    '"accordion-body-text-color": "#646464", '
    '"check-box-border-color": "#646464", '
    '"check-box-checked-background-color": "#463668", '
    '"check-box-mark-color": "#ffffff", '
    '"button-secondary-hover-background-color": "#EBE7F3", '
    '"pcsx-jobcard-flag-text-color": "#474748", '
    '"tab-hover-label": "#5c1b86", '
    '"primary-color-60": "#5c1b86", '
    '"primary-color-70": "#5c1b86", '
    '"button-primary-background-color": "#463668", '
    '"button-primary-text-color": "#ffffff"}}}}'
) * 5  # bump it past the heuristic's minimum length


_HUMAN_JOB = """
AI Software Engineer
Czech Republic, Prague
Apply now

Job description
We are building new AI-powered testing capabilities in Visual Studio and
the .NET CLI that help developers write better tests, identify edge
cases, generate test data, and improve test coverage.

Responsibilities
- Research and experiment with emerging AI technologies.
- Design and implement AI-powered tools for automated unit test generation.
- Develop and maintain benchmarking frameworks.

Qualifications
- BS in Computer Science, EE, Computer Engineering or equivalent.
- Experience with AI/ML concepts, specifically LLMs and prompt engineering.
- Demonstrated passion for developer tools and improving developer
  productivity.
- Experience with one or more of: C#, Java, Python.

This position will be open for a minimum of 5 days, with applications
accepted on an ongoing basis until the position is filled.
"""


# ---------------------------------------------------------------------------
# _looks_like_config_dump
# ---------------------------------------------------------------------------

def test_config_dump_detector_flags_microsoft_careers_blob():
    assert _looks_like_config_dump(_MS_CAREERS_BLOB) is True


def test_config_dump_detector_flags_pure_json_payload():
    raw = '{"jobs": [{"title": "Engineer"}, {"title": "QA"}]}'
    assert _looks_like_config_dump(raw * 30) is True


def test_config_dump_detector_passes_a_normal_job_description():
    assert _looks_like_config_dump(_HUMAN_JOB) is False


def test_config_dump_detector_handles_empty_input():
    assert _looks_like_config_dump("") is False
    assert _looks_like_config_dump("   ") is False


def test_config_dump_detector_handles_short_input():
    # Anything below the min-length check is a no-op so we don't false-
    # positive on legitimate one-liner postings.
    assert _looks_like_config_dump("Apply now.") is False


def test_config_dump_detector_uses_tracking_id_heuristic():
    """A page that begins with a SPA tracking id followed by JSON braces
    should be flagged even if the well-known marker strings are not
    present (so we still catch new SPAs)."""
    raw = (
        "654c6aaa25ad4751986d2b4fdcf3da6f-b7d405fc-078f-42fd-99cf-e21de3479349-7421\n"
        '{"unknownConfigKey": {"foo": "bar", "baz": "qux"}}'
    )
    assert _looks_like_config_dump(raw) is True


# ---------------------------------------------------------------------------
# fetch_job_text validation paths
# ---------------------------------------------------------------------------

def test_fetch_job_text_rejects_empty_url():
    with pytest.raises(JobFetchError) as exc:
        fetch_job_text("")
    assert "empty" in str(exc.value).lower()


def test_fetch_job_text_rejects_unsupported_scheme():
    with pytest.raises(JobFetchError) as exc:
        fetch_job_text("ftp://example.com/jobs/123")
    assert "scheme" in str(exc.value).lower()
    assert exc.value.method == "validate"


def test_jobfetcherror_carries_structured_fields():
    err = JobFetchError(
        "Boom",
        url="https://example.com/jobs/1",
        status=404,
        method="requests+bs4",
        preview="<html>Not found</html>",
    )
    assert err.url == "https://example.com/jobs/1"
    assert err.status == 404
    assert err.method == "requests+bs4"
    assert err.preview is not None
    assert "Boom" in str(err)


# ---------------------------------------------------------------------------
# use_renderer integration
#
# The strategy-1 (trafilatura) and strategy-2 (requests + BS4) calls run
# against the real internet, which the test suite forbids. We monkeypatch
# them to return the Microsoft careers config blob, then plug a fake renderer
# in via ``register_renderer`` to assert the escalation path.
# ---------------------------------------------------------------------------


class _FakeResp:
    """Just enough of ``requests.Response`` for the fetcher."""

    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code


def _stub_static_strategies_to_return_blob(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make trafilatura+BS4 deliver the SPA blob so the fetcher escalates."""
    monkeypatch.setattr(job_url_fetcher, "trafilatura", None)
    monkeypatch.setattr(
        job_url_fetcher.requests,
        "get",
        lambda *_a, **_kw: _FakeResp(_MS_CAREERS_BLOB),
    )


def test_default_path_does_not_invoke_playwright(monkeypatch: pytest.MonkeyPatch) -> None:
    """``use_renderer`` is opt-in; the Playwright module must not even be imported.

    Launching a real browser is expensive (3-5 s), so we want every regular
    fetch to skip the Playwright code path entirely. We assert this by
    poisoning the playwright_renderer module - if anything ever imports it
    on the default path, the test fails loudly.
    """
    _stub_static_strategies_to_return_blob(monkeypatch)

    import sys
    import types

    poisoned = types.ModuleType("src.services.playwright_renderer")

    def _boom(*_a: object, **_kw: object) -> object:
        raise AssertionError(
            "playwright_renderer.render_with_system_browser was called on "
            "the default fetch path - it should only run when use_renderer=True."
        )

    poisoned.PlaywrightUnavailableError = type(  # type: ignore[attr-defined]
        "PlaywrightUnavailableError", (RuntimeError,), {}
    )
    poisoned.render_with_system_browser = _boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "src.services.playwright_renderer", poisoned)

    with pytest.raises(JobFetchError):
        fetch_job_text("https://apply.careers.microsoft.com/x")


def test_use_renderer_escalates_to_playwright_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_static_strategies_to_return_blob(monkeypatch)

    rendered_text = (
        "AI Software Engineer\n\n"
        "Czech Republic, Prague\n\n"
        "We are building new AI-powered testing capabilities in Visual "
        "Studio and the .NET CLI that help developers write better tests, "
        "identify edge cases, generate test data, and improve test "
        "coverage.\n\n"
        "Responsibilities\n- Research emerging AI technologies.\n"
        "- Build benchmarking frameworks.\n"
    )

    class _FakeRender:
        text = rendered_text
        browser = "chrome"

    import sys
    import types

    fake_module = types.ModuleType("src.services.playwright_renderer")
    fake_module.PlaywrightUnavailableError = type(  # type: ignore[attr-defined]
        "PlaywrightUnavailableError", (RuntimeError,), {}
    )
    fake_module.render_with_system_browser = (  # type: ignore[attr-defined]
        lambda url, **_kw: _FakeRender()
    )
    monkeypatch.setitem(sys.modules, "src.services.playwright_renderer", fake_module)

    result = fetch_job_text(
        "https://apply.careers.microsoft.com/x",
        use_renderer=True,
    )

    assert result.text.startswith("AI Software Engineer")
    assert result.method == "playwright[chrome]"


def test_use_renderer_surfaces_unavailable_error_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_static_strategies_to_return_blob(monkeypatch)

    import sys
    import types

    class _FakeUnavailable(RuntimeError):
        pass

    def _raises(_url: str, **_kw: object) -> object:
        raise _FakeUnavailable("no system browser available")

    fake_module = types.ModuleType("src.services.playwright_renderer")
    fake_module.PlaywrightUnavailableError = _FakeUnavailable  # type: ignore[attr-defined]
    fake_module.render_with_system_browser = _raises  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "src.services.playwright_renderer", fake_module)

    with pytest.raises(JobFetchError) as exc:
        fetch_job_text(
            "https://apply.careers.microsoft.com/x",
            use_renderer=True,
        )

    assert "no system browser available" in str(exc.value).lower()
    assert exc.value.method == "playwright"
