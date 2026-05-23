import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.logger import logger


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info("%s %s - %s (%.2fms)", request.method, request.url.path, response.status_code, duration_ms)
        return response
