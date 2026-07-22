import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.api import api_router
from app.api.v1.routes.bed_allocation_routes import router as bed_allocation_router
from app.core.config import settings
import app.core.logger  # noqa: F401 — configure logging before DB engine
from app.core.database import AsyncSessionLocal, init_db
from app.middleware.exception_middleware import ExceptionMiddleware
from app.middleware.logging_middleware import LoggingMiddleware
from app.middleware.rbac_middleware import RBACMiddleware
from app.websocket.chat_socket import router as chat_ws_router
from app.websocket.notification_socket import router as notification_ws_router
from app.agent.router import router as agent_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.production_checks import validate_production_settings

    validate_production_settings()

    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    Path(settings.UPLOAD_DIR + "/doctors").mkdir(parents=True, exist_ok=True)
    Path("app/static").mkdir(parents=True, exist_ok=True)
    await init_db()

    # Start ngrok tunnel for Twilio webhooks (dev only — never in production)
    if (settings.APP_ENV or "").lower() not in ("production", "prod"):
        try:
            from pyngrok import ngrok, conf
            ngrok_token = settings.NGROK_AUTH_TOKEN or os.getenv("NGROK_AUTH_TOKEN")
            if ngrok_token:
                ngrok.kill()  # kill any existing tunnel first
                conf.get_default().auth_token = ngrok_token
                # Bind IPv4 loopback explicitly. On Windows, ngrok.connect(8000) can
                # target [::1]:8000, which may be owned by Docker/WSL — not this uvicorn
                # process (0.0.0.0:8000). That routes Twilio to a different app instance
                # (often APP_ENV=production with SKIP_VOICE_WEBHOOK_AUTH=false).
                tunnel = ngrok.connect("127.0.0.1:8000", "http")
                public_url = tunnel.public_url
                os.environ["PUBLIC_BASE_URL"] = public_url
                import logging
                logging.getLogger("nexacare").info(
                    f"ngrok tunnel: {public_url} -> 127.0.0.1:8000"
                )
                print(f"\n🌐 ngrok URL: {public_url}/agent/v1/voice/incoming")
                print("   (forwarding to 127.0.0.1:8000 — this uvicorn process)\n")
            else:
                print("⚠️  NGROK_AUTH_TOKEN not set — skipping ngrok tunnel")
        except Exception as e:
            print(f"⚠️  ngrok failed to start: {e}")

    # NOTE: Appointment reminders now run via Celery Beat, not in-process.
    # Start separately with:
    #   celery -A app.celery_app worker --loglevel=info
    #   celery -A app.celery_app beat --loglevel=info

    print("\n✅ NexaCare API ready")
    print("   Docs:    http://localhost:8000/docs")
    print("   Health:  http://localhost:8000/health")
    print("   (Use localhost — browsers cannot open http://0.0.0.0:8000)\n")

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
app.include_router(bed_allocation_router, prefix="/api", tags=["Bed Allocation"])
app.include_router(chat_ws_router)
app.include_router(notification_ws_router)
app.include_router(agent_router, prefix="/agent/v1/voice")

static_dir = Path("app/static")
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

uploads_dir = Path(settings.UPLOAD_DIR)
if uploads_dir.exists():
    app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "app": settings.APP_NAME}