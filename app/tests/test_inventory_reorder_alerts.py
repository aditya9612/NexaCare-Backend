import uuid
import pytest
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.inventory_model import InventoryItem, ReorderAlert
from app.services.inventory_service import InventoryService


@pytest.mark.asyncio
async def test_get_reorder_alerts():
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        # Create item with quantity <= reorder_level
        item = InventoryItem(
            name=f"AlertItem_{uid}",
            sku=f"ALSKU_{uid}",
            category="Surgicals",
            quantity=5,
            unit="Box",
            unit_cost=15.0,
            reorder_level=10,
            is_active=True,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)

        # Create active ReorderAlert for item
        alert = ReorderAlert(
            item_id=item.id,
            current_quantity=item.quantity,
            reorder_level=item.reorder_level,
            status="active",
        )
        session.add(alert)
        await session.commit()
        await session.refresh(alert)

        service = InventoryService(session)

        # Call get_reorder_alerts
        alerts = await service.get_reorder_alerts(page=1, size=50)
        assert alerts is not None
        assert isinstance(alerts, list)
        assert len(alerts) >= 1

        # Find our created alert in response list
        target_alert = next((a for a in alerts if a.id == alert.id), None)
        assert target_alert is not None
        assert target_alert.item_id == item.id
        assert target_alert.item_name == item.name
        assert target_alert.sku == item.sku
        assert target_alert.current_quantity == 5
        assert target_alert.reorder_level == 10
        assert target_alert.status == "active"
