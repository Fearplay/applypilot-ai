"""Tailored resume generator (delegates to the AI provider)."""
from __future__ import annotations

import logging
import re
from collections.abc import Sequence

from ..ai.base import BaseAIProvider
from ..i18n import t_in
from ..models.candidate import CandidateProfile, GitHubProject
from ..models.documents import (
    RefinedResume,
    ResumeBullet,
    ResumeSection,
    TailoredResume,
)
from ..models.evidence import EvidenceItem
from ..models.job import JobPosting
from ..models.match import AnswersBundle
from .profile_dedup import (
    _extract_seniority,
    _names_match,
    _normalize_name,
    _parse_year_range,
    _ranges_overlap,
    _strip_diacritics,
    _strip_seniority,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Deterministic CS<->EN text translation (education titles, locations,
# experience subtitles, periods). The AI provider does the bulk of the
# language conversion via OUTPUT_LANGUAGE, but it sometimes leaves residual
# strings in the source language - typically Czech location names like
# "Praha metropolitní oblast" inside an otherwise English resume, or the
# reverse "Faculty of Economics ..." inside a Czech resume. These tables +
# the helpers below scrub any leftovers in a deterministic, line-bounded
# pass that never invents content.
# ---------------------------------------------------------------------------
_EDU_TITLE_TRANSLATIONS_CS: dict[str, str] = {
    "high school diploma": "Maturita",
    "diploma": "Diplom",
    "bachelor": "Bakalář (Bc.)",
    "bachelor's": "Bakalář (Bc.)",
    "master": "Magistr (Mgr.)",
    "master's": "Magistr (Mgr.)",
    "information technology": "Informační technologie",
    "computer science": "Informatika",
    "electrical engineering": "Elektrotechnika",
}

_EDU_INSTITUTION_TRANSLATIONS_CS: dict[str, str] = {
    "secondary technical school of electrical engineering": (
        "Střední průmyslová škola elektrotechnická"
    ),
    "secondary technical school": "Střední průmyslová škola",
    "faculty of economics and management": "Provozně ekonomická fakulta",
    "czech university of life sciences": "Česká zemědělská univerzita",
    "prague": "Praha",
}

# Reverse direction: Czech -> English. Applied to titles + subtitles when the
# user picked English as the resume language but the AI left a Czech string
# in education / experience rows. Keys are LOWERCASE diacritics-stripped so
# matching is robust against the AI's exact wording.
_EDU_TITLE_TRANSLATIONS_EN: dict[str, str] = {
    "maturita": "High School Diploma",
    "maturitni zkouska": "High School Diploma",
    "diplom": "Diploma",
    "bakalar": "Bachelor's degree",
    "bakalarsky": "Bachelor's degree",
    "magistr": "Master's degree",
    "magistersky": "Master's degree",
    "inzenyr": "Engineer's degree",
    "doktorsky": "Doctoral degree",
    "informatika": "Computer Science",
    "informacni technologie": "Information Technology",
    "elektrotechnika": "Electrical Engineering",
    "ekonomika": "Economics",
    "ekonomika a management": "Economics and Management",
    "ekonomicka fakulta": "Faculty of Economics",
    "provozne ekonomicka fakulta": "Faculty of Economics and Management",
}

_EDU_INSTITUTION_TRANSLATIONS_EN: dict[str, str] = {
    "stredni prumyslova skola elektrotechnicka": (
        "Secondary Technical School of Electrical Engineering"
    ),
    "stredni prumyslova skola": "Secondary Technical School",
    "ceska zemedelska univerzita": "Czech University of Life Sciences",
    "ceska zemedelska univerzita v praze": (
        "Czech University of Life Sciences Prague"
    ),
    "czu": "Czech University of Life Sciences",
    "spse": "Secondary Technical School of Electrical Engineering",
    "praha": "Prague",
    "plzen": "Pilsen",
}

# Common job-title and employment-type tokens that survive in Czech inside
# experience subtitles (job rows). Matched whole-word, case-insensitive,
# diacritics-insensitive. The values stay capitalised because they end up in
# resume bullets / subtitles.
_EXPERIENCE_TRANSLATIONS_EN: dict[str, str] = {
    "vyvojar": "Developer",
    "vyvojarka": "Developer",
    "stazista": "Intern",
    "staz": "Internship",
    "tester": "Tester",
    "testerka": "Tester",
    "softwarovy inzenyr": "Software Engineer",
    "softwarovy vyvojar": "Software Developer",
    "programator": "Programmer",
    "vedouci": "Lead",
    "junior vyvojar": "Junior Developer",
    "senior vyvojar": "Senior Developer",
    "kontrakt": "Contract",
    "castecny uvazek": "Part-time",
    "plny uvazek": "Full-time",
    "osvc": "Self-employed",
    "brigada": "Part-time",
}

_EXPERIENCE_TRANSLATIONS_CS: dict[str, str] = {
    "developer": "Vývojář",
    "intern": "Stážista",
    "internship": "Stáž",
    "tester": "Tester",
    "software engineer": "Softwarový inženýr",
    "software developer": "Softwarový vývojář",
    "programmer": "Programátor",
    "junior developer": "Junior vývojář",
    "senior developer": "Senior vývojář",
    "contract": "Kontrakt",
    "part-time": "Částečný úvazek",
    "full-time": "Plný úvazek",
    "self-employed": "OSVČ",
    # Mid-sentence English noise that the AI sometimes leaves inside an
    # otherwise Czech bullet / summary ("a acting QA Lead s 4 lety
    # zkušeností"). Mapped to the closest Czech equivalent so the
    # deterministic post-processing pass doesn't have to call out to
    # another model. ``\b``-anchored matching (in
    # :func:`_translate_text_diacritics_insensitive`) keeps these from
    # mis-translating compound English titles like "Tech Lead".
    "acting": "pověřený",
    "interim": "dočasně pověřený",
}

# Months and "present" markers used inside the period field. Mapping spans
# many spellings users actually produce (genitive Czech months from
# LinkedIn exports, abbreviated English months, etc.).
_MONTH_NUMBERS_FROM_CS: dict[str, str] = {
    "ledna": "01", "leden": "01",
    "unora": "02", "unor": "02",
    "brezna": "03", "brezen": "03",
    "dubna": "04", "duben": "04",
    "kvetna": "05", "kveten": "05",
    "cervna": "06", "cerven": "06",
    "cervence": "07", "cervenec": "07",
    "srpna": "08", "srpen": "08",
    "zari": "09",
    "rijna": "10", "rijen": "10",
    "listopadu": "11", "listopad": "11",
    "prosince": "12", "prosinec": "12",
}

_MONTH_NUMBERS_FROM_EN: dict[str, str] = {
    "january": "01", "jan": "01",
    "february": "02", "feb": "02",
    "march": "03", "mar": "03",
    "april": "04", "apr": "04",
    "may": "05",
    "june": "06", "jun": "06",
    "july": "07", "jul": "07",
    "august": "08", "aug": "08",
    "september": "09", "sep": "09", "sept": "09",
    "october": "10", "oct": "10",
    "november": "11", "nov": "11",
    "december": "12", "dec": "12",
}

_PRESENT_MARKERS_CS: tuple[str, ...] = ("soucasnost", "ted", "nyni", "dnes")
_PRESENT_MARKERS_EN: tuple[str, ...] = (
    "present", "current", "now", "ongoing", "to date",
)

_CZECH_DIACRITICS_SET = set("ěščřžýáíéúůťďňĚŠČŘŽÝÁÍÉÚŮŤĎŇ")

_EN_EDU_MARKERS_RE = re.compile(
    r"\b(?:High School|Diploma|Bachelor|Master|Faculty|University|School|"
    r"College|Institute|Academy|Engineering|Technology|Science)\b",
    re.IGNORECASE,
)

# Czech tokens that are reliable signals the text is still in Czech even
# without diacritics (e.g. ASCII LinkedIn exports). Used by ``_looks_czech``
# to decide whether to run the CZ -> EN translation pass.
_CZECH_WORD_MARKERS: tuple[str, ...] = (
    "soucasnost", "stazista", "vyvojar", "praze", "praha", "praze",
    "ceska", "ceske", "ceski", "ledna", "unora", "brezna", "dubna",
    "kvetna", "cervna", "cervence", "srpna", "zari", "rijna",
    "listopadu", "prosince", "univerzita", "fakulta", "metropolitni",
)


def _looks_english(text: str) -> bool:
    if not text:
        return False
    has_diacritics = any(c in _CZECH_DIACRITICS_SET for c in text)
    if has_diacritics:
        return False
    return bool(_EN_EDU_MARKERS_RE.search(text))


def _contains_translation_keys(text: str, table: dict[str, str]) -> bool:
    """Return ``True`` if ``text`` contains any whole-word key from ``table``.

    Used to gate the bullet/summary scrubbing pass: a mostly-Czech bullet
    that happens to have one English word in it (``"a acting QA Lead"``)
    can NOT be detected via :func:`_looks_english` (the bullet is
    diacritics-heavy), but it DOES contain one of the table keys, so we
    use the table itself as the trigger. Keeps the scrub conservative -
    we only touch text we already know how to translate.
    """
    if not text:
        return False
    ascii_lower = _strip_diacritics(text).lower()
    for src in table:
        if not src:
            continue
        pattern = re.compile(rf"\b{re.escape(src)}\b")
        if pattern.search(ascii_lower):
            return True
    return False


def _looks_czech(text: str) -> bool:
    """Return True when ``text`` looks like Czech (diacritics OR a Czech
    keyword that survives ASCII transliteration).

    Used to gate the CZ -> EN translation pass: we only touch a string if
    we're confident it's still in the wrong language so we never overwrite
    a legitimately English bullet that happens to share a token.
    """
    if not text:
        return False
    if any(c in _CZECH_DIACRITICS_SET for c in text):
        return True
    ascii_text = _strip_diacritics(text).lower()
    return any(marker in ascii_text for marker in _CZECH_WORD_MARKERS)


def _translate_edu_text(text: str, table: dict[str, str]) -> str:
    """Replace each table key (case-insensitive) inside ``text`` with its
    value, longest key first so multi-word phrases win over substrings.
    """
    result = text
    for eng, cz in sorted(table.items(), key=lambda kv: -len(kv[0])):
        pattern = re.compile(re.escape(eng), re.IGNORECASE)
        result = pattern.sub(cz, result)
    return result


def _translate_text_diacritics_insensitive(
    text: str, table: dict[str, str]
) -> str:
    """Like :func:`_translate_edu_text` but matches against the diacritics-
    stripped form of ``text``, so a Czech key like ``"vyvojar"`` matches
    ``"Vývojář"`` in the input. Substitutes with the English value, leaving
    surrounding punctuation / casing of unmatched tokens intact.

    Whole-word boundaries are enforced (``\\b``) so ``"present"`` never
    matches inside ``"presentation"``.
    """
    if not text:
        return text
    ascii_lower = _strip_diacritics(text).lower()
    # Find replacements (longest key first) on the ASCII form, then map
    # the spans back to the original ``text`` so we keep the user's casing
    # of any non-matched neighbours.
    spans: list[tuple[int, int, str]] = []
    consumed = [False] * len(ascii_lower)
    for src, dst in sorted(table.items(), key=lambda kv: -len(kv[0])):
        if not src:
            continue
        pattern = re.compile(rf"\b{re.escape(src)}\b", re.IGNORECASE)
        for m in pattern.finditer(ascii_lower):
            start, end = m.start(), m.end()
            if any(consumed[start:end]):
                continue
            spans.append((start, end, dst))
            for i in range(start, end):
                consumed[i] = True
    if not spans:
        return text
    spans.sort()
    out: list[str] = []
    cursor = 0
    for start, end, replacement in spans:
        out.append(text[cursor:start])
        out.append(replacement)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


_MONTH_NUMERIC_GLUE_RE = re.compile(r"\b(\d{1,2})\s+(\d{4})\b")


def _replace_diacritics_insensitive(
    text: str, table: dict[str, str]
) -> str:
    """Replace each table key (matched against diacritics-stripped form
    of ``text``) with its value, longest key first.

    Used by :func:`_translate_period` for both month names and
    'present' markers because real-world inputs can carry full Czech
    diacritics (``"současnost"``) AND ASCII-stripped LinkedIn exports
    (``"soucasnost"``) that the AI sometimes echoes verbatim.
    """
    if not text:
        return text
    ascii_lower = _strip_diacritics(text).lower()
    consumed = [False] * len(ascii_lower)
    spans: list[tuple[int, int, str]] = []
    for src in sorted(table, key=len, reverse=True):
        if not src:
            continue
        pattern = re.compile(rf"\b{re.escape(src)}\b")
        for m in pattern.finditer(ascii_lower):
            start, end = m.start(), m.end()
            if any(consumed[start:end]):
                continue
            spans.append((start, end, table[src]))
            for i in range(start, end):
                consumed[i] = True
    if not spans:
        return text
    spans.sort()
    out: list[str] = []
    cursor = 0
    for start, end, replacement in spans:
        out.append(text[cursor:start])
        out.append(replacement)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def _translate_period(period: str, output_language: str) -> str:
    """Convert Czech month names to two-digit numbers and 'současnost' to
    'present' (or vice versa) in a free-text date range.

    Conservative: if no token in the period matches the month / present
    table for the target language we return the input unchanged. This
    keeps already-correct periods like ``"04/2022 - 06/2023"`` intact and
    only normalises the mixed-language ones the AI sometimes emits.

    After replacing month words with two-digit numbers we also collapse
    the resulting ``"MM yyyy"`` pattern into ``"MM/yyyy"`` so the styled
    HTML / DOCX rendering matches the canonical period format the rest
    of the resume already uses.
    """
    if not period:
        return period
    code = (output_language or "en").strip().lower()
    if code == "en":
        present_table = {marker: "present" for marker in _PRESENT_MARKERS_CS}
        out = _replace_diacritics_insensitive(period, _MONTH_NUMBERS_FROM_CS)
        out = _replace_diacritics_insensitive(out, present_table)
        out = _MONTH_NUMERIC_GLUE_RE.sub(r"\1/\2", out)
        return out
    if code == "cs":
        present_table = {marker: "současnost" for marker in _PRESENT_MARKERS_EN}
        out = _replace_diacritics_insensitive(period, _MONTH_NUMBERS_FROM_EN)
        out = _replace_diacritics_insensitive(out, present_table)
        out = _MONTH_NUMERIC_GLUE_RE.sub(r"\1/\2", out)
        return out
    return period


def _fixup_education_language(resume: TailoredResume, output_language: str) -> None:
    """Translate residual strings to the target language across education,
    experience and project sections.

    The AI is supposed to honour OUTPUT_LANGUAGE, but it occasionally leaves
    a Czech location ("Praha metropolitní oblast"), a Czech month ("ledna
    2021") or a Czech role title ("Vývojář Python") inside a resume the user
    asked for in English. The reverse happens too. We fix both directions
    here so the styled HTML / DOCX export is consistent.
    """
    code = (output_language or "en").strip().lower()
    if code == "cs":
        edu_table = {**_EDU_TITLE_TRANSLATIONS_CS, **_EDU_INSTITUTION_TRANSLATIONS_CS}
        for section in resume.education:
            if _looks_english(section.title):
                section.title = _translate_edu_text(section.title, edu_table)
            if _looks_english(section.subtitle):
                section.subtitle = _translate_edu_text(section.subtitle, edu_table)
            section.period = _translate_period(section.period, "cs")
        for section in resume.experience:
            if section.title and (
                _looks_english(section.title)
                or _contains_translation_keys(section.title, _EXPERIENCE_TRANSLATIONS_CS)
            ):
                section.title = _translate_text_diacritics_insensitive(
                    section.title, _EXPERIENCE_TRANSLATIONS_CS
                )
            if section.subtitle and (
                _looks_english(section.subtitle)
                or _contains_translation_keys(section.subtitle, _EXPERIENCE_TRANSLATIONS_CS)
            ):
                section.subtitle = _translate_text_diacritics_insensitive(
                    section.subtitle, _EXPERIENCE_TRANSLATIONS_CS
                )
            section.period = _translate_period(section.period, "cs")
            # Bullets are normally Czech but the AI sometimes leaves
            # an English noise word ("Acting QA Lead v týmu...") that
            # :func:`_looks_english` can't catch (the diacritics in
            # the rest of the bullet defeat the heuristic). Detect via
            # the translation table itself: if any of our known keys is
            # present, run the substitution pass.
            for bullet in section.bullets:
                if _contains_translation_keys(bullet.text, _EXPERIENCE_TRANSLATIONS_CS):
                    bullet.text = _translate_text_diacritics_insensitive(
                        bullet.text, _EXPERIENCE_TRANSLATIONS_CS
                    )
        # Same trick for the professional summary so "Software QA
        # Engineer a acting QA Lead" doesn't survive in a CZ resume.
        if resume.professional_summary and _contains_translation_keys(
            resume.professional_summary, _EXPERIENCE_TRANSLATIONS_CS
        ):
            resume.professional_summary = _translate_text_diacritics_insensitive(
                resume.professional_summary, _EXPERIENCE_TRANSLATIONS_CS
            )
        return

    if code == "en":
        edu_table = {**_EDU_TITLE_TRANSLATIONS_EN, **_EDU_INSTITUTION_TRANSLATIONS_EN}
        for section in resume.education:
            if _looks_czech(section.title):
                section.title = _translate_text_diacritics_insensitive(
                    section.title, edu_table
                )
            if _looks_czech(section.subtitle):
                section.subtitle = _translate_text_diacritics_insensitive(
                    section.subtitle, edu_table
                )
            section.period = _translate_period(section.period, "en")
        for section in resume.experience:
            if section.title and _looks_czech(section.title):
                section.title = _translate_text_diacritics_insensitive(
                    section.title, _EXPERIENCE_TRANSLATIONS_EN
                )
            if section.subtitle and _looks_czech(section.subtitle):
                section.subtitle = _translate_text_diacritics_insensitive(
                    section.subtitle, _EXPERIENCE_TRANSLATIONS_EN
                )
            section.period = _translate_period(section.period, "en")
            # Symmetric bullet-level scrub for the EN direction so an
            # otherwise English bullet doesn't carry "Stáž v ..." inside.
            for bullet in section.bullets:
                if _contains_translation_keys(bullet.text, _EXPERIENCE_TRANSLATIONS_EN):
                    bullet.text = _translate_text_diacritics_insensitive(
                        bullet.text, _EXPERIENCE_TRANSLATIONS_EN
                    )
        # Project subtitles often carry stack info ("Vývojář Python | ...").
        for section in resume.projects:
            if section.title and _looks_czech(section.title):
                section.title = _translate_text_diacritics_insensitive(
                    section.title, _EXPERIENCE_TRANSLATIONS_EN
                )
            if section.subtitle and _looks_czech(section.subtitle):
                section.subtitle = _translate_text_diacritics_insensitive(
                    section.subtitle, _EXPERIENCE_TRANSLATIONS_EN
                )
        # And the EN summary - mirror the CS scrub so ``"I worked as a
        # Vývojář Python"`` collapses to plain English.
        if resume.professional_summary and _contains_translation_keys(
            resume.professional_summary, _EXPERIENCE_TRANSLATIONS_EN
        ):
            resume.professional_summary = _translate_text_diacritics_insensitive(
                resume.professional_summary, _EXPERIENCE_TRANSLATIONS_EN
            )

# ---------------------------------------------------------------------------
# Career-progression helpers live in `profile_dedup.py` (single source of
# truth shared between the dedup safety net and the re-injection logic
# below). We re-import the names here so the existing module-level usage
# stays unchanged.
# ---------------------------------------------------------------------------


def _pick_fallback_project(projects: Sequence[GitHubProject]) -> GitHubProject | None:
    """Return the most resume-worthy project from ``projects`` or ``None``.

    Ranking is deterministic: highest ``relevance_score`` first, then most
    stars, then longest description / readme so the choice is stable across
    runs. ``None`` when the input is empty.
    """
    if not projects:
        return None
    return max(
        projects,
        key=lambda p: (
            p.relevance_score or 0.0,
            p.stars or 0,
            len(p.description or "") + len((p.readme_excerpt or "")[:200]),
        ),
    )


def _project_to_section(project: GitHubProject) -> ResumeSection:
    """Build a single ``ResumeSection`` for ``project`` using only facts the
    GitHub fetcher already collected. Conservative on text: at most one
    bullet so the AI's nicer wording wins on the next regeneration."""
    subtitle_bits: list[str] = []
    if project.primary_language:
        subtitle_bits.append(project.primary_language)
    if project.stars:
        subtitle_bits.append(f"★ {project.stars}")
    if project.url:
        subtitle_bits.append(project.url)

    bullet_text = (
        project.description
        or project.relevance_reason
        or (project.readme_excerpt or "").split("\n", 1)[0][:200]
        or "Personal GitHub project."
    )
    return ResumeSection(
        title=project.name,
        subtitle=" | ".join(subtitle_bits),
        bullets=[ResumeBullet(text=bullet_text)],
    )


def ensure_projects_section(
    resume: TailoredResume, candidate: CandidateProfile
) -> TailoredResume:
    """Mutate ``resume`` so the Projects section has at least one entry when
    the candidate's GitHub data has any projects to draw from.

    Returns the same resume for fluent chaining. No-op when:

    * ``resume.projects`` is already non-empty (the AI delivered something), OR
    * ``candidate.projects`` is empty (no GitHub repos were fetched).

    Logs at INFO when it injects a fallback so the user can grep for it.
    """
    if resume.projects:
        return resume
    fallback = _pick_fallback_project(candidate.projects)
    if fallback is None:
        return resume
    resume.projects = [_project_to_section(fallback)]
    logger.info(
        "ensure_projects_section: injected fallback project '%s' "
        "(stars=%s, relevance=%.2f) - AI returned an empty Projects section.",
        fallback.name,
        fallback.stars,
        fallback.relevance_score or 0.0,
    )
    return resume


# ---------------------------------------------------------------------------
# Anti-hallucination: drop AI-emitted projects we can't trace back to the
# candidate's GitHub repos or CV / LinkedIn raw text.
# ---------------------------------------------------------------------------

def _normalize_project_title(text: str) -> str:
    """Lowercase, strip diacritics + punctuation; collapse whitespace.

    Used both for matching AI-emitted project titles against
    ``CandidateProfile.projects`` (GitHub) and against the raw CV /
    LinkedIn text. Liberal on what counts as the same name so a small AI
    rewording (e.g. ``"applypilot ai"`` vs ``"ApplyPilot-AI"``) still
    matches the source.
    """
    if not text:
        return ""
    cleaned = _strip_diacritics(text).lower()
    cleaned = re.sub(r"[\.,/\\\(\)\[\]_\-:|\u00b7\u2022]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _project_title_is_evidenced(
    title: str, candidate: CandidateProfile
) -> bool:
    """Return True when ``title`` matches a real GitHub repo or appears in
    the candidate's CV / LinkedIn text.

    Permissive on purpose: a substring match against the diacritics-
    stripped raw text is enough, because users often shorten the project
    name in the CV ("AI workflow agents") relative to the GitHub repo
    name. Restrictive would mean the deterministic safety net rejects
    perfectly valid AI rewordings.

    Empty / 1-character titles are conservatively treated as evidenced
    so the safety net never trips on degenerate cases.
    """
    norm = _normalize_project_title(title)
    if len(norm) < 2:
        return True
    # 1) Exact / substring match against any GitHub project name.
    for project in candidate.projects:
        proj_norm = _normalize_project_title(project.name)
        if not proj_norm:
            continue
        if norm == proj_norm or norm in proj_norm or proj_norm in norm:
            return True
    # 2) Substring match against CV + LinkedIn raw text. ``in`` on the
    # diacritics-stripped lowercase blob is a cheap way to catch any
    # mention of the title regardless of how it was spelled.
    raw = " ".join(
        _strip_diacritics(chunk or "").lower()
        for chunk in (candidate.raw_cv_text, candidate.raw_linkedin_text)
    )
    return norm in raw


def _strip_invented_projects(
    resume: TailoredResume, candidate: CandidateProfile
) -> list[str]:
    """Remove any project the AI emitted whose title can't be traced back
    to the candidate's GitHub repos or CV / LinkedIn text. Returns the
    list of dropped titles so the caller can surface them in the refine
    explanation / log.

    Pure mutation on ``resume.projects``; no other field is touched.
    """
    if not resume.projects:
        return []
    survivors: list[ResumeSection] = []
    dropped: list[str] = []
    for section in resume.projects:
        if _project_title_is_evidenced(section.title, candidate):
            survivors.append(section)
        else:
            dropped.append(section.title or "(untitled project)")
    if dropped:
        logger.warning(
            "_strip_invented_projects: dropped %d unverifiable project(s): %s",
            len(dropped),
            dropped,
        )
        resume.projects = survivors
    return dropped


# ---------------------------------------------------------------------------
# Output-side dedup: collapse duplicate experience / project rows the AI
# sometimes produces (typically when an English run leaves a Czech twin
# behind, or when career-progression rows get split twice).
# ---------------------------------------------------------------------------

def _bullet_key(text: str) -> str:
    """Diacritics-insensitive, whitespace-collapsed bullet key.

    Two bullets compare equal when their ``_bullet_key`` matches; this
    catches "Backend Python E2E" and "backend python e2e" duplicates
    without disturbing genuinely different bullets that share words.
    """
    return re.sub(r"\s+", " ", _strip_diacritics(text or "").strip().lower())


def _dedup_bullets(bullets: list[ResumeBullet]) -> list[ResumeBullet]:
    """Return ``bullets`` with duplicates removed, preserving order."""
    seen: set[str] = set()
    out: list[ResumeBullet] = []
    for b in bullets:
        key = _bullet_key(b.text)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(b)
    return out


# Employment-type tokens that float around inside resume subtitles (e.g.
# "CreatiWeb · AppYours · IBM · Internship") and would otherwise wedge a
# duplicate entry through the dedup key. Stripped during normalisation -
# *not* during display - so two entries differing only by an "Internship"
# suffix collapse to one row in the rendered resume. Lowercase ASCII keys;
# matching is diacritics-insensitive.
_EMPLOYMENT_TYPE_DEDUP_TOKENS: frozenset[str] = frozenset({
    "internship",
    "stage",
    "staz",
    "staze",
    "stazista",
    "stazistka",
    "intern",
    "trainee",
    "contract",
    "contractor",
    "kontrakt",
    "kontraktor",
    "freelance",
    "freelancer",
    "osvc",
    "self_employed",
    "selfemployed",
    "part",
    "parttime",
    "parttimer",
    "full",
    "fulltime",
    "castecny",
    "castecnaprace",
    "uvazek",
    "plny",
    "temporary",
    "temporarily",
    "docasny",
    "docasna",
    "brigada",
    "brigadnik",
})


def _normalize_section_subtitle(text: str) -> str:
    """Like :func:`_normalize_name` but additionally drops employment-type
    tokens so "CreatiWeb · AppYours · IBM · Internship" and
    "CreatiWeb - AppYours - IBM" produce the same canonical form.
    """
    base = _normalize_name(text)
    if not base:
        return ""
    tokens = [
        tok for tok in base.split()
        if tok and tok not in _EMPLOYMENT_TYPE_DEDUP_TOKENS
    ]
    return " ".join(tokens)


def _experience_dedup_key(section: ResumeSection) -> tuple[str, str, tuple[int, int] | None]:
    """Stable key used to identify duplicate experience rows.

    Tuple of ``(seniority_prefix, normalised_subtitle/title, year_range)``.
    Subtitle is preferred because the company name is the most reliable
    duplicate signal; falls back to a normalised title when the AI omitted
    the subtitle. The year range is parsed loosely so '06/2023 - 07/2025'
    and 'června 2023 - července 2025' produce the same key.

    Employment-type suffixes ('Internship', 'Stáž', 'Contract', ...) are
    stripped from the subtitle before normalising so e.g. "CreatiWeb -
    AppYours - IBM - Internship" and "CreatiWeb · AppYours · IBM" share
    the same key. Without this strip, a single role described once as
    "Internship" and once without the label would survive dedup as two
    siblings.
    """
    title = section.title or ""
    subtitle = section.subtitle or ""
    seniority = _extract_seniority(title)
    name_basis = subtitle or title
    norm = _normalize_section_subtitle(name_basis)
    return seniority, norm, _parse_year_range(section.period or "")


def _section_norms(section: ResumeSection) -> tuple[str, str]:
    """Return ``(normalised_title, normalised_subtitle)`` for fuzzy matching.

    Uses :func:`_normalize_section_subtitle` on both fields so the same
    employment-type stripping that protects :func:`_experience_dedup_key`
    also protects the substring/overlap fallback in
    :func:`_experience_sections_match`.
    """
    return (
        _normalize_section_subtitle(section.title or ""),
        _normalize_section_subtitle(section.subtitle or ""),
    )


def _experience_sections_match(a: ResumeSection, b: ResumeSection) -> bool:
    """Return ``True`` when ``a`` and ``b`` describe the same role.

    Tighter than tuple equality: two sections match when they share the
    same seniority prefix, their year ranges overlap, AND either their
    normalised titles OR their normalised subtitles match via the
    substring / token-overlap heuristic in :func:`_names_match`.

    The double-OR is what catches the "Developer (Python · Chatbot ·
    Game dev)" case where two AI-emitted variants (one English, one
    Czech) carry slightly different separators and an extra "Internship"
    suffix - they share the same title and almost the same subtitle, so
    either path resolves them as the same role. Without this, the
    section dedup compared exact tuple keys and silently kept both
    twins.
    """
    sen_a = _extract_seniority(a.title or "")
    sen_b = _extract_seniority(b.title or "")
    if sen_a != sen_b:
        return False
    range_a = _parse_year_range(a.period or "")
    range_b = _parse_year_range(b.period or "")
    if range_a is not None and range_b is not None:
        if not _ranges_overlap(range_a, range_b):
            return False
    title_a, sub_a = _section_norms(a)
    title_b, sub_b = _section_norms(b)
    if title_a and title_b and _names_match(title_a, title_b):
        return True
    if sub_a and sub_b and _names_match(sub_a, sub_b):
        return True
    return False


def _merge_experience_sections(
    primary: ResumeSection, secondary: ResumeSection
) -> ResumeSection:
    """Combine two duplicate experience rows into the richer one.

    Picks the section with more bullets as the base, merges bullets in
    order without duplicates, and keeps the longer subtitle / period when
    one side is empty.
    """
    if len(secondary.bullets) > len(primary.bullets):
        primary, secondary = secondary, primary
    merged_bullets = _dedup_bullets(list(primary.bullets) + list(secondary.bullets))
    return primary.model_copy(update={
        "title": primary.title or secondary.title,
        "subtitle": primary.subtitle or secondary.subtitle,
        "period": primary.period or secondary.period,
        "bullets": merged_bullets,
    })


_CZECH_BULLET_KEYWORDS: tuple[str, ...] = (
    "skolni", "stage", "staze", "stazi", "stazista", "vyvoj",
    "tymu", "tym", "clenny", "clennem", "nasazeny", "nasazena",
    "produkce", "vyvojar", "spravoval", "spravoval", "prace",
    "pracoval", "pracovala", "vedl", "vedla", "absolvoval",
    "absolvovala", "vytvoril", "vytvorila", "navrhl", "navrhla",
    "implementoval", "implementovala", "testoval", "testovala",
)


def _bullet_language_signal(text: str) -> str:
    """Best-effort 'cs' / 'en' / '' classifier for a single bullet.

    Used by :func:`_dedup_cross_language_bullets` to decide which twin
    of a near-duplicate pair should win when the user picked an
    OUTPUT_LANGUAGE. Returns ``''`` when neither side has a clear
    signal so the caller can fall back to insertion order rather than
    guessing.
    """
    if not text:
        return ""
    if any(c in _CZECH_DIACRITICS_SET for c in text):
        return "cs"
    ascii_lower = _strip_diacritics(text).lower()
    tokens = set(re.findall(r"[a-z]+", ascii_lower))
    if any(kw in tokens for kw in _CZECH_BULLET_KEYWORDS):
        return "cs"
    if _EN_EDU_MARKERS_RE.search(text):
        return "en"
    # Token-overlap fallback: a bullet stuffed with stop-words like
    # "the", "in", "for", "with" is almost certainly English. We don't
    # bother with a heavy NLP check because the dedup is conservative -
    # if both sides are flagged as 'en' or both as 'cs', no replacement
    # happens and both bullets survive untouched.
    en_stopwords = {
        "the", "and", "for", "with", "to", "of", "in", "on",
        "an", "as", "by", "at", "from", "into", "team", "person",
    }
    if tokens & en_stopwords:
        return "en"
    return ""


def _bullet_similarity_key(text: str) -> set[str]:
    """Set of length-3+ ASCII tokens used to compare cross-language bullets.

    Cross-language twins typically share a long English keyword nucleus
    ('Python', 'IBM', 'Watson', 'chatbot', 'game', 'development',
    'Selenium') even when the surrounding prose is Czech. Comparing
    those nuclei lets us collapse "\u0160koln\u00ed st\u00e1\u017ee zam\u011b\u0159en\u00e9 na "
    "Python game development a IBM Watson chatbot v 2\u010dlenn\u00e9m t\u00fdmu" with
    "Python game development" + "IBM Watson chatbot in a 2-person team".
    """
    if not text:
        return set()
    ascii_lower = _strip_diacritics(text).lower()
    return {tok for tok in re.findall(r"[a-z0-9]{3,}", ascii_lower)}


# Word-count threshold below which a bullet is considered a "fragment"
# rather than a full sentence. Used by the cross-language dedup as a
# secondary signal: when the section has at least one rich
# OUTPUT_LANGUAGE bullet, any short other-language bullet next to it is
# almost always a translation fragment the AI sprinkled in by mistake.
_BULLET_FRAGMENT_WORD_LIMIT = 8


def _bullet_word_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def _dedup_cross_language_bullets(
    section: ResumeSection, output_language: str
) -> None:
    """Drop other-language twin bullets within a single section.

    The AI sometimes emits a Czech bullet describing a role and then
    follows it with one or more English fragments that say the SAME
    thing in fewer words ("\u0160koln\u00ed st\u00e1\u017ee zam\u011b\u0159en\u00e9 na Python "
    "game development a IBM Watson chatbot v 2\u010dlenn\u00e9m t\u00fdmu" + "Python "
    "game development" + "IBM Watson chatbot in a 2-person team" +
    "School internships"). The standard ``_dedup_bullets`` only catches
    byte-identical duplicates, so this pass complements it with two
    heuristics:

    1. Keyword-overlap twins: when two bullets share at least 2 long
       keyword tokens AND the smaller side is >= 50% covered, drop the
       one whose language doesn't match ``output_language``. Without a
       clear language signal we keep the longer / earlier bullet.
    2. Fragment guard: when the section has at least ONE clearly
       OUTPUT_LANGUAGE bullet that is "rich" (>=
       ``_BULLET_FRAGMENT_WORD_LIMIT`` words), drop every short
       (< limit words) bullet that looks like the OTHER language.
       This catches cross-language fragments the AI tacked on as
       'extra detail' even when they have no token overlap with the
       rich bullet ("\u0160koln\u00ed st\u00e1\u017ee" vs "School internships" -
       semantically identical but they share zero ASCII tokens).

    Conservative on purpose: nothing is dropped when the section is
    monolingual (every bullet shares the OUTPUT_LANGUAGE) or when no
    rich OUTPUT_LANGUAGE bullet exists yet.
    """
    if len(section.bullets) < 2 or not output_language:
        return
    code = (output_language or "en").strip().lower()
    if code not in ("cs", "en"):
        return
    other_lang = "en" if code == "cs" else "cs"
    keys = [_bullet_similarity_key(b.text) for b in section.bullets]
    languages = [_bullet_language_signal(b.text) for b in section.bullets]
    word_counts = [_bullet_word_count(b.text) for b in section.bullets]
    keep = [True] * len(section.bullets)

    # Pass 1: keyword-overlap twins.
    for i, key_i in enumerate(keys):
        if not keep[i] or len(key_i) < 2:
            continue
        for j in range(i + 1, len(keys)):
            if not keep[j]:
                continue
            key_j = keys[j]
            if len(key_j) < 2:
                continue
            shared = key_i & key_j
            if len(shared) < 2:
                continue
            smaller = min(len(key_i), len(key_j))
            if len(shared) / smaller < 0.5:
                continue
            lang_i = languages[i]
            lang_j = languages[j]
            if lang_i == code and lang_j == other_lang:
                keep[j] = False
            elif lang_j == code and lang_i == other_lang:
                keep[i] = False
                break
            elif lang_i == lang_j:
                if len(section.bullets[i].text) >= len(section.bullets[j].text):
                    keep[j] = False
                else:
                    keep[i] = False
                    break
            else:
                if len(section.bullets[i].text) >= len(section.bullets[j].text):
                    keep[j] = False
                else:
                    keep[i] = False
                    break

    # Pass 2: fragment guard. Only fires when the section has at least
    # one rich OUTPUT_LANGUAGE bullet that survived pass 1 - that's the
    # signal the section is "really" in OUTPUT_LANGUAGE and the other-
    # language fragments are noise the AI sprinkled in.
    has_rich_output_lang = any(
        keep[i]
        and languages[i] == code
        and word_counts[i] >= _BULLET_FRAGMENT_WORD_LIMIT
        for i in range(len(section.bullets))
    )
    if has_rich_output_lang:
        for i in range(len(section.bullets)):
            if not keep[i]:
                continue
            if languages[i] != other_lang:
                continue
            if word_counts[i] >= _BULLET_FRAGMENT_WORD_LIMIT:
                continue
            keep[i] = False

    # Pass 3: rescue-translate. If pass 2 found no rich OUTPUT_LANGUAGE
    # bullet to dedupe against AND the majority of surviving bullets are
    # still in the OTHER language (e.g. AI generated an entire CZ
    # section's experience entry with English bullets), TRANSLATE the
    # other-language bullets in-place using the EN<->CZ mapping table
    # instead of dropping them. This preserves the content the user wrote
    # in their CV - the bug report screenshot showed a Czech resume with
    # English bullets where the safety net dropped them entirely and
    # left the section bullet-less, which was even worse than mixed
    # language. Only runs for cs <-> en today; no-op for any other
    # output_language.
    if not has_rich_output_lang and code == "cs":
        other_count = sum(
            1
            for i, lang in enumerate(languages)
            if keep[i] and lang == other_lang
        )
        kept_total = sum(1 for k in keep if k)
        if kept_total > 0 and other_count / kept_total > 0.5:
            translated = 0
            for i, bullet in enumerate(section.bullets):
                if not keep[i] or languages[i] != other_lang:
                    continue
                rewritten = _translate_text_diacritics_insensitive(
                    bullet.text, _EXPERIENCE_TRANSLATIONS_CS
                )
                if rewritten != bullet.text:
                    bullet.text = rewritten
                    translated += 1
            if translated:
                logger.info(
                    "_dedup_cross_language_bullets: pass 3 translated %d "
                    "%s bullet(s) into %s in section %r instead of "
                    "dropping them.",
                    translated,
                    other_lang,
                    code,
                    section.title or section.subtitle or "?",
                )

    survivors = [b for b, k in zip(section.bullets, keep) if k]
    if len(survivors) != len(section.bullets):
        logger.info(
            "_dedup_cross_language_bullets: dropped %d cross-language "
            "twin bullet(s) from section %r (kept %d).",
            len(section.bullets) - len(survivors),
            section.title or section.subtitle or "?",
            len(survivors),
        )
        section.bullets = survivors


def _dedup_resume_sections(
    resume: TailoredResume, output_language: str = "en"
) -> None:
    """Collapse duplicate experience / project rows and dedup bullets per
    section in place.

    Seniority guard mirrors the candidate-profile dedup pass: rows with
    different seniority prefixes (Junior / Senior / Lead / ...) are
    NEVER merged even when the company + period match - they're real
    career progression entries that must stay separate.

    Cross-language bullet dedup runs in the same pass so a section with
    a rich Czech bullet followed by short English twins ("\u0160koln\u00ed st\u00e1\u017ee
    ... Python game development a IBM Watson chatbot v 2\u010dlenn\u00e9m
    t\u00fdmu" + "Python game development" + "IBM Watson chatbot in a
    2-person team") collapses to just the OUTPUT_LANGUAGE bullet. The
    cheap exact-dup pass cannot catch these because the surface text
    differs; the keyword-overlap heuristic in
    :func:`_dedup_cross_language_bullets` does.
    """
    # Experience: greedy O(n^2) merge with a two-tier match.
    # 1) Exact dedup-key equality is the cheap fast-path that catches the
    #    common case where the AI emitted two truly identical rows.
    # 2) The fuzzy fallback - :func:`_experience_sections_match` - catches
    #    cross-language twins where one row carries an extra employment-
    #    type suffix like "Internship" or uses different separator
    #    characters (·, -, |). Without this fallback, the post-AI dedup
    #    silently kept both copies side by side in the rendered resume.
    new_experience: list[ResumeSection] = []
    for section in resume.experience:
        _dedup_cross_language_bullets(section, output_language)
        section.bullets = _dedup_bullets(section.bullets)
        key = _experience_dedup_key(section)
        merged = False
        for i, existing in enumerate(new_experience):
            if _experience_dedup_key(existing) == key:
                new_experience[i] = _merge_experience_sections(existing, section)
                merged = True
                break
            if _experience_sections_match(existing, section):
                new_experience[i] = _merge_experience_sections(existing, section)
                merged = True
                break
        if not merged:
            new_experience.append(section)
    if len(new_experience) != len(resume.experience):
        logger.info(
            "_dedup_resume_sections: collapsed %d duplicate experience row(s).",
            len(resume.experience) - len(new_experience),
        )
    resume.experience = new_experience

    # Projects: dedup by normalised title only; bullets per section.
    new_projects: list[ResumeSection] = []
    seen_project_keys: set[str] = set()
    for section in resume.projects:
        _dedup_cross_language_bullets(section, output_language)
        section.bullets = _dedup_bullets(section.bullets)
        key = _normalize_project_title(section.title)
        if key and key in seen_project_keys:
            continue
        if key:
            seen_project_keys.add(key)
        new_projects.append(section)
    if len(new_projects) != len(resume.projects):
        logger.info(
            "_dedup_resume_sections: collapsed %d duplicate project row(s).",
            len(resume.projects) - len(new_projects),
        )
    resume.projects = new_projects

    # Education: dedup bullets only; ensure_experience_section equivalent
    # for education isn't a thing because education rows are strict-merged
    # earlier in profile_dedup, so duplicates here should be very rare.
    for section in resume.education:
        _dedup_cross_language_bullets(section, output_language)
        section.bullets = _dedup_bullets(section.bullets)


# ---------------------------------------------------------------------------
# Education completeness: drop rows with no institution
# ---------------------------------------------------------------------------

# Tokens that pad a degree title without contributing real information when
# the institution is missing ("Informatika studies", "Computer Science
# studium"). Stripped before the completeness check so an entry whose
# title is just "<field> studies" / "<field> studium" is still recognised
# as broken.
_EDUCATION_PADDING_TOKENS: frozenset[str] = frozenset({
    "studies", "studium", "studia", "studie", "study",
    "obor", "field", "of",
})

# Substrings (diacritics-stripped, lowercased) that name an institution
# inside a degree title - their presence tells the completeness check
# that the row already carries the school name and is fine even when
# ``subtitle`` is empty (e.g. someone put 'Bachelor of Computer Science,
# Czech University' all in one field).
_INSTITUTION_MARKER_TOKENS: tuple[str, ...] = (
    "university", "univerzita", "univerzity",
    "fakulta", "fakulty", "faculty",
    "skola", "skoly", "school",
    "akademie", "academy",
    "institute", "institut",
    "college", "konzervator", "conservatory",
    "spse", "cvut", "cuni", "vse", "czu", "vsb",
    "muni", "upol", "tul", "vsem", "vsfs",
)


def _education_title_is_just_field(title: str) -> bool:
    """``True`` when ``title`` is a bare field-of-study with no school name.

    Used to detect AI-emitted rows like ``"Informatika studies"`` /
    ``"Computer Science"`` that are missing the institution. We treat
    these as broken (the user can't tell which school they belong to)
    and the surrounding logic drops them entirely rather than rendering
    a half-baked education row.

    A title is "broken" when:

    * after stripping padding words ('studies', 'studium', ...) and
      common separator punctuation it has no recognised institution
      marker token (university, fakulta, akademie, well-known abbrev),
      AND
    * it does not contain a 4-digit year (a year token usually means
      the user wrote a free-form one-line entry like "BSc Informatics
      2019-2023 Charles University" - too risky to drop blindly).

    The check is conservative: we only return True when we're confident
    the row is missing an institution. Anything else is considered
    keep-able.
    """
    if not title:
        return True
    cleaned = _strip_diacritics(title).lower()
    if re.search(r"\b(19|20)\d{2}\b", cleaned):
        return False
    if "," in cleaned:
        # A comma suggests "Degree, Institution" - keep it; even if the
        # second half is short it still gives the renderer something to
        # show and we never want to delete real user content.
        return False
    cleaned_compact = re.sub(r"[\.,/\\\(\)\[\]_\-:|]", " ", cleaned)
    if any(marker in cleaned_compact for marker in _INSTITUTION_MARKER_TOKENS):
        return False
    tokens = [t for t in cleaned_compact.split() if t]
    if not tokens:
        return True
    non_padding = [t for t in tokens if t not in _EDUCATION_PADDING_TOKENS]
    # When stripping the padding words leaves nothing, the title was
    # purely 'studies' / 'studium' with no field at all.
    if not non_padding:
        return True
    # A short title (<=3 non-padding tokens) with no institution marker,
    # no year and no comma is almost always a bare field-of-study like
    # "Informatika", "Informatika studies", "Computer Science" or
    # "Computer Science studium". Drop it.
    return len(non_padding) <= 3


def _strip_incomplete_education(resume: TailoredResume) -> list[str]:
    """Remove education rows that have no institution name.

    Returns the dropped titles so the caller can include them in the
    user-facing explanation. The resume's ``education`` list is mutated
    in place.

    Conservative: a row survives whenever it has a non-empty
    ``subtitle`` (the institution slot) OR a title that obviously
    carries the institution itself (e.g. someone who put "Charles
    University" in the title because they had no separate institution
    field). Only rows whose title is a bare field-of-study AND whose
    subtitle is empty get dropped.
    """
    if not resume.education:
        return []
    survivors: list[ResumeSection] = []
    dropped: list[str] = []
    for section in resume.education:
        subtitle = (section.subtitle or "").strip()
        title = (section.title or "").strip()
        if subtitle:
            survivors.append(section)
            continue
        if title and not _education_title_is_just_field(title):
            survivors.append(section)
            continue
        dropped.append(title or "(untitled education row)")
    if dropped:
        logger.warning(
            "_strip_incomplete_education: dropped %d education row(s) "
            "without an institution name: %s",
            len(dropped),
            dropped,
        )
        resume.education = survivors
    return dropped


def _enforce_bullet_floor(
    resume: TailoredResume, candidate: CandidateProfile
) -> None:
    """Re-inject bullets the AI dropped from roles it kept.

    Matches resume sections back to ``candidate.experience`` rows using
    diacritics-insensitive comparison and the seniority guard, so the
    bullets of a 'Junior Software QA Engineer' row never accidentally
    spill into the 'Senior Software QA Engineer' section.
    """
    if not candidate.experience:
        return
    for section in resume.experience:
        s_title = _strip_diacritics((section.title or "").strip().lower())
        s_sub = _strip_diacritics((section.subtitle or "").strip().lower())
        s_seniority = _extract_seniority(s_title)
        match = None
        for entry in candidate.experience:
            e_title = _strip_diacritics((entry.title or "").strip().lower())
            e_company = _strip_diacritics((entry.company or "").strip().lower())
            e_seniority = _extract_seniority(e_title)
            if e_seniority != s_seniority:
                continue
            if e_title and e_title in s_title:
                match = entry
                break
            if e_company and e_company in s_sub:
                match = entry
                break
        if match is None or not match.bullets:
            continue
        floor = min(len(match.bullets), 4)
        if len(section.bullets) >= floor:
            continue
        existing_texts = {b.text.strip().lower() for b in section.bullets}
        for original in match.bullets:
            if len(section.bullets) >= floor:
                break
            if original.strip().lower() not in existing_texts:
                section.bullets.append(ResumeBullet(text=original))
                existing_texts.add(original.strip().lower())


def _norm_text(text: str) -> str:
    """Diacritics-insensitive lowercase normaliser used by every safety
    net below so 'Vývojář Python' and 'Vyvojar Python' compare equal.
    """
    return _strip_diacritics((text or "").strip().lower())


def _find_experience_match(resume: TailoredResume, entry) -> bool:
    """Return True when ``resume.experience`` already contains a row that
    represents ``entry``, using diacritics-insensitive comparison and the
    seniority guard.
    """
    e_title = _norm_text(entry.title)
    e_company = _norm_text(entry.company)
    e_seniority = _extract_seniority(e_title)
    for s in resume.experience:
        s_title = _norm_text(s.title)
        s_sub = _norm_text(s.subtitle)
        s_seniority = _extract_seniority(s_title)
        # Hard rule: never treat two rows with mismatched seniority as
        # the same entry. A 'Junior Software QA Engineer' must NOT be
        # silently merged into a 'Software QA Engineer' row, even when
        # the company matches.
        if e_seniority != s_seniority:
            continue
        if e_title and e_title in s_title:
            return True
        e_base = _strip_seniority(e_title).lower()
        s_base = _strip_seniority(s_title).lower()
        if e_base and s_base and e_base in s_base:
            return True
        if e_company and e_company in s_sub:
            return True
    return False


def _candidate_entry_key(entry) -> tuple[str, str, tuple[int, int] | None]:
    """Return the same canonical key shape used for resume sections.

    Lets callers compare a :class:`WorkExperience` (candidate side) against
    a :class:`ResumeSection` (output side) without having to materialise a
    fake ``ResumeSection`` first.
    """
    title = entry.title or ""
    company = entry.company or ""
    seniority = _extract_seniority(title)
    name_basis = company or title
    norm = _normalize_section_subtitle(name_basis)
    return seniority, norm, _parse_year_range(entry.period or "")


def _compute_missing_experience(
    resume: TailoredResume,
    candidate: CandidateProfile,
    *,
    skip_keys: set[tuple[str, str, tuple[int, int] | None]] | None = None,
) -> list[ResumeSection]:
    """Return the candidate experience rows that are NOT yet in ``resume``.

    Pure function: never mutates either argument. Callers (e.g. the
    refine safety net) need this to know what they're about to inject so
    they can tell the user about it.

    ``skip_keys`` is the optional set of canonical experience keys
    (produced by :func:`_experience_dedup_key` on a section or
    :func:`_candidate_entry_key` on a candidate row) that should NEVER be
    re-injected even when the AI dropped them. The refine flow uses this
    to honour an explicit "smaž / delete" instruction without losing the
    rest of the safety net's protection on accidentally-dropped rows.
    """
    if not candidate.experience:
        return []
    skip_keys = skip_keys or set()
    missing: list[ResumeSection] = []
    for entry in candidate.experience:
        if _find_experience_match(resume, entry):
            continue
        if _candidate_entry_key(entry) in skip_keys:
            # User explicitly asked to delete this row in the refine
            # feedback - respect their decision instead of re-adding it.
            continue
        subtitle_bits: list[str] = []
        if entry.company:
            subtitle_bits.append(entry.company)
        missing.append(ResumeSection(
            title=entry.title,
            subtitle=" | ".join(subtitle_bits),
            period=entry.period,
            bullets=[ResumeBullet(text=b) for b in entry.bullets],
        ))
    return missing


def ensure_experience_section(
    resume: TailoredResume,
    candidate: CandidateProfile,
    output_language: str = "en",
    *,
    skip_keys: set[tuple[str, str, tuple[int, int] | None]] | None = None,
) -> TailoredResume:
    """Re-inject any candidate experience rows the AI silently dropped.

    Uses seniority-aware matching so "Junior Software QA Engineer" is NOT
    considered a match for "Software QA Engineer" -- career progression
    entries are treated as distinct rows.

    ``skip_keys`` is forwarded to :func:`_compute_missing_experience` so
    the refine flow can keep rows the user explicitly asked to delete
    from sneaking back in.
    """
    missing = _compute_missing_experience(resume, candidate, skip_keys=skip_keys)
    if missing:
        logger.warning(
            "ensure_experience_section: re-injected %d experience rows the AI dropped: %s",
            len(missing),
            [m.title for m in missing],
        )
        resume.experience.extend(missing)
    return resume


def _backfill_periods(
    resume: TailoredResume, candidate: CandidateProfile
) -> None:
    """Fill in empty period fields on resume sections from candidate data.

    Same diacritics + seniority handling as the other safety nets so we
    don't backfill a Senior section with the Junior period from a year
    earlier.
    """
    if candidate.experience:
        for section in resume.experience:
            if section.period:
                continue
            s_title = _strip_diacritics((section.title or "").strip().lower())
            s_sub = _strip_diacritics((section.subtitle or "").strip().lower())
            s_seniority = _extract_seniority(s_title)
            for entry in candidate.experience:
                e_title = _strip_diacritics((entry.title or "").strip().lower())
                e_company = _strip_diacritics((entry.company or "").strip().lower())
                e_seniority = _extract_seniority(e_title)
                if e_seniority != s_seniority:
                    continue
                if (e_title and e_title in s_title) or (
                    e_company and e_company in s_sub
                ):
                    if entry.period:
                        section.period = entry.period
                    break

    if not candidate.education:
        return
    for section in resume.education:
        if section.period:
            continue
        s_title = _strip_diacritics((section.title or "").strip().lower())
        s_sub = _strip_diacritics((section.subtitle or "").strip().lower())
        for entry in candidate.education:
            e_inst = _strip_diacritics((entry.institution or "").strip().lower())
            e_degree = _strip_diacritics((entry.degree or "").strip().lower())
            if (e_inst and e_inst in s_sub) or (e_degree and e_degree in s_title):
                if entry.period:
                    section.period = entry.period
                break


def generate_tailored_resume(
    provider: BaseAIProvider,
    job: JobPosting,
    candidate: CandidateProfile,
    answers: AnswersBundle | None = None,
    evidence: Sequence[EvidenceItem] = (),
    output_language: str = "en",
) -> TailoredResume:
    answers = answers or AnswersBundle()
    resume = provider.generate_resume(
        job, candidate, answers, evidence, output_language=output_language
    )
    # Order matters: translate residual strings first so dedup compares the
    # post-translation form (otherwise a Czech twin and an English twin
    # would never match), THEN dedup (which also strips cross-language
    # twin bullets in OUTPUT_LANGUAGE), THEN re-inject missing rows from
    # the candidate, THEN strip invented projects (so safety-net
    # additions are real GitHub repos), THEN strip incomplete education
    # rows the AI emitted without an institution, THEN backfill periods,
    # THEN ensure at least one project survived.
    _fixup_education_language(resume, output_language)
    _dedup_resume_sections(resume, output_language)
    _enforce_bullet_floor(resume, candidate)
    ensure_experience_section(resume, candidate, output_language)
    # Safety-net rows are copied from the structured candidate profile, which
    # may still be in the source language. Run the output cleanup again so
    # injected rows get translated and collapsed with any AI-emitted twin.
    _fixup_education_language(resume, output_language)
    _dedup_resume_sections(resume, output_language)
    _strip_invented_projects(resume, candidate)
    _strip_incomplete_education(resume)
    _backfill_periods(resume, candidate)
    _fixup_education_language(resume, output_language)
    _dedup_resume_sections(resume, output_language)
    # Mirror the candidate's languages onto the resume on the first
    # render so subsequent refines have a place to apply edits like
    # "změň němčinu na B2" without losing the rest of the list. Only
    # populate when the AI didn't already supply a list - the AI's
    # version may include localised wording the user prefers.
    if not resume.spoken_languages and candidate.spoken_languages:
        resume.spoken_languages = list(candidate.spoken_languages)
    return ensure_projects_section(resume, candidate)


# ---------------------------------------------------------------------------
# Refine flow: deterministic safety net + inline explanation
# ---------------------------------------------------------------------------

# Words that signal the user wants something ADDED to the resume rather than
# removed. Both English and Czech variants are listed because the GUI is
# bilingual and users routinely mix the two in feedback.
_REFINE_ADD_INTENT_KEYWORDS: tuple[str, ...] = (
    # English
    "missing", "add", "include", "forgot", "where is", "where's",
    # Czech (with and without diacritics, several inflected forms)
    "chybi", "chybí", "vynechal", "vynechala", "vynechals", "vynechalas",
    "zapomnel", "zapomněl", "zapomnels", "zapomněls", "pridej", "přidej",
    "doplnit", "doplň", "doplnil",
)

# Words that signal the user wants something REMOVED from the resume. When
# any of these appear in the feedback, the safety net stops re-injecting
# experience rows the AI deliberately dropped between the current and the
# refined resume - otherwise "smaž tu pozici" would be silently undone by
# :func:`ensure_experience_section`.
_REFINE_DELETE_INTENT_KEYWORDS: tuple[str, ...] = (
    # English
    "delete", "remove", "drop", "kick out", "take out", "get rid",
    "exclude", "omit", "strike", "scrap",
    # Czech (with and without diacritics, several inflected forms)
    "smaz", "smaž", "smazat", "smazal", "smazala", "smazals", "smazalas",
    "odstran", "odstraň", "odstranit", "odstranil", "odstranila",
    "odeber", "odebrat", "odebral", "odebrala",
    "vymaz", "vymaž", "vymazat", "vymazal", "vymazala",
    "zrus", "zruš", "zrušit", "zrusil", "zrušil", "zrusila", "zrušila",
    "vyradit", "vyřadit", "vyradil", "vyřadil",
)


def _feedback_has_add_intent(feedback: str) -> bool:
    """Return True when ``feedback`` contains an "ADD this row" keyword."""
    text = _strip_diacritics((feedback or "").lower())
    return any(
        _strip_diacritics(kw.lower()) in text
        for kw in _REFINE_ADD_INTENT_KEYWORDS
    )


def _feedback_has_delete_intent(feedback: str) -> bool:
    """Return True when ``feedback`` contains a "REMOVE this row" keyword.

    Used by the refine flow to decide whether the experience safety net
    should keep its hands off rows the AI intentionally dropped. We
    intentionally use whole-string substring matching (after diacritic
    stripping) instead of token-bounded regexes so e.g. "smazal" inside a
    longer Czech sentence still matches via the "smaz" prefix.
    """
    text = _strip_diacritics((feedback or "").lower())
    return any(
        _strip_diacritics(kw.lower()) in text
        for kw in _REFINE_DELETE_INTENT_KEYWORDS
    )


def _intentionally_dropped_experience(
    current_resume: TailoredResume,
    refined_resume: TailoredResume,
) -> set[tuple[str, str, tuple[int, int] | None]]:
    """Return canonical keys for experience rows the AI removed in refine.

    Compares the resume the user looked at when typing the feedback
    against the resume the AI just produced. Any key present in
    ``current_resume`` but absent from ``refined_resume`` is treated as
    an intentional deletion - the refine flow then asks the safety net
    to leave those keys alone instead of re-injecting them from the
    candidate profile (the user said 'smaž' / 'delete', so honouring
    that decision matters).
    """
    refined_keys: set[tuple[str, str, tuple[int, int] | None]] = {
        _experience_dedup_key(s) for s in refined_resume.experience
    }
    dropped: set[tuple[str, str, tuple[int, int] | None]] = set()
    for s in current_resume.experience:
        key = _experience_dedup_key(s)
        if key not in refined_keys:
            dropped.add(key)
    return dropped


_REFINE_DELETE_MATCH_STOPWORDS: frozenset[str] = frozenset(
    _strip_diacritics(word)
    for word in (
        "please", "pls", "prosím", "prosim", "thanks", "děkuji", "diky",
        "smaž", "smaz", "smazat", "odstraň", "odstran", "odstranit",
        "delete", "remove", "drop", "odeber", "odebrat", "vymaž", "vymaz",
        "pozice", "pozici", "role", "řádek", "radek", "záznam", "zaznam",
        "věc", "vec", "věci", "veci", "thing", "things", "entry", "item",
        "resume", "životopis", "zivotopis", "from", "with", "and", "the",
        "ten", "ta", "to", "ty", "tuhle", "tento", "tahle",
    )
)


def _feedback_delete_chunks(feedback: str) -> list[str]:
    """Return feedback chunks that carry an explicit delete instruction.

    The GUI normally sends one numbered request per line. If only one free-form
    sentence was provided, a single delete keyword applies to that whole chunk.
    For mixed numbered feedback ("1) delete X\n2) add Y") we only treat the
    lines with their own delete keyword as deletion requests.
    """
    raw_lines = [line.strip() for line in (feedback or "").splitlines()]
    chunks: list[str] = []
    for line in raw_lines:
        if not line:
            continue
        cleaned = re.sub(r"^\s*(?:[-*]\s*)?\d+[\).:-]\s*", "", line).strip()
        if cleaned:
            chunks.append(cleaned)
    if not chunks and feedback.strip():
        chunks = [feedback.strip()]
    if len(chunks) == 1:
        return chunks if _feedback_has_delete_intent(chunks[0]) else []
    return [chunk for chunk in chunks if _feedback_has_delete_intent(chunk)]


def _match_phrase(text: str) -> str:
    cleaned = _strip_diacritics(text or "").lower()
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _match_tokens(text: str) -> set[str]:
    return {
        tok
        for tok in re.findall(r"[a-z0-9]{3,}", _match_phrase(text))
        if tok not in _REFINE_DELETE_MATCH_STOPWORDS
    }


def _feedback_matches_section(chunk: str, section: ResumeSection) -> bool:
    """Conservative fuzzy match between a delete request and one resume row."""
    chunk_norm = _match_phrase(chunk)
    title_norm = _match_phrase(section.title)
    subtitle_norm = _match_phrase(section.subtitle)
    if title_norm and len(title_norm) >= 4 and title_norm in chunk_norm:
        return True
    if subtitle_norm and len(subtitle_norm) >= 4 and subtitle_norm in chunk_norm:
        return True

    query_tokens = _match_tokens(chunk)
    if not query_tokens:
        return False
    title_tokens = _match_tokens(section.title)
    subtitle_tokens = _match_tokens(section.subtitle)
    section_tokens = _match_tokens(
        " ".join([section.title or "", section.subtitle or "", section.period or ""])
    )
    if title_tokens and title_tokens <= query_tokens:
        return True
    if subtitle_tokens and subtitle_tokens <= query_tokens:
        return True
    overlap = query_tokens & section_tokens
    if len(overlap) >= 2:
        return True
    return any(len(tok) >= 6 for tok in overlap)


def _feedback_matches_text(chunk: str, text: str) -> bool:
    chunk_norm = _match_phrase(chunk)
    text_norm = _match_phrase(text)
    if text_norm and len(text_norm) >= 4 and text_norm in chunk_norm:
        return True
    query_tokens = _match_tokens(chunk)
    text_tokens = _match_tokens(text)
    if text_tokens and text_tokens <= query_tokens:
        return True
    overlap = query_tokens & text_tokens
    if len(overlap) >= 2:
        return True
    return any(len(tok) >= 6 for tok in overlap)


def _apply_explicit_feedback_deletions(
    resume: TailoredResume,
    feedback: str,
) -> tuple[set[tuple[str, str, tuple[int, int] | None]], bool, list[str]]:
    """Apply named delete requests that the AI failed to perform.

    Returns ``(experience_keys, deleted_all_projects, labels)``. The keys feed
    the experience safety net so rows removed here are not re-injected from the
    candidate profile in the same refine pass.
    """
    chunks = _feedback_delete_chunks(feedback)
    if not chunks:
        return set(), False, []

    deleted_exp_keys: set[tuple[str, str, tuple[int, int] | None]] = set()
    deleted_labels: list[str] = []

    def _filter_sections(
        sections: list[ResumeSection],
        *,
        collect_exp_keys: bool = False,
    ) -> list[ResumeSection]:
        survivors: list[ResumeSection] = []
        for section in sections:
            if any(_feedback_matches_section(chunk, section) for chunk in chunks):
                if collect_exp_keys:
                    deleted_exp_keys.add(_experience_dedup_key(section))
                deleted_labels.append(_format_safety_net_addition(section))
                continue
            survivors.append(section)
        return survivors

    before_projects = len(resume.projects)
    resume.experience = _filter_sections(resume.experience, collect_exp_keys=True)
    resume.education = _filter_sections(resume.education)
    resume.projects = _filter_sections(resume.projects)
    deleted_all_projects = before_projects > 0 and not resume.projects

    if resume.certifications:
        certs: list[str] = []
        for cert in resume.certifications:
            if any(_feedback_matches_text(chunk, cert) for chunk in chunks):
                deleted_labels.append(cert)
                continue
            certs.append(cert)
        resume.certifications = certs

    if deleted_labels:
        logger.info(
            "refine explicit deletion: removed %d resume item(s): %s",
            len(deleted_labels),
            deleted_labels,
        )
    return deleted_exp_keys, deleted_all_projects, deleted_labels


def _feedback_targets_project_deletion(
    current_resume: TailoredResume,
    feedback: str,
) -> bool:
    """Return True when feedback names a current project for deletion.

    Used when the AI already removed the project before our deterministic pass
    runs. In that case ``resume.projects`` may be empty, so we need to inspect
    the previous draft to avoid re-adding a fallback project immediately after
    the user asked to delete it.
    """
    chunks = _feedback_delete_chunks(feedback)
    if not chunks or not current_resume.projects:
        return False
    for chunk in chunks:
        chunk_norm = _match_phrase(chunk)
        asks_for_all_projects = (
            any(word in chunk_norm for word in ("project", "projects", "projekt", "projekty"))
            and any(word in chunk_norm for word in ("all", "every", "vsechny", "vsechno"))
        )
        if asks_for_all_projects:
            return True
        if any(_feedback_matches_section(chunk, project) for project in current_resume.projects):
            return True
    return False


def _format_safety_net_addition(section: ResumeSection) -> str:
    """Render a single re-injected row for the user-facing explanation."""
    label = section.title or "(untitled role)"
    bits: list[str] = [label]
    if section.subtitle:
        bits.append(f"@ {section.subtitle}")
    if section.period:
        bits.append(f"({section.period})")
    return " ".join(bits)


def _candidate_has_linkedin(candidate: CandidateProfile) -> bool:
    """Return True when the user supplied a LinkedIn EXPORT (not just a URL).

    The previous version treated ``candidate.linkedin_url`` as proof of
    LinkedIn data, but the URL is routinely extracted from the candidate's
    CV footer by ``analyze_candidate`` even when the user never uploaded
    a LinkedIn export. With the URL alone we have no actual LinkedIn
    content to compare against, so the AI used to be told it could
    reference LinkedIn data and would then hallucinate ("LinkedIn doesn't
    show experience X"). The bug report screenshot caught this in the
    wild on a Czech resume that had only a CV uploaded.

    A LinkedIn signal now requires either:

    * ``raw_linkedin_text`` non-empty (the actual export blob), OR
    * at least one experience / education entry whose ``source`` is
      ``linkedin`` or ``both`` (set by the LinkedIn parser, never by
      the CV parser).

    A bare ``linkedin_url`` no longer counts.
    """
    if (candidate.raw_linkedin_text or "").strip():
        return True
    for entry in (*candidate.experience, *candidate.education):
        if entry.source in ("linkedin", "both"):
            return True
    return False


# Sentence-ish chunks that name LinkedIn explicitly. We strip these out of
# the AI's ``explanation`` field when ``_candidate_has_linkedin`` returns
# False so the user is never told "your LinkedIn doesn't have X" after
# they only provided a CV. Conservative on purpose: we only delete the
# offending sentence, never the whole explanation.
_LINKEDIN_MENTION_RE = re.compile(
    r"(?:[^.!?\n]*?\bLinkedIn\b[^.!?\n]*[.!?]?)",
    re.IGNORECASE,
)


def _strip_linkedin_mentions(text: str) -> str:
    """Remove sentences that name LinkedIn from ``text``.

    Used on the refine ``explanation`` when the user did NOT supply a
    LinkedIn export. Keeps surrounding sentences intact so a
    multi-sentence explanation still makes sense after the strip.
    Returns the text trimmed of trailing whitespace; an empty string is
    fine - the caller will fall back to its own default message.
    """
    if not text or "linkedin" not in text.lower():
        return text
    cleaned = _LINKEDIN_MENTION_RE.sub("", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# Deterministic language-level edits in refine
# ---------------------------------------------------------------------------

# Map every "name surface form" we want to recognise in user feedback to a
# canonical English language name. Keys are matched after diacritic stripping
# + lowercasing, so "Němčina", "nemcina" and "german" all collapse to the
# same canonical entry. Values are the canonical English name we use to
# look up the existing entry in ``resume.spoken_languages`` (also matched
# diacritics-insensitive against the entry's surface form).
_LANGUAGE_NAME_ALIASES: dict[str, str] = {
    # German
    "german": "German",
    "germana": "German",
    "germanstina": "German",
    "deutsch": "German",
    "nemcina": "German",
    "nemcinu": "German",
    "nemciny": "German",
    "nemcine": "German",
    "nemecky": "German",
    "nemecka": "German",
    # English
    "english": "English",
    "anglictina": "English",
    "anglictinu": "English",
    "anglictiny": "English",
    "anglictine": "English",
    "anglicky": "English",
    "anglicka": "English",
    # Czech
    "czech": "Czech",
    "cestina": "Czech",
    "cestinu": "Czech",
    "cestiny": "Czech",
    "cestine": "Czech",
    "cesky": "Czech",
    "ceska": "Czech",
    # Slovak
    "slovak": "Slovak",
    "slovenstina": "Slovak",
    "slovenstinu": "Slovak",
    "slovenstiny": "Slovak",
    "slovenstine": "Slovak",
    "slovensky": "Slovak",
    "slovenska": "Slovak",
    # Spanish
    "spanish": "Spanish",
    "spanelstina": "Spanish",
    "spanelstinu": "Spanish",
    "spanelstiny": "Spanish",
    "spanelstine": "Spanish",
    "spanelsky": "Spanish",
    # French
    "french": "French",
    "francouzstina": "French",
    "francouzstinu": "French",
    "francouzstiny": "French",
    "francouzstine": "French",
    "francouzsky": "French",
    # Italian
    "italian": "Italian",
    "italstina": "Italian",
    "italstinu": "Italian",
    "italstiny": "Italian",
    "italstine": "Italian",
    "italsky": "Italian",
    # Polish
    "polish": "Polish",
    "polstina": "Polish",
    "polstinu": "Polish",
    "polstiny": "Polish",
    "polstine": "Polish",
    "polsky": "Polish",
    # Russian
    "russian": "Russian",
    "rustina": "Russian",
    "rustinu": "Russian",
    "rustiny": "Russian",
    "rustine": "Russian",
    "rusky": "Russian",
    # Ukrainian
    "ukrainian": "Ukrainian",
    "ukrajinstina": "Ukrainian",
    "ukrajinstinu": "Ukrainian",
    "ukrajinstiny": "Ukrainian",
    "ukrajinstine": "Ukrainian",
    "ukrajinsky": "Ukrainian",
}

# Pattern that matches "<language> <connector?> <CEFR>" in user feedback.
# Examples it must catch (Czech and English both important):
#   "změň němčinu na B2"  -> ("nemcinu", "B2")
#   "set german to B2"     -> ("german", "B2")
#   "german B2"            -> ("german", "B2")
#   "němčinu -> B2"        -> ("nemcinu", "B2")
# The CEFR token is anchored to A1/A2/B1/B2/C1/C2 only; the connector is
# optional (na / to / -> / =) so loose phrasing still works.
_LANGUAGE_LEVEL_RE = re.compile(
    r"\b([A-Za-z\u0080-\uFFFF]{4,})\s*"
    r"(?:na|to|=|->|na\s+\u00farove\u0148|\u2192)?\s*"
    r"([ABC][12])\b",
    re.IGNORECASE,
)


def _canonical_language_name(token: str) -> str | None:
    """Return the canonical English name for a feedback token, or ``None``."""
    if not token:
        return None
    key = _strip_diacritics(token).lower().strip()
    return _LANGUAGE_NAME_ALIASES.get(key)


def _format_language_entry(name: str, level: str, output_language: str) -> str:
    """Build the ``"Language (Level)"`` string we store in ``spoken_languages``.

    When the resume is in Czech we localise the language NAME (so
    "German (B2)" becomes "Němčina (B2)") so the new entry blends with
    the rest of the list. The level itself stays as the CEFR code
    because that's universally recognised.
    """
    code = (output_language or "en").strip().lower()
    cs_names = {
        "German": "Němčina",
        "English": "Angličtina",
        "Czech": "Čeština",
        "Slovak": "Slovenština",
        "Spanish": "Španělština",
        "French": "Francouzština",
        "Italian": "Italština",
        "Polish": "Polština",
        "Russian": "Ruština",
        "Ukrainian": "Ukrajinština",
    }
    display = cs_names.get(name, name) if code == "cs" else name
    return f"{display} ({level.upper()})"


def _entry_matches_language(entry: str, canonical: str) -> bool:
    """Diacritics-insensitive name match for an existing list entry."""
    if not entry:
        return False
    head = entry.split("(")[0].split(" - ")[0].split(" – ")[0].strip()
    head_norm = _strip_diacritics(head).lower()
    target_norm = _strip_diacritics(canonical).lower()
    if head_norm == target_norm:
        return True
    # Czech inflected forms ("Němčina" / "Němčinu" / "Němčiny") all map
    # to the same canonical via the alias table; check that path too.
    return _canonical_language_name(head) == canonical


def _apply_explicit_language_level_changes(
    resume: TailoredResume,
    feedback: str,
    output_language: str,
) -> list[tuple[str, str]]:
    """Update ``resume.spoken_languages`` based on explicit user feedback.

    The bug report screenshot caught the AI saying ``"changed German to
    B2"`` in the explanation while leaving the resume's languages list
    untouched. This deterministic pass parses ``feedback`` for
    ``"<language> ... <CEFR>"`` patterns and rewrites the matching
    entry in place (or appends a new one if the language wasn't present
    yet). Returns the list of ``(language, new_level)`` tuples it
    applied so the caller can include them in the explanation if it
    wants - empty list means nothing matched.

    Conservative: only writes when the language alias is recognised
    AND the CEFR code is one of A1/A2/B1/B2/C1/C2. Anything else falls
    through and the AI's own response wins.
    """
    if not feedback or not resume:
        return []
    applied: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for match in _LANGUAGE_LEVEL_RE.finditer(feedback):
        token = match.group(1)
        level = match.group(2).upper()
        canonical = _canonical_language_name(token)
        if not canonical or level not in {"A1", "A2", "B1", "B2", "C1", "C2"}:
            continue
        pair = (canonical, level)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        new_entry = _format_language_entry(canonical, level, output_language)
        replaced = False
        for idx, existing in enumerate(resume.spoken_languages):
            if _entry_matches_language(existing, canonical):
                if existing.strip() != new_entry:
                    resume.spoken_languages[idx] = new_entry
                replaced = True
                break
        if not replaced:
            resume.spoken_languages.append(new_entry)
        applied.append(pair)
    if applied:
        logger.info(
            "_apply_explicit_language_level_changes: rewrote %d "
            "language(s) on the resume from refine feedback: %s",
            len(applied),
            ", ".join(f"{n}={lvl}" for n, lvl in applied),
        )
    return applied


def refine_tailored_resume(
    provider: BaseAIProvider,
    current_resume: TailoredResume,
    feedback: str,
    job: JobPosting,
    candidate: CandidateProfile,
    answers: AnswersBundle | None = None,
    evidence: Sequence[EvidenceItem] = (),
    output_language: str = "en",
    previous_explanation: str = "",
) -> RefinedResume:
    """Re-generate the resume incorporating the user's textual feedback.

    Returns a :class:`RefinedResume` carrying the updated resume AND a
    short, user-facing ``explanation`` describing what changed. The
    explanation is the AI's own note appended (when applicable) with a
    deterministic safety-net line listing any experience rows the AI
    dropped and we re-injected from the candidate profile.

    ``previous_explanation`` is the explanation the AI returned in the
    previous refine round (empty on the first round). It lets the model
    interpret bare affirmations like ``"ano"`` / ``"yes"`` as agreement
    with the suggestion it made earlier - without that context, the
    user typing "ano" after the AI asked "Mohu sma\u017eat X?" would
    produce a no-op refine.
    """
    answers = answers or AnswersBundle()
    refined = provider.refine_resume(
        current_resume, feedback, job, candidate, answers, evidence,
        output_language=output_language,
        previous_explanation=previous_explanation,
    )
    resume = refined.resume

    _fixup_education_language(resume, output_language)
    _dedup_resume_sections(resume, output_language)
    _enforce_bullet_floor(resume, candidate)

    # Languages on the resume model are the source of truth from now on
    # (see TailoredResume.spoken_languages docstring). Carry them over
    # from the previous draft when the AI omitted them, and seed from
    # the candidate when even that list is empty - otherwise the user's
    # earlier "změň němčinu na B2" edit would silently disappear.
    if not resume.spoken_languages:
        if current_resume.spoken_languages:
            resume.spoken_languages = list(current_resume.spoken_languages)
        elif candidate.spoken_languages:
            resume.spoken_languages = list(candidate.spoken_languages)

    # Detect explicit delete intent so the project-stripper below knows
    # whether "no projects left" is the user's wish (skip the projects
    # safety net) or just an AI drop (re-inject GitHub data).
    if _feedback_has_delete_intent(feedback):
        project_delete_requested = _feedback_targets_project_deletion(
            current_resume, feedback
        )
        _, deleted_all_projects, _ = _apply_explicit_feedback_deletions(
            resume, feedback
        )
        deleted_all_projects = deleted_all_projects or (
            project_delete_requested and not resume.projects
        )
    else:
        deleted_all_projects = False

    # User said "no security should be there at all" for experience rows
    # in particular: ``ensure_experience_section`` used to silently re-
    # add positions the user (or the AI on the user's instruction) just
    # deleted, undoing their choice on every refine pass. The initial
    # ``generate_tailored_resume`` still uses the safety net to protect
    # the very first draft, but refine has to honour the user's edits.
    # Other safety nets (invented-project stripper, education cleanup,
    # period backfill) stay - the user explicitly asked us to keep
    # those.
    _apply_explicit_language_level_changes(resume, feedback, output_language)
    dropped_projects = _strip_invented_projects(resume, candidate)
    _strip_incomplete_education(resume)
    _backfill_periods(resume, candidate)
    _fixup_education_language(resume, output_language)
    _dedup_resume_sections(resume, output_language)
    if not deleted_all_projects:
        ensure_projects_section(resume, candidate)

    explanation_parts: list[str] = []
    ai_explanation = (refined.explanation or "").strip()
    # When the user did NOT supply LinkedIn, strip any sentence that
    # names LinkedIn from the AI's note - the user never gave us
    # LinkedIn data, so 'na LinkedInu nem\u00e1\u0161 X' is hostile noise.
    if ai_explanation and not _candidate_has_linkedin(candidate):
        ai_explanation = _strip_linkedin_mentions(ai_explanation)
    if ai_explanation:
        explanation_parts.append(ai_explanation)

    for title in dropped_projects:
        explanation_parts.append(
            t_in(
                output_language,
                "docs.refine.invented_project_dropped",
                title=title,
            )
        )

    refined.explanation = "\n\n".join(p for p in explanation_parts if p)
    return refined


__all__ = [
    "generate_tailored_resume",
    "refine_tailored_resume",
    "ensure_projects_section",
    "ensure_experience_section",
]


# ---------------------------------------------------------------------------
# Test-only re-exports. These private helpers have unit tests pinning their
# behaviour but we don't want them in the wildcard-import surface.
# ---------------------------------------------------------------------------
_TEST_ONLY = (  # noqa: F841 - documentation aid
    "_dedup_resume_sections",
    "_dedup_cross_language_bullets",
    "_strip_invented_projects",
    "_strip_incomplete_education",
    "_strip_linkedin_mentions",
    "_candidate_has_linkedin",
    "_fixup_education_language",
    "_translate_period",
    "_normalize_project_title",
    "_project_title_is_evidenced",
    "_looks_czech",
    "_education_title_is_just_field",
)
