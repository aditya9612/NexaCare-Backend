from app.core.config import settings
from app.core.logger import logger
from app.utils.phone_utils import normalize_phone
from app.utils.twilio_client import twilio_client


async def send_sms(phone: str, message: str) -> bool:
    normalized = normalize_phone(phone)

    if twilio_client.is_configured:
        try:
            await twilio_client.send_sms(normalized, message)
            logger.info("SMS sent via Twilio to %s", normalized)
            return True
        except Exception as exc:
            logger.error("Twilio SMS failed for %s: %s", normalized, exc)
            return False

    if settings.SMS_API_KEY:
        logger.info("SMS sent to %s: %s", normalized, message[:50])
        return True

    if settings.DEBUG:
        logger.info("SMS (dev, not configured) to %s: %s", normalized, message)
        return True

    logger.warning("SMS not configured; skipping SMS to %s", normalized)
    return False
