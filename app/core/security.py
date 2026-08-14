import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt

from app.core.config import settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def generate_device_api_key() -> str:
    return secrets.token_urlsafe(32)


def create_access_token(subject: str | Any, expires_delta: Optional[timedelta] = None) -> str:
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"sub": str(subject), "exp": expire, "type": "access", "iat": now}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: str | Any) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(subject), "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_2fa_challenge_token(subject: str | Any) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=5)
    jti = secrets.token_urlsafe(32)
    payload = {"sub": str(subject), "exp": expire, "type": "2fa_challenge", "iat": now, "jti": jti}
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, jti


def normalize_bearer_token(token: str) -> str:
    """Strip common client formatting mistakes before JWT decode."""
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ('"', "'"):
        token = token[1:-1].strip()
    while token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


def decode_token(token: str) -> dict:
    token = normalize_bearer_token(token)
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid token") from exc

def get_totp_fernet() -> Fernet:
    if not settings.TOTP_ENCRYPTION_KEY:
        raise ValueError("TOTP_ENCRYPTION_KEY is not configured")
    try:
        return Fernet(settings.TOTP_ENCRYPTION_KEY.encode("utf-8"))
    except Exception as e:
        raise ValueError("Invalid TOTP_ENCRYPTION_KEY format") from e

def encrypt_totp_secret(secret: str) -> str:
    f = get_totp_fernet()
    return f.encrypt(secret.encode("utf-8")).decode("utf-8")

def decrypt_totp_secret(encrypted_secret: str) -> str:
    f = get_totp_fernet()
    try:
        return f.decrypt(encrypted_secret.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise ValueError("Failed to decrypt TOTP secret")
