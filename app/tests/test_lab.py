import pytest
from unittest.mock import AsyncMock, patch
from app.core.constants import UserRole
from app.core.dependencies import get_current_active_user
from app.main import app
from app.models.role_model import Role
from app.models.user_model import User
from app.utils.pagination import build_paginated_result

def override_current_user(user: User):
    async def _get_current_user():
        return user
    app.dependency_overrides[get_current_active_user] = _get_current_user

def build_test_user(role_name: str) -> User:
    role = Role(id=1, name=role_name, description=f"{role_name} role")
    user = User(
        id=1,
        user_code="U_TEST_USER",
        email="user@test.com",
        full_name="Test User",
        role_id=role.id,
        is_active=True,
        is_verified=True,
        hashed_password="hashed_password",
    )
    user.role = role
    return user

@pytest.mark.asyncio
async def test_list_test_orders_success(client):
    user = build_test_user(UserRole.SUPER_ADMIN)
    override_current_user(user)

    paginated_result = build_paginated_result([], 0, 1, 20)
    mock_service = AsyncMock()
    mock_service.list_orders = AsyncMock(return_value=paginated_result)

    with patch("app.api.v1.routes.lab_routes.LabService", return_value=mock_service):
        response = await client.get("/api/v1/lab/orders")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["total"] == 0
        mock_service.list_orders.assert_called_once()
