import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from datetime import date, datetime

from app.main import app
from app.models.hospital_model import Hospital
from app.models.inventory_model import Warehouse, InventoryItem, StockTransaction, ReorderAlert
from app.core.database import AsyncSessionLocal, engine
from app.core.dependencies import get_current_active_user, get_current_user


@pytest.fixture(autouse=True)
async def cleanup_engine():
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_inventory_list_summary_values():
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as db:
        hospital = Hospital(name=f"HospSummary_{uid}", email=f"sum_{uid}@h.com", phone="123", address="A")
        db.add(hospital)
        await db.flush()

        warehouse = Warehouse(name=f"WH_{uid}", code=f"WH_{uid}", hospital_id=hospital.id, location="L1")
        db.add(warehouse)
        await db.flush()

        # Item 1: Qty = 100, Reorder level = 10
        item1 = InventoryItem(
            name=f"Item1_{uid}", sku=f"SKU1_{uid}", category="Med",
            quantity=100, unit="box", unit_cost=10.0, reorder_level=10,
            warehouse_id=warehouse.id
        )
        # Item 2: Qty = 5, Reorder level = 20 (Low stock / Reorder alert)
        item2 = InventoryItem(
            name=f"Item2_{uid}", sku=f"SKU2_{uid}", category="Med",
            quantity=5, unit="box", unit_cost=20.0, reorder_level=20,
            warehouse_id=warehouse.id
        )
        db.add_all([item1, item2])
        await db.flush()

        # Transactions for item 1
        tx_in = StockTransaction(
            transaction_number=f"TXIN_{uid}", item_id=item1.id, warehouse_id=warehouse.id,
            transaction_type="INWARD", direction="IN", quantity=150, unit_cost=10.0,
            transaction_date=datetime.utcnow()
        )
        tx_out = StockTransaction(
            transaction_number=f"TXOUT_{uid}", item_id=item1.id, warehouse_id=warehouse.id,
            transaction_type="OUTWARD", direction="OUT", quantity=50, unit_cost=10.0,
            transaction_date=datetime.utcnow()
        )
        db.add_all([tx_in, tx_out])
        await db.commit()

        h_id = hospital.id

    class FakeUser:
        id = 9999
        role_id = 1
        hospital_id = h_id
        is_active = True
        is_verified = True
        email = f"user_{uid}@test.com"

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
                resp = await ac.get("/api/v1/inventory/items?page=1&size=10")

    app.dependency_overrides.clear()

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    data = body["data"]

    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "size" in data
    assert "pages" in data
    assert "summary" in data

    summary = data["summary"]
    # Total stock on hand = 100 + 5 = 105
    assert summary["stock_on_hand"] == 105
    # Inward restocks = 150
    assert summary["inward_restocks"] == 150
    # Outward issued = 50
    assert summary["outward_issued"] == 50
    # Reorder alerts = 1 (item2 has qty 5 <= reorder 20)
    assert summary["reorder_alerts"] == 1


@pytest.mark.asyncio
async def test_inventory_list_summary_pagination_independence():
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as db:
        hospital = Hospital(name=f"HospPag_{uid}", email=f"pag_{uid}@h.com", phone="123", address="A")
        db.add(hospital)
        await db.flush()

        warehouse = Warehouse(name=f"WHPag_{uid}", code=f"WHP_{uid}", hospital_id=hospital.id, location="L1")
        db.add(warehouse)
        await db.flush()

        items = []
        for i in range(5):
            items.append(InventoryItem(
                name=f"Item_{i}_{uid}", sku=f"SKU_{i}_{uid}", category="Cat",
                quantity=10, unit="box", unit_cost=5.0, reorder_level=15,
                warehouse_id=warehouse.id
            ))
        db.add_all(items)
        await db.commit()
        h_id = hospital.id

    class FakeUser:
        id = 9999
        role_id = 1
        hospital_id = h_id
        is_active = True
        is_verified = True
        email = f"userpag_{uid}@test.com"

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
                # Page 1 with size 2
                resp_p1 = await ac.get("/api/v1/inventory/items?page=1&size=2")
                # Page 2 with size 2
                resp_p2 = await ac.get("/api/v1/inventory/items?page=2&size=2")

    app.dependency_overrides.clear()

    data_p1 = resp_p1.json()["data"]
    data_p2 = resp_p2.json()["data"]

    assert len(data_p1["items"]) == 2
    assert len(data_p2["items"]) == 2

    # Summary totals must be identical for both pages (50 total quantity, 5 reorder alerts)
    assert data_p1["summary"]["stock_on_hand"] == 50
    assert data_p2["summary"]["stock_on_hand"] == 50
    assert data_p1["summary"]["reorder_alerts"] == 5
    assert data_p2["summary"]["reorder_alerts"] == 5


