"""
Offscreen smoke test for the stage 2 editor.

Runs the real MainWindow against a temporary database using Qt's
"offscreen" platform plugin, so it works on CI machines and sandboxes
with no display.  Skipped automatically when PyQt6 is not installed
(the storage layer must never require it).
"""

import os

import pytest

# Must be set before Qt is imported anywhere in the process.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)

from PyQt6.QtWidgets import QApplication  # noqa: E402

from wordvault import DocumentStore  # noqa: E402
from wordvault.editor import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    """One QApplication for the whole test module (Qt allows only one)."""
    app = QApplication.instance() or QApplication([])
    yield app


def test_editor_saves_revisions(qapp, tmp_path):
    db = tmp_path / "smoke.db"
    window = MainWindow(db)

    # Create a document through the store (bypassing the title dialog,
    # which would block a headless test), then open it as the UI would.
    doc = window._store.create_document("Smoke Test Essay")
    window._reload_document_list()
    window._open_document(doc.id)

    # Simulate the author typing, then the pause-save firing.
    window._editor.setPlainText("In the beginning was the Word.")
    window._autosave()

    # And an edit followed by another save.
    window._editor.setPlainText(
        "In the beginning was the Word, and the Word was with God."
    )
    window._autosave()

    # Saving identical text must not create a third revision.
    window._autosave()

    revs = window._store.list_revisions(doc.id)
    assert len(revs) == 2
    assert window._store.current_text(doc.id).endswith("with God.")

    # closeEvent path: window closes cleanly and the data survives reopen.
    window.close()
    with DocumentStore(db) as store:
        assert store.current_text(doc.id).endswith("with God.")


def test_loading_a_document_is_not_an_edit(qapp, tmp_path):
    window = MainWindow(tmp_path / "quiet.db")
    doc = window._store.create_document("Quiet Load")
    window._store.save_revision(doc.id, "existing text\n")

    window._open_document(doc.id)
    # Loading used set_text_quietly, so no pause timer should be pending;
    # an immediate autosave must find nothing new to record.
    window._autosave()
    assert len(window._store.list_revisions(doc.id)) == 1
    window.close()


# -- stage 3: time travel ----------------------------------------------------

@pytest.fixture()
def window_with_history(qapp, tmp_path):
    """A window on a document with three known states, open and live."""
    window = MainWindow(tmp_path / "travel.db")
    doc = window._store.create_document("Travel")
    for text in ["state 0\n", "state 1\n", "state 2\n"]:
        window._store.save_revision(doc.id, text)
    window._reload_document_list()
    window._open_document(doc.id)
    yield window, doc
    window.close()


def test_slider_walks_history_read_only(window_with_history):
    window, doc = window_with_history
    assert window._is_live
    assert window._editor.toPlainText() == "state 2\n"

    # Drag the slider back to the oldest revision (as Alt+Left would step).
    window._timeline._slider.setValue(0)
    assert window._editor.toPlainText() == "state 0\n"
    assert window._editor.isReadOnly()      # history is view-only
    assert not window._is_live

    # And forward again to the newest: editable once more.
    window._timeline.go_newest()
    assert window._editor.toPlainText() == "state 2\n"
    assert not window._editor.isReadOnly()
    assert window._is_live


def test_autosave_refuses_in_history_mode(window_with_history):
    # The guard rail: viewing old text must never be saved as new typing.
    window, doc = window_with_history
    window._timeline._slider.setValue(0)    # now viewing "state 0"
    window._autosave()                      # e.g. a stray Ctrl+S
    assert len(window._store.list_revisions(doc.id)) == 3  # unchanged


def test_leaving_live_mode_saves_pending_words(window_with_history):
    # Typing, then dragging the slider back: the unsaved words must be
    # captured as a revision BEFORE the view switches to history.
    window, doc = window_with_history
    window._editor.setPlainText("state 3, not yet auto-saved\n")
    window._timeline._slider.setValue(0)
    texts = [window._store.get_text(r.id)
             for r in window._store.list_revisions(doc.id)]
    assert "state 3, not yet auto-saved\n" in texts


def test_restore_appends_new_revision(window_with_history):
    window, doc = window_with_history
    window._timeline._slider.setValue(1)    # viewing "state 1"
    window._on_restore()

    history = window._store.list_revisions(doc.id)
    assert len(history) == 4                          # appended, not rewritten
    assert history[-1].origin == "restore"
    assert window._store.current_text(doc.id) == "state 1\n"
    assert window._is_live                            # back to editing
    assert not window._editor.isReadOnly()


def test_restore_does_nothing_when_live(window_with_history):
    window, doc = window_with_history
    window._on_restore()                    # Ctrl+R while at the newest
    assert len(window._store.list_revisions(doc.id)) == 3


# -- stage 7: focus mode, age colors, tags ----------------------------------

DOC_TEXT = "# One\nalpha\nbeta\n# Two\ngamma\n"


@pytest.fixture()
def window_with_sections(qapp, tmp_path):
    window = MainWindow(tmp_path / "st7.db")
    doc = window._store.create_document("Sections")
    window._store.save_revision(doc.id, DOC_TEXT)
    window._reload_document_list()
    window._open_document(doc.id)
    yield window, doc
    window.close()


def test_focus_mode_hides_other_sections(window_with_sections):
    window, doc = window_with_sections
    # Cursor into "alpha" (line 1), then hoist.
    editor = window._editor
    cursor = editor.textCursor()
    cursor.setPosition(editor.document().findBlockByNumber(1).position())
    editor.setTextCursor(cursor)
    window._on_focus_section()

    blocks = editor.document()
    visible = [blocks.findBlockByNumber(i).isVisible() for i in range(5)]
    assert visible == [True, True, True, False, False]   # only section One
    assert editor.is_focused()

    window._on_unfocus()
    assert all(blocks.findBlockByNumber(i).isVisible() for i in range(5))


def test_age_colors_toggle_no_crash_and_clear(window_with_sections):
    window, doc = window_with_sections
    # A second revision so there ARE two ages to tint.
    window._editor.setPlainText(DOC_TEXT + "delta added later\n")
    window._autosave()
    window._age_action.setChecked(True)
    assert len(window._editor.extraSelections()) >= 1   # old lines tinted
    window._age_action.setChecked(False)
    assert window._editor.extraSelections() == []


def test_outline_pane_follows_document(window_with_sections):
    window, doc = window_with_sections
    assert window._outline.topLevelItemCount() == 2     # One, Two


def test_tag_filter_narrows_library(window_with_sections):
    window, doc = window_with_sections
    other = window._store.create_document("Untagged")
    window._store.add_tag(doc.id, "genesis")
    window._reload_tag_filter()
    window._tag_filter.setCurrentText("genesis")

    titles = [window._doc_list.item(i).text()
              for i in range(window._doc_list.count())]
    assert titles == ["Sections"]
    window._tag_filter.setCurrentText("All documents")
    assert window._doc_list.count() == 2
