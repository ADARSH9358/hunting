"""Symmetric encryption for secrets stored in the database (OAuth tokens)."""
from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    s = get_settings()
    if s.token_encryption_key:
        try:
            return Fernet(s.token_encryption_key.strip().encode())
        except ValueError as e:
            raise RuntimeError(
                "TOKEN_ENCRYPTION_KEY in .env is not a valid key. Generate one with: python -c \"from cryptography.fernet "
                "import Fernet;print(Fernet.generate_key().decode())\" (or leave it empty), then restart the backend."
            ) from e
    # Derived key: stable for a given SECRET_KEY. Set TOKEN_ENCRYPTION_KEY in production
    # so rotating SECRET_KEY (which logs everyone out) does not also break Gmail connections.
    digest = hashlib.sha256(b"jobhunt-token-encryption:" + s.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str | None) -> str | None:
    return None if value is None else _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as e:
        raise RuntimeError("Stored token cannot be decrypted (encryption key changed?) - reconnect the account") from e
