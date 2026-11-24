import os
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from jinja2 import Environment, FileSystemLoader

from app.core.exceptions import NotFoundException, ForbiddenException
from app.models.billing_model import Billing, BillItem
from app.models.hospital_model import Hospital
from app.models.patient_model import Patient
from app.models.pharmacy_model import PharmacyInvoice
from app.models.role_model import Role
from app.models.user_model import User
from app.services.billing_service import BillingService
from app.utils.pdf_generator import resolve_logo_as_data_uri


def make_user(role_name: str, hospital_id: int | None = None, active_hospital_id: int | None = None) -> User:
    user = User()
    user.id = 10
    user.hospital_id = hospital_id
    user.active_hospital_id = active_hospital_id
    role = Role()
    role.name = role_name
    user.role = role
    return user


def make_hospital(hosp_id: int, name: str, email: str, phone: str, address: str, website: str, logo_path: str | None = None) -> Hospital:
    hosp = Hospital()
    hosp.id = hosp_id
    hosp.name = name
    hosp.email = email
    hosp.phone = phone
    hosp.address = address
    hosp.website = website
    hosp.logo_path = logo_path
    return hosp


def make_billing(billing_id: int, hospital_id: int | None, bill_number: str = "BILL-001") -> Billing:
    billing = Billing()
    billing.id = billing_id
    billing.hospital_id = hospital_id
    billing.bill_number = bill_number
    billing.patient_id = 99
    billing.items = []
    billing.subtotal = 100.0
    billing.discount_percent = 0.0
    billing.discount_amount = 0.0
    billing.gst_rate = 18.0
    billing.gst_amount = 18.0
    billing.tax_amount = 18.0
    billing.total_amount = 118.0
    billing.paid_amount = 118.0
    billing.balance_amount = 0.0
    billing.status = "paid"
    billing.notes = "Full payment received"
    return billing


# ---------------------------------------------------------------------------
# Test 1: Hospital 1215 invoice displays Chetan Multispeciality Hospital branding
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_hospital_1215_invoice_displays_chetan_branding():
    mock_db = AsyncMock()
    service = BillingService(mock_db)

    hosp_1215 = make_hospital(
        1215,
        "Chetan Multispeciality Hospital",
        "viveksm228@gmail.com",
        "+919876543232",
        "Main Road, Bhusawal, Maharashtra, India",
        "https://chetan-hospital.com",
        "uploads/hospitals/chetan_logo.png",
    )
    billing_1215 = make_billing(501, 1215, "BILL-1215-001")
    patient = Patient(id=99, first_name="Ramesh", last_name="Patil", phone="+919800000000", email="ramesh@gmail.com")

    service.repo.get_by_id = AsyncMock(return_value=billing_1215)
    service.repo.update = AsyncMock()
    service.patient_repo.get_by_id = AsyncMock(return_value=patient)
    service.hospital_repo.get_by_id = AsyncMock(return_value=hosp_1215)
    service.audit_repo.create = AsyncMock()

    user_1215 = make_user("hospital_admin", hospital_id=1215)

    with patch("app.services.billing_service.generate_invoice_pdf", new_callable=AsyncMock) as mock_pdf:
        mock_pdf.return_value = ("/tmp/invoice.pdf", b"%PDF-1.4 mock")
        path, pdf_bytes = await service.generate_invoice(501, user_id=user_1215.id, current_user=user_1215)

        assert mock_pdf.called
        bill_num_arg, data_arg = mock_pdf.call_args[0]
        assert bill_num_arg == "BILL-1215-001"
        assert data_arg["hospital_name"] == "Chetan Multispeciality Hospital"
        assert data_arg["hospital_address"] == "Main Road, Bhusawal, Maharashtra, India"
        assert data_arg["hospital_phone"] == "+919876543232"
        assert data_arg["hospital_email"] == "viveksm228@gmail.com"
        assert data_arg["hospital_website"] == "https://chetan-hospital.com"
        assert data_arg["hospital_logo"] == "uploads/hospitals/chetan_logo.png"


