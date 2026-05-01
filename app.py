"""ApplyPilot AI - desktop application entry point.

Run with:
    python app.py

The application is intentionally usable without any API key. When
``AI_PROVIDER`` is ``fake`` (the default) or no API key is configured, the
``FakeAIProvider`` is used which produces deterministic, offline demo data.
See ``.env.example`` for all configuration options.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _ensure_repo_on_path() -> None:
    """Make ``src`` importable when running ``python app.py`` from the repo."""
    repo_root = Path(__file__).resolve().parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def main() -> int:
    _ensure_repo_on_path()

    from src.config import load_settings
    from src.utils.logging_config import configure_logging

    settings = load_settings()
    configure_logging(settings.log_level)

    # Importing PySide6 lazily so ``--help``/import errors above stay readable.
    from PySide6.QtWidgets import QApplication

    from src.ai.provider_factory import build_provider
    from src.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("ApplyPilot AI")
    app.setOrganizationName("ApplyPilot")

    provider = build_provider(settings)
    window = MainWindow(settings=settings, provider=provider)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
