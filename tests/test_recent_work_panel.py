"""
Tests for the Recent Work panel (below the Outline): the desk with the
works in progress on it — each recently opened document with its age,
size, last-month growth, and writing hours; a click opens it.
"""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from wordvault.editor import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def window(qapp, tmp_path):
    w = MainWindow(tmp_path / "recent.db")
    w.show()
    yield w
    w.close()


def _make_doc(window, title, text):
    doc = window._store.create_document(title)
    window._reload_document_list()
    window._open_document(doc.id)
    window._editor.setPlainText(text)
    window._autosave()
    return doc


def test_panel_lists_recent_documents_with_stats(window):
    _make_doc(window, "The Day of Gods Wrath", "wrath words " * 250)
    _make_doc(window, "Second Essay", "second words " * 100)
    window._refresh_recent_work()

    panel = window._recent_work
    assert panel.count() == 2
    # Most recently opened first — the desk's top paper.
    top = panel.item(0).text()
    assert top.startswith("Second Essay")
    assert "200w" in top                  # its size…
    assert "today" in top                 # …its age…
    assert "w/30d" in top                 # …its month's growth…
    assert "h" in top                     # …and the hours.
    below = panel.item(1).text()
    assert below.startswith("The Day of Gods Wrath")
    assert "500w" in below
    # Everything is younger than a month, so the month gained it all.
    assert "+500w/30d" in below


def test_click_opens_the_document(window):
    first = _make_doc(window, "One", "alpha " * 50)
    _make_doc(window, "Two", "beta " * 50)
    window._refresh_recent_work()
    panel = window._recent_work
    # Find One's row (Two, opened last, sits on top) and click it.
    row = next(i for i in range(panel.count())
               if panel.item(i).text().startswith("One"))
    window._on_recent_work_clicked(panel.item(row))
    assert window._current_doc.id == first.id


def test_settings_limit_caps_the_desk(window):
    for i in range(6):
        _make_doc(window, f"Essay {i}", "words here " * 30)
    window._settings.setValue("recent_panel_count", 4)
    window._refresh_recent_work()
    assert window._recent_work.count() == 4


def test_view_menu_can_hide_the_desk(window):
    action = window._recent_work_dock.toggleViewAction()
    assert action.isChecked()             # visible by default
    action.trigger()
    assert not window._recent_work_dock.isVisible()
    action.trigger()
    assert window._recent_work_dock.isVisible()


def test_viewing_without_editing_does_not_reorder_the_desk(window):
    """Andrew's distinction: File > Recent remembers what was OPENED;
    the desk holds what was EDITED.  Reopening an old essay to read it
    must not lift it above the one actually being worked on."""
    older = _make_doc(window, "Older Essay", "old words " * 60)
    _make_doc(window, "Current Work", "new words " * 60)
    # Reopen the older one — a look, not an edit.
    window._open_document(older.id)
    window._refresh_recent_work()
    assert window._recent_work.item(0).text().startswith("Current Work")
    assert window._recent_work.item(1).text().startswith("Older Essay")


def test_imported_documents_do_not_flood_the_desk(window):
    """A bulk import saves revisions for thousands of documents in an
    hour — none of that is the writer's hand, and none of it belongs
    on the desk."""
    _make_doc(window, "Hand Written", "typed words " * 40)
    imported = window._store.create_document("Imported Book")
    window._store.save_revision(imported.id, "imported text " * 100,
                                origin="ingest")
    window._refresh_recent_work()
    titles = [window._recent_work.item(i).text().split("\n")[0]
              for i in range(window._recent_work.count())]
    assert "Hand Written" in titles
    assert "Imported Book" not in titles
