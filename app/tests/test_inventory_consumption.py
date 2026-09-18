import uuid
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.constants import StockTransactionType, UserRole
from app.core.database import AsyncSessionLocal, engine, get_db
from app.core.dependencies import get_current_active_user
from app.core.exceptions import BadRequestException
from app.main import app
from app.models.inventory_model import InventoryItem, StockTransaction, Warehouse
from app.models.role_model import Role
from app.models.user_model import User
from app.services.inventory_service import InventoryService
from app.utils.helpers import utc_now


@pytest.fixture(autouse=True)
async def cleanup_db_pool():
    yield
    await engine.dispose()


def build_admin_user() -> User:
    role = Role(id=1, name=UserRole.SUPER_ADMIN, description="Super Admin")
    user = User(
        id=1,
        user_code="USR-ADMIN-01",
        email="admin_inv@nexacare.com",
        full_name="Admin Inventory User",
        role_id=role.id,
        is_active=True,
        is_verified=True,
        hashed_password="hashed_password",
    )
    user.role = role
    return user


async def create_test_item_and_warehouse(db) -> tuple[Warehouse, InventoryItem]:
    warehouse = Warehouse(
        name=f"Warehouse {uuid.uuid4().hex[:6]}",
        code=f"WH-{uuid.uuid4().hex[:4].upper()}",
        is_active=True,
    )
    db.add(warehouse)
    await db.flush()

    item = InventoryItem(
        name=f"Syringe 5ml {uuid.uuid4().hex[:6]}",
        sku=f"SKU-{uuid.uuid4().hex[:6].upper()}",
        category="Consumables",
        quantity=500,
        unit="pcs",
        unit_cost=15.50,
        reorder_level=50,
        warehouse_id=warehouse.id,
        is_active=True,
    )
    db.add(item)
    await db.flush()
    return warehouse, item


async def create_consumption_transaction(
    db, item_id: int, warehouse_id: int, quantity: int, unit_cost: float, tx_date: datetime
) -> StockTransaction:
    tx = StockTransaction(
        transaction_number=f"TX-{uuid.uuid4().hex[:8].upper()}",
        item_id=item_id,
        warehouse_id=warehouse_id,
        transaction_type=StockTransactionType.CONSUMPTION,
        direction="OUT",
        quantity=quantity,
        unit_cost=unit_cost,
        transaction_date=tx_date,
        performed_by=1,
    )
    db.add(tx)
    await db.flush()
    return tx


@pytest.mark.asyncio
async def test_consumption_report_empty_returns_200():
    """Verify that when no consumption records exist, API returns 200 OK and empty list."""
    async with AsyncSessionLocal() as db:
        admin_user = build_admin_user()

        async def _override_user():
            return admin_user

        async def _override_db():
            yield db

        app.dependency_overrides[get_current_active_user] = _override_user
        app.dependency_overrides[get_db] = _override_db

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/v1/inventory/consumption-reports?period=monthly")
            assert res.status_code == 200
            body = res.json()
            assert body["success"] is True
            assert body["message"] == "Consumption report"
            assert isinstance(body["data"], list)

        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_consumption_report_monthly_aggregation():
    """Verify that consumption transactions in current month are properly aggregated."""
    async with AsyncSessionLocal() as db:
        admin_user = build_admin_user()
        warehouse, item = await create_test_item_and_warehouse(db)

        now = utc_now()
        # Create 2 consumption transactions in current month
        await create_consumption_transaction(db, item.id, warehouse.id, 10, 15.50, now - timedelta(hours=2))
        await create_consumption_transaction(db, item.id, warehouse.id, 20, 15.50, now - timedelta(hours=1))

        async def _override_user():
            return admin_user

        async def _override_db():
            yield db

        app.dependency_overrides[get_current_active_user] = _override_user
        app.dependency_overrides[get_db] = _override_db

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/v1/inventory/consumption-reports?period=monthly")
            assert res.status_code == 200
            body = res.json()
            assert body["success"] is True
            items = body["data"]

            # Find our item
            matching = next((r for r in items if r["item_id"] == item.id), None)
            assert matching is not None
            assert matching["item_name"] == item.name
            assert matching["sku"] == item.sku
            assert matching["period"] == "monthly"
            assert matching["total_consumed"] == 30
            assert matching["total_value"] == round(30 * 15.50, 2)

        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_transactions_outside_period_excluded():
    """Verify that transactions older than the selected period are excluded."""
    async with AsyncSessionLocal() as db:
        service = InventoryService(db)
        warehouse, item = await create_test_item_and_warehouse(db)

        now = utc_now()
        # 1 transaction 40 days ago (outside current month)
        await create_consumption_transaction(db, item.id, warehouse.id, 50, 10.0, now - timedelta(days=40))

        # Monthly report
        monthly_report = await service.get_consumption_report(period="monthly")
        matching_monthly = next((r for r in monthly_report if r.item_id == item.id), None)
        assert matching_monthly is None

        # Overall / All report includes it
        all_report = await service.get_consumption_report(period="all")
        matching_all = next((r for r in all_report if r.item_id == item.id), None)
        assert matching_all is not None
        assert matching_all.total_consumed >= 50


