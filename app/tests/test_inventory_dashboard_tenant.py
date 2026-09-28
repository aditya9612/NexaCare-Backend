import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from datetime import date

from app.main import app
from app.models.hospital_model import Hospital
from app.models.inventory_model import Warehouse, InventoryItem, ReorderAlert
from app.models.vendor_model import Vendor
from app.core.database import AsyncSessionLocal, engine
from app.core.dependencies import get_current_active_user, get_current_user


@pytest.fixture(autouse=True)
async def cleanup_engine():
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_dashboard_tenant_isolation():
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as db:
        # Create Hospitals with unique emails per run
        hA = Hospital(name=f"Hosp A {uid}", email=f"a_{uid}@h.com", phone="1", address="A")
        hB = Hospital(name=f"Hosp B {uid}", email=f"b_{uid}@h.com", phone="2", address="B")
        db.add_all([hA, hB])
        await db.flush()

        # Create Warehouses with unique codes per run
        wA = Warehouse(name="WH A", code=f"WHA_{uid}", hospital_id=hA.id, location="L1")
        wB = Warehouse(name="WH B", code=f"WHB_{uid}", hospital_id=hB.id, location="L2")
        wA_inactive = Warehouse(name="WH A Inact", code=f"WHAI_{uid}", hospital_id=hA.id, location="L1", is_active=False)
        wB_inactive = Warehouse(name="WH B Inact", code=f"WHBI_{uid}", hospital_id=hB.id, location="L2", is_active=False)
        db.add_all([wA, wB, wA_inactive, wB_inactive])
        await db.flush()

        # Create Vendors (no unique constraint on name)
        vA = Vendor(name=f"Vendor A {uid}")
        vB = Vendor(name=f"Vendor B {uid}")
        db.add_all([vA, vB])
        await db.flush()

        # Create Inventory Items with unique SKUs per run
        iA1 = InventoryItem(name="Item A1", sku=f"A1_{uid}", category="C",
                            quantity=100, unit="box", unit_cost=10,
                            warehouse_id=wA.id, vendor_id=vA.id, reorder_level=10)
        iA2 = InventoryItem(name="Item A2", sku=f"A2_{uid}", category="C",
                            quantity=5, unit="box", unit_cost=20,
                            warehouse_id=wA.id, vendor_id=vA.id, reorder_level=10)  # low stock
        iA3 = InventoryItem(name="Item A3", sku=f"A3_{uid}", category="C",
                            quantity=50, unit="box", unit_cost=5,
                            warehouse_id=wA.id, vendor_id=vA.id, reorder_level=10,
                            expiry_date=date(2000, 1, 1))  # expired
        iB1 = InventoryItem(name="Item B1", sku=f"B1_{uid}", category="C",
                            quantity=1000, unit="box", unit_cost=100,
                            warehouse_id=wB.id, vendor_id=vB.id, reorder_level=10)
        db.add_all([iA1, iA2, iA3, iB1])
        await db.flush()

        # Create Reorder Alerts
        rA = ReorderAlert(item_id=iA2.id, current_quantity=5, reorder_level=10, status="active")
        rB = ReorderAlert(item_id=iB1.id, current_quantity=5, reorder_level=10, status="active")
        db.add_all([rA, rB])
        await db.commit()

        hA_id = hA.id

    # Lightweight stub — avoids any User-table unique constraint
    class FakeUser:
        id = 9999
        role_id = 1
        hospital_id = hA_id
        is_active = True
        is_verified = True
        email = f"fa_{uid}@test.com"

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
                new=AsyncMock(return_value=["inventory:read"]),
            ):
                resp = await ac.get("/api/v1/inventory/dashboard")

    app.dependency_overrides.clear()

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json().get("data", resp.json())

    # All 10 required fields must be present
    required_fields = [
        "total_items", "total_quantity", "low_stock_count", "expired_count",
        "total_value", "total_registered_items", "stock_alerts",
        "active_warehouse_units", "inactive_warehouse_units", "total_vendors",
    ]
    for f in required_fields:
        assert f in data, f"Missing field: {f}"

    # Hospital-A only: 3 items — Hospital B's item must NOT appear
    assert data["total_items"] == 3, f"Expected 3, got {data['total_items']}"
    assert data["total_registered_items"] == 3
    assert data["total_quantity"] == 155        # 100 + 5 + 50
    assert data["low_stock_count"] == 1         # iA2 (qty 5 <= reorder 10)
    assert data["expired_count"] == 1           # iA3
    assert data["active_warehouse_units"] == 1  # wA only
    assert data["inactive_warehouse_units"] == 1  # wA_inactive only
    assert data["stock_alerts"] == 1            # rA only
    assert data["total_vendors"] == 1           # vA has items in hospital A's warehouse
