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
    Extract normalized plain text from one .docx file.

    Paragraph text only — python-docx returns each paragraph's text with
    all character formatting already stripped, which is exactly what we
    want.  Tables/headers/footnotes are out of scope for essays; they can
    be added here later without touching anything else.
    """
    from docx import Document as DocxDocument  # deferred import, see module doc

    docx = DocxDocument(long_path(path))  # long_path: survive >260-char paths
    return normalize_text("\n".join(p.text for p in docx.paragraphs))


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
