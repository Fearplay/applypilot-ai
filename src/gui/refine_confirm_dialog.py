"""Lightweight modal asking the user to confirm an AI refine call.

Refining a tailored resume costs ~$0.01-0.05 depending on the model and
how big the resume is. The user reported feeling like they were charged
"while AFK" - the actual root cause was a stray click on the Refine
button right before stepping away. This dialog is the safety belt: it
forces the user to consciously approve every refine call (or untick the
checkbox if they're doing a flurry of edits and don't want the prompt
between each one).

The "Don't ask again this session" choice lives in
:class:`MainWindow` so it resets on app restart - we never persist the
opt-out, the safer default always returns the next time the app starts.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..i18n import t
from .theme import Tokens


class RefineConfirmDialog(QDialog):
    """Confirm-or-cancel modal with an optional cost estimate.

    ``estimated_usd`` is ``None`` when we don't have pricing for the
    selected model (Custom / Ollama / unknown alias). In that case the
    body falls back to ``docs.refine.confirm.body_unknown_cost`` so the
    user still sees something honest instead of "~$0.00".
    """

    def __init__(
        self,
        model: str,
        estimated_usd: float | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("docs.refine.confirm.title"))
        self.setModal(True)
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        title = QLabel(t("docs.refine.confirm.title"))
        title.setStyleSheet(
            f"color: {Tokens.text}; font-size: 16px; font-weight: 600;"
        )
        layout.addWidget(title)

        if estimated_usd is None or estimated_usd <= 0.0:
            body_text = t(
                "docs.refine.confirm.body_unknown_cost",
                model=model or "?",
            )
        else:
            cost_text = t(
                "docs.refine.confirm.cost_about", cost=estimated_usd
            )
            body_text = t(
                "docs.refine.confirm.body",
                cost=cost_text,
                model=model or "?",
            )

        body = QLabel(body_text)
        body.setTextFormat(Qt.RichText)
        body.setWordWrap(True)
        body.setStyleSheet(f"color: {Tokens.text}; font-size: 12px;")
        layout.addWidget(body)

        self._dont_ask = QCheckBox(t("docs.refine.confirm.dont_ask"))
        self._dont_ask.setStyleSheet(
            f"QCheckBox {{ color: {Tokens.text_muted}; font-size: 11px; }}"
        )
        layout.addWidget(self._dont_ask)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        ok = buttons.button(QDialogButtonBox.Ok)
        ok.setProperty("variant", "primary")
        ok.style().unpolish(ok)
        ok.style().polish(ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, alignment=Qt.AlignRight)

    def dont_ask_again(self) -> bool:
        """``True`` when the user checked the 'don't ask again' box."""
        return self._dont_ask.isChecked()


__all__ = ["RefineConfirmDialog"]
