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

import html
import json
import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import markdown as md_lib

from ..models.candidate import CandidateProfile
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
from ..utils.text_cleaning import strip_ai_tells

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output path bundle
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ExportPaths:
    folder: Path
    resume_md: Path
    resume_docx: Path
    resume_html: Path
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
        resume_html=folder / "tailored_resume.html",
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

# Section headers used by the Markdown / DOCX resume renderers. Kept in sync
# with ``_RESUME_LABELS`` (which drives the styled HTML sidebar / main column)
# so both formats show the same wording for the same output language.
_RESUME_MD_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "summary": "Professional Summary",
        "skills": "Technical Skills",
        "projects": "Projects",
        "experience": "Work Experience",
        "education": "Education",
        "certifications": "Certifications",
    },
    "cs": {
        "summary": "Profesionální shrnutí",
        "skills": "Technické dovednosti",
        "projects": "Vlastní projekty",
        "experience": "Pracovní zkušenosti",
        "education": "Vzdělání",
        "certifications": "Certifikáty",
    },
}


def _md_labels(output_language: str) -> dict[str, str]:
    code = (output_language or "en").strip().lower()
    return _RESUME_MD_LABELS.get(code, _RESUME_MD_LABELS["en"])


def resume_to_markdown(resume: TailoredResume, output_language: str = "en") -> str:
    labels = _md_labels(output_language)
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

    parts.append(f"\n## {labels['summary']}\n")
    parts.append(resume.professional_summary)

    if resume.technical_skills:
        parts.append(f"\n## {labels['skills']}\n")
        parts.append(", ".join(resume.technical_skills))

    def _section(title: str, items: list) -> None:
        if not items:
            return
        parts.append(f"\n## {title}\n")
        for s in items:
            header = f"### {s.title}"
            if s.period:
                header += f" ({s.period})"
            parts.append(header)
            if s.subtitle:
                parts.append(f"*{s.subtitle}*")
            for b in s.bullets:
                parts.append(f"- {b.text}")
            parts.append("")

    _section(labels["projects"], resume.projects)
    _section(labels["experience"], resume.experience)
    _section(labels["education"], resume.education)

    if resume.certifications:
        parts.append(f"\n## {labels['certifications']}\n")
        for cert in resume.certifications:
            parts.append(f"- {cert}")

    return strip_ai_tells("\n".join(parts).rstrip()) + "\n"


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
    return strip_ai_tells("\n".join(lines).rstrip()) + "\n"


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

    return strip_ai_tells("\n".join(parts).rstrip()) + "\n"


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
    return strip_ai_tells("\n".join(parts).rstrip()) + "\n"


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
    return strip_ai_tells("\n".join(parts).rstrip()) + "\n"


