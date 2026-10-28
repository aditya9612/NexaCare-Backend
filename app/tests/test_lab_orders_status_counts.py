import math
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.constants import LabOrderStatus, UserRole
from app.core.dependencies import get_current_active_user, get_current_user
from app.main import app
from app.models.lab_model import LabTest, TestOrder as LabTestOrder
from app.models.role_model import Role
from app.models.user_model import User
from app.repositories.lab_repository import TestOrderRepository as LabOrderRepository
from app.schemas.lab_schema import (
    TestOrderListResponse as LabOrderListResponse,
    TestOrderResponse as LabOrderResponse,
    TestOrderStatusCounts as LabOrderStatusCounts,
)
from app.services.lab_service import LabService


def build_test_user(role_name: str, user_id: int = 1) -> User:
    role = Role(id=1, name=role_name, description=f"{role_name} role")
    user = User(
        id=user_id,
        user_code=f"U_TEST_{user_id}",
        email=f"user{user_id}@test.com",
        full_name=f"Test {role_name}",
        role_id=role.id,
        is_active=True,
        is_verified=True,
        hashed_password="hashed_password",
    )
    user.role = role
    return user


def override_current_user(user: User):
    async def _get_user():
        return user

    app.dependency_overrides[get_current_active_user] = _get_user
    app.dependency_overrides[get_current_user] = _get_user


def test_schema_and_openapi_includes_status_counts():
    """Verify that LabOrderListResponse and the generated OpenAPI documentation for
    GET /api/v1/lab/orders include the status_counts object with all 4 required fields.
    """
    # 1. Pydantic schema validation
    fields = LabOrderListResponse.model_fields
    assert "status_counts" in fields
    assert "items" in fields
    assert "total" in fields
    assert "page" in fields
    assert "size" in fields
    assert "pages" in fields

    status_fields = LabOrderStatusCounts.model_fields
    assert set(status_fields.keys()) == {"pending", "in_progress", "completed", "approved"}

    # 2. OpenAPI documentation check
    openapi = app.openapi()
    schemas = openapi["components"]["schemas"]
    assert "TestOrderListResponse" in schemas
    assert "TestOrderStatusCounts" in schemas

    order_list_props = schemas["TestOrderListResponse"]["properties"]
    assert "status_counts" in order_list_props

    counts_props = schemas["TestOrderStatusCounts"]["properties"]
    assert "pending" in counts_props
    assert "in_progress" in counts_props
    assert "completed" in counts_props
    assert "approved" in counts_props


@pytest.mark.asyncio
async def test_get_lab_orders_api_returns_status_counts(client):
    """Verify that calling GET /api/v1/lab/orders returns status_counts with all 4 dashboard card fields."""
    user = build_test_user(UserRole.SUPER_ADMIN)
    override_current_user(user)

    mock_counts = LabOrderStatusCounts(
        pending=30,
        in_progress=2,
        completed=2,
        approved=0,
    )
    mock_result = LabOrderListResponse(
        items=[],
        total=34,
        page=1,
        size=20,
        pages=2,
        status_counts=mock_counts,
    )

    mock_service = AsyncMock()
    mock_service.list_orders = AsyncMock(return_value=mock_result)

    with patch("app.repositories.rbac_repository.RBACRepository.get_user_permissions", return_value={"lab:read"}), \
         patch("app.api.v1.routes.lab_routes.LabService", return_value=mock_service):

        response = await client.get("/api/v1/lab/orders")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Test orders retrieved"

        payload = data["data"]
        assert payload["total"] == 34
        assert payload["page"] == 1
        assert payload["size"] == 20
        assert payload["pages"] == 2
        assert "status_counts" in payload

        counts = payload["status_counts"]
        assert counts["pending"] == 30
        assert counts["in_progress"] == 2
        assert counts["completed"] == 2
        assert counts["approved"] == 0


