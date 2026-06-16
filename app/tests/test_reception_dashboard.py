from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.core.constants import UserRole
from app.core.dependencies import get_current_active_user
from app.main import app
from app.models.role_model import Role
from app.models.user_model import User
from app.schemas.dashboard_schema import ReceptionDashboardResponse


def override_current_user(user: User):
    async def _get_current_user():
        return user

    app.dependency_overrides[get_current_active_user] = _get_current_user


def build_receptionist_user() -> User:
    role = Role(id=2, name=UserRole.RECEPTIONIST, description="Receptionist role")
    user = User(
        id=2,
        user_code="U_TEST_RECEPTIONIST",
        email="receptionist@test.com",
        full_name="Receptionist User",
        role_id=role.id,
        is_active=True,
        is_verified=True,
        hashed_password="hashed_password",
    )
    user.role = role
    return user


def build_patient_user() -> User:
    role = Role(id=3, name=UserRole.PATIENT, description="Patient role")
    user = User(
        id=3,
        user_code="U_TEST_PATIENT",
        email="patient@test.com",
        full_name="Patient User",
        role_id=role.id,
        is_active=True,
        is_verified=True,
        hashed_password="hashed_password",
    )
    user.role = role
    return user


@pytest.mark.asyncio
async def test_reception_dashboard_stats_success(client):
    receptionist = build_receptionist_user()
    override_current_user(receptionist)

    mock_stats = ReceptionDashboardResponse(
        total_registered_patients=1240,
        today_scheduled_appointments=45,
        checked_in_patients=18,
        waiting_patients=5,
        completed_visits=12,
        cancelled_appointments=2,
        available_doctors=4,
        walk_in_patients=6,
        pending_billing=3,
        rescheduled_appointments=1,
        total_patient_footfall=18
    )

    mock_service = AsyncMock()
    mock_service.reception_dashboard = AsyncMock(return_value=mock_stats)

    with patch("app.core.dependencies.RBACRepository.get_user_permissions", new_callable=AsyncMock, return_value=["dashboard:read"]):
        with patch("app.api.v1.routes.dashboard_routes.DashboardService", return_value=mock_service):
            response = await client.get("/api/v1/dashboard/reception")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["message"] == "Receptionist dashboard stats retrieved successfully"
            assert data["data"]["total_registered_patients"] == 1240
            assert data["data"]["today_scheduled_appointments"] == 45
            assert data["data"]["checked_in_patients"] == 18
            assert data["data"]["waiting_patients"] == 5
            assert data["data"]["completed_visits"] == 12
            assert data["data"]["cancelled_appointments"] == 2
            assert data["data"]["available_doctors"] == 4
            assert data["data"]["walk_in_patients"] == 6
            assert data["data"]["pending_billing"] == 3
            assert data["data"]["rescheduled_appointments"] == 1
            assert data["data"]["total_patient_footfall"] == 18


@pytest.mark.asyncio
async def test_reception_dashboard_stats_with_date(client):
    receptionist = build_receptionist_user()
    override_current_user(receptionist)

    mock_stats = ReceptionDashboardResponse(
        total_registered_patients=1240,
        today_scheduled_appointments=10,
        checked_in_patients=5,
        waiting_patients=2,
        completed_visits=3,
        cancelled_appointments=0,
        available_doctors=4,
        walk_in_patients=1,
        pending_billing=1,
        rescheduled_appointments=0,
        total_patient_footfall=5
    )

    mock_service = AsyncMock()
    mock_service.reception_dashboard = AsyncMock(return_value=mock_stats)

    with patch("app.core.dependencies.RBACRepository.get_user_permissions", new_callable=AsyncMock, return_value=["dashboard:read"]):
        with patch("app.api.v1.routes.dashboard_routes.DashboardService", return_value=mock_service):
            response = await client.get("/api/v1/dashboard/reception?date=2026-06-15")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["data"]["today_scheduled_appointments"] == 10
            mock_service.reception_dashboard.assert_called_once_with(date(2026, 6, 15))


@pytest.mark.asyncio
async def test_reception_dashboard_stats_forbidden_for_patient(client):
    patient = build_patient_user()
    override_current_user(patient)

    response = await client.get("/api/v1/dashboard/reception")
    assert response.status_code == 403
