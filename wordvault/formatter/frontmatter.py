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

  * CONTENTS (fresh page after them): every level-1 and level-2
    heading of the assembled body with its TRUE page number, read from
    the same layout the printer paints (collect_headings in the
    renderer).  Chapter lines full-size, section lines indented and
    smaller — like the Word TOC these books used to need F9 for.
    Page numbers sit against the right edge via a right-aligned tab.

None of these pages carries a header, footer, or page number —
print_book() paints front matter silently, as real books do.

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

from wordvault.formatter.book import BookProject, BookProjectError
from wordvault.printing.format_file import PrintFormat

#: What the QR caption says — the reader-facing explanation Andrew
#: asked for.  Short enough for one small line under the code.
QR_CAPTION = ("This code holds this book's WordVault typesetting "
              "recipe: title, author, ISBN, and the exact page format "
              "used to print it.")


def _qr_payload(fmt: PrintFormat, project: BookProject) -> str:
    """The QR's contents: a small JSON record of what this book IS and
    how it was typeset — including the full .wvfmt text, so a scanned
    code can rebuild the layout.  If the format file is too large for
    a QR (rare; they hold ~2.9 KB), the recipe falls back to metadata
    plus the format's name."""
    import json

    wvfmt_text = ""
    if fmt.path is not None:
        try:
            wvfmt_text = fmt.path.read_text(encoding="utf-8")
        except OSError:
            pass
    cp = project.copyright
    payload = {
        "wordvault": 1,
        "kind": "book",
        "title": project.title,
        "author": project.author,
        "isbn": cp.isbn,
        "year": cp.year or str(date.today().year),
        "format": fmt.name,
        "wvfmt": wvfmt_text,
    }
    return json.dumps(payload, ensure_ascii=False)