def evidence_report_to_dict(items: Iterable[EvidenceItem]) -> dict:
    return {
        "items": [item.model_dump(mode="json") for item in items],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# DOCX renderers (python-docx, ATS-friendly)
# ---------------------------------------------------------------------------
def resume_to_docx(
    resume: TailoredResume, path: str | Path, output_language: str = "en"
) -> None:
    from docx import Document
    from docx.shared import Pt

    labels = _md_labels(output_language)

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    # Local alias - every text fragment we hand python-docx is scrubbed
    # for AI-tell punctuation (em/en-dashes, smart quotes, ellipsis,
    # exotic whitespace) so DOCX exports look as plain as the markdown
    # version.
    s = strip_ai_tells

    name = doc.add_heading(s(resume.name), level=0)
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
        doc.add_paragraph(s("  |  ".join(contact_bits)))

    doc.add_heading(labels["summary"], level=1)
    doc.add_paragraph(s(resume.professional_summary))

    if resume.technical_skills:
        doc.add_heading(labels["skills"], level=1)
        doc.add_paragraph(s(", ".join(resume.technical_skills)))

    def _section(title: str, items: list) -> None:
        if not items:
            return
        doc.add_heading(title, level=1)
        for section in items:
            heading_text = s(section.title)
            if section.period:
                heading_text += f" ({s(section.period)})"
            doc.add_heading(heading_text, level=2)
            if section.subtitle:
                p = doc.add_paragraph()
                p.add_run(s(section.subtitle)).italic = True
            for b in section.bullets:
                doc.add_paragraph(s(b.text), style="List Bullet")

    _section(labels["projects"], resume.projects)
    _section(labels["experience"], resume.experience)
    _section(labels["education"], resume.education)

    if resume.certifications:
        doc.add_heading(labels["certifications"], level=1)
        for cert in resume.certifications:
            doc.add_paragraph(s(cert), style="List Bullet")

    doc.save(str(path))


def cover_letter_to_docx(cover: CoverLetter, path: str | Path) -> None:
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    s = strip_ai_tells  # see resume_to_docx for the rationale

    if cover.role and cover.company:
        doc.add_heading(s(f"Cover letter - {cover.role} at {cover.company}"), level=1)
    elif cover.role:
        doc.add_heading(s(f"Cover letter - {cover.role}"), level=1)

    doc.add_paragraph(s(cover.salutation))
    for para in cover.paragraphs:
        doc.add_paragraph(s(para))
    doc.add_paragraph(s(cover.closing))
    if cover.signature:
        doc.add_paragraph(s(cover.signature))

    doc.save(str(path))


# ---------------------------------------------------------------------------
# Styled HTML resume (modern two-column A4 template)
# ---------------------------------------------------------------------------
_RESUME_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "profile": "Profile",
        "experience": "Work Experience",
        "projects": "Projects",
        "education": "Education",
        "certifications": "Certifications",
        "contact": "Contact",
        "online": "Online",
        "tech_stack": "Tech Stack",
        "languages": "Languages",
    },
    "cs": {
        "profile": "Profil",
        "experience": "Pracovní zkušenosti",
        "projects": "Vlastní projekty",
        "education": "Vzdělání",
        "certifications": "Certifikáty & kurzy",
        "contact": "Kontakt",
        "online": "Online",
        "tech_stack": "Technologie",
        "languages": "Jazyky",
    },
}

# Skill -> group mapping. Lowercased substring matching keeps the table small.
_SKILL_GROUP_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Test Automation", (
        "playwright", "selenium", "cypress", "pytest", "appium", "puppeteer",
        "webdriver", "page object", "robot framework", "testng", "junit",
    )),
    ("Languages", (
        "python", "java", "javascript", "typescript", "c#", "c++", "go ",
        "rust", "kotlin", "swift", "ruby", "php", "sql", "bash", "powershell",
        "scala",
    )),
    ("CI/CD & Tooling", (
        "jenkins", "teamcity", "docker", "kubernetes", "git", "github actions",
        "gitlab ci", "circleci", "jira", "linux", "azure devops", "ansible",
        "terraform", "vmware", "virtualization", "virtualisation",
    )),
    ("Frameworks", (
        "fastapi", "django", "flask", "react", "vue", "angular", "next.js",
        "nextjs", "express", "spring", "node.js", "nodejs", ".net",
    )),
    ("AI / Data", (
        "openai", "anthropic", "claude", "llm", "langchain", "rag",
        "pgvector", "faiss", "chroma", "pinecone", "pandas", "numpy",
        "scikit-learn", "pytorch", "tensorflow", "ai-asistovan",
        "prompt engineering",
    )),
    ("Databases", (
        "postgres", "postgresql", "mysql", "mongodb", "sqlite", "redis",
        "oracle db", "mssql",
    )),
    ("Methodology", (
        "agile", "scrum", "kanban", "tdd", "bdd", "test strategy",
        "framework design", "mentoring",
    )),
)

# Skill GROUP labels (the categories shown above the chip rows). Skill ITEMS
# (Playwright, C#, Pytest, ...) stay in their canonical English form because
# ATS bots and recruiters expect the industry vocabulary verbatim. The
# headers, however, are read by humans and were unintelligible to Czech
# speakers when left in English (especially "Languages", which collides
# semantically with "Jazyky" right below it). New locales can extend this
# table without touching `_localised_group_label`.
_SKILL_GROUP_LOCALISED_LABELS: dict[str, dict[str, str]] = {
    "cs": {
        "Test Automation": "Automatizace testů",
        "Languages": "Programovací jazyky",
        "CI/CD & Tooling": "CI/CD a nástroje",
        "Frameworks": "Frameworky",
        "AI / Data": "AI / Data",
        "Databases": "Databáze",
        "Methodology": "Metodiky",
        "Other": "Ostatní",
    },
    "en": {},
}

