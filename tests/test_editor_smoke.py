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


def test_history_mode_is_marked_and_copyable(window_with_history):
    """The time-travel trap (Aug 2026): clicking into an old version
    showed no cursor and no way back.  Now history mode must (a) keep
    the text selectable WITH a keyboard cursor so copying works, (b)
    wear the amber 'history' border, and (c) light up the timeline's
    Newest/Restore buttons — the road back to editing."""
    from PyQt6.QtCore import Qt

    window, doc = window_with_history
    window._timeline._slider.setValue(0)          # into the past

    flags = window._editor.textInteractionFlags()
    assert flags & Qt.TextInteractionFlag.TextSelectableByMouse
    assert flags & Qt.TextInteractionFlag.TextSelectableByKeyboard
    assert window._editor.property("mode") == "history"
    assert window._timeline._newest_btn.styleSheet() != ""
    assert window._timeline._restore_btn.styleSheet() != ""

    window._timeline.go_newest()                  # and back to now
    assert window._editor.property("mode") == "live"
    assert not window._editor.isReadOnly()
    assert window._timeline._newest_btn.styleSheet() == ""
    flags = window._editor.textInteractionFlags()
    assert flags & Qt.TextInteractionFlag.TextEditable


def test_history_stepping_follows_the_growing_end(qapp, tmp_path):
    """The view rule for time travel (Aug 2026): stepping into history
    jumps to the END of the document — the cusp where essays grow, so
    the changes show as you step.  But once the reader deliberately
    scrolls elsewhere, further steps HOLD that place; and sitting at
    the end keeps following the end."""
    window = MainWindow(tmp_path / "scroll.db")
    doc = window._store.create_document("Long")
    lines = "\n".join(f"line {i}" for i in range(400))
    window._store.save_revision(doc.id, lines + "\nrev one\n")
    window._store.save_revision(doc.id, lines + "\nrev two\n")
    window._store.save_revision(doc.id, lines + "\nrev three\n")
    window._reload_document_list()
    window._open_document(doc.id)
    window.resize(600, 400)

    bar = window._editor.verticalScrollBar()
    if bar.maximum() == 0:
        window.close()
        pytest.skip("offscreen viewport shows the whole document")
    middle = bar.maximum() // 2
    bar.setValue(middle)

    # The restore lands on a zero-delay timer (the fresh text has no
    # layout yet) — give the event loop a turn after each step, as a
    # running app would.
    window._timeline._slider.setValue(1)          # live -> history: END
    qapp.processEvents()
    bar = window._editor.verticalScrollBar()
    assert bar.value() == bar.maximum()

    bar.setValue(middle)                          # reader picks a passage
    window._timeline._slider.setValue(0)          # step again: place HELD
    qapp.processEvents()
    assert abs(window._editor.verticalScrollBar().value() - middle) <= 2

    bar = window._editor.verticalScrollBar()
    bar.setValue(bar.maximum())                   # back to the end...
    window._timeline._slider.setValue(1)          # ...stays at the end
    qapp.processEvents()
    bar = window._editor.verticalScrollBar()
    assert bar.value() == bar.maximum()
    window.close()


def test_timeline_arrow_buttons_step(window_with_history):
    window, doc = window_with_history
    assert window._is_live
    window._timeline._back_btn.click()
    assert not window._is_live                    # stepped into the past
    assert window._editor.toPlainText() == "state 1\n"
    window._timeline._fwd_btn.click()
    assert window._is_live                        # and back to newest
    assert window._editor.toPlainText() == "state 2\n"


def test_note_anchoring_and_jump_back(qapp, tmp_path):
    """Notes anchored to the text (Aug 2026): the first keystroke of a
    note stamps it with the editor's cursor line and a snippet, and
    the stamp jumps the editor back to that line."""
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent, QTextCursor

    window = MainWindow(tmp_path / "anchor.db")
    doc = window._store.create_document("Anchored")
    window._store.save_revision(
        doc.id, "first line here\nsecond line words\nthird line text\n")
    window._reload_document_list()
    window._open_document(doc.id)

    # Park the editor's cursor on line 2, then type into the notes.
    block = window._editor.document().findBlockByNumber(1)
    window._editor.setTextCursor(QTextCursor(block))
    press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A,
                      Qt.KeyboardModifier.NoModifier, "a")
    QApplication.sendEvent(window._notes, press)

    note = window._notes.toPlainText()
    assert note.startswith("▸ line 2 (second line words): ")
    assert note.endswith("a")                  # the typed letter followed

    # A second keystroke on the SAME line must not stamp again.
    QApplication.sendEvent(window._notes, press)
    assert window._notes.toPlainText().count("▸") == 1

    # The jump: a stamped line moves the editor cursor to its line.
    window._editor.setTextCursor(
        QTextCursor(window._editor.document().firstBlock()))
    assert window._jump_to_note_anchor("▸ line 3 (third): my note")
    assert window._editor.textCursor().blockNumber() == 2
    assert not window._jump_to_note_anchor("an ordinary note line")
    window.close()


def test_window_title_carries_version_and_tagline(window_with_history):
    from wordvault import RELEASE_DATE, TAGLINE, __version__

    window, _doc = window_with_history
    title = window.windowTitle()
    assert __version__ in title and RELEASE_DATE in title
    assert TAGLINE in title


