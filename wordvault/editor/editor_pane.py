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

import re

from PyQt6.QtCore import QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QTextCursor
from PyQt6.QtWidgets import QPlainTextEdit, QWidget

from wordvault.editor.markdown_highlighter import MarkdownHighlighter


class _TypewriterStrip(QWidget):
    """
    The thin strip on the editor's left edge in typewriter mode.  Shows a
    small handle at the anchor height; dragging it moves the writing line
    up or down.  All logic lives in EditorPane.
    """

    WIDTH = 14

    def __init__(self, editor: "EditorPane"):
        super().__init__(editor)
        self._editor = editor
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip("Drag to move the typewriter writing line")

    def paintEvent(self, event):  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor("#eef1f4"))
        y = self._editor.typewriter_anchor_y()
        # A small right-pointing handle at the anchor height.
        painter.setBrush(QColor("#3572b0"))
        painter.setPen(Qt.PenStyle.NoPen)
        from PyQt6.QtGui import QPolygon
        from PyQt6.QtCore import QPoint
        painter.drawPolygon(QPolygon([
            QPoint(3, y - 6), QPoint(self.WIDTH - 2, y), QPoint(3, y + 6),
        ]))

    def mousePressEvent(self, event):  # noqa: N802 (Qt naming)
        self._drag(event)

    def mouseMoveEvent(self, event):  # noqa: N802 (Qt naming)
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._drag(event)

    def _drag(self, event) -> None:
        height = max(1, self.height())
        self._editor.set_typewriter_fraction(event.position().y() / height)


class _LineNumberArea(QWidget):
    """The gutter widget; all logic lives in EditorPane (classic Qt
    pattern for QPlainTextEdit line numbers)."""

    def __init__(self, editor: "EditorPane"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):  # noqa: N802 (Qt naming)
        from PyQt6.QtCore import QSize
        return QSize(self._editor.line_number_width(), 0)

    def paintEvent(self, event):  # noqa: N802 (Qt naming)
        self._editor.paint_line_numbers(event)


