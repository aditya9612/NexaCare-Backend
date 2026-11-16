import pytest
from io import BytesIO
import openpyxl
import pypdf
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.services.transaction_service import TransactionService
from app.models.user_model import User
from app.models.role_model import Role


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
def hospital_6_admin():
    user = User(id=1, email="chetan.kumar@gmail.com", hospital_id=6)
    user.role = Role(name="hospital_admin")
    return user


@pytest.fixture
def hospital_other_admin():
    user = User(id=999, email="other@hospital.com", hospital_id=9999)
    user.role = Role(name="hospital_admin")
    return user


@pytest.mark.asyncio
async def test_transaction_export_excel_populates_bill_number_and_patient_name(db_session: AsyncSession, hospital_6_admin):
    """
    Verifies that Excel export resolves bill_number and patient_name correctly
    and does not produce '-' or blank values due to result consumption bugs.
    """
    service = TransactionService(db_session)
    stream, media_type = await service.export_transactions(
        format_type="excel",
        current_user=hospital_6_admin,
    )
    assert media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    wb = openpyxl.load_workbook(stream)
    ws = wb.active
    assert ws.title == "Transactions Report"

    headers = [cell.value for cell in ws[1]]
    assert headers == [
        "Sr. No.", "Bill Number", "Patient Name", "Amount", "Payment Method",
        "Transaction Ref", "Payment Date", "Status", "Is Refund", "Refund Reason",
        "Created At", "Updated At"
    ]

    rows = list(ws.iter_rows(values_only=True))[1:]
    assert len(rows) == 46, f"Expected 46 records, found {len(rows)}"

    # Locate transaction 76
    txn_76 = next((r for r in rows if r[5] == "TEST-IPD-20261105-0002"), None)
    assert txn_76 is not None, "Transaction 76 with ref TEST-IPD-20261105-0002 must exist"

    # Verify fields for transaction 76
    bill_number = txn_76[1]
    patient_name = txn_76[2]
    amount = txn_76[3]
    payment_method = txn_76[4]
    status = txn_76[7]
    is_refund = txn_76[8]

    assert bill_number == "IPD-BILL-20261105-0002"
    assert bill_number != "-"
    assert patient_name == "Test Patient"
    assert patient_name != "-" and patient_name != ""
    assert amount == "₹94500.00"
    assert payment_method.lower() == "cash"
    assert status.lower() == "completed"
    assert is_refund == "No"


@pytest.mark.asyncio
async def test_transaction_export_pdf_contains_patient_name_and_bill_number(db_session: AsyncSession, hospital_6_admin):
    """
    Verifies that PDF export contains the Patient Name column and renders
    valid bill numbers and patient names without omission.
    """
    service = TransactionService(db_session)
    pdf_bytes, media_type = await service.export_transactions(
        format_type="pdf",
        current_user=hospital_6_admin,
    )
    assert media_type == "application/pdf"
    assert len(pdf_bytes) > 0

    reader = pypdf.PdfReader(BytesIO(pdf_bytes))
    assert len(reader.pages) >= 1

    pdf_text = "\n".join(page.extract_text() for page in reader.pages)

    # Verify headers and meta
    assert "Transactions Report" in pdf_text
    assert "Total Records: 46" in pdf_text
    assert "Patient Name" in pdf_text
    assert "Bill Number" in pdf_text

    # Verify transaction 76 content
    assert "IPD-BILL-20261105-0002" in pdf_text
    assert "Test Patient" in pdf_text
    assert "TEST-IPD-20261105-0002" in pdf_text
    assert "Payment" in pdf_text


@pytest.mark.asyncio
async def test_transaction_export_refund_and_payment_types(db_session: AsyncSession, hospital_6_admin):
    """
    Verifies that both payments and refund records are appropriately identified and rendered.
    """
    service = TransactionService(db_session)
    stream, _ = await service.export_transactions(
        format_type="excel",
        current_user=hospital_6_admin,
    )

    wb = openpyxl.load_workbook(stream)
    rows = list(wb.active.iter_rows(values_only=True))[1:]

    refund_rows = [r for r in rows if r[8] == "Yes"]
    payment_rows = [r for r in rows if r[8] == "No"]

    assert len(refund_rows) > 0, "Expected at least 1 refund record"
    assert len(payment_rows) > 0, "Expected payment records"
    assert len(refund_rows) + len(payment_rows) == len(rows)


@pytest.mark.asyncio
async def test_transaction_export_tenant_isolation(db_session: AsyncSession, hospital_other_admin):
    """
    Verifies hospital-wise data isolation: an admin from Hospital 9999
    cannot access or export transactions belonging to Hospital 6.
    """
    service = TransactionService(db_session)
    stream, _ = await service.export_transactions(
        format_type="excel",
        current_user=hospital_other_admin,
    )

    wb = openpyxl.load_workbook(stream)
    rows = list(wb.active.iter_rows(values_only=True))[1:]
    assert len(rows) == 0, "Hospital 9999 should not receive Hospital 6 transactions"


@pytest.mark.asyncio
async def test_transaction_export_sorting_support(db_session: AsyncSession, hospital_6_admin):
    """
    Verifies that sort_by and sort_order parameters correctly affect exported row ordering.
    """
    service = TransactionService(db_session)

    # Export sorted by amount ascending
    stream_asc, _ = await service.export_transactions(
        format_type="excel",
        sort_by="amount",
        sort_order="asc",
        current_user=hospital_6_admin,
    )
    rows_asc = list(openpyxl.load_workbook(stream_asc).active.iter_rows(values_only=True))[1:]

    # Export sorted by amount descending
    stream_desc, _ = await service.export_transactions(
        format_type="excel",
        sort_by="amount",
        sort_order="desc",
        current_user=hospital_6_admin,
    )
    rows_desc = list(openpyxl.load_workbook(stream_desc).active.iter_rows(values_only=True))[1:]

    assert len(rows_asc) == len(rows_desc) == 46
    first_amount_str = rows_asc[0][3].replace("₹", "").replace(",", "")
    last_amount_str = rows_asc[-1][3].replace("₹", "").replace(",", "")
    assert float(first_amount_str) <= float(last_amount_str)


@pytest.mark.asyncio
async def test_regression_duplicate_result_consumption(db_session: AsyncSession, hospital_6_admin):
    """
    Regression test ensuring that calling export_transactions sequentially
    does not exhaust shared state or leave billing_map empty.
    """
    service = TransactionService(db_session)

    # First call
    stream1, _ = await service.export_transactions(format_type="excel", current_user=hospital_6_admin)
    rows1 = list(openpyxl.load_workbook(stream1).active.iter_rows(values_only=True))[1:]

    # Second call immediately after on same service instance
    stream2, _ = await service.export_transactions(format_type="excel", current_user=hospital_6_admin)
    rows2 = list(openpyxl.load_workbook(stream2).active.iter_rows(values_only=True))[1:]

    txn_first = next((r for r in rows1 if r[5] == "TEST-IPD-20261105-0002"), None)
    txn_second = next((r for r in rows2 if r[5] == "TEST-IPD-20261105-0002"), None)

    assert txn_first[1] == txn_second[1] == "IPD-BILL-20261105-0002"
    assert txn_first[2] == txn_second[2] == "Test Patient"
