"""Unit tests for :mod:`src.services.playwright_renderer`.

The real Playwright runtime needs a browser binary, which we don't want to
install in CI just for one fallback module. Instead we monkeypatch
``sync_playwright`` so the tests assert behaviour, not real browser launches.

The trim heuristics (:func:`_trim_listing_chrome`,
:func:`_trim_trailing_listing`) get their own pure-function tests below
because they encode some surprisingly load-bearing rules about Microsoft
Careers and similar SPAs.
"""
from __future__ import annotations

import sys
import types
from contextlib import contextmanager

import pytest

from src.services import playwright_renderer
from src.services.playwright_renderer import (
    PlaywrightUnavailableError,
    _trim_listing_chrome,
    _trim_trailing_listing,
    render_with_system_browser,
)


# ---------------------------------------------------------------------------
# Test doubles for the small slice of Playwright we actually call
# ---------------------------------------------------------------------------


class _FakeError(Exception):
    """Stand-in for ``playwright.sync_api.Error``."""


class _FakePage:
    def __init__(self, body_text: str) -> None:
        self._body = body_text
        self.goto_calls: list[str] = []

    def set_default_timeout(self, _ms: int) -> None:
        pass

    def goto(self, url: str, **_kw: object) -> None:
        self.goto_calls.append(url)

    def wait_for_load_state(self, *_a: object, **_kw: object) -> None:
        pass

    def wait_for_timeout(self, _ms: int) -> None:
        pass

    def inner_text(self, _selector: str) -> str:
        return self._body

    def content(self) -> str:  # pragma: no cover - used only when inner_text fails
        return f"<html>{self._body}</html>"


class _FakeContext:
    def __init__(self, body_text: str) -> None:
        self._page = _FakePage(body_text)

    def new_page(self) -> _FakePage:
        return self._page


class _FakeBrowser:
    def __init__(self, body_text: str) -> None:
        self._body = body_text
        self.closed = False

    def new_context(self, **_kw: object) -> _FakeContext:
        return _FakeContext(self._body)

    def close(self) -> None:
        self.closed = True


class _Launcher:
    """Stand-in for ``p.chromium`` / ``p.firefox`` exposing only ``launch``."""

    def __init__(
        self,
        *,
        body_text: str,
        allowed_channels: set[str | None],
    ) -> None:
        self._body = body_text
        self._allowed = allowed_channels
        self.launch_calls: list[str | None] = []

    def launch(self, *, channel: str | None = None, headless: bool = True) -> _FakeBrowser:  # noqa: ARG002
        self.launch_calls.append(channel)
        if channel not in self._allowed and "" not in self._allowed:
            # "" is the canonical "no channel" sentinel - some test scenarios
            # pre-populate it to mean "bundled is OK too".
            raise _FakeError(f"channel {channel!r} not installed")
        if channel is None and None not in self._allowed:
            raise _FakeError("bundled browser missing")
        return _FakeBrowser(self._body)


class _FakePlaywright:
    def __init__(self, chromium: _Launcher, firefox: _Launcher) -> None:
        self.chromium = chromium
        self.firefox = firefox


@contextmanager
def _sync_playwright_factory(chromium: _Launcher, firefox: _Launcher):
    yield _FakePlaywright(chromium, firefox)


def _install_fake_playwright(
    monkeypatch: pytest.MonkeyPatch,
    *,
    chromium_channels: set[str | None],
    firefox_available: bool,
    body_text: str = "AI Software Engineer\n\nLooking for a Python expert.",
) -> tuple[_Launcher, _Launcher]:
    """Wire ``playwright.sync_api`` so the renderer picks up our doubles."""
    chromium = _Launcher(body_text=body_text, allowed_channels=chromium_channels)
    firefox = _Launcher(
        body_text=body_text,
        allowed_channels={None} if firefox_available else set(),
    )

    fake_module = types.ModuleType("playwright.sync_api")
    fake_module.Error = _FakeError  # type: ignore[attr-defined]
    fake_module.sync_playwright = lambda: _sync_playwright_factory(chromium, firefox)  # type: ignore[attr-defined]

    parent = types.ModuleType("playwright")
    monkeypatch.setitem(sys.modules, "playwright", parent)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_module)
    return chromium, firefox


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_render_uses_system_chrome_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    chromium, firefox = _install_fake_playwright(
        monkeypatch,
        chromium_channels={"chrome", "msedge", None},
        firefox_available=True,
        body_text="Renderowany text z prohlizece",
    )

    result = render_with_system_browser("https://example.com/job", wait_after_load_ms=0)

    assert result.text == "Renderowany text z prohlizece"
    assert result.browser == "chrome"
    assert chromium.launch_calls == ["chrome"]
    assert firefox.launch_calls == []


def test_render_falls_back_to_msedge_when_chrome_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chromium, _firefox = _install_fake_playwright(
        monkeypatch,
        chromium_channels={"msedge", None},
        firefox_available=True,
        body_text="Edge rendered body",
    )

    result = render_with_system_browser("https://example.com/job", wait_after_load_ms=0)

    assert result.browser == "msedge"
    assert result.text == "Edge rendered body"
    assert chromium.launch_calls == ["chrome", "msedge"]


