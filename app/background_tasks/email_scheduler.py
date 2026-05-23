from app.core.logger import logger
from app.utils.email_sender import send_email


async def run_email_scheduler(jobs: list[dict]):
    for job in jobs:
        await send_email(job["to"], job["subject"], job["body"])
        logger.info("Scheduled email sent to %s", job["to"])
