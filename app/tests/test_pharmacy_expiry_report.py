import os
import io
import pypdf
import pytest
import uuid
from datetime import datetime, timedelta, date
from app.core.database import AsyncSessionLocal
from sqlalchemy import select, delete
from app.models.pharmacy_model import Medicine
from app.models.hospital_model import Hospital
from app.models.user_model import User
from app.services.report_service import ReportService
from app.services.report_export_service import ReportExportService
from app.repositories.report_repository import ReportRepository
from app.schemas.report_schema import PharmacyExpiryResponse, PharmacyExpiryItemResponse
from app.main import app
from app.core.dependencies import get_current_active_user, get_current_user
from httpx import AsyncClient, ASGITransport


def test_calculate_expiry_status_helper_logic():
    """Verify that calculate_expiry_status correctly handles 1, 2, 3, 4, 5, 30 days,
    singular 'Day' vs plural 'Days', expired items, and zero days.
    """
    ref_date = date(2026, 10, 27)

    expected_cases = [
        (date(2026, 10, 26), "Expired"),
        (date(2026, 10, 27), "Expiring in 0 Days"),
        (date(2026, 10, 28), "Expiring in 1 Day"),
        (date(2026, 10, 29), "Expiring in 2 Days"),
        (date(2026, 10, 30), "Expiring in 3 Days"),
        (date(2026, 10, 31), "Expiring in 4 Days"),
        (date(2026, 11, 1), "Expiring in 5 Days"),
        (date(2026, 11, 26), "Expiring in 30 Days"),
    ]

    for exp_dt, expected_status in expected_cases:
        repo_status = ReportRepository.calculate_expiry_status(exp_dt, current_date=ref_date)
        export_status = ReportExportService.calculate_expiry_status(exp_dt, current_date=ref_date)
        assert repo_status == expected_status, f"Repo status for {exp_dt} expected {expected_status}, got {repo_status}"
        assert export_status == expected_status, f"Export status for {exp_dt} expected {expected_status}, got {export_status}"


