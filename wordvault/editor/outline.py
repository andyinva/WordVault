"""
outline.py — the document map and section logic (stage 7).

The outline is DERIVED from the plain text, never stored: Markdown-style
heading lines ("# Title", "## Subtitle", up to ######) become a tree.
This keeps faith with the design rule that documents are plain text —
structure is a reading of the text, not markup baked into it.

Two pure functions (tested headless) plus one small widget:

  parse_outline(text)          -> [(level, title, line_no), ...]
  section_bounds(text, line)   -> (first_line, last_line) of the section
                                  containing `line` — used by focus mode
  OutlinePane                  -> the dockable tree; emits
                                  heading_activated(line_no) on click
"""

from __future__ import annotations

import re

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

#: "# Heading" … "###### Heading" at the start of a line.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


def parse_outline(text: str) -> list[tuple[int, str, int]]:
    """All headings as (level, title, line_no); line numbers are 0-based."""
    outline = []
    for line_no, line in enumerate(text.split("\n")):
        m = _HEADING_RE.match(line)
        if m:
            outline.append((len(m.group(1)), m.group(2).strip(), line_no))
    return outline


def section_bounds(text: str, line: int) -> tuple[int, int]:
    """
    The section containing `line`, for focus/hoist mode: from its heading
    down to the line before the next heading of the same or higher level.
    Text before any heading counts as one leading section; a document
    with no headings is a single section (the whole text).
    """
    lines = text.split("\n")
    outline = parse_outline(text)
    last_line = len(lines) - 1

    # The heading at or above `line` (None = the leading, pre-heading part).
    current = None
    for entry in outline:
        if entry[2] <= line:
            current = entry
        else:
            break

    if current is None:
        # Leading section: everything before the first heading (or all text).
        end = outline[0][2] - 1 if outline else last_line
        return 0, max(end, 0)

    level, _title, start = current
    for lvl, _t, ln in outline:
        if ln > start and lvl <= level:
            return start, ln - 1
    return start, last_line


class OutlinePane(QTreeWidget):
    """The dockable document map.  Click a heading to jump to it."""

    #: 0-based line number of the activated heading.
    heading_activated = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.itemActivated.connect(self._on_activated)
        self.itemClicked.connect(self._on_activated)

    def set_outline(self, outline: list[tuple[int, str, int]]) -> None:
        """Rebuild the tree.  Headings nest by level; a level jump deeper
        than one step still nests sensibly (child of the nearest shallower
        heading)."""
        self.clear()
        # Stack of (level, item) giving the current ancestry.
        stack: list[tuple[int, QTreeWidgetItem]] = []
        for level, title, line_no in outline:
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.ItemDataRole.UserRole, line_no)
            while stack and stack[-1][0] >= level:
                stack.pop()
            if stack:
                stack[-1][1].addChild(item)
            else:
                self.addTopLevelItem(item)
            stack.append((level, item))
        self.expandAll()

    def highlight_line(self, line: int) -> None:
        """Mark the heading whose section contains `line` (cursor moved)."""
        best = None
        it = self._iterate_items()
        for item in it:
            item_line = item.data(0, Qt.ItemDataRole.UserRole)
            if item_line <= line and (
                best is None or item_line > best.data(0, Qt.ItemDataRole.UserRole)
            ):
                best = item
        if best is not None:
            # Select quietly — no signal loop back into the editor.
            self.blockSignals(True)
            self.setCurrentItem(best)
            self.blockSignals(False)

    # -- internals ----------------------------------------------------------

    def _iterate_items(self):
        """Every item in the tree, depth-first."""
        def walk(item):
            yield item
            for i in range(item.childCount()):
                yield from walk(item.child(i))
        for i in range(self.topLevelItemCount()):
            yield from walk(self.topLevelItem(i))

    def _on_activated(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        line = item.data(0, Qt.ItemDataRole.UserRole)
        if line is not None:
            self.heading_activated.emit(line)