# Spoken language display names per output language. Keys are the canonical
# English labels emitted by ``profile_dedup._dedup_languages`` and used in
# ``CandidateProfile.spoken_languages`` (e.g. ``"Czech"``, ``"English"``).
# Czech-translated values follow standard Czech orthography (lowercase per CS
# convention for language names).
_LANGUAGE_DISPLAY_BY_LANG: dict[str, dict[str, str]] = {
    "cs": {
        "Czech": "čeština",
        "English": "angličtina",
        "Slovak": "slovenština",
        "German": "němčina",
        "French": "francouzština",
        "Spanish": "španělština",
        "Italian": "italština",
        "Polish": "polština",
        "Russian": "ruština",
        "Ukrainian": "ukrajinština",
        "Chinese": "čínština",
        "Japanese": "japonština",
        "Korean": "korejština",
        "Portuguese": "portugalština",
        "Dutch": "nizozemština",
        "Swedish": "švédština",
        "Norwegian": "norština",
        "Danish": "dánština",
    },
}

# Common English location tokens we translate when the resume language is
# Czech. Matched whole-word, case-insensitive, applied AFTER tokenising on
# whitespace and commas so multi-word names like ``"Czech Republic"`` collapse
# to ``"Česká republika"``. Unknown tokens pass through unchanged.
_LOCATION_TRANSLATIONS_CS: dict[str, str] = {
    "prague": "Praha",
    "brno": "Brno",
    "ostrava": "Ostrava",
    "pilsen": "Plzeň",
    "plzen": "Plzeň",
    "bratislava": "Bratislava",
    "vienna": "Vídeň",
    "berlin": "Berlín",
    "warsaw": "Varšava",
    "budapest": "Budapešť",
    "remote": "Vzdáleně",
    "hybrid": "Hybridně",
    "onsite": "Na pracovišti",
}

_LOCATION_TRANSLATIONS_CS_MULTI: dict[str, str] = {
    "czech republic": "Česká republika",
    "czechia": "Česká republika",
    "slovak republic": "Slovenská republika",
    "slovakia": "Slovensko",
    "united kingdom": "Spojené království",
    "united states": "Spojené státy",
    "germany": "Německo",
    "austria": "Rakousko",
    "poland": "Polsko",
    "hungary": "Maďarsko",
}

# Reverse direction (CS -> EN). Keys are diacritics-stripped lowercase so
# matching is robust whether the AI emits "Praha" or "praha". Multi-word
# phrases live in `_LOCATION_TRANSLATIONS_EN_MULTI` so e.g. "Praha
# metropolitní oblast" doesn't get tokenised before we match it.
_LOCATION_TRANSLATIONS_EN: dict[str, str] = {
    "praha": "Prague",
    "brno": "Brno",
    "ostrava": "Ostrava",
    "plzen": "Pilsen",
    "bratislava": "Bratislava",
    "viden": "Vienna",
    "berlin": "Berlin",
    "varsava": "Warsaw",
    "budapest": "Budapest",
    "vzdalene": "Remote",
    "hybridne": "Hybrid",
    "pracoviste": "On-site",
    "metropolitni": "Metropolitan",
    "oblast": "Area",
    "okoli": "Area",
}

_LOCATION_TRANSLATIONS_EN_MULTI: dict[str, str] = {
    # Place full canonical city/area names first so they win against the
    # token-by-token fallback. Diacritics are stripped on lookup, so the
    # value side is the only place we need the proper English casing.
    "praha a okoli": "Prague Metropolitan Area",
    "praha metropolitni oblast": "Prague Metropolitan Area",
    "metropolitni oblast prahy": "Prague Metropolitan Area",
    "hlavni mesto praha": "Prague",
    "ceska republika": "Czech Republic",
    "ceskoslovensko": "Czechoslovakia",
    "slovenska republika": "Slovak Republic",
    "slovensko": "Slovakia",
    "spojene kralovstvi": "United Kingdom",
    "spojene staty": "United States",
    "nemecko": "Germany",
    "rakousko": "Austria",
    "polsko": "Poland",
    "madarsko": "Hungary",
}

