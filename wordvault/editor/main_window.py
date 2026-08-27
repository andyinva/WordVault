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
    QColor,
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
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from wordvault.editor.age_colors import (
    CHANGED_WASH_DARK,
    CHANGED_WASH_LIGHT,
    age_color,
    age_rank,
    changed_word_spans,
    corresponding_line,
    line_birth_indices,
)
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


def _sentence_start(paragraph_text: str, offset: int) -> int:
    """Where the sentence containing `offset` begins, within one
    paragraph: just after the last sentence-ender (. ! ?) that
    precedes the offset — closing quotes and brackets allowed — or 0
    when the offset sits in the paragraph's first sentence.  Read
    Aloud backs up THIS far: a whole sentence, not a whole paragraph
    (the reader's choice, Aug 2026)."""
    import re

    start = 0
    for match in re.finditer(r"[.!?][\"'”’)\]]*\s+", paragraph_text[:offset]):
        start = match.end()
    return start


#: A keystroke-to-keystroke gap this long or shorter counts as writing
#: (thinking between sentences); anything longer means you were away.
EDIT_GAP_SECONDS = 60.0


def _format_edit_time(total_seconds: int) -> str:
    """Seconds of writing -> a human phrase for the info panel."""
    if total_seconds <= 0:
        return "none yet"
    if total_seconds < 60:
        return "under a minute"
    hours, minutes = divmod(total_seconds // 60, 60)
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min"


def _dictionary_listing(needle: str, personal_words, history_pairs,
                        completions) -> list[str]:
    """The Spelling Dictionary's list, three sources in rank order:

      ★ word                  the author's own dictionary (matched
                              anywhere in the word)
      typed → corrected (n×)  the author's ERROR HISTORY — a
                              misspelling is a valid way to LOOK UP
                              its word (Aug 2026: 'jeprodising' is
                              how this author writes 'jeopardizing',
                              so typing either side finds the pair)
      word                    standard-dictionary completions,
                              most common first
    """
    needle = needle.lower().strip()
    rows: list[str] = []
    shown: set[str] = set()
    for word in personal_words:
        if needle in word:
            rows.append(f"★ {word}")
            shown.add(word)
    for typed, corrected, count in history_pairs:
        if needle and (typed.startswith(needle)
                       or corrected.startswith(needle)):
            times = f"  ({count}×)" if count > 1 else ""
            rows.append(f"{typed} → {corrected}{times}")
            shown.add(corrected)
    for word in completions:
        if word not in shown:
            rows.append(word)
    return rows


def _speakable_mapped(markdown_text: str, base: int = 0):
    """Markdown -> (spoken_text, positions): the words a voice should
    SAY — heading marks, quote and list markers, and emphasis
    asterisks are silent typography ('kingdom', never 'asterisk
    asterisk kingdom') — PLUS a map from every spoken character back
    to its index in the original document (base = document index of
    markdown_text[0]).  The map is what lets the karaoke highlight
    find each spoken word in the marked-up editor text."""
    import re

    markers = (re.compile(r"^#{1,6}\s+"), re.compile(r"^>\s?"),
               re.compile(r"^[-*]\s+"), re.compile(r"^\d{1,3}\.\s+"))
    spoken: list[str] = []
    positions: list[int] = []
    offset = 0                      # index within markdown_text
    for line in markdown_text.split("\n"):
        skip = 0
        for marker in markers:
            m = marker.match(line)
            if m:
                skip = m.end()
                break
        for i, ch in enumerate(line):
            if i < skip or ch == "*":
                continue            # silent typography
            spoken.append(ch)
            positions.append(base + offset + i)
        spoken.append("\n")         # the newline between lines
        positions.append(base + offset + len(line))
        offset += len(line) + 1
    return "".join(spoken), positions


def _speakable(markdown_text: str) -> str:
    """The spoken text alone (see _speakable_mapped)."""
    return _speakable_mapped(markdown_text)[0]


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

        # The program announces itself: version, release date, motto.
        from wordvault import RELEASE_DATE, TAGLINE, __version__

        self.setWindowTitle(
            f"WordVault {__version__} ({RELEASE_DATE}) — {TAGLINE}"
        )
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
        self._apply_font_family(
            str(self._settings.value("font_family", "")))
        self._apply_notes_font()      # notes overrides, when chosen
        self._editor.set_paragraph_return(
            self._settings.value("paragraph_return", True, type=bool))
        self._apply_disabled_keys(
            str(self._settings.value("disabled_keys", "")))
        self._editor.set_line_light(
            self._settings.value("line_light", True, type=bool))
        # Restore the persisted View toggles.
        if self._settings.value("line_numbers", False, type=bool):
            self._line_numbers_action.setChecked(True)
        if self._settings.value("spelling", False, type=bool):
            self._spelling_action.setChecked(True)
        self._autocorrect_action.setChecked(
            self._settings.value("autocorrect", True, type=bool)
        )
        self._refresh_autocorrect()

        # Theme: photograph the platform's REAL look before anything
        # is touched — style name AND the actual startup palette (the
        # style's generic standardPalette() is NOT the same thing, a
        # lesson learned when "light mode" came back flat and gray).
        # Light mode at startup then touches nothing at all.
        from PyQt6.QtGui import QPalette as _QPalette
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        self._base_style_name = app.style().objectName()
        self._base_palette = _QPalette(app.palette())
        self._dark_mode = False
        if self._settings.value("dark_mode", False, type=bool):
            self._apply_theme(True)

        self._reload_document_list()
        self._set_editor_enabled(False)  # nothing open yet
        self._restore_window_state()

        # Personal extensions (see wordvault/editor/extensions.py):
        # abilities the OWNER of this copy added, loaded from
        # ~/.wordvault/extensions.  Most copies have none, and that is
        # by design — nothing is shipped, hidden, or disabled.
        from wordvault.editor.extensions import load_extensions

        names = load_extensions(self)
        if names:
            self.statusBar().showMessage(
                "Personal extensions loaded: " + ", ".join(names), 5000)

    # ---------------------------------- window-state persistence -----------

    def _restore_window_state(self) -> None:
        """Put the window back the way it was closed: size and position,
        dock visibility/placement, the editor/notes divider — and reopen
        the document that was being worked on (per library)."""
        geometry = self._settings.value("win_geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = self._settings.value("win_state")
        if state is not None:
            self.restoreState(state)
        split = self._settings.value("split_state")
        if split is not None:
            self._split.restoreState(split)

        # Reopen the document you were working on — unless the Settings
        # switch says to start with a clean desk (default: reopen).
        last = self._settings.value(f"last_doc:{self._library_path}")
        if last is not None and self._settings.value(
                "reopen_last", True, type=bool):
            try:
                self._open_document(int(last))
            except (KeyError, ValueError):
                pass   # the document is gone or another library: start clean

    def _save_window_state(self) -> None:
        self._settings.setValue("win_geometry", self.saveGeometry())
        self._settings.setValue("win_state", self.saveState())
        self._settings.setValue("split_state", self._split.saveState())
        key = f"last_doc:{self._library_path}"
        if self._current_doc is not None:
            self._settings.setValue(key, self._current_doc.id)
        else:
            self._settings.remove(key)

    # ------------------------------------------------------------------ UI --

    def _build_central_area(self) -> None:
        """Central widget, top to bottom: a FIXED title header (the text
        scrolls beneath it), then a vertical splitter — the document
        editor above (2/3) and the per-document notes pane below (1/3) —
        then the find bar and the timeline."""
        from PyQt6.QtWidgets import QSplitter

        # Fixed title header, in a serif face so it reads as a nameplate,
        # clearly distinct from the monospaced editing font.
        self._title_label = QLabel("No document open", self)
        self._title_label.setStyleSheet(
            "QLabel {"
            "  font-family: Georgia, 'Times New Roman', serif;"
            "  font-size: 15pt; font-weight: bold;"
            "  color: #1c3a5e; background: #f4f6f8;"
            "  padding: 5px 10px; border-bottom: 1px solid #c9d2dc;"
            "}"
        )

        self._editor = EditorPane(self)
        self._editor.pause_detected.connect(self._autosave)
        # The editing clock: counts ACTIVE writing time, not open time.
        self._editor.user_edited.connect(self._on_edit_activity)
        self._edit_clock_doc: Optional[int] = None
        self._edit_last_monotonic: Optional[float] = None
        self._edit_pending = 0.0
        self._editor.textChanged.connect(self._update_status)
        self._editor.cursorPositionChanged.connect(self._refresh_position)
        self._editor.correction_made.connect(self._on_suggestion_correction)
        self._editor.autocorrected.connect(self._on_autocorrected)

        # The notes pane: thinking space attached to the open document.
        # Deliberately NOT revision-tracked — notes are scaffolding.
        from PyQt6.QtWidgets import QPlainTextEdit

        self._notes = QPlainTextEdit(self)
        self._notes.setPlaceholderText(
            "Notes on this document — saved with it, kept out of the text…"
        )
        notes_font = self._notes.font()
        notes_font.setPointSize(max(9, notes_font.pointSize() - 1))
        self._notes.setFont(notes_font)
        self._notes.setStyleSheet(
            "QPlainTextEdit { background: #fbfaf4; }"
            # Blue border = "typing goes HERE" (edit-mode indicator).
            "QPlainTextEdit:focus { border: 2px solid #2f6fce; }"
        )

        # --- edit-mode visuals on the main editor ---
        # Blue border when focused and LIVE (your typing lands here);
        # amber border + parchment tint while viewing an OLD version
        # (read-only: select and copy, but the past cannot be edited —
        # the timeline's highlighted Newest/Restore buttons lead back).
        # The live page is explicitly WHITE — not the platform's base
        # color, which on some Windows themes is already a light gray
        # and swallowed the current-line light whole (Andrew's "I can
        # not see the tint" report).  The page is plain; the line
        # light is the only tint on it.
        self._editor.setStyleSheet(
            'QPlainTextEdit[mode="live"] { background: #ffffff; }'
            'QPlainTextEdit[mode="live"]:focus'
            '  { border: 2px solid #2f6fce; }'
            'QPlainTextEdit[mode="history"]'
            '  { border: 2px solid #c98a00; background: #fbf6ea; }'
        )
        self._editor.setProperty("mode", "live")
        # Notes save themselves after a 3-second pause (their own timer —
        # editing notes must not create document revisions).
        from PyQt6.QtCore import QTimer

        self._notes_timer = QTimer(self)
        self._notes_timer.setSingleShot(True)
        self._notes_timer.setInterval(3000)
        self._notes_timer.timeout.connect(self._save_current_note)
        self._notes.textChanged.connect(
            lambda: self._notes_timer.start()
            if not self._notes.signalsBlocked() else None
        )

        # Notes get spelling too: underlines share the editor's
        # dictionary and its View ▸ Check Spelling toggle; right-click
        # suggestions come from _on_notes_context_menu.
        from wordvault.editor.markdown_highlighter import SpellingHighlighter

        self._notes_highlighter = SpellingHighlighter(self._notes.document())
        self._notes.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._notes.customContextMenuRequested.connect(
            self._on_notes_context_menu)

        # Anchored notes: starting a note on an empty line stamps it
        # with the editor's current cursor position ("▸ line 143 (…): ")
        # and double-clicking such a stamp jumps the editor there.
        # Both behaviors live in eventFilter().
        self._notes.installEventFilter(self)
        self._notes.viewport().installEventFilter(self)

        self._split = QSplitter(Qt.Orientation.Vertical, self)
        self._split.addWidget(self._editor)
        self._split.addWidget(self._notes)
        self._split.setStretchFactor(0, 2)   # document: 2/3
        self._split.setStretchFactor(1, 1)   # notes: 1/3
        self._split.setChildrenCollapsible(True)

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
        layout.addWidget(self._split, stretch=1)
        self.setCentralWidget(container)

        # The serif TITLE HEADER spans the window's full top as a
        # locked, chromeless dock — the mirror of the timeline strip
        # below.  With the top corners assigned to it, the side panels
        # (Outline, Doc Info, ...) BEGIN where the editor begins:
        # every upper border on one line (Aug 2026 request), matching
        # the aligned lower borders.
        title_dock = QDockWidget("", self)
        title_dock.setObjectName("TitleDock")       # saveState needs it
        title_dock.setWidget(self._title_label)
        title_dock.setTitleBarWidget(QWidget(title_dock))    # no chrome
        title_dock.setFeatures(
            QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.setCorner(Qt.Corner.TopLeftCorner,
                       Qt.DockWidgetArea.TopDockWidgetArea)
        self.setCorner(Qt.Corner.TopRightCorner,
                       Qt.DockWidgetArea.TopDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, title_dock)

        # The find bar and timeline live in a LOCKED, chromeless dock
        # spanning the window's full bottom.  With both bottom corners
        # assigned to the bottom area, the side panels (Outline, Doc
        # Info, Library Info, Library list) END where the notes end —
        # every lower border on one line (Aug 2026 request).
        bottom_host = QWidget(self)
        bottom_col = QVBoxLayout(bottom_host)
        bottom_col.setContentsMargins(0, 0, 0, 0)
        bottom_col.setSpacing(0)
        bottom_col.addWidget(self._find_bar)
        bottom_col.addWidget(self._timeline)
        bottom_dock = QDockWidget("", self)
        bottom_dock.setObjectName("TimelineDock")   # saveState needs it
        bottom_dock.setWidget(bottom_host)
        bottom_dock.setTitleBarWidget(QWidget(bottom_dock))  # no chrome
        bottom_dock.setFeatures(
            QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.setCorner(Qt.Corner.BottomLeftCorner,
                       Qt.DockWidgetArea.BottomDockWidgetArea)
        self.setCorner(Qt.Corner.BottomRightCorner,
                       Qt.DockWidgetArea.BottomDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea,
                           bottom_dock)

    # ------------------------------------------ notes anchored to the text --

    def eventFilter(self, obj, event):  # noqa: N802 (Qt naming)
        """Two small notes-pane behaviors (installed in __init__):

        * typing the FIRST character of a note (an empty line) stamps
          it with where the editor's cursor stands — the note is
          associated with that place in the document;
        * a single CLICK ON THE STAMP ITSELF ("▸ line 143 (…):") jumps
          the editor back there — the stamp is the link; clicking in
          the note's own words just edits, as any text does;
        * double-clicking anywhere in a stamped line also jumps.
        """
        from PyQt6.QtCore import QEvent

        if obj is self._notes and event.type() == QEvent.Type.KeyPress:
            text = event.text()
            if (text and text.isprintable()
                    and self._current_doc is not None
                    and self._notes.textCursor().block().text() == ""):
                self._notes.textCursor().insertText(
                    self._note_anchor_prefix())
        elif (obj is self._notes.viewport()
                and event.type() == QEvent.Type.MouseButtonDblClick):
            cursor = self._notes.cursorForPosition(
                event.position().toPoint())
            if self._jump_to_note_anchor(cursor.block().text()):
                return True                    # handled: don't select text
        elif (obj is self._notes.viewport()
                and event.type() == QEvent.Type.MouseButtonRelease):
            cursor = self._notes.cursorForPosition(
                event.position().toPoint())
            if self._click_is_on_stamp(cursor.block().text(),
                                       cursor.positionInBlock()):
                self._jump_to_note_anchor(cursor.block().text())
        return super().eventFilter(obj, event)

    @staticmethod
    def _click_is_on_stamp(note_line: str, position_in_block: int) -> bool:
        """True when a click landed WITHIN the '▸ line N (…):' stamp at
        the head of a note line — the stamp acts as a link; the note's
        own words stay ordinary editable text."""
        import re as _re

        match = _re.match(r"▸ line \d+(?: \([^)]*\))?:", note_line)
        return bool(match) and position_in_block <= match.end()

    def _note_anchor_prefix(self) -> str:
        """The stamp for a new note: the cursor's line plus the first
        words of the SENTENCE under the cursor (not the paragraph's
        opening — a long paragraph holds many thoughts, and the note
        belongs to one of them).  The quoted words also let the jump
        FIND the place again after line numbers drift."""
        cursor = self._editor.textCursor()
        line = cursor.blockNumber() + 1
        block_text = cursor.block().text()
        offset = cursor.position() - cursor.block().position()
        words = block_text[_sentence_start(block_text, offset):].strip()
        snippet = (words[:24].rstrip() + "…") if len(words) > 24 else words
        where = f"▸ line {line}"
        if snippet:
            where += f" ({snippet})"
        return where + ": "

    def _jump_to_note_anchor(self, note_line: str) -> bool:
        """If note_line carries a '▸ line N (words…)' stamp, move the
        editor to the SENTENCE those words begin: found within the
        stamped line when it still lives there, searched for in the
        whole document when editing has moved it (drift-proof), and
        the stamped line's start as the last resort.  Returns True
        when a jump happened."""
        import re as _re

        from PyQt6.QtGui import QTextCursor

        match = _re.match(r"▸ line (\d+)(?: \((.*?)\))?:", note_line)
        if not match:
            return False
        number = min(int(match.group(1)) - 1,
                     self._editor.document().blockCount() - 1)
        block = self._editor.document().findBlockByNumber(max(0, number))
        position = block.position()

        snippet = (match.group(2) or "").rstrip("…").strip()
        if snippet:
            in_block = block.text().find(snippet)
            if in_block >= 0:
                position = block.position() + in_block
            else:
                anywhere = self._editor.toPlainText().find(snippet)
                if anywhere >= 0:
                    position = anywhere      # the passage moved; found it

        cursor = QTextCursor(self._editor.document())
        cursor.setPosition(position)
        self._editor.setTextCursor(cursor)
        self._editor.centerCursor()
        self._editor.setFocus()
        return True

    def _save_current_note(self) -> None:
        """Persist the notes pane for the open document (no-op unchanged)."""
        if self._current_doc is not None and self._notes.isEnabled():
            self._store.set_note(self._current_doc.id,
                                 self._notes.toPlainText())

    def _load_note(self, doc_id: int) -> None:
        """Fill the notes pane WITHOUT triggering its save timer."""
        self._notes.blockSignals(True)
        self._notes.setPlainText(self._store.get_note(doc_id))
        self._notes.blockSignals(False)
        self._notes_timer.stop()

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

        self._library_list_dock = QDockWidget("Library", self)
        # objectName is REQUIRED for QMainWindow.saveState() to persist
        # this dock's visibility/position between sessions.
        self._library_list_dock.setObjectName("LibraryListDock")
        self._library_list_dock.setWidget(container)
        # Closable too: View ▸ Library gets it back (author's request —
        # full-width writing with the list tucked away).
        self._library_list_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,
                           self._library_list_dock)
        self._reload_tag_filter()

    def _build_side_panels(self) -> None:
        """Stage 7 docks: outline (left, under the library) and info panel
        (right).  Both closable — View menu brings them back.

        Each panel sits in a thin ROUNDED frame (Aug 2026 request),
        made by wrapping it in a small margined host so the rounded
        corners have room to show against the dock's edges."""

        def framed(panel, name: str) -> QWidget:
            """A host that draws a rounded hairline around `panel`.

            The frame's colors are THEME work: a stylesheet on a
            widget makes Qt stop trusting the palette for its
            background (which left the Outline glaring white in dark
            mode), so every framed panel registers itself and
            _apply_theme restyles them all, light or dark."""
            host = QWidget(self)
            host.setObjectName(name)
            box = QVBoxLayout(host)
            box.setContentsMargins(3, 3, 3, 3)
            box.addWidget(panel)
            panel.setObjectName(name + "Inner")
            panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            if not hasattr(self, "_panel_frames"):
                self._panel_frames = []
            self._panel_frames.append(panel)
            # The light dress, worn from birth (dark mode restyles).
            panel.setStyleSheet(
                f"#{name}Inner {{ border: 1px solid #b9c4d0;"
                f" border-radius: 6px; }}")
            return host

        self._outline = OutlinePane(self)
        self._outline.heading_activated.connect(self._on_heading_activated)
        self._outline_dock = QDockWidget("Outline", self)
        self._outline_dock.setObjectName("OutlineDock")
        self._outline_dock.setWidget(framed(self._outline, "OutlineFrame"))
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._outline_dock)

        self._info_panel = InfoPanel(self)
        self._info_panel.edit_tags_requested.connect(self._on_edit_tags)
        self._info_dock = QDockWidget("Document Info", self)
        self._info_dock.setObjectName("DocInfoDock")
        self._info_dock.setWidget(framed(self._info_panel, "DocInfoFrame"))
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._info_dock)

        # Library-wide facts, below the document panel.
        self._library_panel = LibraryInfoPanel(self)
        self._library_dock = QDockWidget("Library Info", self)
        self._library_dock.setObjectName("LibraryInfoDock")
        self._library_dock.setWidget(
            framed(self._library_panel, "LibraryInfoFrame"))
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,
                           self._library_dock)
        self._refresh_library_info()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        new_action = QAction("&New Document…", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)   # Ctrl+N
        new_action.triggered.connect(self._on_new_document)
        file_menu.addAction(new_action)

        # --- File ▸ Open: ONE outside file, converted and put straight
        # into the vault, then opened for editing.  Consistent with the
        # design: the editor is a window onto the vault, so material
        # is protected from its first second here.  Each kind has its
        # own conversion (see _import_external_file).
        open_menu = file_menu.addMenu("&Open File (docx, md, txt)")
        for label, kind in (("&Word Document (.docx)…", "docx"),
                            ("&Markdown File (.md)…", "md"),
                            ("Plain &Text File (.txt)…", "txt")):
            action = QAction(label, self)
            action.triggered.connect(
                lambda _c, k=kind: self._on_open_external(k))
            open_menu.addAction(action)

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

        learn_action = QAction("&Learn Print Format from .docx…", self)
        learn_action.setToolTip(
            "Read a Word document's page, margins, and styles and "
            "create a .wvfmt that prints like it"
        )
        learn_action.triggered.connect(self._on_learn_format)
        file_menu.addAction(learn_action)

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

        add_edit("&Read Aloud from Cursor", "Ctrl+Shift+R",
                 self._on_read_aloud)
        # Delete-not-Cut: removes the selection WITHOUT touching the
        # clipboard, so whatever you copied earlier stays copied.
        add_edit("Delete Selectio&n", None, self._on_delete_selection)
        edit_menu.addSeparator()

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

        trash_action = QAction("Move to &Wastebasket…", self)
        trash_action.setToolTip(
            "Banish this document from the library — never destroyed, "
            "always restorable from Library ▸ Wastebasket"
        )
        trash_action.triggered.connect(self._on_trash_document)
        doc_menu.addAction(trash_action)

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

        # --- book navigation: walk the chapters of the current book
        # project in order, so twelve essays read like one book ---
        prev_ch_action = QAction("Previous &Chapter in Book", self)
        prev_ch_action.setShortcut("Ctrl+Alt+Up")
        prev_ch_action.triggered.connect(lambda: self._on_step_chapter(-1))
        doc_menu.addAction(prev_ch_action)

        next_ch_action = QAction("Next C&hapter in Book", self)
        next_ch_action.setShortcut("Ctrl+Alt+Down")
        next_ch_action.triggered.connect(lambda: self._on_step_chapter(+1))
        doc_menu.addAction(next_ch_action)

        doc_menu.addSeparator()

        verses_action = QAction("Documents Sharing &Verses…", self)
        verses_action.setShortcut("Ctrl+Shift+V")
        verses_action.triggered.connect(self._on_shared_verses)
        doc_menu.addAction(verses_action)

        provenance_action = QAction("&Provenance Report…", self)
        provenance_action.setToolTip(
            "The document's construction story, assembled from its own "
            "revision history: sessions, growth, writing time, and the "
            "corrections made along the way")
        provenance_action.triggered.connect(self._on_provenance_report)
        doc_menu.addAction(provenance_action)

        # Export As: every way a document leaves the vault, under one
        # roof.  The first three export what is ON SCREEN (a viewed
        # old draft exports as that old draft); .wvdoc carries the
        # document WITH its whole history, encrypted, to another
        # WordVault.
        export_menu = doc_menu.addMenu("Export &As")
        for label, kind in (("&Word Document (.docx)…", "docx"),
                            ("&Markdown File (.md)…", "md"),
                            ("Plain &Text File (.txt)…", "txt")):
            action = QAction(label, self)
            action.triggered.connect(
                lambda _c, k=kind: self._on_export_as(k))
            export_menu.addAction(action)
        export_menu.addSeparator()
        wvdoc_action = QAction("&WordVault Document (.wvdoc)…", self)
        wvdoc_action.setToolTip(
            "The document WITH its full revision history, encrypted — "
            "for carrying to another WordVault"
        )
        wvdoc_action.triggered.connect(self._on_export_wvdoc)
        export_menu.addAction(wvdoc_action)

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

        self._autocorrect_action = QAction("Auto-&Correct Repeated Fixes", self)
        self._autocorrect_action.setCheckable(True)
        self._autocorrect_action.setToolTip(
            "A fix you make once is applied through the document and "
            "repaired automatically when you type the same mistake again"
        )
        self._autocorrect_action.toggled.connect(
            lambda on: (self._settings.setValue("autocorrect", on),
                        self._refresh_autocorrect())
        )
        view_menu.addAction(self._autocorrect_action)

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
        # The docks provide their own show/hide toggle actions —
        # checkboxes for the Library list, Outline, Document Info, and
        # Library Info panels.
        view_menu.addAction(self._library_list_dock.toggleViewAction())
        view_menu.addAction(self._outline_dock.toggleViewAction())
        view_menu.addAction(self._info_dock.toggleViewAction())
        view_menu.addAction(self._library_dock.toggleViewAction())

        # --- Library menu: search, gather, review (stages 5-6) ---
        library_menu = self.menuBar().addMenu("&Library")

        import_folder_action = QAction("&Import .docx Folder…", self)
        import_folder_action.setShortcut("Ctrl+Shift+I")
        import_folder_action.triggered.connect(self._on_import_folder)
        library_menu.addAction(import_folder_action)

        refresh_fmt_action = QAction("Re&fresh Formatting from Originals…",
                                     self)
        refresh_fmt_action.setToolTip(
            "Re-read every imported document's original .docx with the "
            "current converter; improved text becomes one new revision"
        )
        refresh_fmt_action.triggered.connect(self._on_refresh_formatting)
        library_menu.addAction(refresh_fmt_action)

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

        # --- the Book Formatter: assemble library chapters into a
        # print-ready book PDF (its own window; see wordvault.formatter) ---
        formatter_action = QAction("Book &Formatter…", self)
        formatter_action.setShortcut("Ctrl+Shift+B")
        formatter_action.setToolTip(
            "Assemble chapters from the library into a book PDF"
        )
        formatter_action.triggered.connect(self._on_formatter)
        library_menu.addAction(formatter_action)

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

        wastebasket_action = QAction("&Wastebasket…", self)
        wastebasket_action.setToolTip(
            "Banished documents — restore any of them, whole, anytime"
        )
        wastebasket_action.triggered.connect(self._on_wastebasket)
        library_menu.addAction(wastebasket_action)

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

        guide_action = QAction("&User Guide", self)
        guide_action.setShortcut("Shift+F1")
        guide_action.setToolTip(
            "The complete guide: the philosophy, and every feature "
            "in detail (Shift+F1)"
        )
        guide_action.triggered.connect(self._on_user_guide)

        share_action = QAction("&Share WordVault with a Friend…", self)
        share_action.setToolTip(
            "A ready-to-paste email: what WordVault is and how to "
            "install it"
        )
        share_action.triggered.connect(self._on_share)

        updates_action = QAction("&Getting Updates…", self)
        updates_action.setToolTip(
            "How to load new versions — your library is never touched"
        )
        updates_action.triggered.connect(self._on_updates)

        settings_action = QAction("&Settings…", self)
        settings_action.setToolTip(
            "Auto-save pause, font size, and library encryption"
        )
        settings_action.triggered.connect(self._on_settings)

        dictionary_action = QAction("Spelling &Dictionary…", self)
        dictionary_action.setToolTip(
            "Look a word up — is it known? have you misspelled it "
            "before? — and add it to your dictionary"
        )
        dictionary_action.triggered.connect(self._on_spelling_dictionary)

        habits_action = QAction("My Spelling Ha&bits…", self)
        habits_action.setToolTip(
            "What kinds of spelling fixes you make — a running mirror"
        )
        habits_action.triggered.connect(self._on_spelling_habits)

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(help_action)
        help_menu.addAction(guide_action)
        help_menu.addSeparator()
        help_menu.addAction(share_action)
        help_menu.addAction(updates_action)
        help_menu.addSeparator()
        help_menu.addAction(dictionary_action)
        help_menu.addAction(habits_action)
        help_menu.addAction(settings_action)

    # ------------------------------------------ personal extensions --------
    def add_extension_button(self, text: str, tooltip: str,
                             callback) -> QPushButton:
        """The one-line API personal extensions use to get a button.

        The button joins the timeline bar at the far right, beside
        Read — the established home for editor buttons.  NoFocus, like
        its neighbors, so clicking it never steals the text cursor
        (the lesson the Read button taught us)."""
        button = QPushButton(text, self)
        button.setToolTip(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(callback)
        self._timeline.layout().addWidget(button)
        return button

    def _on_help(self) -> None:
        from wordvault.editor.help_dialog import HelpDialog

        HelpDialog(self).exec()

    def _on_user_guide(self) -> None:
        """The complete User Guide: the philosophy, then every feature
        in detail — for sitting down with (docs/guide.md)."""
        from wordvault.editor.help_dialog import _GUIDE_FILE, HelpDialog

        HelpDialog(self, document=_GUIDE_FILE,
                   title="WordVault User Guide").exec()

    def _on_share(self) -> None:
        """The installation email, with one-click copy — so telling a
        friend about WordVault is a paste, not a writing assignment."""
        from wordvault.editor.help_dialog import ShareDialog

        ShareDialog(self).exec()

    def _on_updates(self) -> None:
        from wordvault.editor.help_dialog import _UPDATES_FILE, HelpDialog

        HelpDialog(self, document=_UPDATES_FILE,
                   title="Getting Updates").exec()

    #: Settings names -> Qt key codes for the Disabled-keys feature.
    _SILENCEABLE_KEYS = {
        "pgup": Qt.Key.Key_PageUp,
        "pgdn": Qt.Key.Key_PageDown,
        "home": Qt.Key.Key_Home,
        "end": Qt.Key.Key_End,
        "insert": Qt.Key.Key_Insert,
    }

    def _apply_disabled_keys(self, names_csv: str) -> None:
        """Silence the named keys in the editor (comma-separated names
        as persisted in QSettings; unknown names are ignored)."""
        names = [n for n in names_csv.split(",") if n]
        self._disabled_key_names = tuple(
            n for n in names if n in self._SILENCEABLE_KEYS)
        self._editor.set_disabled_keys(
            self._SILENCEABLE_KEYS[n] for n in self._disabled_key_names)

    def _on_settings(self) -> None:
        """Open Settings; apply and persist whatever was chosen."""
        from PyQt6.QtWidgets import QDialog

        from wordvault.editor.settings_dialog import SettingsDialog

        dialog = SettingsDialog(
            self,
            encrypted=self._store.is_encrypted,
            idle_seconds=max(1, self._editor.idle_ms() // 1000),
            font_size=self._editor.font().pointSize(),
            author=str(self._settings.value("author", "")),
            recent_limit=self._recent_limit(),
            reopen_last=self._settings.value("reopen_last", True, type=bool),
            font_family=self._editor.font().family(),
            notes_family=self._notes.font().family(),
            notes_size=self._notes.font().pointSize(),
            reading_speed=self._reading_speed_percent(),
            dark_mode=getattr(self, "_dark_mode", False),
            paragraph_return=self._editor.paragraph_return(),
            disabled_keys=getattr(self, "_disabled_key_names", ()),
            line_light=self._editor.line_light(),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        # Everyday knobs: apply now, remember for next start.
        self._editor.set_idle_ms(dialog.idle_seconds * 1000)
        self._editor.set_font_point_size(dialog.font_size)
        self._apply_font_family(dialog.font_family)
        self._settings.setValue("idle_ms", dialog.idle_seconds * 1000)
        self._settings.setValue("font_pt", dialog.font_size)
        self._settings.setValue("font_family", dialog.font_family)
        self._settings.setValue("notes_font_family", dialog.notes_family)
        self._settings.setValue("notes_font_pt", dialog.notes_size)
        self._apply_notes_font()
        self._settings.setValue("tts_rate_percent", dialog.reading_speed)
        self._apply_reading_speed()   # takes hold at the next Read
        self._settings.setValue("dark_mode", dialog.dark_mode)
        if dialog.dark_mode != getattr(self, "_dark_mode", False):
            self._apply_theme(dialog.dark_mode)   # live, no restart
        self._settings.setValue("author", dialog.author)
        self._settings.setValue("recent_limit", dialog.recent_limit)
        self._settings.setValue("reopen_last", dialog.reopen_last)
        self._editor.set_paragraph_return(dialog.paragraph_return)
        self._settings.setValue("paragraph_return", dialog.paragraph_return)
        self._apply_disabled_keys(",".join(dialog.disabled_keys))
        self._settings.setValue("disabled_keys",
                                ",".join(dialog.disabled_keys))
        self._editor.set_line_light(dialog.line_light)
        self._settings.setValue("line_light", dialog.line_light)

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

    # ------------------------------------------------------ read aloud --

    def _ensure_tts(self):
        """The text-to-speech engine, created on first use.  Qt speaks
        through the system's own voices (SAPI on Windows; on Ubuntu,
        speech-dispatcher: sudo apt install speech-dispatcher).  None
        when unavailable — explained once, not crashed over."""
        if hasattr(self, "_tts"):
            return self._tts
        try:
            from PyQt6.QtTextToSpeech import QTextToSpeech
        except ImportError:
            self._tts = None
            QMessageBox.information(
                self, "Read Aloud",
                "This PyQt6 installation lacks the QtTextToSpeech "
                "module.\n\nUsually fixed by:  pip install --upgrade "
                "PyQt6\n(On Ubuntu, also:  sudo apt install "
                "speech-dispatcher)")
            return None
        self._tts = QTextToSpeech(self)
        self._tts.stateChanged.connect(self._on_tts_state)
        # Word-by-word progress (Qt 6.6+, engine willing): the karaoke
        # highlight.  Older Qt or a reticent engine: reading still
        # works, just without the moving light.
        if hasattr(self._tts, "sayingWord"):
            self._tts.sayingWord.connect(self._on_tts_word)
        self._apply_reading_speed()
        return self._tts

    def _reading_speed_percent(self) -> int:
        """The Settings pace, clamped to the dialog's 50..150 range."""
        try:
            value = int(self._settings.value("tts_rate_percent", 100))
        except (TypeError, ValueError):
            value = 100
        return max(50, min(150, value))

    def _apply_reading_speed(self) -> None:
        """Percent -> Qt's rate scale (-1..+1 around normal): 100% is
        the voice's natural pace, 50% half speed for careful proofing,
        150% a brisk skim."""
        if getattr(self, "_tts", None) is not None:
            self._tts.setRate((self._reading_speed_percent() - 100) / 100.0)

    def _on_read_aloud(self) -> None:
        """The 🔊 button / Ctrl+Shift+R: read the SELECTION, or from
        the cursor's paragraph to the end of the document, in the
        system's digital voice.  A second click stops mid-word."""
        from PyQt6.QtCore import QTimer

        # The reading anchor is wherever the reader put the caret —
        # capture it FIRST, and hold the view still through engine
        # start-up (first use initializes the system voice, which must
        # not be allowed to disturb the scene being read).
        cursor = self._editor.textCursor()
        scroll_bar = self._editor.verticalScrollBar()
        scroll_pos = scroll_bar.value()

        tts = self._ensure_tts()
        if tts is None:
            return
        from PyQt6.QtTextToSpeech import QTextToSpeech

        if tts.state() == QTextToSpeech.State.Speaking:
            tts.stop()
            self._read_btn.setText("🔊 Read")
            return
        if cursor.hasSelection():
            # Qt marks paragraph breaks in selections with U+2029
            # (same length as \n, so the position map stays true).
            base = cursor.selectionStart()
            raw = cursor.selectedText().replace("\u2029", "\n")
        else:
            # From the start of the SENTENCE under the cursor: whole
            # sentences sound right, whole paragraphs repeat too much.
            block = cursor.block()
            offset = cursor.position() - block.position()
            base = block.position() + _sentence_start(block.text(), offset)
            raw = self._editor.toPlainText()[base:]
        text, self._read_positions = _speakable_mapped(raw, base)
        if not text.strip():
            self.statusBar().showMessage("Nothing to read here.", 4000)
            return
        tts.say(text)
        self._read_btn.setText("⏹ Stop")
        # Say out loud (in print) what is being said out loud (in air):
        # the anchor line and the first words handed to the voice.
        opening = " ".join(text.split())[:60]
        self.statusBar().showMessage(
            f"Reading from line {cursor.blockNumber() + 1}: "
            f"“{opening}…”", 10000)

        # Belt to the braces: whatever engine start-up stirred, put the
        # view back where the reader was — now, and again once events
        # settle.  Bound method, not a closure: PyQt cancels it if the
        # window dies first (the history-stepping crash's lesson).
        self._pending_scroll = scroll_pos
        self._restore_tries = 0           # fresh retry budget
        self._restore_history_scroll()
        QTimer.singleShot(0, self._restore_history_scroll)

    def _on_tts_state(self, state) -> None:
        """The voice finished (or failed): the button offers to read
        again, and the karaoke light goes out."""
        from PyQt6.QtTextToSpeech import QTextToSpeech

        if state != QTextToSpeech.State.Speaking:
            self._read_btn.setText("🔊 Read")
            self._read_highlight = None
            self._read_positions = []
            self._apply_age_colors()      # repaint without the light

    def _on_tts_word(self, _word, _utterance, start, length) -> None:
        """The engine names the word it is speaking (an offset into
        the STRIPPED text we handed it); the position map carries it
        back to the marked-up document, where it lights up — and the
        view drifts along so the lit word stays on screen."""
        positions = getattr(self, "_read_positions", None)
        if (not positions or length <= 0 or start < 0
                or start + length > len(positions)):
            return
        doc_from = positions[start]
        doc_to = positions[start + length - 1] + 1
        if doc_to > len(self._editor.toPlainText()):
            return                        # text changed under the voice
        self._read_highlight = (doc_from, doc_to)
        self._apply_age_colors()          # repaints WITH the light

        # Follow gently: scroll only when the word leaves the viewport
        # (never touching the caret — the reader may be elsewhere).
        from PyQt6.QtGui import QTextCursor

        cursor = QTextCursor(self._editor.document())
        cursor.setPosition(doc_from)
        rect = self._editor.cursorRect(cursor)
        viewport_h = self._editor.viewport().height()
        if rect.top() < 0 or rect.bottom() > viewport_h:
            bar = self._editor.verticalScrollBar()
            row_h = max(1, self._editor.fontMetrics().height())
            bar.setValue(bar.value()
                         + (rect.top() - viewport_h // 3) // row_h)

    def _read_light_selections(self) -> list:
        """The karaoke highlight as ExtraSelections (empty when the
        voice is silent) — appended to the age tints so the two
        features share the one ExtraSelections channel peacefully."""
        span = getattr(self, "_read_highlight", None)
        if span is None:
            return []
        from PyQt6.QtGui import QColor, QTextCursor

        cursor = QTextCursor(self._editor.document())
        cursor.setPosition(span[0])
        cursor.setPosition(span[1], QTextCursor.MoveMode.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#ffe08a"))      # warm reading light
        fmt.setForeground(QColor("#000000"))      # readable on it in
                                                  # BOTH themes
        sel = QTextEdit.ExtraSelection()
        sel.cursor = cursor
        sel.format = fmt
        return [sel]

    def _build_status_bar(self) -> None:
        """The status bar carries only TRANSIENT messages now — the
        permanent document/revision/word-count labels were retired
        (Aug 2026): every fact they showed lives in the Document Info
        panel and the title header, and one line of screen is worth
        more than saying things twice.  Read Aloud's button lives on
        the timeline bar (right of Restore); its voice lives here."""
        self._read_btn = self._timeline.read_btn
        self._timeline.read_requested.connect(self._on_read_aloud)
        self.statusBar()   # created empty, ready for showMessage()

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

    # ---------------- File ▸ Open: one outside file into the vault --

    def _on_open_external(self, kind: str) -> None:
        """File ▸ Open File: pick one outside file.  It is converted,
        put into the vault as a new document, and opened for editing —
        protected by revisions from its first second here.  (The vault
        keeps everything forever, so open deliberately: there is no
        delete.)"""
        from PyQt6.QtWidgets import QFileDialog

        filters = {
            "docx": "Word documents (*.docx)",
            "md": "Markdown files (*.md *.markdown)",
            "txt": "Text files (*.txt)",
        }
        path, _f = QFileDialog.getOpenFileName(
            self, "Open File into WordVault", "", filters[kind])
        if not path:
            return
        doc = self._import_external_file(Path(path), kind)
        if doc is not None:
            self._autosave()             # current document's last words
            self._reload_document_list()
            self._open_document(doc.id)
            self.statusBar().showMessage(
                f"'{doc.title}' converted and saved into the vault — "
                f"editing it now.", 8000)

    def _import_external_file(self, path: Path, kind: str):
        """Convert one outside file and CREATE its vault document.
        Each kind does its own conversion into WordVault's format:

          docx  -> the full importer (headings, bold/italic, lists,
                   quotes, hyperlinks, tables — same as folder import)
          md    -> already our format; line endings normalized
          txt   -> plain text IS valid WordVault text; normalized

        Title: the file's first '# ' heading, else its name (numbered
        if the library already uses it).  Dates: the file's best
        evidence — Word-internal for docx, filesystem otherwise.
        Returns the new Document, or None on failure."""
        import re as _re

        try:
            if kind == "docx":
                from wordvault.ingest.extract import extract_markdown

                text = extract_markdown(path)
            else:
                from wordvault.ingest.extract import (
                    long_path,
                    normalize_text,
                )

                raw = None
                for encoding in ("utf-8", "cp1252", "latin-1"):
                    try:
                        raw = Path(long_path(path)).read_text(
                            encoding=encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                if raw is None:
                    raise OSError("undecodable text encoding")
                text = normalize_text(raw)
        except Exception as exc:
            QMessageBox.warning(self, "Cannot open file",
                                f"{path.name}: {exc}")
            return None

        title = path.stem
        for line in text.splitlines():
            match = _re.match(r"^#\s+(.+)$", line)
            if match:
                title = match.group(1).strip()
                break
        existing = {d.title for d in self._store.list_documents()}
        final_title, n = title, 2
        while final_title in existing:
            final_title = f"{title} ({n})"
            n += 1

        created = mtime = None
        try:
            if path.suffix.lower() == ".docx":
                from wordvault.ingest.extract import document_dates_utc

                created, mtime = document_dates_utc(path)
            else:
                from wordvault.ingest.extract import file_dates_utc

                created, mtime = file_dates_utc(path)
        except OSError:
            pass                         # unreadable dates: use "now"

        doc = self._store.create_document(
            final_title, original_path=str(path),
            original_mtime=mtime, created_utc=created)
        self._store.save_revision(doc.id, text, origin="file open")
        return self._store.get_document(doc.id)

    # ------------------------------------------------- the wastebasket --

    def _on_delete_selection(self) -> None:
        """Edit ▸ Delete Selection: remove highlighted text WITHOUT
        touching the clipboard (Cut's quiet sibling)."""
        cursor = self._editor.textCursor()
        if cursor.hasSelection():
            cursor.removeSelectedText()
        else:
            self.statusBar().showMessage("Nothing selected.", 3000)

    def _on_trash_document(self) -> None:
        """Document ▸ Move to Wastebasket: banishment, not destruction.
        The document leaves every list and search, but its history,
        notes, and tags stay whole — Library ▸ Wastebasket restores it
        exactly as it was, whenever."""
        if self._current_doc is None:
            return
        doc = self._current_doc
        answer = QMessageBox.question(
            self, "Move to Wastebasket",
            f"Move '{doc.title}' to the Wastebasket?\n\nIt disappears "
            f"from the library, searches, and books — but nothing is "
            f"destroyed. Library ▸ Wastebasket… can restore it, whole, "
            f"at any time.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._autosave()
        self._save_current_note()
        self._store.trash_document(doc.id)
        self._on_close_document()
        self._reload_document_list()
        self.statusBar().showMessage(
            f"'{doc.title}' moved to the Wastebasket.", 6000)

    def _on_wastebasket(self) -> None:
        """Library ▸ Wastebasket: the banished, restorable forever.
        There is deliberately NO destroy button — the vault's first
        promise is that nothing is ever lost, and at the size of text,
        eternal mercy is cheap."""
        from PyQt6.QtWidgets import (
            QDialog,
            QHBoxLayout,
            QListWidgetItem,
            QPushButton,
            QVBoxLayout,
        )

        dialog = QDialog(self)
        dialog.setWindowTitle("Wastebasket")
        dialog.resize(520, 420)
        layout = QVBoxLayout(dialog)
        info = QLabel(
            "Banished documents. Nothing here is ever destroyed — "
            "select one and Restore brings it back whole: text, "
            "history, notes, and tags.")
        info.setWordWrap(True)
        layout.addWidget(info)
        listing = QListWidget(dialog)
        layout.addWidget(listing, stretch=1)

        def refill():
            listing.clear()
            for doc in self._store.list_trashed():
                item = QListWidgetItem(
                    f"{doc.title}   (banished {_local_time(doc.trashed_utc)})")
                item.setData(Qt.ItemDataRole.UserRole, doc.id)
                listing.addItem(item)
            if listing.count() == 0:
                empty = QListWidgetItem("(the wastebasket is empty)")
                empty.setFlags(Qt.ItemFlag.NoItemFlags)
                listing.addItem(empty)

        def restore():
            item = listing.currentItem()
            if item is None or item.data(Qt.ItemDataRole.UserRole) is None:
                return
            doc_id = item.data(Qt.ItemDataRole.UserRole)
            self._store.restore_document(doc_id)
            self._reload_document_list()
            self._reload_tag_filter()
            refill()
            self.statusBar().showMessage("Restored.", 4000)

        buttons = QHBoxLayout()
        restore_btn = QPushButton("&Restore Selected", dialog)
        restore_btn.clicked.connect(restore)
        buttons.addWidget(restore_btn)
        buttons.addStretch()
        close_btn = QPushButton("Close", dialog)
        close_btn.clicked.connect(dialog.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        refill()
        dialog.exec()

    def _on_learn_format(self) -> None:
        """File ▸ Learn Print Format from .docx: pick a Word document
        whose look you admire, name the format, and WordVault reads
        the page, margins, and styles out of the file and writes a
        .wvfmt that prints like it — learning by example, the way the
        KDP 6x9 format was once measured by hand."""
        import re as _re

        from PyQt6.QtWidgets import QFileDialog

        import wordvault.printing.format_file as ff
        from wordvault.printing.format_file import (
            FormatError,
            load_format,
        )
        from wordvault.printing.learn_format import learn_format

        path, _f = QFileDialog.getOpenFileName(
            self, "Learn Print Format from a Word Document", "",
            "Word documents (*.docx)")
        if not path:
            return
        default_name = Path(path).stem.replace("_", " ").strip()
        name, ok = QInputDialog.getText(
            self, "Name the Format",
            "What should this print format be called?",
            text=default_name)
        name = name.strip()
        if not ok or not name:
            return

        try:
            toml_text = learn_format(path, name)
        except Exception as exc:
            QMessageBox.warning(self, "Cannot learn format",
                                f"{Path(path).name}: {exc}")
            return

        # The learner must never emit an invalid format: validate the
        # result through the real loader before it reaches the shelf.
        ff.FORMATS_DIR.mkdir(parents=True, exist_ok=True)
        slug = _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") \
            or "learned"
        target = ff.FORMATS_DIR / f"{slug}.wvfmt"
        probe = target.with_suffix(".wvfmt.tmp")
        probe.write_text(toml_text, encoding="utf-8")
        try:
            fmt = load_format(probe)
        except FormatError as exc:
            probe.unlink(missing_ok=True)
            QMessageBox.warning(
                self, "Cannot learn format",
                f"The learned file did not validate — please report "
                f"this:\n{exc}")
            return
        probe.unlink(missing_ok=True)

        if target.exists():
            answer = QMessageBox.question(
                self, "Format exists",
                f"{target.name} already exists in your formats folder. "
                f"Replace it?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        target.write_text(toml_text, encoding="utf-8")

        traits = []
        if fmt.margins.mirrored:
            traits.append("mirror margins")
        if fmt.footer.wanted():
            traits.append("page numbers")
        summary = (f"'{name}' learned: {fmt.page_size} page, "
                   f"{fmt.body.font} {fmt.body.size_pt:g}pt body"
                   + (", " + ", ".join(traits) if traits else ""))
        QMessageBox.information(
            self, "Format learned",
            summary + f".\n\nSaved to your formats folder — it is now "
            f"a choice in File ▸ Print. Edit it anytime:\n{target}")

    def _on_export_as(self, kind: str) -> None:
        """Document ▸ Export As: the text ON SCREEN leaves the vault
        as .docx (Word styles rebuilt — the importer's exact reverse),
        .md (the text as it is), or .txt (Markdown markers stripped:
        the words without the typography)."""
        import re as _re

        if self._current_doc is None:
            self.statusBar().showMessage("No document open.", 4000)
            return
        from PyQt6.QtWidgets import QFileDialog

        text = self._editor.toPlainText()
        filters = {
            "docx": "Word documents (*.docx)",
            "md": "Markdown files (*.md)",
            "txt": "Text files (*.txt)",
        }
        stem = _re.sub(r'[<>:"/\\|?*]', "", self._current_doc.title
                       ).strip().rstrip(".") or "document"
        path, _f = QFileDialog.getSaveFileName(
            self, "Export Document", f"{stem}.{kind}", filters[kind])
        if not path:
            return
        if not path.lower().endswith(f".{kind}"):
            path += f".{kind}"          # the suffix guard, as always

        try:
            if kind == "docx":
                from wordvault.export_docx import markdown_to_docx

                markdown_to_docx(
                    text, path, title=self._current_doc.title,
                    author=str(self._settings.value("author", "")))
            elif kind == "md":
                Path(path).write_text(text, encoding="utf-8")
            else:
                plain = _speakable(text).rstrip("\n") + "\n"
                Path(path).write_text(plain, encoding="utf-8")
        except ImportError:
            QMessageBox.information(
                self, "Export",
                "Word export needs the python-docx package.\n"
                "Install it with:  pip install python-docx")
            return
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        self.statusBar().showMessage(f"Exported to {path}", 8000)

    def _on_refresh_formatting(self) -> None:
        """Library ▸ Refresh Formatting from Originals: re-read every
        imported document's original .docx with the CURRENT converter
        (which improves over time — toolbar lists, hyperlinks, tables,
        underlines, indent-quotes...).  A document whose text would
        change gets ONE new revision; the old text stays one step back
        in history.  Safe to run after every WordVault update."""
        from pathlib import Path

        from PyQt6.QtWidgets import QApplication, QProgressDialog

        from wordvault.ingest.extract import extract_markdown

        docs = [d for d in self._store.list_documents()
                if d.original_path and Path(d.original_path).exists()]
        if not docs:
            QMessageBox.information(
                self, "Refresh Formatting",
                "No documents with reachable original .docx files.")
            return
        answer = QMessageBox.question(
            self, "Refresh Formatting",
            f"Re-read {len(docs)} original .docx files with the current "
            f"converter?\n\nDocuments whose text improves get one new "
            f"revision each — nothing is overwritten, and unchanged "
            f"documents are left alone.\n\nDates are verified too: where "
            f"the Word file's own created/modified record disagrees with "
            f"what was stored (copied files lie about their age), the "
            f"stored dates are corrected.")
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._autosave()
        progress = QProgressDialog(
            "Refreshing formatting…", "Stop", 0, len(docs), self)
        progress.setWindowTitle("Refresh Formatting")
        progress.setMinimumDuration(0)
        from wordvault.ingest.pipeline import repair_document_dates

        changed = errors = dates_fixed = 0
        for index, doc in enumerate(docs):
            if progress.wasCanceled():
                break
            progress.setValue(index)
            progress.setLabelText(doc.title)
            QApplication.processEvents()
            try:
                markdown = extract_markdown(doc.original_path)
                if repair_document_dates(self._store, doc):
                    dates_fixed += 1
            except Exception:          # one bad file must not stop 1,800
                errors += 1
                continue
            latest = self._store.latest_revision(doc.id)
            current = self._store.get_text(latest.id) if latest else ""
            if markdown != current:
                self._store.save_revision(doc.id, markdown, origin="ingest")
                changed += 1
        progress.setValue(len(docs))

        # The open document may be among the improved: show its new text.
        if self._current_doc is not None:
            self._open_document(self._current_doc.id)
        self._reload_document_list()
        message = (f"{changed} document(s) improved (one new revision "
                   f"each), {len(docs) - changed - errors} already "
                   f"current.")
        if dates_fixed:
            message += (f"\n{dates_fixed} document(s) had their dates "
                        f"corrected from the Word files' own records.")
        if errors:
            message += f"\n{errors} file(s) could not be read."
        QMessageBox.information(self, "Refresh Formatting", message)

    def _on_provenance_report(self) -> None:
        """Document ▸ Provenance Report: the construction story of the
        open document, assembled from the vault's own record (growth,
        sessions, labor, corrections — see wordvault/provenance.py),
        shown for reading and saved as Markdown on request."""
        if self._current_doc is None:
            QMessageBox.information(self, "Provenance Report",
                                    "Open a document first.")
            return
        from PyQt6.QtWidgets import QApplication as _QApp

        from wordvault import __version__
        from wordvault.provenance import build_report, word_count

        _QApp.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            # Every revision's word count — the growth curve.  Hundreds
            # of small reads; a few seconds for a long-lived essay.
            revisions = [
                (r.created_utc, word_count(self._store.get_text(r.id)))
                for r in self._store.list_revisions(self._current_doc.id)
            ]
            report = build_report(
                title=self._current_doc.title,
                created_utc=self._current_doc.created_utc,
                revisions=revisions,
                editing_seconds=self._store.editing_seconds(
                    self._current_doc.id),
                spelling_rows=self._store.spelling_for_document(
                    self._current_doc.id),
                program_version=__version__,
            )
        finally:
            _QApp.restoreOverrideCursor()

        from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QPlainTextEdit,
                                     QPushButton, QVBoxLayout)

        dialog = QDialog(self)
        dialog.setWindowTitle(
            f"Provenance Report — {self._current_doc.title}")
        dialog.resize(720, 560)
        layout = QVBoxLayout(dialog)
        view = QPlainTextEdit(report, dialog)
        view.setReadOnly(True)
        layout.addWidget(view)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_btn = QPushButton("&Save as Markdown…", dialog)

        def save():
            from PyQt6.QtWidgets import QFileDialog

            suggested = f"{self._current_doc.title} — provenance.md"
            path, _f = QFileDialog.getSaveFileName(
                dialog, "Save Provenance Report", suggested,
                "Markdown (*.md)")
            if path:
                Path(path).write_text(report, encoding="utf-8")
                self.statusBar().showMessage(f"Report saved: {path}", 6000)

        save_btn.clicked.connect(save)
        close_btn = QPushButton("Close", dialog)
        close_btn.clicked.connect(dialog.accept)
        buttons.addWidget(save_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)
        dialog.exec()

    def _on_formatter(self) -> None:
        """Open (or raise) the Book Formatter — a NON-modal window, so
        writing in WordVault can continue while a book sits open.  One
        window per session: reopening raises the same one, keeping its
        chapter list and unsaved edits."""
        from wordvault.formatter.window import FormatterWindow

        self._autosave()   # the book builds from saved library text
        existing = getattr(self, "_formatter_window", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        self._formatter_window = FormatterWindow(
            self._store, self._settings, self
        )
        self._formatter_window.show()

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
            cursor.selectedText().replace("\u2029", "\n"),
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
        self._save_current_note()     # the OUTGOING document's notes
        # A departure photograph belongs to ONE document's excursion:
        # carrying it across an open would send a later Newest click to
        # another essay's coordinates.
        self._live_departure = None
        self._current_doc = self._store.get_document(doc_id)
        self._record_recent(doc_id)   # feeds File ▸ Recent
        self._go_live()
        self._set_editor_enabled(True)
        self._load_note(doc_id)
        self._refresh_title_header()
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
        self._editor.setReadOnly(False)   # also restores full editing flags
        self._set_edit_mode_visuals(live=True)

        self._timeline.set_range(len(self._revisions), len(self._revisions) - 1)
        self._timeline.set_live(True)
        self._timeline.set_info(
            _local_time(self._revisions[-1].created_utc) + " · newest"
            if self._revisions else "no revisions yet"
        )
        self._refresh_title_header()
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
            # Leaving live mode: photograph WHERE we are leaving from —
            # scroll and cursor — BEFORE anything else can go wrong.  A
            # trip into history is an excursion: when the traveler
            # clicks Newest, no diff-mapping can know where they started
            # (the passage they left may not even EXIST in older
            # drafts), but this memory does, exactly.  The belt-and-
            # braces guard (flag OR an editable editor) exists because a
            # stale photograph sends every return to the WRONG trip's
            # spot — the 'each return lands one test behind' report.
            if self._is_live or not self._editor.isReadOnly():
                self._live_departure = (
                    self._editor.verticalScrollBar().value(),
                    self._editor.textCursor().position(),
                )
            # Then capture unsaved words, so replacing the editor's
            # content with history cannot lose anything.
            if self._is_live:
                self._commit_live_text()

            self._revisions = self._store.list_revisions(self._current_doc.id)
            if not self._revisions:
                return
            index = max(0, min(index, len(self._revisions) - 1))
            live = index == len(self._revisions) - 1

            rev = self._revisions[index]
            # Hold the reading position across the swap: revisions of
            # one document mostly share their lines, so restoring the
            # same scroll value keeps the SAME PLACE in the text on
            # screen while stepping through time (instead of snapping
            # to page one at every step).
            from PyQt6.QtCore import QTimer

            # Where should the view sit after the step?
            #   * arriving at NEWEST -> back exactly where the live
            #     document was left (the departure photograph above):
            #     the round trip live -> history -> Newest always ends
            #     where it began, even when the passage being written
            #     did not exist in the drafts just visited;
            #   * at the document's END -> stay pinned to the end (the
            #     cusp of the history, where essays grow — stepping
            #     back plays the growth in reverse);
            #   * anywhere ELSE -> hold the PASSAGE, not the pixels.
            #     A raw scrollbar value lies across revisions (older
            #     drafts have different text above the same passage —
            #     the bug where "The key things I take…" became "in
            #     the temple. This"), so the anchor is the LINE in the
            #     middle of the view, mapped by content into the target
            #     revision (corresponding_line) and re-centered there.
            target_text = self._store.get_text(rev.id)
            bar = self._editor.verticalScrollBar()
            at_end = bar.value() >= bar.maximum() - 2
            departure = getattr(self, "_live_departure", None)
            if live and departure is not None:
                self._pending_scroll = ("live", departure)
            elif at_end:
                self._pending_scroll = None
            else:
                from PyQt6.QtCore import QPoint

                midpoint = QPoint(5, self._editor.viewport().height() // 2)
                mid_cursor = self._editor.cursorForPosition(midpoint)
                watched = mid_cursor.blockNumber()
                # Three coordinates make the hold exact:
                #   * the line, mapped by content into the target text;
                #   * the offset WITHIN it — an essay paragraph can fill
                #     the whole screen (one block!), and anchoring to
                #     its start alone snapped every step to word one of
                #     it (the 'word 1,940' screenshots);
                #   * the line's on-screen HEIGHT, so the restore puts
                #     it back at the very same pixels.  Re-centering
                #     instead rounded half a line into a whole-line
                #     creep at the top of the document.
                self._pending_scroll = (
                    "line",
                    corresponding_line(
                        self._editor.toPlainText(), target_text, watched),
                    mid_cursor.positionInBlock(),
                    self._editor.cursorRect(mid_cursor).top(),
                )
            self._editor.set_text_quietly(target_text)

            # Twice on purpose: once now (best effort), and once after
            # the event loop lets the new text finish laying out — at
            # THIS moment the scrollbar's maximum is still 0, so an
            # immediate restore alone gets clamped back to page one
            # (the very bug being fixed).  The deferred call MUST be a
            # bound method (not a closure): PyQt ties the timer to this
            # window's lifetime, so a window closed before the timer
            # fires cancels it instead of crashing on dead widgets.
            self._restore_tries = 0       # fresh retry budget per step
            self._restore_history_scroll()
            QTimer.singleShot(0, self._restore_history_scroll)
            self._editor.setReadOnly(not live)
            if not live:
                # Read-only, but NOT dead: keyboard selection gives a
                # visible cursor, so clicking into an old version shows
                # where you are, and Ctrl+C copies — paste into the
                # notes pane now, or into the text after Newest.
                self._editor.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                    | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self._set_edit_mode_visuals(live=live)
            if not live:
                self.statusBar().showMessage(
                    "Viewing an old version (read-only). Select and copy "
                    "freely — click Newest or Restore to edit again.", 8000)
            self._is_live = live

            # Keep the slider consistent with the (possibly grown) history.
            self._timeline.set_range(len(self._revisions), index)
            self._timeline.set_live(live)
            self._timeline.set_info(
                _local_time(rev.created_utc)
                + (" · newest" if live else f" · {rev.origin}")
            )
            self._refresh_title_header()
            self._update_status()
            # Hoist and age tinting refer to the LIVE text; entering
            # history clears both (age colors return on going live).
            self._editor.clear_focus_lines()
            self._refresh_outline()
            self._apply_age_colors()
            # And the history view gets its own light: a quiet wash on
            # the words that have since been changed.
            self._apply_history_change_tint(live)
        finally:
            self._navigating = False

    def _apply_history_change_tint(self, live: bool) -> None:
        """While time traveling, wash the words of the viewed old
        version that do NOT survive into the newest text — the material
        that has since been rewritten or removed.  The farther back the
        slider goes, the more of the page carries the wash: a quiet map
        of how much the essay has moved since that day.

        Only runs in history mode, where the ExtraSelections channel is
        otherwise idle (age colors are a live-mode feature).  The wash
        is wheat — kin to the amber history border — with a dark-theme
        counterpart, and touches only the background so the words stay
        perfectly readable."""
        if live or not self._revisions:
            return                     # live mode: age colors own the channel
        old_text = self._editor.toPlainText()
        newest_text = self._store.get_text(self._revisions[-1].id)
        color = (CHANGED_WASH_DARK if self._dark_mode
                 else CHANGED_WASH_LIGHT)
        doc = self._editor.document()
        limit = doc.characterCount() - 1   # clamp: QTextDocument's end
        selections = []
        for start, end in changed_word_spans(old_text, newest_text):
            cursor = QTextCursor(doc)
            cursor.setPosition(min(start, limit))
            cursor.setPosition(min(end, limit),
                               QTextCursor.MoveMode.KeepAnchor)
            fmt = QTextCharFormat()
            fmt.setBackground(color)
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format = fmt
            selections.append(sel)
        self._editor.setExtraSelections(
            selections + self._read_light_selections())

    def _refresh_title_header(self) -> None:
        """The serif title header also announces WHICH state of the
        document is on screen: 'draft N of M — date'.  While time
        traveling it names the viewed old draft, so the header always
        answers 'what am I looking at?'."""
        from html import escape

        if self._current_doc is None:
            self._title_label.setText("No document open")
            return
        title = escape(self._current_doc.title)
        total = len(self._revisions)
        if not total:
            self._title_label.setText(title)
            return
        index = total - 1 if self._is_live else \
            max(0, min(self._timeline.position(), total - 1))
        stamp = _local_time(self._revisions[index].created_utc)
        suffix = f"draft {index + 1} of {total} — {stamp}"
        self._title_label.setText(
            f"{title}&nbsp;&nbsp;<span style='font-size:9pt; "
            f"font-weight:normal; color:#5a6b7d;'>{suffix}</span>")

    def _restore_history_scroll(self) -> None:
        """Re-apply the view position noted before a history step (see
        _on_timeline_moved) or a Read Aloud start.  _pending_scroll
        speaks three dialects:
          * None            -> the end of the document;
          * an int          -> a raw scrollbar value (Read Aloud: the
                               text has not changed, so it is exact);
          * ("live", (v,p)) -> the departure photograph: arriving back
                               at Newest restores scroll value v and
                               cursor position p exactly — the text is
                               the very text that was left, so raw
                               values are truthful again;
          * ("line", n, o, y) -> put offset o inside line n back at
                               viewport height y — the content anchor
                               used when stepping between revisions.
                               The offset matters (a screen-filling
                               paragraph is ONE block; without it every
                               step snapped to its first word), and the
                               height matters (re-centering rounded
                               half a line into a one-line creep at the
                               top of the document).
        Runs immediately, via a 0 ms timer, and then RETRIES briefly:
        QPlainTextEdit lays a long document out lazily, so right after
        a text swap the scrollbar's maximum is still growing — an
        exact setValue clamps short unless re-applied once the layout
        has caught up (the 'returned to the wrong screen' bug)."""
        from PyQt6.QtCore import QTimer

        pos = getattr(self, "_pending_scroll", None)
        bar = self._editor.verticalScrollBar()
        retry = False
        if pos is None:
            bar.setValue(bar.maximum())
            retry = True                  # the true maximum may not exist yet
        elif isinstance(pos, tuple) and pos[0] == "live":
            value, cursor_pos = pos[1]
            doc = self._editor.document()
            cursor = self._editor.textCursor()
            cursor.setPosition(min(cursor_pos, doc.characterCount() - 1))
            self._editor.setTextCursor(cursor)   # ensures visibility…
            bar.setValue(min(value, bar.maximum()))  # …then exact frame
            retry = bar.maximum() < value
        elif isinstance(pos, tuple):
            doc = self._editor.document()
            number = max(0, min(pos[1], doc.blockCount() - 1))
            offset = pos[2] if len(pos) > 2 else 0
            anchor_y = pos[3] if len(pos) > 3 else None
            block = doc.findBlockByNumber(number)
            # The (visible, read-only) cursor rides along at the
            # watched spot — so the traveler always sees where the
            # anchor believes they are.
            cursor = QTextCursor(block)
            cursor.setPosition(block.position()
                               + min(offset, max(block.length() - 2, 0)))
            self._editor.setTextCursor(cursor)
            self._editor.centerCursor()       # first, get it on screen…
            if anchor_y is not None:
                # …then slide it to the very height it occupied before
                # the step, in whole visual lines (the scrollbar's
                # unit).  This is what makes the hold pixel-faithful.
                rect = self._editor.cursorRect()
                line_height = max(1, rect.height())
                delta = round((rect.top() - anchor_y) / line_height)
                if delta:
                    bar.setValue(bar.value() + delta)
        else:
            bar.setValue(min(pos, bar.maximum()))
            retry = bar.maximum() < pos
        if retry and getattr(self, "_restore_tries", 0) < 20:
            self._restore_tries = getattr(self, "_restore_tries", 0) + 1
            QTimer.singleShot(15, self._restore_history_scroll)

    def _apply_font_family(self, family: str) -> None:
        """Dress the editor in the chosen typeface; the notes pane
        follows UNLESS it has its own setting (_apply_notes_font runs
        after this and overrides).  Empty family = platform default."""
        if not family:
            return
        self._editor.set_font_family(family)
        notes_font = self._notes.font()
        notes_font.setFamily(family)
        self._notes.setFont(notes_font)

    def _apply_notes_font(self) -> None:
        """The notes pane's OWN typeface and size (Settings knobs,
        Aug 2026).  Unset values leave the follow-the-editor defaults
        alone, so nothing changes until a choice is made."""
        family = str(self._settings.value("notes_font_family", ""))
        try:
            size = int(self._settings.value("notes_font_pt", 0))
        except (TypeError, ValueError):
            size = 0
        font = self._notes.font()
        if family:
            font.setFamily(family)
        if size:
            font.setPointSize(max(7, min(24, size)))
        self._notes.setFont(font)

    def _on_notes_context_menu(self, pos) -> None:
        """Right-click in the notes: the standard menu, topped with
        spelling suggestions — the same courtesy the editor extends."""
        from wordvault.editor.spelling import get_spelling

        menu = self._notes.createStandardContextMenu()
        spelling = get_spelling()
        if spelling.is_available() and self._notes_highlighter.spelling_enabled:
            from PyQt6.QtGui import QTextCursor

            cursor = self._notes.cursorForPosition(pos)
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            word = cursor.selectedText()
            if word and spelling.is_misspelled(word):
                first = menu.actions()[0] if menu.actions() else None
                for suggestion in spelling.suggestions(word):
                    action = menu.addAction(suggestion)
                    menu.insertAction(first, action)
                    action.triggered.connect(
                        lambda _c, s=suggestion, cur=cursor: cur.insertText(s))
                add_action = menu.addAction(f"Add “{word}” to dictionary")
                menu.insertAction(first, add_action)
                add_action.triggered.connect(
                    lambda _c, w=word: (
                        spelling.add_to_dictionary(w),
                        self._notes_highlighter.rehighlight(),
                        self._editor.markdown_highlighter.rehighlight(),
                    ))
                menu.insertSeparator(first)
        menu.exec(self._notes.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------ theme --

    def _apply_theme(self, dark: bool) -> None:
        """Dress the whole program light or dark, LIVE (Settings box).

        Dark mode = Qt's Fusion style with a hand-built dark palette
        (identical on Windows and Ubuntu) plus dark counterparts for
        every surface we color ourselves: the title banner, the notes
        tint, and the history-view amber.  Unchecking restores the
        platform's own style, captured before we ever touched it."""
        from PyQt6.QtGui import QPalette
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        self._dark_mode = dark
        if dark:
            app.setStyle("Fusion")
            palette = QPalette()
            roles = QPalette.ColorRole
            for role, color in (
                (roles.Window, "#2b2d31"), (roles.WindowText, "#e4e6e9"),
                (roles.Base, "#232428"), (roles.AlternateBase, "#2b2d31"),
                (roles.Text, "#e4e6e9"), (roles.Button, "#2b2d31"),
                (roles.ButtonText, "#e4e6e9"), (roles.BrightText, "#ffffff"),
                (roles.Highlight, "#2f6fce"),
                (roles.HighlightedText, "#ffffff"),
                (roles.ToolTipBase, "#3a3d42"),
                (roles.ToolTipText, "#e4e6e9"),
                (roles.PlaceholderText, "#8a8f98"),
                (roles.Link, "#6fa8ff"),
            ):
                palette.setColor(role, QColor(color))
            palette.setColor(QPalette.ColorGroup.Disabled,
                             roles.Text, QColor("#6b6f76"))
            palette.setColor(QPalette.ColorGroup.Disabled,
                             roles.ButtonText, QColor("#6b6f76"))
            app.setPalette(palette)
            self._title_label.setStyleSheet(
                "QLabel { font-family: Georgia, 'Times New Roman', serif;"
                "  font-size: 15pt; font-weight: bold;"
                "  color: #9fc0e8; background: #202226;"
                "  padding: 5px 10px; border-bottom: 1px solid #3a3d42; }")
            self._notes.setStyleSheet(
                "QPlainTextEdit { background: #26251f; }"
                "QPlainTextEdit:focus { border: 2px solid #2f6fce; }")
            self._editor.setStyleSheet(
                'QPlainTextEdit[mode="live"] { background: #232428; }'
                'QPlainTextEdit[mode="live"]:focus'
                '  { border: 2px solid #2f6fce; }'
                'QPlainTextEdit[mode="history"]'
                '  { border: 2px solid #c98a00; background: #2e2a20; }')
            self._editor.set_line_light_color(QColor("#2c3038"))
        else:
            app.setStyle(self._base_style_name)
            app.setPalette(self._base_palette)   # the REAL original
            self._title_label.setStyleSheet(
                "QLabel { font-family: Georgia, 'Times New Roman', serif;"
                "  font-size: 15pt; font-weight: bold;"
                "  color: #1c3a5e; background: #f4f6f8;"
                "  padding: 5px 10px; border-bottom: 1px solid #c9d2dc; }")
            self._notes.setStyleSheet(
                "QPlainTextEdit { background: #fbfaf4; }"
                "QPlainTextEdit:focus { border: 2px solid #2f6fce; }")
            self._editor.setStyleSheet(
                'QPlainTextEdit[mode="live"] { background: #ffffff; }'
                'QPlainTextEdit[mode="live"]:focus'
                '  { border: 2px solid #2f6fce; }'
                'QPlainTextEdit[mode="history"]'
                '  { border: 2px solid #c98a00; background: #fbf6ea; }')
            self._editor.set_line_light_color(QColor("#eef3f9"))

        # The framed side panels (Outline, Doc Info, Library Info):
        # their stylesheets must carry explicit theme colors, because
        # a styled widget no longer listens to the palette (the
        # white-Outline-in-the-dark lesson).
        for panel in getattr(self, "_panel_frames", []):
            inner = panel.objectName()
            if dark:
                panel.setStyleSheet(
                    f"#{inner} {{ border: 1px solid #3a4148;"
                    f" border-radius: 6px; background: #232428;"
                    f" color: #e4e6e9; }}")
            else:
                panel.setStyleSheet(
                    f"#{inner} {{ border: 1px solid #b9c4d0;"
                    f" border-radius: 6px; }}")

        # Palette-dependent paintwork follows the new theme.
        self._editor.markdown_highlighter.rehighlight()
        self._notes_highlighter.rehighlight()
        self._apply_age_colors()

    def _set_edit_mode_visuals(self, live: bool) -> None:
        """Repaint the editor's mode border (see the stylesheet where
        the editor is built).  Qt evaluates property selectors only at
        polish time, so changing the property must be followed by an
        explicit unpolish/polish round trip."""
        self._editor.setProperty("mode", "live" if live else "history")
        self._editor.style().unpolish(self._editor)
        self._editor.style().polish(self._editor)

    def _on_restore(self) -> None:
        """Append the currently VIEWED old state as a brand-new revision.
        History stays intact; the old state simply becomes the newest."""
        if self._is_live or self._current_doc is None:
            return  # nothing to restore when already viewing the newest
        self._store.save_revision(
            self._current_doc.id, self._editor.toPlainText(), origin="restore"
        )
        self.statusBar().showMessage(
            "Restored — the old state is now the newest draft.", 5000)
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
        self._save_current_note()
        self._current_doc = None
        self._revisions = []
        self._is_live = True
        self._set_editor_enabled(False)
        self._info_panel.clear()
        self._outline.set_outline([])
        self._timeline.set_range(0, 0)
        self._update_status()

    def _recent_limit(self) -> int:
        """How far back File ▸ Recent remembers — a Settings knob
        (default 25), clamped to the dialog's own 5..100 range so a
        hand-edited registry value cannot misbehave."""
        try:
            value = int(self._settings.value("recent_limit", 25))
        except (TypeError, ValueError):
            value = 25
        return max(5, min(100, value))

    def _record_recent(self, doc_id: int) -> None:
        """Move doc_id to the front of the persisted recents, trimmed
        to the Settings limit."""
        recent = [int(x) for x in self._settings.value("recent_docs", []) or []]
        recent = [doc_id] + [d for d in recent if d != doc_id]
        self._settings.setValue(
            "recent_docs", [str(d) for d in recent[: self._recent_limit()]])

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
            if doc.trashed_utc:
                continue  # the wastebasket is banished from Recent too
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

    _PLAIN_FORMAT = "Plain (as displayed)"

    def _on_print(self) -> None:
        """File ▸ Print: pick a format BY NAME, then print — the styled
        page is first seen on paper (non-WYSIWYG, by design; a
        Print-to-PDF printer is the paper-free check).  The chosen
        format's page size and margins outrank Page Setup."""
        from PyQt6.QtPrintSupport import QPrintDialog

        from wordvault.printing import list_formats

        if self._current_doc is None:
            QMessageBox.information(self, "Print", "Open a document first.")
            return
        self._autosave()

        # ---- choose the format (remembered per document) ----
        # Each entry lists its features, so what will print is visible
        # BEFORE printing — the only preview a non-WYSIWYG system needs.
        formats = list_formats()

        def describe(f):
            tags = []
            if f.byline_text:
                tags.append("byline")
            if f.header.wanted():
                tags.append("header")
            if f.footer.wanted():
                tags.append("page numbers")
            if f.margins.mirrored:
                tags.append("mirror margins")
            return f.name + (f"   ({', '.join(tags)})" if tags else "")

        display = [self._PLAIN_FORMAT] + [describe(f) for f in formats]
        real_names = [self._PLAIN_FORMAT] + [f.name for f in formats]
        remembered = str(self._settings.value(
            f"print_format:{self._current_doc.uuid}", self._PLAIN_FORMAT
        ))
        current = (real_names.index(remembered)
                   if remembered in real_names else 0)
        choice, ok = QInputDialog.getItem(
            self, "Print Format",
            "Print with format (defined in ~/.wordvault/formats):",
            display, current, editable=False,
        )
        if not ok:
            return
        chosen_name = real_names[display.index(choice)]
        self._settings.setValue(
            f"print_format:{self._current_doc.uuid}", chosen_name
        )
        chosen = next((f for f in formats if f.name == chosen_name), None)

        printer = self._ensure_printer()
        printer.setDocName(self._current_doc.title)
        if chosen is not None:
            from wordvault.printing.renderer import apply_page_setup

            apply_page_setup(printer, chosen)

        dialog = QPrintDialog(printer, self)
        if dialog.exec():
            # Print-to-file always produces PDF content; a filename typed
            # with another suffix (test.txt) would be a PDF in disguise.
            out = printer.outputFileName()
            if out and not out.lower().endswith(".pdf"):
                stem = out.rsplit(".", 1)[0] if "." in Path(out).name else out
                printer.setOutputFileName(stem + ".pdf")
            if chosen is None:
                # Plain: the text as displayed in the editor.
                self._editor.document().print(printer)
            else:
                from wordvault.printing.renderer import print_styled

                # Handles normal AND mirrored margins, headers/footers,
                # and the byline's {title}/{author}/{date} variables.
                print_styled(
                    printer, self._editor.toPlainText(), chosen,
                    title=self._current_doc.title,
                    author=str(self._settings.value("author", "")),
                )
            self.statusBar().showMessage(
                f"Sent to printer ({choice}).", 6000
            )

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
        self._notes_highlighter.spelling_enabled = on   # notes follow
        self._notes_highlighter.rehighlight()
        self._settings.setValue("spelling", on)

    # ------------------------------------------- spelling-habits watcher ---

    def _on_spelling_correction(self, typed: str, corrected: str) -> None:
        """A misspelled word was fixed (menu click or hand edit): classify
        and log it for the habits report; teach the autocorrecter."""
        from wordvault.editor.spelling import classify_error

        kind, detail = classify_error(typed, corrected)
        self._store.log_spelling_fix(
            self._current_doc.id if self._current_doc else None,
            typed, corrected, kind, detail,
        )
        self._refresh_autocorrect()

    def _on_suggestion_correction(self, typed: str, corrected: str) -> None:
        """A suggestion was clicked: log it, then — because rare words are
        bursty and repeat — apply the same fix to every other occurrence
        in the document (one undo step)."""
        self._on_spelling_correction(typed, corrected)
        if not self._autocorrect_action.isChecked():
            return
        from wordvault.editor.spelling import apply_correction_to_text

        text = self._editor.toPlainText()
        new_text, count = apply_correction_to_text(text, typed, corrected)
        if count == 0:
            return
        # Replace as ONE undoable edit, keeping the cursor near its place.
        cursor = self._editor.textCursor()
        position = cursor.position()
        whole = QTextCursor(self._editor.document())
        whole.select(QTextCursor.SelectionType.Document)
        whole.beginEditBlock()
        whole.insertText(new_text)
        whole.endEditBlock()
        cursor.setPosition(min(position, len(new_text)))
        self._editor.setTextCursor(cursor)
        for _ in range(count):
            self._store.log_spelling_fix(
                self._current_doc.id if self._current_doc else None,
                typed, corrected, "auto repeat", "",
            )
        self.statusBar().showMessage(
            f"Also corrected {count} more “{typed}” in this document "
            f"(Ctrl+Z undoes).", 7000,
        )

    def _on_autocorrected(self, typed: str, corrected: str) -> None:
        """The editor repaired a learned typo as it was typed."""
        self._store.log_spelling_fix(
            self._current_doc.id if self._current_doc else None,
            typed, corrected, "auto repeat", "",
        )
        self.statusBar().showMessage(
            f"Auto-corrected “{typed}” → “{corrected}”.", 4000
        )

    def _refresh_autocorrect(self) -> None:
        """Feed the editor the learned typo->fix pairs (or switch off),
        and hand the FULL error history to the suggestion engine — a
        misspelling fixed even once leads its suggestion list ever
        after, and every corrected-to word joins the sound-alike
        index."""
        if self._autocorrect_action.isChecked():
            self._editor.set_autocorrect_lookup(
                self._store.learned_corrections()
            )
        else:
            self._editor.set_autocorrect_lookup(None)
        from wordvault.editor.spelling import get_spelling

        history: dict[str, tuple[str, int]] = {}
        for typed, corrected, count in self._store.spelling_pairs():
            if typed not in history:      # rows arrive most-counted first
                history[typed] = (corrected, count)
        get_spelling().set_history(history)

    def _on_spelling_dictionary(self) -> None:
        """Help ▸ Spelling Dictionary: type a word and learn its whole
        standing at once — known or not, yours or the dictionary's,
        stumbled over before (and fixed to what), and what it might
        BE if it is a misspelling (the sound-alike finder).  Unknown
        words can be added on the spot."""
        from PyQt6.QtWidgets import (
            QDialog,
            QHBoxLayout,
            QLineEdit,
            QListWidget,
            QPushButton,
            QVBoxLayout,
        )

        from wordvault.editor.spelling import get_spelling

        spelling = get_spelling()
        if not spelling.is_available():
            QMessageBox.information(
                self, "Spelling Dictionary",
                "Spell checking needs the pyspellchecker package.\n"
                "Install it with:  pip install pyspellchecker")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Spelling Dictionary")
        dialog.resize(480, 520)
        layout = QVBoxLayout(dialog)

        entry = QLineEdit(dialog)
        entry.setPlaceholderText("Type a word…")
        layout.addWidget(entry)
        verdict = QLabel("", dialog)
        verdict.setWordWrap(True)
        layout.addWidget(verdict)
        add_btn = QPushButton("&Add to My Dictionary", dialog)
        add_btn.setEnabled(False)
        layout.addWidget(add_btn)
        teach_btn = QPushButton("Record as &Misspelling of…", dialog)
        teach_btn.setToolTip(
            "Teach the pair directly: this word is YOUR spelling of a "
            "real one.  It joins your history — findable in this list, "
            "first in suggestions, and (repeated) auto-corrected."
        )
        teach_btn.setEnabled(False)
        layout.addWidget(teach_btn)
        layout.addWidget(QLabel("Matching words — ★ yours, your past "
                                "fixes (typed → corrected), then the "
                                "standard dictionary:", dialog))
        listing = QListWidget(dialog)
        layout.addWidget(listing, stretch=1)
        close_btn = QPushButton("Close", dialog)
        close_btn.clicked.connect(dialog.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close_btn)
        layout.addLayout(row)

        history_pairs = self._store.spelling_pairs()

        def refill_list(needle: str = "") -> None:
            """Three sources (see _dictionary_listing): your words,
            your past fixes — a misspelling looks up its word, so
            'jep' surfaces 'jeprodising → jeopardizing' — and the
            standard dictionary's completions."""
            listing.clear()
            for row in _dictionary_listing(
                    needle, spelling.personal_words(), history_pairs,
                    spelling.prefix_matches(needle)):
                listing.addItem(row)

        def examine() -> None:
            word = entry.text().strip()
            add_btn.setEnabled(False)
            teach_btn.setEnabled(False)
            refill_list(word)
            if not word:
                verdict.setText("")
                return
            lines = []
            if spelling.is_personal(word):
                lines.append(f"“{word}” is in YOUR dictionary.")
            elif spelling.is_standard(word):
                lines.append(f"“{word}” is in the standard dictionary.")
            else:
                lines.append(f"“{word}” is not in any dictionary.")
                add_btn.setEnabled(True)
                teach_btn.setEnabled(True)
                mates = spelling.suggestions(word)
                if mates:
                    lines.append("Did you mean: " + ", ".join(mates) + "?")
            for typed, corrected, count in \
                    self._store.spelling_matches(word):
                times = f"{count}×" if count > 1 else "once"
                lines.append(
                    f"History: you typed “{typed}” and corrected it "
                    f"to “{corrected}” ({times}).")
            verdict.setText("\n".join(lines))

        def add_word() -> None:
            word = entry.text().strip()
            if word:
                spelling.add_to_dictionary(word)
                self._editor.markdown_highlighter.rehighlight()
                self._notes_highlighter.rehighlight()
                examine()

        def teach_pair() -> None:
            """Record 'this word is my spelling of THAT one' by hand —
            for pairs the live watcher never caught (a misspelling
            retyped as another misspelling leaves no trail)."""
            nonlocal history_pairs
            from PyQt6.QtWidgets import QInputDialog

            word = entry.text().strip().lower()
            if not word:
                return
            mates = spelling.suggestions(word)
            correct, ok = QInputDialog.getText(
                dialog, "Record Misspelling",
                f"“{word}” is your spelling of:",
                text=mates[0].lower() if mates else "")
            correct = correct.strip().lower()
            if not ok or not correct or correct == word:
                return
            from wordvault.editor.spelling import classify_error

            kind, detail = classify_error(word, correct)
            self._store.log_spelling_fix(None, word, correct,
                                         kind, detail or "taught")
            history_pairs = self._store.spelling_pairs()
            self._refresh_autocorrect()   # suggestions learn it at once
            examine()

        entry.textChanged.connect(examine)
        add_btn.clicked.connect(add_word)
        teach_btn.clicked.connect(teach_pair)
        refill_list()
        entry.setFocus()
        dialog.exec()

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
        self._refresh_title_header()
        self._reload_document_list()
        self._refresh_info()
        self.statusBar().showMessage("Renamed.", 4000)

    def _on_step_chapter(self, direction: int) -> None:
        """Ctrl+Alt+Up/Down: open the previous/next chapter of the
        book the current document belongs to.

        The chapter ORDER lives in the last saved .wvbook project (the
        Formatter remembers it in settings) — tags mark membership,
        but only the project knows the sequence.  With no current
        document, +1 opens the book's first chapter."""
        from pathlib import Path

        from wordvault.formatter.book import BookProject, BookProjectError

        last = str(self._settings.value("formatter/last_project", ""))
        if not last or not Path(last).exists():
            self.statusBar().showMessage(
                "No book project yet — save one in Library ▸ "
                "Book Formatter first.", 6000)
            return
        try:
            project = BookProject.load(last)
        except BookProjectError as exc:
            self.statusBar().showMessage(str(exc), 6000)
            return
        uuids = [ref.uuid for ref in project.chapters]
        if not uuids:
            self.statusBar().showMessage(
                "The book project has no chapters.", 6000)
            return

        if self._current_doc is not None and self._current_doc.uuid in uuids:
            index = uuids.index(self._current_doc.uuid) + direction
        else:
            # Not inside the book: jump to its first or last chapter.
            index = 0 if direction > 0 else len(uuids) - 1
        if not (0 <= index < len(uuids)):
            edge = "first" if index < 0 else "last"
            self.statusBar().showMessage(
                f"Already at the {edge} chapter of "
                f"'{project.title}'.", 4000)
            return
        doc = self._store.get_document_by_uuid(uuids[index])
        if doc is None:
            self.statusBar().showMessage(
                "That chapter is no longer in the library.", 6000)
            return
        self._autosave()
        self._open_document(doc.id)
        self.statusBar().showMessage(
            f"Chapter {index + 1} of {len(uuids)} — "
            f"'{project.title}'", 4000)

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
            self._editor.setExtraSelections(self._read_light_selections())
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
        self._editor.setExtraSelections(
            selections + self._read_light_selections())

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

    # ------------------------------------------------- the editing clock --

    def _on_edit_activity(self) -> None:
        """One genuine keystroke: extend the writing clock.  Gaps up
        to EDIT_GAP_SECONDS between keystrokes count as writing (the
        pauses in which sentences are composed); longer gaps count as
        absence and add nothing.  So the clock measures the time your
        hands and mind were actually on THIS document — never the
        hours it merely sat open."""
        import time

        if self._current_doc is None or not self._is_live:
            return
        now = time.monotonic()
        if self._edit_clock_doc != self._current_doc.id:
            self._flush_edit_clock()          # credit the previous doc
            self._edit_clock_doc = self._current_doc.id
            self._edit_last_monotonic = now
            return
        if self._edit_last_monotonic is not None:
            gap = now - self._edit_last_monotonic
            if gap <= EDIT_GAP_SECONDS:
                self._edit_pending += gap
        self._edit_last_monotonic = now

    def _flush_edit_clock(self) -> None:
        """Bank the pending seconds into the vault (on autosave,
        document switch, and close — cheap and often).  Only the
        pending count resets: the session itself continues, so a flush
        in mid-writing costs the clock nothing."""
        if self._edit_clock_doc is not None and self._edit_pending >= 1.0:
            try:
                self._store.add_editing_seconds(
                    self._edit_clock_doc, int(self._edit_pending))
            except KeyError:
                pass                       # the document left the vault
            self._edit_pending = 0.0

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
        # The editing clock: banked seconds plus the unbanked pending
        # ones from the session in progress.
        edit_seconds = self._store.editing_seconds(doc.id)
        if self._edit_clock_doc == doc.id:
            edit_seconds += int(self._edit_pending)
        self._info_panel.update_info(
            title=doc.title,
            chain_text=chain_text,
            created=_local_time(doc.created_utc),
            last_edited=last_edit,
            revision_count=len(self._revisions),
            word_count=len(self._editor.toPlainText().split()),
            tags=[t.name for t in self._store.tags_for(doc.id)],
            verse_count=len(self._store.verses_for(doc.id)),
            editing_time=_format_edit_time(edit_seconds),
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
        # (No "saved HH:MM" label anymore: the title header's draft
        # count and date advance on every save — confirmation enough.)
        return rev

    def _autosave(self) -> None:
        """Typing-pause / Ctrl+S / switch-document save.  Live mode only —
        in history mode the editor holds OLD text, which must never be
        recorded as new typing."""
        if self._current_doc is None or not self._is_live:
            return
        self._save_current_note()    # notes ride along with every save
        self._flush_edit_clock()     # writing time banks with the words
        if self._commit_live_text() is not None:
            # History grew: extend the slider, staying parked at the end.
            self._revisions = self._store.list_revisions(self._current_doc.id)
            self._refresh_title_header()   # draft count and date advanced
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
            self._save_current_note()   # history mode skips _autosave
            self._flush_edit_clock()    # the last minutes are banked too
            self._save_window_state()   # layout survives the restart
            self._store.close()
        except Exception as exc:  # never trap the user in a broken window
            QMessageBox.warning(self, "WordVault", f"Error while closing: {exc}")
        event.accept()

    # ------------------------------------------------------------- status --

    def _set_editor_enabled(self, enabled: bool) -> None:
        self._editor.setEnabled(enabled)
        self._notes.setEnabled(enabled)
        self._timeline.setEnabled(enabled and bool(self._revisions))
        if not enabled:
            self._editor.set_text_quietly("")
            self._notes.blockSignals(True)
            self._notes.clear()
            self._notes.blockSignals(False)
            self._notes_timer.stop()
            self._title_label.setText("No document open")

    def _update_status(self) -> None:
        """Once the writer of three status-bar labels; now a quiet
        no-op kept so its many call sites need no changes.  Everything
        it used to say — title, draft count, viewing position, word
        count — lives in the title header and the Document Info panel
        (the redundancy was retired Aug 2026)."""
