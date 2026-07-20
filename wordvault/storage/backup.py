"""
backup.py — one-file encrypted backup/restore and portable .wvdoc files
(roadmap stage 8, DESIGN.md section 10).

Two file types, one encrypted envelope (crypto.py):

  .wvbackup — the WHOLE library.  The store writes a clean copy of the
      database (VACUUM INTO), and the copy is wrapped in the envelope
      together with a small JSON header (creation time, schema version,
      document/revision counts).  The header lets the restore screen show
      what is inside before anything is overwritten.

  .wvdoc — ONE document, portable.  A JSON payload holding the document's
      metadata (including its stable uuid) and its full revision history,
      each revision as plain text with its original timestamp and origin.
      Import merges by uuid: an unknown document is created whole with
      its original timestamps; a known one gets only the revisions newer
      than what the library already has.  Nothing is ever overwritten —
      the append-only rule holds across files too.

Everything here works on paths and stores — no GUI.  The editor's File
menu and the tools/ CLI both call exactly these functions.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from wordvault.models import Document
from wordvault.storage import schema
from wordvault.storage.crypto import decrypt_bytes, encrypt_bytes
from wordvault.storage.store import DocumentStore, _utc_now

_BACKUP_KIND = "wordvault-backup"
_WVDOC_KIND = "wordvault-doc"


@dataclass(frozen=True)
class BackupInfo:
    """What a .wvbackup contains — shown to the author before restoring."""

    created_utc: str
    schema_version: int
    documents: int
    revisions: int


def _split_payload(payload: bytes, expected_kind: str) -> tuple[dict, bytes]:
    """Payload format: one JSON header line + '\\n' + raw body bytes."""
    newline = payload.index(b"\n")
    header = json.loads(payload[:newline].decode("utf-8"))
    if header.get("kind") != expected_kind:
        raise ValueError(
            f"This file is a '{header.get('kind')}', not a '{expected_kind}'."
        )
    return header, payload[newline + 1:]


# ---------------------------------------------------------------- .wvbackup --

def make_backup(
    store: DocumentStore, dest: Union[str, Path], passphrase: str
) -> BackupInfo:
    """Write an encrypted one-file backup of the entire library."""
    dest = Path(dest)
    info = BackupInfo(
        created_utc=_utc_now(),
        schema_version=schema.SCHEMA_VERSION,
        documents=len(store.list_documents()),
        revisions=store.revision_count(),
    )

    # A clean PLAINTEXT database copy (the envelope provides the
    # encryption; stage 9 stores additionally decrypt through SQLCipher).
    tmp = dest.with_suffix(dest.suffix + ".tmp-db")
    if tmp.exists():
        tmp.unlink()
    try:
        store.export_plaintext_copy(tmp)
        db_bytes = tmp.read_bytes()
    finally:
        if tmp.exists():
            tmp.unlink()

    header = {
        "kind": _BACKUP_KIND,
        "format_version": 1,
        "created_utc": info.created_utc,
        "schema_version": info.schema_version,
        "documents": info.documents,
        "revisions": info.revisions,
    }
    payload = json.dumps(header).encode("utf-8") + b"\n" + db_bytes
    dest.write_bytes(encrypt_bytes(payload, passphrase))
    return info


def read_backup(
    path: Union[str, Path], passphrase: str
) -> tuple[BackupInfo, bytes]:
    """Decrypt a backup; return its header info and the raw database bytes.
    Decryption itself verifies integrity (GCM) — if this returns, the
    backup is intact."""
    payload = decrypt_bytes(Path(path).read_bytes(), passphrase)
    header, db_bytes = _split_payload(payload, _BACKUP_KIND)
    info = BackupInfo(
        created_utc=header["created_utc"],
        schema_version=header["schema_version"],
        documents=header["documents"],
        revisions=header["revisions"],
    )
    return info, db_bytes


def restore_backup(
    path: Union[str, Path],
    passphrase: str,
    dest_db: Union[str, Path],
    library_passphrase: Optional[str] = None,
) -> BackupInfo:
    """
    Restore a backup to `dest_db`.  The destination must NOT be open in a
    running store (the editor closes its store first).  The old file, if
    any, is kept beside the new one as '<name>.before-restore' until the
    author deletes it — a restore should never be the thing that loses data.

    library_passphrase — when the library on disk is SQLCipher-encrypted
    (stage 9), pass its passphrase and the restored database is encrypted
    the same way before being swapped in.
    """
    info, db_bytes = read_backup(path, passphrase)
    dest_db = Path(dest_db)

    if library_passphrase is not None:
        # Backup payloads are plaintext; re-encrypt for the live library.
        from wordvault.storage.encryption import encrypt_library

        tmp_plain = dest_db.with_name(dest_db.name + ".tmp-plain")
        tmp_enc = dest_db.with_name(dest_db.name + ".tmp-enc")
        try:
            tmp_plain.write_bytes(db_bytes)
            encrypt_library(tmp_plain, tmp_enc, library_passphrase)
            new_file = tmp_enc
            new_bytes = None
        finally:
            if tmp_plain.exists():
                tmp_plain.unlink()
    else:
        new_file = None
        new_bytes = db_bytes

    if dest_db.exists():
        safety = dest_db.with_name(dest_db.name + ".before-restore")
        if safety.exists():
            safety.unlink()
        os.replace(dest_db, safety)

    if new_file is not None:
        os.replace(new_file, dest_db)
    else:
        dest_db.write_bytes(new_bytes)
    return info


# ------------------------------------------------------------------- .wvdoc --

def export_document(
    store: DocumentStore, doc_id: int, dest: Union[str, Path], passphrase: str
) -> int:
    """
    Write one document (with full history) to an encrypted .wvdoc file.
    Returns the number of revisions exported.

    Revisions are exported as full plain texts (not internal diffs), so a
    .wvdoc is self-contained and future-proof: any WordVault can rebuild
    the chain with its own snapshot/diff policy on import.
    """
    doc = store.get_document(doc_id)
    revisions = [
        {
            "created_utc": rev.created_utc,
            "origin": rev.origin,
            "text": store.get_text(rev.id),
        }
        for rev in store.list_revisions(doc_id)
    ]
    header = {
        "kind": _WVDOC_KIND,
        "format_version": 1,
        "exported_utc": _utc_now(),
        "document": {
            "uuid": doc.uuid,
            "title": doc.title,
            "created_utc": doc.created_utc,
            "original_path": doc.original_path,
            "original_mtime": doc.original_mtime,
        },
        "revisions": revisions,
    }
    payload = json.dumps(header, ensure_ascii=False).encode("utf-8") + b"\n"
    Path(dest).write_bytes(encrypt_bytes(payload, passphrase))
    return len(revisions)


def import_document(
    store: DocumentStore, src: Union[str, Path], passphrase: str
) -> tuple[Document, int]:
    """
    Load a .wvdoc into the library, merging by uuid.

    Unknown uuid  -> the document is created whole, original timestamps
                     and title preserved.
    Known uuid    -> only revisions NEWER than the library's latest
                     revision of that document are appended (in order).
                     Existing history is never touched.

    Returns (document, revisions_added).
    """
    payload = decrypt_bytes(Path(src).read_bytes(), passphrase)
    header, _body = _split_payload(payload, _WVDOC_KIND)
    meta = header["document"]

    doc = store.get_document_by_uuid(meta["uuid"])
    if doc is None:
        doc = store.create_document(
            title=meta["title"],
            created_utc=meta["created_utc"],
            doc_uuid=meta["uuid"],
            original_path=meta.get("original_path"),
            original_mtime=meta.get("original_mtime"),
        )
        newer_than = ""  # replay everything
    else:
        latest = store.latest_revision(doc.id)
        newer_than = latest.created_utc if latest else ""

    added = 0
    for rev in header["revisions"]:
        if rev["created_utc"] <= newer_than:
            continue  # the library already has this part of the history
        saved = store.save_revision(
            doc.id, rev["text"],
            origin=rev["origin"], created_utc=rev["created_utc"],
        )
        if saved is not None:  # identical consecutive states are skipped
            added += 1
    return doc, added
