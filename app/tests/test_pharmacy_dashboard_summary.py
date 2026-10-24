import pytest
import uuid
from datetime import datetime, timedelta, date, time
from app.core.database import AsyncSessionLocal, engine
from app.models.hospital_model import Hospital
from app.models.pharmacy_model import Medicine, PharmacyInvoice, Purchase, Supplier, Prescription
from app.services.pharmacy_service import PharmacyService
from app.utils.helpers import get_today_ist

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


@pytest.mark.asyncio
async def test_get_date_range_all_filters():
    async with AsyncSessionLocal() as session:
        service = PharmacyService(session)
        today = get_today_ist()

        # today
        s, e = service.get_date_range("today")
        assert s == datetime.combine(today, time.min)
        assert e == datetime.combine(today, time.max)

        # 7_days
        s, e = service.get_date_range("7_days")
        assert s == datetime.combine(today - timedelta(days=7), time.min)
        assert e == datetime.combine(today, time.max)

        # 30_days
        s, e = service.get_date_range("30_days")
        assert s == datetime.combine(today - timedelta(days=30), time.min)
        assert e == datetime.combine(today, time.max)

        # month / month_to_date
        s, e = service.get_date_range("month")
        assert s == datetime.combine(today.replace(day=1), time.min)
        assert e == datetime.combine(today, time.max)

        s_mtd, e_mtd = service.get_date_range("month_to_date")
        assert s_mtd == s and e_mtd == e

        # 3_month
        s, e = service.get_date_range("3_month")
        assert s == datetime.combine(today - timedelta(days=90), time.min)
        assert e == datetime.combine(today, time.max)

        # 6_month
        s, e = service.get_date_range("6_month")
        assert s == datetime.combine(today - timedelta(days=180), time.min)
        assert e == datetime.combine(today, time.max)

        # 1_year
        s, e = service.get_date_range("1_year")
        assert s == datetime.combine(today - timedelta(days=365), time.min)
        assert e == datetime.combine(today, time.max)

        # overall
        s, e = service.get_date_range("overall")
        assert s is None and e is None

        # custom: start and end
        custom_s = today - timedelta(days=14)
        custom_e = today - timedelta(days=2)
        s, e = service.get_date_range("custom", custom_s, custom_e)
        assert s == datetime.combine(custom_s, time.min)
        assert e == datetime.combine(custom_e, time.max)

        # custom: inverted start > end safe reordering
        s_inv, e_inv = service.get_date_range("custom", custom_e, custom_s)
        assert s_inv == s and e_inv == e

        # custom: missing start_date defaults to end_date - 7 days
        s_no_start, e_no_start = service.get_date_range("custom", None, custom_e)
        assert s_no_start == datetime.combine(custom_e - timedelta(days=7), time.min)
        assert e_no_start == datetime.combine(custom_e, time.max)

        # custom: missing end_date defaults to today
        s_no_end, e_no_end = service.get_date_range("custom", custom_s, None)
        assert s_no_end == datetime.combine(custom_s, time.min)
        assert e_no_end == datetime.combine(today, time.max)

        # invalid filter
        s_inv_filter, e_inv_filter = service.get_date_range("unknown_filter")
        assert s_inv_filter is None and e_inv_filter is None