@pytest.mark.asyncio
async def test_lab_service_list_orders_calculates_status_counts_from_repo():
    """Verify that LabService.list_orders calls order_repo.get_status_counts and
    populates LabOrderListResponse correctly.
    """
    mock_db = AsyncMock()
    service = LabService(mock_db)
    service.order_repo = AsyncMock()

    service.order_repo.list_all.return_value = []
    service.order_repo.count_all.return_value = 45
    service.order_repo.get_status_counts.return_value = {
        "pending": 25,
        "in_progress": 10,
        "completed": 8,
        "approved": 2,
    }

    user = build_test_user(UserRole.SUPER_ADMIN)
    res = await service.list_orders(page=1, size=20, current_user=user)

    assert isinstance(res, LabOrderListResponse)
    assert res.total == 45
    assert res.pages == 3
    assert res.status_counts.pending == 25
    assert res.status_counts.in_progress == 10
    assert res.status_counts.completed == 8
    assert res.status_counts.approved == 2

    # Verify get_status_counts was called
    service.order_repo.get_status_counts.assert_called_once()


@pytest.mark.asyncio
async def test_status_counts_calculated_across_all_orders_not_limited_to_page():
    """Verify that when size=5 on page 2, the status_counts still reflect the full
    dataset counts across all pages, not just the 5 items on the current page.
    """
    mock_db = AsyncMock()
    service = LabService(mock_db)
    service.order_repo = AsyncMock()

    # Mock orders on page 2
    mock_items = [
        LabTestOrder(
            id=i,
            order_number=f"ORD-{i}",
            patient_id=1,
            doctor_id=1,
            lab_test_id=1,
            status="ordered",
            priority="normal",
            ordered_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        for i in range(6, 11)
    ]
    for it in mock_items:
        it.lab_test = None
        it.patient = None
        it.doctor = None
        it.department = None
        it.created_by_user = None

    service.order_repo.list_all.return_value = mock_items
    service.order_repo.count_all.return_value = 100
    service.order_repo.get_status_counts.return_value = {
        "pending": 60,
        "in_progress": 25,
        "completed": 10,
        "approved": 5,
    }

    user = build_test_user(UserRole.HOSPITAL_ADMIN)
    res = await service.list_orders(page=2, size=5, current_user=user)

    assert len(res.items) == 5
    assert res.page == 2
    assert res.size == 5
    assert res.total == 100
    assert res.pages == 20
    # Status counts must reflect the global 100 orders, not just the 5 items on page 2
    assert res.status_counts.pending == 60
    assert res.status_counts.in_progress == 25
    assert res.status_counts.completed == 10
    assert res.status_counts.approved == 5


@pytest.mark.asyncio
async def test_empty_results_returns_zero_status_counts():
    """Verify that an empty dataset returns zeros for all four status counts."""
    mock_db = AsyncMock()
    service = LabService(mock_db)
    service.order_repo = AsyncMock()

    service.order_repo.list_all.return_value = []
    service.order_repo.count_all.return_value = 0
    service.order_repo.get_status_counts.return_value = {
        "pending": 0,
        "in_progress": 0,
        "completed": 0,
        "approved": 0,
    }

    user = build_test_user(UserRole.SUPER_ADMIN)
    res = await service.list_orders(page=1, size=20, current_user=user)

    assert res.total == 0
    assert res.items == []
    assert res.pages == 0
    assert res.status_counts.pending == 0
    assert res.status_counts.in_progress == 0
    assert res.status_counts.completed == 0
    assert res.status_counts.approved == 0


@pytest.mark.asyncio
async def test_get_status_counts_repository_query_mock():
    """Verify LabOrderRepository.get_status_counts maps row fields accurately."""
    mock_db = AsyncMock()
    repo = LabOrderRepository(mock_db)

    mock_row = MagicMock()
    mock_row._mapping = {
        "pending": 15,
        "in_progress": 7,
        "completed": 3,
        "approved": 1,
    }
    mock_result = MagicMock()
    mock_result.one.return_value = mock_row
    mock_db.execute.return_value = mock_result

    counts = await repo.get_status_counts(hospital_id=1, department_id=2)
    assert counts["pending"] == 15
    assert counts["in_progress"] == 7
    assert counts["completed"] == 3
    assert counts["approved"] == 1
    mock_db.execute.assert_called_once()
