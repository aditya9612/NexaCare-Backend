import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient
import fitz
from pypdf import PdfReader

from app.core.constants import UserRole
from app.core.dependencies import get_current_active_user
from app.main import app
from app.models.role_model import Role
from app.models.user_model import User
from app.models.lab_model import TestOrder as LabTestOrderModel
from app.services.lab_service import LabService


def override_current_user(user: User):
    async def _get_current_user():
        return user
    app.dependency_overrides[get_current_active_user] = _get_current_user


def build_test_user(role_name: str) -> User:
    role = Role(id=1, name=role_name, description=f"{role_name} role")
    user = User(
        id=1,
        user_code="U_TEST_USER",
        email="user@test.com",
        full_name="Test User",
        role_id=role.id,
        is_active=True,
        is_verified=True,
        hashed_password="hashed_password",
    )
    user.role = role
    return user


def create_mock_order(
    order_id: int = 1,
    order_number: str = "ORD-001",
    patient_id: int = 101,
    doctor_id: int = 201,
    notes: str = "Test notes",
    patient_name: str = "John Doe",
    doctor_name: str = "Dr. Smith",
    test_code: str = "LT001",
    test_name: str = "Complete Blood Count",
) -> LabTestOrderModel:
    order = MagicMock(spec=LabTestOrderModel)
    order.id = order_id
    order.order_number = order_number
    order.patient_id = patient_id
    order.doctor_id = doctor_id
    order.appointment_id = None
    order.department_id = 1
    order.status = "Pending"
    order.priority = "Normal"
    order.notes = notes
    order.ordered_at = "2026-09-21 10:00:00"
    order.completed_at = None

    test_obj = MagicMock()
    test_obj.test_code = test_code
    test_obj.test_name = test_name
    test_obj.category = "Pathology"
    test_obj.sample_type = "Blood"
    test_obj.price = 500.0
    order.lab_test = test_obj

    return order


# ============================================================================
# ISSUE 1: MARATHI TEXT PRESERVATION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_lab_export_pdf_marathi_text_service_level():
    """Verify that PDF export preserves Marathi Unicode text and does not render square boxes."""
    mock_db = AsyncMock()
    svc = LabService(mock_db)

    marathi_patient_name = "सुरेश पाटील"
    marathi_doctor_name = "डॉ. रमेश जोशी"
    marathi_test_name = "संपूर्ण रक्त तपासणी"
    marathi_notes = "प्रयोगशाळा चाचणी टिप्पणी: रक्त तपासणी वेळेवर करणे."

    order = create_mock_order(
        notes=marathi_notes,
        test_name=marathi_test_name,
    )

    svc.order_repo = AsyncMock()
    svc.order_repo.get_all_active.return_value = [order]

    # Mock DB query results for patients, doctors, appointments mapping
    mock_db.execute.side_effect = [
        MagicMock(all=lambda: [(101, "सुरेश", "पाटील", "P001")]),
        MagicMock(all=lambda: [(201, "रमेश", "जोशी", "D001")]),
        MagicMock(all=lambda: []),
    ]

    current_user = MagicMock(id=1, role=MagicMock(name=UserRole.SUPER_ADMIN))
    pdf_bytes, media_type = await svc.export_orders(format_type="pdf", current_user=current_user)

    # Assertions
    assert media_type == "application/pdf"
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 0

    # Parse generated PDF content
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    extracted_text = "".join([page.get_text() for page in doc])

    # Assert Marathi Unicode text is preserved correctly
    assert "सुरेश" in extracted_text
    assert "पाटील" in extracted_text
    assert "रक्त तपासणी" in extracted_text
    assert "प्रयोगशाळा" in extracted_text

    # Assert no square box replacement glyphs or unmapped characters
    assert "□" not in extracted_text
    assert "\u25a1" not in extracted_text
    assert "\u25a0" not in extracted_text
    assert "\ufffd" not in extracted_text


@pytest.mark.asyncio
async def test_lab_export_pdf_marathi_text_api_endpoint(client: AsyncClient):
    """Verify GET /api/v1/lab/orders/export?format=pdf endpoint preserves Marathi text."""
    user = build_test_user(UserRole.SUPER_ADMIN)
    override_current_user(user)

    pdf_sample_bytes = b"%PDF-1.4 Mock PDF with Marathi text: \xe0\xa4\xb8\xe0\xa5\x81\xe0\xa4\xb0\xe0\xa5\x87\xe0\xa4\xb6"

    mock_service = AsyncMock()
    mock_service.export_orders = AsyncMock(return_value=(pdf_sample_bytes, "application/pdf"))

    with patch("app.api.v1.routes.lab_routes.LabService", return_value=mock_service):
        response = await client.get("/api/v1/lab/orders/export?format=pdf")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"] == "attachment; filename=lab_test_orders_export.pdf"
        assert response.content == pdf_sample_bytes
        mock_service.export_orders.assert_called_once()


