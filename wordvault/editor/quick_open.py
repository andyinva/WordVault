"""
quick_open.py — "Go to Document" (Ctrl+P): find a document by typing.

With 1,700+ documents, scrolling the Library list is slow.  This dialog
is the fast path: type a few letters, the table narrows as you type,
Enter opens the top match.  Titles that START with what you typed rank
above titles that merely contain it — and the Created / Modified columns
sort on click, so "the newest essay about the kingdom" is two gestures.

The dialog only chooses; MainWindow opens the chosen document.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from wordvault.storage.store import DocumentStore

#: Never show more than this many rows — typing narrows further.
_MAX_ROWS = 50


def _day(iso_utc) -> str:
    """Stored UTC timestamp -> local YYYY-MM-DD (sorts correctly as text)."""
    if not iso_utc:
        return ""
    return datetime.fromisoformat(iso_utc).astimezone().strftime("%Y-%m-%d")


class QuickOpenDialog(QDialog):
    """Type-ahead document chooser.  Read selected_doc_id after exec()."""

    def __init__(self, store: DocumentStore, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Go to Document")
        self.resize(640, 440)
        self.selected_doc_id: Optional[int] = None

        # Loaded once; filtering happens in memory.  Modified dates come
        # from one bulk query, not one query per document.
        modified = store.last_modified_map()
        self._docs = [
            (d.id, d.title, _day(d.created_utc), _day(modified.get(d.id)))
            for d in store.list_documents()
        ]

        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText("Type part of a document title…")
        self._edit.textChanged.connect(self._refilter)
        self._edit.returnPressed.connect(self._accept_current)
        # Up/Down in the text box steer the table — no need to Tab over.
        self._edit.installEventFilter(self)

        self._tree = QTreeWidget(self)
        self._tree.setHeaderLabels(["Document", "Created", "Modified"])
        self._tree.setRootIsDecorated(False)
        self._tree.setColumnWidth(0, 380)
        self._tree.setColumnWidth(1, 90)
        self._tree.setColumnWidth(2, 90)
        self._tree.setSortingEnabled(True)
        # No initial sort indicator: best-match ranking order until the
        # author clicks a column header.
        self._tree.header().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self._tree.itemActivated.connect(lambda _i, _c: self._accept_current())

        layout = QVBoxLayout(self)
        layout.addWidget(self._edit)
        layout.addWidget(self._tree)
        layout.addWidget(QLabel(
            "Enter opens the highlighted document · click a column header "
            "to sort · Esc cancels", self
        ))

        self._refilter("")
        self._edit.setFocus()

    # -- filtering ----------------------------------------------------------

    def _refilter(self, text: str) -> None:
        query = text.strip().lower()
        starts: list[tuple] = []
        contains: list[tuple] = []
        for row in self._docs:
            lowered = row[1].lower()
            if not query:
                contains.append(row)
            elif lowered.startswith(query):
                starts.append(row)
            elif query in lowered:
                contains.append(row)

        self._tree.clear()
        for doc_id, title, created, modified in (starts + contains)[:_MAX_ROWS]:
            item = QTreeWidgetItem([title, created, modified])
            item.setData(0, Qt.ItemDataRole.UserRole, doc_id)
            self._tree.addTopLevelItem(item)
        if self._tree.topLevelItemCount():
            self._tree.setCurrentItem(self._tree.topLevelItem(0))

    # -- choosing -----------------------------------------------------------

    def _accept_current(self) -> None:
        item = self._tree.currentItem()
        if item is not None:
            self.selected_doc_id = item.data(0, Qt.ItemDataRole.UserRole)
            self.accept()

    def eventFilter(self, obj, event):  # noqa: N802 (Qt naming)
        """Arrow keys typed in the text box move the table highlight."""
        if obj is self._edit and event.type() == event.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                current = self._tree.currentItem()
                row = self._tree.indexOfTopLevelItem(current) if current else 0
                step = 1 if event.key() == Qt.Key.Key_Down else -1
                new_row = max(0, min(self._tree.topLevelItemCount() - 1,
                                     row + step))
                self._tree.setCurrentItem(self._tree.topLevelItem(new_row))
                return True
        return super().eventFilter(obj, event)
