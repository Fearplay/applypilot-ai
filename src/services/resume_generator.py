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
    _normalize_name,
    _parse_year_range,
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
    "programmer": "Programátor",
    "junior developer": "Junior vývojář",
    "senior developer": "Senior vývojář",
    "contract": "Kontrakt",
    "part-time": "Částečný úvazek",
    "full-time": "Plný úvazek",
    "self-employed": "OSVČ",
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


def _translate_period(period: str, output_language: str) -> str:
    """Convert Czech month names to two-digit numbers and 'současnost' to
    'present' (or vice versa) in a free-text date range.

    Conservative: if no token in the period matches the month / present
    table for the target language we return the input unchanged. This
    keeps already-correct periods like ``"04/2022 - 06/2023"`` intact and
    only normalises the mixed-language ones the AI sometimes emits.
    """
    if not period:
        return period
    code = (output_language or "en").strip().lower()
    if code == "en":
        # Czech months -> 01..12 (case + diacritics insensitive on lookup).
        out = period
        ascii_lower = _strip_diacritics(out).lower()
        # Months: replace by scanning for each token (longest first).
        for src in sorted(_MONTH_NUMBERS_FROM_CS, key=len, reverse=True):
            pattern = re.compile(rf"\b{re.escape(src)}\b", re.IGNORECASE)
            for m in list(pattern.finditer(ascii_lower)):
                out = out[:m.start()] + _MONTH_NUMBERS_FROM_CS[src] + out[m.end():]
                ascii_lower = (
                    ascii_lower[:m.start()]
                    + _MONTH_NUMBERS_FROM_CS[src]
                    + ascii_lower[m.end():]
                )
        for src in _PRESENT_MARKERS_CS:
            pattern = re.compile(rf"\b{re.escape(src)}\b", re.IGNORECASE)
            out = pattern.sub("present", out)
        return out
    if code == "cs":
        out = period
        for src in sorted(_MONTH_NUMBERS_FROM_EN, key=len, reverse=True):
            pattern = re.compile(rf"\b{re.escape(src)}\b", re.IGNORECASE)
            out = pattern.sub(_MONTH_NUMBERS_FROM_EN[src], out)
        for src in _PRESENT_MARKERS_EN:
            pattern = re.compile(rf"\b{re.escape(src)}\b", re.IGNORECASE)
            out = pattern.sub("současnost", out)
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
            if section.title and _looks_english(section.title):
                section.title = _translate_text_diacritics_insensitive(
                    section.title, _EXPERIENCE_TRANSLATIONS_CS
                )
            if section.subtitle and _looks_english(section.subtitle):
                section.subtitle = _translate_text_diacritics_insensitive(
                    section.subtitle, _EXPERIENCE_TRANSLATIONS_CS
                )
            section.period = _translate_period(section.period, "cs")
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


def _experience_dedup_key(section: ResumeSection) -> tuple[str, str, tuple[int, int] | None]:
    """Stable key used to identify duplicate experience rows.

    Tuple of ``(seniority_prefix, normalised_subtitle/title, year_range)``.
    Subtitle is preferred because the company name is the most reliable
    duplicate signal; falls back to a normalised title when the AI omitted
    the subtitle. The year range is parsed loosely so '06/2023 - 07/2025'
    and 'června 2023 - července 2025' produce the same key.
    """
    title = section.title or ""
    subtitle = section.subtitle or ""
    seniority = _extract_seniority(title)
    name_basis = subtitle or title
    norm = _normalize_name(name_basis)
    return seniority, norm, _parse_year_range(section.period or "")


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


def _dedup_resume_sections(resume: TailoredResume) -> None:
    """Collapse duplicate experience / project rows and dedup bullets per
    section in place.

    Seniority guard mirrors the candidate-profile dedup pass: rows with
    different seniority prefixes (Junior / Senior / Lead / ...) are
    NEVER merged even when the company + period match - they're real
    career progression entries that must stay separate.
    """
    # Experience: greedy O(n^2) merge by dedup key, preserving order.
    new_experience: list[ResumeSection] = []
    for section in resume.experience:
        section.bullets = _dedup_bullets(section.bullets)
        key = _experience_dedup_key(section)
        merged = False
        for i, existing in enumerate(new_experience):
            if _experience_dedup_key(existing) == key:
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
        section.bullets = _dedup_bullets(section.bullets)


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


