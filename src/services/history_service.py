"""Public API for reading and updating the application history."""
from __future__ import annotations

import logging
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


__all__ = ["history_path", "append_history", "load_history"]
