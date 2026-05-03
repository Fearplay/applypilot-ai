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
    CertificationEntry,
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
    # Faculty types (CZ adjective <-> EN noun). Without these the dedup
    # heuristic can't see that "Provozně ekonomická fakulta ČZU v Praze"
    # and "Faculty of Economics and Management, Czech University of Life
    # Sciences Prague" describe the same school - they'd only share the
    # city token after normalisation, which is below the 2-shared-tokens
    # bar that protects against merging two genuinely distinct Prague
    # universities (Karlova vs ČVUT). Mapping the most common faculty
    # adjectives lifts the user-bug pair above the bar without affecting
    # the unrelated-schools case.
    "ekonomicka": "economics",
    "ekonomicke": "economics",
    "ekonomicky": "economics",
    "ekonomicky,": "economics",
    "ekonomie": "economics",
    "economic": "economics",
    "economical": "economics",
    "ekonomicke,": "economics",
    "spravni": "administration",
    "pravnicka": "law",
    "pravnicke": "law",
    "lekarska": "medical",
    "lekarske": "medical",
    "prirodovedecka": "science",
    "prirodovedecke": "science",
    "filozoficka": "philosophy",
    "filozoficke": "philosophy",
    "pedagogicka": "education",
    "pedagogicke": "education",
    "informatika": "informatics",
    "informatiky": "informatics",
    "computer": "informatics",  # "computer science" / "informatika"
    "informatics": "informatics",
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


# ---------------------------------------------------------------------------
# Seniority prefixes used to distinguish career-progression entries.
# Single source of truth shared with the resume generator (which imports
# ``_extract_seniority`` from here so the two modules can never drift).
# ---------------------------------------------------------------------------
SENIORITY_PREFIXES: tuple[str, ...] = (
    "junior", "senior", "lead", "staff", "principal", "head",
)
_SENIORITY_RE = re.compile(
    r"^(" + "|".join(SENIORITY_PREFIXES) + r")\b",
    re.IGNORECASE,
)


def _strip_seniority(title: str) -> str:
    """Drop a leading 'Junior'/'Senior'/'Lead'/... prefix, if any."""
    return _SENIORITY_RE.sub("", (title or "").strip()).strip()


def _extract_seniority(title: str) -> str:
    """Return the lowercase seniority prefix on ``title`` or ``""``."""
    m = _SENIORITY_RE.match((title or "").strip())
    return m.group(1).lower() if m else ""


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
    if _periods_are_equivalent(a_period, b_period):
        # Catches both literal equality AND year-range equality (e.g.
        # "06/2023 - 07/2025" vs "června 2023 - července 2025").
        return None
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
    """Greedy O(n^2) dedup - n is small (rarely > 15) so this is fine.

    Seniority guard (HARD RULE): two rows with DIFFERENT seniority prefixes
    on their titles (e.g. 'Junior Software QA Engineer' vs 'Software QA
    Engineer' vs 'Senior Software QA Engineer') are NEVER merged, even if
    the company name matches and the date ranges overlap. Career
    progression entries always remain separate so the resume keeps its
    full timeline.
    """
    survivors: list[WorkExperience] = []
    for entry in entries:
        entry_sen = _extract_seniority(entry.title)
        merged = False
        for i, existing in enumerate(survivors):
            existing_sen = _extract_seniority(existing.title)
            if entry_sen != existing_sen:
                # Distinct seniority levels are different career-progression
                # rows even when company + dates would otherwise match.
                continue
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
    """Greedy O(n^2) dedup of education rows.

    Relies on the strict :func:`_names_match` heuristic - which was made
    cross-language-aware via the expanded :data:`_TOKEN_EQUIVALENCES` map
    (faculty adjectives, "informatika" <-> "informatics", etc.) so that
    e.g. "Provozně ekonomická fakulta ČZU v Praze" and "Faculty of
    Economics and Management, Czech University of Life Sciences Prague"
    now collapse on shared tokens (``economics`` + ``praha``) without
    needing the city-only fallback that risked merging genuinely distinct
    Prague schools (Karlova vs ČVUT, both of which only share ``praha``
    after normalisation).
    """
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


# ---------------------------------------------------------------------------
# Certifications dedup
# ---------------------------------------------------------------------------

