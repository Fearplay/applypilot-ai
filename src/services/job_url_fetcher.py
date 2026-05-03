"""Fetch the human-readable text of a job posting URL.

Strategy:
    1. ``trafilatura.fetch_url`` + ``trafilatura.extract`` (best for blogs and
       most ATS pages).
    2. Plain ``requests.get`` + ``BeautifulSoup`` text extraction.
    3. Optional Playwright system-browser render (only when ``use_renderer``
       is True, e.g. after the user clicks the *Wrong content* button). This
       runs Chrome / Edge / Firefox in headless mode to obtain the rendered
       DOM for SPA career sites.
    4. Custom renderer registered via :func:`register_renderer` (escape hatch
       for callers that want to plug in a different browser/automation stack).

Each strategy's output is also screened by :func:`_looks_like_config_dump`,
which rejects pages whose body is dominated by JSON / config blobs (Microsoft
Careers, Workday, some Greenhouse landings) - those pages need a real browser
to render the description, so we treat them as "fetch failed" and let the
caller decide what to do (retry with desktop UA, escalate to renderer, ask
the user to paste).

If all attempts fail we raise :class:`JobFetchError` so the GUI can prompt
the user to paste the description manually.
"""
from __future__ import annotations

import logging
import re
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

_BOT_USER_AGENT = (
    "Mozilla/5.0 (compatible; ApplyPilotAI/0.1; +https://github.com/Fearplay/applypilot-ai)"
)
# Sent when the caller passes ``force_desktop_ua=True``. SPA career sites
# (Microsoft, Workday) frequently serve the bootstrap JSON to anything that
# looks bot-y; pretending to be desktop Chrome gets us a step closer to the
# real HTML in some cases.
_DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
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
    """Raised when we cannot extract a usable job description from a URL.

    The exception carries structured fields (``url``, ``status``, ``method``,
    ``preview``) so the GUI can render a precise error message and decide
    whether the *Wrong content* fallback should be offered.
    """

    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        status: int | None = None,
        method: str | None = None,
        preview: str | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.status = status
        self.method = method
        self.preview = preview


@dataclass(frozen=True)
class FetchResult:
    text: str
    source_url: str
    method: str  # "trafilatura" | "requests+bs4" | "playwright" | "custom_renderer"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Common SPA bootstrap blobs always hit one or more of these markers very early
# in the response. We use them as a fast signal alongside the structural
# heuristic in :func:`_looks_like_config_dump`.
_CONFIG_BLOB_MARKERS = (
    '"themeOptions"',
    '"customTheme"',
    '"varTheme"',
    '"window.__INITIAL_STATE__"',
    'window.__INITIAL_STATE__',
    '"runtimeConfig"',
    '"NEXT_DATA"',
    '"__NEXT_DATA__"',
    '"phApp"',  # Workday bootstrap
    '"PCS"',  # Microsoft careers bootstrap
)

_TAG_RE = re.compile(r"<[a-zA-Z/!][^>]*>")
_BRACE_OR_QUOTE_RE = re.compile(r"[{}\[\]\":,]")
_TRACKING_ID_RE = re.compile(
    r"^[0-9a-f]{8,}-[0-9a-f]{4,}-[0-9a-f]{4,}-[0-9a-f]{4,}-[0-9a-f]{4,}",
    re.IGNORECASE,
)


