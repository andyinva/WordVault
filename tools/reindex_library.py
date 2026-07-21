#!/usr/bin/env python3
"""
reindex_library.py - upgrade an existing library with the newer indexes.

Two jobs, both safe to re-run:

  1. Scripture index (always): scans every document's current text for
     Bible references (John 3:16, 1 Cor. 15:22, Gen 1:1-5, ...) and
     fills the verse index that powers "documents sharing verses".
     Documents ingested before this feature existed get indexed here;
     anything saved from now on is indexed automatically.

  2. Formatting refresh (--formatting): re-reads each document's original
     .docx file (when it still exists) with the Markdown extractor, so
     headings, bold, italics, lists and quotes recovered from Word are
     carried into the text. A document whose text would change gets ONE
     new revision (origin 'ingest') - the append-only rule holds, so the
     plain-text state remains one step back in its history.

Usage:

    python tools/reindex_library.py                  # scripture index only
    python tools/reindex_library.py --formatting     # both jobs

The library defaults to the editor's ~/.wordvault/library.db; an
encrypted library asks for its passphrase.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wordvault.storage.encryption import is_encrypted_database  # noqa: E402
from wordvault.storage.store import DocumentStore  # noqa: E402


def default_library_path() -> Path:
    folder = Path.home() / ".wordvault"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "library.db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", default=None,
                        help="library database (default: ~/.wordvault/library.db)")
    parser.add_argument("--formatting", action="store_true",
                        help="also re-extract Markdown formatting from the "
                             "original .docx files")
    args = parser.parse_args(argv)

    library = Path(args.library) if args.library else default_library_path()
    passphrase = None
    if is_encrypted_database(library):
        passphrase = getpass.getpass("Library passphrase: ")

    reformatted = 0
    missing_files = 0
    total_verses = 0

    with DocumentStore(library, passphrase=passphrase) as store:
        docs = store.list_documents()
        print(f"Library: {library}  ({len(docs)} documents)")

        for i, doc in enumerate(docs, start=1):
            # --- job 2: formatting refresh (optional) ---
            if args.formatting and doc.original_path:
                from wordvault.ingest.extract import extract_markdown, long_path

                source = Path(doc.original_path)
                if source.exists() or Path(long_path(source)).exists():
                    try:
                        markdown = extract_markdown(source)
                    except Exception as exc:
                        print(f"  ERROR {doc.title}: {exc}")
                        markdown = None
                    if markdown and markdown != store.current_text(doc.id):
                        # One new revision; save_revision also refreshes
                        # the scripture index for this document.
                        store.save_revision(doc.id, markdown, origin="ingest")
                        reformatted += 1
                else:
                    missing_files += 1

            # --- job 1: scripture index (always) ---
            total_verses += store.reindex_scripture(doc.id)

            if i % 200 == 0:
                print(f"  processed {i}/{len(docs)} documents...")

    print()
    print(f"Scripture index:  {total_verses} verse citations across the library")
    if args.formatting:
        print(f"Formatting:       {reformatted} documents gained Markdown "
              f"formatting (as a new revision)")
        if missing_files:
            print(f"                  {missing_files} original files no longer "
                  f"exist (texts kept as they are)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
