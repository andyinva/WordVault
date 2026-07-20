"""
models.py — plain data classes shared across WordVault.

These classes carry data between the storage layer and everything else
(the future editor, ingest tools, tests).  They hold no behavior and no
database code on purpose: all persistence lives in wordvault.storage.

Design notes (see DESIGN.md section 4):
  * A Document row is a logical document.  Version chains — documents that
    are earlier/later drafts of the same material — are linked lists through
    `parent_doc_id`.
  * A Revision is one captured state of a document's text.  Revisions are
    append-only: they are never updated or deleted.  The revision's text
    payload is deliberately NOT carried on this class; text can be large,
    so it is fetched on demand through DocumentStore.get_text().
  * A SourceLink records provenance: "this revision pulled text from that
    document/revision", including character offsets when known.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Document:
    """One logical document in the library."""

    id: int                       # database primary key
    uuid: str                     # stable identity across export/import/merge
    title: str
    created_utc: str              # ISO-8601 timestamp, always UTC
    parent_doc_id: Optional[int]  # earlier version of the same material, or None
    original_path: Optional[str]  # source .docx path if this came from ingest
    original_mtime: Optional[str] # source file date, used for chronological order


@dataclass(frozen=True)
class Revision:
    """
    One captured state of a document's text.

    kind    'snapshot' — payload held the full text
            'diff'     — payload held a delta against parent_rev_id
    origin  what produced this revision:
            'typing' | 'ingest' | 'replace' | 'pull' | 'restore'
    """

    id: int
    doc_id: int
    created_utc: str
    kind: str
    origin: str
    parent_rev_id: Optional[int]  # previous revision, or None for the first


@dataclass(frozen=True)
class SourceLink:
    """Provenance: target revision pulled text from a source document/revision."""

    id: int
    target_rev_id: int            # the revision that received the pulled text
    source_doc_id: int            # where the text came from
    source_rev_id: int            # exact source revision
    excerpt_start: Optional[int]  # character offsets in the source revision's
    excerpt_end: Optional[int]    # text, when known (None = whole document)


@dataclass(frozen=True)
class Tag:
    """A library-organization tag (topic, series, status, ...)."""

    id: int
    name: str


@dataclass(frozen=True)
class GatherItem:
    """One marked passage waiting in the gather tray (mark-and-gather)."""

    id: int
    doc_id: int
    rev_id: int          # revision the passage was marked in
    start_off: int       # character offsets within that revision's text
    end_off: int
    text: str            # the passage itself, snapshotted at marking time
    added_utc: str
