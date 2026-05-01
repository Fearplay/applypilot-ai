"""Fetch the human-readable text of a job posting URL.

Strategy:
    1. ``trafilatura.fetch_url`` + ``trafilatura.extract`` (best for blogs and
       most ATS pages).
    2. Plain ``requests.get`` + ``BeautifulSoup`` text extraction.
    3. Custom renderer registered via :func:`register_renderer` (placeholder
       hook - lets us add Playwright later without touching this module).

If all attempts fail we raise :class:`JobFetchError` so the GUI can prompt
the user to paste the description manually.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

try:  # trafilatura is optional at import-time so unit tests do not need it.
    import trafilatura
except Exception:  # pragma: no cover - extremely unlikely
    trafilatura = None  # type: ignore[assignment]

from ..utils.text_cleaning import normalize_whitespace

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (compatible; ApplyPilotAI/0.1; +https://github.com/Fearplay/applypilot-ai)"
)
_DEFAULT_TIMEOUT = 20

#: Hook for callers (e.g. a future Playwright renderer) to register a fallback.
_renderer: Callable[[str], str] | None = None


def register_renderer(renderer: Callable[[str], str]) -> None:
    """Install a custom renderer used after BS4 fails.

    The renderer takes a URL and returns the page text. If it raises, the
    fetcher gives up and raises :class:`JobFetchError`.
    """
    global _renderer
    _renderer = renderer


class JobFetchError(RuntimeError):
    """Raised when we cannot extract a usable job description from a URL."""


@dataclass(frozen=True)
class FetchResult:
    text: str
    source_url: str
    method: str  # "trafilatura" | "requests+bs4" | "custom_renderer"


def fetch_job_text(url: str, timeout: int = _DEFAULT_TIMEOUT) -> FetchResult:
    """Best-effort job posting text extraction."""
    url = (url or "").strip()
    if not url:
        raise JobFetchError("Job URL is empty.")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise JobFetchError(f"Unsupported URL scheme: {url!r}")

    # 1) trafilatura
    if trafilatura is not None:
        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                extracted = trafilatura.extract(
                    downloaded,
                    include_comments=False,
                    include_tables=True,
                    favor_recall=True,
                )
                if extracted and len(extracted.strip()) > 200:
                    return FetchResult(
                        text=normalize_whitespace(extracted),
                        source_url=url,
                        method="trafilatura",
                    )
        except Exception as exc:  # pragma: no cover - network failure path
            logger.debug("trafilatura failed: %s", exc)

    # 2) requests + BeautifulSoup
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT, "Accept-Language": "en;q=0.9"},
        )
    except requests.RequestException as exc:
        raise JobFetchError(f"Network error: {exc}") from exc

    if resp.status_code >= 400:
        # Some sites still return useful HTML on 403, but if it's redirect-
        # to-login content we give up.
        if resp.status_code in {401, 403, 404, 451}:
            raise JobFetchError(
                f"Job URL returned HTTP {resp.status_code}. "
                "Please paste the description manually."
            )

    soup = BeautifulSoup(resp.text or "", "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    text = normalize_whitespace(text)
    if text and len(text) > 400:
        return FetchResult(
            text=text,
            source_url=url,
            method="requests+bs4",
        )

    # 3) custom renderer (Playwright in the future)
    if _renderer is not None:
        try:
            rendered = _renderer(url)
            if rendered and len(rendered.strip()) > 200:
                return FetchResult(
                    text=normalize_whitespace(rendered),
                    source_url=url,
                    method="custom_renderer",
                )
        except Exception as exc:  # pragma: no cover - depends on user code
            logger.warning("Custom renderer failed: %s", exc)

    raise JobFetchError(
        "Could not extract a usable job description from this URL. "
        "Paste the text manually instead."
    )


__all__ = ["fetch_job_text", "FetchResult", "JobFetchError", "register_renderer"]