class EditorPane(QPlainTextEdit):
    """Plain-text editor that signals when the author pauses typing."""

    #: Emitted once, IDLE_MS after the last keystroke.  MainWindow connects
    #: this to its auto-save slot.
    pause_detected = pyqtSignal()

    #: (typed, corrected) — the author accepted a spelling suggestion
    #: from the context menu; MainWindow logs it for the habits report.
    correction_made = pyqtSignal(str, str)

    #: (typed, corrected) — a previously-learned fix was applied
    #: automatically as the author typed the same mistake again.
    autocorrected = pyqtSignal(str, str)

    #: The typewriter anchor was dragged; MainWindow persists the value.
    typewriter_fraction_changed = pyqtSignal(float)

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

        # Live Markdown styling: the text stays plain; the display honors
        # the conventions (headings larger, **bold** bold, markers dimmed).
        self.markdown_highlighter = MarkdownHighlighter(
            self.document(), base_point_size=lambda: self.font().pointSize()
        )

        # Learned corrections for as-you-type repair of repeated errors:
        # dict typed(lower) -> corrected, or None = feature off.
        self._autocorrect_lookup = None

        # Optional line-number gutter (View menu toggle).
        self._line_numbers_on = False
        self._line_area = _LineNumberArea(self)
        self._line_area.hide()
        self.blockCountChanged.connect(lambda _n: self._update_gutter_width())
        self.updateRequest.connect(self._on_update_request)

        # Typewriter scrolling (View menu toggle): the writing line stays
        # anchored at a fixed height; text scrolls up past it.
        self._typewriter_on = False
        self._typewriter_fraction = 0.6   # anchor height, 0=top .. 1=bottom
        self._typewriter_strip = _TypewriterStrip(self)
        self._typewriter_strip.hide()

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
        # setPlainText resets the document, losing the typewriter margin;
        # re-apply (the undo stack is fresh here, so the guard is free).
        self._apply_typewriter_margin()

    def stop_idle_timer(self) -> None:
        """Cancel a pending pause signal (e.g. the document was just saved
        by some other trigger, so the timer's save would be redundant)."""
        self._idle_timer.stop()

    # -- settings knobs -----------------------------------------------------

    def idle_ms(self) -> int:
        """Current auto-save pause in milliseconds."""
        return self._idle_timer.interval()

    def set_idle_ms(self, ms: int) -> None:
        """Change how long a typing silence must last to trigger a save."""
        self._idle_timer.setInterval(max(500, ms))

    def set_font_point_size(self, points: int) -> None:
        font = self.font()
        font.setPointSize(points)
        self.setFont(font)
        # Heading sizes are relative to the base font — restyle.
        self.markdown_highlighter.rehighlight()

    # -- Markdown editing commands (Edit menu / shortcuts) ------------------
    #
    # All of these edit the PLAIN text — they type the Markdown characters
    # the author could type by hand.  Each command is one undo step.

    def toggle_inline_marks(self, marker: str) -> None:
        """Wrap the selection (or the word under the cursor) in `marker`
        — "**" for bold, "*" for italic — or unwrap it if already wrapped."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        text = cursor.selectedText().replace(" ", "\n")
        if not text.strip():
            return

        if (text.startswith(marker) and text.endswith(marker)
                and len(text) >= 2 * len(marker) + 1):
            new = text[len(marker):-len(marker)]        # unwrap
        else:
            # Markers must hug the words: keep surrounding spaces outside.
            lead = text[: len(text) - len(text.lstrip())]
            trail = text[len(text.rstrip()):]
            new = f"{lead}{marker}{text.strip()}{marker}{trail}"

        start = cursor.selectionStart()
        cursor.beginEditBlock()
        cursor.insertText(new)
        cursor.endEditBlock()
        # Keep the changed text selected so the command can be re-toggled.
        cursor.setPosition(start)
        cursor.setPosition(start + len(new), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)

    def set_heading_level(self, level: int) -> None:
        """Make the current line a heading of `level` (1-6); 0 removes
        any heading marks.  Repeating the same level also removes them."""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                            QTextCursor.MoveMode.KeepAnchor)
        line = cursor.selectedText()
        m = re.match(r"^(#{1,6})\s+", line)
        bare = line[m.end():] if m else line
        current = len(m.group(1)) if m else 0

        if level == 0 or level == current:
            new = bare                        # remove / toggle off
        else:
            new = "#" * level + " " + bare
        cursor.beginEditBlock()
        cursor.insertText(new)
        cursor.endEditBlock()

    def toggle_line_prefix(self, prefix: str) -> None:
        """Add `prefix` ("- " bullet, "> " quote) to every selected line,
        or remove it if every selected line already has it."""
        cursor = self.textCursor()
        doc = self.document()
        first = doc.findBlock(cursor.selectionStart()).blockNumber()
        last = doc.findBlock(cursor.selectionEnd()).blockNumber()
        lines = [doc.findBlockByNumber(n).text() for n in range(first, last + 1)]

        removing = all(l.startswith(prefix) for l in lines if l.strip())
        new_lines = []
        for line in lines:
            if not line.strip():
                new_lines.append(line)        # blank lines pass through
            elif removing:
                new_lines.append(line[len(prefix):])
            elif not line.startswith(prefix):
                new_lines.append(prefix + line)
            else:
                new_lines.append(line)

        # Replace the whole span in one undo step.
        span = QTextCursor(doc.findBlockByNumber(first))
        end_block = doc.findBlockByNumber(last)
        span.setPosition(end_block.position() + len(end_block.text()),
                         QTextCursor.MoveMode.KeepAnchor)
        span.beginEditBlock()
        span.insertText("\n".join(new_lines))
        span.endEditBlock()

    def set_autocorrect_lookup(self, lookup) -> None:
        """dict typed(lower) -> corrected, or None to disable."""
        self._autocorrect_lookup = lookup

    def _maybe_autocorrect(self) -> None:
        """A word was just completed (space/punct/Enter): if it matches a
        learned misspelling, repair it in place — bursty words repeat, and
        so do their errors."""
        if not self._autocorrect_lookup or self.isReadOnly():
            return
        cursor = self.textCursor()
        if cursor.hasSelection():
            return
        before = cursor.block().text()[:cursor.positionInBlock()]
        m = re.search(r"[A-Za-z][A-Za-z']*$", before)
        if not m:
            return
        word = m.group()
        corrected = self._autocorrect_lookup.get(word.lower())
        if not corrected or corrected.lower() == word.lower():
            return
        if not corrected[:1].isupper() and word[:1].isupper():
            corrected = corrected.capitalize()   # mirror sentence case
        fix = QTextCursor(self.document())
        fix.setPosition(cursor.position() - len(word))
        fix.setPosition(cursor.position(), QTextCursor.MoveMode.KeepAnchor)
        fix.insertText(corrected)
        self.autocorrected.emit(word, corrected)

    keyPressEvent_completers = " .,;:!?\"”)"

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """Smart list/quote continuation: Enter inside a "- ", "1. " or
        "> " line starts the next line with the same marker; Enter on an
        EMPTY marker line ends the list by clearing the marker.

        Also the auto-correction hook: finishing a word (space,
        punctuation, or Enter) first repairs it if it is a learned typo."""
        is_enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if is_enter or (event.text() and
                        event.text() in self.keyPressEvent_completers):
            self._maybe_autocorrect()

        if is_enter and not event.modifiers():
            cursor = self.textCursor()
            line = cursor.block().text()
            m = re.match(r"^(\s*)(- |\* |(\d{1,3})\. |> )", line)
            if m and not cursor.hasSelection():
                content = line[m.end():]
                if not content.strip() and cursor.atBlockEnd():
                    # Empty item: Enter means "done with this list".
                    cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                    cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                                        QTextCursor.MoveMode.KeepAnchor)
                    cursor.removeSelectedText()
                    return
                if cursor.atBlockEnd():
                    prefix = m.group(0)
                    if m.group(3):            # numbered: count upward
                        prefix = f"{m.group(1)}{int(m.group(3)) + 1}. "
                    super().keyPressEvent(event)
                    self.textCursor().insertText(prefix)
                    return
        super().keyPressEvent(event)

    # -- typewriter scrolling (View menu toggle) ----------------------------
    #
    # The writing line is held at a fixed height (the anchor); text
    # scrolls up past it instead of piling at the window's bottom edge.
    # To let the LAST line of the document sit at the anchor, the document
    # gets a large bottom margin while the mode is on ("scroll past end").
    # Changing that margin must not enter the undo history, so it is
    # applied inside an undo-disabled guard — which clears the session's
    # undo stack.  It therefore only happens at load, on toggle, and when
    # the anchor handle is dragged, never during ordinary typing.

    def set_typewriter_mode(self, on: bool) -> None:
        self._typewriter_on = on
        self._typewriter_strip.setVisible(on)
        self._update_gutter_width()
        self._apply_typewriter_margin()
        if on:
            self._typewriter_adjust()
        self.viewport().update()

    def typewriter_on(self) -> bool:
        return self._typewriter_on

    def set_typewriter_fraction(self, fraction: float) -> None:
        """Anchor height as a fraction of the window (0.15 top … 0.85
        bottom); called by the drag handle and by settings restore."""
        fraction = max(0.15, min(0.85, fraction))
        if abs(fraction - self._typewriter_fraction) < 0.005:
            return
        self._typewriter_fraction = fraction
        self._apply_typewriter_margin()
        self._typewriter_strip.update()
        self._typewriter_adjust()
        self.viewport().update()
        self.typewriter_fraction_changed.emit(fraction)

    def typewriter_anchor_y(self) -> int:
        """The anchor height in viewport pixels."""
        return int(self.viewport().height() * self._typewriter_fraction)

    def _apply_typewriter_margin(self) -> None:
        """Give the document a bottom margin equal to the space below the
        anchor, so the final line can be scrolled up to the anchor."""
        document = self.document()
        frame = document.rootFrame()
        fmt = frame.frameFormat()
        wanted = (
            max(4, self.viewport().height() - self.typewriter_anchor_y())
            if self._typewriter_on else 4
        )
        if int(fmt.bottomMargin()) == wanted:
            return
        # Root-frame format changes are undoable; keep them OUT of the
        # author's undo history (see the section comment for the cost).
        document.setUndoRedoEnabled(False)
        fmt.setBottomMargin(wanted)
        frame.setFrameFormat(fmt)
        document.setUndoRedoEnabled(True)

    def _typewriter_adjust(self) -> None:
        """Scroll so the cursor's line sits at the anchor height."""
        if not self._typewriter_on or self.isReadOnly():
            return
        spacing = max(1, self.fontMetrics().lineSpacing())
        delta_lines = round(
            (self.cursorRect().top() - self.typewriter_anchor_y()) / spacing
        )
        if delta_lines:
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() + delta_lines)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """Normal painting, plus a faint dashed line at the anchor height
        so the writing line's home is visible."""
        super().paintEvent(event)
        if self._typewriter_on:
            painter = QPainter(self.viewport())
            pen = QPen(QColor("#c9d2dc"))
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            y = self.typewriter_anchor_y()
            painter.drawLine(0, y, self.viewport().width(), y)

    # -- line numbers (View menu toggle) ------------------------------------

    def set_line_numbers_visible(self, on: bool) -> None:
        self._line_numbers_on = on
        self._line_area.setVisible(on)
        self._update_gutter_width()

    def line_numbers_visible(self) -> bool:
        return self._line_numbers_on

    def line_number_width(self) -> int:
        """Gutter width: enough digits for the last line, plus padding."""
        if not self._line_numbers_on:
            return 0
        digits = max(2, len(str(self.blockCount())))
        return 10 + self.fontMetrics().horizontalAdvance("9") * digits

    def _strip_width(self) -> int:
        return _TypewriterStrip.WIDTH if self._typewriter_on else 0

    def _update_gutter_width(self) -> None:
        self.setViewportMargins(
            self._strip_width() + self.line_number_width(), 0, 0, 0
        )

    def _on_update_request(self, rect, dy) -> None:
        """Keep the gutter scrolled/redrawn in step with the text."""
        if not self._line_numbers_on:
            return
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(),
                                   rect.height())

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().resizeEvent(event)
        rect = self.contentsRect()
        self._typewriter_strip.setGeometry(
            QRect(rect.left(), rect.top(), self._strip_width(), rect.height())
        )
        self._line_area.setGeometry(
            QRect(rect.left() + self._strip_width(), rect.top(),
                  self.line_number_width(), rect.height())
        )

    def paint_line_numbers(self, event) -> None:
        """Draw the visible block numbers in the gutter (called by the
        gutter widget's paintEvent)."""
        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), QColor("#f2f3f5"))
        painter.setPen(QColor("#8a929c"))
        painter.setFont(self.font())

        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block)
                    .translated(self.contentOffset()).top())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible():
                bottom = top + round(self.blockBoundingRect(block).height())
                if bottom >= event.rect().top():
                    painter.drawText(
                        0, top, self._line_area.width() - 6,
                        self.fontMetrics().height(),
                        Qt.AlignmentFlag.AlignRight,
                        str(block.blockNumber() + 1),
                    )
                top = bottom
            block = block.next()

    # -- spelling context menu ----------------------------------------------

    def contextMenuEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """Right-click: the standard menu, topped with spelling
        suggestions when the click landed on a misspelled word."""
        from wordvault.editor.spelling import get_spelling

        menu = self.createStandardContextMenu()
        spelling = get_spelling()
        if spelling.is_available() and self.markdown_highlighter.spelling_enabled:
            cursor = self.cursorForPosition(event.pos())
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            word = cursor.selectedText()
            if word and spelling.is_misspelled(word):
                first = menu.actions()[0] if menu.actions() else None
                for suggestion in spelling.suggestions(word):
                    action = menu.addAction(suggestion)
                    menu.insertAction(first, action)
                    action.triggered.connect(
                        lambda _c, s=suggestion, cur=cursor, w=word: (
                            cur.insertText(s),
                            self.correction_made.emit(w, s),
                        )
                    )
                add_action = menu.addAction(f"Add “{word}” to dictionary")
                menu.insertAction(first, add_action)
                add_action.triggered.connect(
                    lambda _c, w=word: (
                        spelling.add_to_dictionary(w),
                        self.markdown_highlighter.rehighlight(),
                    )
                )
                menu.insertSeparator(first)
        menu.exec(event.globalPos())

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
        """Every genuine edit restarts the idle countdown — and, in
        typewriter mode, re-anchors the writing line after the layout
        settles (hence the zero-delay timer)."""
        if not self._suppress_signals:
            self._idle_timer.start()
            if self._typewriter_on:
                QTimer.singleShot(0, self._typewriter_adjust)

    @staticmethod
    def _on_windows() -> bool:
        import sys
        return sys.platform.startswith("win")
