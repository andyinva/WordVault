"""
store.py — DocumentStore, the one and only door to a WordVault database.

Everything the editor (or an ingest tool, or a future server) does with
stored text goes through this class: creating documents, saving revisions,
rebuilding historical text, tagging, provenance, and basic current-text
search.  No other module executes SQL.

Key behaviors (DESIGN.md sections 4-5):
  * save_revision() is called whenever the author pauses typing.  It skips
    identical states, stores a compact diff most of the time, and stores a
    full snapshot every `snapshot_interval` revisions so rebuilds stay fast.
  * History is append-only.  Nothing here ever UPDATEs or DELETEs a revision.
  * The doc_text FTS index always mirrors each document's CURRENT text, so
    library-wide search is instant.  If this SQLite build lacks FTS5 the
    store still works; only search_current() is unavailable.
"""

from __future__ import annotations

import sqlite3
import uuid as uuid_module
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from wordvault.models import Document, GatherItem, Revision, SourceLink, Tag
from wordvault.storage import schema
from wordvault.storage.diffs import apply_delta, make_delta


def _utc_now() -> str:
    """Current time as an ISO-8601 UTC string — the only timestamp format
    stored anywhere in the database (display conversion is the UI's job)."""
    return datetime.now(timezone.utc).isoformat()


