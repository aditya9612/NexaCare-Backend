import io
import os
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, date

from app.utils.excel_security import sanitize_excel_cell, sanitize_excel_row, TrustedFormula
from app.utils.csv_security import sanitize_csv_cell, sanitize_csv_row, sanitize_csv_dict
from app.services.branding_resolver_service import (
    BrandingResolverService,
    HospitalBrandingContext,
    clear_branding_cache,
)
from app.utils.excel_branding import (
    apply_excel_hospital_header,
    style_excel_header_row,
    auto_fit_columns,
)
from app.utils.reportlab_branding import (
    create_reportlab_header_flowables,
    NumberedCanvas,
)
from app.core.exceptions import ForbiddenException
from app.schemas.appointment_schema import (
    TodayAppointmentsResponse,
    AppointmentListWithCountsResponse,
)
import openpyxl
from jinja2 import Environment, FileSystemLoader


# =========================================================================
# 1. EXCEL FORMULA INJECTION TESTS (CWE-1236)
# =========================================================================

class TestExcelFormulaInjection:
    def test_sanitize_excel_cell_dangerous_formula_prefixes(self):
        dangerous_payloads = [
            ("=1+1", "'=1+1"),
            ("=cmd|' /C calc'!A0", "'=cmd|' /C calc'!A0"),
            ("+SUM(A1:A10)", "'+SUM(A1:A10)"),
            ("-SUM(A1:A10)", "'-SUM(A1:A10)"),
            ("@SUM(A1:A10)", "'@SUM(A1:A10)"),
            ("\t=1+1", "'\t=1+1"),
            ("\r=1+1", "'\r=1+1"),
            ("  =2+2", "'=2+2"),
            (" |cmd", "'|cmd"),
            (" %0A=1+1", "'%0A=1+1"),
            (" ;cmd", "';cmd"),
        ]
        for payload, expected in dangerous_payloads:
            result = sanitize_excel_cell(payload)
            assert str(result).startswith("'"), f"Failed to prepend quote for payload: {payload}"

    def test_preserve_genuine_numeric_values(self):
        # Genuine negative numbers must remain numeric, NOT converted to string with quote
        assert sanitize_excel_cell(-150) == -150
        assert sanitize_excel_cell(-45.50) == -45.50
        assert sanitize_excel_cell(0) == 0
        assert sanitize_excel_cell(1234) == 1234
        assert sanitize_excel_cell(99.99) == 99.99
        assert sanitize_excel_cell(None) == ""

    def test_sanitize_excel_cell_safe_text(self):
        assert sanitize_excel_cell("John Doe") == "John Doe"
        assert sanitize_excel_cell("Paracetamol 500mg") == "Paracetamol 500mg"
        assert sanitize_excel_cell("INV-2026-001") == "INV-2026-001"

    def test_trusted_formula_bypass(self):
        formula = TrustedFormula("=SUM(A1:A10)")
        assert sanitize_excel_cell(formula) == "=SUM(A1:A10)"

    def test_sanitize_excel_row(self):
        row = [1, "=1+1", -25.5, "Safe Text", "@HYPERLINK('http://evil.com')"]
        sanitized = sanitize_excel_row(row)
        assert sanitized[0] == 1
        assert sanitized[1] == "'=1+1"
        assert sanitized[2] == -25.5
        assert sanitized[3] == "Safe Text"
        assert sanitized[4].startswith("'@")


# =========================================================================
# 2. CSV FORMULA INJECTION TESTS
# =========================================================================

class TestCSVFormulaInjection:
    def test_sanitize_csv_cell_dangerous_prefixes(self):
        assert sanitize_csv_cell("=1+1") == "'=1+1"
        assert sanitize_csv_cell("+cmd") == "'+cmd"
        assert sanitize_csv_cell("@SUM(1,2)") == "'@SUM(1,2)"
        assert sanitize_csv_cell("-cmd") == "'-cmd"
        assert sanitize_csv_cell("\t=test") == "'\t=test"
        assert sanitize_csv_cell("\r=test") == "'\r=test"

    def test_sanitize_csv_cell_numbers(self):
        assert sanitize_csv_cell(-150) == -150
        assert sanitize_csv_cell(-45.50) == -45.50
        assert sanitize_csv_cell("-150") == "-150"
        assert sanitize_csv_cell(0) == 0
        assert sanitize_csv_cell(100) == 100
        assert sanitize_csv_cell(None) == ""

    def test_sanitize_csv_row_and_dict(self):
        row = [10, "=calc", "Normal text"]
        assert sanitize_csv_row(row) == [10, "'=calc", "Normal text"]

        d = {"id": 1, "name": "=cmd", "amount": -50.0}
        sd = sanitize_csv_dict(d)
        assert sd["id"] == 1
        assert sd["name"] == "'=cmd"
        assert sd["amount"] == -50.0


# =========================================================================
# 3. MULTI-TENANT BRANDING RESOLVER SERVICE
# =========================================================================