@pytest.mark.asyncio
async def test_inventory_list_summary_tenant_isolation():
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as db:
        hA = Hospital(name=f"HospA_{uid}", email=f"ha_{uid}@t.com", phone="1", address="A")
        hB = Hospital(name=f"HospB_{uid}", email=f"hb_{uid}@t.com", phone="2", address="B")
        db.add_all([hA, hB])
        await db.flush()

        wA = Warehouse(name=f"WHA_{uid}", code=f"WHA_{uid}", hospital_id=hA.id)
        wB = Warehouse(name=f"WHB_{uid}", code=f"WHB_{uid}", hospital_id=hB.id)
        db.add_all([wA, wB])
        await db.flush()

        iA = InventoryItem(name="A", sku=f"A_{uid}", category="C", unit="box", quantity=50, reorder_level=5, warehouse_id=wA.id)
        iB = InventoryItem(name="B", sku=f"B_{uid}", category="C", unit="box", quantity=500, reorder_level=5, warehouse_id=wB.id)
        db.add_all([iA, iB])
        await db.flush()

        txA = StockTransaction(transaction_number=f"TA_{uid}", item_id=iA.id, warehouse_id=wA.id, transaction_type="INWARD", direction="IN", quantity=20, transaction_date=datetime.utcnow())
        txB = StockTransaction(transaction_number=f"TB_{uid}", item_id=iB.id, warehouse_id=wB.id, transaction_type="INWARD", direction="IN", quantity=300, transaction_date=datetime.utcnow())
        db.add_all([txA, txB])
        await db.commit()

        hA_id = hA.id

    class FakeUser:
        id = 9999
        role_id = 1
        hospital_id = hA_id
        is_active = True
        is_verified = True
        email = f"userA_{uid}@test.com"

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
                resp = await ac.get("/api/v1/inventory/items")

    app.dependency_overrides.clear()

    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["summary"]["stock_on_hand"] == 50
    assert data["summary"]["inward_restocks"] == 20


@pytest.mark.asyncio
async def test_inventory_list_summary_search():
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as db:
        hospital = Hospital(name=f"HospSearch_{uid}", email=f"sch_{uid}@h.com", phone="123", address="A")
        db.add(hospital)
        await db.flush()

        warehouse = Warehouse(name=f"WH_{uid}", code=f"WH_{uid}", hospital_id=hospital.id)
        db.add(warehouse)
        await db.flush()

        item = InventoryItem(name=f"Syringe_{uid}", sku=f"SKUSYR_{uid}", category="Supplies", unit="box", quantity=30, reorder_level=5, warehouse_id=warehouse.id)
        db.add(item)
        await db.commit()

        h_id = hospital.id

    class FakeUser:
        id = 9999
        role_id = 1
        hospital_id = h_id
        is_active = True
        is_verified = True
        email = f"schuser_{uid}@test.com"

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
                resp = await ac.get(f"/api/v1/inventory/items?q=Syringe_{uid}")

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "summary" in data
    assert data["summary"]["stock_on_hand"] == 30


@pytest.mark.asyncio
async def test_inventory_list_summary_empty():
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as db:
        hospital = Hospital(name=f"HospEmpty_{uid}", email=f"emp_{uid}@h.com", phone="123", address="A")
        db.add(hospital)
        await db.commit()
        h_id = hospital.id

    class FakeUser:
        id = 9999
        role_id = 1
        hospital_id = h_id
        is_active = True
        is_verified = True
        email = f"empuser_{uid}@test.com"

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
                resp = await ac.get("/api/v1/inventory/items")

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 0
    assert data["summary"]["stock_on_hand"] == 0
    assert data["summary"]["inward_restocks"] == 0
    assert data["summary"]["outward_issued"] == 0
    assert data["summary"]["reorder_alerts"] == 0
