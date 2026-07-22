"""
Stage 6 — Validation of extracted Indian patient names.
"""

from __future__ import annotations

import re

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
_LATIN_NAME_RE = re.compile(r"^[A-Za-z\u0900-\u097F\s.'\-]+$", re.UNICODE)
_DIGIT_RE = re.compile(r"\d")
_PHONE_RE = re.compile(r"\d{6,}")
_SENTENCE_MARKERS = re.compile(r"[?!]")

# Titles that are allowed at the start.
_ALLOWED_TITLES = frozenset(
    t.lower()
    for t in (
        "mr.", "mr", "mrs.", "mrs", "ms.", "ms", "dr.", "dr",
        "shri", "shri.", "smt", "smt.", "श्री", "श्री.", "श्रीमती", "श्रीमती.",
    )
)

_GREETINGS = frozenset(
    w.lower()
    for w in (
        "hello", "hi", "hey", "namaste", "namaskar", "good", "morning",
        "afternoon", "evening", "thanks", "thank", "please", "yes", "no",
        "ok", "okay", "ji", "jee", "uh", "um", "hmm",
        "नमस्ते", "नमस्कार", "जी", "हाँ", "हां", "धन्यवाद",
    )
)

_HOSPITAL_KEYWORDS = frozenset(
    w.lower()
    for w in (
        "hospital", "clinic", "nursing", "medical", "healthcare", "apollo",
        "fortis", "max", "manipal", "nexacare", "dispensary", "pharmacy",
        "हॉस्पिटल", "क्लिनिक", "नर्सिंग", "अस्पताल",
    )
)

_CITY_KEYWORDS = frozenset(
    w.lower()
    for w in (
        "mumbai", "pune", "delhi", "bangalore", "bengaluru", "chennai",
        "hyderabad", "kolkata", "ahmedabad", "nagpur", "aurangabad",
        "nashik", "thane", "navi", "मुंबई", "पुणे", "दिल्ली",
    )
)

_SYMPTOM_KEYWORDS = frozenset(
    w.lower()
    for w in (
        "pain", "fever", "headache", "cough", "cold", "vomiting", "nausea",
        "bleeding", "injury", "fracture", "diabetes", "bp", "pressure",
        "symptom", "problem", "sick", "ill", "ache", "hurt",
        "दर्द", "बुखार", "सिरदर्द", "खांसी", "उलटी", "तकलीफ",
        "दुखणे", "ताप", "डोकेदुखी",
    )
)

_MEDICINE_KEYWORDS = frozenset(
    w.lower()
    for w in (
        "tablet", "medicine", "injection", "dose", "mg", "paracetamol",
        "antibiotic", "syrup", "capsule", "prescription",
        "दवा", "गoli", "इंजेक्शन",
    )
)

_DOCTOR_ONLY = frozenset(
    w.lower()
    for w in (
        "doctor", "dr", "physician", "surgeon", "specialist",
        "डॉक्टर", "डॉ",
    )
)

_MIN_LEN = 2
_MAX_LEN = 60
_MAX_TOKENS = 5


def _strip_title(name: str) -> tuple[str, str | None]:
    """Return (name_without_title, title_or_none)."""
    tokens = name.split()
    if not tokens:
        return name, None
    first = tokens[0].lower().rstrip(".")
    if first in {t.rstrip(".") for t in _ALLOWED_TITLES} or tokens[0] in _ALLOWED_TITLES:
        return " ".join(tokens[1:]), tokens[0]
    return name, None


def _token_matches_any(token: str, keywords: frozenset[str]) -> bool:
    t = token.lower().rstrip(".,;")
    if t in keywords:
        return True
    return any(kw in t for kw in keywords if len(kw) >= 4)


def is_valid_indian_name(name: str) -> tuple[bool, str]:
    """
    Validate whether a string is a plausible Indian patient name.

    Returns (is_valid, reason).
    """
    if not name or not name.strip():
        return False, "Empty name."

    text = name.strip()
    char_count = len(text.replace(" ", ""))

    if char_count < _MIN_LEN:
        return False, "Name too short."
    if len(text) > _MAX_LEN:
        return False, "Name too long."

    if _DIGIT_RE.search(text):
        return False, "Name contains digits."
    if _PHONE_RE.search(text):
        return False, "Name contains phone-like digit sequence."

    if _SENTENCE_MARKERS.search(text):
        return False, "Name contains sentence markers."

    if not _LATIN_NAME_RE.match(text):
        return False, "Name contains invalid characters."

    core, title = _strip_title(text)
    tokens = core.split() if core else []

    if not tokens:
        return False, "Name has only a title, no personal name."

    if len(tokens) + (1 if title else 0) > _MAX_TOKENS:
        return False, "Too many tokens for a personal name."

    for token in tokens:
        t_lower = token.lower().rstrip(".,;")
        if t_lower in _GREETINGS:
            return False, f"Name contains greeting: {token}."
        if _token_matches_any(token, _HOSPITAL_KEYWORDS):
            return False, f"Name contains hospital keyword: {token}."
        if _token_matches_any(token, _CITY_KEYWORDS):
            return False, f"Name contains city keyword: {token}."
        if _token_matches_any(token, _SYMPTOM_KEYWORDS):
            return False, f"Name contains symptom keyword: {token}."
        if _token_matches_any(token, _MEDICINE_KEYWORDS):
            return False, f"Name contains medicine keyword: {token}."

    # Reject if entire name is a doctor reference without personal name.
    if len(tokens) == 1 and tokens[0].lower().rstrip(".") in _DOCTOR_ONLY:
        return False, "Name is a doctor reference, not a patient name."

    # Reject if all tokens are doctor/greeting keywords.
    non_name_tokens = sum(
        1 for t in tokens
        if t.lower().rstrip(".") in _DOCTOR_ONLY or t.lower() in _GREETINGS
    )
    if non_name_tokens == len(tokens):
        return False, "Name contains no personal name tokens."

    return True, "Valid Indian name."