def _looks_like_config_dump(text: str) -> bool:
    """Return True if *text* is dominated by JSON / config-blob noise.

    Used after each extraction strategy. A True result means: drop the result
    and try the next strategy (or surface a clearer JobFetchError).

    The heuristic combines three cheap signals so a normal HTML extraction is
    never mis-classified:

    1. Pages that begin with a SPA tracking id followed by ``{"themeOptions":``
       (Microsoft Careers, captured in ``careers-0.md``).
    2. Direct presence of any well-known bootstrap marker.
    3. Structural domination: more than ~70 % of the meaningful characters
       are JSON braces / quotes / colons, with negligible HTML tag density.
    """
    if not text:
        return False

    body = text.strip()
    if len(body) < 80:
        return False

    # Heuristic 1: tracking-id + JSON object start (very targeted, cheap).
    head = body[:600]
    first_line, _, _ = head.partition("\n")
    if _TRACKING_ID_RE.match(first_line.strip()) and "{" in head and ":" in head:
        return True

    # Heuristic 2: bootstrap marker in the first ~4 KB.
    head_for_markers = body[:4000]
    if any(marker in head_for_markers for marker in _CONFIG_BLOB_MARKERS):
        # Marker alone is suspicious; require the brace ratio below to be
        # noticeable so we don't reject HTML pages that happen to embed a tiny
        # snippet of config in a <script> tag.
        sample = body[:6000]
        brace_ratio = len(_BRACE_OR_QUOTE_RE.findall(sample)) / max(1, len(sample))
        if brace_ratio >= 0.08:
            return True

    # Heuristic 3: structural - lots of JSON-ish characters, few HTML tags,
    # very low whitespace ratio (raw JSON blobs tend to be one long line).
    sample = body[:8000]
    json_chars = len(_BRACE_OR_QUOTE_RE.findall(sample))
    tag_chars = len(_TAG_RE.findall(sample))
    sample_len = len(sample)
    json_ratio = json_chars / max(1, sample_len)
    if json_ratio >= 0.18 and tag_chars <= 5:
        return True

    return False


