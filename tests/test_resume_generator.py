"""Tests for the tailored-resume generator.

Covers two safety nets:

* :func:`ensure_projects_section` re-injects a GitHub project when the AI
  drops it (the fallback guarantees at least one project survives
  whenever the candidate has any GitHub data to draw from).
* :func:`refine_tailored_resume` re-injects missing experience rows when
  the user feedback says "missing/chybí" and writes a one-liner into the
  ``RefinedResume.explanation`` so the GUI can show the user what
  actually happened.
"""
from __future__ import annotations

from collections.abc import Sequence

from src.ai.base import BaseAIProvider
from src.models.candidate import (
    CandidateProfile,
    GitHubProject,
    WorkExperience,
)
from src.models.documents import (
    RefinedResume,
    ResumeBullet,
    ResumeSection,
    TailoredResume,
)
from src.models.evidence import EvidenceItem
from src.models.job import JobPosting
from src.models.match import AnswersBundle
from src.services.resume_generator import (
    _dedup_resume_sections,
    _fixup_education_language,
    _looks_czech,
    _normalize_project_title,
    _project_title_is_evidenced,
    _strip_invented_projects,
    _translate_period,
    ensure_projects_section,
    refine_tailored_resume,
)


def _make_resume(projects: list[ResumeSection] | None = None) -> TailoredResume:
    return TailoredResume(
        name="Test Candidate",
        professional_summary="Software engineer.",
        technical_skills=["Python"],
        projects=projects or [],
        role_targeted_for="Backend Developer",
    )


def test_ensure_projects_section_is_noop_when_resume_already_has_projects():
    existing = ResumeSection(
        title="My App",
        subtitle="Python",
        bullets=[ResumeBullet(text="Existing bullet.")],
    )
    resume = _make_resume([existing])
    candidate = CandidateProfile(
        full_name="X",
        projects=[
            GitHubProject(
                name="other-repo",
                url="https://github.com/x/other-repo",
                description="Should NOT be injected because we already have one.",
                stars=10,
            ),
        ],
    )
    out = ensure_projects_section(resume, candidate)
    assert out is resume
    assert len(out.projects) == 1
    assert out.projects[0].title == "My App"


def test_ensure_projects_section_is_noop_when_no_github_projects():
    resume = _make_resume([])
    candidate = CandidateProfile(full_name="X")
    out = ensure_projects_section(resume, candidate)
    assert out.projects == []


def test_ensure_projects_section_injects_highest_relevance_project():
    """When the AI returned an empty Projects section but the candidate has
    GitHub repos, we inject ONE fallback project ranked by
    (relevance, stars, description length)."""
    resume = _make_resume([])
    high_rel = GitHubProject(
        name="ai-resume-tool",
        url="https://github.com/x/ai-resume-tool",
        description="Tailored resume generator using OpenAI.",
        primary_language="Python",
        stars=2,
        relevance_score=0.85,
    )
    high_stars = GitHubProject(
        name="popular-cli",
        url="https://github.com/x/popular-cli",
        description="Tiny CLI tool.",
        primary_language="Go",
        stars=120,
        relevance_score=0.1,
    )
    candidate = CandidateProfile(full_name="X", projects=[high_stars, high_rel])
    out = ensure_projects_section(resume, candidate)
    assert len(out.projects) == 1
    section = out.projects[0]
    assert section.title == "ai-resume-tool"
    # Subtitle should include language + stars + url for transparency.
    assert "Python" in section.subtitle
    assert "https://github.com/x/ai-resume-tool" in section.subtitle
    assert section.bullets and section.bullets[0].text


def test_ensure_projects_section_falls_back_to_stars_then_description():
    """With equal relevance, the one with more stars wins. With equal stars,
    the one with the longer description wins."""
    resume = _make_resume([])
    short = GitHubProject(
        name="short",
        url="https://github.com/x/short",
        description="Short.",
        stars=5,
        relevance_score=0.3,
    )
    long = GitHubProject(
        name="long",
        url="https://github.com/x/long",
        description="A much longer and richer description that gives the AI more to work with.",
        stars=5,
        relevance_score=0.3,
    )
    candidate = CandidateProfile(full_name="X", projects=[short, long])
    out = ensure_projects_section(resume, candidate)
    assert out.projects[0].title == "long"


