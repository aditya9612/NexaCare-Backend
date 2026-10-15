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

        # Step 3: Record in all keys (Redis ZSET semantics: update score if member exists)
        for i in range(numkeys):
            key = keys[i]
            entries = self.buckets.get(key, [])
            existing_idx = next((idx for idx, e in enumerate(entries) if e[1] == member), None)
            if existing_idx is not None:
                entries[existing_idx] = (now, member)
            else:
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
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_SECOND", 10)
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTHENTICATED_PER_MINUTE", 10)
    monkeypatch.setattr(settings, "RATE_LIMIT_ANONYMOUS_PER_MINUTE", 10)
    monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT_PER_MINUTE", 10)
    monkeypatch.setattr(settings, "RATE_LIMIT_OTP_COOLDOWN_SECONDS", 0)
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

    async def mock_verify_otp_code(*args, **kwargs):
        return None

    async def mock_reset_password(*args, **kwargs):
        return None

    monkeypatch.setattr(RBACRepository, "list_roles", mock_list_roles)
    monkeypatch.setattr(AuthService, "login", mock_login)
    monkeypatch.setattr(AuthService, "send_otp", mock_send_otp)
    monkeypatch.setattr(AuthService, "verify_otp_code", mock_verify_otp_code)
    monkeypatch.setattr(AuthService, "reset_password", mock_reset_password)


# ============================================================================
# 1. GLOBAL DEFAULT LIMIT & HEADERS
# ============================================================================

@pytest.mark.asyncio
async def test_global_rate_limit_default_and_headers(enable_rate_limiting, mock_redis, client):
    """Verify 10 allowed requests on normal API, 11th rejected with HTTP 429 and RFC headers."""
    for i in range(10):
        resp = await client.get("/api/v1/auth/roles")
        assert resp.status_code == 200, f"Request {i+1} failed"
        assert resp.headers["X-RateLimit-Limit"] == "10"
        assert int(resp.headers["X-RateLimit-Remaining"]) == 10 - (i + 1)
        assert "X-RateLimit-Reset" in resp.headers

    resp_11 = await client.get("/api/v1/auth/roles")
    assert resp_11.status_code == 429
    assert "Too many requests" in resp_11.json()["detail"]
    assert "Retry-After" in resp_11.headers
    assert int(resp_11.headers["Retry-After"]) > 0
    assert resp_11.headers["X-RateLimit-Remaining"] == "0"


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

    for _ in range(10):
        resp = await client.get("/api/v1/auth/roles", headers=headers_a)
        assert resp.status_code == 200

    resp_a_blocked = await client.get("/api/v1/auth/roles", headers=headers_a)
    assert resp_a_blocked.status_code == 429

    resp_b = await client.get("/api/v1/auth/roles", headers=headers_b)
    assert resp_b.status_code == 200
    assert resp_b.headers["X-RateLimit-Remaining"] == "9"


# ============================================================================
# 3. IP ISOLATION
# ============================================================================

@pytest.mark.asyncio
async def test_ip_isolation(enable_rate_limiting, mock_redis, client):
    """Client IP 1 exhausts quota; Client IP 2 is unaffected."""
    headers_ip1 = {"X-Forwarded-For": "203.0.113.1"}
    headers_ip2 = {"X-Forwarded-For": "203.0.113.2"}

    for _ in range(10):
        resp = await client.get("/api/v1/auth/roles", headers=headers_ip1)
        assert resp.status_code == 200

    resp_ip1_blocked = await client.get("/api/v1/auth/roles", headers=headers_ip1)
    assert resp_ip1_blocked.status_code == 429

    resp_ip2 = await client.get("/api/v1/auth/roles", headers=headers_ip2)
    assert resp_ip2.status_code == 200


# ============================================================================
# 4. AUTH ENDPOINTS RATE LIMIT (LOGIN & OTP)
# ============================================================================

