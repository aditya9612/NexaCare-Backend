from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
import traceback

from app.core.logger import logger
from app.core.config import settings


class ExceptionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=exc.headers
            )
        except Exception as exc:
            logger.exception("Unhandled error: %s", exc)
            
            content = {"detail": "Internal server error"}
            return JSONResponse(status_code=500, content=content)

