"""
encryption.py — SQLCipher support for the LIVE database (roadmap stage 9).

Stage 8 encrypted the backups; this stage encrypts the library file
itself, so the database on disk is unreadable without the passphrase
(DESIGN.md section 9).

SQLCipher is a drop-in encrypted build of SQLite.  Its Python binding
(`sqlcipher3`) mirrors the standard `sqlite3` module, so DocumentStore
uses either one through the same code — the only differences are the
connect call and the key PRAGMA, both handled here and in store.__init__.

Install:  pip install sqlcipher3-wheels     (Windows, macOS, Linux)
     or:  pip install sqlcipher3-binary     (Linux/macOS wheels)

Everything degrades gracefully: without the package, plain (unencrypted)
libraries work exactly as before; only opening/creating an ENCRYPTED
library needs it, and the error says what to install.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Union

#: Every plain SQLite file starts with these 16 bytes.  An encrypted
#: SQLCipher file starts with random-looking salt instead — which is how
#: we tell the two apart without any passphrase.
_SQLITE_HEADER = b"SQLite format 3\x00"


def sqlcipher_module():
    """Import and return sqlcipher3, with a helpful error if missing."""
    try:
        import sqlcipher3
        return sqlcipher3
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "Encrypted libraries need the 'sqlcipher3' package. Install it "
            "with:  pip install sqlcipher3-wheels   (or sqlcipher3-binary "
            "on Linux)"
        ) from exc


def is_encrypted_database(path: Union[str, Path]) -> bool:
    """True if the file exists and is NOT a plain SQLite database."""
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return False
    with open(p, "rb") as fh:
        return fh.read(16) != _SQLITE_HEADER


def apply_key(conn, passphrase: str, pragma: str = "key") -> None:
    """Issue PRAGMA key/rekey.  PRAGMAs cannot take bound parameters, so
    the passphrase is single-quote escaped by hand."""
    escaped = passphrase.replace("'", "''")
    conn.execute(f"PRAGMA {pragma} = '{escaped}'")


def encrypt_library(
    src: Union[str, Path], dest: Union[str, Path], passphrase: str
) -> None:
    """Write an ENCRYPTED copy of a plaintext library to `dest`
    (SQLCipher's sqlcipher_export — the official migration route)."""
    mod = sqlcipher_module()
    dest = Path(dest)
    if dest.exists():
        dest.unlink()
    conn = mod.connect(str(src))  # no key: reads the plaintext database
    try:
        conn.execute(
            "ATTACH DATABASE ? AS encrypted KEY ?", (str(dest), passphrase)
        )
        conn.execute("SELECT sqlcipher_export('encrypted')")
        conn.execute("DETACH DATABASE encrypted")
    finally:
        conn.close()


def decrypt_library(
    src: Union[str, Path], dest: Union[str, Path], passphrase: str
) -> None:
    """Write a PLAINTEXT copy of an encrypted library to `dest`.
    Raises ValueError on a wrong passphrase."""
    mod = sqlcipher_module()
    dest = Path(dest)
    if dest.exists():
        dest.unlink()
    conn = mod.connect(str(src))
    try:
        apply_key(conn, passphrase)
        try:
            conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        except mod.DatabaseError:
            raise ValueError(
                "Wrong passphrase (or the file is not a WordVault library)."
            ) from None
        conn.execute("ATTACH DATABASE ? AS plaintext KEY ''", (str(dest),))
        conn.execute("SELECT sqlcipher_export('plaintext')")
        conn.execute("DETACH DATABASE plaintext")
    finally:
        conn.close()


def swap_in(new_file: Union[str, Path], target: Union[str, Path],
            safety_suffix: str) -> None:
    """Atomically put `new_file` in place of `target`, keeping the old
    target beside it (target name + safety_suffix) until the author
    deletes it — the same never-lose-data pattern as backup restore."""
    new_file, target = Path(new_file), Path(target)
    if target.exists():
        safety = target.with_name(target.name + safety_suffix)
        if safety.exists():
            safety.unlink()
        os.replace(target, safety)
    os.replace(new_file, target)
