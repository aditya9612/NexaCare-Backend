import random
import string
from datetime import datetime, timedelta

from app.core.config import settings
from app.utils.phone_utils import normalize_phone


_otp_store: dict[str, tuple[str, datetime]] = {}


def _email_key(email: str) -> str:
    return f"email:{email.strip().lower()}"


def _phone_key(phone: str) -> str:
    return f"phone:{normalize_phone(phone)}"


def _otp_keys(email: str | None = None, phone: str | None = None) -> list[str]:
    keys: list[str] = []
    if email:
        keys.append(_email_key(email))
    if phone:
        keys.append(_phone_key(phone))
    return keys


def generate_otp(length: int = 6) -> str:
    if settings.STATIC_OTP_CODE and settings.APP_ENV.lower() not in ("production", "prod"):
        return settings.STATIC_OTP_CODE
    return "".join(random.choices(string.digits, k=length))


def store_otp(email: str | None, otp: str, expiry_minutes: int = 10, phone: str | None = None) -> None:
    """Store OTP under email and/or phone keys (same code for both)."""
    expires = datetime.utcnow() + timedelta(minutes=expiry_minutes)
    for key in _otp_keys(email=email, phone=phone):
        _otp_store[key] = (otp, expires)


def _static_otp_accepted(otp: str) -> bool:
    return bool(
        settings.STATIC_OTP_CODE
        and settings.APP_ENV.lower() not in ("production", "prod")
        and otp == settings.STATIC_OTP_CODE
    )


def _check_key(key: str, otp: str) -> bool:
    stored = _otp_store.get(key)
    if not stored:
        return False
    code, expires = stored
    if datetime.utcnow() > expires:
        del _otp_store[key]
        return False
    return code == otp


def _clear_keys(keys: list[str]) -> None:
    for key in keys:
        _otp_store.pop(key, None)


def verify_otp(email: str | None, otp: str, phone: str | None = None) -> bool:
    """Verify OTP for email and/or phone identifier."""
    if _static_otp_accepted(otp):
        return True

    keys = _otp_keys(email=email, phone=phone)
    if not keys:
        return False

    for key in keys:
        if _check_key(key, otp):
            _clear_keys(keys)
            return True
    return False
