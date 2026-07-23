"""
info_panel.py — the document information panel (stage 7).

A dockable panel answering "where am I, in what?" (DESIGN.md section 8):
document identity and dates, position in its version chain, revision and
word counts, the cursor's place in the whole text, and the document's
tags with an edit button.

The panel is display-only: MainWindow computes the values (it owns the
store) and pushes them in via update_info() / update_position().  The one
outbound signal is edit_tags_requested — tag editing needs the store.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class InfoPanel(QWidget):
    """Dockable 'about this document' panel."""

    edit_tags_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # One QLabel per fact; the form layout keeps captions aligned.
        self._title = QLabel("—")
        self._title.setWordWrap(True)
        self._chain = QLabel("—")
        self._created = QLabel("—")
        self._edited = QLabel("—")
        self._revisions = QLabel("—")
        self._words = QLabel("—")
        self._position = QLabel("—")
        self._position.setWordWrap(True)
        self._tags = QLabel("—")
        self._tags.setWordWrap(True)
        self._verses = QLabel("—")
        self._verses.setWordWrap(True)

        edit_tags_btn = QPushButton("Edit tags…", self)
        edit_tags_btn.clicked.connect(self.edit_tags_requested)

        form = QFormLayout()
        form.addRow("Document:", self._title)
        form.addRow("Versions:", self._chain)
        form.addRow("Created:", self._created)
        form.addRow("Last edit:", self._edited)
        form.addRow("Revisions:", self._revisions)
        form.addRow("Words:", self._words)
        form.addRow("Position:", self._position)
        form.addRow("Tags:", self._tags)
        form.addRow("Verses cited:", self._verses)

        outer = QVBoxLayout(self)
        outer.addLayout(form)
        outer.addWidget(edit_tags_btn)
        outer.addStretch(1)

    # -- fed by MainWindow --------------------------------------------------

    def update_info(
        self,
        title: str,
        chain_text: str,
        created: str,
        last_edited: str,
        revision_count: int,
        word_count: int,
        tags: list[str],
        verse_count: int = 0,
    ) -> None:
        """Document-level facts (refreshed on open/save)."""
        self._title.setText(title)
        self._chain.setText(chain_text)
        self._created.setText(created)
        self._edited.setText(last_edited)
        self._revisions.setText(str(revision_count))
        self._words.setText(f"{word_count:,}")
        self._tags.setText(", ".join(tags) if tags else "none")
        self._verses.setText(str(verse_count) if verse_count else "none")

    def update_position(self, word_index: int, word_count: int, percent: int) -> None:
        """Cursor-level facts (refreshed as the cursor moves)."""
        if word_count == 0:
            self._position.setText("empty document")
        else:
            self._position.setText(
                f"word {word_index:,} of {word_count:,} — {percent}% through"
            )

    def clear(self) -> None:
        for label in (self._title, self._chain, self._created, self._edited,
                      self._revisions, self._words, self._position, self._tags,
                      self._verses):
            label.setText("—")


class LibraryInfoPanel(QWidget):
    """
    Dockable 'about this library' panel (sits below Document Info):
    document/revision counts, file size, oldest document date, the
    library's file name and its location.  The location is shown in a
    read-only line edit — it scrolls horizontally instead of stretching
    the panel wide.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self._documents = QLabel("—")
        self._revisions = QLabel("—")
        self._size = QLabel("—")
        self._oldest = QLabel("—")
        self._encrypted = QLabel("—")
        self._name = QLabel("—")
        self._name.setWordWrap(True)

        # A read-only QLineEdit scrolls long paths horizontally — the
        # requested space-saving trick.
        self._location = QLineEdit()
        self._location.setReadOnly(True)
        self._location.setFrame(True)
        self._location.setCursorPosition(0)

        form = QFormLayout()
        form.addRow("Documents:", self._documents)
        form.addRow("Revisions:", self._revisions)
        form.addRow("File size:", self._size)
        form.addRow("Oldest doc:", self._oldest)
        form.addRow("Encrypted:", self._encrypted)
        form.addRow("File name:", self._name)
        form.addRow("Location:", self._location)

        outer = QVBoxLayout(self)
        outer.addLayout(form)
        outer.addStretch(1)

    def update_info(
        self,
        documents: int,
        revisions: int,
        size_bytes: int,
        oldest: str,
        encrypted: bool,
        file_name: str,
        location: str,
    ) -> None:
        self._documents.setText(f"{documents:,}")
        self._revisions.setText(f"{revisions:,}")
        if size_bytes >= 1024 * 1024:
            self._size.setText(f"{size_bytes / (1024 * 1024):.1f} MB")
        else:
            self._size.setText(f"{size_bytes / 1024:.0f} KB")
        self._oldest.setText(oldest)
        self._encrypted.setText("yes" if encrypted else "no")
        self._name.setText(file_name)
        self._location.setText(location)
        self._location.setCursorPosition(0)   # show the start of the path
