import secrets
from datetime import datetime, timedelta
from typing import Optional

from app.core.config import settings
from app.core.logger import logger
from app.utils.helpers import utc_now
from app.utils.phone_utils import normalize_phone
from app.utils.redis_service import cache_delete, cache_get, cache_set

# In-memory store fallback: key -> (otp_code, expires_at, attempts)
_otp_store: dict[str, tuple[str, datetime, int]] = {}


def _email_key(email: str) -> str:
    return f"otp:email:{email.strip().lower()}"


def _phone_key(phone: str) -> str:
    return f"otp:phone:{normalize_phone(phone)}"


def _otp_keys(email: str | None = None, phone: str | None = None) -> list[str]:
    keys: list[str] = []
    if email:
        keys.append(_email_key(email))
    if phone:
        keys.append(_phone_key(phone))
    return keys


def generate_otp(length: int = 6) -> str:
    """
    Generate an unpredictable, cryptographically secure numeric OTP string of given length,
    preserving leading zeros (e.g., '004291', '839201').
    """
    max_val = 10 ** length
    code_int = secrets.randbelow(max_val)
    return f"{code_int:0{length}d}"


async def store_otp(
    email: str | None,
    otp: str,
    expiry_minutes: int = 10,
    phone: str | None = None,
) -> None:
    """
    Store dynamic OTP under email and/or phone keys with TTL.
    Uses Redis when available, with in-memory fallback.
    """
    ttl_seconds = expiry_minutes * 60
    expires = utc_now() + timedelta(minutes=expiry_minutes)
    keys = _otp_keys(email=email, phone=phone)
    payload = {"otp": otp, "attempts": 0}

    for key in keys:
        try:
            await cache_set(key, payload, ttl=ttl_seconds)
        except Exception as exc:
            logger.warning("Redis store_otp failed for %s: %s", key, exc)

        # Maintain in memory store as fallback
        _otp_store[key] = (otp, expires, 0)


def store_otp_sync(
    email: str | None,
    otp: str,
    expiry_minutes: int = 10,
    phone: str | None = None,
) -> None:
    """Synchronous storage helper for offline scripts/tests."""
    expires = utc_now() + timedelta(minutes=expiry_minutes)
    for key in _otp_keys(email=email, phone=phone):
        _otp_store[key] = (otp, expires, 0)


async def verify_otp(
    email: str | None,
    otp: str,
    phone: str | None = None,
) -> bool:
    """
    Verify OTP for email and/or phone identifier.
    Enforces expiry, max attempts, and atomic single-use consumption.
    """
    if not otp or not str(otp).strip():
        return False

    otp_clean = str(otp).strip()
    keys = _otp_keys(email=email, phone=phone)
    if not keys:
        return False

    max_attempts = getattr(settings, "OTP_MAX_ATTEMPTS", 5)

    for key in keys:
        # 1. Try Redis store first
        try:
            redis_data = await cache_get(key)
        except Exception:
            redis_data = None

        if redis_data:
            if isinstance(redis_data, dict):
                stored_otp = redis_data.get("otp")
                attempts = redis_data.get("attempts", 0)
            else:
                stored_otp = str(redis_data)
                attempts = 0

            if attempts >= max_attempts:
                await cache_delete(key)
                _otp_store.pop(key, None)
                logger.warning("OTP maximum verification attempts exceeded for key: %s", key)
                return False

            if stored_otp == otp_clean:
                # Valid OTP! Atomically delete to guarantee SINGLE-USE
                for k in keys:
                    await cache_delete(k)
                    _otp_store.pop(k, None)
                return True
            else:
                attempts += 1
                if attempts >= max_attempts:
                    await cache_delete(key)
                    _otp_store.pop(key, None)
                    logger.warning("OTP invalidated after %s failed attempts for %s", attempts, key)
                else:
                    await cache_set(
                        key,
                        {"otp": stored_otp, "attempts": attempts},
                        ttl=settings.OTP_EXPIRE_MINUTES * 60,
                    )
                continue

        # 2. In-memory store fallback
        mem_data = _otp_store.get(key)
        if mem_data:
            stored_otp, expires, attempts = mem_data
            if utc_now() > expires:
                _otp_store.pop(key, None)
                continue

            if attempts >= max_attempts:
                _otp_store.pop(key, None)
                logger.warning("OTP maximum verification attempts exceeded for key: %s", key)
                return False

            if stored_otp == otp_clean:
                # Valid OTP! Atomically delete to guarantee SINGLE-USE
                for k in keys:
                    _otp_store.pop(k, None)
                    await cache_delete(k)
                return True
            else:
                attempts += 1
                if attempts >= max_attempts:
                    _otp_store.pop(key, None)
                    logger.warning("OTP invalidated after %s failed attempts for %s", attempts, key)
                else:
                    _otp_store[key] = (stored_otp, expires, attempts)
                continue

    return False


def verify_otp_sync(
    email: str | None,
    otp: str,
    phone: str | None = None,
) -> bool:
    """Synchronous verification helper for offline scripts/tests."""
    if not otp or not str(otp).strip():
        return False
    otp_clean = str(otp).strip()
    keys = _otp_keys(email=email, phone=phone)
    max_attempts = getattr(settings, "OTP_MAX_ATTEMPTS", 5)

    for key in keys:
        mem_data = _otp_store.get(key)
        if mem_data:
            stored_otp, expires, attempts = mem_data
            if utc_now() > expires:
                _otp_store.pop(key, None)
                continue
            if attempts >= max_attempts:
                _otp_store.pop(key, None)
                return False
            if stored_otp == otp_clean:
                for k in keys:
                    _otp_store.pop(k, None)
                return True
            else:
                attempts += 1
                if attempts >= max_attempts:
                    _otp_store.pop(key, None)
                else:
                    _otp_store[key] = (stored_otp, expires, attempts)
    return False
