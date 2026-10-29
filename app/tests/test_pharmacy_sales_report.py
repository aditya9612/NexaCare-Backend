import os
import calendar
import io
import pypdf
import pytest
import uuid
from datetime import datetime, timedelta, date, time
from app.core.database import AsyncSessionLocal
from sqlalchemy import select, delete
from app.models.pharmacy_model import PharmacyInvoice
from app.models.patient_model import Patient
from app.models.hospital_model import Hospital
from app.models.user_model import User
from app.services.report_service import ReportService
from app.services.report_export_service import ReportExportService
from app.schemas.report_schema import PharmacySalesResponse, PharmacySalesItemResponse
from app.utils.helpers import utc_now
from app.main import app
from app.core.dependencies import get_current_active_user, get_current_user
from httpx import AsyncClient, ASGITransport
from fastapi.exceptions import HTTPException


@pytest.mark.asyncio
async def test_pharmacy_sales_report_all_cases():
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as session:
        from sqlalchemy import delete
        await session.execute(
            delete(PharmacyInvoice).where(
                PharmacyInvoice.invoice_number.like("INV_HIST_%") |
                PharmacyInvoice.invoice_number.like("INV_TDY_%") |
                PharmacyInvoice.invoice_number.like("INV_MON_%") |
                PharmacyInvoice.invoice_number.like("INV_YR_%") |
                PharmacyInvoice.invoice_number.like("INV_CANC_%") |
                PharmacyInvoice.invoice_number.like("INV_DEL_%") |
                PharmacyInvoice.invoice_number.like("INV_OTHER_%")
            )
        )
        await session.commit()

        today = date.today()

        # Create two test hospitals for tenant isolation
        hosp1 = Hospital(name=f"Hosp 1 {uid}", email=f"hosp1_{uid}@test.com")
        hosp2 = Hospital(name=f"Hosp 2 {uid}", email=f"hosp2_{uid}@test.com")
        session.add_all([hosp1, hosp2])
        await session.flush()

        # Create a test patient linked to hosp1 to test outer join relationship
        patient = Patient(
            first_name="Ramesh",
            last_name="Sharma",
            patient_code=f"PAT_{uid}",
            hospital_id=hosp1.id,
            is_deleted=False
        )
        session.add(patient)
        await session.flush()

        # 1. Historical Invoice (2 years ago)
        hist_date = today - timedelta(days=700)
        hist_inv = PharmacyInvoice(
            invoice_number=f"INV_HIST_{uid}",
            status="completed",
            total_amount=100.0,
            subtotal=90.0,
            discount_amount=0.0,
            tax_amount=10.0,
            paid_amount=100.0,
            payment_mode="Cash",
            hospital_id=hosp1.id,
            is_deleted=False
        )
        session.add(hist_inv)

        # 2. Today's Invoice (linked to patient)
        today_inv = PharmacyInvoice(
            invoice_number=f"INV_TDY_{uid}",
            status="completed",
            patient_id=patient.id,
            subtotal=180.0,
            discount_amount=10.0,
            tax_amount=30.0,
            total_amount=200.0,
            paid_amount=200.0,
            payment_mode="UPI",
            hospital_id=hosp1.id,
            is_deleted=False
        )
        session.add(today_inv)

        # 3. This Month's Invoice
        month_inv = PharmacyInvoice(
            invoice_number=f"INV_MON_{uid}",
            status="completed",
            subtotal=270.0,
            discount_amount=0.0,
            tax_amount=30.0,
            total_amount=300.0,
            paid_amount=300.0,
            payment_mode="Card",
            hospital_id=hosp1.id,
            is_deleted=False
        )
        session.add(month_inv)

        # 4. This Year's Invoice
        year_inv = PharmacyInvoice(
            invoice_number=f"INV_YR_{uid}",
            status="completed",
            subtotal=360.0,
            discount_amount=0.0,
            tax_amount=40.0,
            total_amount=400.0,
            paid_amount=400.0,
            payment_mode="Cash",
            hospital_id=hosp1.id,
            is_deleted=False
        )
        session.add(year_inv)

        # 5. Cancelled Invoice (must be excluded from summary and records list)
        cancelled_inv = PharmacyInvoice(
            invoice_number=f"INV_CANC_{uid}",
            status="cancelled",
            subtotal=500.0,
            discount_amount=0.0,
            tax_amount=0.0,
            total_amount=500.0,
            paid_amount=0.0,
            hospital_id=hosp1.id,
            is_deleted=False
        )
        session.add(cancelled_inv)

        # 6. Soft-Deleted Invoice (must be excluded from summary and records list)
        deleted_inv = PharmacyInvoice(
            invoice_number=f"INV_DEL_{uid}",
            status="completed",
            subtotal=600.0,
            discount_amount=0.0,
            tax_amount=0.0,
            total_amount=600.0,
            paid_amount=600.0,
            hospital_id=hosp1.id,
            is_deleted=True
        )
        session.add(deleted_inv)

        # 7. Another Hospital's Invoice (for tenant isolation test)
        other_hosp_inv = PharmacyInvoice(
            invoice_number=f"INV_OTHER_{uid}",
            status="completed",
            subtotal=700.0,
            discount_amount=0.0,
            tax_amount=0.0,
            total_amount=700.0,
            paid_amount=700.0,
            payment_mode="Cash",
            hospital_id=hosp2.id,
            is_deleted=False
        )
        session.add(other_hosp_inv)

        await session.commit()

        # Explicitly align timestamps
        hist_time = datetime.combine(hist_date, time(12, 0))
        hist_inv.created_at = hist_time

        today_time = datetime.combine(today, time(12, 0))
        today_inv.created_at = today_time
        cancelled_inv.created_at = today_time
        deleted_inv.created_at = today_time
        other_hosp_inv.created_at = today_time

        month_time = datetime.combine(today.replace(day=1), time(12, 0))
        month_inv.created_at = month_time

        if today.month > 1:
            year_time = datetime.combine(today.replace(month=1, day=1), time(12, 0))
        else:
            year_time = datetime.combine(today.replace(month=1, day=2), time(12, 0))
        year_inv.created_at = year_time

        await session.commit()

        service = ReportService(session)

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
        assert sales_all.total_invoices >= 5
        assert hasattr(sales_all, "items")
        assert hasattr(sales_all, "records")
        assert sales_all.records == sales_all.items
        assert len(sales_all.items) >= 5

        # Check records list structure and fields
        inv_numbers = [item.invoice_number for item in sales_all.items]
        assert f"INV_HIST_{uid}" in inv_numbers
        assert f"INV_TDY_{uid}" in inv_numbers
        assert f"INV_MON_{uid}" in inv_numbers
        assert f"INV_YR_{uid}" in inv_numbers
        assert f"INV_OTHER_{uid}" in inv_numbers

        # Exclusion of cancelled and deleted invoices
        assert f"INV_CANC_{uid}" not in inv_numbers
        assert f"INV_DEL_{uid}" not in inv_numbers
        assert all(item.status != "cancelled" for item in sales_all.items)

        # Patient relationship join verification
        today_record = next(item for item in sales_all.items if item.invoice_number == f"INV_TDY_{uid}")
        assert today_record.patient_id == patient.id
        assert today_record.patient_name == "Ramesh Sharma"
        assert today_record.payment_mode == "UPI"
        assert today_record.subtotal == 180.0
        assert today_record.discount_amount == 10.0
        assert today_record.tax_amount == 30.0
        assert today_record.total_amount == 200.0
        assert today_record.paid_amount == 200.0
        assert today_record.status == "completed"
        assert today_record.invoice_id == today_record.id

        # --- B. Tenant Isolation Test ---
        sales_hosp1 = await service.get_pharmacy_sales(None, None, hospital_id=hosp1.id)
        hosp1_numbers = [item.invoice_number for item in sales_hosp1.items]
        assert f"INV_TDY_{uid}" in hosp1_numbers
        assert f"INV_OTHER_{uid}" not in hosp1_numbers

        sales_hosp2 = await service.get_pharmacy_sales(None, None, hospital_id=hosp2.id)
        hosp2_numbers = [item.invoice_number for item in sales_hosp2.items]
        assert f"INV_OTHER_{uid}" in hosp2_numbers
        assert f"INV_TDY_{uid}" not in hosp2_numbers
        assert sales_hosp2.total_sales >= 700.0

        # --- C. period=daily ---
        s_day, e_day = calc_s_e("daily")
        sales_day = await service.get_pharmacy_sales(s_day, e_day, hospital_id=hosp1.id)
        day_numbers = [item.invoice_number for item in sales_day.items]
        assert f"INV_TDY_{uid}" in day_numbers
        assert f"INV_HIST_{uid}" not in day_numbers

        # --- D. period=monthly ---
        s_mon, e_mon = calc_s_e("monthly")
        sales_mon = await service.get_pharmacy_sales(s_mon, e_mon, hospital_id=hosp1.id)
        mon_numbers = [item.invoice_number for item in sales_mon.items]
        assert f"INV_TDY_{uid}" in mon_numbers
        assert f"INV_MON_{uid}" in mon_numbers
        assert f"INV_HIST_{uid}" not in mon_numbers

        # --- E. period=yearly ---
        s_yr, e_yr = calc_s_e("yearly")
        sales_yr = await service.get_pharmacy_sales(s_yr, e_yr, hospital_id=hosp1.id)
        yr_numbers = [item.invoice_number for item in sales_yr.items]
        assert f"INV_TDY_{uid}" in yr_numbers
        assert f"INV_YR_{uid}" in yr_numbers
        assert f"INV_HIST_{uid}" not in yr_numbers

        # --- F. Explicit date range ---
        sales_explicit = await service.get_pharmacy_sales(hist_date, hist_date, hospital_id=hosp1.id)
        assert sales_explicit.total_sales >= 100.0
        assert all(item.invoice_date.date() == hist_date for item in sales_explicit.items)
        assert f"INV_HIST_{uid}" in [item.invoice_number for item in sales_explicit.items]
        assert f"INV_TDY_{uid}" not in [item.invoice_number for item in sales_explicit.items]

        # --- G. Pagination (limit & offset) ---
        sales_page1 = await service.get_pharmacy_sales(None, None, hospital_id=hosp1.id, limit=2, offset=0)
        assert len(sales_page1.items) == 2
        assert sales_page1.total_invoices >= 4

        sales_page2 = await service.get_pharmacy_sales(None, None, hospital_id=hosp1.id, limit=2, offset=2)
        assert len(sales_page2.items) >= 2
        page1_ids = {item.id for item in sales_page1.items}
        page2_ids = {item.id for item in sales_page2.items}
        assert page1_ids.isdisjoint(page2_ids)

        # --- Router Integration Test ---
        from httpx import AsyncClient, ASGITransport
        from app.main import app
        from app.models.user_model import User
        from app.core.dependencies import get_current_active_user, get_current_user
        from unittest.mock import patch

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            u = User(id=1, email=f"user_{uid}@test.com", is_active=True, is_verified=True, hashed_password="pw", user_code=f"U_{uid}", hospital_id=hosp1.id)
            app.dependency_overrides[get_current_active_user] = lambda: u
            app.dependency_overrides[get_current_user] = lambda: u

            with patch('app.core.dependencies.require_permission') as mock_req:
                mock_req.return_value = lambda: u
                with patch('app.core.dependencies.RBACRepository.get_user_permissions') as mock_rbac:
                    mock_rbac.return_value = ["pharmacy:read"]

                    # 1. Invalid period
                    resp = await ac.get("/api/v1/reports/pharmacy/sales?period=invalid")
                    assert resp.status_code == 400

                    # 2. JSON format with items list
                    resp_all = await ac.get("/api/v1/reports/pharmacy/sales?period=all")
                    assert resp_all.status_code == 200
                    data_all = resp_all.json()
                    assert data_all["total_sales"] > 0
                    assert data_all["total_invoices"] >= 4
                    assert "items" in data_all
                    assert isinstance(data_all["items"], list)
                    assert len(data_all["items"]) >= 4

                    first_item = data_all["items"][0]
                    assert "id" in first_item
                    assert "invoice_number" in first_item
                    assert "invoice_date" in first_item
                    assert "patient_id" in first_item
                    assert "patient_name" in first_item
                    assert "payment_mode" in first_item
                    assert "subtotal" in first_item
                    assert "discount_amount" in first_item
                    assert "tax_amount" in first_item
                    assert "total_amount" in first_item
                    assert "paid_amount" in first_item
                    assert "status" in first_item

                    # 3. Pagination via Query parameters
                    resp_paged = await ac.get("/api/v1/reports/pharmacy/sales?period=all&limit=2&offset=0")
                    assert resp_paged.status_code == 200
                    data_paged = resp_paged.json()
                    assert len(data_paged["items"]) == 2
                    assert data_paged["total_invoices"] >= 4

                    # 4. CSV export includes items table
                    resp_csv = await ac.get("/api/v1/reports/pharmacy/sales?period=all&format=csv")
                    assert resp_csv.status_code == 200
                    assert "text/csv" in resp_csv.headers.get("content-type", "")
                    csv_text = resp_csv.text
                    assert "SUMMARY" in csv_text
                    assert "total_sales" in csv_text
                    assert "invoice_number" in csv_text
                    assert f"INV_TDY_{uid}" in csv_text

                    # 5. PDF export with layout and content inspection
                    resp_pdf = await ac.get("/api/v1/reports/pharmacy/sales?period=all&format=pdf")
                    assert resp_pdf.status_code == 200
                    assert "application/pdf" in resp_pdf.headers.get("content-type", "")
                    assert resp_pdf.content.startswith(b"%PDF")

                    # Inspect PDF text and structure
                    pdf_reader = pypdf.PdfReader(io.BytesIO(resp_pdf.content))
                    assert len(pdf_reader.pages) >= 1
                    first_page_text = pdf_reader.pages[0].extract_text()

                    # Concise human-readable column headers
                    assert "Invoice No." in first_page_text
                    assert "Date" in first_page_text
                    assert "Patient" in first_page_text
                    assert "Payment" in first_page_text or "Payment Mode" in first_page_text
                    assert "Subtotal" in first_page_text
                    assert "Discount" in first_page_text
                    assert "Tax" in first_page_text
                    assert "Total Sales" in first_page_text
                    assert "Paid" in first_page_text
                    assert "Status" in first_page_text
                    assert "Total (" in first_page_text

                    # Raw internal IDs excluded from table columns
                    assert "patient_id" not in first_page_text

                    # Summary metrics with human-readable keys and 2 decimals
                    assert "Total Sales:" in first_page_text
                    assert "Total Invoices:" in first_page_text
                    assert "Average Invoice Value:" in first_page_text

                    assert f"INV_TDY_{uid}" in first_page_text
                    assert "Ramesh Sharma" in first_page_text
                    assert "200.00" in first_page_text
                    assert "180.00" in first_page_text
                    assert "30.00" in first_page_text
                    assert "Completed" in first_page_text

            app.dependency_overrides.clear()

        # Clean up created test records
        for obj in [hist_inv, today_inv, month_inv, year_inv, cancelled_inv, deleted_inv, other_hosp_inv, patient, hosp1, hosp2]:
            try:
                await session.delete(obj)
            except Exception:
                pass
        await session.commit()