# ---------------------------------------------------------------------------
# Test 2: Hospital 6 invoice displays its own stored hospital branding
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_hospital_6_invoice_displays_stored_branding():
    mock_db = AsyncMock()
    service = BillingService(mock_db)

    hosp_6 = make_hospital(
        6,
        "NexaCare Default Hospital",
        "superadmin@nexacare.com",
        "+919890114346",
        "NexaCare Hospital, Wing B, Floor 1, Pune, Maharashtra, India",
        "https://nexacare.com",
        "uploads/hospitals/nexacare_logo.png",
    )
    billing_6 = make_billing(101, 6, "IPD-BILL-20261105-0002")
    patient = Patient(id=99, first_name="Aarav", last_name="Sharma", phone="+919811111111", email="aarav@gmail.com")

    service.repo.get_by_id = AsyncMock(return_value=billing_6)
    service.repo.update = AsyncMock()
    service.patient_repo.get_by_id = AsyncMock(return_value=patient)
    service.hospital_repo.get_by_id = AsyncMock(return_value=hosp_6)
    service.audit_repo.create = AsyncMock()

    user_6 = make_user("hospital_admin", hospital_id=6)

    with patch("app.services.billing_service.generate_invoice_pdf", new_callable=AsyncMock) as mock_pdf:
        mock_pdf.return_value = ("/tmp/invoice.pdf", b"%PDF-1.4 mock")
        path, pdf_bytes = await service.generate_invoice(101, user_id=user_6.id, current_user=user_6)

        assert mock_pdf.called
        bill_num_arg, data_arg = mock_pdf.call_args[0]
        assert bill_num_arg == "IPD-BILL-20261105-0002"
        assert data_arg["hospital_name"] == "NexaCare Default Hospital"
        assert data_arg["hospital_address"] == "NexaCare Hospital, Wing B, Floor 1, Pune, Maharashtra, India"
        assert data_arg["hospital_phone"] == "+919890114346"
        assert data_arg["hospital_email"] == "superadmin@nexacare.com"


# ---------------------------------------------------------------------------
# Test 3: Super Admin with default hospital ID 6 accessing Hospital 1215 invoice gets Hospital 1215 branding
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_super_admin_with_hospital_6_gets_hospital_1215_branding():
    mock_db = AsyncMock()
    service = BillingService(mock_db)

    hosp_1215 = make_hospital(
        1215,
        "Chetan Multispeciality Hospital",
        "viveksm228@gmail.com",
        "+919876543232",
        "Main Road, Bhusawal, Maharashtra, India",
        "https://chetan-hospital.com",
        "uploads/hospitals/chetan_logo.png",
    )
    billing_1215 = make_billing(501, 1215, "BILL-1215-001")
    patient = Patient(id=99, first_name="Ramesh", last_name="Patil", phone="-", email="-")

    # Super Admin has hospital_id=6 (seeded)
    super_admin_user = make_user("super_admin", hospital_id=6)

    service.repo.get_by_id = AsyncMock(return_value=billing_1215)
    service.repo.update = AsyncMock()
    service.patient_repo.get_by_id = AsyncMock(return_value=patient)
    service.hospital_repo.get_by_id = AsyncMock(return_value=hosp_1215)
    service.audit_repo.create = AsyncMock()

    with patch("app.services.billing_service.generate_invoice_pdf", new_callable=AsyncMock) as mock_pdf:
        mock_pdf.return_value = ("/tmp/invoice.pdf", b"%PDF-1.4 mock")
        path, pdf_bytes = await service.generate_invoice(501, user_id=super_admin_user.id, current_user=super_admin_user)

        assert mock_pdf.called
        _, data_arg = mock_pdf.call_args[0]
        # Must resolve to billing.hospital_id (1215), NOT current_user.hospital_id (6)!
        service.hospital_repo.get_by_id.assert_called_with(1215)
        assert data_arg["hospital_name"] == "Chetan Multispeciality Hospital"
        assert data_arg["hospital_address"] == "Main Road, Bhusawal, Maharashtra, India"


# ---------------------------------------------------------------------------
# Test 4: Normal Hospital 6 users cannot access Hospital 1215 invoices
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_hospital_6_user_cannot_access_hospital_1215_invoice():
    mock_db = AsyncMock()
    service = BillingService(mock_db)

    user_6 = make_user("receptionist", hospital_id=6)

    # Repository returns None because hospital_id=6 does not match billing.hospital_id=1215
    service.repo.get_by_id = AsyncMock(return_value=None)
    mock_db.execute = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_res

    with pytest.raises(NotFoundException) as exc_info:
        await service.generate_invoice(501, user_id=user_6.id, current_user=user_6)

    assert "Billing record not found" in str(exc_info.value)
    service.repo.get_by_id.assert_called_once_with(501, hospital_id=6)


# ---------------------------------------------------------------------------
# Test 5: Valid logo is converted to a Base64 Data URI
# ---------------------------------------------------------------------------
def test_valid_logo_converted_to_base64_data_uri():
    # Test PNG
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01")
        tmp_png = tmp.name

    try:
        data_uri = resolve_logo_as_data_uri(tmp_png)
        assert data_uri is not None
        assert data_uri.startswith("data:image/png;base64,")
    finally:
        os.remove(tmp_png)

    # Test JPEG
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01")
        tmp_jpg = tmp.name

    try:
        data_uri = resolve_logo_as_data_uri(tmp_jpg)
        assert data_uri is not None
        assert data_uri.startswith("data:image/jpeg;base64,")
    finally:
        os.remove(tmp_jpg)


