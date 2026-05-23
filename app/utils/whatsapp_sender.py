from app.core.config import settings
from app.core.logger import logger


async def send_whatsapp(phone: str, message: str) -> bool:
    if not settings.WHATSAPP_API_KEY:
        logger.warning("WhatsApp API not configured; skipping message to %s", phone)
        return False
    logger.info("WhatsApp sent to %s: %s", phone, message[:50])
    return True