@pytest.mark.asyncio
async def test_pharmacy_sales_pdf_multipage_and_layout():
    """Verify landscape orientation, column widths, two-decimal currencies, and header repetition across pages."""
    items = []
    for i in range(1, 45):
        items.append(
            PharmacySalesItemResponse(
                id=i,
                invoice_number=f"INV-2026-{i:05d}",
                invoice_date=datetime(2026, 10, 26, 14, 30, 0),
                patient_id=i,
                patient_name=f"Patient With Long Name Number {i}",
                payment_mode="Cash" if i % 2 == 0 else "UPI",
                subtotal=100.0 * i,
                discount_amount=5.0 * i,
                tax_amount=10.0 * i,
                total_amount=105.0 * i,
                paid_amount=105.0 * i,
                status="completed"
            )
        )

    resp = PharmacySalesResponse(
        total_sales=sum(item.total_amount for item in items),
        total_invoices=len(items),
        average_invoice_value=sum(item.total_amount for item in items) / len(items),
        items=items
    )
    payload = ReportService.build_export_payload("Pharmacy Sales", resp)

    pdf_buffer = ReportExportService.export_pdf(payload)
    reader = pypdf.PdfReader(pdf_buffer)

    # 1. Multi-page document
    assert len(reader.pages) >= 2

    # 2. Landscape orientation: width (792) > height (612)
    page1 = reader.pages[0]
    box = page1.mediabox
    width = float(box.width)
    height = float(box.height)
    assert width > height
    assert width == 792.0
    assert height == 612.0

    # 3. Repeating header across pages
    for page_idx, page in enumerate(reader.pages):
        page_text = page.extract_text()
        assert "Invoice No." in page_text, f"Page {page_idx + 1} is missing repeated header 'Invoice No.'"
        assert "Patient" in page_text, f"Page {page_idx + 1} is missing repeated header 'Patient'"
        assert "Total" in page_text, f"Page {page_idx + 1} is missing repeated header 'Total'"

    # 4. Currency formatting to 2 decimal places in PDF
    first_page_text = reader.pages[0].extract_text()
    assert "105.00" in first_page_text
    assert "100.00" in first_page_text
    assert "Completed" in first_page_text

    # 5. Summary Bar appears on Page 1 above the table, and totals footer is on the last page
    first_page_text = reader.pages[0].extract_text()
    last_page_text = reader.pages[-1].extract_text()
    assert "Average Invoice Value:" in first_page_text
    assert f"Total Invoices: {len(items)}" in first_page_text
    assert "Total Sales:" in first_page_text
    assert "Average Invoice Value:" not in last_page_text
    assert f"Total ({len(items)} Invoices)" in last_page_text

    sum_bar_pos = first_page_text.find(f"Total Invoices: {len(items)}")
    header_pos = first_page_text.find("Invoice No.")
    assert sum_bar_pos != -1
    assert header_pos != -1
    assert sum_bar_pos < header_pos


