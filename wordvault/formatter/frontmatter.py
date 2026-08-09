"""
frontmatter.py — the book's opening pages: title page and copyright
page, built as one QTextDocument for the renderer's print_book().

Layout follows book convention rather than the .wvfmt styles:
  * TITLE PAGE (a recto, page 1): the title large and centered about
    a third of the way down, "By <author>" beneath it.  Measurements
    echo the Word manuscripts this replaces (24 pt Georgia title).
  * COPYRIGHT PAGE (the verso, page 2): a small, quiet block in the
    lower half — copyright line, edition, ISBN, and the Scripture-
    translation notice (KJV needs none, being public domain; most
    modern translations require a specific credit line).

Neither page carries a header, footer, or page number — print_book()
paints front matter silently, as real books do.

Empty fields simply do not print: a book without an ISBN gets no
"ISBN" line, not a blank one.
"""

from __future__ import annotations

from datetime import date

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QFont,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)

from wordvault.formatter.book import BookProject
from wordvault.printing.format_file import PrintFormat


def _write(cursor: QTextCursor, text: str, *, family: str,
           size_pt: float, first: bool, align=Qt.AlignmentFlag.AlignHCenter,
           top_margin_pt: float = 0.0, italic: bool = False,
           page_break: bool = False) -> None:
    """Append one styled block (the front matter is simple enough that
    every element is a single block with one uniform format)."""
    block = QTextBlockFormat()
    block.setAlignment(align)
    block.setTopMargin(top_margin_pt)
    if page_break and not first:
        block.setPageBreakPolicy(
            QTextBlockFormat.PageBreakFlag.PageBreak_AlwaysBefore)
    char = QTextCharFormat()
    font = QFont(family)
    font.setPointSizeF(size_pt)
    font.setItalic(italic)
    char.setFont(font)
    if first:
        cursor.setBlockFormat(block)
        cursor.setBlockCharFormat(char)
    else:
        cursor.insertBlock(block, char)
    cursor.insertText(text, char)


def build_front_matter(fmt: PrintFormat,
                       project: BookProject) -> QTextDocument | None:
    """The title and/or copyright pages, or None when both are off."""
    want_title = bool(project.sections.get("title_page"))
    want_copyright = bool(project.sections.get("copyright"))
    if not (want_title or want_copyright):
        return None

    family = fmt.body.font or "Georgia"
    document = QTextDocument()
    cursor = QTextCursor(document)
    first = True

    if want_title:
        _write(cursor, project.title.strip() or "Untitled",
               family=family, size_pt=24.0, first=first,
               top_margin_pt=170.0)      # ~a third of the page down
        first = False
        if project.author.strip():
            _write(cursor, f"By {project.author.strip()}",
                   family=family, size_pt=13.0, first=False,
                   top_margin_pt=28.0)

    if want_copyright:
        cp = project.copyright
        year = cp.year.strip() or str(date.today().year)
        owner = project.author.strip()

        lines = []
        notice = f"© {year}" + (f" {owner}" if owner else "")
        if cp.rights.strip():
            notice += f". {cp.rights.strip()}"
        lines.append(notice)
        if cp.edition.strip():
            lines.append(cp.edition.strip())
        if cp.isbn.strip():
            lines.append(f"ISBN {cp.isbn.strip()}")
        if cp.scripture_notice.strip():
            lines.append(cp.scripture_notice.strip())

        for index, line in enumerate(lines):
            _write(cursor, line, family=family, size_pt=9.5,
                   first=first, align=Qt.AlignmentFlag.AlignLeft,
                   # First line: fresh page (the verso), pushed to the
                   # lower half where copyright blocks live.
                   top_margin_pt=330.0 if index == 0 else 6.0,
                   page_break=(index == 0))
            first = False

    return document
