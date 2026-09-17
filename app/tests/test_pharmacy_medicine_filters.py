import pytest
from datetime import date
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_active_user, get_db
from app.main import app
from app.models.role_model import Role
from app.models.user_model import User
from app.models.pharmacy_model import Medicine
from app.schemas.pharmacy_schema import MedicineResponse
from app.utils.pagination import PaginatedResult

from app.core.constants import UserRole

def build_test_user(role_name: str = UserRole.SUPER_ADMIN) -> User:
    role = Role(id=1, name=role_name, description=f"{role_name} role")
    user = User(
        id=1,
        user_code="U_TEST_PHARMACIST",
        email="pharmacist@test.com",
        full_name="Test Pharmacist",
        role_id=role.id,
        is_active=True,
        is_verified=True,
        hashed_password="hashed_password",
    )
    user.role = role
    return user

def mock_medicine(id: int, name: str, category: str = "Tablet", is_active: bool = True, stock_quantity: int = 50) -> Medicine:
    from datetime import datetime
    med = Medicine(
        id=id,
        name=name,
        sku=f"SKU-{id}",
        category=category,
        unit="Strip",
        unit_price=10.0,
        stock_quantity=stock_quantity,
        reserved_quantity=0,
        reorder_level=10,
        is_active=is_active,
        is_deleted=False,
    )
    med.created_at = datetime(2026, 9, 15, 10, 0, 0)
    med.updated_at = datetime(2026, 9, 15, 10, 0, 0)
    return med

@pytest.mark.asyncio
async def test_list_medicines_with_status_filter():
    user = build_test_user(UserRole.SUPER_ADMIN)
    app.dependency_overrides[get_current_active_user] = lambda: user

    med_active = mock_medicine(1, "Paracetamol", is_active=True)
    
    mock_service = AsyncMock()
    mock_service.list_medicines.return_value = PaginatedResult(
        items=[MedicineResponse.model_validate(med_active)],
        total=1,
        page=1,
        size=20,
        pages=1
    )

    with patch("app.api.v1.routes.pharmacy_routes.PharmacyService", return_value=mock_service):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.get("/api/v1/pharmacy/medicines?status=active")
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert len(data["data"]["items"]) == 1
            assert data["data"]["items"][0]["name"] == "Paracetamol"
            mock_service.list_medicines.assert_called_once_with(
                page=1, size=20, sort_by="created_at", sort_order="desc", category=None,
                status="active", patient_name=None, medicine_date=None
            )

    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_list_medicines_with_patient_name_and_date_filters():
    user = build_test_user(UserRole.SUPER_ADMIN)
    app.dependency_overrides[get_current_active_user] = lambda: user

    med_patient = mock_medicine(2, "Amoxicillin")
    
    mock_service = AsyncMock()
    mock_service.list_medicines.return_value = PaginatedResult(
        items=[MedicineResponse.model_validate(med_patient)],
        total=1,
        page=1,
        size=20,
        pages=1
    )

    with patch("app.api.v1.routes.pharmacy_routes.PharmacyService", return_value=mock_service):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.get("/api/v1/pharmacy/medicines?patient_name=Rahul&date=2026-09-15")
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert len(data["data"]["items"]) == 1
            assert data["data"]["items"][0]["name"] == "Amoxicillin"
            mock_service.list_medicines.assert_called_once_with(
                page=1, size=20, sort_by="created_at", sort_order="desc", category=None,
                status=None, patient_name="Rahul", medicine_date=date(2026, 9, 15)
            )

    app.dependency_overrides.clear()
