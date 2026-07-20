"""
review.py — the version-group review screen (roadmap stage 5, Phase C).

The ingest tool proposed groups of documents that look like drafts of the
same material.  Automation proposes; the author decides (DESIGN.md
section 6).  For each pending group this dialog shows the members with
dates, similarity scores and word counts, lets the author compare any two
side-by-side as a colored diff, and offers three decisions:

  Confirm & Link  — the CHECKED members become a version chain, linked
                    oldest → newest via parent_doc_id.  Unchecking a
                    member is the "split" operation: it simply stays an
                    independent document.
  Reject          — the group is dismissed; all members stay independent.
  (Skip)          — selecting another group decides nothing; the group
                    stays pending for a later sitting.  The review queue
                    is persistent on purpose — 188 groups need not be
                    judged in one evening.

Nothing here deletes or rewrites anything: chain links are metadata, and
a confirmed/rejected decision survives re-runs of the ingest detector.
"""

from __future__ import annotations

import difflib
import html
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from wordvault.storage.store import DocumentStore


def _short_date(iso_utc: str) -> str:
    """Stored UTC timestamp -> short local date for table display."""
    return datetime.fromisoformat(iso_utc).astimezone().strftime("%Y-%m-%d")


def diff_as_html(title_a: str, text_a: str, title_b: str, text_b: str) -> str:
    """
    A unified diff rendered as colored HTML: deletions red, additions
    green, hunk markers gray.  Plain difflib + html.escape — no external
    dependencies, works in a QTextBrowser.
    """
    lines = difflib.unified_diff(
        text_a.splitlines(), text_b.splitlines(),
        fromfile=title_a, tofile=title_b, lineterm="", n=2,
    )
    out = ['<pre style="font-family: monospace; font-size: 10pt;">']
    for line in lines:
        esc = html.escape(line)
        if line.startswith("+") and not line.startswith("+++"):
            out.append(f'<span style="color:#1a7f1a;">{esc}</span>')
        elif line.startswith("-") and not line.startswith("---"):
            out.append(f'<span style="color:#b22222;">{esc}</span>')
        elif line.startswith("@@"):
            out.append(f'<span style="color:#888888;">{esc}</span>')
        else:
            out.append(esc)
    out.append("</pre>")
    if len(out) == 2:  # nothing between the <pre> tags
        return "<p>The two selected documents have identical text.</p>"
    return "\n".join(out)