@pytest.mark.asyncio
async def test_pharmacy_sales_pdf_hospital_logo_and_summary_metrics():
    """Verify hospital logo rendering, tenant isolation, and table summary metrics."""
    uid = uuid.uuid4().hex[:8]
    test_logo = os.path.abspath("app/static/logo.png")

    async with AsyncSessionLocal() as session:
        real_user = (await session.execute(select(User).limit(1))).scalar_one_or_none()
        real_user_id = real_user.id if real_user else 1

        hosp_with_logo = Hospital(
            name=f"Logo Hospital {uid}",
            email=f"logo_hosp_{uid}@test.com",
            logo_path=test_logo,
        )
        hosp_no_logo = Hospital(
            name=f"NoLogo Hospital {uid}",
            email=f"nologo_hosp_{uid}@test.com",
            logo_path=None,
        )
        session.add_all([hosp_with_logo, hosp_no_logo])
        await session.flush()

        inv1 = PharmacyInvoice(
            invoice_number=f"INV_LOGO_1_{uid}",
            hospital_id=hosp_with_logo.id,
            subtotal=200.0,
            discount_amount=20.0,
            tax_amount=10.0,
            total_amount=190.0,
            paid_amount=190.0,
            payment_mode="UPI",
            status="completed",
            is_deleted=False,
            created_at=utc_now(),
        )
        inv2 = PharmacyInvoice(
            invoice_number=f"INV_LOGO_2_{uid}",
            hospital_id=hosp_with_logo.id,
            subtotal=300.0,
            discount_amount=30.0,
            tax_amount=15.0,
            total_amount=285.0,
            paid_amount=285.0,
            payment_mode="Cash",
            status="completed",
            is_deleted=False,
            created_at=utc_now(),
        )
        session.add_all([inv1, inv2])
        await session.commit()

        hosp_logo_id = hosp_with_logo.id
        hosp_no_logo_id = hosp_no_logo.id

    class FakeUser:
        id = real_user_id
        role_id = 1
        hospital_id = hosp_logo_id
        is_active = True
        is_verified = True
        email = f"user_{uid}@test.com"

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
                # 1. Test export_format=pdf with hospital logo present
                res_logo = await client.get("/api/v1/reports/pharmacy/sales?export_format=pdf")
                assert res_logo.status_code == 200
                assert res_logo.headers.get("content-type") == "application/pdf"
                
                reader_logo = pypdf.PdfReader(io.BytesIO(res_logo.content))
                assert len(reader_logo.pages) >= 1
                page1 = reader_logo.pages[0]
                page1_text = page1.extract_text()
                
                # Check embedded logo image
                assert len(page1.images) >= 1, "Hospital logo image must be embedded in the PDF"
                assert f"Logo Hospital {uid}" in page1_text
                assert "Pharmacy Sales" in page1_text

                # Check duplicate summary section at top is removed
                assert "Summary:" not in page1_text

                # Check table columns
                assert "Invoice No." in page1_text
                assert "Total Sales" in page1_text

                # Check table footer row with column sums and invoice count
                assert "Total (2 Invoices)" in page1_text
                assert "500.00" in page1_text  # Subtotal sum: 200 + 300 = 500.00
                assert "50.00" in page1_text   # Discount sum: 20 + 30 = 50.00
                assert "25.00" in page1_text   # Tax sum: 10 + 15 = 25.00
                assert "475.00" in page1_text  # Total sales sum: 190 + 285 = 475.00
                assert "237.50" in page1_text  # Average invoice value: 475 / 2 = 237.50
                assert "Total Invoices: 2" in page1_text
                assert "Total Sales: 475.00" in page1_text
                assert "Average Invoice Value: 237.50" in page1_text

                # Verify Summary Bar appears above main table and not below the table
                sum_bar_pos = page1_text.find("Total Invoices: 2")
                header_pos = page1_text.find("Invoice No.")
                footer_pos = page1_text.find("Total (2 Invoices)")
                assert sum_bar_pos != -1
                assert header_pos != -1
                assert footer_pos != -1
                assert sum_bar_pos < header_pos < footer_pos
                assert page1_text.find("Total Invoices: 2", footer_pos) == -1

                # 2. Test graceful fallback when hospital has no logo & zero-invoice handling
                fake_user.hospital_id = hosp_no_logo_id
                res_no_logo = await client.get("/api/v1/reports/pharmacy/sales?export_format=pdf")
                assert res_no_logo.status_code == 200
                reader_no_logo = pypdf.PdfReader(io.BytesIO(res_no_logo.content))
                page_nl = reader_no_logo.pages[0]
                assert len(page_nl.images) == 0, "No logo image should be embedded when logo_path is None"
                nl_text = page_nl.extract_text()
                assert f"NoLogo Hospital {uid}" in nl_text
                assert "Total (0 Invoices)" in nl_text
                assert "Total Invoices: 0" in nl_text
                assert "Total Sales: 0.00" in nl_text
                assert "Average Invoice Value: 0.00" in nl_text

    finally:
        app.dependency_overrides.clear()
        async with AsyncSessionLocal() as session:
            for obj in [inv1, inv2, hosp_with_logo, hosp_no_logo]:
                try:
                    await session.delete(obj)
                except Exception:
                    pass
            await session.commit()


