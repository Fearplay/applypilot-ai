"""ApplyPilot AI - desktop application entry point.

Run with:
    python app.py

The application is intentionally usable without any API key. When
``AI_PROVIDER`` is ``fake`` (the default) or no API key is configured, the
``FakeAIProvider`` is used which produces deterministic, offline demo data.
See ``.env.example`` for all configuration options.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Native trust-store injection (must run BEFORE any module imports `ssl` /
# `requests`). Some Windows / corporate environments don't ship the OpenAI
# CA bundle inside the static `certifi` package, which causes the user-
# visible failure ``SSL: CERTIFICATE_VERIFY_FAILED`` on the first call to
# ``api.openai.com/v1/models`` (Settings -> Test connection) and on every
# subsequent ``chat/completions`` call. ``truststore.inject_into_ssl()``
# patches the stdlib ``ssl`` module to use the OS-native certificate store
# (Windows CryptoAPI / macOS Security / Linux OpenSSL) so HTTPS works
# wherever the user's browser already works.
#
# We swallow every exception on purpose: truststore requires Python 3.10+
# AND a supported OS, and a missing dependency or unsupported platform must
# never prevent the GUI from starting. The fallback (default certifi behavior)
# matches the pre-existing experience.
#
# Per the truststore docs this call MUST happen as early as possible and
# ONLY in applications/scripts (never in libraries) - hence this block sits
# at the very top of app.py, right after the mandatory ``from __future__``
# line and before any stdlib import that might pull ``ssl`` transitively.
try:  # pragma: no cover - environment-dependent
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

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
    from src.gui.theme import apply_theme

    app = QApplication(sys.argv)
    app.setApplicationName("ApplyPilot AI")
    app.setOrganizationName("ApplyPilot")
    apply_theme(app)

    provider = build_provider(settings)
    window = MainWindow(settings=settings, provider=provider)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
