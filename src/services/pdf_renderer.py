"""Render an HTML string to a printable PDF via Playwright.

Used by :func:`src.services.export_service.export_package` to ship a
``{slug}_cv.pdf`` and ``{slug}_cover_letter.pdf`` next to the markdown /
DOCX / HTML artefacts. The HTML we feed in is the same self-contained
styled HTML the ``DocumentsPage`` modern preview tab already shows the
user, so the printed PDF matches what the user sees on screen pixel-for-
pixel (modulo font availability differences between the system browser
and the user's installed fonts).

Design goals mirror ``playwright_renderer.py`` for the SPA fetcher:

* No mandatory ``playwright install`` step. We try the user's existing
  Chrome, then Edge, then Playwright's bundled Chromium / Firefox.
* Lazy import. The ``playwright`` Python package is only imported when
  this module is actually used so the rest of the app boots even if the
  user never installed it.
* Fully headless. No browser window pops up; the user just sees the
  spinner and then the new files on disk.
* Best-effort. Failure raises :class:`PdfRendererUnavailableError` so
  callers can degrade gracefully (skip the PDFs, surface a status hint)
  instead of breaking the whole save action.
"""
from __future__ import annotations

import logging
from contextlib import suppress
from pathlib import Path

logger = logging.getLogger(__name__)


_CHANNEL_PREFERENCES: tuple[tuple[str, str], ...] = (
    ("chromium", "chrome"),
    ("chromium", "msedge"),
    ("chromium", ""),
    ("firefox", ""),
)


class PdfRendererUnavailableError(RuntimeError):
    """Raised when no usable browser is reachable through Playwright.

    Carries an optional ``hint`` the GUI can paste into a status banner
    (e.g. "Install Chrome / Edge or run ``playwright install chromium``"
    so the user knows what to do next).
    """


def is_pdf_renderer_available() -> bool:
    """Return ``True`` when the ``playwright`` Python package is importable.

    Used by callers that want to short-circuit before spinning up a
    background save job. The actual browser launch only happens on the
    real call - this is a cheap probe.
    """
    try:
        import playwright  # noqa: F401  - presence check only
    except ImportError:
        return False
    return True


def render_html_to_pdf(html: str, pdf_path: Path | str) -> None:
    """Render ``html`` to an A4 PDF written at ``pdf_path``.

    The HTML must be a fully self-contained document (inlined ``<style>``
    is the easy way; remote stylesheets / fonts are best-effort because
    we run the page with ``wait_until='networkidle'`` and a short extra
    delay).

    Raises:
        PdfRendererUnavailableError: Playwright is not installed, or
            none of the supported browsers can be launched on this
            machine. Callers should catch this and skip the PDF write.
    """
    try:
        from playwright.sync_api import (  # noqa: PLC0415
            Error as PlaywrightError,
            sync_playwright,
        )
    except ImportError as exc:
        raise PdfRendererUnavailableError(
            "Playwright Python package is not installed. "
            "Run `pip install playwright` and (optionally) "
            "`playwright install chromium` to enable PDF export."
        ) from exc

    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

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
                    "PDF renderer launched via kind=%s channel=%r",
                    kind,
                    channel or "<bundled>",
                )
                break
            except PlaywrightError as exc:
                last_error = exc
                logger.debug(
                    "PDF renderer launch failed for kind=%s channel=%r: %s",
                    kind,
                    channel,
                    exc,
                )
            except Exception as exc:  # pragma: no cover - safety net
                last_error = exc
                logger.debug(
                    "Unexpected error launching kind=%s channel=%r: %s",
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
            raise PdfRendererUnavailableError(hint)

        try:
            context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(20_000)
            page.set_content(html, wait_until="domcontentloaded")
            with suppress(Exception):
                page.wait_for_load_state("networkidle", timeout=8_000)
            # Firefox does not support page.pdf(); fall back to printing
            # via the chromium-only API and let the caller decide.
            if not hasattr(page, "pdf"):
                raise PdfRendererUnavailableError(
                    "Selected browser does not expose a PDF printer. "
                    "Install Chrome / Edge or run `playwright install chromium`."
                )
            try:
                page.pdf(
                    path=str(pdf_path),
                    format="A4",
                    print_background=True,
                    margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                    prefer_css_page_size=True,
                )
            except PlaywrightError as exc:
                # Firefox raises here at runtime; surface as
                # PdfRendererUnavailableError so the caller can degrade.
                raise PdfRendererUnavailableError(
                    f"PDF generation failed in browser={chosen_label}: {exc}"
                ) from exc
            logger.info(
                "PDF renderer wrote %s via browser=%s",
                pdf_path,
                chosen_label,
            )
        finally:
            with suppress(Exception):
                browser.close()


__all__ = [
    "PdfRendererUnavailableError",
    "is_pdf_renderer_available",
    "render_html_to_pdf",
]
