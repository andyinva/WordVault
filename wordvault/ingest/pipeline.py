"""
pipeline.py — Ingestor: the Phase A + Phase B orchestrator.

Ties extract.py and similar.py to a DocumentStore.  Designed for a very
large one-time run (6,000+ files) that must be SAFE TO RE-RUN:

  * Files already ingested (matched by path) are skipped, so an
    interrupted run just continues where it left off.
  * Texts identical to an already-stored document (matched by content
    hash) are collapsed to a duplicate-path note, never stored twice.
  * The version-detection phase clears only PENDING proposals and
    regenerates them; the author's confirmed/rejected decisions survive.

Usage (the CLI in tools/ingest_docx.py wraps exactly this):

    with DocumentStore("library.db") as store:
        stats = Ingestor(store).ingest_folder("path/to/DocxIndexSearch")
        print(stats.summary())
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Union

from wordvault.ingest.extract import (
    extract_markdown,
    extract_text,
    file_dates_utc,
    long_path,
)
from wordvault.ingest.similar import MinHasher, cluster
from wordvault.storage.store import DocumentStore


def _content_hash(text: str) -> str:
    """Stable hash of normalized text, for exact-duplicate collapsing."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class IngestStats:
    """What one ingest run did — printed as the run report."""

    files_seen: int = 0
    ingested: int = 0        # new documents created
    duplicates: int = 0      # exact-duplicate files collapsed to a note
    skipped_known: int = 0   # already ingested in a previous run (by path)
    empty: int = 0           # files with no extractable text
    archived: int = 0        # source files copied into the archive folder
    errors: list = field(default_factory=list)   # (path, message)
    groups_proposed: int = 0  # version groups awaiting review

    def summary(self) -> str:
        lines = [
            f"Files seen:           {self.files_seen}",
            f"New documents:        {self.ingested}",
            f"Exact duplicates:     {self.duplicates} (collapsed, paths noted)",
            f"Already ingested:     {self.skipped_known} (skipped)",
            f"Empty files:          {self.empty}",
            f"Errors:               {len(self.errors)}",
            f"Version groups:       {self.groups_proposed} proposed for review",
        ]
        if self.archived:
            lines.insert(2, f"Archived copies:      {self.archived}")
        for path, msg in self.errors[:20]:
            lines.append(f"  ERROR {path}: {msg}")
        if len(self.errors) > 20:
            lines.append(f"  ... and {len(self.errors) - 20} more errors")
        return "\n".join(lines)


