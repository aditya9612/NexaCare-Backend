from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.background_tasks.appointment_reminder import send_appointment_reminders
from app.core.config import settings
from app.core.constants import VoiceCallType, VoiceLanguage
from app.core.logger import logger
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.patient_repository import PatientRepository
from app.schemas.voice_schema import ScheduleCallRequest
from app.services.hospital_voice_config_service import HospitalVoiceConfigService
from app.services.voice_service import VoiceService
from app.utils.helpers import utc_now


class ReminderOrchestrator:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.appointment_repo = AppointmentRepository(db)
        self.patient_repo = PatientRepository(db)
        self.voice_service = VoiceService(db)
        self.voice_config_service = HospitalVoiceConfigService(db)

    async def schedule_voice_reminders_for_date(self, target_date: date) -> int:
        appointments = await self.appointment_repo.list_needing_voice_reminder(target_date)
        scheduled = 0

        for appt in appointments:
            patient = await self.patient_repo.get_by_id(appt.patient_id)
            if not patient or not patient.phone:
                logger.warning("Skipping voice reminder for appointment %s: no patient phone", appt.id)
                continue

            hospital_id = None
            if getattr(patient, "user_id", None):
                from app.models.user_model import User
                from sqlalchemy import select

                result = await self.db.execute(select(User).where(User.id == patient.user_id))
                user = result.scalar_one_or_none()
                if user:
                    hospital_id = user.hospital_id

            language = VoiceLanguage.EN
            if patient.preferred_language in VoiceLanguage.ALL:
                language = patient.preferred_language
            elif hospital_id:
                cfg = await self.voice_config_service.get_entity(hospital_id)
                if cfg and cfg.default_language in VoiceLanguage.ALL:
                    language = cfg.default_language

            scheduled_time = datetime.combine(appt.appointment_date, appt.appointment_time) - timedelta(
                hours=settings.VOICE_REMINDER_HOURS_BEFORE
            )
            now = utc_now()
            if scheduled_time < now:
                scheduled_time = now

            self.voice_service.hospital_id = hospital_id
            await self.voice_service.schedule_call(
                ScheduleCallRequest(
                    patient_id=appt.patient_id,
                    appointment_id=appt.id,
                    phone_number=patient.phone,
                    call_type=VoiceCallType.REMINDER,
                    language=language,
                    scheduled_time=scheduled_time,
                )
            )
            appt.reminder_sent = True
            scheduled += 1

        return scheduled

    async def send_email_reminders(self, appointments_payload: list[dict]) -> None:
        await send_appointment_reminders(appointments_payload)
