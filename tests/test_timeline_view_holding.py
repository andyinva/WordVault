"""
GUI tests for view-holding during time travel: the departure
photograph (leave live -> wander history -> Newest returns you exactly
where you left, scroll AND cursor) and its freshness across
consecutive trips — Andrew's 'each return lands one test behind'
report made trip-to-trip staleness the very thing to pin down.

Runs the real MainWindow offscreen with the real timeline buttons.
"""

import os
import time

import pytest

# Must be set before Qt is imported anywhere in the process.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)

from PyQt6.QtWidgets import QApplication  # noqa: E402

from wordvault.editor import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _pump(app, ms=700):
    """Let timers (deferred restores, retries) run their course."""
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


@pytest.fixture()
def essay_window(qapp, tmp_path):
    """A window holding an essay-shaped document (markdown headings +
    screen-filling paragraphs) with two revisions."""
    window = MainWindow(tmp_path / "trips.db")
    window.resize(1000, 700)
    window.show()
    doc = window._store.create_document("Trips")
    window._reload_document_list()
    window._open_document(doc.id)

    sections = []
    for s in range(8):
        sections.append(f"### {s}. Section title {s}")
        sections.append(f"Paragraph {s} " + (f"word{s} " * 300))
    v1 = "\n\n".join(sections)
    window._editor.setPlainText(v1)
    window._autosave()
    window._editor.setPlainText(
        v1.replace("word5 word5", "changed5 altered5", 2))
    window._autosave()
    yield window
    window.close()


def _park(window, qapp, block_no, offset=9):
    """Place the cursor mid-document and settle the view there."""
    doc = window._editor.document()
    cursor = window._editor.textCursor()
    cursor.setPosition(doc.findBlockByNumber(block_no).position() + offset)
    window._editor.setTextCursor(cursor)
    window._editor.centerCursor()
    _pump(qapp, 300)
    bar = window._editor.verticalScrollBar()
    return window._editor.textCursor().position(), bar.value()


def _round_trip(window, qapp, back_steps=1):
    """Real buttons: back_steps clicks of ◀, then Newest."""
    for _ in range(back_steps):
        window._timeline._back_btn.click()
        _pump(qapp, 400)
    window._timeline._newest_btn.click()
    _pump(qapp, 700)
    bar = window._editor.verticalScrollBar()
    return window._editor.textCursor().position(), bar.value()


def test_single_step_round_trip_returns_exactly(essay_window, qapp):
    d_cur, d_bar = _park(essay_window, qapp, 10)
    r_cur, r_bar = _round_trip(essay_window, qapp)
    assert r_cur == d_cur
    assert abs(r_bar - d_bar) <= 2


def test_consecutive_trips_never_return_one_behind(essay_window, qapp):
    """Three trips from three different spots: every return must match
    ITS OWN departure — never the previous trip's (the exact failure
    pattern from Andrew's screenshots: 1,940 -> returned 1,761;
    1,761 -> returned 1,940)."""
    spots = [(10, 9), (4, 7), (12, 25)]
    departures = []
    for block, offset in spots:
        d = _park(essay_window, qapp, block, offset)
        departures.append(d)
        r_cur, r_bar = _round_trip(essay_window, qapp)
        assert (r_cur, r_bar) == pytest.approx(d, abs=2), (
            f"return {(r_cur, r_bar)} != departure {d}; "
            f"all departures so far: {departures}")
        # Especially: never the PREVIOUS trip's departure.
        if len(departures) >= 2:
            assert r_cur != departures[-2][0] or d[0] == departures[-2][0]


def test_multi_step_trip_still_returns_home(essay_window, qapp):
    """Back, back, back, then Newest: however deep the excursion, it
    ends where it began."""
    # A third revision so there is room to step twice.
    window = essay_window
    text = window._editor.toPlainText()
    window._editor.setPlainText(text.replace("word2 word2", "two too", 1))
    window._autosave()
    d_cur, d_bar = _park(window, qapp, 8)
    r_cur, r_bar = _round_trip(window, qapp, back_steps=2)
    assert r_cur == d_cur
    assert abs(r_bar - d_bar) <= 2


def test_top_of_document_does_not_creep(essay_window, qapp):
    """Andrew's report: cursor on line 1, step back, and line 2 sat at
    the top — the view had crept one line.  The anchor now restores the
    watched line to its exact on-screen height, so at the very top the
    first line stays the first line, both ways."""
    window = essay_window
    bar = window._editor.verticalScrollBar()
    cursor = window._editor.textCursor()
    cursor.setPosition(0)
    window._editor.setTextCursor(cursor)
    bar.setValue(0)
    _pump(qapp, 300)

    window._timeline._back_btn.click()
    _pump(qapp, 600)
    assert bar.value() == 0, "history view crept off the first line"

    window._timeline._newest_btn.click()
    _pump(qapp, 600)
    assert bar.value() == 0


def test_mid_document_step_holds_the_exact_scroll(essay_window, qapp):
    """Between nearly identical revisions the step should not move the
    view at all — not even the old half-line centering nudge."""
    window = essay_window
    bar = window._editor.verticalScrollBar()
    d_cur, d_bar = _park(window, qapp, 10)
    window._timeline._back_btn.click()
    _pump(qapp, 600)
    assert abs(bar.value() - d_bar) <= 1
    window._timeline._newest_btn.click()
    _pump(qapp, 600)
    assert bar.value() == d_bar


def test_photograph_does_not_cross_documents(essay_window, qapp):
    """Opening another document forgets the photograph — a Newest
    click there must not fly to the first essay's coordinates."""
    window = essay_window
    _park(window, qapp, 10)
    window._timeline._back_btn.click()
    _pump(qapp, 400)
    window._timeline._newest_btn.click()
    _pump(qapp, 500)

    other = window._store.create_document("Other")
    window._reload_document_list()
    window._open_document(other.id)
    assert getattr(window, "_live_departure", None) is None