_CZECH_DIACRITICS = set("ěščřžýáíéúůťďňĚŠČŘŽÝÁÍÉÚŮŤĎŇ")


def _detect_resume_language(resume: TailoredResume) -> str:
    """Return ``'cs'`` if Czech diacritics are common, ``'en'`` otherwise."""
    blobs: list[str] = [resume.professional_summary or ""]
    for section in (resume.experience, resume.projects, resume.education):
        for s in section:
            blobs.append(s.title or "")
            blobs.append(s.subtitle or "")
            for b in s.bullets:
                blobs.append(b.text or "")
    text = " ".join(blobs)
    if not text:
        return "en"
    cz = sum(1 for c in text if c in _CZECH_DIACRITICS)
    letters = sum(1 for c in text if c.isalpha())
    if letters and (cz / letters) > 0.005:
        return "cs"
    return "en"


def _group_skills(skills: Iterable[str]) -> list[tuple[str, list[str]]]:
    """Bucket a flat skill list into ``(group_label, skills)`` tuples."""
    buckets: dict[str, list[str]] = {g: [] for g, _ in _SKILL_GROUP_KEYWORDS}
    other: list[str] = []
    for skill in skills:
        s_low = (skill or "").lower()
        if not s_low:
            continue
        placed = False
        for group, keywords in _SKILL_GROUP_KEYWORDS:
            if any(kw in s_low for kw in keywords):
                if skill not in buckets[group]:
                    buckets[group].append(skill)
                placed = True
                break
        if not placed and skill not in other:
            other.append(skill)
    result: list[tuple[str, list[str]]] = [
        (group, items) for group, items in buckets.items() if items
    ]
    if other:
        result.append(("Other", other))
    return result


def _esc(text: str | None) -> str:
    """HTML-escape ``text`` after scrubbing AI-tell punctuation (em/en
    dashes, curly quotes, ellipsis, exotic whitespace).
    """
    return html.escape(strip_ai_tells(text or ""), quote=True)


def _localised_group_label(group: str, lang: str) -> str:
    """Return the display label for a skill group.

    The skill ITEMS (Playwright, C#, Pytest, ...) always stay in their
    canonical English form because ATS bots and recruiters expect the
    industry vocabulary verbatim. The GROUP HEADERS are read by humans
    though, so they get translated when ``lang`` has an entry in
    :data:`_SKILL_GROUP_LOCALISED_LABELS`. Falls back to the canonical
    English label when no override exists for ``lang``.
    """
    overrides = _SKILL_GROUP_LOCALISED_LABELS.get(lang, {})
    return overrides.get(group, group)


def _localise_spoken_language(name: str, lang: str) -> str:
    """Translate a canonical English language label (e.g. ``"Czech"``) into the
    target ``lang``. Falls back to the input verbatim when no translation
    exists - never silently drops or invents a name.
    """
    overrides = _LANGUAGE_DISPLAY_BY_LANG.get(lang, {})
    return overrides.get(name, name)


