"""
Tests for stage 9: SQLCipher encryption of the live database.

Skipped automatically when the sqlcipher3 package is missing — plain
(unencrypted) libraries never need it.
"""

import pytest

sqlcipher3 = pytest.importorskip("sqlcipher3")

from wordvault import DocumentStore  # noqa: E402
from wordvault.storage.encryption import (  # noqa: E402
    decrypt_library,
    encrypt_library,
    is_encrypted_database,
)

PW = "a passphrase with 'quotes' in it"


@pytest.fixture()
def plain_library(tmp_path):
    """A small plaintext library on disk."""
    db = tmp_path / "plain.db"
    with DocumentStore(db) as store:
        doc = store.create_document("Essay")
        store.save_revision(doc.id, "the text survives encryption\n")
        uuid = doc.uuid
    return db, uuid


def test_encrypt_then_open_with_passphrase(plain_library, tmp_path):
    db, uuid = plain_library
    enc = tmp_path / "enc.db"
    encrypt_library(db, enc, PW)

    assert is_encrypted_database(enc)          # header is no longer SQLite's
    assert not is_encrypted_database(db)

    with DocumentStore(enc, passphrase=PW) as store:
        assert store.is_encrypted
        doc = store.get_document_by_uuid(uuid)
        assert store.current_text(doc.id) == "the text survives encryption\n"
        # Normal work continues under encryption.
        store.save_revision(doc.id, "and grows\n")

    with DocumentStore(enc, passphrase=PW) as store:
        doc = store.get_document_by_uuid(uuid)
        assert store.current_text(doc.id) == "and grows\n"


def test_wrong_passphrase_and_missing_passphrase(plain_library, tmp_path):
    db, _uuid = plain_library
    enc = tmp_path / "enc.db"
    encrypt_library(db, enc, PW)

    with pytest.raises(ValueError, match="Wrong passphrase"):
        DocumentStore(enc, passphrase="not it")
    with pytest.raises(ValueError, match="encrypted"):
        DocumentStore(enc)                      # no passphrase at all


def test_decrypt_round_trip(plain_library, tmp_path):
    db, uuid = plain_library
    enc = tmp_path / "enc.db"
    back = tmp_path / "back.db"
    encrypt_library(db, enc, PW)
    decrypt_library(enc, back, PW)

    assert not is_encrypted_database(back)
    with DocumentStore(back) as store:
        doc = store.get_document_by_uuid(uuid)
        assert store.current_text(doc.id) == "the text survives encryption\n"

    with pytest.raises(ValueError):
        decrypt_library(enc, tmp_path / "x.db", "wrong")


def test_change_passphrase(plain_library, tmp_path):
    db, uuid = plain_library
    enc = tmp_path / "enc.db"
    encrypt_library(db, enc, PW)

    with DocumentStore(enc, passphrase=PW) as store:
        store.change_passphrase("new passphrase")

    with pytest.raises(ValueError):
        DocumentStore(enc, passphrase=PW)       # old one no longer works
    with DocumentStore(enc, passphrase="new passphrase") as store:
        assert len(store.list_documents()) == 1


def test_backup_from_encrypted_store_restores_anywhere(plain_library, tmp_path):
    """Backups stay universal: made from an encrypted library, restorable
    into a plain one (the .wvbackup envelope is the protection)."""
    cryptography = pytest.importorskip("cryptography")  # noqa: F841
    from wordvault.storage.backup import make_backup, restore_backup

    db, uuid = plain_library
    enc = tmp_path / "enc.db"
    encrypt_library(db, enc, PW)

    backup_file = tmp_path / "lib.wvbackup"
    with DocumentStore(enc, passphrase=PW) as store:
        info = make_backup(store, backup_file, "backup-pw")
        assert info.documents == 1

    # Restore as PLAIN (no library passphrase).
    plain_out = tmp_path / "restored-plain.db"
    restore_backup(backup_file, "backup-pw", plain_out)
    assert not is_encrypted_database(plain_out)
    with DocumentStore(plain_out) as store:
        assert store.get_document_by_uuid(uuid) is not None

    # Restore RE-ENCRYPTED (library passphrase given).
    enc_out = tmp_path / "restored-enc.db"
    restore_backup(backup_file, "backup-pw", enc_out, library_passphrase=PW)
    assert is_encrypted_database(enc_out)
    with DocumentStore(enc_out, passphrase=PW) as store:
        assert store.get_document_by_uuid(uuid) is not None
