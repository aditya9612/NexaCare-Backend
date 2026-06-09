from datetime import date, datetime, time
from unittest.mock import AsyncMock, patch

import pytest

from app.core.constants import UserRole
from app.core.dependencies import get_current_active_user
from app.core.exceptions import NotFoundException
from app.main import app
from app.models.role_model import Role
from app.models.user_model import User
from app.schemas.nurse_schema import NurseShiftResponse
from app.utils.pagination import build_paginated_result


def override_current_user(user: User):
    async def _get_current_user():
        return user

    app.dependency_overrides[get_current_active_user] = _get_current_user


def build_admin_user() -> User:
    role = Role(id=1, name=UserRole.SUPER_ADMIN, description="Admin role")
    user = User(
        id=1,
        user_code="U_TEST_ADMIN",
        email="admin@test.com",
        full_name="Admin User",
        role_id=role.id,
        is_active=True,
        is_verified=True,
        hashed_password="hashed_password",
    )
    user.role = role
    return user


def build_shift_response(
    shift_id: int = 1,
    nurse_id: int = 1,
    shift_name: str = "Morning",
    notes: str | None = None,
) -> NurseShiftResponse:
    now = datetime(2026, 6, 7, 12, 0, 0)
    return NurseShiftResponse(
        id=shift_id,
        nurse_id=nurse_id,
        shift_name=shift_name,
        shift_date=date(2026, 6, 5),
        start_time=time(8, 0),
        end_time=time(16, 0),
        status="Scheduled",
        notes=notes,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_list_nurse_shifts(client):
    admin_user = build_admin_user()
    override_current_user(admin_user)

    morning_shift = build_shift_response(shift_id=1, shift_name="Morning")
    night_shift = build_shift_response(shift_id=2, shift_name="Night", nurse_id=1)
    night_shift.shift_date = date(2026, 6, 6)
    night_shift.start_time = time(22, 0)
    night_shift.end_time = time(6, 0)

    all_shifts = build_paginated_result([night_shift, morning_shift], 2, 1, 20)
    morning_only = build_paginated_result([morning_shift], 1, 1, 20)
    date_filtered = build_paginated_result([morning_shift], 1, 1, 20)

    mock_service = AsyncMock()
    mock_service.list_shifts = AsyncMock(
        side_effect=[all_shifts, morning_only, date_filtered]
    )

    with patch("app.api.v1.routes.nurse_routes.NurseService", return_value=mock_service):
        response = await client.get("/api/v1/nurses/1/shifts")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["total"] == 2
        assert len(data["data"]["items"]) == 2

        response = await client.get("/api/v1/nurses/1/shifts?shift_name=Morning")
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["total"] == 1
        assert data["data"]["items"][0]["shift_name"] == "Morning"

        response = await client.get(
            "/api/v1/nurses/1/shifts?start_date=2026-06-05&end_date=2026-06-05"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["total"] == 1


@pytest.mark.asyncio
async def test_list_nurse_shifts_not_found(client):
    admin_user = build_admin_user()
    override_current_user(admin_user)

    mock_service = AsyncMock()
    mock_service.list_shifts = AsyncMock(side_effect=NotFoundException("Nurse not found"))

    with patch("app.api.v1.routes.nurse_routes.NurseService", return_value=mock_service):
        response = await client.get("/api/v1/nurses/99999/shifts")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_nurse_shift(client):
    admin_user = build_admin_user()
    override_current_user(admin_user)

    created_shift = build_shift_response(
        shift_id=3,
        nurse_id=1,
        shift_name="Afternoon",
        notes="Coverage shift",
    )
    created_shift.shift_date = date(2026, 6, 7)
    created_shift.start_time = time(12, 0)
    created_shift.end_time = time(20, 0)

    mock_service = AsyncMock()
    mock_service.create_shift = AsyncMock(return_value=created_shift)

    payload = {
        "shift_name": "Afternoon",
        "shift_date": "2026-06-07",
        "start_time": "12:00:00",
        "end_time": "20:00:00",
        "status": "Scheduled",
        "notes": "Coverage shift",
    }

    with patch("app.api.v1.routes.nurse_routes.NurseService", return_value=mock_service):
        response = await client.post("/api/v1/nurses/1/shifts", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["data"]["nurse_id"] == 1
        assert data["data"]["shift_name"] == "Afternoon"
        assert data["data"]["notes"] == "Coverage shift"


@pytest.mark.asyncio
async def test_create_nurse_shift_nurse_not_found(client):
    admin_user = build_admin_user()
    override_current_user(admin_user)

    mock_service = AsyncMock()
    mock_service.create_shift = AsyncMock(side_effect=NotFoundException("Nurse not found"))

    payload = {
        "shift_name": "Afternoon",
        "shift_date": "2026-06-07",
        "start_time": "12:00:00",
        "end_time": "20:00:00",
    }

    with patch("app.api.v1.routes.nurse_routes.NurseService", return_value=mock_service):
        response = await client.post("/api/v1/nurses/99999/shifts", json=payload)
        assert response.status_code == 404
