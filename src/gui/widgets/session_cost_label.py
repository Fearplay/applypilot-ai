"""Status-bar widget that surfaces the session-wide AI spend.

Lives in the bottom-left corner of :class:`MainWindow` so the user sees
``AI: 8 calls - 24.3k tokens - ~$0.18 this session`` updating in real time.
The widget subscribes to :mod:`src.ai.session_cost` and uses Qt's
``QMetaObject.invokeMethod`` to marshal updates to the GUI thread - the
counter is bumped from background QThreadPool workers and Qt widgets
must only be touched from the main thread.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import QLabel

from ...ai import session_cost
from ...i18n import register_listener as register_lang_listener
from ...i18n import t
from ..theme import Tokens


class SessionCostLabel(QLabel):
    """Read-only label that reflects :func:`session_cost.get_totals`."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("sessionCostLabel")
        self.setStyleSheet(
            f"QLabel#sessionCostLabel {{ "
            f"color: {Tokens.text_muted}; font-size: 11px; "
            "padding: 2px 10px; }}"
        )
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._refresh()
        # Subscribe to live updates...
        session_cost.register_listener(self._on_totals_changed)
        # ...but also tick once a second as belt-and-braces in case a
        # listener was lost (Qt cross-thread quirks). Cheap; we only
        # call _refresh which is a string format.
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        # Re-render on language switch so the label uses the active locale.
        register_lang_listener(lambda _code: self._refresh())

    # The session_cost listener fires from worker threads; bounce the
    # update through QTimer.singleShot(0) which is thread-safe and posts
    # a deferred call to the GUI thread.
    def _on_totals_changed(self, _totals: session_cost.SessionTotals) -> None:
        QTimer.singleShot(0, self._refresh)

    @Slot()
    def _refresh(self) -> None:
        totals = session_cost.get_totals()
        if totals.total_tokens >= 1000:
            tokens_label = t(
                "ai.session.tokens.short", value=totals.total_tokens / 1000.0
            )
        else:
            tokens_label = str(totals.total_tokens)
        text = t("ai.session.label") + ": " + t(
            "ai.session.summary",
            calls=totals.calls,
            tokens=tokens_label,
            cost=totals.estimated_usd,
        )
        self.setText(text)
        self.setToolTip(t("ai.session.tooltip"))


__all__ = ["SessionCostLabel"]
