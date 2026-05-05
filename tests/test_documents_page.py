"""Smoke tests for the multi-problem refine panel inside DocumentsPage.

We exercise the new ``_RefinePanel`` widget directly (not the full
``DocumentsPage``) so the test stays focused on the behaviour the user
sees: typing into multiple ``Problem N`` rows, clicking *Refine with
AI* and confirming the formatted ``"1) ...\n2) ..."`` payload reaches
the ``refine_clicked`` signal.

Skipped automatically when PySide6 can't open an offscreen
``QApplication`` (CI runners without GL libraries).
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")  # noqa: N816
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.gui.documents_page import (  # noqa: E402
    _MAX_REFINE_PROBLEMS,
    _RefinePanel,
)


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


def _capture_emit(panel: _RefinePanel) -> list[str]:
    """Hook ``refine_clicked`` so we can assert what gets emitted."""
    received: list[str] = []
    panel.refine_clicked.connect(received.append)
    return received


def test_panel_starts_with_one_empty_problem_row(qt_app):
    panel = _RefinePanel()
    # One default row, no remove button visible (single-row state).
    assert len(panel._rows) == 1
    assert panel._rows[0].text() == ""


def test_add_problem_grows_up_to_six_rows(qt_app):
    panel = _RefinePanel()
    for _ in range(_MAX_REFINE_PROBLEMS - 1):
        panel._on_add()
    assert len(panel._rows) == _MAX_REFINE_PROBLEMS
    # One more click is a no-op so the prompt size stays bounded.
    panel._on_add()
    assert len(panel._rows) == _MAX_REFINE_PROBLEMS


def test_remove_problem_keeps_at_least_one_row(qt_app):
    panel = _RefinePanel()
    panel._on_add()
    panel._on_add()
    assert len(panel._rows) == 3
    # Remove the middle row by simulating a click on its X button.
    panel._on_remove(panel._rows[1])
    assert len(panel._rows) == 2
    # Removing the remaining ones must stop at one.
    panel._on_remove(panel._rows[1])
    assert len(panel._rows) == 1
    panel._on_remove(panel._rows[0])
    assert len(panel._rows) == 1


def test_submit_formats_three_problems_as_numbered_list(qt_app):
    panel = _RefinePanel()
    received = _capture_emit(panel)
    # Type into the first row, add two more, type into them.
    panel._rows[0]._editor.setPlainText("Reword the summary.")
    panel._on_add()
    panel._rows[1]._editor.setPlainText("Add an internship from 2019.")
    panel._on_add()
    panel._rows[2]._editor.setPlainText("Drop the IT-tester row.")

    panel._on_submit()

    assert received == [
        "1) Reword the summary.\n"
        "2) Add an internship from 2019.\n"
        "3) Drop the IT-tester row."
    ]


def test_submit_skips_blank_rows_and_renumbers(qt_app):
    """Blank rows in the middle of the list must not produce a
    ``"2) "`` empty entry; the numbering follows the surviving items."""
    panel = _RefinePanel()
    received = _capture_emit(panel)
    panel._rows[0]._editor.setPlainText("First.")
    panel._on_add()  # row 2 stays blank
    panel._on_add()
    panel._rows[2]._editor.setPlainText("Third.")

    panel._on_submit()

    assert received == ["1) First.\n2) Third."]


def test_submit_ignored_when_all_rows_are_blank(qt_app):
    """No emission, no exception - the user just sees the
    'Nothing to refine' info dialog (which we suppress in tests by
    monkeypatching ``QMessageBox.information``)."""
    from PySide6.QtWidgets import QMessageBox

    calls: list[tuple] = []

    def _capture(*args, **kwargs):
        calls.append(args)
        return QMessageBox.Ok

    original = QMessageBox.information
    QMessageBox.information = staticmethod(_capture)  # type: ignore[assignment]
    try:
        panel = _RefinePanel()
        received = _capture_emit(panel)
        panel._on_submit()
    finally:
        QMessageBox.information = original  # type: ignore[assignment]

    assert received == []
    # The empty-warning info box was shown.
    assert calls and calls[0][0] is panel


def test_set_busy_disables_inputs_and_buttons(qt_app):
    panel = _RefinePanel()
    panel._on_add()
    panel.set_busy(True)
    assert not panel._refine_btn.isEnabled()
    assert not panel._add_btn.isEnabled()
    for row in panel._rows:
        assert row._editor.isReadOnly()
    panel.set_busy(False)
    assert panel._refine_btn.isEnabled()
    assert panel._add_btn.isEnabled()


def test_reset_to_single_problem_clears_extras(qt_app):
    panel = _RefinePanel()
    panel._rows[0]._editor.setPlainText("First.")
    panel._on_add()
    panel._rows[1]._editor.setPlainText("Second.")
    panel._on_add()
    assert len(panel._rows) == 3

    panel.reset_to_single_problem()

    assert len(panel._rows) == 1
    assert panel._rows[0].text() == ""


# ---------------------------------------------------------------------------
# Tab-aware refine routing (resume vs cover letter vs blocked)
# ---------------------------------------------------------------------------
from src.gui.documents_page import DocumentsPage  # noqa: E402


def _select_tab(page: DocumentsPage, widget) -> None:
    idx = page._tabs.indexOf(widget)
    assert idx >= 0
    page._tabs.setCurrentIndex(idx)


def test_refine_on_resume_tab_emits_resume_target(qt_app):
    """Pressing Refine while the Tailored Resume tab is active must
    fire ``refine_requested(feedback, "resume")`` so the main window
    routes the AI call to the resume pipeline.
    """
    page = DocumentsPage()
    received: list[tuple[str, str]] = []
    page.refine_requested.connect(lambda fb, tgt: received.append((fb, tgt)))

    _select_tab(page, page._resume_edit)
    page._refine_panel._rows[0]._editor.setPlainText("Tighten the summary.")
    page._refine_panel._on_submit()

    assert received == [("1) Tighten the summary.", "resume")]


def test_refine_on_modern_resume_tab_also_routes_to_resume(qt_app):
    """The Modern Resume tab is just a styled view of the same data, so
    refining there must still hit the resume pipeline (not no-op)."""
    page = DocumentsPage()
    received: list[tuple[str, str]] = []
    page.refine_requested.connect(lambda fb, tgt: received.append((fb, tgt)))

    _select_tab(page, page._modern_resume)
    page._refine_panel._rows[0]._editor.setPlainText("Use forest theme.")
    page._refine_panel._on_submit()

    assert received and received[0][1] == "resume"


def test_refine_on_cover_letter_tab_emits_cover_letter_target(qt_app):
    page = DocumentsPage()
    received: list[tuple[str, str]] = []
    page.refine_requested.connect(lambda fb, tgt: received.append((fb, tgt)))

    _select_tab(page, page._cover_edit)
    page._refine_panel._rows[0]._editor.setPlainText("Less formal opening.")
    page._refine_panel._on_submit()

    assert received == [("1) Less formal opening.", "cover_letter")]


def test_refine_on_unsupported_tab_blocks_and_shows_hint(qt_app):
    """Match-report / interview / gap / evidence tabs do not have an
    AI refine flow yet. Pressing Refine there must NOT silently rewrite
    the resume - it must show the 'switch tabs' hint and emit nothing.
    """
    from PySide6.QtWidgets import QMessageBox

    info_calls: list[tuple] = []

    def _capture(*args, **kwargs):
        info_calls.append(args)
        return QMessageBox.Ok

    original = QMessageBox.information
    QMessageBox.information = staticmethod(_capture)  # type: ignore[assignment]
    try:
        page = DocumentsPage()
        received: list[tuple[str, str]] = []
        page.refine_requested.connect(
            lambda fb, tgt: received.append((fb, tgt))
        )
        # Match report tab is read-only and has no AI refine flow.
        _select_tab(page, page._match_edit)
        page._refine_panel._rows[0]._editor.setPlainText("Boost the score.")
        page._refine_panel._on_submit()
    finally:
        QMessageBox.information = original  # type: ignore[assignment]

    assert received == []
    assert info_calls, "expected the 'switch tabs' info dialog to fire"
