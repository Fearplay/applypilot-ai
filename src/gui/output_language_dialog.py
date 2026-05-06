"""Modal popup that asks which language and visual theme the AI documents use.

Shown right before ``MainWindow._start_document_generation`` so the user can:

* Keep the chat / questions in their UI language but ask the AI to write the
  resume + cover letter in another language (typical case: Czech UI, English
  resume because the job is at an international company).
* Pick the visual theme of the styled CV / cover letter PDFs - the user
  explicitly asked for the look to vary between generations ("at to furt
  neni stejny styl"). Six concrete themes ship out of the box plus a
  ``Random`` sentinel that lets the engine pick a different look each save.

The dialog file is named ``output_language_dialog`` for backwards
compatibility - existing imports keep working - but internally it is now a
combined "document options" dialog and exposes ``selected_theme()``
alongside the legacy ``selected_language()`` accessor.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import t
from ..services.document_themes import (
    DEFAULT_THEME_SLUG,
    RANDOM_THEME_SLUG,
    theme_choices,
)
from ..utils.preferences import get_preference, set_preference
from .theme import Tokens

#: Preference key used to remember the last picked theme across runs.
PREF_KEY_DOCS_THEME = "docs_theme"
#: Preference key for the "translate position titles" checkbox. Persisted
#: as a bool string so we round-trip cleanly through the JSON preference
#: store.
PREF_KEY_TRANSLATE_POSITIONS = "translate_positions"


class OutputLanguageDialog(QDialog):
    """Pick the language + visual theme for the resume, cover letter and other AI outputs."""

    def __init__(
        self,
        default: str = "en",
        *,
        default_theme: str | None = None,
        default_translate_positions: bool | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("out_lang.title"))
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        heading = QLabel(t("out_lang.heading"))
        heading.setWordWrap(True)
        heading.setStyleSheet(
            f"color: {Tokens.text}; font-size: 16px; font-weight: 600;"
        )
        layout.addWidget(heading)

        intro = QLabel(t("out_lang.intro"))
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {Tokens.text_muted}; font-size: 12px;")
        layout.addWidget(intro)

        self._group = QButtonGroup(self)
        self._radio_en = QRadioButton(t("out_lang.option.en"))
        self._radio_cs = QRadioButton(t("out_lang.option.cs"))
        self._group.addButton(self._radio_en, id=0)
        self._group.addButton(self._radio_cs, id=1)
        layout.addWidget(self._radio_en)
        layout.addWidget(self._radio_cs)

        if default == "cs":
            self._radio_cs.setChecked(True)
        else:
            self._radio_en.setChecked(True)

        ui_lang = "cs" if default == "cs" else "en"

        style_label = QLabel(t("out_lang.style_label"))
        style_label.setStyleSheet(
            f"color: {Tokens.text}; font-size: 13px; font-weight: 600; margin-top: 8px;"
        )
        layout.addWidget(style_label)

        style_intro = QLabel(t("out_lang.style.intro"))
        style_intro.setWordWrap(True)
        style_intro.setStyleSheet(f"color: {Tokens.text_muted}; font-size: 12px;")
        layout.addWidget(style_intro)

        self._theme_combo = QComboBox()
        # First entry is the random sentinel - ``slug`` is the user-data so
        # we never ship "random" as if it were a real theme to the
        # exporter (MainWindow resolves it to a concrete slug at save
        # time).
        self._theme_combo.addItem(t("out_lang.style.random"), RANDOM_THEME_SLUG)
        for theme in theme_choices():
            i18n_key = f"out_lang.style.{theme.slug}"
            translated = t(i18n_key)
            # Fall back to the theme's built-in display name if the i18n
            # table doesn't carry an entry yet (keeps the picker working
            # for newly added themes before localisation lands).
            label = (
                translated
                if translated and translated != i18n_key
                else theme.display_name(ui_lang)
            )
            self._theme_combo.addItem(label, theme.slug)
        layout.addWidget(self._theme_combo)

        # Pick the default theme - the explicit caller wins, then the
        # persisted preference, then the random sentinel so each new user
        # gets variety out of the box.
        target_slug: str = (
            default_theme
            or str(get_preference(PREF_KEY_DOCS_THEME, RANDOM_THEME_SLUG))
            or RANDOM_THEME_SLUG
        )
        idx = self._theme_combo.findData(target_slug)
        if idx < 0:
            # Fall back to the default visual theme if the stored slug
            # was retired between releases.
            idx = self._theme_combo.findData(DEFAULT_THEME_SLUG)
        self._theme_combo.setCurrentIndex(max(idx, 0))

        # "Translate position titles" toggle. Default ON because that has
        # been the implicit historical behaviour for years; users who
        # specifically want to keep ``"Senior Software QA Engineer"``
        # verbatim on a Czech resume tick the box off and the preference
        # is persisted so they don't have to do it every run.
        if default_translate_positions is None:
            stored = get_preference(PREF_KEY_TRANSLATE_POSITIONS, True)
            default_translate_positions = (
                stored if isinstance(stored, bool) else str(stored).lower() != "false"
            )
        self._translate_positions = QCheckBox(
            t("out_lang.translate_positions.label")
        )
        self._translate_positions.setToolTip(
            t("out_lang.translate_positions.tooltip")
        )
        self._translate_positions.setChecked(bool(default_translate_positions))
        layout.addWidget(self._translate_positions)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.Ok)
        ok_btn.setText(t("out_lang.confirm"))
        ok_btn.setProperty("variant", "primary")
        ok_btn.style().unpolish(ok_btn)
        ok_btn.style().polish(ok_btn)
        cancel_btn = buttons.button(QDialogButtonBox.Cancel)
        cancel_btn.setText(t("out_lang.cancel"))
        cancel_btn.setProperty("variant", "ghost")
        cancel_btn.style().unpolish(cancel_btn)
        cancel_btn.style().polish(cancel_btn)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, alignment=Qt.AlignRight)

    def selected_language(self) -> str:
        return "cs" if self._radio_cs.isChecked() else "en"

    def selected_theme(self) -> str:
        """Return the picked theme slug (may be ``random``)."""
        slug = self._theme_combo.currentData()
        return str(slug or RANDOM_THEME_SLUG)

    def selected_translate_positions(self) -> bool:
        """Return whether role titles should be translated to ``selected_language``.

        ``True`` by default and after every run that didn't touch the
        checkbox; ``False`` only when the user explicitly opted out via
        the dialog. Mirrors :func:`selected_theme` in shape so callers
        plumb the three accessors through together.
        """
        return self._translate_positions.isChecked()

    def _on_accept(self) -> None:
        # Persist the user's pick so next time the dialog opens with the
        # same theme highlighted - this directly addresses the user's
        # "I want the look to be different per generation" request when
        # combined with the ``random`` default for new installs.
        try:
            set_preference(PREF_KEY_DOCS_THEME, self.selected_theme())
        except Exception:  # pragma: no cover - preferences must never break the dialog
            pass
        try:
            set_preference(
                PREF_KEY_TRANSLATE_POSITIONS,
                self.selected_translate_positions(),
            )
        except Exception:  # pragma: no cover - preferences must never break the dialog
            pass
        self.accept()


__all__ = [
    "OutputLanguageDialog",
    "PREF_KEY_DOCS_THEME",
    "PREF_KEY_TRANSLATE_POSITIONS",
]
