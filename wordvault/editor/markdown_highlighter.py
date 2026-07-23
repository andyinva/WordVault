"""
markdown_highlighter.py — live Markdown styling in the editor.

The stored text stays plain — `# Heading` and `**bold**` remain ordinary
characters — but the editor DISPLAYS the conventions nicely: headings
larger and bold, **bold** shown bold, *italic* shown italic, quotes and
list markers tinted, and the marker characters themselves dimmed so they
recede without disappearing (they must stay visible and editable — the
text is the truth, the styling is a courtesy).

QSyntaxHighlighter restyles only changed lines, so this stays fast on
book-length documents.  Inline styling is per-line, matching how the
docx extractor writes Markdown (spans never cross lines).
"""

from __future__ import annotations

import re

from PyQt6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat

# Marker characters (#, *, >, -) are dimmed to this color.
_MARKER = QColor("#9aa5b1")
# Quote text: muted, italic.
_QUOTE = QColor("#5f6b7a")
# List bullets/numbers: a quiet blue.
_LIST = QColor("#3572b0")

# Heading size factors relative to the editor's base font size.
_HEADING_SCALE = {1: 1.5, 2: 1.3, 3: 1.15}   # deeper levels: 1.05
_DEFAULT_SCALE = 1.05

_RE_HEADING = re.compile(r"^(#{1,6})\s+")
_RE_LIST = re.compile(r"^(\s*)([-*] |\d{1,3}\. )")
_RE_BOLD_ITALIC = re.compile(r"\*\*\*(?!\s)(.+?)(?<!\s)\*\*\*")
_RE_BOLD = re.compile(r"\*\*(?!\s|\*)(.+?)(?<!\s)\*\*")
_RE_ITALIC = re.compile(r"(?<!\*)\*(?!\s|\*)([^*]+?)(?<!\s)\*(?!\*)")


class MarkdownHighlighter(QSyntaxHighlighter):
    """Styles Markdown conventions; never changes a single character."""

    def __init__(self, document, base_point_size):
        """
        base_point_size — a CALLABLE returning the editor's current font
        size, so heading sizes track the font-size setting live.
        """
        super().__init__(document)
        self._base = base_point_size
        #: When True (and pyspellchecker is installed), unknown words get
        #: a red spell-check underline on top of any Markdown styling.
        self.spelling_enabled = False

    # -- per-line styling ---------------------------------------------------

    def highlightBlock(self, text: str) -> None:  # noqa: N802 (Qt naming)
        base = self._base()

        # --- headings: whole line bold and enlarged, hashes dimmed ---
        m = _RE_HEADING.match(text)
        if m:
            level = len(m.group(1))
            fmt = QTextCharFormat()
            fmt.setFontWeight(700)
            fmt.setFontPointSize(base * _HEADING_SCALE.get(level, _DEFAULT_SCALE))
            self.setFormat(0, len(text), fmt)
            self.setFormat(0, level, self._marker_format())
            self._underline_misspellings(text)
            return  # headings carry no inline styling

        # --- blockquote: the whole line muted italic, ">" dimmed ---
        if text.startswith(">"):
            fmt = QTextCharFormat()
            fmt.setForeground(_QUOTE)
            fmt.setFontItalic(True)
            self.setFormat(0, len(text), fmt)
            self.setFormat(0, 1, self._marker_format())
            return

        # --- list marker: tint the "- " or "1. " ---
        m = _RE_LIST.match(text)
        if m:
            fmt = QTextCharFormat()
            fmt.setForeground(_LIST)
            fmt.setFontWeight(700)
            self.setFormat(len(m.group(1)), len(m.group(2)), fmt)

        # --- inline spans: italic, then bold, then bold-italic (last
        #     pass wins where they nest) ---
        for m in _RE_ITALIC.finditer(text):
            fmt = QTextCharFormat()
            fmt.setFontItalic(True)
            self._apply_span(m, fmt, marker_len=1)
        for m in _RE_BOLD.finditer(text):
            fmt = QTextCharFormat()
            fmt.setFontWeight(700)
            self._apply_span(m, fmt, marker_len=2)
        for m in _RE_BOLD_ITALIC.finditer(text):
            fmt = QTextCharFormat()
            fmt.setFontWeight(700)
            fmt.setFontItalic(True)
            self._apply_span(m, fmt, marker_len=3)

        self._underline_misspellings(text)

    # -- helpers ------------------------------------------------------------

    def _underline_misspellings(self, text: str) -> None:
        """Red squiggles under unknown words — ADDED to whatever format a
        span already carries (bold stays bold, just underlined too)."""
        if not self.spelling_enabled:
            return
        from wordvault.editor.spelling import get_spelling

        spelling = get_spelling()
        if not spelling.is_available():
            return
        for start, end in spelling.misspelled_spans(text):
            fmt = QTextCharFormat(self.format(start))  # keep existing style
            fmt.setUnderlineStyle(
                QTextCharFormat.UnderlineStyle.SpellCheckUnderline
            )
            fmt.setUnderlineColor(QColor("#cc3333"))
            self.setFormat(start, end - start, fmt)

    @staticmethod
    def _marker_format() -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(_MARKER)
        return fmt

    def _apply_span(self, m: re.Match, inner_fmt: QTextCharFormat,
                    marker_len: int) -> None:
        """Style the text between the markers; dim the markers themselves."""
        start, end = m.start(), m.end()
        self.setFormat(start + marker_len, end - start - 2 * marker_len, inner_fmt)
        self.setFormat(start, marker_len, self._marker_format())
        self.setFormat(end - marker_len, marker_len, self._marker_format())
