import pytest
import pymupdf
from datetime import datetime
from unittest.mock import AsyncMock
from app.services.patient_service import PatientService
from app.models.patient_model import Patient

@pytest.mark.asyncio
async def test_export_patients_pdf_marathi_rendering():
    # Create mock patient with Marathi Devanagari name
    patient1 = Patient(
        id=1,
        patient_code="P001",
        first_name="राहुल",
        last_name="पाटील",
        gender="Male",
        dob="1990-01-01",
        blood_group="O+",
        phone="9876543210",
        email="rahul@example.com",
        address="123 मेन स्ट्रीट",
        city="पुणे",
        state="महाराष्ट्र",
        pincode="411001",
        status="active",
        diagnosis="सामान्य तपासणी",
        emergency_contact_name="अमित पाटील",
        emergency_contact_number="9876543211",
        created_at=datetime(2026, 9, 15, 10, 0, 0),
    )

    patient2 = Patient(
        id=2,
        patient_code="P002",
        first_name="John",
        last_name="Doe",
        gender="Male",
        dob="1985-05-15",
        blood_group="A+",
        phone="9876543212",
        email="john@example.com",
        address="456 High St",
        city="Mumbai",
        state="Maharashtra",
        pincode="400001",
        status="active",
        diagnosis="Routine Checkup",
        emergency_contact_name="Jane Doe",
        emergency_contact_number="9876543213",
        created_at=datetime(2026, 9, 15, 11, 0, 0),
    )

    mock_db = AsyncMock()
    service = PatientService(mock_db)

    # Patch repo.filter_patients and repo.get_all to return our test patients
    service.repo = AsyncMock()
    service.repo.filter_patients.return_value = [patient1, patient2]
    service.repo.get_all.return_value = [patient1, patient2]

    # Generate PDF export
    pdf_bytes, media_type = await service.export_patients(format_type="pdf", status="active")

    assert media_type == "application/pdf"
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0

    # Verify extracted text from generated PDF contains both Marathi and English names
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    full_text = "".join([page.get_text() for page in doc])

    # Check Marathi characters
    assert "राहुल" in full_text
    assert "पाटील" in full_text
    assert "पुणे" in full_text

    # Check English characters
    assert "John" in full_text
    assert "Doe" in full_text
    assert "P001" in full_text
    assert "P002" in full_text
