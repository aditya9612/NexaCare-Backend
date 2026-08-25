import re

from app.utils.validators import is_valid_phone

_NON_DIGIT = re.compile(r"[\s\-().]")


def indian_mobile_last10(phone: str | None) -> str:
    """
    Canonical 10-digit Indian mobile key for matching.
    Supports: 9876543210, +919876543210, 0919876543210, 919876543210.
    """
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if not digits:
        return ""
    if digits.startswith("91") and len(digits) >= 12:
        return digits[-10:]
    if digits.startswith("0") and len(digits) >= 11:
        return digits[-10:]
    if len(digits) >= 10:
        return digits[-10:]
    return digits


def normalize_phone(phone: str) -> str:
    """Normalize to E.164-style (+countrycode...) for storage and SMS."""
    cleaned = _NON_DIGIT.sub("", phone.strip())
    # 091XXXXXXXXXX or 0XXXXXXXXXX
    if cleaned.startswith("0") and not cleaned.startswith("00"):
        rest = cleaned[1:]
        if rest.startswith("91") and len(rest) >= 12:
            cleaned = rest
        elif len(rest) == 10 and rest[0] in "6789":
            cleaned = rest
    if cleaned.startswith("+"):
        return cleaned
    if cleaned.startswith("00"):
        return f"+{cleaned[2:]}"
    if len(cleaned) == 10 and cleaned[0] in "6789":
        return f"+91{cleaned}"
    if cleaned.startswith("91") and len(cleaned) >= 12:
        return f"+91{cleaned[-10:]}"
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
        or (len(digits) >= 12 and digits.startswith("91"))
    )

    if is_indian:
        local_num = indian_mobile_last10(normalized)
        if not local_num or local_num[0] not in {"6", "7", "8", "9"}:
            raise ValueError("Phone number must start with 6, 7, 8, or 9")

    return normalized


def normalize_inbound_did(phone: str | None) -> str:
    """
    Canonical E.164-style key for inbound DID matching (voice hospital resolution).

    Strips formatting, normalizes country codes, and returns +digits form.
    Used only for comparison — does not validate carrier rules.
    """
    if not phone:
        return ""
    cleaned = _NON_DIGIT.sub("", phone.strip())
    if cleaned.startswith("00"):
        cleaned = cleaned[2:]
    if cleaned.startswith("0") and not cleaned.startswith("00"):
        rest = cleaned[1:]
        if rest.startswith("91") and len(rest) >= 12:
            cleaned = rest
        elif len(rest) == 10 and rest[0] in "6789":
            cleaned = f"91{rest}"
    if len(cleaned) == 10 and cleaned[0] in "6789":
        cleaned = f"91{cleaned}"
    if cleaned.startswith("91") and len(cleaned) >= 12:
        return f"+91{cleaned[-10:]}"
    if cleaned.startswith("1") and len(cleaned) == 11:
        return f"+{cleaned}"
    if cleaned and not cleaned.startswith("+"):
        return f"+{cleaned}"
    return cleaned if cleaned.startswith("+") else f"+{cleaned}"


def inbound_dids_match(stored_did: str | None, caller_did: str | None) -> bool:
    """True when two inbound DIDs refer to the same number after normalization."""
    a = normalize_inbound_did(stored_did)
    b = normalize_inbound_did(caller_did)
    if not a or not b:
        return False
    if a == b:
        return True
    # National significant number fallback (last 10) for legacy rows
    a_digits = "".join(c for c in a if c.isdigit())
    b_digits = "".join(c for c in b if c.isdigit())
    if len(a_digits) >= 10 and len(b_digits) >= 10:
        return a_digits[-10:] == b_digits[-10:]
    return False
