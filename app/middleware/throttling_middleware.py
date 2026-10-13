import fnmatch
from typing import Set, Tuple
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.logger import logger
from app.services.throttling_service import ThrottlingService


class ThrottlingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces instantaneous concurrency limits on heavy endpoints
    (such as PDF exports, downloads, and bulk operations) to protect server capacity.
    """

    FAST_PATH_EXEMPT_PATHS: Set[str] = {
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

    FAST_PATH_EXEMPT_PREFIXES: Tuple[str, ...] = (
        "/static/",
        "/uploads/",
        "/ws/",
    )

    HEAVY_PATH_PATTERNS: Tuple[str, ...] = (
        "*/export",
        "*/download",
        "*/bulk-template",
        "*/bulk-upload",
    )

    # Concurrency configuration for heavy resource endpoints
    HEAVY_MAX_CONCURRENCY: int = 3
    HEAVY_SLOT_TTL_SECONDS: int = 30
    HEAVY_RETRY_AFTER_SECONDS: int = 2

    async def dispatch(self, request: Request, call_next) -> Response:
        if not getattr(settings, "RATE_LIMIT_ENABLED", True):
            return await call_next(request)

        if request.scope.get("type") != "http":
            return await call_next(request)

        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path

        # 1. Fast-path exemptions
        if path in self.FAST_PATH_EXEMPT_PATHS or any(path.startswith(p) for p in self.FAST_PATH_EXEMPT_PREFIXES):
            return await call_next(request)

        # 2. Check if the path targets a heavy resource requiring concurrency throttling
        is_heavy = any(fnmatch.fnmatch(path, pattern) or path.endswith(pattern.lstrip("*")) for pattern in self.HEAVY_PATH_PATTERNS)

        if not is_heavy:
            return await call_next(request)

        # 3. Apply concurrency throttling for heavy resource endpoints
        resource_key = f"heavy:{path}"
        acquire_res = await ThrottlingService.acquire_slot(
            resource_key=resource_key,
            max_concurrency=self.HEAVY_MAX_CONCURRENCY,
            slot_ttl=self.HEAVY_SLOT_TTL_SECONDS,
            retry_after=self.HEAVY_RETRY_AFTER_SECONDS,
        )

        if not acquire_res.allowed:
            logger.warning(
                "ThrottlingMiddleware: Concurrency limit reached for path=%s (method=%s). Returning HTTP 429.",
                path,
                request.method,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Processing capacity full. Concurrency limit reached for this resource."
                },
                headers={
                    "Retry-After": str(acquire_res.retry_after),
                },
            )

        # 4. Process request with guaranteed slot cleanup
        token = acquire_res.token
        try:
            return await call_next(request)
        finally:
            await ThrottlingService.release_slot(resource_key, token)
