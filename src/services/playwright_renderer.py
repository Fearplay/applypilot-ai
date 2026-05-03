"""Render SPA career pages using the user's system browser via Playwright.

Many large career sites (Microsoft Careers, Workday, Greenhouse, some LinkedIn
job pages) ship the job description as data injected by JavaScript at runtime,
so plain HTTP fetches return a useless config blob. To handle these we drive a
real browser and read the rendered DOM.

Design goals
------------

1. **No mandatory ``playwright install`` step.** We start by asking Playwright
   to drive the user's existing Chrome / Edge installation through its
   ``channel="chrome"`` / ``channel="msedge"`` mechanism. Edge ships with
   Windows 10/11, so most Windows users get this for free. If neither is
   present we fall back to Playwright's bundled Chromium and Firefox (which
   require ``playwright install`` once), and finally raise a clear error so
   the GUI can show the manual-paste fallback.
2. **Fully headless / silent.** No browser window pops up; the user just
   sees the spinner and then either the parsed text or a fallback dialog.
3. **Lazy import.** The Playwright dependency is only touched when this
   module is actually called, so the rest of the app boots even if the user
   skipped ``pip install playwright``.
4. **Trim navigation chrome.** When the rendered page combines a search
   listing and a detail panel (Microsoft Careers does this), we look for
   classic detail-page markers ("Apply now", "Job description", "Job number")
   that appear *after* a "X jobs" listing header and trim everything before
   them. Saves the AI from chewing on the search filters / job tiles.
"""
from __future__ import annotations

import logging
import re
from contextlib import suppress
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# Channels are tried in this order. The first two reuse a system installation
# (no extra disk usage). ``chromium`` and ``firefox`` reach into Playwright's
# own browser binaries, which only exist if the user ran ``playwright install``.
_CHANNEL_PREFERENCES: tuple[tuple[str, str], ...] = (
    ("chromium", "chrome"),
    ("chromium", "msedge"),
    ("chromium", ""),  # Playwright-bundled Chromium - needs `playwright install`.
    ("firefox", ""),  # Playwright-bundled Firefox - needs `playwright install firefox`.
)


class PlaywrightUnavailableError(RuntimeError):
    """Raised when no usable browser is reachable through Playwright."""


@dataclass(frozen=True)
class RenderResult:
    """Outcome of a successful render call."""

    text: str
    browser: str  # "chrome" | "msedge" | "chromium" | "firefox"


def is_playwright_installed() -> bool:
    """Return True if the ``playwright`` Python package is importable.

    Used by the GUI to decide whether to even try the renderer; importing the
    package is not free, so the caller can short-circuit when it's missing.
    """
    try:
        import playwright  # noqa: F401  - presence check only
    except ImportError:
        return False
    return True


#: Selectors known to wrap a job description on common ATSes. The renderer
#: tries each one with a short timeout; the first hit wins, otherwise we
#: fall back to ``body`` text (which is also good enough most of the time).
_DESCRIPTION_SELECTORS: tuple[str, ...] = (
    # Microsoft Careers - the modal wraps the description in a dialog.
    "[role='dialog'] article",
    "[role='dialog']",
    # Workday
    "[data-automation-id='jobPostingDescription']",
    # Greenhouse
    "#content article",
    "#app_body",
    # Generic ATS markup
    "main article",
    "article",
    "main",
)


#: Strong "this is where the detail begins" signals. Microsoft Careers
#: prints "1 of 2" between the listing and the detail panel; Workday and
#: Greenhouse do not, but they don't render a listing either, so missing
#: this match just means we keep the full body.
_DETAIL_BOUNDARY_RE = re.compile(
    r"\n\s*(?:\d+\s+of\s+\d+|Page\s+\d+\s+of\s+\d+)\s*\n",
    re.IGNORECASE,
)

