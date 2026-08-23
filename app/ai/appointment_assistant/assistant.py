import json
import re
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.appointment_assistant.prompts import booking_system_prompt
from app.ai.appointment_assistant.schemas import BookingState, BookingStep, BookingTurnResult, SuggestedSlot
from app.ai.symptom_analysis.analyzer import SymptomAnalyzer
from app.core.constants import BookingSource
from app.core.exceptions import ConflictException
from app.models.chat_model import ChatSession
from app.repositories.chat_repository import ChatRepository
from app.repositories.doctor_repository import DoctorRepository
from app.schemas.appointment_schema import AppointmentCreate
from app.services.appointment_service import AppointmentService
from app.utils.ai_llm import llm_service

SPECIALIST_ALIASES = {
    "general_physician": ["general", "physician", "family"],
    "cardiologist": ["cardio", "heart"],
    "pulmonologist": ["pulmo", "lung", "respiratory"],
    "neurologist": ["neuro", "brain"],
    "gastroenterologist": ["gastro", "stomach", "digest"],
}

DEFAULT_SLOTS = [
    time(9, 0),
    time(10, 0),
    time(11, 0),
    time(14, 0),
    time(15, 0),
    time(16, 0),
]

CONFIRM_WORDS = {"yes", "confirm", "ok", "okay", "book", "proceed", "y"}
CANCEL_WORDS = {"no", "cancel", "stop", "nevermind", "n"}


