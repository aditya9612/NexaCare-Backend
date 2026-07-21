import re
from datetime import date, time
from typing import Optional


# ================= TEXT & IDENTIFIER VALIDATORS =================

def validate_full_name(v: Optional[str], field_name: str = "Full name") -> Optional[str]:
    if v is None:
        return v

    stripped = v.strip()

    if not stripped or stripped.lower() in ("null", "string"):
        if field_name == "Full name":
            raise ValueError("Full name cannot be empty or only spaces")
        raise ValueError(f"{field_name} cannot be blank or 'null'")

    if "  " in v or "  " in stripped:
        raise ValueError(f"{field_name} must contain only alphabetic characters and single spaces between words")

    if re.search(r"\d", stripped):
        raise ValueError(f"{field_name} must contain only alphabetic characters and single spaces between words")

    if not re.match(r"^[a-zA-Z\s\-\'\.]+$", stripped):
        raise ValueError(
            f"{field_name} must contain only alphabetic characters and single spaces between words"
        )

    return stripped





def validate_mobile(v: Optional[str], field_name: str = "Phone number") -> Optional[str]:
    if v is None:
        raise ValueError(f"{field_name} cannot be null")

    v = v.strip()

    if not v or v.lower() in ("null", "string"):
        raise ValueError(f"{field_name} cannot be blank or 'null'")

    if " " in v:
        raise ValueError(f"{field_name} must not contain spaces")

    raw_num = v

    if v.startswith("+91"):
        raw_num = v[3:]
    elif v.startswith("91") and len(v) == 12:
        raw_num = v[2:]

    if not raw_num.isdigit():
        raise ValueError(f"{field_name} must contain only numeric digits")

    if len(raw_num) != 10:
        raise ValueError(f"{field_name} must be exactly 10 digits")

    if raw_num[0] not in {"6", "7", "8", "9"}:
        raise ValueError(f"{field_name} must start with 6, 7, 8, or 9")

    return f"+91{raw_num}"




def validate_password(v: str) -> str:
    """Strict password validator matching the project's security schemas."""
    if not v:
        raise ValueError("Password is required")
    if len(v) < 8 or len(v) > 20:
        raise ValueError("Password must be between 8 and 20 characters in length")
    if v.startswith(" ") or v.endswith(" "):
        raise ValueError("Password must not contain leading or trailing spaces")
    if not v.isascii():
        raise ValueError("Password must contain only standard ASCII characters")
        
    if not any(c.isupper() for c in v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not any(c.islower() for c in v):
        raise ValueError("Password must contain at least one lowercase letter")
    if not any(c.isdigit() for c in v):
        raise ValueError("Password must contain at least one numeric digit")
    if not any(not (c.isalnum() or c.isspace()) for c in v):
        raise ValueError("Password must contain at least one special character")
        
    common_passwords = {
        "password@123", "admin@123", "welcome@123", "qwerty@123", "12345678",
    }
    if v.lower() in common_passwords:
        raise ValueError("Password is too common or easily guessable")
        
    return v


def validate_code_identifier(v: Optional[str], field_name: str = "Code") -> Optional[str]:
    """Validates alphanumeric unique codes like staff_code, doctor_code, etc."""
    if v is None:
        return v
    if not v.strip() or v.lower() == "null":
        raise ValueError(f"{field_name} cannot be empty or 'null'")
    if not v.isascii():
        raise ValueError(f"{field_name} must contain only standard ASCII characters")
    if not re.match(r"^[a-zA-Z0-9\-\/_]+$", v):
        raise ValueError(f"{field_name} must contain only alphanumeric characters, hyphens, slashes, or underscores")
    return v


# ================= INDIAN KYC & BILLING VALIDATORS =================

def validate_pan(v: Optional[str]) -> Optional[str]:
    """Validates Indian PAN card format."""
    if v is None:
        return v
    v = v.strip().upper()
    if not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", v):
        raise ValueError("Invalid PAN format (e.g., ABCDE1234F)")
    return v


def validate_aadhaar(v: Optional[str]) -> Optional[str]:
    """Validates Indian Aadhaar card format."""
    if v is None:
        return v
    v = v.replace(" ", "").strip()
    if not re.match(r"^[0-9]{12}$", v):
        raise ValueError("Aadhaar must be 12 digits")
    return v


def validate_gst(v: Optional[str]) -> Optional[str]:
    """Validates Indian GST Number format."""
    if v is None:
        return v
    v = v.strip().upper()
    if not re.match(r"^(0[1-9]|[1-2][0-9]|3[0-8])[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$", v):
        raise ValueError("Invalid GST number format")
    return v


def validate_ifsc(v: Optional[str]) -> Optional[str]:
    """Validates Indian IFSC Code format."""
    if v is None:
        return v
    v = v.strip().upper()
    if not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", v):
        raise ValueError("Invalid IFSC code")
    return v


def validate_upi(v: Optional[str]) -> Optional[str]:
    """Validates UPI ID format."""
    if v is None:
        return v
    v = v.strip()
    if not re.match(r"^[\w.-]+@[\w.-]+$", v):
        raise ValueError("Invalid UPI ID")
    return v


def validate_account_number(v: Optional[str]) -> Optional[str]:
    """Validates standard Bank Account Number format."""
    if v is None:
        return v
    v = v.strip()
    if not re.match(r"^[0-9]{9,18}$", v):
        raise ValueError("Invalid account number (must be 9-18 digits)")
    return v


# ================= NUMERIC & DATE VALIDATORS =================

def validate_positive_required(v: float, field_name: str = "Value") -> float:
    """Ensures a numerical value is strictly greater than 0."""
    if v <= 0:
        raise ValueError(f"{field_name} must be greater than 0")
    return v


def validate_non_negative(v: float, field_name: str = "Value") -> float:
    """Ensures a numerical value is 0 or greater."""
    if v < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return v


def validate_not_future_date(v: Optional[date], field_name: str = "Date") -> Optional[date]:
    """Ensures a date is today or in the past."""
    if v and v > date.today():
        raise ValueError(f"{field_name} cannot be in the future")
    return v


def validate_start_end_dates(start_date: Optional[date], end_date: Optional[date]) -> Optional[date]:
    """Ensures an end date occurs after or on the start date."""
    if start_date and end_date and end_date < start_date:
        raise ValueError("End date cannot be before start date")
    return end_date


def validate_start_end_times(start_time: Optional[time], end_time: Optional[time]) -> Optional[time]:
    """Ensures an end time occurs strictly after the start time."""
    if start_time and end_time and end_time <= start_time:
        raise ValueError("End time must be after start time")
    return end_time