def _build_preview(text: str | None) -> str:
    if not text:
        return ""
    snippet = text.strip().replace("\r", " ").replace("\n", " ")
    snippet = re.sub(r"\s+", " ", snippet)
    return snippet[:120]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_job_text(
    url: str,
    timeout: int = _DEFAULT_TIMEOUT,
    *,
    force_desktop_ua: bool = False,
    use_renderer: bool = False,
) -> FetchResult:
    """Best-effort job posting text extraction.

    Args:
        url: Absolute http(s) URL of the job posting.
        timeout: Per-request timeout in seconds.
        force_desktop_ua: If True, the requests fallback uses a desktop
            Chrome User-Agent and stricter ``Accept`` headers. Some SPA career
            sites (Microsoft, Workday) only serve real HTML to UAs that look
            like a browser. The default is False so the bot-friendly UA stays
            the norm and we don't suddenly look spammy on simpler ATS pages.
        use_renderer: If True, the fetcher will escalate to a Playwright-based
            system-browser render after the static strategies fail or return
            a config blob. Off by default because launching a headless Chrome
            is slow (~3-5 s) and most pages do not need it; the GUI flips it
            on when the user clicks *Wrong content*.
    """
    url = (url or "").strip()
    if not url:
        raise JobFetchError("Job URL is empty.", url=url, method="validate")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise JobFetchError(
            f"Unsupported URL scheme: {url!r}",
            url=url,
            method="validate",
        )

    last_status: int | None = None
    last_preview: str = ""
    last_method: str = "trafilatura"
    rejection_reason: str = "extraction returned too little text"

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
                    cleaned = normalize_whitespace(extracted)
                    if _looks_like_config_dump(cleaned):
                        last_method = "trafilatura"
                        last_preview = _build_preview(cleaned)
                        rejection_reason = (
                            "page returned a JSON / config blob instead of a description"
                        )
                        logger.debug(
                            "trafilatura returned config-looking content for %s", url
                        )
                    else:
                        return FetchResult(
                            text=cleaned,
                            source_url=url,
                            method="trafilatura",
                        )
                elif extracted:
                    last_preview = _build_preview(extracted)
                    last_method = "trafilatura"
        except Exception as exc:  # pragma: no cover - network failure path
            logger.debug("trafilatura failed: %s", exc)
            last_method = "trafilatura"

    # 2) requests + BeautifulSoup
    try:
        ua = _DESKTOP_USER_AGENT if force_desktop_ua else _BOT_USER_AGENT
        headers = {"User-Agent": ua}
        if force_desktop_ua:
            headers["Accept"] = (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            )
            headers["Accept-Language"] = "en-US,en;q=0.9"
        else:
            headers["Accept-Language"] = "en;q=0.9"
        resp = requests.get(url, timeout=timeout, headers=headers)
    except requests.RequestException as exc:
        raise JobFetchError(
            f"Network error while fetching {url}: {exc}",
            url=url,
            method="requests+bs4",
        ) from exc

    last_status = resp.status_code

    if resp.status_code >= 400:
        if resp.status_code in {401, 403, 404, 451}:
            raise JobFetchError(
                f"Job URL returned HTTP {resp.status_code}. "
                "The site may require login or block automated fetches. "
                "Open the URL in your browser and paste the description below.",
                url=url,
                status=resp.status_code,
                method="requests+bs4",
                preview=_build_preview(resp.text),
            )

    soup = BeautifulSoup(resp.text or "", "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    text = normalize_whitespace(text)
    if text and len(text) > 400:
        if _looks_like_config_dump(text):
            last_method = "requests+bs4"
            last_preview = _build_preview(text)
            rejection_reason = (
                "page returned a JSON / config blob instead of a description"
            )
            logger.debug("requests+bs4 returned config-looking content for %s", url)
        else:
            return FetchResult(
                text=text,
                source_url=url,
                method="requests+bs4",
            )
    elif text:
        last_method = "requests+bs4"
        last_preview = _build_preview(text)

    # 3) Playwright system-browser render (opt-in via use_renderer=True).
    if use_renderer:
        try:
            from .playwright_renderer import (  # noqa: PLC0415 - lazy import
                PlaywrightUnavailableError,
                render_with_system_browser,
            )
        except Exception as exc:  # pragma: no cover - importing renderer module
            logger.warning("Playwright renderer module unavailable: %s", exc)
        else:
            try:
                rendered = render_with_system_browser(url, timeout_ms=timeout * 1000)
                if rendered.text and len(rendered.text.strip()) > 200:
                    cleaned = normalize_whitespace(rendered.text)
                    if not _looks_like_config_dump(cleaned):
                        return FetchResult(
                            text=cleaned,
                            source_url=url,
                            method=f"playwright[{rendered.browser}]",
                        )
                    last_method = f"playwright[{rendered.browser}]"
                    last_preview = _build_preview(cleaned)
                    rejection_reason = (
                        "the rendered page still looked like a JSON / config blob"
                    )
                else:
                    last_method = f"playwright[{rendered.browser}]"
                    last_preview = _build_preview(rendered.text)
                    rejection_reason = "rendered page was too short to be a description"
            except PlaywrightUnavailableError as exc:
                logger.info("Playwright renderer unavailable: %s", exc)
                last_method = "playwright"
                rejection_reason = (
                    "no system browser available for SPA rendering "
                    "(install Chrome/Edge or run `playwright install chromium`)"
                )
            except Exception as exc:  # pragma: no cover - real browser failures
                logger.warning("Playwright renderer raised: %s", exc)
                last_method = "playwright"
                rejection_reason = f"renderer crashed: {exc}"

    # 4) custom renderer (escape hatch for tests / alternate stacks)
    if _renderer is not None:
        try:
            rendered = _renderer(url)
            if rendered and len(rendered.strip()) > 200:
                cleaned = normalize_whitespace(rendered)
                if not _looks_like_config_dump(cleaned):
                    return FetchResult(
                        text=cleaned,
                        source_url=url,
                        method="custom_renderer",
                    )
                last_method = "custom_renderer"
                last_preview = _build_preview(cleaned)
                rejection_reason = (
                    "renderer returned a JSON / config blob instead of a description"
                )
        except Exception as exc:  # pragma: no cover - depends on user code
            logger.warning("Custom renderer failed: %s", exc)
            last_method = "custom_renderer"

    detail_parts = [
        f"Could not extract a usable job description from {url}.",
        f"Last attempt: {last_method}",
    ]
    if last_status is not None:
        detail_parts[-1] += f" (HTTP {last_status})"
    detail_parts[-1] += f" - {rejection_reason}."
    if last_preview:
        detail_parts.append(f"First chars: {last_preview!r}")
    detail_parts.append("Open the URL in your browser and paste the description below.")
    raise JobFetchError(
        " ".join(detail_parts),
        url=url,
        status=last_status,
        method=last_method,
        preview=last_preview,
    )


__all__ = [
    "fetch_job_text",
    "FetchResult",
    "JobFetchError",
    "register_renderer",
]