class Ingestor:
    """Imports a folder of .docx files and proposes version groups."""

    def __init__(
        self,
        store: DocumentStore,
        threshold: float = 0.6,
        progress: Optional[Callable[[str], None]] = None,
        markdown: bool = True,
        archive_dir: Optional[Union[str, Path]] = None,
        tick: Optional[Callable[[], None]] = None,
    ):
        """
        threshold — minimum estimated similarity (0-1) for two documents
                    to be proposed as versions of each other (DESIGN.md:
                    Jaccard >= 0.6 by default).
        progress  — optional callback for status lines (the CLI passes
                    print; tests pass None).
        markdown  — translate structural Word formatting (headings, bold,
                    italics, lists, quotes) into Markdown while extracting
                    (default).  False = pure plain text.
        archive_dir — when given, every file that becomes a NEW document
                    is also copied here, named "<doc-id> - <filename>",
                    giving a flat folder holding a copy of exactly the
                    files the database was built from.  A failed copy is
                    logged as an error but never stops the import.
        tick      — optional no-argument callback invoked once per file
                    processed; the editor uses it to keep its progress
                    dialog painting during a long import.
        """
        self._store = store
        self._threshold = threshold
        self._say = progress or (lambda msg: None)
        self._extract = extract_markdown if markdown else extract_text
        self._archive_dir = Path(archive_dir) if archive_dir else None
        self._tick = tick or (lambda: None)

    # ------------------------------------------------------------- Phase A --

    def ingest_folder(
        self, folder: Union[str, Path], limit: Optional[int] = None
    ) -> IngestStats:
        """Run Phase A (extract + store) then Phase B (detect versions).
        `limit` ingests only the first N new files — handy for a trial run."""
        stats = IngestStats()
        folder = Path(folder)

        # Gather .docx files, oldest first, so documents enter the library
        # in the order the material was written (user requirement).
        # "~$..." files are Word's lock files, not documents.
        def mtime_or_zero(p: Path) -> float:
            """Sort key that survives >260-char Windows paths and files
            that vanish between the scan and the stat (sorted to the front;
            extraction will log them as errors rather than crash the run)."""
            try:
                return os.stat(long_path(p)).st_mtime
            except OSError:
                return 0.0

        files = sorted(
            (p for p in folder.rglob("*.docx") if not p.name.startswith("~$")),
            key=mtime_or_zero,
        )

        # Re-run safety: what do we already have?  (path -> skip;
        # content hash -> collapse as duplicate)
        known_paths: set[str] = set()
        known_hashes: dict[str, int] = {}
        for doc in self._store.ingested_documents():
            known_paths.add(doc.original_path)
            known_hashes[_content_hash(self._store.current_text(doc.id))] = doc.id
        # Duplicate files noted in earlier runs are "known" too — skip them
        # without re-reading (and without re-noting them a second time).
        known_paths.update(self._store.all_ingest_duplicate_paths())

        for path in files:
            stats.files_seen += 1
            self._tick()   # let a GUI progress dialog breathe
            path_str = str(path)

            if path_str in known_paths:
                stats.skipped_known += 1
                continue
            if limit is not None and stats.ingested >= limit:
                continue  # keep counting files_seen, ingest no more

            try:
                text = self._extract(path)
            except Exception as exc:  # unreadable/corrupt file: log, move on
                stats.errors.append((path_str, str(exc)))
                continue

            if not text:
                stats.empty += 1
                continue

            created_utc, mtime_utc = file_dates_utc(path)
            digest = _content_hash(text)

            if digest in known_hashes:
                # Same words under another name: remember the path only.
                self._store.record_ingest_duplicate(
                    known_hashes[digest], path_str, mtime_utc
                )
                stats.duplicates += 1
                continue

            # A genuinely new text: one document + one snapshot revision,
            # both carrying the FILE's dates, not today's.
            doc = self._store.create_document(
                title=path.stem,
                original_path=path_str,
                original_mtime=mtime_utc,
                created_utc=created_utc,
            )
            self._store.save_revision(
                doc.id, text, origin="ingest", created_utc=created_utc
            )
            known_hashes[digest] = doc.id
            known_paths.add(path_str)
            stats.ingested += 1

            # Optional archive: a flat copy of every file that became a
            # document, prefixed with its document id so names never clash.
            if self._archive_dir is not None:
                try:
                    self._archive_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(
                        long_path(path),
                        self._archive_dir / f"{doc.id:05d} - {path.name}",
                    )
                    stats.archived += 1
                except OSError as exc:
                    stats.errors.append((path_str, f"archive copy failed: {exc}"))

            if stats.ingested % 100 == 0:
                self._say(f"  ingested {stats.ingested} documents...")

        self._say(f"Phase A done: {stats.ingested} new documents.")

        # ---------------------------------------------------------- Phase B --
        stats.groups_proposed = self._detect_versions()
        self._say(f"Phase B done: {stats.groups_proposed} version groups proposed.")
        return stats

    # ------------------------------------------------------------- Phase B --

    def _detect_versions(self) -> int:
        """Fingerprint every ingested document and store near-duplicate
        groups as 'pending' proposals for the review screen (Phase C)."""
        docs = self._store.ingested_documents()
        if len(docs) < 2:
            return 0

        # Documents already inside a CONFIRMED or REJECTED group have been
        # judged by the author — leave them out of new proposals.
        decided: set[int] = set()
        for status in ("confirmed", "rejected"):
            for gid in self._store.list_similarity_groups(status):
                decided.update(d.id for d, _ in self._store.group_members(gid))

        hasher = MinHasher()
        signatures = {}
        for i, doc in enumerate(docs):
            if doc.id in decided:
                continue
            signatures[doc.id] = hasher.signature(self._store.current_text(doc.id))
            if (i + 1) % 200 == 0:
                self._say(f"  fingerprinted {i + 1}/{len(docs)} documents...")

        groups = cluster(signatures, threshold=self._threshold)

        # Replace old pending proposals with the fresh ones.
        self._store.clear_pending_similarity_groups()
        for members in groups:
            self._store.create_similarity_group(members)
        return len(groups)
