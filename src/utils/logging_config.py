"""Centralised logging configuration.

The function is idempotent so it is safe to call multiple times (for example
from tests).
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: str = "INFO", log_dir: str | Path | None = None) -> None:
    """Configure the root logger with a console handler and rotating file."""
    log_level = getattr(logging, str(level).upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(log_level)

    if any(getattr(h, "_applypilot", False) for h in root.handlers):
        for h in root.handlers:
            if getattr(h, "_applypilot", False):
                h.setLevel(log_level)
        return

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT)

    console = logging.StreamHandler()
    console.setLevel(log_level)
    console.setFormatter(formatter)
    console._applypilot = True  # type: ignore[attr-defined]
    root.addHandler(console)

    if log_dir is None:
        log_dir = Path(__file__).resolve().parents[2] / "logs"
    log_dir = Path(log_dir)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "applypilot.log",
            maxBytes=512 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        file_handler._applypilot = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)
    except OSError:
        # Disk-write failures should never break the GUI, console handler stays.
        pass


def get_ai_request_logger(log_dir: str | Path | None = None) -> logging.Logger:
    """Logger dedicated to real AI request audit trails."""
    logger = logging.getLogger("applypilot.ai.requests")
    if any(getattr(h, "_applypilot_ai", False) for h in logger.handlers):
        return logger

    if log_dir is None:
        log_dir = Path(__file__).resolve().parents[2] / "logs"
    log_dir = Path(log_dir)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_dir / "ai_requests.log",
            maxBytes=512 * 1024,
            backupCount=2,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT)
        )
        handler._applypilot_ai = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    except OSError:
        pass
    logger.propagate = True
    return logger


__all__ = ["configure_logging", "get_ai_request_logger"]
