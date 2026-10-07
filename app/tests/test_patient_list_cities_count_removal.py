import uuid
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.models.hospital_model import Hospital
from app.models.patient_model import Patient
from app.core.database import AsyncSessionLocal, engine
from app.core.dependencies import get_current_active_user, get_current_user


@pytest.fixture(autouse=True)
async def cleanup_engine():
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_patient_list_cities_count_absent():
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as db:
        patient = Patient(
            first_name=f"John_{uid}",
            last_name="Doe",
            patient_code=f"PAT_{uid}",
            gender="Male",
            status="active",
            city="New York",
        )
        db.add(patient)
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
                resp = await ac.get("/api/v1/patients?page=1&size=20")

    app.dependency_overrides.clear()

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["success"] is True
    data = body["data"]

    # Verify cities_count is NOT present
    assert "cities_count" not in data, "cities_count field should be completely removed from GET /api/v1/patients response"

    # Verify all expected fields ARE present
    expected_fields = [
        "items", "total", "page", "size", "pages",
        "active_count", "inactive_count", "new_today", "this_month",
        "ipd", "opd", "today_discharge"
    ]
    for field in expected_fields:
        assert field in data, f"Expected field {field} to be present in response"
