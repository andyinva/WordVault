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
    QColor,
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


def _qt_page_size(name: str) -> "QPageSize":
    """The QPageSize for a format's page-size name.  Qt has no built-in
    id for the 6x9-inch KDP book trim, so that one (and any future
    custom trim) is constructed by its point dimensions (72 pt/inch)."""
    from PyQt6.QtCore import QSizeF

    if name == "6x9":
        return QPageSize(QSizeF(6 * 72.0, 9 * 72.0),
                         QPageSize.Unit.Point, "6x9 (KDP trim)")
    return QPageSize(_PAGE_SIZES.get(name, QPageSize.PageSizeId.Letter))


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


def _expand(template: str, variables: dict) -> str:
    """Fill {title}/{author}/{date}/{page}/{pages} in a template."""
    def replace(m: re.Match) -> str:
        return str(variables.get(m.group(1), m.group(0)))
    return re.sub(r"\{(\w+)\}", replace, template)


def build_print_document(
    markdown_text: str,
    fmt: PrintFormat,
    *,
    title: str = "",
    author: str = "",
    date_str: str = "",
) -> QTextDocument:
    """The whole translation: plain Markdown in, styled document out.

    When the format defines a [byline], its expanded template is inserted
    as a generated block AFTER the first heading — or before everything
    when the document opens with plain text instead of a title."""
    document = QTextDocument()
    cursor = QTextCursor(document)
    first = True
    list_counter = 0          # sequential numbering per contiguous list
    paragraph_lines: list[str] = []

    byline_pending = bool(fmt.byline_text)
    byline_vars = {"title": title, "author": author, "date": date_str}

    def write_byline():
        nonlocal first, byline_pending
        if byline_pending:
            _write_block(cursor, fmt.style_for_byline(),
                         _expand(fmt.byline_text, byline_vars), first)
            first = False
            byline_pending = False

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
            level = len(heading.group(1))
            style = fmt.style_for_heading(level)
            _write_block(cursor, style, heading.group(2).strip(), first)
            # Tag the block with its heading level (an invisible block
            # property) so collect_headings() can find every heading —
            # and its true page — after layout.  This is what makes
            # the table of contents honest by construction.
            from PyQt6.QtGui import QTextFormat

            block_fmt = cursor.blockFormat()
            block_fmt.setProperty(QTextFormat.Property.UserProperty, level)
            cursor.setBlockFormat(block_fmt)
            first = False
            write_byline()               # the byline follows the title
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
            if byline_pending:
                write_byline()   # no opening heading: byline leads the text
            paragraph_lines.append(line.strip())  # plain prose accumulates

    flush_paragraph()
    write_byline()               # an all-blank document still gets its byline
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
        _qt_page_size(fmt.page_size),
        QPageLayout.Orientation.Portrait,
        margins,
        QPageLayout.Unit.Millimeter,
    )
    printer.setPageLayout(layout)
    if fmt.duplex:
        # The format asks for two-sided itself (long-edge flip, the
        # book-like turn).  Printers without duplex simply ignore it;
        # PDF output is unaffected.
        from PyQt6.QtPrintSupport import QPrinter

        printer.setDuplex(QPrinter.DuplexMode.DuplexLongSide)


def _draw_furniture(painter, spec, variables, x_left: float, x_right: float,
                    baseline_y: float, body_font: str) -> None:
    """Paint one header or footer line: three template slots at the text
    column's left edge, centre, and right edge.

    MUST be called with the painter scaled so 1 unit = 1 point, and the
    font is sized in PIXELS (= points in that space).  Pixel sizing
    bypasses the font engine's DPI mapping — a POINT-size font on a
    scaled printer painter gets enlarged twice (DPI mapping x transform),
    which printed the running title enormously ("book title in very
    large print across the top", Aug 2026)."""
    from PyQt6.QtGui import QFontMetrics

    font = QFont(spec.font or body_font)
    font.setPixelSize(max(1, round(spec.size_pt)))
    font.setBold(spec.bold)
    font.setItalic(spec.italic)
    painter.setFont(font)
    metrics = QFontMetrics(font)

    def draw(template: str, align: str) -> None:
        if not template:
            return
        text = _expand(template, variables)
        width = metrics.horizontalAdvance(text)
        if align == "left":
            x = x_left
        elif align == "right":
            x = x_right - width
        else:
            x = (x_left + x_right - width) / 2.0
        painter.drawText(int(x), int(baseline_y), text)

    draw(spec.left, "left")
    draw(spec.center, "center")
    draw(spec.right, "right")


