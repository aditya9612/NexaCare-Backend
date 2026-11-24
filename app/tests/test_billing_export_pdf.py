import pytest
from io import BytesIO
import pypdf
from unittest.mock import patch
from datetime import datetime
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.services.billing_service import BillingService
from app.models.user_model import User
from app.models.role_model import Role
from app.utils.helpers import get_now_ist


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
def hospital_6_admin():
    user = User(id=1, email="chetan.kumar@gmail.com", hospital_id=6)
    user.role = Role(name="hospital_admin")
    return user


@pytest.mark.asyncio
async def test_billing_export_pdf_uses_ist_timestamp(db_session: AsyncSession, hospital_6_admin):
    """
    Verifies that BillingService.export_billings generates the PDF
    using Indian Standard Time (IST, UTC+05:30) via get_now_ist().
    """
    fixed_ist_dt = datetime(2026, 11, 19, 19, 30, 45)
    expected_timestamp_str = "2026-11-19 19:30:45"

    service = BillingService(db_session)

    with patch("app.utils.helpers.get_now_ist", return_value=fixed_ist_dt) as mock_get_now_ist:
        pdf_bytes, media_type = await service.export_billings(
            format_type="pdf",
            current_user=hospital_6_admin,
        )

        assert media_type == "application/pdf"
        assert len(pdf_bytes) > 0
        assert mock_get_now_ist.called, "get_now_ist() must be called to generate the IST timestamp"

        # Verify extracted PDF text contains the IST timestamp
        reader = pypdf.PdfReader(BytesIO(pdf_bytes))
        assert len(reader.pages) >= 1

        pdf_text = "\n".join(page.extract_text() for page in reader.pages)
        assert expected_timestamp_str in pdf_text, f"Expected {expected_timestamp_str} in PDF text"
        assert "Billings & Invoices Report" in pdf_text


@pytest.mark.asyncio
async def test_billing_export_pdf_dynamic_timestamp_matches_ist_format(db_session: AsyncSession, hospital_6_admin):
    """
    Verifies that the PDF export with real get_now_ist() produces a valid timestamp
    matching today's date in IST.
    """
    current_ist = get_now_ist()
    today_ist_str = current_ist.strftime("%Y-%m-%d")

    service = BillingService(db_session)
    pdf_bytes, media_type = await service.export_billings(
        format_type="pdf",
        current_user=hospital_6_admin,
    )

    assert media_type == "application/pdf"
    assert len(pdf_bytes) > 0

    reader = pypdf.PdfReader(BytesIO(pdf_bytes))
    pdf_text = "\n".join(page.extract_text() for page in reader.pages)

    assert "Generated:" in pdf_text
    assert today_ist_str in pdf_text
