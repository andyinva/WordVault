"""
builder.py — turns a BookProject into one print-ready PDF.

Stage F1 scope: the chapters, assembled in order and printed through
the existing .wvfmt renderer (which already handles mirror margins,
headers, footers, and page numbers).  Later stages add the front
matter (title page, copyright, table of contents) and back matter
(subject and scripture indexes) around this same core.

Assembly rules
--------------
* Each chapter must OPEN with a level-1 heading so the print format's
  heading1 style (typically page_break_before) starts it on a fresh
  page.  A chapter whose text already begins with '# ...' is trusted;
  otherwise its library title is inserted as the heading.
* Chapter page breaks are guaranteed: the book build forces
  page_break_before onto heading1 even when the chosen format doesn't
  set it (an essay format pressed into book service must still break
  between chapters).

The markdown-assembly half of this module is pure Python; only
build_book_pdf touches Qt, and imports it lazily so the module can be
tested anywhere.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from wordvault.formatter.book import BookProject, BookProjectError
from wordvault.printing.format_file import (
    StyleSpec,
    ensure_default_formats,
    list_formats,
    load_format,
)

_RE_H1 = re.compile(r"^#\s+\S")          # a level-1 heading with content


def chapter_markdown(title: str, text: str) -> str:
    """One chapter's markdown, guaranteed to open with a # heading."""
    stripped = text.lstrip("\n")
    first_line = stripped.split("\n", 1)[0]
    if _RE_H1.match(first_line):
        return stripped.rstrip() + "\n"
    # No opening title in the text: the library title becomes one.
    return f"# {title}\n\n" + stripped.rstrip() + "\n"


def assemble_markdown(chapters: list[tuple[str, str]]) -> str:
    """All chapters, in order, as one manuscript."""
    return "\n\n".join(chapter_markdown(t, x) for t, x in chapters)


def format_for_book(fmt):
    """The chosen format, adjusted for BOOK duty: heading1 always
    breaks to a fresh page, so chapters never run together even under
    a format written for single essays."""
    h1 = fmt.headings.get(1, StyleSpec())
    if h1.page_break_before:
        return fmt                        # already book-ready; untouched
    headings = dict(fmt.headings)
    headings[1] = dataclasses.replace(h1, page_break_before=True)
    return dataclasses.replace(fmt, headings=headings)


def find_format(name: str):
    """Look a .wvfmt up by its display name (the name the project file
    stores) among the user's personal copies."""
    ensure_default_formats()
    for fmt in list_formats():
        if fmt.name == name:
            # Reload from its path for a fresh, complete object.
            return load_format(fmt.path) if fmt.path else fmt
    raise BookProjectError(
        f"Print format '{name}' was not found — "
        "choose another in the Formatter window"
    )


def resolve_chapters(store, project: BookProject) -> list[tuple[str, str]]:
    """Fetch each chapter's CURRENT text from the library by uuid.

    The project stores pointers, not text, so this is where 'the
    library is the source of truth' becomes real: whatever was last
    saved in WordVault is what the book gets."""
    chapters: list[tuple[str, str]] = []
    missing: list[str] = []
    for ref in project.chapters:
        doc = store.get_document_by_uuid(ref.uuid)
        if doc is None:
            missing.append(ref.title or ref.uuid)
            continue
        latest = store.latest_revision(doc.id)
        text = store.get_text(latest.id) if latest else ""
        chapters.append((doc.title, text))
    if missing:
        raise BookProjectError(
            "These chapters are no longer in the library: "
            + ", ".join(missing)
        )
    return chapters


def build_book_pdf(store, project: BookProject, out_path: str | Path) -> None:
    """Assemble the book and write it as a PDF (Qt imported here only).

    Front matter first (title page, copyright — when their checkboxes
    are on), then the chapters.  The renderer's book path does the
    careful work: mirror margins by physical page, silent front-matter
    pages, body page numbers restarting at 1."""
    from datetime import datetime

    from PyQt6.QtPrintSupport import QPrinter

    from wordvault.formatter.frontmatter import build_front_matter
    from wordvault.printing.renderer import (
        apply_page_setup,
        build_print_document,
        collect_headings,
        print_book,
    )

    fmt = format_for_book(find_format(project.format_name))
    markdown = assemble_markdown(resolve_chapters(store, project))

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(out_path))

    date_str = datetime.now().strftime("%B %d, %Y")
    body = build_print_document(markdown, fmt, title=project.title,
                                author=project.author, date_str=date_str)
    # The table of contents reads its page numbers off the body's OWN
    # print layout — body numbering restarts at 1 after front matter,
    # so the TOC's length can never shift the numbers it reports.
    toc_entries = (collect_headings(body, fmt)
                   if project.sections.get("toc") else None)
    front = build_front_matter(fmt, project, toc_entries)

    if front is None and not fmt.needs_manual_pagination():
        # A plain format with no front matter: Qt can paginate alone.
        apply_page_setup(printer, fmt)
        body.print(printer)
        return
    print_book(printer, fmt, body_document=body, front_document=front,
               title=project.title, author=project.author)
