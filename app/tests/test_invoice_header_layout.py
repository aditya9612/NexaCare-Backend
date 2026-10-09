import pytest
from jinja2 import Environment, FileSystemLoader
from app.utils.pdf_generator import generate_invoice_pdf

env = Environment(loader=FileSystemLoader("app/templates"))

def test_invoice_template_renders_hospital_name():
    template = env.get_template("invoice_template.html")
    html = template.render(
        hospital_name="City Care Super Speciality Hospital",
        invoice_number="BIL-2026100567AC1B",
        patient_name="Yogesh Rahane",
        patient_phone="+917898789846",
        patient_email="yogesh@user.com",
        date="2026-10-05",
        status="Pending",
        items=[],
        subtotal="0.00",
        discount_percent="0.0",
        discount_amount="0.00",
        gst_rate="18.0",
        gst_amount="0.00",
        tax_amount="0.00",
        total_amount="0.00",
        paid_amount="0.00",
        balance_amount="0.00",
        notes="Test Notes",
    )
    
    # Assert hospital name replaces hardcoded INVOICE
    assert "City Care Super Speciality Hospital" in html
    assert '<div class="invoice-title">INVOICE</div>' not in html
    
    # Assert compact label widths are used instead of excessive 35% and 45% widths
    assert 'width: 35%' not in html
    assert 'width: 45%' not in html
    assert 'width: 55px' in html
    assert 'width: 110px' in html


def test_invoice_template_fallback_hospital_name():
    template = env.get_template("invoice_template.html")
    html = template.render(
        hospital_name=None,
        invoice_number="BIL-TEST-001",
        patient_name="John Doe",
        patient_phone="-",
        patient_email="-",
        date="2026-10-05",
        status="Paid",
        items=[],
        subtotal="0.00",
        discount_percent="0.0",
        discount_amount="0.00",
        gst_rate="0.0",
        gst_amount="0.00",
        tax_amount="0.00",
        total_amount="0.00",
        paid_amount="0.00",
        balance_amount="0.00",
        notes="",
    )
    assert "NexaCare Hospital" in html
    assert '<div class="invoice-title">INVOICE</div>' not in html


@pytest.mark.asyncio
async def test_generate_invoice_pdf_success():
    data = {
        "hospital_name": "City Care Super Speciality Hospital",
        "patient_name": "Yogesh Rahane",
        "patient_phone": "+917898789846",
        "patient_email": "yogesh@user.com",
        "date": "2026-10-05",
        "items": [],
        "subtotal": "100.00",
        "discount_percent": "0.0",
        "discount_amount": "0.00",
        "gst_rate": "18.0",
        "gst_amount": "18.00",
        "tax_amount": "18.00",
        "total_amount": "118.00",
        "paid_amount": "118.00",
        "balance_amount": "0.00",
        "status": "Paid",
        "notes": "Thank you",
    }
    file_path, pdf_bytes = await generate_invoice_pdf("BIL-TEST-PDF", data)
    assert len(pdf_bytes) > 0
    assert pdf_bytes.startswith(b"%PDF")
