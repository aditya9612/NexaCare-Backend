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

@pytest.mark.asyncio
async def test_list_test_orders_as_lab_technician(client):
    user = build_test_user("Lab Technician")
    override_current_user(user)

    mock_order = {
        "id": 1,
        "order_number": "ORD-20260922-0001",
        "patient_id": 10,
        "patient_name": "John Doe",
        "patient_code": "P-001",
        "doctor_id": None,
        "doctor_name": None,
        "lab_test_id": 5,
        "test_name": "Complete Blood Count",
        "test_code": "CBC01",
        "department_id": 2,
        "department_name": "Pathology",
        "status": "ordered",
        "priority": "normal",
        "created_by": 1,
        "created_by_name": "Test User",
        "ordered_at": "2026-09-22T10:00:00",
        "created_at": "2026-09-22T10:00:00"
    }
    paginated_result = build_paginated_result([mock_order], 1, 1, 20)
    mock_service = AsyncMock()
    mock_service.list_orders = AsyncMock(return_value=paginated_result)

    with patch("app.repositories.rbac_repository.RBACRepository.get_user_permissions", return_value={"lab:read", "lab:create"}), \
         patch("app.api.v1.routes.lab_routes.LabService", return_value=mock_service):
        response = await client.get("/api/v1/lab/orders")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["total"] == 1
        assert data["data"]["items"][0]["patient_name"] == "John Doe"
        assert data["data"]["items"][0]["test_name"] == "Complete Blood Count"
        mock_service.list_orders.assert_called_once()

@pytest.mark.asyncio
async def test_create_test_order_as_lab_technician(client):
    user = build_test_user("Lab Technician")
    override_current_user(user)

    mock_order = {
        "id": 1,
        "order_number": "ORD-20260922-0001",
        "patient_id": 10,
        "patient_name": "John Doe",
        "patient_code": "P-001",
        "doctor_id": None,
        "doctor_name": None,
        "lab_test_id": 5,
        "test_name": "Complete Blood Count",
        "test_code": "CBC01",
        "department_id": 2,
        "department_name": "Pathology",
        "status": "ordered",
        "priority": "normal",
        "created_by": 1,
        "created_by_name": "Test User",
        "ordered_at": "2026-09-22T10:00:00",
        "created_at": "2026-09-22T10:00:00"
    }
    mock_service = AsyncMock()
    mock_service.create_order = AsyncMock(return_value=mock_order)

    with patch("app.repositories.rbac_repository.RBACRepository.get_user_permissions", return_value={"lab:read", "lab:create"}), \
         patch("app.api.v1.routes.lab_routes.LabService", return_value=mock_service):
        response = await client.post(
            "/api/v1/lab/orders",
            json={"patient_id": 10, "lab_test_id": 5, "priority": "normal"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["data"]["created_by"] == 1
        assert data["data"]["patient_name"] == "John Doe"
        mock_service.create_order.assert_called_once()


@pytest.mark.asyncio
async def test_order_response_department_name_mapping():
    from app.services.lab_service import LabService
    from app.models.lab_model import TestOrder, LabTest
    from app.models.department_model import Department
    from app.models.patient_model import Patient
    from datetime import datetime

    mock_db = AsyncMock()
    service = LabService(mock_db)

    dept = Department(department_id=2, department_name="Biochemistry", department_code="BIO")
    lab_test = LabTest(
        id=81,
        test_code="TEST-81",
        test_name="Lipid Profile",
        category="Blood",
        price=500.0,
        sample_type="blood",
        turnaround_hours=24,
        is_active=True,
        department_id=2,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    patient = Patient(
        id=197,
        first_name="Test",
        last_name="Patient",
        patient_code="PAT-197",
    )
    order = TestOrder(
        id=1,
        order_number="ORD-20260924-001",
        patient_id=197,
        doctor_id=1,
        lab_test_id=81,
        department_id=2,
        appointment_id=204,
        status="ordered",
        priority="normal",
        notes="lab test",
        ordered_at=datetime.now(),
        created_at=datetime.now(),
    )
    order.department = dept
    order.lab_test = lab_test
    order.patient = patient
    order.doctor = None
    order.created_by_user = None

    resp = service._order_response(order)
    assert resp.department_name == "Biochemistry"
    assert resp.test_name == "Lipid Profile"
    assert resp.patient_name == "Test Patient"
    assert resp.patient_code == "PAT-197"


@pytest.mark.asyncio
async def test_get_pending_tests_success(client):
    user = build_test_user(UserRole.SUPER_ADMIN)
    override_current_user(user)

    paginated_result = build_paginated_result([], 0, 1, 20)
    mock_service = AsyncMock()
    mock_service.get_pending_tests = AsyncMock(return_value=paginated_result)

    with patch("app.repositories.rbac_repository.RBACRepository.get_user_permissions", return_value={"lab:read"}), \
         patch("app.api.v1.routes.lab_routes.LabService", return_value=mock_service):
        response = await client.get("/api/v1/lab/pending-tests")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["total"] == 0
        mock_service.get_pending_tests.assert_called_once()


@pytest.mark.asyncio
async def test_get_completed_tests_success(client):
    user = build_test_user(UserRole.SUPER_ADMIN)
    override_current_user(user)

    paginated_result = build_paginated_result([], 0, 1, 20)
    mock_service = AsyncMock()
    mock_service.get_completed_tests = AsyncMock(return_value=paginated_result)

    with patch("app.repositories.rbac_repository.RBACRepository.get_user_permissions", return_value={"lab:read"}), \
         patch("app.api.v1.routes.lab_routes.LabService", return_value=mock_service):
        response = await client.get("/api/v1/lab/completed-tests")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["total"] == 0
        mock_service.get_completed_tests.assert_called_once()

