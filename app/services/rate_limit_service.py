import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import List, Optional

from app.core.config import settings
from app.core.logger import logger
from app.utils.redis_service import get_redis

# Atomic Sliding Window Lua script for single or multiple buckets
# Evaluates sorted sets (ZREMRANGEBYSCORE, ZCARD, ZADD, EXPIRE)
# If ANY bucket exceeds limit:
#   returns {0, max_retry_after, reset_epoch, 0} without modifying any bucket
# If ALL buckets allow request:
#   adds unique member to all buckets, sets TTL, and returns {1, 0, reset_epoch, min_remaining}
_SLIDING_WINDOW_LUA = """
local now = tonumber(ARGV[1])
local member = ARGV[2]
local key_count = #KEYS

local any_exceeded = 0
local max_retry_after = 0
local min_remaining = 999999999
local max_window = 0

-- 1. Inspect all buckets first
for i = 1, key_count do
    local key = KEYS[i]
    local window = tonumber(ARGV[2 + (i - 1) * 2 + 1])
    local limit = tonumber(ARGV[2 + (i - 1) * 2 + 2])
    
    if window > max_window then
        max_window = window
    end
    
    local clear_before = now - window
    redis.call('ZREMRANGEBYSCORE', key, '-inf', clear_before)
    local current_count = redis.call('ZCARD', key)
    
    if current_count >= limit then
        any_exceeded = 1
        local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
        local retry_after = window
        if oldest and #oldest >= 2 then
            local oldest_ts = tonumber(oldest[2])
            retry_after = math.max(1, math.ceil((oldest_ts + window) - now))
        end
        if retry_after > max_retry_after then
            max_retry_after = retry_after
        end
    else
        local rem = limit - (current_count + 1)
        if rem < min_remaining then
            min_remaining = rem
        end
    end
end

-- 2. Reject if any bucket exceeded
if any_exceeded == 1 then
    return {0, max_retry_after, math.ceil(now + max_retry_after), 0}
end

-- 3. All allowed: record request in all buckets
for i = 1, key_count do
    local key = KEYS[i]
    local window = tonumber(ARGV[2 + (i - 1) * 2 + 1])
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, math.ceil(window))
end

if min_remaining == 999999999 then
    min_remaining = 0
end

return {1, 0, math.ceil(now + max_window), min_remaining}
"""


@dataclass
class RateLimitBucket:
    key: str
    limit: int
    window: int  # in seconds


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    reset_epoch: int


def hash_identifier(raw: Optional[str]) -> str:
    """Safely hash an identifier (email, phone, device key) with SHA-256."""
    if not raw:
        return "none"
    norm = raw.strip().lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]


class RateLimitService:
    @staticmethod
    async def check_rate_limits(
        buckets: List[RateLimitBucket],
        now: Optional[float] = None,
    ) -> RateLimitResult:
        """
        Check and record rate limit atomically across all specified buckets.
        Fails open if Redis is unavailable or encountering connection errors.
        """
        if not settings.RATE_LIMIT_ENABLED or not buckets:
            current_ts = int(time.time())
            default_limit = buckets[0].limit if buckets else settings.RATE_LIMIT_DEFAULT_PER_MINUTE
            return RateLimitResult(
                allowed=True,
                limit=default_limit,
                remaining=default_limit,
                retry_after=0,
                reset_epoch=current_ts + 60,
            )

        client = await get_redis()
        current_time = now if now is not None else time.time()
        primary_bucket = buckets[0]

        if not client:
            if settings.RATE_LIMIT_FAIL_OPEN:
                logger.warning("RateLimiter: Redis unavailable; failing open")
                return RateLimitResult(
                    allowed=True,
                    limit=primary_bucket.limit,
                    remaining=primary_bucket.limit,
                    retry_after=0,
                    reset_epoch=int(current_time + primary_bucket.window),
                )
            else:
                logger.error("RateLimiter: Redis unavailable; fail-closed rejection")
                return RateLimitResult(
                    allowed=False,
                    limit=primary_bucket.limit,
                    remaining=0,
                    retry_after=primary_bucket.window,
                    reset_epoch=int(current_time + primary_bucket.window),
                )

        keys = [b.key for b in buckets]
        # ARGV: now, unique_member, (window_1, limit_1), (window_2, limit_2), ...
        unique_member = f"{current_time}:{uuid.uuid4().hex[:8]}"
        argv = [str(current_time), unique_member]
        for b in buckets:
            argv.extend([str(b.window), str(b.limit)])

        try:
            res = await client.eval(_SLIDING_WINDOW_LUA, len(keys), *keys, *argv)
            allowed = bool(res[0] == 1)
            retry_after = int(res[1])
            reset_epoch = int(res[2])
            remaining = int(res[3])

            min_limit = min(b.limit for b in buckets)

            return RateLimitResult(
                allowed=allowed,
                limit=min_limit,
                remaining=remaining,
                retry_after=retry_after,
                reset_epoch=reset_epoch,
            )
        except Exception as exc:
            logger.warning("RateLimiter: Redis operation error: %s; failing open", exc)
            if settings.RATE_LIMIT_FAIL_OPEN:
                return RateLimitResult(
                    allowed=True,
                    limit=primary_bucket.limit,
                    remaining=primary_bucket.limit,
                    retry_after=0,
                    reset_epoch=int(current_time + primary_bucket.window),
                )
            raise
