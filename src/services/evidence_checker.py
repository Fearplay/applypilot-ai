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
        snippet = text[start:end].strip()
    return EvidenceItem(
        claim=f"Candidate has experience with {skill}.",
        skill=skill,
        source_type=source_type,  # type: ignore[arg-type]
        source_name=source_name,
        evidence_text=snippet[:300],
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
        evidence_text=(project.description or project.name)[:300],
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
