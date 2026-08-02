"""
renderer.py — Markdown text -> a fully styled QTextDocument for printing.

The only place in WordVault where formatting is APPLIED — and its output
goes straight to the printer, never to the screen (the non-WYSIWYG
principle).  The renderer walks the plain Markdown conventions the
editor already uses:

    # .. ######   headings 1-6
    > text        block quote
    - text        bullet list item
    1. text       numbered list item (renumbered sequentially per list)
    **b** *i*     bold / italic / ***both*** inline runs
    blank line    paragraph separator (consecutive plain lines join
                  into one paragraph, as in hand-written Markdown)

and styles each element from the chosen PrintFormat.  Millimetre values
from the format file become points (1 mm = 2.835 pt), the unit
QTextDocument uses for print layout.
"""

from __future__ import annotations

import re

from PyQt6.QtCore import QMarginsF, Qt
from PyQt6.QtGui import (
    QFont,
    QPageLayout,
    QPageSize,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)

from wordvault.printing.format_file import PrintFormat, StyleSpec

_MM_TO_PT = 72.0 / 25.4

_RE_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_RE_BULLET = re.compile(r"^[-*]\s+(.*)$")
_RE_NUMBERED = re.compile(r"^\d{1,3}\.\s+(.*)$")
_RE_QUOTE = re.compile(r"^>\s?(.*)$")
_RE_INLINE = re.compile(
    r"\*\*\*(.+?)\*\*\*|\*\*(.+?)\*\*|(?<!\*)\*([^*]+?)\*(?!\*)"
)

_ALIGN = {
    "left": Qt.AlignmentFlag.AlignLeft,
    "right": Qt.AlignmentFlag.AlignRight,
    "center": Qt.AlignmentFlag.AlignHCenter,
    "justify": Qt.AlignmentFlag.AlignJustify,
}

_PAGE_SIZES = {
    "Letter": QPageSize.PageSizeId.Letter,
    "Legal": QPageSize.PageSizeId.Legal,
    "A4": QPageSize.PageSizeId.A4,
    "A5": QPageSize.PageSizeId.A5,
    "B5": QPageSize.PageSizeId.B5,
}


def _inline_segments(text: str):
    """Split one line into (text, bold, italic) runs per the ** and *
    conventions; unmatched markers stay literal."""
    segments = []
    pos = 0
    for m in _RE_INLINE.finditer(text):
        if m.start() > pos:
            segments.append((text[pos:m.start()], False, False))
        if m.group(1) is not None:
            segments.append((m.group(1), True, True))
        elif m.group(2) is not None:
            segments.append((m.group(2), True, False))
        else:
            segments.append((m.group(3), False, True))
        pos = m.end()
    if pos < len(text):
        segments.append((text[pos:], False, False))
    return segments


def _block_format(style: StyleSpec, *, suppress_break: bool = False) -> QTextBlockFormat:
    fmt = QTextBlockFormat()
    fmt.setAlignment(_ALIGN.get(style.align or "left", _ALIGN["left"]))
    fmt.setTextIndent((style.first_line_indent_mm or 0.0) * _MM_TO_PT)
    fmt.setLeftMargin((style.indent_mm or 0.0) * _MM_TO_PT)
    fmt.setTopMargin(style.space_before_pt or 0.0)
    fmt.setBottomMargin(style.space_after_pt or 0.0)
    if style.line_spacing:
        fmt.setLineHeight(style.line_spacing * 100.0,
                          QTextBlockFormat.LineHeightTypes
                          .ProportionalHeight.value)
    if style.page_break_before and not suppress_break:
        fmt.setPageBreakPolicy(
            QTextBlockFormat.PageBreakFlag.PageBreak_AlwaysBefore
        )
    return fmt