def _strip_diacritics_for_match(text: str) -> str:
    """Return ``text`` with diacritics removed, used for table lookups."""
    import unicodedata
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _localise_location(location: str, lang: str) -> str:
    """Translate common place names to ``lang`` while preserving structure.

    Bidirectional: ``lang='cs'`` maps English -> Czech, ``lang='en'`` maps
    Czech -> English. Tokenises on commas first so a multi-part location
    like ``"Praha, Česká republika"`` becomes ``"Prague, Czech Republic"``;
    falls back to a token-level lookup for chunks that aren't recognised
    as a whole. Unknown chunks pass through verbatim - we never silently
    drop or fabricate place names.
    """
    if not location or lang not in ("cs", "en"):
        return location
    parts = [p.strip() for p in location.split(",")]
    out: list[str] = []
    if lang == "cs":
        for part in parts:
            if not part:
                continue
            lowered = part.lower()
            translated = _LOCATION_TRANSLATIONS_CS_MULTI.get(lowered)
            if translated is not None:
                out.append(translated)
                continue
            tokens = part.split()
            rebuilt = [
                _LOCATION_TRANSLATIONS_CS.get(tok.lower(), tok) for tok in tokens
            ]
            out.append(" ".join(rebuilt))
        return ", ".join(out)
    # lang == "en": Czech -> English. Compare on the diacritics-stripped
    # lowercase form so the maps don't have to enumerate every accented
    # spelling ("Plzeň" vs "Plzen"). The original casing is used as the
    # fallback for unknown tokens so unusual place names look untouched.
    for part in parts:
        if not part:
            continue
        norm = _strip_diacritics_for_match(part).lower().strip()
        translated = _LOCATION_TRANSLATIONS_EN_MULTI.get(norm)
        if translated is not None:
            out.append(translated)
            continue
        tokens = part.split()
        rebuilt: list[str] = []
        for tok in tokens:
            tok_norm = _strip_diacritics_for_match(tok).lower()
            rebuilt.append(_LOCATION_TRANSLATIONS_EN.get(tok_norm, tok))
        out.append(" ".join(rebuilt))
    return ", ".join(out)


_STYLED_RESUME_CSS = """
:root{
  --teal-900:#0E7490;
  --teal-700:#0F766E;
  --teal-500:#14B8A6;
  --teal-50:#F0FDFA;
  --ink-900:#0F172A;
  --ink-700:#334155;
  --ink-500:#64748B;
  --ink-200:#E2E8F0;
  --bg:#FFFFFF;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{font-family:'Inter','Segoe UI','Helvetica Neue',Arial,sans-serif;color:var(--ink-900);background:#F8FAFC;line-height:1.45;font-size:10.5pt}
.page{max-width:210mm;min-height:297mm;margin:0 auto;background:var(--bg);box-shadow:0 8px 30px rgba(15,23,42,0.08);display:grid;grid-template-columns:73mm 1fr}
.sidebar{background:linear-gradient(180deg,var(--teal-900) 0%,var(--teal-700) 100%);color:#fff;padding:14mm 9mm 12mm 9mm}
.sidebar h1{font-size:20pt;line-height:1.1;font-weight:800;letter-spacing:-0.02em;margin-bottom:3mm}
.sidebar .role{font-size:10.5pt;color:var(--teal-50);font-weight:500;margin-bottom:8mm;letter-spacing:0.02em}
.sb-section{margin-top:7mm}
.sb-section h3{font-size:9pt;text-transform:uppercase;letter-spacing:0.18em;font-weight:700;color:#7DD3FC;border-bottom:1px solid rgba(125,211,252,0.35);padding-bottom:1.5mm;margin-bottom:3mm}
.sb-section p, .sb-section li{font-size:9.5pt;color:#E0F7FA;margin-bottom:1.5mm;word-wrap:break-word}
.sb-section a{color:#fff;text-decoration:none;border-bottom:1px dotted rgba(255,255,255,0.4)}
.sb-section ul{list-style:none}
.sb-section .contact-line{display:flex;align-items:center;gap:2.2mm;font-size:9pt;margin-bottom:1.8mm}
.sb-section .contact-line .ic{flex:0 0 5mm;color:#7DD3FC;font-weight:700;font-size:10.5pt;line-height:1;font-family:"Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji","Twemoji Mozilla",system-ui,sans-serif}
.skill-group{margin-bottom:3.5mm}
.skill-group .group-label{font-size:8.5pt;color:#7DD3FC;font-weight:600;margin-bottom:1mm;text-transform:uppercase;letter-spacing:0.06em}
.skill-tags{display:flex;flex-wrap:wrap;gap:1.5mm}
.skill-tag{background:rgba(255,255,255,0.12);border:1px solid rgba(255,255,255,0.2);padding:0.8mm 2mm;border-radius:2mm;font-size:8.5pt;color:#fff}
.lang-row{display:flex;justify-content:space-between;align-items:center;font-size:9.5pt;margin-bottom:1.5mm}
.lang-row .lvl{font-size:8.5pt;color:#7DD3FC;font-weight:600}
.main{padding:14mm 12mm 12mm 12mm}
.main h2{font-size:11pt;text-transform:uppercase;letter-spacing:0.16em;color:var(--teal-900);font-weight:800;border-bottom:2px solid var(--teal-500);padding-bottom:1.2mm;margin:0 0 4mm 0}
.main h2:not(:first-child){margin-top:7mm}
.tailored{font-size:9pt;color:var(--ink-500);font-style:italic;margin-bottom:5mm}
.tailored strong{color:var(--teal-700);font-style:normal;font-weight:600}
.summary{font-size:10pt;color:var(--ink-700);line-height:1.55}
.job{margin-bottom:5mm}
.job-header{display:flex;justify-content:space-between;align-items:baseline;gap:3mm;margin-bottom:0.5mm}
.job-title{font-size:10.5pt;font-weight:700;color:var(--ink-900)}
.job-period{font-size:9pt;color:var(--ink-500);font-variant-numeric:tabular-nums;white-space:nowrap;font-weight:500}
.job-company{font-size:9.5pt;color:var(--teal-700);font-weight:600;margin-bottom:1.5mm}
.job ul{list-style:none;padding-left:0}
.job ul li{position:relative;padding-left:4mm;margin-bottom:1.4mm;font-size:9.5pt;color:var(--ink-700);line-height:1.45}
.job ul li::before{content:'\\25B8';position:absolute;left:0;top:0;color:var(--teal-500);font-weight:700;font-size:9pt}
.project-card{border-left:3px solid var(--teal-500);padding-left:3mm;margin-bottom:3mm}
.project-card .pname{font-size:10pt;font-weight:700;color:var(--ink-900);margin-bottom:0.5mm}
.project-card .pdesc{font-size:9.5pt;color:var(--ink-700);line-height:1.45}
.edu-row{margin-bottom:3mm}
.edu-row .top{display:flex;justify-content:space-between;font-size:10pt;font-weight:600;color:var(--ink-900)}
.edu-row .sub{font-size:9.5pt;color:var(--ink-500);font-style:italic}
.cert-list{display:grid;grid-template-columns:1fr 1fr;gap:1.5mm 4mm}
.cert-item{font-size:9.5pt;color:var(--ink-700)}
@page{size:A4;margin:0}
@media print{body{background:#fff}.page{box-shadow:none;margin:0}}
"""


