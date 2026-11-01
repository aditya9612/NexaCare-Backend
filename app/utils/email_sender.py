import asyncio
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
import re
import smtplib

from app.core.config import settings
from app.core.logger import logger


def _send_sync_email(to: str, subject: str, html_body: str, plain_body: str | None = None) -> bool:
    if not settings.SMTP_USER or not settings.SMTP_HOST:
        logger.warning("SMTP not configured; skipping email delivery to %s", to)
        return False

    from_addr = settings.SMTP_FROM or settings.SMTP_USER
    sender_name = settings.APP_NAME or "NexaCare"

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = formataddr((sender_name, from_addr))
        msg["To"] = to
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="gmail.com")
        msg["Reply-To"] = formataddr((f"{sender_name} Support", from_addr))
        msg["Auto-Submitted"] = "auto-generated"
        msg["X-Auto-Response-Suppress"] = "All"
        msg["MIME-Version"] = "1.0"

        # Attach plain-text fallback first
        if plain_body:
            msg.attach(MIMEText(plain_body, "plain", "utf-8"))
        else:
            clean_text = re.sub(r"<[^>]+>", " ", html_body)
            clean_text = re.sub(r"\s+", " ", clean_text).strip()
            msg.attach(MIMEText(clean_text, "plain", "utf-8"))

        # Attach HTML content
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)

        logger.info("Email delivered successfully to %s (subject: %s)", to, subject)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed for user %s", settings.SMTP_USER)
        return False
    except smtplib.SMTPException as exc:
        logger.error("SMTP error sending email to %s: %s", to, type(exc).__name__)
        return False
    except Exception as exc:
        logger.error("Unexpected error sending email to %s: %s", to, type(exc).__name__)
        return False


async def send_email(to: str, subject: str, body: str, plain_body: str | None = None) -> bool:
    """
    Asynchronously send an email using Gmail SMTP via asyncio.to_thread
    to prevent blocking the event loop.
    """
    return await asyncio.to_thread(_send_sync_email, to, subject, body, plain_body)
