import pytest
import uuid
from datetime import datetime, timedelta, date, time
from app.core.database import AsyncSessionLocal
from app.models.pharmacy_model import Medicine, PharmacyInvoice, Purchase, Supplier, Prescription
from app.services.pharmacy_service import PharmacyService

@pytest.mark.asyncio
async def test_pharmacy_dashboard_summary_all_cases():
    uid = uuid.uuid4().hex[:8]
    
    async with AsyncSessionLocal() as session:
        # Create an old medicine that is currently low stock and active
        old_med = Medicine(
            name=f"Med_{uid}",
            category="Tablet",
            unit="Strip",
            unit_price=10.0,
            stock_quantity=2,
            reorder_level=5,
            sku=f"SKU_1_{uid}",
            batch_number=f"BATCH_{uid}_1",
            is_active=True,
            is_deleted=False
        )
        session.add(old_med)
        
        # Create an old medicine that expired yesterday
        yesterday = date.today() - timedelta(days=1)
        exp_med = Medicine(
            name=f"ExpMed_{uid}",
            category="Tablet",
            unit="Strip",
            unit_price=10.0,
            stock_quantity=10,
            reorder_level=5,
            expiry_date=yesterday,
            sku=f"SKU_2_{uid}",
            batch_number=f"BATCH_{uid}_2",
            is_active=True,
            is_deleted=False
        )
        session.add(exp_med)
        await session.flush()
        
        service = PharmacyService(session)
        
        # --- 1. Snapshot Filters ---
        overview_overall = await service.get_dashboard_overview("overall", None, None)
        
        tomorrow = datetime.combine(datetime.today() + timedelta(days=1), time.min)
        next_week = tomorrow + timedelta(days=7)
        overview_future = await service.get_dashboard_overview("custom", tomorrow, next_week)
        
        assert overview_overall.total_medicines == overview_future.total_medicines
        assert overview_overall.low_stock_alerts == overview_future.low_stock_alerts
        assert overview_overall.total_suppliers == overview_future.total_suppliers
        assert overview_overall.pending_purchases == overview_future.pending_purchases
        assert overview_overall.prescriptions_count == overview_future.prescriptions_count
        
        # --- 2. Expiry Alerts ---
        assert overview_overall.expired_alerts == overview_future.expired_alerts
        assert overview_overall.expired_medicines_alerts == overview_future.expired_medicines_alerts
        
        # --- 3. Trend Filters ---
        assert isinstance(overview_future.monthly_sales_trend, list)

