import json
from typing import Any, Optional

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logger import logger

_redis_client: Optional[aioredis.Redis] = None


async def get_redis() -> Optional[aioredis.Redis]:
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await _redis_client.ping()
        return _redis_client
    except Exception as exc:
        logger.warning("Redis unavailable: %s", exc)
        return None


async def cache_get(key: str) -> Optional[Any]:
    client = await get_redis()
    if not client:
        return None
    value = await client.get(key)
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
    await client.setex(key, ttl, payload)
    return True


async def cache_delete(key: str) -> bool:
    client = await get_redis()
    if not client:
        return False
    await client.delete(key)
    return True


async def cache_delete_pattern(pattern: str) -> None:
    client = await get_redis()
    if not client:
        return
    async for key in client.scan_iter(match=pattern):
        await client.delete(key)
