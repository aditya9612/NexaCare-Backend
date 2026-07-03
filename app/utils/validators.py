import re

PHONE_REGEX = re.compile(r"^\+?[1-9]\d{6,14}$")
MRN_REGEX = re.compile(r"^MRN-\d{8}$")


def is_valid_phone(phone: str) -> bool:
    return bool(PHONE_REGEX.match(phone))


def is_valid_mrn(mrn: str) -> bool:
    return bool(MRN_REGEX.match(mrn))


def validate_gst_number(v: str | None) -> str | None:
    if v is None:
        return v
    cleaned = v.strip().upper()
    if not cleaned or cleaned.lower() == "null":
        raise ValueError("GST number cannot be blank or 'null'")
    if len(cleaned) != 15:
        raise ValueError("GST number must be exactly 15 characters long")
    
    pattern = r"^(0[1-9]|[1-2][0-9]|3[0-8])[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9][A-Z][A-Z0-9]$"
    if not re.match(pattern, cleaned):
        raise ValueError("Invalid GST number format")
    return cleaned