# ---------------------------------------------------------------------------
# refine_tailored_resume + RefinedResume safety net
# ---------------------------------------------------------------------------

class _StubProvider(BaseAIProvider):
    """Minimal provider stub: returns a pre-built ``RefinedResume``.

    Concrete subclasses fill ``next_resume`` and ``next_explanation``
    before the test calls :func:`refine_tailored_resume`. All other
    abstract methods raise so we never accidentally exercise other AI
    capabilities.
    """

    name = "stub"
    is_demo = True

    def __init__(self, refined: RefinedResume) -> None:
        self._refined = refined
        self.received_feedback: str | None = None
        self.received_lang: str | None = None

    def refine_resume(  # type: ignore[override]
        self,
        current_resume: TailoredResume,
        feedback: str,
        job: JobPosting,
        candidate: CandidateProfile,
        answers: AnswersBundle,
        evidence: Sequence[EvidenceItem] = (),
        output_language: str = "en",
    ) -> RefinedResume:
        self.received_feedback = feedback
        self.received_lang = output_language
        return self._refined

    # --- everything else is a NotImplementedError so the test never
    #     accidentally takes another code path ---
    def analyze_job(self, raw_text, source_url=None):
        raise NotImplementedError

    def analyze_candidate(self, cv_text="", linkedin_text="", github_username=None, github_projects=()):
        raise NotImplementedError

    def generate_clarifying_questions(self, job, candidate, output_language="en"):
        raise NotImplementedError

    def generate_match_report(self, job, candidate, answers, evidence=(), output_language="en"):
        raise NotImplementedError

    def generate_resume(self, job, candidate, answers, evidence=(), output_language="en"):
        raise NotImplementedError

    def generate_cover_letter(self, job, candidate, answers, output_language="en"):
        raise NotImplementedError

    def generate_interview_questions(self, job, candidate, output_language="en"):
        raise NotImplementedError

    def generate_skill_gap_plan(self, match_report, job, output_language="en"):
        raise NotImplementedError


def _make_job() -> JobPosting:
    return JobPosting(title="QA Engineer", company="Acme")


def _make_candidate_with_two_qa_roles() -> CandidateProfile:
    """Reproduces the user's 'Junior Avast got dropped' scenario."""
    return CandidateProfile(
        full_name="Test Candidate",
        experience=[
            WorkExperience(
                id="exp-junior",
                title="Junior Software QA Engineer",
                company="Avast Software",
                period="04/2022 - 06/2023",
                bullets=["Manual regression suite for AVG."],
                source="linkedin",
            ),
            WorkExperience(
                id="exp-senior",
                title="Senior Software QA Engineer",
                company="Gen Digital",
                period="07/2025 - present",
                bullets=["Lead QA across the trust portfolio."],
                source="cv",
            ),
        ],
    )


def _make_resume_missing_junior() -> TailoredResume:
    """Resume the AI returned that silently dropped the Junior row."""
    return TailoredResume(
        name="Test Candidate",
        professional_summary="QA engineer.",
        technical_skills=["Python", "Playwright"],
        experience=[
            ResumeSection(
                title="Senior Software QA Engineer",
                subtitle="Gen Digital",
                period="07/2025 - present",
                bullets=[ResumeBullet(text="Lead QA across the trust portfolio.")],
            ),
        ],
        role_targeted_for="QA Engineer",
    )


def test_refine_tailored_resume_returns_refined_resume_with_resume_field():
    """The new contract: ``refine_tailored_resume`` must return a
    :class:`RefinedResume` instance carrying both an updated resume and
    an explanation. Old code that expected a plain ``TailoredResume`` no
    longer compiles - this test pins the new shape down.
    """
    candidate = _make_candidate_with_two_qa_roles()
    starting = _make_resume_missing_junior()
    refined = RefinedResume(resume=starting, explanation="AI wrote this.")
    provider = _StubProvider(refined)

    out = refine_tailored_resume(
        provider, starting, "looks fine", _make_job(), candidate,
        output_language="en",
    )

    assert isinstance(out, RefinedResume)
    assert isinstance(out.resume, TailoredResume)
    assert out.explanation  # never empty when AI gave any note
    assert "AI wrote this." in out.explanation


