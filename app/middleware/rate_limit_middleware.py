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

    AUTH_PROTECTED_PATHS = {
        "/api/v1/auth/login",
        "/auth/login",
        "/api/v1/auth/send-otp",
        "/auth/send-otp",
        "/api/v1/auth/verify-otp",
        "/auth/verify-otp",
        "/api/v1/auth/forgot-password",
        "/auth/forgot-password",
        "/api/v1/auth/reset-password",
        "/auth/reset-password",
        "/api/v1/auth/refresh-token",
        "/auth/refresh-token",
        "/api/v1/auth/refresh",
        "/auth/refresh",
        "/api/v1/auth/login/2fa",
        "/auth/login/2fa",
        "/api/v1/auth/verify-2fa",
        "/auth/verify-2fa",
    }

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

        # 3. Policy routing & bucket building: Unified 50 req/sec across all APIs (A to Z)
        method = request.method.upper()
        is_auth_route = path in self.AUTH_PROTECTED_PATHS

        limit = getattr(settings, "RATE_LIMIT_PER_SECOND", 50)
        window = 1  # 1 second sliding window

        # Client identification: isolated per user if authenticated, per client IP if anonymous
        bucket_key = f"rl:api:usr:{user_id}:{window}" if user_id else f"rl:api:ip:{client_ip}:{window}"
        buckets: List[RateLimitBucket] = [
            RateLimitBucket(
                key=bucket_key,
                limit=limit,
                window=window,
            )
        ]



        # 4. Execute atomic rate-limit check via RateLimitService
        result: RateLimitResult = await RateLimitService.check_rate_limits(
            buckets,
            fail_open=False if is_auth_route else None,
        )

        # 5. Handle rate limit rejection or service unavailability
        if not result.allowed:
            if getattr(result, "unavailable", False):
                logger.error(
                    "RateLimiter backend offline on protected route: path=%s method=%s",
                    path,
                    method,
                )
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": "Authentication service temporarily unavailable. Please try again shortly."
                    },
                    headers={
                        "Retry-After": "5",
                    },
                )

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
