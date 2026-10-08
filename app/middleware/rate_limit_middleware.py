import fnmatch
import ipaddress
import json
from typing import Dict, List, Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.logger import logger
from app.core.security import decode_token
from app.services.rate_limit_service import (
    RateLimitBucket,
    RateLimitResult,
    RateLimitService,
    hash_identifier,
)
from app.utils.phone_utils import normalize_phone

# Cache parsed trusted proxy networks
_TRUSTED_NETWORKS: Optional[List[ipaddress.IPv4Network | ipaddress.IPv6Network]] = None


def _get_trusted_networks() -> List[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    global _TRUSTED_NETWORKS
    if _TRUSTED_NETWORKS is not None:
        return _TRUSTED_NETWORKS

    networks = []
    for item in settings.TRUSTED_PROXIES:
        raw = item.strip()
        if not raw:
            continue
        try:
            if "/" in raw:
                networks.append(ipaddress.ip_network(raw, strict=False))
            else:
                ip = ipaddress.ip_address(raw)
                networks.append(ipaddress.ip_network(f"{ip}/{ip.max_prefixlen}"))
        except ValueError:
            pass
    _TRUSTED_NETWORKS = networks
    return _TRUSTED_NETWORKS


def _is_trusted_proxy(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    for net in _get_trusted_networks():
        if ip_obj in net:
            return True
    return False


def get_validated_client_ip(request: Request) -> str:
    """
    Safely resolves client IP without trusting spoofed X-Forwarded-For headers.
    Only processes X-Forwarded-For if request.client.host is a configured trusted proxy.
    """
    peer_host = request.client.host if request.client else "127.0.0.1"
    try:
        peer_ip = ipaddress.ip_address(peer_host)
    except ValueError:
        return "127.0.0.1"

    # If the direct peer is not in trusted proxy network, do not trust any forwarded headers
    if not _is_trusted_proxy(peer_ip):
        return str(peer_ip)

    xff = request.headers.get("x-forwarded-for")
    if not xff:
        return str(peer_ip)

    raw_ips = [x.strip() for x in xff.split(",") if x.strip()]
    if not raw_ips:
        return str(peer_ip)

    # Process right-to-left: step back past trusted proxies until first untrusted IP
    for candidate_str in reversed(raw_ips):
        try:
            cand_ip = ipaddress.ip_address(candidate_str)
        except ValueError:
            continue
        if _is_trusted_proxy(cand_ip):
            continue
        return str(cand_ip)

    # If all IPs in XFF were trusted proxies, use the leftmost IP
    return raw_ips[0]


def extract_user_id_from_jwt(request: Request) -> Optional[str]:
    """
    Extracts user_id from Authorization Bearer token without database lookup.
    Fails safely to None if missing, expired, or malformed.
    """
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None

    token = auth_header[7:].strip()
    if not token:
        return None

    try:
        payload = decode_token(token)
        if payload.get("type") == "access":
            sub = payload.get("sub")
            if sub is not None:
                return str(sub)
    except Exception:
        # Invalid or expired token: rate limiter treats as anonymous;
        # downstream auth dependency will handle returning HTTP 401.
        return None

    return None


async def _extract_json_body_safe(request: Request) -> Tuple[Request, Optional[dict]]:
    """
    Safely extracts JSON body and re-injects receive stream so downstream FastAPI
    can continue to parse the body without error.
    """
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 65536:  # 64 KB limit for auth payloads
                return request, None
        except ValueError:
            pass

    try:
        body_bytes = await request.body()
    except Exception:
        return request, None

    async def receive():
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    new_request = Request(request.scope, receive=receive)

    if not body_bytes:
        return new_request, None

    try:
        data = json.loads(body_bytes.decode("utf-8"))
        if isinstance(data, dict):
            return new_request, data
    except Exception:
        pass

    return new_request, None


class RateLimitMiddleware(BaseHTTPMiddleware):
    FAST_PATH_EXEMPT_PATHS = {
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        f"{settings.API_V1_PREFIX}/openapi.json",
        f"{settings.API_V1_PREFIX}/docs",
        f"{settings.API_V1_PREFIX}/redoc",
        f"{settings.API_V1_PREFIX}/health",
        "/favicon.ico",
    }

    FAST_PATH_EXEMPT_PREFIXES = (
        "/static/",
        "/uploads/",
        "/ws/",
    )

    async def dispatch(self, request: Request, call_next) -> Response:
        # 1. Fast-path exemptions
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        if request.scope.get("type") != "http":
            return await call_next(request)

        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if path in self.FAST_PATH_EXEMPT_PATHS or any(path.startswith(p) for p in self.FAST_PATH_EXEMPT_PREFIXES):
            return await call_next(request)

        # 2. Determine client identification
        client_ip = get_validated_client_ip(request)
        user_id = extract_user_id_from_jwt(request)
        user_or_ip = f"usr:{user_id}" if user_id else f"ip:{client_ip}"

        # 3. Policy routing & bucket building
        buckets: List[RateLimitBucket] = []
        body_data: Optional[dict] = None

        method = request.method.upper()

        # Route A: Login (/api/v1/auth/login)
        if method == "POST" and (path == "/api/v1/auth/login" or path == "/auth/login"):
            request, body_data = await _extract_json_body_safe(request)
            target = None
            if body_data:
                target = body_data.get("email") or body_data.get("phone")
                if target and "@" not in str(target):
                    target = normalize_phone(str(target))

            target_hash = hash_identifier(target) if target else "anonymous"
            # Dual bucket: IP burst (20/min) + Target account (5/min)
            buckets.append(RateLimitBucket(key=f"rl:auth:login:target:{target_hash}:60", limit=5, window=60))
            buckets.append(RateLimitBucket(key=f"rl:auth:login:ip:{client_ip}:60", limit=20, window=60))

        # Route B: Send OTP (/api/v1/auth/send-otp)
        elif method == "POST" and (path == "/api/v1/auth/send-otp" or path == "/auth/send-otp"):
            request, body_data = await _extract_json_body_safe(request)
            target = None
            if body_data:
                target = body_data.get("phone") or body_data.get("email")
                if target and "@" not in str(target):
                    target = normalize_phone(str(target))

            target_hash = hash_identifier(target) if target else "anonymous"
            # Dual bucket: Target phone (3 / 10m) + IP burst (10 / 1h)
            buckets.append(RateLimitBucket(key=f"rl:otp:send:target:{target_hash}:600", limit=3, window=600))
            buckets.append(RateLimitBucket(key=f"rl:otp:send:ip:{client_ip}:3600", limit=10, window=3600))

        # Route C: Verify OTP (/api/v1/auth/verify-otp)
        elif method == "POST" and (path == "/api/v1/auth/verify-otp" or path == "/auth/verify-otp"):
            request, body_data = await _extract_json_body_safe(request)
            target = None
            if body_data:
                target = body_data.get("phone") or body_data.get("email")
                if target and "@" not in str(target):
                    target = normalize_phone(str(target))

            target_hash = hash_identifier(target) if target else "anonymous"
            # Target + IP combined bucket: 5 / 10m
            buckets.append(RateLimitBucket(key=f"rl:otp:verify:{target_hash}:{client_ip}:600", limit=5, window=600))

        # Route D: Password Reset (/api/v1/auth/reset-password)
        elif method == "POST" and (path == "/api/v1/auth/reset-password" or path == "/auth/reset-password"):
            request, body_data = await _extract_json_body_safe(request)
            target = None
            if body_data:
                target = body_data.get("email") or body_data.get("phone")

            target_hash = hash_identifier(target) if target else "anonymous"
            buckets.append(RateLimitBucket(key=f"rl:auth:reset:{target_hash}:{client_ip}:600", limit=5, window=600))

        # Route E: Token Refresh (/api/v1/auth/refresh-token)
        elif method == "POST" and (path in ("/api/v1/auth/refresh-token", "/auth/refresh-token", "/api/v1/auth/refresh")):
            buckets.append(RateLimitBucket(key=f"rl:auth:refresh:ip:{client_ip}:60", limit=30, window=60))

        # Route F: ICU Telemetry Stream (/api/v1/icu/telemetry)
        elif path.startswith("/api/v1/icu/telemetry") or path.startswith("/icu/telemetry"):
            dev_key = request.headers.get("x-device-api-key") or request.headers.get("authorization") or client_ip
            buckets.append(RateLimitBucket(key=f"rl:icu:dev:{hash_identifier(dev_key)}:60", limit=600, window=60))

        # Route G: Export Endpoints (*/export)
        elif fnmatch.fnmatch(path, "*/export") or path.endswith("/export"):
            buckets.append(RateLimitBucket(key=f"rl:export:{user_or_ip}:60", limit=10, window=60))

        # Route H: Download Endpoints (*/download)
        elif fnmatch.fnmatch(path, "*/download") or path.endswith("/download"):
            buckets.append(RateLimitBucket(key=f"rl:download:{user_or_ip}:60", limit=10, window=60))

        # Route I: AI Chat (/api/v1/ai/chat/*)
        elif path.startswith("/api/v1/ai/chat") or path.startswith("/ai/chat"):
            buckets.append(RateLimitBucket(key=f"rl:ai:chat:{user_or_ip}:60", limit=30, window=60))

        # Route J: Telephony Webhooks (/agent/v1/voice/*, */twiml/*)
        elif path.startswith("/agent/v1/voice") or "twiml" in path or "exotel" in path:
            provider = "exotel" if "exotel" in path else "twilio"
            buckets.append(RateLimitBucket(key=f"rl:voice:webhook:{provider}:{client_ip}:60", limit=120, window=60))

        # Route K: Global Default Policy (All normal APIs)
        else:
            default_limit = settings.RATE_LIMIT_DEFAULT_PER_MINUTE
            if user_id:
                buckets.append(RateLimitBucket(key=f"rl:api:usr:{user_id}:60", limit=default_limit, window=60))
            else:
                buckets.append(RateLimitBucket(key=f"rl:api:ip:{client_ip}:60", limit=default_limit, window=60))

        # 4. Execute atomic rate-limit check via RateLimitService
        result: RateLimitResult = await RateLimitService.check_rate_limits(buckets)

        # 5. Handle rate limit rejection
        if not result.allowed:
            logger.warning(
                "Rate limit exceeded: path=%s method=%s client_ip=%s user=%s retry_after=%s",
                path,
                method,
                client_ip,
                user_id or "anonymous",
                result.retry_after,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"Too many requests. Please try again in {result.retry_after} seconds."
                },
                headers={
                    "Retry-After": str(result.retry_after),
                    "X-RateLimit-Limit": str(result.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(result.reset_epoch),
                },
            )

        # 6. Proceed to downstream handler & attach rate-limit headers to response
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(result.limit)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        response.headers["X-RateLimit-Reset"] = str(result.reset_epoch)

        return response
