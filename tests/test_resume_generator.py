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


# ---------------------------------------------------------------------------
# Issue 2: cross-language / employment-type-suffix dedup of experience rows
# ---------------------------------------------------------------------------


def test_dedup_resume_sections_collapses_internship_suffix_and_separator():
    """Reproduces the original bug report: two ``Developer (Python ...)``
    rows where one carries an ``"Internship"`` suffix and ASCII dashes
    while the twin uses Czech middle-dots survived dedup before the
    fuzzy match was added. Both rows describe the same role; one
    survivor is correct.
    """
    resume = TailoredResume(
        name="Test",
        professional_summary="Developer.",
        experience=[
            ResumeSection(
                title="Developer (Python - Chatbot - Game dev)",
                subtitle="CreatiWeb - AppYours - IBM - Internship",
                period="2019 - 2020",
                bullets=[ResumeBullet(text="Python game development a IBM Watson chatbot.")],
            ),
            ResumeSection(
                title="Developer (Python · Chatbot · Game dev)",
                subtitle="CreatiWeb · AppYours · IBM",
                period="2019 - 2020",
                bullets=[ResumeBullet(text="Python game development and IBM Watson chatbot.")],
            ),
        ],
    )
    _dedup_resume_sections(resume)
    assert len(resume.experience) == 1
    bullets = [b.text for b in resume.experience[0].bullets]
    assert any("Watson" in b for b in bullets)


def test_dedup_resume_sections_collapses_when_only_subtitle_separator_differs():
    """The second twin has the very same subtitle but with a different
    set of separator characters - dedup must still merge."""
    resume = TailoredResume(
        name="Test",
        professional_summary="Developer.",
        experience=[
            ResumeSection(
                title="Developer",
                subtitle="A | B | C",
                period="2020 - 2021",
                bullets=[ResumeBullet(text="One.")],
            ),
            ResumeSection(
                title="Developer",
                subtitle="A · B · C",
                period="2020 - 2021",
                bullets=[ResumeBullet(text="Two.")],
            ),
        ],
    )
    _dedup_resume_sections(resume)
    assert len(resume.experience) == 1


# ---------------------------------------------------------------------------
# Issue 3: refine respects an explicit "smaž / delete" instruction
# ---------------------------------------------------------------------------


def _candidate_with_two_roles_and_optional_first():
    """Two distinct roles: a "first job" that the user wants gone and a
    "current job" that should always survive. The first role lives only
    in the candidate profile (and in the resume the user is looking at)
    so the safety net would re-inject it without the new diff guard.
    """
    return CandidateProfile(
        full_name="Test",
        experience=[
            WorkExperience(
                id="exp-old",
                title="Junior Developer",
                company="OldCorp",
                period="2018 - 2019",
                bullets=["Wrote my first Python."],
                source="cv",
            ),
            WorkExperience(
                id="exp-current",
                title="Senior Engineer",
                company="NewCorp",
                period="2024 - present",
                bullets=["Lead the platform team."],
                source="cv",
            ),
        ],
    )


def _resume_with_two_roles():
    return TailoredResume(
        name="Test",
        professional_summary="Engineer.",
        technical_skills=["Python"],
        experience=[
            ResumeSection(
                title="Junior Developer",
                subtitle="OldCorp",
                period="2018 - 2019",
                bullets=[ResumeBullet(text="Wrote my first Python.")],
            ),
            ResumeSection(
                title="Senior Engineer",
                subtitle="NewCorp",
                period="2024 - present",
                bullets=[ResumeBullet(text="Lead the platform team.")],
            ),
        ],
        role_targeted_for="Engineer",
    )


def test_refine_with_delete_intent_does_not_reinject_dropped_role():
    """When the user types 'smaž tu pozici X' and the AI honours it,
    the experience safety net must NOT undo the deletion by re-adding
    the row from the candidate profile. Pre-fix this regressed the
    resume back to its original state."""
    candidate = _candidate_with_two_roles_and_optional_first()
    starting = _resume_with_two_roles()

    # AI returns a resume with the OldCorp row removed.
    refined = TailoredResume(
        name=starting.name,
        professional_summary=starting.professional_summary,
        technical_skills=list(starting.technical_skills),
        experience=[
            ResumeSection(
                title="Senior Engineer",
                subtitle="NewCorp",
                period="2024 - present",
                bullets=[ResumeBullet(text="Lead the platform team.")],
            ),
        ],
        role_targeted_for="Engineer",
    )
    provider = _StubProvider(RefinedResume(resume=refined, explanation="Smazáno."))

    out = refine_tailored_resume(
        provider, starting,
        "smaž pozici Junior Developer u OldCorp prosím",
        _make_job(), candidate,
        output_language="cs",
    )

    titles = [s.title for s in out.resume.experience]
    assert "Senior Engineer" in titles
    assert "Junior Developer" not in titles


def test_refine_without_delete_intent_keeps_safety_net_active():
    """Counter-test for the diff guard: a stylistic-only feedback must
    NOT disarm the safety net, otherwise we'd silently drop rows the AI
    accidentally lost. Same fixture but the user asks for prose
    polish, so the OldCorp role must come back."""
    candidate = _candidate_with_two_roles_and_optional_first()
    starting = _resume_with_two_roles()

    refined = TailoredResume(
        name=starting.name,
        professional_summary=starting.professional_summary,
        technical_skills=list(starting.technical_skills),
        experience=[
            ResumeSection(
                title="Senior Engineer",
                subtitle="NewCorp",
                period="2024 - present",
                bullets=[ResumeBullet(text="Lead the platform team.")],
            ),
        ],
        role_targeted_for="Engineer",
    )
    provider = _StubProvider(RefinedResume(resume=refined, explanation="Polished."))

    out = refine_tailored_resume(
        provider, starting,
        "Make the summary punchier please",
        _make_job(), candidate,
        output_language="en",
    )

    titles = [s.title for s in out.resume.experience]
    assert "Junior Developer" in titles
    assert "Senior Engineer" in titles


