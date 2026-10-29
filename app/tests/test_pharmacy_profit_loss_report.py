import io
import uuid
import pypdf
import pytest
from datetime import datetime, date, timedelta
from httpx import AsyncClient, ASGITransport

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.hospital_model import Hospital
from app.models.pharmacy_model import PharmacyInvoice, Purchase, Medicine, Supplier
from app.models.user_model import User
from app.repositories.report_repository import ReportRepository
from app.services.report_service import ReportService
from app.services.report_export_service import ReportExportService
from app.schemas.report_schema import PharmacyProfitLossResponse
from app.core.dependencies import get_current_active_user, get_current_user


@pytest.mark.asyncio
async def test_pharmacy_profit_loss_repository_and_calculations():
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as session:
        # Create test hospital
        hosp1 = Hospital(name=f"Hosp PL 1 {uid}", email=f"hosp_pl1_{uid}@test.com")
        session.add(hosp1)
        await session.flush()

        today = date.today()
        start_date = today - timedelta(days=5)
        end_date = today + timedelta(days=5)

        # Run get_pharmacy_profit_loss for Hospital 1
        repo = ReportRepository(session)
        result = await repo.get_pharmacy_profit_loss(start_date=start_date, end_date=end_date, hospital_id=hosp1.id)

        # Verify default return structure
        assert "total_sales" in result
        assert "total_cost" in result
        assert "gross_profit" in result
        assert "invoice_count" in result
        assert "medicine_count" in result


@pytest.mark.asyncio
async def test_pharmacy_profit_loss_pdf_export_and_layout():
    data = PharmacyProfitLossResponse(
        total_sales=12500.50,
        total_cost=7500.00,
        gross_profit=5000.50,
        invoice_count=42,
        medicine_count=85,
    )

    filters = {"Period": "Monthly", "Date Range": "2026-10-01 to 2026-10-31"}
    payload = ReportService.build_export_payload(
        "Pharmacy Profit & Loss Report",
        data,
        filters=filters,
        main_table_title="Pharmacy Profit & Loss Report",
        hospital_name="City Central Hospital",
    )

    # Generate PDF stream
    pdf_stream = ReportExportService.export_pdf(payload)
    pdf_bytes = pdf_stream.getvalue()
    assert len(pdf_bytes) > 0

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    full_text = "".join(page.extract_text() for page in reader.pages)

    # 1. Report title and hospital branding
    assert "Pharmacy Profit & Loss Report" in full_text
    assert "City Central Hospital" in full_text

    # 2. Applied filters
    assert "Applied Filters" in full_text
    assert "2026-10-01 to 2026-10-31" in full_text

    # 3. Currency formatted with true INR symbol (₹), no fallback box (■)
    assert "₹" in full_text
    assert "■" not in full_text
    assert "₹12,500.50" in full_text
    assert "₹7,500.00" in full_text
    assert "₹5,000.50" in full_text

    # 4. Summary bar metrics with accurate, unexaggerated labels
    assert "Total Sales" in full_text
    assert "Procurement Purchases" in full_text
    assert "Net Flow (Sales - Purchases)" in full_text
    assert "Total Invoices" in full_text
    assert "42" in full_text
    assert "Active Medicines" in full_text
    assert "85" in full_text
    assert "Gross Margin" in full_text
    assert "Gross Margin: N/A" in full_text

    # 5. Table headers with INR symbol and transparent financial labels
    assert "Total Sales (₹)" in full_text
    assert "Procurement Purchases (₹)" in full_text
    assert "Net Flow (Sales - Purchases)" in full_text

    # 6. Explanatory footnote regarding COGS limitation
    assert "COGS" in full_text or "Cost of Goods Sold" in full_text
    assert "medicines sold during this period do not have tracked acquisition costs" in full_text
    assert "not tracked in the current database" not in full_text

    # 7. Verify that generic "Main Data" heading is NOT present
    assert "Main Data" not in full_text

    # 8. Test negative net flow formatting (procurement purchases > sales)
    loss_data = PharmacyProfitLossResponse(
        total_sales=100.00,
        total_cost=500.00,
        gross_profit=-400.00,
        invoice_count=2,
        medicine_count=10,
    )
    loss_payload = ReportService.build_export_payload(
        "Pharmacy Profit & Loss Report",
        loss_data,
        filters={"Period": "Monthly"},
        main_table_title="Pharmacy Profit & Loss Report",
    )
    loss_pdf = ReportExportService.export_pdf(loss_payload)
    loss_reader = pypdf.PdfReader(io.BytesIO(loss_pdf.getvalue()))
    loss_text = "".join(p.extract_text() for p in loss_reader.pages)
    assert "-₹400.00" in loss_text
    assert "■" not in loss_text

    # 9. Test zero sales handling (no ZeroDivisionError)
    zero_sales_data = PharmacyProfitLossResponse(
        total_sales=0.0,
        total_cost=250.0,
        gross_profit=-250.0,
        invoice_count=0,
        medicine_count=0,
    )
    zero_payload = ReportService.build_export_payload(
        "Pharmacy Profit & Loss Report",
        zero_sales_data,
        filters={"Period": "Daily"},
        main_table_title="Pharmacy Profit & Loss Report",
    )
    zero_pdf = ReportExportService.export_pdf(zero_payload)
    zero_reader = pypdf.PdfReader(io.BytesIO(zero_pdf.getvalue()))
    zero_text = "".join(p.extract_text() for p in zero_reader.pages)
    assert "Gross Margin: N/A" in zero_text
    assert "■" not in zero_text