def test_pharmacy_expiry_pdf_direct_layout_and_summary_bar():
    """Verify that Pharmacy Expiry PDF export renders:
    1. Hospital branding and title in header.
    2. Generated At timestamp.
    3. Dedicated 2-cell summary bar (Total Medicines, Expiring Within 30 Days).
    4. Absence of duplicate Summary section.
    5. Expiry-specific columns and medicine items with accurate day statuses.
    6. Totals footer with Total (N Medicines) and total stock quantity.
    """
    today = date.today()
    items = [
        PharmacyExpiryItemResponse(
            id=1,
            name="Amoxicillin 500mg",
            generic_name="Amoxicillin",
            category="Antibiotics",
            sku="SKU-AMOX-500",
            batch_number="BATCH-001",
            unit="Capsule",
            stock_quantity=150,
            expiry_date=today + timedelta(days=1),
            status="Expiring in 1 Day"
        ),
        PharmacyExpiryItemResponse(
            id=2,
            name="Paracetamol 650mg",
            generic_name="Paracetamol",
            category="Analgesics",
            sku="SKU-PARA-650",
            batch_number="BATCH-002",
            unit="Tablet",
            stock_quantity=50,
            expiry_date=today + timedelta(days=2),
            status="Expiring in 2 Days"
        ),
        PharmacyExpiryItemResponse(
            id=3,
            name="Azithromycin 250mg",
            generic_name="Azithromycin",
            category="Antibiotics",
            sku="SKU-AZI-250",
            batch_number="BATCH-003",
            unit="Tablet",
            stock_quantity=30,
            expiry_date=today + timedelta(days=3),
            status="Expiring in 3 Days"
        ),
        PharmacyExpiryItemResponse(
            id=4,
            name="Cough Syrup 100ml",
            generic_name="Diphenhydramine",
            category="Syrups",
            sku="SKU-COUGH-100",
            batch_number="BATCH-004",
            unit="Bottle",
            stock_quantity=40,
            expiry_date=today + timedelta(days=5),
            status="Expiring in 5 Days"
        ),
        PharmacyExpiryItemResponse(
            id=5,
            name="Metformin 500mg",
            generic_name="Metformin",
            category="Antidiabetic",
            sku="SKU-MET-500",
            batch_number="BATCH-005",
            unit="Tablet",
            stock_quantity=80,
            expiry_date=today + timedelta(days=30),
            status="Expiring in 30 Days"
        ),
    ]

    total_stock_sum = sum(i.stock_quantity for i in items)

    resp = PharmacyExpiryResponse(
        total_medicines=len(items),
        expired_medicines=0,
        expiring_30_days=len(items),
        expiring_60_days=0,
        expiring_90_days=0,
        items=items
    )

    test_logo = os.path.abspath("app/static/logo.png") if os.path.exists("app/static/logo.png") else None
    payload = ReportService.build_export_payload(
        "Pharmacy Expiry",
        resp,
        hospital_name="NexaCare City Hospital",
        hospital_logo=test_logo
    )

    pdf_buf = ReportExportService.export_pdf(payload)
    reader = pypdf.PdfReader(pdf_buf)

    assert len(reader.pages) >= 1
    page1 = reader.pages[0]
    txt = page1.extract_text()

    # 1. Header elements
    assert "NexaCare City Hospital" in txt
    assert "Pharmacy Expiry" in txt
    assert "Generated At:" in txt

    # 2. Duplicate Summary: section must be suppressed
    assert "Summary:" not in txt

    # 3. Dedicated Expiry Summary Bar metrics (2-box 30-day layout)
    assert "Total Medicines: 5" in txt
    assert "Expiring Within 30 Days: 5" in txt
    assert "Expired:" not in txt
    assert "Expiring (≤30d):" not in txt
    assert "Expiring (31-60d):" not in txt
    assert "Expiring (61-90d):" not in txt

    # 4. Placement: Summary Bar must be ABOVE table headers and table footer
    sum_bar_pos = txt.find("Total Medicines: 5")
    header_pos = txt.find("Medicine Name")
    footer_pos = txt.find("Total (5 Medicines)")
    assert sum_bar_pos != -1, "Summary Bar not found"
    assert header_pos != -1, "Table header 'Medicine Name' not found"
    assert footer_pos != -1, "Table footer 'Total (5 Medicines)' not found"
    assert sum_bar_pos < header_pos < footer_pos, "Summary bar must appear above table headers, which appear above footer"

    # 5. Expiry Table Headers & Rows
    norm_txt = " ".join(txt.split())
    assert "Medicine Name" in norm_txt
    assert "Category" in norm_txt
    assert "Batch No." in norm_txt
    assert "Unit" in norm_txt
    assert "Stock Qty" in norm_txt
    assert "Expiry Date" in norm_txt
    assert "Expiry Status" in norm_txt

    assert "Amoxicillin 500mg" in txt
    assert "Paracetamol 650mg" in txt
    assert "Azithromycin 250mg" in txt
    assert "Cough Syrup 100ml" in txt
    assert "Metformin 500mg" in txt

    assert "Expiring in 1 Day" in txt
    assert "Expiring in 2 Days" in txt
    assert "Expiring in 3 Days" in txt
    assert "Expiring in 5 Days" in txt
    assert "Expiring in 30 Days" in txt

    # 6. Footer row calculations
    assert f"Total ({len(items)} Medicines)" in txt
    assert str(total_stock_sum) in txt


def test_pharmacy_expiry_empty_records_pdf():
    """Verify that an empty expiry report renders gracefully with 0 totals and empty state row."""
    resp = PharmacyExpiryResponse(
        total_medicines=0,
        expired_medicines=0,
        expiring_30_days=0,
        expiring_60_days=0,
        expiring_90_days=0,
        items=[]
    )

    payload = ReportService.build_export_payload(
        "Pharmacy Expiry",
        resp,
        hospital_name="Empty Hospital",
        hospital_logo=None
    )

    pdf_buf = ReportExportService.export_pdf(payload)
    reader = pypdf.PdfReader(pdf_buf)
    txt = reader.pages[0].extract_text()

    assert "Total Medicines: 0" in txt
    assert "Expiring Within 30 Days: 0" in txt
    assert "Expired:" not in txt
    assert "Expiring (≤30d):" not in txt
    assert "Expiring (31-60d):" not in txt
    assert "Expiring (61-90d):" not in txt
    assert "No pharmacy expiry records found." in txt
    assert "Total (0 Medicines)" in txt