def test_render_falls_back_to_firefox_when_no_chromium_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chromium, firefox = _install_fake_playwright(
        monkeypatch,
        chromium_channels=set(),  # no chrome, msedge, or bundled chromium
        firefox_available=True,
        body_text="Firefox rendered body",
    )

    result = render_with_system_browser("https://example.com/job", wait_after_load_ms=0)

    assert result.browser == "firefox"
    assert result.text == "Firefox rendered body"
    assert chromium.launch_calls == ["chrome", "msedge", None]
    assert firefox.launch_calls == [None]


def test_render_raises_when_no_browser_available(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_playwright(
        monkeypatch,
        chromium_channels=set(),
        firefox_available=False,
    )

    with pytest.raises(PlaywrightUnavailableError) as exc:
        render_with_system_browser("https://example.com/job", wait_after_load_ms=0)

    assert "system browser" in str(exc.value).lower()


def test_render_raises_when_playwright_package_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)

    with pytest.raises(PlaywrightUnavailableError) as exc:
        render_with_system_browser("https://example.com/job", wait_after_load_ms=0)

    assert "not installed" in str(exc.value).lower()


def test_is_playwright_installed_reports_truthfully(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    assert playwright_renderer.is_playwright_installed() is True

    monkeypatch.setitem(sys.modules, "playwright", None)
    assert playwright_renderer.is_playwright_installed() is False


# ---------------------------------------------------------------------------
# Trim helpers - exercise the heuristics that keep Microsoft / Workday
# detail pages free of search-listing noise.
# ---------------------------------------------------------------------------


def _ms_listing_block() -> str:
    """Synthetic Microsoft careers SPA body with listing + detail + listing."""
    listing = (
        "Microsoft\nCareers\n18 jobs\nSort: Distance\nTurn on job alerts\n"
        + "\n".join(
            f"Software Engineer {n}\nCzech Republic, Prague, Prague\nPosted {n} days ago"
            for n in range(1, 11)
        )
        + "\n1 of 2\n"
    )
    detail = (
        "AI Software Engineer\n"
        "Czech Republic, Prague, Prague\n"
        "Apply now\n"
        "Add to cart\n"
        "Job description\n"
        "Job number\n200011050\n"
        "Date posted\nApr 23, 2026\n"
        "Overview\n"
        "Artificial intelligence is transforming how we approach testing "
        "and quality assurance. " * 6
        + "\nResponsibilities\n"
        "- Research and experiment with emerging AI technologies.\n"
        "- Design and implement AI-powered tools.\n"
        + "Microsoft is an equal opportunity employer. All qualified "
        "applicants will receive consideration. "
        + "If you need assistance with religious accommodations and/or a "
        "reasonable accommodation due to a disability during the application "
        "process, read more about requesting accommodations.\n"
    )
    trailing_listing = (
        "\n".join(
            f"Backend Engineer {n}\nCzech Republic, Multiple Locations, "
            f"Multiple Locations\nPosted {n} months ago"
            for n in range(1, 9)
        )
        + "\n"
    )
    return listing + detail + trailing_listing


def test_trim_listing_chrome_drops_pre_detail_listing() -> None:
    body = _ms_listing_block()
    trimmed = _trim_listing_chrome(body)

    assert trimmed != body
    # Header text from the listing must be gone.
    assert "Microsoft\nCareers\n18 jobs" not in trimmed
    # Detail headline must be present at (or very near) the start.
    assert trimmed.lstrip().startswith("AI Software Engineer")


def test_trim_listing_chrome_passes_through_short_text() -> None:
    body = "Quick description.\nNo listing here."
    assert _trim_listing_chrome(body) == body


def test_trim_listing_chrome_passes_through_pure_detail_page() -> None:
    body = (
        "AI Software Engineer\n"
        "Apply now\n"
        "Job description\n"
        + "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 60
    )
    # No listing -> returned unchanged (no false positives).
    assert _trim_listing_chrome(body) == body


def test_trim_trailing_listing_drops_followup_listing() -> None:
    body = _ms_listing_block()
    trimmed = _trim_trailing_listing(body)

    assert trimmed != body
    assert "Backend Engineer 1" not in trimmed
    assert trimmed.rstrip().endswith("requesting accommodations.")


def test_trim_trailing_listing_keeps_pure_detail_page() -> None:
    """A clean detail page that mentions 'Posted' once should be untouched."""
    body = (
        "AI Software Engineer\n"
        "Job description\n"
        + "Lorem ipsum dolor sit amet. " * 50
        + "\nMicrosoft is an equal opportunity employer. "
        + "If you need assistance with religious accommodations, "
        "read more about requesting accommodations.\n"
        "Posted by HR. "
    )
    assert _trim_trailing_listing(body) == body


def test_combined_trim_yields_clean_detail_only_block() -> None:
    body = _ms_listing_block()
    trimmed = _trim_trailing_listing(_trim_listing_chrome(body))

    assert "AI Software Engineer" in trimmed
    assert "Software Engineer 1" not in trimmed  # listing prefix gone
    assert "Backend Engineer 1" not in trimmed  # listing suffix gone
