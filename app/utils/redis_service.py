import asyncio
import json
import time
from typing import Any, Optional

import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.core.config import settings
from app.core.logger import logger

REDIS_UNAVAILABLE_COOLDOWN_SECONDS = 30
REDIS_CONNECT_TIMEOUT_SECONDS = 1

_redis_client: Optional[aioredis.Redis] = None
_redis_unavailable_until: float = 0.0

_CONNECTION_ERRORS = (
    RedisConnectionError,
    RedisTimeoutError,
    ConnectionError,
    OSError,
    TimeoutError,
    asyncio.TimeoutError,
)


def _mark_unavailable(reason: str) -> None:
    """Clear client and start cooldown so callers skip reconnect until it expires."""
    global _redis_client, _redis_unavailable_until
    _redis_client = None
    _redis_unavailable_until = time.monotonic() + REDIS_UNAVAILABLE_COOLDOWN_SECONDS
    logger.warning(
        "Redis unavailable: %s; cooldown %ss",
        reason,
        REDIS_UNAVAILABLE_COOLDOWN_SECONDS,
    )


def _is_connection_error(exc: BaseException) -> bool:
    return isinstance(exc, _CONNECTION_ERRORS)


def _reset_redis_state_for_tests() -> None:
    """Test helper — clear cached client and cooldown."""
    global _redis_client, _redis_unavailable_until
    _redis_client = None
    _redis_unavailable_until = 0.0


async def get_redis() -> Optional[aioredis.Redis]:
    global _redis_client, _redis_unavailable_until
    if _redis_client is not None:
        return _redis_client

    now = time.monotonic()
    if now < _redis_unavailable_until:
        logger.debug(
            "Redis cooldown active; skipping connect (%.1fs left)",
            _redis_unavailable_until - now,
        )
        return None

    try:
        client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=REDIS_CONNECT_TIMEOUT_SECONDS,
            socket_timeout=REDIS_CONNECT_TIMEOUT_SECONDS,
        )
        await asyncio.wait_for(
            client.ping(),
            timeout=REDIS_CONNECT_TIMEOUT_SECONDS,
        )
        _redis_client = client
        if _redis_unavailable_until > 0:
            logger.info("Redis reconnected after cooldown")
        _redis_unavailable_until = 0.0
        return _redis_client
    except Exception as exc:
        _mark_unavailable(str(exc))
        return None


async def cache_get(key: str) -> Optional[Any]:
    client = await get_redis()
    if not client:
        return None
    try:
        value = await client.get(key)
    except Exception as exc:
        logger.warning("Redis get failed: %s", exc)
        if _is_connection_error(exc):
            _mark_unavailable(str(exc))
        return None
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


async def cache_set(key: str, value: Any, ttl: int = 300) -> bool:
    client = await get_redis()
    if not client:
        return False
    payload = json.dumps(value) if not isinstance(value, str) else value
    try:
        await client.setex(key, ttl, payload)
        return True
    except Exception as exc:
        logger.warning("Redis set failed: %s", exc)
        if _is_connection_error(exc):
            _mark_unavailable(str(exc))
        return False


async def cache_delete(key: str) -> bool:
    client = await get_redis()
    if not client:
        return False
    try:
        await client.delete(key)
        return True
    except Exception as exc:
        logger.warning("Redis delete failed: %s", exc)
        if _is_connection_error(exc):
            _mark_unavailable(str(exc))
        return False


async def cache_delete_pattern(pattern: str) -> None:
    client = await get_redis()
    if not client:
        return
    try:
        async for key in client.scan_iter(match=pattern):
            await client.delete(key)
    except Exception as exc:
        logger.warning("Redis delete_pattern failed: %s", exc)
        if _is_connection_error(exc):
            _mark_unavailable(str(exc))
