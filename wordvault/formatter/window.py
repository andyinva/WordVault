"""
window.py — the Formatter's own window (Library menu -> Book Formatter).

The layout reads left to right the way a book is assembled:

    +----------------------------------------------------------+
    | Title [_______________]  Author [__________]  Format [v] |
    |                                                          |
    |  Library documents        |  >  |   Chapters (in order)  |
    |  [filter___]              |  <  |                        |
    |  (double-click adds)      | Up  |                        |
    |                           | Down|                        |
    |                                                          |
    |  Sections: [x] Title page [ ] Copyright ... (checkboxes) |
    |                                                          |
    |  [Open…] [Save] [Save As…]          [Build Book PDF…]    |
    +----------------------------------------------------------+

Section checkboxes arriving in later stages are shown but disabled,
each labelled with the stage that will light it up — the plan is
visible in the window itself.

The window is non-modal: the author can keep writing in WordVault
while a book project sits open beside it.  Chapter text is never
copied into the project; every build re-reads the library.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from wordvault.formatter.book import BookProject, BookProjectError, ChapterRef
from wordvault.formatter.builder import (
    assemble_markdown,
    build_book_pdf,
    resolve_chapters,
)
from wordvault.printing.format_file import ensure_default_formats, list_formats

#: Checkbox labels, and which stage delivers each not-yet-live section.
_SECTION_LABELS = {
    "title_page": ("Title page", "F2"),
    "copyright": ("Copyright page (ISBN)", "F2"),
    "toc": ("Table of contents", "F3"),
    "subject_index": ("Subject index", "F4"),
    "scripture_index": ("Scripture index", "F4"),
}

#: Sections whose stage has shipped — their checkboxes are live.
_LIVE_SECTIONS = {"title_page", "copyright", "toc",
                  "subject_index", "scripture_index"}


class FormatterWindow(QDialog):
    """The book assembler.  Needs only the DocumentStore (its single
    door to the library) and QSettings for small persisted comforts."""

    def __init__(self, store, settings: QSettings, parent=None):
        super().__init__(parent)
        self._store = store
        self._settings = settings
        self._project = BookProject()
        self._project_path: Path | None = None
        #: The book tag last stamped on chapters ("Book: <title>") —
        #: remembered so renaming the book cleans up its old tag.
        self._last_book_tag: str | None = None

        self.setWindowTitle("WordVault Book Formatter")
        self.setModal(False)
        self.resize(940, 560)   # room for the sections column + lists
        self._build_ui()
        self._reload_library_list()
        self._reopen_last_project()

    # -- construction ---------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        # Book identity row: title, author, print format.
        row = QHBoxLayout()
        row.addWidget(QLabel("Title:"))
        self._title_edit = QLineEdit()
        row.addWidget(self._title_edit, stretch=3)
        row.addWidget(QLabel("Author:"))
        self._author_edit = QLineEdit()
        # A new project starts with the Settings author — one less field
        # to retype for every book.
        self._author_edit.setText(str(self._settings.value("author", "")))
        row.addWidget(self._author_edit, stretch=2)
        row.addWidget(QLabel("Format:"))
        self._format_combo = QComboBox()
        ensure_default_formats()
        for fmt in list_formats():
            self._format_combo.addItem(fmt.name)
        row.addWidget(self._format_combo, stretch=2)
        outer.addLayout(row)

        # The book's SECTIONS: a vertical, scrolling checklist down the
        # far-left side.  Vertical on purpose (Aug 2026 request): the
        # list can grow beyond the window's height — indexes, covers,
        # and whatever the years add — and simply scrolls, where the
        # old horizontal row would have run out of window.
        section_host = QWidget()
        section_col = QVBoxLayout(section_host)
        section_col.setContentsMargins(6, 4, 6, 4)
        self._section_checks: dict[str, QCheckBox] = {}
        for key, (label, stage) in _SECTION_LABELS.items():
            check = QCheckBox(label)
            if key not in _LIVE_SECTIONS:
                check.setEnabled(False)             # lit in its stage
                check.setToolTip(f"Coming in stage {stage}")
            section_col.addWidget(check)
            self._section_checks[key] = check
        details_btn = QPushButton("Copyright &Details…")
        details_btn.setToolTip(
            "ISBN, copyright year, edition, rights statement, and the\n"
            "Scripture-translation notice printed on the copyright page"
        )
        details_btn.clicked.connect(self._on_copyright_details)
        section_col.addWidget(details_btn)

        vocab_btn = QPushButton("Subject &Vocabulary…")
        vocab_btn.setToolTip(
            "The controlled vocabulary (vocabulary.json) the Subject "
            "Index\nis built from — the Word Index Creator's file "
            "works as-is"
        )
        vocab_btn.clicked.connect(self._on_choose_vocabulary)
        section_col.addWidget(vocab_btn)
        self._vocab_label = QLabel("(no vocabulary chosen)")
        self._vocab_label.setWordWrap(True)
        self._vocab_label.setStyleSheet("color: #667; font-size: 8pt;")
        section_col.addWidget(self._vocab_label)
        section_col.addStretch()

        section_scroll = QScrollArea()
        section_scroll.setWidget(section_host)
        section_scroll.setWidgetResizable(True)
        section_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        section_scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        section_box = QGroupBox("Sections")
        section_box_layout = QVBoxLayout(section_box)
        section_box_layout.setContentsMargins(2, 6, 2, 2)
        section_box_layout.addWidget(section_scroll)
        section_box.setMaximumWidth(230)

        # The columns: sections | library | transfer buttons | chapters.
        lists = QHBoxLayout()
        lists.addWidget(section_box)

        left_col = QVBoxLayout()
        left_col.addWidget(QLabel("Library documents (double-click to add):"))
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Type to filter…")
        self._filter_edit.textChanged.connect(self._reload_library_list)
        left_col.addWidget(self._filter_edit)
        self._library_list = QListWidget()
        self._library_list.itemDoubleClicked.connect(self._on_add_chapter)
        left_col.addWidget(self._library_list)
        lists.addLayout(left_col, stretch=3)

        # The transfer / ordering buttons between the lists.
        buttons = QVBoxLayout()
        buttons.addStretch()
        add_btn = QPushButton("Add →")
        add_btn.clicked.connect(self._on_add_chapter)
        buttons.addWidget(add_btn)
        tag_btn = QPushButton("Add All by Tag…")
        tag_btn.setToolTip(
            "Pull in every library document carrying a chosen tag —\n"
            "the one-step gather for essays already marked as a book"
        )
        tag_btn.clicked.connect(self._on_add_by_tag)
        buttons.addWidget(tag_btn)
        remove_btn = QPushButton("← Remove")
        remove_btn.clicked.connect(self._on_remove_chapter)
        buttons.addWidget(remove_btn)
        up_btn = QPushButton("Move Up")
        up_btn.clicked.connect(lambda: self._move_chapter(-1))
        buttons.addWidget(up_btn)
        down_btn = QPushButton("Move Down")
        down_btn.clicked.connect(lambda: self._move_chapter(+1))
        buttons.addWidget(down_btn)
        buttons.addStretch()
        lists.addLayout(buttons)

        right_col = QVBoxLayout()
        right_col.addWidget(QLabel("Chapters, in book order:"))
        self._chapter_list = QListWidget()
        self._chapter_list.itemDoubleClicked.connect(self._on_remove_chapter)
        right_col.addWidget(self._chapter_list)
        lists.addLayout(right_col, stretch=3)

        outer.addLayout(lists, stretch=1)

        # Project and build buttons.
        bottom = QHBoxLayout()
        open_btn = QPushButton("&Open Project…")
        open_btn.clicked.connect(self._on_open_project)
        bottom.addWidget(open_btn)
        save_btn = QPushButton("&Save Project")
        save_btn.clicked.connect(self._on_save_project)
        bottom.addWidget(save_btn)
        save_as_btn = QPushButton("Save Project &As…")
        save_as_btn.clicked.connect(self._on_save_project_as)
        bottom.addWidget(save_as_btn)
        bottom.addStretch()
        draft_btn = QPushButton("Create &Draft Document")
        draft_btn.setToolTip(
            "Assemble the chapters into ONE library document — a\n"
            "read-through snapshot for checking the book's flow.\n"
            "It is an output, like a printed proof: make fixes in the\n"
            "chapter essays, then create a fresh draft any time."
        )
        draft_btn.clicked.connect(self._on_create_draft)
        bottom.addWidget(draft_btn)
        build_btn = QPushButton("&Build Book PDF…")
        build_btn.setDefault(True)
        build_btn.clicked.connect(self._on_build)
        bottom.addWidget(build_btn)
        outer.addLayout(bottom)

    # -- the library side -----------------------------------------------

    def _reload_library_list(self) -> None:
        """Fill the left list from the store, newest last, filtered by
        the search box (plain case-insensitive substring — the same
        simple rule as the editor's quick-open)."""
        needle = self._filter_edit.text().strip().lower() \
            if hasattr(self, "_filter_edit") else ""
        self._library_list.clear()
        for doc in self._store.list_documents():
            if needle and needle not in doc.title.lower():
                continue
            item = QListWidgetItem(doc.title)
            # The uuid rides along invisibly; it is what the project saves.
            item.setData(Qt.ItemDataRole.UserRole, doc.uuid)
            self._library_list.addItem(item)

    # -- chapter assembly ------------------------------------------------

    def _on_add_chapter(self, *_args) -> None:
        item = self._library_list.currentItem()
        if item is None:
            return
        uuid = item.data(Qt.ItemDataRole.UserRole)
        # A chapter appears once; adding again is a quiet no-op.
        for i in range(self._chapter_list.count()):
            if self._chapter_list.item(i).data(
                    Qt.ItemDataRole.UserRole) == uuid:
                return
        chapter = QListWidgetItem(item.text())
        chapter.setData(Qt.ItemDataRole.UserRole, uuid)
        self._chapter_list.addItem(chapter)

    def _on_remove_chapter(self, *_args) -> None:
        row = self._chapter_list.currentRow()
        if row >= 0:
            self._chapter_list.takeItem(row)

    def _on_add_by_tag(self) -> None:
        """The one-step gather: every library document carrying a
        chosen tag becomes a chapter (skipping ones already in the
        book).  Essays tagged 'Book: ...' months earlier assemble
        themselves in a single motion; order is yours to adjust."""
        names = [t.name for t in self._store.list_tags()]
        if not names:
            QMessageBox.information(
                self, "No tags yet",
                "No document in the library has a tag.  Tag essays in "
                "WordVault (Document > Edit Tags…), or just save this "
                "project — its chapters get a book tag automatically.")
            return
        # Book tags first: they are what this button is usually for.
        names.sort(key=lambda n: (not n.startswith("Book: "), n.lower()))
        name, ok = QInputDialog.getItem(
            self, "Add All by Tag", "Add every document tagged:",
            names, 0, False)
        if not ok or not name:
            return
        added = self._add_documents_with_tag(name)
        QMessageBox.information(
            self, "Chapters added",
            f"Added {added} document(s) tagged '{name}'.\n"
            "Use Move Up / Move Down to set the book's order.")

    def _add_documents_with_tag(self, name: str) -> int:
        """Append every tagged document not already in the book;
        returns how many were added.  (The dialog-free half of Add All
        by Tag, so tests can drive it directly.)"""
        present = {self._chapter_list.item(i).data(Qt.ItemDataRole.UserRole)
                   for i in range(self._chapter_list.count())}
        added = 0
        for doc in self._store.documents_with_tag(name):
            if doc.uuid in present:
                continue
            item = QListWidgetItem(doc.title)
            item.setData(Qt.ItemDataRole.UserRole, doc.uuid)
            self._chapter_list.addItem(item)
            added += 1
        return added

    def _move_chapter(self, delta: int) -> None:
        """Reorder: take the item out, put it back one slot away, keep
        it selected so repeated clicks keep moving it."""
        row = self._chapter_list.currentRow()
        target = row + delta
        if row < 0 or not (0 <= target < self._chapter_list.count()):
            return
        item = self._chapter_list.takeItem(row)
        self._chapter_list.insertItem(target, item)
        self._chapter_list.setCurrentRow(target)

    def _chapter_refs(self) -> list[ChapterRef]:
        return [
            ChapterRef(
                uuid=self._chapter_list.item(i).data(
                    Qt.ItemDataRole.UserRole),
                title=self._chapter_list.item(i).text(),
            )
            for i in range(self._chapter_list.count())
        ]

    # -- project file round trip ------------------------------------------

    def _gather_project(self) -> BookProject:
        """UI state -> BookProject (the reverse of _apply_project)."""
        project = self._project      # keeps copyright fields from F2 on
        project.title = self._title_edit.text().strip()
        project.author = self._author_edit.text().strip()
        project.format_name = self._format_combo.currentText()
        project.chapters = self._chapter_refs()
        project.sections = {
            key: check.isChecked()
            for key, check in self._section_checks.items()
        }
        return project

    def _apply_project(self, project: BookProject) -> None:
        self._project = project
        self._title_edit.setText(project.title)
        if project.author:
            self._author_edit.setText(project.author)
        index = self._format_combo.findText(project.format_name)
        if index >= 0:
            self._format_combo.setCurrentIndex(index)
        self._chapter_list.clear()
        for ref in project.chapters:
            item = QListWidgetItem(ref.title)
            item.setData(Qt.ItemDataRole.UserRole, ref.uuid)
            self._chapter_list.addItem(item)
        for key, check in self._section_checks.items():
            check.setChecked(bool(project.sections.get(key)))
        # A loaded project's chapters were presumably tagged at its
        # last save; remember that tag so a rename cleans it up.
        self._last_book_tag = (f"Book: {project.title.strip()}"
                               if project.title.strip() else None)
        self._refresh_vocab_label()
        self._refresh_title_bar()

    def _refresh_title_bar(self) -> None:
        name = self._project_path.name if self._project_path else "unsaved"
        self.setWindowTitle(f"WordVault Book Formatter — {name}")

    def _reopen_last_project(self) -> None:
        """Come back to the book you were working on — same courtesy
        the editor extends with its last-open document."""
        last = str(self._settings.value("formatter/last_project", ""))
        if last and Path(last).exists():
            try:
                self._project_path = Path(last)
                self._apply_project(BookProject.load(last))
            except BookProjectError:
                self._project_path = None    # a broken file is not fatal

    def _on_open_project(self) -> None:
        start = str(self._project_path.parent) if self._project_path else ""
        path, _f = QFileDialog.getOpenFileName(
            self, "Open Book Project", start,
            "WordVault book projects (*.wvbook)")
        if not path:
            return
        try:
            project = BookProject.load(path)
        except BookProjectError as exc:
            QMessageBox.warning(self, "Cannot open project", str(exc))
            return
        self._project_path = Path(path)
        self._apply_project(project)
        self._settings.setValue("formatter/last_project", path)

    def _on_save_project(self) -> None:
        if self._project_path is None:
            self._on_save_project_as()
            return
        project = self._gather_project()
        project.save(self._project_path)
        self._settings.setValue("formatter/last_project",
                                str(self._project_path))
        self._sync_book_tags(project)
        self._refresh_title_bar()

    def _sync_book_tags(self, project: BookProject) -> None:
        """Stamp the project's knowledge back into the library: every
        chapter carries a 'Book: <title>' tag, so membership is visible
        in WordVault (Library Info, Edit Tags, the tag filter).

        The .wvbook stays the master; tags are its shadow.  Chapters
        removed from the book lose the tag at the next save, and a
        RENAMED book cleans up the tag it used before."""
        if not project.title.strip():
            return                       # an untitled book marks nothing
        tag = f"Book: {project.title.strip()}"
        member_ids = []
        for ref in project.chapters:
            doc = self._store.get_document_by_uuid(ref.uuid)
            if doc is not None:
                member_ids.append(doc.id)

        # The rename case: strip the OLD tag everywhere first.
        if self._last_book_tag and self._last_book_tag != tag:
            for doc in self._store.documents_with_tag(self._last_book_tag):
                self._store.remove_tag(doc.id, self._last_book_tag)

        # Ex-chapters: tagged, but no longer in the project.
        for doc in self._store.documents_with_tag(tag):
            if doc.id not in member_ids:
                self._store.remove_tag(doc.id, tag)
        for doc_id in member_ids:
            self._store.add_tag(doc_id, tag)
        self._last_book_tag = tag
        self._refresh_main_window_library()

    def _refresh_main_window_library(self) -> None:
        """Tags or documents changed under WordVault's feet: ask the
        main window (our parent, when launched from the menu) to
        reload its lists so the change is visible immediately."""
        parent = self.parent()
        for method in ("_reload_tag_filter", "_reload_document_list"):
            if parent is not None and hasattr(parent, method):
                getattr(parent, method)()

    def _on_save_project_as(self) -> None:
        suggestion = (self._title_edit.text().strip() or "book") + ".wvbook"
        path, _f = QFileDialog.getSaveFileName(
            self, "Save Book Project", suggestion,
            "WordVault book projects (*.wvbook)")
        if not path:
            return
        if not path.lower().endswith(".wvbook"):
            path += ".wvbook"       # same suffix guard printing needed
        self._project_path = Path(path)
        self._on_save_project()

    def _on_choose_vocabulary(self) -> None:
        """Pick the vocabulary.json the Subject Index reads.  Saved in
        the .wvbook, so a book keeps its vocabulary across sessions."""
        start = (str(Path(self._project.vocabulary_path).parent)
                 if self._project.vocabulary_path else "")
        path, _f = QFileDialog.getOpenFileName(
            self, "Choose Subject Vocabulary", start,
            "Vocabulary files (*.json)")
        if path:
            self._project.vocabulary_path = path
            self._refresh_vocab_label()

    def _refresh_vocab_label(self) -> None:
        name = (Path(self._project.vocabulary_path).name
                if self._project.vocabulary_path else
                "(no vocabulary chosen)")
        self._vocab_label.setText(name)

    # -- copyright details -------------------------------------------------

    def _on_copyright_details(self) -> None:
        """The copyright page's small form: edits go straight into the
        project (saved with the .wvbook, printed when the Copyright
        checkbox is on)."""
        from PyQt6.QtWidgets import QDialogButtonBox, QFormLayout

        cp = self._project.copyright
        dialog = QDialog(self)
        dialog.setWindowTitle("Copyright Page Details")
        form = QFormLayout(dialog)

        isbn_edit = QLineEdit(cp.isbn)
        isbn_edit.setPlaceholderText("e.g. 979-8-1234-5678-9 (from KDP)")
        form.addRow("ISBN:", isbn_edit)
        year_edit = QLineEdit(cp.year)
        year_edit.setPlaceholderText("blank = the year you print")
        form.addRow("Copyright year:", year_edit)
        edition_edit = QLineEdit(cp.edition)
        edition_edit.setPlaceholderText("e.g. First edition")
        form.addRow("Edition:", edition_edit)
        rights_edit = QLineEdit(cp.rights)
        form.addRow("Rights statement:", rights_edit)
        notice_edit = QLineEdit(cp.scripture_notice)
        notice_edit.setPlaceholderText(
            "e.g. Scripture quotations are from the King James Version.")
        form.addRow("Scripture notice:", notice_edit)
        qr_check = QCheckBox(
            "Include QR code (the book's typesetting recipe)")
        qr_check.setChecked(cp.include_qr)
        qr_check.setToolTip(
            "Prints a small QR code at the foot of the copyright page\n"
            "holding title, author, ISBN, and the .wvfmt format text —\n"
            "the book carries how to rebuild its own layout.\n"
            "Needs the 'qrcode' package:  pip install qrcode")
        form.addRow(qr_check)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        if dialog.exec():
            cp.isbn = isbn_edit.text().strip()
            cp.year = year_edit.text().strip()
            cp.edition = edition_edit.text().strip()
            cp.rights = rights_edit.text().strip()
            cp.scripture_notice = notice_edit.text().strip()
            cp.include_qr = qr_check.isChecked()

    # -- the draft snapshot ----------------------------------------------

    def _on_create_draft(self) -> None:
        """Assemble the chapters into ONE new library document — the
        read-through draft.  It is an OUTPUT, like a printed proof:
        made for reading the book straight through and judging its
        flow.  Fixes belong in the chapter essays; the draft is
        disposable and can be rebuilt any time.  (This is why chapter
        edits never sync FROM a draft — one source of truth.)"""
        from datetime import date

        project = self._gather_project()
        if not project.chapters:
            QMessageBox.information(
                self, "No chapters",
                "Add at least one chapter from the library first.")
            return
        try:
            markdown = assemble_markdown(
                resolve_chapters(self._store, project))
        except BookProjectError as exc:
            QMessageBox.warning(self, "Cannot assemble", str(exc))
            return
        title = (f"{project.title.strip() or 'Book'} — draft of "
                 f"{date.today().strftime('%B %d, %Y')}")
        doc = self._store.create_document(title)
        self._store.save_revision(doc.id, markdown, origin="book draft")
        self._refresh_main_window_library()
        QMessageBox.information(
            self, "Draft created",
            f"'{title}' is now in the library — open it in WordVault "
            f"to read the whole book in order.\n\n"
            f"Remember: it is a snapshot.  Make fixes in the chapter "
            f"essays, then create a fresh draft.")

    # -- the build --------------------------------------------------------

    def _on_build(self) -> None:
        project = self._gather_project()
        if not project.chapters:
            QMessageBox.information(
                self, "No chapters",
                "Add at least one chapter from the library first.")
            return
        suggestion = (project.title.strip() or "book") + ".pdf"
        path, _f = QFileDialog.getSaveFileName(
            self, "Build Book PDF", suggestion, "PDF files (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            build_book_pdf(self._store, project, path)
        except BookProjectError as exc:
            QMessageBox.warning(self, "Build failed", str(exc))
            return
        QMessageBox.information(
            self, "Book built",
            f"Wrote {path}\n\nChapters: {len(project.chapters)}")
