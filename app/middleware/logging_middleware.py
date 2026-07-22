import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.logger import logger

_trace = logging.getLogger("nexacare.http")


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/agent/v1/voice"):
            _trace.info(
                "TRACE middleware ENTER %s %s",
                request.method,
                path,
            )
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info("%s %s - %s (%.2fms)", request.method, path, response.status_code, duration_ms)
        if path.startswith("/agent/v1/voice"):
            _trace.info(
                "TRACE middleware EXIT %s %s status=%s reject_hdr=%r (%.2fms)",
                request.method,
                path,
                response.status_code,
                response.headers.get("X-Voice-Auth-Reject"),
                duration_ms,
            )
        return response
