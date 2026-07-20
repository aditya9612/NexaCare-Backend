import re

from app.utils.validators import is_valid_phone

_NON_DIGIT = re.compile(r"[\s\-().]")


def normalize_phone(phone: str) -> str:
    """Normalize to E.164-style (+countrycode...) for storage and SMS."""
    cleaned = _NON_DIGIT.sub("", phone.strip())
    if cleaned.startswith("0") and not cleaned.startswith("00") and len(cleaned) == 11 and cleaned[1] in "6789":
        cleaned = cleaned[1:]
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
    
    digits = "".join(c for c in normalized if c.isdigit())
    if len(digits) < 10:
        raise ValueError("Phone number must contain at least 10 digits")
        
    is_indian = (
        normalized.startswith("+91")
        or (len(digits) == 10)
        or (len(digits) == 11 and digits.startswith("0"))
        or (len(digits) == 12 and digits.startswith("91"))
    )
    
    if is_indian:
        local_num = digits[-10:]
        if local_num[0] not in {"6", "7", "8", "9"}:
            raise ValueError("Phone number must start with 6, 7, 8, or 9")
            
    return normalized