def _styled_sidebar(
    resume: TailoredResume,
    candidate: CandidateProfile | None,
    labels: dict[str, str],
    lang: str,
) -> str:
    candidate = candidate or CandidateProfile()

    # Icon glyphs are emoji-class Unicode characters with the explicit emoji
    # variation selector (U+FE0F) where needed so browsers / Qt WebEngine
    # use the colour-emoji font instead of the monochrome text variant. We
    # avoid plain letter abbreviations (`@`, `e`, `t`) here because they
    # rendered as visually weak placeholder text on the dark sidebar and
    # the user explicitly asked for proper icon glyphs in the contact
    # block. Brand-specific marks (LinkedIn / GitHub) keep their two-
    # letter abbreviations because there is no widely supported native
    # icon glyph for those that scales reliably across browsers and PDF
    # printers.
    _ICON_LOCATION = "&#x1F4CD;"           # round pushpin
    _ICON_EMAIL = "&#x2709;&#xFE0F;"        # envelope (forced emoji style)
    _ICON_PHONE = "&#x1F4DE;"               # telephone receiver
    _ICON_PORTFOLIO = "&#x1F517;"           # link symbol

    contact_lines: list[str] = []
    if candidate.location:
        location_text = _localise_location(candidate.location, lang)
        contact_lines.append(
            f'<div class="contact-line"><span class="ic">{_ICON_LOCATION}</span>'
            f'<span>{_esc(location_text)}</span></div>'
        )
    if candidate.contact_email:
        contact_lines.append(
            f'<div class="contact-line"><span class="ic">{_ICON_EMAIL}</span>'
            f'<span>{_esc(candidate.contact_email)}</span></div>'
        )
    if candidate.phone:
        contact_lines.append(
            f'<div class="contact-line"><span class="ic">{_ICON_PHONE}</span>'
            f'<span>{_esc(candidate.phone)}</span></div>'
        )
    if not contact_lines and resume.contact_line:
        # Split fallback "X | Y | Z" contact_line into separate rows.
        for piece in [p.strip() for p in resume.contact_line.split("|") if p.strip()]:
            contact_lines.append(
                f'<div class="contact-line"><span class="ic">&middot;</span>'
                f'<span>{_esc(piece)}</span></div>'
            )

    online_lines: list[str] = []
    li = resume.linkedin or candidate.linkedin_url
    gh = resume.github or candidate.github_url
    pf = resume.portfolio or candidate.portfolio_url
    if li:
        online_lines.append(
            f'<div class="contact-line"><span class="ic">in</span>'
            f'<a href="{_esc(li)}">{_esc(li)}</a></div>'
        )
    if gh:
        online_lines.append(
            f'<div class="contact-line"><span class="ic">gh</span>'
            f'<a href="{_esc(gh)}">{_esc(gh)}</a></div>'
        )
    if pf:
        online_lines.append(
            f'<div class="contact-line"><span class="ic">{_ICON_PORTFOLIO}</span>'
            f'<a href="{_esc(pf)}">{_esc(pf)}</a></div>'
        )

    skill_groups_html: list[str] = []
    for group_label, items in _group_skills(resume.technical_skills):
        tags = "".join(
            f'<span class="skill-tag">{_esc(s)}</span>' for s in items
        )
        skill_groups_html.append(
            f'<div class="skill-group">'
            f'<div class="group-label">{_esc(_localised_group_label(group_label, lang))}</div>'
            f'<div class="skill-tags">{tags}</div>'
            f"</div>"
        )

    languages_html = ""
    if candidate.spoken_languages:
        rows: list[str] = []
        for entry in candidate.spoken_languages:
            # Accept either plain "Czech" or "Czech (C2)" / "Czech - native".
            name, level = entry, ""
            for sep in ("(", " - ", " \u2013 ", ":"):
                if sep in entry:
                    name, _, raw_level = entry.partition(sep)
                    level = raw_level.rstrip(") ").strip()
                    name = name.strip()
                    break
            display_name = _localise_spoken_language(name, lang)
            rows.append(
                f'<div class="lang-row"><span>{_esc(display_name)}</span>'
                f'<span class="lvl">{_esc(level)}</span></div>'
            )
        languages_html = (
            f'<div class="sb-section"><h3>{_esc(labels["languages"])}</h3>'
            + "".join(rows)
            + "</div>"
        )

    sections: list[str] = [f'<h1>{_esc(resume.name or "Candidate")}</h1>']
    if contact_lines:
        sections.append(
            f'<div class="sb-section"><h3>{_esc(labels["contact"])}</h3>'
            + "".join(contact_lines)
            + "</div>"
        )
    if online_lines:
        sections.append(
            f'<div class="sb-section"><h3>{_esc(labels["online"])}</h3>'
            + "".join(online_lines)
            + "</div>"
        )
    if skill_groups_html:
        sections.append(
            f'<div class="sb-section"><h3>{_esc(labels["tech_stack"])}</h3>'
            + "".join(skill_groups_html)
            + "</div>"
        )
    if languages_html:
        sections.append(languages_html)
    return f'<aside class="sidebar">{"".join(sections)}</aside>'