def _compute_missing_experience(
    resume: TailoredResume, candidate: CandidateProfile
) -> list[ResumeSection]:
    """Return the candidate experience rows that are NOT yet in ``resume``.

    Pure function: never mutates either argument. Callers (e.g. the
    refine safety net) need this to know what they're about to inject so
    they can tell the user about it.
    """
    if not candidate.experience:
        return []
    missing: list[ResumeSection] = []
    for entry in candidate.experience:
        if _find_experience_match(resume, entry):
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
) -> TailoredResume:
    """Re-inject any candidate experience rows the AI silently dropped.

    Uses seniority-aware matching so "Junior Software QA Engineer" is NOT
    considered a match for "Software QA Engineer" -- career progression
    entries are treated as distinct rows.
    """
    missing = _compute_missing_experience(resume, candidate)
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
    # would never match), THEN dedup, THEN re-inject missing rows from the
    # candidate, THEN strip invented projects (so safety-net additions
    # are real GitHub repos), THEN backfill periods, THEN ensure at least
    # one project survived.
    _fixup_education_language(resume, output_language)
    _dedup_resume_sections(resume)
    _enforce_bullet_floor(resume, candidate)
    ensure_experience_section(resume, candidate, output_language)
    _strip_invented_projects(resume, candidate)
    _backfill_periods(resume, candidate)
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


def _feedback_has_add_intent(feedback: str) -> bool:
    """Return True when ``feedback`` contains an "ADD this row" keyword."""
    text = _strip_diacritics((feedback or "").lower())
    return any(
        _strip_diacritics(kw.lower()) in text
        for kw in _REFINE_ADD_INTENT_KEYWORDS
    )


def _format_safety_net_addition(section: ResumeSection) -> str:
    """Render a single re-injected row for the user-facing explanation."""
    label = section.title or "(untitled role)"
    bits: list[str] = [label]
    if section.subtitle:
        bits.append(f"@ {section.subtitle}")
    if section.period:
        bits.append(f"({section.period})")
    return " ".join(bits)


def refine_tailored_resume(
    provider: BaseAIProvider,
    current_resume: TailoredResume,
    feedback: str,
    job: JobPosting,
    candidate: CandidateProfile,
    answers: AnswersBundle | None = None,
    evidence: Sequence[EvidenceItem] = (),
    output_language: str = "en",
) -> RefinedResume:
    """Re-generate the resume incorporating the user's textual feedback.

    Returns a :class:`RefinedResume` carrying the updated resume AND a
    short, user-facing ``explanation`` describing what changed. The
    explanation is the AI's own note appended (when applicable) with a
    deterministic safety-net line listing any experience rows the AI
    dropped and we re-injected from the candidate profile.
    """
    answers = answers or AnswersBundle()
    refined = provider.refine_resume(
        current_resume, feedback, job, candidate, answers, evidence,
        output_language=output_language,
    )
    resume = refined.resume

    _fixup_education_language(resume, output_language)
    _dedup_resume_sections(resume)
    _enforce_bullet_floor(resume, candidate)

    # Capture missing experience rows BEFORE we inject them so we can tell
    # the user (in their language) which rows the safety net rescued.
    missing_before = _compute_missing_experience(resume, candidate)
    ensure_experience_section(resume, candidate, output_language)
    dropped_projects = _strip_invented_projects(resume, candidate)
    _backfill_periods(resume, candidate)
    ensure_projects_section(resume, candidate)

    # Build the inline explanation. The AI's own note always comes first,
    # then we append a one-liner per safety-net intervention so the user
    # sees both AI- and rule-based modifications in one place.
    explanation_parts: list[str] = []
    if refined.explanation:
        explanation_parts.append(refined.explanation.strip())

    # Always announce safety-net additions so the user is never surprised
    # by a row they didn't see in the previous draft. The "add intent"
    # check is informational (used to make the message louder when the
    # user explicitly asked) but the announcement itself is unconditional.
    if missing_before:
        labels = ", ".join(
            _format_safety_net_addition(s) for s in missing_before
        )
        # Always use the resume's ``output_language`` (not the global UI
        # locale) so a Czech resume gets a Czech safety-net note even
        # when the user is browsing the chrome in English.
        if _feedback_has_add_intent(feedback):
            line = t_in(
                output_language, "docs.refine.safety_added.explicit",
                labels=labels,
            )
        else:
            line = t_in(
                output_language, "docs.refine.safety_added.auto",
                labels=labels,
            )
        explanation_parts.append(line)

    # Tell the user which fabricated projects we removed - one line per
    # dropped title so they can either supply a link / description or
    # confirm the AI was making things up.
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
    "_strip_invented_projects",
    "_fixup_education_language",
    "_translate_period",
    "_normalize_project_title",
    "_project_title_is_evidenced",
    "_looks_czech",
)