@pytest.mark.asyncio
async def test_login_unified_rate_limit(enable_rate_limiting, mock_redis, client):
    """Login enforces the unified rate limit (10 in test fixture)."""
    login_payload = {"email": "patient@nexacare.com", "password": "wrongpassword123"}

    for _ in range(10):
        resp = await client.post("/api/v1/auth/login", json=login_payload)
        assert resp.status_code == 200

    resp_11 = await client.post("/api/v1/auth/login", json=login_payload)
    assert resp_11.status_code == 429
    assert "Too many requests" in resp_11.json()["detail"]


@pytest.mark.asyncio
async def test_otp_unified_rate_limit(enable_rate_limiting, mock_redis, client):
    """Send OTP enforces the unified rate limit (10 in test fixture)."""
    otp_payload = {"phone": "9876543210"}

    for _ in range(10):
        resp = await client.post("/api/v1/auth/send-otp", json=otp_payload)
        assert resp.status_code == 200

    resp_11 = await client.post("/api/v1/auth/send-otp", json=otp_payload)
    assert resp_11.status_code == 429



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
    assert resp.headers["X-RateLimit-Limit"] == "10"


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
# 9. REDIS FAILURE / FAIL-OPEN & FAIL-CLOSED
# ============================================================================

@pytest.mark.asyncio
async def test_redis_failure_fail_open(enable_rate_limiting, client):
    """When Redis is unavailable, normal APIs fail open without 500 error."""
    with patch("app.services.rate_limit_service.get_redis", new=AsyncMock(return_value=None)):
        resp = await client.get("/api/v1/auth/roles")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_redis_failure_fail_closed_503(enable_rate_limiting, client):
    """When Redis is unavailable, protected auth endpoints fail closed with HTTP 503 (not 429 or 500)."""
    with patch("app.services.rate_limit_service.get_redis", new=AsyncMock(return_value=None)):
        resp = await client.post("/api/v1/auth/login", json={"email": "doc@nexacare.com", "password": "pass"})
        assert resp.status_code == 503
        assert "temporarily unavailable" in resp.json()["detail"].lower()
        assert resp.headers.get("Retry-After") == "5"


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
    for _ in range(10):
        resp = await client.get("/api/v1/auth/roles")
        assert resp.status_code == 200

    resp_blocked = await client.get("/api/v1/auth/roles")
    assert resp_blocked.status_code == 429

    # Advance time past the 1-second window
    t_future = time.time() + 2.0
    with patch("time.time", return_value=t_future):
        resp_after_reset = await client.get("/api/v1/auth/roles")
        assert resp_after_reset.status_code == 200
        assert int(resp_after_reset.headers["X-RateLimit-Remaining"]) == 9


# ============================================================================
# 12. CONCURRENCY ATOMICITY & SAME-MILLISECOND COLLISION RESISTANCE
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


@pytest.mark.asyncio
async def test_lua_concurrent_same_millisecond_collision_resistance(enable_rate_limiting, mock_redis):
    """
    Deterministic concurrency test: 15 concurrent requests share the exact same timestamp
    down to the nanosecond. Collision-resistant 128-bit UUID member generation guarantees
    no ZSET member overwrites occur and exactly 10 requests are allowed, 5 rejected.
    """
    bucket = RateLimitBucket(key="rl:test:same_ms:1", limit=10, window=60)
    fixed_ts = 1700000000.0

    async def attempt():
        return await RateLimitService.check_rate_limits([bucket], now=fixed_ts)

    tasks = [attempt() for _ in range(15)]
    results = await asyncio.gather(*tasks)

    allowed = [r for r in results if r.allowed]
    denied = [r for r in results if not r.allowed]

    # Must be strictly 10 allowed, 5 denied.
    # If collision occurred in member generation, duplicate members would overwrite
    # and allow MORE than 10 requests.
    assert len(allowed) == 10
    assert len(denied) == 5
    # Verify mock redis recorded 10 distinct members in ZSET
    assert len(mock_redis.buckets["rl:test:same_ms:1"]) == 10