def test_refine_safety_net_reinjects_missing_avast_role_on_explicit_feedback():
    """When the user says 'chybí pozice X' and the AI returns a resume
    that still doesn't contain X, the Python safety net re-injects the
    missing row from the candidate profile and tells the user about it
    in the explanation.
    """
    candidate = _make_candidate_with_two_qa_roles()
    starting = _make_resume_missing_junior()
    # AI returns the same incomplete resume - the safety net must save us.
    ai_returned = TailoredResume.model_validate(starting.model_dump())
    ai_returned.professional_summary = "Updated by AI."
    refined_from_ai = RefinedResume(
        resume=ai_returned,
        explanation="Aktualizoval jsem profesní shrnutí.",
    )
    provider = _StubProvider(refined_from_ai)

    out = refine_tailored_resume(
        provider, starting,
        "Chybí ti pozice Junior Software QA Engineer @ Avast Software.",
        _make_job(), candidate,
        output_language="cs",
    )

    titles = [s.title for s in out.resume.experience]
    assert "Junior Software QA Engineer" in titles
    # Both the AI's original explanation AND the safety-net line must
    # appear so the user sees the full picture.
    assert "Aktualizoval jsem profesní shrnutí." in out.explanation
    assert "Junior Software QA Engineer" in out.explanation
    assert "Avast Software" in out.explanation


def test_refine_safety_net_announces_silent_additions_too():
    """Even when the user did NOT ask for the row explicitly, the
    safety net still re-injects missing experience and announces it
    (the user must never be surprised by silent additions)."""
    candidate = _make_candidate_with_two_qa_roles()
    starting = _make_resume_missing_junior()
    ai_returned = TailoredResume.model_validate(starting.model_dump())
    refined_from_ai = RefinedResume(resume=ai_returned, explanation="Drobné úpravy.")
    provider = _StubProvider(refined_from_ai)

    # Feedback that doesn't mention the missing row - just stylistic.
    out = refine_tailored_resume(
        provider, starting, "Make the summary punchier please.",
        _make_job(), candidate,
        output_language="en",
    )

    titles = [s.title for s in out.resume.experience]
    assert "Junior Software QA Engineer" in titles
    # English locale -> English message.
    assert "Junior Software QA Engineer" in out.explanation
    assert "Avast Software" in out.explanation


def test_refine_no_safety_net_when_resume_already_complete():
    """When the AI already returned the full resume the safety net
    must not append spurious 'we re-added X' lines."""
    candidate = _make_candidate_with_two_qa_roles()
    # Build a resume that already contains BOTH candidate roles.
    full = TailoredResume(
        name="Test Candidate",
        professional_summary="QA engineer.",
        technical_skills=["Python"],
        experience=[
            ResumeSection(
                title="Junior Software QA Engineer",
                subtitle="Avast Software",
                period="04/2022 - 06/2023",
                bullets=[ResumeBullet(text="Did things.")],
            ),
            ResumeSection(
                title="Senior Software QA Engineer",
                subtitle="Gen Digital",
                period="07/2025 - present",
                bullets=[ResumeBullet(text="Did more things.")],
            ),
        ],
        role_targeted_for="QA Engineer",
    )
    refined_from_ai = RefinedResume(
        resume=full, explanation="No structural changes."
    )
    provider = _StubProvider(refined_from_ai)

    out = refine_tailored_resume(
        provider, full, "Looks great.",
        _make_job(), candidate,
        output_language="en",
    )

    # AI's note survives; nothing else is appended.
    assert out.explanation == "No structural changes."


def test_refine_uses_czech_safety_net_message_when_output_language_cs():
    """Locale-aware messages: a Czech resume gets the Czech safety-net
    line, not the English one."""
    candidate = _make_candidate_with_two_qa_roles()
    starting = _make_resume_missing_junior()
    ai_returned = TailoredResume.model_validate(starting.model_dump())
    refined_from_ai = RefinedResume(resume=ai_returned, explanation="")
    provider = _StubProvider(refined_from_ai)

    # Feedback uses Czech "chybi" keyword to make the explicit-add path fire.
    out = refine_tailored_resume(
        provider, starting, "chybi mi tam Junior Avast",
        _make_job(), candidate,
        output_language="cs",
    )

    # Czech wording is selected; the English version must NOT appear.
    assert "Bezpečnostní vrstva" in out.explanation
    assert "Safety net" not in out.explanation


