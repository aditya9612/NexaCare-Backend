import asyncio
import time
import pytest
import redis.asyncio as aioredis

from app.core.config import settings
from app.utils.redis_service import _reset_redis_state_for_tests
from app.services.rate_limit_service import (
    RateLimitBucket,
    RateLimitService,
    _SLIDING_WINDOW_LUA,
)


@pytest.mark.asyncio
async def test_real_redis_sliding_window_concurrency():
    """
    Execute real concurrent requests against the local Redis instance (port 6379)
    using the actual Redis Lua sliding-window script.
    Proves:
    1. Concurrent requests cannot exceed the configured limit (10).
    2. Exactly 10 requests succeed and exactly 5 are rejected.
    3. Collision resistance holds under real Redis ZSET mechanics.
    """
    _reset_redis_state_for_tests()
    client = aioredis.from_url(settings.REDIS_URL, decode_responses=False)
    try:
        await client.ping()
    except Exception as exc:
        pytest.skip(f"Local Redis instance at {settings.REDIS_URL} not available: {exc}")

    test_key = f"rl:test:real_redis:concurrent:{int(time.time())}"
    await client.delete(test_key)

    bucket = RateLimitBucket(key=test_key, limit=10, window=60)

    # 15 concurrent tasks executing against real Redis
    async def attempt(idx: int):
        # All tasks fire concurrently
        return await RateLimitService.check_rate_limits([bucket])

    tasks = [attempt(i) for i in range(15)]
    results = await asyncio.gather(*tasks)

    allowed = [r for r in results if r.allowed]
    denied = [r for r in results if not r.allowed]

    assert len(allowed) == 10, f"Expected 10 allowed, got {len(allowed)}"
    assert len(denied) == 5, f"Expected 5 denied, got {len(denied)}"

    # Verify real Redis ZSET cardinality is exactly 10
    real_card = await client.zcard(test_key)
    assert real_card == 10, f"Expected Redis ZCARD=10, got {real_card}"

    # Verify TTL was set on the key in real Redis
    real_ttl = await client.ttl(test_key)
    assert real_ttl > 0 and real_ttl <= 62

    # Clean up
    await client.delete(test_key)
    await client.aclose()


@pytest.mark.asyncio
async def test_real_redis_multi_bucket_atomicity():
    """
    Verify multi-bucket atomicity against real Redis:
    Bucket A (limit 5) and Bucket B (limit 20).
    When Bucket A is exhausted at request 6:
    Bucket B must NOT be incremented (no partial increment on rejected requests).
    """
    _reset_redis_state_for_tests()
    client = aioredis.from_url(settings.REDIS_URL, decode_responses=False)
    try:
        await client.ping()
    except Exception as exc:
        pytest.skip(f"Local Redis instance at {settings.REDIS_URL} not available: {exc}")

    key_a = f"rl:test:real_atomicity:a:{int(time.time())}"
    key_b = f"rl:test:real_atomicity:b:{int(time.time())}"
    await client.delete(key_a, key_b)

    bucket_a = RateLimitBucket(key=key_a, limit=5, window=60)
    bucket_b = RateLimitBucket(key=key_b, limit=20, window=60)

    # Make 5 allowed requests
    for _ in range(5):
        res = await RateLimitService.check_rate_limits([bucket_a, bucket_b])
        assert res.allowed is True

    assert await client.zcard(key_a) == 5
    assert await client.zcard(key_b) == 5

    # 6th request: Bucket A is full, so the entire request must be rejected
    res_6 = await RateLimitService.check_rate_limits([bucket_a, bucket_b])
    assert res_6.allowed is False
    assert res_6.retry_after > 0

    # CRITICAL ATOMICITY CHECK:
    # Bucket B had capacity (5 out of 20), but because Bucket A rejected,
    # Bucket B must REMAIN at 5 and NOT be incremented!
    card_a = await client.zcard(key_a)
    card_b = await client.zcard(key_b)

    assert card_a == 5, f"Bucket A changed to {card_a}"
    assert card_b == 5, f"Bucket B partially consumed! ZCARD is {card_b}, expected 5"

    # Clean up
    await client.delete(key_a, key_b)
    await client.aclose()
