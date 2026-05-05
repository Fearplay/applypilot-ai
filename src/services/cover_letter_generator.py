"""Cover letter generator + deterministic content safety nets.

The user reported two recurring issues with AI-produced cover letters:

1. The closing line ("Kind regards, Jan Novak") shows up twice -
   once as the structured ``closing`` + ``signature`` fields, and again
   tacked onto the end of the last body paragraph. The exporter then
   prints both, so the user sees the sign-off duplicated.
2. The cover letter occasionally opens with "Cover letter for <Role> at
   <Company>" because the model treats the ``role`` / ``company`` slots as
   a heading. The user wants the cover letter to read as a direct
   message - the role + company already live on the resume + filename.

The first issue is fixed deterministically here (regardless of which AI
provider is in use); the second is fixed in the prompt + the exporter
(which no longer prints any role-in-title heading).
"""
from __future__ import annotations

import logging
import re
import unicodedata

from ..ai.base import BaseAIProvider
from ..models.candidate import CandidateProfile
from ..models.documents import CoverLetter, RefinedCoverLetter
from ..models.job import JobPosting
from ..models.match import AnswersBundle

logger = logging.getLogger(__name__)


_SIGNOFF_PHRASES: tuple[str, ...] = (
    # English
    "best regards",
    "kind regards",
    "warm regards",
    "regards",
    "sincerely",
    "sincerely yours",
    "yours sincerely",
    "yours faithfully",
    "thank you",
    "thanks",
    # Czech
    "s pozdravem",
    "s uctou",
    "s pratelskym pozdravem",
    "se srdecnym pozdravem",
)


def _ascii_fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _strip_duplicate_signoff(cover: CoverLetter) -> CoverLetter:
    """Drop a trailing "<closing>, <name>" tail from the last body paragraph.

    The cover letter model reserves dedicated ``closing`` + ``signature``
    fields, and every exporter prints them once at the end of the
    document. When the AI also concatenates the same sign-off at the end
    of the final paragraph the saved file shows the closing twice.

    This helper looks for either:

    * a closing phrase known to :data:`_SIGNOFF_PHRASES` followed by an
      optional comma + the candidate signature on the same line / next
      line, or
    * the candidate signature alone on a trailing line (already a
      duplicate because it lives on the structured ``signature`` field
      and gets printed once),

    and rewrites the last paragraph in place.

    The match is diacritics-insensitive (``"S pozdravem"`` matches
    ``"s pozdravem"``) and case-insensitive. When the strip would empty
    the entire last paragraph we drop the paragraph instead of leaving a
    blank line.
    """
    if not cover.paragraphs:
        return cover

    closing = (cover.closing or "").strip()
    signature = (cover.signature or "").strip()
    fold_signature = _ascii_fold(signature)

    # Strip an empty trailing paragraph the AI might have added so we
    # don't accidentally treat it as the meaningful "last" paragraph.
    while cover.paragraphs and not cover.paragraphs[-1].strip():
        cover.paragraphs.pop()
    if not cover.paragraphs:
        return cover

    last = cover.paragraphs[-1]
    lines = [ln for ln in last.splitlines() if ln.strip()]
    changed = False

    # Walk lines from the end stripping any trailing signature / sign-off.
    while lines:
        candidate_line = lines[-1].strip()
        candidate_fold = _ascii_fold(candidate_line)

        if signature and candidate_fold == fold_signature:
            lines.pop()
            changed = True
            continue

        # "<closing>, <signature>" or "<closing>" alone.
        matched_phrase = False
        for phrase in _SIGNOFF_PHRASES:
            pattern = re.compile(
                r"^" + re.escape(phrase) + r"[\s,.\-:!]*(.*)$", re.IGNORECASE
            )
            m = pattern.match(candidate_fold)
            if not m:
                continue
            tail = m.group(1).strip(" ,.!-:\t")
            # Either nothing follows, or the trailing token equals the
            # candidate signature - both mean we have a duplicate sign-off.
            if not tail or tail == fold_signature:
                lines.pop()
                changed = True
                matched_phrase = True
                break
        if matched_phrase:
            continue

        # If the line is "<closing>, <signature>" with extra text before
        # the closing phrase (rare, but happens when the model writes
        # "I look forward to hearing from you. Best regards, Jan Novak"),
        # split the sentence and drop only the trailing sign-off chunk.
        if signature and fold_signature in candidate_fold:
            for phrase in _SIGNOFF_PHRASES:
                trailing_re = re.compile(
                    r"\s*" + re.escape(phrase) + r"[\s,.\-:!]+"
                    + re.escape(fold_signature) + r"\s*$",
                    re.IGNORECASE,
                )
                if trailing_re.search(candidate_fold):
                    cleaned = trailing_re.sub("", candidate_line).rstrip(" ,.\t")
                    if cleaned:
                        lines[-1] = cleaned
                    else:
                        lines.pop()
                    changed = True
                    matched_phrase = True
                    break
            if matched_phrase:
                continue

        # Nothing more to strip on this line.
        break

    if not changed:
        return cover

    if lines:
        cover.paragraphs[-1] = "\n".join(lines)
    else:
        cover.paragraphs.pop()
        # Drop further trailing blanks.
        while cover.paragraphs and not cover.paragraphs[-1].strip():
            cover.paragraphs.pop()

    logger.debug(
        "Stripped duplicate sign-off from cover letter for signature=%r",
        signature,
    )
    return cover