@pytest.mark.asyncio
async def test_pharmacy_expiry_api_endpoint_and_tenant_isolation():
    """Integration test verifying that:
    1. Only medicines expiring today through next 30 days (inclusive) are returned.
    2. Accurate expiry status days are calculated (1, 2, 3, 5, 30 days) with proper singular/plural wording.
    3. Medicines expiring in 31 days, future medicines, and expired medicines are strictly EXCLUDED.
    4. Category filter works properly across included items.
    5. Tenant isolation prevents cross-hospital data leakage.
    6. PDF export contains the expected items and matching footer and summary counts.
    """
    uid = uuid.uuid4().hex[:8]
    today = date.today()

    async with AsyncSessionLocal() as session:
        # Create two hospitals for tenant isolation testing
        hospA = Hospital(name=f"HospA_{uid}", email=f"hospA_{uid}@test.com")
        hospB = Hospital(name=f"HospB_{uid}", email=f"hospB_{uid}@test.com")
        session.add_all([hospA, hospB])
        await session.flush()

        # Seed medicines for Hosp A:
        # Included in 30-day window: 1d, 2d, 3d, 5d, 30d
        medA_1d = Medicine(
            name=f"MedA_1d_{uid}",
            category="Antibiotics",
            sku=f"SKU_A1_{uid}",
            batch_number="B-1D",
            unit="Tablet",
            unit_price=10.0,
            stock_quantity=10,
            reorder_level=5,
            expiry_date=today + timedelta(days=1),
            is_active=True,
            hospital_id=hospA.id,
            is_deleted=False
        )
        medA_2d = Medicine(
            name=f"MedA_2d_{uid}",
            category="Syrups",
            sku=f"SKU_A2_{uid}",
            batch_number="B-2D",
            unit="Bottle",
            unit_price=50.0,
            stock_quantity=20,
            reorder_level=10,
            expiry_date=today + timedelta(days=2),
            is_active=True,
            hospital_id=hospA.id,
            is_deleted=False
        )
        medA_3d = Medicine(
            name=f"MedA_3d_{uid}",
            category="Antibiotics",
            sku=f"SKU_A3_{uid}",
            batch_number="B-3D",
            unit="Capsule",
            unit_price=25.0,
            stock_quantity=30,
            reorder_level=10,
            expiry_date=today + timedelta(days=3),
            is_active=True,
            hospital_id=hospA.id,
            is_deleted=False
        )
        medA_5d = Medicine(
            name=f"MedA_5d_{uid}",
            category="Ointments",
            sku=f"SKU_A5_{uid}",
            batch_number="B-5D",
            unit="Tube",
            unit_price=30.0,
            stock_quantity=15,
            reorder_level=5,
            expiry_date=today + timedelta(days=5),
            is_active=True,
            hospital_id=hospA.id,
            is_deleted=False
        )
        medA_30d = Medicine(
            name=f"MedA_30d_{uid}",
            category="Tablets",
            sku=f"SKU_A30_{uid}",
            batch_number="B-30D",
            unit="Tablet",
            unit_price=15.0,
            stock_quantity=25,
            reorder_level=5,
            expiry_date=today + timedelta(days=30),
            is_active=True,
            hospital_id=hospA.id,
            is_deleted=False
        )

        # Strictly EXCLUDED: Expired (< today)
        medA_expired = Medicine(
            name=f"MedA_Expired_{uid}",
            category="Antibiotics",
            sku=f"SKU_A_EXP_{uid}",
            batch_number="B-EXP",
            unit="Tablet",
            unit_price=10.0,
            stock_quantity=100,
            reorder_level=20,
            expiry_date=today - timedelta(days=5),
            is_active=True,
            hospital_id=hospA.id,
            is_deleted=False
        )
        # Strictly EXCLUDED: 31 days (> 30 days)
        medA_31d = Medicine(
            name=f"MedA_31d_{uid}",
            category="Antibiotics",
            sku=f"SKU_A31_{uid}",
            batch_number="B-31D",
            unit="Tablet",
            unit_price=20.0,
            stock_quantity=40,
            reorder_level=10,
            expiry_date=today + timedelta(days=31),
            is_active=True,
            hospital_id=hospA.id,
            is_deleted=False
        )
        # Strictly EXCLUDED: Future valid (200 days)
        medA_future = Medicine(
            name=f"MedA_Future_{uid}",
            category="Antibiotics",
            sku=f"SKU_AFUT_{uid}",
            batch_number="B-FUT",
            unit="Tablet",
            unit_price=15.0,
            stock_quantity=80,
            reorder_level=20,
            expiry_date=today + timedelta(days=200),
            is_active=True,
            hospital_id=hospA.id,
            is_deleted=False
        )

        # Seed medicine for Hosp B (must not leak into Hosp A report)
        medB = Medicine(
            name=f"MedB_Secret_{uid}",
            category="Injections",
            sku=f"SKU_B_{uid}",
            batch_number="B-SEC",
            unit="Vial",
            unit_price=120.0,
            stock_quantity=500,
            reorder_level=50,
            expiry_date=today + timedelta(days=5),
            is_active=True,
            hospital_id=hospB.id,
            is_deleted=False
        )
        session.add_all([
            medA_1d, medA_2d, medA_3d, medA_5d, medA_30d,
            medA_expired, medA_31d, medA_future, medB
        ])
        await session.commit()

        hospA_id = hospA.id
        hospB_id = hospB.id
        med_ids = [
            medA_1d.id, medA_2d.id, medA_3d.id, medA_5d.id, medA_30d.id,
            medA_expired.id, medA_31d.id, medA_future.id, medB.id
        ]

    class FakeUser:
        id = 1
        role_id = 1
        hospital_id = hospA_id
        is_active = True
        is_verified = True
        email = f"admin_{uid}@test.com"

        class role:
            name = "Hospital Admin"

    fake_user = FakeUser()
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_current_active_user] = lambda: fake_user

    try:
        from unittest.mock import patch, AsyncMock
        with patch("app.core.dependencies.RBACRepository.get_user_permissions", new=AsyncMock(return_value=["pharmacy:read"])):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # 1. Test JSON response
                resp = await client.get("/api/v1/reports/pharmacy/expiry")
                assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
                data = resp.json()

                # total_medicines and expiring_30_days must match exactly 5 items
                assert data["total_medicines"] == 5
                assert data["expiring_30_days"] == 5
                assert data["expired_medicines"] == 0
                assert data["expiring_60_days"] == 0
                assert data["expiring_90_days"] == 0

                # Check items list: must be exactly 5 items
                items = data.get("items", [])
                assert len(items) == 5
                item_names = [i["name"] for i in items]
                assert f"MedA_1d_{uid}" in item_names
                assert f"MedA_2d_{uid}" in item_names
                assert f"MedA_3d_{uid}" in item_names
                assert f"MedA_5d_{uid}" in item_names
                assert f"MedA_30d_{uid}" in item_names

                # Excluded medicines must NOT be returned
                assert f"MedA_Expired_{uid}" not in item_names
                assert f"MedA_31d_{uid}" not in item_names
                assert f"MedA_Future_{uid}" not in item_names
                # Hosp B medicine must not leak
                assert f"MedB_Secret_{uid}" not in item_names

                # Verify accurate statuses and singular/plural wording
                status_map = {i["name"]: i["status"] for i in items}
                assert status_map[f"MedA_1d_{uid}"] == "Expiring in 1 Day"
                assert status_map[f"MedA_2d_{uid}"] == "Expiring in 2 Days"
                assert status_map[f"MedA_3d_{uid}"] == "Expiring in 3 Days"
                assert status_map[f"MedA_5d_{uid}"] == "Expiring in 5 Days"
                assert status_map[f"MedA_30d_{uid}"] == "Expiring in 30 Days"

                # 2. Test Category Filter
                resp_filter = await client.get("/api/v1/reports/pharmacy/expiry?category=Antibiotics")
                assert resp_filter.status_code == 200
                data_filter = resp_filter.json()
                # Exactly 2 Antibiotics are in the 30-day window (MedA_1d and MedA_3d)
                assert data_filter["total_medicines"] == 2
                assert data_filter["expiring_30_days"] == 2
                assert len(data_filter["items"]) == 2
                for item in data_filter["items"]:
                    assert item["category"] == "Antibiotics"

                # 3. Test PDF export via ?export_format=pdf
                pdf_resp = await client.get("/api/v1/reports/pharmacy/expiry?export_format=pdf")
                assert pdf_resp.status_code == 200
                assert "application/pdf" in pdf_resp.headers.get("content-type", "")

                pdf_reader = pypdf.PdfReader(io.BytesIO(pdf_resp.content))
                assert len(pdf_reader.pages) >= 1
                pdf_text = pdf_reader.pages[0].extract_text()

                # Verify hospital branding & report title
                assert f"HospA_{uid}" in pdf_text
                assert f"HospB_{uid}" not in pdf_text
                assert "Pharmacy Expiry" in pdf_text
                assert "Generated At:" in pdf_text

                # Verify duplicate summary is suppressed
                assert "Summary:" not in pdf_text

                # Verify dedicated summary bar metrics (2-box 30-day layout)
                assert "Total Medicines: 5" in pdf_text
                assert "Expiring Within 30 Days: 5" in pdf_text
                assert "Expired:" not in pdf_text
                assert "Expiring (≤30d):" not in pdf_text
                assert "Expiring (31-60d):" not in pdf_text
                assert "Expiring (61-90d):" not in pdf_text

                # Verify items and individual statuses are rendered in table
                assert f"MedA_1d_{uid}" in pdf_text
                assert f"MedA_2d_{uid}" in pdf_text
                assert f"MedA_3d_{uid}" in pdf_text
                assert f"MedA_5d_{uid}" in pdf_text
                assert f"MedA_30d_{uid}" in pdf_text
                assert "Expiring in 1 Day" in pdf_text
                assert "Expiring in 2 Days" in pdf_text
                assert "Expiring in 3 Days" in pdf_text
                assert "Expiring in 5 Days" in pdf_text
                assert "Expiring in 30 Days" in pdf_text

                # Excluded medicines must NOT appear in PDF
                assert f"MedA_Expired_{uid}" not in pdf_text
                assert f"MedA_31d_{uid}" not in pdf_text
                assert f"MedA_Future_{uid}" not in pdf_text
                assert f"MedB_Secret_{uid}" not in pdf_text

                # Verify footer row
                assert "Total (5 Medicines)" in pdf_text
                assert "100" in pdf_text  # 10 + 20 + 30 + 15 + 25 = 100

    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_active_user, None)

        async with AsyncSessionLocal() as session:
            await session.execute(delete(Medicine).where(Medicine.id.in_(med_ids)))
            await session.execute(delete(Hospital).where(Hospital.id.in_([hospA_id, hospB_id])))
            await session.commit()


