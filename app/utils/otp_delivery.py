from app.core.config import settings
from app.core.logger import logger
from app.utils.email_sender import send_email
from app.utils.phone_utils import normalize_phone
from app.utils.sms_sender import send_sms


async def deliver_otp(
    *,
    email: str | None,
    phone: str | None,
    otp: str,
    purpose: str = "verification",
) -> dict[str, bool]:
    """Send OTP via email and/or SMS. Returns which channels were used."""
    subject = f"{settings.APP_NAME} - OTP for {purpose}"
    html_body = (
        f"<p>Your one-time password is <strong>{otp}</strong>.</p>"
        f"<p>It expires in {settings.OTP_EXPIRE_MINUTES} minutes.</p>"
        f"<p>If you did not request this, ignore this message.</p>"
    )
    sms_body = (
        f"Your {settings.APP_NAME} OTP is {otp}. "
        f"Valid for {settings.OTP_EXPIRE_MINUTES} minutes."
    )

    email_sent = False
    sms_sent = False

    if email:
        email_sent = await send_email(email, subject, html_body)

    if phone:
        sms_sent = await send_sms(normalize_phone(phone), sms_body)

    if settings.DEBUG:
        logger.info(
            "OTP delivery (%s) email=%s phone=%s | email_sent=%s sms_sent=%s otp=%s",
            purpose,
            email,
            phone,
            email_sent,
            sms_sent,
            otp,
        )

    return {"email_sent": email_sent, "sms_sent": sms_sent}
