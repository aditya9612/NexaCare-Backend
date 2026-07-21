"""Symmetric encryption for telephony credentials at rest (Fernet)."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.logger import logger

_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    # Derive a stable 32-byte key from SECRET_KEY
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    if value.startswith(_PREFIX):
        return value
    token = _fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    return f"{_PREFIX}{token}"


def decrypt_secret(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    if not value.startswith(_PREFIX):
        # Legacy plaintext — return as-is (will be re-encrypted on next save)
        return value
    raw = value[len(_PREFIX) :]
    try:
        return _fernet().decrypt(raw.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.error("Failed to decrypt telephony credential")
        return None
