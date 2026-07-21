"""
Stage 9 — Structured logging for name extraction pipeline.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger("nexacare.agent.name_extraction")


@dataclass
class ExtractionLogRecord:
    """Structured log payload for a single name extraction run."""

    input_transcript: str
    clean_transcript: str
    language_hint: str
    regex_candidate: str | None = None
    regex_score: float = 0.0
    gemini_output: dict[str, Any] | None = None
    validation_ok: bool = False
    validation_reason: str = ""
    final_output: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    path_used: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def log_extraction(record: ExtractionLogRecord) -> None:
    """Emit a single structured INFO log line for the extraction run."""
    try:
        payload = json.dumps(record.to_dict(), ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        payload = str(record.to_dict())
    logger.info("name_extraction | %s", payload)
