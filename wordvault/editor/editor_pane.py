"""
editor_pane.py — the text-editing widget.

A thin subclass of QPlainTextEdit whose one added job is detecting the
author's typing pauses.  DESIGN.md section 5 ("capture policy"): a revision
is committed when the author pauses for ~3 seconds — the pane itself only
*detects* the pause and emits a signal; deciding what to do belongs to
MainWindow, which owns the DocumentStore.

Why QPlainTextEdit: it already handles plain-text editing, selection,
undo/redo within the session, and very large documents.  WordVault's
revision system covers everything beyond the session.
"""

from __future__ import annotations

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QPlainTextEdit


class EditorPane(QPlainTextEdit):
    """Plain-text editor that signals when the author pauses typing."""

    #: Emitted once, IDLE_MS after the last keystroke.  MainWindow connects
    #: this to its auto-save slot.
    pause_detected = pyqtSignal()

    #: How long a silence counts as "a pause" (DESIGN.md: ~3 seconds).
    IDLE_MS = 3000

    def __init__(self, parent=None):
        super().__init__(parent)

        # A comfortable writing font; monospace keeps columns predictable
        # for now (a preferences dialog can override this later).
        font = QFont("Consolas" if self._on_windows() else "DejaVu Sans Mono")
        font.setPointSize(12)
        self.setFont(font)

        # Single-shot idle timer: every text change restarts it, so it only
        # fires after IDLE_MS of true silence.
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(self.IDLE_MS)
        self._idle_timer.timeout.connect(self.pause_detected)

        # While set_text_quietly() runs, programmatic changes must NOT look
        # like typing (loading a document is not an edit).
        self._suppress_signals = False

        self.textChanged.connect(self._on_text_changed)

    # -- public API ---------------------------------------------------------

    def set_text_quietly(self, text: str) -> None:
        """Replace the pane's content WITHOUT triggering pause detection.
        Used when loading a document or a historical state into the view."""
        self._suppress_signals = True
        try:
            self.setPlainText(text)
        finally:
            self._suppress_signals = False
        self._idle_timer.stop()

    def stop_idle_timer(self) -> None:
        """Cancel a pending pause signal (e.g. the document was just saved
        by some other trigger, so the timer's save would be redundant)."""
        self._idle_timer.stop()

    # -- focus (hoist) mode: show one section, hide the rest (stage 7) ------

    def set_focus_lines(self, first_line: int, last_line: int) -> None:
        """MaxThink-style hoist: only blocks first_line..last_line stay
        visible.  Purely a view — the document's text is untouched, and
        edits inside the visible section work normally."""
        doc = self.document()
        block = doc.firstBlock()
        while block.isValid():
            n = block.blockNumber()
            block.setVisible(first_line <= n <= last_line)
            block = block.next()
        self._focused = True
        self._relayout()
        # Park the cursor inside the visible section, not in hidden text.
        cursor = self.textCursor()
        if not (first_line <= cursor.blockNumber() <= last_line):
            cursor.setPosition(doc.findBlockByNumber(first_line).position())
            self.setTextCursor(cursor)

    def clear_focus_lines(self) -> None:
        """Leave hoist mode: every block visible again."""
        doc = self.document()
        block = doc.firstBlock()
        while block.isValid():
            block.setVisible(True)
            block = block.next()
        self._focused = False
        self._relayout()

    def is_focused(self) -> bool:
        return getattr(self, "_focused", False)

    def _relayout(self) -> None:
        """Force the layout to honor changed block visibility."""
        doc = self.document()
        doc.markContentsDirty(0, doc.characterCount())
        self.viewport().update()
        self.ensureCursorVisible()

    # -- internals ----------------------------------------------------------

    def _on_text_changed(self) -> None:
        """Every genuine edit restarts the idle countdown."""
        if not self._suppress_signals:
            self._idle_timer.start()

    @staticmethod
    def _on_windows() -> bool:
        import sys
        return sys.platform.startswith("win")
