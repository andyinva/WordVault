"""
schema.py — database schema creation and versioning.

All CREATE TABLE statements for a WordVault library database live here,
mirroring DESIGN.md section 4.  The schema is created idempotently
(IF NOT EXISTS) every time a store opens, so opening a brand-new file and
opening an existing library are the same code path.

Schema versioning uses SQLite's built-in `PRAGMA user_version` integer.
When a future stage changes the schema, add a migration step keyed on the
old version number in `create_all()` and bump SCHEMA_VERSION.

FTS5 note: the full-text index (doc_text) needs SQLite compiled with the
FTS5 extension.  Standard python.org builds on Windows and Ubuntu's system
Python both include it, but we degrade gracefully if it is missing —
everything works except instant library-wide search.
"""

from __future__ import annotations

import sqlite3

# Bump this whenever the schema changes; add a migration in create_all().
SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Core tables — see DESIGN.md section 4 for the annotated version.
# ---------------------------------------------------------------------------
_CORE_TABLES = """
-- One row per logical document.  Version chains are linked lists through
-- parent_doc_id (an earlier draft of the same material).
CREATE TABLE IF NOT EXISTS documents (
    id             INTEGER PRIMARY KEY,
    uuid           TEXT NOT NULL UNIQUE,
    title          TEXT NOT NULL,
    created_utc    TEXT NOT NULL,
    parent_doc_id  INTEGER REFERENCES documents(id),
    original_path  TEXT,
    original_mtime TEXT
);

-- Append-only history.  Rows are never updated or deleted.
CREATE TABLE IF NOT EXISTS revisions (
    id            INTEGER PRIMARY KEY,
    doc_id        INTEGER NOT NULL REFERENCES documents(id),
    created_utc   TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('snapshot', 'diff')),
    payload       TEXT NOT NULL,
    parent_rev_id INTEGER REFERENCES revisions(id),
    origin        TEXT NOT NULL DEFAULT 'typing'
);
CREATE INDEX IF NOT EXISTS idx_revisions_doc ON revisions(doc_id);

-- Provenance for material pulled from other documents.
CREATE TABLE IF NOT EXISTS sources (
    id            INTEGER PRIMARY KEY,
    target_rev_id INTEGER NOT NULL REFERENCES revisions(id),
    source_doc_id INTEGER NOT NULL REFERENCES documents(id),
    source_rev_id INTEGER NOT NULL REFERENCES revisions(id),
    excerpt_start INTEGER,
    excerpt_end   INTEGER
);

-- Lightweight organization for the library view (GrandView-style categories).
CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS document_tags (
    doc_id INTEGER NOT NULL REFERENCES documents(id),
    tag_id INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (doc_id, tag_id)
);

-- Distiller working tables (DESIGN.md section 6, Phase B/C): candidate
-- version groups proposed by the ingest tool, awaiting the author's review.
CREATE TABLE IF NOT EXISTS similarity_groups (
    id     INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending'
           CHECK (status IN ('pending', 'confirmed', 'rejected'))
);
CREATE TABLE IF NOT EXISTS similarity_members (
    group_id INTEGER NOT NULL REFERENCES similarity_groups(id),
    doc_id   INTEGER NOT NULL REFERENCES documents(id),
    score    REAL NOT NULL,   -- estimated similarity to the group's oldest member
    PRIMARY KEY (group_id, doc_id)
);

-- Exact-duplicate files found during ingest: the text was identical to an
-- already-ingested document, so only the path is remembered (Phase A).
CREATE TABLE IF NOT EXISTS ingest_duplicates (
    id     INTEGER PRIMARY KEY,
    doc_id INTEGER NOT NULL REFERENCES documents(id),
    path   TEXT NOT NULL,
    mtime  TEXT
);

-- The gather tray (DESIGN.md section 8, "mark and gather"): passages the
-- author marked across documents, queued up to be gathered into a new
-- document.  Persistent on purpose — marking can span many sittings.
-- The text is snapshotted at marking time, so later edits to the source
-- cannot change what was marked.
CREATE TABLE IF NOT EXISTS gather_tray (
    id         INTEGER PRIMARY KEY,
    doc_id     INTEGER NOT NULL REFERENCES documents(id),
    rev_id     INTEGER NOT NULL REFERENCES revisions(id),
    start_off  INTEGER NOT NULL,
    end_off    INTEGER NOT NULL,
    text       TEXT NOT NULL,
    added_utc  TEXT NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Full-text index over each document's CURRENT text (derived data — rebuilt
# whenever a document changes).  rowid is kept equal to documents.id so a
# search hit maps straight back to its document.
# ---------------------------------------------------------------------------
_FTS_TABLE = """
CREATE VIRTUAL TABLE IF NOT EXISTS doc_text USING fts5(title, body);
"""


def create_all(conn: sqlite3.Connection) -> bool:
    """
    Create every table this stage needs (idempotent) and stamp the schema
    version.  Returns True if the FTS5 full-text index is available,
    False if this SQLite build lacks FTS5 (search degrades, nothing breaks).
    """
    # Referential integrity is off by default in SQLite; always turn it on.
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript(_CORE_TABLES)

    # FTS5 may be missing from unusual SQLite builds — try, and remember.
    try:
        conn.executescript(_FTS_TABLE)
        fts_available = True
    except sqlite3.OperationalError:
        fts_available = False

    # Stamp a fresh database; future versions will migrate here.
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current == 0:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    elif current != SCHEMA_VERSION:
        # Placeholder for real migrations in later stages.
        raise RuntimeError(
            f"Database schema version {current} is newer than this "
            f"WordVault ({SCHEMA_VERSION}); please upgrade WordVault."
        )

    conn.commit()
    return fts_available