# Common issuer prefixes that prevent two records from looking like the same
# course (e.g. CV bullet "Java Programming" vs LinkedIn "Oracle Academy -
# Java Programming"). Stripped during normalization so the substring rule
# in :func:`_certs_are_same` catches the pair.
_CERT_ISSUER_PREFIXES: tuple[str, ...] = (
    "oracle academy",
    "oracle university",
    "engeto",
    "udemy",
    "coursera",
    "edx",
    "linkedin learning",
    "pluralsight",
    "microsoft learn",
    "microsoft",
    "aws",
    "google",
    "ibm",
)


# Cross-language token map applied during cert normalisation so that e.g.
# "Python Akademie" and "Python Academy" share enough tokens to be flagged
# as duplicates. Kept narrow on purpose - random tokens here would silently
# merge unrelated certificates.
_CERT_TOKEN_EQUIVALENCES: dict[str, str] = {
    "akademie": "academy",
    "akademy": "academy",
    "akademia": "academy",
    "kurzu": "course",
    "kurzem": "course",
    "kurz": "course",
    "kurs": "course",
    "kurzy": "course",
    "skoleni": "training",
    "skolenia": "training",
    "training": "training",
    "trening": "training",
    "zaklady": "fundamentals",
    "zaklad": "fundamentals",
    "fundamentals": "fundamentals",
    "foundations": "fundamentals",
    "intensive": "intensive",
    "intenzivni": "intensive",
    "intenzivny": "intensive",
}