@pytest.mark.asyncio
async def test_pharmacy_expiry_all_future_medicines():
    """Verify that when all medicines in a hospital expire in future years (2027, 2028, 2030):
    1. All expiry bucket counts are 0.
    2. total_medicines == 0.
    3. items == [].
    4. PDF export renders the empty-state message and does not list those future-valid medicines.
    """
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as session:
        hosp = Hospital(name=f"HospFuture_{uid}", email=f"future_{uid}@test.com")
        session.add(hosp)
        await session.flush()

        med1 = Medicine(
            name=f"Med_2027_{uid}",
            category="Antibiotics",
            sku=f"SKU_27_{uid}",
            batch_number="B-2027",
            unit="Tablet",
            unit_price=10.0,
            stock_quantity=50,
            reorder_level=10,
            expiry_date=date(2027, 6, 15),
            is_active=True,
            hospital_id=hosp.id,
            is_deleted=False
        )
        med2 = Medicine(
            name=f"Med_2028_{uid}",
            category="Analgesics",
            sku=f"SKU_28_{uid}",
            batch_number="B-2028",
            unit="Tablet",
            unit_price=15.0,
            stock_quantity=100,
            reorder_level=20,
            expiry_date=date(2028, 1, 1),
            is_active=True,
            hospital_id=hosp.id,
            is_deleted=False
        )
        med3 = Medicine(
            name=f"Med_2030_{uid}",
            category="Syrups",
            sku=f"SKU_30_{uid}",
            batch_number="B-2030",
            unit="Bottle",
            unit_price=25.0,
            stock_quantity=30,
            reorder_level=5,
            expiry_date=date(2030, 12, 31),
            is_active=True,
            hospital_id=hosp.id,
            is_deleted=False
        )
        session.add_all([med1, med2, med3])
        await session.commit()

        hosp_id = hosp.id
        med_ids = [med1.id, med2.id, med3.id]

    class FakeUser:
        id = 1
        role_id = 1
        hospital_id = hosp_id
        is_active = True
        is_verified = True
        email = f"admin_future_{uid}@test.com"

        class role:
            name = "Hospital Admin"

    fake_user = FakeUser()
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_current_active_user] = lambda: fake_user

    try:
        from unittest.mock import patch, AsyncMock
        with patch("app.core.dependencies.RBACRepository.get_user_permissions", new=AsyncMock(return_value=["pharmacy:read"])):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # 1. Verify JSON response: all counts must be 0 and items empty
                resp = await client.get("/api/v1/reports/pharmacy/expiry")
                assert resp.status_code == 200
                data = resp.json()
                assert data["total_medicines"] == 0
                assert data["expired_medicines"] == 0
                assert data["expiring_30_days"] == 0
                assert data["expiring_60_days"] == 0
                assert data["expiring_90_days"] == 0
                assert data["items"] == []

                # 2. Verify PDF export
                pdf_resp = await client.get("/api/v1/reports/pharmacy/expiry?export_format=pdf")
                assert pdf_resp.status_code == 200
                assert "application/pdf" in pdf_resp.headers.get("content-type", "")

                reader = pypdf.PdfReader(io.BytesIO(pdf_resp.content))
                pdf_text = reader.pages[0].extract_text()

                assert f"HospFuture_{uid}" in pdf_text
                assert "Pharmacy Expiry" in pdf_text
                assert "Total Medicines: 0" in pdf_text
                assert "Expiring Within 30 Days: 0" in pdf_text
                assert "Expired:" not in pdf_text
                assert "Expiring (≤30d):" not in pdf_text
                assert "Expiring (31-60d):" not in pdf_text
                assert "Expiring (61-90d):" not in pdf_text

                # PDF empty-state message and footer row
                assert "No pharmacy expiry records found." in pdf_text
                assert "Total (0 Medicines)" in pdf_text

                # Ensure future medicines are NOT listed anywhere in the PDF
                assert f"Med_2027_{uid}" not in pdf_text
                assert f"Med_2028_{uid}" not in pdf_text
                assert f"Med_2030_{uid}" not in pdf_text

    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_active_user, None)

        async with AsyncSessionLocal() as session:
            await session.execute(delete(Medicine).where(Medicine.id.in_(med_ids)))
            await session.execute(delete(Hospital).where(Hospital.id == hosp_id))
            await session.commit()


