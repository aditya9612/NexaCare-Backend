from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.logger import logger


class ExceptionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Unhandled error: %s", exc)
            return JSONResponse(status_code=500, content={"detail": "Internal server error"})
