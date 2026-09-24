import uuid
import pytest
from app.core.database import AsyncSessionLocal, engine
from app.models.hospital_model import Hospital
from app.models.inventory_model import Warehouse, InventoryItem, ReorderAlert
from app.services.inventory_service import InventoryService


@pytest.fixture(autouse=True)
async def cleanup_engine():
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_reorder_alerts():
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        hospital = Hospital(name=f"HospAlert_{uid}", email=f"h_{uid}@alert.com", phone="123", address="Main")
        session.add(hospital)
        await session.flush()

        warehouse = Warehouse(name=f"WHAlert_{uid}", code=f"WHA_{uid}", hospital_id=hospital.id, location="L1")
        session.add(warehouse)
        await session.flush()

        # Create item with quantity <= reorder_level attached to warehouse
        item = InventoryItem(
            name=f"AlertItem_{uid}",
            sku=f"ALSKU_{uid}",
            category="Surgicals",
            quantity=5,
            unit="Box",
            unit_cost=15.0,
            reorder_level=10,
            warehouse_id=warehouse.id,
            is_active=True,
        )
        session.add(item)
        await session.flush()

        # Create active ReorderAlert for item
        alert = ReorderAlert(
            item_id=item.id,
            current_quantity=item.quantity,
            reorder_level=item.reorder_level,
            status="active",
        )
        session.add(alert)
        await session.commit()

        service = InventoryService(session)

        # Call get_reorder_alerts with hospital_id
        alerts = await service.get_reorder_alerts(hospital_id=hospital.id, page=1, size=50)
        assert alerts is not None
        assert isinstance(alerts, list)

        # Find our created alert in response list
        target_alert = next((a for a in alerts if a.id == alert.id), None)
        assert target_alert is not None
        assert target_alert.item_id == item.id
        assert target_alert.item_name == item.name
        assert target_alert.sku == item.sku
        assert target_alert.current_quantity == 5
        assert target_alert.reorder_level == 10
        assert target_alert.status == "active"


@pytest.mark.asyncio
async def test_reorder_alerts_tenant_isolation():
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        # Hospital A
        hA = Hospital(name=f"HospA_{uid}", email=f"ha_{uid}@test.com", phone="111", address="A")
        hB = Hospital(name=f"HospB_{uid}", email=f"hb_{uid}@test.com", phone="222", address="B")
        session.add_all([hA, hB])
        await session.flush()

        wA = Warehouse(name=f"WHA_{uid}", code=f"WHA_{uid}", hospital_id=hA.id, location="L1")
        wB = Warehouse(name=f"WHB_{uid}", code=f"WHB_{uid}", hospital_id=hB.id, location="L2")
        session.add_all([wA, wB])
        await session.flush()

        itemA = InventoryItem(name=f"ItemA_{uid}", sku=f"SKUA_{uid}", category="Surgicals", unit="box", quantity=2, reorder_level=10, warehouse_id=wA.id)
        itemB = InventoryItem(name=f"ItemB_{uid}", sku=f"SKUB_{uid}", category="Surgicals", unit="box", quantity=3, reorder_level=10, warehouse_id=wB.id)
        session.add_all([itemA, itemB])
        await session.flush()

        alertA = ReorderAlert(item_id=itemA.id, current_quantity=2, reorder_level=10, status="active")
        alertB = ReorderAlert(item_id=itemB.id, current_quantity=3, reorder_level=10, status="active")
        session.add_all([alertA, alertB])
        await session.commit()

        service = InventoryService(session)

        # Hospital A reorder alerts
        alerts_A = await service.get_reorder_alerts(hospital_id=hA.id)
        alert_ids_A = [a.id for a in alerts_A]
        assert alertA.id in alert_ids_A
        assert alertB.id not in alert_ids_A

        # Hospital B reorder alerts
        alerts_B = await service.get_reorder_alerts(hospital_id=hB.id)
        alert_ids_B = [a.id for a in alerts_B]
        assert alertB.id in alert_ids_B
        assert alertA.id not in alert_ids_B

        # Dashboard consistency check
        dashboard_A = await service.get_dashboard_summary(hospital_id=hA.id)
        assert dashboard_A.stock_alerts == len(alerts_A)
        assert dashboard_A.low_stock_count == 1

