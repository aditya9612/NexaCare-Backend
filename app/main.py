import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.api import api_router
from app.api.v1.routes.bed_allocation_routes import router as bed_allocation_router
from app.core.config import settings
from app.core.database import AsyncSessionLocal, init_db
from app.middleware.exception_middleware import ExceptionMiddleware
from app.middleware.logging_middleware import LoggingMiddleware
from app.middleware.rbac_middleware import RBACMiddleware
from app.websocket.chat_socket import router as chat_ws_router
from app.websocket.notification_socket import router as notification_ws_router
from app.agent import agent_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    Path(settings.UPLOAD_DIR + "/doctors").mkdir(parents=True, exist_ok=True)
    Path("app/static").mkdir(parents=True, exist_ok=True)
    await init_db()
    
    ngrok_token = getattr(settings, "NGROK_AUTH_TOKEN", None) or os.getenv("NGROK_AUTH_TOKEN")
    if ngrok_token and os.getenv("ENVIRONMENT", "development") == "development":
        try:
            from pyngrok import ngrok, conf
            conf.get_default().auth_token = ngrok_token
            port = int(os.getenv("PORT", 8000))
            tunnel = ngrok.connect(port, "http")
            public_url = tunnel.public_url
 
            # Store URL so router.py can use it in TwiML responses
            app.state.agent_base_url = public_url
 
            import logging
            logger = logging.getLogger("nexacare.main")
            logger.info("=" * 60)
            logger.info("  NexaCare AI Voice Agent — ngrok active")
            logger.info(f"  Public URL : {public_url}")
            logger.info(f"  Twilio webhook → {public_url}/agent/v1/voice/incoming")
            logger.info("=" * 60)
        except Exception as e:
            import logging
            logging.getLogger("nexacare.main").warning(f"ngrok failed to start: {e}")
            app.state.agent_base_url = os.getenv("BASE_URL", "http://localhost:8000")
    else:
        # Production: set BASE_URL env var to your real domain
        app.state.agent_base_url = os.getenv("BASE_URL", "http://localhost:8000")
 
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
