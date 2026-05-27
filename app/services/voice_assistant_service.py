from datetime import date, time
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.voice_appointment_assistant.assistant import VoiceAppointmentAssistant
from app.ai.voice_appointment_assistant import prompts
from app.ai.voice_appointment_assistant.schemas import (
    VoiceBookingPayload,
    VoiceIntent,
    VoiceState,
    VoiceStep,
)
from app.core.config import settings
from app.core.constants import AppointmentStatus
from app.core.exceptions import ConflictException
from app.core.logger import logger
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.doctor_repository import DoctorRepository
from app.repositories.patient_repository import PatientRepository
from app.schemas.appointment_schema import AppointmentCreate, CancelRequest, RescheduleRequest
from app.services.appointment_service import AppointmentService
from app.utils.redis_service import cache_get, cache_set
from app.utils.twiml_builder import (
    gather_speech_or_dtmf,
    hangup,
    say,
    twilio_say_language,
    twiml_response,
)

VOICE_STATE_TTL = 3600
_memory_store: Dict[str, Dict[str, Any]] = {}


class VoiceAssistantService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.assistant = VoiceAppointmentAssistant()
        self.doctor_repo = DoctorRepository(db)
        self.patient_repo = PatientRepository(db)
        self.appointment_repo = AppointmentRepository(db)

    def _state_key(self, call_sid: str) -> str:
        return f"voice_assistant:{call_sid}"

    def _twiml_url(self, path: str) -> str:
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        prefix = settings.API_V1_PREFIX.rstrip("/")
        return f"{base}{prefix}/voice-assistant{path}"

    async def load_state(self, call_sid: str) -> Optional[VoiceState]:
        key = self._state_key(call_sid)
        data = await cache_get(key)
        if data is None:
            data = _memory_store.get(key)
        if not data:
            return None
        return VoiceState.from_dict(data)

    async def save_state(self, state: VoiceState) -> None:
        key = self._state_key(state.call_sid)
        payload = state.to_dict()
        saved = await cache_set(key, payload, ttl=VOICE_STATE_TTL)
        if not saved:
            _memory_store[key] = payload

    async def build_start_twiml(
        self,
        call_sid: str,
        from_number: str = "",
        language: str = "en",
    ) -> str:
        state = VoiceState(
            call_sid=call_sid,
            from_number=from_number or "",
            language=language,
            step=VoiceStep.GREET,
        )
        if from_number:
            digits = self.assistant._normalize_phone(from_number)
            if digits:
                state.mobile_number = digits

        turn = self.assistant.start_call(state)
        await self.save_state(turn.state)
        return self._build_gather_twiml(turn)

    async def handle_turn(
        self,
        call_sid: str,
        speech_result: str = "",
        digits: str = "",
        confidence: str | None = None,
        from_number: str = "",
    ) -> str:
        state = await self.load_state(call_sid)
        if not state:
            return await self.build_start_twiml(call_sid, from_number=from_number)

        transcript = (speech_result or "").strip()
        if not transcript and digits:
            transcript = digits
        conf_val = None
        if confidence:
            try:
                conf_val = float(confidence)
            except (TypeError, ValueError):
                conf_val = None

        turn = self.assistant.process_turn(state, transcript, confidence=conf_val)

        if (
            turn.state.intent == VoiceIntent.AVAILABILITY
            and turn.state.doctor_or_department
            and turn.hangup
        ):
            doctors = await self.doctor_repo.list_available()
            matched = self.assistant.match_doctor(doctors, turn.state.doctor_or_department)
            available = [matched] if matched else doctors[:2]
            turn.prompt = self.assistant.format_availability(available, turn.state.language)

        if turn.booking_json and turn.state.booking_completed:
            await self._finalize_action(turn.state, turn.booking_json)
            if turn.state.pending_booking:
                turn.prompt = prompts.pending_callback(turn.state.language)

        await self.save_state(turn.state)

        if turn.hangup:
            lang = twilio_say_language(turn.state.language)
            return twiml_response(say(turn.prompt, lang), hangup())

        return self._build_gather_twiml(turn)

    def _build_gather_twiml(self, turn) -> str:
        lang = twilio_say_language(turn.state.language)
        action = self._twiml_url("/twiml/turn")
        dtmf_hint = ""
        if turn.use_dtmf_menu or turn.state.step == VoiceStep.INTENT:
            dtmf_hint = (
                " Press 1 to book, 2 to reschedule, 3 to cancel, "
                "4 for doctor availability, 5 for hospital information."
            )
        prompt = turn.prompt + dtmf_hint
        hints = "appointment, doctor, book, cancel, reschedule"
        return twiml_response(
            gather_speech_or_dtmf(action, prompt, language=lang, hints=hints)
        )

    async def _finalize_action(self, state: VoiceState, payload: VoiceBookingPayload) -> None:
        logger.info("Voice assistant booking JSON: %s", payload.model_dump())
        try:
            if state.intent == VoiceIntent.BOOK:
                await self._book_appointment(state, payload)
            elif state.intent == VoiceIntent.RESCHEDULE:
                await self._reschedule_appointment(state)
            elif state.intent == VoiceIntent.CANCEL:
                await self._cancel_appointment(state)
        except ConflictException:
            alt1, alt2 = "4 PM", "6 PM"
            state.step = VoiceStep.BOOK_TIME
            state.booking_completed = False
            logger.warning("Slot conflict for voice booking call_sid=%s", state.call_sid)
        except Exception as exc:
            logger.error("Voice booking finalize error: %s", exc)
            state.pending_booking = True

    async def _book_appointment(self, state: VoiceState, payload: VoiceBookingPayload) -> None:
        patient = await self._find_patient(state.mobile_number)
        if not patient:
            state.pending_booking = True
            return

        doctors = await self.doctor_repo.list_available()
        doctor = self.assistant.match_doctor(doctors, state.doctor_or_department or "")
        if not doctor:
            state.pending_booking = True
            return

        appt_date = self._parse_date(state.appointment_date)
        appt_time = self._parse_time(state.appointment_time)
        if not appt_date or not appt_time:
            state.pending_booking = True
            return

        data = AppointmentCreate(
            patient_id=patient.id,
            doctor_id=doctor.id,
            appointment_date=appt_date,
            appointment_time=appt_time,
            symptoms=state.symptoms,
            consultation_type="in_person",
        )
        await AppointmentService(self.db).create(data, user_id=patient.user_id or 0)
        state.patient_id = patient.id
        state.doctor_id = doctor.id

    async def _reschedule_appointment(self, state: VoiceState) -> None:
        appt = await self._find_upcoming_appointment(state.mobile_number)
        if not appt:
            state.pending_booking = True
            return
        new_date = self._parse_date(state.appointment_date)
        new_time = self._parse_time(state.appointment_time)
        if not new_date or not new_time:
            state.pending_booking = True
            return
        await AppointmentService(self.db).reschedule(
            RescheduleRequest(
                appointment_id=appt.id,
                appointment_date=new_date,
                appointment_time=new_time,
                notes="Rescheduled via voice assistant",
            ),
            user_id=0,
        )
        state.appointment_id = appt.id

    async def _cancel_appointment(self, state: VoiceState) -> None:
        appt = await self._find_upcoming_appointment(state.mobile_number)
        if not appt:
            state.pending_booking = True
            return
        await AppointmentService(self.db).cancel(
            CancelRequest(appointment_id=appt.id, reason="Cancelled via voice assistant"),
            user_id=0,
        )
        state.appointment_id = appt.id

    async def _find_patient(self, mobile: str | None):
        if not mobile:
            return None
        patients = await self.patient_repo.search(mobile, limit=5)
        digits = self.assistant._normalize_phone(mobile)
        for p in patients:
            if p.phone and digits in self.assistant._normalize_phone(p.phone):
                return p
        return patients[0] if patients else None

    async def _find_upcoming_appointment(self, mobile: str | None):
        patient = await self._find_patient(mobile)
        if not patient:
            return None
        appointments = await self.appointment_repo.list_all(
            patient_id=patient.id,
            status=AppointmentStatus.CONFIRMED,
            limit=5,
        )
        if not appointments:
            appointments = await self.appointment_repo.list_all(
                patient_id=patient.id,
                status=AppointmentStatus.PENDING,
                limit=5,
            )
        return appointments[0] if appointments else None

    def _parse_date(self, value: str | None) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            d, _ = self.assistant._parse_datetime(value)
            return d

    def _parse_time(self, value: str | None) -> time | None:
        if not value:
            return None
        try:
            parts = str(value).split(":")
            return time(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            _, t = self.assistant._parse_datetime(value or "")
            return t
