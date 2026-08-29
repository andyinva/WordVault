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


# -- disabled keys (Settings ▸ Disabled keys) --------------------------------

def test_disabled_page_keys_are_swallowed(pane):
    """Andrew's keyboard: Pg Up / Pg Dn sit where stray fingers land —
    silenced, a press moves neither cursor nor view."""
    pane.set_disabled_keys({Qt.Key.Key_PageUp, Qt.Key.Key_PageDown})
    pane.setPlainText("\n".join(f"line {i}" for i in range(200)))
    cursor = pane.textCursor()
    cursor.setPosition(0)
    pane.setTextCursor(cursor)
    QTest.keyClick(pane, Qt.Key.Key_PageDown)
    assert pane.textCursor().position() == 0
    assert pane.verticalScrollBar().value() == 0
    # Other keys still work.
    QTest.keyClick(pane, Qt.Key.Key_Down)
    assert pane.textCursor().blockNumber() == 1


def test_enabled_keys_work_again_when_cleared(pane):
    pane.set_disabled_keys({Qt.Key.Key_PageDown})
    pane.setPlainText("\n".join(f"line {i}" for i in range(200)))
    cursor = pane.textCursor()
    cursor.setPosition(0)
    pane.setTextCursor(cursor)
    pane.set_disabled_keys(set())
    QTest.keyClick(pane, Qt.Key.Key_PageDown)
    assert pane.textCursor().position() > 0


"""-- current-line light (Settings) ----------------------------------------"""


def _lights(pane):
    from PyQt6.QtGui import QTextFormat

    return [s for s in pane.extraSelections()
            if s.format.hasProperty(
                QTextFormat.Property.FullWidthSelection)]


def test_line_light_follows_the_cursor(pane):
    pane.set_line_light(True)
    pane.setPlainText("first\nsecond\nthird")
    cursor = pane.textCursor()
    cursor.setPosition(pane.document().findBlockByNumber(1).position())
    pane.setTextCursor(cursor)
    lights = _lights(pane)
    assert len(lights) == 1
    assert lights[0].cursor.blockNumber() == 1
    # And it moves with the cursor.
    QTest.keyClick(pane, Qt.Key.Key_Down)
    assert _lights(pane)[0].cursor.blockNumber() == 2


def test_line_light_rides_under_other_decorations(pane):
    """Age colors, karaoke, and the wash all pass through
    setExtraSelections — the light must join them, underneath, without
    losing them."""
    from PyQt6.QtGui import QColor, QTextCharFormat
    from PyQt6.QtWidgets import QTextEdit

    pane.set_line_light(True)
    pane.setPlainText("one line")
    other = QTextEdit.ExtraSelection()
    other.cursor = pane.textCursor()
    fmt = QTextCharFormat()
    fmt.setForeground(QColor("red"))
    other.format = fmt
    pane.setExtraSelections([other])
    selections = pane.extraSelections()
    assert len(selections) == 2           # the light + the other
    # The light is FIRST (painted underneath).
    from PyQt6.QtGui import QTextFormat
    assert selections[0].format.hasProperty(
        QTextFormat.Property.FullWidthSelection)


def test_line_light_off_leaves_no_trace(pane):
    pane.set_line_light(False)
    pane.setPlainText("plain")
    pane.setExtraSelections([])
    assert pane.extraSelections() == []


def test_line_light_round_trips_through_the_dialog(qapp):
    from wordvault.editor.settings_dialog import SettingsDialog

    dialog = SettingsDialog(encrypted=False, idle_seconds=3,
                            font_size=12, line_light=False)
    assert dialog.line_light is False
    dialog._line_light_box.setChecked(True)
    assert dialog.line_light is True


def test_disabled_keys_round_trip_through_the_dialog(qapp):
    from wordvault.editor.settings_dialog import SettingsDialog

    dialog = SettingsDialog(encrypted=False, idle_seconds=3,
                            font_size=12, disabled_keys=("pgup", "pgdn"))
    assert set(dialog.disabled_keys) == {"pgup", "pgdn"}
    dialog._key_boxes["pgdn"].setChecked(False)
    dialog._key_boxes["insert"].setChecked(True)
    assert set(dialog.disabled_keys) == {"pgup", "insert"}


# -- paste funnel (provenance comments) --------------------------------------

def test_sizable_paste_announces_itself(pane, qapp):
    from PyQt6.QtCore import QMimeData

    heard = []
    pane.text_pasted.connect(heard.append)
    mime = QMimeData()
    text = "word " * 15                    # well past the threshold
    mime.setText(text)
    pane.insertFromMimeData(mime)
    assert heard == [text]
    assert "word word" in pane.toPlainText()


def test_tiny_paste_stays_quiet(pane, qapp):
    from PyQt6.QtCore import QMimeData

    heard = []
    pane.text_pasted.connect(heard.append)
    mime = QMimeData()
    mime.setText("just three words")
    pane.insertFromMimeData(mime)
    assert heard == []
    assert "just three words" in pane.toPlainText()
