from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class AuthMiddleware(BaseHTTPMiddleware):
    PUBLIC_PATHS = {
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
        "/api/v1/auth/refresh-token",
    }

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in self.PUBLIC_PATHS or path.startswith("/static"):
            return await call_next(request)
        return await call_next(request)