def _qr_image(payload: str):
    """The QR code as a crisp QImage (8 device pixels per module, so
    printing at ~1.1 inch stays sharp).  Needs the pure-Python
    'qrcode' package; the error says exactly how to get it."""
    try:
        import qrcode
    except ImportError as exc:
        raise BookProjectError(
            "The copyright-page QR code needs the 'qrcode' package.\n"
            "Install it with:  pip install qrcode\n"
            "(or untick 'Include QR code' in Copyright Details)"
        ) from exc

    from PyQt6.QtGui import QImage

    qr = qrcode.QRCode(border=2,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(payload)
    try:
        qr.make(fit=True)
    except (ValueError, qrcode.exceptions.DataOverflowError):
        # Payload too big (an unusually long .wvfmt): drop the format
        # text, keep the metadata — still a scannable provenance mark.
        import json

        slim = json.loads(payload)
        slim["wvfmt"] = ""
        qr = qrcode.QRCode(border=2,
                           error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(json.dumps(slim, ensure_ascii=False))
        qr.make(fit=True)

    matrix = qr.get_matrix()               # list of rows of booleans
    scale = 8
    size = len(matrix) * scale
    image = QImage(size, size, QImage.Format.Format_RGB32)
    image.fill(0xFFFFFF)
    for row_index, row in enumerate(matrix):
        for col_index, dark in enumerate(row):
            if dark:
                for dy in range(scale):
                    for dx in range(scale):
                        image.setPixel(col_index * scale + dx,
                                       row_index * scale + dy, 0x000000)
    return image


def _write(cursor: QTextCursor, text: str, *, family: str,
           size_pt: float, first: bool, align=Qt.AlignmentFlag.AlignHCenter,
           top_margin_pt: float = 0.0, left_margin_pt: float = 0.0,
           italic: bool = False, bold: bool = False,
           page_break: bool = False) -> None:
    """Append one styled block (front and back matter are simple
    enough that every element is a single block with one uniform
    format — the indexes module borrows this writer too)."""
    block = QTextBlockFormat()
    block.setAlignment(align)
    block.setTopMargin(top_margin_pt)
    block.setLeftMargin(left_margin_pt)
    if page_break and not first:
        block.setPageBreakPolicy(
            QTextBlockFormat.PageBreakFlag.PageBreak_AlwaysBefore)
    char = QTextCharFormat()
    font = QFont(family)
    font.setPointSizeF(size_pt)
    font.setItalic(italic)
    font.setBold(bold)
    char.setFont(font)
    if first:
        cursor.setBlockFormat(block)
        cursor.setBlockCharFormat(char)
    else:
        cursor.insertBlock(block, char)
    cursor.insertText(text, char)


def _toc_line(cursor: QTextCursor, level: int, text: str, page: int, *,
              family: str, right_edge_pt: float, first: bool) -> None:
    """One Contents entry: title, then the page number pushed to the
    right edge by a right-aligned tab stop.  Level 2 is indented and
    a shade smaller; deeper levels never reach here (the caller keeps
    the Contents to levels 1-2, as book TOCs do)."""
    from PyQt6.QtGui import QTextOption

    block = QTextBlockFormat()
    block.setAlignment(Qt.AlignmentFlag.AlignLeft)
    block.setLeftMargin(16.0 if level == 2 else 0.0)
    block.setTopMargin(2.0 if level == 2 else 7.0)
    tab = QTextOption.Tab(right_edge_pt - block.leftMargin(),
                          QTextOption.TabType.RightTab)
    block.setTabPositions([tab])
    char = QTextCharFormat()
    font = QFont(family)
    font.setPointSizeF(10.0 if level == 2 else 11.0)
    char.setFont(font)
    if first:
        cursor.setBlockFormat(block)
        cursor.setBlockCharFormat(char)
    else:
        cursor.insertBlock(block, char)
    cursor.insertText(f"{text}\t{page}", char)


def build_front_matter(fmt: PrintFormat, project: BookProject,
                       toc_entries=None) -> QTextDocument | None:
    """The title page, copyright page, and/or table of contents —
    or None when nothing is switched on.

    toc_entries: (level, text, page) triples from collect_headings(),
    required only when the project's toc section is enabled."""
    want_title = bool(project.sections.get("title_page"))
    want_copyright = bool(project.sections.get("copyright"))
    want_toc = bool(project.sections.get("toc")) and toc_entries is not None
    if not (want_title or want_copyright or want_toc):
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

        if cp.include_qr:
            # The provenance mark: the book carries its own recipe.
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QTextImageFormat

            image = _qr_image(_qr_payload(fmt, project))
            document.addResource(QTextDocument.ResourceType.ImageResource,
                                 QUrl("wordvault://copyright-qr"), image)
            block = QTextBlockFormat()
            block.setAlignment(Qt.AlignmentFlag.AlignLeft)
            block.setTopMargin(14.0)
            cursor.insertBlock(block, QTextCharFormat())
            image_fmt = QTextImageFormat()
            image_fmt.setName("wordvault://copyright-qr")
            image_fmt.setWidth(80.0)       # ~1.1 inch square on paper
            image_fmt.setHeight(80.0)
            cursor.insertImage(image_fmt)
            _write(cursor, QR_CAPTION, family=family, size_pt=8.0,
                   first=False, align=Qt.AlignmentFlag.AlignLeft,
                   top_margin_pt=4.0, italic=True)

    if want_toc:
        # The renderer's text_area_pt is the single truth about the
        # text column, so the right-tab stop lands exactly at the
        # column's right edge — where the page numbers line up.
        from wordvault.printing.renderer import text_area_pt

        text_w_pt, _text_h_pt = text_area_pt(fmt)
        _write(cursor, "Contents", family=family, size_pt=16.0,
               first=first, top_margin_pt=36.0, page_break=True)
        first = False
        for level, text, page in toc_entries:
            if level > 2:
                continue        # book TOCs stop at sections (\o "1-2")
            _toc_line(cursor, level, text, page, family=family,
                      right_edge_pt=text_w_pt - 2.0, first=False)

    return document
