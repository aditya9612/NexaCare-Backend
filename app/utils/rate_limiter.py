import time
from collections import defaultdict
from typing import Dict, Tuple

from app.core.config import settings
from app.core.exceptions import BadRequestException


class InMemoryRateLimiter:
    """Simple per-key rate limiter (per minute)."""

    def __init__(self, limit_per_minute: int | None = None):
        self.limit = limit_per_minute or settings.CHAT_RATE_LIMIT_PER_MINUTE
        self._buckets: Dict[str, Tuple[int, float]] = defaultdict(lambda: (0, 0.0))

    def check(self, key: str) -> None:
        count, window_start = self._buckets[key]
        now = time.time()
        if now - window_start >= 60:
            count = 0
            window_start = now
        count += 1
        self._buckets[key] = (count, window_start)
        if count > self.limit:
            raise BadRequestException("Rate limit exceeded. Please wait a moment and try again.")


chat_rate_limiter = InMemoryRateLimiter()
voice_webhook_rate_limiter = InMemoryRateLimiter(limit_per_minute=120)
