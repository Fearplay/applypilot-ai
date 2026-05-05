"""ASCII-friendly slugifier used for output folder names + document filenames."""
from __future__ import annotations

import re
import unicodedata

_NON_SLUG = re.compile(r"[^a-z0-9]+")
_NAME_TOKEN = re.compile(r"[a-z0-9]+")


def slugify(text: str, max_len: int = 60, fallback: str = "untitled") -> str:
    """Produce a filesystem-safe slug from arbitrary text.

    Lowercases, strips diacritics via NFKD, replaces every non-``[a-z0-9]``
    run with a single ``-`` and trims leading / trailing hyphens. Returns
    ``fallback`` when the input is empty or collapses to an empty string.
    """
    if not text:
        return fallback
    normalised = unicodedata.normalize("NFKD", text)
    ascii_text = normalised.encode("ascii", errors="ignore").decode("ascii")
    slug = _NON_SLUG.sub("-", ascii_text.lower()).strip("-")
    if not slug:
        return fallback
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or fallback


def name_slug(full_name: str, *, fallback: str = "applicant", max_len: int = 80) -> str:
    """Slugify a person's name into ``firstname_lastname`` form.

    Uses underscores instead of hyphens (recruiters expect ``jan_novak``
    rather than ``jan-novak`` for personal documents) and preserves all
    name tokens so middle names / particles like ``"von"`` survive.

    Examples
    --------
    >>> name_slug("Jan Novak")
    'jan_novak'
    >>> name_slug("Jan Novák")
    'jan_novak'
    >>> name_slug("Anna-Maria von Bismarck")
    'anna_maria_von_bismarck'
    >>> name_slug("")
    'applicant'
    """
    if not full_name:
        return fallback
    normalised = unicodedata.normalize("NFKD", full_name)
    ascii_text = normalised.encode("ascii", errors="ignore").decode("ascii").lower()
    tokens = _NAME_TOKEN.findall(ascii_text)
    if not tokens:
        return fallback
    slug = "_".join(tokens)
    if len(slug) > max_len:
        # Preserve whole tokens up to ``max_len`` so we never produce a
        # mid-word truncation like ``jan_nov``.
        out: list[str] = []
        running = 0
        for tok in tokens:
            extra = len(tok) + (1 if out else 0)
            if running + extra > max_len:
                break
            out.append(tok)
            running += extra
        slug = "_".join(out) if out else slug[:max_len].rstrip("_")
    return slug or fallback


def pretty_name_slug(
    full_name: str, *, fallback: str = "Applicant", max_len: int = 80
) -> str:
    """Title-case underscored slug for user-facing filenames.

    Recruiters expect ``Juraj_Acsay_CV.pdf`` rather than the all-lowercase
    ``juraj_acsay_cv.pdf``. This is the helper for the artefact filenames
    the user actually emails out; :func:`name_slug` (lowercase) keeps its
    historical meaning for folder hashes / internal IDs that other code
    paths still rely on.

    Examples
    --------
    >>> pretty_name_slug("Jan Novak")
    'Jan_Novak'
    >>> pretty_name_slug("Jan Novák")
    'Jan_Novak'
    >>> pretty_name_slug("Anna-Maria von Bismarck")
    'Anna_Maria_Von_Bismarck'
    >>> pretty_name_slug("j. doe")
    'J_Doe'
    >>> pretty_name_slug("")
    'Applicant'
    """
    if not full_name:
        return fallback
    normalised = unicodedata.normalize("NFKD", full_name)
    ascii_text = normalised.encode("ascii", errors="ignore").decode("ascii").lower()
    tokens = _NAME_TOKEN.findall(ascii_text)
    if not tokens:
        return fallback
    capitalised = [tok.capitalize() for tok in tokens]
    slug = "_".join(capitalised)
    if len(slug) > max_len:
        out: list[str] = []
        running = 0
        for tok in capitalised:
            extra = len(tok) + (1 if out else 0)
            if running + extra > max_len:
                break
            out.append(tok)
            running += extra
        slug = "_".join(out) if out else slug[:max_len].rstrip("_")
    return slug or fallback


__all__ = ["slugify", "name_slug", "pretty_name_slug"]
