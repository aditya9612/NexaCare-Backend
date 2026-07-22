"""
Stage 2 — Regex-based name candidate extraction.

Extracts candidate names from common EN/HI/MR/transliterated patterns
before invoking the LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Name token: Latin letters, Devanagari, dots (titles), apostrophe, hyphen.
_NAME_TOKEN = r"[\u0900-\u097F\w.'\-]+"
_NAME_CAPTURE = rf"({_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,3}})"

# Explicit introduction cues with capture group.
_CUE_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (
        re.compile(
            rf"(?:my\s+name\s+is|i\s*'?m|i\s+am|this\s+is|call\s+me|myself|"
            rf"name\s+is|hello\s+this\s+side|this\s+side|(?:i\s+am\s+)?speaking)\s+{_NAME_CAPTURE}",
            re.IGNORECASE | re.UNICODE,
        ),
        0.95,
    ),
    (
        re.compile(
            rf"(?:mera\s+naam(?:\s+hai)?|main\s+hoon|main\s+hu)\s+{_NAME_CAPTURE}",
            re.IGNORECASE | re.UNICODE,
        ),
        0.93,
    ),
    (
        re.compile(
            rf"(?:majhe?\s+naav(?:\s+aahe)?|majha\s+naav|mi\s+aahe|mi)\s+{_NAME_CAPTURE}",
            re.IGNORECASE | re.UNICODE,
        ),
        0.93,
    ),
    (
        re.compile(
            rf"(?:मेरा\s+नाम(?:\s+है)?|मैं\s+हूँ|मैं)\s+{_NAME_CAPTURE}",
            re.UNICODE,
        ),
        0.95,
    ),
    (
        re.compile(
            rf"(?:माझे?\s+नाव(?:\s+आहे)?|माझं\s+नाव|मी\s+आहे|मी)\s+{_NAME_CAPTURE}",
            re.UNICODE,
        ),
        0.95,
    ),
]

# Title + name pattern.
_TITLE_PATTERN = re.compile(
    rf"^((?:Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Shri\.?|Smt\.?|श्री\.?|श्रीमती\.?)\s+{_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,2}})$",
    re.IGNORECASE | re.UNICODE,
)

# Bare short utterance (1–3 tokens, no digits).
_BARE_NAME_PATTERN = re.compile(
    rf"^({_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,2}})$",
    re.UNICODE,
)

_NOISE_WORDS = frozenset(
    w.lower()
    for w in (
        "hello", "hi", "hey", "namaste", "namaskar", "yes", "no", "ok", "okay",
        "please", "thanks", "thank", "you", "ji", "jee", "uh", "um", "hmm",
        "hospital", "clinic", "doctor", "appointment", "book", "booking",
        "pain", "fever", "headache", "problem", "symptom",
        "नमस्ते", "नमस्कार", "जी", "हाँ", "हां", "हospital",
    )
)


@dataclass
class NameCandidate:
    """A regex-extracted name candidate with confidence score."""

    name: str
    score: float
    source: str  # e.g. "cue:my name is", "title", "bare"


def _clean_candidate(name: str) -> str:
    """Trim and collapse whitespace on a captured candidate."""
    return re.sub(r"\s+", " ", name.strip().strip('"').strip("'"))


def _is_noise_candidate(name: str) -> bool:
    """Reject candidates that are purely noise words."""
    tokens = name.lower().split()
    if not tokens:
        return True
    return all(t.rstrip(".") in _NOISE_WORDS for t in tokens)


def extract_regex_candidates(cleaned: str) -> list[NameCandidate]:
    """
    Extract and score name candidates from a preprocessed transcript.

    Returns candidates sorted by score descending.
    """
    if not cleaned or not cleaned.strip():
        return []

    candidates: list[NameCandidate] = []
    seen: set[str] = set()

    def _add(name: str, score: float, source: str) -> None:
        candidate = _clean_candidate(name)
        if not candidate or _is_noise_candidate(candidate):
            return
        key = candidate.lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(NameCandidate(name=candidate, score=score, source=source))

    # Cue-based patterns (search anywhere in transcript).
    for pattern, score in _CUE_PATTERNS:
        for match in pattern.finditer(cleaned):
            _add(match.group(1), score, f"cue:{pattern.pattern[:30]}")

    # Title + name (full string match).
    title_match = _TITLE_PATTERN.match(cleaned.strip())
    if title_match:
        _add(title_match.group(1), 0.70, "title")

    # Bare 1–3 token utterance.
    bare_match = _BARE_NAME_PATTERN.match(cleaned.strip())
    if bare_match:
        bare = bare_match.group(1)
        # Skip if it looks like a cue phrase without a name.
        lower = bare.lower()
        cue_only = any(
            lower.startswith(c)
            for c in (
                "my name", "i am", "i'm", "this is", "mera naam", "majhe naav",
                "मेरा नाम", "माझे नाव", "call me",
            )
        )
        if not cue_only and not re.search(r"\d", bare):
            _add(bare, 0.62, "bare")

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def best_regex_candidate(cleaned: str) -> NameCandidate | None:
    """Return the highest-scoring regex candidate, or None."""
    candidates = extract_regex_candidates(cleaned)
    return candidates[0] if candidates else None
