"""
search_dialog.py — library-wide search and staged replace (stage 6).

A non-modal dialog (the author keeps writing while it is open):

    Find:     [ melchizedek            ]  [x] Regular expression
    Replace:  [                        ]  Scope: [Whole library v]
    [Search]  [Preview replace]  [Apply checked replacements]
    ┌────────────────────────────────────────────────────────┐
    │ ▸ On the Priesthood (2019-03-02) — 4 matches           │
    │     ☑ ...and Melchizedek king of Salem brought forth...│
    │ ▸ Hebrews Essay (2021-11-15) — 2 matches               │
    └────────────────────────────────────────────────────────┘

Search results and replace previews share the tree.  Double-clicking a
match asks the main window to open that document at that exact spot
(open_requested signal).  Replace follows DESIGN.md section 7 exactly:
preview first, uncheck what should not change, then Apply writes one
revision per document (origin='replace') — fully reversible through the
timeline like every other revision.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from wordvault.storage.search import DocPlan, SearchEngine
from wordvault.storage.store import DocumentStore

# Scope combo entries (index order matters, used in _scope_doc_ids).
_SCOPES = ["Whole library", "Current document", "Current version chain"]


class SearchDialog(QDialog):
    """Find / staged replace across the library."""

    #: (doc_id, start, end) — the main window opens the document there.
    open_requested = pyqtSignal(int, int, int)
    #: emitted after replacements were applied (the editor reloads its view).
    replacements_applied = pyqtSignal()

    def __init__(
        self,
        store: DocumentStore,
        current_doc_id: Callable[[], Optional[int]],
        parent=None,
    ):
        """
        current_doc_id — callable returning the id of the document open in
        the editor (or None); used for the narrower search scopes.
        """
        super().__init__(parent)
        self._store = store
        self._engine = SearchEngine(store)
        self._current_doc_id = current_doc_id
        self._plans: list[DocPlan] = []   # active replace preview, if any

        self.setWindowTitle("Search the Library")
        self.resize(900, 600)
        self.setModal(False)  # keep writing while searching

        # ---- controls ----
        self._find_edit = QLineEdit(self)
        self._find_edit.setPlaceholderText("word, phrase, or regular expression")
        self._find_edit.returnPressed.connect(self._on_search)

        self._replace_edit = QLineEdit(self)
        self._replace_edit.setPlaceholderText("replacement (for Preview replace)")

        self._regex_box = QCheckBox("Regular expression", self)
        self._case_box = QCheckBox("Match case", self)

        self._scope_combo = QComboBox(self)
        self._scope_combo.addItems(_SCOPES)

        search_btn = QPushButton("Search", self)
        search_btn.clicked.connect(self._on_search)
        preview_btn = QPushButton("Preview replace", self)
        preview_btn.clicked.connect(self._on_preview)
        self._apply_btn = QPushButton("Apply checked replacements", self)
        self._apply_btn.clicked.connect(self._on_apply)
        self._apply_btn.setEnabled(False)  # only after a preview

        # ---- results tree ----
        self._tree = QTreeWidget(self)
        self._tree.setHeaderLabels(["Match", "Becomes"])
        self._tree.setColumnWidth(0, 560)
        self._tree.itemActivated.connect(self._on_item_activated)

        self._status = QLabel("", self)

        # ---- layout ----
        grid = QGridLayout()
        grid.addWidget(QLabel("Find:"), 0, 0)
        grid.addWidget(self._find_edit, 0, 1)
        grid.addWidget(self._regex_box, 0, 2)
        grid.addWidget(self._case_box, 0, 3)
        grid.addWidget(QLabel("Replace:"), 1, 0)
        grid.addWidget(self._replace_edit, 1, 1)
        grid.addWidget(QLabel("Scope:"), 1, 2)
        grid.addWidget(self._scope_combo, 1, 3)

        buttons = QHBoxLayout()
        buttons.addWidget(search_btn)
        buttons.addWidget(preview_btn)
        buttons.addWidget(self._apply_btn)
        buttons.addStretch(1)

        outer = QVBoxLayout(self)
        outer.addLayout(grid)
        outer.addLayout(buttons)
        outer.addWidget(self._tree, stretch=1)
        outer.addWidget(self._status)

    # ------------------------------------------------------------- scoping --

    def _scope_doc_ids(self) -> Optional[list[int]]:
        """None = whole library; otherwise explicit document ids."""
        scope = self._scope_combo.currentIndex()
        if scope == 0:
            return None
        doc_id = self._current_doc_id()
        if doc_id is None:
            QMessageBox.information(
                self, "Search", "No document is open — using the whole library."
            )
            return None
        if scope == 1:
            return [doc_id]
        return [d.id for d in self._store.version_chain(doc_id)]

    # -------------------------------------------------------------- search --

    def _on_search(self) -> None:
        """Plain search: fill the tree with matches (no checkboxes)."""
        self._plans = []
        self._apply_btn.setEnabled(False)
        self._tree.clear()

        try:
            matches = self._engine.find(
                self._find_edit.text(),
                doc_ids=self._scope_doc_ids(),
                regex=self._regex_box.isChecked(),
                case_sensitive=self._case_box.isChecked(),
            )
        except Exception as exc:   # bad regex etc. — tell, don't crash
            QMessageBox.warning(self, "Search", str(exc))
            return

        by_doc: dict[int, list] = {}
        for m in matches:
            by_doc.setdefault(m.doc_id, []).append(m)

        for doc_id, doc_matches in by_doc.items():
            doc = self._store.get_document(doc_id)
            top = QTreeWidgetItem(
                [f"{doc.title} — {len(doc_matches)} match"
                 + ("es" if len(doc_matches) != 1 else ""), ""]
            )
            for m in doc_matches:
                child = QTreeWidgetItem([m.line, ""])
                child.setData(0, Qt.ItemDataRole.UserRole, (m.doc_id, m.start, m.end))
                top.addChild(child)
            self._tree.addTopLevelItem(top)
            top.setExpanded(len(by_doc) <= 8)   # expand when list is short

        self._status.setText(
            f"{len(matches)} matches in {len(by_doc)} documents. "
            "Double-click a match to open it."
        )

    # ------------------------------------------------------------- replace --

    def _on_preview(self) -> None:
        """Staged replace: fill the tree with CHECKABLE proposed changes."""
        self._tree.clear()
        try:
            self._plans = self._engine.plan_replace(
                self._find_edit.text(),
                self._replace_edit.text(),
                doc_ids=self._scope_doc_ids(),
                regex=self._regex_box.isChecked(),
                case_sensitive=self._case_box.isChecked(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Replace", str(exc))
            return

        total = 0
        for plan in self._plans:
            top = QTreeWidgetItem(
                [f"{plan.title} — {len(plan.matches)} change"
                 + ("s" if len(plan.matches) != 1 else ""), ""]
            )
            for m in plan.matches:
                child = QTreeWidgetItem([m.line, m.replacement])
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Checked)
                child.setData(0, Qt.ItemDataRole.UserRole, (m.doc_id, m.start, m.end))
                top.addChild(child)
                total += 1
            self._tree.addTopLevelItem(top)
            top.setExpanded(len(self._plans) <= 8)

        self._apply_btn.setEnabled(total > 0)
        self._status.setText(
            f"Preview: {total} proposed changes in {len(self._plans)} documents. "
            "Uncheck any you do not want, then Apply."
        )

    def _on_apply(self) -> None:
        """Execute the previewed replace for every still-checked change."""
        if not self._plans:
            return
        selected: set[tuple[int, int]] = set()
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            for j in range(top.childCount()):
                child = top.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    doc_id, start, _end = child.data(0, Qt.ItemDataRole.UserRole)
                    selected.add((doc_id, start))

        changed, skipped = self._engine.apply_replace(self._plans, selected)

        msg = f"Replaced in {changed} document" + ("s" if changed != 1 else "") + "."
        if skipped:
            msg += (
                "  Skipped (edited since preview — run Preview again): "
                + ", ".join(skipped)
            )
        self._status.setText(msg)
        self._plans = []
        self._apply_btn.setEnabled(False)
        self._tree.clear()
        self.replacements_applied.emit()

    # ------------------------------------------------------------ open-at --

    def _on_item_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data is not None:
            doc_id, start, end = data
            self.open_requested.emit(doc_id, start, end)
