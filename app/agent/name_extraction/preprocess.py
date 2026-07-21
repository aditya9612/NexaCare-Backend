"""
Stage 1 — Transcript preprocessing for name extraction.

Normalises Unicode, strips greetings/fillers, deduplicates tokens,
and infers a coarse language hint (en/hi/mr/mixed/unknown).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

LanguageHint = Literal["en", "hi", "mr", "mixed", "unknown"]

# Leading greetings and fillers (EN / HI / MR / transliterated).
_GREETING_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE | re.UNICODE)
    for p in (
        r"^(?:hello|hi|hey|good\s+(?:morning|afternoon|evening)|namaste|namaskar)\b[\s,]*",
        r"^(?:नमस्ते|नमस्कार|हॅलो|हैलो|जी)[\s,]*",
        r"^(?:uh+|um+|aah+|hmm+|er+|ah+)[\s,]*",
    )
]

_FILLER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE | re.UNICODE)
    for p in (
        r"^(?:ji|jee|yes|ok|okay|please|thanks|thank\s+you)\b[\s,]*",
        r"^(?:जी|हाँ|हां|ठीक\s+है|धन्यवाद)[\s,]*",
    )
]

# Devanagari range check.
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

# Hindi vs Marathi cue words for language hinting.
_HINDI_CUES = re.compile(
    r"(?:मेरा|मैं|मेरी|mera|main|meri|naam|हूँ|है)",
    re.IGNORECASE | re.UNICODE,
)
_MARATHI_CUES = re.compile(
    r"(?:माझ|मी|majhe|majha|majhi|naav|aahe|आहे)",
    re.IGNORECASE | re.UNICODE,
)
_LATIN_RE = re.compile(r"[A-Za-z]")


@dataclass
class PreprocessResult:
    """Output of Stage 1 preprocessing."""

    cleaned: str
    language_hint: LanguageHint = "unknown"
    removed_greetings: list[str] = field(default_factory=list)


def _normalize_unicode(text: str) -> str:
    """Apply NFC normalisation and replace smart punctuation."""
    text = unicodedata.normalize("NFC", text)
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": ".",
        "\u00a0": " ",
        "\u200b": "",
        "\ufeff": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _normalize_punctuation(text: str) -> str:
    """Collapse repeated punctuation and trim stray marks."""
    text = re.sub(r"[.!?]{2,}", ".", text)
    text = re.sub(r"[,;]{2,}", ",", text)
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    return text.strip(".,!?; ")


def _strip_leading_patterns(
    text: str, patterns: list[re.Pattern[str]], removed: list[str]
) -> str:
    """Repeatedly strip leading greeting/filler patterns."""
    changed = True
    while changed:
        changed = False
        for pattern in patterns:
            match = pattern.match(text)
            if match:
                removed.append(match.group(0).strip())
                text = text[match.end() :].lstrip()
                changed = True
    return text


def _collapse_duplicate_tokens(text: str) -> str:
    """Remove consecutive duplicate words (STT echo)."""
    tokens = text.split()
    if not tokens:
        return text
    deduped: list[str] = [tokens[0]]
    for token in tokens[1:]:
        if token.lower() != deduped[-1].lower():
            deduped.append(token)
    return " ".join(deduped)


def _detect_language_hint(text: str) -> LanguageHint:
    """Infer coarse language from script and cue words."""
    has_devanagari = bool(_DEVANAGARI_RE.search(text))
    has_latin = bool(_LATIN_RE.search(text))

    if has_devanagari and has_latin:
        return "mixed"

    hi_score = len(_HINDI_CUES.findall(text))
    mr_score = len(_MARATHI_CUES.findall(text))

    if has_devanagari:
        if mr_score > hi_score:
            return "mr"
        if hi_score > mr_score:
            return "hi"
        return "hi"  # default Devanagari to Hindi when ambiguous

    if has_latin:
        if mr_score > hi_score:
            return "mr"
        if hi_score > mr_score:
            return "hi"
        return "en"

    return "unknown"


def preprocess_transcript(raw: str) -> PreprocessResult:
    """
    Clean a raw speech transcript for downstream name extraction.

    Returns cleaned text, language hint, and list of stripped greeting tokens.
    """
    if not raw or not raw.strip():
        return PreprocessResult(cleaned="", language_hint="unknown")

    removed: list[str] = []
    text = _normalize_unicode(raw.strip())
    text = re.sub(r"\s+", " ", text)
    text = _normalize_punctuation(text)

    # Strip leading greetings and fillers (may repeat).
    text = _strip_leading_patterns(text, _GREETING_PATTERNS, removed)
    text = _strip_leading_patterns(text, _FILLER_PATTERNS, removed)

    text = _collapse_duplicate_tokens(text)
    text = text.strip()

    language_hint = _detect_language_hint(text)

    return PreprocessResult(
        cleaned=text,
        language_hint=language_hint,
        removed_greetings=removed,
    )
