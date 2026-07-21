#!/usr/bin/env python3
"""
ingest_docx.py — command-line importer for a legacy .docx library
(DESIGN.md section 6, Phases A and B).

Typical use on Windows 11:

    cd C:\\Users\\Andrew Hopkins\\Documents\\WordVault
    pip install python-docx
    python tools\\ingest_docx.py "C:\\Users\\Andrew Hopkins\\Documents\\DocxIndexSearch"

and on Ubuntu:

    python3 tools/ingest_docx.py ~/Documents/DocxIndexSearch

By default the documents go into the same library the editor uses
(~/.wordvault/library.db), so after ingesting, just start the editor and
the whole library is there.  Safe to re-run: already-ingested files are
skipped, so an interrupted run simply continues.

Recommended first step:  --limit 50  ingests only 50 files as a trial.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running straight from the repository without installing the package:
# put the repo root (this file's grandparent) on the import path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wordvault.ingest import Ingestor            # noqa: E402
from wordvault.storage.store import DocumentStore  # noqa: E402


def default_library_path() -> Path:
    """Same default library the editor opens (see wordvault/__main__.py)."""
    folder = Path.home() / ".wordvault"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "library.db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import .docx files into a WordVault library and "
        "propose version groups for review."
    )
    parser.add_argument("source", help="folder containing .docx files (searched recursively)")
    parser.add_argument(
        "library",
        nargs="?",
        default=None,
        help="library database file (default: the editor's ~/.wordvault/library.db)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.6,
        help="similarity needed to propose two documents as versions (0-1, default 0.6)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="ingest at most N new files (a trial run; re-run without it to continue)",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="extract pure plain text (default translates Word headings, "
        "bold/italic, lists and quotes into Markdown)",
    )
    parser.add_argument(
        "--archive",
        metavar="DIR",
        default=None,
        help="also copy every file that becomes a document into DIR, "
        "named '<doc-id> - <filename>'",
    )
    args = parser.parse_args(argv)

    source = Path(args.source)
    if not source.is_dir():
        parser.error(f"Not a folder: {source}")

    library = Path(args.library) if args.library else default_library_path()
    print(f"Library:  {library}")
    print(f"Source:   {source}")

    with DocumentStore(library) as store:
        stats = Ingestor(
            store, threshold=args.threshold, progress=print,
            markdown=not args.plain, archive_dir=args.archive,
        ).ingest_folder(source, limit=args.limit)

    print()
    print(stats.summary())
    print()
    print("Next: open the editor (python -m wordvault) to see the documents.")
    print("The proposed version groups await the review screen (roadmap stage 5).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
