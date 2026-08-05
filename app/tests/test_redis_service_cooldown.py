"""Unit tests for Redis unavailable cooldown in redis_service."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.utils import redis_service


@pytest.fixture(autouse=True)
def _clean_redis_state():
    redis_service._reset_redis_state_for_tests()
    yield
    redis_service._reset_redis_state_for_tests()


@pytest.mark.asyncio
async def test_failed_connect_opens_cooldown_and_skips_reconnect():
    fail_client = MagicMock()
    fail_client.ping = AsyncMock(side_effect=ConnectionError("refused"))

    with patch.object(
        redis_service.aioredis, "from_url", return_value=fail_client
    ) as from_url:
        first = await redis_service.get_redis()
        assert first is None
        assert from_url.call_count == 1

        second = await redis_service.get_redis()
        assert second is None
        assert from_url.call_count == 1  # no reconnect during cooldown

        third = await redis_service.cache_get("any-key")
        assert third is None
        assert from_url.call_count == 1


@pytest.mark.asyncio
async def test_after_cooldown_allows_one_reconnect_attempt():
    fail_client = MagicMock()
    fail_client.ping = AsyncMock(side_effect=ConnectionError("refused"))

    ok_client = MagicMock()
    ok_client.ping = AsyncMock(return_value=True)

    with patch.object(
        redis_service.aioredis,
        "from_url",
        side_effect=[fail_client, ok_client],
    ) as from_url:
        assert await redis_service.get_redis() is None
        assert from_url.call_count == 1

        # Expire cooldown
        redis_service._redis_unavailable_until = time.monotonic() - 1

        client = await redis_service.get_redis()
        assert client is ok_client
        assert from_url.call_count == 2
        assert redis_service._redis_unavailable_until == 0.0


@pytest.mark.asyncio
async def test_reconnect_failure_restarts_cooldown():
    fail_client = MagicMock()
    fail_client.ping = AsyncMock(side_effect=ConnectionError("still down"))

    with patch.object(
        redis_service.aioredis, "from_url", return_value=fail_client
    ) as from_url:
        assert await redis_service.get_redis() is None
        assert from_url.call_count == 1

        redis_service._redis_unavailable_until = time.monotonic() - 1
        assert await redis_service.get_redis() is None
        assert from_url.call_count == 2

        # Still in new cooldown — no third connect
        assert await redis_service.get_redis() is None
        assert from_url.call_count == 2


@pytest.mark.asyncio
async def test_cache_ops_during_cooldown_are_instant():
    fail_client = MagicMock()
    fail_client.ping = AsyncMock(side_effect=ConnectionError("refused"))

    with patch.object(redis_service.aioredis, "from_url", return_value=fail_client):
        await redis_service.get_redis()  # open cooldown

    t0 = time.perf_counter()
    for _ in range(5):
        assert await redis_service.cache_get("k") is None
        assert await redis_service.cache_set("k", {"a": 1}) is False
        assert await redis_service.cache_delete("k") is False
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 50, f"cooldown path too slow: {elapsed_ms:.1f}ms"


@pytest.mark.asyncio
async def test_midflight_connection_error_opens_cooldown():
    live = MagicMock()
    live.ping = AsyncMock(return_value=True)
    live.get = AsyncMock(side_effect=RedisConnectionError("broken"))

    with patch.object(redis_service.aioredis, "from_url", return_value=live) as from_url:
        assert await redis_service.cache_get("k") is None
        assert from_url.call_count == 1
        assert redis_service._redis_client is None
        assert redis_service._redis_unavailable_until > time.monotonic()

        # Subsequent call must not reconnect
        assert await redis_service.cache_get("k") is None
        assert from_url.call_count == 1
