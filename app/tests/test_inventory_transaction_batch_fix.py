import uuid
import pytest
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.core.exceptions import BadRequestException
from app.models.hospital_model import Hospital
from app.models.inventory_model import InventoryItem, Warehouse
from app.models.user_model import User
from app.schemas.inventory_schema import StockTransactionCreate
from app.services.inventory_service import InventoryService


@pytest.mark.asyncio
async def test_inventory_transaction_batch_and_warehouse_validations():
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        # Get or create hospital
        hosp = await session.scalar(select(Hospital).limit(1))
        if not hosp:
            hosp = Hospital(
                name=f"Hosp_{uid}",
                email=f"hosp_{uid}@example.com",
                is_active=True,
            )
            session.add(hosp)
            await session.commit()
            await session.refresh(hosp)

        # Ensure user with id=1 has hosp.id
        user = await session.get(User, 1)
        if user:
            user.hospital_id = hosp.id
            await session.commit()

        # Create warehouse with hosp.id
        warehouse = Warehouse(
            name=f"WH_{uid}",
            code=f"WHC_{uid}",
            location="Storage A",
            hospital_id=hosp.id,
        )
        session.add(warehouse)
        await session.commit()
        await session.refresh(warehouse)

        # Create item with warehouse
        item = InventoryItem(
            name=f"Item_{uid}",
            sku=f"SKU_{uid}",
            category="Surgicals",
            quantity=50,
            unit="Box",
            unit_cost=10.0,
            warehouse_id=warehouse.id,
            is_active=True,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)

        service = InventoryService(session)

        # 1. Payload WITHOUT batch_id (reproducing original issue) -> MUST succeed (HTTP 201 equivalent)
        data_without_batch = StockTransactionCreate(
            item_id=item.id,
            warehouse_id=warehouse.id,
            transaction_type="INWARD",
            type="INWARD",
            quantity=10,
            unit_cost=0,
            reference_type="Opening Stock",
            reference_id=1,
            notes="",
            target_warehouse_id=None,
        )

        resp = await service.create_transaction(data_without_batch, user_id=1)
        assert resp is not None
        assert resp.item_id == item.id
        assert resp.quantity == 10

        # 2. Payload WITH batch_id -> MUST succeed
        data_with_batch = StockTransactionCreate(
            item_id=item.id,
            warehouse_id=warehouse.id,
            batch_id=None,
            transaction_type="INWARD",
            quantity=5,
        )
        resp2 = await service.create_transaction(data_with_batch, user_id=1)
        assert resp2 is not None
        assert resp2.quantity == 5

        # 3. Create item WITHOUT warehouse_id and test missing warehouse -> MUST raise BadRequestException (HTTP 400)
        item_no_wh = InventoryItem(
            name=f"Item_No_WH_{uid}",
            sku=f"SKU_NO_WH_{uid}",
            category="Surgicals",
            quantity=50,
            unit="Box",
            unit_cost=10.0,
            warehouse_id=None,
            is_active=True,
        )
        session.add(item_no_wh)
        await session.commit()
        await session.refresh(item_no_wh)

        data_missing_wh = StockTransactionCreate(
            item_id=item_no_wh.id,
            warehouse_id=None,
            transaction_type="INWARD",
            quantity=10,
        )

        with pytest.raises(BadRequestException) as exc_info:
            await service.create_transaction(data_missing_wh, user_id=1)
        assert exc_info.value.detail == "Warehouse ID is required for stock transaction"