def _styled_main(resume: TailoredResume, labels: dict[str, str]) -> str:
    parts: list[str] = []

    if resume.professional_summary:
        parts.append(
            f'<h2>{_esc(labels["profile"])}</h2>'
            f'<p class="summary">{_esc(resume.professional_summary)}</p>'
        )

    if resume.experience:
        parts.append(f'<h2>{_esc(labels["experience"])}</h2>')
        for s in resume.experience:
            bullets = "".join(f"<li>{_esc(b.text)}</li>" for b in s.bullets)
            period_html = (
                f'<div class="job-period">{_esc(s.period)}</div>'
                if s.period else ""
            )
            parts.append(
                '<div class="job">'
                '<div class="job-header">'
                f'<div class="job-title">{_esc(s.title)}</div>'
                + period_html
                + "</div>"
                + (f'<div class="job-company">{_esc(s.subtitle)}</div>' if s.subtitle else "")
                + (f"<ul>{bullets}</ul>" if bullets else "")
                + "</div>"
            )

    if resume.projects:
        parts.append(f'<h2>{_esc(labels["projects"])}</h2>')
        for s in resume.projects:
            description = " ".join(b.text for b in s.bullets) or s.subtitle
            parts.append(
                '<div class="project-card">'
                f'<div class="pname">{_esc(s.title)}</div>'
                f'<div class="pdesc">{_esc(description)}</div>'
                "</div>"
            )

    if resume.education:
        parts.append(f'<h2>{_esc(labels["education"])}</h2>')
        for s in resume.education:
            period_html = (
                f'<span class="job-period">{_esc(s.period)}</span>'
                if s.period else ""
            )
            parts.append(
                '<div class="edu-row">'
                f'<div class="top"><span>{_esc(s.title)}</span>{period_html}</div>'
                + (f'<div class="sub">{_esc(s.subtitle)}</div>' if s.subtitle else "")
                + "</div>"
            )

    if resume.certifications:
        parts.append(f'<h2>{_esc(labels["certifications"])}</h2>')
        items = "".join(
            f'<div class="cert-item">{_esc(cert)}</div>'
            for cert in resume.certifications
        )
        parts.append(f'<div class="cert-list">{items}</div>')

    return f'<main class="main">{"".join(parts)}</main>'


