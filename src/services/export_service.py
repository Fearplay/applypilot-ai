"""Render every artefact of a :class:`GeneratedApplicationPackage` to disk.

For one application we produce nine files in a single output folder:

* ``tailored_resume.md`` and ``tailored_resume.docx``
* ``cover_letter.md``    and ``cover_letter.docx``
* ``match_report.md``
* ``interview_questions.md``
* ``skill_gap_plan.md``
* ``evidence_report.json``
* ``application_summary.html`` (Markdown rendered to HTML)
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import markdown as md_lib

from ..models.documents import (
    CoverLetter,
    InterviewQuestion,
    SkillGap,
    TailoredResume,
)
from ..models.evidence import EvidenceItem
from ..models.match import MatchReport
from ..models.package import GeneratedApplicationPackage
from ..utils.file_utils import ensure_dir
from ..utils.slugify import slugify

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output path bundle
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ExportPaths:
    folder: Path
    resume_md: Path
    resume_docx: Path
    cover_letter_md: Path
    cover_letter_docx: Path
    match_report_md: Path
    interview_md: Path
    skill_gap_md: Path
    evidence_json: Path
    summary_html: Path

    def as_dict(self) -> dict[str, str]:
        return {k: str(v) for k, v in asdict(self).items()}


def build_output_folder(
    base_dir: str | Path, company: str, role: str, *, when: datetime | None = None
) -> Path:
    when = when or datetime.now()
    stamp = when.strftime("%Y%m%d-%H%M%S")
    folder_name = f"{slugify(company, fallback='unknown-company')}-" \
                  f"{slugify(role, fallback='unknown-role')}-{stamp}"
    folder = Path(base_dir) / folder_name
    ensure_dir(folder)
    return folder


def build_export_paths(folder: Path) -> ExportPaths:
    return ExportPaths(
        folder=folder,
        resume_md=folder / "tailored_resume.md",
        resume_docx=folder / "tailored_resume.docx",
        cover_letter_md=folder / "cover_letter.md",
        cover_letter_docx=folder / "cover_letter.docx",
        match_report_md=folder / "match_report.md",
        interview_md=folder / "interview_questions.md",
        skill_gap_md=folder / "skill_gap_plan.md",
        evidence_json=folder / "evidence_report.json",
        summary_html=folder / "application_summary.html",
    )


# ---------------------------------------------------------------------------
# Markdown renderers
# ---------------------------------------------------------------------------
def resume_to_markdown(resume: TailoredResume) -> str:
    parts: list[str] = []
    parts.append(f"# {resume.name}")
    contact_parts = [resume.contact_line] if resume.contact_line else []
    if resume.linkedin:
        contact_parts.append(f"LinkedIn: {resume.linkedin}")
    if resume.github:
        contact_parts.append(f"GitHub: {resume.github}")
    if resume.portfolio:
        contact_parts.append(f"Portfolio: {resume.portfolio}")
    if contact_parts:
        parts.append("  ".join(contact_parts))

    if resume.role_targeted_for:
        parts.append(f"\n*Tailored for:* **{resume.role_targeted_for}**")

    parts.append("\n## Professional Summary\n")
    parts.append(resume.professional_summary)

    if resume.technical_skills:
        parts.append("\n## Technical Skills\n")
        parts.append(", ".join(resume.technical_skills))

    def _section(title: str, items: list) -> None:
        if not items:
            return
        parts.append(f"\n## {title}\n")
        for s in items:
            parts.append(f"### {s.title}")
            if s.subtitle:
                parts.append(f"*{s.subtitle}*")
            for b in s.bullets:
                parts.append(f"- {b.text}")
            parts.append("")

    _section("Projects", resume.projects)
    _section("Experience", resume.experience)
    _section("Education", resume.education)

    if resume.certifications:
        parts.append("\n## Certifications\n")
        for cert in resume.certifications:
            parts.append(f"- {cert}")

    return "\n".join(parts).rstrip() + "\n"


def cover_letter_to_markdown(cover: CoverLetter) -> str:
    lines: list[str] = []
    if cover.role and cover.company:
        lines.append(f"# Cover letter - {cover.role} at {cover.company}")
    elif cover.role:
        lines.append(f"# Cover letter - {cover.role}")
    else:
        lines.append("# Cover letter")
    lines.append("")
    lines.append(cover.salutation)
    lines.append("")
    for para in cover.paragraphs:
        lines.append(para)
        lines.append("")
    lines.append(cover.closing)
    if cover.signature:
        lines.append(cover.signature)
    return "\n".join(lines).rstrip() + "\n"


def match_report_to_markdown(report: MatchReport, role_label: str = "") -> str:
    parts: list[str] = []
    title = "Match Report"
    if role_label:
        title += f" - {role_label}"
    parts.append(f"# {title}")
    parts.append(f"\n**Overall score: {report.overall_score} / 100**\n")
    parts.append("## Category scores\n")
    cs = report.category_scores
    parts.append(f"- Technical skills: {cs.technical_skills} / 100")
    parts.append(f"- Experience:       {cs.experience} / 100")
    parts.append(f"- Tools:            {cs.tools} / 100")
    parts.append(f"- Process / QA:     {cs.qa_process} / 100")

    parts.append("\n## Matched requirements\n")
    parts += [f"- {x}" for x in report.matched_requirements] or ["- (none)"]

    parts.append("\n## Missing requirements\n")
    parts += [f"- {x}" for x in report.missing_requirements] or ["- (none)"]

    if report.risky_gaps:
        parts.append("\n## Risky gaps\n")
        parts += [f"- {x}" for x in report.risky_gaps]

    parts.append("\n## ATS keywords\n")
    parts.append("**Present:** " + (", ".join(report.ats_keywords_present) or "(none)"))
    parts.append("**Missing:** " + (", ".join(report.ats_keywords_missing) or "(none)"))

    if report.recommended_improvements:
        parts.append("\n## Recommended improvements\n")
        parts += [f"- {x}" for x in report.recommended_improvements]

    if report.summary:
        parts.append("\n## Summary\n")
        parts.append(report.summary)

    return "\n".join(parts).rstrip() + "\n"


def interview_questions_to_markdown(questions: Iterable[InterviewQuestion]) -> str:
    parts: list[str] = ["# Interview Preparation\n"]
    for i, q in enumerate(questions, start=1):
        parts.append(f"## {i}. {q.question}")
        if q.category:
            parts.append(f"*Category: {q.category}*")
        if q.why_asked:
            parts.append(f"\n**Why this is asked:** {q.why_asked}")
        if q.suggested_answer:
            parts.append(f"\n**Suggested answer:** {q.suggested_answer}")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def skill_gap_to_markdown(gaps: Iterable[SkillGap]) -> str:
    parts: list[str] = ["# Skill Gap Plan\n"]
    for gap in gaps:
        parts.append(f"## {gap.skill}")
        parts.append(f"*Importance: {gap.importance}*")
        if gap.rationale:
            parts.append(f"\n**Why it matters:** {gap.rationale}")
        if gap.learning_path:
            parts.append("\n**Learning path:**")
            for step in gap.learning_path:
                parts.append(f"- {step}")
        if gap.suggested_project:
            parts.append(f"\n**Suggested project:** {gap.suggested_project}")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def evidence_report_to_dict(items: Iterable[EvidenceItem]) -> dict:
    return {
        "items": [item.model_dump(mode="json") for item in items],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# DOCX renderers (python-docx, ATS-friendly)
# ---------------------------------------------------------------------------
def resume_to_docx(resume: TailoredResume, path: str | Path) -> None:
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    name = doc.add_heading(resume.name, level=0)
    for run in name.runs:
        run.bold = True

    contact_bits = [resume.contact_line] if resume.contact_line else []
    if resume.linkedin:
        contact_bits.append(f"LinkedIn: {resume.linkedin}")
    if resume.github:
        contact_bits.append(f"GitHub: {resume.github}")
    if resume.portfolio:
        contact_bits.append(f"Portfolio: {resume.portfolio}")
    if contact_bits:
        doc.add_paragraph("  |  ".join(contact_bits))

    if resume.role_targeted_for:
        p = doc.add_paragraph()
        p.add_run(f"Tailored for: {resume.role_targeted_for}").italic = True

    doc.add_heading("Professional Summary", level=1)
    doc.add_paragraph(resume.professional_summary)

    if resume.technical_skills:
        doc.add_heading("Technical Skills", level=1)
        doc.add_paragraph(", ".join(resume.technical_skills))

    def _section(title: str, items: list) -> None:
        if not items:
            return
        doc.add_heading(title, level=1)
        for s in items:
            doc.add_heading(s.title, level=2)
            if s.subtitle:
                p = doc.add_paragraph()
                p.add_run(s.subtitle).italic = True
            for b in s.bullets:
                doc.add_paragraph(b.text, style="List Bullet")

    _section("Projects", resume.projects)
    _section("Experience", resume.experience)
    _section("Education", resume.education)

    if resume.certifications:
        doc.add_heading("Certifications", level=1)
        for cert in resume.certifications:
            doc.add_paragraph(cert, style="List Bullet")

    doc.save(str(path))


def cover_letter_to_docx(cover: CoverLetter, path: str | Path) -> None:
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    if cover.role and cover.company:
        doc.add_heading(f"Cover letter - {cover.role} at {cover.company}", level=1)
    elif cover.role:
        doc.add_heading(f"Cover letter - {cover.role}", level=1)

    doc.add_paragraph(cover.salutation)
    for para in cover.paragraphs:
        doc.add_paragraph(para)
    doc.add_paragraph(cover.closing)
    if cover.signature:
        doc.add_paragraph(cover.signature)

    doc.save(str(path))


# ---------------------------------------------------------------------------
# HTML application_summary.html
# ---------------------------------------------------------------------------
_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
          Helvetica, Arial, sans-serif; max-width: 880px; margin: 2em auto;
          padding: 0 1em; color: #1a1a1a; line-height: 1.55; }}
  h1, h2, h3 {{ color: #0b3d91; }}
  hr {{ border: none; border-top: 1px solid #ddd; margin: 2em 0; }}
  code, pre {{ background: #f4f4f8; padding: 2px 4px; border-radius: 4px; }}
  .meta {{ color: #666; font-size: 0.9em; }}
  .badge {{ display: inline-block; background: #0b3d91; color: white;
            padding: 2px 8px; border-radius: 12px; font-size: 0.85em; }}
</style>
</head>
<body>
<p class="meta">Generated by ApplyPilot AI on {generated_at}</p>
{body}
</body>
</html>
"""