# ---------------------------------------------------------------------------
# Test 6: Missing logo file does not break PDF / Data URI generation
# ---------------------------------------------------------------------------
def test_missing_logo_file_returns_none_safely():
    non_existent = "uploads/hospitals/non_existent_logo_12345.png"
    assert resolve_logo_as_data_uri(non_existent) is None
    assert resolve_logo_as_data_uri(None) is None
    assert resolve_logo_as_data_uri("") is None


# ---------------------------------------------------------------------------
# Test 7: NULL hospital ID is handled safely without error
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_null_hospital_id_handled_safely():
    mock_db = AsyncMock()
    service = BillingService(mock_db)

    # Bill has hospital_id=None, user has hospital_id=None
    billing_no_hosp = make_billing(999, hospital_id=None, bill_number="BILL-NO-HOSP-001")
    patient = Patient(id=99, first_name="Anonymous", last_name="", phone="-", email="-")

    service.repo.get_by_id = AsyncMock(return_value=billing_no_hosp)
    service.repo.update = AsyncMock()
    service.patient_repo.get_by_id = AsyncMock(return_value=patient)
    service.hospital_repo.get_by_id = AsyncMock(return_value=None)
    service.audit_repo.create = AsyncMock()

    user_null = make_user("super_admin", hospital_id=None)

    with patch("app.services.billing_service.generate_invoice_pdf", new_callable=AsyncMock) as mock_pdf:
        mock_pdf.return_value = ("/tmp/invoice.pdf", b"%PDF-1.4 mock")
        path, pdf_bytes = await service.generate_invoice(999, user_id=user_null.id, current_user=user_null)

        assert mock_pdf.called
        bill_num_arg, data_arg = mock_pdf.call_args[0]
        assert data_arg["hospital_name"] == ""
        assert data_arg["hospital_address"] == ""
        assert data_arg["hospital_phone"] == ""
        assert data_arg["hospital_email"] == ""
        assert data_arg["hospital_logo"] is None


# ---------------------------------------------------------------------------
# Test 8: Pharmacy invoice fallback uses the correct hospital branding
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pharmacy_invoice_fallback_uses_correct_hospital_branding():
    mock_db = AsyncMock()
    service = BillingService(mock_db)

    # Standard billing not found
    service.repo.get_by_id = AsyncMock(return_value=None)

    # Pharmacy invoice with hospital_id=1215
    pharmacy_invoice = PharmacyInvoice()
    pharmacy_invoice.id = 801
    pharmacy_invoice.hospital_id = 1215
    pharmacy_invoice.invoice_number = "PHARM-INV-801"
    pharmacy_invoice.patient_id = 99
    pharmacy_invoice.prescription_id = 10
    pharmacy_invoice.items = []
    pharmacy_invoice.subtotal = 200.0
    pharmacy_invoice.discount_percentage = 0.0
    pharmacy_invoice.discount_amount = 0.0
    pharmacy_invoice.tax_percentage = 12.0
    pharmacy_invoice.gst_amount = 24.0
    pharmacy_invoice.tax_amount = 24.0
    pharmacy_invoice.total_amount = 224.0
    pharmacy_invoice.paid_amount = 224.0
    pharmacy_invoice.status = "paid"
    pharmacy_invoice.created_at = None

    mock_db.execute = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = pharmacy_invoice
    mock_db.execute.return_value = mock_res

    hosp_1215 = make_hospital(
        1215,
        "Chetan Multispeciality Hospital",
        "viveksm228@gmail.com",
        "+919876543232",
        "Main Road, Bhusawal, Maharashtra, India",
        "https://chetan-hospital.com",
        "uploads/hospitals/chetan_logo.png",
    )
    service.hospital_repo.get_by_id = AsyncMock(return_value=hosp_1215)
    service.patient_repo.get_by_id = AsyncMock(return_value=None)
    service.audit_repo.create = AsyncMock()

    user = make_user("hospital_admin", hospital_id=1215)

    with patch("app.services.billing_service.generate_invoice_pdf", new_callable=AsyncMock) as mock_pdf:
        mock_pdf.return_value = ("/tmp/invoice.pdf", b"%PDF-1.4 mock")
        path, pdf_bytes = await service.generate_invoice(801, user_id=user.id, current_user=user)

        assert mock_pdf.called
        bill_num_arg, data_arg = mock_pdf.call_args[0]
        assert bill_num_arg == "PHARM-INV-801"
        assert data_arg["hospital_name"] == "Chetan Multispeciality Hospital"
        assert data_arg["hospital_address"] == "Main Road, Bhusawal, Maharashtra, India"
        assert data_arg["hospital_phone"] == "+919876543232"
        assert data_arg["hospital_email"] == "viveksm228@gmail.com"
        assert data_arg["hospital_website"] == "https://chetan-hospital.com"
        assert data_arg["hospital_logo"] == "uploads/hospitals/chetan_logo.png"