# ============================================================================
# 13. AUTHENTICATED AND ANONYMOUS UNIFIED RATE LIMIT
# ============================================================================

@pytest.mark.asyncio
async def test_authenticated_and_anonymous_unified_limits(mock_redis, client, monkeypatch):
    """Verify both authenticated and anonymous requests enforce the unified rate limit."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_SECOND", 50)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_OPEN", True)

    # Anonymous request receives 50 limit header
    resp_anon = await client.get("/api/v1/auth/roles", headers={"X-Forwarded-For": "203.0.113.80"})
    assert resp_anon.status_code == 200
    assert resp_anon.headers["X-RateLimit-Limit"] == "50"

    # Authenticated request receives 50 limit header
    token = create_access_token(subject=777)
    resp_auth = await client.get("/api/v1/auth/roles", headers={"Authorization": f"Bearer {token}"})
    assert resp_auth.status_code == 200
    assert resp_auth.headers["X-RateLimit-Limit"] == "50"


# ============================================================================
# 14. PRODUCTION DEFAULT 50 REQ/SEC ACROSS ALL APIS
# ============================================================================

@pytest.mark.asyncio
async def test_production_default_50_per_sec(mock_redis, client, monkeypatch):
    """Verify production default setting allows 50 requests/sec and blocks the 51st."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_SECOND", 50)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_OPEN", True)

    t_base = 1700000000.0
    headers = {"X-Forwarded-For": "203.0.113.99"}
    for i in range(50):
        with patch("time.time", return_value=t_base + i * 0.01):
            resp = await client.get("/api/v1/auth/roles", headers=headers)
            assert resp.status_code == 200, f"Request {i+1} failed"
            assert resp.headers["X-RateLimit-Limit"] == "50"
            assert int(resp.headers["X-RateLimit-Remaining"]) == 50 - (i + 1)

    with patch("time.time", return_value=t_base + 0.51):
        resp_51 = await client.get("/api/v1/auth/roles", headers=headers)
        assert resp_51.status_code == 429
        assert resp_51.headers["X-RateLimit-Limit"] == "50"
        assert resp_51.headers["X-RateLimit-Remaining"] == "0"
        assert "Too many requests" in resp_51.json()["detail"]


# ============================================================================
# 15. UNIFIED RATE LIMIT ACROSS ALL APIS A TO Z
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint,method,payload", [
    ("/api/v1/auth/verify-otp", "POST", {"phone": "9876543210", "otp": "123456"}),
    ("/api/v1/auth/reset-password", "POST", {"email": "user@hospital.com", "otp": "123456", "new_password": "Pass123!@#"}),
    ("/api/v1/auth/refresh-token", "POST", {"refresh_token": "fake.refresh"}),
    ("/api/v1/icu/telemetry", "POST", {"device_code": "DEV-01", "bed_id": 1, "heart_rate": 75.0, "spo2": 98.0, "temperature": 37.0, "blood_pressure_sys": 120.0, "blood_pressure_dia": 80.0, "respiratory_rate": 16.0}),
    ("/api/v1/patients/export?format=excel", "GET", None),
    ("/agent/v1/voice/incoming", "POST", None),
    ("/api/v1/ai/chat", "POST", {"message": "hello", "session_id": "sess-1"}),
])
async def test_all_apis_unified_rate_limit_a_to_z(enable_rate_limiting, mock_redis, client, endpoint, method, payload):
    """Verify that every API endpoint from A to Z enforces the unified rate limit."""
    client_ip = f"198.51.100.{(abs(hash(endpoint)) % 200) + 1}"
    headers = {"X-Forwarded-For": client_ip, "X-Device-API-Key": "dev_key_1"}

    t_base = 1700000000.0
    for i in range(10):
        with patch("time.time", return_value=t_base + i * 0.05):
            if method == "POST":
                resp = await client.post(endpoint, json=payload, headers=headers)
            else:
                resp = await client.get(endpoint, headers=headers)
            assert resp.status_code in (200, 201, 400, 401, 403, 404, 422), f"Req {i+1} on {endpoint} gave {resp.status_code}"
            assert resp.headers.get("X-RateLimit-Limit") == "10"

    # 11th request blocked by unified rate limit within same 1-second window (0.55s < 1.0s)
    with patch("time.time", return_value=t_base + 0.55):
        if method == "POST":
            resp_11 = await client.post(endpoint, json=payload, headers=headers)
        else:
            resp_11 = await client.get(endpoint, headers=headers)
        assert resp_11.status_code == 429
        assert resp_11.headers.get("X-RateLimit-Limit") == "10"
        assert resp_11.headers.get("X-RateLimit-Remaining") == "0"
        assert "Retry-After" in resp_11.headers