def _normalize_cert_name(text: str) -> str:
    """Lowercase, drop diacritics, strip issuer prefix, drop year tokens.

    Also collapses common CZ <-> EN cert vocabulary via
    :data:`_CERT_TOKEN_EQUIVALENCES` so "Python Akademie" and "Python
    Academy" produce the same canonical form.
    """
    if not text:
        return ""
    cleaned = _strip_diacritics(text).lower()
    cleaned = re.sub(r"\b(19|20)\d{2}\b", " ", cleaned)
    cleaned = re.sub(r"[\.,/\\\(\)\[\]_·•:]", " ", cleaned)
    # The issuer is sometimes glued to the name with a hyphen, sometimes
    # with " - " or " | ". Normalise all separators to a single space
    # before scanning for prefixes.
    cleaned = re.sub(r"\s*-\s*", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    for prefix in _CERT_ISSUER_PREFIXES:
        if cleaned.startswith(prefix + " ") or cleaned == prefix:
            cleaned = cleaned[len(prefix):].strip()
    # Final tokenisation reuses the academic stop-word list so noise
    # tokens like "the", "of" don't get in the way, and applies the
    # cert-specific equivalence map so cross-language duplicates collapse.
    raw_tokens = [tok for tok in cleaned.split() if tok and tok not in _STOP_TOKENS]
    tokens = [_CERT_TOKEN_EQUIVALENCES.get(tok, tok) for tok in raw_tokens]
    return " ".join(tokens)


def _certs_are_same(a: CertificationEntry, b: CertificationEntry) -> bool:
    """Heuristic: same normalized name OR substring OR >= 0.6 token overlap."""
    na = _normalize_cert_name(a.name)
    nb = _normalize_cert_name(b.name)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if na in nb or nb in na:
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
        return False
    return overlap / len(smaller) >= 0.6


def _merge_certs(a: CertificationEntry, b: CertificationEntry) -> CertificationEntry:
    """Keep the longer name; backfill issuer / year from whichever side has them."""
    primary, secondary = (a, b) if len(a.name or "") >= len(b.name or "") else (b, a)
    return primary.model_copy(update={
        "name": primary.name or secondary.name,
        "issuer": primary.issuer or secondary.issuer,
        "year": primary.year or secondary.year,
    })


def _dedup_certifications(entries: list[CertificationEntry]) -> list[CertificationEntry]:
    """Greedy O(n^2) dedup of a certification list."""
    survivors: list[CertificationEntry] = []
    for entry in entries:
        if not (entry.name or "").strip():
            continue
        merged = False
        for i, existing in enumerate(survivors):
            if _certs_are_same(existing, entry):
                survivors[i] = _merge_certs(existing, entry)
                merged = True
                break
        if not merged:
            survivors.append(entry)
    return survivors


# ---------------------------------------------------------------------------
# Spoken languages dedup
# ---------------------------------------------------------------------------

# Map any spelling we see in the inputs to a canonical English label. New
# entries are always lowercase + diacritic-stripped on lookup. The canonical
# label is what stays on the deduplicated profile; we DO NOT translate to
# the active UI language here (the resume prompt + renderer handle that).
_LANGUAGE_CANONICAL: dict[str, str] = {
    "czech": "Czech",
    "cestina": "Czech",
    "ceski": "Czech",
    "cesky": "Czech",
    "cesko": "Czech",
    "slovak": "Slovak",
    "slovencina": "Slovak",
    "slovenstina": "Slovak",
    "english": "English",
    "anglictina": "English",
    "anglicky": "English",
    "german": "German",
    "nemcina": "German",
    "deutsch": "German",
    "french": "French",
    "francouzstina": "French",
    "francais": "French",
    "spanish": "Spanish",
    "spanelstina": "Spanish",
    "espanol": "Spanish",
    "italian": "Italian",
    "italstina": "Italian",
    "italiano": "Italian",
    "polish": "Polish",
    "polstina": "Polish",
    "russian": "Russian",
    "rustina": "Russian",
    "ukrainian": "Ukrainian",
    "ukrajinstina": "Ukrainian",
    "chinese": "Chinese",
    "cinstina": "Chinese",
    "japanese": "Japanese",
    "japonstina": "Japanese",
    "korean": "Korean",
    "korejstina": "Korean",
    "portuguese": "Portuguese",
    "portugalstina": "Portuguese",
    "dutch": "Dutch",
    "nizozemstina": "Dutch",
    "swedish": "Swedish",
    "svedstina": "Swedish",
    "norwegian": "Norwegian",
    "norstina": "Norwegian",
    "danish": "Danish",
    "dantina": "Danish",
}


def _split_language_entry(entry: str) -> tuple[str, str]:
    """Split ``"Czech (C2 - native)"`` into ``("Czech", "C2 - native")``."""
    text = (entry or "").strip()
    if not text:
        return "", ""
    for sep in ("(", " - ", " \u2013 ", ":"):
        if sep in text:
            name, _, raw_level = text.partition(sep)
            return name.strip(), raw_level.rstrip(") ").strip()
    return text, ""


def _canonicalise_language_name(name: str) -> str:
    """Map ``name`` to a canonical English label, falling back to the input."""
    key = _strip_diacritics(name).lower().strip()
    # Strip trailing modifiers some users include in the name itself
    # (e.g. "English language", "Czech mother tongue").
    key = re.sub(r"\b(language|jazyk|mother\s*tongue|materstina|materský)\b", "", key)
    key = re.sub(r"\s+", " ", key).strip()
    return _LANGUAGE_CANONICAL.get(key, name.strip())


_CEFR_RE = re.compile(r"^[ABC][12]$", re.IGNORECASE)

_DESCRIPTIVE_TO_CEFR: dict[str, str] = {
    "native or bilingual": "C2",
    "native or bilingual proficiency": "C2",
    "native": "C2",
    "bilingual": "C2",
    "mateřský": "C2",
    "mateřsky": "C2",
    "rodilý mluvčí": "C2",
    "full professional": "C1",
    "full professional proficiency": "C1",
    "professional working": "B2",
    "professional working proficiency": "B2",
    "limited working": "B1",
    "limited working proficiency": "B1",
    "elementary": "A2",
    "elementary proficiency": "A2",
    "beginner": "A1",
    "passive": "B2",
    "pasivní": "B2",
    "pasivně": "B2",
}


def _extract_cefr(level: str) -> str:
    """Pull a CEFR code out of a compound string like "C1 - native"."""
    m = re.search(r"\b([ABC][12])\b", level, re.IGNORECASE)
    return m.group(1).upper() if m else ""


def _to_cefr(level: str) -> str:
    """Convert a level string to CEFR if possible, otherwise return as-is."""
    stripped = level.strip()
    if not stripped:
        return ""
    embedded = _extract_cefr(stripped)
    if embedded:
        return embedded
    key = stripped.lower()
    return _DESCRIPTIVE_TO_CEFR.get(key, stripped)


def _is_cefr(level: str) -> bool:
    return bool(_CEFR_RE.match(level.strip()))


_CEFR_RANK = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}


