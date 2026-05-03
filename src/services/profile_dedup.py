"""Deterministic safety net for candidate profile deduplication.

Even with the new prompt rules in [src/ai/prompts.py](src/ai/prompts.py)
the AI sometimes still emits the same role / study twice when the CV and
LinkedIn export describe it in different languages. This module runs a
cheap Python-side dedup over the merged :class:`CandidateProfile` and also
generates clarifying questions whenever a fact appears in only one source.

The two public entry points are:

* :func:`dedup_profile` - mutates / returns a profile with duplicate
  experience and education entries merged in place.
* :func:`build_source_discrepancy_questions` - for every entry that exists
  in only ``cv`` or only ``linkedin``, returns a :class:`ClarifyingQuestion`
  asking the user whether to include it in the resume.

The implementation is intentionally string-based and dependency-free: we
strip diacritics, drop common legal suffixes / academic stop words, and
compare 4-digit year ranges parsed out of the ``period`` field. That gives
us robust grouping of "Czech University of Life Sciences Prague, 2021-2024"
vs "ČZU v Praze, 2021-2023" without pulling in a fuzzy-matching library.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterable

from ..models.candidate import (
    CandidateProfile,
    EducationEntry,
    EntrySource,
    WorkExperience,
)
from ..models.match import ClarifyingQuestion

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

# Multi-character legal suffixes that contain dots / spaces. We need to
# strip these BEFORE we break punctuation into spaces, otherwise "s.r.o."
# turns into the loose tokens "s r o" that don't match any stop word.
_LEGAL_SUFFIX_PATTERNS: tuple[str, ...] = (
    r"\bs\s*\.\s*r\s*\.\s*o\s*\.?",
    r"\ba\s*\.\s*s\s*\.?",
    r"\bspol\s*\.\s*s\s*r\s*\.?\s*o\s*\.?",
    r"\bltd\s*\.?",
    r"\binc\s*\.?",
    r"\bllc\s*\.?",
    r"\bgmbh\b",
    r"\bplc\b",
)

# Single-token stop words removed during the final tokenization pass.
_STOP_TOKENS: frozenset[str] = frozenset({
    "university",
    "univerzita",
    "fakulta",
    "faculty",
    "school",
    "skola",  # ASCII fallback for "škola"
    "vysoka",
    "stredni",
    "of",
    "the",
    "a",
    "an",
})


def _strip_diacritics(text: str) -> str:
    """Remove diacritics so 'ČZU' and 'czu' compare equal."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _normalize_name(text: str) -> str:
    """Lowercase, drop diacritics, strip legal suffixes / academic stop words."""
    if not text:
        return ""
    cleaned = _strip_diacritics(text).lower()
    for pat in _LEGAL_SUFFIX_PATTERNS:
        cleaned = re.sub(pat, " ", cleaned)
    cleaned = re.sub(r"[\.,/\\\(\)\[\]\-_]", " ", cleaned)
    tokens = [tok for tok in cleaned.split() if tok and tok not in _STOP_TOKENS]
    return " ".join(tokens)


_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _parse_year_range(period: str) -> tuple[int, int] | None:
    """Return ``(start_year, end_year)`` extracted from ``period`` or ``None``.

    Treats 'Present' / 'Současnost' / 'Now' as the current calendar year. We
    don't try to do month-level precision: jobs and degrees are slow enough
    that year-level overlap is the right granularity.
    """
    if not period:
        return None
    years = [int(m.group(0)) for m in _YEAR_RE.finditer(period)]
    if not years:
        return None
    start = years[0]
    end = years[-1] if len(years) > 1 else start
    if re.search(r"(?i)present|now|current|sou[čc]asn[oa]st", period):
        from datetime import date  # noqa: PLC0415 - stdlib lazy import is fine
        end = max(end, date.today().year)
    if start > end:
        start, end = end, start
    return start, end


def _ranges_overlap(a: tuple[int, int] | None, b: tuple[int, int] | None) -> bool:
    """Two year ranges overlap if they share at least one calendar year."""
    if a is None or b is None:
        # If at least one entry has no parsable date we still want to merge
        # them when the names match - otherwise the AI tends to keep the
        # CV entry without dates and the LinkedIn entry with dates as twins.
        return True
    return a[0] <= b[1] and b[0] <= a[1]


def _names_match(a: str, b: str) -> bool:
    """Heuristic match: full normalized equality OR mutual substring."""
    na, nb = _normalize_name(a), _normalize_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if na in nb or nb in na:
        # Catches "ceska zemedelska v praze" inside the longer English name.
        return True
    # Token-set similarity: at least half of the shorter token set sits in
    # the longer one. Calibrated so 'ČZU Prague' merges with 'Provozně
    # ekonomická fakulta ČZU v Praze' (1/2 shared after stop-word removal)
    # but 'MIT' and 'Stanford' still stay separate.
    tokens_a = set(na.split())
    tokens_b = set(nb.split())
    if not tokens_a or not tokens_b:
        return False
    smaller, larger = (tokens_a, tokens_b) if len(tokens_a) <= len(tokens_b) else (tokens_b, tokens_a)
    overlap = len(smaller & larger)
    return overlap / len(smaller) >= 0.5


