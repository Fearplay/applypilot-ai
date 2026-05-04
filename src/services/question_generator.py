"""Generate clarifying questions for the human-in-the-loop step."""
from __future__ import annotations

import re

from ..ai.base import BaseAIProvider
from ..i18n import t_in
from ..models.candidate import CandidateProfile
from ..models.job import JobPosting
from ..models.match import AnswersBundle, ClarifyingQuestion
from .profile_dedup import (
    build_date_conflict_questions,
    build_source_discrepancy_questions,
    build_structural_mismatch_questions,
)


# "Do you have experience with X?", "Have you worked with X?", and the
# Czech / Slovak equivalents the screenshot in the bug report showed
# arriving as a short_text input. The patterns are intentionally lenient
# - false positives (a question accidentally promoted to yes_no) lose
# nothing because the user can still type a free comment in the answer
# bundle alongside the dropdown choice; false negatives (a yes_no
# question stuck as short_text) cost the user real friction.
_YES_NO_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^\s*(do|did|have|has)\s+(you|the\s+candidate)\s+"
        r"(work(ed)?\s+with|use[ds]?|known?|led|ship(ped)?|"
        r"writ(ten|e)|build|built|deploy(ed)?|run|ran|"
        r"got|have|had)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(are|were)\s+you\s+(familiar|comfortable|"
        r"experienced|hands[- ]on)\s+with\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*m[áa]š\s+(zku[šs]enost|zku[šs]enosti|n[ěe]jakou)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*pracoval/?\s*(jsi|jste)?\b|^\s*pou[žz][ií]val/?\s*(jsi|jste)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*zn[áa][šs]\b|^\s*um[ií][šs]\b",
        re.IGNORECASE,
    ),
)

# Open-ended question starters - even when followed by "experience" we
# must NOT promote to yes_no because the user is meant to type a number
# / name / paragraph. Without this guard "How many years of NUnit
# experience do you have?" would silently turn into Yes/No.
_OPEN_QUESTION_PREFIXES: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^\s*(how\s+many|how\s+much|how\s+often|how\s+long|"
        r"which|what|when|where|why|briefly|describe|name|list|tell)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(kolik|jak\s+(dlouho|dlouhý|dlouhá|často|často|"
        r"mnoho)|který|která|které|jaký|jaká|jaké|popi[šs]|"
        r"jmenuj|vyjmenuj)\b",
        re.IGNORECASE,
    ),
)


def _is_skill_yes_no_phrasing(text: str) -> bool:
    """``True`` when ``text`` matches a "have you used X" style question."""
    if not text:
        return False
    if any(p.search(text) for p in _OPEN_QUESTION_PREFIXES):
        return False
    return any(p.search(text) for p in _YES_NO_PATTERNS)


def _coerce_skill_questions_to_yes_no(
    questions: list[ClarifyingQuestion],
    output_language: str,
) -> list[ClarifyingQuestion]:
    """Rewrite mis-typed AI questions in place.

    The :func:`clarifying_questions_user_prompt` already tells the AI
    when to pick ``yes_no``; this is the safety net for providers that
    ignore the directive. We never DROP a question - worst case the
    options are slightly off and the user still gets a usable choice.
    """
    yes_label = t_in(output_language, "dedup.opt.include")
    no_label = t_in(output_language, "dedup.opt.skip")
    out: list[ClarifyingQuestion] = []
    for q in questions:
        if (
            q.answer_type == "short_text"
            and _is_skill_yes_no_phrasing(q.question)
        ):
            out.append(
                q.model_copy(
                    update={
                        "answer_type": "yes_no",
                        "options": [yes_label, no_label],
                    }
                )
            )
            continue
        # If the AI returned a yes_no / single_choice / multi_choice
        # without options, fall back to Yes/No so the GUI never has to
        # render a choice question with no choices.
        if q.answer_type in ("yes_no", "single_choice", "multi_choice") and not q.options:
            out.append(
                q.model_copy(
                    update={"options": [yes_label, no_label]}
                )
            )
            continue
        out.append(q)
    return out


def generate_questions(
    provider: BaseAIProvider,
    job: JobPosting,
    candidate: CandidateProfile,
    existing_answers: AnswersBundle | None = None,
    output_language: str = "en",
    *,
    max_discrepancy_questions: int = 4,
    max_date_conflict_questions: int = 4,
    max_structural_questions: int = 3,
    max_total_questions: int = 10,
) -> list[ClarifyingQuestion]:
    """Build the full clarifying-question list shown to the user.

    The list is the concatenation of:

    1. Structural mismatch questions (one CV row combines N companies that
       LinkedIn lists as separate rows) - the user picks split / merge /
       manual. Asked first because the answer can drop or restructure rows
       referenced by the discrepancy / date-conflict questions below.
    2. Date-conflict questions (CV vs LinkedIn disagree on the period of a
       merged entry) - the user picks the correct period.
    3. Source discrepancy questions (CV-only / LinkedIn-only experience or
       education entries) - the user picks 'No - skip it' on anything they
       don't want to ship in the resume.
    4. AI-generated skill-coverage questions returned by the provider.

    All four lists are filtered to remove entries the user already answered
    in a previous round, then truncated to ``max_total_questions``.
    """
    structural = build_structural_mismatch_questions(
        candidate, max_questions=max_structural_questions
    )
    date_conflicts = build_date_conflict_questions(
        candidate, max_questions=max_date_conflict_questions
    )
    discrepancies = build_source_discrepancy_questions(
        candidate, max_questions=max_discrepancy_questions
    )
    ai_questions = provider.generate_clarifying_questions(
        job, candidate, output_language=output_language
    )
    ai_questions = _coerce_skill_questions_to_yes_no(
        ai_questions, output_language
    )

    answered_skills: set[str] = set()
    answered_ids: set[str] = set()
    if existing_answers and existing_answers.answers:
        answered_skills = {a.skill for a in existing_answers.answers if a.skill}
        answered_ids = {a.question_id for a in existing_answers.answers}

    def keep(q: ClarifyingQuestion) -> bool:
        if q.id in answered_ids:
            return False
        if q.skill and q.skill in answered_skills:
            return False
        return True

    combined = [
        q
        for q in (*structural, *date_conflicts, *discrepancies, *ai_questions)
        if keep(q)
    ]
    return combined[:max_total_questions]


__all__ = ["generate_questions"]
