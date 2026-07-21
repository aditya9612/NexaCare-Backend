"""
Stage 5 — Post-processing of extracted names.

Trims, removes residual fillers, deduplicates tokens, normalises punctuation,
and applies Title Case only for Latin-script names.
"""

from __future__ import annotations

import re

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

# Residual cue/filler phrases that may leak from LLM or regex.
_RESIDUAL_CUE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE | re.UNICODE)
    for p in (
        r"^(?:my\s+name\s+is|i\s*'?m|i\s+am|this\s+is|call\s+me|myself|name\s+is|speaking)\s+",
        r"^(?:mera\s+naam(?:\s+hai)?|main\s+hoon|main\s+hu)\s+",
        r"^(?:majhe?\s+naav(?:\s+aahe)?|majha\s+naav|mi\s+aahe|mi)\s+",
        r"^(?:मेरा\s+नाम(?:\s+है)?|मैं\s+हूँ|मैं)\s+",
        r"^(?:माझे?\s+नाव(?:\s+आहे)?|माझं\s+नाव|मी\s+आहे|मी)\s+",
        r"^(?:hello|hi|hey|namaste|namaskar|uh+|um+|aah+|hmm+)\s+",
        r"^(?:नमस्ते|नमस्कार|जी)\s+",
    )
]

# Trailing grammatical copulas leaked from regex/LLM — not part of a name.
_TRAILING_COPULAS_LATIN = frozenset({"is", "am", "are"})
_TRAILING_COPULAS_DEVANAGARI = frozenset({"है", "हूँ", "हूं", "हैं", "आहे", "आहेत"})

_TRAILING_GARBAGE = re.compile(
    r"\s+(?:hospital|clinic|doctor|appointment|mumbai|pune|delhi|"
    r"chennai|bangalore|hyderabad|nagpur|aurangabad|"
    r"हॉस्पिटल|hospital|city|se\s+hoon|from)\b.*$",
    re.IGNORECASE | re.UNICODE,
)

# Allowed characters in a name.
_ALLOWED_CHARS_RE = re.compile(r"[^\w\s\u0900-\u097F.'\-]", re.UNICODE)


def _has_devanagari(text: str) -> bool:
    return bool(_DEVANAGARI_RE.search(text))


def _strip_residual_cues(name: str) -> str:
    """Remove leading cue phrases if model leaked them."""
    text = name.strip()
    changed = True
    while changed:
        changed = False
        for pattern in _RESIDUAL_CUE_PATTERNS:
            match = pattern.match(text)
            if match:
                text = text[match.end() :].strip()
                changed = True
    return text


def _strip_trailing_copulas(name: str) -> str:
    """Remove trailing sentence-ending copulas if leaked into the capture."""
    tokens = name.split()
    while len(tokens) > 1:
        last = tokens[-1].rstrip(".,;")
        if last.lower() in _TRAILING_COPULAS_LATIN or last in _TRAILING_COPULAS_DEVANAGARI:
            tokens.pop()
        else:
            break
    return " ".join(tokens)


def _dedupe_adjacent_tokens(name: str) -> str:
    """Remove consecutive duplicate tokens."""
    tokens = name.split()
    if not tokens:
        return name
    deduped = [tokens[0]]
    for token in tokens[1:]:
        if token.lower() != deduped[-1].lower():
            deduped.append(token)
    return " ".join(deduped)


def _title_case_latin(name: str) -> str:
    """Title-case Latin tokens; preserve titles like Mr., Dr."""
    tokens = name.split()
    result: list[str] = []
    for token in tokens:
        if re.match(r"^(?:Mr|Mrs|Ms|Dr|Shri|Smt)\.?$", token, re.IGNORECASE):
            # Normalise title abbreviation.
            title_map = {
                "mr": "Mr.", "mrs": "Mrs.", "ms": "Ms.", "dr": "Dr.",
                "shri": "Shri", "smt": "Smt.",
            }
            key = token.rstrip(".").lower()
            result.append(title_map.get(key, token))
        elif _has_devanagari(token):
            result.append(token)
        else:
            result.append(token.capitalize())
    return " ".join(result)


def postprocess_name(name: str) -> str:
    """
    Clean and normalise an extracted name string.

    Devanagari names are kept as-is (no title case).
    Latin names receive Title Case per token.
    """
    if not name or not name.strip():
        return ""

    text = name.strip().strip('"').strip("'")
    text = _strip_residual_cues(text)
    text = _strip_trailing_copulas(text)
    text = _TRAILING_GARBAGE.sub("", text)
    text = _ALLOWED_CHARS_RE.sub("", text)
    text = _dedupe_adjacent_tokens(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip(".,!?; ")

    if not text:
        return ""

    if _has_devanagari(text):
        return text

    return _title_case_latin(text)
