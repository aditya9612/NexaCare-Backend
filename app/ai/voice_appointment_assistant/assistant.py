import logging
import re
from datetime import date, time, timedelta
from typing import List, Optional, Tuple

from app.agent.llm import extract_patient_name, extract_problem
from app.ai.voice_appointment_assistant import prompts
from app.ai.voice_appointment_assistant.emergency import emergency_message, is_emergency

logger = logging.getLogger("nexacare.agent.assistant")
from app.ai.voice_appointment_assistant.schemas import (
    VoiceBookingPayload,
    VoiceIntent,
    VoiceState,
    VoiceStep,
    VoiceTurnResult,
)

INTENT_KEYWORDS = {
    VoiceIntent.BOOK: {
        "en": ["book", "appointment", "schedule", "new appointment"],
        "hi": ["बुक", "अपॉइंटमेंट", "नियुक्ति", "मिलना"],
        "mr": ["बुक", "अपॉइंटमेंट", "भेट", "वेळ"],
    },
    VoiceIntent.RESCHEDULE: {
        "en": ["reschedule", "change appointment", "move appointment"],
        "hi": ["बदल", "रीशेड्यूल", "समय बदल"],
        "mr": ["बदल", "रीशेड्यूल", "वेळ बदल"],
    },
    VoiceIntent.CANCEL: {
        "en": ["cancel", "cancellation"],
        "hi": ["रद्द", "कैंसल"],
        "mr": ["रद्द", "कॅन्सल"],
    },
    VoiceIntent.AVAILABILITY: {
        "en": ["available", "availability", "doctor free", "which doctor"],
        "hi": ["उपलब्ध", "डॉक्टर", "समय"],
        "mr": ["उपलब्ध", "डॉक्टर"],
    },
    VoiceIntent.HOSPITAL_INFO: {
        "en": ["hours", "timing", "location", "address", "contact", "open", "fee", "fees", "faq"],
        "hi": ["समय", "घंटे", "पता", "स्थान", "संपर्क", "खुला", "शुल्क"],
        "mr": ["वेळ", "पत्ता", "संपर्क", "उघडे", "शुल्क"],
    },
    VoiceIntent.RECEPTION: {
        "en": [
            "reception",
            "receptionist",
            "talk to someone",
            "speak to someone",
            "human",
            "operator",
            "transfer",
            "agent",
        ],
        "hi": ["रिसेप्शन", "रिसेप्शनिस्ट", "व्यक्ति से बात", "ट्रांसफर"],
        "mr": ["रिसेप्शन", "व्यक्तीशी बोला", "ट्रान्सफर"],
    },
}

CONFIRM_WORDS = {
    "yes", "yeah", "yep", "confirm", "ok", "okay", "book", "proceed", "1",
    "haan", "ha", "हाँ", "हां", "ठीक", "होय", "बरोबर", "1",
}
CANCEL_WORDS = {"no", "nope", "cancel", "stop", "2", "नहीं", "नाही", "2"}
SLOW_WORDS = {"slow", "slowly", "repeat", "again", "धीरे", "पुन्हा", "दोहरा"}


