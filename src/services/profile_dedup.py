"""Deterministic safety net for candidate profile deduplication.

Even with the new prompt rules in [src/ai/prompts.py](src/ai/prompts.py)
the AI sometimes still emits the same role / study twice when the CV and
LinkedIn export describe it in different languages or with different dates.
This module runs a cheap Python-side dedup over the merged
:class:`CandidateProfile` and also generates clarifying questions whenever a
fact appears in only one source or the two sources disagree on a date.

Public entry points:

* :func:`dedup_profile` - mutates / returns a profile with duplicate
  experience and education entries merged in place.
* :func:`build_source_discrepancy_questions` - for every entry that exists
  in only ``cv`` or only ``linkedin``, returns a :class:`ClarifyingQuestion`
  asking the user whether to include it in the resume.
* :func:`build_date_conflict_questions` - for every entry whose ``notes``
  field carries a ``CV: ... | LinkedIn: ...`` date discrepancy, returns a
  :class:`ClarifyingQuestion` asking the user which period is correct.

The implementation is intentionally string-based and dependency-free: we
strip diacritics, drop common legal suffixes / academic stop words, apply a
small Czech<->English token map (``prague`` <-> ``praha`` etc.) and compare
4-digit year ranges parsed out of the ``period`` field.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterable

from ..i18n import t
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
    # Articles / prepositions that survive in either language and add noise.
    "of",
    "the",
    "a",
    "an",
    "and",
    "v",   # Czech preposition for "in" (e.g. "ČZU v Praze")
    "ve",
    "i",   # Czech "and"
    "se",
    "in",
    "at",
})

# Cross-language token equivalences. Applied AFTER tokenization so we don't
# disturb the legal-suffix / stop-word logic. The key is the input token
# (already lowercased & diacritic-stripped), the value is the canonical form
# we use for comparison. Add new entries narrowly - false positives here
# silently merge unrelated rows.
_TOKEN_EQUIVALENCES: dict[str, str] = {
    # Place names (CZ <-> EN)
    "praha": "praha",
    "praze": "praha",
    "prague": "praha",
    "prag": "praha",
    "brno": "brno",
    "ostrava": "ostrava",
    "plzen": "plzen",
    "pilsen": "plzen",
    "republiky": "cz",
    "republika": "cz",
    "republic": "cz",
    "ceska": "cz",
    "ceske": "cz",
    "cesky": "cz",
    "cesko": "cz",
    "czech": "cz",
    "czechia": "cz",
    "ceskoslovenska": "cz",
    "ceskoslovenske": "cz",
    "ceskoslovenske,": "cz",
}


def _strip_diacritics(text: str) -> str:
    """Remove diacritics so 'ČZU' and 'czu' compare equal."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _normalize_name(text: str) -> str:
    """Lowercase, drop diacritics, strip legal suffixes / academic stop words.

    Also collapses brand-parenthetical lists ("Trust Based Solutions (Norton
    · Avast · ...)") and applies the cross-language token map so place
    names and country adjectives match across CZ/EN spellings.
    """
    if not text:
        return ""
    cleaned = _strip_diacritics(text).lower()
    for pat in _LEGAL_SUFFIX_PATTERNS:
        cleaned = re.sub(pat, " ", cleaned)
    # Bullets / interpuncts and parens are common in LinkedIn/CV strings;
    # treat them as plain word boundaries so "Gen Digital · Trust ..." has
    # the same tokenisation as "Gen Digital, Trust ...".
    cleaned = re.sub(r"[\.,/\\\(\)\[\]\-_·•]", " ", cleaned)
    raw_tokens = [tok for tok in cleaned.split() if tok]
    tokens: list[str] = []
    for tok in raw_tokens:
        if tok in _STOP_TOKENS:
            continue
        tokens.append(_TOKEN_EQUIVALENCES.get(tok, tok))
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
    """Heuristic match: full normalized equality OR mutual substring OR
    >= 0.4 token overlap (smaller-coverage) with at least TWO shared tokens.

    Lowered the smaller-coverage threshold from 0.5 to 0.4 in the
    cost-analysis-and-ux-overhaul pass so single-word variations like "Gen"
    vs "Gen Digital · Trust Based Solutions ..." merge even when the long
    variant brings many extra brand parentheticals - though that case is
    actually caught by the substring rule above.

    The "at least two shared tokens" guard prevents false positives where
    two unrelated organisations share a single common token that survives
    normalisation (e.g. two real Prague universities both having "praha"
    after place-name equivalence).
    """
    na, nb = _normalize_name(a), _normalize_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if na in nb or nb in na:
        # Catches "ceska zemedelska v praze" inside the longer English name
        # and "gen" inside "gen digital trust based solutions".
        return True
    tokens_a = set(na.split())
    tokens_b = set(nb.split())
    if not tokens_a or not tokens_b:
        return False
    smaller, larger = (
        (tokens_a, tokens_b) if len(tokens_a) <= len(tokens_b) else (tokens_b, tokens_a)
    )
    overlap = len(smaller & larger)
    if overlap < 2:
        # A single shared generic token (e.g. just "praha") is not enough
        # signal to merge two genuinely distinct organisations.
        return False
    return overlap / len(smaller) >= 0.4


