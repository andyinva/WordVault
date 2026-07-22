"""
quick_open.py — "Go to Document" (Ctrl+P): find a document by typing.

With 1,700+ documents, scrolling the Library list is slow.  This dialog
is the fast path: type a few letters, the list narrows as you type,
Enter opens the top match.  Titles that START with what you typed rank
above titles that merely contain it.

The dialog only chooses; MainWindow opens the chosen document.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from wordvault.storage.store import DocumentStore

#: Never show more than this many rows — typing narrows further.
_MAX_ROWS = 50


class QuickOpenDialog(QDialog):
    """Type-ahead document chooser.  Read selected_doc_id after exec()."""

    def __init__(self, store: DocumentStore, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Go to Document")
        self.resize(520, 420)
        self.selected_doc_id: Optional[int] = None

        # Titles are loaded once; filtering happens in memory (fast even
        # for thousands of documents).
        self._docs = [(d.id, d.title) for d in store.list_documents()]

        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText("Type part of a document title…")
        self._edit.textChanged.connect(self._refilter)
        self._edit.returnPressed.connect(self._accept_current)
        # Up/Down in the text box steer the list — no need to Tab over.
        self._edit.installEventFilter(self)

        self._list = QListWidget(self)
        self._list.itemActivated.connect(lambda _i: self._accept_current())

        layout = QVBoxLayout(self)
        layout.addWidget(self._edit)
        layout.addWidget(self._list)
        layout.addWidget(QLabel(
            "Enter opens the highlighted document · Esc cancels", self
        ))

        self._refilter("")
        self._edit.setFocus()

    # -- filtering ----------------------------------------------------------

    def _refilter(self, text: str) -> None:
        query = text.strip().lower()
        starts: list[tuple[int, str]] = []
        contains: list[tuple[int, str]] = []
        for doc_id, title in self._docs:
            lowered = title.lower()
            if not query:
                contains.append((doc_id, title))
            elif lowered.startswith(query):
                starts.append((doc_id, title))
            elif query in lowered:
                contains.append((doc_id, title))

        self._list.clear()
        for doc_id, title in (starts + contains)[:_MAX_ROWS]:
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, doc_id)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)

    # -- choosing -----------------------------------------------------------

    def _accept_current(self) -> None:
        item = self._list.currentItem()
        if item is not None:
            self.selected_doc_id = item.data(Qt.ItemDataRole.UserRole)
            self.accept()

    def eventFilter(self, obj, event):  # noqa: N802 (Qt naming)
        """Arrow keys typed in the text box move the list highlight."""
        if obj is self._edit and event.type() == event.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self._list.currentRow()
                step = 1 if event.key() == Qt.Key.Key_Down else -1
                new_row = max(0, min(self._list.count() - 1, row + step))
                self._list.setCurrentRow(new_row)
                return True
        return super().eventFilter(obj, event)
