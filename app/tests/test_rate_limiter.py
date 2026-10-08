import asyncio
import json
import time
from typing import Any, Dict, List, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.security import create_access_token
from app.main import app
from app.middleware.rate_limit_middleware import (
    _get_trusted_networks,
    get_validated_client_ip,
)
from app.services.rate_limit_service import (
    RateLimitBucket,
    RateLimitService,
    hash_identifier,
)


class MockRedisClient:
    """
    In-memory simulation of Redis sorted set sliding-window Lua execution.
    Executes the exact same logic as _SLIDING_WINDOW_LUA atomically.
    """

    def __init__(self):
        self.buckets: Dict[str, List[Tuple[float, str]]] = {}
        self.call_count = 0

    async def eval(self, script: str, numkeys: int, *args: Any) -> List[int]:
        self.call_count += 1
        keys = list(args[:numkeys])
        argv = list(args[numkeys:])

        now = float(argv[0])
        member = str(argv[1])

        any_exceeded = 0
        max_retry_after = 0
        min_remaining = 999999999
        max_window = 0

        # Step 1: Check all keys
        for i in range(numkeys):
            key = keys[i]
            window = float(argv[2 + i * 2])
            limit = int(argv[2 + i * 2 + 1])

            if window > max_window:
                max_window = window

            entries = self.buckets.get(key, [])
            # Prune expired
            clear_before = now - window
            entries = [e for e in entries if e[0] > clear_before]
            self.buckets[key] = entries

            current_count = len(entries)
            if current_count >= limit:
                any_exceeded = 1
                oldest_ts = entries[0][0] if entries else (now - window)
                retry_after = max(1, int((oldest_ts + window) - now + 0.999))
                if retry_after > max_retry_after:
                    max_retry_after = retry_after
            else:
                rem = limit - (current_count + 1)
                if rem < min_remaining:
                    min_remaining = rem

        # Step 2: Reject if any exceeded
        if any_exceeded == 1:
            return [0, max_retry_after, int(now + max_retry_after), 0]

        # Step 3: Record in all keys
        for i in range(numkeys):
            key = keys[i]
            entries = self.buckets.get(key, [])
            entries.append((now, member))
            self.buckets[key] = entries

        if min_remaining == 999999999:
            min_remaining = 0

        return [1, 0, int(now + max_window), min_remaining]


@pytest.fixture
def mock_redis():
    mock_client = MockRedisClient()
    with patch("app.services.rate_limit_service.get_redis", new=AsyncMock(return_value=mock_client)):
        yield mock_client


@pytest.fixture
def enable_rate_limiting(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT_PER_MINUTE", 120)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_OPEN", True)
    yield


@pytest.fixture(autouse=True)
def mock_service_dependencies(monkeypatch):
    """Mock auth / role methods so downstream routes return 200 without database calls."""
    from app.repositories.rbac_repository import RBACRepository
    from app.services.auth_service import AuthService
    from app.schemas.auth_schema import TokenResponse

    async def mock_list_roles(*args, **kwargs):
        return []

    async def mock_login(*args, **kwargs):
        return TokenResponse(access_token="fake.token", refresh_token="fake.refresh")

    async def mock_send_otp(*args, **kwargs):
        return None

    monkeypatch.setattr(RBACRepository, "list_roles", mock_list_roles)
    monkeypatch.setattr(AuthService, "login", mock_login)
    monkeypatch.setattr(AuthService, "send_otp", mock_send_otp)


# ============================================================================
# 1. GLOBAL DEFAULT LIMIT & HEADERS
# ============================================================================

@pytest.mark.asyncio
async def test_global_rate_limit_default_and_headers(enable_rate_limiting, mock_redis, client):
    """Verify 120 allowed requests on normal API, 121st rejected with HTTP 429 and RFC headers."""
    for i in range(120):
        resp = await client.get("/api/v1/auth/roles")
        assert resp.status_code == 200, f"Request {i+1} failed"
        assert resp.headers["X-RateLimit-Limit"] == "120"
        assert int(resp.headers["X-RateLimit-Remaining"]) == 120 - (i + 1)
        assert "X-RateLimit-Reset" in resp.headers

    resp_121 = await client.get("/api/v1/auth/roles")
    assert resp_121.status_code == 429
    assert "Too many requests" in resp_121.json()["detail"]
    assert "Retry-After" in resp_121.headers
    assert int(resp_121.headers["Retry-After"]) > 0
    assert resp_121.headers["X-RateLimit-Remaining"] == "0"


# ============================================================================
# 2. USER ISOLATION
# ============================================================================

