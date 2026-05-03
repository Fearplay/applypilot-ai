"""Modal popup that asks which language the AI documents should be in.

Shown right before ``MainWindow._start_document_generation`` so the user can
keep the chat / questions in their UI language but still ask the AI to write
the resume + cover letter in a different language (typical case: Czech UI,
English resume because the job is at an international company).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import t
from .theme import Tokens


class OutputLanguageDialog(QDialog):
    """Pick the language for the resume, cover letter and other AI outputs."""

    def __init__(self, default: str = "en", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("out_lang.title"))
        self.setModal(True)
        self.setMinimumWidth(440)

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
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, alignment=Qt.AlignRight)

    def selected_language(self) -> str:
        return "cs" if self._radio_cs.isChecked() else "en"


__all__ = ["OutputLanguageDialog"]