class DocumentStore:
    """
    Open (or create) a WordVault library database.

    Usage:
        with DocumentStore("library.db") as store:
            doc = store.create_document("My Essay")
            store.save_revision(doc.id, "First words.")

    Parameters
    ----------
    path : str | Path
        Database file.  ":memory:" gives a throwaway in-memory library,
        which the test suite uses heavily.
    snapshot_interval : int
        A full snapshot is stored at least every this-many revisions, so
        rebuilding any historical state never replays more than
        snapshot_interval - 1 diffs.  Default 50 (see DESIGN.md).
    """

    def __init__(
        self,
        path: Union[str, Path],
        snapshot_interval: int = 50,
        passphrase: Optional[str] = None,
    ):
        if snapshot_interval < 1:
            raise ValueError("snapshot_interval must be >= 1")
        self.snapshot_interval = snapshot_interval

        # Stage 9: with a passphrase the database is SQLCipher-encrypted on
        # disk; without one it is plain SQLite.  The sqlcipher3 module
        # mirrors sqlite3, so everything below this constructor is
        # identical for both cases.
        from wordvault.storage.encryption import (
            apply_key,
            is_encrypted_database,
            sqlcipher_module,
        )

        if passphrase is not None:
            mod = sqlcipher_module()
            self._conn = mod.connect(str(path))
            self._conn.row_factory = mod.Row
            apply_key(self._conn, passphrase)
            try:  # a wrong key surfaces on the first real read
                self._conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
            except mod.DatabaseError:
                self._conn.close()
                raise ValueError(
                    "Wrong passphrase for this encrypted library."
                ) from None
            self.is_encrypted = True
        else:
            if is_encrypted_database(path):
                raise ValueError(
                    "This library is encrypted — open it with its passphrase."
                )
            self._conn = sqlite3.connect(str(path))
            self._conn.row_factory = sqlite3.Row  # column access by name
            self.is_encrypted = False

        # create_all is idempotent and reports whether FTS5 search exists.
        self.fts_available: bool = schema.create_all(self._conn)

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        """Commit and close.  The store is unusable afterwards."""
        self._conn.commit()
        self._conn.close()

    def __enter__(self) -> "DocumentStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- documents ----------------------------------------------------------

    def create_document(
        self,
        title: str,
        parent_doc_id: Optional[int] = None,
        original_path: Optional[str] = None,
        original_mtime: Optional[str] = None,
        created_utc: Optional[str] = None,
        doc_uuid: Optional[str] = None,
    ) -> Document:
        """
        Create a new logical document (with no revisions yet).

        `created_utc` and `doc_uuid` are normally left to default; the
        ingest tool passes explicit values so imported documents keep the
        dates of their source files, and .wvdoc import (a later stage)
        passes the uuid to merge rather than duplicate.
        """
        row_uuid = doc_uuid or str(uuid_module.uuid4())
        created = created_utc or _utc_now()

        cur = self._conn.execute(
            "INSERT INTO documents "
            "(uuid, title, created_utc, parent_doc_id, original_path, original_mtime) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (row_uuid, title, created, parent_doc_id, original_path, original_mtime),
        )
        self._conn.commit()
        return self.get_document(cur.lastrowid)

    def get_document(self, doc_id: int) -> Document:
        """Fetch one document by id; raises KeyError if it does not exist."""
        row = self._conn.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"No document with id {doc_id}")
        return self._doc_from_row(row)

    def get_document_by_uuid(self, doc_uuid: str) -> Optional[Document]:
        """Fetch by stable uuid (used by import/merge); None if unknown."""
        row = self._conn.execute(
            "SELECT * FROM documents WHERE uuid = ?", (doc_uuid,)
        ).fetchone()
        return self._doc_from_row(row) if row else None

    def list_documents(self) -> list[Document]:
        """All documents, oldest first (creation order = chronological)."""
        rows = self._conn.execute(
            "SELECT * FROM documents ORDER BY created_utc, id"
        ).fetchall()
        return [self._doc_from_row(r) for r in rows]

    def rename_document(self, doc_id: int, new_title: str) -> None:
        """Change a document's title (titles are metadata, not history)."""
        self.get_document(doc_id)  # existence check
        self._conn.execute(
            "UPDATE documents SET title = ? WHERE id = ?", (new_title, doc_id)
        )
        # Keep the search index's title column in step.
        self._refresh_fts(doc_id)
        self._conn.commit()

    # -- revisions (the heart of WordVault) ---------------------------------

    def save_revision(
        self,
        doc_id: int,
        text: str,
        origin: str = "typing",
        created_utc: Optional[str] = None,
    ) -> Optional[Revision]:
        """
        Record the document's current text as a new revision.

        Returns the new Revision, or None if `text` is identical to the
        latest stored state (saving nothing is the correct behavior for
        an auto-save timer that fires with no changes).

        Snapshot-vs-diff decision: store a diff against the latest revision
        unless the replay chain would grow to `snapshot_interval` — then
        store a full snapshot to cap rebuild cost.
        """
        self.get_document(doc_id)  # existence check
        latest = self.latest_revision(doc_id)

        if latest is None:
            # Very first revision is always a full snapshot.
            kind, payload = "snapshot", text
            parent_id = None
        else:
            current_text = self.get_text(latest.id)
            if current_text == text:
                return None  # nothing changed — skip, per capture policy

            # +1 counts the diff we are about to add to the replay chain.
            if self._chain_length(latest.id) + 1 >= self.snapshot_interval:
                kind, payload = "snapshot", text
            else:
                kind, payload = "diff", make_delta(current_text, text)
            parent_id = latest.id

        cur = self._conn.execute(
            "INSERT INTO revisions "
            "(doc_id, created_utc, kind, payload, parent_rev_id, origin) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (doc_id, created_utc or _utc_now(), kind, payload, parent_id, origin),
        )
        # The FTS index mirrors current text; this save changed it.
        self._refresh_fts(doc_id, current_text=text)
        self._conn.commit()
        return self.get_revision(cur.lastrowid)

    def get_revision(self, rev_id: int) -> Revision:
        """Fetch one revision's metadata (not its text — see get_text)."""
        row = self._conn.execute(
            "SELECT id, doc_id, created_utc, kind, origin, parent_rev_id "
            "FROM revisions WHERE id = ?",
            (rev_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"No revision with id {rev_id}")
        return Revision(**dict(row))

    def latest_revision(self, doc_id: int) -> Optional[Revision]:
        """Newest revision of a document, or None if it has no text yet."""
        row = self._conn.execute(
            "SELECT id, doc_id, created_utc, kind, origin, parent_rev_id "
            "FROM revisions WHERE doc_id = ? ORDER BY id DESC LIMIT 1",
            (doc_id,),
        ).fetchone()
        return Revision(**dict(row)) if row else None

    def list_revisions(self, doc_id: int) -> list[Revision]:
        """A document's full history, oldest first."""
        rows = self._conn.execute(
            "SELECT id, doc_id, created_utc, kind, origin, parent_rev_id "
            "FROM revisions WHERE doc_id = ? ORDER BY id",
            (doc_id,),
        ).fetchall()
        return [Revision(**dict(r)) for r in rows]

    def get_text(self, rev_id: int) -> str:
        """
        Rebuild the full text as it stood at revision `rev_id`.

        Walk parent links back to the nearest snapshot (bounded by
        snapshot_interval), then replay the diffs forward.
        """
        # Collect the diff chain: rev_id back to (not including) a snapshot.
        chain: list[sqlite3.Row] = []
        row = self._payload_row(rev_id)
        while row["kind"] != "snapshot":
            chain.append(row)
            row = self._payload_row(row["parent_rev_id"])

        # row is now the snapshot; replay diffs oldest-first on top of it.
        text = row["payload"]
        for diff_row in reversed(chain):
            text = apply_delta(text, diff_row["payload"])
        return text

    def current_text(self, doc_id: int) -> str:
        """The document's newest text ("" if it has no revisions yet)."""
        latest = self.latest_revision(doc_id)
        return self.get_text(latest.id) if latest else ""

    # -- provenance ---------------------------------------------------------

    def record_source(
        self,
        target_rev_id: int,
        source_doc_id: int,
        source_rev_id: int,
        excerpt_start: Optional[int] = None,
        excerpt_end: Optional[int] = None,
    ) -> SourceLink:
        """Record that `target_rev_id` pulled text from a source document."""
        cur = self._conn.execute(
            "INSERT INTO sources "
            "(target_rev_id, source_doc_id, source_rev_id, excerpt_start, excerpt_end) "
            "VALUES (?, ?, ?, ?, ?)",
            (target_rev_id, source_doc_id, source_rev_id, excerpt_start, excerpt_end),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT * FROM sources WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return SourceLink(**dict(row))

    def sources_for(self, target_rev_id: int) -> list[SourceLink]:
        """All provenance records attached to one revision."""
        rows = self._conn.execute(
            "SELECT * FROM sources WHERE target_rev_id = ? ORDER BY id",
            (target_rev_id,),
        ).fetchall()
        return [SourceLink(**dict(r)) for r in rows]

    # -- tags ---------------------------------------------------------------

    def add_tag(self, doc_id: int, name: str) -> Tag:
        """Attach a tag to a document, creating the tag if it is new."""
        self.get_document(doc_id)  # existence check
        name = name.strip()
        self._conn.execute(
            "INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,)
        )
        tag_row = self._conn.execute(
            "SELECT * FROM tags WHERE name = ?", (name,)
        ).fetchone()
        self._conn.execute(
            "INSERT OR IGNORE INTO document_tags (doc_id, tag_id) VALUES (?, ?)",
            (doc_id, tag_row["id"]),
        )
        self._conn.commit()
        return Tag(id=tag_row["id"], name=tag_row["name"])

    def remove_tag(self, doc_id: int, name: str) -> None:
        """Detach a tag from a document (the tag itself is kept)."""
        self._conn.execute(
            "DELETE FROM document_tags WHERE doc_id = ? AND "
            "tag_id = (SELECT id FROM tags WHERE name = ?)",
            (doc_id, name.strip()),
        )
        self._conn.commit()

    def tags_for(self, doc_id: int) -> list[Tag]:
        """All tags on one document, alphabetical."""
        rows = self._conn.execute(
            "SELECT t.id, t.name FROM tags t "
            "JOIN document_tags dt ON dt.tag_id = t.id "
            "WHERE dt.doc_id = ? ORDER BY t.name",
            (doc_id,),
        ).fetchall()
        return [Tag(**dict(r)) for r in rows]

    def list_tags(self) -> list[Tag]:
        """Every tag in the library, alphabetical (for filter menus)."""
        rows = self._conn.execute("SELECT * FROM tags ORDER BY name").fetchall()
        return [Tag(**dict(r)) for r in rows]

    def documents_with_tag(self, name: str) -> list[Document]:
        """All documents carrying a tag, oldest first."""
        rows = self._conn.execute(
            "SELECT d.* FROM documents d "
            "JOIN document_tags dt ON dt.doc_id = d.id "
            "JOIN tags t ON t.id = dt.tag_id "
            "WHERE t.name = ? ORDER BY d.created_utc, d.id",
            (name.strip(),),
        ).fetchall()
        return [self._doc_from_row(r) for r in rows]

    # -- backup support ------------------------------------------------------

    def vacuum_into(self, dest_path: Union[str, Path]) -> None:
        """Write a clean, compacted copy of the whole database to a new
        file (SQLite's VACUUM INTO).  Used by the backup tool; the live
        database keeps running untouched."""
        self._conn.commit()
        self._conn.execute("VACUUM INTO ?", (str(dest_path),))

    def revision_count(self) -> int:
        """Total revisions across all documents (for backup headers/UI)."""
        return self._conn.execute("SELECT COUNT(*) FROM revisions").fetchone()[0]

    def export_plaintext_copy(self, dest_path: Union[str, Path]) -> None:
        """A PLAIN (unencrypted) clean copy of the database — what goes
        inside a .wvbackup, whose own envelope provides the encryption.
        Plain store: just VACUUM INTO.  Encrypted store: SQLCipher export."""
        if not self.is_encrypted:
            self.vacuum_into(dest_path)
            return
        self._conn.commit()
        self._conn.execute(
            "ATTACH DATABASE ? AS plaintext KEY ''", (str(dest_path),)
        )
        self._conn.execute("SELECT sqlcipher_export('plaintext')")
        self._conn.execute("DETACH DATABASE plaintext")

    def change_passphrase(self, new_passphrase: str) -> None:
        """Re-key an encrypted library in place (SQLCipher PRAGMA rekey)."""
        if not self.is_encrypted:
            raise ValueError(
                "This library is not encrypted; use encrypt_library() first."
            )
        from wordvault.storage.encryption import apply_key

        apply_key(self._conn, new_passphrase, pragma="rekey")
        self._conn.commit()

    # -- version chains (DESIGN.md sec. 6, Phase C) -------------------------

    def set_parent_document(self, doc_id: int, parent_id: Optional[int]) -> None:
        """
        Link `doc_id` as a later version of `parent_id` (or unlink with None).

        Guards against cycles: a document cannot become a version of its own
        descendant.  Chain links are metadata, not history — changing them
        never touches any revision.
        """
        self.get_document(doc_id)  # existence check
        if parent_id is not None:
            if parent_id == doc_id:
                raise ValueError("A document cannot be its own parent")
            # Walk the proposed parent's ancestry; doc_id must not be in it.
            if doc_id in self._ancestor_ids(parent_id) :
                raise ValueError("Linking would create a version-chain cycle")
            self.get_document(parent_id)  # existence check
        self._conn.execute(
            "UPDATE documents SET parent_doc_id = ? WHERE id = ?",
            (parent_id, doc_id),
        )
        self._conn.commit()

    def link_version_chain(self, doc_ids: list[int]) -> None:
        """
        Link documents as successive versions: doc_ids[0] is the oldest
        draft, each later entry becomes a child of the one before it.
        This is what the review screen's Confirm button calls.
        """
        if len(doc_ids) < 2:
            raise ValueError("A version chain needs at least two documents")
        if len(set(doc_ids)) != len(doc_ids):
            raise ValueError("Duplicate document in version chain")
        for earlier, later in zip(doc_ids, doc_ids[1:]):
            self.set_parent_document(later, earlier)

    def version_chain(self, doc_id: int) -> list[Document]:
        """
        The whole chain this document belongs to, oldest first: walk up to
        the root draft, then collect descendants in chronological order.
        A document with no links returns a one-element list (itself).
        """
        # Up to the root (cycle-safe even against bad data).
        doc = self.get_document(doc_id)
        seen = {doc.id}
        while doc.parent_doc_id is not None and doc.parent_doc_id not in seen:
            doc = self.get_document(doc.parent_doc_id)
            seen.add(doc.id)

        # Down through descendants, breadth-first, oldest children first.
        chain: list[Document] = []
        queue = [doc]
        while queue:
            current = queue.pop(0)
            chain.append(current)
            rows = self._conn.execute(
                "SELECT * FROM documents WHERE parent_doc_id = ? "
                "ORDER BY created_utc, id",
                (current.id,),
            ).fetchall()
            queue.extend(self._doc_from_row(r) for r in rows)
        return chain

    def _ancestor_ids(self, doc_id: int) -> set[int]:
        """All ids on the parent path above a document (cycle-safe)."""
        ancestors: set[int] = set()
        current = self.get_document(doc_id)
        while current.parent_doc_id is not None:
            if current.parent_doc_id in ancestors:
                break  # existing bad data; do not loop forever
            ancestors.add(current.parent_doc_id)
            current = self.get_document(current.parent_doc_id)
        return ancestors

    # -- ingest support: duplicates & similarity groups (DESIGN.md sec. 6) --

    def record_ingest_duplicate(
        self, doc_id: int, path: str, mtime: Optional[str] = None
    ) -> None:
        """Note that a file's text was identical to an existing document."""
        self._conn.execute(
            "INSERT INTO ingest_duplicates (doc_id, path, mtime) VALUES (?, ?, ?)",
            (doc_id, path, mtime),
        )
        self._conn.commit()

    def all_ingest_duplicate_paths(self) -> list[str]:
        """Every file path ever noted as an exact duplicate — lets a re-run
        of the ingest skip these files without re-reading them."""
        rows = self._conn.execute(
            "SELECT path FROM ingest_duplicates ORDER BY id"
        ).fetchall()
        return [r["path"] for r in rows]

    def ingest_duplicates_for(self, doc_id: int) -> list[str]:
        """Paths of files whose text duplicated this document."""
        rows = self._conn.execute(
            "SELECT path FROM ingest_duplicates WHERE doc_id = ? ORDER BY id",
            (doc_id,),
        ).fetchall()
        return [r["path"] for r in rows]

    def ingested_documents(self) -> list[Document]:
        """Documents that came from files (original_path set), oldest first —
        the population the version-detector fingerprints."""
        rows = self._conn.execute(
            "SELECT * FROM documents WHERE original_path IS NOT NULL "
            "ORDER BY created_utc, id"
        ).fetchall()
        return [self._doc_from_row(r) for r in rows]

    def create_similarity_group(self, members: list[tuple[int, float]]) -> int:
        """Store one proposed version group: [(doc_id, score), ...].
        Returns the new group id (status starts as 'pending')."""
        cur = self._conn.execute("INSERT INTO similarity_groups DEFAULT VALUES")
        group_id = cur.lastrowid
        self._conn.executemany(
            "INSERT INTO similarity_members (group_id, doc_id, score) "
            "VALUES (?, ?, ?)",
            [(group_id, doc_id, score) for doc_id, score in members],
        )
        self._conn.commit()
        return group_id

    def list_similarity_groups(self, status: str = "pending") -> list[int]:
        """Ids of all groups with the given review status."""
        rows = self._conn.execute(
            "SELECT id FROM similarity_groups WHERE status = ? ORDER BY id",
            (status,),
        ).fetchall()
        return [r["id"] for r in rows]

    def group_members(self, group_id: int) -> list[tuple[Document, float]]:
        """A group's documents with their similarity scores, oldest first —
        the proposed draft order (Phase B orders by file date)."""
        rows = self._conn.execute(
            "SELECT d.*, m.score AS score FROM similarity_members m "
            "JOIN documents d ON d.id = m.doc_id "
            "WHERE m.group_id = ? ORDER BY d.created_utc, d.id",
            (group_id,),
        ).fetchall()
        out = []
        for r in rows:
            data = dict(r)
            score = data.pop("score")
            out.append((Document(**data), score))
        return out

    def set_group_status(self, group_id: int, status: str) -> None:
        """Review decision: 'confirmed' or 'rejected' (or back to 'pending')."""
        if status not in ("pending", "confirmed", "rejected"):
            raise ValueError(f"Invalid group status: {status}")
        self._conn.execute(
            "UPDATE similarity_groups SET status = ? WHERE id = ?",
            (status, group_id),
        )
        self._conn.commit()

    def clear_pending_similarity_groups(self) -> None:
        """Drop all still-pending proposals (a re-run of the detector will
        regenerate them).  Confirmed/rejected decisions are kept."""
        self._conn.execute(
            "DELETE FROM similarity_members WHERE group_id IN "
            "(SELECT id FROM similarity_groups WHERE status = 'pending')"
        )
        self._conn.execute(
            "DELETE FROM similarity_groups WHERE status = 'pending'"
        )
        self._conn.commit()

    # -- gather tray (DESIGN.md section 8: mark and gather) ------------------

    def add_gather_item(
        self, doc_id: int, rev_id: int, text: str, start_off: int, end_off: int
    ) -> GatherItem:
        """Mark a passage: snapshot it into the persistent gather tray."""
        cur = self._conn.execute(
            "INSERT INTO gather_tray (doc_id, rev_id, start_off, end_off, text, added_utc) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (doc_id, rev_id, start_off, end_off, text, _utc_now()),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT * FROM gather_tray WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return GatherItem(**dict(row))

    def list_gather_items(self) -> list[GatherItem]:
        """Everything in the tray, in the order it was marked."""
        rows = self._conn.execute(
            "SELECT * FROM gather_tray ORDER BY id"
        ).fetchall()
        return [GatherItem(**dict(r)) for r in rows]

    def remove_gather_item(self, item_id: int) -> None:
        self._conn.execute("DELETE FROM gather_tray WHERE id = ?", (item_id,))
        self._conn.commit()

    def gather_into_document(self, title: str) -> Document:
        """
        The Gather step: create a NEW document from every passage in the
        tray (in marking order, separated by blank lines), write one
        `sources` provenance row per passage, and empty the tray.
        """
        items = self.list_gather_items()
        if not items:
            raise ValueError("The gather tray is empty — mark passages first")

        doc = self.create_document(title)
        combined = "\n\n".join(item.text.strip("\n") for item in items) + "\n"
        rev = self.save_revision(doc.id, combined, origin="pull")

        # Provenance: each gathered passage remembers exactly where it
        # came from (document, revision, and character offsets).
        for item in items:
            self.record_source(
                rev.id, item.doc_id, item.rev_id,
                excerpt_start=item.start_off, excerpt_end=item.end_off,
            )
        self._conn.execute("DELETE FROM gather_tray")
        self._conn.commit()
        return doc

    # -- search (current text only; history search arrives in stage 6) ------

    def search_current(self, query: str) -> list[tuple[Document, str]]:
        """
        Full-text search over every document's CURRENT text.

        Returns (document, snippet) pairs, best match first.  The snippet
        marks matched terms with [brackets].  Requires FTS5; raises
        RuntimeError with a clear message if this build lacks it.
        """
        if not self.fts_available:
            raise RuntimeError(
                "This SQLite build lacks the FTS5 extension; "
                "library-wide search is unavailable."
            )
        rows = self._conn.execute(
            "SELECT rowid, snippet(doc_text, 1, '[', ']', '…', 12) AS snip "
            "FROM doc_text WHERE doc_text MATCH ? ORDER BY rank",
            (query,),
        ).fetchall()
        return [(self.get_document(r["rowid"]), r["snip"]) for r in rows]

    # -- internal helpers ---------------------------------------------------

    @staticmethod
    def _doc_from_row(row: sqlite3.Row) -> Document:
        return Document(**dict(row))

    def _payload_row(self, rev_id: int) -> sqlite3.Row:
        """Fetch a revision row including its payload (internal only —
        payloads never leave the storage layer raw)."""
        row = self._conn.execute(
            "SELECT id, kind, payload, parent_rev_id FROM revisions WHERE id = ?",
            (rev_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"No revision with id {rev_id}")
        return row

    def _chain_length(self, rev_id: int) -> int:
        """How many diffs must be replayed to rebuild `rev_id`
        (0 if it is itself a snapshot).  Bounded by snapshot_interval."""
        count = 0
        row = self._payload_row(rev_id)
        while row["kind"] != "snapshot":
            count += 1
            row = self._payload_row(row["parent_rev_id"])
        return count

    def _refresh_fts(self, doc_id: int, current_text: Optional[str] = None) -> None:
        """
        Re-index one document's current text in doc_text (rowid == doc id).
        FTS5 has no UPDATE for external content, so: delete then insert.
        No-op when FTS5 is unavailable.
        """
        if not self.fts_available:
            return
        if current_text is None:
            current_text = self.current_text(doc_id)
        title = self.get_document(doc_id).title
        self._conn.execute("DELETE FROM doc_text WHERE rowid = ?", (doc_id,))
        self._conn.execute(
            "INSERT INTO doc_text (rowid, title, body) VALUES (?, ?, ?)",
            (doc_id, title, current_text),
        )
