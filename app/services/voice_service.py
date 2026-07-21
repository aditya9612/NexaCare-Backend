from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.voice_call.handler import VoiceCallHandler
from app.core.config import settings
from app.core.constants import AppointmentStatus, VoiceCallStatus, VoiceCallType, VoiceResponseType
from app.core.exceptions import BadRequestException, NotFoundException
from app.models.voice_model import CallSchedule, VoiceCall, VoiceCallLog, VoiceResponse
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.patient_repository import PatientRepository
from app.repositories.voice_repository import VoiceRepository
from app.schemas.voice_schema import (
    CallActionRequest,
    CallAnalyticsResponse,
    RescheduleViaVoiceRequest,
    RetryCallRequest,
    ScheduleCallRequest,
    StartCallRequest,
    VoiceCallResponse,
)
from app.services.hospital_voice_config_service import HospitalVoiceConfigService
from app.telephony.factory import ProviderFactory
from app.utils.helpers import utc_now
from app.utils.pagination import build_paginated_result
from app.utils.twiml_builder import gather, say, twiml_response


def call_provider_hint(payload: dict) -> str:
    if payload.get("CallFrom") or payload.get("DialCallStatus"):
        return "exotel"
    if payload.get("CallSid") and ("From" in payload or "CallStatus" in payload):
        return "twilio"
    return settings.DEFAULT_TELEPHONY_PROVIDER