# ---------------------------------------------------------------------------
# Date-conflict notes helpers
# ---------------------------------------------------------------------------

# Pattern used both when WRITING the conflict note (in :func:`_merge_*`) and
# when READING it back in :func:`build_date_conflict_questions`. Keep them
# in sync - the test suite asserts a round trip.
_DATE_CONFLICT_RE = re.compile(
    r"CV:\s*(?P<cv>[^|]+?)\s*\|\s*LinkedIn:\s*(?P<linkedin>[^|]+?)(?:\s*\||$)",
    re.IGNORECASE,
)


def _format_date_conflict_note(cv_period: str, linkedin_period: str) -> str:
    return f"CV: {cv_period.strip()} | LinkedIn: {linkedin_period.strip()}"


def _append_note(existing: str | None, addition: str) -> str:
    """Append ``addition`` to ``existing`` notes without duplicating it.

    We use ``" | "`` as the joiner so the AI's pre-existing notes (which
    already follow the same convention) are preserved verbatim.
    """
    if not existing:
        return addition
    if addition in existing:
        return existing
    return f"{existing} | {addition}"


def _detect_date_conflict(
    a_period: str,
    b_period: str,
    a_source: EntrySource,
    b_source: EntrySource,
) -> tuple[str, str] | None:
    """Return ``(cv_period, linkedin_period)`` when the two entries describe
    the same role/study but disagree on dates, otherwise ``None``.

    We deliberately surface the conflict only when one side is from the CV
    and the other from LinkedIn - if both came from the same source, the
    user already cross-checked the dates themselves.
    """
    if not a_period or not b_period:
        return None
    if a_period.strip() == b_period.strip():
        return None
    a_range = _parse_year_range(a_period)
    b_range = _parse_year_range(b_period)
    if a_range and b_range and a_range == b_range:
        return None  # different wording, same years
    sources = {a_source, b_source}
    if not ({"cv", "linkedin"} <= sources):
        return None
    cv_period = a_period if a_source == "cv" else b_period
    linkedin_period = a_period if a_source == "linkedin" else b_period
    return cv_period, linkedin_period


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
    notes = primary.notes or secondary.notes
    if primary.notes and secondary.notes and primary.notes != secondary.notes:
        notes = _append_note(primary.notes, secondary.notes)
    conflict = _detect_date_conflict(
        primary.period, secondary.period, primary.source, secondary.source
    )
    if conflict is not None:
        notes = _append_note(notes, _format_date_conflict_note(*conflict))
    return primary.model_copy(update={
        "title": primary.title or secondary.title,
        "company": primary.company or secondary.company,
        "period": primary.period or secondary.period,
        "location": primary.location or secondary.location,
        "bullets": bullets,
        "technologies": technologies,
        "employment_type": employment_type,
        "source": _merge_source(primary.source, secondary.source),
        "notes": notes,
    })


