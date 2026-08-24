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
from app.services.hospital_voice_config_service import HospitalVoiceConfigService


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.production_checks import validate_production_settings
    from app.core.database import engine
    from app.utils.ngrok_tunnel import start_dev_tunnel, stop_dev_tunnel

    validate_production_settings()

    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    Path(settings.UPLOAD_DIR + "/doctors").mkdir(parents=True, exist_ok=True)
    Path(settings.SARVAM_TTS_CACHE_DIR).mkdir(parents=True, exist_ok=True)
    Path("app/static").mkdir(parents=True, exist_ok=True)
    await init_db()

    # Voice: warn if TWILIO_PHONE_NUMBER does not match any hospital inbound_did
    if settings.TWILIO_PHONE_NUMBER:
        try:
            async with AsyncSessionLocal() as session:
                await HospitalVoiceConfigService(session).validate_twilio_did_configuration(
                    settings.TWILIO_PHONE_NUMBER
                )
        except Exception as exc:
            from app.core.logger import logger
            logger.warning("voice_startup_did_check_failed: %s", exc)

    # Optional embedded ngrok (dev only). Default OFF — set ENABLE_NGROK_TUNNEL=true
    # or run `ngrok http 8000` separately and keep PUBLIC_BASE_URL in .env.
    public_url = start_dev_tunnel(port=8000)
    if public_url:
        print(f"\nngrok URL: {public_url}/agent/v1/voice/incoming")
        print("   (forwarding to 127.0.0.1:8000 — this uvicorn process)\n")

    # NOTE: Appointment reminders now run via Celery Beat, not in-process.
    # Start separately with:
    #   celery -A app.celery_app worker --loglevel=info
    #   celery -A app.celery_app beat --loglevel=info

    print("\nNexaCare API ready")
    print("   Docs:    http://localhost:8000/docs")
    print("   Health:  http://localhost:8000/health")
    print("   (Use localhost — browsers cannot open http://0.0.0.0:8000)\n")

    try:
        yield
    finally:
        stop_dev_tunnel()
        await engine.dispose()


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