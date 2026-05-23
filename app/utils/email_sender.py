import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings
from app.core.logger import logger


async def send_email(to: str, subject: str, body: str) -> bool:
    if not settings.SMTP_USER:
        logger.warning("SMTP not configured; skipping email to %s", to)
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = settings.SMTP_FROM
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as exc:
        logger.error("Email send failed: %s", exc)
        return False