# ---------------------------------------------------------------------------
# Issue 6: bullet + summary scrubbing in CZ resume
# ---------------------------------------------------------------------------


def test_fixup_education_language_scrubs_acting_inside_czech_bullet():
    """The AI's favourite mistake: an otherwise Czech bullet that
    sneaks 'acting' through ('jako acting QA Lead'). The deterministic
    cleanup pass replaces it with 'pověřený' so the rendered resume is
    consistently Czech."""
    resume = TailoredResume(
        name="X",
        professional_summary="Software QA Engineer a acting QA Lead s 4 lety zkušeností.",
        experience=[
            ResumeSection(
                title="Software QA Engineer",
                subtitle="Gen Digital",
                period="06/2023 - 07/2025",
                bullets=[
                    ResumeBullet(
                        text="Jako acting QA Lead jsem vedl tým 2 QA inženýrů a koordinoval review.",
                    ),
                ],
            ),
        ],
    )
    _fixup_education_language(resume, "cs")
    bullet_text = resume.experience[0].bullets[0].text
    assert "acting" not in bullet_text.lower()
    assert "pověřený" in bullet_text.lower()
    # Summary is scrubbed too.
    assert "acting" not in resume.professional_summary.lower()
    assert "pověřený" in resume.professional_summary.lower()


def test_fixup_education_language_does_not_touch_unmapped_english_words():
    """Conservative scrub: we only translate words listed in our
    table. Unrelated English noise stays put so we don't accidentally
    Czech-ify product or technology names."""
    resume = TailoredResume(
        name="X",
        professional_summary="Senior Engineer at Gen Digital.",
        experience=[
            ResumeSection(
                title="Engineer",
                subtitle="Gen Digital",
                period="2024 - present",
                bullets=[ResumeBullet(text="Used Playwright for E2E testing.")],
            ),
        ],
    )
    _fixup_education_language(resume, "cs")
    # Unchanged because no key in the translation table appears.
    assert resume.professional_summary == "Senior Engineer at Gen Digital."
    assert resume.experience[0].bullets[0].text == "Used Playwright for E2E testing."


# ---------------------------------------------------------------------------
# Refine + already-excluded rows: the safety net must NEVER re-inject a
# row the user previously chose to drop via the discrepancy questions or
# the section-removal dialog. The fix lives in ``main_window`` (the GUI
# now passes ``filter_profile_entries(candidate, excluded_ids)`` to the
# refine call) but we pin the contract from the service-level here too:
# given a candidate that no longer contains the excluded row, the
# safety net has nothing to re-inject.
# ---------------------------------------------------------------------------


def test_refine_safety_net_does_not_resurrect_excluded_role_when_candidate_was_filtered():
    """Reproduces the 'IT Tester comes back on every refine' regression.

    In the GUI flow the user excluded the IT Tester row via the section-
    removal dialog. The full ``CandidateProfile`` on ``WorkflowState``
    still carries that row, but ``main_window`` now filters it out
    before calling ``refine_tailored_resume``. This test pins the
    contract: when the candidate handed to the refine flow does NOT
    contain the row, the safety net cannot bring it back even if the
    AI's output omits it and the feedback contains no delete keyword.
    """
    full_candidate = CandidateProfile(
        full_name="Test",
        experience=[
            WorkExperience(
                id="exp-keep",
                title="Software Developer",
                company="Air Bank a.s.",
                period="11/2021 - 01/2022",
                bullets=["Java backend."],
                source="cv",
            ),
            WorkExperience(
                id="exp-drop",
                title="IT Tester",
                company="Trask Solutions",
                period="08/2021 - 10/2021",
                bullets=["Manual QA."],
                source="cv",
            ),
        ],
    )
    from src.services.profile_dedup import filter_profile_entries
    candidate = filter_profile_entries(full_candidate, {"exp-drop"})

    starting = TailoredResume(
        name="Test",
        professional_summary="Developer.",
        technical_skills=["Java"],
        experience=[
            ResumeSection(
                title="Software Developer",
                subtitle="Air Bank a.s.",
                period="11/2021 - 01/2022",
                bullets=[ResumeBullet(text="Java backend.")],
            ),
            ResumeSection(
                title="IT Tester",
                subtitle="Trask Solutions",
                period="08/2021 - 10/2021",
                bullets=[ResumeBullet(text="Manual QA.")],
            ),
        ],
        role_targeted_for="Developer",
    )
    refined = TailoredResume(
        name="Test",
        professional_summary="Developer.",
        technical_skills=["Java"],
        experience=[
            ResumeSection(
                title="Software Developer",
                subtitle="Air Bank a.s.",
                period="11/2021 - 01/2022",
                bullets=[ResumeBullet(text="Java backend.")],
            ),
        ],
        role_targeted_for="Developer",
    )
    provider = _StubProvider(RefinedResume(resume=refined, explanation="Translated."))

    # Stylistic feedback - no delete keyword. Without the GUI-side filter
    # the safety net would helpfully re-inject IT Tester from the FULL
    # candidate; with the filter the candidate has no such row and the
    # safety net stays quiet.
    out = refine_tailored_resume(
        provider, starting,
        "Translate the Software Developer bullet to Czech and bump German to B2.",
        _make_job(), candidate,
        output_language="cs",
    )

    titles = [s.title for s in out.resume.experience]
    assert "Software Developer" in titles
    assert "IT Tester" not in titles
    assert "IT Tester" not in (out.explanation or "")
