"""
export_docx.py — Markdown conventions -> a real Word document.

The exact REVERSE of the importer (wordvault/ingest/extract.py):
where ingest turns Word styles into our Markdown, this turns our
Markdown back into Word styles, so a document can leave the vault as
cleanly as it arrived:

    # .. ######    ->  Heading 1..6 styles
    > text        ->  the Quote style (italic fallback if absent)
    - text        ->  List Bullet style
    1. text       ->  List Number style
    **b** *i*     ->  bold / italic / bold-italic runs
    blank line    ->  paragraph break (consecutive plain lines join
                      into one paragraph, per the house conventions)

Standard python-docx (already required by the importer); no other
dependencies.  The Word file also carries title and author in its
core properties — the same fields the importer reads back as a
document's true dates and identity.
"""

from __future__ import annotations

import re
from pathlib import Path

_RE_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_RE_BULLET = re.compile(r"^[-*]\s+(.*)$")
_RE_NUMBERED = re.compile(r"^\d{1,3}\.\s+(.*)$")
_RE_QUOTE = re.compile(r"^>\s?(.*)$")
_RE_INLINE = re.compile(
    r"\*\*\*(.+?)\*\*\*|\*\*(.+?)\*\*|(?<!\*)\*([^*]+?)\*(?!\*)"
)


def _add_runs(paragraph, text: str) -> None:
    """Write one line's text as runs, honoring **bold** / *italic* /
    ***both*** (unmatched markers stay literal, as everywhere)."""
    pos = 0
    for match in _RE_INLINE.finditer(text):
        if match.start() > pos:
            paragraph.add_run(text[pos:match.start()])
        if match.group(1) is not None:
            run = paragraph.add_run(match.group(1))
            run.bold = run.italic = True
        elif match.group(2) is not None:
            paragraph.add_run(match.group(2)).bold = True
        else:
            paragraph.add_run(match.group(3)).italic = True
        pos = match.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])


def _styled_paragraph(document, style_name: str):
    """A paragraph in the named style, or plain when the template
    lacks it (older/stripped templates) — never an error."""
    try:
        return document.add_paragraph(style=style_name)
    except KeyError:
        return document.add_paragraph()


def markdown_to_docx(markdown_text: str, path: str | Path, *,
                     title: str = "", author: str = "") -> None:
    """Write `markdown_text` to `path` as a .docx (see module doc)."""
    from docx import Document as DocxDocument

    document = DocxDocument()
    if title:
        document.core_properties.title = title
    if author:
        document.core_properties.author = author

    paragraph_lines: list[str] = []

    def flush() -> None:
        if paragraph_lines:
            paragraph = document.add_paragraph()
            _add_runs(paragraph, " ".join(paragraph_lines))
            paragraph_lines.clear()

    for line in markdown_text.split("\n"):
        heading = _RE_HEADING.match(line)
        bullet = _RE_BULLET.match(line)
        numbered = _RE_NUMBERED.match(line)
        quote = _RE_QUOTE.match(line)

        if heading:
            flush()
            level = len(heading.group(1))
            paragraph = _styled_paragraph(document, f"Heading {level}")
            _add_runs(paragraph, heading.group(2).strip())
        elif quote:
            flush()
            paragraph = _styled_paragraph(document, "Quote")
            _add_runs(paragraph, quote.group(1))
        elif bullet:
            flush()
            paragraph = _styled_paragraph(document, "List Bullet")
            _add_runs(paragraph, bullet.group(1))
        elif numbered:
            flush()
            paragraph = _styled_paragraph(document, "List Number")
            _add_runs(paragraph, numbered.group(1))
        elif not line.strip():
            flush()
        else:
            paragraph_lines.append(line.strip())
    flush()

    document.save(str(path))