@pytest.mark.asyncio
async def test_user_isolation(enable_rate_limiting, mock_redis, client):
    """User A exhausts quota; User B has independent quota."""
    token_user_a = create_access_token(subject=1001)
    token_user_b = create_access_token(subject=1002)

    headers_a = {"Authorization": f"Bearer {token_user_a}"}
    headers_b = {"Authorization": f"Bearer {token_user_b}"}

    for _ in range(120):
        resp = await client.get("/api/v1/auth/roles", headers=headers_a)
        assert resp.status_code == 200

    resp_a_blocked = await client.get("/api/v1/auth/roles", headers=headers_a)
    assert resp_a_blocked.status_code == 429

    resp_b = await client.get("/api/v1/auth/roles", headers=headers_b)
    assert resp_b.status_code == 200
    assert resp_b.headers["X-RateLimit-Remaining"] == "119"


# ============================================================================
# 3. IP ISOLATION
# ============================================================================

@pytest.mark.asyncio
async def test_ip_isolation(enable_rate_limiting, mock_redis, client):
    """Client IP 1 exhausts quota; Client IP 2 is unaffected."""
    headers_ip1 = {"X-Forwarded-For": "203.0.113.1"}
    headers_ip2 = {"X-Forwarded-For": "203.0.113.2"}

    for _ in range(120):
        resp = await client.get("/api/v1/auth/roles", headers=headers_ip1)
        assert resp.status_code == 200

    resp_ip1_blocked = await client.get("/api/v1/auth/roles", headers=headers_ip1)
    assert resp_ip1_blocked.status_code == 429

    resp_ip2 = await client.get("/api/v1/auth/roles", headers=headers_ip2)
    assert resp_ip2.status_code == 200


# ============================================================================
# 4. LOGIN DUAL BUCKET (TARGET ACCOUNT + IP BURST)
# ============================================================================

@pytest.mark.asyncio
async def test_login_target_bucket(enable_rate_limiting, mock_redis, client):
    """Login limits target account to 5 attempts per 60s."""
    login_payload = {"email": "patient@nexacare.com", "password": "wrongpassword123"}

    for _ in range(5):
        resp = await client.post("/api/v1/auth/login", json=login_payload)
        assert resp.status_code == 200

    resp_6 = await client.post("/api/v1/auth/login", json=login_payload)
    assert resp_6.status_code == 429
    assert "Too many requests" in resp_6.json()["detail"]


@pytest.mark.asyncio
async def test_login_ip_burst_bucket(enable_rate_limiting, mock_redis, client):
    """IP burst bucket limits an IP to 20 attempts even across different accounts."""
    for i in range(20):
        payload = {"email": f"victim{i}@nexacare.com", "password": "testpassword"}
        resp = await client.post("/api/v1/auth/login", json=payload)
        assert resp.status_code == 200

    payload_21 = {"email": "victim21@nexacare.com", "password": "testpassword"}
    resp_21 = await client.post("/api/v1/auth/login", json=payload_21)
    assert resp_21.status_code == 429


# ============================================================================
# 5. OTP TARGET & IP BUCKET
# ============================================================================

@pytest.mark.asyncio
async def test_otp_target_and_ip_buckets(enable_rate_limiting, mock_redis, client):
    """Send OTP limits target phone to 3 / 10m, and IP to 10 / 1h."""
    otp_payload = {"phone": "9876543210"}

    for _ in range(3):
        resp = await client.post("/api/v1/auth/send-otp", json=otp_payload)
        assert resp.status_code == 200

    resp_4 = await client.post("/api/v1/auth/send-otp", json=otp_payload)
    assert resp_4.status_code == 429

    different_phone_payload = {"phone": "9876543211"}
    resp_diff = await client.post("/api/v1/auth/send-otp", json=different_phone_payload)
    assert resp_diff.status_code == 200


# ============================================================================
# 6. BODY REPLAY & DOWNSTREAM PYDANTIC PARSING
# ============================================================================

