"""Evidence-based skill bucketing.

This is the gatekeeper that enforces the "no hallucinated experience"
policy: every job-required skill is checked against concrete evidence
sources (CV text, LinkedIn text, GitHub project metadata, user answers
marked as ``practical_experience``). Skills with no evidence go into the
gap plan, never into the tailored resume.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from ..models.candidate import CandidateProfile, GitHubProject
from ..models.evidence import EvidenceCheckResult, EvidenceItem
from ..models.job import JobPosting
from ..models.match import AnswersBundle, ClarifyingAnswer


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9+#.]", "", (s or "").lower())


def _contains_skill(skill: str, text: str) -> bool:
    n = _norm(skill)
    if not n:
        return False
    return n in _norm(text)


_SEPARATOR_LINE_RE = re.compile(r"^\s*[=\-_*~#]{3,}\s*$", re.MULTILINE)
_MULTI_NEWLINE_RE = re.compile(r"\n{2,}")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")


def _clean_snippet(text: str, *, limit: int = 200) -> str:
    """Strip noisy ASCII separators and collapse whitespace in an evidence snippet.

    The CV / LinkedIn parsers emit raw text that often contains lines like
    ``===========`` (PDF/TXT decorative dividers) which look terrible in the
    Match report's evidence preview. We drop those lines, normalise newlines
    and trim to ``limit`` chars while preferring not to cut mid-word.
    """
    if not text:
        return ""
    cleaned = _SEPARATOR_LINE_RE.sub("", text)
    cleaned = "\n".join(line.rstrip() for line in cleaned.splitlines() if line.strip())
    cleaned = _MULTI_NEWLINE_RE.sub("\n", cleaned)
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit]
    last_space = cut.rfind(" ")
    if last_space > limit * 0.7:
        cut = cut[:last_space]
    return cut.rstrip(",;:.- ") + "..."


def _scan_text_for_skill(skill: str, text: str, source_type: str, source_name: str) -> EvidenceItem | None:
    if not text or not skill:
        return None
    n = _norm(skill)
    if not n:
        return None
    pattern = re.compile(rf"(?i)\b{re.escape(skill)}\b")
    match = pattern.search(text)
    if not match:
        # Try the normalised (no separators) form.
        if n not in _norm(text):
            return None
        snippet = text[:160]
    else:
        start = max(match.start() - 60, 0)
        end = min(match.end() + 60, len(text))
        snippet = text[start:end]
    return EvidenceItem(
        claim=f"Candidate has experience with {skill}.",
        skill=skill,
        source_type=source_type,  # type: ignore[arg-type]
        source_name=source_name,
        evidence_text=_clean_snippet(snippet),
        confidence="medium",
    )


def _scan_project_for_skill(skill: str, project: GitHubProject) -> EvidenceItem | None:
    if not skill:
        return None
    haystack = " ".join([
        project.name or "",
        project.description or "",
        project.readme_excerpt or "",
        " ".join(project.detected_technologies),
        " ".join(project.languages),
        " ".join(project.topics),
        project.primary_language or "",
    ])
    if not _contains_skill(skill, haystack):
        return None
    return EvidenceItem(
        claim=f"Candidate has experience with {skill}.",
        skill=skill,
        source_type="github",
        source_name=f"github:{project.name}",
        evidence_text=_clean_snippet(project.description or project.name),
        confidence="high" if skill.lower() in {l.lower() for l in project.languages} else "medium",
    )


def _scan_answers_for_skill(skill: str, answers: AnswersBundle) -> EvidenceItem | None:
    if not skill or not answers:
        return None
    for ans in answers.answers:
        if (ans.skill and _norm(ans.skill) == _norm(skill)) and ans.treat_as == "practical_experience":
            return EvidenceItem(
                claim=f"Candidate confirmed practical experience with {skill}.",
                skill=skill,
                source_type="user_answer",
                source_name=f"answer:{ans.question_id}",
                evidence_text=(ans.answer or "User confirmed via clarifying question.")[:300],
                confidence=ans.confidence,
            )
    return None


def check_evidence(
    job: JobPosting,
    candidate: CandidateProfile,
    answers: AnswersBundle | None = None,
) -> EvidenceCheckResult:
    """Bucket every job-relevant skill into evidenced / weak / missing."""
    answers = answers or AnswersBundle()
    skills_to_check: Iterable[str] = list(dict.fromkeys(
        list(job.required_skills) + list(job.nice_to_have_skills) + list(job.ats_keywords)
    ))

    items: list[EvidenceItem] = []
    evidenced: list[str] = []
    weak: list[str] = []
    missing: list[str] = []

    for skill in skills_to_check:
        skill_items: list[EvidenceItem] = []

        if candidate.raw_cv_text:
            ev = _scan_text_for_skill(skill, candidate.raw_cv_text, "cv", "cv")
            if ev:
                skill_items.append(ev)
        if candidate.raw_linkedin_text:
            ev = _scan_text_for_skill(skill, candidate.raw_linkedin_text, "linkedin", "linkedin export")
            if ev:
                skill_items.append(ev)

        for project in candidate.projects:
            ev = _scan_project_for_skill(skill, project)
            if ev:
                skill_items.append(ev)

        ev = _scan_answers_for_skill(skill, answers)
        if ev:
            skill_items.append(ev)

        # Listed skill / tool fields (no quote available, so weak evidence).
        skills_pool = list(candidate.technical_skills) + list(candidate.tools)
        if any(_contains_skill(skill, s) or _contains_skill(s, skill) for s in skills_pool):
            skill_items.append(
                EvidenceItem(
                    claim=f"Candidate lists '{skill}' in their skills section.",
                    skill=skill,
                    source_type="cv",
                    source_name="skills section",
                    evidence_text=f"Listed in candidate skills/tools.",
                    confidence="low",
                )
            )

        if not skill_items:
            missing.append(skill)
            continue

        items.extend(skill_items)
        confidences = {i.confidence for i in skill_items}
        if "high" in confidences or "medium" in confidences:
            evidenced.append(skill)
        else:
            weak.append(skill)

    return EvidenceCheckResult(
        evidenced_skills=list(dict.fromkeys(evidenced)),
        weak_evidence_skills=list(dict.fromkeys(weak)),
        missing_evidence_skills=list(dict.fromkeys(missing)),
        items=items,
    )


__all__ = ["check_evidence"]
