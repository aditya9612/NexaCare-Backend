import time
import uuid
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings
from app.core.logger import logger
from app.utils.redis_service import get_redis, redis_cooldown_active

# Lua script for atomic concurrency slot acquisition
_ACQUIRE_CONCURRENCY_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local token = ARGV[2]
local max_concurrency = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

-- Purge stale slots older than (now - ttl)
local clear_before = now - ttl
redis.call('ZREMRANGEBYSCORE', key, '-inf', clear_before)

local current_active = redis.call('ZCARD', key)
if current_active < max_concurrency then
    redis.call('ZADD', key, now, token)
    redis.call('EXPIRE', key, ttl)
    return token
else
    return nil
end
"""

# Lua script for atomic concurrency slot release
_RELEASE_CONCURRENCY_LUA = """
local key = KEYS[1]
local token = ARGV[1]

redis.call('ZREM', key, token)
local remaining = redis.call('ZCARD', key)
return remaining
"""


@dataclass
class ThrottlingAcquireResult:
    allowed: bool
    token: Optional[str] = None
    retry_after: int = 2


class ThrottlingService:
    """
    Manages atomic Redis-backed concurrency throttling slots.
    Ensures heavy endpoints do not exceed instantaneous execution concurrency.
    """

    _acquire_script = None
    _release_script = None

    @classmethod
    async def acquire_slot(
        cls,
        resource_key: str,
        max_concurrency: int = 3,
        slot_ttl: int = 30,
        retry_after: int = 2,
    ) -> ThrottlingAcquireResult:
        token = uuid.uuid4().hex
        now = time.time()
        redis_key = f"throttle:active:{resource_key}"

        # 1. Try Redis acquisition
        if not redis_cooldown_active():
            try:
                redis_client = await get_redis()
                if redis_client is not None:
                    if cls._acquire_script is None:
                        cls._acquire_script = redis_client.register_script(_ACQUIRE_CONCURRENCY_LUA)

                    acquired_token = await cls._acquire_script(
                        keys=[redis_key],
                        args=[now, token, max_concurrency, slot_ttl],
                    )

                    if acquired_token:
                        token_str = acquired_token.decode("utf-8") if isinstance(acquired_token, bytes) else str(acquired_token)
                        return ThrottlingAcquireResult(allowed=True, token=token_str)
                    else:
                        return ThrottlingAcquireResult(allowed=False, retry_after=retry_after)

            except Exception as exc:
                logger.warning("ThrottlingService: Redis acquisition failed (%s); failing open.", exc)

        # 2. Fail-open if Redis is unavailable
        return ThrottlingAcquireResult(allowed=True, token=token)

    @classmethod
    async def release_slot(cls, resource_key: str, token: Optional[str]) -> None:
        if not token:
            return

        redis_key = f"throttle:active:{resource_key}"

        if not redis_cooldown_active():
            redis_client = await get_redis()
            if redis_client is not None:
                try:
                    if cls._release_script is None:
                        cls._release_script = redis_client.register_script(_RELEASE_CONCURRENCY_LUA)

                    await cls._release_script(keys=[redis_key], args=[token])
                except Exception as exc:
                    logger.warning("ThrottlingService: Redis release failed (%s).", exc)
