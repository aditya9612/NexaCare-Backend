import time
from app.core.config import settings
from app.core.exceptions import BadRequestException
from app.core.logger import logger
from app.utils.redis_service import get_redis


class FaqAiRedisRateLimiter:
    """Isolated async Redis rate limiter for FAQ AI operations."""

    def __init__(self, limit_per_minute: int | None = None):
        self.limit = limit_per_minute or settings.CHAT_RATE_LIMIT_PER_MINUTE
        self.window = 60

    async def check(self, hospital_id: int, user_id: int) -> None:
        """
        Check rate limit and increment atomically via pipeline.
        Fails open if Redis is unavailable to preserve NexaCare availability.
        """
        client = await get_redis()
        if not client:
            logger.warning("faq_ai_rate_limiter: Redis unavailable, skipping rate limit check")
            return

        key = f"faq_ai:rate_limit:{hospital_id}:{user_id}"
        
        try:
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.ttl(key)
            results = await pipe.execute()
            
            count = results[0]
            ttl = results[1]
            
            # If the key has no TTL (ttl == -1), set it. 
            # This happens exactly once when INCR creates the key.
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