def _merge_education(a: EducationEntry, b: EducationEntry) -> EducationEntry:
    primary, secondary = (a, b) if len(a.degree or "") >= len(b.degree or "") else (b, a)
    notes_chunks = [n for n in (primary.notes, secondary.notes) if n]
    notes = " | ".join(notes_chunks) if notes_chunks else None
    conflict = _detect_date_conflict(
        primary.period, secondary.period, primary.source, secondary.source
    )
    if conflict is not None:
        notes = _append_note(notes, _format_date_conflict_note(*conflict))
    return primary.model_copy(update={
        "institution": primary.institution or secondary.institution,
        "degree": primary.degree or secondary.degree,
        "period": primary.period or secondary.period,
        "notes": notes,
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
    ``source`` (mixed -> ``both``). Date conflicts are persisted in the
    entry's ``notes`` field for later question generation.
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
        question = t("dedup.q.cv_only", label=label)
        why = t("dedup.why.cv_only")
    elif source == "linkedin":
        question = t("dedup.q.linkedin_only", label=label)
        why = t("dedup.why.linkedin_only")
    else:
        # Defensive fallback - the caller shouldn't reach here for `both`/
        # `unknown`, but if they do we surface a generic phrasing.
        question = t("dedup.q.cv_only", label=label)
        why = t("dedup.why.cv_only")
    return ClarifyingQuestion(
        id=qid,
        skill=skill,
        question=question,
        why_it_matters=why,
        options=[
            t("dedup.opt.include"),
            t("dedup.opt.skip"),
        ],
        answer_type="single_choice",
    )


def _date_conflict_question(
    *,
    qid: str,
    label: str,
    cv_period: str,
    linkedin_period: str,
) -> ClarifyingQuestion:
    return ClarifyingQuestion(
        id=qid,
        skill=None,
        question=t(
            "dedup.q.date_conflict",
            label=label,
            cv_period=cv_period,
            linkedin_period=linkedin_period,
        ),
        why_it_matters=t("dedup.why.date_conflict"),
        options=[cv_period, linkedin_period, t("dedup.opt.other_dates")],
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


def build_date_conflict_questions(
    profile: CandidateProfile,
    *,
    max_questions: int = 6,
) -> list[ClarifyingQuestion]:
    """Generate ``discrepancy:date:<entry_id>`` questions for merged entries
    where the CV and LinkedIn dates disagree.

    Reads the ``notes`` field of each ``experience`` and ``education`` row
    looking for the canonical ``CV: ... | LinkedIn: ...`` pattern. The note
    is written by :func:`_merge_experience` / :func:`_merge_education` and
    can also be supplied by the AI directly (see
    ``analyze_candidate_user_prompt``). Both sources funnel into the same
    handler.
    """
    questions: list[ClarifyingQuestion] = []

    for entry in profile.experience:
        match = _DATE_CONFLICT_RE.search(entry.notes or "")
        if match is None:
            continue
        cv_period = match.group("cv").strip()
        linkedin_period = match.group("linkedin").strip()
        if not cv_period or not linkedin_period:
            continue
        if cv_period == linkedin_period:
            continue
        questions.append(
            _date_conflict_question(
                qid=f"discrepancy:date:{entry.id or _format_experience_label(entry)}",
                label=_format_experience_label(entry),
                cv_period=cv_period,
                linkedin_period=linkedin_period,
            )
        )

    for entry in profile.education:
        match = _DATE_CONFLICT_RE.search(entry.notes or "")
        if match is None:
            continue
        cv_period = match.group("cv").strip()
        linkedin_period = match.group("linkedin").strip()
        if not cv_period or not linkedin_period:
            continue
        if cv_period == linkedin_period:
            continue
        questions.append(
            _date_conflict_question(
                qid=f"discrepancy:date:{entry.id or _format_education_label(entry)}",
                label=_format_education_label(entry),
                cv_period=cv_period,
                linkedin_period=linkedin_period,
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
    ``discrepancy:`` (but NOT ``discrepancy:date:``) and whose answer text
    starts with 'no' / 'ne' (case-insensitive) - so "No - skip it" /
    "Ne - vynechat" both qualify regardless of which UI language was active
    when the user clicked. Date-conflict answers are NEVER an exclusion
    signal: they pick which date is correct, not whether to keep the row.
    """
    result: set[str] = set()
    for ans in answers or []:
        qid = getattr(ans, "question_id", "") or ""
        if not qid.startswith("discrepancy:"):
            continue
        if qid.startswith("discrepancy:date:"):
            continue
        text = (getattr(ans, "answer", "") or "").strip().lower()
        if not text:
            continue
        # Prefix match on "no" / "ne" covers both English and Czech "skip"
        # answers without us hardcoding every translation. We also explicitly
        # ignore positive-prefix answers (e.g. "Ne_vim" wouldn't normally
        # be in the option list, but just in case).
        if text.startswith("no") or text.startswith("ne"):
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
    "build_date_conflict_questions",
    "excluded_ids_from_answers",
    "filter_profile_entries",
]