class VoiceService:
    def __init__(self, db: AsyncSession, hospital_id: int | None = None):
        self.db = db
        self.hospital_id = hospital_id
        self.repo = VoiceRepository(db)
        self.patient_repo = PatientRepository(db)
        self.appointment_repo = AppointmentRepository(db)
        self.voice_handler = VoiceCallHandler()
        self.voice_config_service = HospitalVoiceConfigService(db)

    def _reminder_url(self, path: str, provider_name: str | None = None) -> str:
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        prefix = settings.API_V1_PREFIX.rstrip("/")
        root = "/exotel" if (provider_name or "").lower() == "exotel" else ""
        # Twilio: /voice-reminder/twiml/...  Exotel: /voice-reminder/exotel/...
        if root == "/exotel":
            return f"{base}{prefix}/voice-reminder/exotel{path}"
        return f"{base}{prefix}/voice-reminder{path}"

    def _twiml_url(self, path: str) -> str:
        return self._reminder_url(path, "twilio")

    async def _get_provider(self, hospital_id: int | None = None):
        hid = hospital_id or self.hospital_id
        config = None
        if hid:
            config = await self.voice_config_service.get_entity(hid)
        return ProviderFactory.from_hospital_config(config), config

    async def schedule_call(self, data: ScheduleCallRequest) -> VoiceCallResponse:
        if not await self.patient_repo.get_by_id(data.patient_id):
            raise NotFoundException("Patient not found")
        if data.appointment_id:
            appt = await self.appointment_repo.get_by_id(data.appointment_id)
            if not appt:
                raise NotFoundException("Appointment not found")

        hospital_id = getattr(data, "hospital_id", None) or self.hospital_id
        max_retries = 3
        provider_name = settings.DEFAULT_TELEPHONY_PROVIDER
        if hospital_id:
            cfg = await self.voice_config_service.get_entity(hospital_id)
            if cfg:
                max_retries = cfg.retry_count
                provider_name = cfg.telephony_provider

        call = VoiceCall(
            patient_id=data.patient_id,
            appointment_id=data.appointment_id,
            hospital_id=hospital_id,
            phone_number=data.phone_number,
            call_type=data.call_type,
            language=data.language,
            scheduled_time=data.scheduled_time,
            call_status=VoiceCallStatus.PENDING,
            max_retries=max_retries,
            provider=provider_name,
        )
        call = await self.repo.create_call(call)

        schedule = CallSchedule(call_id=call.id, scheduled_at=data.scheduled_time)
        await self.repo.create_schedule(schedule)
        await self.repo.add_log(
            VoiceCallLog(call_id=call.id, event_type="scheduled", event_data="Call scheduled")
        )

        try:
            from app.tasks.voice_tasks import execute_voice_call

            if data.scheduled_time <= utc_now() + timedelta(minutes=1):
                execute_voice_call.delay(call.id)
        except Exception as exc:
            from app.core.logger import logger

            logger.error(
                "Failed to enqueue execute_voice_call for call_id=%s: %s",
                call.id,
                exc,
                exc_info=True,
            )

        return VoiceCallResponse.model_validate(call)

    async def start_call(self, data: StartCallRequest) -> VoiceCallResponse:
        call = await self._get_call(data.call_id)
        return VoiceCallResponse.model_validate(await self.start_call_internal(call.id))

    async def start_call_internal(self, call_id: int) -> VoiceCall:
        call = await self._get_call(call_id)
        if call.call_status not in (VoiceCallStatus.PENDING, VoiceCallStatus.BUSY, VoiceCallStatus.FAILED):
            raise BadRequestException(f"Cannot start call in status: {call.call_status}")

        call.call_status = VoiceCallStatus.CALLING
        await self.repo.update_call(call)
        await self.repo.add_log(
            VoiceCallLog(call_id=call.id, event_type="calling", event_data="Initiating call")
        )

        provider, cfg = await self._get_provider(call.hospital_id)
        resolved = provider.name
        if call.call_type == VoiceCallType.APPOINTMENT_ASSISTANT:
            base = settings.PUBLIC_BASE_URL.rstrip("/")
            api = settings.API_V1_PREFIX.rstrip("/")
            root = "exotel" if resolved == "exotel" else "twiml"
            twiml_url = f"{base}{api}/voice-assistant/{root}/start"
        else:
            twiml_url = self._reminder_url(f"/twiml/{call.id}", resolved)
        status_url = self._reminder_url("/status-callback", resolved)
        result = await provider.initiate_call(
            call.phone_number,
            webhook_url=twiml_url,
            status_callback_url=status_url,
            from_number=getattr(cfg, "from_number", None) if cfg else None,
        )
        call.provider_call_id = result.provider_call_id
        call.provider = provider.name
        await self.repo.update_call(call)
        await self.repo.add_log(
            VoiceCallLog(
                call_id=call.id,
                event_type="initiated",
                event_data=f"provider={provider.name} sid={call.provider_call_id}",
            )
        )
        return call

    async def build_initial_twiml(self, call_id: int) -> str:
        call = await self._get_call(call_id)
        greeting = await self.voice_handler.generate_voice_prompt(call.language)
        appt_text = ""
        if call.appointment_id:
            appt = await self.appointment_repo.get_by_id(call.appointment_id)
            if appt:
                appt_text = (
                    f" Your appointment is on {appt.appointment_date} "
                    f"at {appt.appointment_time}."
                )
        menu_data = await self.voice_handler.process_audio("")
        prompt = f"{greeting}{appt_text} {menu_data.get('menu', '')}"
        gather_url = self._reminder_url(
            f"/twiml/{call.id}/gather", call.provider or settings.DEFAULT_TELEPHONY_PROVIDER
        )
        lang = "en-US" if call.language == "en" else call.language
        return twiml_response(gather(gather_url, prompt, num_digits=1, language=lang))

    async def handle_dtmf_gather(self, call_id: int, digits: str) -> str:
        call = await self._get_call(call_id)
        action = self.voice_handler.parse_dtmf(digits)
        lang = "en-US" if call.language == "en" else call.language

        if action == "confirm_appointment":
            await self._handle_appointment_action(
                CallActionRequest(call_id=call.id, response_value=digits),
                "confirm",
                AppointmentStatus.CONFIRMED,
                "1",
            )
            text = "Thank you. Your appointment is confirmed. Goodbye."
        elif action == "cancel_appointment":
            await self._handle_appointment_action(
                CallActionRequest(call_id=call.id, response_value=digits),
                "cancel",
                AppointmentStatus.CANCELLED,
                "2",
            )
            text = "Your appointment has been cancelled. Goodbye."
        elif action == "reschedule_appointment":
            await self.repo.add_response(
                VoiceResponse(
                    call_id=call.id,
                    response_type=VoiceResponseType.DTMF,
                    response_value="3",
                    captured_at=utc_now(),
                )
            )
            await self.repo.add_log(
                VoiceCallLog(
                    call_id=call.id,
                    event_type="reschedule_requested",
                    event_data="Patient requested reschedule via phone",
                )
            )
            text = (
                "We have noted your reschedule request. "
                "Our team will contact you shortly. Goodbye."
            )
        elif action == "repeat_menu":
            return await self.build_initial_twiml(call_id)
        else:
            text = "Invalid option. Goodbye."

        if call.call_status == VoiceCallStatus.CALLING:
            call.call_status = VoiceCallStatus.COMPLETED
        await self.repo.update_call(call)
        return twiml_response(say(text, lang))

    async def handle_status_callback(self, payload: dict) -> None:
        provider_name = payload.get("_provider") or call_provider_hint(payload)
        provider = ProviderFactory.create(provider_name)
        normalized = provider.normalize_webhook(payload)
        call_sid = normalized.call_sid
        call_status = normalized.call_status
        duration = normalized.duration_seconds

        call = await self.repo.get_call_by_provider_sid(call_sid) if call_sid else None
        if not call:
            return

        status_map = {
            "completed": VoiceCallStatus.COMPLETED,
            "busy": VoiceCallStatus.BUSY,
            "no-answer": VoiceCallStatus.FAILED,
            "no_answer": VoiceCallStatus.FAILED,
            "failed": VoiceCallStatus.FAILED,
            "canceled": VoiceCallStatus.CANCELLED,
            "cancelled": VoiceCallStatus.CANCELLED,
        }
        if call_status in status_map:
            call.call_status = status_map[call_status]
        if duration is not None:
            call.duration_seconds = duration
        await self.repo.update_call(call)
        await self.repo.add_log(
            VoiceCallLog(
                call_id=call.id,
                event_type="status_callback",
                event_data=f"provider={provider.name} {call_status} duration={duration}",
            )
        )

    async def retry_call(self, data: RetryCallRequest) -> VoiceCallResponse:
        call = await self._get_call(data.call_id)
        if call.retry_count >= call.max_retries:
            raise BadRequestException("Maximum retry attempts reached")
        call.retry_count += 1
        call.call_status = VoiceCallStatus.PENDING
        call = await self.repo.update_call(call)
        await self.repo.add_log(
            VoiceCallLog(call_id=call.id, event_type="retry", event_data=f"Retry #{call.retry_count}")
        )
        try:
            from app.tasks.voice_tasks import execute_voice_call

            execute_voice_call.delay(call.id)
        except Exception as exc:
            from app.core.logger import logger

            logger.error(
                "Failed to enqueue retry execute_voice_call for call_id=%s: %s",
                call.id,
                exc,
                exc_info=True,
            )
        return VoiceCallResponse.model_validate(call)

    async def get_call_history(
        self, page: int = 1, size: int = 20, patient_id: int | None = None, call_status: str | None = None
    ):
        skip = (page - 1) * size
        items = await self.repo.list_calls(skip=skip, limit=size, patient_id=patient_id, call_status=call_status)
        total = await self.repo.count_calls(patient_id=patient_id, call_status=call_status)
        return build_paginated_result(
            [VoiceCallResponse.model_validate(c) for c in items], total, page, size
        )

    async def get_pending_calls(self) -> list[VoiceCallResponse]:
        calls = await self.repo.list_pending_calls()
        return [VoiceCallResponse.model_validate(c) for c in calls]

    async def get_analytics(self) -> CallAnalyticsResponse:
        breakdown = await self.repo.status_breakdown()
        status_map = {s: c for s, c in breakdown}
        total = sum(status_map.values())
        completed = status_map.get(VoiceCallStatus.COMPLETED, 0)
        failed = status_map.get(VoiceCallStatus.FAILED, 0)
        pending = status_map.get(VoiceCallStatus.PENDING, 0)
        busy = status_map.get(VoiceCallStatus.BUSY, 0)
        confirmations = await self.repo.count_calls(call_status=VoiceCallStatus.COMPLETED)
        total_calls = total or 1

        return CallAnalyticsResponse(
            total_calls=total,
            completed_calls=completed,
            failed_calls=failed,
            pending_calls=pending,
            busy_calls=busy,
            avg_duration_seconds=await self.repo.avg_duration(),
            confirmation_rate=round(confirmations / total_calls * 100, 2),
            status_breakdown=[{"status": s, "count": c} for s, c in breakdown],
            language_breakdown=[
                {"language": lang, "count": cnt} for lang, cnt in await self.repo.language_breakdown()
            ],
        )

    async def confirm_appointment(self, data: CallActionRequest) -> VoiceCallResponse:
        call = await self._handle_appointment_action(data, "confirm", AppointmentStatus.CONFIRMED, "1")
        return VoiceCallResponse.model_validate(call)

    async def cancel_appointment(self, data: CallActionRequest) -> VoiceCallResponse:
        call = await self._handle_appointment_action(data, "cancel", AppointmentStatus.CANCELLED, "2")
        return VoiceCallResponse.model_validate(call)

    async def reschedule_appointment(self, data: RescheduleViaVoiceRequest) -> VoiceCallResponse:
        call = await self._get_call(data.call_id)
        if call.appointment_id:
            appt = await self.appointment_repo.get_by_id(call.appointment_id)
            if appt:
                appt.appointment_date = data.new_scheduled_time.date()
                appt.appointment_time = data.new_scheduled_time.time().replace(second=0, microsecond=0)
                appt.appointment_status = AppointmentStatus.CONFIRMED
        await self.repo.add_response(
            VoiceResponse(
                call_id=call.id,
                response_type=VoiceResponseType.DTMF,
                response_value="3",
                captured_at=utc_now(),
            )
        )
        call.scheduled_time = data.new_scheduled_time
        call = await self.repo.update_call(call)
        return VoiceCallResponse.model_validate(call)

    async def _handle_appointment_action(
        self, data: CallActionRequest, action: str, status: str, dtmf: str
    ) -> VoiceCall:
        call = await self._get_call(data.call_id)
        if call.appointment_id:
            appt = await self.appointment_repo.get_by_id(call.appointment_id)
            if appt:
                appt.appointment_status = status
        await self.repo.add_response(
            VoiceResponse(
                call_id=call.id,
                response_type=VoiceResponseType.DTMF,
                response_value=data.response_value or dtmf,
                captured_at=utc_now(),
            )
        )
        await self.repo.add_log(
            VoiceCallLog(call_id=call.id, event_type=action, event_data=f"DTMF {dtmf}")
        )
        return await self.repo.update_call(call)

    async def _get_call(self, call_id: int) -> VoiceCall:
        call = await self.repo.get_call(call_id)
        if not call:
            raise NotFoundException("Voice call not found")
        return call
