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


def resolve_logo_as_data_uri(logo_path: str | None) -> str | None:
    """
    Converts a local image path or existing data URI to a Base64 Data URI.
    Supports PNG, JPG, and JPEG files.
    Verifies that the file exists before reading.
    Returns None if logo_path is missing, invalid, or file does not exist.
    """
    if not logo_path or not isinstance(logo_path, str):
        return None

    stripped_path = logo_path.strip()
    if not stripped_path:
        return None

    if stripped_path.startswith("data:"):
        return stripped_path

    import base64
    import mimetypes
    import os

    norm_path = stripped_path.lstrip("/\\")
    candidates = [
        stripped_path,
        norm_path,
        os.path.join("app", norm_path),
        os.path.abspath(stripped_path),
        os.path.abspath(norm_path),
        os.path.abspath(os.path.join("app", norm_path)),
    ]
    resolved = None
    for c in candidates:
        if os.path.exists(c) and os.path.isfile(c):
            resolved = c
            break

    if not resolved:
        return None

    mime_type, _ = mimetypes.guess_type(resolved)
    if not mime_type:
        ext = os.path.splitext(resolved)[1].lower()
        if ext in (".jpg", ".jpeg"):
            mime_type = "image/jpeg"
        elif ext == ".png":
            mime_type = "image/png"
        else:
            mime_type = "image/png"

    try:
        with open(resolved, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")
        return f"data:{mime_type};base64,{b64_data}"
    except Exception as exc:
        logger.warning("Failed to encode hospital logo from %s: %s", resolved, exc)
        return None


async def generate_invoice_html(bill_number: str, data: dict) -> str:
    template = env.get_template("invoice_template.html")
    render_data = dict(data)
    render_data["hospital_logo"] = resolve_logo_as_data_uri(render_data.get("hospital_logo"))
    html = template.render(invoice_number=bill_number, **render_data)
    output_dir = _ensure_output_dir("invoices")
    file_path = output_dir / f"{bill_number}.html"
    file_path.write_text(html, encoding="utf-8")
    logger.info("Invoice generated: %s", file_path)
    return str(file_path)


async def generate_invoice_pdf(bill_number: str, data: dict) -> tuple[str, bytes]:
    template = env.get_template("invoice_template.html")
    render_data = dict(data)
    render_data["hospital_logo"] = resolve_logo_as_data_uri(render_data.get("hospital_logo"))
    html = template.render(invoice_number=bill_number, **render_data)
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
    data["hospital_logo"] = resolve_logo_as_data_uri(data.get("hospital_logo"))

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


async def generate_analytics_report_html(report_number: str, data: dict) -> str:
    template = env.get_template("analytics_export_template.html")
    report_title = data.get("title", "Analytics Report")
    report_type = data.get("report_type", "analytics")

    # Process hospital logo if local file path
    data["hospital_logo"] = resolve_logo_as_data_uri(data.get("hospital_logo"))

    raw_rows = data.get("rows", [])
    summary_cards = []
    tables = []
    generic_columns = []
    generic_rows = []

    if raw_rows and isinstance(raw_rows[0], dict):
        first_dict = raw_rows[0]
        has_analytics_structure = any(isinstance(v, list) for v in first_dict.values())
        if has_analytics_structure or len(raw_rows) == 1:
            for k, v in first_dict.items():
                title_k = k.replace("_", " ").title()
                if isinstance(v, (int, float, str)) or v is None:
                    if isinstance(v, float):
                        if "revenue" in k.lower() or "amount" in k.lower():
                            val_str = f"₹ {v:,.2f}"
                        else:
                            val_str = f"{v:,.2f}".rstrip("0").rstrip(".") if "." in f"{v:,.2f}" else f"{v:,.2f}"
                    elif isinstance(v, int):
                        val_str = f"{v:,}"
                    else:
                        val_str = str(v) if v is not None else "-"
                    summary_cards.append({"label": title_k, "value": val_str})

                elif isinstance(v, list) and v:
                    if isinstance(v[0], dict):
                        if "label" in v[0] and "value" in v[0]:
                            col1_name = "Metric / Category"
                            k_lower = k.lower()
                            if "gender" in k_lower:
                                col1_name = "Gender"
                            elif "trend" in k_lower or "daily" in k_lower or "date" in k_lower:
                                col1_name = "Date / Period"
                            elif "payment" in k_lower or "method" in k_lower:
                                col1_name = "Payment Method"
                            elif "department" in k_lower:
                                col1_name = "Department"
                            elif "status" in k_lower:
                                col1_name = "Status"
                            elif "availability" in k_lower:
                                col1_name = "Availability"

                            col2_name = "Amount" if ("revenue" in k_lower or "amount" in k_lower) else "Count / Total"

                            tbl_rows = []
                            for item in v:
                                lbl = str(item.get("label") or "-")
                                val = item.get("value")
                                if isinstance(val, float) and ("revenue" in k_lower or "amount" in k_lower):
                                    v_str = f"₹ {val:,.2f}"
                                elif isinstance(val, (int, float)):
                                    v_str = f"{val:,.0f}" if float(val).is_integer() else f"{val:,.2f}"
                                else:
                                    v_str = str(val or "-")
                                tbl_rows.append([lbl, v_str])

                            tables.append({
                                "title": title_k,
                                "columns": [col1_name, col2_name],
                                "rows": tbl_rows
                            })
                        elif "name" in v[0] and "data" in v[0]:
                            for series in v:
                                s_name = series.get("name") or title_k
                                s_data = series.get("data") or []
                                s_rows = []
                                for dp in s_data:
                                    if isinstance(dp, dict):
                                        s_rows.append([str(dp.get("label", "-")), str(dp.get("value", "-"))])
                                if s_rows:
                                    tables.append({
                                        "title": s_name,
                                        "columns": ["Period / Label", "Value"],
                                        "rows": s_rows
                                    })
                        else:
                            cols = [ck.replace("_", " ").title() for ck in v[0].keys()]
                            tbl_rows = []
                            for item in v:
                                tbl_rows.append([format_cell_value(item.get(ck)) for ck in v[0].keys()])
                            tables.append({
                                "title": title_k,
                                "columns": cols,
                                "rows": tbl_rows
                            })
        else:
            keys = list(first_dict.keys())
            generic_columns = [k.replace("_", " ").title() for k in keys]
            for r in raw_rows:
                generic_rows.append([format_cell_value(r.get(k)) for k in keys])
    elif raw_rows:
        for r in raw_rows:
            if isinstance(r, (list, tuple)):
                generic_rows.append([format_cell_value(cell) for cell in r])
            else:
                generic_rows.append([format_cell_value(r)])

    render_context = dict(data)
    render_context["report_number"] = report_number
    render_context["report_type"] = report_type
    render_context["report_title"] = report_title
    render_context["summary_cards"] = summary_cards
    render_context["tables"] = tables
    render_context["generic_columns"] = generic_columns
    render_context["generic_rows"] = generic_rows

    html = template.render(**render_context)

    folder_name = "analytics_reports"
    output_dir = _ensure_output_dir(folder_name)

    try:
        pdf_bytes = await run_in_threadpool(html_to_pdf, html)
        file_path = output_dir / f"{report_number}.pdf"
        file_path.write_bytes(pdf_bytes)
        logger.info("Analytics Report PDF generated: %s", file_path)
    except Exception as exc:
        logger.warning("PDF conversion failed (%s), falling back to HTML", exc)
        file_path = output_dir / f"{report_number}.html"
        file_path.write_text(html, encoding="utf-8")
        logger.info("Analytics Report HTML generated: %s", file_path)

    relative = str(file_path).replace("\\", "/")
    if relative.startswith("app/"):
        relative = relative[len("app"):]
    return relative
