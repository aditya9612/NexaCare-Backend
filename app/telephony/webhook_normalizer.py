from typing import Any

from app.core.constants import TelephonyProviderType
from app.telephony.base import NormalizedWebhook
from app.telephony.exotel_provider import ExotelProvider
from app.telephony.twilio_provider import TwilioProvider


def normalize_webhook(provider: str, payload: dict[str, Any]) -> NormalizedWebhook:
    """Unify Twilio / Exotel webhook form bodies into NormalizedWebhook."""
    name = (provider or TelephonyProviderType.TWILIO).lower()
    if name == TelephonyProviderType.EXOTEL:
        return ExotelProvider().normalize_webhook(payload)
    return TwilioProvider().normalize_webhook(payload)


async def form_payload_from_request(request) -> dict[str, Any]:
    """Extract form or JSON body from a FastAPI Request."""
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        try:
            data = await request.json()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    try:
        form = await request.form()
        return {k: (v if isinstance(v, str) else str(v)) for k, v in form.items()}
    except Exception:
        return {}