def test_refine_passes_feedback_and_language_to_provider():
    """Smoke check: the wrapper hands the user's text and the chosen
    output language straight to the underlying provider unchanged."""
    candidate = _make_candidate_with_two_qa_roles()
    starting = _make_resume_missing_junior()
    refined_from_ai = RefinedResume(resume=starting, explanation="")
    provider = _StubProvider(refined_from_ai)

    refine_tailored_resume(
        provider, starting, "verbatim feedback",
        _make_job(), candidate,
        output_language="cs",
    )

    assert provider.received_feedback == "verbatim feedback"
    assert provider.received_lang == "cs"


# ---------------------------------------------------------------------------
# Output-side dedup of duplicate experience / project rows
# ---------------------------------------------------------------------------

def test_dedup_resume_sections_collapses_duplicate_experience_rows():
    """When the AI emits both an English and a Czech twin of the same
    role, the deterministic dedup pass must keep just one row with the
    union of bullets."""
    resume = TailoredResume(
        name="Test",
        professional_summary="QA.",
        experience=[
            ResumeSection(
                title="Software QA Engineer",
                subtitle="Gen Digital",
                period="06/2023 - 07/2025",
                bullets=[ResumeBullet(text="Backend Python E2E")],
            ),
            ResumeSection(
                title="Software QA Engineer",
                subtitle="Gen Digital",
                period="06/2023 - 07/2025",
                bullets=[ResumeBullet(text="REST API testing")],
            ),
        ],
    )
    _dedup_resume_sections(resume)
    assert len(resume.experience) == 1
    bullet_texts = [b.text for b in resume.experience[0].bullets]
    assert "Backend Python E2E" in bullet_texts
    assert "REST API testing" in bullet_texts


def test_dedup_resume_sections_keeps_career_progression_distinct():
    """Junior and Senior at the same company must NEVER be merged - the
    seniority guard from profile_dedup applies here too."""
    resume = TailoredResume(
        name="Test",
        professional_summary="QA.",
        experience=[
            ResumeSection(
                title="Junior Software QA Engineer",
                subtitle="Gen Digital",
                period="04/2022 - 06/2023",
                bullets=[ResumeBullet(text="Junior bullet.")],
            ),
            ResumeSection(
                title="Senior Software QA Engineer",
                subtitle="Gen Digital",
                period="07/2025 - present",
                bullets=[ResumeBullet(text="Senior bullet.")],
            ),
        ],
    )
    _dedup_resume_sections(resume)
    titles = [s.title for s in resume.experience]
    assert "Junior Software QA Engineer" in titles
    assert "Senior Software QA Engineer" in titles


def test_dedup_resume_sections_dedups_repeated_bullets():
    """Two identical bullets within the SAME section (one of the AI's
    favourite mistakes) collapse to one without affecting other rows."""
    resume = TailoredResume(
        name="Test",
        professional_summary="QA.",
        experience=[
            ResumeSection(
                title="QA Engineer",
                subtitle="Acme",
                period="2020 - 2022",
                bullets=[
                    ResumeBullet(text="Backend Python E2E"),
                    ResumeBullet(text="Backend Python E2E"),
                    ResumeBullet(text="REST API testing"),
                ],
            ),
        ],
    )
    _dedup_resume_sections(resume)
    bullets = resume.experience[0].bullets
    assert len(bullets) == 2
    texts = [b.text for b in bullets]
    assert texts.count("Backend Python E2E") == 1


def test_dedup_resume_sections_collapses_duplicate_projects():
    resume = TailoredResume(
        name="Test",
        professional_summary="QA.",
        projects=[
            ResumeSection(title="ApplyPilot AI", subtitle="Python"),
            ResumeSection(title="applypilot-ai", subtitle="Python"),
        ],
    )
    _dedup_resume_sections(resume)
    assert len(resume.projects) == 1


# ---------------------------------------------------------------------------
# Anti-hallucinated projects
# ---------------------------------------------------------------------------