def _char_format(style: StyleSpec, bold=False, italic=False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    font = QFont(style.font or "Georgia")
    font.setPointSizeF(style.size_pt or 11.0)
    font.setBold(bold or bool(style.bold))
    font.setItalic(italic or bool(style.italic))
    fmt.setFont(font)
    return fmt


def _write_block(cursor: QTextCursor, style: StyleSpec, text: str,
                 first_block: bool, prefix: str = "") -> None:
    """Append one styled block; inline **/* runs styled within it."""
    # The document's automatic first block is reused; afterwards each
    # element starts a new block.  A page-break-before on the very first
    # block would print a blank leading page — suppressed.
    # The block-level char format is set too (not just the runs): it
    # governs the height of empty lines and the block's baseline font.
    block_fmt = _block_format(style, suppress_break=first_block)
    base_char = _char_format(style)
    if first_block:
        cursor.setBlockFormat(block_fmt)
        cursor.setBlockCharFormat(base_char)
    else:
        cursor.insertBlock(block_fmt, base_char)
    if prefix:
        cursor.insertText(prefix, _char_format(style))
    for segment, bold, italic in _inline_segments(text):
        cursor.insertText(segment, _char_format(style, bold, italic))


def build_print_document(markdown_text: str, fmt: PrintFormat) -> QTextDocument:
    """The whole translation: plain Markdown in, styled document out."""
    document = QTextDocument()
    cursor = QTextCursor(document)
    first = True
    list_counter = 0          # sequential numbering per contiguous list
    paragraph_lines: list[str] = []

    def flush_paragraph():
        nonlocal first
        if paragraph_lines:
            _write_block(cursor, fmt.body, " ".join(paragraph_lines), first)
            paragraph_lines.clear()
            first = False

    for line in markdown_text.split("\n"):
        heading = _RE_HEADING.match(line)
        bullet = _RE_BULLET.match(line)
        numbered = _RE_NUMBERED.match(line)
        quote = _RE_QUOTE.match(line)

        if not (numbered or bullet):
            list_counter = 0                      # a list just ended

        if heading:
            flush_paragraph()
            style = fmt.style_for_heading(len(heading.group(1)))
            _write_block(cursor, style, heading.group(2).strip(), first)
            first = False
        elif quote:
            flush_paragraph()
            _write_block(cursor, fmt.style_for_quote(), quote.group(1), first)
            first = False
        elif bullet:
            flush_paragraph()
            _write_block(cursor, fmt.style_for_list(), bullet.group(1),
                         first, prefix="•  ")
            first = False
        elif numbered:
            flush_paragraph()
            list_counter += 1
            _write_block(cursor, fmt.style_for_list(), numbered.group(1),
                         first, prefix=f"{list_counter}.  ")
            first = False
        elif not line.strip():
            flush_paragraph()                     # blank line ends a paragraph
        else:
            paragraph_lines.append(line.strip())  # plain prose accumulates

    flush_paragraph()
    return document


def apply_page_setup(printer, fmt: PrintFormat) -> None:
    """Impose the format's page size and margins on the printer (the
    format file outranks the Page Setup dialog when a format is chosen).
    For mirrored formats this sets size only — print_styled() draws each
    page with its own margins."""
    if fmt.margins.mirrored:
        margins = QMarginsF(0, 0, 0, 0)
    else:
        top, right, bottom, left = fmt.margins.for_page(0)
        margins = QMarginsF(left, top, right, bottom)
    layout = QPageLayout(
        QPageSize(_PAGE_SIZES.get(fmt.page_size, QPageSize.PageSizeId.Letter)),
        QPageLayout.Orientation.Portrait,
        margins,
        QPageLayout.Unit.Millimeter,
    )
    printer.setPageLayout(layout)


def print_styled(printer, markdown_text: str, fmt: PrintFormat) -> None:
    """
    Render and print with the chosen format.

    Normal margins: QTextDocument.print() handles pagination.

    MIRRORED margins (Word's book mode): Qt applies one margin set to
    every page, so pagination is done by hand — the document is laid out
    at the constant text width (page minus inside+gutter+outside), then
    each page is painted at its own left offset: spine margin on the
    left of odd (right-hand) pages, on the right of even pages.
    """
    document = build_print_document(markdown_text, fmt)

    if not fmt.margins.mirrored:
        apply_page_setup(printer, fmt)
        document.print(printer)
        return

    from PyQt6.QtCore import QRectF, QSizeF
    from PyQt6.QtGui import QPainter

    apply_page_setup(printer, fmt)     # size; zero driver margins
    printer.setFullPage(True)

    page_id = _PAGE_SIZES.get(fmt.page_size, QPageSize.PageSizeId.Letter)
    paper_pt = QPageSize(page_id).sizePoints()   # QSize, in points
    text_w_pt = paper_pt.width() - fmt.margins.text_width_deduction() * _MM_TO_PT
    text_h_pt = (paper_pt.height()
                 - (fmt.margins.top + fmt.margins.bottom) * _MM_TO_PT)
    document.setPageSize(QSizeF(text_w_pt, text_h_pt))

    painter = QPainter(printer)
    try:
        # Document coordinates are points; the printer wants device dots.
        dots_per_pt = printer.resolution() / 72.0
        top_pt = fmt.margins.top * _MM_TO_PT
        for page in range(document.pageCount()):
            if page:
                printer.newPage()
            _t, _r, _b, left_mm = fmt.margins.for_page(page)
            painter.save()
            painter.scale(dots_per_pt, dots_per_pt)
            # Place this page's slice of the document at its margins.
            painter.translate(left_mm * _MM_TO_PT,
                              top_pt - page * text_h_pt)
            document.drawContents(
                painter, QRectF(0, page * text_h_pt, text_w_pt, text_h_pt)
            )
            painter.restore()
    finally:
        painter.end()
