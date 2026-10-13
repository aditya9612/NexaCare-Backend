import pytest
from unittest.mock import patch
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.services.throttling_service import ThrottlingService
from app.middleware.throttling_middleware import ThrottlingMiddleware


@pytest.mark.asyncio
async def test_concurrency_acquisition_and_release():
    resource_key = "test:concurrency:basic"
    res1 = await ThrottlingService.acquire_slot(resource_key, max_concurrency=2, slot_ttl=10)
    assert res1.allowed is True
    assert res1.token is not None

    res2 = await ThrottlingService.acquire_slot(resource_key, max_concurrency=2, slot_ttl=10)
    assert res2.allowed is True
    assert res2.token is not None

    # Exceed limit
    res3 = await ThrottlingService.acquire_slot(resource_key, max_concurrency=2, slot_ttl=10)
    assert res3.allowed is False
    assert res3.retry_after == 2

    # Release 1 slot
    await ThrottlingService.release_slot(resource_key, res1.token)

    # Acquire again should succeed
    res4 = await ThrottlingService.acquire_slot(resource_key, max_concurrency=2, slot_ttl=10)
    assert res4.allowed is True
    assert res4.token is not None

    # Cleanup
    await ThrottlingService.release_slot(resource_key, res2.token)
    await ThrottlingService.release_slot(resource_key, res4.token)


@pytest.mark.asyncio
async def test_redis_failure_fail_open_handling():
    with patch("app.services.throttling_service.get_redis", side_effect=Exception("Redis connection refused")):
        res = await ThrottlingService.acquire_slot("test:redis:fail", max_concurrency=1)
        assert res.allowed is True
        assert res.token is not None


@pytest.mark.asyncio
async def test_throttling_middleware_heavy_route():
    app = FastAPI()
    app.add_middleware(ThrottlingMiddleware)

    @app.get("/api/v1/patients/export")
    async def patient_export():
        return {"status": "exported"}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Health route is exempt
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

        # Simulate 3 active concurrent requests on patient_export
        res1 = await ThrottlingService.acquire_slot("heavy:/api/v1/patients/export", max_concurrency=3)
        res2 = await ThrottlingService.acquire_slot("heavy:/api/v1/patients/export", max_concurrency=3)
        res3 = await ThrottlingService.acquire_slot("heavy:/api/v1/patients/export", max_concurrency=3)

        assert res1.allowed and res2.allowed and res3.allowed

        # 4th request via middleware should be rejected with 429
        resp_rejected = await client.get("/api/v1/patients/export")
        assert resp_rejected.status_code == 429
        assert resp_rejected.headers.get("Retry-After") == "2"
        assert "Concurrency limit reached" in resp_rejected.json()["detail"]

        # Release slots
        await ThrottlingService.release_slot("heavy:/api/v1/patients/export", res1.token)
        await ThrottlingService.release_slot("heavy:/api/v1/patients/export", res2.token)
        await ThrottlingService.release_slot("heavy:/api/v1/patients/export", res3.token)

        # Now request should succeed
        resp_success = await client.get("/api/v1/patients/export")
        assert resp_success.status_code == 200
        assert resp_success.json() == {"status": "exported"}