@pytest.mark.asyncio
async def test_pharmacy_profit_loss_endpoint_api():
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as session:
        hosp = Hospital(name=f"Hosp API {uid}", email=f"hosp_api_{uid}@test.com")
        session.add(hosp)
        await session.commit()
        await session.refresh(hosp)
        hosp_id = hosp.id

    class FakeRole:
        name = "Hospital Admin"

    class FakeUser:
        id = 999
        hospital_id = hosp_id
        is_active = True
        is_verified = True
        email = f"admin_{uid}@test.com"
        role = FakeRole()

    fake_user = FakeUser()
    app.dependency_overrides[get_current_active_user] = lambda: fake_user
    app.dependency_overrides[get_current_user] = lambda: fake_user

    try:
        from unittest.mock import patch, AsyncMock
        with patch("app.core.dependencies.RBACRepository.get_user_permissions", new=AsyncMock(return_value=["pharmacy:read"])):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # 1. Test JSON response
                resp_json = await client.get("/api/v1/reports/pharmacy/profit-loss?period=monthly")
                assert resp_json.status_code == 200
                data = resp_json.json()
                assert "total_sales" in data
                assert "total_cost" in data
                assert "gross_profit" in data
                assert "invoice_count" in data
                assert "medicine_count" in data

                # 2. Test PDF download response via format=pdf
                resp_pdf = await client.get("/api/v1/reports/pharmacy/profit-loss?period=monthly&format=pdf")
                assert resp_pdf.status_code == 200
                assert resp_pdf.headers["content-type"] == "application/pdf"
                assert len(resp_pdf.content) > 0
                assert resp_pdf.content.startswith(b"%PDF")

                # 3. Test PDF download response via export_format=pdf alias
                resp_pdf_alias = await client.get("/api/v1/reports/pharmacy/profit-loss?period=monthly&export_format=pdf")
                assert resp_pdf_alias.status_code == 200
                assert resp_pdf_alias.headers["content-type"] == "application/pdf"
                assert len(resp_pdf_alias.content) > 0
                assert resp_pdf_alias.content.startswith(b"%PDF")

    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_pharmacy_moving_weighted_average_cost_and_opening_stock():
    from app.schemas.pharmacy_schema import MedicineCreate, PurchaseCreate, PurchaseItemCreate
    from app.services.pharmacy_service import PharmacyService

    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as session:
        hosp = Hospital(name=f"Hosp WAC {uid}", email=f"hosp_wac_{uid}@test.com")
        session.add(hosp)
        await session.commit()
        await session.refresh(hosp)

        user = User(
            user_code=f"U1_{uid}",
            full_name="Pharmacist Test",
            email=f"pharmacist_{uid}@test.com",
            hashed_password="fake",
            role_id=1,
            hospital_id=hosp.id,
            is_active=True,
            is_verified=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        supplier = Supplier(
            name=f"Supplier {uid}",
            contact_person="Distributor",
            phone="9876543210",
            email=f"supp_{uid}@test.com",
            hospital_id=hosp.id,
            is_active=True,
        )
        session.add(supplier)
        await session.commit()
        await session.refresh(supplier)

        service = PharmacyService(session)

        import random
        # 1. Opening stock with purchase_cost supplied
        med_create_costed = MedicineCreate(
            name=f"Med Costed {uid}",
            generic_name="Paracetamol",
            barcode=str(random.randint(1000000000000, 9999999999999)),
            batch_number=f"BAT-{uid[:5]}",
            category="Tablet",
            unit="strip",
            unit_price=100.0,
            purchase_cost=50.0,
            stock_quantity=10,
            reorder_level=5,
            expiry_date=date.today() + timedelta(days=365),
        )
        res_costed = await service.create_medicine(med_create_costed, user_id=user.id, current_user=user)
        assert res_costed.average_unit_cost == 50.0

        # Verify DB directly
        db_med_costed = await service.medicine_repo.get_by_id(res_costed.id)
        assert db_med_costed.average_unit_cost == 50.0
        assert db_med_costed.stock_quantity == 10

        # 2. Opening stock without purchase_cost supplied
        med_create_uncosted = MedicineCreate(
            name=f"Med Uncosted {uid}",
            generic_name="Amoxicillin",
            barcode=str(random.randint(1000000000000, 9999999999999)),
            batch_number=f"BAT2-{uid[:4]}",
            category="Capsule",
            unit="strip",
            unit_price=150.0,
            purchase_cost=None,
            stock_quantity=10,
            reorder_level=5,
            expiry_date=date.today() + timedelta(days=365),
        )
        res_uncosted = await service.create_medicine(med_create_uncosted, user_id=user.id, current_user=user)
        assert res_uncosted.average_unit_cost is None

        db_med_uncosted = await service.medicine_repo.get_by_id(res_uncosted.id)
        assert db_med_uncosted.average_unit_cost is None

        # 3. Incoming purchase order receipt for med_costed:
        # Old stock = 10, Old WAC = 50.0.
        # Received qty = 10, Supplier acquisition cost = 100.0.
        # Expected new WAC = ((10 * 50) + (10 * 100)) / (10 + 10) = 1500 / 20 = 75.0.
        po_create = PurchaseCreate(
            supplier_id=supplier.id,
            notes="Test PO for WAC",
            items=[
                PurchaseItemCreate(
                    medicine_id=res_costed.id,
                    quantity=10,
                    unit_price=100.0,
                    expiry_date=date.today() + timedelta(days=400),
                )
            ]
        )
        po = await service.create_purchase(po_create, user_id=user.id, current_user=user)
        await service.receive_purchase_order(po.id, current_user=user)

        # Refresh medicine and verify WAC and updated stock
        await session.refresh(db_med_costed)
        assert db_med_costed.stock_quantity == 20
        assert db_med_costed.average_unit_cost == 75.0

        # 4. Incoming purchase order receipt for med_uncosted (old cost was None):
        # Received qty = 10 @ 120.0.
        # Expected new WAC = 120.0.
        po_uncosted = PurchaseCreate(
            supplier_id=supplier.id,
            notes="Test PO for uncosted med",
            items=[
                PurchaseItemCreate(
                    medicine_id=res_uncosted.id,
                    quantity=10,
                    unit_price=120.0,
                    expiry_date=date.today() + timedelta(days=400),
                )
            ]
        )
        po2 = await service.create_purchase(po_uncosted, user_id=user.id, current_user=user)
        await service.receive_purchase_order(po2.id, current_user=user)

        await session.refresh(db_med_uncosted)
        assert db_med_uncosted.stock_quantity == 20
        assert db_med_uncosted.average_unit_cost == 120.0


@pytest.mark.asyncio
async def test_pharmacy_invoice_cogs_snapshot_and_returns():
    from app.schemas.pharmacy_schema import MedicineCreate, PharmacyInvoiceCreate, PharmacyInvoiceItemCreate, PharmacyReturnCreate, PharmacyReturnItemRequest
    from app.services.pharmacy_service import PharmacyService

    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as session:
        hosp = Hospital(name=f"Hosp COGS {uid}", email=f"hosp_cogs_{uid}@test.com")
        session.add(hosp)
        await session.commit()
        await session.refresh(hosp)

        user = User(
            user_code=f"U2_{uid}",
            full_name="Cashier Test",
            email=f"cashier_{uid}@test.com",
            hashed_password="fake",
            role_id=1,
            hospital_id=hosp.id,
            is_active=True,
            is_verified=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        service = PharmacyService(session)

        import random
        # Create medicine with initial WAC = 75.0, selling price = 150.0, stock = 20
        med_create = MedicineCreate(
            name=f"Med Sales {uid}",
            generic_name="Cetirizine",
            barcode=str(random.randint(1000000000000, 9999999999999)),
            batch_number=f"BAT3-{uid[:4]}",
            category="Tablet",
            unit="strip",
            unit_price=150.0,
            purchase_cost=75.0,
            stock_quantity=20,
            reorder_level=5,
            expiry_date=date.today() + timedelta(days=365),
        )
        med = await service.create_medicine(med_create, user_id=user.id, current_user=user)

        # Create Walk-in Invoice for 4 units:
        # Sales = 4 * 150 = 600.0
        # Expected COGS snapshot = 4 * 75 = 300.0
        inv_create = PharmacyInvoiceCreate(
            patient_id=None,
            prescription_id=None,
            items=[
                PharmacyInvoiceItemCreate(
                    medicine_id=med.id,
                    quantity=4,
                    unit_price=150.0,
                )
            ],
            payment_status="paid",
            payment_mode="Cash",
        )
        inv = await service.create_invoice(inv_create, user_id=user.id, current_user=user)
        assert len(inv.items) == 1
        inv_item = inv.items[0]
        assert inv_item.unit_cost == 75.0
        assert inv_item.line_cost == 300.0

        # Process a partial customer return: 1 unit returned
        ret_create = PharmacyReturnCreate(
            items=[
                PharmacyReturnItemRequest(
                    invoice_item_id=inv_item.id,
                    medicine_id=med.id,
                    quantity=1,
                    reason="Defective box",
                )
            ],
            reason="Customer partial return",
            payment_mode="Cash",
        )
        ret_res = await service.process_return(inv.id, ret_create, user_id=user.id, current_user=user)
        assert len(ret_res.items) == 1
        assert ret_res.items[0].unit_cost == 75.0
        assert ret_res.items[0].refund_amount == 150.0

        # Query profit & loss report:
        # Net sold quantity = 4 - 1 = 3 units
        # Costed Sales = 3 * 150.0 = 450.0
        # Total Sales = 600.0 (gross invoices amount)
        # COGS = 3 * 75.0 = 225.0
        # Gross Profit = Costed Sales - COGS = 450.0 - 225.0 = 225.0
        # Gross Margin % = (225.0 / 450.0) * 100 = 50.0%
        repo = ReportRepository(session)
        today = date.today()
        stats = await repo.get_pharmacy_profit_loss(
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
            hospital_id=hosp.id,
        )
        assert stats["costed_sales"] == 450.0
        assert stats["cogs"] == 225.0
        assert stats["gross_profit"] == 225.0
        assert stats["gross_margin_percentage"] == 50.0


@pytest.mark.asyncio
async def test_pharmacy_profit_loss_dual_bucket_legacy_and_zero_sales():
    from app.schemas.pharmacy_schema import MedicineCreate, PharmacyInvoiceCreate, PharmacyInvoiceItemCreate
    from app.services.pharmacy_service import PharmacyService

    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as session:
        hosp = Hospital(name=f"Hosp Dual {uid}", email=f"hosp_dual_{uid}@test.com")
        session.add(hosp)
        await session.commit()
        await session.refresh(hosp)

        user = User(
            user_code=f"U3_{uid}",
            full_name="Mgr Test",
            email=f"mgr_{uid}@test.com",
            hashed_password="fake",
            role_id=1,
            hospital_id=hosp.id,
            is_active=True,
            is_verified=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        service = PharmacyService(session)

        import random
        # 1. Costed medicine: WAC = 40.0, price = 100.0
        med1 = await service.create_medicine(
            MedicineCreate(
                name=f"Med Costed {uid}",
                generic_name="Aspirin",
                barcode=str(random.randint(1000000000000, 9999999999999)),
                batch_number=f"BAT4-{uid[:4]}",
                category="Tablet",
                unit="strip",
                unit_price=100.0,
                purchase_cost=40.0,
                stock_quantity=50,
                reorder_level=5,
                expiry_date=date.today() + timedelta(days=365),
            ),
            user_id=user.id,
            current_user=user,
        )

        # 2. Uncosted legacy medicine: WAC = None, price = 80.0
        med2 = await service.create_medicine(
            MedicineCreate(
                name=f"Med Legacy {uid}",
                generic_name="Vitamin C",
                barcode=str(random.randint(1000000000000, 9999999999999)),
                batch_number=f"BAT5-{uid[:4]}",
                category="Tablet",
                unit="strip",
                unit_price=80.0,
                purchase_cost=None,
                stock_quantity=50,
                reorder_level=5,
                expiry_date=date.today() + timedelta(days=365),
            ),
            user_id=user.id,
            current_user=user,
        )

        # Create Invoice 1: 2 units of Med1 (Sales: 200.0, COGS: 80.0)
        await service.create_invoice(
            PharmacyInvoiceCreate(
                items=[PharmacyInvoiceItemCreate(medicine_id=med1.id, quantity=2, unit_price=100.0)],
                payment_status="paid",
                payment_mode="Cash",
            ),
            user_id=user.id,
            current_user=user,
        )

        # Create Invoice 2: 1 unit of Med2 (Sales: 80.0, COGS: None)
        await service.create_invoice(
            PharmacyInvoiceCreate(
                items=[PharmacyInvoiceItemCreate(medicine_id=med2.id, quantity=1, unit_price=80.0)],
                payment_status="paid",
                payment_mode="Cash",
            ),
            user_id=user.id,
            current_user=user,
        )

        repo = ReportRepository(session)
        today = date.today()
        report = await repo.get_pharmacy_profit_loss(
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
            hospital_id=hosp.id,
        )

        # Total Sales = 330.4 (280.0 subtotal + 18% GST)
        # Costed Sales = 200.0 (item revenue)
        # Uncosted Sales = 130.4 (total_sales - costed_sales)
        # COGS = 80.0
        # Gross Profit = 200.0 - 80.0 = 120.0
        # Gross Margin % = (120.0 / 200.0) * 100 = 60.0%
        assert round(report["total_sales"], 2) == 330.4
        assert report["costed_sales"] == 200.0
        assert round(report["uncosted_sales"], 2) == 130.4
        assert report["cogs"] == 80.0
        assert report["gross_profit"] == 120.0
        assert report["gross_margin_percentage"] == 60.0

        # Test period with ZERO sales (future period)
        future_start = today + timedelta(days=30)
        future_end = today + timedelta(days=40)
        zero_report = await repo.get_pharmacy_profit_loss(
            start_date=future_start,
            end_date=future_end,
            hospital_id=hosp.id,
        )
        assert zero_report["total_sales"] == 0.0
        assert zero_report["costed_sales"] == 0.0
        assert zero_report["uncosted_sales"] == 0.0
        assert zero_report["cogs"] == 0.0
        assert zero_report["gross_profit"] == 0.0
        assert zero_report["gross_margin_percentage"] is None


@pytest.mark.asyncio
async def test_pharmacy_profit_loss_pdf_with_verified_cogs():
    data = PharmacyProfitLossResponse(
        total_sales=10000.00,
        total_cost=6000.00,
        procurement_purchases=6000.00,
        costed_sales=8000.00,
        uncosted_sales=2000.00,
        cogs=4800.00,
        gross_profit=3200.00,
        gross_margin_percentage=40.0,
        invoice_count=15,
        medicine_count=30,
    )

    filters = {"Period": "Monthly", "Date Range": "2026-10-01 to 2026-10-31"}
    payload = ReportService.build_export_payload(
        "Pharmacy Profit & Loss Report",
        data,
        filters=filters,
        main_table_title="Pharmacy Profit & Loss Report",
        hospital_name="Apollo Care",
    )

    pdf_stream = ReportExportService.export_pdf(payload)
    pdf_bytes = pdf_stream.getvalue()
    assert len(pdf_bytes) > 0

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    full_text = "".join(page.extract_text() for page in reader.pages)

    # Verified metrics are in the PDF text
    assert "Pharmacy Profit & Loss Report" in full_text
    assert "Apollo Care" in full_text
    assert "₹10,000.00" in full_text
    assert "₹4,800.00" in full_text
    assert "₹3,200.00" in full_text
    assert "40.0%" in full_text
    assert "₹2,000.00" in full_text
    assert "COGS" in full_text
    assert "Gross Profit" in full_text
    assert "Gross Margin" in full_text
    assert "Uncosted Sales" in full_text
    assert "Moving Weighted Average Cost" in full_text
    assert "₹4,000.00" in full_text  # Net Flow (Sales - Purchases)
    assert "■" not in full_text


@pytest.mark.asyncio
async def test_pharmacy_profit_loss_pdf_legacy_uncosted_net_flow_consistency_and_note():
    """
    Regression test for:
    1. Summary Net Flow (Sales - Purchases) = ₹11.80
    2. Table Net Flow (Sales - Purchases) = ₹11.80 (previously bugged at ₹0.00)
    3. Note reflects actual COGS tracking status without false 'not tracked in current database' claim.
    """
    data = PharmacyProfitLossResponse(
        total_sales=11.80,
        total_cost=0.00,
        procurement_purchases=0.00,
        net_flow=11.80,
        costed_sales=0.00,
        uncosted_sales=11.80,
        cogs=None,
        gross_profit=None,
        gross_margin_percentage=None,
        invoice_count=1,
        medicine_count=50,
    )

    payload = ReportService.build_export_payload(
        "Pharmacy Profit & Loss Report",
        data,
        filters={"Period": "Monthly"},
        main_table_title="Pharmacy Profit & Loss Report",
        hospital_name="City Central Hospital",
    )

    pdf_stream = ReportExportService.export_pdf(payload)
    pdf_bytes = pdf_stream.getvalue()
    assert len(pdf_bytes) > 0

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    full_text = "".join(page.extract_text() for page in reader.pages)

    # 1. Total Sales and Procurement Purchases
    assert "₹11.80" in full_text
    assert "₹0.00" in full_text

    # 2. Both summary and table consistently display Net Flow = ₹11.80
    assert full_text.count("₹11.80") >= 2

    # 3. Gross Margin is cleanly shown as N/A
    assert "Gross Margin: N/A" in full_text

    # 4. Note reflects accurate tracking status without claiming db lacks tracking
    assert "Accounting Gross Profit and Profit Margin are not displayed because the medicines sold during this period do not have tracked acquisition costs (Cost of Goods Sold / COGS)" in full_text
    assert "indicates Total Sales minus Total Procurement Purchases in the selected period" in full_text
    assert "not tracked in the current database" not in full_text


@pytest.mark.asyncio
async def test_pharmacy_invoice_zero_unit_price_http_422():
    """
    Regression test:
    Explicit unit_price <= 0 in PharmacyInvoiceItemCreate must fail Pydantic validation (HTTP 422).
    """
    import pydantic
    from app.schemas.pharmacy_schema import PharmacyInvoiceItemCreate

    # 1. Direct schema validation
    with pytest.raises(pydantic.ValidationError) as exc:
        PharmacyInvoiceItemCreate(medicine_id=1, quantity=1, unit_price=0.0)
    assert "greater than 0" in str(exc.value)

    with pytest.raises(pydantic.ValidationError) as exc:
        PharmacyInvoiceItemCreate(medicine_id=1, quantity=1, unit_price=-5.0)
    assert "greater than 0" in str(exc.value)

    # 2. Endpoint validation via AsyncClient
    uid = uuid.uuid4().hex[:8]
    class FakeRole:
        name = "Hospital Admin"

    class FakeUser:
        id = 999
        hospital_id = 1
        is_active = True
        is_verified = True
        email = f"admin_{uid}@test.com"
        role = FakeRole()

    app.dependency_overrides[get_current_active_user] = lambda: FakeUser()
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    try:
        from unittest.mock import patch, AsyncMock
        with patch("app.core.dependencies.RBACRepository.get_user_permissions", new=AsyncMock(return_value=["pharmacy:create"])):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/pharmacy/invoices",
                    json={
                        "payment_status": "paid",
                        "payment_mode": "Cash",
                        "items": [
                            {"medicine_id": 54, "quantity": 1, "unit_price": 0}
                        ]
                    }
                )
                assert resp.status_code == 422
                assert "greater than 0" in str(resp.json())
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_pharmacy_invoice_missing_selling_price_business_error_and_rollback():
    """
    Regression test:
    1. A medicine with unit_price = 0 or None raises BadRequestException on invoice creation.
    2. Failed invoice creation preserves transaction rollback: stock is unchanged and no invoice is left behind.
    """
    from app.core.exceptions import BadRequestException
    from app.services.pharmacy_service import PharmacyService
    from app.models.pharmacy_model import PharmacyInvoice
    from app.schemas.pharmacy_schema import PharmacyInvoiceCreate, PharmacyInvoiceItemCreate
    from sqlalchemy import select

    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        hosp = Hospital(name=f"Hosp Err {uid}", email=f"hosp_err_{uid}@test.com")
        session.add(hosp)
        await session.commit()
        await session.refresh(hosp)

        user = User(
            user_code=f"U_err_{uid}",
            full_name="Cashier Err",
            email=f"cashier_err_{uid}@test.com",
            hashed_password="fake",
            role_id=1,
            hospital_id=hosp.id,
            is_active=True,
            is_verified=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        hosp_id = hosp.id

        # Create medicine with unit_price = 0.0 directly in DB
        med = Medicine(
            name=f"Med Zero Price {uid}",
            sku=f"SKU_ZP_{uid}",
            category="Tablet",
            unit="box",
            unit_price=0.0,
            stock_quantity=50,
            hospital_id=hosp_id,
        )
        session.add(med)
        await session.commit()
        await session.refresh(med)
        med_id = med.id

        service = PharmacyService(session)
        inv_create = PharmacyInvoiceCreate(
            items=[
                PharmacyInvoiceItemCreate(medicine_id=med_id, quantity=5, unit_price=None)
            ],
            payment_status="paid",
            payment_mode="Cash",
        )

        # Invoice creation must fail with clear business error
        with pytest.raises(BadRequestException) as exc_info:
            await service.create_invoice(inv_create, user_id=user.id, current_user=user)

        assert "has no valid selling price configured" in str(exc_info.value.detail)

        # Verify transaction rollback: stock remains 50
        await session.rollback()
        fresh_med = (await session.execute(
            select(Medicine).where(Medicine.id == med_id)
        )).scalar_one()
        assert fresh_med.stock_quantity == 50

        # Verify no invoice exists for this hospital
        invoices = (await session.execute(
            select(PharmacyInvoice).where(PharmacyInvoice.hospital_id == hosp_id)
        )).scalars().all()
        assert len(invoices) == 0


@pytest.mark.asyncio
async def test_pharmacy_invoice_cogs_snapshot_and_null_preservation():
    """
    Regression test:
    - Known average_unit_cost is snapshotted into unit_cost and line_cost.
    - Missing average_unit_cost remains NULL in unit_cost and line_cost.
    """
    import random
    from app.services.pharmacy_service import PharmacyService
    from app.schemas.pharmacy_schema import MedicineCreate, PharmacyInvoiceCreate, PharmacyInvoiceItemCreate

    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        hosp = Hospital(name=f"Hosp Snap {uid}", email=f"hosp_snap_{uid}@test.com")
        session.add(hosp)
        await session.commit()
        await session.refresh(hosp)
        hosp_id = hosp.id

        user = User(
            user_code=f"U_snap_{uid}",
            full_name="Cashier Snap",
            email=f"cashier_snap_{uid}@test.com",
            hashed_password="fake",
            role_id=1,
            hospital_id=hosp_id,
            is_active=True,
            is_verified=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        service = PharmacyService(session)

        # Medicine 1: costed (purchase_cost / WAC = 35.0, selling = 70.0)
        med1_create = MedicineCreate(
            name=f"Med Costed {uid}",
            generic_name="Paracetamol",
            barcode=str(random.randint(1000000000000, 9999999999999)),
            batch_number=f"BAT_C_{uid[:4]}",
            category="Tablet",
            unit="box",
            unit_price=70.0,
            purchase_cost=35.0,
            stock_quantity=20,
            reorder_level=5,
            expiry_date=date.today() + timedelta(days=365),
        )
        med1 = await service.create_medicine(med1_create, user_id=user.id, current_user=user)

        # Medicine 2: uncosted (purchase_cost / WAC = None, selling = 50.0)
        med2_create = MedicineCreate(
            name=f"Med Uncosted {uid}",
            generic_name="Amoxicillin",
            barcode=str(random.randint(1000000000000, 9999999999999)),
            batch_number=f"BAT_U_{uid[:4]}",
            category="Tablet",
            unit="box",
            unit_price=50.0,
            purchase_cost=None,
            stock_quantity=20,
            reorder_level=5,
            expiry_date=date.today() + timedelta(days=365),
        )
        med2 = await service.create_medicine(med2_create, user_id=user.id, current_user=user)

        inv_create = PharmacyInvoiceCreate(
            items=[
                PharmacyInvoiceItemCreate(medicine_id=med1.id, quantity=2, unit_price=None),
                PharmacyInvoiceItemCreate(medicine_id=med2.id, quantity=3, unit_price=None),
            ],
            payment_status="paid",
            payment_mode="Cash",
        )
        inv = await service.create_invoice(inv_create, user_id=user.id, current_user=user)

        assert inv.subtotal == 2 * 70.0 + 3 * 50.0  # 140 + 150 = 290.0
        assert len(inv.items) == 2

        item1 = next(it for it in inv.items if it.medicine_id == med1.id)
        assert item1.unit_price == 70.0
        assert item1.line_total == 140.0
        assert item1.unit_cost == 35.0
        assert item1.line_cost == 70.0

        item2 = next(it for it in inv.items if it.medicine_id == med2.id)
        assert item2.unit_price == 50.0
        assert item2.line_total == 150.0
        assert item2.unit_cost is None
        assert item2.line_cost is None

        # Verify stock decrements
        fresh1 = await session.get(Medicine, med1.id)
        fresh2 = await session.get(Medicine, med2.id)
        assert fresh1.stock_quantity < 20
        assert fresh2.stock_quantity < 20
        assert fresh1.stock_quantity == 16
        assert fresh2.stock_quantity == 14