@pytest.mark.asyncio
async def test_body_replay_downstream_pydantic(enable_rate_limiting, mock_redis, client):
    """Ensure middleware body inspection does not prevent downstream FastAPI Pydantic parsing."""
    resp = await client.post("/api/v1/auth/login", json={"email": "test@nesacare.com"})
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_malformed_json_handled_gracefully(enable_rate_limiting, mock_redis, client):
    """Malformed JSON does not crash middleware; downstream returns 422 or 400."""
    resp = await client.post(
        "/api/v1/auth/login",
        content=b"{bad_json: True}",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code in (400, 422)


# ============================================================================
# 7. MALFORMED JWT HANDLING
# ============================================================================

@pytest.mark.asyncio
async def test_malformed_jwt_fallback_to_anonymous(enable_rate_limiting, mock_redis, client):
    """Malformed JWT does not crash RateLimitMiddleware; it falls back to anonymous client IP."""
    headers = {"Authorization": "Bearer this-is-not-a-valid-jwt-token"}
    resp = await client.get("/api/v1/auth/roles", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["X-RateLimit-Limit"] == "120"


# ============================================================================
# 8. TRUSTED PROXY & SPOOFED IP HANDLING
# ============================================================================

def test_trusted_proxy_ip_resolution():
    """Verify trusted proxy chains and untrusted IP spoof protection."""
    from starlette.requests import Request

    # Case 1: Trusted proxy (127.0.0.1) forwarding valid client
    scope_trusted = {
        "type": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [(b"x-forwarded-for", b"203.0.113.195")],
    }
    req_trusted = Request(scope_trusted)
    assert get_validated_client_ip(req_trusted) == "203.0.113.195"

    # Case 2: Untrusted direct client attempting to spoof X-Forwarded-For
    scope_untrusted = {
        "type": "http",
        "client": ("198.51.100.55", 12345),
        "headers": [(b"x-forwarded-for", b"1.1.1.1, 8.8.8.8")],
    }
    req_untrusted = Request(scope_untrusted)
    assert get_validated_client_ip(req_untrusted) == "198.51.100.55"

    # Case 3: Multiple proxies in XFF chain
    scope_multi = {
        "type": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [(b"x-forwarded-for", b"203.0.113.50, 10.0.0.1")],
    }
    req_multi = Request(scope_multi)
    assert get_validated_client_ip(req_multi) == "203.0.113.50"


# ============================================================================
# 9. REDIS FAILURE / FAIL-OPEN
# ============================================================================

@pytest.mark.asyncio
async def test_redis_failure_fail_open(enable_rate_limiting, client):
    """When Redis is unavailable, RateLimitMiddleware fails open without 500 error."""
    with patch("app.services.rate_limit_service.get_redis", new=AsyncMock(return_value=None)):
        resp = await client.get("/api/v1/auth/roles")
        assert resp.status_code == 200


# ============================================================================
# 10. FAST-PATH EXEMPTIONS
# ============================================================================

@pytest.mark.asyncio
async def test_fast_path_exemptions(enable_rate_limiting, mock_redis, client):
    """Health, docs, and OPTIONS are exempt from rate limiting."""
    resp_health = await client.get("/health")
    assert resp_health.status_code == 200
    assert "X-RateLimit-Limit" not in resp_health.headers

    resp_options = await client.options("/api/v1/auth/roles")
    assert "X-RateLimit-Limit" not in resp_options.headers

    resp_docs = await client.get(f"{settings.API_V1_PREFIX}/openapi.json")
    assert resp_docs.status_code == 200
    assert "X-RateLimit-Limit" not in resp_docs.headers


# ============================================================================
# 11. WINDOW RESET
# ============================================================================

@pytest.mark.asyncio
async def test_window_reset(enable_rate_limiting, mock_redis, client):
    """Quota resets after the sliding window expires."""
    for _ in range(120):
        resp = await client.get("/api/v1/auth/roles")
        assert resp.status_code == 200

    resp_blocked = await client.get("/api/v1/auth/roles")
    assert resp_blocked.status_code == 429

    # Advance time by 61 seconds
    t_future = time.time() + 61.0
    with patch("time.time", return_value=t_future):
        resp_after_reset = await client.get("/api/v1/auth/roles")
        assert resp_after_reset.status_code == 200
        assert int(resp_after_reset.headers["X-RateLimit-Remaining"]) == 119


# ============================================================================
# 12. CONCURRENCY ATOMICITY IN LUA SCRIPT
# ============================================================================

@pytest.mark.asyncio
async def test_lua_script_atomic_concurrency(enable_rate_limiting, mock_redis):
    """Test concurrent checks against RateLimitService with atomic sliding window."""
    bucket = RateLimitBucket(key="rl:test:concurrent:1", limit=10, window=60)

    async def attempt(idx: int):
        return await RateLimitService.check_rate_limits([bucket], now=time.time() + idx * 0.001)

    tasks = [attempt(i) for i in range(15)]
    results = await asyncio.gather(*tasks)

    allowed = [r for r in results if r.allowed]
    denied = [r for r in results if not r.allowed]

    assert len(allowed) == 10
    assert len(denied) == 5
    for d in denied:
        assert d.retry_after > 0