@pytest.mark.asyncio
class TestBrandingResolverService:
    def setup_method(self):
        clear_branding_cache()

    async def test_super_admin_consolidated_resolution(self):
        mock_db = AsyncMock()
        super_admin = MagicMock()
        super_admin.role.name = "Super Admin"
        super_admin.hospital_id = None
        super_admin.active_hospital_id = None

        branding = await BrandingResolverService.resolve_branding(mock_db, current_user=super_admin)
        assert branding.hospital_id is None
        assert branding.hospital_name == "NexaCare Healthcare Network"
        assert "All Hospitals" in branding.hospital_address
        assert branding.is_consolidated is True
        assert branding.logo_data_uri.startswith("data:image/")

    async def test_super_admin_explicit_hospital_scoping(self):
        mock_db = AsyncMock()
        mock_hospital = MagicMock()
        mock_hospital.id = 5
        mock_hospital.name = "Apollo General Hospital"
        mock_hospital.address = "123 Marine Drive, Mumbai"
        mock_hospital.phone = "+91 9876543210"
        mock_hospital.email = "info@apollo.com"
        mock_hospital.website = "www.apollo.com"
        mock_hospital.logo = "app/static/images/logo.png"

        super_admin = MagicMock()
        super_admin.role.name = "Super Admin"
        super_admin.hospital_id = None
        super_admin.active_hospital_id = None

        with pytest.MonkeyPatch.context() as m:
            mock_repo = MagicMock()
            mock_repo.get_by_id = AsyncMock(return_value=mock_hospital)
            m.setattr("app.services.branding_resolver_service.HospitalRepository", lambda db: mock_repo)

            branding = await BrandingResolverService.resolve_branding(
                mock_db, current_user=super_admin, hospital_id=5
            )
            assert branding.hospital_id == 5
            assert branding.hospital_name == "Apollo General Hospital"
            assert branding.hospital_phone == "+91 9876543210"
            assert branding.is_consolidated is False

    async def test_hospital_admin_cross_tenant_rejection(self):
        mock_db = AsyncMock()
        hosp_admin = MagicMock()
        hosp_admin.role.name = "Hospital Admin"
        hosp_admin.hospital_id = 1

        # Attempting to access Hospital 2 data must raise ForbiddenException
        with pytest.raises(ForbiddenException):
            await BrandingResolverService.resolve_branding(
                mock_db, current_user=hosp_admin, hospital_id=2
            )

    async def test_hospital_admin_own_tenant_resolution(self):
        mock_db = AsyncMock()
        mock_hospital = MagicMock()
        mock_hospital.id = 1
        mock_hospital.name = "City Care Hospital"
        mock_hospital.address = "45 Ring Road, Delhi"
        mock_hospital.phone = "011-23456789"
        mock_hospital.email = "contact@citycare.com"
        mock_hospital.website = "www.citycare.com"
        mock_hospital.logo = None

        hosp_admin = MagicMock()
        hosp_admin.role.name = "Hospital Admin"
        hosp_admin.hospital_id = 1

        with pytest.MonkeyPatch.context() as m:
            mock_repo = MagicMock()
            mock_repo.get_by_id = AsyncMock(return_value=mock_hospital)
            m.setattr("app.services.branding_resolver_service.HospitalRepository", lambda db: mock_repo)

            branding = await BrandingResolverService.resolve_branding(
                mock_db, current_user=hosp_admin
            )
            assert branding.hospital_id == 1
            assert branding.hospital_name == "City Care Hospital"
            # Fallback logo should be used since mock_hospital.logo is None
            assert branding.logo_file_path is not None
            assert branding.logo_data_uri.startswith("data:image/")

    async def test_cache_invalidation(self):
        mock_db = AsyncMock()
        mock_hospital = MagicMock()
        mock_hospital.id = 3
        mock_hospital.name = "Original Name Hospital"
        mock_hospital.address = ""
        mock_hospital.phone = ""
        mock_hospital.email = ""
        mock_hospital.website = ""
        mock_hospital.logo = None

        user = MagicMock()
        user.role.name = "Hospital Admin"
        user.hospital_id = 3

        with pytest.MonkeyPatch.context() as m:
            mock_repo = MagicMock()
            mock_repo.get_by_id = AsyncMock(return_value=mock_hospital)
            m.setattr("app.services.branding_resolver_service.HospitalRepository", lambda db: mock_repo)

            b1 = await BrandingResolverService.resolve_branding(mock_db, current_user=user)
            assert b1.hospital_name == "Original Name Hospital"

            # Invalidate cache
            clear_branding_cache(3)

            # Change hospital name in mock
            mock_hospital.name = "Renamed Hospital"
            b2 = await BrandingResolverService.resolve_branding(mock_db, current_user=user)
            assert b2.hospital_name == "Renamed Hospital"


# =========================================================================
# 4. EXCEL BRANDING & LAYOUT TESTS
# =========================================================================

