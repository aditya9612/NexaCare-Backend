import os
import re
import io
import csv
import unicodedata
from typing import Any
from datetime import datetime, date, timedelta
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from app.schemas.report_schema import ExportPayload
from app.core.report_config import HOSPITAL_BRANDING_NAME, REPORT_THEME, DEFAULT_DATE_FORMAT, DEFAULT_DATETIME_FORMAT, DEFAULT_PAGE_SIZE, DEFAULT_MARGINS

class ReportExportService:

    @classmethod
    def _ensure_font_registered(cls) -> bool:
        font_path = os.path.abspath("app/static/fonts/DejaVuSans.ttf")
        if os.path.exists(font_path) and "DejaVuSans" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("DejaVuSans", font_path))
            registerFontFamily(
                "DejaVuSans",
                normal="DejaVuSans",
                bold="DejaVuSans",
                italic="DejaVuSans",
                boldItalic="DejaVuSans"
            )
            return True
        return "DejaVuSans" in pdfmetrics.getRegisteredFontNames()


    @staticmethod
    def resolve_hospital_logo(logo_path_attr: str | None) -> str | None:
        if not logo_path_attr:
            return None
        raw_path = str(logo_path_attr).strip()
        candidates = [
            raw_path,
            os.path.abspath(raw_path),
            os.path.join(os.getcwd(), raw_path),
            os.path.join("app", raw_path),
            os.path.abspath(os.path.join("app", raw_path)),
        ]
        for cand in candidates:
            if os.path.isfile(cand):
                return os.path.abspath(cand).replace("\\", "/")
        return None

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

    HEADER_LABELS = {
        "invoice_number": "Invoice No.",
        "invoice_date": "Date",
        "patient_name": "Patient",
        "payment_mode": "Payment Mode",
        "subtotal": "Subtotal",
        "discount_amount": "Discount",
        "tax_amount": "Tax",
        "total_amount": "Total",
        "paid_amount": "Paid",
        "status": "Status",
        "total_sales": "Total Sales",
        "total_invoices": "Total Invoices",
        "average_invoice_value": "Average Invoice Value",
        "hospital_id": "Hospital ID",
        "created_at": "Created At",
        "updated_at": "Updated At",
        "name": "Medicine Name",
        "generic_name": "Generic Name",
        "sku": "SKU",
        "batch_number": "Batch No.",
        "category": "Category",
        "unit": "Unit",
        "unit_price": "Unit Price",
        "stock_quantity": "Stock Qty",
        "reorder_level": "Reorder Level",
        "expiry_date": "Expiry Date",
        "total_medicines": "Total Medicines",
        "active_medicines": "Active Medicines",
        "inactive_medicines": "Inactive Medicines",
        "low_stock_medicines": "Low Stock",
        "out_of_stock_medicines": "Out of Stock",
        "total_cost": "Procurement Purchases",
        "gross_profit": "Net Flow (Sales - Purchases)",
        "invoice_count": "Total Invoices",
        "medicine_count": "Active Medicines",
        "expired_medicines": "Expired",
        "expiring_30_days": "Expiring (30 Days)",
        "expiring_60_days": "Expiring (60 Days)",
        "expiring_90_days": "Expiring (90 Days)",
    }

    CURRENCY_KEYS = {
        "subtotal", "discount_amount", "tax_amount", "gst_amount",
        "total_amount", "paid_amount", "total_sales", "total_cost", "average_invoice_value",
        "revenue", "billing_revenue", "pharmacy_revenue", "total_revenue",
        "total_billed_amount", "total_collected_amount", "total_expense_amount",
        "net_cash_flow", "cost", "gross_profit", "unit_price"
    }

    @classmethod
    def _get_header_display_name(cls, key: str) -> str:
        if key in cls.HEADER_LABELS:
            return cls.HEADER_LABELS[key]
        return key.replace('_', ' ').title()

    @classmethod
    def _format_cell_value(cls, key: str, val: Any) -> str:
        if val is None:
            return "-"
        if isinstance(val, bool):
            return "Yes" if val else "No"
        if key.lower() in cls.CURRENCY_KEYS:
            if isinstance(val, (int, float)):
                return f"{float(val):.2f}"
        if isinstance(val, float):
            return f"{val:.2f}"
        if isinstance(val, datetime):
            return val.strftime(DEFAULT_DATETIME_FORMAT)
        if isinstance(val, date):
            return val.strftime(DEFAULT_DATE_FORMAT)
        s = str(val).strip()
        if s.lower() in ("completed", "pending", "cancelled", "active", "inactive"):
            return s.capitalize()
        return s

    @staticmethod
    def _format_value(val: Any) -> str:
        if val is None:
            return "-"
        if isinstance(val, bool):
            return "Yes" if val else "No"
        if isinstance(val, float):
            return f"{val:.2f}"
        if isinstance(val, datetime):
            return val.strftime(DEFAULT_DATETIME_FORMAT)
        if isinstance(val, date):
            return val.strftime(DEFAULT_DATE_FORMAT)
        return str(val)

    @staticmethod
    def _infer_column_alignment(headers: list[str], rows: list[dict]) -> list[str]:
        alignments = []
        for h in headers:
            h_low = h.lower()
            if h_low in ("subtotal", "discount_amount", "tax_amount", "gst_amount", "total_amount", "paid_amount", "amount", "total", "revenue", "price", "discount", "tax", "paid"):
                alignment = 'RIGHT'
            elif h_low in ("invoice_date", "date", "status", "gender"):
                alignment = 'CENTER'
            elif h_low in ("invoice_number", "patient_name", "name", "description", "title", "payment_mode"):
                alignment = 'LEFT'
            else:
                alignment = 'LEFT'
                for row in rows:
                    val = row.get(h)
                    if val is not None and str(val).strip() != "":
                        if isinstance(val, bool) or isinstance(val, (datetime, date)):
                            alignment = 'CENTER'
                        elif isinstance(val, (int, float)):
                            alignment = 'RIGHT'
                        else:
                            alignment = 'LEFT'
                        break
            alignments.append(alignment)
        return alignments

    @staticmethod
    def _calculate_column_widths(headers: list[str], display_headers: list[str], rows: list[dict], available_width: float) -> list[float]:
        num_cols = len(headers)
        if num_cols == 0:
            return []
            
        weights = []
        for h, dh in zip(headers, display_headers):
            header_len = len(dh)
            max_len = 0
            for row in rows:
                val_str = ReportExportService._format_cell_value(h, row.get(h))
                max_len = max(max_len, len(val_str))
                
            mult = 1.0
            if h in ("patient_name", "description", "name", "generic_name"):
                mult = 1.4
            elif h in ("invoice_number", "order_number"):
                mult = 1.2
            elif h in ("invoice_date", "created_at"):
                mult = 1.1
            
            w = (header_len * 1.2 + max_len * 1.0) * mult
            weights.append(max(w, 8.0))
            
        total_weight = sum(weights)
        if total_weight == 0:
            return [available_width / num_cols] * num_cols
            
        raw_widths = [(w / total_weight) * available_width for w in weights]
        
        if num_cols >= 10:
            min_w = 48.0
        elif num_cols >= 7:
            min_w = 55.0
        else:
            min_w = 60.0
            
        clamped_widths = [max(min_w, w) for w in raw_widths]
        
        sum_clamped = sum(clamped_widths)
        if sum_clamped > 0:
            final_widths = [(w / sum_clamped) * available_width for w in clamped_widths]
        else:
            final_widths = [available_width / num_cols] * num_cols
            
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
            footer_hosp = payload.hospital_name or HOSPITAL_BRANDING_NAME
            footer_text = f"{footer_hosp} | Generated: {payload.generated_at.strftime(DEFAULT_DATETIME_FORMAT)} | Page {doc.page}"
            canvas.drawCentredString(DEFAULT_PAGE_SIZE[0] / 2.0, REPORT_THEME['footer_height'], footer_text)
            canvas.restoreState()
        return footer

    @staticmethod
    def _render_summary_bar(elements, summary_metrics: dict, available_width: float, styles):
        if not summary_metrics:
            return
        summary_metric_style = ParagraphStyle(
            'TableSummaryMetric',
            parent=styles['Normal'],
            fontName=REPORT_THEME['font_name_bold'],
            fontSize=8.5,
            leading=11.5,
            alignment=1,
            textColor=REPORT_THEME['header_bg_color'],
            spaceAfter=0
        )
        summary_table_data = [
            [
                Paragraph(f"<b>Total Invoices:</b>  {summary_metrics['total_invoices']}", summary_metric_style),
                Paragraph(f"<b>Total Sales:</b>  {float(summary_metrics['total_sales']):.2f}", summary_metric_style),
                Paragraph(f"<b>Average Invoice Value:</b>  {float(summary_metrics['average_invoice_value']):.2f}", summary_metric_style),
            ]
        ]
        summary_table = Table(summary_table_data, colWidths=[available_width / 3.0] * 3)
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F2F4F4")),
            ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor("#BDC3C7")),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#BDC3C7")),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, REPORT_THEME['section_spacing']))

    @staticmethod
    def _render_inventory_summary_bar(elements, summary_metrics: dict, available_width: float, styles):
        if not summary_metrics:
            return
        summary_metric_style = ParagraphStyle(
            'InventoryTableSummaryMetric',
            parent=styles['Normal'],
            fontName=REPORT_THEME['font_name_bold'],
            fontSize=8.5,
            leading=11.5,
            alignment=1,
            textColor=REPORT_THEME['header_bg_color'],
            spaceAfter=0
        )
        total_meds = summary_metrics.get("total_medicines", 0)
        total_stock = summary_metrics.get("total_stock_quantity", 0)
        low_stock = summary_metrics.get("low_stock_medicines", 0)
        out_of_stock = summary_metrics.get("out_of_stock_medicines", 0)

        summary_table_data = [
            [
                Paragraph(f"<b>Total Medicines:</b>  {total_meds}", summary_metric_style),
                Paragraph(f"<b>Total Stock Qty:</b>  {total_stock}", summary_metric_style),
                Paragraph(f"<b>Low Stock:</b>  {low_stock}", summary_metric_style),
                Paragraph(f"<b>Out of Stock:</b>  {out_of_stock}", summary_metric_style),
            ]
        ]
        summary_table = Table(summary_table_data, colWidths=[available_width / 4.0] * 4)
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F2F4F4")),
            ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor("#BDC3C7")),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#BDC3C7")),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, REPORT_THEME['section_spacing']))

    @staticmethod
    def calculate_expiry_status(exp_date: Any, current_date: date | None = None) -> str:
        if exp_date is None:
            return "-"
        if isinstance(exp_date, datetime):
            exp_date = exp_date.date()
        elif isinstance(exp_date, str):
            try:
                exp_date = date.fromisoformat(exp_date.split("T")[0])
            except Exception:
                return str(exp_date)

        today = current_date or date.today()
        diff_days = (exp_date - today).days

        if diff_days < 0:
            return "Expired"
        if diff_days == 1:
            return "Expiring in 1 Day"
        return f"Expiring in {diff_days} Days"

    @staticmethod
    def _render_expiry_summary_bar(elements, summary_metrics: dict, available_width: float, styles):
        if not summary_metrics:
            return
        summary_metric_style = ParagraphStyle(
            'ExpiryTableSummaryMetric',
            parent=styles['Normal'],
            fontName=REPORT_THEME['font_name_bold'],
            fontSize=8.5,
            leading=11.5,
            alignment=1,
            textColor=REPORT_THEME['header_bg_color'],
            spaceAfter=0
        )
        total_meds = summary_metrics.get("total_medicines")
        if total_meds is None:
            total_meds = summary_metrics.get("total", 0)

        exp30 = summary_metrics.get("expiring_within_30_days")
        if exp30 is None:
            exp30 = summary_metrics.get("expiring_30_days")
        if exp30 is None:
            exp30 = total_meds

        summary_table_data = [
            [
                Paragraph(f"<b>Total Medicines:</b>  {total_meds}", summary_metric_style),
                Paragraph(f"<b>Expiring Within 30 Days:</b>  {exp30}", summary_metric_style),
            ]
        ]
        summary_table = Table(summary_table_data, colWidths=[available_width / 2.0, available_width / 2.0])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F2F4F4")),
            ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor("#BDC3C7")),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#BDC3C7")),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, REPORT_THEME['section_spacing']))

    @staticmethod
    def _render_profit_loss_summary_bar(elements, summary_metrics: dict, available_width: float, styles):
        if not summary_metrics:
            return
        ReportExportService._ensure_font_registered()
        summary_font = "DejaVuSans" if ("DejaVuSans" in pdfmetrics.getRegisteredFontNames()) else REPORT_THEME['font_name_bold']
        summary_metric_style = ParagraphStyle(
            'ProfitLossSummaryMetric',
            parent=styles['Normal'],
            fontName=summary_font,
            fontSize=8.5,
            leading=11.5,
            alignment=1,
            textColor=REPORT_THEME['header_bg_color'],
            spaceAfter=0
        )
        total_sales = float(summary_metrics.get("total_sales", 0.0) or 0.0)
        total_cost = float(summary_metrics.get("total_cost", 0.0) or 0.0)
        procurement = float(summary_metrics.get("procurement_purchases", total_cost) or 0.0)
        cogs = summary_metrics.get("cogs")
        uncosted_sales = summary_metrics.get("uncosted_sales")
        gross_profit = summary_metrics.get("gross_profit")
        gross_margin_pct = summary_metrics.get("gross_margin_percentage")
        invoice_count = summary_metrics.get("invoice_count", 0) or 0
        medicine_count = summary_metrics.get("medicine_count", 0) or 0

        sales_str = f"₹{total_sales:,.2f}"
        procurement_str = f"₹{procurement:,.2f}"

        net_flow_raw = summary_metrics.get("net_flow")
        if net_flow_raw is not None:
            net_flow = float(net_flow_raw)
        else:
            net_flow = round(total_sales - procurement, 2)
        net_flow_str = f"-₹{abs(net_flow):,.2f}" if net_flow < 0 else f"₹{net_flow:,.2f}"

        has_cogs = cogs is not None
        if has_cogs and gross_profit is not None:
            cogs_val = float(cogs)
            cogs_str = f"₹{cogs_val:,.2f}"
            profit_val = float(gross_profit)
            profit_str = f"-₹{abs(profit_val):,.2f}" if profit_val < 0 else f"₹{profit_val:,.2f}"
            margin_str = f"{float(gross_margin_pct):.1f}%" if gross_margin_pct is not None else "N/A"

            summary_table_data = [
                [
                    Paragraph(f"<b>Total Sales:</b>  {sales_str}", summary_metric_style),
                    Paragraph(f"<b>COGS:</b>  {cogs_str}", summary_metric_style),
                    Paragraph(f"<b>Gross Profit:</b>  {profit_str}", summary_metric_style),
                ],
                [
                    Paragraph(f"<b>Gross Margin:</b>  {margin_str}", summary_metric_style),
                    Paragraph(f"<b>Procurement Purchases:</b>  {procurement_str}", summary_metric_style),
                    Paragraph(f"<b>Net Flow (Sales - Purchases):</b>  {net_flow_str}", summary_metric_style),
                ],
                [
                    Paragraph(f"<b>Total Invoices:</b>  {invoice_count}", summary_metric_style),
                    Paragraph(f"<b>Active Medicines:</b>  {medicine_count}", summary_metric_style),
                    Paragraph(f"<b>Uncosted Sales:</b>  ₹{float(uncosted_sales or 0.0):,.2f}", summary_metric_style),
                ]
            ]
        else:
            summary_table_data = [
                [
                    Paragraph(f"<b>Total Sales:</b>  {sales_str}", summary_metric_style),
                    Paragraph(f"<b>Procurement Purchases:</b>  {procurement_str}", summary_metric_style),
                    Paragraph(f"<b>Net Flow (Sales - Purchases):</b>  {net_flow_str}", summary_metric_style),
                ],
                [
                    Paragraph(f"<b>Total Invoices:</b>  {invoice_count}", summary_metric_style),
                    Paragraph(f"<b>Active Medicines:</b>  {medicine_count}", summary_metric_style),
                    Paragraph(f"<b>Gross Margin:</b>  N/A", summary_metric_style),
                ]
            ]
        summary_table = Table(summary_table_data, colWidths=[available_width / 3.0] * 3)
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F2F4F4")),
            ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor("#BDC3C7")),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#BDC3C7")),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, REPORT_THEME['section_spacing']))

    @staticmethod
    def _render_table(elements, title, rows, available_width, styles, summary_metrics: dict = None):
        is_pharmacy_sales = bool(
            (title and "Pharmacy Sales" in title) or (
                rows and "invoice_number" in ReportExportService._extract_headers(rows)
            )
        )
        is_pharmacy_expiry = bool(
            not is_pharmacy_sales and (
                (title and "Pharmacy Expiry" in title) or (
                    rows and "expiry_date" in ReportExportService._extract_headers(rows) and "reorder_level" not in ReportExportService._extract_headers(rows)
                )
            )
        )
        is_pharmacy_inventory = bool(
            not is_pharmacy_sales and not is_pharmacy_expiry and (
                (title and "Pharmacy Inventory" in title) or (
                    rows and any(k in ReportExportService._extract_headers(rows) for k in ("reorder_level", "inventory_value", "stock_quantity"))
                )
            )
        )
        is_pharmacy_profit_loss = bool(
            not is_pharmacy_sales and not is_pharmacy_expiry and not is_pharmacy_inventory and (
                (title and ("Profit & Loss" in title or "Profit and Loss" in title)) or (
                    rows and {"total_sales", "total_cost", "gross_profit"}.issubset(ReportExportService._extract_headers(rows))
                )
            )
        )
        if not rows and not is_pharmacy_sales and not is_pharmacy_inventory and not is_pharmacy_expiry and not is_pharmacy_profit_loss:
            return

        if is_pharmacy_sales:
            total_invoices = len(rows) if rows else 0
            sum_total = sum(float(r.get("total_sales") or r.get("total_amount") or 0.0) for r in rows) if rows else 0.0
            avg_invoice_val = round(sum_total / total_invoices, 2) if total_invoices > 0 else 0.0

            metrics = {
                "total_invoices": total_invoices,
                "total_sales": sum_total,
                "average_invoice_value": avg_invoice_val,
            }
            if summary_metrics:
                if summary_metrics.get("total_invoices") is not None:
                    metrics["total_invoices"] = summary_metrics["total_invoices"]
                if summary_metrics.get("total_sales") is not None:
                    metrics["total_sales"] = float(summary_metrics["total_sales"])
                if summary_metrics.get("average_invoice_value") is not None:
                    metrics["average_invoice_value"] = float(summary_metrics["average_invoice_value"])

            ReportExportService._render_summary_bar(elements, metrics, available_width, styles)

        elif is_pharmacy_inventory:
            total_meds = len(rows) if rows else 0
            total_stock = sum(int(r.get("stock_quantity") or 0) for r in rows) if rows else 0
            low_stock = sum(1 for r in rows if 0 < int(r.get("stock_quantity") or 0) <= int(r.get("reorder_level") or 0)) if rows else 0
            out_of_stock = sum(1 for r in rows if int(r.get("stock_quantity") or 0) <= 0) if rows else 0

            metrics = {
                "total_medicines": total_meds,
                "total_stock_quantity": total_stock,
                "low_stock_medicines": low_stock,
                "out_of_stock_medicines": out_of_stock,
            }
            if summary_metrics:
                if summary_metrics.get("total_medicines") is not None:
                    metrics["total_medicines"] = summary_metrics["total_medicines"]
                if summary_metrics.get("total_stock_quantity") is not None:
                    metrics["total_stock_quantity"] = summary_metrics["total_stock_quantity"]
                if summary_metrics.get("low_stock_medicines") is not None:
                    metrics["low_stock_medicines"] = summary_metrics["low_stock_medicines"]
                if summary_metrics.get("out_of_stock_medicines") is not None:
                    metrics["out_of_stock_medicines"] = summary_metrics["out_of_stock_medicines"]

            ReportExportService._render_inventory_summary_bar(elements, metrics, available_width, styles)

        elif is_pharmacy_expiry:
            table_record_count = len(rows) if rows else 0

            if rows:
                total_meds = table_record_count
                exp30 = table_record_count
                for row in rows:
                    if not row.get("status") and row.get("expiry_date"):
                        row["status"] = ReportExportService.calculate_expiry_status(row.get("expiry_date"))
            else:
                total_meds = summary_metrics.get("total_medicines", 0) if summary_metrics else 0
                exp30 = (
                    summary_metrics.get("expiring_within_30_days")
                    if summary_metrics and summary_metrics.get("expiring_within_30_days") is not None
                    else (summary_metrics.get("expiring_30_days", 0) if summary_metrics else 0)
                )

            metrics = {
                "total_medicines": total_meds,
                "expiring_within_30_days": exp30,
                "expiring_30_days": exp30,
            }

            ReportExportService._render_expiry_summary_bar(elements, metrics, available_width, styles)

        elif is_pharmacy_profit_loss:
            row_data = rows[0] if rows else {}
            src = summary_metrics or row_data
            metrics = {
                "total_sales": src.get("total_sales", 0.0),
                "total_cost": src.get("total_cost", 0.0),
                "procurement_purchases": src.get("procurement_purchases", src.get("total_cost", 0.0)),
                "net_flow": src.get("net_flow"),
                "costed_sales": src.get("costed_sales"),
                "uncosted_sales": src.get("uncosted_sales"),
                "cogs": src.get("cogs"),
                "gross_profit": src.get("gross_profit"),
                "gross_margin_percentage": src.get("gross_margin_percentage"),
                "invoice_count": src.get("invoice_count", 0),
                "medicine_count": src.get("medicine_count", 0),
            }
            ReportExportService._render_profit_loss_summary_bar(elements, metrics, available_width, styles)

        if title:
            bold_style = ParagraphStyle(
                'BoldTitle',
                parent=styles['Normal'],
                fontName=REPORT_THEME['font_name_bold'],
                fontSize=REPORT_THEME['header_font_size'],
                spaceAfter=REPORT_THEME['title_spacing']
            )
            elements.append(Paragraph(f"<b>{title}</b>", bold_style))
            
        if is_pharmacy_sales:
            preferred_cols = [
                ("invoice_number", "Invoice No.", "LEFT"),
                ("invoice_date", "Date", "CENTER"),
                ("patient_name", "Patient", "LEFT"),
                ("payment_mode", "Payment Mode", "LEFT"),
                ("subtotal", "Subtotal", "RIGHT"),
                ("discount_amount", "Discount", "RIGHT"),
                ("tax_amount", "Tax", "RIGHT"),
                ("total_sales", "Total Sales", "RIGHT"),
                ("paid_amount", "Paid", "RIGHT"),
                ("status", "Status", "CENTER"),
            ]
            headers = [k for k, _, _ in preferred_cols]
            display_headers = [label for _, label, _ in preferred_cols]
            alignments = [align for _, _, align in preferred_cols]

            if rows:
                raw_headers = ReportExportService._extract_headers(rows)
                # If total_amount exists but not total_sales in raw_headers, map total_sales to total_amount
                if "total_amount" in raw_headers and "total_sales" not in raw_headers:
                    idx = headers.index("total_sales")
                    headers[idx] = "total_amount"

                excluded = {"id", "patient_id", "total_amount", "total_sales"} | set(headers)
                extra = [k for k in raw_headers if k not in excluded]
                if extra:
                    headers.extend(extra)
                    display_headers.extend([ReportExportService._get_header_display_name(k) for k in extra])
                    alignments.extend(["LEFT"] * len(extra))
        elif is_pharmacy_inventory:
            preferred_cols = [
                ("name", "Medicine Name", "LEFT"),
                ("category", "Category", "LEFT"),
                ("sku", "SKU", "CENTER"),
                ("batch_number", "Batch No.", "CENTER"),
                ("unit", "Unit", "CENTER"),
                ("unit_price", "Unit Price", "RIGHT"),
                ("stock_quantity", "Stock Qty", "RIGHT"),
                ("reorder_level", "Reorder Level", "RIGHT"),
                ("expiry_date", "Expiry Date", "CENTER"),
                ("status", "Status", "CENTER"),
            ]
            headers = [k for k, _, _ in preferred_cols]
            display_headers = [label for _, label, _ in preferred_cols]
            alignments = [align for _, _, align in preferred_cols]

            if rows:
                raw_headers = ReportExportService._extract_headers(rows)
                if "generic_name" in raw_headers and any(r.get("generic_name") for r in rows):
                    headers.insert(1, "generic_name")
                    display_headers.insert(1, "Generic Name")
                    alignments.insert(1, "LEFT")

                excluded = {"id", "generic_name"} | set(headers)
                extra = [k for k in raw_headers if k not in excluded]
                if extra:
                    headers.extend(extra)
                    display_headers.extend([ReportExportService._get_header_display_name(k) for k in extra])
                    alignments.extend(["LEFT"] * len(extra))
        elif is_pharmacy_expiry:
            preferred_cols = [
                ("name", "Medicine Name", "LEFT"),
                ("category", "Category", "LEFT"),
                ("batch_number", "Batch No.", "CENTER"),
                ("unit", "Unit", "CENTER"),
                ("stock_quantity", "Stock Qty", "RIGHT"),
                ("expiry_date", "Expiry Date", "CENTER"),
                ("status", "Expiry Status", "CENTER"),
            ]
            headers = [k for k, _, _ in preferred_cols]
            display_headers = [label for _, label, _ in preferred_cols]
            alignments = [align for _, _, align in preferred_cols]

            if rows:
                raw_headers = ReportExportService._extract_headers(rows)
                if "generic_name" in raw_headers and any(r.get("generic_name") for r in rows):
                    headers.insert(1, "generic_name")
                    display_headers.insert(1, "Generic Name")
                    alignments.insert(1, "LEFT")
                if "sku" in raw_headers and any(r.get("sku") for r in rows):
                    b_idx = headers.index("batch_number") if "batch_number" in headers else len(headers)
                    headers.insert(b_idx, "sku")
                    display_headers.insert(b_idx, "SKU")
                    alignments.insert(b_idx, "CENTER")

                excluded = {"id", "generic_name", "sku"} | set(headers)
                extra = [k for k in raw_headers if k not in excluded]
                if extra:
                    headers.extend(extra)
                    display_headers.extend([ReportExportService._get_header_display_name(k) for k in extra])
                    alignments.extend(["LEFT"] * len(extra))
        elif is_pharmacy_profit_loss:
            has_cogs = any(r.get("cogs") is not None for r in rows) if rows else False
            if has_cogs:
                preferred_cols = [
                    ("total_sales", "Total Sales (₹)", "RIGHT"),
                    ("cogs", "COGS (₹)", "RIGHT"),
                    ("gross_profit", "Gross Profit (₹)", "RIGHT"),
                    ("gross_margin_percentage", "Gross Margin", "CENTER"),
                    ("procurement_purchases", "Procurement Purchases (₹)", "RIGHT"),
                    ("net_flow", "Net Flow (Sales - Purchases) (₹)", "RIGHT"),
                    ("invoice_count", "Total Invoices", "CENTER"),
                    ("medicine_count", "Active Medicines", "CENTER"),
                ]
            else:
                preferred_cols = [
                    ("total_sales", "Total Sales (₹)", "RIGHT"),
                    ("procurement_purchases", "Procurement Purchases (₹)", "RIGHT"),
                    ("net_flow", "Net Flow (Sales - Purchases) (₹)", "RIGHT"),
                    ("invoice_count", "Total Invoices", "CENTER"),
                    ("medicine_count", "Active Medicines", "CENTER"),
                ]
            headers = [k for k, _, _ in preferred_cols]
            display_headers = [label for _, label, _ in preferred_cols]
            alignments = [align for _, _, align in preferred_cols]
        else:
            headers = ReportExportService._extract_headers(rows)
            display_headers = [ReportExportService._get_header_display_name(k) for k in headers]
            alignments = ReportExportService._infer_column_alignment(headers, rows)
            
        col_widths = ReportExportService._calculate_column_widths(headers, display_headers, rows or [], available_width)
        
        header_font_size = REPORT_THEME.get('table_header_font_size', 8.5)
        body_font_size = REPORT_THEME.get('table_body_font_size', 8.0)
        
        # Build header row as Paragraphs so headings never overlap
        header_row = []
        for dh, align in zip(display_headers, alignments):
            align_code = 2 if align == 'RIGHT' else (1 if align == 'CENTER' else 0)
            use_dejavu_h = ("₹" in str(dh)) and ("DejaVuSans" in pdfmetrics.getRegisteredFontNames())
            h_style = ParagraphStyle(
                f'TH_{align}_{"dj" if use_dejavu_h else "std"}',
                parent=styles['Normal'],
                fontName="DejaVuSans" if use_dejavu_h else REPORT_THEME['font_name_bold'],
                fontSize=header_font_size,
                leading=header_font_size + 2.0,
                textColor=REPORT_THEME['header_text_color'],
                alignment=align_code,
                spaceAfter=0
            )
            header_row.append(Paragraph(f"<b>{dh}</b>", h_style))
        data = [header_row]
        
        # Build data rows with Paragraph cells
        if rows:
            for row in rows:
                cell_row = []
                for h, align in zip(headers, alignments):
                    if is_pharmacy_profit_loss and h in (
                        "total_sales", "total_cost", "gross_profit", "cogs", 
                        "procurement_purchases", "costed_sales", "uncosted_sales", "net_flow"
                    ):
                        if h == "net_flow":
                            net_raw = row.get("net_flow")
                            if net_raw is not None:
                                val_num = float(net_raw)
                            else:
                                s = float(row.get("total_sales") or 0.0)
                                p = float(row.get("procurement_purchases") if row.get("procurement_purchases") is not None else (row.get("total_cost") or 0.0))
                                val_num = round(s - p, 2)
                            val_str = f"-₹{abs(val_num):,.2f}" if val_num < 0 else f"₹{val_num:,.2f}"
                        elif h in ("cogs", "gross_profit"):
                            raw_val = row.get(h)
                            if raw_val is None:
                                val_str = "N/A"
                            else:
                                val_num = float(raw_val)
                                val_str = f"-₹{abs(val_num):,.2f}" if val_num < 0 else f"₹{val_num:,.2f}"
                        elif h in ("procurement_purchases", "total_cost"):
                            raw_val = row.get("procurement_purchases")
                            if raw_val is None:
                                raw_val = row.get("total_cost") or 0.0
                            val_num = float(raw_val)
                            val_str = f"-₹{abs(val_num):,.2f}" if val_num < 0 else f"₹{val_num:,.2f}"
                        else:
                            val_num = float(row.get(h) or 0.0)
                            val_str = f"-₹{abs(val_num):,.2f}" if val_num < 0 else f"₹{val_num:,.2f}"
                    elif is_pharmacy_profit_loss and h == "gross_margin_percentage":
                        val_m = row.get(h)
                        val_str = f"{float(val_m):.1f}%" if val_m is not None else "N/A"
                    else:
                        val_str = ReportExportService._format_cell_value(h, row.get(h))
                    align_code = 2 if align == 'RIGHT' else (1 if align == 'CENTER' else 0)
                    use_dejavu_b = ("₹" in str(val_str)) and ("DejaVuSans" in pdfmetrics.getRegisteredFontNames())
                    b_style = ParagraphStyle(
                        f'TD_{align}_{"dj" if use_dejavu_b else "std"}',
                        parent=styles['Normal'],
                        fontName="DejaVuSans" if use_dejavu_b else REPORT_THEME['font_name_regular'],
                        fontSize=body_font_size,
                        leading=body_font_size + 2.0,
                        alignment=align_code,
                        spaceAfter=0
                    )
                    cell_row.append(Paragraph(val_str, b_style))
                data.append(cell_row)
        else:
            if is_pharmacy_expiry:
                empty_msg = "<i>No pharmacy expiry records found.</i>"
            elif is_pharmacy_inventory:
                empty_msg = "<i>No pharmacy inventory records found.</i>"
            else:
                empty_msg = "<i>No pharmacy sales records found for the selected period.</i>"
            empty_style = ParagraphStyle(
                'EmptySalesRow',
                parent=styles['Normal'],
                fontName=REPORT_THEME['font_name_regular'],
                fontSize=body_font_size,
                leading=body_font_size + 2.0,
                alignment=1,
                spaceAfter=0
            )
            empty_row = [Paragraph(empty_msg, empty_style)] + [
                Paragraph("", empty_style) for _ in range(len(headers) - 1)
            ]
            data.append(empty_row)

        # If this is a pharmacy sales, inventory, or expiry table, append a summary Total row at the end
        has_summary_row = False
        summary_metrics = None
        if is_pharmacy_sales:
            has_summary_row = True
            total_invoices = len(rows) if rows else 0
            sum_subtotal = sum(float(r.get("subtotal") or 0.0) for r in rows) if rows else 0.0
            sum_discount = sum(float(r.get("discount_amount") or 0.0) for r in rows) if rows else 0.0
            sum_tax = sum(float(r.get("tax_amount") or 0.0) for r in rows) if rows else 0.0
            sum_total = sum(float(r.get("total_sales") or r.get("total_amount") or 0.0) for r in rows) if rows else 0.0
            sum_paid = sum(float(r.get("paid_amount") or 0.0) for r in rows) if rows else 0.0
            avg_invoice_val = round(sum_total / total_invoices, 2) if total_invoices > 0 else 0.0

            summary_metrics = {
                "total_invoices": total_invoices,
                "total_sales": sum_total,
                "average_invoice_value": avg_invoice_val,
            }

            footer_row = []
            for h, align in zip(headers, alignments):
                align_code = 2 if align == 'RIGHT' else (1 if align == 'CENTER' else 0)
                if h == headers[0]:
                    val_str = f"<b>Total ({total_invoices} Invoices)</b>"
                elif h == "subtotal":
                    val_str = f"<b>{sum_subtotal:.2f}</b>"
                elif h == "discount_amount":
                    val_str = f"<b>{sum_discount:.2f}</b>"
                elif h == "tax_amount":
                    val_str = f"<b>{sum_tax:.2f}</b>"
                elif h in ("total_sales", "total_amount"):
                    val_str = f"<b>{sum_total:.2f}</b>"
                elif h == "paid_amount":
                    val_str = f"<b>{sum_paid:.2f}</b>"
                else:
                    val_str = ""

                f_style = ParagraphStyle(
                    f'TF_{align}',
                    parent=styles['Normal'],
                    fontName=REPORT_THEME['font_name_bold'],
                    fontSize=body_font_size,
                    leading=body_font_size + 2.0,
                    alignment=align_code,
                    spaceAfter=0
                )
                footer_row.append(Paragraph(val_str, f_style))
            data.append(footer_row)
        elif is_pharmacy_inventory:
            has_summary_row = True
            total_meds = len(rows) if rows else 0
            total_stock = sum(int(r.get("stock_quantity") or 0) for r in rows) if rows else 0

            footer_row = []
            for h, align in zip(headers, alignments):
                align_code = 2 if align == 'RIGHT' else (1 if align == 'CENTER' else 0)
                if h == headers[0]:
                    val_str = f"<b>Total ({total_meds} Medicines)</b>"
                elif h == "stock_quantity":
                    val_str = f"<b>{total_stock}</b>"
                else:
                    val_str = ""

                f_style = ParagraphStyle(
                    f'TF_Inv_{align}',
                    parent=styles['Normal'],
                    fontName=REPORT_THEME['font_name_bold'],
                    fontSize=body_font_size,
                    leading=body_font_size + 2.0,
                    alignment=align_code,
                    spaceAfter=0
                )
                footer_row.append(Paragraph(val_str, f_style))
            data.append(footer_row)
        elif is_pharmacy_expiry:
            has_summary_row = True
            total_meds = len(rows) if rows else 0
            total_stock = sum(int(r.get("stock_quantity") or 0) for r in rows) if rows else 0

            footer_row = []
            for h, align in zip(headers, alignments):
                align_code = 2 if align == 'RIGHT' else (1 if align == 'CENTER' else 0)
                if h == headers[0]:
                    val_str = f"<b>Total ({total_meds} Medicines)</b>"
                elif h == "stock_quantity":
                    val_str = f"<b>{total_stock}</b>"
                else:
                    val_str = ""

                f_style = ParagraphStyle(
                    f'TF_Exp_{align}',
                    parent=styles['Normal'],
                    fontName=REPORT_THEME['font_name_bold'],
                    fontSize=body_font_size,
                    leading=body_font_size + 2.0,
                    alignment=align_code,
                    spaceAfter=0
                )
                footer_row.append(Paragraph(val_str, f_style))
            data.append(footer_row)
            
        table = Table(data, repeatRows=1, colWidths=col_widths)
        padding = REPORT_THEME.get('cell_padding', 4)
        ts = [
            ('BACKGROUND', (0, 0), (-1, 0), REPORT_THEME['header_bg_color']),
            ('TEXTCOLOR', (0, 0), (-1, 0), REPORT_THEME['header_text_color']),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), padding),
            ('BOTTOMPADDING', (0, 0), (-1, -1), padding),
            ('LEFTPADDING', (0, 0), (-1, -1), padding),
            ('RIGHTPADDING', (0, 0), (-1, -1), padding),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, REPORT_THEME['alt_row_bg_color']]),
            ('GRID', (0, 0), (-1, -1), REPORT_THEME.get('grid_width', 0.5), REPORT_THEME.get('grid_color', colors.HexColor("#BDC3C7"))),
        ]
        if not rows and (is_pharmacy_sales or is_pharmacy_inventory or is_pharmacy_expiry):
            ts.append(('SPAN', (0, 1), (-1, 1)))

        if has_summary_row:
            ts.extend([
                ('LINEABOVE', (0, -1), (-1, -1), 1.0, colors.HexColor("#2C3E50")),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#EAEDED")),
            ])
        table.setStyle(TableStyle(ts))
        elements.append(table)
        if is_pharmacy_profit_loss:
            note_font = "DejaVuSans" if ("DejaVuSans" in pdfmetrics.getRegisteredFontNames()) else REPORT_THEME['font_name_regular']
            note_style = ParagraphStyle(
                'ProfitLossFootnote',
                parent=styles['Normal'],
                fontName=note_font,
                fontSize=7.5,
                leading=10.0,
                textColor=colors.HexColor("#7F8C8D"),
                spaceBefore=3,
                spaceAfter=4
            )
            has_cogs = any(r.get("cogs") is not None for r in rows) if rows else (summary_metrics and summary_metrics.get("cogs") is not None)
            if has_cogs:
                uncosted = float((summary_metrics and summary_metrics.get("uncosted_sales")) or (rows and rows[0].get("uncosted_sales")) or 0.0)
                uncosted_note = f" Uncosted Sales of ₹{uncosted:,.2f} are excluded from margin calculations." if uncosted > 0 else ""
                elements.append(Paragraph(
                    f"<i>* Note: Cost of Goods Sold (COGS) is calculated using Moving Weighted Average Cost (WAC) for items sold during the period. Gross Profit = Costed Sales - COGS.{uncosted_note} Net Flow indicates Total Sales minus Total Procurement Purchases in the selected period.</i>",
                    note_style
                ))
            else:
                elements.append(Paragraph(
                    "<i>* Note: Accounting Gross Profit and Profit Margin are not displayed because the medicines sold during this period do not have tracked acquisition costs (Cost of Goods Sold / COGS). Net Flow indicates Total Sales minus Total Procurement Purchases in the selected period.</i>",
                    note_style
                ))
        elements.append(Spacer(1, REPORT_THEME['table_spacing']))

    @staticmethod
    def _render_summary(elements, title, data_dict, styles):
        if not data_dict:
            return
        
        bold_style = ParagraphStyle(
            'SummaryTitle',
            parent=styles['Normal'],
            fontName=REPORT_THEME['font_name_bold'],
            fontSize=10,
            leading=13,
            spaceAfter=6
        )
        elements.append(Paragraph(f"<b>{title}:</b>", bold_style))
        for k, v in data_dict.items():
            display_k = ReportExportService._get_header_display_name(k)
            formatted_val = ReportExportService._format_cell_value(k, v)
            use_dejavu_s = ("₹" in str(formatted_val)) and ("DejaVuSans" in pdfmetrics.getRegisteredFontNames())
            val_style = ParagraphStyle(
                f'SummaryMetric_{"dj" if use_dejavu_s else "std"}',
                parent=styles['Normal'],
                fontName="DejaVuSans" if use_dejavu_s else REPORT_THEME['font_name_regular'],
                fontSize=9,
                leading=12,
                spaceAfter=3
            )
            elements.append(Paragraph(f"<b>{display_k}:</b> {formatted_val}", val_style))
        elements.append(Spacer(1, REPORT_THEME['section_spacing']))

    @staticmethod
    def export_pdf(payload: ExportPayload) -> io.BytesIO:
        ReportExportService._ensure_font_registered()
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
        
        # Header (with optional Hospital Logo)
        hospital_name = payload.hospital_name or HOSPITAL_BRANDING_NAME
        logo_path = payload.hospital_logo
        logo_img_flowable = None
        if logo_path and os.path.isfile(logo_path):
            try:
                from PIL import Image as PILImage
                pil_img = PILImage.open(logo_path)
                w, h = pil_img.size
                if w > 0 and h > 0:
                    max_w, max_h = 90, 42
                    scale = min(max_w / w, max_h / h)
                    logo_w = int(w * scale)
                    logo_h = int(h * scale)
                    logo_img_flowable = RLImage(logo_path, width=logo_w, height=logo_h)
            except Exception:
                logo_img_flowable = None

        if logo_img_flowable:
            title_cell = [
                Paragraph(f"<b>{hospital_name}</b>", title_style),
                Paragraph(f"<b>{payload.title}</b>", title_style),
            ]
            header_table = Table(
                [[logo_img_flowable, title_cell]],
                colWidths=[100, available_width - 100]
            )
            header_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
            elements.append(header_table)
        else:
            elements.append(Paragraph(f"<b>{hospital_name}</b>", title_style))
            elements.append(Paragraph(f"<b>{payload.title}</b>", title_style))

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
        
        # Tables and Summary
        is_pharm_sales = bool(
            (payload.title and "Pharmacy Sales" in payload.title) or 
            (payload.main_table_title and "Pharmacy Sales" in payload.main_table_title) or
            (payload.main_rows and "invoice_number" in ReportExportService._extract_headers(payload.main_rows))
        )
        is_pharm_exp = bool(
            not is_pharm_sales and (
                (payload.title and "Pharmacy Expiry" in payload.title) or 
                (payload.main_table_title and "Pharmacy Expiry" in payload.main_table_title) or
                (payload.summary and any(k in payload.summary for k in ("expired_medicines", "expiring_30_days", "expiring_60_days", "expiring_90_days")))
            )
        )
        is_pharm_inv = bool(
            not is_pharm_sales and not is_pharm_exp and (
                (payload.title and "Pharmacy Inventory" in payload.title) or 
                (payload.main_table_title and "Pharmacy Inventory" in payload.main_table_title) or
                (payload.main_rows and any(k in ReportExportService._extract_headers(payload.main_rows) for k in ("stock_quantity", "reorder_level")))
            )
        )
        is_pharm_pl = bool(
            not is_pharm_sales and not is_pharm_exp and not is_pharm_inv and (
                (payload.title and ("Profit & Loss" in payload.title or "Profit and Loss" in payload.title)) or 
                (payload.main_table_title and ("Profit & Loss" in payload.main_table_title or "Profit and Loss" in payload.main_table_title)) or
                (payload.main_rows and {"total_sales", "total_cost", "gross_profit"}.issubset(ReportExportService._extract_headers(payload.main_rows)))
            )
        )
        is_custom_pharm_report = is_pharm_sales or is_pharm_inv or is_pharm_exp or is_pharm_pl

        # Filters and Summary
        ReportExportService._render_summary(elements, "Applied Filters", payload.filters, styles)
        if not is_custom_pharm_report:
            ReportExportService._render_summary(elements, "Summary", payload.summary, styles)

        if payload.main_rows or is_custom_pharm_report:
            table_title = payload.title if is_custom_pharm_report else payload.main_table_title
            ReportExportService._render_table(
                elements, table_title, payload.main_rows or [], available_width, styles,
                summary_metrics=payload.summary if is_custom_pharm_report else None
            )
            
        for section in payload.additional_sections:
            ReportExportService._render_table(elements, section.title, section.rows, available_width, styles)
            
        footer_cb = ReportExportService._footer_factory(payload)
        doc.build(elements, onFirstPage=footer_cb, onLaterPages=footer_cb)
        buffer.seek(0)
        return buffer
