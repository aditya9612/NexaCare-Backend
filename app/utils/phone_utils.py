import re

from app.utils.validators import is_valid_phone

_NON_DIGIT = re.compile(r"[\s\-().]")


def normalize_phone(phone: str) -> str:
    """Normalize to E.164-style (+countrycode...) for storage and SMS."""
    cleaned = _NON_DIGIT.sub("", phone.strip())
    if cleaned.startswith("+"):
        return cleaned
    if cleaned.startswith("00"):
        return f"+{cleaned[2:]}"
    if len(cleaned) == 10 and cleaned[0] in "6789":
        return f"+91{cleaned}"
    if cleaned.startswith("91") and len(cleaned) == 12:
        return f"+{cleaned}"
    return f"+{cleaned}"


def validate_phone_field(phone: str) -> str:
    normalized = normalize_phone(phone)
    if not is_valid_phone(normalized):
        raise ValueError("Invalid phone number")
    return normalized
