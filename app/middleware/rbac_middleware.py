from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.security import decode_token
from app.repositories.rbac_repository import RBACRepository


class RBACMiddleware(BaseHTTPMiddleware):
    """Optional path-level permission check using X-Required-Permission header."""

    PUBLIC_PREFIXES = (
        "/docs",
        "/redoc",
        "/openapi.json",
        "/health",
        "/api/v1/auth/roles",
        "/api/v1/auth/register",
        "/api/v1/auth/send-otp",
        "/api/v1/auth/login",
        "/api/v1/auth/forgot-password",
        "/api/v1/auth/reset-password",
        "/api/v1/auth/verify-otp",
        "/api/v1/auth/activate",
        "/api/v1/whatsapp/webhook",
        "/ws/",
    )

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in self.PUBLIC_PREFIXES) or path.startswith("/static"):
            return await call_next(request)

        required_permission = request.headers.get("X-Required-Permission")
        if not required_permission:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

        token = auth_header.split(" ", 1)[1]
        try:
            payload = decode_token(token)
            user_id = int(payload["sub"])
        except (ValueError, KeyError, TypeError):
            return JSONResponse(status_code=401, content={"detail": "Invalid token"})

        db_factory = request.app.state.db_factory
        async with db_factory() as db:
            from app.repositories.auth_repository import AuthRepository

            user = await AuthRepository(db).get_by_id(user_id)
            if not user:
                return JSONResponse(status_code=401, content={"detail": "User not found"})
            permissions = await RBACRepository(db).get_user_permissions(user.role_id)
            if required_permission not in permissions:
                return JSONResponse(status_code=403, content={"detail": "Permission denied"})

        return await call_next(request)
