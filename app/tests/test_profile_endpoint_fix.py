import pytest
from datetime import datetime
from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user, get_db
from app.main import app
from app.models.user_model import User


@pytest.mark.asyncio
async def test_update_profile_with_empty_dob():
    mock_user = User(
        id=1,
        user_code="USR-001",
        full_name="Hospital Admin",
        email="admin@nexacare.com",
        phone="9876543210",
        role_id=1,
        is_active=True,
        is_verified=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    mock_user.role = AsyncMock()
    mock_user.role.name = "hospital_admin"

    mock_db = AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Test multipart/form-data with empty date_of_birth string
        response = await ac.put(
            "/api/v1/auth/profile",
            data={
                "full_name": "Hospital Admin Updated",
                "date_of_birth": "",
                "phone": "9876543210",
            },
        )
        assert response.status_code == 200, f"Expected 200 but got {response.status_code}: {response.text}"
        res_json = response.json()
        assert res_json["message"] == "Profile updated"
        assert res_json["data"]["full_name"] == "Hospital Admin Updated"
        assert res_json["data"]["date_of_birth"] is None

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_profile_with_valid_dob():
    mock_user = User(
        id=1,
        user_code="USR-001",
        full_name="Hospital Admin",
        email="admin@nexacare.com",
        phone="9876543210",
        role_id=1,
        is_active=True,
        is_verified=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    mock_user.role = AsyncMock()
    mock_user.role.name = "hospital_admin"

    mock_db = AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Test multipart/form-data with valid date_of_birth string
        response = await ac.put(
            "/api/v1/auth/profile",
            data={
                "full_name": "Hospital Admin Updated",
                "date_of_birth": "1990-05-20",
                "phone": "9876543210",
            },
        )
        assert response.status_code == 200, f"Expected 200 but got {response.status_code}: {response.text}"
        res_json = response.json()
        assert res_json["message"] == "Profile updated"
        assert res_json["data"]["date_of_birth"] == "1990-05-20"

    app.dependency_overrides.clear()
