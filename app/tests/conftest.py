import asyncio
import os
import sys
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import engine, get_db
from app.main import app

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(autouse=True)
def guard_persistent_database(request):
    """
    Guarantees that integration tests cannot inadvertently write to the persistent development database 'nexacare'.
    If a test attempts live database writes, it must explicitly run against an isolated test database
    configured via TEST_DATABASE_URL ending with '_test'.
    """
    if "test_notifications_e2e" in request.node.nodeid:
        test_db_url = os.getenv("TEST_DATABASE_URL", "")
        if not test_db_url or not test_db_url.split("/")[-1].split("?")[0].endswith("_test"):
            pytest.skip(
                "SAFETY BLOCK: Live integration test writing to persistent development database 'nexacare' is blocked. "
                "Set TEST_DATABASE_URL to an isolated test database (ending with '_test') to enable."
            )


@pytest.fixture(autouse=True)
async def cleanup_db_engine():
    await engine.dispose()
    yield
    await engine.dispose()



@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    mock_session = AsyncMock(spec=AsyncSession)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _mock_rbac_permissions():
    with patch(
        "app.core.dependencies.RBACRepository.get_user_permissions",
        new_callable=AsyncMock,
        return_value=[],
    ):
        yield
