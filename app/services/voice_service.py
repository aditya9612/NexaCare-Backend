from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.voice_call.handler import VoiceCallHandler
from app.core.constants import AppointmentStatus, VoiceCallStatus, VoiceResponseType
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
    VoiceCallLogResponse,
    VoiceCallResponse,
    VoiceResponseSchema,
)
from app.utils.helpers import utc_now
from app.utils.pagination import build_paginated_result
from app.utils.twilio_client import twilio_client


class VoiceService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = VoiceRepository(db)
        self.patient_repo = PatientRepository(db)
        self.appointment_repo = AppointmentRepository(db)
        self.voice_handler = VoiceCallHandler()

    async def schedule_call(self, data: ScheduleCallRequest) -> VoiceCallResponse:
        if not await self.patient_repo.get_by_id(data.patient_id):
            raise NotFoundException("Patient not found")
        if data.appointment_id:
            appt = await self.appointment_repo.get_by_id(data.appointment_id)
            if not appt:
                raise NotFoundException("Appointment not found")

        call = VoiceCall(
            patient_id=data.patient_id,
            appointment_id=data.appointment_id,
            phone_number=data.phone_number,
            call_type=data.call_type,
            language=data.language,
            scheduled_time=data.scheduled_time,
            call_status=VoiceCallStatus.PENDING,
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
        except Exception:
            pass

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

        result = await twilio_client.initiate_call(call.phone_number)
        call.provider_call_id = result.get("sid")
        processed = await self.voice_handler.process_audio("")
        call.call_status = VoiceCallStatus.COMPLETED
        call.duration_seconds = 30
        await self.repo.update_call(call)
        await self.repo.add_log(
            VoiceCallLog(
                call_id=call.id,
                event_type="completed",
                event_data=str(processed),
            )
        )
        return call

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
        except Exception:
            pass
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