def application_summary_to_html(package: GeneratedApplicationPackage) -> str:
    role_label = package.job_posting.title or "Unknown role"
    company = package.job_posting.company or ""
    title = f"{role_label}" + (f" at {company}" if company else "")
    score = package.match_report.overall_score

    sections_md: list[str] = [
        f"# Application summary - {title}",
        f"<p><span class='badge'>Match score: {score} / 100</span></p>",
        match_report_to_markdown(package.match_report, role_label=role_label),
        "---",
        resume_to_markdown(package.tailored_resume),
        "---",
        cover_letter_to_markdown(package.cover_letter),
        "---",
        interview_questions_to_markdown(package.interview_questions),
        "---",
        skill_gap_to_markdown(package.skill_gap_plan),
    ]
    body_md = "\n\n".join(sections_md)
    body_html = md_lib.markdown(body_md, extensions=["extra"])
    return _HTML_TEMPLATE.format(
        title=title,
        generated_at=package.generated_at.isoformat(timespec="seconds"),
        body=body_html,
    )


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------
def export_package(
    package: GeneratedApplicationPackage,
    base_dir: str | Path,
) -> ExportPaths:
    """Write all 9 artefacts of ``package`` into a fresh folder under ``base_dir``."""
    folder = build_output_folder(
        base_dir,
        company=package.job_posting.company,
        role=package.job_posting.title,
        when=package.generated_at,
    )
    paths = build_export_paths(folder)

    paths.resume_md.write_text(resume_to_markdown(package.tailored_resume), encoding="utf-8")
    resume_to_docx(package.tailored_resume, paths.resume_docx)

    paths.cover_letter_md.write_text(cover_letter_to_markdown(package.cover_letter), encoding="utf-8")
    cover_letter_to_docx(package.cover_letter, paths.cover_letter_docx)

    paths.match_report_md.write_text(
        match_report_to_markdown(package.match_report, role_label=package.job_posting.title),
        encoding="utf-8",
    )
    paths.interview_md.write_text(
        interview_questions_to_markdown(package.interview_questions), encoding="utf-8"
    )
    paths.skill_gap_md.write_text(
        skill_gap_to_markdown(package.skill_gap_plan), encoding="utf-8"
    )

    paths.evidence_json.write_text(
        json.dumps(evidence_report_to_dict(package.evidence), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    paths.summary_html.write_text(application_summary_to_html(package), encoding="utf-8")

    object.__setattr__(package, "output_dir", str(folder))
    logger.info("Exported application package to %s", folder)
    return paths


__all__ = [
    "ExportPaths",
    "build_output_folder",
    "build_export_paths",
    "resume_to_markdown",
    "cover_letter_to_markdown",
    "match_report_to_markdown",
    "interview_questions_to_markdown",
    "skill_gap_to_markdown",
    "evidence_report_to_dict",
    "resume_to_docx",
    "cover_letter_to_docx",
    "application_summary_to_html",
    "export_package",
]
