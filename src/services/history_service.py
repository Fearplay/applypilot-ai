"""Public API for reading and updating the application history."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..models.package import GeneratedApplicationPackage
from ..storage.file_history import HistoryEntry, HistoryFile, iter_recent

logger = logging.getLogger(__name__)


def history_path(base_dir: str | Path) -> Path:
    return Path(base_dir) / "history.json"


def append_history(base_dir: str | Path, package: GeneratedApplicationPackage) -> HistoryEntry:
    history = HistoryFile.load(history_path(base_dir))
    entry = HistoryEntry.now(
        company=package.job_posting.company or "",
        role=package.job_posting.title or "",
        job_url=package.job_posting.source_url,
        match_score=package.match_report.overall_score,
        output_folder=package.output_dir,
        role_type=package.job_posting.role_type,
    )
    history.append(entry)
    history.save()
    return entry


def load_history(base_dir: str | Path, *, limit: int = 50) -> list[HistoryEntry]:
    history = HistoryFile.load(history_path(base_dir))
    return iter_recent(history.entries, limit=limit)


@dataclass
class StoredAnalysis:
    """Plain-text payload of a previously exported analysis folder.

    The fields hold the file contents verbatim so the GUI can drop them
    straight into its existing markdown editors. Missing files become
    empty strings - we never fail because a folder is partial. The
    ``styled_resume_html`` is the standalone styled CV (preferred over
    the markdown-rendered ``application_summary_html`` for the Modern
    Resume preview tab).
    """

    folder: Path
    resume_md: str = ""
    cover_letter_md: str = ""
    match_report_md: str = ""
    interview_md: str = ""
    skill_gap_md: str = ""
    evidence_json: str = ""
    styled_resume_html: str = ""
    summary_html: str = ""
    evidence: dict = field(default_factory=dict)


def _read_text_or_empty(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return ""


def _first_existing(folder: Path, *candidates: str) -> Path:
    """Return the first existing path among ``candidates`` under ``folder``.

    Falls back to ``folder / candidates[0]`` so the caller always has a
    well-defined :class:`Path` to log / report against, even when none
    of the variants exist on disk.
    """
    for name in candidates:
        path = folder / name
        if path.exists():
            return path
    return folder / candidates[0]


def _resolve_resume_paths(folder: Path) -> tuple[Path, Path]:
    """Locate the resume markdown + styled HTML for an analysis folder.

    Tries the new ``{Slug}_CV.{md,html}`` Title_Case filenames first (so
    re-opened folders saved with the latest convention always win), then
    falls back to the previous ``{slug}_cv.{md,html}`` lowercase form,
    and finally to the legacy ``tailored_resume.{md,html}`` so analyses
    exported by older builds keep loading without manual rename.
    """
    md_candidates = ["tailored_resume.md"]
    html_candidates = ["tailored_resume.html"]
    # Glob is case-insensitive on Windows but case-sensitive on Linux/macOS;
    # explicitly probe both casings so saved folders open from either OS.
    for pattern in ("*_CV.md", "*_cv.md"):
        for child in folder.glob(pattern):
            md_candidates.insert(0, child.name)
    for pattern in ("*_CV.html", "*_cv.html"):
        for child in folder.glob(pattern):
            html_candidates.insert(0, child.name)
    return (
        _first_existing(folder, *md_candidates),
        _first_existing(folder, *html_candidates),
    )


def _resolve_cover_md(folder: Path) -> Path:
    candidates = ["cover_letter.md"]
    for pattern in ("*_Cover_Letter.md", "*_cover_letter.md"):
        for child in folder.glob(pattern):
            candidates.insert(0, child.name)
    return _first_existing(folder, *candidates)


def load_package_files(folder: str | Path) -> StoredAnalysis:
    """Read back the markdown / HTML / JSON artefacts of a past analysis.

    Tolerates partial folders (returns empty strings for missing files)
    AND tolerates every filename convention this app has shipped - the
    current ``{Slug}_CV.*`` / ``{Slug}_Cover_Letter.*`` Title_Case names,
    the previous lowercase ``{slug}_cv.*`` / ``{slug}_cover_letter.*``
    form, and the legacy ``tailored_resume.*`` / ``cover_letter.*``
    files. Old saved analyses keep opening without any user action.
    """
    p = Path(folder)
    evidence_raw = _read_text_or_empty(
        _first_existing(p, "Evidence_Report.json", "evidence_report.json")
    )
    evidence_obj: dict = {}
    if evidence_raw:
        try:
            parsed = json.loads(evidence_raw)
            if isinstance(parsed, dict):
                evidence_obj = parsed
        except json.JSONDecodeError as exc:
            logger.warning("evidence_report.json in %s is malformed: %s", p, exc)

    resume_md_path, resume_html_path = _resolve_resume_paths(p)
    cover_md_path = _resolve_cover_md(p)

    return StoredAnalysis(
        folder=p,
        resume_md=_read_text_or_empty(resume_md_path),
        cover_letter_md=_read_text_or_empty(cover_md_path),
        match_report_md=_read_text_or_empty(
            _first_existing(p, "Match_Report.md", "match_report.md")
        ),
        interview_md=_read_text_or_empty(
            _first_existing(p, "Interview_Questions.md", "interview_questions.md")
        ),
        skill_gap_md=_read_text_or_empty(
            _first_existing(p, "Skill_Gap_Plan.md", "skill_gap_plan.md")
        ),
        evidence_json=evidence_raw,
        styled_resume_html=_read_text_or_empty(resume_html_path),
        summary_html=_read_text_or_empty(
            _first_existing(p, "Application_Summary.html", "application_summary.html")
        ),
        evidence=evidence_obj,
    )


__all__ = [
    "history_path",
    "append_history",
    "load_history",
    "load_package_files",
    "StoredAnalysis",
]