@pytest.mark.asyncio
async def test_pharmacy_dashboard_date_filtering_and_hospital_isolation():
    uid = uuid.uuid4().hex[:8]
    today = get_today_ist()

    class DummyUser:
        def __init__(self, hospital_id):
            self.hospital_id = hospital_id

    async with AsyncSessionLocal() as session:
        # Create real hospitals to satisfy foreign key
        hA = Hospital(name=f"Hosp A {uid}", email=f"ha_{uid}@test.com", phone="1111111111", address="A")
        hB = Hospital(name=f"Hosp B {uid}", email=f"hb_{uid}@test.com", phone="2222222222", address="B")
        session.add_all([hA, hB])
        await session.flush()
        hosp_a_id = hA.id
        hosp_b_id = hB.id

        user_a = DummyUser(hosp_a_id)
        user_b = DummyUser(hosp_b_id)

        # Hospital A Invoices
        # 1. Today invoice: 100.0
        inv_today_a = PharmacyInvoice(
            invoice_number=f"INV_T_A_{uid}",
            hospital_id=hosp_a_id,
            status="completed",
            total_amount=100.0,
            is_deleted=False,
            created_at=datetime.combine(today, time(10, 30))
        )
        session.add(inv_today_a)

        # 2. 5 days ago invoice: 200.0
        inv_5d_a = PharmacyInvoice(
            invoice_number=f"INV_5D_A_{uid}",
            hospital_id=hosp_a_id,
            status="completed",
            total_amount=200.0,
            is_deleted=False,
            created_at=datetime.combine(today - timedelta(days=5), time(14, 0))
        )
        session.add(inv_5d_a)

        # 3. 20 days ago invoice: 400.0
        inv_20d_a = PharmacyInvoice(
            invoice_number=f"INV_20D_A_{uid}",
            hospital_id=hosp_a_id,
            status="completed",
            total_amount=400.0,
            is_deleted=False,
            created_at=datetime.combine(today - timedelta(days=20), time(15, 0))
        )
        session.add(inv_20d_a)

        # 4. 60 days ago invoice: 800.0
        inv_60d_a = PharmacyInvoice(
            invoice_number=f"INV_60D_A_{uid}",
            hospital_id=hosp_a_id,
            status="completed",
            total_amount=800.0,
            is_deleted=False,
            created_at=datetime.combine(today - timedelta(days=60), time(11, 0))
        )
        session.add(inv_60d_a)

        # 5. Cancelled invoice today: 999.0 (should not be counted)
        inv_canc_a = PharmacyInvoice(
            invoice_number=f"INV_CANC_A_{uid}",
            hospital_id=hosp_a_id,
            status="cancelled",
            total_amount=999.0,
            is_deleted=False,
            created_at=datetime.combine(today, time(12, 0))
        )
        session.add(inv_canc_a)

        # Hospital B Invoices (Isolation test)
        inv_today_b = PharmacyInvoice(
            invoice_number=f"INV_T_B_{uid}",
            hospital_id=hosp_b_id,
            status="completed",
            total_amount=5000.0,
            is_deleted=False,
            created_at=datetime.combine(today, time(10, 30))
        )
        session.add(inv_today_b)

        await session.commit()

        service = PharmacyService(session)

        # --- A. Filter = today for Hospital A ---
        res_today_a = await service.get_dashboard_summary("today", current_user=user_a)
        assert res_today_a.today_sales == 100.0
        assert res_today_a.today_sales_subtext == "Today's sales"

        # --- B. Filter = 7_days for Hospital A ---
        res_7d_a = await service.get_dashboard_summary("7_days", current_user=user_a)
        assert res_7d_a.today_sales == 300.0  # 100 + 200

        # --- C. Filter = 30_days for Hospital A ---
        res_30d_a = await service.get_dashboard_summary("30_days", current_user=user_a)
        assert res_30d_a.today_sales == 700.0  # 100 + 200 + 400

        # --- D. Filter = 3_month for Hospital A ---
        res_3m_a = await service.get_dashboard_summary("3_month", current_user=user_a)
        assert res_3m_a.today_sales == 1500.0  # 100 + 200 + 400 + 800

        # --- E. Filter = overall for Hospital A ---
        res_overall_a = await service.get_dashboard_summary("overall", current_user=user_a)
        assert res_overall_a.today_sales == 1500.0

        # --- F. Custom date range covering only 20 days ago invoice ---
        start_c = today - timedelta(days=25)
        end_c = today - timedelta(days=10)
        res_custom_a = await service.get_dashboard_summary("custom", start_date=start_c, end_date=end_c, current_user=user_a)
        assert res_custom_a.today_sales == 400.0

        # --- G. Hospital Isolation: Hospital B sees ONLY Hospital B's sales ---
        res_today_b = await service.get_dashboard_summary("today", current_user=user_b)
        assert res_today_b.today_sales == 5000.0


