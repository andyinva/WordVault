"""
Tests for assembling lists in the editor: the bullet and numbered list
commands, Enter carrying a list on, numbers kept counting upward, and
the row of edit buttons in the caption bar that presses the Edit
commands.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # no display needed
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QTextCursor  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from wordvault.editor.editor_pane import EditorPane  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def pane(qapp):
    editor = EditorPane()
    editor.show()
    yield editor
    editor.close()


def select_lines(pane, first: int, last: int) -> None:
    """Select whole lines first..last (counting from 0)."""
    doc = pane.document()
    cursor = QTextCursor(doc.findBlockByNumber(first))
    end = doc.findBlockByNumber(last)
    cursor.setPosition(end.position() + len(end.text()),
                       QTextCursor.MoveMode.KeepAnchor)
    pane.setTextCursor(cursor)


def put_cursor(pane, line: int, column: int) -> None:
    cursor = QTextCursor(pane.document().findBlockByNumber(line))
    cursor.setPosition(cursor.position() + column)
    pane.setTextCursor(cursor)


def press_enter(pane) -> None:
    QTest.keyClick(pane, Qt.Key.Key_Return)


# ------------------------------------------------------ the commands --

def test_numbered_list_numbers_the_selected_lines(pane):
    pane.setPlainText("Passover\nPentecost\nTabernacles")
    select_lines(pane, 0, 2)
    pane.toggle_list("numbered")
    assert pane.toPlainText() == "1. Passover\n2. Pentecost\n3. Tabernacles"
    # The lines stay selected, so pressing again takes the numbers off.
    pane.toggle_list("numbered")
    assert pane.toPlainText() == "Passover\nPentecost\nTabernacles"


def test_bullet_list_marks_and_unmarks(pane):
    pane.setPlainText("Passover\nPentecost")
    select_lines(pane, 0, 1)
    pane.toggle_list("bullet")
    assert pane.toPlainText() == "- Passover\n- Pentecost"
    pane.toggle_list("bullet")
    assert pane.toPlainText() == "Passover\nPentecost"


def test_one_kind_of_list_switches_to_the_other(pane):
    pane.setPlainText("- Passover\n- Pentecost\n- Tabernacles")
    select_lines(pane, 0, 2)
    pane.toggle_list("numbered")          # bullets become numbers...
    assert pane.toPlainText() == "1. Passover\n2. Pentecost\n3. Tabernacles"
    pane.toggle_list("bullet")            # ...and numbers become bullets
    assert pane.toPlainText() == "- Passover\n- Pentecost\n- Tabernacles"


def test_blank_lines_between_paragraphs_are_not_numbered(pane):
    pane.setPlainText("First point.\n\nSecond point.")
    select_lines(pane, 0, 2)
    pane.toggle_list("numbered")
    assert pane.toPlainText() == "1. First point.\n\n2. Second point."


def test_on_an_empty_line_the_marker_is_typed_ready_for_an_item(pane):
    pane.setPlainText("Intro.\n")
    put_cursor(pane, 1, 0)
    pane.toggle_list("numbered")
    assert pane.toPlainText() == "Intro.\n1. "
    QTest.keyClicks(pane, "first")        # the cursor is after the marker
    assert pane.toPlainText() == "Intro.\n1. first"


def test_a_new_numbered_item_carries_on_from_the_one_above(pane):
    pane.setPlainText("1. one\n2. two\nthree")
    put_cursor(pane, 2, 2)
    pane.toggle_list("numbered")
    assert pane.toPlainText() == "1. one\n2. two\n3. three"
    # The cursor stayed on the same letter (after "th").
    assert pane.textCursor().positionInBlock() == len("3. th")


def test_the_whole_change_is_one_undo_step(pane):
    pane.setPlainText("a\nb\nc")
    select_lines(pane, 0, 2)
    pane.toggle_list("numbered")
    pane.undo()
    assert pane.toPlainText() == "a\nb\nc"


def test_nothing_happens_to_an_old_version(pane):
    pane.setPlainText("a\nb")
    pane.setReadOnly(True)
    select_lines(pane, 0, 1)
    pane.toggle_list("bullet")
    assert pane.toPlainText() == "a\nb"


# ----------------------------------------------------------- Enter --

def test_enter_at_the_end_starts_the_next_number(pane):
    pane.setPlainText("1. one")
    put_cursor(pane, 0, len("1. one"))
    press_enter(pane)
    QTest.keyClicks(pane, "two")
    assert pane.toPlainText() == "1. one\n2. two"


def test_enter_in_the_middle_of_a_list_recounts_the_items_below(pane):
    pane.setPlainText("1. one\n2. three\n3. four")
    put_cursor(pane, 0, len("1. one"))
    press_enter(pane)
    QTest.keyClicks(pane, "two")
    assert pane.toPlainText() == "1. one\n2. two\n3. three\n4. four"
    pane.undo()                           # the typed word
    pane.undo()                           # the new item AND the recount
    assert pane.toPlainText() == "1. one\n2. three\n3. four"


def test_enter_inside_an_item_splits_it_into_two_items(pane):
    pane.setPlainText("- bread and wine")
    put_cursor(pane, 0, len("- bread "))
    press_enter(pane)
    assert pane.toPlainText() == "- bread \n- and wine"


def test_enter_on_an_empty_item_ends_the_list(pane):
    pane.setPlainText("1. one\n2. ")
    put_cursor(pane, 1, len("2. "))
    press_enter(pane)
    assert pane.toPlainText() == "1. one\n"


def test_recount_stops_where_the_list_stops(pane):
    pane.setPlainText("1. one\n2. two\n\n1. another list")
    put_cursor(pane, 0, len("1. one"))
    press_enter(pane)
    assert pane.toPlainText() == "1. one\n2. \n3. two\n\n1. another list"


# ------------------------------------------------- the edit buttons --

@pytest.fixture()
def window(qapp, tmp_path):
    from wordvault.editor import MainWindow

    win = MainWindow(tmp_path / "lists.db")
    win.show()
    yield win
    win.close()


def test_edit_buttons_press_the_edit_commands(window):
    buttons = window._edit_tool_buttons
    assert list(buttons) == [
        "Undo", "Redo", "Bold", "Italic", "Heading 1", "Heading 2",
        "Heading 3", "Toggle Bullet List", "Toggle Numbered List",
        "Toggle Quote"]
    editor = window._editor
    editor.setPlainText("Passover\nPentecost")
    select_lines(editor, 0, 1)

    buttons["Toggle Numbered List"].click()
    assert editor.toPlainText() == "1. Passover\n2. Pentecost"
    buttons["Toggle Bullet List"].click()
    assert editor.toPlainText() == "- Passover\n- Pentecost"
    buttons["Undo"].click()
    assert editor.toPlainText() == "1. Passover\n2. Pentecost"
    buttons["Redo"].click()
    assert editor.toPlainText() == "- Passover\n- Pentecost"

    editor.setPlainText("spirit")
    put_cursor(editor, 0, 2)
    buttons["Bold"].click()
    assert editor.toPlainText() == "**spirit**"
    buttons["Heading 2"].click()
    assert editor.toPlainText().startswith("## ")

    # The tooltip names the keyboard shortcut for the same command.
    assert "Ctrl+Shift+N" in buttons["Toggle Numbered List"].toolTip()
    # A button never takes the typing cursor out of the text.
    assert buttons["Bold"].focusPolicy() == Qt.FocusPolicy.NoFocus


def test_edit_buttons_can_be_hidden_and_sit_after_the_find_box(window):
    QApplication.processEvents()
    assert not window._edit_buttons.isHidden()          # shown to start
    window._find_boxes_action.setChecked(True)
    QApplication.processEvents()
    find = window._caption_finds[0]
    bar = window._caption_bars[0]
    # (The buttons sit in a little "window" of their own in the bar.)
    assert bar._window.x() >= find.x() + find.width()

    window._edit_buttons_action.setChecked(False)
    assert window._edit_buttons.isHidden()
    assert window._settings.value("edit_buttons", type=bool) is False
    window._edit_buttons_action.setChecked(True)        # leave it as found
    window._find_boxes_action.setChecked(False)
    assert not window._edit_buttons.isHidden()


def test_edit_buttons_go_gray_while_viewing_an_old_version(window):
    window._set_edit_mode_visuals(live=False)
    assert not window._edit_buttons.isEnabled()
    window._set_edit_mode_visuals(live=True)
    assert window._edit_buttons.isEnabled()


def test_a_narrow_window_keeps_the_finds_aligned_and_cuts_buttons(window):
    """Short of room, the caption bar must not squeeze its title (the
    two Find boxes then stopped lining up) and must not refuse to get
    narrow either: the Find box shrinks first, then buttons are cut
    off whole from the right."""
    window._find_boxes_action.setChecked(True)
    editor_bar = window._caption_bars[0]
    full = window._edit_buttons.sizeHint().width()

    window.resize(1500, 700)                  # plenty of room
    QApplication.processEvents()
    assert editor_bar._window.width() == full            # every button
    roomy = window._caption_finds[0]._edit.width()

    window.resize(window.minimumSizeHint().width(), 700)  # as narrow as allowed
    QApplication.processEvents()
    editor_find, notes_find = window._caption_finds
    assert editor_find.x() == notes_find.x()             # still aligned
    assert editor_find._edit.width() < roomy             # Find gave way
    assert editor_bar._window.width() < full             # buttons cut...
    # ...but each button kept its own size (none squashed).
    button = window._edit_tool_buttons["Bold"]
    assert button.width() == button.minimumWidth() == button.maximumWidth()

    window._find_boxes_action.setChecked(False)          # leave it as found