def test_normalize_project_title_is_diacritics_and_punctuation_insensitive():
    assert _normalize_project_title("ApplyPilot-AI") == "applypilot ai"
    assert _normalize_project_title("Žížala_Foo") == _normalize_project_title("zizala foo")


def test_project_title_is_evidenced_matches_github_repo_name():
    candidate = CandidateProfile(
        full_name="X",
        projects=[
            GitHubProject(name="applypilot-ai", url="https://x/a"),
        ],
    )
    assert _project_title_is_evidenced("ApplyPilot AI", candidate)
    assert _project_title_is_evidenced("applypilot-ai", candidate)


def test_project_title_is_evidenced_falls_back_to_raw_text():
    """When the AI used a CV-style name not present in the repo list, the
    safety net should still match it via raw_cv_text."""
    candidate = CandidateProfile(
        full_name="X",
        raw_cv_text="Built an internal QA toolkit in Python with Playwright.",
    )
    assert _project_title_is_evidenced("internal QA toolkit", candidate)


def test_strip_invented_projects_drops_unverified_titles():
    candidate = CandidateProfile(
        full_name="X",
        projects=[GitHubProject(name="real-repo", url="https://x/r")],
        raw_cv_text="Worked on real-repo.",
    )
    resume = TailoredResume(
        name="X",
        professional_summary="QA.",
        projects=[
            ResumeSection(title="real-repo", subtitle="Python"),
            ResumeSection(
                title="AI workflow agents for QA context",
                subtitle="LLM, Jira, Confluence",
            ),
        ],
    )
    dropped = _strip_invented_projects(resume, candidate)
    assert dropped == ["AI workflow agents for QA context"]
    titles = [s.title for s in resume.projects]
    assert titles == ["real-repo"]


# ---------------------------------------------------------------------------
# Bidirectional CS<->EN cleanup
# ---------------------------------------------------------------------------

def test_looks_czech_detects_diacritics_and_keywords():
    assert _looks_czech("Provozně ekonomická fakulta")
    assert _looks_czech("praha metropolitni oblast")
    assert not _looks_czech("Faculty of Economics")


def test_translate_period_cs_months_become_numeric_in_english_resume():
    assert _translate_period("ledna 2021 - července 2023", "en").startswith("01/2021")
    assert "07/2023" in _translate_period("ledna 2021 - července 2023", "en")
    assert _translate_period("06/2020 - současnost", "en") == "06/2020 - present"


def test_translate_period_round_trips_present_to_czech():
    assert _translate_period("06/2020 - present", "cs") == "06/2020 - současnost"


def test_fixup_education_language_translates_czech_residue_in_english_resume():
    """A user picked English output but the AI left the Czech faculty
    name; the cleanup pass must rewrite it to English."""
    resume = TailoredResume(
        name="X",
        professional_summary="QA.",
        education=[
            ResumeSection(
                title="Provozně ekonomická fakulta",
                subtitle="Česká zemědělská univerzita v Praze",
                period="ledna 2021 - července 2023",
            ),
        ],
        experience=[
            ResumeSection(
                title="Vývojář Python",
                subtitle="CreatiWeb",
                period="06/2020 - současnost",
                bullets=[ResumeBullet(text="Worked on chatbots.")],
            ),
        ],
    )
    _fixup_education_language(resume, "en")
    edu = resume.education[0]
    assert "Faculty of Economics" in edu.title
    assert "Czech University of Life Sciences" in edu.subtitle
    assert "Prague" in edu.subtitle
    assert "01/2021" in edu.period and "07/2023" in edu.period
    exp = resume.experience[0]
    assert "Developer" in exp.title
    assert exp.period == "06/2020 - present"


def test_fixup_education_language_still_translates_english_to_czech():
    resume = TailoredResume(
        name="X",
        professional_summary="QA.",
        education=[
            ResumeSection(
                title="Bachelor of Computer Science",
                subtitle="Faculty of Economics and Management, Prague",
                period="2018 - 2021",
            ),
        ],
    )
    _fixup_education_language(resume, "cs")
    edu = resume.education[0]
    assert "Bakal" in edu.title
    assert "Provozně ekonomická" in edu.subtitle
    assert "Praha" in edu.subtitle
