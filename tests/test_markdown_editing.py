"""
Offscreen tests for the Markdown editing commands and the highlighter.

The commands must produce exactly the plain text an author could have
typed by hand — these tests assert on the resulting text, which is the
only thing that gets stored.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QKeyEvent, QTextCursor  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from wordvault.editor.editor_pane import EditorPane  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def pane(qapp):
    return EditorPane()


def select(pane, start, end):
    cursor = pane.textCursor()
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    pane.setTextCursor(cursor)


def press_enter(pane):
    pane.keyPressEvent(QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier
    ))


# -- inline marks ------------------------------------------------------------

def test_bold_wrap_and_unwrap(pane):
    pane.setPlainText("hello world")
    select(pane, 6, 11)                       # "world"
    pane.toggle_inline_marks("**")
    assert pane.toPlainText() == "hello **world**"
    pane.toggle_inline_marks("**")            # selection kept: toggles back
    assert pane.toPlainText() == "hello world"


def test_italic_uses_word_under_cursor_without_selection(pane):
    pane.setPlainText("hello world")
    cursor = pane.textCursor()
    cursor.setPosition(8)                     # inside "world", no selection
    pane.setTextCursor(cursor)
    pane.toggle_inline_marks("*")
    assert pane.toPlainText() == "hello *world*"


def test_marks_hug_words_not_spaces(pane):
    pane.setPlainText("hello world here")
    select(pane, 5, 12)                       # " world " with spaces
    pane.toggle_inline_marks("**")
    assert pane.toPlainText() == "hello **world** here"


# -- headings ----------------------------------------------------------------

def test_heading_set_change_and_remove(pane):
    pane.setPlainText("The Coming Kingdom")
    pane.set_heading_level(1)
    assert pane.toPlainText() == "# The Coming Kingdom"
    pane.set_heading_level(2)                 # change level in place
    assert pane.toPlainText() == "## The Coming Kingdom"
    pane.set_heading_level(2)                 # same level again = toggle off
    assert pane.toPlainText() == "The Coming Kingdom"


# -- line prefixes -----------------------------------------------------------

def test_bullet_toggle_multiline(pane):
    pane.setPlainText("first\nsecond\nthird")
    select(pane, 0, len(pane.toPlainText()))
    pane.toggle_line_prefix("- ")
    assert pane.toPlainText() == "- first\n- second\n- third"
    select(pane, 0, len(pane.toPlainText()))
    pane.toggle_line_prefix("- ")             # all bulleted: removes
    assert pane.toPlainText() == "first\nsecond\nthird"


def test_quote_toggle_skips_blank_lines(pane):
    pane.setPlainText("one\n\ntwo")
    select(pane, 0, len(pane.toPlainText()))
    pane.toggle_line_prefix("> ")
    assert pane.toPlainText() == "> one\n\n> two"


# -- smart Enter -------------------------------------------------------------

def test_enter_continues_bullet_list(pane):
    pane.setPlainText("- first item")
    cursor = pane.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    pane.setTextCursor(cursor)
    press_enter(pane)
    assert pane.toPlainText() == "- first item\n- "


def test_enter_increments_numbered_list(pane):
    pane.setPlainText("3. third point")
    cursor = pane.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    pane.setTextCursor(cursor)
    press_enter(pane)
    assert pane.toPlainText() == "3. third point\n4. "


def test_enter_on_empty_item_ends_the_list(pane):
    pane.setPlainText("- item\n- ")
    cursor = pane.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    pane.setTextCursor(cursor)
    press_enter(pane)
    assert pane.toPlainText() == "- item\n"


# -- as-you-type autocorrect -------------------------------------------------

def press_key(pane, char):
    pane.keyPressEvent(QKeyEvent(
        QKeyEvent.Type.KeyPress, 0, Qt.KeyboardModifier.NoModifier, char
    ))


def test_autocorrect_repairs_learned_typo_on_space(pane):
    fired = []
    pane.autocorrected.connect(lambda t, c: fired.append((t, c)))
    pane.set_autocorrect_lookup({"machpela": "Machpelah"})
    pane.setPlainText("cave of machpela")
    cursor = pane.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    pane.setTextCursor(cursor)
    press_key(pane, " ")
    assert pane.toPlainText().startswith("cave of Machpelah")
    assert fired == [("machpela", "Machpelah")]


def test_autocorrect_mirrors_case_for_lowercase_fix(pane):
    pane.set_autocorrect_lookup({"becase": "because"})
    pane.setPlainText("Becase")
    cursor = pane.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    pane.setTextCursor(cursor)
    press_key(pane, " ")
    assert pane.toPlainText().startswith("Because")


def test_autocorrect_leaves_unknown_words_alone(pane):
    pane.set_autocorrect_lookup({"becase": "because"})
    pane.setPlainText("beluga")
    cursor = pane.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    pane.setTextCursor(cursor)
    press_key(pane, " ")
    assert pane.toPlainText().startswith("beluga")


def test_autocorrect_disabled_when_lookup_none(pane):
    pane.set_autocorrect_lookup(None)
    pane.setPlainText("becase")
    cursor = pane.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    pane.setTextCursor(cursor)
    press_key(pane, " ")
    assert pane.toPlainText().startswith("becase")


def test_autocorrect_fires_before_smart_enter(pane):
    # Enter both fixes the word AND continues the list.
    pane.set_autocorrect_lookup({"becase": "because"})
    pane.setPlainText("- becase")
    cursor = pane.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    pane.setTextCursor(cursor)
    press_enter(pane)
    assert pane.toPlainText() == "- because\n- "


# -- highlighter -------------------------------------------------------------

def test_highlighter_styles_without_changing_text(pane):
    text = "# Title\nplain **bold** and *italic*\n> a quote"
    pane.setPlainText(text)
    pane.markdown_highlighter.rehighlight()
    assert pane.toPlainText() == text         # display-only, text untouched

    # The heading line carries an enlarged-font format range.
    layout = pane.document().findBlockByNumber(0).layout()
    sizes = [r.format.fontPointSize() for r in layout.formats()
             if r.format.fontPointSize() > 0]
    assert sizes and max(sizes) > pane.font().pointSize()

    # The bold line carries a bold format range.
    layout = pane.document().findBlockByNumber(1).layout()
    assert any(r.format.fontWeight() >= 700 for r in layout.formats())
