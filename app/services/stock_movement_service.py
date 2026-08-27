from datetime import datetime
import uuid
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from app.models.inventory_model import InventoryItem, WarehouseStock, ItemBatch, StockTransaction

class StockMovementService:
    @staticmethod
    async def create_movement(
        db: AsyncSession,
        item_id: int,
        warehouse_id: int,
        transaction_type: str,
        direction: str,
        quantity: int,
        batch_id: int = None,
        unit_cost: float = 0.0,
        reference_type: str = None,
        reference_id: int = None,
        notes: str = None,
        performed_by: int = None
    ) -> StockTransaction:
        if quantity <= 0:
            raise ValueError("Quantity must be greater than 0")
        if direction not in ("IN", "OUT"):
            raise ValueError("Direction must be IN or OUT")

        if not performed_by:
            raise ValueError("Stock movement requires an authenticated user")

        from app.models.user_model import User
        from app.models.inventory_model import Warehouse
        u_hosp_id = await db.scalar(select(User.hospital_id).where(User.id == performed_by))
        w_hosp_id = await db.scalar(select(Warehouse.hospital_id).where(Warehouse.id == warehouse_id))

        if not u_hosp_id or not w_hosp_id or u_hosp_id != w_hosp_id:
            raise HTTPException(status_code=403, detail="User or warehouse not found or tenant mismatch")

        # 1. Lock WarehouseStock for safety
        ws_query = select(WarehouseStock).where(
            WarehouseStock.inventory_item_id == item_id,
            WarehouseStock.warehouse_id == warehouse_id
        ).with_for_update()
        result = await db.execute(ws_query)
        warehouse_stock = result.scalars().first()

        if reference_type and reference_id:
            dup_query = select(StockTransaction.id).where(
                StockTransaction.reference_type == reference_type,
                StockTransaction.reference_id == reference_id,
                StockTransaction.item_id == item_id
            )
            if batch_id:
                dup_query = dup_query.where(StockTransaction.batch_id == batch_id)
            else:
                dup_query = dup_query.where(StockTransaction.batch_id.is_(None))

            existing_tx = await db.scalar(dup_query)
            if existing_tx:
                raise HTTPException(status_code=400, detail="Duplicate stock movement detected for this reference.")


        if not warehouse_stock:
            # Create if IN, fail if OUT
            if direction == "OUT":
                raise HTTPException(status_code=400, detail="Insufficient stock (no record found)")

            from sqlalchemy.exc import IntegrityError
            try:
                async with db.begin_nested():
                    warehouse_stock = WarehouseStock(
                        warehouse_id=warehouse_id,
                        inventory_item_id=item_id,
                        quantity=0
                    )
                    db.add(warehouse_stock)
                    await db.flush()
            except IntegrityError:
                result = await db.execute(ws_query)
                warehouse_stock = result.scalars().first()
                if not warehouse_stock:
                    raise HTTPException(status_code=500, detail="Failed to acquire warehouse stock after concurrent insert")

        balance_before = warehouse_stock.quantity

        if direction == "OUT" and balance_before < quantity:
            raise HTTPException(status_code=400, detail=f"Insufficient warehouse stock (have {balance_before}, need {quantity})")

        balance_after = balance_before + quantity if direction == "IN" else balance_before - quantity
        warehouse_stock.quantity = balance_after

        # 2. Update Batch if provided
        if batch_id:
            batch_query = select(ItemBatch).where(ItemBatch.id == batch_id).with_for_update()
            batch_res = await db.execute(batch_query)
            batch = batch_res.scalars().first()
            if not batch:
                raise HTTPException(status_code=404, detail="Batch not found")

            if direction == "OUT" and batch.quantity < quantity:
                raise HTTPException(status_code=400, detail="Insufficient batch stock")

            batch.quantity = batch.quantity + quantity if direction == "IN" else batch.quantity - quantity

        # 3. Create Ledger Entry
        tx_number = f"TX-{uuid.uuid4().hex[:8].upper()}"

        transaction = StockTransaction(
            transaction_number=tx_number,
            item_id=item_id,
            warehouse_id=warehouse_id,
            batch_id=batch_id,
            transaction_type=transaction_type,
            direction=direction,
            quantity=quantity,
            balance_before=balance_before,
            balance_after=balance_after,
            unit_cost=unit_cost,
            reference_type=reference_type,
            reference_id=reference_id,
            notes=notes,
            performed_by=performed_by,
            transaction_date=datetime.utcnow()
        )
        db.add(transaction)
        await db.flush()

        return transaction
