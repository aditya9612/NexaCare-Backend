from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.background_tasks.appointment_reminder import send_appointment_reminders
from app.core.config import settings
from app.core.constants import VoiceCallType
from app.core.logger import logger
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.patient_repository import PatientRepository
from app.schemas.voice_schema import ScheduleCallRequest
from app.services.voice_service import VoiceService
from app.utils.helpers import utc_now


class ReminderOrchestrator:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.appointment_repo = AppointmentRepository(db)
        self.patient_repo = PatientRepository(db)
        self.voice_service = VoiceService(db)

    async def schedule_voice_reminders_for_date(self, target_date: date) -> int:
        appointments = await self.appointment_repo.list_needing_voice_reminder(target_date)
        scheduled = 0

        for appt in appointments:
            patient = await self.patient_repo.get_by_id(appt.patient_id)
            if not patient or not patient.phone:
                logger.warning("Skipping voice reminder for appointment %s: no patient phone", appt.id)
                continue

            scheduled_time = datetime.combine(appt.appointment_date, appt.appointment_time) - timedelta(
                hours=settings.VOICE_REMINDER_HOURS_BEFORE
            )
            now = utc_now()
            if scheduled_time < now:
                scheduled_time = now

            await self.voice_service.schedule_call(
                ScheduleCallRequest(
                    patient_id=appt.patient_id,
                    appointment_id=appt.id,
                    phone_number=patient.phone,
                    call_type=VoiceCallType.REMINDER,
                    language="en",
                    scheduled_time=scheduled_time,
                )
            )
            appt.reminder_sent = True
            scheduled += 1

        return scheduled

    async def send_email_reminders(self, appointments_payload: list[dict]) -> None:
        await send_appointment_reminders(appointments_payload)
