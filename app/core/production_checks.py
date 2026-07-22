"""Reject weak / incomplete production configuration at process start."""

from __future__ import annotations

from app.core.config import settings
from app.core.logger import logger

_WEAK_SECRETS = {
    "",
    "change-me",
    "change-me-in-production",
    "change-me-to-some-secure-random-key",
    "secret",
    "password",
}


def validate_production_settings() -> None:
    """Raise RuntimeError if APP_ENV is production and critical settings are unsafe."""
    env = (settings.APP_ENV or "").lower()
    if env not in ("production", "prod"):
        return

    errors: list[str] = []
    warnings: list[str] = []

    if (settings.SECRET_KEY or "").strip().lower() in _WEAK_SECRETS or len(settings.SECRET_KEY or "") < 32:
        errors.append("SECRET_KEY must be a strong value (>=32 chars), not a default placeholder")

    if settings.SKIP_VOICE_WEBHOOK_AUTH:
        errors.append("SKIP_VOICE_WEBHOOK_AUTH must be false in production")

    if not (settings.PUBLIC_BASE_URL or "").startswith("https://"):
        errors.append("PUBLIC_BASE_URL must be an https:// webhook URL in production")

    if "localhost" in (settings.PUBLIC_BASE_URL or ""):
        errors.append("PUBLIC_BASE_URL must not use localhost in production")

    if "ngrok" in (settings.PUBLIC_BASE_URL or "").lower():
        warnings.append("PUBLIC_BASE_URL still uses ngrok — replace with hospital HTTPS domain before final go-live")

    if not settings.DATABASE_URL:
        errors.append("DATABASE_URL is required")

    twilio_ok = bool(
        settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_PHONE_NUMBER
    )
    exotel_ok = bool(
        settings.EXOTEL_SID
        and settings.EXOTEL_API_KEY
        and settings.EXOTEL_API_TOKEN
        and settings.EXOTEL_PHONE_NUMBER
    )
    if not twilio_ok and not exotel_ok:
        warnings.append(
            "No live Twilio/Exotel credentials configured — voice calls will be simulated until providers are set"
        )
    elif twilio_ok and not settings.TWILIO_AUTH_TOKEN:
        errors.append("TWILIO_AUTH_TOKEN is required when Twilio SID/phone are set")
    elif (settings.DEFAULT_TELEPHONY_PROVIDER or "").lower() == "exotel" and not (
        settings.EXOTEL_WEBHOOK_SECRET or settings.EXOTEL_API_TOKEN
    ):
        errors.append("EXOTEL_WEBHOOK_SECRET (or EXOTEL_API_TOKEN) required for Exotel webhooks")

    if settings.DEBUG:
        errors.append("DEBUG must be false in production")

    if settings.ALLOW_ADMIN_SELF_REGISTER:
        errors.append("ALLOW_ADMIN_SELF_REGISTER must be false in production")

    for w in warnings:
        logger.warning("Production config warning: %s", w)

    if errors:
        for err in errors:
            logger.error("Production config rejected: %s", err)
        raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))

    logger.info("Production configuration validation passed")


def live_telephony_ready() -> tuple[bool, list[str]]:
    """Return whether real (non-simulated) telephony can be used."""
    issues: list[str] = []
    twilio_ok = bool(
        settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_PHONE_NUMBER
    )
    exotel_ok = bool(
        settings.EXOTEL_SID
        and settings.EXOTEL_API_KEY
        and settings.EXOTEL_API_TOKEN
        and settings.EXOTEL_PHONE_NUMBER
        and (settings.EXOTEL_WEBHOOK_SECRET or settings.EXOTEL_API_TOKEN)
    )
    if not twilio_ok:
        issues.append("Twilio credentials incomplete")
    if not exotel_ok:
        issues.append("Exotel credentials incomplete")
    # India hospital needs at least one live provider; prefer both for dual-path audit
    ready = twilio_ok or exotel_ok
    if not ready:
        issues.append("At least one live telephony provider is required for go-live")
    return ready, issues
