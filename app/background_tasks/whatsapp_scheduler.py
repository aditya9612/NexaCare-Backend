from app.core.logger import logger
from app.utils.whatsapp_sender import send_whatsapp


async def run_whatsapp_scheduler(messages: list[dict]):
    for msg in messages:
        await send_whatsapp(msg["phone"], msg["text"])
        logger.info("Scheduled WhatsApp sent to %s", msg["phone"])
