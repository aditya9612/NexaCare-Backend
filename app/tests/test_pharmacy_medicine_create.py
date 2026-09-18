import pytest
from unittest.mock import AsyncMock, patch
from app.core.constants import UserRole
from app.core.dependencies import get_current_active_user
from app.main import app
from app.models.role_model import Role
from app.models.user_model import User
from app.schemas.pharmacy_schema import MedicineCreate

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

def get_base_payload():
    return {
        "name": "Test Med",
        "category": "Tablet",
        "unit": "Strip",
        "unit_price": 10.0,
        "stock_quantity": 100,
        "reorder_level": 10
    }

@pytest.mark.asyncio
@pytest.mark.parametrize("batch_number", [
    "ABC123",
    "BATCH-001",
    "BATCH_001",
    "aBc123",
    "123", # 3 chars
    "A"*30, # 30 chars
])
async def test_create_medicine_valid_batch(client, batch_number):
    user = build_test_user(UserRole.SUPER_ADMIN)
    override_current_user(user)

    mock_service = AsyncMock()
    mock_response = {
        "id": 1,
        "name": "Test Med",
        "generic_name": None,
        "barcode": None,
        "batch_number": batch_number,
        "sku": "SKU123",
        "category": "Tablet",
        "unit": "Strip",
        "unit_price": 10.0,
        "stock_quantity": 100,
        "reserved_quantity": 0,
        "available_quantity": 100,
        "reorder_level": 10,
        "expiry_date": None,
        "manufacturer": None,
        "description": None,
        "is_active": True,
        "created_at": "2023-01-01T00:00:00Z",
        "updated_at": "2023-01-01T00:00:00Z"
    }
    mock_service.create_medicine = AsyncMock(return_value=mock_response)

    with patch("app.api.v1.routes.pharmacy_routes.PharmacyService", return_value=mock_service):
        payload = get_base_payload()
        payload["batch_number"] = batch_number
        response = await client.post("/api/v1/pharmacy/medicines", json=payload)
        assert response.status_code == 201

@pytest.mark.asyncio
@pytest.mark.parametrize("batch_number", [
    None,
    "",
    "AB", # 2 chars
    "A"*31, # 31 chars
    " BATCH", # leading space
    "BATCH ", # trailing space
    "BAT CH", # internal space
    "BATCH@",
    "BATCH#",
    "BATCH%",
    "BATCH.",
    "BATCH/",
    "BATCH\\"
])
async def test_create_medicine_invalid_batch(client, batch_number):
    user = build_test_user(UserRole.SUPER_ADMIN)
    override_current_user(user)

    payload = get_base_payload()
    payload["batch_number"] = batch_number
    
    response = await client.post("/api/v1/pharmacy/medicines", json=payload)
    assert response.status_code == 422
    
@pytest.mark.asyncio
async def test_create_medicine_missing_batch(client):
    user = build_test_user(UserRole.SUPER_ADMIN)
    override_current_user(user)

    payload = get_base_payload()
    response = await client.post("/api/v1/pharmacy/medicines", json=payload)
    assert response.status_code == 422