def print_styled(printer, markdown_text: str, fmt: PrintFormat, *,
                 title: str = "", author: str = "") -> None:
    """
    Render and print with the chosen format.

    Plain margins with no page furniture: QTextDocument.print() handles
    pagination.  MIRRORED margins and/or headers/footers: pagination is
    done by hand — the document is laid out at the constant text width,
    each page painted at its own margins (spine side alternating in
    mirror mode), with header and footer templates ({page}, {pages},
    {title}, {author}, {date}) drawn into the margins.
    """
    from datetime import datetime

    date_str = datetime.now().strftime("%B %d, %Y")
    document = build_print_document(
        markdown_text, fmt, title=title, author=author, date_str=date_str
    )

    if not fmt.needs_manual_pagination():
        apply_page_setup(printer, fmt)
        document.print(printer)
        return

    print_book(printer, fmt, body_document=document,
               title=title, author=author)


def text_area_pt(fmt: PrintFormat) -> tuple[float, float]:
    """The text column's (width, height) in points — the page size the
    manual paginator lays documents out at.  One definition, used by
    print_book, collect_headings, and the front-matter builder, so
    they can never disagree about where pages break."""
    paper_pt = _qt_page_size(fmt.page_size).sizePoints()
    width = paper_pt.width() - fmt.margins.text_width_deduction() * _MM_TO_PT
    height = (paper_pt.height()
              - (fmt.margins.top + fmt.margins.bottom) * _MM_TO_PT)
    return width, height


