"""Tests for the export service: every artefact must be written and readable."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

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


def test_export_writes_all_ten_files(tmp_path: Path, fake_provider, sample_job_text, sample_cv_text):
    package = _build_package(fake_provider, sample_job_text, sample_cv_text)
    paths = export_package(package, tmp_path)

    expected = [
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
    for p in expected:
        assert p.exists(), f"Missing: {p}"
        assert p.stat().st_size > 0, f"Empty: {p}"

    # Resume MD should contain the candidate's name.
    assert package.tailored_resume.name in paths.resume_md.read_text(encoding="utf-8")

    # Match report MD should mention overall score.
    assert "Overall score" in paths.match_report_md.read_text(encoding="utf-8")

    # Evidence JSON must parse and contain "items".
    data = json.loads(paths.evidence_json.read_text(encoding="utf-8"))
    assert "items" in data

    # Summary HTML wraps the body and mentions the role.
    html = paths.summary_html.read_text(encoding="utf-8")
    assert "<html" in html
    assert package.job_posting.title in html

    # Styled resume HTML must be self-contained (sidebar + main + inlined CSS).
    styled = paths.resume_html.read_text(encoding="utf-8")
    assert '<aside class="sidebar">' in styled
    assert '<main class="main">' in styled
    assert "<style>" in styled
    assert package.tailored_resume.name in styled


def test_history_round_trip(tmp_path: Path, fake_provider, sample_job_text, sample_cv_text):
    package = _build_package(fake_provider, sample_job_text, sample_cv_text)
    export_package(package, tmp_path)
    entry = append_history(tmp_path, package)
    assert entry.match_score == package.match_report.overall_score
    entries = load_history(tmp_path)
    assert entries and entries[0].company == package.job_posting.company


def test_load_package_files_round_trip(tmp_path: Path, fake_provider, sample_job_text, sample_cv_text):
    package = _build_package(fake_provider, sample_job_text, sample_cv_text)
    paths = export_package(package, tmp_path)
    payload = load_package_files(paths.folder)

    assert payload.folder == paths.folder
    assert package.tailored_resume.name in payload.resume_md
    assert payload.cover_letter_md.startswith("# Cover letter")
    assert "Overall score" in payload.match_report_md
    assert payload.interview_md.startswith("# Interview Preparation")
    assert payload.skill_gap_md.startswith("# Skill Gap Plan")
    assert "<aside" in payload.styled_resume_html
    assert isinstance(payload.evidence, dict)
    assert "items" in payload.evidence


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