class ReviewDialog(QDialog):
    """Work through the pending similarity groups, one decision at a time."""

    def __init__(self, store: DocumentStore, parent=None):
        super().__init__(parent)
        self._store = store

        self.setWindowTitle("Review Version Groups")
        self.resize(1100, 700)

        # ---- left: the queue of pending groups ----
        self._group_list = QListWidget(self)
        self._group_list.currentItemChanged.connect(self._on_group_selected)

        # ---- right: members table, diff view, decision buttons ----
        self._members = QTableWidget(0, 4, self)
        self._members.setHorizontalHeaderLabels(
            ["Document (oldest first)", "Date", "Similarity", "Words"]
        )
        self._members.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._members.setSelectionMode(
            QTableWidget.SelectionMode.ExtendedSelection
        )
        self._members.horizontalHeader().setStretchLastSection(False)
        self._members.setColumnWidth(0, 420)

        self._compare_btn = QPushButton("Compare selected pair", self)
        self._compare_btn.clicked.connect(self._on_compare)

        self._diff_view = QTextBrowser(self)
        self._diff_view.setPlaceholderText(
            "Select two rows above and click “Compare selected pair” "
            "to see what changed between drafts."
        )

        self._confirm_btn = QPushButton("Confirm && Link checked as versions", self)
        self._confirm_btn.clicked.connect(self._on_confirm)
        self._reject_btn = QPushButton("Reject group", self)
        self._reject_btn.clicked.connect(self._on_reject)
        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.accept)

        self._progress = QLabel("", self)

        # ---- layout ----
        right = QWidget(self)
        right_box = QVBoxLayout(right)
        right_box.addWidget(QLabel(
            "Uncheck a document to leave it OUT of the chain (split). "
            "Checked documents are linked oldest → newest on Confirm."
        ))
        right_box.addWidget(self._members, stretch=2)
        right_box.addWidget(self._compare_btn)
        right_box.addWidget(self._diff_view, stretch=3)

        buttons = QHBoxLayout()
        buttons.addWidget(self._confirm_btn)
        buttons.addWidget(self._reject_btn)
        buttons.addStretch(1)
        buttons.addWidget(self._progress)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        right_box.addLayout(buttons)

        splitter = QSplitter(self)
        splitter.addWidget(self._group_list)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        outer = QVBoxLayout(self)
        outer.addWidget(splitter)

        self._reload_groups()

    # -------------------------------------------------------------- queue --

    def _reload_groups(self) -> None:
        """Fill the left list with all still-pending groups."""
        self._group_list.clear()
        for gid in self._store.list_similarity_groups("pending"):
            members = self._store.group_members(gid)
            avg = sum(score for _, score in members) / len(members)
            item = QListWidgetItem(
                f"Group {gid} — {len(members)} documents, avg {avg:.0%}"
            )
            item.setData(Qt.ItemDataRole.UserRole, gid)
            self._group_list.addItem(item)
        self._update_progress()
        if self._group_list.count():
            self._group_list.setCurrentRow(0)
        else:
            self._members.setRowCount(0)
            self._diff_view.setHtml(
                "<p>All groups reviewed — nothing pending. Well done!</p>"
            )
            self._confirm_btn.setEnabled(False)
            self._reject_btn.setEnabled(False)

    def _current_group_id(self):
        item = self._group_list.currentItem()
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def _update_progress(self) -> None:
        self._progress.setText(f"{self._group_list.count()} groups pending")

    # ------------------------------------------------------------ members --

    def _on_group_selected(self, current, _previous) -> None:
        if current is None:
            return
        gid = current.data(Qt.ItemDataRole.UserRole)
        members = self._store.group_members(gid)  # oldest first already

        self._members.setRowCount(len(members))
        for row, (doc, score) in enumerate(members):
            # Column 0: title, checkable (checked = include in the chain).
            title_item = QTableWidgetItem(doc.title)
            title_item.setFlags(
                title_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            )
            title_item.setCheckState(Qt.CheckState.Checked)
            title_item.setData(Qt.ItemDataRole.UserRole, doc.id)

            words = len(self._store.current_text(doc.id).split())
            self._members.setItem(row, 0, title_item)
            self._members.setItem(row, 1, QTableWidgetItem(_short_date(doc.created_utc)))
            self._members.setItem(row, 2, QTableWidgetItem(f"{score:.0%}"))
            self._members.setItem(row, 3, QTableWidgetItem(f"{words}"))
        self._diff_view.clear()

    def _checked_doc_ids(self) -> list[int]:
        """Ids of checked members, in table (= chronological) order."""
        ids = []
        for row in range(self._members.rowCount()):
            item = self._members.item(row, 0)
            if item.checkState() == Qt.CheckState.Checked:
                ids.append(item.data(Qt.ItemDataRole.UserRole))
        return ids

    # --------------------------------------------------------------- diff --

    def _on_compare(self) -> None:
        rows = sorted(
            {index.row() for index in self._members.selectionModel().selectedRows()}
        )
        if len(rows) != 2:
            QMessageBox.information(
                self, "Compare",
                "Select exactly two rows (Ctrl+click) to compare."
            )
            return
        items = [self._members.item(r, 0) for r in rows]
        docs = [self._store.get_document(i.data(Qt.ItemDataRole.UserRole))
                for i in items]
        self._diff_view.setHtml(diff_as_html(
            docs[0].title, self._store.current_text(docs[0].id),
            docs[1].title, self._store.current_text(docs[1].id),
        ))

    # ---------------------------------------------------------- decisions --

    def _on_confirm(self) -> None:
        """Link the checked members as a version chain, oldest → newest."""
        gid = self._current_group_id()
        if gid is None:
            return
        ids = self._checked_doc_ids()
        if len(ids) < 2:
            QMessageBox.information(
                self, "Confirm",
                "A version chain needs at least two checked documents. "
                "Use Reject if these are not versions of each other."
            )
            return
        try:
            self._store.link_version_chain(ids)
        except ValueError as exc:  # e.g. would create a cycle
            QMessageBox.warning(self, "Confirm", str(exc))
            return
        self._store.set_group_status(gid, "confirmed")
        self._remove_current_group()

    def _on_reject(self) -> None:
        gid = self._current_group_id()
        if gid is None:
            return
        self._store.set_group_status(gid, "rejected")
        self._remove_current_group()

    def _remove_current_group(self) -> None:
        """Drop the decided group from the queue and move to the next."""
        row = self._group_list.currentRow()
        self._group_list.takeItem(row)
        self._update_progress()
        if self._group_list.count() == 0:
            self._reload_groups()  # shows the "all reviewed" state
