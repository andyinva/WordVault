"""
extract.py — pull plain text out of .docx files (ingest Phase A).

Formatting is discarded BY DESIGN (DESIGN.md section 2): WordVault stores
plain UTF-8 text; styling belongs to the future Formatter app.  We keep
paragraph breaks (one per line) because they carry structure, not style.

Requires python-docx:  pip install python-docx
The import lives inside extract_text() so that the rest of WordVault
(editor, storage) never needs python-docx installed.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Union


def long_path(path: Union[str, Path]) -> str:
    """
    Return a path string safe for very long paths on Windows.

    Windows historically limits paths to 260 characters (MAX_PATH); some
    essay filenames are long enough to exceed it, which makes open() and
    os.stat() fail even though the directory listing shows the file.  The
    '\\\\?\\' extended-length prefix on an absolute path lifts the limit.
    On Linux (and for short Windows paths) this returns the path unchanged.
    """
    p = str(Path(path).absolute())
    if os.name == "nt" and len(p) > 240 and not p.startswith("\\\\?\\"):
        p = "\\\\?\\" + p
    return p


def normalize_text(text: str) -> str:
    """
    Normalize extracted text to WordVault's storage form
    (DESIGN.md section 12): LF line endings, no trailing whitespace on
    lines, exactly one trailing newline on non-empty text.

    The same normalization is applied before exact-duplicate hashing, so
    two files that differ only in line endings or trailing spaces are
    recognized as the same text.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    body = "\n".join(lines).strip("\n")
    return body + "\n" if body else ""


def extract_text(path: Union[str, Path]) -> str:
    """
    Extract normalized plain text from one .docx file — every scrap of
    formatting discarded.

    Paragraph text only.  Tables/headers/footnotes are out of scope for
    essays; they can be added here later without touching anything else.
    """
    from docx import Document as DocxDocument  # deferred import, see module doc

    docx = DocxDocument(long_path(path))  # long_path: survive >260-char paths
    return normalize_text("\n".join(p.text for p in docx.paragraphs))


# -- Markdown extraction ------------------------------------------------------
#
# The design keeps documents as plain text, but plain text can CARRY a
# little structure by convention: Markdown.  These mappings translate the
# most meaningful Word formatting into Markdown so it survives ingest and
# can be mapped back to Word styles by the future Formatter:
#
#     Word style "Heading 1..6"      ->  # .. ######
#     Word style "Title"/"Subtitle"  ->  # / ##
#     Word styles "Quote"/"Intense Quote"  ->  > blockquote
#     Word styles "List Bullet*"     ->  - item
#     Word styles "List Number*"     ->  1. item
#     bold / italic runs             ->  **bold** / *italic* / ***both***
#
# Everything else (fonts, sizes, colors, alignment) is aesthetics, not
# structure — deliberately dropped, per DESIGN.md section 2.

def _runs_to_markdown(paragraph) -> str:
    """One paragraph's runs -> text with **bold** / *italic* markers.
    Adjacent runs with identical formatting are merged first, because
    Word often splits a single visually-uniform phrase into many runs."""
    merged: list[list] = []   # [bold, italic, text]
    for run in paragraph.runs:
        if not run.text:
            continue
        bold, italic = bool(run.bold), bool(run.italic)
        if merged and merged[-1][0] == bold and merged[-1][1] == italic:
            merged[-1][2] += run.text
        else:
            merged.append([bold, italic, run.text])

    parts: list[str] = []
    for bold, italic, text in merged:
        if not text.strip() or (not bold and not italic):
            parts.append(text)      # plain, or whitespace-only: as-is
            continue
        # Markers must hug the words, not surrounding spaces, or Markdown
        # renderers refuse them ("** bold **" is not bold).
        lead = text[: len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()):]
        marker = "***" if bold and italic else "**" if bold else "*"
        parts.append(f"{lead}{marker}{text.strip()}{marker}{trail}")
    return "".join(parts)


def extract_markdown(path: Union[str, Path]) -> str:
    """Extract text from a .docx, translating structural formatting to
    Markdown (see the mapping table above).  This is the default
    extraction for ingest; extract_text() remains for a pure-plain run."""
    from docx import Document as DocxDocument

    docx = DocxDocument(long_path(path))
    lines: list[str] = []
    for p in docx.paragraphs:
        style = (p.style.name if p.style is not None else "") or ""
        style_lower = style.lower()

        if style_lower.startswith("heading"):
            # "Heading 1" .. "Heading 9" -> # .. ###### (capped at 6).
            digits = "".join(ch for ch in style if ch.isdigit())
            level = min(int(digits), 6) if digits else 1
            lines.append("#" * level + " " + p.text.strip())
        elif style_lower == "title":
            lines.append("# " + p.text.strip())
        elif style_lower == "subtitle":
            lines.append("## " + p.text.strip())
        elif "quote" in style_lower:
            lines.append("> " + _runs_to_markdown(p))
        elif style_lower.startswith("list bullet"):
            lines.append("- " + _runs_to_markdown(p))
        elif style_lower.startswith("list number"):
            lines.append("1. " + _runs_to_markdown(p))
        else:
            lines.append(_runs_to_markdown(p))
    return normalize_text("\n".join(lines))


def file_dates_utc(path: Union[str, Path]) -> tuple[str, str]:
    """
    (created_utc, modified_utc) for a file, as stored ISO-8601 UTC strings.

    On Windows st_ctime is true creation time; on Linux it is metadata-
    change time — so we take min(ctime, mtime) as the best available
    "written when" estimate, and mtime as the modification date.  These
    become the document's created_utc / original_mtime, keeping the
    library ordered by when the material was actually written.
    """
    st = os.stat(long_path(path))  # long_path: survive >260-char paths
    to_iso = lambda ts: datetime.fromtimestamp(ts, timezone.utc).isoformat()
    return to_iso(min(st.st_ctime, st.st_mtime)), to_iso(st.st_mtime)