def _pick_better_level(existing: str, incoming: str) -> str:
    """Pick the best level between two candidates, preferring CEFR codes.

    When both resolve to CEFR, the higher proficiency wins.
    """
    if not existing:
        return _to_cefr(incoming)
    if not incoming:
        return _to_cefr(existing)
    e_resolved = _to_cefr(existing)
    i_resolved = _to_cefr(incoming)
    e_is = _is_cefr(e_resolved)
    i_is = _is_cefr(i_resolved)
    if e_is and i_is:
        return e_resolved if _CEFR_RANK.get(e_resolved, 0) >= _CEFR_RANK.get(i_resolved, 0) else i_resolved
    if e_is:
        return e_resolved
    if i_is:
        return i_resolved
    return e_resolved


def _dedup_languages(entries: list[str]) -> list[str]:
    """Collapse "Czech" / "čeština" / "Czech (mateřský)" into one entry.

    The canonical English name wins. For levels, CEFR codes (C2, C1, B2, ...)
    are always preferred over descriptive labels ("Native or Bilingual",
    "Full Professional"). Descriptive labels are converted to CEFR.
    """
    canonical_order: list[str] = []
    by_canonical: dict[str, str] = {}
    for raw in entries:
        name, level = _split_language_entry(raw)
        if not name:
            continue
        canonical = _canonicalise_language_name(name)
        if canonical not in by_canonical:
            canonical_order.append(canonical)
            by_canonical[canonical] = _to_cefr(level)
        else:
            by_canonical[canonical] = _pick_better_level(
                by_canonical[canonical], level
            )

    result: list[str] = []
    for canonical in canonical_order:
        level = by_canonical[canonical]
        if level:
            result.append(f"{canonical} ({level})")
        else:
            result.append(canonical)
    return result


# ---------------------------------------------------------------------------
# CEFR fallback: scan raw CV / LinkedIn text when the AI forgot to attach
# proficiency labels to the spoken_languages entries
# ---------------------------------------------------------------------------

# Match "Name (proficiency)" pairs. We allow one or two words for the name
# (covers cases like "Mandarin Chinese") and any non-paren content for the
# proficiency. The full Unicode letter range catches diacritics in
# "angličtina", "čeština", "němčina", "français", ... The intra-word
# whitespace is restricted to spaces/tabs so we never bridge a newline -
# otherwise a heading like "Languages\nangličtina (Full Professional)"
# would be captured as the two-word name "Languages\nangličtina".
_LANG_PROFICIENCY_RE = re.compile(
    r"([A-Za-z\u00C0-\u024F]+(?:[ \t]+[A-Za-z\u00C0-\u024F]+)?)[ \t]*\(([^)]+)\)",
    re.UNICODE,
)

# Recognised English canonical labels - used to filter out spurious matches
# like "Pilsen (Czech Republic)" or "Praha (CZ)" which look syntactically
# like a language proficiency pair.
_KNOWN_CANONICAL_LANGUAGES: frozenset[str] = frozenset(
    v.lower() for v in _LANGUAGE_CANONICAL.values()
)


def _extract_language_levels_from_raw_text(text: str) -> dict[str, str]:
    """Scan ``text`` for ``Name (proficiency)`` pairs and return a map of
    canonical English language name -> CEFR level.

    Used by :func:`_backfill_language_levels` when the AI dropped the
    proficiency annotations from ``spoken_languages`` (the AI sometimes
    emits ``["Czech", "English", "German"]`` instead of ``["Czech (Native
    or Bilingual)", ...]``). Parses defensively: any pair that doesn't map
    to a known language label is silently skipped so we don't accidentally
    treat ``"Prague (Czech Republic)"`` as a language entry.
    """
    if not text:
        return {}
    out: dict[str, str] = {}
    for m in _LANG_PROFICIENCY_RE.finditer(text):
        raw_name = m.group(1).strip()
        raw_level = m.group(2).strip()
        if not raw_name or not raw_level:
            continue
        canonical = _canonicalise_language_name(raw_name)
        # Reject if the name was unchanged AND not in the canonical
        # whitelist - that means it was a non-language token like a
        # city name or product name.
        canonical_lower = canonical.lower()
        if canonical_lower not in _KNOWN_CANONICAL_LANGUAGES:
            continue
        cefr = _to_cefr(raw_level)
        if not _is_cefr(cefr):
            continue
        existing = out.get(canonical)
        if existing:
            out[canonical] = _pick_better_level(existing, cefr)
        else:
            out[canonical] = cefr
    return out


