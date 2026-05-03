"""Helper for relaunching the desktop app in a fresh process.

Used when the user changes the UI language: a real process restart is the
cleanest way to make every label, menu and dialog reflect the new locale
without weaving live-retranslate hooks into every widget. We:

1. Re-launch the same Python interpreter with the same ``sys.argv``.
2. Quit the running ``QApplication`` so the old window closes cleanly.
3. ``sys.exit(0)`` on the off-chance Qt's quit fails to stop the loop.

The new process inherits ``stdin`` / ``stdout`` / ``stderr`` so the user
keeps seeing log output where they expect it.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Sequence

logger = logging.getLogger(__name__)


def _spawn_replacement(args: Sequence[str]) -> None:
    """Start a detached child process running ``args``.

    ``close_fds=False`` is intentional on Windows to avoid the warning the
    runtime emits when redirecting stdio with ``close_fds=True``. On POSIX
    it has no negative effect for our use case.
    """
    subprocess.Popen(  # noqa: S603 - args list is fully controlled by us
        list(args),
        close_fds=False,
    )


def restart_app() -> None:
    """Restart the running ApplyPilot AI process in place.

    Best-effort: if the new process cannot be launched (sandbox, missing
    interpreter, permission errors) we log and return so the caller can
    surface a friendlier message instead of crashing.
    """
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover - PySide6 always present in prod
        QApplication = None  # type: ignore[assignment]

    args = [sys.executable, *sys.argv]
    try:
        _spawn_replacement(args)
    except OSError:
        logger.exception("Failed to spawn replacement process for restart")
        return

    if QApplication is not None:
        instance = QApplication.instance()
        if instance is not None:
            instance.quit()

    sys.exit(0)


__all__ = ["restart_app"]
