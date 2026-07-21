"""Go-live gate checks (run inside API container):

docker compose exec api python scripts/go_live_gate.py
"""

from __future__ import annotations

import asyncio
import sys
import time
import urllib.request


def check_health() -> None:
    with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5) as resp:
        body = resp.read().decode()
        assert resp.status == 200 and "ok" in body, body
    print("PASS health")


def check_settings() -> None:
    from app.core.config import settings
    from app.core.production_checks import live_telephony_ready, validate_production_settings

    validate_production_settings()
    print("PASS production_settings")
    ready, issues = live_telephony_ready()
    if not ready:
        print("FAIL live_telephony:", "; ".join(issues))
        raise SystemExit(2)
    print("PASS live_telephony")


async def check_schema() -> None:
    from sqlalchemy import text
    from app.core.database import AsyncSessionLocal

    required = [
        "hospital_voice_configs",
        "hospital_faqs",
        "hospital_policies",
        "hospital_voice_documents",
        "voice_callback_tickets",
    ]
    async with AsyncSessionLocal() as db:
        rev = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        print("alembic_version", rev)
        assert rev == "b2c3d4e5f6a7", rev
        for table in required:
            n = (
                await db.execute(
                    text(
                        "SELECT COUNT(*) FROM information_schema.tables "
                        "WHERE table_schema=DATABASE() AND table_name=:t"
                    ),
                    {"t": table},
                )
            ).scalar()
            assert int(n or 0) == 1, f"missing {table}"
        nullable = (
            await db.execute(
                text(
                    "SELECT IS_NULLABLE FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='voice_calls' "
                    "AND COLUMN_NAME='patient_id'"
                )
            )
        ).scalar()
        assert nullable == "YES", nullable
    print("PASS schema")


async def check_celery_task() -> None:
    from app.tasks.voice_tasks import process_pending_calls

    process_pending_calls.delay()
    print("PASS celery_enqueue_pending_calls")


async def check_redis() -> None:
    from app.utils.redis_service import cache_set, cache_get

    key = f"voice:golive:{int(time.time())}"
    ok = await cache_set(key, {"ok": True}, ttl=60)
    assert ok, "redis set failed"
    val = await cache_get(key)
    assert val and val.get("ok") is True
    print("PASS redis")


async def main() -> int:
    check_health()
    check_settings()
    await check_schema()
    await check_redis()
    await check_celery_task()
    print("GO_LIVE_GATE_OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except SystemExit:
        raise
    except Exception as exc:
        print("GO_LIVE_GATE_FAIL", exc)
        raise SystemExit(1) from exc
