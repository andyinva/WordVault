#!/usr/bin/env python3
"""
import_markdown.py — load a folder of .md files into a WordVault
library, one document per file.

The natural partner of split_book_docx.py: split a book into chapter
Markdown, import the chapters here, then assemble them in Library >
Book Formatter.  Works for any Markdown files, not just book chapters.

Each file becomes a library document whose title is the file's first
'# ' heading (or the filename without its number prefix when there is
no heading), with the file's text as its first revision — full
version history begins from that moment, like any WordVault document.

The duplicate guard compares TEXT, not just titles: a file whose text
already lives in the library under the same title is skipped (so
running the import twice cannot create duplicates), but a file that
merely SHARES a title with a different document — a book's "Preface"
colliding with an old essay called "Preface" — is imported under a
numbered title like "Preface (2)".  Rename it afterwards in WordVault
(Document > Rename) if you want something prettier.

Usage:
    python tools/import_markdown.py chapters_folder
    python tools/import_markdown.py chapters_folder --library my.db

Default library: ~/.wordvault/library.db (the one WordVault opens).
Close WordVault before importing, or restart it afterwards, so the
editor sees the new documents.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Run from the repo without installing: put the repo root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wordvault import DocumentStore  # noqa: E402


def title_for(path: Path, text: str) -> str:
    """The document title: the first '# ' heading, else the filename
    with any 'NN ' ordering prefix removed."""
    for line in text.splitlines():
        m = re.match(r"^#\s+(.+)$", line)
        if m:
            return m.group(1).strip()
    return re.sub(r"^\d+\s+", "", path.stem)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Import a folder of .md files into a WordVault "
                    "library (one document per file; duplicates by "
                    "title are skipped).")
    parser.add_argument("folder", help="Folder containing .md files")
    parser.add_argument("--library",
                        default=str(Path.home() / ".wordvault"
                                    / "library.db"),
                        help="Library database (default: the one "
                             "WordVault opens)")
    args = parser.parse_args(argv)

    folder = Path(args.folder)
    files = sorted(folder.glob("*.md"))
    if not files:
        print(f"No .md files in {folder}", file=sys.stderr)
        return 1

    store = DocumentStore(args.library)
    try:
        # title -> [doc, doc...]: titles are NOT unique in a library.
        by_title: dict[str, list] = {}
        for doc in store.list_documents():
            by_title.setdefault(doc.title, []).append(doc)

        def current_text(doc) -> str:
            latest = store.latest_revision(doc.id)
            return store.get_text(latest.id) if latest else ""

        added = skipped = 0
        for path in files:
            text = path.read_text(encoding="utf-8")
            title = title_for(path, text)

            # The REAL duplicate test: same text already stored under
            # this title (under any "(n)" variant too)?  Then skip.
            candidates = [d for t, docs in by_title.items()
                          if t == title or t.startswith(f"{title} (")
                          for d in docs]
            if any(current_text(d) == text for d in candidates):
                print(f"  skip (this text is already in the library): "
                      f"{title}")
                skipped += 1
                continue

            # A title collision with DIFFERENT text is not a duplicate
            # — it is two documents that happen to share a name.  Keep
            # both: the newcomer gets a numbered title.
            final_title = title
            n = 2
            while by_title.get(final_title):
                final_title = f"{title} ({n})"
                n += 1
            if final_title != title:
                print(f"  note: another document is already called "
                      f"'{title}' — importing as '{final_title}'")

            doc = store.create_document(final_title,
                                        original_path=str(path))
            store.save_revision(doc.id, text, origin="md import")
            by_title.setdefault(final_title, []).append(doc)
            print(f"  added: {final_title}")
            added += 1
    finally:
        store.close()

    print(f"{added} imported, {skipped} skipped -> {args.library}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
