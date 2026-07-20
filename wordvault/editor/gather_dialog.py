"""
gather_dialog.py — the gather tray (stage 6, "mark and gather").

The MaxThink-inspired workflow (DESIGN.md section 8): while reading any
document, the author marks passages (Ctrl+M in the editor).  Marks queue
up in a persistent tray — across documents and across sittings.  This
dialog shows the tray and performs the Gather: one click builds a NEW
document from all marked passages, each with a provenance (`sources`)
row pointing back to exactly where it came from.

This is the primary tool for distilling material out of the legacy
library into new essays.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from wordvault.storage.store import DocumentStore


def _preview(text: str, width: int = 70) -> str:
    """First words of a passage, single-line, for the tray list."""
    flat = " ".join(text.split())
    return flat[:width] + ("…" if len(flat) > width else "")


class GatherDialog(QDialog):
    """Show the tray; remove items; gather everything into a new document."""

    #: emitted with the new document's id after a successful gather,
    #: so the main window can refresh the library and open it.
    gathered = pyqtSignal(int)

    def __init__(self, store: DocumentStore, parent=None):
        super().__init__(parent)
        self._store = store

        self.setWindowTitle("Gather Tray")
        self.resize(700, 450)

        self._list = QListWidget(self)

        remove_btn = QPushButton("Remove selected", self)
        remove_btn.clicked.connect(self._on_remove)
        gather_btn = QPushButton("Gather into new document…", self)
        gather_btn.clicked.connect(self._on_gather)
        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.accept)

        self._status = QLabel("", self)

        buttons = QHBoxLayout()
        buttons.addWidget(remove_btn)
        buttons.addStretch(1)
        buttons.addWidget(gather_btn)
        buttons.addWidget(close_btn)

        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "Passages marked with Ctrl+M, in marking order. "
            "Gather builds a new document from all of them, with a "
            "provenance record for every passage."
        ))
        outer.addWidget(self._list, stretch=1)
        outer.addWidget(self._status)
        outer.addLayout(buttons)

        self._reload()

    # -------------------------------------------------------------- items --

    def _reload(self) -> None:
        self._list.clear()
        items = self._store.list_gather_items()
        for item in items:
            doc = self._store.get_document(item.doc_id)
            entry = QListWidgetItem(f"[{doc.title}]  {_preview(item.text)}")
            entry.setData(Qt.ItemDataRole.UserRole, item.id)
            self._list.addItem(entry)
        self._status.setText(
            f"{len(items)} passage" + ("s" if len(items) != 1 else "") + " in the tray"
        )

    def _on_remove(self) -> None:
        for entry in self._list.selectedItems():
            self._store.remove_gather_item(entry.data(Qt.ItemDataRole.UserRole))
        self._reload()

    # ------------------------------------------------------------- gather --

    def _on_gather(self) -> None:
        if self._list.count() == 0:
            QMessageBox.information(
                self, "Gather",
                "The tray is empty. Select text in a document and press "
                "Ctrl+M to mark passages first."
            )
            return
        title, ok = QInputDialog.getText(
            self, "Gather", "Title for the new document:"
        )
        if not ok or not title.strip():
            return
        doc = self._store.gather_into_document(title.strip())
        self.gathered.emit(doc.id)
        self.accept()   # done — the main window opens the new document
