import csv
import uuid
from pathlib import Path
from typing import Any, Dict, List

from app.core.config import settings
from app.core.logger import logger


def generate_excel_report(report_type: str, rows: List[Dict[str, Any]]) -> str:
    """Generate CSV-based Excel-compatible export (no extra dependency)."""
    output_dir = Path(settings.UPLOAD_DIR) / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / f"{report_type}_{uuid.uuid4().hex[:8]}.csv"

    if not rows:
        rows = [{"message": "No data available"}]

    fieldnames = list(rows[0].keys())
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Excel/CSV report generated: %s", file_path)
    return str(file_path)
