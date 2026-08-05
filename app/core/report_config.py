from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from app.schemas.report_schema import ReportFormat

HOSPITAL_BRANDING_NAME = "NexaCare Hospital"

REPORT_THEME = {
    "header_bg_color": colors.HexColor("#2C3E50"),
    "header_text_color": colors.whitesmoke,
    "alt_row_bg_color": colors.HexColor("#ECF0F1"),
    "grid_color": colors.black,
    "font_name_bold": "Helvetica-Bold",
    "font_name_regular": "Helvetica",
    "title_font_size": 18,
    "header_font_size": 12,
    "body_font_size": 10,
    "footer_font_size": 9,
    "title_spacing": 12,
    "section_spacing": 16,
    "table_spacing": 12,
    "grid_width": 1,
    "header_padding": 12,
    "footer_height": 15,
    "paragraph_spacing": 6,
    "minimum_column_width": 60,
    "maximum_column_width_ratio": 0.4,
    "column_padding": 12,
    "column_weight_multiplier": 1.0,
    "header_weight": 1.5,
    "content_weight": 1.0
}

REPORT_CONTENT_TYPES = {
    ReportFormat.PDF: "application/pdf",
    ReportFormat.CSV: "text/csv"
}

DEFAULT_DATE_FORMAT = "%Y-%m-%d"
DEFAULT_DATETIME_FORMAT = "%Y-%m-%d %H:%M"
DEFAULT_PAGE_SIZE = landscape(letter)
DEFAULT_MARGINS = 30
