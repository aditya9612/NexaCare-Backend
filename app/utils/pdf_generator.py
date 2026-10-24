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
def html_to_pdf(html_content: str) -> bytes:
    import threading
    import asyncio
    from pathlib import Path
    from playwright.async_api import async_playwright

    pdf_bytes = None
    exc = None

    def worker():
        nonlocal pdf_bytes, exc
        import sys
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        async def _async_pdf():
            font_dir = Path(__file__).resolve().parent.parent / "static" / "fonts"
            
            dejavu_path = (font_dir / "DejaVuSans.ttf").as_posix()
            noto_path = (font_dir / "NotoSansDevanagari-Regular.ttf").as_posix()
            
            font_css = f'''
            <style>
            @font-face {{
                font-family: 'DejaVuSans';
                src: url('file:///{dejavu_path}') format('truetype');
            }}
            @font-face {{
                font-family: 'NotoSansDevanagari';
                src: url('file:///{noto_path}') format('truetype');
            }}
            </style>
            '''
            
            nonlocal html_content
            if '</head>' in html_content:
                html_content = html_content.replace('</head>', font_css + '</head>')
            else:
                html_content = font_css + html_content

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    page = await browser.new_page()
                    await page.set_content(html_content, wait_until='networkidle')
                    
                    pdf_data = await page.pdf(
                        prefer_css_page_size=True,
                        print_background=True
                    )
                    
                    return pdf_data
                finally:
                    await browser.close()

        try:
            pdf_bytes = asyncio.run(_async_pdf())
        except Exception as e:
            exc = e

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    if exc:
        try:
            import io
            from xhtml2pdf import pisa
            result = io.BytesIO()
            pdf = pisa.pisaDocument(io.StringIO(html_content), result)
            if not pdf.err:
                return result.getvalue()
        except Exception:
            pass
        raise Exception("PDF generation failed") from exc
    
    return pdf_bytes


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
    report_type = data.get("title", "Diagnostic Report")
    
    # Process hospital logo if local file path
    logo_path = data.get("hospital_logo")
    if logo_path and isinstance(logo_path, str) and not logo_path.startswith("data:"):
        import os
        import mimetypes
        import base64
        resolved_logo = None
        candidates = [
            logo_path,
            os.path.join("app", logo_path),
            os.path.abspath(logo_path),
            os.path.abspath(os.path.join("app", logo_path)),
        ]
        for c in candidates:
            if os.path.exists(c) and os.path.isfile(c):
                resolved_logo = c
                break
        if resolved_logo:
            mime_type, _ = mimetypes.guess_type(resolved_logo)
            if not mime_type:
                mime_type = "image/png"
            try:
                with open(resolved_logo, "rb") as f:
                    b64_data = base64.b64encode(f.read()).decode("utf-8")
                data["hospital_logo"] = f"data:{mime_type};base64,{b64_data}"
            except Exception:
                pass

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

    render_context = dict(data)
    render_context["report_number"] = report_number
    render_context["report_type"] = report_type
    html = template.render(**render_context)

    # Save folder based on report type
    folder_name = "lab_reports"
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