def test_pharmacy_sales_pdf_exact_13_invoices_footer_and_summary_bar():
    """Verify that a report with exactly 13 invoices renders Total (13 Invoices) and the 3-cell Summary Bar."""
    subtotals = [10.0, 0.0, 0.0, 50.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 455.0, 0.0, 0.0]
    discounts = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 22.75, 0.0, 0.0]
    taxes = [1.80, 0.0, 0.0, 9.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 77.81, 0.0, 0.0]
    totals = [11.80, 300.0, 500.0, 59.0, 300.0, 500.0, 300.0, 500.0, 300.0, 500.0, 510.06, 300.0, 500.0]
    paids = [11.80, 0.0, 500.0, 59.0, 0.0, 500.0, 0.0, 500.0, 0.0, 500.0, 510.06, 0.0, 500.0]

    items = []
    for i in range(13):
        items.append(
            PharmacySalesItemResponse(
                id=i + 1,
                invoice_number=f"INV_TEST_{i+1:02d}",
                invoice_date=datetime(2026, 9, 9, 12, 0) + timedelta(minutes=i),
                patient_name=f"Patient {i+1}",
                payment_mode="Cash" if i % 2 == 0 else "UPI",
                subtotal=subtotals[i],
                discount_amount=discounts[i],
                tax_amount=taxes[i],
                total_amount=totals[i],
                total_sales=totals[i],
                paid_amount=paids[i],
                status="paid" if paids[i] > 0 else "Pending"
            )
        )

    total_sales_sum = round(sum(totals), 2)
    avg_inv_val = round(total_sales_sum / 13, 2)
    resp = PharmacySalesResponse(
        total_sales=total_sales_sum,
        total_invoices=13,
        average_invoice_value=avg_inv_val,
        items=items
    )

    test_logo = os.path.abspath("app/static/logo.png") if os.path.exists("app/static/logo.png") else None
    payload = ReportService.build_export_payload(
        "Pharmacy Sales",
        resp,
        hospital_name="NexaCare Default Hospital",
        hospital_logo=test_logo
    )

    pdf_buf = ReportExportService.export_pdf(payload)
    reader = pypdf.PdfReader(pdf_buf)

    # 1. Fits cleanly on 1 page without trailing blank page
    assert len(reader.pages) == 1
    page1 = reader.pages[0]
    txt = page1.extract_text()
    assert "Summary:" not in txt

    # 2. Table footer row verification
    assert "Total (13 Invoices)" in txt
    assert f"{sum(subtotals):.2f}" in txt
    assert f"{sum(discounts):.2f}" in txt
    assert f"{sum(taxes):.2f}" in txt
    assert f"{total_sales_sum:.2f}" in txt
    assert f"{sum(paids):.2f}" in txt

    # 3. Dedicated 3-cell Summary Bar verification
    assert "Total Invoices: 13" in txt
    assert f"Total Sales: {total_sales_sum:.2f}" in txt
    assert f"Average Invoice Value: {avg_inv_val:.2f}" in txt

    # 4. Verify Summary Bar appears above main table and not below it
    sum_bar_pos = txt.find("Total Invoices: 13")
    header_pos = txt.find("Invoice No.")
    footer_pos = txt.find("Total (13 Invoices)")
    assert sum_bar_pos != -1
    assert header_pos != -1
    assert footer_pos != -1
    assert sum_bar_pos < header_pos < footer_pos
    assert txt.find("Total Invoices: 13", footer_pos) == -1