#: Secondary fallback patterns. These appear inside a job detail almost
#: universally on the major ATSes; we use them to pinpoint the start of
#: the description when the boundary marker is missing.
_DETAIL_START_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\n\s*Job description\s*\n", re.IGNORECASE),
    re.compile(r"\n\s*Job number\s*\n", re.IGNORECASE),
    re.compile(r"\n\s*Date posted\s*\n", re.IGNORECASE),
    re.compile(r"\n\s*Overview\s*\n", re.IGNORECASE),
)
_LIST_HEADER_RE = re.compile(r"\n\s*\d+\s+jobs?\s*\n", re.IGNORECASE)

#: Strings that almost always sit at the *end* of an ATS detail page.
#: When we see one in a body that also has a trailing job listing, we trim
#: the listing to keep the user-facing description tight.
_DETAIL_END_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"read more about requesting accommodations\.?",
        re.IGNORECASE,
    ),
    re.compile(
        r"applications accepted on an ongoing basis until the position is filled\.?",
        re.IGNORECASE,
    ),
    re.compile(r"equal opportunity employer\.?", re.IGNORECASE),
)


def _trim_trailing_listing(text: str) -> str:
    """Drop a trailing job-listing block, when we can see the detail ended.

    Microsoft Careers, when accessed at a `?pid=...` URL, renders the
    detail panel followed by *more* job tiles ("page 2"). Once the detail
    has obviously ended (signalled by one of the boilerplate footer
    strings), everything after the next paragraph break belongs to the
    listing and is just noise. We trim it conservatively so simpler ATS
    pages that don't repeat the listing are unaffected.
    """
    if not text or len(text) < 1500:
        return text

    end_marker_pos = -1
    for pattern in _DETAIL_END_PATTERNS:
        for match in pattern.finditer(text):
            end_marker_pos = max(end_marker_pos, match.end())

    if end_marker_pos < 0:
        return text

    tail = text[end_marker_pos:]
    # If the tail still contains many "Posted ... ago" snippets, it's the
    # listing - drop it. A single "Posted" inside the detail isn't enough
    # to trigger the trim (some descriptions reference earlier job posts).
    posted_count = len(re.findall(r"\bPosted\b", tail, flags=re.IGNORECASE))
    if posted_count < 3:
        return text

    return text[:end_marker_pos].rstrip()


def _trim_listing_chrome(text: str) -> str:
    """Drop search-results chrome from rendered text, if a detail panel exists.

    Microsoft Careers renders both the job list *and* the per-job detail
    inside the body when you visit a `?pid=...` URL. To save the AI from
    parsing through 1.5 KB of filter + tile text, we look for two signals
    that indicate the detail panel begins:

    1. A `"1 of N"` / `"Page X of Y"` pagination boundary - the strongest
       signal because Microsoft prints exactly that between the listing
       and the detail.
    2. Otherwise, the first occurrence of a recognisable detail heading
       ("Job description", "Job number", "Date posted", "Overview") that
       appears *after* a `"X jobs"` listing header.

    The function is purposefully conservative: if neither signal is found
    (i.e. this is a regular job-detail page already), we return *text*
    unchanged.
    """
    if not text or len(text) < 1500:
        return text

    boundary = _DETAIL_BOUNDARY_RE.search(text)
    if boundary is not None:
        trimmed = text[boundary.end():].lstrip()
        if len(trimmed) >= 400:
            return trimmed

    list_marker = _LIST_HEADER_RE.search(text)
    if list_marker is None:
        return text
    list_end = list_marker.end()

    earliest_detail: int | None = None
    for pattern in _DETAIL_START_PATTERNS:
        match = pattern.search(text, list_end)
        if match is None:
            continue
        if earliest_detail is None or match.start() < earliest_detail:
            earliest_detail = match.start()

    if earliest_detail is None:
        return text

    safe_back = max(list_end, earliest_detail - 200)
    trimmed = text[safe_back:].lstrip()
    if len(trimmed) < 400:
        return text  # Don't trim if it leaves us with too little content.
    return trimmed


