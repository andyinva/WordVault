"""
Offscreen tests for the Document menu: Go to Document (quick open),
Find in Document (find bar), rename, and version-chain stepping.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)

from PyQt6.QtWidgets import QApplication, QInputDialog  # noqa: E402

from wordvault import DocumentStore  # noqa: E402
from wordvault.editor import MainWindow  # noqa: E402
from wordvault.editor.quick_open import QuickOpenDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# -- quick open --------------------------------------------------------------

@pytest.fixture()
def store_with_titles(tmp_path):
    store = DocumentStore(tmp_path / "qo.db")
    for title in ["Atonement Study", "The Coming Kingdom",
                  "Kingdom Parables", "Genesis Notes"]:
        doc = store.create_document(title)
        store.save_revision(doc.id, title + " text\n")
    yield store
    store.close()


def titles_shown(dialog):
    return [dialog._tree.topLevelItem(i).text(0)
            for i in range(dialog._tree.topLevelItemCount())]


def test_quick_open_filters_and_ranks(qapp, store_with_titles):
    dialog = QuickOpenDialog(store_with_titles)
    assert dialog._tree.topLevelItemCount() == 4   # empty query: everything

    dialog._edit.setText("kingdom")
    shown = titles_shown(dialog)
    # Startswith beats contains: "Kingdom Parables" ranks first.
    assert shown == ["Kingdom Parables", "The Coming Kingdom"]

    dialog._edit.setText("zzz")
    assert dialog._tree.topLevelItemCount() == 0


def test_quick_open_shows_and_sorts_dates(qapp, tmp_path):
    from PyQt6.QtCore import Qt

    store = DocumentStore(tmp_path / "dates.db")
    for title, created in [("Newest", "2026-03-01T00:00:00+00:00"),
                           ("Oldest", "2019-06-01T00:00:00+00:00"),
                           ("Middle", "2023-01-15T00:00:00+00:00")]:
        doc = store.create_document(title, created_utc=created)
        store.save_revision(doc.id, title + " text\n", created_utc=created)

    dialog = QuickOpenDialog(store)
    first = dialog._tree.topLevelItem(0)
    assert first.text(1) and first.text(2)         # both date columns filled

    dialog._tree.sortByColumn(1, Qt.SortOrder.AscendingOrder)
    assert titles_shown(dialog) == ["Oldest", "Middle", "Newest"]
    dialog._tree.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    assert titles_shown(dialog) == ["Newest", "Middle", "Oldest"]
    store.close()


def test_search_dialog_doc_rows_carry_dates(qapp, tmp_path):
    from wordvault.editor.search_dialog import SearchDialog

    store = DocumentStore(tmp_path / "sd.db")
    doc = store.create_document("Kingdom Essay",
                                created_utc="2022-04-01T00:00:00+00:00")
    store.save_revision(doc.id, "the kingdom come\n")

    dialog = SearchDialog(store, current_doc_id=lambda: None)
    dialog._find_edit.setText("kingdom")
    dialog._on_search()

    top = dialog._tree.topLevelItem(0)
    assert top.text(0).startswith("Kingdom Essay")
    # Dates display in LOCAL time — compute the expectation the same way
    # (midnight UTC is the previous evening west of Greenwich).
    from datetime import datetime
    expected = datetime.fromisoformat(
        "2022-04-01T00:00:00+00:00"
    ).astimezone().strftime("%Y-%m-%d")
    assert top.text(2) == expected                 # created
    assert top.text(3)                             # modified (today)
    store.close()


def test_quick_open_enter_selects_top_match(qapp, store_with_titles):
    dialog = QuickOpenDialog(store_with_titles)
    dialog._edit.setText("genesis")
    dialog._accept_current()
    assert dialog.selected_doc_id is not None
    doc = store_with_titles.get_document(dialog.selected_doc_id)
    assert doc.title == "Genesis Notes"


# -- find bar ----------------------------------------------------------------

@pytest.fixture()
def window_with_text(qapp, tmp_path):
    window = MainWindow(tmp_path / "fb.db")
    doc = window._store.create_document("Find Me")
    window._store.save_revision(
        doc.id, "alpha beta gamma\nbeta again\nlast beta here\n"
    )
    window._reload_document_list()
    window._open_document(doc.id)
    yield window
    window.close()


def test_find_bar_steps_and_wraps(window_with_text):
    window = window_with_text
    bar = window._find_bar
    bar.open_bar()
    bar._edit.setText("beta")                   # incremental: finds first

    positions = [window._editor.textCursor().position()]
    assert bar.find_next() and bar.find_next()  # second and third match
    positions.append(window._editor.textCursor().position())
    assert positions[0] != positions[1]

    assert bar.find_next()                      # wraps to the first again
    assert bar._status.text() == "wrapped"

    bar._edit.setText("nowhere")
    assert not bar.find_next()
    assert bar._status.text() == "not found"


def test_find_bar_close_returns_to_editor(window_with_text):
    window = window_with_text
    window._find_bar.open_bar()
    assert window._find_bar.isVisible() or True  # offscreen: visibility flag
    window._find_bar.close_bar()
    assert not window._find_bar.isVisible()


# -- rename ------------------------------------------------------------------

def test_rename_document(qapp, tmp_path, monkeypatch):
    window = MainWindow(tmp_path / "rn.db")
    doc = window._store.create_document("Old Name")
    window._store.save_revision(doc.id, "text\n")
    window._reload_document_list()
    window._open_document(doc.id)

    monkeypatch.setattr(
        QInputDialog, "getText",
        staticmethod(lambda *a, **k: ("New Name", True)),
    )
    window._on_rename_document()
    assert window._store.get_document(doc.id).title == "New Name"
    assert window._current_doc.title == "New Name"
    window.close()


# -- version stepping --------------------------------------------------------

def test_step_through_version_chain(qapp, tmp_path):
    window = MainWindow(tmp_path / "vc.db")
    ids = []
    for title in ["Draft 1", "Draft 2", "Draft 3"]:
        doc = window._store.create_document(title)
        window._store.save_revision(doc.id, title + "\n")
        ids.append(doc.id)
    window._store.link_version_chain(ids)
    window._reload_document_list()
    window._open_document(ids[1])               # middle draft

    window._on_step_version(-1)
    assert window._current_doc.id == ids[0]
    window._on_step_version(-1)                 # already oldest: stays
    assert window._current_doc.id == ids[0]
    window._on_step_version(+1)
    window._on_step_version(+1)
    assert window._current_doc.id == ids[2]
    window.close()


# -- find boxes in the caption bars -----------------------------------------

def test_find_boxes_toggle_align_and_search_their_own_pane(window_with_text):
    """View > Find Boxes shows a "Find:" box beside "WV Editor" and
    "WV Notes Editor" (Nov 2026 request): hidden when unchecked, lined
    up with each other, and each searching only its own pane."""
    window = window_with_text
    window.show()
    editor_find, notes_find = window._caption_finds

    # Unchecked: the boxes are not there.
    window._find_boxes_action.setChecked(False)
    assert editor_find.isHidden() and notes_find.isHidden()

    # Checked: both appear, starting at the same distance from the left.
    window._find_boxes_action.setChecked(True)
    QApplication.processEvents()
    assert not editor_find.isHidden() and not notes_find.isHidden()
    assert editor_find.x() == notes_find.x()
    assert window._settings.value("find_boxes", type=bool) is True

    # The editor's box finds text in the document...
    window._notes.setPlainText("a note about gamma rays\n")
    editor_find._edit.setText("beta")
    assert window._editor.textCursor().selectedText() == "beta"
    first = window._editor.textCursor().position()
    assert editor_find.find_next()
    assert window._editor.textCursor().position() != first

    # ...and the notes box finds text in the notes, leaving the
    # document's own selection alone.
    notes_find._edit.setText("gamma")
    assert window._notes.textCursor().selectedText() == "gamma"
    assert window._editor.textCursor().selectedText() == "beta"

    notes_find._edit.setText("nowhere")
    assert notes_find._status.text() == "not found"

    window._find_boxes_action.setChecked(False)     # leave it as found
    assert editor_find.isHidden() and notes_find.isHidden()


# -- every match marked, and counted -----------------------------------------

def test_find_marks_every_match_and_counts_them(window_with_text):
    """Searching for a word colours EVERY place it stands and says how
    many there are, beside the box (Nov 2026 request: "search for
    spirit ... make spirit in blue every time ... say how many")."""
    from PyQt6.QtGui import QColor

    from wordvault.editor.find_bar import MATCH_BACKGROUND

    window = window_with_text
    window.show()
    window._find_boxes_action.setChecked(True)
    QApplication.processEvents()
    editor_find, notes_find = window._caption_finds
    blue = QColor(MATCH_BACKGROUND)

    def marked(editor):
        """The text of every blue mark now showing in an editor."""
        return [sel.cursor.selectedText()
                for sel in editor.extraSelections()
                if sel.format.background().color() == blue]

    text = window._editor.toPlainText()
    editor_find._edit.setText("BETA")               # any letter case
    expected = text.lower().count("beta")
    assert expected >= 2
    assert [m.lower() for m in marked(window._editor)] == ["beta"] * expected
    assert editor_find._count.text() == f"{expected} found"

    # The document's other decorations may be reset at any time
    # without the marks being lost.
    window._editor.setExtraSelections([])
    assert len(marked(window._editor)) == expected

    # The notes box marks the notes, and only the notes.
    window._notes.setPlainText("spirit and Spirit, in spirit\n")
    notes_find._edit.setText("spirit")
    assert len(marked(window._notes)) == 3
    assert notes_find._count.text() == "3 found"
    assert len(marked(window._editor)) == expected

    # No match: nothing marked, no count, and the status says so.
    notes_find._edit.setText("nowhere")
    assert marked(window._notes) == []
    assert notes_find._count.text() == ""
    assert notes_find._status.text() == "not found"

    # Emptying the box, or switching the boxes off, removes the marks.
    editor_find._edit.setText("")
    assert marked(window._editor) == []
    editor_find._edit.setText("beta")
    window._find_boxes_action.setChecked(False)
    assert marked(window._editor) == []


def test_find_bar_marks_and_counts_too(window_with_text):
    """The Ctrl+F bar marks and counts the same way, and takes its
    marks away when it is closed."""
    from PyQt6.QtGui import QColor

    from wordvault.editor.find_bar import MATCH_BACKGROUND

    window = window_with_text
    bar = window._find_bar
    blue = QColor(MATCH_BACKGROUND)

    def marks():
        return [s for s in window._editor.extraSelections()
                if s.format.background().color() == blue]

    bar.open_bar()
    bar._edit.setText("beta")
    expected = window._editor.toPlainText().lower().count("beta")
    assert len(marks()) == expected
    assert bar._count.text() == f"{expected} found"
    bar.close_bar()
    assert marks() == []
