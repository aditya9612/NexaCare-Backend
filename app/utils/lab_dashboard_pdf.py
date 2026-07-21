from datetime import datetime
from jinja2 import Environment, FileSystemLoader

from app.schemas.lab_dashboard_schema import LabDashboardResponse
from app.utils.pdf_generator import html_to_pdf
from app.utils.helpers import utc_now
from fastapi.concurrency import run_in_threadpool

env = Environment(loader=FileSystemLoader("app/templates"))

async def generate_lab_dashboard_pdf(
    data: LabDashboardResponse,
    filter_applied: str,
    date_range: str,
) -> bytes:
    template = env.get_template("lab_dashboard_template.html")
    
    # Format current generated date
    generated_at_str = utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # Prepare template context
    context = data.model_dump()
    context["filter_applied"] = filter_applied
    context["date_range"] = date_range
    context["generated_at"] = generated_at_str
    
    html = template.render(**context)
    pdf_bytes = await run_in_threadpool(html_to_pdf, html)
    return pdf_bytes
