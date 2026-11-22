"""
find_bar.py — Find in Document (Ctrl+F): a slim in-editor find bar.

The library-wide Search dialog (Ctrl+Shift+F) answers "which documents
mention this?"; the find bar answers "where is the next occurrence RIGHT
HERE?".  It sits between the editor and the timeline, hidden until
Ctrl+F, and searches incrementally as you type.

Keys while the bar is open: Enter = next match, Shift+Enter = previous,
Esc = close and return to writing.  Search wraps around the document.

This file also holds ``CaptionFind``, the small "Find:" box that can sit
in the caption bar of each editor ("WV Editor", "WV Notes Editor") when
View ▸ Find Boxes is checked.  Each box searches its own pane, with the
same keys as the bar.

Both the bar and the boxes MARK every match in light blue while a
search is showing, and say how many there are ("12 found") beside the
box, so a writer searching for "spirit" sees at a glance every place
the word stands.  ``MatchMarker`` does the marking and the counting.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextDocument
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QWidget,
)

#: The colour laid behind every match: a light blue, with the words
#: themselves in black so they read clearly in light AND dark mode.
#: (The match the cursor is on keeps the ordinary, darker selection
#: colour, which is how it stands out from the rest.)
MATCH_BACKGROUND = "#9cc7ff"
MATCH_TEXT = "#000000"


class MatchMarker:
    """Marks every match of a search in one editor, and counts them.

    ``mark(query)`` colours every occurrence (upper or lower case
    alike, the same rule Find itself uses) and returns how many there
    are; ``clear()`` takes the colour away again.

    While a search is marked, the marker keeps watch on the text: a
    moment after the writer stops typing in the document it marks
    again, so new matches gain their colour and the count stays true.
    ``on_count`` (if given) is called with the new count each time.
    """

    #: No more than this many matches are coloured (a long book and a
    #: common word could otherwise mean tens of thousands of marks and
    #: a sluggish editor).  The COUNT is always complete.
    MOST_MARKS = 3000

    def __init__(self, editor: QPlainTextEdit, on_count=None):
        self._editor = editor
        self._on_count = on_count
        self._query = ""
        # Re-mark a third of a second after the text last changed,
        # not on every keystroke.
        self._timer = QTimer(editor)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._mark_again)
        editor.textChanged.connect(self._on_editor_text_changed)

    def mark(self, query: str) -> int:
        """Colour every match of ``query``; return the number found."""
        self._query = query
        if not query:
            self._show([])
            return 0
        document = self._editor.document()
        style = QTextCharFormat()
        style.setBackground(QColor(MATCH_BACKGROUND))
        style.setForeground(QColor(MATCH_TEXT))

        marks = []
        count = 0
        # Walk the document from the top, one match at a time.
        cursor = document.find(query, 0)
        while not cursor.isNull():
            count += 1
            if count <= self.MOST_MARKS:
                mark = QTextEdit.ExtraSelection()
                mark.cursor = cursor
                mark.format = style
                marks.append(mark)
            if cursor.selectionEnd() == cursor.selectionStart():
                break                      # safety: never loop in place
            cursor = document.find(query, cursor)
        self._show(marks)
        return count

    def clear(self) -> None:
        """Take every mark away and stop watching the text."""
        self._query = ""
        self._timer.stop()
        self._show([])

    def _show(self, marks: list) -> None:
        # The document editor has a layer just for find marks, so they
        # sit peacefully with its other decorations; a plain editor
        # (the notes pane) has only its ordinary extra selections.
        setter = getattr(self._editor, "set_find_selections",
                         self._editor.setExtraSelections)
        setter(marks)

    def _on_editor_text_changed(self) -> None:
        if self._query:
            self._timer.start()            # (re)start the short wait

    def _mark_again(self) -> None:
        if self._query:
            count = self.mark(self._query)
            if self._on_count is not None:
                self._on_count(count)


def count_words(count: int) -> str:
    """The count as shown beside a Find box: "12 found", or nothing
    when there are no matches (the status then says "not found")."""
    return f"{count} found" if count else ""


class FindBar(QWidget):
    """Incremental find over the editor pane's current text."""

    def __init__(self, editor: QPlainTextEdit, parent=None):
        super().__init__(parent)
        self._editor = editor

        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText("Find in this document…")
        self._edit.textChanged.connect(self._on_text_changed)

        prev_btn = QPushButton("Previous", self)
        prev_btn.clicked.connect(self.find_previous)
        next_btn = QPushButton("Next", self)
        next_btn.clicked.connect(self.find_next)
        close_btn = QPushButton("✕", self)
        close_btn.setFixedWidth(28)
        close_btn.clicked.connect(self.close_bar)

        # How many matches there are ("12 found"), then the passing
        # remarks "wrapped" and "not found".
        self._count = QLabel("", self)
        self._status = QLabel("", self)
        self._marker = MatchMarker(
            editor, lambda n: self._count.setText(count_words(n)))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.addWidget(QLabel("Find:", self))
        layout.addWidget(self._edit, stretch=1)
        layout.addWidget(self._count)
        layout.addWidget(prev_btn)
        layout.addWidget(next_btn)
        layout.addWidget(self._status)
        layout.addWidget(close_btn)

        self.hide()

    # -- opening / closing --------------------------------------------------

    def open_bar(self) -> None:
        """Show the bar; a selected word in the editor becomes the query."""
        selection = self._editor.textCursor().selectedText()
        if selection and " " not in selection:
            self._edit.setText(selection)
        self.show()
        self._edit.setFocus()
        self._edit.selectAll()
        # Bring the marks back for whatever is in the box.
        self._count.setText(count_words(self._marker.mark(self._edit.text())))

    def close_bar(self) -> None:
        self.hide()
        self._marker.clear()               # the marks go with the bar
        self._editor.setFocus()

    # -- searching ----------------------------------------------------------

    def find_next(self) -> bool:
        return self._find(forward=True)

    def find_previous(self) -> bool:
        return self._find(forward=False)

    def _find(self, forward: bool, from_start: bool = False) -> bool:
        """One find step, wrapping around the ends of the document."""
        query = self._edit.text()
        if not query:
            self._status.setText("")
            return False
        flags = QTextDocument.FindFlag(0)
        if not forward:
            flags |= QTextDocument.FindFlag.FindBackward

        if from_start:  # incremental typing: search from the top
            cursor = self._editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self._editor.setTextCursor(cursor)

        if self._editor.find(query, flags):
            self._status.setText("")
            return True

        # Wrap: jump to the far end and try once more.
        cursor = self._editor.textCursor()
        cursor.movePosition(
            QTextCursor.MoveOperation.Start if forward
            else QTextCursor.MoveOperation.End
        )
        self._editor.setTextCursor(cursor)
        if self._editor.find(query, flags):
            self._status.setText("wrapped")
            return True
        self._status.setText("not found")
        return False

    # -- keys ---------------------------------------------------------------

    def _on_text_changed(self, text: str) -> None:
        """Incremental search: every keystroke marks all the matches,
        counts them, and re-searches from the top."""
        self._count.setText(count_words(self._marker.mark(text)))
        self._find(forward=True, from_start=True)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if event.key() == Qt.Key.Key_Escape:
            self.close_bar()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.find_previous()
            else:
                self.find_next()
        else:
            super().keyPressEvent(event)


