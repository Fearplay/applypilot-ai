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
    _strip_diacritics,
    _strip_seniority,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Deterministic education-entry translation (EN -> CS)
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

_CZECH_DIACRITICS_SET = set("ěščřžýáíéúůťďňĚŠČŘŽÝÁÍÉÚŮŤĎŇ")

_EN_EDU_MARKERS_RE = re.compile(
    r"\b(?:High School|Diploma|Bachelor|Master|Faculty|University|School|"
    r"College|Institute|Academy|Engineering|Technology|Science)\b",
    re.IGNORECASE,
)


def _looks_english(text: str) -> bool:
    if not text:
        return False
    has_diacritics = any(c in _CZECH_DIACRITICS_SET for c in text)
    if has_diacritics:
        return False
    return bool(_EN_EDU_MARKERS_RE.search(text))


def _translate_edu_text(text: str, table: dict[str, str]) -> str:
    result = text
    for eng, cz in sorted(table.items(), key=lambda kv: -len(kv[0])):
        pattern = re.compile(re.escape(eng), re.IGNORECASE)
        result = pattern.sub(cz, result)
    return result


def _fixup_education_language(resume: TailoredResume, output_language: str) -> None:
    if output_language != "cs":
        return
    for section in resume.education:
        if _looks_english(section.title):
            section.title = _translate_edu_text(
                section.title,
                {**_EDU_TITLE_TRANSLATIONS_CS, **_EDU_INSTITUTION_TRANSLATIONS_CS},
            )
        if _looks_english(section.subtitle):
            section.subtitle = _translate_edu_text(
                section.subtitle,
                {**_EDU_TITLE_TRANSLATIONS_CS, **_EDU_INSTITUTION_TRANSLATIONS_CS},
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
    _fixup_education_language(resume, output_language)
    _enforce_bullet_floor(resume, candidate)
    ensure_experience_section(resume, candidate, output_language)
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
    _enforce_bullet_floor(resume, candidate)

    # Capture missing experience rows BEFORE we inject them so we can tell
    # the user (in their language) which rows the safety net rescued.
    missing_before = _compute_missing_experience(resume, candidate)
    ensure_experience_section(resume, candidate, output_language)
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

    refined.explanation = "\n\n".join(p for p in explanation_parts if p)
    return refined


__all__ = [
    "generate_tailored_resume",
    "refine_tailored_resume",
    "ensure_projects_section",
    "ensure_experience_section",
]
