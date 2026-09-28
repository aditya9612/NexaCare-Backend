import pytest
from datetime import datetime
from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user, get_db
from app.main import app
from app.models.user_model import User


@pytest.mark.asyncio
async def test_delete_profile_image():
    mock_user = User(
        id=1,
        user_code="USR-001",
        full_name="Hospital Admin",
        email="admin@nexacare.com",
        phone="9876543210",
        profile_image="/uploads/profiles/test.jpg",
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
        response = await ac.delete("/api/v1/auth/profile/image")
        assert response.status_code == 200, f"Expected 200 but got {response.status_code}: {response.text}"
        res_json = response.json()
        assert res_json["message"] == "Profile image deleted successfully"
        assert mock_user.profile_image is None

    app.dependency_overrides.clear()
