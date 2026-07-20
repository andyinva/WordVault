#!/usr/bin/env python3
"""
backup_library.py - command-line encrypted backup (and restore) of a
WordVault library. The same operations as the editor's File menu, for
scripting and scheduled tasks (Windows Task Scheduler / cron).

Examples:

    python tools/backup_library.py backup  "D:\\Backups\\wv-2026-07-19.wvbackup"
    python tools/backup_library.py info    "D:\\Backups\\wv-2026-07-19.wvbackup"
    python tools/backup_library.py restore "D:\\Backups\\wv-2026-07-19.wvbackup"

The passphrase is asked interactively (never on the command line, where
it would land in shell history). The library defaults to the editor's
~/.wordvault/library.db; pass --library to use another file.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wordvault.storage.backup import (  # noqa: E402
    make_backup,
    read_backup,
    restore_backup,
)
from wordvault.storage.store import DocumentStore  # noqa: E402


def default_library_path() -> Path:
    folder = Path.home() / ".wordvault"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "library.db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "info", "restore"])
    parser.add_argument("file", help="the .wvbackup file")
    parser.add_argument("--library", default=None,
                        help="library database (default: ~/.wordvault/library.db)")
    args = parser.parse_args(argv)

    library = Path(args.library) if args.library else default_library_path()

    if args.action == "backup":
        pw = getpass.getpass("Passphrase: ")
        if getpass.getpass("Repeat passphrase: ") != pw:
            print("Passphrases did not match; nothing written.")
            return 1
        with DocumentStore(library) as store:
            info = make_backup(store, args.file, pw)
        print(f"Backed up {info.documents} documents, "
              f"{info.revisions} revisions -> {args.file}")

    elif args.action == "info":
        pw = getpass.getpass("Passphrase: ")
        info, _db = read_backup(args.file, pw)
        print(f"Created:   {info.created_utc}")
        print(f"Schema:    v{info.schema_version}")
        print(f"Documents: {info.documents}")
        print(f"Revisions: {info.revisions}")

    else:  # restore
        pw = getpass.getpass("Passphrase: ")
        info, _db = read_backup(args.file, pw)   # verify before touching anything
        print(f"Backup: {info.documents} documents, {info.revisions} revisions, "
              f"made {info.created_utc}")
        answer = input(f"Replace {library} with this backup? [y/N] ")
        if answer.strip().lower() != "y":
            print("Nothing changed.")
            return 0
        restore_backup(args.file, pw, library)
        print(f"Restored. Previous library kept as {library.name}.before-restore")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
