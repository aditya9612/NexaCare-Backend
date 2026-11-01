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
    """Send OTP via email and/or SMS with branded template and security warning."""
    subject = f"{otp} is your {settings.APP_NAME} verification code"

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{settings.APP_NAME} Verification Code</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #f1f5f9; padding: 36px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 520px; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06); overflow: hidden; border: 1px solid #e2e8f0;">
          <tr>
            <td style="background-color: #0369a1; padding: 24px 32px; text-align: left;">
              <h1 style="margin: 0; color: #ffffff; font-size: 20px; font-weight: 700; letter-spacing: 0.5px;">
                {settings.APP_NAME}
              </h1>
              <p style="margin: 4px 0 0; color: #e0f2fe; font-size: 13px;">Hospital Management System</p>
            </td>
          </tr>
          <tr>
            <td style="padding: 32px 32px 24px;">
              <p style="margin: 0 0 16px; font-size: 15px; color: #334155; line-height: 1.5;">
                Hello,
              </p>
              <p style="margin: 0 0 20px; font-size: 14px; color: #334155; line-height: 1.5;">
                We received a request to verify your account for <strong>{purpose.lower()}</strong> on {settings.APP_NAME}. Please enter the verification code below to proceed:
              </p>

              <div style="background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px; padding: 18px 24px; text-align: center; margin: 24px 0;">
                <span style="font-size: 32px; font-weight: 700; letter-spacing: 8px; color: #0f172a; font-family: 'Consolas', 'Courier New', monospace; display: inline-block; padding-left: 8px;">
                  {otp}
                </span>
              </div>

              <p style="margin: 0 0 16px; font-size: 13px; color: #64748b; line-height: 1.5; text-align: center;">
                This code will expire in <strong>{settings.OTP_EXPIRE_MINUTES} minutes</strong>.
              </p>

              <div style="margin: 20px 0; font-size: 13px; color: #475569; background-color: #f8fafc; border-left: 3px solid #0284c7; padding: 12px 14px; border-radius: 4px; line-height: 1.4;">
                <strong>Security Warning:</strong> Never share this code with anyone. NexaCare staff will never ask for your verification code.
              </div>

              <p style="margin: 20px 0 0; font-size: 13px; color: #64748b; line-height: 1.5;">
                If you did not initiate this request, no action is required; your account remains secure.
              </p>
            </td>
          </tr>
          <tr>
            <td style="background-color: #f8fafc; padding: 16px 32px; text-align: center; border-top: 1px solid #f1f5f9;">
              <p style="margin: 0; font-size: 12px; color: #94a3b8; line-height: 1.4;">
                &copy; 2026 {settings.APP_NAME}. All rights reserved.<br>
                Automated security notification &bull; Please do not reply to this email.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    plain_body = (
        f"{settings.APP_NAME} - Verification Code\n\n"
        f"Hello,\n\n"
        f"We received a request to verify your account for {purpose.lower()} on {settings.APP_NAME}.\n"
        f"Your verification code is: {otp}\n\n"
        f"This code will expire in {settings.OTP_EXPIRE_MINUTES} minutes.\n\n"
        "Security Warning: Never share this code with anyone. NexaCare staff will never ask for your verification code.\n\n"
        "If you did not initiate this request, no action is required; your account remains secure.\n\n"
        f"---\n(c) 2026 {settings.APP_NAME}. Automated security notification."
    )


    sms_body = (
        f"Your {settings.APP_NAME} OTP is {otp}. "
        f"Valid for {settings.OTP_EXPIRE_MINUTES} minutes. Never share this code."
    )

    email_sent = False
    sms_sent = False

    if email:
        email_sent = await send_email(email, subject, html_body, plain_body=plain_body)

    if phone:
        sms_sent = await send_sms(normalize_phone(phone), sms_body)

    logger.info(
        "OTP delivery dispatched (%s) email=%s phone=%s | email_sent=%s sms_sent=%s",
        purpose,
        email,
        phone,
        email_sent,
        sms_sent,
    )

    return {"email_sent": email_sent, "sms_sent": sms_sent}
