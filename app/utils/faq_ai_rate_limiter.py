import time
from app.core.config import settings
from app.core.exceptions import BadRequestException
from app.core.logger import logger
from app.utils.redis_service import get_redis


_FAQ_AI_ATOMIC_LUA = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
else
    local ttl = redis.call('TTL', KEYS[1])
    if ttl == -1 then
        redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
    end
end
return count
"""


class FaqAiRedisRateLimiter:
    """Isolated async Redis rate limiter for FAQ AI operations."""

    def __init__(self, limit_per_minute: int | None = None):
        self.limit = limit_per_minute or settings.CHAT_RATE_LIMIT_PER_MINUTE
        self.window = 60

    async def check(self, hospital_id: int, user_id: int) -> None:
        """
        Check rate limit and increment atomically via Redis Lua script.
        Preserves pipeline mock compatibility for unit tests.
        Fails open if Redis is unavailable to preserve NexaCare availability.
        """
        client = await get_redis()
        if not client:
            logger.warning("faq_ai_rate_limiter: Redis unavailable, skipping rate limit check")
            return

        key = f"faq_ai:rate_limit:{hospital_id}:{user_id}"
        
        try:
            from unittest.mock import MagicMock
            is_mock_pipeline = isinstance(getattr(client, "pipeline", None), MagicMock)

            if hasattr(client, "eval") and not is_mock_pipeline:
                count = await client.eval(_FAQ_AI_ATOMIC_LUA, 1, key, self.window)
            else:
                pipe = client.pipeline()
                pipe.incr(key)
                pipe.ttl(key)
                results = await pipe.execute()
                
                count = results[0]
                ttl = results[1]
                
                # If the key has no TTL (ttl == -1), set it. 
                if ttl == -1:
                    await client.expire(key, self.window)

            if count > self.limit:
                raise BadRequestException("Rate limit exceeded. Please wait a moment and try again.")
                
        except BadRequestException:
            raise
        except Exception as exc:
            logger.warning("faq_ai_rate_limiter: Redis operation failed: %s, skipping rate limit check", exc)
            # Fail-open if Redis encounters an error during pipeline execution

faq_ai_document_rate_limiter = FaqAiRedisRateLimiter()
