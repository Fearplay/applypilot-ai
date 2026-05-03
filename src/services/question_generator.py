"""Generate clarifying questions for the human-in-the-loop step."""
from __future__ import annotations

from ..ai.base import BaseAIProvider
from ..models.candidate import CandidateProfile
from ..models.job import JobPosting
from ..models.match import AnswersBundle, ClarifyingQuestion


def generate_questions(
    provider: BaseAIProvider,
    job: JobPosting,
    candidate: CandidateProfile,
    existing_answers: AnswersBundle | None = None,
    output_language: str = "en",
) -> list[ClarifyingQuestion]:
    """Ask the provider for clarifying questions, filter ones already answered."""
    questions = provider.generate_clarifying_questions(
        job, candidate, output_language=output_language
    )
    if not existing_answers or not existing_answers.answers:
        return questions
    answered_skills = {a.skill for a in existing_answers.answers if a.skill}
    answered_ids = {a.question_id for a in existing_answers.answers}
    return [
        q for q in questions
        if q.id not in answered_ids
        and (q.skill is None or q.skill not in answered_skills)
    ]


__all__ = ["generate_questions"]
