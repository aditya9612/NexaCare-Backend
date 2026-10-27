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
from app.schemas.report_schema import PharmacyInventoryResponse, PharmacyInventoryItemResponse
from app.utils.helpers import utc_now
from app.main import app
from app.core.dependencies import get_current_active_user, get_current_user
from httpx import AsyncClient, ASGITransport


def test_pharmacy_inventory_pdf_direct_layout_and_summary_bar():
    """Verify that Pharmacy Inventory PDF export renders:
    1. Hospital branding and title in header.
    2. Generated At timestamp.
    3. Dedicated 4-cell summary bar positioned ABOVE the inventory table.
    4. Absence of duplicate Summary section.
    5. Inventory-specific columns and medicine items.
    6. Totals footer with Total (N Medicines) and total stock quantity.
    """
    items = [
        PharmacyInventoryItemResponse(
            id=1,
            name="Amoxicillin 500mg",
            generic_name="Amoxicillin",
            category="Antibiotics",
            sku="SKU-AMOX-500",
            batch_number="BATCH-001",
            unit="Capsule",
            unit_price=12.50,
            stock_quantity=150,
            reorder_level=20,
            expiry_date=date(2027, 5, 20),
            status="Active"
        ),
        PharmacyInventoryItemResponse(
            id=2,
            name="Paracetamol 650mg",
            generic_name="Paracetamol",
            category="Analgesics",
            sku="SKU-PARA-650",
            batch_number="BATCH-002",
            unit="Tablet",
            unit_price=2.00,
            stock_quantity=15,
            reorder_level=50,
            expiry_date=date(2026, 11, 15),
            status="Low Stock"
        ),
        PharmacyInventoryItemResponse(
            id=3,
            name="Azithromycin 250mg",
            generic_name="Azithromycin",
            category="Antibiotics",
            sku="SKU-AZI-250",
            batch_number="BATCH-003",
            unit="Tablet",
            unit_price=25.00,
            stock_quantity=0,
            reorder_level=10,
            expiry_date=date(2026, 12, 1),
            status="Out of Stock"
        ),
        PharmacyInventoryItemResponse(
            id=4,
            name="Metformin 500mg",
            generic_name="Metformin",
            category="Antidiabetic",
            sku="SKU-MET-500",
            batch_number="BATCH-004",
            unit="Tablet",
            unit_price=4.50,
            stock_quantity=80,
            reorder_level=25,
            expiry_date=date(2027, 8, 10),
            status="Active"
        ),
    ]

    total_stock_sum = sum(i.stock_quantity for i in items)
    low_stock_count = sum(1 for i in items if i.status == "Low Stock")
    out_of_stock_count = sum(1 for i in items if i.status == "Out of Stock")

    resp = PharmacyInventoryResponse(
        total_medicines=len(items),
        active_medicines=2,
        inactive_medicines=0,
        low_stock_medicines=low_stock_count,
        out_of_stock_medicines=out_of_stock_count,
        total_stock_quantity=total_stock_sum,
        items=items
    )

    test_logo = os.path.abspath("app/static/logo.png") if os.path.exists("app/static/logo.png") else None
    payload = ReportService.build_export_payload(
        "Pharmacy Inventory",
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
    assert "Pharmacy Inventory" in txt
    assert "Generated At:" in txt

    # 2. Duplicate Summary: section must be suppressed
    assert "Summary:" not in txt

    # 3. Dedicated Inventory Summary Bar metrics
    assert f"Total Medicines: {len(items)}" in txt
    assert f"Total Stock Qty: {total_stock_sum}" in txt
    assert f"Low Stock: {low_stock_count}" in txt
    assert f"Out of Stock: {out_of_stock_count}" in txt

    # 4. Placement: Summary Bar must be ABOVE table headers and table footer
    sum_bar_pos = txt.find("Total Medicines: 4")
    header_pos = txt.find("Medicine Name")
    footer_pos = txt.find("Total (4 Medicines)")
    assert sum_bar_pos != -1, "Summary Bar not found"
    assert header_pos != -1, "Table header 'Medicine Name' not found"
    assert footer_pos != -1, "Table footer 'Total (4 Medicines)' not found"
    assert sum_bar_pos < header_pos < footer_pos, "Summary bar must appear above table headers, which appear above footer"

    # 5. Inventory Table Headers & Rows
    norm_txt = " ".join(txt.split())
    assert "Medicine Name" in norm_txt
    assert "Category" in norm_txt
    assert "SKU" in norm_txt
    assert "Stock Qty" in norm_txt
    assert "Reorder Level" in norm_txt
    assert "Status" in norm_txt
    assert "Amoxicillin 500mg" in txt
    assert "Paracetamol 650mg" in txt
    assert "Azithromycin 250mg" in txt
    assert "Metformin 500mg" in txt

    # 6. Footer row calculations
    assert f"Total ({len(items)} Medicines)" in txt
    assert str(total_stock_sum) in txt


def test_pharmacy_inventory_empty_records_pdf():
    """Verify that an empty inventory report renders gracefully with 0 totals and empty state row."""
    resp = PharmacyInventoryResponse(
        total_medicines=0,
        active_medicines=0,
        inactive_medicines=0,
        low_stock_medicines=0,
        out_of_stock_medicines=0,
        total_stock_quantity=0,
        items=[]
    )

    payload = ReportService.build_export_payload(
        "Pharmacy Inventory",
        resp,
        hospital_name="Empty Hospital",
        hospital_logo=None
    )

    pdf_buf = ReportExportService.export_pdf(payload)
    reader = pypdf.PdfReader(pdf_buf)
    txt = reader.pages[0].extract_text()

    assert "Total Medicines: 0" in txt
    assert "Total Stock Qty: 0" in txt
    assert "No pharmacy inventory records found." in txt
    assert "Total (0 Medicines)" in txt


@pytest.mark.asyncio
async def test_pharmacy_inventory_api_endpoint_and_tenant_isolation():
    """Integration test for GET /api/v1/reports/pharmacy/inventory with PDF export & tenant isolation."""
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as session:
        # Create two hospitals for tenant isolation testing
        hospA = Hospital(name=f"HospA_{uid}", email=f"hospA_{uid}@test.com")
        hospB = Hospital(name=f"HospB_{uid}", email=f"hospB_{uid}@test.com")
        session.add_all([hospA, hospB])
        await session.flush()

        # Seed medicines for Hosp A
        medA1 = Medicine(
            name=f"MedA1_{uid}",
            category="Tablets",
            sku=f"SKU_A1_{uid}",
            batch_number="B-A1",
            unit="Strip",
            unit_price=10.0,
            stock_quantity=100,
            reorder_level=20,
            is_active=True,
            hospital_id=hospA.id,
            is_deleted=False
        )
        medA2 = Medicine(
            name=f"MedA2_{uid}",
            category="Syrups",
            sku=f"SKU_A2_{uid}",
            batch_number="B-A2",
            unit="Bottle",
            unit_price=50.0,
            stock_quantity=5,
            reorder_level=10,
            is_active=True,
            hospital_id=hospA.id,
            is_deleted=False
        )
        # Seed medicine for Hosp B (must not leak into Hosp A report)
        medB = Medicine(
            name=f"MedB_Secret_{uid}",
            category="Injections",
            sku=f"SKU_B_{uid}",
            batch_number="B-B1",
            unit="Vial",
            unit_price=120.0,
            stock_quantity=500,
            reorder_level=50,
            is_active=True,
            hospital_id=hospB.id,
            is_deleted=False
        )
        session.add_all([medA1, medA2, medB])
        await session.commit()

        hospA_id = hospA.id
        med_ids = [medA1.id, medA2.id, medB.id]

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
    app.dependency_overrides[get_current_active_user] = lambda: fake_user
    app.dependency_overrides[get_current_user] = lambda: fake_user

    try:
        from unittest.mock import patch, AsyncMock
        with patch("app.core.dependencies.RBACRepository.get_user_permissions", new=AsyncMock(return_value=["pharmacy:read"])):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # 1. Test JSON response includes items list
                json_res = await client.get("/api/v1/reports/pharmacy/inventory")
                assert json_res.status_code == 200
                data = json_res.json()
                assert data["total_medicines"] == 2
                assert data["total_stock_quantity"] == 105
                assert data["low_stock_medicines"] == 1
                assert "items" in data
                assert len(data["items"]) == 2
                names = [item["name"] for item in data["items"]]
                assert f"MedA1_{uid}" in names
                assert f"MedA2_{uid}" in names
                assert f"MedB_Secret_{uid}" not in names, "Cross-tenant data must not leak"

                # 2. Test PDF export via export_format=pdf
                pdf_res = await client.get("/api/v1/reports/pharmacy/inventory?export_format=pdf")
                assert pdf_res.status_code == 200
                assert pdf_res.headers.get("content-type") == "application/pdf"

                reader = pypdf.PdfReader(io.BytesIO(pdf_res.content))
                page_txt = reader.pages[0].extract_text()

                assert f"HospA_{uid}" in page_txt
                assert "Pharmacy Inventory" in page_txt
                assert "Summary:" not in page_txt
                assert "Total Medicines: 2" in page_txt
                assert "Total Stock Qty: 105" in page_txt
                assert "Low Stock: 1" in page_txt
                assert f"MedA1_{uid}" in page_txt
                assert f"MedA2_{uid}" in page_txt
                assert f"MedB_Secret_{uid}" not in page_txt, "Cross-tenant data must not leak into PDF"
                assert "Total (2 Medicines)" in page_txt

                # 3. Test PDF export via format=pdf
                pdf_res2 = await client.get("/api/v1/reports/pharmacy/inventory?format=pdf")
                assert pdf_res2.status_code == 200
                assert pdf_res2.headers.get("content-type") == "application/pdf"

    finally:
        app.dependency_overrides.clear()
        async with AsyncSessionLocal() as session:
            for m_id in med_ids:
                try:
                    obj = await session.get(Medicine, m_id)
                    if obj:
                        await session.delete(obj)
                except Exception:
                    pass
            for h in [hospA, hospB]:
                try:
                    obj = await session.get(Hospital, h.id)
                    if obj:
                        await session.delete(obj)
                except Exception:
                    pass
            await session.commit()