# ---------------------------------------------------------------------------
# Source merging
# ---------------------------------------------------------------------------

def _merge_source(left: EntrySource, right: EntrySource) -> EntrySource:
    """Combine two source labels: anything mixed becomes ``both``."""
    pair = {left, right}
    if "cv" in pair and "linkedin" in pair:
        return "both"
    if pair == {"both"} or "both" in pair:
        return "both"
    if pair == {"cv"}:
        return "cv"
    if pair == {"linkedin"}:
        return "linkedin"
    # Any 'unknown' wins by the more specific value.
    pair.discard("unknown")
    if pair == {"cv"}:
        return "cv"
    if pair == {"linkedin"}:
        return "linkedin"
    if pair == {"both"}:
        return "both"
    return "unknown"


def _merge_experience(a: WorkExperience, b: WorkExperience) -> WorkExperience:
    """Merge two `WorkExperience` rows, preferring the richer one."""
    primary, secondary = (a, b) if len(a.bullets) >= len(b.bullets) else (b, a)
    bullets: list[str] = []
    for bullet in list(primary.bullets) + list(secondary.bullets):
        b_norm = bullet.strip()
        if b_norm and b_norm not in bullets:
            bullets.append(b_norm)
    technologies = sorted({*primary.technologies, *secondary.technologies})
    employment_type = primary.employment_type
    if employment_type == "unknown" and secondary.employment_type != "unknown":
        employment_type = secondary.employment_type
    return primary.model_copy(update={
        "title": primary.title or secondary.title,
        "company": primary.company or secondary.company,
        "period": primary.period or secondary.period,
        "location": primary.location or secondary.location,
        "bullets": bullets,
        "technologies": technologies,
        "employment_type": employment_type,
        "source": _merge_source(primary.source, secondary.source),
    })


def _merge_education(a: EducationEntry, b: EducationEntry) -> EducationEntry:
    primary, secondary = (a, b) if len(a.degree or "") >= len(b.degree or "") else (b, a)
    notes_chunks = [n for n in (primary.notes, secondary.notes) if n]
    return primary.model_copy(update={
        "institution": primary.institution or secondary.institution,
        "degree": primary.degree or secondary.degree,
        "period": primary.period or secondary.period,
        "notes": " | ".join(notes_chunks) if notes_chunks else None,
        "source": _merge_source(primary.source, secondary.source),
    })


# ---------------------------------------------------------------------------
# Dedup passes
# ---------------------------------------------------------------------------

def _dedup_experience(entries: list[WorkExperience]) -> list[WorkExperience]:
    """Greedy O(n^2) dedup - n is small (rarely > 15) so this is fine."""
    survivors: list[WorkExperience] = []
    for entry in entries:
        merged = False
        for i, existing in enumerate(survivors):
            if _names_match(existing.company, entry.company) and _ranges_overlap(
                _parse_year_range(existing.period),
                _parse_year_range(entry.period),
            ):
                survivors[i] = _merge_experience(existing, entry)
                merged = True
                break
        if not merged:
            survivors.append(entry)
    return survivors


def _dedup_education(entries: list[EducationEntry]) -> list[EducationEntry]:
    survivors: list[EducationEntry] = []
    for entry in entries:
        merged = False
        for i, existing in enumerate(survivors):
            if _names_match(existing.institution, entry.institution) and _ranges_overlap(
                _parse_year_range(existing.period),
                _parse_year_range(entry.period),
            ):
                survivors[i] = _merge_education(existing, entry)
                merged = True
                break
        if not merged:
            survivors.append(entry)
    return survivors


def _ensure_ids(entries: list, prefix: str) -> None:
    """Guarantee every entry has a stable id - mutates in place."""
    used: set[str] = {e.id for e in entries if e.id}
    counter = 0
    for entry in entries:
        if entry.id:
            continue
        while True:
            candidate = f"{prefix}-{counter}"
            counter += 1
            if candidate not in used:
                break
        entry.id = candidate
        used.add(candidate)


def dedup_profile(profile: CandidateProfile) -> CandidateProfile:
    """Return a profile with experience / education entries deduplicated.

    Mutates the model fields in place but also returns the profile for
    callers that prefer a fluent style. The merged entries keep the longer
    description, the union of bullets / technologies and the merged
    ``source`` (mixed -> ``both``).
    """
    deduped_exp = _dedup_experience(list(profile.experience))
    deduped_edu = _dedup_education(list(profile.education))
    if len(deduped_exp) != len(profile.experience):
        logger.info(
            "profile_dedup: collapsed %d duplicate experience rows",
            len(profile.experience) - len(deduped_exp),
        )
    if len(deduped_edu) != len(profile.education):
        logger.info(
            "profile_dedup: collapsed %d duplicate education rows",
            len(profile.education) - len(deduped_edu),
        )
    profile.experience = deduped_exp
    profile.education = deduped_edu
    _ensure_ids(profile.experience, "exp")
    _ensure_ids(profile.education, "edu")
    return profile