def _strip_role_heading(cover: CoverLetter, job: JobPosting) -> CoverLetter:
    """Drop a leading "Cover letter for <role> at <company>" heading.

    The user explicitly asked for the cover letter NOT to start with the
    role / company - that information already lives on the resume + the
    filename. Some providers still occasionally emit a heading line in
    the first paragraph; this safety net removes it deterministically so
    the saved markdown / docx never carry it.
    """
    if not cover.paragraphs:
        return cover
    first = cover.paragraphs[0]
    fold_first = _ascii_fold(first).strip()
    role = _ascii_fold(job.title or "").strip()
    company = _ascii_fold(job.company or "").strip()

    triggers: list[str] = ["cover letter for", "cover letter -", "covering letter for"]
    if role:
        triggers.append(role)
    if role and company:
        triggers.append(f"{role} at {company}")
        triggers.append(f"{role} - {company}")

    head_line = fold_first.split("\n", 1)[0]
    looks_like_heading = (
        any(head_line.startswith(t) for t in triggers)
        or (role and head_line == role)
        or (role and company and head_line == f"{role} at {company}")
    )
    if not looks_like_heading:
        return cover

    # Drop just the heading line, keep the rest of the first paragraph.
    rest = first.split("\n", 1)[1] if "\n" in first else ""
    if rest.strip():
        cover.paragraphs[0] = rest.lstrip()
    else:
        cover.paragraphs.pop(0)
    logger.debug("Stripped role-in-title heading from cover letter")
    return cover


def generate_cover_letter(
    provider: BaseAIProvider,
    job: JobPosting,
    candidate: CandidateProfile,
    answers: AnswersBundle | None = None,
    output_language: str = "en",
) -> CoverLetter:
    answers = answers or AnswersBundle()
    cover = provider.generate_cover_letter(
        job, candidate, answers, output_language=output_language
    )
    # Apply deterministic post-processing regardless of provider so even
    # the offline FakeAIProvider gets the cleanup for free.
    cover = _strip_role_heading(cover, job)
    cover = _strip_duplicate_signoff(cover)
    return cover


def refine_cover_letter(
    provider: BaseAIProvider,
    current_cover_letter: CoverLetter,
    feedback: str,
    job: JobPosting,
    candidate: CandidateProfile,
    answers: AnswersBundle | None = None,
    output_language: str = "en",
    previous_explanation: str = "",
) -> RefinedCoverLetter:
    """Re-generate the cover letter with the user's feedback applied.

    Routes the request through the provider's
    :meth:`refine_cover_letter` and then runs the same deterministic
    safety nets the initial-generation path uses. The user's "Refine
    with AI" button on the cover-letter tab calls this function (the
    documents page resolves the active tab to ``"cover_letter"`` before
    emitting the signal).

    Returns a :class:`RefinedCoverLetter` carrying the cleaned cover
    letter plus the AI's 1-3 sentence ``explanation`` so the GUI can
    show what changed under the refine panel - same shape as the
    resume refine flow.
    """
    answers = answers or AnswersBundle()
    refined = provider.refine_cover_letter(
        current_cover_letter,
        feedback,
        job,
        candidate,
        answers,
        output_language=output_language,
        previous_explanation=previous_explanation,
    )
    # Apply the same safety nets the initial-generation path uses so a
    # refined draft can never reintroduce a "Cover letter for X at Y"
    # heading or a duplicate sign-off, regardless of which provider
    # produced the refined output.
    refined.cover_letter = _strip_role_heading(refined.cover_letter, job)
    refined.cover_letter = _strip_duplicate_signoff(refined.cover_letter)
    return refined


__all__ = [
    "generate_cover_letter",
    "refine_cover_letter",
    "_strip_duplicate_signoff",
    "_strip_role_heading",
]
