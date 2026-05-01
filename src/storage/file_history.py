"""File-based storage for the application history.

We keep things deliberately simple: history lives in
``<output_dir>/history.json`` and is appended to whenever a new application
package is exported.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class HistoryEntry:
    date: str
    company: str
    role: str
    job_url: str | None
    match_score: int
    output_folder: str
    role_type: str = ""

    @classmethod
    def now(cls, *, company: str, role: str, job_url: str | None,
            match_score: int, output_folder: str, role_type: str = "") -> "HistoryEntry":
        return cls(
            date=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            company=company,
            role=role,
            job_url=job_url,
            match_score=int(match_score),
            output_folder=output_folder,
            role_type=role_type,
        )


@dataclass
class HistoryFile:
    path: Path
    entries: list[HistoryEntry] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "HistoryFile":
        p = Path(path)
        if not p.exists():
            return cls(path=p, entries=[])
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read history file %s: %s", p, exc)
            return cls(path=p, entries=[])
        items = raw if isinstance(raw, list) else raw.get("items", [])
        entries = [HistoryEntry(**item) for item in items if isinstance(item, dict)]
        return cls(path=p, entries=entries)

    def append(self, entry: HistoryEntry) -> None:
        self.entries.append(entry)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(e) for e in self.entries]
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def iter_recent(entries: Iterable[HistoryEntry], limit: int = 50) -> list[HistoryEntry]:
    items = sorted(entries, key=lambda e: e.date, reverse=True)
    return items[:limit]


__all__ = ["HistoryEntry", "HistoryFile", "iter_recent"]