@pytest.mark.asyncio
async def test_pharmacy_dashboard_empty_dataset_and_compatibility():
    uid = uuid.uuid4().hex[:8]

    class DummyUser:
        def __init__(self, hospital_id):
            self.hospital_id = hospital_id

    async with AsyncSessionLocal() as session:
        hEmpty = Hospital(name=f"Hosp Empty {uid}", email=f"he_{uid}@test.com", phone="9999999999", address="Empty")
        session.add(hEmpty)
        await session.flush()

        empty_user = DummyUser(hEmpty.id)
        service = PharmacyService(session)

        # Empty hospital returns zeroed response without errors
        summary = await service.get_dashboard_summary("7_days", current_user=empty_user)
        assert summary.today_sales == 0.0
        assert summary.monthly_sales == 0.0
        assert summary.total_medicines == 0
        assert summary.low_stock_alerts == 0
        assert summary.total_suppliers == 0
        assert summary.pending_purchases == 0
        assert summary.prescriptions_count == 0
        assert summary.today_sales_trend == []
        assert summary.monthly_sales_trend == []
        assert summary.inventory_status_mix.expiring_soon == 0
        assert summary.inventory_health_progress.in_stock == 0.0


@pytest.mark.asyncio
async def test_pharmacy_dashboard_api_endpoint_filters_and_validation():
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    from app.core.dependencies import get_current_active_user, get_db

    uid = uuid.uuid4().hex[:8]
    today = get_today_ist()

    async with AsyncSessionLocal() as session:
        hosp = Hospital(name=f"Hosp API {uid}", email=f"api_{uid}@test.com", phone="1234512345", address="API")
        session.add(hosp)
        await session.flush()

        class MockRole:
            name = "Super Admin"

        class MockUser:
            id = 1
            hospital_id = hosp.id
            is_active = True
            role_id = 1
            role = MockRole()

        mock_user = MockUser()

        async def _override_user():
            return mock_user

        async def _override_db():
            yield session

        app.dependency_overrides[get_current_active_user] = _override_user
        app.dependency_overrides[get_db] = _override_db

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Default filter 200
            res = await client.get("/api/v1/pharmacy/dashboard/summary")
            assert res.status_code == 200
            data = res.json()["data"]
            assert "today_sales" in data
            assert "monthly_sales" in data
            assert "inventory_status_mix" in data

            # 2. Preset filters
            for f in ("today", "7_days", "30_days", "month_to_date", "month", "3_month", "6_month", "1_year", "overall"):
                res = await client.get(f"/api/v1/pharmacy/dashboard/summary?filter={f}")
                assert res.status_code == 200, f"Filter {f} failed with status {res.status_code}: {res.text}"

            # 3. Custom filter valid
            s_str = (today - timedelta(days=10)).isoformat()
            e_str = today.isoformat()
            res_custom = await client.get(f"/api/v1/pharmacy/dashboard/summary?filter=custom&start_date={s_str}&end_date={e_str}")
            assert res_custom.status_code == 200

            # 4. Custom filter missing dates -> 400
            res_bad_custom = await client.get("/api/v1/pharmacy/dashboard/summary?filter=custom")
            assert res_bad_custom.status_code == 400

            # 5. Invalid filter -> 400
            res_bad_filter = await client.get("/api/v1/pharmacy/dashboard/summary?filter=invalid_xyz")
            assert res_bad_filter.status_code == 400

            # 6. start_date > end_date -> 400
            res_inverted = await client.get(f"/api/v1/pharmacy/dashboard/summary?start_date={e_str}&end_date={s_str}")
            assert res_inverted.status_code == 400

        app.dependency_overrides.clear()
