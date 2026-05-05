"""Tests for the export service: every artefact must be written and readable."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from src.models.candidate import CandidateProfile
from src.models.documents import (
    ResumeBullet,
    ResumeSection,
    TailoredResume,
)
from src.models.match import AnswersBundle
from src.models.package import GeneratedApplicationPackage
from src.services.cover_letter_generator import generate_cover_letter
from src.services.export_service import (
    export_package,
    tailored_resume_to_styled_html,
)
from src.services.gap_plan_generator import generate_skill_gap_plan
from src.services.history_service import (
    append_history,
    load_history,
    load_package_files,
)
from src.services.interview_generator import generate_interview_questions
from src.services.match_engine import compute_match
from src.services.resume_generator import generate_tailored_resume


def _build_package(fake_provider, sample_job_text, sample_cv_text) -> GeneratedApplicationPackage:
    job = fake_provider.analyze_job(sample_job_text, source_url="https://x/job")
    candidate = fake_provider.analyze_candidate(cv_text=sample_cv_text)
    answers = AnswersBundle()
    report, evidence = compute_match(fake_provider, job, candidate, answers)
    resume = generate_tailored_resume(fake_provider, job, candidate, answers, evidence.items)
    cover = generate_cover_letter(fake_provider, job, candidate, answers)
    interview = generate_interview_questions(fake_provider, job, candidate)
    gaps = generate_skill_gap_plan(fake_provider, report, job)
    return GeneratedApplicationPackage(
        job_posting=job,
        candidate_profile=candidate,
        answers=answers,
        match_report=report,
        tailored_resume=resume,
        cover_letter=cover,
        interview_questions=interview,
        skill_gap_plan=gaps,
        evidence=evidence.items,
        generated_at=datetime.now(),
    )


def test_export_writes_every_user_doc(tmp_path: Path, fake_provider, sample_job_text, sample_cv_text):
    package = _build_package(fake_provider, sample_job_text, sample_cv_text)
    summary = export_package(package, tmp_path)
    paths = summary.paths

    # Markdown / DOCX / HTML for both documents always ship; PDF is best
    # effort and may be skipped when Playwright cannot launch a browser
    # in CI - covered by ``test_export_skips_pdf_when_renderer_unavailable``.
    expected_required = [
        paths.resume_md,
        paths.resume_docx,
        paths.resume_html,
        paths.cover_letter_md,
        paths.cover_letter_docx,
        paths.match_report_md,
        paths.interview_md,
        paths.skill_gap_md,
        paths.evidence_json,
        paths.summary_html,
    ]
    for p in expected_required:
        assert p.exists(), f"Missing: {p}"
        assert p.stat().st_size > 0, f"Empty: {p}"

    assert package.tailored_resume.name in paths.resume_md.read_text(encoding="utf-8")
    assert "Overall score" in paths.match_report_md.read_text(encoding="utf-8")

    data = json.loads(paths.evidence_json.read_text(encoding="utf-8"))
    assert "items" in data

    html = paths.summary_html.read_text(encoding="utf-8")
    assert "<html" in html
    assert package.job_posting.title in html

    # Default theme is the classic two-column teal layout, so the
    # styled HTML must still ship a sidebar + main column + inlined CSS.
    styled = paths.resume_html.read_text(encoding="utf-8")
    assert '<aside class="sidebar">' in styled
    assert '<main class="main">' in styled
    assert "<style>" in styled
    assert package.tailored_resume.name in styled


def test_export_uses_candidate_slug_for_resume_and_cover_filenames(
    tmp_path: Path, fake_provider, sample_job_text, sample_cv_text
):
    """Every resume / cover letter artefact is named ``{slug}_cv.*`` /
    ``{slug}_cover_letter.*`` so a recruiter who downloads the folder
    sees who the documents belong to without opening them. Match report
    / interview prep / skill gap / evidence keep generic filenames.
    """
    package = _build_package(fake_provider, sample_job_text, sample_cv_text)
    summary = export_package(package, tmp_path)
    paths = summary.paths

    from src.utils.slugify import name_slug

    expected_slug = name_slug(
        package.tailored_resume.name or package.candidate_profile.full_name
    )
    assert paths.resume_md.name == f"{expected_slug}_cv.md"
    assert paths.resume_docx.name == f"{expected_slug}_cv.docx"
    assert paths.resume_html.name == f"{expected_slug}_cv.html"
    assert paths.resume_pdf.name == f"{expected_slug}_cv.pdf"
    assert paths.cover_letter_md.name == f"{expected_slug}_cover_letter.md"
    assert paths.cover_letter_docx.name == f"{expected_slug}_cover_letter.docx"
    assert paths.cover_letter_pdf.name == f"{expected_slug}_cover_letter.pdf"
    # Non-personal artefacts stay on their stable names so re-opens never
    # have to scan for "the match report".
    assert paths.match_report_md.name == "match_report.md"
    assert paths.interview_md.name == "interview_questions.md"
    assert paths.skill_gap_md.name == "skill_gap_plan.md"
    assert paths.evidence_json.name == "evidence_report.json"


def test_export_skips_pdf_when_renderer_unavailable(
    tmp_path: Path, monkeypatch, fake_provider, sample_job_text, sample_cv_text
):
    """When Playwright can't launch a browser the markdown / docx / html
    must still ship and ``ExportSummary.pdf_skipped`` must be set so the
    GUI can surface a "install Chrome / Edge" hint."""
    from src.services import export_service

    def _boom(*_args, **_kwargs):
        raise export_service.PdfRendererUnavailableError(
            "no browser - test stub"
        )

    monkeypatch.setattr(export_service, "render_html_to_pdf", _boom)

    package = _build_package(fake_provider, sample_job_text, sample_cv_text)
    summary = export_package(package, tmp_path)

    assert summary.pdf_skipped is True
    assert "no browser" in summary.pdf_skip_reason
    # Markdown / DOCX / HTML still on disk:
    assert summary.paths.resume_md.exists()
    assert summary.paths.resume_html.exists()
    assert summary.paths.cover_letter_md.exists()
    # PDFs were not written:
    assert not summary.paths.resume_pdf.exists()
    assert not summary.paths.cover_letter_pdf.exists()


def test_history_round_trip(tmp_path: Path, fake_provider, sample_job_text, sample_cv_text):
    package = _build_package(fake_provider, sample_job_text, sample_cv_text)
    export_package(package, tmp_path)
    entry = append_history(tmp_path, package)
    assert entry.match_score == package.match_report.overall_score
    entries = load_history(tmp_path)
    assert entries and entries[0].company == package.job_posting.company


def test_load_package_files_round_trip(tmp_path: Path, fake_provider, sample_job_text, sample_cv_text):
    package = _build_package(fake_provider, sample_job_text, sample_cv_text)
    summary = export_package(package, tmp_path)
    payload = load_package_files(summary.folder)

    assert payload.folder == summary.folder
    assert package.tailored_resume.name in payload.resume_md
    # The cover letter markdown no longer carries a "Cover letter for X
    # at Y" heading - it must read as a direct message starting with the
    # salutation per the user's explicit request.
    assert "Cover letter for" not in payload.cover_letter_md
    assert "# Cover letter" not in payload.cover_letter_md
    assert payload.cover_letter_md.lstrip().startswith("Dear ") \
        or payload.cover_letter_md.lstrip().startswith("Vážený") \
        or payload.cover_letter_md.lstrip().startswith("Vážená")
    assert "Overall score" in payload.match_report_md
    assert payload.interview_md.startswith("# Interview Preparation")
    assert payload.skill_gap_md.startswith("# Skill Gap Plan")
    # Default theme is two-column-sidebar so ``<aside>`` survives.
    assert "<aside" in payload.styled_resume_html
    assert isinstance(payload.evidence, dict)
    assert "items" in payload.evidence


def test_load_package_files_back_compat_with_legacy_filenames(tmp_path: Path):
    """A folder still using the pre-rename ``tailored_resume.*`` /
    ``cover_letter.*`` filenames must keep loading - older saved
    analyses on disk should never need a manual rename to re-open."""
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "tailored_resume.md").write_text(
        "# John Doe\n\n## Profile\nSenior dev.\n", encoding="utf-8"
    )
    (legacy / "tailored_resume.html").write_text(
        '<html><body><aside class="sidebar"></aside></body></html>',
        encoding="utf-8",
    )
    (legacy / "cover_letter.md").write_text(
        "Dear Hiring Team,\n\nI am writing to ...\n\nBest regards,\nJohn Doe\n",
        encoding="utf-8",
    )
    (legacy / "match_report.md").write_text(
        "# Match Report\n\n**Overall score: 80 / 100**\n", encoding="utf-8"
    )

    payload = load_package_files(legacy)
    assert "John Doe" in payload.resume_md
    assert "Dear Hiring Team" in payload.cover_letter_md
    assert "<aside" in payload.styled_resume_html
    assert "Overall score" in payload.match_report_md


def test_load_package_files_handles_missing_folder(tmp_path: Path):
    # Pointing at an empty folder must still return a populated dataclass
    # with empty strings instead of raising.
    payload = load_package_files(tmp_path)
    assert payload.resume_md == ""
    assert payload.cover_letter_md == ""
    assert payload.match_report_md == ""
    assert payload.evidence == {}


def test_styled_html_uses_czech_labels_for_czech_resume():
    resume = TailoredResume(
        name="Jana Nováková",
        professional_summary=(
            "Zkušená QA inženýrka se 4 lety praxe v automatizaci testování, "
            "specializuji se na Playwright a Python. Vedu mentoring nových "
            "členů týmu."
        ),
        technical_skills=["Python", "Playwright", "Selenium", "Jenkins", "Docker", "Agile"],
        experience=[
            ResumeSection(
                title="Senior QA Engineer",
                subtitle="Gen Digital - Praha",
                bullets=[ResumeBullet(text="Spoluautor interního QA toolkitu.")],
            )
        ],
        role_targeted_for="QA Automation Engineer",
    )
    candidate = CandidateProfile(
        full_name="Jana Nováková",
        contact_email="jana@example.cz",
        location="Praha",
        spoken_languages=["Čeština (mateřský)", "Angličtina (C1)"],
    )
    html = tailored_resume_to_styled_html(resume, candidate)
    assert "Profil" in html
    assert "Pracovní zkušenosti" in html
    assert "Jazyky" in html
    # Skill grouping kicks in: at least one group label should appear.
    assert "skill-tag" in html
    # Localised contact section heading.
    assert "Kontakt" in html
    assert "jana@example.cz" in html


def test_styled_html_uses_english_labels_for_english_resume():
    resume = TailoredResume(
        name="John Doe",
        professional_summary="Experienced QA engineer with 4 years of automation experience.",
        technical_skills=["Python", "Playwright"],
        role_targeted_for="QA Automation Engineer",
    )
    html = tailored_resume_to_styled_html(resume)
    assert "Profile" in html
    assert "Tech Stack" in html
    # No Czech labels leak in.
    assert "Pracovní zkušenosti" not in html


def test_styled_html_does_not_render_tailored_for_paragraph_or_role():
    """The user explicitly asked for a generic-looking resume - we must
    not put 'Tailored for: ...' anywhere in the output, and the role
    should not appear under the candidate's name in the sidebar either.
    """
    resume = TailoredResume(
        name="John Doe",
        professional_summary="QA engineer.",
        technical_skills=["Python"],
        role_targeted_for="AI Software Engineer",
    )
    html = tailored_resume_to_styled_html(resume)
    assert "Tailored for" not in html
    assert "AI Software Engineer" not in html  # role not surfaced anywhere
    assert '<div class="role"' not in html
    assert '<p class="tailored"' not in html


def test_styled_html_does_not_double_encode_ampersand_in_section_labels():
    """Issue: `_RESUME_LABELS["cs"]["certifications"]` used to be the
    pre-encoded string ``"Certifikáty &amp; kurzy"``. After ``_esc()``
    it became ``"Certifikáty &amp;amp; kurzy"`` in the rendered HTML.
    Now that the dictionary holds a plain ``&`` we must see ``&amp;``
    exactly once and never the double-encoded ``&amp;amp;``.

    Skill GROUP labels are also translated in Czech mode (the user
    requested all sidebar headers in CS, including skill categories);
    those translations come from ``_SKILL_GROUP_LOCALISED_LABELS["cs"]``
    and must not regress the double-encoding fix either.
    """
    resume = TailoredResume(
        name="Jana Nováková",
        professional_summary="Testerka.",
        technical_skills=[
            "Python", "Playwright", "Jenkins", "Docker", "Git",
        ],
        certifications=["ISTQB Foundation"],
        role_targeted_for="QA",
    )
    html = tailored_resume_to_styled_html(resume, output_language="cs")
    assert "&amp;amp;" not in html
    assert "Certifikáty &amp; kurzy" in html
    # CS resume now shows the localised group header; the canonical
    # English "CI/CD & Tooling" must NOT leak into the rendered HTML.
    assert "CI/CD a nástroje" in html
    assert "CI/CD &amp; Tooling" not in html
    # Programovací jazyky / Frameworky are also expected to land in CS.
    assert "Programovací jazyky" in html or "Frameworky" in html
    # Double-encoded would have looked like "CI/CD &amp;amp; Tooling".
    assert "CI/CD &amp;amp;" not in html


def test_styled_html_uses_explicit_output_language_over_diacritic_sniff():
    """When `output_language` is passed it overrides the diacritic
    heuristic. A Czech-diacritic-heavy resume rendered with
    ``output_language='en'`` must still get English section labels.
    """
    resume = TailoredResume(
        name="Jana Nováková",
        professional_summary=(
            "Zkušená inženýrka se silnou orientací na automatizaci. "
            "Zaměřuji se na Playwright, Pythonové testy a Jenkins."
        ),
        technical_skills=["Python", "Playwright"],
        experience=[
            ResumeSection(
                title="Senior QA",
                subtitle="Gen Digital",
                bullets=[ResumeBullet(text="Vedl jsem tým automatizace.")],
            )
        ],
        role_targeted_for="QA",
    )
    html_en = tailored_resume_to_styled_html(resume, output_language="en")
    # Use closing-tag-anchored substrings so "Profile" doesn't trip the
    # bare-substring "Profil" check (and vice versa for Czech).
    assert "<h2>Profile</h2>" in html_en
    assert "<h2>Work Experience</h2>" in html_en
    assert "Pracovní zkušenosti" not in html_en

    html_cs = tailored_resume_to_styled_html(resume, output_language="cs")
    assert "<h2>Profil</h2>" in html_cs
    assert "<h2>Pracovní zkušenosti</h2>" in html_cs
    assert "<h2>Work Experience</h2>" not in html_cs


def test_resume_to_markdown_strips_em_and_en_dashes():
    """AI providers love em / en dashes. The exporter must scrub them
    so the user-facing markdown looks human-typed.
    """
    from src.services.export_service import resume_to_markdown

    resume = TailoredResume(
        name="John Doe",
        professional_summary="QA engineer \u2014 4 years \u2013 Playwright fan.",
        technical_skills=["Python"],
        experience=[
            ResumeSection(
                title="Senior QA \u2014 Gen Digital",
                subtitle="Praha \u2013 2021 \u2013 2025",
                bullets=[
                    ResumeBullet(text="Built \u201cawesome\u201d test suites \u2026"),
                ],
            )
        ],
    )
    md = resume_to_markdown(resume)
    assert "\u2014" not in md
    assert "\u2013" not in md
    assert "\u2026" not in md
    assert "\u201c" not in md and "\u201d" not in md
    assert "QA engineer - 4 years - Playwright fan." in md
    assert 'Built "awesome" test suites ...' in md


def test_styled_html_sidebar_uses_cs_language_names_for_czech_resume():
    """When `output_language='cs'` the spoken-language names rendered in
    the sidebar are translated to lowercase Czech (čeština / angličtina /
    slovenština / němčina) instead of the canonical English labels.
    """
    resume = TailoredResume(
        name="Jana Nováková",
        professional_summary="Testerka.",
        technical_skills=["Python"],
        role_targeted_for="QA",
    )
    candidate = CandidateProfile(
        full_name="Jana Nováková",
        spoken_languages=["Czech", "English", "Slovak", "German"],
    )
    html = tailored_resume_to_styled_html(resume, candidate, output_language="cs")
    # CS translations must be present.
    for cs_name in ("čeština", "angličtina", "slovenština", "němčina"):
        assert cs_name in html, f"missing {cs_name!r} in CS resume sidebar"
    # And the canonical English form should NOT survive verbatim in the
    # sidebar (it might still appear elsewhere, but not as a language row).
    assert "<span>Czech</span>" not in html
    assert "<span>English</span>" not in html


def test_styled_html_sidebar_keeps_english_language_names_for_english_resume():
    """English resumes keep the canonical English language names verbatim -
    the CS translation must not leak into an EN render.
    """
    resume = TailoredResume(
        name="John Doe",
        professional_summary="QA engineer.",
        technical_skills=["Python"],
        role_targeted_for="QA",
    )
    candidate = CandidateProfile(
        full_name="John Doe",
        spoken_languages=["Czech", "English"],
    )
    html = tailored_resume_to_styled_html(resume, candidate, output_language="en")
    assert "<span>Czech</span>" in html
    assert "<span>English</span>" in html
    assert "čeština" not in html
    assert "angličtina" not in html


def test_styled_html_sidebar_localises_location_for_czech_resume():
    """Common English place names ("Prague, Czech Republic") must render in
    Czech ("Praha, Česká republika") when the resume language is CS.
    """
    resume = TailoredResume(
        name="Jana Nováková",
        professional_summary="Testerka.",
        technical_skills=["Python"],
        role_targeted_for="QA",
    )
    candidate = CandidateProfile(
        full_name="Jana Nováková",
        location="Prague, Czech Republic",
    )
    html = tailored_resume_to_styled_html(resume, candidate, output_language="cs")
    assert "Praha" in html
    assert "Česká republika" in html
    # Original English form must NOT appear next to the @-icon contact line.
    assert "Prague, Czech Republic" not in html


def test_styled_html_sidebar_keeps_location_unchanged_for_english_resume():
    resume = TailoredResume(
        name="John Doe",
        professional_summary="QA engineer.",
        technical_skills=["Python"],
        role_targeted_for="QA",
    )
    candidate = CandidateProfile(
        full_name="John Doe",
        location="Prague, Czech Republic",
    )
    html = tailored_resume_to_styled_html(resume, candidate, output_language="en")
    assert "Prague, Czech Republic" in html
    assert "Praha" not in html


def test_styled_html_sidebar_uses_technologie_label_for_czech():
    """``Tech Stack`` must render as ``Technologie`` in CS mode (was the
    English ``Tech Stack`` literal even in CS resumes before this fix)."""
    resume = TailoredResume(
        name="Jana Nováková",
        professional_summary="Testerka.",
        technical_skills=["Python", "Playwright"],
        role_targeted_for="QA",
    )
    html_cs = tailored_resume_to_styled_html(resume, output_language="cs")
    assert "Technologie" in html_cs
    assert "Tech Stack" not in html_cs

    html_en = tailored_resume_to_styled_html(resume, output_language="en")
    assert "Tech Stack" in html_en
    assert "Technologie" not in html_en


def test_resume_to_markdown_localises_section_headers_for_czech():
    """``resume_to_markdown(..., output_language='cs')`` must use Czech
    section headers so the .md file matches the styled HTML wording."""
    from src.services.export_service import resume_to_markdown

    resume = TailoredResume(
        name="Jana Nováková",
        professional_summary="Testerka.",
        technical_skills=["Python"],
        experience=[
            ResumeSection(
                title="Senior QA",
                subtitle="Gen Digital",
                bullets=[ResumeBullet(text="Vedl jsem tým automatizace.")],
            )
        ],
        certifications=["ISTQB Foundation"],
        role_targeted_for="QA",
    )
    md_cs = resume_to_markdown(resume, output_language="cs")
    assert "## Profesionální shrnutí" in md_cs
    assert "## Technické dovednosti" in md_cs
    assert "## Pracovní zkušenosti" in md_cs
    assert "## Certifikáty" in md_cs

    md_en = resume_to_markdown(resume, output_language="en")
    assert "## Professional Summary" in md_en
    assert "## Technical Skills" in md_en
    assert "## Work Experience" in md_en
    assert "## Certifications" in md_en


# ---------------------------------------------------------------------------
# Bidirectional location translation
# ---------------------------------------------------------------------------

def test_localise_location_cs_to_en_handles_metropolitan_area():
    """The most-reported translation gap: 'Praha metropolitní oblast'
    leaking into an English resume must collapse to the canonical
    'Prague Metropolitan Area' phrase users expect."""
    from src.services.export_service import _localise_location

    out = _localise_location("Praha metropolitní oblast", "en")
    assert out == "Prague Metropolitan Area"


def test_localise_location_cs_to_en_translates_known_city_and_country():
    from src.services.export_service import _localise_location

    out = _localise_location("Plzeň, Česká republika", "en")
    # Comma-separated parts are translated independently and rejoined.
    assert "Pilsen" in out
    assert "Czech Republic" in out


def test_localise_location_en_to_cs_still_works():
    """Pre-existing EN -> CS direction must keep working unchanged."""
    from src.services.export_service import _localise_location

    out = _localise_location("Prague, Czech Republic", "cs")
    assert "Praha" in out
    assert "Česká republika" in out


def test_localise_location_passes_unknown_chunks_through_verbatim():
    """We never silently drop or fabricate place names - unknown tokens
    survive the round trip untouched."""
    from src.services.export_service import _localise_location

    assert _localise_location("Nowhere, Atlantis", "cs") == "Nowhere, Atlantis"
    assert _localise_location("Nowhere, Atlantis", "en") == "Nowhere, Atlantis"


def test_localise_location_styled_html_no_longer_leaks_metropolitan_area():
    """Integration check: a Czech location attached to an English resume
    must not appear in the rendered HTML in its Czech form."""
    resume = TailoredResume(
        name="John Doe",
        professional_summary="QA engineer.",
        technical_skills=["Python"],
        role_targeted_for="QA",
    )
    candidate = CandidateProfile(
        full_name="John Doe",
        location="Praha metropolitní oblast, Česká republika",
    )
    html = tailored_resume_to_styled_html(resume, candidate, output_language="en")
    assert "Prague Metropolitan Area" in html
    assert "Czech Republic" in html
    assert "Praha metropolitní oblast" not in html


# ---------------------------------------------------------------------------
# name_slug + filename-based naming
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "input_name, expected",
    [
        ("Jan Novak", "jan_novak"),
        ("Jan Novák", "jan_novak"),
        ("Jana Nováková", "jana_novakova"),
        ("Anna-Maria von Bismarck", "anna_maria_von_bismarck"),
        ("    spaced   name   ", "spaced_name"),
        ("", "applicant"),
        ("###", "applicant"),
        ("J. Doe", "j_doe"),
    ],
)
def test_name_slug_handles_diacritics_and_separators(input_name, expected):
    from src.utils.slugify import name_slug

    assert name_slug(input_name) == expected


# ---------------------------------------------------------------------------
# Visual themes
# ---------------------------------------------------------------------------
def test_every_theme_renders_with_unique_accent_colour():
    """Walk every shipped theme and assert its accent colour shows up
    uniquely in the rendered HTML so a future refactor cannot silently
    collapse all themes back into one."""
    from src.services.document_themes import RESUME_THEMES

    resume = TailoredResume(
        name="Jana Nováková",
        professional_summary="Testerka.",
        technical_skills=["Python", "Playwright", "Docker"],
        experience=[
            ResumeSection(
                title="Senior QA",
                subtitle="Gen Digital",
                bullets=[ResumeBullet(text="Built tests.")],
            )
        ],
        role_targeted_for="QA",
    )
    candidate = CandidateProfile(
        full_name="Jana Nováková",
        contact_email="jana@example.cz",
        spoken_languages=["Czech (native)", "English (C1)"],
    )

    seen_accents: set[str] = set()
    seen_html: set[str] = set()
    for slug, theme in RESUME_THEMES.items():
        html = tailored_resume_to_styled_html(
            resume, candidate, output_language="en", theme=slug
        )
        # The accent colour must appear inside the <style> block.
        assert theme.accent.lower() in html.lower(), (
            f"theme {slug!r} did not embed its accent {theme.accent!r}"
        )
        # And every theme's HTML body must differ from every other theme
        # (different layout structure or different palette in the CSS).
        body = html
        assert body not in seen_html, f"theme {slug!r} produced duplicate HTML"
        seen_html.add(body)
        seen_accents.add(theme.accent.lower())
    # We ship at least 6 themes, every accent unique.
    assert len(seen_accents) >= 6


def test_random_theme_returns_one_of_the_registered_themes():
    """The ``random`` slug must always resolve to a real theme - never
    leak as a literal string into the rendered HTML."""
    from src.services.document_themes import (
        RESUME_THEMES,
        resolve_theme,
    )

    for _ in range(10):
        chosen = resolve_theme("random")
        assert chosen.slug in RESUME_THEMES
        assert chosen.slug != "random"


def test_unknown_theme_slug_falls_back_to_default():
    from src.services.document_themes import (
        DEFAULT_THEME_SLUG,
        resolve_theme,
    )

    chosen = resolve_theme("not-a-real-theme")
    assert chosen.slug == DEFAULT_THEME_SLUG


def test_export_persists_resolved_theme_on_package(
    tmp_path: Path, fake_provider, sample_job_text, sample_cv_text
):
    """The exporter must persist the resolved theme slug on the package
    so reopening a saved analysis renders it identically. ``random``
    should be resolved to a concrete slug before storage."""
    package = _build_package(fake_provider, sample_job_text, sample_cv_text)
    export_package(package, tmp_path, theme="random")
    assert package.output_theme != "random"

    from src.services.document_themes import RESUME_THEMES
    assert package.output_theme in RESUME_THEMES


# ---------------------------------------------------------------------------
# Cover letter cleanup
# ---------------------------------------------------------------------------
def test_strip_duplicate_signoff_removes_trailing_kind_regards_name():
    """Issue: AI providers sometimes paste 'Kind regards, Jan Novák' at
    the end of the last paragraph AND populate the structured ``closing``/
    ``signature`` fields. The exporter prints both, so the saved file
    shows the sign-off twice. The deterministic safety net must drop
    the in-paragraph copy."""
    from src.models.documents import CoverLetter
    from src.services.cover_letter_generator import _strip_duplicate_signoff

    cover = CoverLetter(
        salutation="Dear Hiring Team,",
        paragraphs=[
            "I am writing to express my interest in the QA role.",
            (
                "I look forward to discussing the next steps.\n"
                "Kind regards,\nJan Novák"
            ),
        ],
        closing="Kind regards,",
        signature="Jan Novák",
    )
    cleaned = _strip_duplicate_signoff(cover)
    last = cleaned.paragraphs[-1]
    assert "Kind regards" not in last
    assert "Jan Novák" not in last
    assert "look forward" in last  # body content is preserved


def test_strip_duplicate_signoff_handles_diacritics_insensitive_match():
    """A signature with diacritics ('Jan Novák') tucked at the end of the
    last paragraph must be stripped even when the AI wrote it in
    ASCII-folded form ('Jan Novak') - i.e. the match is diacritics-
    and case-insensitive."""
    from src.models.documents import CoverLetter
    from src.services.cover_letter_generator import _strip_duplicate_signoff

    cover = CoverLetter(
        salutation="Vážený pane,",
        paragraphs=[
            "Mám zájem o pozici QA inženýra.",
            "Těším se na další kroky.\nS pozdravem, Jan Novak",
        ],
        closing="S pozdravem,",
        signature="Jan Novák",
    )
    cleaned = _strip_duplicate_signoff(cover)
    last = cleaned.paragraphs[-1]
    assert "S pozdravem" not in last
    assert "Jan Novak" not in last
    assert "Těším" in last


def test_strip_role_heading_drops_cover_letter_for_role_at_company():
    """The user explicitly asked for the cover letter NOT to start with
    'Cover letter for X at Y' - the role and company already live on the
    resume + the filename. The first paragraph must survive everything
    after the heading line."""
    from src.models.documents import CoverLetter
    from src.models.job import JobPosting
    from src.services.cover_letter_generator import _strip_role_heading

    cover = CoverLetter(
        salutation="Dear Hiring Team,",
        paragraphs=[
            "Cover letter for QA Engineer at ACME Inc.\nI am writing to express my interest...",
            "I look forward to discussing the next steps.",
        ],
        closing="Best regards,",
        signature="Jan Novak",
    )
    job = JobPosting(title="QA Engineer", company="ACME Inc.")
    cleaned = _strip_role_heading(cover, job)
    assert not cleaned.paragraphs[0].lower().startswith("cover letter for")
    assert "I am writing to express my interest" in cleaned.paragraphs[0]


def test_cover_letter_md_does_not_contain_role_heading_after_export(
    tmp_path: Path, fake_provider, sample_job_text, sample_cv_text
):
    """End-to-end: even if the AI emits a role heading, the saved
    markdown must never start with 'Cover letter -' / 'Cover letter for'."""
    package = _build_package(fake_provider, sample_job_text, sample_cv_text)
    summary = export_package(package, tmp_path)
    md = summary.paths.cover_letter_md.read_text(encoding="utf-8")
    first_line = md.lstrip().split("\n", 1)[0]
    assert "Cover letter for" not in md
    assert not first_line.startswith("# Cover letter")
    # The exported markdown must open with the salutation directly.
    assert (
        first_line.startswith("Dear ")
        or first_line.startswith("Vážený")
        or first_line.startswith("Vážená")
        or first_line.startswith("Hello")
    ), f"Unexpected first line: {first_line!r}"


# ---------------------------------------------------------------------------
# Cover letter styled HTML (used by the PDF renderer)
# ---------------------------------------------------------------------------
def test_cover_letter_styled_html_uses_chosen_theme_accent():
    """The cover letter HTML must pick up the resume theme's accent
    colour so the resume + cover PDFs ship as a visually consistent
    pair."""
    from src.models.documents import CoverLetter
    from src.services.document_themes import (
        RESUME_THEMES,
        cover_letter_to_styled_html,
    )

    cover = CoverLetter(
        salutation="Dear Hiring Team,",
        paragraphs=["I am writing about the QA role."],
        closing="Best regards,",
        signature="Jane Doe",
    )
    candidate = CandidateProfile(full_name="Jane Doe", contact_email="jane@example.com")

    burgundy = RESUME_THEMES["burgundy_serif"]
    indigo = RESUME_THEMES["indigo_header"]

    html_b = cover_letter_to_styled_html(cover, candidate, theme=burgundy)
    html_i = cover_letter_to_styled_html(cover, candidate, theme=indigo)
    assert burgundy.accent.lower() in html_b.lower()
    assert indigo.accent.lower() in html_i.lower()
    assert "Jane Doe" in html_b
    assert "I am writing about the QA role." in html_b
    # No role-in-title heading on top of the styled cover letter either.
    assert "Cover letter for" not in html_b
    # The two themes must produce visibly different markup.
    assert html_b != html_i