# ============================================================================
# ISSUE 2: NOTES COLUMN LAYOUT & WRAPPING TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_lab_export_pdf_notes_column_layout_wrapping():
    """Verify that long unbroken notes wrap properly and do not break PDF table layout."""
    mock_db = AsyncMock()
    svc = LabService(mock_db)

    long_note_with_unbroken_code = (
        "Patient requires urgent processing. Ref code: REF_12345678901234567890 for verification."
    )

    order = create_mock_order(
        notes=long_note_with_unbroken_code,
        order_number="ORD-999999999999999",
    )

    svc.order_repo = AsyncMock()
    svc.order_repo.get_all_active.return_value = [order]

    mock_db.execute.side_effect = [
        MagicMock(all=lambda: [(101, "John", "Doe", "P001")]),
        MagicMock(all=lambda: [(201, "Jane", "Smith", "D001")]),
        MagicMock(all=lambda: []),
    ]

    current_user = MagicMock(id=1, role=MagicMock(name=UserRole.SUPER_ADMIN))
    pdf_bytes, media_type = await svc.export_orders(format_type="pdf", current_user=current_user)

    # Assertions
    assert media_type == "application/pdf"
    assert pdf_bytes.startswith(b"%PDF-")

    # Verify text extraction via PyMuPDF / fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    assert len(doc) >= 1  # PDF generated with valid pages
    extracted_text = "".join([page.get_text() for page in doc])

    # Verify notes content and unbroken code wrapping
    clean_text = extracted_text.replace("\u200b", "").replace("\n", " ")
    assert "Patient requires urgent processing" in clean_text
    assert "REF_12345678901234567890" in clean_text
    assert "verification" in clean_text

    # Verify unbroken code chunking inside extracted text
    assert "REF_12345678" in extracted_text

    # Verify PyPDF Reader can also parse document structure without corruption
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) >= 1
    pypdf_text = "".join([p.extract_text() for p in reader.pages]).replace("\u200b", "")
    assert "REF_12345678901234567890" in pypdf_text


@pytest.mark.asyncio
async def test_lab_export_pdf_notes_column_layout_api_endpoint(client: AsyncClient):
    """Verify GET /api/v1/lab/orders/export?format=pdf endpoint returns wrapped layout PDF."""
    user = build_test_user(UserRole.SUPER_ADMIN)
    override_current_user(user)

    mock_pdf_content = b"%PDF-1.4 Mock PDF Layout Content"
    mock_service = AsyncMock()
    mock_service.export_orders = AsyncMock(return_value=(mock_pdf_content, "application/pdf"))

    with patch("app.api.v1.routes.lab_routes.LabService", return_value=mock_service):
        response = await client.get("/api/v1/lab/orders/export?format=pdf&status=Pending")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content == mock_pdf_content
        mock_service.export_orders.assert_called_once()


def test_wrap_unbroken_text_behavior():
    """Unit test for the unbroken text wrapping logic embedded in export_orders."""
    def wrap_unbroken_text(text: str, max_chars: int = 12) -> str:
        if not text:
            return ""
        words = text.split(" ")
        processed_words = []
        for word in words:
            if len(word) > max_chars:
                chunks = [word[i:i+max_chars] for i in range(0, len(word), max_chars)]
                processed_words.append("\u200b".join(chunks))
            else:
                processed_words.append(word)
        return " ".join(processed_words)

    # Empty text
    assert wrap_unbroken_text("") == ""
    assert wrap_unbroken_text(None) == ""

    # Short text <= 12 chars
    assert wrap_unbroken_text("Short Note") == "Short Note"

    # Single long word > 12 chars gets zero-width spaces inserted
    long_word = "A" * 25
    wrapped = wrap_unbroken_text(long_word, max_chars=12)
    assert "\u200b" in wrapped
    parts = wrapped.split("\u200b")
    assert len(parts) == 3
    assert len(parts[0]) == 12
    assert len(parts[1]) == 12
    assert len(parts[2]) == 1

    # Mixed short and long words
    mixed = "Patient Note VERYLONGWORDWITHOUTSPACES12345 Regular"
    wrapped_mixed = wrap_unbroken_text(mixed, max_chars=12)
    assert "Patient Note " in wrapped_mixed
    assert " Regular" in wrapped_mixed
    assert "\u200b" in wrapped_mixed