class TestExcelBranding:
    def test_apply_excel_hospital_header(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        branding = HospitalBrandingContext(
            hospital_id=1,
            hospital_name="Fortis Hospital",
            hospital_address="Sector 62, Noida, UP",
            hospital_phone="+91 120 4567890",
            hospital_email="support@fortis.com",
            hospital_website="www.fortis.com",
            logo_file_path="app/static/images/logo.png",
            logo_data_uri="",
            logo_base64="",
            is_consolidated=False,
        )

        headers = ["Col 1", "Col 2", "Col 3"]
        data_start_row = apply_excel_hospital_header(
            ws, branding, title="MONTHLY AUDIT REPORT", total_records=100
        )
        assert data_start_row == 5

        # Check Row 1: Hospital Name
        assert ws.cell(row=1, column=1).value == "Fortis Hospital"
        # Check Row 2: Contact
        assert "+91 120 4567890" in ws.cell(row=2, column=1).value
        # Check Row 3: Title & records
        assert "MONTHLY AUDIT REPORT" in ws.cell(row=3, column=1).value
        assert "Total Records: 100" in ws.cell(row=3, column=1).value

        # Apply header styling
        style_excel_header_row(ws, headers, header_row_idx=data_start_row)
        for col_idx, col_name in enumerate(headers, start=1):
            assert ws.cell(row=data_start_row, column=col_idx).value == col_name

        # Append sample row with formula injection
        sample_row = [sanitize_excel_cell("=1+1"), sanitize_excel_cell(-50.0), sanitize_excel_cell("Active")]
        ws.append(sample_row)

        auto_fit_columns(ws)

        stream = io.BytesIO()
        wb.save(stream)
        stream.seek(0)
        assert len(stream.getvalue()) > 1000


# =========================================================================
# 5. REPORTLAB BRANDING FLOWABLES & NUMBERED CANVAS TESTS
# =========================================================================

class TestReportLabBranding:
    def test_create_reportlab_header_flowables(self):
        branding = HospitalBrandingContext(
            hospital_id=2,
            hospital_name="Max Healthcare",
            hospital_address="Saket, New Delhi",
            hospital_phone="011-456789",
            hospital_email="info@max.com",
            hospital_website="www.maxhealthcare.in",
            logo_file_path="app/static/images/logo.png",
            logo_data_uri="",
            logo_base64="",
            is_consolidated=False,
        )

        flowables = create_reportlab_header_flowables(
            branding, "Clinical Summary", meta_info="Doctor: Dr. Sharma"
        )
        assert len(flowables) >= 3

    def test_numbered_canvas_build(self):
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()

        elements = [
            Paragraph("Page 1 Content", styles["Normal"]),
            Spacer(1, 200),
            Paragraph("Still Page 1", styles["Normal"]),
        ]

        doc.build(
            elements,
            canvasmaker=lambda *args, **kwargs: NumberedCanvas(
                *args, branding_footer_text="Max Healthcare", **kwargs
            ),
        )
        pdf_bytes = buffer.getvalue()
        assert len(pdf_bytes) > 500
        assert pdf_bytes.startswith(b"%PDF")


# =========================================================================
# 6. APPOINTMENT DASHBOARD REGRESSION (NO_SHOW METRIC INTEGRITY)
# =========================================================================

class TestAppointmentDashboardRegression:
    def test_today_appointments_response_no_unintended_field(self):
        # Verify TodayAppointmentsResponse does NOT have an independent no_show field
        fields = TodayAppointmentsResponse.model_fields.keys()
        assert "no_show" not in fields, "Unintended 'no_show' field found in TodayAppointmentsResponse"
        assert "cancelled" in fields
        assert "completed" in fields
        assert "pending" in fields
        assert "confirmed" in fields

    def test_appointment_list_with_counts_no_unintended_field(self):
        # Verify AppointmentListWithCountsResponse does NOT have an independent no_show field
        fields = AppointmentListWithCountsResponse.model_fields.keys()
        assert "no_show" not in fields, "Unintended 'no_show' field found in AppointmentListWithCountsResponse"
        assert "cancelled" in fields


# =========================================================================
# 7. JINJA TEMPLATE RENDERING SUITE (ALL 14 EXPORT TEMPLATES)
# =========================================================================

class TestJinjaTemplateRendering:
    def setup_method(self):
        self.env = Environment(loader=FileSystemLoader("app/templates"))

    @pytest.mark.parametrize(
        "template_name,context",
        [
            (
                "billings_export_template.html",
                {
                    "billings": [
                        {
                            "id": 1,
                            "bill_number": "BILL-001",
                            "patient_name": "John Doe",
                            "subtotal": 1000.0,
                            "discount_percent": 0.0,
                            "discount_amount": 0.0,
                            "gst_rate": 18.0,
                            "gst_amount": 180.0,
                            "tax_amount": 180.0,
                            "total_amount": 1180.0,
                            "paid_amount": 1180.0,
                            "balance_amount": 0.0,
                            "status": "PAID",
                            "source": "clinical",
                            "due_date": "2026-11-15",
                            "notes": "Full payment received",
                            "appointment_id": 1,
                            "created_at": "2026-11-01 10:00:00",
                            "bill_items": [
                                {
                                    "id": 1,
                                    "description": "General Consultation",
                                    "quantity": 1,
                                    "unit_price": 1000.0,
                                    "gst_rate": 18.0,
                                    "gst_amount": 180.0,
                                    "line_total": 1180.0,
                                    "item_type": "service",
                                }
                            ],
                        }
                    ],
                    "hospital_name": "NexaCare Test Hospital",
                    "hospital_address": "Test Road",
                    "hospital_phone": "123456",
                    "hospital_email": "test@nexacare.com",
                    "logo_data_uri": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
                    "report_title": "Billings Report",
                    "generated_at": "2026-11-01 12:00:00",
                },
            ),
            (
                "doctors_export_template.html",
                {
                    "doctors": [
                        {
                            "doctor_code": "DOC-001",
                            "full_name": "Dr. Sarah Connor",
                            "gender": "Female",
                            "dob": "1980-01-01",
                            "phone": "555-1234",
                            "email": "sarah@hospital.com",
                            "specialization": "Cardiology",
                            "qualification": "MD",
                            "department_name": "Cardiology",
                            "status": "Available",
                            "created_at": "2026-11-01 10:00:00",
                        }
                    ],
                    "hospital_name": "NexaCare Test Hospital",
                    "hospital_address": "Test Road",
                    "hospital_phone": "123456",
                    "hospital_email": "test@nexacare.com",
                    "logo_data_uri": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
                    "report_title": "Doctors Report",
                    "generated_at": "2026-11-01 12:00:00",
                },
            ),
            (
                "expenses_export_template.html",
                {
                    "expenses": [
                        {
                            "id": 1,
                            "category_id": 1,
                            "vendor_id": 1,
                            "amount": "₹500.00",
                            "description": "Medical Supplies",
                            "expense_date": "2026-11-01",
                            "status": "Paid",
                            "category_name": "Supplies",
                            "vendor_name": "Acme Pharma",
                            "created_at": "2026-11-01 10:00:00",
                            "updated_at": "2026-11-01 10:00:00",
                            "source": "expense",
                        }
                    ],
                    "hospital_name": "NexaCare Test Hospital",
                    "hospital_address": "Test Road",
                    "hospital_phone": "123456",
                    "hospital_email": "test@nexacare.com",
                    "logo_data_uri": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
                    "report_title": "Expenses Report",
                    "generated_at": "2026-11-01 12:00:00",
                },
            ),
            (
                "inventory_items_export_template.html",
                {
                    "items": [
                        {
                            "id": 1,
                            "name": "Surgical Mask",
                            "sku": "MSK-001",
                            "barcode": "1234567890",
                            "category": "Consumables",
                            "quantity": 500,
                            "unit": "pcs",
                            "unit_cost": 2.50,
                            "reorder_level": 100,
                            "expiry_date": "2028-12-31",
                            "warehouse_name": "Main WH",
                            "vendor_name": "Acme",
                            "department_name": "General",
                            "description": "3-ply mask",
                            "is_active": "Yes",
                            "created_at": "2026-11-01 10:00:00",
                            "updated_at": "2026-11-01 10:00:00",
                        }
                    ],
                    "hospital_name": "NexaCare Test Hospital",
                    "hospital_address": "Test Road",
                    "hospital_phone": "123456",
                    "hospital_email": "test@nexacare.com",
                    "logo_data_uri": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
                    "report_title": "Inventory Items Report",
                    "generated_at": "2026-11-01 12:00:00",
                },
            ),
            (
                "lab_orders_export_template.html",
                {
                    "orders": [
                        {
                            "id": 1,
                            "order_number": "ORD-001",
                            "patient_name": "John Doe",
                            "doctor_name": "Dr. Sarah",
                            "appointment_number": "APT-001",
                            "department_id": 1,
                            "status": "Completed",
                            "priority": "Normal",
                            "notes": "Fasting",
                            "ordered_at": "2026-11-01 10:00:00",
                            "completed_at": "2026-11-01 11:00:00",
                            "lab_test_test_code": "CBC",
                            "lab_test_test_name": "Complete Blood Count",
                            "lab_test_category": "Hematology",
                            "lab_test_sample_type": "Blood",
                            "lab_test_price": 400.0,
                        }
                    ],
                    "hospital_name": "NexaCare Test Hospital",
                    "hospital_address": "Test Road",
                    "hospital_phone": "123456",
                    "hospital_email": "test@nexacare.com",
                    "logo_data_uri": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
                    "report_title": "Lab Orders Report",
                    "generated_at": "2026-11-01 12:00:00",
                },
            ),
            (
                "medicines_export_template.html",
                {
                    "medicines": [
                        {
                            "sr_no": 1,
                            "name": "Paracetamol 500mg",
                            "category": "Analgesic",
                            "batch_number": "B123",
                            "stock_quantity": 200,
                            "unit_price": 3.00,
                            "cost_price": "₹1.50",
                            "selling_price": "₹3.00",
                            "expiry_date": "2027-05-31",
                            "status": "Available",
                        }
                    ],
                    "hospital_name": "NexaCare Test Hospital",
                    "hospital_address": "Test Road",
                    "hospital_phone": "123456",
                    "hospital_email": "test@nexacare.com",
                    "logo_data_uri": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
                    "report_title": "Medicines Report",
                    "generated_at": "2026-11-01 12:00:00",
                },
            ),
            (
                "patients_export_template.html",
                {
                    "patients": [
                        {
                            "id": 1,
                            "patient_code": "PAT-001",
                            "first_name": "Jane",
                            "last_name": "Smith",
                            "gender": "Female",
                            "dob": "1992-04-15",
                            "phone": "9876543210",
                            "email": "jane@example.com",
                            "blood_group": "O+",
                            "created_at": "2026-11-01 10:00:00",
                        }
                    ],
                    "hospital_name": "NexaCare Test Hospital",
                    "hospital_address": "Test Road",
                    "hospital_phone": "123456",
                    "hospital_email": "test@nexacare.com",
                    "logo_data_uri": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
                    "report_title": "Patients Report",
                    "generated_at": "2026-11-01 12:00:00",
                },
            ),
            (
                "suppliers_export_template.html",
                {
                    "suppliers": [
                        {
                            "sr_no": 1,
                            "name": "Global Pharma Inc.",
                            "contact_person": "Robert Green",
                            "phone": "555-8888",
                            "email": "robert@globalpharma.com",
                            "address": "Pharma Park, Hyderabad",
                            "status": "Active",
                        }
                    ],
                    "hospital_name": "NexaCare Test Hospital",
                    "hospital_address": "Test Road",
                    "hospital_phone": "123456",
                    "hospital_email": "test@nexacare.com",
                    "logo_data_uri": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
                    "report_title": "Suppliers Report",
                    "generated_at": "2026-11-01 12:00:00",
                },
            ),
            (
                "transactions_export_template.html",
                {
                    "transactions": [
                        {
                            "id": 1,
                            "billing_id": 1,
                            "bill_number": "BILL-001",
                            "patient_name": "John Doe",
                            "amount": 500.0,
                            "payment_method": "UPI",
                            "transaction_ref": "TXN12345",
                            "payment_date": "2026-11-01 10:00:00",
                            "status": "Success",
                            "is_refund": False,
                            "refund_reason": "",
                            "created_at": "2026-11-01 10:00:00",
                            "updated_at": "2026-11-01 10:00:00",
                        }
                    ],
                    "hospital_name": "NexaCare Test Hospital",
                    "hospital_address": "Test Road",
                    "hospital_phone": "123456",
                    "hospital_email": "test@nexacare.com",
                    "logo_data_uri": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
                    "report_title": "Transactions Report",
                    "generated_at": "2026-11-01 12:00:00",
                },
            ),
            (
                "vendors_export_template.html",
                {
                    "vendors": [
                        {
                            "id": 1,
                            "name": "MediSupply Co.",
                            "vendor_type": "Medical",
                            "contact_person": "Alice Smith",
                            "phone": "555-4321",
                            "email": "alice@medisupply.com",
                            "address": "Industrial Area, Pune",
                            "gst_number": "27AAAAA0000A1Z5",
                            "service_type": "Equipment",
                            "is_active": True,
                            "created_at": "2026-11-01 10:00:00",
                            "updated_at": "2026-11-01 10:00:00",
                        }
                    ],
                    "hospital_name": "NexaCare Test Hospital",
                    "hospital_address": "Test Road",
                    "hospital_phone": "123456",
                    "hospital_email": "test@nexacare.com",
                    "logo_data_uri": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
                    "report_title": "Vendors Report",
                    "generated_at": "2026-11-01 12:00:00",
                },
            ),
            (
                "appointments_export_template.html",
                {
                    "appointments": [
                        {
                            "appointment_number": "APT-001",
                            "appointment_date": "2026-11-01",
                            "appointment_time": "10:30",
                            "queue_token": "T-01",
                            "patient_name": "Jane Doe",
                            "patient_code": "PAT-001",
                            "patient_phone": "9999999999",
                            "doctor_name": "Dr. Sarah",
                            "department_name": "Cardiology",
                            "appointment_type": "OPD",
                            "booking_source": "online",
                            "appointment_status": "Confirmed",
                            "queue_status": "Waiting",
                            "admission_status": "None",
                            "admission_recommended": False,
                            "check_in_time": "10:25",
                            "check_out_time": "",
                        }
                    ],
                    "hospital_name": "NexaCare Test Hospital",
                    "hospital_address": "Test Road",
                    "hospital_phone": "123456",
                    "hospital_email": "test@nexacare.com",
                    "logo_data_uri": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
                    "report_title": "Appointments Report",
                    "generated_at": "2026-11-01 12:00:00",
                },
            ),
        ],
    )
    def test_templates_render_successfully(self, template_name, context):
        template = self.env.get_template(template_name)
        html = template.render(**context)
        assert len(html) > 100
        assert "NexaCare Test Hospital" in html
        assert "data:image/png;base64," in html


# =========================================================================
# 8. VENDOR SERVICE CRUD & EXPORT SUITE
# =========================================================================

from unittest.mock import patch
from app.services.vendor_service import VendorService
from app.schemas.vendor_schema import VendorCreate, VendorUpdate, VendorResponse
from app.core.exceptions import NotFoundException, BadRequestException, ConflictException


@pytest.mark.asyncio
class TestVendorServiceCRUDAndExport:
    def setup_method(self):
        self.mock_db = AsyncMock()
        self.service = VendorService(self.mock_db)

    async def test_vendor_list_vendors(self):
        mock_vendor = MagicMock()
        mock_vendor.id = 1
        mock_vendor.name = "Health Supplies Ltd"
        mock_vendor.vendor_type = "inventory"
        mock_vendor.contact_person = "Alice"
        mock_vendor.phone = "1234567890"
        mock_vendor.email = "alice@health.com"
        mock_vendor.address = "123 Care St"
        mock_vendor.gst_number = "27AAAAA0000A1Z5"
        mock_vendor.service_type = "Medical Consumables"
        mock_vendor.is_active = True
        mock_vendor.created_at = datetime(2026, 1, 1, 10, 0, 0)
        mock_vendor.updated_at = datetime(2026, 1, 2, 10, 0, 0)

        self.service.vendor_repo.list_all = AsyncMock(return_value=[mock_vendor])
        self.service.vendor_repo.count_all = AsyncMock(return_value=1)

        result = await self.service.list_vendors(page=1, size=20, hospital_id=1)
        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].name == "Health Supplies Ltd"

    async def test_vendor_get_vendor_found_and_not_found(self):
        mock_vendor = MagicMock()
        mock_vendor.id = 10
        mock_vendor.name = "Pharma Global"
        mock_vendor.vendor_type = "expenses"
        mock_vendor.contact_person = "Bob"
        mock_vendor.phone = "9876543210"
        mock_vendor.email = "bob@pharma.com"
        mock_vendor.address = "456 Drug Way"
        mock_vendor.gst_number = "27BBBBB1111B1Z2"
        mock_vendor.service_type = "Logistics"
        mock_vendor.is_active = True
        mock_vendor.created_at = datetime(2026, 1, 1)
        mock_vendor.updated_at = datetime(2026, 1, 2)

        self.service.vendor_repo.get_by_id = AsyncMock(return_value=mock_vendor)
        res = await self.service.get_vendor(10, hospital_id=1)
        assert res.id == 10
        assert res.name == "Pharma Global"

        self.service.vendor_repo.get_by_id = AsyncMock(return_value=None)
        with pytest.raises(NotFoundException):
            await self.service.get_vendor(99, hospital_id=1)

    async def test_vendor_update_vendor(self):
        mock_vendor = MagicMock()
        mock_vendor.id = 5
        mock_vendor.name = "Old Vendor"
        mock_vendor.vendor_type = "inventory"
        mock_vendor.contact_person = "Charlie"
        mock_vendor.phone = "1111111111"
        mock_vendor.email = "c@old.com"
        mock_vendor.address = "Old Addr"
        mock_vendor.gst_number = "27CCCCC2222C1Z3"
        mock_vendor.service_type = "Supplies"
        mock_vendor.is_active = True
        mock_vendor.created_at = datetime(2026, 1, 1)
        mock_vendor.updated_at = datetime(2026, 1, 2)

        self.service.vendor_repo.get_by_id = AsyncMock(return_value=mock_vendor)
        self.service.vendor_repo.get_by_name = AsyncMock(return_value=None)
        self.service.vendor_repo.update = AsyncMock(return_value=mock_vendor)
        self.service.audit_repo.create = AsyncMock()

        update_data = VendorUpdate(name="New Vendor Name")
        res = await self.service.update_vendor(5, update_data, user_id=1, hospital_id=1)
        assert res.id == 5

    async def test_vendor_delete_vendor(self):
        mock_vendor = MagicMock()
        mock_vendor.id = 7
        self.service.vendor_repo.get_by_id = AsyncMock(return_value=mock_vendor)
        self.mock_db.scalar = AsyncMock(return_value=0)
        self.service.vendor_repo.soft_delete = AsyncMock()
        self.service.audit_repo.create = AsyncMock()

        await self.service.delete_vendor(7, user_id=1, hospital_id=1)
        self.service.vendor_repo.soft_delete.assert_called_once_with(mock_vendor)

    async def test_vendor_generate_bulk_template(self):
        stream = await self.service.generate_vendor_bulk_template(hospital_id=1)
        assert stream is not None
        wb = openpyxl.load_workbook(stream)
        assert "Vendors Bulk Import" in wb.sheetnames
        assert "Guidelines & Reference" in wb.sheetnames
        ws = wb["Vendors Bulk Import"]
        headers = [cell.value for cell in ws[1]]
        assert "name" in headers
        assert "vendor_type" in headers

    async def test_vendor_export_excel_with_branding_and_security(self):
        v1 = MagicMock()
        v1.id = 1
        v1.name = "=cmd|' /C calc'!A0"
        v1.vendor_type = "inventory"
        v1.contact_person = "Hacker"
        v1.phone = "123456"
        v1.email = "h@evil.com"
        v1.address = "Unknown"
        v1.gst_number = "27EVIL0000E1Z1"
        v1.service_type = "IT Services"
        v1.is_active = True
        v1.created_at = datetime(2026, 1, 1, 10, 0, 0)
        v1.updated_at = datetime(2026, 1, 2, 10, 0, 0)

        self.service.vendor_repo.get_all_active = AsyncMock(return_value=[v1])

        mock_branding = HospitalBrandingContext(
            hospital_id=1,
            hospital_name="NexaCare City Hospital",
            hospital_address="100 Metro Ave",
            hospital_phone="555-1234",
            hospital_email="city@nexacare.com",
            hospital_website="www.citycare.com",
            logo_path=None,
            is_platform_branding=False,
        )

        with patch("app.services.branding_resolver_service.BrandingResolverService.resolve_branding", AsyncMock(return_value=mock_branding)):
            stream, media_type = await self.service.export_vendors("excel", hospital_id=1)
            assert media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            
            wb = openpyxl.load_workbook(stream)
            ws = wb.active
            assert ws.title == "Vendors Export"

            # Verify hospital branding banner
            assert ws.cell(row=1, column=1).value == "NexaCare City Hospital"

            # Table column headers on row 5
            headers = [ws.cell(row=5, column=col).value for col in range(1, 13)]
            assert "name" in headers
            assert "vendor_type" in headers

            # Check formula injection sanitization on row 6
            name_cell_val = ws.cell(row=6, column=2).value
            assert str(name_cell_val).startswith("'="), f"Formula injection not neutralized: {name_cell_val}"

    async def test_vendor_export_pdf_with_branding(self):
        v1 = MagicMock()
        v1.id = 1
        v1.name = "Standard Medical Supplies"
        v1.vendor_type = "inventory"
        v1.contact_person = "John"
        v1.phone = "123456"
        v1.email = "j@med.com"
        v1.address = "123 Main St"
        v1.gst_number = "27MED1111M1Z1"
        v1.service_type = "Consumables"
        v1.is_active = True
        v1.created_at = datetime(2026, 1, 1, 10, 0, 0)
        v1.updated_at = datetime(2026, 1, 2, 10, 0, 0)

        self.service.vendor_repo.get_all_active = AsyncMock(return_value=[v1])

        mock_branding = HospitalBrandingContext(
            hospital_id=1,
            hospital_name="NexaCare City Hospital",
            hospital_address="100 Metro Ave",
            hospital_phone="555-1234",
            hospital_email="city@nexacare.com",
            hospital_website="www.citycare.com",
            logo_path=None,
            logo_data_uri="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
            is_platform_branding=False,
        )

        with patch("app.services.branding_resolver_service.BrandingResolverService.resolve_branding", AsyncMock(return_value=mock_branding)):
            with patch("app.utils.pdf_generator.html_to_pdf", return_value=b"%PDF-1.4 mock vendor pdf"):
                data, media_type = await self.service.export_vendors("pdf", hospital_id=1)
                assert media_type == "application/pdf"
                assert data.startswith(b"%PDF")

    async def test_vendor_export_invalid_format(self):
        with pytest.raises(BadRequestException):
            await self.service.export_vendors("unsupported_format", hospital_id=1)