def collect_headings(document, fmt: PrintFormat):
    """Lay the body out at its print size and report every heading as
    (level, text, page_number) — page numbers as the READER will see
    them (starting at 1 on the first chapter page).

    This is the fact-gathering half of the table of contents: the
    numbers come from the same layout the printer paints, so they are
    correct by construction — no refresh step, ever."""
    from PyQt6.QtCore import QSizeF
    from PyQt6.QtGui import QTextFormat

    width, height = text_area_pt(fmt)
    document.setPageSize(QSizeF(width, height))
    layout = document.documentLayout()

    headings = []
    block = document.firstBlock()
    while block.isValid():
        level = block.blockFormat().property(
            QTextFormat.Property.UserProperty)
        if level:
            y = layout.blockBoundingRect(block).y()
            headings.append((int(level), block.text(),
                             int(y // height) + 1))
        block = block.next()
    return headings


def collect_blocks(document, fmt: PrintFormat):
    """Lay the body out at print size and report EVERY text-bearing
    block as (text, page_number, heading_level) — heading_level 0 for
    ordinary paragraphs.  This is the raw material of the back-matter
    indexes: which words stand on which page, as the printer will
    paint them."""
    from PyQt6.QtCore import QSizeF
    from PyQt6.QtGui import QTextFormat

    width, height = text_area_pt(fmt)
    document.setPageSize(QSizeF(width, height))
    layout = document.documentLayout()

    blocks = []
    block = document.firstBlock()
    while block.isValid():
        text = block.text()
        if text.strip():
            level = block.blockFormat().property(
                QTextFormat.Property.UserProperty) or 0
            y = layout.blockBoundingRect(block).y()
            blocks.append((text, int(y // height) + 1, int(level)))
        block = block.next()
    return blocks


def print_book(printer, fmt: PrintFormat, *, body_document,
               front_document=None, back_document=None, title: str = "",
               author: str = "") -> None:
    """
    Hand-done pagination for a body document plus optional FRONT
    MATTER (title page, copyright, contents) and BACK MATTER (the
    subject and scripture indexes) — both built by the Formatter.

    The rules of the finished book:
      * front-matter pages carry NO header, footer, or page number —
        title and copyright pages are silent, by book convention;
      * body page numbers restart at 1 on the first chapter page;
      * back-matter pages CONTINUE the body's numbering (an index is
        a numbered part of the book), and {pages} counts body + back;
      * mirror margins follow the PHYSICAL page position, so the spine
        edge keeps alternating correctly straight through the book.

    Each page is a clipped slice of its document, painted under a
    scaled painter (document coordinates are points).  NOT
    drawContents(): its default paint context leaves the text color
    undefined, which printed every body invisibly (the "blank pages
    with page numbers" hunt).  Furniture shares the same scaled space
    with pixel-sized fonts — see _draw_furniture's warning.
    """
    from datetime import datetime

    from PyQt6.QtCore import QRectF, QSizeF
    from PyQt6.QtGui import QAbstractTextDocumentLayout, QPainter, QPalette

    date_str = datetime.now().strftime("%B %d, %Y")
    apply_page_setup(printer, fmt)     # size; zero margins when mirrored
    printer.setFullPage(True)

    paper_pt = _qt_page_size(fmt.page_size).sizePoints()  # QSize, points
    text_w_pt, text_h_pt = text_area_pt(fmt)

    # (document, carries furniture?, page-number offset) in book order.
    sections = []
    if front_document is not None:
        front_document.setPageSize(QSizeF(text_w_pt, text_h_pt))
        sections.append((front_document, False, 0))
    body_document.setPageSize(QSizeF(text_w_pt, text_h_pt))
    sections.append((body_document, True, 0))
    numbered_pages = body_document.pageCount()
    if back_document is not None:
        back_document.setPageSize(QSizeF(text_w_pt, text_h_pt))
        # Indexes continue the body's numbering where it left off.
        sections.append((back_document, True, numbered_pages))
        numbered_pages += back_document.pageCount()

    base_vars = {"title": title, "author": author, "date": date_str,
                 "pages": numbered_pages}
    body_font = fmt.body.font or "Georgia"

    painter = QPainter(printer)
    try:
        # Document coordinates are points; the printer wants device dots.
        dots_per_pt = printer.resolution() / 72.0
        top_pt = fmt.margins.top * _MM_TO_PT
        bottom_pt = fmt.margins.bottom * _MM_TO_PT
        physical = 0                   # position in the WHOLE book
        for document, furnished, number_offset in sections:
            for page in range(document.pageCount()):
                if physical:
                    printer.newPage()
                _t, _r, _b, left_mm = fmt.margins.for_page(physical)
                left_pt = left_mm * _MM_TO_PT

                painter.save()
                painter.scale(dots_per_pt, dots_per_pt)
                painter.translate(left_pt, top_pt - page * text_h_pt)
                context = QAbstractTextDocumentLayout.PaintContext()
                context.clip = QRectF(0, page * text_h_pt,
                                      text_w_pt, text_h_pt)
                context.palette.setColor(QPalette.ColorRole.Text,
                                         QColor(0, 0, 0))
                document.documentLayout().draw(painter, context)
                painter.restore()

                if furnished:
                    page_vars = dict(base_vars,
                                     page=number_offset + page + 1)
                    painter.save()
                    painter.scale(dots_per_pt, dots_per_pt)
                    x_left, x_right = left_pt, left_pt + text_w_pt
                    if fmt.header.wanted():
                        _draw_furniture(painter, fmt.header, page_vars,
                                        x_left, x_right, top_pt - 9.0,
                                        body_font)
                    if fmt.footer.wanted():
                        _draw_furniture(
                            painter, fmt.footer, page_vars,
                            x_left, x_right,
                            paper_pt.height() - bottom_pt + 9.0
                            + fmt.footer.size_pt,
                            body_font,
                        )
                    painter.restore()
                physical += 1
    finally:
        painter.end()
