from app.utils.email_sender import send_email
from app.utils.sms_sender import send_sms
from app.utils.whatsapp_sender import send_whatsapp


class NotificationService:
    @staticmethod
    async def notify_appointment_reminder(email: str, phone: str | None, message: str):
        await send_email(email, "Appointment Reminder", message)
        if phone:
            await send_sms(phone, message)
            await send_whatsapp(phone, message)
