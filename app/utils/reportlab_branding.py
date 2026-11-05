import os
from typing import Any, Optional

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import HRFlowable, Image as RLImage, Paragraph, Spacer, Table, TableStyle

from app.services.branding_resolver_service import HospitalBrandingContext
from app.utils.helpers import utc_now


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas that accumulates pages and renders exact 'Page X of Y'
    along with dynamic hospital identity in the footer.
    """
    def __init__(self, *args, **kwargs):
        self.branding_footer_text = kwargs.pop("branding_footer_text", "NexaCare Hospital")
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_footer(num_pages)
            super().showPage()
        super().save()

    def draw_footer(self, page_count: int):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))

        # Footer divider line
        page_width, _ = self._pagesize
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(30, 28, page_width - 30, 28)

        # Left: Hospital Name / Confidential
        left_text = f"{self.branding_footer_text} • Confidential Document"
        self.drawString(30, 16, left_text)

        # Right: Page X of Y
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(page_width - 30, 16, page_text)

        self.restoreState()


def create_reportlab_header_flowables(
    branding: HospitalBrandingContext,
    report_title: str,
    meta_info: Optional[str] = None,
    available_width: float = 540.0,
) -> list:
    """
    Generates a professional Platypus flowable header table featuring the hospital logo,
    hospital name, address/contact details, report title, and metadata.
    """
    elements = []
    styles = getSampleStyleSheet()

    hosp_name_style = ParagraphStyle(
        'HospBrandTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=18,
        textColor=colors.HexColor('#1E40AF')
    )

    hosp_sub_style = ParagraphStyle(
        'HospBrandSub',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#4B5563')
    )

    report_title_style = ParagraphStyle(
        'ReportTitleRight',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        alignment=2,  # Right aligned
        textColor=colors.HexColor('#1F2937')
    )

    meta_style = ParagraphStyle(
        'ReportMetaRight',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        alignment=2,
        textColor=colors.HexColor('#6B7280')
    )

    # 1. Prepare Logo flowable
    logo_flowable = None
    if branding.logo_path and os.path.isfile(branding.logo_path):
        try:
            from PIL import Image as PILImage
            with PILImage.open(branding.logo_path) as pil_img:
                w, h = pil_img.size
            if w > 0 and h > 0:
                max_w, max_h = 110.0, 42.0
                aspect = w / h
                if aspect > (max_w / max_h):
                    logo_w = max_w
                    logo_h = max_w / aspect
                else:
                    logo_h = max_h
                    logo_w = max_h * aspect
                logo_flowable = RLImage(branding.logo_path, width=logo_w, height=logo_h)
        except Exception:
            logo_flowable = None

    # 2. Left Identity cell
    left_elements = []
    hosp_name = branding.hospital_name or "NexaCare Hospital"
    left_elements.append(Paragraph(hosp_name, hosp_name_style))

    contact_parts = []
    if branding.hospital_address:
        contact_parts.append(branding.hospital_address)
    if branding.hospital_phone:
        contact_parts.append(f"Ph: {branding.hospital_phone}")
    if branding.hospital_email:
        contact_parts.append(f"Email: {branding.hospital_email}")
    if branding.hospital_website:
        contact_parts.append(f"Web: {branding.hospital_website}")

    if contact_parts:
        left_elements.append(Paragraph(" • ".join(contact_parts), hosp_sub_style))

    # Inner table for Logo + Name
    if logo_flowable:
        id_table_data = [[logo_flowable, left_elements]]
        id_table = Table(id_table_data, colWidths=[120, available_width * 0.55])
        id_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        left_cell = id_table
    else:
        left_cell = left_elements

    # 3. Right Title cell
    right_elements = [Paragraph(report_title, report_title_style)]
    gen_str = f"Generated: {utc_now().strftime('%Y-%m-%d %H:%M UTC')}"
    if meta_info:
        right_elements.append(Paragraph(f"{meta_info}<br/>{gen_str}", meta_style))
    else:
        right_elements.append(Paragraph(gen_str, meta_style))

    # 4. Master Header Table
    header_table = Table([[left_cell, right_elements]], colWidths=[available_width * 0.65, available_width * 0.35])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))

    elements.append(header_table)
    elements.append(Spacer(1, 6))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#1E40AF'), spaceAfter=12))
    return elements
