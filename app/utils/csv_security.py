from datetime import date, datetime, time
from typing import Any


def sanitize_csv_cell(val: Any) -> Any:
    """
    Sanitizes values written to CSV exports against Spreadsheet Formula Injection (CWE-1236).

    Spreadsheet programs (Microsoft Excel, LibreOffice Calc) interpret cells starting with
    '=', '+', '-', '@', tab, carriage return, or newline as formulas or DDE commands.
    Prepending a single quote (') forces spreadsheet parsers to interpret the cell as a literal text string.
    """
    if val is None:
        return ""
    if isinstance(val, (int, float, bool, date, datetime, time)):
        return val

    s = str(val)
    if not s:
        return ""

    stripped = s.lstrip(" \t\r\n")
    if stripped and stripped[0] in ("=", "+", "-", "@", "|", "%", ";"):
        try:
            float(stripped)
            return val
        except (ValueError, TypeError):
            return f"'{s}"

    if s[0] in ("\t", "\r", "\n"):
        return f"'{s}"

    return s


def sanitize_csv_row(row: list | tuple) -> list:
    """Sanitizes an entire row for CSV writer."""
    return [sanitize_csv_cell(c) for c in row]


def sanitize_csv_dict(row_dict: dict) -> dict:
    """Sanitizes all values in a dictionary for csv.DictWriter."""
    return {k: sanitize_csv_cell(v) for k, v in row_dict.items()}