def render_with_system_browser(
    url: str,
    *,
    timeout_ms: int = 25_000,
    wait_after_load_ms: int = 4_000,
) -> RenderResult:
    """Open *url* in a headless system browser and return its visible text.

    Args:
        url: Absolute http(s) URL to render.
        timeout_ms: Per-navigation timeout. SPA career sites can be slow on
            first load; 25s is a reasonable middle ground.
        wait_after_load_ms: Extra wait after ``networkidle`` to let
            ``DOMContentLoaded``-after-fetch frameworks (Workday, MS Careers)
            paint the description. 4s lets the Microsoft Careers modal
            finish populating - empirically anything below ~3s only catches
            the search-results list.

    Raises:
        PlaywrightUnavailableError: Playwright is not installed, or none of
            the supported browsers can be launched on this machine.
        RuntimeError: An unexpected error occurred while driving the browser.
    """
    try:
        from playwright.sync_api import (  # noqa: PLC0415
            Error as PlaywrightError,
            sync_playwright,
        )
    except ImportError as exc:
        raise PlaywrightUnavailableError(
            "Playwright Python package is not installed. "
            "Run `pip install playwright` to enable SPA rendering."
        ) from exc

    last_error: Exception | None = None

    with sync_playwright() as p:
        browser = None
        chosen_label = ""
        for kind, channel in _CHANNEL_PREFERENCES:
            launcher = getattr(p, kind, None)
            if launcher is None:
                continue
            try:
                if channel:
                    browser = launcher.launch(channel=channel, headless=True)
                    chosen_label = channel
                else:
                    browser = launcher.launch(headless=True)
                    chosen_label = kind
                logger.info(
                    "Playwright launched via kind=%s channel=%r", kind, channel or "<bundled>"
                )
                break
            except PlaywrightError as exc:
                last_error = exc
                logger.debug(
                    "Playwright launch failed for kind=%s channel=%r: %s",
                    kind,
                    channel,
                    exc,
                )
            except Exception as exc:  # pragma: no cover - safety net
                last_error = exc
                logger.debug(
                    "Unexpected error while launching kind=%s channel=%r: %s",
                    kind,
                    channel,
                    exc,
                )

        if browser is None:
            hint = (
                "Could not launch any system browser through Playwright. "
                "Install Google Chrome or Microsoft Edge (recommended), or "
                "run `playwright install chromium` to get a bundled browser."
            )
            if last_error is not None:
                hint = f"{hint} Last error: {last_error}"
            raise PlaywrightUnavailableError(hint)

        try:
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            with suppress(Exception):
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
            if wait_after_load_ms > 0:
                page.wait_for_timeout(wait_after_load_ms)

            text = ""
            for selector in _DESCRIPTION_SELECTORS:
                with suppress(Exception):
                    handle = page.query_selector(selector)
                    if handle is None:
                        continue
                    candidate = (handle.inner_text() or "").strip()
                    if len(candidate) > 600:
                        # We accept the first selector that yielded a chunk
                        # bigger than the typical SPA chrome (header, nav,
                        # filter panel). Going below ~600 chars risks
                        # picking up sidebar widgets.
                        text = candidate
                        logger.info(
                            "Playwright extracted description via selector %r (%d chars)",
                            selector,
                            len(candidate),
                        )
                        break
            if not text:
                with suppress(Exception):
                    text = page.inner_text("body") or ""
            if not text:
                with suppress(Exception):
                    text = page.content() or ""
            text = _trim_listing_chrome(text)
            text = _trim_trailing_listing(text)
            return RenderResult(text=text, browser=chosen_label)
        finally:
            with suppress(Exception):
                browser.close()


__all__ = [
    "PlaywrightUnavailableError",
    "RenderResult",
    "is_playwright_installed",
    "render_with_system_browser",
]