class CaptionFind(QWidget):
    """A compact "Find: [........]" for an editor's caption bar.

    It searches the one pane it was given (the document editor or the
    notes editor), as you type.  Enter = next match, Shift+Enter =
    previous, Esc = back to writing.  The search wraps around the text,
    and a short word beside the box says "wrapped" or "not found".

    Shown and hidden as a whole by View ▸ Find Boxes; hidden to start.
    """

    #: How wide the typing box is, in pixels: room for a phrase without
    #: crowding a narrow window.
    BOX_WIDTH = 260

    def __init__(self, editor: QPlainTextEdit, parent=None):
        super().__init__(parent)
        self._editor = editor

        self._edit = QLineEdit(self)
        self._edit.setFixedWidth(self.BOX_WIDTH)
        self._edit.setClearButtonEnabled(True)     # the little x to empty it
        self._edit.setToolTip(
            "Find in this pane as you type. Enter: next match. "
            "Shift+Enter: previous. Esc: back to the text.")
        self._edit.textChanged.connect(self._on_text_changed)
        self._edit.installEventFilter(self)        # for Enter and Esc

        # Just after the box: how many matches ("12 found"), then the
        # passing remarks "wrapped" and "not found".
        self._count = QLabel("", self)
        self._status = QLabel("", self)
        self._marker = MatchMarker(
            editor, lambda n: self._count.setText(count_words(n)))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(QLabel("Find:", self))
        layout.addWidget(self._edit)
        layout.addWidget(self._count)
        layout.addWidget(self._status)

        self.hide()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """View ▸ Find Boxes unchecked: the marks leave with the box."""
        self._marker.clear()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """Shown again: mark whatever is still typed in the box."""
        self._count.setText(count_words(self._marker.mark(self._edit.text())))
        super().showEvent(event)

    # -- for the window -----------------------------------------------------

    def focus_box(self) -> None:
        """Put the typing cursor in the box, with its text selected."""
        self._edit.setFocus()
        self._edit.selectAll()

    # -- searching ----------------------------------------------------------

    def find_next(self) -> bool:
        return self._find(forward=True)

    def find_previous(self) -> bool:
        return self._find(forward=False)

    def _find(self, forward: bool, from_start: bool = False) -> bool:
        """One find step in this box's pane, wrapping at the ends.
        The same steps as FindBar._find, on this box's own editor."""
        query = self._edit.text()
        if not query:
            self._status.setText("")
            return False
        flags = QTextDocument.FindFlag(0)
        if not forward:
            flags |= QTextDocument.FindFlag.FindBackward

        if from_start:  # typing: always show the FIRST match in the pane
            cursor = self._editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self._editor.setTextCursor(cursor)

        if self._editor.find(query, flags):
            self._status.setText("")
            return True

        # Wrap: jump to the far end and try once more.
        cursor = self._editor.textCursor()
        cursor.movePosition(
            QTextCursor.MoveOperation.Start if forward
            else QTextCursor.MoveOperation.End
        )
        self._editor.setTextCursor(cursor)
        if self._editor.find(query, flags):
            self._status.setText("wrapped")
            return True
        self._status.setText("not found")
        return False

    # -- keys ---------------------------------------------------------------

    def _on_text_changed(self, text: str) -> None:
        """Incremental search: every keystroke marks all the matches,
        counts them, and re-searches from the top."""
        self._count.setText(count_words(self._marker.mark(text)))
        self._find(forward=True, from_start=True)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt naming)
        """Enter, Shift+Enter and Esc typed in the box."""
        from PyQt6.QtCore import QEvent

        if watched is self._edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._editor.setFocus()            # back to writing
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self.find_previous()
                else:
                    self.find_next()
                return True
        return super().eventFilter(watched, event)
