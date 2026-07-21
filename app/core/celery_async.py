"""Run async coroutines from Celery workers safely.

SQLAlchemy async engines bind to the event loop that first uses them.
Celery calls ``asyncio.run()`` per task (new loop each time), which causes:
``RuntimeError: Task ... got Future attached to a different loop``.

Dispose the shared engine after each task so the next ``asyncio.run`` gets a clean loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import TypeVar

from app.core.database import engine

T = TypeVar("T")


def run_celery_async(coro: Coroutine[object, object, T]) -> T:
    """Execute an async coroutine inside a Celery task with a fresh event loop."""

    async def _runner() -> T:
        try:
            return await coro
        finally:
            await engine.dispose()

    return asyncio.run(_runner())
