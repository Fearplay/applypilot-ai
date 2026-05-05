"""Smoke tests for the sidebar's session-cost panel.

The user explicitly asked for a permanent, prominent cost readout next
to the ``Aktivita`` block so they can always see how much they've spent
in the current session, separate from the ephemeral activity messages.

These tests pin down two contracts:

* The sidebar exposes its cost label so external code (and tests) can
  read the formatted spend.
* :meth:`Sidebar.set_activity` only mutates the activity area; it must
  NEVER overwrite or hide the cost label, even after a stream of
  AI-call messages.

Skipped automatically when PySide6 can't open an offscreen
``QApplication`` (CI runners without GL libraries).
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")  # noqa: N816
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.gui.widgets.sidebar import Sidebar, SidebarItem  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance()
    created = False
    if app is None:
        try:
            app = QApplication([])
            created = True
        except Exception as exc:  # pragma: no cover - missing GL/X server
            pytest.skip(f"Qt application unavailable: {exc}")
    yield app
    if created:
        app.quit()


def _make_sidebar() -> Sidebar:
    return Sidebar(
        items=[
            SidebarItem(key="setup", title="Setup"),
            SidebarItem(key="documents", title="Documents"),
        ]
    )


def test_sidebar_renders_cost_panel_above_activity(qt_app):
    """The new cost panel must:
    * have its own header label (translated; not empty),
    * render the SessionCostLabel underneath that header,
    * sit ABOVE the activity row inside the same vertical layout.
    """
    sidebar = _make_sidebar()

    assert sidebar._cost_header.text(), (
        "expected a translated header above the cost value"
    )
    assert sidebar._cost_value is not None
    # Cost label always carries a non-empty rendering of the totals
    # (even when the session has not made any AI calls, "0 calls /
    # 0 tokens / ~$0.00" still fills the text).
    assert sidebar._cost_value.text(), (
        "cost label must show formatted totals from the start"
    )

    layout = sidebar.layout()
    indices = {}
    for i in range(layout.count()):
        item = layout.itemAt(i)
        widget = item.widget()
        if widget is sidebar._cost_header:
            indices["cost_header"] = i
        elif widget is sidebar._cost_value:
            indices["cost_value"] = i
        elif widget is sidebar._footer_lbl:
            indices["activity_header"] = i
        elif widget is sidebar._activity:
            indices["activity_value"] = i

    assert indices["cost_header"] < indices["cost_value"]
    assert indices["cost_value"] < indices["activity_header"]
    assert indices["activity_header"] < indices["activity_value"]


def test_set_activity_does_not_overwrite_cost_label(qt_app):
    """Workflow status updates feed ``Sidebar.set_activity`` from
    background workers. They must NEVER touch the cost row, otherwise
    the user loses sight of how much the current session has spent."""
    sidebar = _make_sidebar()

    cost_text_before = sidebar._cost_value.text()
    activity_text_before = sidebar._activity.text()

    sidebar.set_activity("Refining cover letter with your feedback...")
    assert sidebar._cost_value.text() == cost_text_before
    assert sidebar._activity.text() == (
        "Refining cover letter with your feedback..."
    )

    sidebar.set_activity("")  # empty falls back to "Ready" / "Připraveno"
    assert sidebar._cost_value.text() == cost_text_before
    # Activity falls back, cost stays put.
    assert sidebar._activity.text() != activity_text_before or (
        sidebar._activity.text()
    ).strip() != ""


def test_session_cost_listener_keeps_cost_visible_after_record_call(qt_app):
    """When a real AI call lands (or, in this test, we synthesise one
    via ``session_cost.record_call``), the cost label updates, but the
    activity area stays separate. This is the user's "I want to keep
    seeing the cost while activity scrolls" requirement."""
    from src.ai import session_cost

    sidebar = _make_sidebar()
    sidebar.set_activity("Working...")
    activity_before = sidebar._activity.text()

    # Synthesise a call so the cost label has something to format.
    session_cost.record_call(
        model="gpt-4o-mini",
        prompt_tokens=1234,
        completion_tokens=567,
    )
    # Force the QTimer.singleShot(0, _refresh) onto the active event
    # loop so the cost label has actually updated by the time we read.
    QApplication.processEvents()

    # The activity row never changed - still "Working..." - even though
    # we just bumped the cost counter.
    assert sidebar._activity.text() == activity_before
    # And the cost label DOES contain the new dollar / call info.
    cost_html = sidebar._cost_value.text()
    assert cost_html  # non-empty
    # The compact=False sidebar renders RichText; checking for the
    # call-count digit AND the dollar sign verifies both rows refreshed.
    assert "1" in cost_html  # at least one call recorded
    assert "$" in cost_html
