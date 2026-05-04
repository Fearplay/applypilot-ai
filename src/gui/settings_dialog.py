"""In-app settings dialog: provider preset, API key, GitHub token.

This module replaces the inline ``SettingsDialog`` that used to live in
:mod:`src.gui.main_window`. The new dialog is the single place users
configure their AI provider so the workflow stops requiring them to edit
``.env`` by hand.

Design notes:

* **Secrets never touch ``.env``.** The user's AI API key and optional
  GitHub token are written to the OS keyring (Windows Credential Manager
  / macOS Keychain / Linux Secret Service) via :mod:`src.utils.secrets`.
  When the keyring is unavailable the secrets module falls back to
  ``~/.applypilot/secrets.json`` with ``0o600`` perms - still strictly
  better than the project-root ``.env`` getting checked into git.
* **Non-secret AI defaults persist via ``preferences.set_preference``.**
  ``ai_provider_raw`` / ``ai_base_url`` / ``ai_model`` survive restarts
  through ``~/.applypilot/state.json`` so the next launch picks up the
  user's choice without anyone editing env vars.
* **Provider presets** auto-fill Base URL and a recommended Model when
  the user picks a vendor from the combo. ``Custom`` keeps whatever the
  user typed manually so power users keep their freedom.
* **Test connection** does a single low-cost ``GET /models`` request so
  the user can confirm the key works *before* spending tokens on a
  real run.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

import requests
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings, load_settings
from ..i18n import t
from ..utils.preferences import set_preference
from ..utils.secrets import (
    delete_secret,
    is_keyring_available,
    set_secret,
)
from .theme import Tokens

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider presets
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _ProviderPreset:
    """One row in the Preset combo.

    ``provider_kind`` is what we write into ``AI_PROVIDER`` (and into
    preferences) - everything except ``fake`` resolves to
    ``openai_compatible`` so the existing :class:`OpenAICompatibleProvider`
    handles the call. The user-visible label comes from i18n via
    ``label_key`` to keep the dialog translatable.
    """

    key: str
    label_key: str
    base_url: str
    models: tuple[str, ...]
    provider_kind: str = "openai_compatible"


_PRESETS: tuple[_ProviderPreset, ...] = (
    _ProviderPreset(
        key="openai",
        label_key="settings.preset.openai",
        base_url="https://api.openai.com/v1",
        models=(
            "gpt-4o-mini",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "gpt-4o",
            "gpt-4.1",
            "o4-mini",
        ),
    ),
    _ProviderPreset(
        key="groq",
        label_key="settings.preset.groq",
        base_url="https://api.groq.com/openai/v1",
        models=(
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ),
    ),
    _ProviderPreset(
        key="mistral",
        label_key="settings.preset.mistral",
        base_url="https://api.mistral.ai/v1",
        models=(
            "mistral-small-latest",
            "mistral-medium-latest",
            "mistral-large-latest",
            "codestral-latest",
        ),
    ),
    _ProviderPreset(
        key="openrouter",
        label_key="settings.preset.openrouter",
        base_url="https://openrouter.ai/api/v1",
        models=(
            "openai/gpt-4o-mini",
            "anthropic/claude-3.5-sonnet",
            "meta-llama/llama-3.3-70b-instruct",
            "mistralai/mistral-large-latest",
        ),
    ),
    _ProviderPreset(
        key="deepseek",
        label_key="settings.preset.deepseek",
        base_url="https://api.deepseek.com/v1",
        models=("deepseek-chat", "deepseek-reasoner"),
    ),
    _ProviderPreset(
        key="anthropic",
        label_key="settings.preset.anthropic",
        # Anthropic ships an OpenAI-compatible /v1 endpoint as of 2025-Q4
        base_url="https://api.anthropic.com/v1",
        models=(
            "claude-3-5-haiku-latest",
            "claude-3-5-sonnet-latest",
            "claude-3-7-sonnet-latest",
            "claude-sonnet-4-5",
            "claude-opus-4-1",
        ),
    ),
    _ProviderPreset(
        key="gemini",
        label_key="settings.preset.gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        models=(
            "gemini-2.0-flash",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ),
    ),
    _ProviderPreset(
        key="ollama",
        label_key="settings.preset.ollama",
        base_url="http://localhost:11434/v1",
        models=("llama3.2", "qwen2.5-coder", "deepseek-r1:8b"),
    ),
    _ProviderPreset(
        key="lmstudio",
        label_key="settings.preset.lmstudio",
        base_url="http://localhost:1234/v1",
        models=("local-model",),
    ),
    _ProviderPreset(
        key="custom",
        label_key="settings.preset.custom",
        base_url="",
        models=(),
    ),
    _ProviderPreset(
        key="fake",
        label_key="settings.preset.fake",
        base_url="",
        models=("fake-deterministic",),
        provider_kind="fake",
    ),
)


def _detect_preset_key(settings: Settings) -> str:
    """Best guess for which preset matches the saved settings.

    Falls back to ``custom`` so the user never sees the form pre-filled
    with a vendor they didn't choose.
    """
    if settings.ai_provider == "fake":
        return "fake"
    base = (settings.ai_base_url or "").rstrip("/").lower()
    if not base:
        return "custom"
    for preset in _PRESETS:
        preset_base = (preset.base_url or "").rstrip("/").lower()
        if preset_base and preset_base == base:
            return preset.key
    return "custom"


# ---------------------------------------------------------------------------
# Worker thread for "Test connection"
# ---------------------------------------------------------------------------
class _ConnectionTester(QThread):
    """Hits ``GET {base_url}/models`` once on a background thread.

    Anything that resembles a 200 with a non-empty list / dict is treated
    as success - different providers ship slightly different shapes
    (OpenAI returns ``{"data": [...]}``, Groq returns the same, Ollama
    returns ``{"object": "list", "data": [...]}``) but all of them put
    something countable in ``data``.
    """

    finished_ok = Signal(int)
    finished_fail = Signal(str)

    def __init__(self, base_url: str, api_key: str) -> None:
        super().__init__()
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    def run(self) -> None:  # pragma: no cover - exercised manually
        url = f"{self._base_url}/models"
        try:
            headers = {"Accept": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            self.finished_fail.emit(str(exc))
            return
        except ValueError as exc:
            self.finished_fail.emit(f"Invalid JSON: {exc}")
            return

        items = payload.get("data") if isinstance(payload, dict) else None
        count = len(items) if isinstance(items, list) else 0
        self.finished_ok.emit(count)


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------
@dataclass
class _DialogState:
    """Pure-data snapshot the dialog mutates while the user clicks around."""

    api_key_dirty: bool = False
    github_token_dirty: bool = False
    test_thread: QThread | None = field(default=None)


class SettingsDialog(QDialog):
    """Modern settings dialog with vendor presets and keyring storage."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("settings.title"))
        self.setMinimumWidth(620)
        self.setModal(True)

        self._settings = settings
        self._state = _DialogState()
        self._suppress_preset_signal = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        title = QLabel(t("settings.section"))
        title.setStyleSheet(
            f"color: {Tokens.text}; font-size: 18px; font-weight: 600;"
        )
        layout.addWidget(title)

        # Storage tip - changes copy depending on whether the OS keyring
        # is actually available so the user gets honest expectations.
        tip_key = (
            "settings.tip_html"
            if is_keyring_available()
            else "settings.tip_html.json_fallback"
        )
        info = QLabel(t(tip_key))
        info.setTextFormat(Qt.RichText)
        info.setOpenExternalLinks(True)
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color: {Tokens.text}; font-size: 12px;"
            f" background-color: {Tokens.surface_alt};"
            f" border: 1px solid {Tokens.border};"
            f" border-radius: 8px; padding: 10px 12px;"
        )
        layout.addWidget(info)

        layout.addLayout(self._build_provider_form())
        layout.addLayout(self._build_api_key_row())
        layout.addLayout(self._build_model_row())
        layout.addWidget(self._build_separator())
        layout.addLayout(self._build_github_section())
        layout.addWidget(self._build_separator())
        layout.addWidget(self._build_confirm_refine_check())
        layout.addWidget(self._build_examples_label())
        layout.addStretch(1)

        # The status label is shared between Test connection / Delete /
        # Save messages so the user always has a single visible feedback
        # line at the bottom of the dialog.
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(
            f"color: {Tokens.text_muted}; font-size: 11px; padding-top: 4px;"
        )
        layout.addWidget(self._status)

        layout.addLayout(self._build_button_row())

        # Initial sync so combos / placeholders match the loaded settings.
        self._sync_preset_to_inputs(_detect_preset_key(settings), refill=True)

    # ----------------------------------------------------------- builders
    def _build_provider_form(self) -> QFormLayout:
        form = QFormLayout()
        form.setSpacing(10)

        self._preset_combo = QComboBox()
        for preset in _PRESETS:
            self._preset_combo.addItem(t(preset.label_key), preset.key)
        self._preset_combo.setToolTip(t("settings.preset.tip"))
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        form.addRow(t("settings.preset"), self._preset_combo)

        self._base_url = QLineEdit(self._settings.ai_base_url)
        self._base_url.setPlaceholderText("https://api.example.com/v1")
        # Switching to Custom whenever the user hand-edits the URL keeps
        # the preset combo honest - we never lie about which vendor the
        # user is actually targeting.
        self._base_url.textEdited.connect(self._on_manual_base_url_edit)
        form.addRow(t("settings.base_url"), self._base_url)
        return form

    def _build_api_key_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        label = QLabel(t("settings.api_key"))
        label.setMinimumWidth(120)
        row.addWidget(label)

        self._api_key = QLineEdit(self._settings.ai_api_key)
        self._api_key.setEchoMode(QLineEdit.Password)
        self._api_key.setPlaceholderText("sk-...")
        self._api_key.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._api_key.textEdited.connect(self._mark_api_key_dirty)
        row.addWidget(self._api_key, stretch=1)

        self._api_key_show = QPushButton(t("settings.api_key.show"))
        self._api_key_show.setProperty("variant", "ghost")
        self._api_key_show.setCheckable(True)
        self._api_key_show.toggled.connect(self._toggle_api_key_echo)
        row.addWidget(self._api_key_show)

        self._api_key_test = QPushButton(t("settings.api_key.test"))
        self._api_key_test.clicked.connect(self._on_test_connection)
        row.addWidget(self._api_key_test)

        self._api_key_delete = QPushButton(t("settings.api_key.delete"))
        self._api_key_delete.setProperty("variant", "danger")
        self._api_key_delete.clicked.connect(self._on_delete_api_key)
        row.addWidget(self._api_key_delete)
        return row

    def _build_model_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        label = QLabel(t("settings.model"))
        label.setMinimumWidth(120)
        row.addWidget(label)

        # Editable combo so presets seed the recommended models but the
        # user can still type anything (e.g. a freshly-released model
        # alias the dropdown doesn't know about yet).
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._model_combo.setMinimumWidth(280)
        self._model_combo.setCurrentText(self._settings.ai_model)
        self._model_combo.lineEdit().textEdited.connect(self._mark_manual_model)
        row.addWidget(self._model_combo, stretch=1)
        return row

    def _build_github_section(self) -> QVBoxLayout:
        wrapper = QVBoxLayout()
        wrapper.setSpacing(8)

        title = QLabel(t("settings.github.title"))
        title.setStyleSheet(
            f"color: {Tokens.text}; font-size: 14px; font-weight: 600;"
        )
        wrapper.addWidget(title)

        hint = QLabel(t("settings.github.tip_html"))
        hint.setTextFormat(Qt.RichText)
        hint.setOpenExternalLinks(True)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {Tokens.text_muted}; font-size: 11px;")
        wrapper.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel(t("settings.github.token"))
        label.setMinimumWidth(120)
        row.addWidget(label)

        self._github_token = QLineEdit(self._settings.github_token)
        self._github_token.setEchoMode(QLineEdit.Password)
        self._github_token.setPlaceholderText("ghp_... or github_pat_...")
        self._github_token.textEdited.connect(self._mark_github_dirty)
        row.addWidget(self._github_token, stretch=1)

        self._github_show = QPushButton(t("settings.api_key.show"))
        self._github_show.setProperty("variant", "ghost")
        self._github_show.setCheckable(True)
        self._github_show.toggled.connect(self._toggle_github_echo)
        row.addWidget(self._github_show)

        self._github_delete = QPushButton(t("settings.github.delete"))
        self._github_delete.setProperty("variant", "danger")
        self._github_delete.clicked.connect(self._on_delete_github)
        row.addWidget(self._github_delete)
        wrapper.addLayout(row)
        return wrapper

    def _build_confirm_refine_check(self) -> QCheckBox:
        cb = QCheckBox(t("settings.confirm_refine"))
        cb.setToolTip(t("settings.confirm_refine.tip"))
        cb.setChecked(self._settings.ai_confirm_refine)
        self._confirm_refine_check = cb
        return cb

    def _build_examples_label(self) -> QLabel:
        hint = QLabel(t("settings.examples_html"))
        hint.setTextFormat(Qt.RichText)
        hint.setStyleSheet(f"color: {Tokens.text_muted}; font-size: 11px;")
        hint.setWordWrap(True)
        return hint

    def _build_separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {Tokens.border}; background-color: {Tokens.border};")
        line.setFixedHeight(1)
        return line

    def _build_button_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(t("settings.cancel"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        save = QPushButton(t("settings.save"))
        save.setProperty("variant", "primary")
        save.setDefault(True)
        save.clicked.connect(self._on_save)
        row.addWidget(save)
        return row

    # ----------------------------------------------------------- handlers
    def _on_preset_changed(self) -> None:
        if self._suppress_preset_signal:
            return
        key = self._preset_combo.currentData()
        self._sync_preset_to_inputs(key, refill=True)

    def _sync_preset_to_inputs(self, preset_key: str, *, refill: bool) -> None:
        preset = next((p for p in _PRESETS if p.key == preset_key), None)
        if preset is None:
            return
        self._suppress_preset_signal = True
        try:
            for i in range(self._preset_combo.count()):
                if self._preset_combo.itemData(i) == preset_key:
                    self._preset_combo.setCurrentIndex(i)
                    break
        finally:
            self._suppress_preset_signal = False

        if preset_key in {"custom"}:
            # Don't touch the user's freeform inputs in custom mode.
            return

        if refill and preset.base_url:
            self._base_url.setText(preset.base_url)
        # Always rebuild the model dropdown so the suggestions match the
        # picked vendor. Preserve whatever the user already typed at the
        # top so we don't clobber a custom alias on re-open.
        current_typed = self._model_combo.currentText().strip()
        self._model_combo.blockSignals(True)
        try:
            self._model_combo.clear()
            for m in preset.models:
                self._model_combo.addItem(m)
            if current_typed and current_typed not in preset.models:
                # Keep the manual choice as the current text so refill
                # doesn't silently drop it.
                self._model_combo.setEditText(current_typed)
            elif preset.models:
                self._model_combo.setCurrentIndex(0)
            else:
                self._model_combo.setEditText("")
        finally:
            self._model_combo.blockSignals(False)

    def _on_manual_base_url_edit(self, _text: str) -> None:
        # Any hand-edit means we can no longer claim the user picked
        # the matching preset, so flip to Custom for honesty.
        if self._preset_combo.currentData() != "custom":
            self._sync_preset_to_inputs("custom", refill=False)

    def _mark_manual_model(self, _text: str) -> None:
        # Typing a fresh model name into the combo doesn't change the
        # preset URL, so we only flip to Custom when the user typed
        # something the active preset doesn't recognise.
        preset_key = self._preset_combo.currentData()
        preset = next((p for p in _PRESETS if p.key == preset_key), None)
        if preset is None:
            return
        if preset.models and self._model_combo.currentText().strip() not in preset.models:
            self._sync_preset_to_inputs("custom", refill=False)

    def _mark_api_key_dirty(self, _text: str) -> None:
        self._state.api_key_dirty = True

    def _mark_github_dirty(self, _text: str) -> None:
        self._state.github_token_dirty = True

    def _toggle_api_key_echo(self, checked: bool) -> None:
        self._api_key.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self._api_key_show.setText(
            t("settings.api_key.hide") if checked else t("settings.api_key.show")
        )

    def _toggle_github_echo(self, checked: bool) -> None:
        self._github_token.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self._github_show.setText(
            t("settings.api_key.hide") if checked else t("settings.api_key.show")
        )

    def _on_test_connection(self) -> None:
        base_url = self._base_url.text().strip()
        api_key = self._api_key.text().strip()
        if not base_url or not api_key:
            self._set_status(t("settings.api_key.test_no_url"), kind="warn")
            return
        self._api_key_test.setEnabled(False)
        self._set_status(t("settings.api_key.testing"), kind="muted")
        thread = _ConnectionTester(base_url, api_key)
        self._state.test_thread = thread

        def _finished_ok(count: int) -> None:
            self._api_key_test.setEnabled(True)
            self._set_status(
                t("settings.api_key.test_ok", n=count), kind="ok"
            )
            self._cleanup_thread()

        def _finished_fail(error: str) -> None:
            self._api_key_test.setEnabled(True)
            self._set_status(
                t("settings.api_key.test_fail", error=error), kind="warn"
            )
            self._cleanup_thread()

        thread.finished_ok.connect(_finished_ok)
        thread.finished_fail.connect(_finished_fail)
        thread.start()

    def _cleanup_thread(self) -> None:
        thread = self._state.test_thread
        if thread is None:
            return
        try:
            thread.quit()
            thread.wait(2000)
        except Exception:  # pragma: no cover - thread shutdown is best-effort
            logger.debug("Test connection thread cleanup failed", exc_info=True)
        self._state.test_thread = None

    def _on_delete_api_key(self) -> None:
        try:
            delete_secret("AI_API_KEY")
        except Exception as exc:  # pragma: no cover - keyring backend can vary
            self._set_status(
                t("settings.api_key.delete_failed", error=str(exc)), kind="warn"
            )
            return
        self._api_key.clear()
        self._state.api_key_dirty = True
        self._set_status(t("settings.api_key.deleted"), kind="ok")

    def _on_delete_github(self) -> None:
        try:
            delete_secret("GITHUB_TOKEN")
        except Exception as exc:  # pragma: no cover - keyring backend can vary
            self._set_status(
                t("settings.github.delete_failed", error=str(exc)), kind="warn"
            )
            return
        self._github_token.clear()
        self._state.github_token_dirty = True
        self._set_status(t("settings.github.deleted"), kind="ok")

    # ----------------------------------------------------------- save
    def _on_save(self) -> None:
        try:
            self._persist()
        except Exception as exc:  # pragma: no cover - keyring write may fail
            logger.exception("Saving settings failed")
            QMessageBox.critical(self, t("settings.title"), str(exc))
            return
        self.accept()

    def _persist(self) -> None:
        preset_key = self._preset_combo.currentData()
        preset = next((p for p in _PRESETS if p.key == preset_key), None)
        provider_kind = preset.provider_kind if preset else "openai_compatible"

        base_url = self._base_url.text().strip()
        model = self._model_combo.currentText().strip()
        confirm_refine = self._confirm_refine_check.isChecked()

        # Persist the non-secret AI defaults so the next launch picks
        # them up without any .env edits.
        set_preference("ai_provider_raw", provider_kind)
        if base_url:
            set_preference("ai_base_url", base_url)
        if model:
            set_preference("ai_model", model)
        set_preference("ai_confirm_refine", confirm_refine)

        # Secrets only land in the keyring (or the JSON fallback) - never
        # in .env. We only touch the store when the user actually edited
        # the field so untouched keys don't get re-written every save.
        if self._state.api_key_dirty:
            api_key = self._api_key.text().strip()
            if api_key:
                set_secret("AI_API_KEY", api_key)
            else:
                # Empty + dirty = the user explicitly cleared the field.
                _silent_delete("AI_API_KEY")

        if self._state.github_token_dirty:
            token = self._github_token.text().strip()
            if token:
                set_secret("GITHUB_TOKEN", token)
            else:
                _silent_delete("GITHUB_TOKEN")

    def accepted_settings(self) -> Settings:
        """Re-read settings after Save so the caller sees the new values.

        ``MainWindow._open_settings`` calls this to rebuild the AI
        provider; everything we just persisted (preferences + keyring)
        is picked up by ``load_settings`` automatically.
        """
        return load_settings()

    # ----------------------------------------------------------- helpers
    def _set_status(self, message: str, *, kind: str) -> None:
        colour = {
            "ok": Tokens.success,
            "warn": Tokens.warn,
            "muted": Tokens.text_muted,
        }.get(kind, Tokens.text_muted)
        self._status.setStyleSheet(
            f"color: {colour}; font-size: 11px; padding-top: 4px;"
        )
        self._status.setText(message)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override naming
        self._cleanup_thread()
        super().closeEvent(event)


def _silent_delete(name: str) -> None:
    """Delete a secret without raising if the keyring backend complains."""
    try:
        delete_secret(name)
    except Exception:  # pragma: no cover - some backends raise on missing keys
        logger.debug("Silent delete of %s failed", name, exc_info=True)


__all__ = ["SettingsDialog"]


# Tiny shim so ``Callable`` import isn't flagged as unused on builds where
# ``__future__.annotations`` makes the typing references lazy.
_ = Callable  # type: ignore[misc]
