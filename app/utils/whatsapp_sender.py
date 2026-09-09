from app.core.config import settings
from app.core.logger import logger
from app.utils.exotel_client import exotel_client
from app.utils.twilio_client import twilio_client


async def send_whatsapp(phone: str, message: str, media_url: str | None = None) -> bool:
    """Send WhatsApp message using the active telephony provider (Exotel / Twilio)."""
    if not phone:
        return False

    clean_phone = phone.strip().replace(" ", "").replace("-", "")

    # Exotel Provider (Primary for India)
    if settings.DEFAULT_TELEPHONY_PROVIDER == "exotel" and exotel_client.is_configured:
        try:
            logger.info("Sending WhatsApp via Exotel to %s", clean_phone)
            res = await exotel_client.send_whatsapp(to=clean_phone, body=message, media_url=media_url)
            return bool(res.get("sid") or res.get("status") in ("queued", "sent", "delivered", "success"))
        except Exception as exc:
            logger.error("Exotel WhatsApp dispatch failed for %s: %s", clean_phone, exc)
            return False

    # Twilio Provider (Fallback / International)
    if settings.DEFAULT_TELEPHONY_PROVIDER == "twilio" and twilio_client.is_configured:
        try:
            logger.info("Sending WhatsApp via Twilio to %s", clean_phone)
            res = await twilio_client.send_whatsapp(to=clean_phone, body=message, media_url=media_url)
            return bool(res.get("sid"))
        except Exception as exc:
            logger.error("Twilio WhatsApp dispatch failed for %s: %s", clean_phone, exc)
            return False

    logger.warning("No active WhatsApp provider configured; skipping message to %s", clean_phone)
    return False