class AppointmentAssistant:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.chat_repo = ChatRepository(db)
        self.doctor_repo = DoctorRepository(db)
        self.symptom_analyzer = SymptomAnalyzer()

    async def handle_turn(
        self,
        session: ChatSession,
        message: str,
        user_id: int,
        language: str = "en",
    ) -> BookingTurnResult:
        state = await self._load_state(session)
        entities = await llm_service.extract_booking_entities(message, language=language)
        self._merge_entities(state, entities, message)

        if state.step == BookingStep.BOOKED:
            return BookingTurnResult(
                message="Your appointment is already booked. Need anything else?",
                booking_state=state,
            )

        if self._is_confirm(message) and state.step == BookingStep.CONFIRM:
            return await self._finalize_booking(session, state, user_id)

        if self._is_cancel(message) and state.step == BookingStep.CONFIRM:
            state.step = BookingStep.PICK_SLOT
            await self._save_state(session, state)
            return BookingTurnResult(
                message="No problem. Please tell me your preferred date and time.",
                booking_state=state,
            )

        if state.step == BookingStep.COLLECT_SYMPTOMS:
            return await self._step_symptoms(session, state, message, language)
        if state.step == BookingStep.SUGGEST_SPECIALIST:
            return await self._step_specialist(session, state, language)
        if state.step == BookingStep.PICK_DOCTOR:
            return await self._step_doctor(session, state, message, language)
        if state.step == BookingStep.PICK_SLOT:
            return await self._step_slot(session, state, message, language)
        if state.step == BookingStep.CONFIRM:
            return await self._step_confirm(session, state, language)

        return BookingTurnResult(
            message="How can I help you book an appointment?",
            booking_state=state,
        )

    async def get_booking_state(self, session: ChatSession) -> Optional[BookingState]:
        return await self._load_state(session)

    async def _step_symptoms(
        self, session: ChatSession, state: BookingState, message: str, language: str
    ) -> BookingTurnResult:
        if not state.symptoms:
            symptom_tokens = self._extract_symptom_tokens(message)
            if symptom_tokens:
                analysis = await self.symptom_analyzer.analyze(symptom_tokens)
                state.symptoms = ", ".join(symptom_tokens)
                state.recommended_specialist = analysis.get("recommended_specialist", "general_physician")
                state.step = BookingStep.SUGGEST_SPECIALIST
                await self._save_state(session, state)
                return await self._step_specialist(session, state, language)

            return BookingTurnResult(
                message=(
                    "I can help you book an appointment. "
                    "Please describe your symptoms, or say which doctor or specialty you need."
                ),
                booking_state=state,
            )

        state.step = BookingStep.SUGGEST_SPECIALIST
        await self._save_state(session, state)
        return await self._step_specialist(session, state, language)

    async def _step_specialist(
        self, session: ChatSession, state: BookingState, language: str
    ) -> BookingTurnResult:
        specialist = state.recommended_specialist or "general_physician"
        doctors = await self._find_doctors(specialist)
        if not doctors:
            doctors = await self.doctor_repo.list_available()

        if not doctors:
            return BookingTurnResult(
                message="Sorry, no doctors are available right now. Please try again later or contact reception.",
                booking_state=state,
            )

        if len(doctors) == 1:
            doc = doctors[0]
            state.doctor_id = doc.id
            state.doctor_name = f"Dr. {doc.first_name} {doc.last_name}"
            state.step = BookingStep.PICK_SLOT
            await self._save_state(session, state)
            return BookingTurnResult(
                message=(
                    f"I recommend {state.doctor_name} ({doc.specialization}). "
                    "What date and time work for you? For example: tomorrow at 10 AM."
                ),
                booking_state=state,
                suggested_slots=await self._suggest_slots(doc.id, doc.first_name, doc.last_name, doc.specialization),
            )

        listing = "\n".join(
            f"{i + 1}. Dr. {d.first_name} {d.last_name} — {d.specialization}"
            for i, d in enumerate(doctors[:5])
        )
        state.step = BookingStep.PICK_DOCTOR
        await self._save_state(session, state)
        return BookingTurnResult(
            message=(
                f"Based on your needs, we suggest a {specialist.replace('_', ' ')}. "
                f"Available doctors:\n{listing}\n"
                "Reply with the doctor number or name."
            ),
            booking_state=state,
        )

    async def _step_doctor(
        self, session: ChatSession, state: BookingState, message: str, language: str
    ) -> BookingTurnResult:
        specialist = state.recommended_specialist or "general_physician"
        doctors = await self._find_doctors(specialist)
        if not doctors:
            doctors = await self.doctor_repo.list_available()

        selected = self._match_doctor_choice(message, doctors)
        if state.doctor_id and not selected:
            doc = await self.doctor_repo.get_by_id(state.doctor_id)
            if doc:
                selected = doc

        if not selected:
            return BookingTurnResult(
                message="I didn't catch which doctor you want. Please reply with the number or doctor's name.",
                booking_state=state,
            )

        state.doctor_id = selected.id
        state.doctor_name = f"Dr. {selected.first_name} {selected.last_name}"
        state.step = BookingStep.PICK_SLOT
        await self._save_state(session, state)
        return BookingTurnResult(
            message=f"Great, {state.doctor_name}. What date and time would you prefer?",
            booking_state=state,
            suggested_slots=await self._suggest_slots(
                selected.id, selected.first_name, selected.last_name, selected.specialization
            ),
        )

    async def _step_slot(
        self, session: ChatSession, state: BookingState, message: str, language: str
    ) -> BookingTurnResult:
        if not state.appointment_date or not state.appointment_time:
            parsed_date, parsed_time = self._parse_datetime_from_text(message)
            if parsed_date:
                state.appointment_date = parsed_date
            if parsed_time:
                state.appointment_time = parsed_time

        if not state.doctor_id:
            state.step = BookingStep.PICK_DOCTOR
            await self._save_state(session, state)
            return BookingTurnResult(
                message="Please choose a doctor first.",
                booking_state=state,
            )

        if not state.appointment_date or not state.appointment_time:
            slots = []
            if state.doctor_id:
                doc = await self.doctor_repo.get_by_id(state.doctor_id)
                if doc:
                    slots = await self._suggest_slots(
                        doc.id, doc.first_name, doc.last_name, doc.specialization
                    )
            return BookingTurnResult(
                message="Please provide a date and time (e.g. 2026-05-25 at 10:00 or tomorrow at 2 PM).",
                booking_state=state,
                suggested_slots=slots,
            )

        state.step = BookingStep.CONFIRM
        await self._save_state(session, state)
        return await self._step_confirm(session, state, language)

    async def _step_confirm(
        self, session: ChatSession, state: BookingState, language: str
    ) -> BookingTurnResult:
        summary = (
            f"Please confirm your appointment:\n"
            f"- Doctor: {state.doctor_name}\n"
            f"- Date: {state.appointment_date}\n"
            f"- Time: {state.appointment_time}\n"
            f"- Symptoms: {state.symptoms or 'Not specified'}\n"
            "Reply YES to confirm or NO to change the time."
        )
        return BookingTurnResult(
            message=summary,
            booking_state=state,
            requires_confirmation=True,
        )

    async def _finalize_booking(
        self, session: ChatSession, state: BookingState, user_id: int
    ) -> BookingTurnResult:
        if not state.doctor_id or not state.appointment_date or not state.appointment_time:
            state.step = BookingStep.PICK_SLOT
            await self._save_state(session, state)
            return BookingTurnResult(
                message="I still need a doctor, date, and time before I can book.",
                booking_state=state,
            )

        payload = AppointmentCreate(
            patient_id=state.patient_id,
            doctor_id=state.doctor_id,
            department_id=state.department_id,
            appointment_date=state.appointment_date,
            appointment_time=state.appointment_time,
            symptoms=state.symptoms,
            consultation_type=state.consultation_type,
            booking_source=BookingSource.AI_CHAT,
        )
        try:
            appointment = await AppointmentService(self.db).create(payload, user_id)
        except ConflictException:
            state.step = BookingStep.PICK_SLOT
            state.appointment_time = None
            await self._save_state(session, state)
            return BookingTurnResult(
                message="That slot is no longer available. Please choose another date and time.",
                booking_state=state,
            )

        state.step = BookingStep.BOOKED
        await self._save_state(session, state)
        await self.chat_repo.upsert_memory(session.id, "last_appointment_id", str(appointment.id))

        appt_data = appointment.model_dump(mode="json")
        return BookingTurnResult(
            message=(
                f"Your appointment is confirmed! Reference: {appointment.appointment_number}. "
                f"Token #{appointment.token_number} on {appointment.appointment_date} at {appointment.appointment_time}."
            ),
            booking_state=state,
            appointment=appt_data,
        )

    async def _load_state(self, session: ChatSession) -> BookingState:
        memories = await self.chat_repo.get_memories(session.id)
        for mem in memories:
            if mem.memory_key == "booking_state":
                return BookingState.from_dict(json.loads(mem.memory_value))
        return BookingState(step=BookingStep.COLLECT_SYMPTOMS, patient_id=session.patient_id)

    async def _save_state(self, session: ChatSession, state: BookingState) -> None:
        await self.chat_repo.upsert_memory(
            session.id, "booking_state", json.dumps(state.to_dict())
        )

    async def _find_doctors(self, specialist: str) -> list:
        doctors = await self.doctor_repo.list_available()
        if not doctors:
            return []
        aliases = SPECIALIST_ALIASES.get(specialist, [specialist.replace("_", " ")])
        matched = [
            d
            for d in doctors
            if any(
                alias in (d.specialization or "").lower() or alias in (d.department or "").lower()
                for alias in aliases
            )
        ]
        return matched or doctors[:5]

    async def _suggest_slots(
        self, doctor_id: int, first_name: str, last_name: str, specialization: str
    ) -> List[SuggestedSlot]:
        target_date = date.today() + timedelta(days=1)
        slots = []
        for slot_time in DEFAULT_SLOTS[:3]:
            slots.append(
                SuggestedSlot(
                    doctor_id=doctor_id,
                    doctor_name=f"Dr. {first_name} {last_name}",
                    specialization=specialization,
                    appointment_date=target_date,
                    appointment_time=slot_time,
                )
            )
        return slots

    def _merge_entities(self, state: BookingState, entities: Dict[str, Any], message: str) -> None:
        if entities.get("symptoms"):
            state.symptoms = entities["symptoms"]
        if entities.get("doctor_id"):
            try:
                state.doctor_id = int(entities["doctor_id"])
            except (TypeError, ValueError):
                pass
        if entities.get("doctor_name"):
            state.doctor_name = entities["doctor_name"]
        if entities.get("appointment_date"):
            try:
                state.appointment_date = date.fromisoformat(str(entities["appointment_date"])[:10])
            except ValueError:
                pass
        if entities.get("appointment_time"):
            try:
                parts = str(entities["appointment_time"]).split(":")
                state.appointment_time = time(int(parts[0]), int(parts[1]))
            except (ValueError, IndexError):
                pass
        if entities.get("recommended_specialist"):
            state.recommended_specialist = entities["recommended_specialist"]

        parsed_date, parsed_time = self._parse_datetime_from_text(message)
        if parsed_date and not state.appointment_date:
            state.appointment_date = parsed_date
        if parsed_time and not state.appointment_time:
            state.appointment_time = parsed_time

    def _extract_symptom_tokens(self, message: str) -> List[str]:
        lowered = message.lower()
        found = []
        for pattern in SymptomAnalyzer.SYMPTOM_MAP:
            if pattern in lowered:
                found.append(pattern)
        if not found and len(message.split()) >= 2:
            return [message.strip()]
        return found

    def _match_doctor_choice(self, message: str, doctors: list):
        msg = message.strip().lower()
        if msg.isdigit():
            idx = int(msg) - 1
            if 0 <= idx < len(doctors):
                return doctors[idx]
        for doc in doctors:
            full = f"{doc.first_name} {doc.last_name}".lower()
            if doc.first_name.lower() in msg or doc.last_name.lower() in msg or full in msg:
                return doc
        return None

    def _parse_datetime_from_text(self, text: str) -> tuple[Optional[date], Optional[time]]:
        lowered = text.lower()
        target_date = None
        if "tomorrow" in lowered:
            target_date = date.today() + timedelta(days=1)
        elif "today" in lowered:
            target_date = date.today()

        iso_date = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        if iso_date:
            try:
                target_date = date.fromisoformat(iso_date.group(1))
            except ValueError:
                pass

        target_time = None
        match_12h = re.search(r"(\d{1,2})\s*(?::(\d{2}))?\s*(am|pm)", lowered)
        if match_12h:
            hour = int(match_12h.group(1))
            minute = int(match_12h.group(2) or 0)
            if match_12h.group(3) == "pm" and hour < 12:
                hour += 12
            if match_12h.group(3) == "am" and hour == 12:
                hour = 0
            target_time = time(hour, minute)
        else:
            match_24h = re.search(r"(\d{1,2}):(\d{2})", text)
            if match_24h:
                target_time = time(int(match_24h.group(1)), int(match_24h.group(2)))

        return target_date, target_time

    def _is_confirm(self, message: str) -> bool:
        return message.strip().lower() in CONFIRM_WORDS

    def _is_cancel(self, message: str) -> bool:
        return message.strip().lower() in CANCEL_WORDS
