import time
from collections import defaultdict
from typing import Dict, Tuple

from app.core.config import settings
from app.core.exceptions import BadRequestException


class InMemoryRateLimiter:
    """Simple per-key rate limiter."""

    def __init__(self, limit_per_minute: int | None = None, limit_per_second: int | None = None):
        if limit_per_second is not None:
            self.limit = limit_per_second
            self.window = 1.0
        elif limit_per_minute is not None:
            self.limit = limit_per_minute
            self.window = 60.0
        else:
            self.limit = getattr(settings, "RATE_LIMIT_PER_SECOND", 50)
            self.window = 1.0
        self._buckets: Dict[str, Tuple[int, float]] = defaultdict(lambda: (0, 0.0))

    def check(self, key: str) -> None:
        count, window_start = self._buckets[key]
        now = time.time()
        if now - window_start >= self.window:
            count = 0
            window_start = now
        count += 1
        self._buckets[key] = (count, window_start)
        if count > self.limit:
            raise BadRequestException("Rate limit exceeded. Please wait a moment and try again.")


chat_rate_limiter = InMemoryRateLimiter()
voice_webhook_rate_limiter = InMemoryRateLimiter(limit_per_second=getattr(settings, "RATE_LIMIT_PER_SECOND", 50))


async def check_chat_rate_limit(session_id: str) -> None:
    """
    Shared Redis rate limit for chat sessions (50 req / 1s).
    Falls back to in-memory check if Redis is unavailable.
    """
    if not settings.RATE_LIMIT_ENABLED:
        return

    from app.services.rate_limit_service import RateLimitBucket, RateLimitService
    from app.core.logger import logger

    limit = getattr(settings, "RATE_LIMIT_PER_SECOND", 50)
    bucket = RateLimitBucket(
        key=f"rl:chat:session:{session_id}:1",
        limit=limit,
        window=1,
    )
    try:
        result = await RateLimitService.check_rate_limits([bucket])
        if not result.allowed:
            raise BadRequestException("Rate limit exceeded. Please wait a moment and try again.")
    except BadRequestException:
        raise
    except Exception as exc:
        logger.warning("check_chat_rate_limit: Redis error: %s; falling back to in-memory", exc)
        chat_rate_limiter.check(f"chat:{session_id}")

