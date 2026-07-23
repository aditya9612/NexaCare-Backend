from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.core.config import settings
from app.core.logger import logger

env = Environment(loader=FileSystemLoader("app/templates"))


def _ensure_output_dir(subdir: str) -> Path:
    path = Path(settings.UPLOAD_DIR) / subdir
    path.mkdir(parents=True, exist_ok=True)
    return path


from fastapi.concurrency import run_in_threadpool
from io import BytesIO
from xhtml2pdf import pisa

def html_to_pdf(html_content: str) -> bytes:
    result = BytesIO()
    pdf = pisa.pisaDocument(BytesIO(html_content.encode("utf-8")), result)
    if not pdf.err:
        return result.getvalue()
    raise Exception("PDF generation failed")


async def generate_invoice_html(bill_number: str, data: dict) -> str:
    template = env.get_template("invoice_template.html")
    html = template.render(invoice_number=bill_number, **data)
    output_dir = _ensure_output_dir("invoices")
    file_path = output_dir / f"{bill_number}.html"
    file_path.write_text(html, encoding="utf-8")
    logger.info("Invoice generated: %s", file_path)
    return str(file_path)


async def generate_invoice_pdf(bill_number: str, data: dict) -> tuple[str, bytes]:
    template = env.get_template("invoice_template.html")
    html = template.render(invoice_number=bill_number, **data)
    pdf_bytes = await run_in_threadpool(html_to_pdf, html)
    output_dir = _ensure_output_dir("invoices")
    file_path = output_dir / f"{bill_number}.pdf"
    file_path.write_bytes(pdf_bytes)
    logger.info("Invoice PDF generated: %s", file_path)
    return str(file_path), pdf_bytes


from typing import Any

def format_cell_value(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, list):
        items = []
        for item in val:
            if isinstance(item, dict):
                if "label" in item and "value" in item:
                    items.append(f"{item['label']}: {item['value']}")
                else:
                    items.append(str(item))
            elif hasattr(item, "label") and hasattr(item, "value"):
                items.append(f"{getattr(item, 'label')}: {getattr(item, 'value')}")
            else:
                items.append(str(item))
        return ", ".join(items)
    if isinstance(val, dict):
        if "label" in val and "value" in val:
            return f"{val['label']}: {val['value']}"
        return ", ".join(f"{k}: {v}" for k, v in val.items())
    return str(val)


async def generate_lab_report_html(report_number: str, data: dict) -> str:
    template = env.get_template("report_template.html")
    report_type = data.get("title", "Lab Report").title()
    
    # Process rows/columns to handle lists of dicts (like model_dump from responses)
    rows = data.get("rows", [])
    columns = data.get("columns", [])
    formatted_rows = []
    
    if rows and isinstance(rows[0], dict):
        keys = list(rows[0].keys())
        columns = [k.replace("_", " ").title() for k in keys]
        for r in rows:
            formatted_rows.append([format_cell_value(r.get(k)) for k in keys])
        data["columns"] = columns
        data["rows"] = formatted_rows
    else:
        for r in rows:
            if isinstance(r, (list, tuple)):
                formatted_rows.append([format_cell_value(cell) for cell in r])
            else:
                formatted_rows.append([format_cell_value(r)])
        data["rows"] = formatted_rows

    html = template.render(report_type=report_type, report_number=report_number, **data)

    # Save folder based on report type
    folder_name = "lab_reports" if report_type == "Lab Report" else "reports"
    output_dir = _ensure_output_dir(folder_name)

    # Try to generate a real PDF, fall back to HTML if it fails
    try:
        pdf_bytes = await run_in_threadpool(html_to_pdf, html)
        file_path = output_dir / f"{report_number}.pdf"
        file_path.write_bytes(pdf_bytes)
        logger.info("Report PDF generated: %s", file_path)
    except Exception as exc:
        logger.warning("PDF conversion failed (%s), falling back to HTML", exc)
        file_path = output_dir / f"{report_number}.html"
        file_path.write_text(html, encoding="utf-8")
        logger.info("Report HTML generated: %s", file_path)

    # Return web-relative path with forward slashes (strip leading 'app' prefix)
    relative = str(file_path).replace("\\", "/")
    if relative.startswith("app/"):
        relative = relative[len("app"):]
    return relative
