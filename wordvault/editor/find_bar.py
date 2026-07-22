"""
find_bar.py — Find in Document (Ctrl+F): a slim in-editor find bar.

The library-wide Search dialog (Ctrl+Shift+F) answers "which documents
mention this?"; the find bar answers "where is the next occurrence RIGHT
HERE?".  It sits between the editor and the timeline, hidden until
Ctrl+F, and searches incrementally as you type.

Keys while the bar is open: Enter = next match, Shift+Enter = previous,
Esc = close and return to writing.  Search wraps around the document.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor, QTextDocument
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)


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

        self._status = QLabel("", self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.addWidget(QLabel("Find:", self))
        layout.addWidget(self._edit, stretch=1)
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

    def close_bar(self) -> None:
        self.hide()
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

    def _on_text_changed(self, _text: str) -> None:
        """Incremental search: every keystroke re-searches from the top."""
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