def _backfill_language_levels(
    languages: list[str], raw_text: str
) -> list[str]:
    """For each entry in ``languages`` that lacks a CEFR level, try to
    fill one in from ``raw_text`` (CV + LinkedIn export concatenated).

    Pure function: returns a new list, never mutates the input. Order is
    preserved. Entries that already have a level are passed through
    untouched.
    """
    if not languages or not raw_text:
        return list(languages)
    levels = _extract_language_levels_from_raw_text(raw_text)
    if not levels:
        return list(languages)
    out: list[str] = []
    for entry in languages:
        name, level = _split_language_entry(entry)
        if level:
            out.append(entry)
            continue
        canonical = _canonicalise_language_name(name)
        cefr = levels.get(canonical)
        if cefr:
            out.append(f"{name} ({cefr})")
        else:
            out.append(entry)
    return out


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

    Also collapses duplicate certifications and spoken-language entries
    that come from the same source mentioned twice with different
    spellings (e.g. ``"Czech"`` + ``"čeština"``, or ``"Java Programming"``
    + ``"Oracle Academy - Java Programming"``). Spoken languages without
    a CEFR level are augmented from ``profile.raw_cv_text`` /
    ``profile.raw_linkedin_text`` so the rendered sidebar always has the
    proficiency the user actually provided.
    """
    deduped_exp = _dedup_experience(list(profile.experience))
    deduped_edu = _dedup_education(list(profile.education))
    deduped_certs = _dedup_certifications(list(profile.certifications))
    deduped_langs = _dedup_languages(list(profile.spoken_languages))
    raw_text = "\n".join(
        chunk for chunk in (profile.raw_cv_text, profile.raw_linkedin_text)
        if chunk
    )
    deduped_langs = _backfill_language_levels(deduped_langs, raw_text)
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
    if len(deduped_certs) != len(profile.certifications):
        logger.info(
            "profile_dedup: collapsed %d duplicate certification rows",
            len(profile.certifications) - len(deduped_certs),
        )
    if len(deduped_langs) != len(profile.spoken_languages):
        logger.info(
            "profile_dedup: collapsed %d duplicate spoken-language rows",
            len(profile.spoken_languages) - len(deduped_langs),
        )
    profile.experience = deduped_exp
    profile.education = deduped_edu
    profile.certifications = deduped_certs
    profile.spoken_languages = deduped_langs
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


def _periods_are_equivalent(a: str, b: str) -> bool:
    """Return True when two free-text date ranges describe the same period.

    Treats ``"06/2023 - 07/2025"`` and ``"června 2023 - července 2025"`` as
    equal because both parse to the same ``(2023, 2025)`` year range.
    Falls back to a whitespace-insensitive string comparison when neither
    side parses (handles cases like ``"ongoing"`` vs ``"ongoing "``).
    """
    a_clean = (a or "").strip()
    b_clean = (b or "").strip()
    if a_clean == b_clean:
        return True
    a_range = _parse_year_range(a_clean)
    b_range = _parse_year_range(b_clean)
    if a_range is not None and b_range is not None:
        return a_range == b_range
    return False


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

    Conflict detection compares parsed year ranges, not raw strings, so we
    do NOT bother the user when the two sources just spell the same period
    differently (``"06/2023 - 07/2025"`` vs ``"června 2023 - července
    2025"`` both parse to ``(2023, 2025)``).
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
        if _periods_are_equivalent(cv_period, linkedin_period):
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
        if _periods_are_equivalent(cv_period, linkedin_period):
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


# ---------------------------------------------------------------------------
# Structural mismatch (CV combines N companies vs. LinkedIn splits them)
# ---------------------------------------------------------------------------

# Separators we treat as "this is a list of companies, not a single brand".
# Order matters: bullets / interpuncts come first so they don't get
# accidentally caught by the more aggressive comma split. ``" / "`` and
# ``" + "`` need surrounding spaces to avoid splitting URLs (``a/b``) and
# trademarks (``C++``).
_COMBINED_COMPANY_SPLIT_RE = re.compile(
    r"\s*(?:·|•|\u2027|\|| / | \+ |, | & | and )\s*",
    re.IGNORECASE,
)


def _split_combined_company(name: str) -> list[str]:
    """Return the list of company names found inside ``name``.

    Returns a list of length one when no separator is found, so callers can
    safely treat the result as "candidate sub-companies".  Empty fragments
    (e.g. trailing comma) are dropped, and each fragment is whitespace-
    stripped. The original ordering is preserved so downstream code can
    still attribute bullets in the order the user wrote them.
    """
    if not name:
        return []
    parts = [p.strip() for p in _COMBINED_COMPANY_SPLIT_RE.split(name)]
    return [p for p in parts if p]


def _is_combined_company(name: str) -> bool:
    """``True`` when ``name`` looks like multiple companies merged into one
    string (``"CreatiWeb · AppYours · IBM"``)."""
    parts = _split_combined_company(name)
    return len(parts) >= 2


def detect_structural_mismatches(
    profile: CandidateProfile,
) -> list[tuple[WorkExperience, list[WorkExperience]]]:
    """Find CV entries that lump multiple companies together when LinkedIn
    has the same period broken into separate rows.

    Returns a list of ``(cv_entry, [linkedin_entry, ...])`` tuples. The
    LinkedIn entries in the inner list are the rows whose company name
    matches one of the sub-companies parsed out of ``cv_entry.company`` AND
    whose date range overlaps the CV period. Only emits a pair when:

    * the CV entry's source is exactly ``"cv"`` (i.e. dedup didn't already
      merge it with a LinkedIn twin),
    * the company string contains a recognised list separator,
    * at least TWO matching LinkedIn entries exist (single-company splits
      aren't really a mismatch worth bothering the user about - the
      regular date-conflict question can already cover those),
    * none of the CV's sub-companies are already represented inside that
      same CV row by virtue of merging (defensive guard against double-asks).
    """
    findings: list[tuple[WorkExperience, list[WorkExperience]]] = []
    for cv_entry in profile.experience:
        if cv_entry.source != "cv":
            continue
        if not _is_combined_company(cv_entry.company):
            continue
        sub_companies = _split_combined_company(cv_entry.company)
        cv_range = _parse_year_range(cv_entry.period)
        matches: list[WorkExperience] = []
        for li_entry in profile.experience:
            if li_entry is cv_entry:
                continue
            if li_entry.source not in ("linkedin", "both"):
                continue
            if not li_entry.company:
                continue
            li_range = _parse_year_range(li_entry.period)
            if not _ranges_overlap(cv_range, li_range):
                continue
            for sub in sub_companies:
                if _names_match(sub, li_entry.company):
                    matches.append(li_entry)
                    break
        if len(matches) >= 2:
            findings.append((cv_entry, matches))
    return findings


def _structural_mismatch_question(
    *,
    cv_entry: WorkExperience,
    linkedin_entries: list[WorkExperience],
) -> ClarifyingQuestion:
    cv_label = _format_experience_label(cv_entry)
    linkedin_labels = ", ".join(
        _format_experience_label(li) for li in linkedin_entries
    )
    qid = f"discrepancy:struct:{cv_entry.id}"
    return ClarifyingQuestion(
        id=qid,
        skill=None,
        question=t(
            "dedup.q.struct_mismatch",
            cv_label=cv_label,
            linkedin_labels=linkedin_labels,
        ),
        why_it_matters=t("dedup.why.struct_mismatch"),
        options=[
            t("dedup.opt.struct_split"),
            t("dedup.opt.struct_merge"),
            t("dedup.opt.struct_manual"),
        ],
        answer_type="single_choice",
    )


def build_structural_mismatch_questions(
    profile: CandidateProfile,
    *,
    max_questions: int = 3,
) -> list[ClarifyingQuestion]:
    """Generate one question per detected structural mismatch.

    The id is ``discrepancy:struct:<cv_entry_id>`` so :func:`apply_structural_choice`
    can map the answer back to the right CV row. Capped at ``max_questions``
    to avoid drowning the user when CV and LinkedIn diverge a lot.
    """
    findings = detect_structural_mismatches(profile)
    questions: list[ClarifyingQuestion] = []
    for cv_entry, linkedin_entries in findings[:max_questions]:
        questions.append(
            _structural_mismatch_question(
                cv_entry=cv_entry, linkedin_entries=linkedin_entries
            )
        )
    return questions


def _structural_choice_kind(answer: str) -> str:
    """Classify the user's free-text answer to a struct_mismatch question.

    Returns one of ``"split"``, ``"merge"``, ``"manual"``. Defaults to
    ``"manual"`` when the answer can't be matched - that's the safest
    no-op outcome (the profile stays as-is and the user can edit it later).
    """
    text = (answer or "").strip().lower()
    if not text:
        return "manual"
    # Prefix-match on the first localised word of each option ("split"
    # / "rozdělit", "keep" / "nechat", "other" / "jiné") so we don't have
    # to compare the full sentence.
    if text.startswith(("split", "rozdel", "rozděl")):
        return "split"
    if text.startswith(("keep", "nechat", "spojit", "merge")):
        return "merge"
    if text.startswith(("other", "jiné", "jine")):
        return "manual"
    # Fallback: full localised string comparison.
    if text == t("dedup.opt.struct_split").lower():
        return "split"
    if text == t("dedup.opt.struct_merge").lower():
        return "merge"
    return "manual"


def apply_structural_choice(
    profile: CandidateProfile,
    cv_entry_id: str,
    answer: str,
) -> CandidateProfile:
    """Apply the user's structural-mismatch decision to ``profile``.

    * ``split``: drop the combined CV row entirely so only the LinkedIn
      per-company rows survive (the CV bullets are already redundant with
      the LinkedIn ones in the typical user case).
    * ``merge``: drop the matching LinkedIn rows so only the combined CV
      row remains - the CV row's bullets stay verbatim.
    * ``manual``: no-op. The user said they'd edit the resume themselves
      so we leave both representations in the profile.

    Mutates the model in place and returns it for fluent chaining.
    """
    kind = _structural_choice_kind(answer)
    if kind == "manual":
        return profile

    cv_entry = next(
        (e for e in profile.experience if e.id == cv_entry_id), None
    )
    if cv_entry is None:
        return profile
    if not _is_combined_company(cv_entry.company):
        return profile

    sub_companies = _split_combined_company(cv_entry.company)
    cv_range = _parse_year_range(cv_entry.period)

    matched_linkedin: list[WorkExperience] = []
    for li_entry in profile.experience:
        if li_entry is cv_entry:
            continue
        if li_entry.source not in ("linkedin", "both"):
            continue
        if not li_entry.company:
            continue
        if not _ranges_overlap(cv_range, _parse_year_range(li_entry.period)):
            continue
        if any(_names_match(sub, li_entry.company) for sub in sub_companies):
            matched_linkedin.append(li_entry)

    if not matched_linkedin:
        return profile

    if kind == "split":
        profile.experience = [
            e for e in profile.experience if e is not cv_entry
        ]
    elif kind == "merge":
        ids_to_drop = {id(e) for e in matched_linkedin}
        profile.experience = [
            e for e in profile.experience if id(e) not in ids_to_drop
        ]
    return profile


__all__ = [
    "dedup_profile",
    "build_source_discrepancy_questions",
    "build_date_conflict_questions",
    "build_structural_mismatch_questions",
    "detect_structural_mismatches",
    "apply_structural_choice",
    "excluded_ids_from_answers",
    "filter_profile_entries",
]


# ---------------------------------------------------------------------------
# Test-only re-exports
# ---------------------------------------------------------------------------
# The test suite imports these private helpers directly so it can pin their
# behaviour without going through dedup_profile. Listed here, not in
# __all__, so star-imports stay narrow.
_TEST_ONLY = (  # noqa: F841 - documentation aid, not used at runtime
    "_dedup_certifications",
    "_dedup_languages",
    "_canonicalise_language_name",
    "_normalize_cert_name",
    "_periods_are_equivalent",
    "_split_combined_company",
    "_is_combined_company",
    "_structural_choice_kind",
    "_extract_language_levels_from_raw_text",
    "_backfill_language_levels",
)
