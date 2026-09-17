import pytest
import uuid
from datetime import datetime, timedelta, date, time
from app.core.database import AsyncSessionLocal
from app.models.pharmacy_model import PharmacyInvoice, Medicine
from app.services.report_service import ReportService
from fastapi.exceptions import HTTPException

@pytest.mark.asyncio
async def test_pharmacy_sales_report_all_cases():
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as session:
        # We need invoices in different periods.
        today = date.today()

        # 1. Historical Invoice (2 years ago)
        hist_date = today - timedelta(days=700)
        hist_inv = PharmacyInvoice(
            invoice_number=f"INV_HIST_{uid}",
            status="completed",
            total_amount=100.0,
            is_deleted=False
        )
        session.add(hist_inv)

        # 2. Today's Invoice
        today_inv = PharmacyInvoice(
            invoice_number=f"INV_TDY_{uid}",

            status="completed",
            total_amount=200.0,
            is_deleted=False
        )
        session.add(today_inv)

        # 3. This Month's Invoice
        month_inv = PharmacyInvoice(
            invoice_number=f"INV_MON_{uid}",

            status="completed",
            total_amount=300.0,
            is_deleted=False
        )
        session.add(month_inv)

        # 4. This Year's Invoice
        year_inv = PharmacyInvoice(
            invoice_number=f"INV_YR_{uid}",

            status="completed",
            total_amount=400.0,
            is_deleted=False
        )
        session.add(year_inv)

        # 5. Cancelled Invoice
        cancelled_inv = PharmacyInvoice(
            invoice_number=f"INV_CANC_{uid}",

            status="cancelled",
            total_amount=500.0,
            is_deleted=False
        )
        session.add(cancelled_inv)

        await session.commit()

        # Overwrite created_at
        hist_time = datetime.combine(hist_date, time(12, 0))
        hist_inv.created_at = hist_time

        today_time = datetime.combine(today, time(12, 0))
        today_inv.created_at = today_time
        cancelled_inv.created_at = today_time

        month_time = datetime.combine(today.replace(day=1), time(12, 0))
        month_inv.created_at = month_time

        if today.month > 1:
            year_time = datetime.combine(today.replace(month=1, day=1), time(12, 0))
        else:
            year_time = datetime.combine(today.replace(month=1, day=2), time(12, 0))

        year_inv.created_at = year_time

        await session.commit()

        service = ReportService(session)
        import calendar

        def calc_s_e(period):
            if period == "all":
                return None, None
            elif period == "daily":
                return today, today
            elif period == "monthly":
                return today.replace(day=1), today.replace(day=calendar.monthrange(today.year, today.month)[1])
            elif period == "yearly":
                return today.replace(month=1, day=1), today.replace(month=12, day=31)
            return None, None

        # --- A. period=all ---
        sales_all = await service.get_pharmacy_sales(None, None)
        assert sales_all.total_sales > 0
        assert sales_all.total_invoices >= 4

        # --- B. period=daily ---
        s_day, e_day = calc_s_e("daily")
        sales_day = await service.get_pharmacy_sales(s_day, e_day)
        # Should include today_inv
        assert sales_all.total_sales >= sales_day.total_sales + 100.0

        # --- C. period=monthly ---
        s_mon, e_mon = calc_s_e("monthly")
        sales_mon = await service.get_pharmacy_sales(s_mon, e_mon)
        assert sales_all.total_sales >= sales_mon.total_sales + 100.0

        # --- D. period=yearly ---
        s_yr, e_yr = calc_s_e("yearly")
        sales_yr = await service.get_pharmacy_sales(s_yr, e_yr)
        assert sales_all.total_sales >= sales_yr.total_sales + 100.0

        # --- E. Explicit date range ---
        sales_explicit = await service.get_pharmacy_sales(hist_date, hist_date)
        assert sales_explicit.total_sales >= 100.0
        assert sales_explicit.total_sales < sales_all.total_sales

        # --- Router Integration Test ---
        from httpx import AsyncClient, ASGITransport
        from app.main import app
        from app.models.user_model import User
        from app.core.dependencies import get_current_active_user, get_current_user
        from unittest.mock import patch

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            u = User(id=1, email="test@test.com", is_active=True, is_verified=True, hashed_password="pw", user_code="TEST1")
            app.dependency_overrides[get_current_active_user] = lambda: u
            app.dependency_overrides[get_current_user] = lambda: u

            with patch('app.core.dependencies.require_permission') as mock_req:
                mock_req.return_value = lambda: u
                with patch('app.core.dependencies.RBACRepository.get_user_permissions') as mock_rbac:
                    mock_rbac.return_value = ["pharmacy:read"]

                    # --- G. Invalid period ---
                    resp = await ac.get("/api/v1/reports/pharmacy/sales?period=invalid")
                    assert resp.status_code == 400

                    # period=all
                    resp_all = await ac.get("/api/v1/reports/pharmacy/sales?period=all")
                    assert resp_all.status_code == 200
                    data_all = resp_all.json()
                    assert data_all["total_sales"] > 0

            app.dependency_overrides.clear()
