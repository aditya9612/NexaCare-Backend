from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.core.config import settings
from app.core.logger import logger

env = Environment(loader=FileSystemLoader("app/templates"))


def _ensure_output_dir(subdir: str) -> Path:
    path = Path(settings.UPLOAD_DIR) / subdir
    path.mkdir(parents=True, exist_ok=True)
    return path


async def generate_invoice_html(bill_number: str, data: dict) -> str:
    template = env.get_template("invoice_template.html")
    html = template.render(invoice_number=bill_number, **data)
    output_dir = _ensure_output_dir("invoices")
    file_path = output_dir / f"{bill_number}.html"
    file_path.write_text(html, encoding="utf-8")
    logger.info("Invoice generated: %s", file_path)
    return str(file_path)


async def generate_lab_report_html(report_number: str, data: dict) -> str:
    template = env.get_template("report_template.html")
    html = template.render(report_type="Lab Report", report_number=report_number, **data)
    output_dir = _ensure_output_dir("lab_reports")
    file_path = output_dir / f"{report_number}.html"
    file_path.write_text(html, encoding="utf-8")
    logger.info("Lab report generated: %s", file_path)
    return str(file_path)
