import re
import io
import csv
import unicodedata
from typing import Any
from datetime import datetime, date
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from app.schemas.report_schema import ExportPayload
from app.core.report_config import HOSPITAL_BRANDING_NAME, REPORT_THEME, DEFAULT_DATE_FORMAT, DEFAULT_DATETIME_FORMAT, DEFAULT_PAGE_SIZE, DEFAULT_MARGINS

class ReportExportService:

    @staticmethod
    def slugify(text: str) -> str:
        text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8')
        text = text.lower()
        text = re.sub(r'[^a-z0-9\-]', '-', text)
        text = re.sub(r'-+', '-', text)
        text = text.strip('-')
        return text if text else "report"

    @staticmethod
    def generate_export_filename(report_name: str, extension: str, generated_at: datetime = None) -> str:
        gen_time = generated_at or datetime.now()
        timestamp = gen_time.strftime('%Y%m%d-%H%M%S')
        safe_name = ReportExportService.slugify(report_name)
        return f"{safe_name}-{timestamp}.{extension}"

    @staticmethod
    def _extract_headers(rows: list[dict]) -> list[str]:
        headers = []
        for row in rows:
            for k in row.keys():
                if k not in headers:
                    headers.append(k)
        return headers

    @staticmethod
    def _sanitize_csv_value(val: Any) -> str:
        if val is None:
            return ""
        s = str(val)
        if s and s[0] in ('=', '+', '-', '@'):
            return f"'{s}"
        return s

    @staticmethod
    def _format_value(val: Any) -> str:
        if val is None:
            return "-"
        if isinstance(val, bool):
            return "Yes" if val else "No"
        if isinstance(val, datetime):
            return val.strftime(DEFAULT_DATETIME_FORMAT)
        if isinstance(val, date):
            return val.strftime(DEFAULT_DATE_FORMAT)
        return str(val)

    @staticmethod
    def _infer_column_alignment(headers: list[str], rows: list[dict]) -> list[str]:
        alignments = []
        for h in headers:
            alignment = 'CENTER' # Default for all-null
            for row in rows:
                val = row.get(h)
                if val is not None and str(val).strip() != "":
                    if isinstance(val, bool) or isinstance(val, (datetime, date)):
                        alignment = 'CENTER'
                    elif isinstance(val, (int, float)):
                        alignment = 'RIGHT'
                    else:
                        s = str(val).strip()
                        if s.endswith('%') or s.startswith('$'):
                            alignment = 'RIGHT'
                        else:
                            alignment = 'LEFT'
                    break
            alignments.append(alignment)
        return alignments

    @staticmethod
    def _calculate_column_widths(headers: list[str], rows: list[dict], available_width: float) -> list[float]:
        num_cols = len(headers)
        if num_cols == 0:
            return []
            
        weights = []
        for h in headers:
            header_len = len(h)
            max_len = 0
            for row in rows:
                val_str = ReportExportService._format_value(row.get(h))
                max_len = max(max_len, len(val_str))
                
            w = (header_len * REPORT_THEME.get('header_weight', 1.5)) + (max_len * REPORT_THEME.get('content_weight', 1.0))
            weights.append(w * REPORT_THEME.get('column_weight_multiplier', 1.0))
            
        total_weight = sum(weights)
        if total_weight == 0:
            return [available_width / num_cols] * num_cols
            
        raw_widths = [(w / total_weight) * available_width for w in weights]
        
        min_w = REPORT_THEME.get('minimum_column_width', 60)
        max_w = available_width * REPORT_THEME.get('maximum_column_width_ratio', 0.4)
        
        final_widths = []
        for w in raw_widths:
            w_clamped = max(min_w, min(max_w, w))
            final_widths.append(w_clamped)
            
        return final_widths

    @staticmethod
    def _write_csv_table(writer, title: str, rows: list[dict]):
        if not rows:
            return
        if title:
            writer.writerow([title])
        
        headers = ReportExportService._extract_headers(rows)
        writer.writerow(headers)
        
        for row in rows:
            sanitized_row = [ReportExportService._sanitize_csv_value(row.get(k)) for k in headers]
            writer.writerow(sanitized_row)
        writer.writerow([])

    @staticmethod
    def export_csv(payload: ExportPayload) -> io.StringIO:
        output = io.StringIO()
        writer = csv.writer(output)
        
        if not payload.summary and not payload.filters and not payload.main_rows and not payload.additional_sections:
            writer.writerow(["Report"])
            writer.writerow(["No data found for this report."])
            output.seek(0)
            return output
        
        if payload.summary:
            writer.writerow(["SUMMARY"])
            for key, val in payload.summary.items():
                writer.writerow([key, ReportExportService._sanitize_csv_value(val)])
            writer.writerow([])
            
        if payload.filters:
            writer.writerow(["FILTERS"])
            for key, val in payload.filters.items():
                writer.writerow([key, ReportExportService._sanitize_csv_value(val)])
            writer.writerow([])

        if payload.main_rows:
            ReportExportService._write_csv_table(writer, payload.main_table_title, payload.main_rows)
            
        for section in payload.additional_sections:
            ReportExportService._write_csv_table(writer, section.title, section.rows)

        output.seek(0)
        return output

    @staticmethod
    def _footer_factory(payload: ExportPayload):
        def footer(canvas, doc):
            canvas.saveState()
            canvas.setFont(REPORT_THEME['font_name_regular'], REPORT_THEME['footer_font_size'])
            footer_text = f"{HOSPITAL_BRANDING_NAME} | Generated: {payload.generated_at.strftime(DEFAULT_DATETIME_FORMAT)} | Page {doc.page}"
            canvas.drawCentredString(DEFAULT_PAGE_SIZE[0] / 2.0, REPORT_THEME['footer_height'], footer_text)
            canvas.restoreState()
        return footer

    @staticmethod
    def _render_table(elements, title, rows, available_width, styles):
        if not rows:
            return
            
        if title:
            bold_style = ParagraphStyle(
                'BoldTitle',
                parent=styles['Normal'],
                fontName=REPORT_THEME['font_name_bold'],
                fontSize=REPORT_THEME['header_font_size'],
                spaceAfter=REPORT_THEME['title_spacing']
            )
            elements.append(Paragraph(f"<b>{title}</b>", bold_style))
            
        headers = ReportExportService._extract_headers(rows)
        data = [headers]
        
        alignments = ReportExportService._infer_column_alignment(headers, rows)
        col_widths = ReportExportService._calculate_column_widths(headers, rows, available_width)
        
        body_style = ParagraphStyle(
            'Body',
            parent=styles['Normal'],
            fontName=REPORT_THEME['font_name_regular'],
            fontSize=REPORT_THEME['body_font_size'],
            spaceAfter=REPORT_THEME['paragraph_spacing']
        )
        
        for row in rows:
            cell_row = []
            for h in headers:
                val = ReportExportService._format_value(row.get(h))
                cell_row.append(Paragraph(val, body_style))
            data.append(cell_row)
            
        table = Table(data, repeatRows=1, colWidths=col_widths)
        ts = [
            ('BACKGROUND', (0, 0), (-1, 0), REPORT_THEME['header_bg_color']),
            ('TEXTCOLOR', (0, 0), (-1, 0), REPORT_THEME['header_text_color']),
            ('FONTNAME', (0, 0), (-1, 0), REPORT_THEME['font_name_bold']),
            ('FONTSIZE', (0, 0), (-1, 0), REPORT_THEME['header_font_size']),
            ('BOTTOMPADDING', (0, 0), (-1, 0), REPORT_THEME['header_padding']),
            ('BACKGROUND', (0, 1), (-1, -1), REPORT_THEME['alt_row_bg_color']),
            ('GRID', (0, 0), (-1, -1), REPORT_THEME['grid_width'], REPORT_THEME['grid_color']),
            ('VALIGN', (0, 0), (-1, -1), 'TOP')
        ]
        for col_idx, align in enumerate(alignments):
            ts.append(('ALIGN', (col_idx, 0), (col_idx, -1), align))
            
        table.setStyle(TableStyle(ts))
        elements.append(table)
        elements.append(Spacer(1, REPORT_THEME['table_spacing']))

    @staticmethod
    def _render_summary(elements, title, data_dict, styles):
        if not data_dict:
            return
        
        bold_style = ParagraphStyle(
            'BoldStyle',
            parent=styles['Normal'],
            fontName=REPORT_THEME['font_name_bold'],
            fontSize=REPORT_THEME['body_font_size'],
            spaceAfter=REPORT_THEME['paragraph_spacing']
        )
        normal_style = ParagraphStyle(
            'NormalStyle',
            parent=styles['Normal'],
            fontName=REPORT_THEME['font_name_regular'],
            fontSize=REPORT_THEME['body_font_size'],
            spaceAfter=REPORT_THEME['paragraph_spacing']
        )
        
        elements.append(Paragraph(f"<b>{title}:</b>", bold_style))
        for k, v in data_dict.items():
            elements.append(Paragraph(f"{k}: {ReportExportService._format_value(v)}", normal_style))
        elements.append(Spacer(1, REPORT_THEME['section_spacing']))

    @staticmethod
    def export_pdf(payload: ExportPayload) -> io.BytesIO:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, 
            pagesize=DEFAULT_PAGE_SIZE, 
            rightMargin=DEFAULT_MARGINS, 
            leftMargin=DEFAULT_MARGINS, 
            topMargin=DEFAULT_MARGINS, 
            bottomMargin=DEFAULT_MARGINS + 20
        )
        
        available_width = DEFAULT_PAGE_SIZE[0] - (2 * DEFAULT_MARGINS)
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'DocTitle',
            parent=styles['Title'],
            fontName=REPORT_THEME['font_name_bold'],
            fontSize=REPORT_THEME['title_font_size'],
            spaceAfter=REPORT_THEME['title_spacing']
        )
        
        elements = []
        
        # Header
        elements.append(Paragraph(HOSPITAL_BRANDING_NAME, title_style))
        elements.append(Paragraph(payload.title, title_style))
        elements.append(Spacer(1, REPORT_THEME['section_spacing']))
        
        normal_style = ParagraphStyle(
            'NormalStyle',
            parent=styles['Normal'],
            fontName=REPORT_THEME['font_name_regular'],
            fontSize=REPORT_THEME['body_font_size'],
            spaceAfter=REPORT_THEME['paragraph_spacing']
        )
        
        elements.append(Paragraph(f"<b>Generated At:</b> {ReportExportService._format_value(payload.generated_at)}", normal_style))
        elements.append(Spacer(1, REPORT_THEME['section_spacing']))
        
        # Filters and Summary
        ReportExportService._render_summary(elements, "Applied Filters", payload.filters, styles)
        ReportExportService._render_summary(elements, "Summary", payload.summary, styles)

        # Tables
        if payload.main_rows:
            ReportExportService._render_table(elements, payload.main_table_title, payload.main_rows, available_width, styles)
            
        for section in payload.additional_sections:
            ReportExportService._render_table(elements, section.title, section.rows, available_width, styles)
            
        footer_cb = ReportExportService._footer_factory(payload)
        doc.build(elements, onFirstPage=footer_cb, onLaterPages=footer_cb)
        buffer.seek(0)
        return buffer
