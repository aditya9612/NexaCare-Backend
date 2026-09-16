from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.dependencies import get_db
from app.utils.redis_service import get_redis
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/faq-ai", tags=["FAQ AI Health"])

@router.get("/health")
async def faq_ai_health(db: AsyncSession = Depends(get_db)):
    dependencies = {
        "database": "unknown",
        "redis": "unknown",
        "celery": "unknown",
        "openai": "not_probed"
    }
    
    # 1. Database Check
    try:
        await db.execute(text("SELECT 1"))
        dependencies["database"] = "ok"
    except Exception as exc:
        logger.warning(f"FAQ AI Health - DB Check Failed: {exc}")
        dependencies["database"] = "unavailable"

    # 2. Redis Check
    try:
        redis_client = await get_redis()
        if redis_client:
            await redis_client.ping()
            dependencies["redis"] = "ok"
        else:
            dependencies["redis"] = "unavailable"
    except Exception as exc:
        logger.warning(f"FAQ AI Health - Redis Check Failed: {exc}")
        dependencies["redis"] = "unavailable"
        
    # 3. Celery Check
    # A safe celery ping is technically complex without exposing timeout risks on HTTP threads.
    # We report 'unknown' rather than a fake 'ok' based on the broker.
    dependencies["celery"] = "unknown"

    # 4. Determine Readiness Status
    status = "ok"
    if dependencies["database"] != "ok":
        status = "unavailable"
    elif dependencies["redis"] != "ok":
        # Redis is fail-open for FAQ AI, but degraded health is appropriate
        status = "degraded"

    # Return 200 OK even if degraded/unavailable so we don't break simple HTTP pingers,
    # or return 503 if unavailable?
    # The prompt: "Determine which dependencies are truly required... DB is required, Redis is optional. 
    # Do not automatically return 503 for an optional dependency."
    # We will return 503 ONLY if DB is down.
    status_code = 200 if status != "unavailable" else 503
    
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status_code, content={
        "status": status,
        "dependencies": dependencies
    })
