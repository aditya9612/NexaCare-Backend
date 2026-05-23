import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.api import api_router
from app.core.config import settings
from app.core.database import AsyncSessionLocal, init_db
from app.middleware.exception_middleware import ExceptionMiddleware
from app.middleware.logging_middleware import LoggingMiddleware
from app.middleware.rbac_middleware import RBACMiddleware
from app.websocket.chat_socket import router as chat_ws_router
from app.websocket.notification_socket import router as notification_ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    Path("app/static").mkdir(parents=True, exist_ok=True)
    await init_db()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.state.db_factory = AsyncSessionLocal

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LoggingMiddleware)
app.add_middleware(ExceptionMiddleware)
app.add_middleware(RBACMiddleware)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)
app.include_router(chat_ws_router)
app.include_router(notification_ws_router)

static_dir = Path("app/static")
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "app": settings.APP_NAME}
