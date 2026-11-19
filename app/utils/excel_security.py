from datetime import date, datetime, time
from typing import Any


class TrustedFormula(str):
    """Marker class for trusted, application-generated spreadsheet formulas that should not be sanitized."""
    pass


def sanitize_excel_cell(val: Any) -> Any:
    """
    Sanitizes spreadsheet cell values against CSV/Excel Formula Injection (CWE-1236).

    Rules:
    - None returns empty string or None.
    - Native numbers (int, float), booleans, dates, and times are preserved as-is.
    - Instances of TrustedFormula are preserved as-is.
    - Strings starting with formula triggers ('=', '+', '-', '@', '\\t', '\\r', '\\n'),
      or with leading whitespace followed by formula triggers, are sanitized by prepending a single quote (').
    - Legitimate signed numeric strings (e.g. "-100", "+50.25") are safely preserved.
    """
    if val is None:
        return ""
    if isinstance(val, (int, float, bool, date, datetime, time)):
        return val
    if isinstance(val, TrustedFormula):
        return str(val)

    s = str(val)
    if not s:
        return ""

    stripped = s.lstrip(" \t\r\n")
    if stripped and stripped[0] in ("=", "+", "-", "@", "|", "%", ";"):
        # Check if it is a legitimate signed number
        try:
            float(stripped)
            return val
        except (ValueError, TypeError):
            return f"'{s}"

    # Also neutralize leading raw control characters
    if s[0] in ("\t", "\r", "\n"):
        return f"'{s}"

    return s


def sanitize_excel_row(row: list | tuple) -> list:
    """Sanitizes an entire row for openpyxl workbook append."""
    return [sanitize_excel_cell(c) for c in row]
