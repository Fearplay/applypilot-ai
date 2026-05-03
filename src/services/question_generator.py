"""Generate clarifying questions for the human-in-the-loop step."""
from __future__ import annotations

from ..ai.base import BaseAIProvider
from ..models.candidate import CandidateProfile
from ..models.job import JobPosting
from ..models.match import AnswersBundle, ClarifyingQuestion
from .profile_dedup import (
    build_date_conflict_questions,
    build_source_discrepancy_questions,
    build_structural_mismatch_questions,
)


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
