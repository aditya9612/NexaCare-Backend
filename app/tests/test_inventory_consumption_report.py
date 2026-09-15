import uuid
import pytest
from app.core.database import AsyncSessionLocal
from app.models.inventory_model import InventoryItem, StockTransaction, Warehouse
from app.services.inventory_service import InventoryService
from app.utils.helpers import utc_now


@pytest.mark.asyncio
async def test_get_consumption_report_monthly():
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        # Create warehouse & item
        warehouse = Warehouse(
            name=f"ReportWh_{uid}",
            code=f"WH_{uid}",
            location="Building A",
            is_active=True,
        )
        session.add(warehouse)
        await session.commit()
        await session.refresh(warehouse)

        item = InventoryItem(
            name=f"ReportItem_{uid}",
            sku=f"RPSKU_{uid}",
            category="Consumables",
            quantity=100,
            unit="Box",
            unit_cost=20.0,
            reorder_level=10,
            is_active=True,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)

        # Create a consumption transaction within last 30 days
        transaction = StockTransaction(
            transaction_number=f"TX_{uid}",
            item_id=item.id,
            warehouse_id=warehouse.id,
            transaction_type="consumption",
            quantity=15,
            unit_cost=20.0,
            transaction_date=utc_now(),
        )
        session.add(transaction)
        await session.commit()

        service = InventoryService(session)

        # Call get_consumption_report with period="monthly"
        reports = await service.get_consumption_report(period="monthly")
        assert reports is not None
        assert isinstance(reports, list)
        assert len(reports) >= 1

        # Find created item in report
        target_report = next((r for r in reports if r.item_id == item.id), None)
        assert target_report is not None
        assert target_report.period == "monthly"
        assert target_report.item_id == item.id
        assert target_report.item_name == item.name
        assert target_report.sku == item.sku
        assert target_report.total_consumed == 15
        assert target_report.total_value == 300.0