@pytest.mark.asyncio
async def test_soft_deleted_inventory_items_excluded():
    """Verify that soft-deleted items are not included in consumption reports."""
    async with AsyncSessionLocal() as db:
        service = InventoryService(db)
        warehouse, item = await create_test_item_and_warehouse(db)

        now = utc_now() - timedelta(minutes=1)
        await create_consumption_transaction(db, item.id, warehouse.id, 25, 20.0, now)

        # Confirm it appears before deletion
        report_before = await service.get_consumption_report(period="monthly")
        assert any(r.item_id == item.id for r in report_before)

        # Soft delete the item
        raw_item = await db.get(InventoryItem, item.id)
        raw_item.is_deleted = True
        await db.flush()

        # Confirm it is excluded after deletion
        report_after = await service.get_consumption_report(period="monthly")
        assert not any(r.item_id == item.id for r in report_after)


@pytest.mark.asyncio
async def test_all_supported_periods():
    """Verify that daily, weekly, monthly, yearly, all, and overall periods work properly."""
    async with AsyncSessionLocal() as db:
        service = InventoryService(db)
        warehouse, item = await create_test_item_and_warehouse(db)

        now = utc_now() - timedelta(minutes=1)
        await create_consumption_transaction(db, item.id, warehouse.id, 5, 12.0, now)

        for period in ["daily", "weekly", "monthly", "yearly", "all", "overall"]:
            report = await service.get_consumption_report(period=period)
            assert isinstance(report, list)
            matching = next((r for r in report if r.item_id == item.id), None)
            assert matching is not None
            assert matching.period == period
            assert matching.total_consumed == 5


@pytest.mark.asyncio
async def test_invalid_period_raises_400():
    """Verify that an invalid period parameter raises BadRequestException (HTTP 400)."""
    async with AsyncSessionLocal() as db:
        service = InventoryService(db)
        with pytest.raises(BadRequestException) as exc_info:
            await service.get_consumption_report(period="invalid_period_xyz")
        assert "Invalid period parameter" in exc_info.value.detail


@pytest.mark.asyncio
async def test_existing_inventory_items_endpoint_unaffected():
    """Verify that existing inventory endpoints (e.g. GET /api/v1/inventory/items) remain unaffected."""
    async with AsyncSessionLocal() as db:
        admin_user = build_admin_user()

        async def _override_user():
            return admin_user

        async def _override_db():
            yield db

        app.dependency_overrides[get_current_active_user] = _override_user
        app.dependency_overrides[get_db] = _override_db

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/v1/inventory/items")
            assert res.status_code == 200
            body = res.json()
            assert body["success"] is True
            assert "items" in body["data"]

        app.dependency_overrides.clear()
