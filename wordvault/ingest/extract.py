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

    Runs of blank lines are capped at TWO.  Word documents often contain
    a dozen empty paragraphs in a row (title pages, manual page spacing);
    kept verbatim they become walls of blank space in the editor.  Capped
    at two, the text reads like a hand-written Markdown file: one blank
    line between paragraphs, at most a double break between sections.

    The same normalization is applied before exact-duplicate hashing, so
    two files that differ only in line endings, trailing spaces, or
    blank-line padding are recognized as the same text.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    lines = []
    blank_run = 0
    for line in (l.rstrip() for l in text.split("\n")):
        if line == "":
            blank_run += 1
            if blank_run > 2:
                continue          # cap the run — skip the excess blanks
        else:
            blank_run = 0
        lines.append(line)

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


def _effective_spacing_pts(paragraph, attribute: str):
    """
    Word's visual paragraph spacing ('space_after' / 'space_before') in
    points, honoring style inheritance: the paragraph's own setting wins,
    then its style, then the style's base styles.  None = nothing set
    anywhere we can see (Word then falls back to document defaults,
    which usually DO add space — see extract_markdown).
    """
    value = getattr(paragraph.paragraph_format, attribute)
    if value is not None:
        return value.pt
    style = paragraph.style
    seen = set()
    while style is not None and style.style_id not in seen:
        seen.add(style.style_id)
        try:
            value = getattr(style.paragraph_format, attribute)
        except AttributeError:
            value = None
        if value is not None:
            return value.pt
        style = style.base_style
    return None


def extract_markdown(path: Union[str, Path]) -> str:
    """
    Extract text from a .docx, translating structural formatting to
    Markdown (see the mapping table above).  This is the default
    extraction for ingest; extract_text() remains for a pure-plain run.

    Paragraph SPACING is reproduced faithfully: Word shows space between
    paragraphs either as empty paragraphs (kept, capped by
    normalize_text) or as style-based "space after/before" settings —
    for those, a blank line is emitted wherever Word actually showed
    space, so the text reads in the editor the way the page read in
    Word.  Rules:

      * headings always get a blank line before and after;
      * consecutive list items stay tight (a list is one block);
      * consecutive quote lines stay tight (one quotation);
      * otherwise: blank line when the previous paragraph's space-after
        or this paragraph's space-before is >= 4pt — and also when NO
        spacing is discoverable, because Word's document defaults add
        space between paragraphs (tight blocks in Word carry an explicit
        0pt / "No Spacing" style, which we honor).
    """
    from docx import Document as DocxDocument

    docx = DocxDocument(long_path(path))
    lines: list[str] = []
    prev_kind: str = ""       # 'heading' | 'quote' | 'list' | 'plain' | ''
    prev_space_after = None

    for p in docx.paragraphs:
        style = (p.style.name if p.style is not None else "") or ""
        style_lower = style.lower()

        # ---- classify and render this paragraph ----
        if style_lower.startswith("heading"):
            digits = "".join(ch for ch in style if ch.isdigit())
            level = min(int(digits), 6) if digits else 1
            kind, line = "heading", "#" * level + " " + p.text.strip()
        elif style_lower == "title":
            kind, line = "heading", "# " + p.text.strip()
        elif style_lower == "subtitle":
            kind, line = "heading", "## " + p.text.strip()
        elif "quote" in style_lower:
            kind, line = "quote", "> " + _runs_to_markdown(p)
        elif style_lower.startswith("list bullet"):
            kind, line = "list", "- " + _runs_to_markdown(p)
        elif style_lower.startswith("list number"):
            kind, line = "list", "1. " + _runs_to_markdown(p)
        else:
            kind, line = "plain", _runs_to_markdown(p)

        if kind == "plain" and not line.strip():
            # A genuinely empty paragraph: Word-authored spacing — keep it
            # as a blank line (normalize_text caps long runs later).
            lines.append("")
            prev_kind, prev_space_after = "", None
            continue

        # ---- decide whether Word showed space before this paragraph ----
        if lines and lines[-1] != "":
            if kind == "heading" or prev_kind == "heading":
                separated = True                    # headings breathe
            elif kind == prev_kind and kind in ("list", "quote"):
                separated = False                   # one block, stay tight
            else:
                after = prev_space_after
                before = _effective_spacing_pts(p, "space_before")
                if after is None and before is None:
                    separated = True                # Word defaults add space
                else:
                    separated = (after or 0) >= 4 or (before or 0) >= 4
            if separated:
                lines.append("")

        lines.append(line)
        prev_kind = kind
        prev_space_after = _effective_spacing_pts(p, "space_after")

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
