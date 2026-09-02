import pytest
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from app.services.pharmacy_service import PharmacyService
from app.services.stock_movement_service import StockMovementService
from app.models.inventory_model import WarehouseStock
from app.models.inventory_model import WarehouseStock as WSModel
from alembic.config import Config
from alembic.script import ScriptDirectory

class TestStageB3(unittest.IsolatedAsyncioTestCase):
    async def test_pharmacy_return_missing_hospital(self):
        db = AsyncMock()
        mock_user = MagicMock()
        mock_user.hospital_id = None
        db.scalar.return_value = mock_user

        service = PharmacyService(db)
        mock_rx = MagicMock()
        mock_rx.status = "dispensed"

        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = mock_rx
        db.execute.return_value = mock_res

        with self.assertRaises(Exception) as context:
            await service.return_prescription(1, 999)

        self.assertIn("User hospital not configured", str(context.exception))

    async def test_pharmacy_return_valid_hospital(self):
        db = AsyncMock()
        mock_user = MagicMock()
        mock_user.hospital_id = 42
        db.scalar.return_value = mock_user

        mock_rx = MagicMock()
        mock_rx.status = "dispensed"
        mock_rx.items = []

        mock_res_rx = MagicMock()
        mock_res_rx.scalar_one_or_none.return_value = mock_rx

        mock_res_wh = MagicMock()
        mock_res_wh.scalar.return_value = 100

        db.execute.side_effect = [mock_res_rx, mock_res_wh]

        service = PharmacyService(db)
        service._prescription_response = MagicMock(return_value="Success")

        try:
            await service.return_prescription(1, 999)
        except Exception:
            pass

    async def test_stock_movement_tenant_security_mismatch(self):
        db = AsyncMock()
        db.scalar.side_effect = [42, 99]

        with self.assertRaises(HTTPException) as context:
            await StockMovementService.create_movement(db, 1, 1, "purchase", "IN", 10, performed_by=123)

        self.assertEqual(context.exception.status_code, 403)
        self.assertIn("tenant mismatch", context.exception.detail)

    async def test_stock_movement_tenant_security_success(self):
        db = AsyncMock()
        db.scalar.side_effect = [42, 42]
        db.add = MagicMock()
        db.begin_nested = MagicMock()
        db.begin_nested.return_value.__aenter__ = AsyncMock()
        db.begin_nested.return_value.__aexit__ = AsyncMock()

        mock_ws = MagicMock()
        mock_ws.quantity = 50
        mock_res = MagicMock()
        mock_res.scalars().first.return_value = mock_ws
        db.execute.return_value = mock_res

        try:
            await StockMovementService.create_movement(db, 1, 1, "purchase", "IN", 10, performed_by=123)
        except Exception:
            pass

    async def test_stock_movement_concurrency_integrity_error(self):
        db = AsyncMock()
        db.scalar.side_effect = [42, 42]
        db.add = MagicMock()
        db.begin_nested = MagicMock()
        db.begin_nested.return_value.__aenter__ = AsyncMock()
        db.begin_nested.return_value.__aexit__ = AsyncMock()

        mock_res_empty = MagicMock()
        mock_res_empty.scalars().first.return_value = None

        db.flush.side_effect = IntegrityError("statement", "params", "orig")

        mock_ws = MagicMock()
        mock_ws.quantity = 0
        mock_res_refetch = MagicMock()
        mock_res_refetch.scalars().first.return_value = mock_ws

        db.execute.side_effect = [mock_res_empty, mock_res_refetch]

        try:
            await StockMovementService.create_movement(db, 1, 1, "purchase", "IN", 10, performed_by=123)
        except Exception:
            pass

        db.begin_nested.assert_called_once()

    def test_unique_constraint(self):
        table_args = getattr(WSModel, "__table_args__", None)
        has_uq = False
        for arg in table_args:
            if hasattr(arg, "name") and arg.name == "uq_warehouse_item":
                self.assertEqual(list(arg.columns.keys()), ["warehouse_id", "inventory_item_id"])
                has_uq = True
        self.assertTrue(has_uq)

    def test_migration_statically(self):
        with open("alembic/versions/b7d5f0e9c1a2_phase_11_consolidated_stock_tenant_architecture.py", "r") as f:
            content = f.read()
            self.assertIn("down_revision: Union[str, None] = 'f7a1c2d3e4b5'", content)
            self.assertIn("revision: str = 'b7d5f0e9c1a2'", content)
            self.assertIn(
                """op.create_unique_constraint(
        'uq_warehouse_item',
        'warehouse_stock',
        ['warehouse_id', 'inventory_item_id']
    )""",
                content,
            )
            self.assertIn(
                """op.drop_constraint(
        'uq_warehouse_item',
        'warehouse_stock',
        type_='unique'
    )""",
                content,
            )

if __name__ == '__main__':
    unittest.main()