# =========================================================================
# 9. DIRECT IMPACT HTTP API REGRESSION SUITE (25 Endpoints + Tenant Safety)
# =========================================================================

from httpx import AsyncClient, ASGITransport
import io
from app.main import app
from app.core.database import get_db
from app.core.dependencies import get_current_active_user, get_current_user
from app.core.constants import UserRole
from app.utils.helpers import utc_now
from app.schemas.lab_schema import LabReportResponse
from app.schemas.hospital_schema import HospitalResponse
from app.schemas.user_schema import UserResponse
from app.schemas.report_schema import (
    PharmacySalesResponse,
    PharmacyInventoryResponse,
    PharmacyExpiryResponse,
    PharmacyProfitLossResponse,
)


class MockRole:
    def __init__(self, name="Super Admin"):
        self.name = name


class MockSyntheticUser:
    def __init__(self, user_id=1, hospital_id=1, role_name="Super Admin", is_superuser=True):
        self.id = user_id
        self.hospital_id = hospital_id
        self.role = MockRole(role_name)
        self.role_name = role_name
        self.is_active = True
        self.is_superuser = is_superuser


@pytest.mark.asyncio
class TestDirectImpactAPIHTTPRegression:
    def setup_method(self):
        self.mock_db = AsyncMock()
        self.mock_db.add = MagicMock()
        self.mock_db.flush = AsyncMock()
        self.mock_db.commit = AsyncMock()
        self.mock_db.rollback = AsyncMock()

        self.super_user = MockSyntheticUser(user_id=1, hospital_id=1, role_name=UserRole.SUPER_ADMIN, is_superuser=True)
        self.tenant_user_hosp1 = MockSyntheticUser(user_id=2, hospital_id=1, role_name=UserRole.HOSPITAL_ADMIN, is_superuser=False)
        self.tenant_user_hosp2 = MockSyntheticUser(user_id=3, hospital_id=2, role_name=UserRole.HOSPITAL_ADMIN, is_superuser=False)

    async def _get_client(self, user):
        async def override_db():
            yield self.mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_active_user] = lambda: user
        app.dependency_overrides[get_current_user] = lambda: user

        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": "Bearer test-mock-token"})

    # 1. Patients Export HTTP Endpoint
    async def test_http_export_patients(self):
        client = await self._get_client(self.super_user)
        async with client:
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.services.patient_service.PatientService.export_patients", AsyncMock(return_value=(io.BytesIO(b"patient_excel"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))):
                    r = await client.get("/api/v1/patients/export?format=excel")
                    assert r.status_code == 200
                    assert r.content == b"patient_excel"

    # 2. Doctors Export HTTP Endpoint
    async def test_http_export_doctors(self):
        client = await self._get_client(self.super_user)
        async with client:
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.services.doctor_service.DoctorService.export_doctors", AsyncMock(return_value=(io.BytesIO(b"doctor_excel"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))):
                    r = await client.get("/api/v1/doctors/export?format=excel")
                    assert r.status_code == 200
                    assert r.content == b"doctor_excel"

    # 3. Appointments Export HTTP Endpoint
    async def test_http_export_appointments(self):
        client = await self._get_client(self.super_user)
        async with client:
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.services.appointment_service.AppointmentService.export_appointments", AsyncMock(return_value=(b"appt_excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))):
                    r = await client.get("/api/v1/appointments/export?format=excel")
                    assert r.status_code == 200
                    assert r.content == b"appt_excel"

    # 4. Appointment PDF Download HTTP Endpoint
    async def test_http_download_appointment_pdf(self):
        client = await self._get_client(self.super_user)
        async with client:
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.services.appointment_service.AppointmentService.download_appointment_pdf", AsyncMock(return_value=b"%PDF-1.4 appt")):
                    r = await client.get("/api/v1/appointments/101/download")
                    assert r.status_code == 200
                    assert r.headers["content-type"] == "application/pdf"
                    assert r.content.startswith(b"%PDF")

    # 5. Bed Allocation Export HTTP Endpoint
    async def test_http_export_bed_allocation(self):
        client = await self._get_client(self.super_user)
        async with client:
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.services.bed_allocation_service.BedAllocationService.export_bed_data_csv", AsyncMock(return_value=b"bed_csv")):
                    r = await client.get("/api/v1/bed-allocation/export?format=csv")
                    assert r.status_code == 200
                    assert r.content == b"bed_csv"

    # 6. Pharmacy Medicines Export HTTP Endpoint
    async def test_http_export_pharmacy_medicines(self):
        client = await self._get_client(self.super_user)
        async with client:
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.services.pharmacy_service.PharmacyService.export_medicines", AsyncMock(return_value=(io.BytesIO(b"med_excel"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))):
                    r = await client.get("/api/v1/pharmacy/medicines/export?format=excel")
                    assert r.status_code == 200
                    assert r.content == b"med_excel"

    # 7. Pharmacy Suppliers Export HTTP Endpoint
    async def test_http_export_pharmacy_suppliers(self):
        client = await self._get_client(self.super_user)
        async with client:
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.services.pharmacy_service.PharmacyService.export_suppliers", AsyncMock(return_value=(io.BytesIO(b"supp_excel"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))):
                    r = await client.get("/api/v1/pharmacy/suppliers/export?format=excel")
                    assert r.status_code == 200
                    assert r.content == b"supp_excel"

    # 8. Lab Orders Export HTTP Endpoint
    async def test_http_export_lab_orders(self):
        client = await self._get_client(self.super_user)
        async with client:
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.services.lab_service.LabService.export_orders", AsyncMock(return_value=(io.BytesIO(b"lab_excel"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))):
                    r = await client.get("/api/v1/lab/orders/export?format=excel")
                    assert r.status_code == 200
                    assert r.content == b"lab_excel"

    # 9. Create Lab Report HTTP Endpoint
    async def test_http_create_lab_report(self):
        client = await self._get_client(self.super_user)
        async with client:
            mock_rep = LabReportResponse(id=1, test_order_id=1, report_number="LR-1", status="COMPLETED", created_at=utc_now())
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.services.lab_service.LabService.create_report", AsyncMock(return_value=mock_rep)):
                    r = await client.post("/api/v1/lab/reports", json={"test_order_id": 1, "test_result_id": 1, "summary": "Normal"})
                    assert r.status_code == 201
                    assert r.json()["data"]["id"] == 1

    # 10. Verify Lab Report Doctor HTTP Endpoint
    async def test_http_verify_lab_report_doctor(self):
        client = await self._get_client(self.super_user)
        async with client:
            mock_rep = LabReportResponse(id=1, test_order_id=1, report_number="LR-1", status="VERIFIED", doctor_remarks="Approved by Dr.", created_at=utc_now())
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.services.lab_service.LabService.verify_by_doctor", AsyncMock(return_value=mock_rep)):
                    r = await client.patch("/api/v1/lab/reports/1/verify-doctor", json={"doctor_remarks": "Approved by Dr.", "approved": True})
                    assert r.status_code == 200
                    assert r.json()["data"]["status"] == "VERIFIED"

    # 11. Approve Lab Report HTTP Endpoint
    async def test_http_approve_lab_report(self):
        client = await self._get_client(self.super_user)
        async with client:
            mock_rep = LabReportResponse(id=1, test_order_id=1, report_number="LR-1", status="APPROVED", remarks="Approved", created_at=utc_now())
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.services.lab_service.LabService.approve_report", AsyncMock(return_value=mock_rep)):
                    r = await client.put("/api/v1/lab/reports/1/approve", json={"remarks": "Pathologist stamp", "approved": True})
                    assert r.status_code == 200
                    assert r.json()["data"]["status"] == "APPROVED"

    # 12. Download Lab Report HTTP Endpoint (Block 53 Path)
    async def test_http_download_lab_report_pdf(self, tmp_path):
        client = await self._get_client(self.super_user)
        dummy_pdf = tmp_path / "test_report.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 lab report")
        async with client:
            mock_report_entity = MagicMock()
            mock_report_entity.id = 1
            mock_report_entity.report_path = str(dummy_pdf)
            mock_report_entity.report_number = "LR-001"
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.repositories.lab_repository.LabReportRepository.get_by_id", AsyncMock(return_value=mock_report_entity)):
                    with patch("app.services.lab_service.LabService._validate_lab_report_access", AsyncMock()):
                        r = await client.get("/api/v1/lab/reports/1/download")
                        assert r.status_code == 200
                        assert r.headers["content-type"] == "application/pdf"
                        assert r.content.startswith(b"%PDF")

    # 13. Download Lab Dashboard PDF HTTP Endpoint
    async def test_http_download_lab_dashboard_pdf(self):
        client = await self._get_client(self.super_user)
        async with client:
            mock_hosp_entity = MagicMock()
            mock_hosp_entity.name = "Test Hosp"
            mock_hosp_entity.address = "123 Test"
            mock_hosp_entity.phone = "123"
            mock_hosp_entity.email = "h@t.com"
            mock_hosp_entity.logo = None
            mock_hosp_entity.logo_path = None
            mock_hosp_entity.logo_url = None
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.services.lab_dashboard_service.LabDashboardService.get_dashboard_data", AsyncMock(return_value=MagicMock())):
                    with patch("app.repositories.hospital_repository.HospitalRepository.get_by_id", AsyncMock(return_value=mock_hosp_entity)):
                        with patch("app.utils.lab_dashboard_pdf.generate_lab_dashboard_pdf", AsyncMock(return_value=b"%PDF-1.4 dash")):
                            r = await client.get("/api/v1/lab/dashboard/download/pdf")
                            assert r.status_code == 200
                            assert r.headers["content-type"] == "application/pdf"
                            assert r.content.startswith(b"%PDF")

    # 14. Billing Export HTTP Endpoint
    async def test_http_export_billing(self):
        client = await self._get_client(self.super_user)
        async with client:
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.services.billing_service.BillingService.export_billings", AsyncMock(return_value=(io.BytesIO(b"bill_excel"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))):
                    r = await client.get("/api/v1/billing/export?format=excel")
                    assert r.status_code == 200
                    assert r.content == b"bill_excel"

    # 15. Expenses Export HTTP Endpoint
    async def test_http_export_expenses(self):
        client = await self._get_client(self.super_user)
        async with client:
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.services.expense_service.ExpenseService.export_expenses", AsyncMock(return_value=(io.BytesIO(b"exp_excel"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))):
                    r = await client.get("/api/v1/expenses/export?format=excel")
                    assert r.status_code == 200
                    assert r.content == b"exp_excel"

    # 16. Inventory Items Export HTTP Endpoint
    async def test_http_export_inventory_items(self):
        client = await self._get_client(self.super_user)
        async with client:
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.services.inventory_service.InventoryService.export_items", AsyncMock(return_value=(io.BytesIO(b"inv_excel"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))):
                    r = await client.get("/api/v1/inventory/items/export?format=excel")
                    assert r.status_code == 200
                    assert r.content == b"inv_excel"

    # 17. Vendors Export HTTP Endpoint
    async def test_http_export_vendors(self):
        client = await self._get_client(self.super_user)
        async with client:
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.services.vendor_service.VendorService.export_vendors", AsyncMock(return_value=(io.BytesIO(b"vendor_excel"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))):
                    r = await client.get("/api/v1/vendors/export?format=excel")
                    assert r.status_code == 200
                    assert r.content == b"vendor_excel"

    # 18. Super Admin Update Hospital HTTP Endpoint
    async def test_http_update_hospital(self):
        client = await self._get_client(self.super_user)
        async with client:
            mock_hosp = HospitalResponse(id=1, name="Updated Hosp", email="hosp@example.com", is_active=True, created_at=utc_now(), updated_at=utc_now())
            with patch("app.services.hospital_service.HospitalService.update_hospital", AsyncMock(return_value=mock_hosp)):
                r = await client.put("/api/v1/super-admin/hospitals/1", json={"name": "Updated Hosp"})
                assert r.status_code == 200
                assert r.json()["data"]["name"] == "Updated Hosp"

    # 19. Super Admin Update Hospital Admin HTTP Endpoint
    async def test_http_update_hospital_admin(self):
        client = await self._get_client(self.super_user)
        async with client:
            mock_adm = UserResponse(id=2, user_code="U002", email="admin2@example.com", full_name="Admin2", role_id=2, is_active=True, is_verified=True, created_at=utc_now(), updated_at=utc_now(), phone=None, profile_image=None, gender=None, date_of_birth=None, last_login=None)
            with patch("app.services.hospital_service.HospitalService.update_hospital_admin", AsyncMock(return_value=mock_adm)):
                r = await client.put("/api/v1/super-admin/hospital-admins/2", json={"first_name": "Admin2"})
                assert r.status_code == 200
                assert r.json()["data"]["email"] == "admin2@example.com"

    # 20. Transactions Export HTTP Endpoint
    async def test_http_export_transactions(self):
        client = await self._get_client(self.super_user)
        async with client:
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.services.transaction_service.TransactionService.export_transactions", AsyncMock(return_value=(io.BytesIO(b"tx_excel"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))):
                    r = await client.get("/api/v1/transactions/export?format=excel")
                    assert r.status_code == 200
                    assert r.content == b"tx_excel"

    # 21. Pharmacy Sales Report HTTP Endpoint
    async def test_http_pharmacy_sales_report(self):
        client = await self._get_client(self.super_user)
        async with client:
            mock_hosp_entity = MagicMock()
            mock_hosp_entity.name = "Test Hosp"
            mock_hosp_entity.logo = None
            mock_hosp_entity.logo_path = None
            mock_hosp_entity.logo_url = None
            mock_sales = PharmacySalesResponse(total_sales=100.0, total_invoices=5, average_invoice_value=20.0)
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.repositories.hospital_repository.HospitalRepository.get_by_id", AsyncMock(return_value=mock_hosp_entity)):
                    with patch("app.services.report_service.ReportService.get_pharmacy_sales", AsyncMock(return_value=mock_sales)):
                        with patch("app.services.report_export_service.ReportExportService.export_csv", MagicMock(return_value=io.BytesIO(b"sales_csv"))):
                            r = await client.get("/api/v1/reports/pharmacy/sales?format=csv")
                            assert r.status_code == 200
                            assert r.content == b"sales_csv"

    # 22. Pharmacy Inventory Report HTTP Endpoint
    async def test_http_pharmacy_inventory_report(self):
        client = await self._get_client(self.super_user)
        async with client:
            mock_hosp_entity = MagicMock()
            mock_hosp_entity.name = "Test Hosp"
            mock_hosp_entity.logo = None
            mock_hosp_entity.logo_path = None
            mock_hosp_entity.logo_url = None
            mock_inv = PharmacyInventoryResponse(total_medicines=10, active_medicines=10, inactive_medicines=0, low_stock_medicines=0, out_of_stock_medicines=0, total_stock_quantity=100)
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.repositories.hospital_repository.HospitalRepository.get_by_id", AsyncMock(return_value=mock_hosp_entity)):
                    with patch("app.services.report_service.ReportService.get_pharmacy_inventory", AsyncMock(return_value=mock_inv)):
                        with patch("app.services.report_export_service.ReportExportService.export_csv", MagicMock(return_value=io.BytesIO(b"inv_csv"))):
                            r = await client.get("/api/v1/reports/pharmacy/inventory?format=csv")
                            assert r.status_code == 200
                            assert r.content == b"inv_csv"

    # 23. Pharmacy Expiry Report HTTP Endpoint
    async def test_http_pharmacy_expiry_report(self):
        client = await self._get_client(self.super_user)
        async with client:
            mock_hosp_entity = MagicMock()
            mock_hosp_entity.name = "Test Hosp"
            mock_hosp_entity.logo = None
            mock_hosp_entity.logo_path = None
            mock_hosp_entity.logo_url = None
            mock_exp = PharmacyExpiryResponse(total_medicines=10, expired_medicines=0, expiring_30_days=0, expiring_60_days=0, expiring_90_days=0)
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.repositories.hospital_repository.HospitalRepository.get_by_id", AsyncMock(return_value=mock_hosp_entity)):
                    with patch("app.services.report_service.ReportService.get_pharmacy_expiry", AsyncMock(return_value=mock_exp)):
                        with patch("app.services.report_export_service.ReportExportService.export_csv", MagicMock(return_value=io.BytesIO(b"exp_csv"))):
                            r = await client.get("/api/v1/reports/pharmacy/expiry?format=csv")
                            assert r.status_code == 200
                            assert r.content == b"exp_csv"

    # 24. Pharmacy Profit & Loss Report HTTP Endpoint
    async def test_http_pharmacy_profit_loss_report(self):
        client = await self._get_client(self.super_user)
        async with client:
            mock_hosp_entity = MagicMock()
            mock_hosp_entity.name = "Test Hosp"
            mock_hosp_entity.logo = None
            mock_hosp_entity.logo_path = None
            mock_hosp_entity.logo_url = None
            mock_pl = PharmacyProfitLossResponse(total_sales=100.0, total_cost=80.0, invoice_count=5, medicine_count=10)
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.repositories.hospital_repository.HospitalRepository.get_by_id", AsyncMock(return_value=mock_hosp_entity)):
                    with patch("app.services.report_service.ReportService.get_pharmacy_profit_loss", AsyncMock(return_value=mock_pl)):
                        with patch("app.services.report_export_service.ReportExportService.export_csv", MagicMock(return_value=io.BytesIO(b"pl_csv"))):
                            r = await client.get("/api/v1/reports/pharmacy/profit-loss?format=csv")
                            assert r.status_code == 200
                            assert r.content == b"pl_csv"

    # 25. Discharge Gate Pass PDF Download HTTP Endpoint
    async def test_http_download_gate_pass_pdf(self):
        client = await self._get_client(self.super_user)
        async with client:
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                with patch("app.services.discharge_service.DischargeService.download_gate_pass_pdf", AsyncMock(return_value=b"%PDF-1.4 gate pass")):
                    r = await client.get("/api/v1/discharge/1/gate-pass/download")
                    assert r.status_code == 200
                    assert r.headers["content-type"] == "application/pdf"
                    assert r.content.startswith(b"%PDF")

    # Multi-Tenant Isolation HTTP Endpoint Check: Non-superuser cannot access other hospital
    async def test_http_tenant_isolation_forbidden_on_cross_hospital_header(self):
        client = await self._get_client(self.tenant_user_hosp1)
        async with client:
            with patch("app.core.dependencies.RBACRepository.get_user_permissions", AsyncMock(return_value=["*"])):
                r = await client.get("/api/v1/appointments/export?format=excel", headers={"X-Hospital-Id": "2"})
                assert r.status_code == 403
                data = r.json()
                assert "detail" in data or "message" in data

    # Unauthenticated HTTP Endpoint Check: Returns 401
    async def test_http_unauthenticated_request_rejected(self):
        app.dependency_overrides.clear()
        async def override_db():
            yield self.mock_db
        app.dependency_overrides[get_db] = override_db

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/api/v1/patients/export?format=excel")
            assert r.status_code == 401
