"""
Tests for the Enter-key setting (paragraph return): in the vault a
paragraph is a line and a blank line makes the next one, so Enter can
add the blank line itself — one keystroke, ready for the next
paragraph.  Shift+Enter is always a plain single return; lists keep
their smart continuation; the plain-return mode restores the old
behavior.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from wordvault.editor.editor_pane import EditorPane  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def pane(qapp):
    editor = EditorPane()
    editor.show()
    yield editor
    editor.close()


def _type_enter(editor, shift=False):
    modifier = (Qt.KeyboardModifier.ShiftModifier if shift
                else Qt.KeyboardModifier.NoModifier)
    QTest.keyClick(editor, Qt.Key.Key_Return, modifier)


def test_enter_starts_a_new_paragraph(pane):
    pane.setPlainText("First paragraph.")
    pane.moveCursor(pane.textCursor().MoveOperation.End)
    _type_enter(pane)
    QTest.keyClicks(pane, "Second.")
    assert pane.toPlainText() == "First paragraph.\n\nSecond."


def test_shift_enter_is_a_plain_single_return(pane):
    pane.setPlainText("One line.")
    pane.moveCursor(pane.textCursor().MoveOperation.End)
    _type_enter(pane, shift=True)
    QTest.keyClicks(pane, "Next line.")
    assert pane.toPlainText() == "One line.\nNext line."
    # And it is a real newline, never Qt's invisible line separator.
    assert " " not in pane.toPlainText()


def test_enter_on_an_empty_line_adds_only_one(pane):
    """Spacing, not starting a paragraph: no runaway blank stacks."""
    pane.setPlainText("Text.\n")
    pane.moveCursor(pane.textCursor().MoveOperation.End)
    _type_enter(pane)
    assert pane.toPlainText() == "Text.\n\n"


def test_lists_keep_their_smart_continuation(pane):
    pane.setPlainText("- first item")
    pane.moveCursor(pane.textCursor().MoveOperation.End)
    _type_enter(pane)
    QTest.keyClicks(pane, "second item")
    assert pane.toPlainText() == "- first item\n- second item"


def test_plain_mode_restores_the_old_behavior(pane):
    pane.set_paragraph_return(False)
    pane.setPlainText("First.")
    pane.moveCursor(pane.textCursor().MoveOperation.End)
    _type_enter(pane)
    QTest.keyClicks(pane, "Second.")
    assert pane.toPlainText() == "First.\nSecond."


def test_setting_round_trips_through_the_dialog(qapp):
    from wordvault.editor.settings_dialog import SettingsDialog

    dialog = SettingsDialog(encrypted=False, idle_seconds=3,
                            font_size=12, paragraph_return=False)
    assert dialog.paragraph_return is False
    dialog._enter_combo.setCurrentIndex(0)
    assert dialog.paragraph_return is True
