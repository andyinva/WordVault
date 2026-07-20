"""
crypto.py — the encrypted envelope shared by .wvbackup and .wvdoc files
(DESIGN.md section 10).

One format for everything WordVault encrypts:

    bytes 0-6   magic  b"WVENC1\\n"   (identifies the file, carries version)
    bytes 7-22  salt   16 random bytes for the key derivation
    bytes 23-34 nonce  12 random bytes for AES-GCM
    bytes 35-   ciphertext + GCM tag

Pipeline: payload -> zlib compress -> AES-256-GCM encrypt with a key
derived from the passphrase via scrypt.  GCM gives tamper detection for
free — a corrupted or altered file fails loudly at decrypt time with a
clear error, never silently.

Requires the `cryptography` package (pip install cryptography).  The
import is deferred so the rest of WordVault runs without it; only
actually encrypting/decrypting needs it.
"""

from __future__ import annotations

import os
import zlib

_MAGIC = b"WVENC1\n"
_SALT_LEN = 16
_NONCE_LEN = 12

# scrypt parameters: interactive-use strength (~100 ms), standard choices.
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_LEN = 32  # AES-256


def _require_cryptography():
    """Import the cryptography primitives, with a helpful error if absent."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "Encrypted files need the 'cryptography' package. "
            "Install it with:  pip install cryptography"
        ) from exc
    return AESGCM, Scrypt


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Passphrase -> 32-byte AES key via scrypt (memory-hard, slow for
    attackers guessing passphrases, fast enough for interactive use)."""
    _AESGCM, Scrypt = _require_cryptography()
    kdf = Scrypt(salt=salt, length=_KEY_LEN,
                 n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_bytes(payload: bytes, passphrase: str) -> bytes:
    """Compress and encrypt a payload into the envelope format."""
    AESGCM, _Scrypt = _require_cryptography()
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    key = _derive_key(passphrase, salt)
    ciphertext = AESGCM(key).encrypt(nonce, zlib.compress(payload, 6), None)
    return _MAGIC + salt + nonce + ciphertext


def decrypt_bytes(blob: bytes, passphrase: str) -> bytes:
    """
    Reverse encrypt_bytes().  Raises ValueError with a plain-language
    message when the file is not a WordVault envelope, the passphrase is
    wrong, or the content was tampered with (GCM authentication failure —
    indistinguishable from a wrong passphrase by design).
    """
    if not blob.startswith(_MAGIC):
        raise ValueError("Not a WordVault encrypted file (bad header).")
    body = blob[len(_MAGIC):]
    if len(body) < _SALT_LEN + _NONCE_LEN + 16:
        raise ValueError("File is truncated or corrupted.")
    salt = body[:_SALT_LEN]
    nonce = body[_SALT_LEN:_SALT_LEN + _NONCE_LEN]
    ciphertext = body[_SALT_LEN + _NONCE_LEN:]

    AESGCM, _Scrypt = _require_cryptography()
    key = _derive_key(passphrase, salt)
    try:
        compressed = AESGCM(key).decrypt(nonce, ciphertext, None)
    except Exception:
        raise ValueError(
            "Could not decrypt: wrong passphrase, or the file was "
            "corrupted or tampered with."
        ) from None
    return zlib.decompress(compressed)
