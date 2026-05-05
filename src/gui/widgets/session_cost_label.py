"""Widget that surfaces the session-wide AI spend.

Two layouts:

* **Compact (default).** A one-liner like
  ``AI: 8 calls - 24.3k tokens - ~$0.18 this session`` used as a
  status-bar widget. Kept for back-compat callers that may still
  rely on the historical look.
* **Multi-line / sidebar.** Used inside :class:`Sidebar` above the
  ``Aktivita`` block. Calls + tokens sit on one line and the dollar
  total sits on a second, slightly larger line so the user can glance
  at the sidebar and read the dollar amount without parsing the rest.
  This is what the user explicitly asked for: a permanent, prominent
  cost readout next to the activity area, separate from the
  ephemeral status-bar messages.

The widget subscribes to :mod:`src.ai.session_cost` and uses Qt's
``QTimer.singleShot(0, ...)`` to marshal updates to the GUI thread -
the counter is bumped from background QThreadPool workers and Qt
widgets must only be touched from the main thread.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import QLabel

from ...ai import session_cost
from ...i18n import register_listener as register_lang_listener
from ...i18n import t
from ..theme import Tokens


class SessionCostLabel(QLabel):
    """Read-only label that reflects :func:`session_cost.get_totals`.

    Set ``compact=False`` (the sidebar default) to render a multi-line
    block where the dollar total stands out on its own row. The status
    bar still uses the default ``compact=True`` one-liner.
    """

    def __init__(self, parent=None, *, compact: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("sessionCostLabel")
        self._compact = compact
        if compact:
            self.setStyleSheet(
                f"QLabel#sessionCostLabel {{ "
                f"color: {Tokens.text_muted}; font-size: 11px; "
                "padding: 2px 10px; }"
            )
        else:
            # Sidebar styling: bigger and brighter so the user can read
            # the running dollar total at a glance. Uses HTML in the
            # label text (see ``_refresh``) so we can highlight the cost
            # row separately from the calls / tokens summary line.
            self.setStyleSheet(
                "QLabel#sessionCostLabel { "
                f"color: {Tokens.text}; "
                "font-size: 12px; "
                "padding: 4px 14px 8px 14px; "
                "}"
            )
            self.setTextFormat(Qt.RichText)
            self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._refresh()
        # Subscribe to live updates...
        session_cost.register_listener(self._on_totals_changed)
        # ...and unsubscribe automatically when Qt deletes us, otherwise
        # the listener keeps a reference to a dead Qt widget and the
        # next ``record_call`` raises ``RuntimeError: Internal C++
        # object already deleted``. The ``destroyed`` signal fires AFTER
        # the C++ side is gone, so the unregister has to capture the
        # bound method up-front.
        bound_listener = self._on_totals_changed
        self.destroyed.connect(
            lambda *_: session_cost.unregister_listener(bound_listener)
        )
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
        QTimer.singleShot(0, self._safe_refresh)

    @Slot()
    def _safe_refresh(self) -> None:
        # ``QTimer.singleShot`` may fire after the widget has been
        # destroyed (typical in tests that recreate sidebars). Guard the
        # actual refresh so a stale listener never raises into the
        # session_cost dispatch loop.
        try:
            self._refresh()
        except RuntimeError:
            return

    @Slot()
    def _refresh(self) -> None:
        totals = session_cost.get_totals()
        if totals.total_tokens >= 1000:
            tokens_label = t(
                "ai.session.tokens.short", value=totals.total_tokens / 1000.0
            )
        else:
            tokens_label = str(totals.total_tokens)
        if self._compact:
            text = t("ai.session.label") + ": " + t(
                "ai.session.summary",
                calls=totals.calls,
                tokens=tokens_label,
                cost=totals.estimated_usd,
            )
            self.setText(text)
        else:
            # Sidebar layout: two lines.
            #   line 1: calls + tokens  (small, muted)
            #   line 2: ~$0.42 this session  (big, accent colour)
            line1 = t(
                "sidebar.cost.usage",
                calls=totals.calls,
                tokens=tokens_label,
            )
            line2 = t(
                "sidebar.cost.total",
                cost=totals.estimated_usd,
            )
            self.setText(
                f"<div style='color:{Tokens.text_muted};font-size:11px'>"
                f"{line1}</div>"
                f"<div style='color:{Tokens.accent};"
                "font-size:14px;font-weight:600;margin-top:2px'>"
                f"{line2}</div>"
            )
        self.setToolTip(t("ai.session.tooltip"))


__all__ = ["SessionCostLabel"]
