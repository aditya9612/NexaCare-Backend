import asyncio
import json
import secrets
from datetime import datetime, timedelta
from typing import Optional

from app.core.config import settings
from app.core.logger import logger
from app.utils.helpers import utc_now
from app.utils.phone_utils import normalize_phone
from app.utils.redis_service import cache_delete, cache_get, cache_set, get_redis

# In-memory store fallback: key -> (otp_code, expires_at, attempts, purpose)
_otp_store: dict[str, tuple[str, datetime, int, str | None]] = {}
_mem_lock: asyncio.Lock | None = None
_mem_lock_loop: asyncio.AbstractEventLoop | None = None


def _get_mem_lock() -> asyncio.Lock:
    global _mem_lock, _mem_lock_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _mem_lock is None or _mem_lock_loop != loop:
        _mem_lock = asyncio.Lock()
        _mem_lock_loop = loop
    return _mem_lock

_VERIFY_AND_CONSUME_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then
    return -1
end

local data = cjson.decode(raw)
local stored_otp = tostring(data['otp'] or '')
local attempts = tonumber(data['attempts'] or 0)
local max_attempts = tonumber(ARGV[2] or 5)
local expected_purpose = tostring(ARGV[3] or '')
local stored_purpose = tostring(data['purpose'] or '')

if expected_purpose ~= '' and stored_purpose ~= '' and stored_purpose ~= expected_purpose then
    return -4
end

if attempts >= max_attempts then
    redis.call('DEL', KEYS[1])
    return -2
end

if stored_otp == tostring(ARGV[1] or '') then
    redis.call('DEL', KEYS[1])
    return 1
else
    attempts = attempts + 1
    if attempts >= max_attempts then
        redis.call('DEL', KEYS[1])
        return -2
    else
        data['attempts'] = attempts
        local ttl = redis.call('TTL', KEYS[1])
        if ttl <= 0 then ttl = 600 end
        redis.call('SETEX', KEYS[1], ttl, cjson.encode(data))
        return 0
    end
end
"""


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
    purpose: str = "login",
) -> None:
    """
    Store dynamic OTP under email and/or phone keys with TTL.
    Uses Redis when available, with in-memory fallback.
    """
    ttl_seconds = expiry_minutes * 60
    expires = utc_now() + timedelta(minutes=expiry_minutes)
    keys = _otp_keys(email=email, phone=phone)
    payload = {"otp": otp, "attempts": 0, "purpose": purpose, "email": email}

    for key in keys:
        try:
            await cache_set(key, payload, ttl=ttl_seconds)
        except Exception as exc:
            logger.warning("Redis store_otp failed for %s: %s", key, exc)

        async with _get_mem_lock():
            _otp_store[key] = (otp, expires, 0, purpose)


def store_otp_sync(
    email: str | None,
    otp: str,
    expiry_minutes: int = 10,
    phone: str | None = None,
    purpose: str = "login",
) -> None:
    """Synchronous storage helper for offline scripts/tests."""
    expires = utc_now() + timedelta(minutes=expiry_minutes)
    for key in _otp_keys(email=email, phone=phone):
        _otp_store[key] = (otp, expires, 0, purpose)


async def verify_otp(
    email: str | None,
    otp: str,
    phone: str | None = None,
    purpose: str | None = None,
) -> bool:
    """
    Verify OTP for email and/or phone identifier.
    Enforces expiry, max attempts, purpose-binding, and atomic single-use consumption.
    """
    if not otp or not str(otp).strip():
        return False

    otp_clean = str(otp).strip()
    keys = _otp_keys(email=email, phone=phone)
    if not keys:
        return False

    max_attempts = getattr(settings, "OTP_MAX_ATTEMPTS", 5)
    expected_purpose = purpose or ""

    for key in keys:
        # 1. Try atomic Redis Lua execution first
        client = await get_redis()
        if client:
            try:
                res = await client.eval(
                    _VERIFY_AND_CONSUME_LUA,
                    1,
                    key,
                    otp_clean,
                    max_attempts,
                    expected_purpose,
                )
                res_code = int(res)
                if res_code == 1:
                    # Valid OTP atomically consumed! Clean up sibling keys & memory store
                    for k in keys:
                        if k != key:
                            await cache_delete(k)
                    async with _get_mem_lock():
                        for k in keys:
                            _otp_store.pop(k, None)
                    return True
                elif res_code == -2:
                    logger.warning("OTP maximum verification attempts exceeded for key: %s", key)
                    for k in keys:
                        await cache_delete(k)
                    async with _get_mem_lock():
                        for k in keys:
                            _otp_store.pop(k, None)
                    return False
                elif res_code == -4:
                    logger.warning("OTP purpose mismatch for key: %s", key)
                    return False
                elif res_code == 0:
                    logger.warning("Invalid OTP attempt for key: %s", key)
                    continue
                # res_code == -1 (key not found in Redis, check next key or fallback to memory)
            except Exception as exc:
                logger.warning("Redis Lua verify_otp failed: %s, checking memory fallback", exc)

        # 2. In-memory store fallback with atomic lock
        async with _get_mem_lock():
            mem_data = _otp_store.get(key)
            if mem_data:
                stored_otp = mem_data[0]
                expires = mem_data[1]
                attempts = mem_data[2]
                stored_purpose = mem_data[3] if len(mem_data) > 3 else None

                if utc_now() > expires:
                    _otp_store.pop(key, None)
                    continue

                if expected_purpose and stored_purpose and stored_purpose != expected_purpose:
                    logger.warning("OTP purpose mismatch in memory store for key: %s", key)
                    return False

                if attempts >= max_attempts:
                    for k in keys:
                        _otp_store.pop(k, None)
                        await cache_delete(k)
                    logger.warning("OTP maximum verification attempts exceeded for key: %s", key)
                    return False

                if stored_otp == otp_clean:
                    for k in keys:
                        _otp_store.pop(k, None)
                        await cache_delete(k)
                    return True
                else:
                    attempts += 1
                    if attempts >= max_attempts:
                        for k in keys:
                            _otp_store.pop(k, None)
                            await cache_delete(k)
                        logger.warning("OTP invalidated after %s failed attempts for %s", attempts, key)
                    else:
                        _otp_store[key] = (stored_otp, expires, attempts, stored_purpose)
                    continue

    return False


def verify_otp_sync(
    email: str | None,
    otp: str,
    phone: str | None = None,
    purpose: str | None = None,
) -> bool:
    """Synchronous verification helper for offline scripts/tests."""
    if not otp or not str(otp).strip():
        return False
    otp_clean = str(otp).strip()
    keys = _otp_keys(email=email, phone=phone)
    max_attempts = getattr(settings, "OTP_MAX_ATTEMPTS", 5)
    expected_purpose = purpose or ""

    for key in keys:
        mem_data = _otp_store.get(key)
        if mem_data:
            stored_otp = mem_data[0]
            expires = mem_data[1]
            attempts = mem_data[2]
            stored_purpose = mem_data[3] if len(mem_data) > 3 else None

            if utc_now() > expires:
                _otp_store.pop(key, None)
                continue
            if expected_purpose and stored_purpose and stored_purpose != expected_purpose:
                return False
            if attempts >= max_attempts:
                for k in keys:
                    _otp_store.pop(k, None)
                return False
            if stored_otp == otp_clean:
                for k in keys:
                    _otp_store.pop(k, None)
                return True
            else:
                attempts += 1
                if attempts >= max_attempts:
                    for k in keys:
                        _otp_store.pop(k, None)
                else:
                    _otp_store[key] = (stored_otp, expires, attempts, stored_purpose)
    return False