def tailored_resume_to_styled_html(
    resume: TailoredResume,
    candidate: CandidateProfile | None = None,
    output_language: str = "",
) -> str:
    """Render a printable two-column A4 HTML resume.

    The layout is inspired by a modern teal-and-ink CV: a sidebar with
    contact details, online links, grouped tech-stack pill chips and
    spoken languages, plus a main column with profile, experience,
    projects, education and certifications. CSS is inlined so the output
    file is fully self-contained.

    ``output_language`` overrides the diacritic-sniff fallback so the
    section headers stay consistent with what the user picked in the
    output-language dialog. Pass ``""`` to keep the legacy auto-detection
    (used by tests that don't have a ``GeneratedApplicationPackage``).
    """
    lang = (output_language or "").strip().lower()
    if lang not in _RESUME_LABELS:
        # No explicit hint - fall back to the original diacritic heuristic
        # so callers that don't yet pipe the language through still work.
        lang = _detect_resume_language(resume)
    labels = _RESUME_LABELS[lang]
    title = resume.name or "Resume"
    sidebar = _styled_sidebar(resume, candidate, labels, lang)
    main = _styled_main(resume, labels)
    return (
        '<!doctype html>\n'
        f'<html lang="{lang}"><head><meta charset="utf-8"/>'
        f"<title>{_esc(title)}</title>"
        f"<style>{_STYLED_RESUME_CSS}</style></head>"
        f'<body><div class="page">{sidebar}{main}</div></body></html>'
    )


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
    docs_lang = package.output_language or "en"

    sections_md: list[str] = [
        f"# Application summary - {title}",
        f"<p><span class='badge'>Match score: {score} / 100</span></p>",
        match_report_to_markdown(package.match_report, role_label=role_label),
        "---",
        resume_to_markdown(package.tailored_resume, output_language=docs_lang),
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

    docs_lang = package.output_language or "en"
    paths.resume_md.write_text(
        resume_to_markdown(package.tailored_resume, output_language=docs_lang),
        encoding="utf-8",
    )
    resume_to_docx(
        package.tailored_resume, paths.resume_docx, output_language=docs_lang
    )
    paths.resume_html.write_text(
        tailored_resume_to_styled_html(
            package.tailored_resume,
            package.candidate_profile,
            output_language=docs_lang,
        ),
        encoding="utf-8",
    )

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
    "tailored_resume_to_styled_html",
    "application_summary_to_html",
    "export_package",
]
