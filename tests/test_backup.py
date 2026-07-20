"""
Tests for the encrypted envelope, .wvbackup, and .wvdoc (stage 8).

Skipped automatically when the 'cryptography' package is missing —
everything else in WordVault runs without it.
"""

import pytest

pytest.importorskip("cryptography")

from wordvault import DocumentStore  # noqa: E402
from wordvault.storage.backup import (  # noqa: E402
    export_document,
    import_document,
    make_backup,
    read_backup,
    restore_backup,
)
from wordvault.storage.crypto import decrypt_bytes, encrypt_bytes  # noqa: E402

PW = "correct horse battery staple"


# -- the envelope ------------------------------------------------------------

def test_envelope_roundtrip():
    payload = "Ἐν ἀρχῇ ἦν ὁ λόγος — some unicode text\n".encode() * 100
    blob = encrypt_bytes(payload, PW)
    assert blob != payload
    assert decrypt_bytes(blob, PW) == payload


def test_wrong_passphrase_fails_clearly():
    blob = encrypt_bytes(b"secret", PW)
    with pytest.raises(ValueError, match="wrong passphrase"):
        decrypt_bytes(blob, "not the passphrase")


def test_tampering_is_detected():
    blob = bytearray(encrypt_bytes(b"secret", PW))
    blob[-1] ^= 0xFF   # flip one bit of the ciphertext
    with pytest.raises(ValueError):
        decrypt_bytes(bytes(blob), PW)


def test_not_an_envelope():
    with pytest.raises(ValueError, match="Not a WordVault"):
        decrypt_bytes(b"just some random file content", PW)


# -- .wvbackup ---------------------------------------------------------------

@pytest.fixture()
def populated_library(tmp_path):
    db = tmp_path / "library.db"
    store = DocumentStore(db)
    doc = store.create_document("Essay")
    store.save_revision(doc.id, "first\n")
    store.save_revision(doc.id, "first\nsecond\n")
    other = store.create_document("Notes")
    store.save_revision(other.id, "some notes\n")
    yield store, db, doc
    store.close()


def test_backup_and_restore(populated_library, tmp_path):
    store, db, doc = populated_library
    backup_file = tmp_path / "lib.wvbackup"

    info = make_backup(store, backup_file, PW)
    assert info.documents == 2 and info.revisions == 3

    # The header is readable (after decryption) without restoring.
    info2, db_bytes = read_backup(backup_file, PW)
    assert info2.documents == 2
    assert db_bytes[:16] == b"SQLite format 3\x00"

    # Restore to a NEW location and verify the library is complete.
    restored_db = tmp_path / "restored.db"
    restore_backup(backup_file, PW, restored_db)
    with DocumentStore(restored_db) as restored:
        assert len(restored.list_documents()) == 2
        rdoc = restored.get_document_by_uuid(doc.uuid)
        assert restored.current_text(rdoc.id) == "first\nsecond\n"


def test_restore_keeps_previous_file(populated_library, tmp_path):
    store, db, doc = populated_library
    backup_file = tmp_path / "lib.wvbackup"
    make_backup(store, backup_file, PW)

    target = tmp_path / "target.db"
    target.write_bytes(b"precious old data")
    restore_backup(backup_file, PW, target)

    safety = tmp_path / "target.db.before-restore"
    assert safety.read_bytes() == b"precious old data"   # nothing lost


# -- .wvdoc ------------------------------------------------------------------

def test_export_import_into_fresh_library(populated_library, tmp_path):
    store, db, doc = populated_library
    wvdoc = tmp_path / "essay.wvdoc"
    assert export_document(store, doc.id, wvdoc, PW) == 2

    with DocumentStore(tmp_path / "other.db") as other:
        imported, added = import_document(other, wvdoc, PW)
        assert added == 2
        assert imported.uuid == doc.uuid          # identity preserved
        assert imported.title == "Essay"
        assert other.current_text(imported.id) == "first\nsecond\n"
        # Full history came across, timestamps intact.
        revs = other.list_revisions(imported.id)
        assert len(revs) == 2
        assert revs[0].created_utc == store.list_revisions(doc.id)[0].created_utc


def test_import_merges_by_uuid_appending_only_newer(populated_library, tmp_path):
    store, db, doc = populated_library
    wvdoc = tmp_path / "essay.wvdoc"

    # Export, then the library moves on with a third revision.
    export_document(store, doc.id, wvdoc, PW)
    store.save_revision(doc.id, "first\nsecond\nthird\n")

    # Importing the OLDER file back must add nothing and change nothing.
    imported, added = import_document(store, wvdoc, PW)
    assert imported.id == doc.id
    assert added == 0
    assert store.current_text(doc.id) == "first\nsecond\nthird\n"
    assert len(store.list_revisions(doc.id)) == 3


def test_import_newer_wvdoc_appends(populated_library, tmp_path):
    store, db, doc = populated_library
    # Simulate the traveling laptop: a copy of the library gains a revision.
    backup_file = tmp_path / "lib.wvbackup"
    make_backup(store, backup_file, PW)
    away_db = tmp_path / "laptop.db"
    restore_backup(backup_file, PW, away_db)
    with DocumentStore(away_db) as away:
        away_doc = away.get_document_by_uuid(doc.uuid)
        away.save_revision(away_doc.id, "first\nsecond\nwritten away from home\n")
        wvdoc = tmp_path / "travel.wvdoc"
        export_document(away, away_doc.id, wvdoc, PW)

    # Back home: importing appends just the new revision.
    imported, added = import_document(store, wvdoc, PW)
    assert added == 1
    assert store.current_text(doc.id).endswith("written away from home\n")
    assert len(store.list_revisions(doc.id)) == 3


def test_wvdoc_is_not_a_backup(populated_library, tmp_path):
    store, db, doc = populated_library
    wvdoc = tmp_path / "essay.wvdoc"
    export_document(store, doc.id, wvdoc, PW)
    with pytest.raises(ValueError, match="not a"):
        read_backup(wvdoc, PW)