# ---------------------------------------------------------------------------
# Discrepancy clarifying questions
# ---------------------------------------------------------------------------

def _format_experience_label(entry: WorkExperience) -> str:
    bits = [entry.title or "Role"]
    if entry.company:
        bits.append(f"at {entry.company}")
    if entry.period:
        bits.append(f"({entry.period})")
    return " ".join(bits)


def _format_education_label(entry: EducationEntry) -> str:
    bits = [entry.degree or "Studies"]
    if entry.institution:
        bits.append(f"at {entry.institution}")
    if entry.period:
        bits.append(f"({entry.period})")
    return " ".join(bits)


def _source_question(
    *,
    qid: str,
    skill: str | None,
    label: str,
    source: EntrySource,
) -> ClarifyingQuestion:
    """Build a yes / no / other question about a single-source entry."""
    if source == "cv":
        sentence = f"'{label}' is on your CV but not on your LinkedIn export."
    elif source == "linkedin":
        sentence = f"'{label}' is on LinkedIn but not in your CV."
    else:
        sentence = f"'{label}' was only found in one of your inputs."
    return ClarifyingQuestion(
        id=qid,
        skill=skill,
        question=sentence + " Should we include it in the resume?",
        why_it_matters=(
            "Including or skipping it changes the experience section. We want "
            "to keep the resume honest and match what you actually want to "
            "show."
        ),
        options=[
            "Yes - include it",
            "No - skip it",
        ],
        answer_type="single_choice",
    )


def build_source_discrepancy_questions(
    profile: CandidateProfile,
    *,
    max_questions: int = 6,
) -> list[ClarifyingQuestion]:
    """Generate "is this only on one source?" questions for the user.

    Each question's ``id`` encodes the originating entry id so the GUI can
    map a 'No - skip it' answer back to the row that should be excluded
    before document generation. The format is ``discrepancy:<entry_id>``
    (e.g. ``discrepancy:exp-3``).
    """
    questions: list[ClarifyingQuestion] = []

    for entry in profile.experience:
        if entry.source not in ("cv", "linkedin"):
            continue
        if not (entry.title or entry.company):
            continue
        questions.append(
            _source_question(
                qid=f"discrepancy:{entry.id or _format_experience_label(entry)}",
                skill=None,
                label=_format_experience_label(entry),
                source=entry.source,
            )
        )

    for entry in profile.education:
        if entry.source not in ("cv", "linkedin"):
            continue
        if not entry.institution:
            continue
        questions.append(
            _source_question(
                qid=f"discrepancy:{entry.id or _format_education_label(entry)}",
                skill=None,
                label=_format_education_label(entry),
                source=entry.source,
            )
        )

    return questions[:max_questions]


# ---------------------------------------------------------------------------
# Excluded-entry helpers used by main_window before document generation
# ---------------------------------------------------------------------------

def excluded_ids_from_answers(
    answers: Iterable,
) -> set[str]:
    """Return the set of profile-entry ids the user said to skip.

    Looks for ``ClarifyingAnswer`` objects whose ``question_id`` starts with
    ``discrepancy:`` and whose answer text starts with 'no' (case-insensitive,
    strips whitespace - so "No - skip it" and "no" both qualify).
    """
    skip_prefixes = {"discrepancy:"}
    result: set[str] = set()
    for ans in answers or []:
        qid = getattr(ans, "question_id", "") or ""
        if not any(qid.startswith(p) for p in skip_prefixes):
            continue
        text = (getattr(ans, "answer", "") or "").strip().lower()
        if not text or text.startswith("no"):
            entry_id = qid.split("discrepancy:", 1)[1]
            if entry_id:
                result.add(entry_id)
    return result


def filter_profile_entries(
    profile: CandidateProfile,
    excluded_ids: set[str],
) -> CandidateProfile:
    """Return a shallow copy of ``profile`` without any excluded experience or
    education entries. Used right before resume / cover / interview / gap
    generation so excluded rows never reach the AI prompt.
    """
    if not excluded_ids:
        return profile
    return profile.model_copy(update={
        "experience": [e for e in profile.experience if e.id not in excluded_ids],
        "education": [e for e in profile.education if e.id not in excluded_ids],
    })


__all__ = [
    "dedup_profile",
    "build_source_discrepancy_questions",
    "excluded_ids_from_answers",
    "filter_profile_entries",
]
