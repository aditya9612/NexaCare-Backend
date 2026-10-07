import uuid
import pytest
from datetime import datetime, timedelta, timezone
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.models.patient_model import Patient
from app.core.database import AsyncSessionLocal, engine
from app.core.dependencies import get_current_active_user, get_current_user
from app.utils.helpers import utc_now, get_today_ist


@pytest.fixture(autouse=True)
async def cleanup_engine():
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_patient_list_new_today_count():
    uid = uuid.uuid4().hex[:8]

    # Create one patient created TODAY (now) and one created 10 days ago
    async with AsyncSessionLocal() as db:
        p_today = Patient(
            first_name=f"Today_{uid}",
            last_name="Patient",
            patient_code=f"PAT_TODAY_{uid}",
            gender="Female",
            status="active",
            created_at=utc_now(),
        )
        p_past = Patient(
            first_name=f"Past_{uid}",
            last_name="Patient",
            patient_code=f"PAT_PAST_{uid}",
            gender="Male",
            status="active",
            created_at=utc_now() - timedelta(days=10),
        )
        db.add_all([p_today, p_past])
        await db.commit()

    class FakeUser:
        id = 9999
        role_id = 1
        hospital_id = 1
        is_active = True
        is_verified = True
        email = f"admin_{uid}@test.com"

        class role:
            name = "super_admin"

    fake_user = FakeUser()
    app.dependency_overrides[get_current_active_user] = lambda: fake_user
    app.dependency_overrides[get_current_user] = lambda: fake_user

    from unittest.mock import patch, AsyncMock
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch("app.core.dependencies.require_permission") as mock_perm:
            mock_perm.return_value = lambda: fake_user
            with patch(
                "app.repositories.rbac_repository.RBACRepository.get_user_permissions",
                new=AsyncMock(return_value=["patients:read"]),
            ):
                resp = await ac.get("/api/v1/patients?page=1&size=50")

    app.dependency_overrides.clear()

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["success"] is True
    data = body["data"]

    # new_today field must be present
    assert "new_today" in data, "new_today must be present in response data"
    assert isinstance(data["new_today"], int)

    # new_today must count p_today (at least 1)
    assert data["new_today"] >= 1

    # Verify new_today is strictly <= total and <= active_count
    assert data["new_today"] <= data["total"]