@pytest.mark.asyncio
async def test_pharmacy_expiry_exact_day_boundaries():
    """Verify exact date boundary conditions for 30-day report:
    - yesterday (< today) -> EXCLUDED (expired)
    - today -> INCLUDED -> Expiring in 0 Days
    - day 1 -> INCLUDED -> Expiring in 1 Day
    - day 2 -> INCLUDED -> Expiring in 2 Days
    - day 3 -> INCLUDED -> Expiring in 3 Days
    - day 5 -> INCLUDED -> Expiring in 5 Days
    - day 30 -> INCLUDED -> Expiring in 30 Days
    - day 31 -> EXCLUDED (> 30 days)
    - day 60 -> EXCLUDED (> 30 days)
    - day 90 -> EXCLUDED (> 30 days)
    - day 91 -> EXCLUDED (> 30 days)
    """
    uid = uuid.uuid4().hex[:8]
    today = date.today()

    async with AsyncSessionLocal() as session:
        hosp = Hospital(name=f"HospBoundary_{uid}", email=f"boundary_{uid}@test.com")
        session.add(hosp)
        await session.flush()

        meds = [
            Medicine(
                name=f"B_Yesterday_{uid}",
                category="Tablets",
                sku=f"SKU_Y_{uid}",
                batch_number="B-Y",
                unit="Tab",
                unit_price=5.0,
                stock_quantity=10,
                reorder_level=5,
                expiry_date=today - timedelta(days=1),
                is_active=True,
                hospital_id=hosp.id,
                is_deleted=False
            ),
            Medicine(
                name=f"B_Today_{uid}",
                category="Tablets",
                sku=f"SKU_T0_{uid}",
                batch_number="B-T0",
                unit="Tab",
                unit_price=5.0,
                stock_quantity=10,
                reorder_level=5,
                expiry_date=today,
                is_active=True,
                hospital_id=hosp.id,
                is_deleted=False
            ),
            Medicine(
                name=f"B_Day1_{uid}",
                category="Tablets",
                sku=f"SKU_D1_{uid}",
                batch_number="B-D1",
                unit="Tab",
                unit_price=5.0,
                stock_quantity=10,
                reorder_level=5,
                expiry_date=today + timedelta(days=1),
                is_active=True,
                hospital_id=hosp.id,
                is_deleted=False
            ),
            Medicine(
                name=f"B_Day2_{uid}",
                category="Tablets",
                sku=f"SKU_D2_{uid}",
                batch_number="B-D2",
                unit="Tab",
                unit_price=5.0,
                stock_quantity=10,
                reorder_level=5,
                expiry_date=today + timedelta(days=2),
                is_active=True,
                hospital_id=hosp.id,
                is_deleted=False
            ),
            Medicine(
                name=f"B_Day3_{uid}",
                category="Tablets",
                sku=f"SKU_D3_{uid}",
                batch_number="B-D3",
                unit="Tab",
                unit_price=5.0,
                stock_quantity=10,
                reorder_level=5,
                expiry_date=today + timedelta(days=3),
                is_active=True,
                hospital_id=hosp.id,
                is_deleted=False
            ),
            Medicine(
                name=f"B_Day5_{uid}",
                category="Tablets",
                sku=f"SKU_D5_{uid}",
                batch_number="B-D5",
                unit="Tab",
                unit_price=5.0,
                stock_quantity=10,
                reorder_level=5,
                expiry_date=today + timedelta(days=5),
                is_active=True,
                hospital_id=hosp.id,
                is_deleted=False
            ),
            Medicine(
                name=f"B_Day30_{uid}",
                category="Tablets",
                sku=f"SKU_30_{uid}",
                batch_number="B-30",
                unit="Tab",
                unit_price=5.0,
                stock_quantity=10,
                reorder_level=5,
                expiry_date=today + timedelta(days=30),
                is_active=True,
                hospital_id=hosp.id,
                is_deleted=False
            ),
            Medicine(
                name=f"B_Day31_{uid}",
                category="Tablets",
                sku=f"SKU_31_{uid}",
                batch_number="B-31",
                unit="Tab",
                unit_price=5.0,
                stock_quantity=10,
                reorder_level=5,
                expiry_date=today + timedelta(days=31),
                is_active=True,
                hospital_id=hosp.id,
                is_deleted=False
            ),
            Medicine(
                name=f"B_Day60_{uid}",
                category="Tablets",
                sku=f"SKU_60_{uid}",
                batch_number="B-60",
                unit="Tab",
                unit_price=5.0,
                stock_quantity=10,
                reorder_level=5,
                expiry_date=today + timedelta(days=60),
                is_active=True,
                hospital_id=hosp.id,
                is_deleted=False
            ),
            Medicine(
                name=f"B_Day90_{uid}",
                category="Tablets",
                sku=f"SKU_90_{uid}",
                batch_number="B-90",
                unit="Tab",
                unit_price=5.0,
                stock_quantity=10,
                reorder_level=5,
                expiry_date=today + timedelta(days=90),
                is_active=True,
                hospital_id=hosp.id,
                is_deleted=False
            ),
            Medicine(
                name=f"B_Day91_Future_{uid}",
                category="Tablets",
                sku=f"SKU_91_{uid}",
                batch_number="B-91",
                unit="Tab",
                unit_price=5.0,
                stock_quantity=10,
                reorder_level=5,
                expiry_date=today + timedelta(days=91),
                is_active=True,
                hospital_id=hosp.id,
                is_deleted=False
            ),
        ]
        session.add_all(meds)
        await session.commit()

        hosp_id = hosp.id
        med_ids = [m.id for m in meds]

    class FakeUser:
        id = 1
        role_id = 1
        hospital_id = hosp_id
        is_active = True
        is_verified = True
        email = f"admin_b_{uid}@test.com"

        class role:
            name = "Hospital Admin"

    fake_user = FakeUser()
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_current_active_user] = lambda: fake_user

    try:
        from unittest.mock import patch, AsyncMock
        with patch("app.core.dependencies.RBACRepository.get_user_permissions", new=AsyncMock(return_value=["pharmacy:read"])):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/reports/pharmacy/expiry")
                assert resp.status_code == 200
                data = resp.json()

                # Exactly 6 medicines within 0 to 30 days inclusive
                assert data["total_medicines"] == 6
                assert data["expiring_30_days"] == 6
                assert data["expired_medicines"] == 0
                assert data["expiring_60_days"] == 0
                assert data["expiring_90_days"] == 0

                items = data.get("items", [])
                assert len(items) == 6
                item_names = [i["name"] for i in items]

                # Included items
                assert f"B_Today_{uid}" in item_names
                assert f"B_Day1_{uid}" in item_names
                assert f"B_Day2_{uid}" in item_names
                assert f"B_Day3_{uid}" in item_names
                assert f"B_Day5_{uid}" in item_names
                assert f"B_Day30_{uid}" in item_names

                # Excluded items
                assert f"B_Yesterday_{uid}" not in item_names
                assert f"B_Day31_{uid}" not in item_names
                assert f"B_Day60_{uid}" not in item_names
                assert f"B_Day90_{uid}" not in item_names
                assert f"B_Day91_Future_{uid}" not in item_names

                # Check each status and wording
                status_map = {i["name"]: i["status"] for i in items}
                assert status_map[f"B_Today_{uid}"] == "Expiring in 0 Days"
                assert status_map[f"B_Day1_{uid}"] == "Expiring in 1 Day"
                assert status_map[f"B_Day2_{uid}"] == "Expiring in 2 Days"
                assert status_map[f"B_Day3_{uid}"] == "Expiring in 3 Days"
                assert status_map[f"B_Day5_{uid}"] == "Expiring in 5 Days"
                assert status_map[f"B_Day30_{uid}"] == "Expiring in 30 Days"

    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_active_user, None)

        async with AsyncSessionLocal() as session:
            await session.execute(delete(Medicine).where(Medicine.id.in_(med_ids)))
            await session.execute(delete(Hospital).where(Hospital.id == hosp_id))
            await session.commit()