class VoiceAppointmentAssistant:
    """Multilingual voice receptionist state machine (one question per turn)."""

    def process_turn(
        self,
        state: VoiceState,
        transcript: str,
        confidence: float | None = None,
    ) -> VoiceTurnResult:
        text = (transcript or "").strip()
        logger.info(f"Processing turn - State: {state.step.name}, Transcript: {text}")
        # Language is locked after LanguageResolver / DTMF — never auto-switch mid-call.
        if text and not state.language_locked:
            # Secondary AI fallback only when language is not yet locked (speech-only edge case).
            from app.ai.voice_appointment_assistant.language import detect_language

            state.language = detect_language(text, state.language)
            state.language_source = state.language_source or "ai_fallback"

        if state.step == VoiceStep.LANGUAGE_SELECT:
            return self._handle_language_select(state, text)

        if state.step == VoiceStep.EMERGENCY:
            return VoiceTurnResult(
                prompt=emergency_message(state.language),
                state=state,
                hangup=True,
            )

        if text and is_emergency(text):
            state.step = VoiceStep.EMERGENCY
            return VoiceTurnResult(
                prompt=emergency_message(state.language),
                state=state,
                hangup=True,
            )

        # Reception transfer: speech anytime; DTMF 4 on menu / greet steps only
        wants_reception_speech = bool(text) and self._detect_intent(text) == VoiceIntent.RECEPTION
        wants_reception_dtmf = (
            text.strip() == "4"
            and state.step in (VoiceStep.INTENT, VoiceStep.GREET, VoiceStep.LANGUAGE_SELECT)
        )
        if wants_reception_speech or wants_reception_dtmf:
            state.intent = VoiceIntent.RECEPTION
            state.step = VoiceStep.TRANSFER
            state.transfer_requested = True
            return VoiceTurnResult(
                prompt=prompts.transferring_to_reception(state.language),
                state=state,
                hangup=False,
            )

        if text and any(w in text.lower() for w in SLOW_WORDS):
            return VoiceTurnResult(
                prompt=prompts.repeat_slowly(state.language) + " " + self._repeat_current_question(state),
                state=state,
            )

        if not text or (confidence is not None and confidence < 0.4):
            return VoiceTurnResult(
                prompt=prompts.could_not_hear(state.language),
                state=state,
            )

        if state.step == VoiceStep.GREET:
            return self._after_greet(state, text)

        if state.step == VoiceStep.INTENT:
            return self._handle_intent_choice(state, text)

        if state.step == VoiceStep.FAQ_QUESTION:
            state.faq_answer = text
            state.step = VoiceStep.DONE
            return VoiceTurnResult(
                prompt=text,
                state=state,
                hangup=False,
            )

        handlers = {
            VoiceStep.BOOK_NAME: self._book_name,
            VoiceStep.BOOK_DOCTOR: self._book_doctor,
            VoiceStep.BOOK_SYMPTOMS: self._book_symptoms,
            VoiceStep.BOOK_DATE: self._book_date,
            VoiceStep.BOOK_TIME: self._book_time,
            VoiceStep.BOOK_MOBILE: self._book_mobile,
            VoiceStep.BOOK_CONFIRM: self._book_confirm,
            VoiceStep.RESCHEDULE_MOBILE: self._reschedule_mobile,
            VoiceStep.RESCHEDULE_DATE: self._reschedule_date,
            VoiceStep.RESCHEDULE_TIME: self._reschedule_time,
            VoiceStep.RESCHEDULE_CONFIRM: self._reschedule_confirm,
            VoiceStep.CANCEL_MOBILE: self._cancel_mobile,
            VoiceStep.CANCEL_CONFIRM: self._cancel_confirm,
            VoiceStep.AVAILABILITY_QUERY: self._availability_query,
            VoiceStep.DONE: self._done,
            VoiceStep.TRANSFER: self._transfer_step,
        }
        handler = handlers.get(state.step)
        if handler:
            return handler(state, text)

        return VoiceTurnResult(prompt=prompts.intent_menu(state.language), state=state)

    def start_call(self, state: VoiceState) -> VoiceTurnResult:
        if not state.language_locked:
            state.step = VoiceStep.LANGUAGE_SELECT
            from app.ai.voice_appointment_assistant.language import language_select_prompt

            return VoiceTurnResult(
                prompt=language_select_prompt(state.language),
                state=state,
                use_dtmf_menu=True,
            )
        state.step = VoiceStep.INTENT
        greeting = prompts.greeting(state.language)
        menu = prompts.intent_menu(state.language)
        return VoiceTurnResult(prompt=f"{greeting} {menu}", state=state, use_dtmf_menu=True)

    def _handle_language_select(self, state: VoiceState, text: str) -> VoiceTurnResult:
        from app.core.constants import VoiceLanguage

        digit = text.strip()
        if digit in VoiceLanguage.DTMF_MAP:
            state.language = VoiceLanguage.DTMF_MAP[digit]
            state.language_locked = True
            state.language_source = "dtmf"
            state.step = VoiceStep.INTENT
            greeting = prompts.greeting(state.language)
            menu = prompts.intent_menu(state.language)
            return VoiceTurnResult(
                prompt=f"{greeting} {menu}",
                state=state,
                use_dtmf_menu=True,
            )
        from app.ai.voice_appointment_assistant.language import language_select_prompt

        return VoiceTurnResult(
            prompt=language_select_prompt(state.language),
            state=state,
            use_dtmf_menu=True,
        )

    def _transfer_step(self, state: VoiceState, text: str) -> VoiceTurnResult:
        state.transfer_requested = True
        state.step = VoiceStep.TRANSFER
        return VoiceTurnResult(
            prompt=prompts.transferring_to_reception(state.language),
            state=state,
        )

    def _after_greet(self, state: VoiceState, text: str) -> VoiceTurnResult:
        intent = self._detect_intent(text)
        if intent == VoiceIntent.UNKNOWN:
            state.step = VoiceStep.INTENT
            return VoiceTurnResult(prompt=prompts.intent_menu(state.language), state=state)
        return self._start_intent_flow(state, intent)

    def _handle_intent_choice(self, state: VoiceState, text: str) -> VoiceTurnResult:
        if text.strip() == "1":
            return self._start_intent_flow(state, VoiceIntent.BOOK)
        if text.strip() == "2":
            return self._start_intent_flow(state, VoiceIntent.RESCHEDULE)
        if text.strip() == "3":
            return self._start_intent_flow(state, VoiceIntent.CANCEL)
        if text.strip() == "4":
            return self._start_intent_flow(state, VoiceIntent.RECEPTION)
        if text.strip() == "5":
            return self._start_intent_flow(state, VoiceIntent.HOSPITAL_INFO)

        intent = self._detect_intent(text)
        if intent == VoiceIntent.UNKNOWN:
            return VoiceTurnResult(
                prompt=prompts.intent_menu(state.language),
                state=state,
                use_dtmf_menu=True,
            )
        return self._start_intent_flow(state, intent)

    def _start_intent_flow(self, state: VoiceState, intent: VoiceIntent) -> VoiceTurnResult:
        state.intent = intent
        if intent == VoiceIntent.BOOK:
            state.step = VoiceStep.BOOK_NAME
            return VoiceTurnResult(prompt=prompts.ask_patient_name(state.language), state=state)
        if intent == VoiceIntent.RESCHEDULE:
            state.step = VoiceStep.RESCHEDULE_MOBILE
            return VoiceTurnResult(prompt=prompts.ask_mobile(state.language), state=state)
        if intent == VoiceIntent.CANCEL:
            state.step = VoiceStep.CANCEL_MOBILE
            return VoiceTurnResult(prompt=prompts.ask_mobile(state.language), state=state)
        if intent == VoiceIntent.AVAILABILITY:
            state.step = VoiceStep.AVAILABILITY_QUERY
            return VoiceTurnResult(prompt=prompts.ask_doctor(state.language), state=state)
        if intent == VoiceIntent.HOSPITAL_INFO:
            state.step = VoiceStep.FAQ_QUESTION
            return VoiceTurnResult(
                prompt=prompts.ask_faq_question(state.language),
                state=state,
            )
        if intent == VoiceIntent.RECEPTION:
            state.step = VoiceStep.TRANSFER
            state.transfer_requested = True
            return VoiceTurnResult(
                prompt=prompts.transferring_to_reception(state.language),
                state=state,
            )
        state.step = VoiceStep.INTENT
        return VoiceTurnResult(prompt=prompts.intent_menu(state.language), state=state)

    def _book_name(self, state: VoiceState, text: str) -> VoiceTurnResult:
        logger.info(f"Extracting name from raw transcript: {text}")
        result = extract_patient_name(text)
        if result.get("found") and result.get("name"):
            state.patient_name = result["name"]
            logger.info(f"Extracted name: {state.patient_name}")
            state.step = VoiceStep.BOOK_DOCTOR
            return VoiceTurnResult(prompt=prompts.ask_doctor(state.language), state=state)
        else:
            logger.info(f"Failed to extract name strictly from: {text}")
            return VoiceTurnResult(
                prompt=prompts.could_not_hear(state.language) + " " + prompts.ask_patient_name(state.language),
                state=state
            )

    def _book_doctor(self, state: VoiceState, text: str) -> VoiceTurnResult:
        state.doctor_or_department = text.strip()
        logger.info(f"Set doctor/department to: {state.doctor_or_department}")
        state.step = VoiceStep.BOOK_SYMPTOMS
        return VoiceTurnResult(prompt=prompts.ask_symptoms(state.language), state=state)

    def _book_symptoms(self, state: VoiceState, text: str) -> VoiceTurnResult:
        logger.info(f"Extracting problem from raw transcript: {text}")
        result = extract_problem(text)
        if result.get("found") and result.get("problem"):
            state.symptoms = result["problem"]
            logger.info(f"Extracted problem: {state.symptoms}")
            state.step = VoiceStep.BOOK_DATE
            return VoiceTurnResult(prompt=prompts.ask_date(state.language), state=state)
        else:
            logger.info(f"Failed to extract problem strictly from: {text}")
            return VoiceTurnResult(
                prompt=prompts.could_not_hear(state.language) + " " + prompts.ask_symptoms(state.language),
                state=state
            )

    def _book_date(self, state: VoiceState, text: str) -> VoiceTurnResult:
        parsed_date, _ = self._parse_datetime(text)
        if parsed_date:
            state.appointment_date = parsed_date.isoformat()
        else:
            state.appointment_date = text.strip()
        state.step = VoiceStep.BOOK_TIME
        return VoiceTurnResult(prompt=prompts.ask_time(state.language), state=state)

    def _book_time(self, state: VoiceState, text: str) -> VoiceTurnResult:
        _, parsed_time = self._parse_datetime(text)
        if parsed_time:
            state.appointment_time = parsed_time.strftime("%H:%M")
        else:
            state.appointment_time = text.strip()
        state.step = VoiceStep.BOOK_MOBILE
        if state.from_number and not state.mobile_number:
            digits = self._normalize_phone(state.from_number)
            if digits:
                state.mobile_number = digits
                state.step = VoiceStep.BOOK_CONFIRM
                return VoiceTurnResult(
                    prompt=prompts.confirmation_summary(state, state.language),
                    state=state,
                )
        return VoiceTurnResult(prompt=prompts.ask_mobile(state.language), state=state)

    def _book_mobile(self, state: VoiceState, text: str) -> VoiceTurnResult:
        phone = self._normalize_phone(text) or text.strip()
        state.mobile_number = phone
        state.step = VoiceStep.BOOK_CONFIRM
        return VoiceTurnResult(
            prompt=prompts.confirmation_summary(state, state.language),
            state=state,
        )

    def _book_confirm(self, state: VoiceState, text: str) -> VoiceTurnResult:
        lowered = text.lower().strip()
        if lowered in CONFIRM_WORDS or text.strip() == "1":
            state.step = VoiceStep.DONE
            state.booking_completed = True
            payload = VoiceBookingPayload.from_state(state)
            return VoiceTurnResult(
                prompt=prompts.booking_success(state.language),
                state=state,
                hangup=True,
                booking_json=payload,
            )
        if lowered in CANCEL_WORDS or text.strip() == "2":
            state.step = VoiceStep.BOOK_TIME
            return VoiceTurnResult(
                prompt=prompts.ask_time(state.language),
                state=state,
            )
        return VoiceTurnResult(
            prompt=prompts.confirmation_summary(state, state.language),
            state=state,
        )

    def _reschedule_mobile(self, state: VoiceState, text: str) -> VoiceTurnResult:
        state.mobile_number = self._normalize_phone(text) or text.strip()
        state.step = VoiceStep.RESCHEDULE_DATE
        return VoiceTurnResult(prompt=prompts.ask_date(state.language), state=state)

    def _reschedule_date(self, state: VoiceState, text: str) -> VoiceTurnResult:
        parsed_date, _ = self._parse_datetime(text)
        state.appointment_date = (parsed_date.isoformat() if parsed_date else text.strip())
        state.step = VoiceStep.RESCHEDULE_TIME
        return VoiceTurnResult(prompt=prompts.ask_time(state.language), state=state)

    def _reschedule_time(self, state: VoiceState, text: str) -> VoiceTurnResult:
        _, parsed_time = self._parse_datetime(text)
        state.appointment_time = (
            parsed_time.strftime("%H:%M") if parsed_time else text.strip()
        )
        state.step = VoiceStep.RESCHEDULE_CONFIRM
        return VoiceTurnResult(
            prompt=prompts.confirmation_summary(state, state.language),
            state=state,
        )

    def _reschedule_confirm(self, state: VoiceState, text: str) -> VoiceTurnResult:
        lowered = text.lower().strip()
        if lowered in CONFIRM_WORDS or text.strip() == "1":
            state.step = VoiceStep.DONE
            state.booking_completed = True
            return VoiceTurnResult(
                prompt=prompts.reschedule_success(state.language),
                state=state,
                hangup=True,
                booking_json=VoiceBookingPayload.from_state(state),
            )
        state.step = VoiceStep.RESCHEDULE_TIME
        return VoiceTurnResult(prompt=prompts.ask_time(state.language), state=state)

    def _cancel_mobile(self, state: VoiceState, text: str) -> VoiceTurnResult:
        state.mobile_number = self._normalize_phone(text) or text.strip()
        state.step = VoiceStep.CANCEL_CONFIRM
        return VoiceTurnResult(
            prompt={
                "en": "Should I cancel your upcoming appointment?",
                "hi": "क्या मैं आपका अपॉइंटमेंट रद्द करूँ?",
                "mr": "मी आपली अपॉइंटमेंट रद्द करू?",
            }.get(state.language, "Should I cancel your appointment?"),
            state=state,
        )

    def _cancel_confirm(self, state: VoiceState, text: str) -> VoiceTurnResult:
        lowered = text.lower().strip()
        if lowered in CONFIRM_WORDS or text.strip() == "1":
            state.step = VoiceStep.DONE
            state.booking_completed = True
            return VoiceTurnResult(
                prompt=prompts.cancel_success(state.language),
                state=state,
                hangup=True,
                booking_json=VoiceBookingPayload.from_state(state),
            )
        state.step = VoiceStep.INTENT
        return VoiceTurnResult(prompt=prompts.intent_menu(state.language), state=state)

    def _availability_query(self, state: VoiceState, text: str) -> VoiceTurnResult:
        state.doctor_or_department = text.strip()
        state.step = VoiceStep.DONE
        return VoiceTurnResult(
            prompt={
                "en": "Thank you. I will check availability and our team can confirm shortly. Goodbye.",
                "hi": "धन्यवाद। मैं उपलब्धता जांचूंगी और हमारी टीम जल्द पुष्टि करेगी। अलविदा।",
                "mr": "धन्यवाद. मी उपलब्धता तपासेन आणि आमची टीम लवकर पुष्टी करेल. नमस्कार.",
            }.get(state.language, "Thank you. Goodbye."),
            state=state,
            hangup=True,
        )

    def _done(self, state: VoiceState, text: str) -> VoiceTurnResult:
        return VoiceTurnResult(
            prompt=prompts.greeting(state.language),
            state=state,
            hangup=True,
        )

    def _detect_intent(self, text: str) -> VoiceIntent:
        lowered = text.lower()
        for intent, lang_map in INTENT_KEYWORDS.items():
            for keywords in lang_map.values():
                if any(kw in lowered for kw in keywords):
                    return intent
        return VoiceIntent.UNKNOWN

    def _repeat_current_question(self, state: VoiceState) -> str:
        step_prompts = {
            VoiceStep.BOOK_NAME: prompts.ask_patient_name,
            VoiceStep.BOOK_DOCTOR: prompts.ask_doctor,
            VoiceStep.BOOK_SYMPTOMS: prompts.ask_symptoms,
            VoiceStep.BOOK_DATE: prompts.ask_date,
            VoiceStep.BOOK_TIME: prompts.ask_time,
            VoiceStep.BOOK_MOBILE: prompts.ask_mobile,
            VoiceStep.BOOK_CONFIRM: lambda lang: prompts.confirmation_summary(state, lang),
            VoiceStep.RESCHEDULE_MOBILE: prompts.ask_mobile,
            VoiceStep.RESCHEDULE_DATE: prompts.ask_date,
            VoiceStep.RESCHEDULE_TIME: prompts.ask_time,
            VoiceStep.CANCEL_MOBILE: prompts.ask_mobile,
            VoiceStep.AVAILABILITY_QUERY: prompts.ask_doctor,
            VoiceStep.INTENT: prompts.intent_menu,
        }
        fn = step_prompts.get(state.step, prompts.intent_menu)
        return fn(state.language)

    def _parse_datetime(self, text: str) -> Tuple[Optional[date], Optional[time]]:
        lowered = text.lower()
        target_date = None
        if "tomorrow" in lowered or "कल" in lowered or "उद्या" in lowered:
            target_date = date.today() + timedelta(days=1)
        elif "today" in lowered or "आज" in lowered:
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

    def _normalize_phone(self, text: str) -> str:
        digits = "".join(c for c in text if c.isdigit())
        if len(digits) >= 10:
            return digits[-10:]
        return digits

    def match_doctor(self, doctors: list, query: str):
        if not query:
            return None
        q = query.lower()
        aliases = {
            "cardiologist": ["cardio", "heart", "हृदय"],
            "dentist": ["dental", "tooth", "दांत"],
            "general physician": ["general", "physician", "family", "सामान्य"],
            "orthopedic": ["ortho", "bone", "हाड"],
            "eye": ["eye", "ophthal", "आंख", "नेत्र"],
        }
        for doc in doctors:
            spec = (doc.specialization or "").lower()
            dept = (doc.department or "").lower()
            name = f"{doc.first_name} {doc.last_name}".lower()
            if q in spec or q in dept or q in name:
                return doc
            for _label, keys in aliases.items():
                if any(k in q for k in keys) and any(k in spec or k in dept for k in keys):
                    return doc
                if _label in q and (_label.split()[0] in spec or _label.split()[0] in dept):
                    return doc
        return doctors[0] if len(doctors) == 1 else None

    def format_availability(self, doctors: list, language: str, limit: int = 2) -> str:
        if not doctors:
            return {
                "en": "Sorry, no doctors are available right now.",
                "hi": "क्षमा करें, अभी कोई डॉक्टर उपलब्ध नहीं है।",
                "mr": "क्षमस्व, सध्या कोणतेही डॉक्टर उपलब्ध नाहीत.",
            }.get(language, "No doctors available.")
        names = [
            f"Dr. {d.first_name} {d.last_name}, {d.specialization}"
            for d in doctors[:limit]
        ]
        joined = " and ".join(names)
        return {
            "en": f"Available doctors include {joined}.",
            "hi": f"उपलब्ध डॉक्टर: {joined}.",
            "mr": f"उपलब्ध डॉक्टर: {joined}.",
        }.get(language, f"Available: {joined}.")
