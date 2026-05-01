"""Small pill-style status chip used in sidebar and header."""
from __future__ import annotations

from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from ..theme import Tokens

ChipVariant = Literal["idle", "active", "done", "demo", "live", "warn", "danger"]


_VARIANT_COLOURS: dict[str, tuple[str, str]] = {
    "idle":   (Tokens.chip_idle_bg,   Tokens.chip_idle_fg),
    "active": (Tokens.chip_active_bg, Tokens.chip_active_fg),
    "done":   (Tokens.chip_done_bg,   Tokens.chip_done_fg),
    "demo":   (Tokens.chip_demo_bg,   Tokens.chip_demo_fg),
    "live":   (Tokens.chip_live_bg,   Tokens.chip_live_fg),
    "warn":   (Tokens.chip_demo_bg,   Tokens.chip_demo_fg),
    "danger": ("#2a0d0d",             Tokens.danger),
}


class StatusChip(QLabel):
    """Compact text pill with a coloured background.

    Usage::

        chip = StatusChip("Demo", variant="demo")
        chip.set_variant("live", text="Live")
    """

    def __init__(
        self,
        text: str = "",
        variant: ChipVariant = "idle",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setContentsMargins(0, 0, 0, 0)
        self._variant: ChipVariant = variant
        self._apply_style()

    # ------------------------------------------------------------ public
    def set_variant(self, variant: ChipVariant, text: str | None = None) -> None:
        self._variant = variant
        if text is not None:
            self.setText(text)
        self._apply_style()

    # ------------------------------------------------------------ helpers
    def _apply_style(self) -> None:
        bg, fg = _VARIANT_COLOURS.get(self._variant, _VARIANT_COLOURS["idle"])
        self.setStyleSheet(
            f"QLabel {{"
            f"  background-color: {bg};"
            f"  color: {fg};"
            f"  border-radius: 9px;"
            f"  padding: 2px 9px;"
            f"  font-size: 10px;"
            f"  font-weight: 600;"
            f"  letter-spacing: 0.4px;"
            f"}}"
        )


__all__ = ["StatusChip", "ChipVariant"]
