import pytest
from app.utils.pdf_generator import generate_lab_report_html
import os

@pytest.mark.asyncio
async def test_generate_lab_report_html_with_hospital_details(tmp_path):
    report_data = {
        "order_number": "ORD-20261023-001",
        "report_number": "RPT-20261023-001",
        "status": "approved",
        "generated_at": "2026-10-23 10:00:00",
        "patient_name": "Manisha Koirala",
        "patient_code": "PAT-20261021-001",
        "patient_gender": "Female",
        "patient_dob": "1970-09-05",
        "doctor_name": "Dr. Rajesh Swami",
        "doctor_code": "DOC-20260909-01",
        "test_name": "Blood Glucose",
        "test_category": "Biochemistry",
        "sample_type": "Blood",
        "summary": "Fasting blood sugar within normal physiological limits.",
        "columns": ["Parameter", "Result Value", "Unit", "Normal Range", "Is Critical"],
        "rows": [
            ["Fasting Blood Sugar", "95", "mg/dL", "70-110", "No"],
            ["Post Prandial", "135", "mg/dL", "< 140", "No"],
        ],
        "hospital_name": "NexaCare Multi-Speciality Hospital",
        "hospital_address": "123 Medical Enclave, Pune, Maharashtra 411001",
        "hospital_phone": "+91 98765 43210",
        "hospital_email": "contact@nexacare.com",
        "hospital_website": "www.nexacare.com",
        "hospital_logo": None,
        "title": "Diagnostic Report",
    }

    rel_path = await generate_lab_report_html("RPT-20261023-001", report_data)
    assert rel_path is not None
    # Verify file created
    disk_path = os.path.join("app", rel_path.lstrip("/"))
    assert os.path.exists(disk_path)
    
    # Read generated content to verify template fields
    if disk_path.endswith(".html"):
        with open(disk_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "NexaCare Multi-Speciality Hospital" in content
            assert "Manisha Koirala" in content
            assert "Blood Glucose" in content
            assert "Medical Laboratory Technologist" in content
            assert "Consultant Pathologist" in content
            assert "Confidential Medical Document" in content
            assert "Lab Report Report" not in content
