"""Encryption for the secrets Calivi stores in its database: MCP tokens and provider API keys.

These are **bearer credentials for other people's systems** — a GitHub PAT, a Context7 key, an
OpenAI key. They used to sit in `calivi.db` in the clear, which meant a copy of the database
(the nightly backup, a stolen volume, an accidental `sqlite3` dump in a paste) handed them over
directly. The threat model is exactly that: an attacker holding the database file *without* the
environment the app runs in. It is not protection against someone who already has the running
container, and it is not meant to be — such an attacker can simply read the decrypted value.

**Applied as a column type, not at the call sites.** `EncryptedString` goes through every read
and write of the column, so a new endpoint or a script that touches the value cannot forget to
encrypt it. There is no "encrypt here, decrypt there" to keep in sync.
"""
import base64
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app import config

log = logging.getLogger(__name__)

# Domain separation. SECRET_KEY already signs session JWTs; deriving a distinct key with its
# own `info` means the two uses never share key material. This string is part of the storage
# format — changing it makes every stored secret undecryptable. It is not a tunable.
_INFO = b"calivi column encryption v1"

# Every Fernet token starts with version byte 0x80, which is "gAAAAA" once base64-encoded.
# Used only to tell "this was never encrypted" from "this will not decrypt", which are two
# very different situations (see process_result_value).
_TOKEN_PREFIX = "gAAAAA"

_cipher: MultiFernet | None = None


def _fernet(key_material: str) -> Fernet:
    raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(
        key_material.encode("utf-8")
    )
    return Fernet(base64.urlsafe_b64encode(raw))


def cipher() -> MultiFernet:
    """Current key first: MultiFernet encrypts with the first and decrypts with any of them."""
    global _cipher
    if _cipher is None:
        keys = [_fernet(config.SECRET_KEY)]
        if config.SECRET_KEY_OLD:
            keys.append(_fernet(config.SECRET_KEY_OLD))
        _cipher = MultiFernet(keys)
    return _cipher


def reset_cipher() -> None:
    """Drops the cached cipher so a changed key takes effect (rotation, and the tests)."""
    global _cipher
    _cipher = None


def looks_encrypted(value: str) -> bool:
    return value.startswith(_TOKEN_PREFIX)


def encrypt(value: str) -> str:
    return cipher().encrypt(value.encode("utf-8")).decode("ascii")


class EncryptedString(TypeDecorator):
    """A String column, encrypted at rest and plaintext in Python."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if not value:  # None and "" both mean "no secret" and are stored as-is
            return value
        return encrypt(value)

    def process_result_value(self, value, dialect):
        if not value:
            return value
        try:
            return cipher().decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            if looks_encrypted(value):
                # Written under a key this instance does not have. Returning None rather than
                # raising is deliberate: one unreadable secret must not 500 the whole settings
                # page, and the admin's fix is to re-enter it. `CALIVI_SECRET_KEY_OLD` exists
                # precisely so a planned rotation never lands here.
                log.warning(
                    "Could not decrypt a stored secret — was CALIVI_SECRET_KEY changed? "
                    "Set CALIVI_SECRET_KEY_OLD to the previous key, or re-enter the secret."
                )
                return None
            # Never encrypted: a row written before this shipped, or a database restored from
            # an older backup. The startup migration rewrites these, but reading has to keep
            # working in the meantime or an upgrade would look like data loss.
            return value