def test_title_header_shows_draft_number_and_date(window_with_history):
    window, doc = window_with_history
    text = window._title_label.text()
    assert "draft 3 of 3" in text              # live: the newest state
    window._timeline._slider.setValue(0)       # oldest draft on screen
    assert "draft 1 of 3" in window._title_label.text()
    window._timeline.go_newest()
    assert "draft 3 of 3" in window._title_label.text()


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


def test_close_document_resets_editor(window_with_sections):
    window, doc = window_with_sections
    assert window._current_doc is not None
    window._on_close_document()
    assert window._current_doc is None
    assert not window._editor.isEnabled()
    # Closing again is a harmless no-op.
    window._on_close_document()


def test_line_number_toggle(window_with_sections):
    # NOTE: MainWindow loads the REAL user's persisted QSettings, so the
    # gutter may start on or off — assert the toggle from either state,
    # and restore the user's preference afterwards.
    window, doc = window_with_sections
    initial = window._line_numbers_action.isChecked()
    try:
        window._line_numbers_action.setChecked(True)
        assert window._editor.line_numbers_visible()
        assert window._editor.line_number_width() > 0
        window._line_numbers_action.setChecked(False)
        assert not window._editor.line_numbers_visible()
        assert window._editor.line_number_width() == 0
    finally:
        window._line_numbers_action.setChecked(initial)


def test_library_info_panel_populates(window_with_sections):
    window, doc = window_with_sections
    panel = window._library_panel
    assert panel._documents.text() == "1"
    assert panel._name.text().endswith(".db")
    assert panel._location.text()          # the path line edit is filled
    # A new revision bumps the counts on save.
    before = int(panel._revisions.text().replace(",", ""))
    window._editor.setPlainText(DOC_TEXT + "more\n")
    window._autosave()
    assert int(panel._revisions.text().replace(",", "")) == before + 1


def test_recent_menu_lists_opened_documents(window_with_sections):
    window, doc = window_with_sections
    saved = window._settings.value("recent_docs", [])  # the user's real list
    try:
        window._settings.setValue("recent_docs", [])   # isolate the test
        window._open_document(doc.id)
        window._rebuild_recent_menu()
        titles = [a.text() for a in window._recent_menu.actions()]
        assert "Sections" in titles
    finally:
        window._settings.setValue("recent_docs", saved)


def test_title_header_follows_document(window_with_sections):
    window, doc = window_with_sections
    # The header opens with the title and now carries the draft
    # number and date after it (see the draft-header test).
    assert window._title_label.text().startswith("Sections")
    assert "draft" in window._title_label.text()
    window._on_close_document()
    assert window._title_label.text() == "No document open"


def test_notes_pane_saves_and_travels_per_document(window_with_sections):
    window, doc = window_with_sections
    window._notes.setPlainText("tighten the second section")
    window._save_current_note()

    other = window._store.create_document("Other Doc")
    window._store.save_revision(other.id, "other text\n")
    window._open_document(other.id)                # switch saves + loads
    assert window._notes.toPlainText() == ""       # fresh doc: empty note

    window._notes.setPlainText("note on the other doc")
    window._open_document(doc.id)                  # switching back saves it
    assert window._notes.toPlainText() == "tighten the second section"
    assert window._store.get_note(other.id) == "note on the other doc"


def test_notes_editing_never_creates_revisions(window_with_sections):
    window, doc = window_with_sections
    before = len(window._store.list_revisions(doc.id))
    window._notes.setPlainText("just thinking out loud")
    window._save_current_note()
    assert len(window._store.list_revisions(doc.id)) == before


def test_dock_toggle_actions_exist(window_with_sections):
    window, doc = window_with_sections
    # The author can hide the Library list and the Library Info panels.
    assert window._library_list_dock.toggleViewAction() is not None
    window._library_list_dock.close()
    assert not window._library_list_dock.isVisible()
    window._library_list_dock.toggleViewAction().trigger()


def test_window_state_persists_across_sessions(qapp, tmp_path):
    # Close with the Library list hidden and a document open; a new
    # session must come back the same way.  The user's REAL layout keys
    # are snapshotted and restored — tests must not rearrange their app.
    from PyQt6.QtCore import QSettings
    settings = QSettings("WordVault", "WordVault")
    saved = {k: settings.value(k)
             for k in ("win_geometry", "win_state", "split_state")}
    db = tmp_path / "persist.db"
    try:
        window1 = MainWindow(db)
        doc = window1._store.create_document("Resume Me")
        window1._store.save_revision(doc.id, "where I left off\n")
        window1._reload_document_list()
        window1._open_document(doc.id)
        window1._library_list_dock.hide()
        window1.close()                          # closeEvent saves state

        window2 = MainWindow(db)
        assert window2._library_list_dock.isHidden()
        assert window2._current_doc is not None
        assert window2._current_doc.title == "Resume Me"
        assert window2._title_label.text().startswith("Resume Me")
        window2._library_list_dock.show()        # tidy up for later tests
        window2.close()
    finally:
        for key, value in saved.items():
            if value is None:
                settings.remove(key)
            else:
                settings.setValue(key, value)
        settings.remove(f"last_doc:{db}")


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
