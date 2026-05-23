from app.core.logger import logger
from app.services.notification_service import NotificationService


async def send_appointment_reminders(appointments: list[dict]):
    for appt in appointments:
        await NotificationService.notify_appointment_reminder(
            email=appt.get("email", ""),
            phone=appt.get("phone"),
            message=f"Reminder: Appointment on {appt.get('scheduled_at')}",
        )
        logger.info("Reminder sent for appointment %s", appt.get("id"))
