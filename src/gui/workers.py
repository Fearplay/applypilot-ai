"""Lightweight QRunnable wrapper used to run blocking work off the GUI thread.

Usage::

    from PySide6.QtCore import QThreadPool
    from src.gui.workers import run_in_background

    pool = QThreadPool.globalInstance()
    run_in_background(
        pool,
        lambda: heavy_function(arg),
        on_finished=lambda result: ...,
        on_failed=lambda message: ...,
    )

The callable runs in a worker thread; ``on_finished`` / ``on_failed`` are
called back on the GUI thread via Qt signals.
"""
from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class _Worker(QRunnable):
    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:  # noqa: D401 - QRunnable override
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:
            logger.exception("Background worker failed")
            tb = traceback.format_exc(limit=2)
            self.signals.failed.emit(f"{exc.__class__.__name__}: {exc}\n{tb}")
        else:
            self.signals.finished.emit(result)


def run_in_background(
    pool,
    fn: Callable[..., Any],
    *args: Any,
    on_finished: Callable[[Any], None] | None = None,
    on_failed: Callable[[str], None] | None = None,
    **kwargs: Any,
) -> _Worker:
    """Schedule ``fn(*args, **kwargs)`` on ``pool``."""
    worker = _Worker(fn, *args, **kwargs)
    if on_finished is not None:
        worker.signals.finished.connect(on_finished)
    if on_failed is not None:
        worker.signals.failed.connect(on_failed)
    pool.start(worker)
    return worker


__all__ = ["run_in_background", "WorkerSignals"]
