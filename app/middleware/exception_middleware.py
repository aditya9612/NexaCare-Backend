import traceback
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.logger import logger


class ExceptionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=exc.headers,
            )
        except (RequestValidationError, ValidationError) as exc:
            logger.warning("Validation error on %s: %s", request.url.path, exc)
            errors = exc.errors() if hasattr(exc, "errors") else str(exc)
            return JSONResponse(
                status_code=422,
                content={"detail": errors},
            )
        except IntegrityError as exc:
            logger.error("Database integrity error on %s: %s", request.url.path, exc)
            orig_msg = str(getattr(exc, "orig", exc)).lower()
            if "foreign key constraint fails" in orig_msg:
                detail = "Invalid reference ID: One or more referenced records (such as Bed, Patient, Doctor, or User) do not exist."
            elif "duplicate entry" in orig_msg:
                detail = "Duplicate entry error: A record with these unique details already exists."
            else:
                detail = "Database integrity error: Constraint violation."
            return JSONResponse(status_code=400, content={"detail": detail})
        except ValueError as exc:
            logger.warning("Value error on %s: %s", request.url.path, exc)
            return JSONResponse(status_code=400, content={"detail": str(exc)})
        except Exception as exc:
            logger.exception("Unhandled error on %s: %s", request.url.path, exc)
            error_detail = str(exc) if getattr(settings, "DEBUG", False) else f"Internal server error: {str(exc)}"
            return JSONResponse(status_code=500, content={"detail": error_detail})

