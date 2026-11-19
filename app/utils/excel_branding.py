from datetime import datetime
from typing import Optional

from openpyxl.styles import Alignment, Font, PatternFill, Side, Border
from openpyxl.utils import get_column_letter

from app.services.branding_resolver_service import HospitalBrandingContext
from app.utils.excel_security import sanitize_excel_cell
from app.utils.helpers import utc_now


def apply_excel_hospital_header(
    ws,
    branding: HospitalBrandingContext,
    report_title: str = "Report",
    title: Optional[str] = None,
    date_range_label: Optional[str] = None,
    total_records: Optional[int] = None,
) -> int:
    report_title = title or report_title
    """
    Applies professional, tenant-aware hospital branding to the top of an openpyxl worksheet.

    Layout:
    Row 1: Hospital Name (14pt Bold, Brand Blue #1E40AF)
    Row 2: Hospital Contact & Address info (9pt Regular, Gray #4B5563)
    Row 3: Report Name | Generation Timestamp | Period | Record count (9pt Italic, #6B7280)
    Row 4: Blank spacer
    Row 5: Table column headers start here

    Returns:
    int: The row number where table column headers should be placed (5).
    """
    # 1. Hospital Name
    hosp_name = branding.hospital_name or "NexaCare Hospital"
    cell_name = ws.cell(row=1, column=1, value=sanitize_excel_cell(hosp_name))
    cell_name.font = Font(name="Calibri", size=14, bold=True, color="1E40AF")

    # 2. Contact details & address
    contact_text = branding.contact_line or ""
    cell_contact = ws.cell(row=2, column=1, value=sanitize_excel_cell(contact_text))
    cell_contact.font = Font(name="Calibri", size=9, bold=False, color="4B5563")

    # 3. Report metadata
    gen_time = utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")
    meta_parts = [f"Report: {report_title}", f"Generated: {gen_time}"]
    if date_range_label:
        meta_parts.append(f"Period: {date_range_label}")
    if total_records is not None:
        meta_parts.append(f"Total Records: {total_records}")
    meta_text = " | ".join(meta_parts)

    cell_meta = ws.cell(row=3, column=1, value=sanitize_excel_cell(meta_text))
    cell_meta.font = Font(name="Calibri", size=9, italic=True, color="6B7280")

    # Row heights
    ws.row_dimensions[1].height = 24
    ws.row_dimensions[2].height = 18
    ws.row_dimensions[3].height = 18
    ws.row_dimensions[4].height = 10  # Spacer row
    ws.row_dimensions[5].height = 28  # Header row height

    # Print setup: Repeat headers on each page and show grid lines
    try:
        ws.print_title_rows = '5:5'
        ws.sheet_view.showGridLines = True
    except Exception:
        pass

    return 5


def style_excel_header_row(ws, headers: list, header_row_idx: int = 5) -> None:
    """Styles the table header row with professional hospital theme."""
    header_font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1E40AF", end_color="1E40AF", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1"),
    )

    for col_idx, header_title in enumerate(headers, start=1):
        cell = ws.cell(row=header_row_idx, column=col_idx, value=sanitize_excel_cell(header_title))
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border


def auto_fit_columns(ws, min_width: int = 12, max_width: int = 40) -> None:
    """Auto-adjusts worksheet column widths based on maximum string lengths."""
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            # Skip the hospital branding banner rows (rows 1-3) when calculating column width
            if cell.row < 5:
                continue
            val_str = str(cell.value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(min_width, min(max_len + 3, max_width))
