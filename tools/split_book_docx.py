#!/usr/bin/env python3
"""
split_book_docx.py — carve a finished Word book back into chapter
Markdown files, ready for the WordVault library and Book Formatter.

Why: a compiled book manuscript (like the out.docx the index builder
produces) contains things WordVault generates ITSELF — the title page,
the table of contents, and the index sections.  Only the chapters are
real writing.  This tool keeps exactly those:

  * everything BEFORE the first Heading 1 is dropped (title page, byline,
    the TOC and its field codes),
  * each Heading 1 starts a new chapter file ("# title" heading),
  * Heading 2/3/4 become ##/###/####,
  * italic and bold runs become *marks* / **marks**,
  * hidden field machinery (XE index markers, PAGEREF, INDEX fields) is
    ignored — only visible text survives,
  * chapters named "Scripture Index" / "Subject Index" and everything
    after them are dropped (WordVault will regenerate them, stage F4).

Usage:
    python tools/split_book_docx.py book.docx -o chapters_folder

Then load the folder into a library with tools/import_markdown.py and
assemble the book in Library > Book Formatter.

Standard library only (zipfile + ElementTree) — runs anywhere Python
does, Windows 11 or Ubuntu, no installs.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

#: WordprocessingML namespace — every tag in document.xml wears it.
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

#: Word paragraph styles -> Markdown heading prefixes.
_HEADING_PREFIX = {
    "Heading1": "# ",
    "Heading2": "## ",
    "Heading3": "### ",
    "Heading4": "#### ",
}

#: Heading-1 titles that mark generated back matter: the chapter stream
#: ends when one of these (or anything after it) appears.
_BACK_MATTER = {"scripture index", "subject index"}


def _style_of(paragraph) -> str:
    """The paragraph's named style, or 'Normal' when unstyled."""
    el = paragraph.find(f"{W}pPr/{W}pStyle")
    return el.get(f"{W}val") if el is not None else "Normal"


def _runs_of(paragraph):
    """Yield (text, bold, italic) for each VISIBLE run.

    Runs that are field plumbing — instruction text like { XE "..." }
    or { PAGEREF ... }, and the fldChar begin/separate/end markers —
    carry no visible words and are skipped entirely."""
    for run in paragraph.iter(f"{W}r"):
        if run.find(f"{W}instrText") is not None:
            continue                       # hidden field instruction
        if run.find(f"{W}fldChar") is not None:
            continue                       # field state marker
        rpr = run.find(f"{W}rPr")
        bold = rpr is not None and rpr.find(f"{W}b") is not None
        italic = rpr is not None and rpr.find(f"{W}i") is not None
        text = "".join(t.text or "" for t in run.findall(f"{W}t"))
        if text:
            yield text, bold, italic


def _markdown_line(paragraph) -> str:
    """One paragraph's visible text with */** marks applied.

    Adjacent runs sharing the same formatting are merged first, so a
    phrase Word split across several runs (its habit) gets ONE pair of
    marks, not one per fragment.  Leading/trailing spaces are moved
    outside the marks — '* word *' would not render as italic."""
    merged: list[list] = []                # [text, bold, italic]
    for text, bold, italic in _runs_of(paragraph):
        if merged and merged[-1][1] == bold and merged[-1][2] == italic:
            merged[-1][0] += text
        else:
            merged.append([text, bold, italic])

    parts = []
    for text, bold, italic in merged:
        mark = ("***" if bold and italic else
                "**" if bold else "*" if italic else "")
        if mark and text.strip():
            lead = text[: len(text) - len(text.lstrip())]
            trail = text[len(text.rstrip()):]
            parts.append(f"{lead}{mark}{text.strip()}{mark}{trail}")
        else:
            parts.append(text)
    return "".join(parts).strip()


def _safe_filename(title: str) -> str:
    """A chapter title as a filename Windows and Linux both accept."""
    cleaned = re.sub(r'[<>:"/\\|?*]', "", title).strip().rstrip(".")
    return cleaned or "untitled"


def split_book(docx_path: Path, out_dir: Path) -> list[Path]:
    """The whole operation; returns the chapter files written."""
    with zipfile.ZipFile(docx_path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    body = root.find(f"{W}body")

    chapters: list[tuple[str, list[str]]] = []   # (title, md lines)
    current: list[str] | None = None             # None until 1st Heading1

    for paragraph in body.findall(f"{W}p"):
        style = _style_of(paragraph)
        line = _markdown_line(paragraph)

        if style == "Heading1":
            if line.lower() in _BACK_MATTER:
                break                    # generated indexes: stop here
            current = []
            chapters.append((line, current))
            current.append(f"# {line}")
            continue
        if current is None:
            continue                     # front matter: title page, TOC
        if not line:
            continue                     # blank paragraphs add nothing
        prefix = _HEADING_PREFIX.get(style, "")
        current.append(prefix + line)

    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for number, (title, lines) in enumerate(chapters):
        # Two-digit prefix keeps the files listed in book order.
        path = out_dir / f"{number:02d} {_safe_filename(title)}.md"
        # Blank line between blocks: the Markdown paragraph separator.
        path.write_text("\n\n".join(lines) + "\n", encoding="utf-8")
        written.append(path)
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Split a book .docx into chapter Markdown files "
                    "(drops title page, TOC, and index sections).")
    parser.add_argument("docx", help="The compiled book .docx")
    parser.add_argument("-o", "--out", required=True,
                        help="Folder to write the chapter .md files into")
    args = parser.parse_args(argv)

    written = split_book(Path(args.docx), Path(args.out))
    if not written:
        print("No chapters found — does the document use Heading 1 "
              "for its chapter titles?", file=sys.stderr)
        return 1
    for path in written:
        print(f"  {path.name}")
    print(f"{len(written)} chapter files in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