# ============================================================================
# 21. 2FA ATOMIC FAILED-ATTEMPTS ONLY LIMITING
# ============================================================================

@pytest.mark.asyncio
async def test_2fa_failed_attempts_rate_limit(monkeypatch):
    """Verify 2FA rate limiting only increments on failed attempts and locks out at threshold."""
    from app.services.auth_service import AuthService
    from app.schemas.auth_schema import TOTPLoginRequest
    from app.core.security import create_2fa_challenge_token
    from app.core.exceptions import UnauthorizedException
    from unittest.mock import AsyncMock

    mock_db = AsyncMock()
    service = AuthService(mock_db)

    # In-memory redis mock for 2fa
    cache_store = {}

    async def mock_cache_get(k):
        return cache_store.get(k)

    async def mock_cache_set(k, v, ttl=300):
        cache_store[k] = str(v)
        return True

    async def mock_cache_incr(k, ttl=300):
        curr = int(cache_store.get(k, 0)) + 1
        cache_store[k] = str(curr)
        return curr

    async def mock_cache_delete(k):
        cache_store.pop(k, None)
        return True

    monkeypatch.setattr("app.utils.redis_service.cache_get", mock_cache_get)
    monkeypatch.setattr("app.utils.redis_service.cache_set", mock_cache_set)
    monkeypatch.setattr("app.utils.redis_service.cache_incr", mock_cache_incr)
    monkeypatch.setattr("app.utils.redis_service.cache_delete", mock_cache_delete)
    monkeypatch.setattr(settings, "RATE_LIMIT_2FA_TARGET_LIMIT", 5)

    challenge_token, jti = create_2fa_challenge_token(123)
    cache_store[f"2fa_jti:{jti}"] = "valid"

    # Mock user and security settings
    fake_user = MagicMock(id=123, is_active=True, is_deleted=False)
    service.repo.get_by_id = AsyncMock(return_value=fake_user)
    service._is_user_deleted = AsyncMock(return_value=False)

    fake_sec = MagicMock(is_2fa_enabled=True, totp_secret_encrypted="enc", recovery_codes_hashed=[])
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=fake_sec)))

    # TOTP verify always fails for invalid code
    from app.services.totp_service import TOTPService
    monkeypatch.setattr(TOTPService, "decrypt_secret", lambda s: "SECRET")
    monkeypatch.setattr(TOTPService, "verify_totp", lambda s, c: False)

    req = TOTPLoginRequest(challenge_token=challenge_token, code="000000")

    # 5 failed attempts
    for i in range(5):
        with pytest.raises(UnauthorizedException) as exc:
            await service.verify_totp_login(req, ip_address="1.2.3.4")
        assert "Invalid TOTP" in str(exc.value)

    # 6th attempt is blocked by rate limiter
    with pytest.raises(UnauthorizedException) as exc:
        await service.verify_totp_login(req, ip_address="1.2.3.4")
    assert "Too many failed 2FA attempts" in str(exc.value)

