from datetime import date, time
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.voice_appointment_assistant.assistant import VoiceAppointmentAssistant
from app.ai.voice_appointment_assistant import prompts
from app.ai.voice_appointment_assistant.language import language_select_prompt
from app.ai.voice_appointment_assistant.schemas import (
    VoiceBookingPayload,
    VoiceIntent,
    VoiceState,
    VoiceStep,
)
from app.core.config import settings
from app.core.constants import (
    AppointmentStatus,
    BookingSource,
    TelephonyProviderType,
    TransferStatus,
    VoiceCallStatus,
    VoiceCallType,
)
from app.core.exceptions import ConflictException
from app.core.logger import logger
from app.models.voice_model import VoiceCall, VoiceCallLog
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.doctor_repository import DoctorRepository
from app.repositories.patient_repository import PatientRepository
from app.repositories.voice_repository import VoiceRepository
from app.schemas.appointment_schema import AppointmentCreate, CancelRequest, RescheduleRequest
from app.services.appointment_service import AppointmentService
from app.services.faq_retrieval_service import FaqRetrievalService
from app.services.hospital_voice_config_service import HospitalVoiceConfigService
from app.services.language_resolver_service import LanguageResolverService
from app.services.medical_safety_guard import MedicalSafetyGuard
from app.services.reception_transfer_service import ReceptionTransferService
from app.telephony.factory import ProviderFactory
from app.utils.helpers import utc_now
from app.utils.phone_utils import indian_mobile_last10
from app.utils.redis_service import cache_get, cache_set
from app.utils.twiml_builder import (
    gather,
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
        self.voice_repo = VoiceRepository(db)
        self.language_resolver = LanguageResolverService(db)
        self.voice_config_service = HospitalVoiceConfigService(db)
        self.faq_service = FaqRetrievalService(db)
        self.transfer_service = ReceptionTransferService(db)

    def _state_key(self, call_sid: str) -> str:
        return f"voice_assistant:{call_sid}"

    def _provider_prefix(self, provider_name: str | None) -> str:
        if (provider_name or "").lower() == TelephonyProviderType.EXOTEL:
            return "/exotel"
        return "/twiml"

    def _assistant_url(self, path: str, provider_name: str | None = None) -> str:
        """Provider-aware webhook URL under /voice-assistant/{twiml|exotel}/..."""
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        prefix = settings.API_V1_PREFIX.rstrip("/")
        root = self._provider_prefix(provider_name)
        # path like "/language" or "/turn" or "/transfer-result"
        return f"{base}{prefix}/voice-assistant{root}{path}"

    def _voice_kwargs(self, config) -> dict:
        if not config:
            return {}
        return {
            "voice": getattr(config, "voice_profile", None) or None,
            "voice_gender": getattr(config, "voice_gender", None) or None,
        }

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

    async def _ensure_inbound_call(self, state: VoiceState) -> None:
        """Create or refresh VoiceCall row for inbound analytics."""
        if state.voice_call_id:
            call = await self.voice_repo.get_call(state.voice_call_id)
            if call:
                call.language = state.language
                call.provider = state.provider
                call.hospital_id = state.hospital_id
                call.patient_id = state.patient_id
                call.intent = state.intent.value if state.intent else call.intent
                call.faq_hit = bool(state.faq_hit)
                call.ai_fallback = bool(state.ai_fallback)
                call.confidence = state.last_confidence
                call.transferred_to_reception = bool(state.transfer_requested)
                call.booking_success = bool(state.booking_completed and not state.pending_booking)
                if state.transfer_requested:
                    call.transfer_status = TransferStatus.INITIATED
                await self.voice_repo.update_call(call)
                return

        call = VoiceCall(
            patient_id=state.patient_id,
            hospital_id=state.hospital_id,
            phone_number=state.from_number or state.mobile_number or "unknown",
            call_type=VoiceCallType.APPOINTMENT_ASSISTANT,
            language=state.language or "en",
            scheduled_time=utc_now(),
            call_status=VoiceCallStatus.CALLING,
            provider=state.provider,
            provider_call_id=state.call_sid or None,
            intent=state.intent.value if state.intent else None,
        )
        call = await self.voice_repo.create_call(call)
        await self.voice_repo.add_log(
            VoiceCallLog(
                call_id=call.id,
                event_type="inbound_started",
                event_data=f"provider={state.provider} sid={state.call_sid}",
            )
        )
        state.voice_call_id = call.id

    async def _finalize_inbound_call(self, state: VoiceState, status: str = VoiceCallStatus.COMPLETED) -> None:
        if not state.voice_call_id:
            return
        call = await self.voice_repo.get_call(state.voice_call_id)
        if not call:
            return
        call.call_status = status
        call.language = state.language
        call.intent = state.intent.value if state.intent else call.intent
        call.faq_hit = bool(state.faq_hit)
        call.ai_fallback = bool(state.ai_fallback)
        call.confidence = state.last_confidence
        call.transferred_to_reception = bool(state.transfer_requested)
        call.booking_success = bool(state.booking_completed and not state.pending_booking)
        call.patient_id = state.patient_id or call.patient_id
        await self.voice_repo.update_call(call)

    async def build_start_twiml(
        self,
        call_sid: str,
        from_number: str = "",
        to_number: str = "",
        language: str = "en",
        provider_name: str | None = None,
    ) -> str:
        resolution_result = await self.voice_config_service.resolve_inbound_hospital(
            to_number=to_number
        )
        from app.services.hospital_voice_config_service import (
            log_hospital_resolution,
            mask_inbound_did,
        )

        log_hospital_resolution(
            resolution_result,
            call_sid=call_sid,
            masked_did=mask_inbound_did(to_number),
            step="incoming",
        )
        config = resolution_result.config
        hospital_id = resolution_result.hospital_id
        default_lang = (config.default_language if config else language) or "en"
        provider = ProviderFactory.from_hospital_config(config)
        pname = provider_name or provider.name

        resolution = await self.language_resolver.resolve_for_inbound(
            from_number=from_number,
            hospital_default=default_lang,
        )

        state = VoiceState(
            call_sid=call_sid,
            from_number=from_number or "",
            language=resolution.language,
            language_locked=not resolution.needs_dtmf_menu,
            language_source=resolution.source,
            step=VoiceStep.GREET,
            hospital_id=hospital_id,
            provider=pname,
            patient_id=resolution.patient_id,
        )
        if from_number:
            digits = indian_mobile_last10(from_number)
            if digits:
                state.mobile_number = digits

        await self._ensure_inbound_call(state)
        vk = self._voice_kwargs(config)

        if resolution.needs_dtmf_menu:
            state.step = VoiceStep.LANGUAGE_SELECT
            state.language_locked = False
            await self.save_state(state)
            lang = twilio_say_language(default_lang)
            action = self._assistant_url("/language", pname)
            # DTMF timeout → speech turn with AI language fallback
            timeout_url = self._assistant_url("/turn", pname)
            prompt = language_select_prompt(default_lang)
            return provider.render_response(
                twiml_response(
                    gather(
                        action,
                        prompt,
                        num_digits=1,
                        language=lang,
                        timeout_redirect_url=timeout_url,
                        **vk,
                    )
                )
            )

        turn = self.assistant.start_call(state)
        await self.save_state(turn.state)
        return provider.render_response(self._build_gather_twiml(turn, config))

    async def handle_language_dtmf(
        self,
        call_sid: str,
        digits: str = "",
        from_number: str = "",
        speech_result: str = "",
    ) -> str:
        state = await self.load_state(call_sid)
        if not state:
            return await self.build_start_twiml(call_sid, from_number=from_number)

        config = None
        if state.hospital_id:
            config = await self.voice_config_service.get_entity(state.hospital_id)
        provider = ProviderFactory.from_hospital_config(config)
        pname = state.provider or provider.name
        vk = self._voice_kwargs(config)

        # Empty digits + speech → AI fallback path
        if not digits.strip() and speech_result.strip():
            resolution = await self.language_resolver.resolve_for_inbound(
                from_number=from_number or state.from_number,
                hospital_default=config.default_language if config else "en",
                speech_for_fallback=speech_result,
                allow_ai_fallback=True,
            )
            state.language = resolution.language
            state.language_locked = True
            state.language_source = resolution.source
            state.patient_id = resolution.patient_id or state.patient_id
            state.step = VoiceStep.INTENT
            await self._ensure_inbound_call(state)
            turn = self.assistant.start_call(state)
            await self.save_state(turn.state)
            return provider.render_response(self._build_gather_twiml(turn, config))

        resolution = await self.language_resolver.resolve_for_inbound(
            from_number=from_number or state.from_number,
            hospital_default=config.default_language if config else "en",
            dtmf_digit=digits.strip(),
        )
        if resolution.source == "dtmf":
            state.language = resolution.language
            state.language_locked = True
            state.language_source = "dtmf"
            state.patient_id = resolution.patient_id or state.patient_id
            state.step = VoiceStep.INTENT
            await self._ensure_inbound_call(state)
            turn = self.assistant.start_call(state)
            await self.save_state(turn.state)
            return provider.render_response(self._build_gather_twiml(turn, config))

        lang = twilio_say_language(state.language)
        action = self._assistant_url("/language", pname)
        timeout_url = self._assistant_url("/turn", pname)
        prompt = language_select_prompt(state.language)
        await self.save_state(state)
        return provider.render_response(
            twiml_response(
                gather(
                    action,
                    prompt,
                    num_digits=1,
                    language=lang,
                    timeout_redirect_url=timeout_url,
                    **vk,
                )
            )
        )

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

        # Language still unlocked (DTMF timeout redirected here) → AI fallback once
        if not state.language_locked and (speech_result or digits):
            resolution = await self.language_resolver.resolve_for_inbound(
                from_number=from_number or state.from_number,
                hospital_default=state.language or "en",
                speech_for_fallback=speech_result or digits,
                allow_ai_fallback=True,
            )
            if resolution.source in ("ai_fallback", "preferred", "temp_store", "dtmf"):
                state.language = resolution.language
                state.language_locked = True
                state.language_source = resolution.source
                state.patient_id = resolution.patient_id or state.patient_id
                if state.step == VoiceStep.LANGUAGE_SELECT:
                    state.step = VoiceStep.INTENT

        config = None
        if state.hospital_id:
            config = await self.voice_config_service.get_entity(state.hospital_id)
        provider = ProviderFactory.from_hospital_config(config)
        vk = self._voice_kwargs(config)

        transcript = (speech_result or "").strip()
        if not transcript and digits:
            transcript = digits
        conf_val = None
        if confidence:
            try:
                conf_val = float(confidence)
            except (TypeError, ValueError):
                conf_val = None

        await self._ensure_inbound_call(state)

        safety = MedicalSafetyGuard.check(transcript, state.language)
        if safety.is_medical_advice:
            state.transfer_requested = True
            state.step = VoiceStep.TRANSFER
            await self.save_state(state)
            await self._finalize_inbound_call(state)
            return await self._do_transfer(
                state,
                config,
                provider,
                reason="medical_advice_refused",
                preface=safety.refusal_message,
            )

        if state.step == VoiceStep.FAQ_QUESTION and transcript:
            hospital_id = state.hospital_id
            if not hospital_id:
                res = await self.voice_config_service.resolve_inbound_hospital(
                    to_number=getattr(state, "to_number", "") or "",
                )
                hospital_id = res.hospital_id
                if hospital_id:
                    state.hospital_id = hospital_id
            if hospital_id:
                faq = await self.faq_service.answer(
                    hospital_id,
                    transcript,
                    state.language,
                    session_id=state.call_sid or None,
                )
                state.faq_hit = faq.faq_hit
                state.ai_fallback = faq.ai_fallback
                state.last_confidence = faq.confidence
                state.intent = VoiceIntent.HOSPITAL_INFO
                if faq.should_transfer:
                    state.transfer_requested = True
                    state.step = VoiceStep.TRANSFER
                    await self.save_state(state)
                    await self._finalize_inbound_call(state)
                    return await self._do_transfer(
                        state,
                        config,
                        provider,
                        reason=faq.transfer_reason or "faq_low_confidence",
                        preface=faq.answer,
                    )
                state.step = VoiceStep.DONE
                await self.save_state(state)
                await self._finalize_inbound_call(state)
                lang = twilio_say_language(state.language)
                return provider.render_response(
                    twiml_response(say(faq.answer, lang, **vk), hangup())
                )
            state.step = VoiceStep.DONE
            await self.save_state(state)
            await self._finalize_inbound_call(state)
            lang = twilio_say_language(state.language)
            return provider.render_response(
                twiml_response(say(prompts.hospital_info(state.language), lang, **vk), hangup())
            )

        turn = self.assistant.process_turn(state, transcript, confidence=conf_val)

        if turn.state.language_locked and turn.state.language_source == "dtmf":
            await self.language_resolver.persist_language(
                turn.state.from_number or turn.state.mobile_number or "",
                turn.state.language,
                patient_id=turn.state.patient_id,
            )

        if turn.state.transfer_requested or turn.state.step == VoiceStep.TRANSFER:
            await self.save_state(turn.state)
            await self._finalize_inbound_call(turn.state)
            return await self._do_transfer(
                turn.state, config, provider, reason="patient_requested_reception"
            )

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

        await self._ensure_inbound_call(turn.state)
        await self.save_state(turn.state)

        if turn.hangup:
            await self._finalize_inbound_call(turn.state)
            lang = twilio_say_language(turn.state.language)
            return provider.render_response(
                twiml_response(say(turn.prompt, lang, **vk), hangup())
            )

        return provider.render_response(self._build_gather_twiml(turn, config))

    async def handle_transfer_result(
        self,
        call_sid: str,
        dial_status: str = "",
        from_number: str = "",
    ) -> str:
        state = await self.load_state(call_sid)
        config = None
        if state and state.hospital_id:
            config = await self.voice_config_service.get_entity(state.hospital_id)
        provider = ProviderFactory.from_hospital_config(config)
        result = await self.transfer_service.handle_dial_status(
            dial_status=dial_status,
            from_number=(state.from_number if state else from_number) or "",
            language=(state.language if state else "en"),
            hospital_id=state.hospital_id if state else None,
            patient_id=state.patient_id if state else None,
            call_id=state.voice_call_id if state else None,
            provider=provider,
        )
        if state:
            state.transfer_requested = True
            if state.voice_call_id:
                call = await self.voice_repo.get_call(state.voice_call_id)
                if call:
                    call.transferred_to_reception = True
                    call.transfer_status = result.transfer_status
                    call.call_status = VoiceCallStatus.COMPLETED
                    await self.voice_repo.update_call(call)
            await self.save_state(state)
            # Queue callback processing when reception busy
            if result.ticket_id:
                try:
                    from app.tasks.voice_tasks import process_reception_callback_tickets
                    from app.utils.redis_service import redis_cooldown_active

                    if redis_cooldown_active():
                        logger.info(
                            "callback_enqueue_skipped call_sid=%s ticket_id=%s reason=redis_unavailable",
                            state.call_sid,
                            result.ticket_id,
                        )
                    else:
                        process_reception_callback_tickets.delay()
                except Exception as exc:
                    logger.warning(
                        "callback_enqueue_failed call_sid=%s ticket_id=%s error=%s",
                        state.call_sid,
                        result.ticket_id,
                        exc,
                    )
        return provider.render_response(result.xml)

    async def _do_transfer(
        self,
        state: VoiceState,
        config,
        provider,
        reason: str,
        preface: str | None = None,
    ) -> str:
        pname = state.provider or provider.name
        action = self._assistant_url("/transfer-result", pname)
        vk = self._voice_kwargs(config)
        result = await self.transfer_service.transfer(
            reception_number=getattr(config, "reception_number", None) if config else None,
            from_number=state.from_number or state.mobile_number or "",
            language=state.language,
            hospital_id=state.hospital_id,
            patient_id=state.patient_id,
            call_id=state.voice_call_id,
            reason=reason,
            provider=provider,
            action_url=action,
        )
        if result.ticket_id:
            try:
                from app.tasks.voice_tasks import process_reception_callback_tickets
                from app.utils.redis_service import redis_cooldown_active

                if redis_cooldown_active():
                    logger.info(
                        "callback_enqueue_skipped call_sid=%s ticket_id=%s reason=redis_unavailable",
                        state.call_sid,
                        result.ticket_id,
                    )
                else:
                    process_reception_callback_tickets.delay()
            except Exception as exc:
                logger.warning(
                    "callback_enqueue_failed call_sid=%s ticket_id=%s error=%s",
                    state.call_sid,
                    result.ticket_id,
                    exc,
                )
        lang = twilio_say_language(state.language)
        if preface:
            xml = result.xml
            if "<Response>" in xml:
                xml = xml.replace(
                    "<Response>",
                    f"<Response>{say(preface, lang, **vk)}",
                    1,
                )
            else:
                xml = twiml_response(say(preface, lang, **vk)) + xml
            return provider.render_response(xml)
        return provider.render_response(result.xml)

    def _build_gather_twiml(self, turn, config=None) -> str:
        lang = twilio_say_language(turn.state.language)
        pname = turn.state.provider
        vk = self._voice_kwargs(config)
        if turn.state.step == VoiceStep.LANGUAGE_SELECT:
            action = self._assistant_url("/language", pname)
            timeout_url = self._assistant_url("/turn", pname)
            return twiml_response(
                gather(
                    action,
                    turn.prompt,
                    num_digits=1,
                    language=lang,
                    timeout_redirect_url=timeout_url,
                    **vk,
                )
            )
        action = self._assistant_url("/turn", pname)
        dtmf_hint = ""
        if turn.use_dtmf_menu or turn.state.step == VoiceStep.INTENT:
            dtmf_hint = (
                " Press 1 to book, 2 to reschedule, 3 to cancel, "
                "4 for reception, 5 for hospital information."
            )
        prompt = turn.prompt + dtmf_hint
        hints = "appointment, doctor, book, cancel, reschedule, reception"
        return twiml_response(
            gather_speech_or_dtmf(action, prompt, language=lang, hints=hints, **vk)
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
            state.step = VoiceStep.BOOK_TIME
            state.booking_completed = False
            logger.warning("Slot conflict for voice booking call_sid=%s", state.call_sid)
        except Exception as exc:
            logger.error("Voice booking finalize error: %s", exc)
            state.pending_booking = True

    async def _book_appointment(self, state: VoiceState, payload: VoiceBookingPayload) -> None:
        from app.services.voice_patient_resolver import VoicePatientResolver

        phone = state.mobile_number or state.from_number
        spoken_name = payload.patient_name or state.patient_name
        if not phone and not spoken_name:
            state.pending_booking = True
            return

        attendee, holder = await VoicePatientResolver(self.db).resolve_for_booking(
            phone=phone,
            spoken_name=spoken_name,
        )

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
            patient_id=attendee.id,
            doctor_id=doctor.id,
            appointment_date=appt_date,
            appointment_time=appt_time,
            booking_source=BookingSource.AI_VOICE,
            symptoms=state.symptoms,
            consultation_type="in_person",
            notes=(
                f"Booked via voice assistant. "
                f"Spoken name: {spoken_name or attendee.first_name}. "
                f"Booked by patient_id={holder.id}."
            ),
        )
        await AppointmentService(self.db).create(data, user_id=holder.user_id or 0)
        state.patient_id = attendee.id
        state.doctor_id = doctor.id
        state.booking_completed = True
        await self.language_resolver.promote_temp_language_to_patient(
            state.mobile_number or state.from_number or "",
            holder.id,
        )
        if holder.preferred_language is None and state.language_locked:
            holder.preferred_language = state.language

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
        return await self.patient_repo.get_by_phone(mobile)

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
