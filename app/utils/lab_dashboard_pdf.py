from datetime import datetime
from typing import Optional
from jinja2 import Environment, FileSystemLoader
import base64
import mimetypes
import os

from app.schemas.lab_dashboard_schema import LabDashboardResponse
from app.utils.pdf_generator import html_to_pdf
from app.utils.helpers import utc_now
from fastapi.concurrency import run_in_threadpool

env = Environment(loader=FileSystemLoader("app/templates"))

async def generate_lab_dashboard_pdf(
    data: LabDashboardResponse,
    filter_applied: str,
    date_range: str,
    section: str = "all",
    hospital_name: Optional[str] = None,
    hospital_address: Optional[str] = None,
    hospital_phone: Optional[str] = None,
    hospital_email: Optional[str] = None,
    hospital_logo: Optional[str] = None,
) -> bytes:
    template = env.get_template("lab_dashboard_template.html")
    
    # Format current generated date
    generated_at_str = utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    pdf_logo_src = None
    if hospital_logo and os.path.exists(hospital_logo):
        mime_type, _ = mimetypes.guess_type(hospital_logo)
        if not mime_type:
            mime_type = "image/png"
        try:
            with open(hospital_logo, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("utf-8")
            pdf_logo_src = f"data:{mime_type};base64,{b64_data}"
        except Exception:
            pdf_logo_src = None

    # Prepare template context
    context = data.model_dump()
    context["filter_applied"] = filter_applied
    context["date_range"] = date_range
    context["generated_at"] = generated_at_str
    context["section"] = section
    context["hospital_name"] = hospital_name or "NexaCare Hospital"
    context["hospital_address"] = hospital_address
    context["hospital_phone"] = hospital_phone
    context["hospital_email"] = hospital_email
    context["hospital_logo"] = pdf_logo_src
    
    html = template.render(**context)
    pdf_bytes = await run_in_threadpool(html_to_pdf, html)
    return pdf_bytes
