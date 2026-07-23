"""
main_window.py — the WordVault main window (stages 2 + 3).

Owns the DocumentStore and wires the pieces together:

    ┌──────────────────────────────────────────────┐
    │ File  History  ...               (menu bar)  │
    ├───────────────┬──────────────────────────────┤
    │ Library dock  │                              │
    │  (documents,  │        EditorPane            │
    │   dbl-click   │   (auto-revision on pause)   │
    │   to open)    │                              │
    │               ├──────────────────────────────┤
    │               │  TimelineBar (time travel)   │
    ├───────────────┴──────────────────────────────┤
    │ title · rev count | words | last saved (bar) │
    └──────────────────────────────────────────────┘

Two modes, tracked by self._is_live:

  LIVE     — the slider is at the newest revision; the editor is editable
             and auto-saves on typing pauses (stage 2 behavior).
  HISTORY  — the slider is on an older revision; the editor shows that
             state READ-ONLY.  "Restore this version" appends the viewed
             text as a new revision (origin='restore'); nothing in history
             is ever rewritten (DESIGN.md section 5).

Guard rails worth knowing about:
  * Leaving live mode auto-saves first, so unsaved words are captured
    before the view is replaced with history.
  * Auto-save and window-close saving only act in live mode — the editor
    can never accidentally save an OLD state as if it were new typing.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QAction,
    QKeySequence,
    QPalette,
    QTextCharFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from wordvault.editor.age_colors import age_color, age_rank, line_birth_indices
from wordvault.editor.editor_pane import EditorPane
from wordvault.editor.info_panel import InfoPanel, LibraryInfoPanel
from wordvault.editor.outline import OutlinePane, section_bounds
from wordvault.editor.timeline import TimelineBar
from wordvault.models import Document, Revision
from wordvault.storage.store import DocumentStore


def _local_time(iso_utc: str) -> str:
    """Display helper: stored UTC ISO timestamp -> local human time."""
    return datetime.fromisoformat(iso_utc).astimezone().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


class MainWindow(QMainWindow):
    """Top-level window; owns the store and the currently open document."""

    def __init__(
        self,
        library_path: Union[str, Path],
        passphrase: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)

        # The one and only door to the database (DESIGN.md section 3).
        # passphrase (stage 9): set when the library is SQLCipher-encrypted;
        # kept for reopen after restore/encrypt operations.
        self._library_path = Path(library_path)
        self._passphrase = passphrase
        self._store = DocumentStore(library_path, passphrase=passphrase)
        self._current_doc: Optional[Document] = None
        self._revisions: list[Revision] = []  # open document's history cache
        self._is_live = True       # see module docstring
        self._navigating = False   # re-entrancy guard for slider handling
        self._search_dialog = None  # created on first Ctrl+Shift+F, then reused

        self.setWindowTitle("WordVault")
        self.resize(1000, 700)

        self._build_central_area()
        self._build_library_dock()
        self._build_side_panels()
        self._build_menu()
        self._build_toolbar()
        self._build_status_bar()

        # Persisted preferences (auto-save pause, font size) — QSettings
        # stores them per user on both Windows and Linux.
        from PyQt6.QtCore import QSettings

        self._settings = QSettings("WordVault", "WordVault")
        self._editor.set_idle_ms(
            int(self._settings.value("idle_ms", EditorPane.IDLE_MS))
        )
        self._editor.set_font_point_size(
            int(self._settings.value("font_pt", 12))
        )
        # Restore the persisted View toggles.
        if self._settings.value("line_numbers", False, type=bool):
            self._line_numbers_action.setChecked(True)
        if self._settings.value("spelling", False, type=bool):
            self._spelling_action.setChecked(True)

        self._reload_document_list()
        self._set_editor_enabled(False)  # nothing open yet

    # ------------------------------------------------------------------ UI --

    def _build_central_area(self) -> None:
        """Central widget: editor pane on top, timeline bar underneath."""
        self._editor = EditorPane(self)
        self._editor.pause_detected.connect(self._autosave)
        self._editor.textChanged.connect(self._update_status)
        self._editor.cursorPositionChanged.connect(self._refresh_position)
        self._editor.correction_made.connect(self._on_spelling_correction)

        self._timeline = TimelineBar(self)
        self._timeline.position_changed.connect(self._on_timeline_moved)
        self._timeline.restore_requested.connect(self._on_restore)

        # Find-in-document bar (Ctrl+F), hidden until asked for.
        from wordvault.editor.find_bar import FindBar

        self._find_bar = FindBar(self._editor, self)

        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._editor, stretch=1)
        layout.addWidget(self._find_bar)
        layout.addWidget(self._timeline)
        self.setCentralWidget(container)

    def _build_library_dock(self) -> None:
        """Left dock: tag filter + the document list."""
        self._tag_filter = QComboBox(self)
        self._tag_filter.addItem("All documents")
        self._tag_filter.currentTextChanged.connect(
            lambda _t: self._reload_document_list()
        )

        self._doc_list = QListWidget(self)
        self._doc_list.itemActivated.connect(self._on_document_activated)

        container = QWidget(self)
        box = QVBoxLayout(container)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self._tag_filter)
        box.addWidget(self._doc_list)

        dock = QDockWidget("Library", self)
        dock.setWidget(container)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self._reload_tag_filter()

    def _build_side_panels(self) -> None:
        """Stage 7 docks: outline (left, under the library) and info panel
        (right).  Both closable — View menu brings them back."""
        self._outline = OutlinePane(self)
        self._outline.heading_activated.connect(self._on_heading_activated)
        self._outline_dock = QDockWidget("Outline", self)
        self._outline_dock.setWidget(self._outline)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._outline_dock)

        self._info_panel = InfoPanel(self)
        self._info_panel.edit_tags_requested.connect(self._on_edit_tags)
        self._info_dock = QDockWidget("Document Info", self)
        self._info_dock.setWidget(self._info_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._info_dock)

        # Library-wide facts, below the document panel.
        self._library_panel = LibraryInfoPanel(self)
        self._library_dock = QDockWidget("Library Info", self)
        self._library_dock.setWidget(self._library_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,
                           self._library_dock)
        self._refresh_library_info()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        new_action = QAction("&New Document…", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)   # Ctrl+N
        new_action.triggered.connect(self._on_new_document)
        file_menu.addAction(new_action)

        save_action = QAction("&Save Revision Now", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)  # Ctrl+S
        save_action.triggered.connect(self._autosave)
        file_menu.addAction(save_action)

        close_action = QAction("&Close Document", self)
        close_action.setShortcut("Ctrl+W")
        close_action.triggered.connect(self._on_close_document)
        file_menu.addAction(close_action)

        # Recently opened documents; rebuilt each time the menu opens.
        self._recent_menu = file_menu.addMenu("&Recent")
        self._recent_menu.aboutToShow.connect(self._rebuild_recent_menu)

        file_menu.addSeparator()

        import_action = QAction("&Import .wvdoc…", self)
        import_action.triggered.connect(self._on_import_wvdoc)
        file_menu.addAction(import_action)

        file_menu.addSeparator()

        print_action = QAction("&Print Document…", self)
        print_action.setShortcut("Ctrl+Shift+P")
        print_action.triggered.connect(self._on_print)
        file_menu.addAction(print_action)

        page_setup_action = QAction("Page Se&tup…", self)
        page_setup_action.triggered.connect(self._on_page_setup)
        file_menu.addAction(page_setup_action)

        file_menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)  # closeEvent saves first
        file_menu.addAction(quit_action)

        # --- Edit menu: clipboard, Markdown commands, gather marking ---
        edit_menu = self.menuBar().addMenu("&Edit")

        def add_edit(text, shortcut, slot):
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(slot)
            edit_menu.addAction(action)
            return action

        add_edit("&Undo", QKeySequence.StandardKey.Undo, lambda: self._editor.undo())
        add_edit("&Redo", QKeySequence.StandardKey.Redo, lambda: self._editor.redo())
        edit_menu.addSeparator()
        add_edit("Cu&t", QKeySequence.StandardKey.Cut, lambda: self._editor.cut())
        add_edit("&Copy", QKeySequence.StandardKey.Copy, lambda: self._editor.copy())
        add_edit("&Paste", QKeySequence.StandardKey.Paste, lambda: self._editor.paste())
        add_edit("Select &All", QKeySequence.StandardKey.SelectAll,
                 lambda: self._editor.selectAll())
        edit_menu.addSeparator()

        # Markdown commands — they simply type the plain-text conventions.
        add_edit("&Bold", "Ctrl+B",
                 lambda: self._editor.toggle_inline_marks("**"))
        add_edit("&Italic", "Ctrl+I",
                 lambda: self._editor.toggle_inline_marks("*"))
        add_edit("Heading &1", "Ctrl+1", lambda: self._editor.set_heading_level(1))
        add_edit("Heading &2", "Ctrl+2", lambda: self._editor.set_heading_level(2))
        add_edit("Heading &3", "Ctrl+3", lambda: self._editor.set_heading_level(3))
        add_edit("Remove &Heading", "Ctrl+0",
                 lambda: self._editor.set_heading_level(0))
        add_edit("Toggle Bullet &List", "Ctrl+Shift+L",
                 lambda: self._editor.toggle_line_prefix("- "))
        add_edit("Toggle &Quote", "Ctrl+Shift+Q",
                 lambda: self._editor.toggle_line_prefix("> "))
        edit_menu.addSeparator()

        mark_action = QAction("&Mark Selection for Gather", self)
        mark_action.setShortcut("Ctrl+M")
        mark_action.triggered.connect(self._on_mark_for_gather)
        edit_menu.addAction(mark_action)

        # --- Document menu: everything about the OPEN document ---
        doc_menu = self.menuBar().addMenu("&Document")

        goto_action = QAction("&Go to Document…", self)
        goto_action.setShortcut("Ctrl+P")
        goto_action.triggered.connect(self._on_quick_open)
        doc_menu.addAction(goto_action)

        find_action = QAction("&Find in Document", self)
        find_action.setShortcut("Ctrl+F")
        find_action.triggered.connect(lambda: self._find_bar.open_bar())
        doc_menu.addAction(find_action)

        doc_menu.addSeparator()

        rename_action = QAction("&Rename Document…", self)
        rename_action.triggered.connect(self._on_rename_document)
        doc_menu.addAction(rename_action)

        tags_action = QAction("Edit &Tags…", self)
        tags_action.triggered.connect(self._on_edit_tags)
        doc_menu.addAction(tags_action)

        doc_menu.addSeparator()

        prev_ver_action = QAction("&Previous Version", self)
        prev_ver_action.setShortcut("Ctrl+Alt+Left")
        prev_ver_action.triggered.connect(lambda: self._on_step_version(-1))
        doc_menu.addAction(prev_ver_action)

        next_ver_action = QAction("&Next Version", self)
        next_ver_action.setShortcut("Ctrl+Alt+Right")
        next_ver_action.triggered.connect(lambda: self._on_step_version(+1))
        doc_menu.addAction(next_ver_action)

        doc_menu.addSeparator()

        verses_action = QAction("Documents Sharing &Verses…", self)
        verses_action.setShortcut("Ctrl+Shift+V")
        verses_action.triggered.connect(self._on_shared_verses)
        doc_menu.addAction(verses_action)

        export_action = QAction("&Export as .wvdoc…", self)
        export_action.triggered.connect(self._on_export_wvdoc)
        doc_menu.addAction(export_action)

        # --- View menu: age colors, focus mode, panels (stage 7) ---
        view_menu = self.menuBar().addMenu("&View")

        self._age_action = QAction("Color Text by &Age", self)
        self._age_action.setCheckable(True)
        self._age_action.setShortcut("Ctrl+Shift+A")
        self._age_action.toggled.connect(lambda _on: self._apply_age_colors())
        view_menu.addAction(self._age_action)

        md_action = QAction("&Markdown Styling", self)
        md_action.setCheckable(True)
        md_action.setChecked(True)
        md_action.toggled.connect(self._on_toggle_markdown_styling)
        view_menu.addAction(md_action)

        self._line_numbers_action = QAction("Line &Numbers", self)
        self._line_numbers_action.setCheckable(True)
        self._line_numbers_action.toggled.connect(
            lambda on: (self._editor.set_line_numbers_visible(on),
                        self._settings.setValue("line_numbers", on))
        )
        view_menu.addAction(self._line_numbers_action)

        self._spelling_action = QAction("Check &Spelling", self)
        self._spelling_action.setCheckable(True)
        self._spelling_action.toggled.connect(self._on_toggle_spelling)
        view_menu.addAction(self._spelling_action)

        view_menu.addSeparator()

        focus_action = QAction("&Focus Current Section", self)
        focus_action.setShortcut("Ctrl+Shift+H")   # H for hoist
        focus_action.triggered.connect(self._on_focus_section)
        view_menu.addAction(focus_action)

        unfocus_action = QAction("Show &Whole Document", self)
        unfocus_action.setShortcut("Ctrl+Shift+U")
        unfocus_action.triggered.connect(self._on_unfocus)
        view_menu.addAction(unfocus_action)

        view_menu.addSeparator()
        # The docks provide their own show/hide toggle actions.
        view_menu.addAction(self._outline_dock.toggleViewAction())
        view_menu.addAction(self._info_dock.toggleViewAction())

        # --- Library menu: search, gather, review (stages 5-6) ---
        library_menu = self.menuBar().addMenu("&Library")

        import_folder_action = QAction("&Import .docx Folder…", self)
        import_folder_action.setShortcut("Ctrl+Shift+I")
        import_folder_action.triggered.connect(self._on_import_folder)
        library_menu.addAction(import_folder_action)

        library_menu.addSeparator()

        search_action = QAction("&Search Library…", self)
        search_action.setShortcut("Ctrl+Shift+F")
        search_action.triggered.connect(self._on_search)
        library_menu.addAction(search_action)

        gather_action = QAction("&Gather Tray…", self)
        gather_action.setShortcut("Ctrl+Shift+G")
        gather_action.triggered.connect(self._on_gather_tray)
        library_menu.addAction(gather_action)

        review_action = QAction("&Review Version Groups…", self)
        review_action.setShortcut("Ctrl+G")
        review_action.triggered.connect(self._on_review_groups)
        library_menu.addAction(review_action)

        library_menu.addSeparator()

        # --- library-level safety: backup, restore, encryption (moved
        # here from File — they act on the LIBRARY, as the menu says) ---
        backup_action = QAction("&Back Up Library…", self)
        backup_action.triggered.connect(self._on_backup)
        library_menu.addAction(backup_action)

        restore_action = QAction("Rest&ore Library from Backup…", self)
        restore_action.triggered.connect(self._on_restore_library)
        library_menu.addAction(restore_action)

        library_menu.addSeparator()

        self._encrypt_action = QAction("&Encrypt Library…", self)
        self._encrypt_action.triggered.connect(self._on_encrypt_library)
        library_menu.addAction(self._encrypt_action)

        self._change_pw_action = QAction("&Change Library Passphrase…", self)
        self._change_pw_action.triggered.connect(self._on_change_passphrase)
        library_menu.addAction(self._change_pw_action)

        self._decrypt_action = QAction("Remove Library Encr&yption…", self)
        self._decrypt_action.triggered.connect(self._on_decrypt_library)
        library_menu.addAction(self._decrypt_action)
        self._update_encryption_actions()

        # --- History menu: the time-travel keys (stage 3) ---
        history_menu = self.menuBar().addMenu("&History")

        back_action = QAction("&Back in Time", self)
        back_action.setShortcut("Alt+Left")
        back_action.triggered.connect(lambda: self._timeline.step(-1))
        history_menu.addAction(back_action)

        fwd_action = QAction("&Forward in Time", self)
        fwd_action.setShortcut("Alt+Right")
        fwd_action.triggered.connect(lambda: self._timeline.step(+1))
        history_menu.addAction(fwd_action)

        newest_action = QAction("Jump to &Newest", self)
        newest_action.setShortcut("Alt+Home")
        newest_action.triggered.connect(self._timeline.go_newest)
        history_menu.addAction(newest_action)

        history_menu.addSeparator()

        restore_action = QAction("&Restore This Version", self)
        restore_action.setShortcut("Ctrl+R")
        restore_action.triggered.connect(self._on_restore)
        history_menu.addAction(restore_action)

    def _build_toolbar(self) -> None:
        """The Help menu (after History): Help (F1) and Settings.
        These used to be toolbar buttons in the top-right corner as well,
        but the duplication was clutter — the menu is enough."""
        help_action = QAction("WordVault &Help", self)
        help_action.setShortcut("F1")
        help_action.setToolTip("How WordVault works — the concept and the use (F1)")
        help_action.triggered.connect(self._on_help)

        settings_action = QAction("&Settings…", self)
        settings_action.setToolTip(
            "Auto-save pause, font size, and library encryption"
        )
        settings_action.triggered.connect(self._on_settings)

        habits_action = QAction("My Spelling Ha&bits…", self)
        habits_action.setToolTip(
            "What kinds of spelling fixes you make — a running mirror"
        )
        habits_action.triggered.connect(self._on_spelling_habits)

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(help_action)
        help_menu.addAction(habits_action)
        help_menu.addAction(settings_action)

    def _on_help(self) -> None:
        from wordvault.editor.help_dialog import HelpDialog

        HelpDialog(self).exec()

    def _on_settings(self) -> None:
        """Open Settings; apply and persist whatever was chosen."""
        from PyQt6.QtWidgets import QDialog

        from wordvault.editor.settings_dialog import SettingsDialog

        dialog = SettingsDialog(
            self,
            encrypted=self._store.is_encrypted,
            idle_seconds=max(1, self._editor.idle_ms() // 1000),
            font_size=self._editor.font().pointSize(),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        # Everyday knobs: apply now, remember for next start.
        self._editor.set_idle_ms(dialog.idle_seconds * 1000)
        self._editor.set_font_point_size(dialog.font_size)
        self._settings.setValue("idle_ms", dialog.idle_seconds * 1000)
        self._settings.setValue("font_pt", dialog.font_size)

        # Encryption transitions (the dialog already validated the
        # matched passphrase pair when enabling).
        if dialog.wants_encryption and not self._store.is_encrypted:
            self._do_encrypt(dialog.passphrase)
        elif not dialog.wants_encryption and self._store.is_encrypted:
            answer = QMessageBox.question(
                self, "Remove Encryption",
                "The library will be stored UNENCRYPTED on disk again. "
                "Continue?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._do_decrypt()

    def _build_status_bar(self) -> None:
        """Three permanent labels: document/revisions, words, last save.
        This is the seed of the full info panel (DESIGN.md section 8)."""
        self._doc_label = QLabel("No document open")
        self._words_label = QLabel("")
        self._saved_label = QLabel("")
        self.statusBar().addWidget(self._doc_label, stretch=1)
        self.statusBar().addPermanentWidget(self._words_label)
        self.statusBar().addPermanentWidget(self._saved_label)

    # -------------------------------------------------------------- library --

    def _reload_document_list(self) -> None:
        """Refresh the dock from the store (oldest first, like the store),
        honoring the tag filter.  Documents that are later versions in a
        confirmed chain get a "↳" marker."""
        self._doc_list.clear()
        tag = self._tag_filter.currentText()
        docs = (
            self._store.list_documents()
            if tag == "All documents"
            else self._store.documents_with_tag(tag)
        )
        for doc in docs:
            prefix = "↳ " if doc.parent_doc_id is not None else ""
            item = QListWidgetItem(prefix + doc.title)
            item.setData(Qt.ItemDataRole.UserRole, doc.id)
            self._doc_list.addItem(item)
        # The list changing usually means the library changed too — keep
        # the Library Info panel honest (guard: panel builds after dock).
        if hasattr(self, "_library_panel"):
            self._refresh_library_info()

    def _reload_tag_filter(self) -> None:
        """Rebuild the tag combo, keeping the current choice if it survives."""
        current = self._tag_filter.currentText()
        self._tag_filter.blockSignals(True)
        self._tag_filter.clear()
        self._tag_filter.addItem("All documents")
        for tag in self._store.list_tags():
            self._tag_filter.addItem(tag.name)
        index = self._tag_filter.findText(current)
        self._tag_filter.setCurrentIndex(index if index >= 0 else 0)
        self._tag_filter.blockSignals(False)

    def _on_review_groups(self) -> None:
        """Open the version-group review screen (imported lazily so the
        editor starts fast even with many pending groups)."""
        from wordvault.editor.review import ReviewDialog

        self._autosave()  # decisions may re-order the library; save first
        ReviewDialog(self._store, self).exec()
        self._reload_document_list()  # chain markers may have changed

    # ------------------------------------------- search & gather (stage 6) --

    def _on_search(self) -> None:
        """Open (or re-focus) the non-modal library search dialog."""
        from wordvault.editor.search_dialog import SearchDialog

        self._autosave()  # search runs over STORED text; capture the latest
        if self._search_dialog is None:
            self._search_dialog = SearchDialog(
                self._store,
                current_doc_id=lambda: (
                    self._current_doc.id if self._current_doc else None
                ),
                parent=self,
            )
            self._search_dialog.open_requested.connect(self._open_at)
            self._search_dialog.replacements_applied.connect(
                self._after_replacements
            )
        self._search_dialog.show()
        self._search_dialog.raise_()
        self._search_dialog.activateWindow()

    def _open_at(self, doc_id: int, start: int, end: int) -> None:
        """Open a document and select the span a search hit points at."""
        if self._current_doc is None or self._current_doc.id != doc_id:
            self._autosave()
            self._open_document(doc_id)
        cursor = self._editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self._editor.setTextCursor(cursor)
        self._editor.centerCursor()
        self.raise_()
        self._editor.setFocus()

    def _after_replacements(self) -> None:
        """A replace batch ran: the open document may have a new revision."""
        if self._current_doc is not None and self._is_live:
            self._go_live()   # reload newest text + timeline range
        self._reload_document_list()

    def _on_mark_for_gather(self) -> None:
        """Ctrl+M: snapshot the selected text into the gather tray."""
        if self._current_doc is None:
            return
        cursor = self._editor.textCursor()
        if not cursor.hasSelection():
            self.statusBar().showMessage(
                "Select a passage first, then press Ctrl+M to mark it.", 4000
            )
            return
        # Save so the marked offsets refer to a stored revision.
        self._autosave()
        latest = self._store.latest_revision(self._current_doc.id)
        self._store.add_gather_item(
            self._current_doc.id,
            latest.id,
            # QTextCursor.selectedText() uses U+2029 as its paragraph
            # separator; convert to real newlines for storage.
            cursor.selectedText().replace(" ", "\n"),
            cursor.selectionStart(),
            cursor.selectionEnd(),
        )
        count = len(self._store.list_gather_items())
        self.statusBar().showMessage(
            f"Marked for gather — {count} passage"
            + ("s" if count != 1 else "") + " in the tray (Ctrl+Shift+G).",
            4000,
        )

    def _on_gather_tray(self) -> None:
        """Open the gather tray; on Gather, show the new document."""
        from wordvault.editor.gather_dialog import GatherDialog

        dialog = GatherDialog(self._store, self)
        dialog.gathered.connect(self._on_gathered)
        dialog.exec()

    def _on_gathered(self, doc_id: int) -> None:
        self._reload_document_list()
        self._autosave()
        self._open_document(doc_id)

    def _on_new_document(self) -> None:
        """Ask for a title, create the document, and open it."""
        title, ok = QInputDialog.getText(self, "New Document", "Title:")
        if not ok or not title.strip():
            return
        self._autosave()  # capture the previous document before switching
        doc = self._store.create_document(title.strip())
        self._reload_document_list()
        self._open_document(doc.id)

    def _on_document_activated(self, item: QListWidgetItem) -> None:
        doc_id = item.data(Qt.ItemDataRole.UserRole)
        if self._current_doc and self._current_doc.id == doc_id:
            return  # already open
        self._autosave()  # never lose the outgoing document's last words
        self._open_document(doc_id)

    def _open_document(self, doc_id: int) -> None:
        """Load a document's newest text into the editor, in live mode."""
        self._current_doc = self._store.get_document(doc_id)
        self._record_recent(doc_id)   # feeds File ▸ Recent
        self._go_live()
        self._set_editor_enabled(True)
        self._editor.setFocus()

    # -------------------------------------------------- time travel (new) --

    def _go_live(self) -> None:
        """Show the newest revision, editable; park the slider at the end."""
        assert self._current_doc is not None
        self._revisions = self._store.list_revisions(self._current_doc.id)
        self._is_live = True

        self._editor.set_text_quietly(
            self._store.get_text(self._revisions[-1].id) if self._revisions else ""
        )
        self._editor.setReadOnly(False)

        self._timeline.set_range(len(self._revisions), len(self._revisions) - 1)
        self._timeline.set_live(True)
        self._timeline.set_info(
            _local_time(self._revisions[-1].created_utc) + " · newest"
            if self._revisions else "no revisions yet"
        )
        self._update_status()
        # Stage 7 panels track the live document.
        self._editor.clear_focus_lines()
        self._refresh_outline()
        self._refresh_info()
        self._apply_age_colors()

    def _on_timeline_moved(self, index: int) -> None:
        """The user moved the slider (drag, Alt+arrows, or Newest button)."""
        if self._navigating or self._current_doc is None:
            return
        self._navigating = True
        try:
            # Leaving live mode: capture unsaved words FIRST, so replacing
            # the editor's content with history cannot lose anything.
            if self._is_live:
                self._commit_live_text()

            self._revisions = self._store.list_revisions(self._current_doc.id)
            if not self._revisions:
                return
            index = max(0, min(index, len(self._revisions) - 1))
            live = index == len(self._revisions) - 1

            rev = self._revisions[index]
            self._editor.set_text_quietly(self._store.get_text(rev.id))
            self._editor.setReadOnly(not live)
            self._is_live = live

            # Keep the slider consistent with the (possibly grown) history.
            self._timeline.set_range(len(self._revisions), index)
            self._timeline.set_live(live)
            self._timeline.set_info(
                _local_time(rev.created_utc)
                + (" · newest" if live else f" · {rev.origin}")
            )
            self._update_status()
            # Hoist and age tinting refer to the LIVE text; entering
            # history clears both (age colors return on going live).
            self._editor.clear_focus_lines()
            self._refresh_outline()
            self._apply_age_colors()
        finally:
            self._navigating = False

    def _on_restore(self) -> None:
        """Append the currently VIEWED old state as a brand-new revision.
        History stays intact; the old state simply becomes the newest."""
        if self._is_live or self._current_doc is None:
            return  # nothing to restore when already viewing the newest
        self._store.save_revision(
            self._current_doc.id, self._editor.toPlainText(), origin="restore"
        )
        self._saved_label.setText("restored " + datetime.now().strftime("%H:%M:%S"))
        self._go_live()

    def _on_import_folder(self) -> None:
        """Library ▸ Import .docx Folder: run the ingest pipeline right
        from the editor — one place for everything.

        Incremental by design: files already in the library are skipped,
        so pointing this at the same folder after adding a new
        subdirectory imports just the new files."""
        from PyQt6.QtWidgets import QApplication, QFileDialog, QProgressDialog

        try:
            import docx  # noqa: F401 — the importer needs python-docx
        except ImportError:
            QMessageBox.warning(
                self, "Import",
                "The importer needs the python-docx package.\n"
                "Install it with:  pip install python-docx"
            )
            return

        start_dir = str(self._settings.value(
            "ingest_dir", str(Path.home() / "Documents")
        ))
        folder = QFileDialog.getExistingDirectory(
            self, "Import .docx Folder (searched recursively)", start_dir
        )
        if not folder:
            return
        self._settings.setValue("ingest_dir", folder)

        # Optional archive: keep a copy of every file that becomes a
        # document, so the database's sources are gathered in one place.
        archive_dir = Path.home() / ".wordvault" / "ingested_originals"
        keep_copies = QMessageBox.question(
            self, "Import",
            "Keep a copy of each imported file in the archive folder?\n\n"
            f"{archive_dir}\n\n"
            "(Files are named '<document id> - <filename>' so the copy "
            "matching any document is easy to find.)",
        ) == QMessageBox.StandardButton.Yes

        self._autosave()

        # Indeterminate progress dialog; WindowModal blocks the editor so
        # nothing can edit the database mid-import, while tick() keeps the
        # dialog painting between the pipeline's progress messages.
        progress = QProgressDialog("Scanning folder…", None, 0, 0, self)
        progress.setWindowTitle("Importing")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        from wordvault.ingest import Ingestor

        def say(message: str) -> None:
            progress.setLabelText(message)
            QApplication.processEvents()

        try:
            stats = Ingestor(
                self._store,
                progress=say,
                archive_dir=archive_dir if keep_copies else None,
                tick=QApplication.processEvents,
            ).ingest_folder(folder)
        except Exception as exc:
            progress.close()
            QMessageBox.warning(self, "Import", str(exc))
            return
        progress.close()

        self._reload_document_list()
        self._refresh_library_info()
        message = stats.summary()
        if stats.groups_proposed:
            message += (
                "\n\nProposed version groups await review "
                "(Library ▸ Review Version Groups, Ctrl+G)."
            )
        QMessageBox.information(self, "Import finished", message)

    # ------------------------------------------- File menu additions -------

    def _on_close_document(self) -> None:
        """Ctrl+W: save and put the editor back to 'nothing open'."""
        if self._current_doc is None:
            return
        self._autosave()
        self._current_doc = None
        self._revisions = []
        self._is_live = True
        self._set_editor_enabled(False)
        self._info_panel.clear()
        self._outline.set_outline([])
        self._timeline.set_range(0, 0)
        self._update_status()

    def _record_recent(self, doc_id: int) -> None:
        """Move doc_id to the front of the persisted recents (max 10)."""
        recent = [int(x) for x in self._settings.value("recent_docs", []) or []]
        recent = [doc_id] + [d for d in recent if d != doc_id]
        self._settings.setValue("recent_docs", [str(d) for d in recent[:10]])

    def _rebuild_recent_menu(self) -> None:
        """Fill File ▸ Recent when it opens (titles resolved fresh)."""
        self._recent_menu.clear()
        recent = [int(x) for x in self._settings.value("recent_docs", []) or []]
        shown = 0
        for doc_id in recent:
            try:
                doc = self._store.get_document(doc_id)
            except KeyError:
                continue  # e.g. a different library than last session
            action = self._recent_menu.addAction(doc.title)
            action.triggered.connect(
                lambda _c, d=doc_id: (self._autosave(), self._open_document(d))
            )
            shown += 1
        if not shown:
            self._recent_menu.addAction("(no recent documents)").setEnabled(False)

    def _ensure_printer(self):
        """One QPrinter shared by Print and Page Setup, made on demand."""
        from PyQt6.QtPrintSupport import QPrinter

        if not hasattr(self, "_printer"):
            self._printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        return self._printer

    def _on_page_setup(self) -> None:
        from PyQt6.QtPrintSupport import QPageSetupDialog

        QPageSetupDialog(self._ensure_printer(), self).exec()

    def _on_print(self) -> None:
        """File ▸ Print: the open document to a local printer (or PDF)."""
        from PyQt6.QtPrintSupport import QPrintDialog

        if self._current_doc is None:
            QMessageBox.information(self, "Print", "Open a document first.")
            return
        self._autosave()
        printer = self._ensure_printer()
        printer.setDocName(self._current_doc.title)
        dialog = QPrintDialog(printer, self)
        if dialog.exec():
            # Prints the text as displayed (Markdown styling included);
            # QTextDocument handles pagination and margins from Page Setup.
            self._editor.document().print(printer)
            self.statusBar().showMessage("Sent to printer.", 5000)

    # ----------------------------------------------- View menu additions ---

    def _on_toggle_spelling(self, on: bool) -> None:
        """View ▸ Check Spelling: squiggles + right-click suggestions."""
        from wordvault.editor.spelling import get_spelling

        if on and not get_spelling().is_available():
            QMessageBox.information(
                self, "Spelling",
                "Spell checking needs the pyspellchecker package.\n"
                "Install it with:  pip install pyspellchecker\n"
                "then restart WordVault."
            )
            self._spelling_action.setChecked(False)
            return
        self._editor.markdown_highlighter.spelling_enabled = on
        self._editor.markdown_highlighter.rehighlight()
        self._settings.setValue("spelling", on)

    # ------------------------------------------- spelling-habits watcher ---

    def _on_spelling_correction(self, typed: str, corrected: str) -> None:
        """A misspelled word was fixed (menu click or hand edit): classify
        and log it for the habits report."""
        from wordvault.editor.spelling import classify_error

        kind, detail = classify_error(typed, corrected)
        self._store.log_spelling_fix(
            self._current_doc.id if self._current_doc else None,
            typed, corrected, kind, detail,
        )

    def _on_spelling_habits(self) -> None:
        """Help ▸ My Spelling Habits: the running mirror of error kinds."""
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser

        kinds, pairs = self._store.spelling_summary()
        recent = self._store.spelling_history(15)

        lines = ["# My Spelling Habits\n"]
        if not kinds:
            lines.append(
                "No corrections recorded yet. Turn on **View ▸ Check "
                "Spelling** and fix flagged words — by right-click "
                "suggestion or by hand — and each fix is noted here."
            )
        else:
            total = sum(n for _k, n in kinds)
            lines.append(f"**{total} corrections observed.** By error kind:\n")
            for kind, n in kinds:
                lines.append(f"- **{kind}** — {n} ({100 * n // total}%)")
            if pairs:
                lines.append("\n**Most-repeated fixes:**\n")
                for t, c, n in pairs:
                    times = f"{n}×" if n > 1 else "once"
                    lines.append(f"- {t} → {c} ({times})")
            if recent:
                lines.append("\n**Recent:**\n")
                for r in recent:
                    lines.append(
                        f"- {r['created_utc'][:10]}: {r['typed']} → "
                        f"{r['corrected']} ({r['kind']})"
                    )
            lines.append(
                "\n*Vowel swaps and dropped silent letters are 'writing "
                "by ear' — seeing them here is what builds the habit of "
                "catching them.*"
            )

        dialog = QDialog(self)
        dialog.setWindowTitle("My Spelling Habits")
        dialog.resize(560, 520)
        viewer = QTextBrowser(dialog)
        viewer.setMarkdown("\n".join(lines))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout = QVBoxLayout(dialog)
        layout.addWidget(viewer)
        layout.addWidget(buttons)
        dialog.exec()

    # ------------------------------------------------ library info panel ---

    def _refresh_library_info(self) -> None:
        """Push library-wide facts into the Library Info panel."""
        docs = self._store.list_documents()
        try:
            size = self._library_path.stat().st_size
        except OSError:
            size = 0
        oldest = (_local_time(docs[0].created_utc)[:10] if docs else "—")
        self._library_panel.update_info(
            documents=len(docs),
            revisions=self._store.revision_count(),
            size_bytes=size,
            oldest=oldest,
            encrypted=self._store.is_encrypted,
            file_name=self._library_path.name,
            location=str(self._library_path.parent),
        )

    # ---------------------------------------------- Document menu handlers --

    def _on_quick_open(self) -> None:
        """Ctrl+P: type-ahead chooser; open the picked document."""
        from wordvault.editor.quick_open import QuickOpenDialog

        dialog = QuickOpenDialog(self._store, self)
        if dialog.exec() and dialog.selected_doc_id is not None:
            if (self._current_doc is None
                    or self._current_doc.id != dialog.selected_doc_id):
                self._autosave()
                self._open_document(dialog.selected_doc_id)

    def _on_rename_document(self) -> None:
        """Rename the open document (title is metadata, not history)."""
        if self._current_doc is None:
            QMessageBox.information(self, "Rename", "Open a document first.")
            return
        title, ok = QInputDialog.getText(
            self, "Rename Document", "New title:",
            text=self._current_doc.title,
        )
        if not ok or not title.strip() or title == self._current_doc.title:
            return
        self._store.rename_document(self._current_doc.id, title.strip())
        self._current_doc = self._store.get_document(self._current_doc.id)
        self._reload_document_list()
        self._refresh_info()
        self.statusBar().showMessage("Renamed.", 4000)

    def _on_step_version(self, direction: int) -> None:
        """Ctrl+Alt+Left/Right: open the previous/next draft in the
        document's confirmed version chain."""
        if self._current_doc is None:
            return
        chain = self._store.version_chain(self._current_doc.id)
        if len(chain) < 2:
            self.statusBar().showMessage(
                "This document has no linked versions "
                "(chains are made in Library ▸ Review Version Groups).", 6000
            )
            return
        index = next(i for i, d in enumerate(chain)
                     if d.id == self._current_doc.id)
        target = index + direction
        if not 0 <= target < len(chain):
            self.statusBar().showMessage(
                "Already at the " + ("oldest" if direction < 0 else "newest")
                + " draft of this chain.", 4000
            )
            return
        self._autosave()
        self._open_document(chain[target].id)
        self.statusBar().showMessage(
            f"Draft {target + 1} of {len(chain)} in this chain.", 4000
        )

    def _on_shared_verses(self) -> None:
        """Library ▸ Documents Sharing Verses: rank other documents by how
        many Bible verses they cite in common with the open one — the
        scripture-based identification signal."""
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox

        if self._current_doc is None:
            QMessageBox.information(
                self, "Shared Verses", "Open a document first."
            )
            return
        self._autosave()   # index the latest words before comparing
        matches = self._store.documents_sharing_verses(self._current_doc.id)
        if not matches:
            QMessageBox.information(
                self, "Shared Verses",
                "No other document shares Bible citations with this one "
                "(or this document cites no verses yet).\n\n"
                "Tip: run tools/reindex_library.py once to index documents "
                "imported before this feature existed."
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(
            f"Documents sharing verses with “{self._current_doc.title}”"
        )
        dialog.resize(640, 460)
        listing = QListWidget(dialog)
        for doc, count in matches:
            sample = ", ".join(
                self._store.shared_verses(self._current_doc.id, doc.id)[:4]
            )
            item = QListWidgetItem(
                f"{doc.title} — {count} shared verse"
                + ("s" if count != 1 else "") + f"  ({sample}…)"
            )
            item.setData(Qt.ItemDataRole.UserRole, doc.id)
            listing.addItem(item)

        def open_selected(item: QListWidgetItem) -> None:
            dialog.accept()
            self._open_document(item.data(Qt.ItemDataRole.UserRole))

        listing.itemActivated.connect(open_selected)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Double-click a document to open it.", dialog))
        layout.addWidget(listing)
        layout.addWidget(buttons)
        dialog.exec()

    # ------------------------------------ writing environment (stage 7) ----

    def _apply_age_colors(self) -> None:
        """Tint each line by the revision that introduced it (View menu
        toggle).  Only meaningful in live mode; history views and disabled
        state simply clear the tinting.

        Cost note: this replays the document's history (bounded by the
        snapshot policy).  For essays it is instant; for a book with a very
        long history the first application can take a moment — which is
        why it is a toggle and not always on."""
        if (
            not self._age_action.isChecked()
            or self._current_doc is None
            or not self._is_live
            or not self._revisions
        ):
            self._editor.setExtraSelections([])
            return

        texts = [self._store.get_text(r.id) for r in self._revisions]
        ages = line_birth_indices(texts)
        newest = self._editor.palette().color(QPalette.ColorRole.Text)
        doc = self._editor.document()

        selections = []
        row = 0
        while row < len(ages):
            # Group consecutive lines born in the same revision: one
            # ExtraSelection per run keeps the list small.
            start = row
            while row + 1 < len(ages) and ages[row + 1] == ages[start]:
                row += 1
            rank = age_rank(ages[start], len(texts))
            if rank < 0.999 and start < doc.blockCount():
                fmt = QTextCharFormat()
                fmt.setForeground(age_color(rank, newest))
                cursor = QTextCursor(doc.findBlockByNumber(start))
                end_block = doc.findBlockByNumber(min(row, doc.blockCount() - 1))
                cursor.setPosition(
                    end_block.position() + max(end_block.length() - 1, 0),
                    QTextCursor.MoveMode.KeepAnchor,
                )
                sel = QTextEdit.ExtraSelection()
                sel.cursor = cursor
                sel.format = fmt
                selections.append(sel)
            row += 1
        self._editor.setExtraSelections(selections)

    def _on_toggle_markdown_styling(self, enabled: bool) -> None:
        """View ▸ Markdown Styling: attach/detach the highlighter.  The
        text itself is identical either way — only the display changes."""
        highlighter = self._editor.markdown_highlighter
        if enabled:
            highlighter.setDocument(self._editor.document())
            highlighter.rehighlight()
        else:
            highlighter.setDocument(None)

    def _refresh_outline(self) -> None:
        """Rebuild the document map from the current text."""
        from wordvault.editor.outline import parse_outline

        self._outline.set_outline(
            parse_outline(self._editor.toPlainText())
            if self._current_doc is not None else []
        )

    def _on_heading_activated(self, line: int) -> None:
        """Outline click: jump the cursor to that heading."""
        doc = self._editor.document()
        if line < doc.blockCount():
            cursor = self._editor.textCursor()
            cursor.setPosition(doc.findBlockByNumber(line).position())
            self._editor.setTextCursor(cursor)
            self._editor.centerCursor()
            self._editor.setFocus()

    def _on_focus_section(self) -> None:
        """Ctrl+Shift+H: hoist — show only the section under the cursor."""
        if self._current_doc is None:
            return
        first, last = section_bounds(
            self._editor.toPlainText(),
            self._editor.textCursor().blockNumber(),
        )
        self._editor.set_focus_lines(first, last)
        self.statusBar().showMessage(
            "Focused on this section — Ctrl+Shift+U shows the whole document.",
            6000,
        )

    def _on_unfocus(self) -> None:
        self._editor.clear_focus_lines()

    def _refresh_info(self) -> None:
        """Push document-level facts into the info panel."""
        if self._current_doc is None:
            self._info_panel.clear()
            return
        doc = self._current_doc
        chain = self._store.version_chain(doc.id)
        if len(chain) > 1:
            position = next(
                i for i, d in enumerate(chain, start=1) if d.id == doc.id
            )
            chain_text = f"draft {position} of {len(chain)}"
        else:
            chain_text = "no linked versions"
        last_edit = (
            _local_time(self._revisions[-1].created_utc)
            if self._revisions else "never"
        )
        self._info_panel.update_info(
            title=doc.title,
            chain_text=chain_text,
            created=_local_time(doc.created_utc),
            last_edited=last_edit,
            revision_count=len(self._revisions),
            word_count=len(self._editor.toPlainText().split()),
            tags=[t.name for t in self._store.tags_for(doc.id)],
            verse_count=len(self._store.verses_for(doc.id)),
        )

    def _refresh_position(self) -> None:
        """Cursor moved: update 'word X of Y' and the outline highlight."""
        if self._current_doc is None:
            return
        text = self._editor.toPlainText()
        pos = self._editor.textCursor().position()
        total = len(text.split())
        before = len(text[:pos].split())
        percent = int(100 * pos / len(text)) if text else 0
        self._info_panel.update_position(before, total, percent)
        self._outline.highlight_line(self._editor.textCursor().blockNumber())

    def _on_edit_tags(self) -> None:
        """Info panel's Edit tags: comma-separated, applied as a set."""
        if self._current_doc is None:
            return
        current = [t.name for t in self._store.tags_for(self._current_doc.id)]
        text, ok = QInputDialog.getText(
            self, "Edit Tags",
            "Tags (comma-separated), e.g. Genesis, atonement, book:",
            text=", ".join(current),
        )
        if not ok:
            return
        wanted = {t.strip() for t in text.split(",") if t.strip()}
        for name in current:
            if name not in wanted:
                self._store.remove_tag(self._current_doc.id, name)
        for name in wanted:
            if name not in current:
                self._store.add_tag(self._current_doc.id, name)
        self._reload_tag_filter()
        self._refresh_info()

    # --------------------------------------- backup & portable files (st 8) --

    def _ask_passphrase(self, confirm: bool = False) -> Optional[str]:
        """Prompt for a passphrase (hidden input).  With confirm=True the
        author types it twice — for anything being ENCRYPTED, since a
        mistyped passphrase would lock the file forever."""
        from PyQt6.QtWidgets import QInputDialog, QLineEdit

        pw, ok = QInputDialog.getText(
            self, "Passphrase", "Passphrase:", QLineEdit.EchoMode.Password
        )
        if not ok or not pw:
            return None
        if confirm:
            pw2, ok = QInputDialog.getText(
                self, "Passphrase", "Repeat passphrase:",
                QLineEdit.EchoMode.Password,
            )
            if not ok or pw2 != pw:
                QMessageBox.warning(
                    self, "Passphrase", "The passphrases did not match."
                )
                return None
        return pw

    def _on_backup(self) -> None:
        """File ▸ Back Up Library: one encrypted file, whole library."""
        from PyQt6.QtWidgets import QFileDialog

        from wordvault.storage.backup import make_backup

        self._autosave()
        suggested = f"wordvault-{datetime.now():%Y-%m-%d}.wvbackup"
        path, _ = QFileDialog.getSaveFileName(
            self, "Back Up Library", suggested,
            "WordVault backup (*.wvbackup)",
        )
        if not path:
            return
        pw = self._ask_passphrase(confirm=True)
        if pw is None:
            return
        try:
            info = make_backup(self._store, path, pw)
        except Exception as exc:
            QMessageBox.warning(self, "Backup", str(exc))
            return
        self.statusBar().showMessage(
            f"Backed up {info.documents} documents "
            f"({info.revisions} revisions) to {Path(path).name}.", 8000
        )

    def _on_restore_library(self) -> None:
        """File ▸ Restore: decrypt, show what is inside, confirm, swap in.

        NOTE the name: the timeline's revision-restore is _on_restore().
        These two once shared a name, and Python silently kept only the
        later definition — the timeline button opened this file dialog.
        Distinct names, and a test now guards against regressions."""
        from PyQt6.QtWidgets import QFileDialog

        from wordvault.storage.backup import read_backup, restore_backup

        path, _ = QFileDialog.getOpenFileName(
            self, "Restore Library from Backup", "",
            "WordVault backup (*.wvbackup)",
        )
        if not path:
            return
        pw = self._ask_passphrase()
        if pw is None:
            return
        try:
            info, _db = read_backup(path, pw)   # verifies passphrase+integrity
        except Exception as exc:
            QMessageBox.warning(self, "Restore", str(exc))
            return

        answer = QMessageBox.question(
            self, "Restore Library",
            f"This backup contains {info.documents} documents and "
            f"{info.revisions} revisions, made {info.created_utc[:19]} UTC.\n\n"
            f"Replace the current library with it?\n"
            f"(The current library file is kept beside it as "
            f"'.before-restore' until you delete it.)",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        # Swap the database file under a CLOSED store, then reopen fresh.
        self._autosave()
        self._store.close()
        try:
            restore_backup(path, pw, self._library_path,
                           library_passphrase=self._passphrase)
        finally:
            self._store = DocumentStore(self._library_path,
                                        passphrase=self._passphrase)
        self._reset_after_reopen()
        self.statusBar().showMessage("Library restored.", 8000)

    def _reset_after_reopen(self) -> None:
        """The store was closed and reopened (restore/encrypt/decrypt):
        drop every reference to the old one and show a clean slate."""
        self._current_doc = None
        self._revisions = []
        self._search_dialog = None   # held the old store; rebuild on demand
        self._reload_tag_filter()
        self._reload_document_list()
        self._set_editor_enabled(False)
        self._info_panel.clear()
        self._outline.set_outline([])
        self._update_status()
        self._update_encryption_actions()
        self._refresh_library_info()

    # ------------------------------ live-database encryption (stage 9) -----

    def _update_encryption_actions(self) -> None:
        """Enable the encryption menu items that fit the current state."""
        encrypted = self._store.is_encrypted
        self._encrypt_action.setEnabled(not encrypted)
        self._change_pw_action.setEnabled(encrypted)
        self._decrypt_action.setEnabled(encrypted)

    def _on_encrypt_library(self) -> None:
        """File ▸ Encrypt Library: warn, ask the passphrase, encrypt.
        (The Settings dialog reaches _do_encrypt directly — its checkbox
        flow already collected and verified the passphrase.)"""
        answer = QMessageBox.question(
            self, "Encrypt Library",
            "The library file itself will be encrypted with a passphrase.\n"
            "You will need this passphrase EVERY time WordVault starts —\n"
            "there is no recovery if it is forgotten.\n\nContinue?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        pw = self._ask_passphrase(confirm=True)
        if pw is None:
            return
        self._do_encrypt(pw)

    def _do_encrypt(self, pw: str) -> None:
        """Plaintext -> SQLCipher, in place, never losing the original."""
        from wordvault.storage.encryption import encrypt_library, swap_in

        self._autosave()
        self._store.close()
        tmp = self._library_path.with_name(self._library_path.name + ".tmp-enc")
        try:
            encrypt_library(self._library_path, tmp, pw)
            swap_in(tmp, self._library_path, ".before-encrypt")
        except Exception as exc:
            if tmp.exists():
                tmp.unlink()
            self._store = DocumentStore(self._library_path)  # reopen plain
            self._update_encryption_actions()
            QMessageBox.warning(self, "Encrypt Library", str(exc))
            return
        self._passphrase = pw
        self._store = DocumentStore(self._library_path, passphrase=pw)
        self._reset_after_reopen()
        self.statusBar().showMessage(
            "Library encrypted. The old plaintext file is kept as "
            "'.before-encrypt' — delete it once you are confident.", 12000
        )

    def _on_decrypt_library(self) -> None:
        """File ▸ Remove Library Encryption: confirm, then decrypt."""
        answer = QMessageBox.question(
            self, "Remove Encryption",
            "The library will be stored UNENCRYPTED on disk again. Continue?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._do_decrypt()

    def _do_decrypt(self) -> None:
        """SQLCipher -> plaintext, in place, never losing the original."""
        from wordvault.storage.encryption import decrypt_library, swap_in

        self._autosave()
        self._store.close()
        tmp = self._library_path.with_name(self._library_path.name + ".tmp-plain")
        try:
            decrypt_library(self._library_path, tmp, self._passphrase)
            swap_in(tmp, self._library_path, ".before-decrypt")
        except Exception as exc:
            if tmp.exists():
                tmp.unlink()
            self._store = DocumentStore(self._library_path,
                                        passphrase=self._passphrase)
            self._update_encryption_actions()
            QMessageBox.warning(self, "Remove Encryption", str(exc))
            return
        self._passphrase = None
        self._store = DocumentStore(self._library_path)
        self._reset_after_reopen()
        self.statusBar().showMessage("Library encryption removed.", 8000)

    def _on_change_passphrase(self) -> None:
        pw = self._ask_passphrase(confirm=True)
        if pw is None:
            return
        try:
            self._store.change_passphrase(pw)
        except Exception as exc:
            QMessageBox.warning(self, "Change Passphrase", str(exc))
            return
        self._passphrase = pw
        self.statusBar().showMessage("Library passphrase changed.", 8000)

    def _on_export_wvdoc(self) -> None:
        """File ▸ Export Document: the open document -> encrypted .wvdoc."""
        from PyQt6.QtWidgets import QFileDialog

        from wordvault.storage.backup import export_document

        if self._current_doc is None:
            QMessageBox.information(self, "Export", "Open a document first.")
            return
        self._autosave()
        safe_name = "".join(
            c for c in self._current_doc.title if c.isalnum() or c in " -_"
        ).strip() or "document"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Document", f"{safe_name}.wvdoc",
            "WordVault document (*.wvdoc)",
        )
        if not path:
            return
        pw = self._ask_passphrase(confirm=True)
        if pw is None:
            return
        try:
            count = export_document(self._store, self._current_doc.id, path, pw)
        except Exception as exc:
            QMessageBox.warning(self, "Export", str(exc))
            return
        self.statusBar().showMessage(
            f"Exported with {count} revisions to {Path(path).name}.", 8000
        )

    def _on_import_wvdoc(self) -> None:
        """File ▸ Import .wvdoc: merge by uuid, open the result."""
        from PyQt6.QtWidgets import QFileDialog

        from wordvault.storage.backup import import_document

        path, _ = QFileDialog.getOpenFileName(
            self, "Import Document", "", "WordVault document (*.wvdoc)"
        )
        if not path:
            return
        pw = self._ask_passphrase()
        if pw is None:
            return
        try:
            doc, added = import_document(self._store, path, pw)
        except Exception as exc:
            QMessageBox.warning(self, "Import", str(exc))
            return
        self._reload_document_list()
        self._autosave()
        self._open_document(doc.id)
        self.statusBar().showMessage(
            f"Imported '{doc.title}' — {added} revision"
            + ("s" if added != 1 else "") + " added.", 8000
        )

    # ------------------------------------------------------------- saving --

    def _commit_live_text(self) -> Optional[Revision]:
        """Save the editor's text as a revision (identical states skipped).
        Only ever called in live mode; returns the new revision or None."""
        assert self._current_doc is not None
        new_text = self._editor.toPlainText()

        # Spelling-habits watcher: with checking ON, hand-made fixes of
        # misspelled words are mined from the edit before it is saved.
        if self._editor.markdown_highlighter.spelling_enabled:
            from wordvault.editor.spelling import (
                extract_corrections,
                get_spelling,
            )
            spelling = get_spelling()
            if spelling.is_available():
                old_text = self._store.current_text(self._current_doc.id)
                for typed, corrected in extract_corrections(
                        old_text, new_text, spelling.is_misspelled):
                    self._on_spelling_correction(typed, corrected)

        rev = self._store.save_revision(
            self._current_doc.id, new_text, origin="typing"
        )
        self._editor.stop_idle_timer()  # a pending pause-save is now redundant
        if rev is not None:
            self._saved_label.setText("saved " + datetime.now().strftime("%H:%M:%S"))
        return rev

    def _autosave(self) -> None:
        """Typing-pause / Ctrl+S / switch-document save.  Live mode only —
        in history mode the editor holds OLD text, which must never be
        recorded as new typing."""
        if self._current_doc is None or not self._is_live:
            return
        if self._commit_live_text() is not None:
            # History grew: extend the slider, staying parked at the end.
            self._revisions = self._store.list_revisions(self._current_doc.id)
            self._timeline.set_range(len(self._revisions), len(self._revisions) - 1)
            self._timeline.set_info(
                _local_time(self._revisions[-1].created_utc) + " · newest"
            )
            # New revision: the panels and age tints may have shifted.
            self._refresh_outline()
            self._refresh_info()
            self._apply_age_colors()
            self._refresh_library_info()
        self._update_status()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """Window closing: capture any final words (live mode only), then
        close the store."""
        try:
            self._autosave()
            self._store.close()
        except Exception as exc:  # never trap the user in a broken window
            QMessageBox.warning(self, "WordVault", f"Error while closing: {exc}")
        event.accept()

    # ------------------------------------------------------------- status --

    def _set_editor_enabled(self, enabled: bool) -> None:
        self._editor.setEnabled(enabled)
        self._timeline.setEnabled(enabled and bool(self._revisions))
        if not enabled:
            self._editor.set_text_quietly("")

    def _update_status(self) -> None:
        """Refresh the status-bar labels from current state."""
        if self._current_doc is None:
            self._doc_label.setText("No document open — File ▸ New Document")
            self._words_label.setText("")
            return

        rev_count = len(self._revisions)
        if self._is_live:
            self._doc_label.setText(
                f"{self._current_doc.title}  ·  {rev_count} revision"
                + ("s" if rev_count != 1 else "")
            )
        else:
            # Position is 1-based for humans: "revision 3 of 7".
            pos = self._timeline.position() + 1
            self._doc_label.setText(
                f"{self._current_doc.title}  ·  viewing revision "
                f"{pos} of {rev_count} (read-only — Restore to bring it back)"
            )
        text = self._editor.toPlainText()
        self._words_label.setText(f"{len(text.split())} words")
