"""
app/agent/nodes/booking.py
--------------------------
All booking-flow nodes.

Name + Problem collection uses Gemini LLM extraction (not rule-based).
Each field extraction has full positive + negative scenario handling.
After a successful booking, an SMS confirmation is sent to the caller.
"""

import os
import re
import logging
from datetime import date, timedelta, datetime
from xml.sax.saxutils import escape

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.agent.state import BookingCallState
from app.agent.llm import extract_patient_name, extract_problem, detect_specialty
from app.models.doctor_model import Doctor, DoctorSchedule

logger = logging.getLogger("nexacare.agent.nodes.booking")

MAX_RETRIES = 2


# ── SMS confirmation ───────────────────────────────────────────────────────────

SMS_TEMPLATES = {
    "en": (
        "NexaCare Appointment Confirmed!\n"
        "Patient: {name}\n"
        "Doctor: Dr. {doctor}\n"
        "Date: {date}\n"
        "Time: {time}\n"
        "Appt No: {appt_no}\n"
        "Please arrive 10 mins early. Reply CANCEL to cancel."
    ),
    "hi": (
        "NexaCare अपॉइंटमेंट कन्फर्म!\n"
        "मरीज: {name}\n"
        "डॉक्टर: Dr. {doctor}\n"
        "तारीख: {date}\n"
        "समय: {time}\n"
        "अपॉइंटमेंट नं: {appt_no}\n"
        "10 मिनट पहले आएं।"
    ),
    "mr": (
        "NexaCare अपॉइंटमेंट कन्फर्म!\n"
        "रुग्ण: {name}\n"
        "डॉक्टर: Dr. {doctor}\n"
        "तारीख: {date}\n"
        "वेळ: {time}\n"
        "अपॉइंटमेंट नं: {appt_no}\n"
        "10 मिनिटे आधी या."
    ),
}


def _plain_doctor_name(name: str) -> str:
    return re.sub(r"^Dr\.?\s*", "", (name or "").strip(), flags=re.IGNORECASE)


def _send_sms_confirmation(
    to_number: str,
    lang: str,
    name: str,
    doctor: str,
    appt_date: str,
    appt_time: str,
    appt_no: str,
) -> bool:
    """
    Send an SMS booking confirmation via shared sms_sender (no direct Twilio SDK).
    Returns True on success, False on failure (never raises — booking
    should not be rolled back because of an SMS failure).
    """
    try:
        import asyncio

        from app.utils.sms_sender import send_sms

        if not to_number:
            logger.warning("SMS skipped: missing caller number")
            return False

        template = SMS_TEMPLATES.get(lang, SMS_TEMPLATES["en"])
        body = template.format(
            name=name,
            doctor=_plain_doctor_name(doctor),
            date=appt_date,
            time=appt_time,
            appt_no=appt_no,
        )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Sync node inside async agent — schedule and wait briefly via new loop thread
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                ok = pool.submit(asyncio.run, send_sms(to_number, body)).result(timeout=30)
        else:
            ok = asyncio.run(send_sms(to_number, body))

        if ok:
            logger.info("SMS sent to %s", to_number)
        return bool(ok)

    except Exception as e:
        logger.warning(f"SMS failed (non-critical): {e}")
        return False


# ── Localised strings ─────────────────────────────────────────────────────────
STRINGS = {
    # Name collection
    "ask_name": {
        "en": "Please say your full name.",
        "hi": "कृपया अपना पूरा नाम बोलें।",
        "mr": "कृपया आपले पूर्ण नाव सांगा.",
    },
    "name_confirmed": {
        "en": "Got it. I have noted your name as {name}. ",
        "hi": "ठीक है। मैंने आपका नाम {name} नोट कर लिया है। ",
        "mr": "ठीक आहे. मी तुमचे नाव {name} नोंदवले आहे. ",
    },
    "name_not_found": {
        "en": "I could not catch your name clearly. Could you please say your name again?",
        "hi": "मुझे आपका नाम स्पष्ट नहीं सुना। कृपया अपना नाम फिर से बोलें।",
        "mr": "मला तुमचे नाव स्पष्ट ऐकू आले नाही. कृपया पुन्हा सांगा.",
    },
    # Problem collection
    "ask_problem": {
        "en": "Please describe the health problem or symptoms you are experiencing.",
        "hi": "कृपया अपनी स्वास्थ्य समस्या या लक्षण बताएं।",
        "mr": "कृपया तुमची आरोग्य समस्या किंवा लक्षणे सांगा.",
    },
    "problem_confirmed": {
        "en": "I understand. You are experiencing {problem}. Let me find the right doctor for you. Please hold for a moment.",
        "hi": "समझ गया। आप {problem} का अनुभव कर रहे हैं। मैं आपके लिए सही डॉक्टर ढूंढता हूँ।",
        "mr": "समजले. तुम्हाला {problem} होत आहे. मी तुमच्यासाठी योग्य डॉक्टर शोधतो.",
    },
    "problem_not_found": {
        "en": "I could not understand your problem clearly. Could you please describe your symptoms in a little more detail?",
        "hi": "मुझे आपकी समस्या स्पष्ट नहीं समझ आई। कृपया थोड़ा और विस्तार से बताएं।",
        "mr": "मला तुमची समस्या स्पष्ट समजली नाही. कृपया थोडे अधिक सांगा.",
    },
    # Doctors
    "suggest_doctors_intro": {
        "en": "Based on your symptoms, I recommend a {specialty} specialist. Here are the available doctors. ",
        "hi": "आपके लक्षणों के आधार पर, {specialty} विशेषज्ञ उचित रहेंगे। उपलब्ध डॉक्टर: ",
        "mr": "तुमच्या लक्षणांवरून {specialty} तज्ञ योग्य आहेत. उपलब्ध डॉक्टर: ",
    },
    "press_for_doctor": {
        "en": "Press {n} for Doctor {name}. ",
        "hi": "{n} दबाएं डॉक्टर {name} के लिए। ",
        "mr": "{n} दाबा डॉक्टर {name} साठी. ",
    },
    "no_doctors": {
        "en": "I am sorry, no specialists are currently available. Please call during working hours.",
        "hi": "क्षमा करें, कोई विशेषज्ञ उपलब्ध नहीं है। कार्यालय समय में कॉल करें।",
        "mr": "माफ करा, सध्या कोणतेही तज्ञ उपलब्ध नाहीत.",
    },
    # Slots
    "ask_slot_intro": {
        "en": "You selected Doctor {name}. Here are the available appointment slots. ",
        "hi": "आपने डॉक्टर {name} को चुना। उपलब्ध स्लॉट: ",
        "mr": "तुम्ही डॉक्टर {name} निवडले. उपलब्ध स्लॉट्स: ",
    },
    "press_for_slot": {
        "en": "Press {n} for {date} at {time}. ",
        "hi": "{n} दबाएं {date} को {time} बजे। ",
        "mr": "{n} दाबा {date} रोजी {time} वाजता. ",
    },
    # Confirmation
    "confirm_booking": {
        "en": (
            "Your appointment has been booked successfully. "
            "Doctor {doctor}, on {date} at {time}. "
            "Your appointment number is {appt_no}. "
            "We will send a confirmation to your registered number. "
            "Thank you for choosing NexaCare. Have a healthy day. Goodbye."
        ),
        "hi": (
            "आपकी अपॉइंटमेंट सफलतापूर्वक बुक हो गई। "
            "डॉक्टर {doctor}, {date} को {time} बजे। "
            "अपॉइंटमेंट नंबर: {appt_no}। "
            "NexaCare चुनने के लिए धन्यवाद।"
        ),
        "mr": (
            "तुमची अपॉइंटमेंट यशस्वीरित्या बुक झाली. "
            "डॉक्टर {doctor}, {date} रोजी {time} वाजता. "
            "अपॉइंटमेंट नंबर: {appt_no}. "
            "NexaCare निवडल्याबद्दल धन्यवाद."
        ),
    },
    # Errors
    "error": {
        "en": "I am sorry, something went wrong. Please call again. Goodbye.",
        "hi": "क्षमा करें, कुछ गड़बड़ी हुई। पुनः कॉल करें।",
        "mr": "माफ करा, काहीतरी चुकीचे झाले. पुन्हा कॉल करा.",
    },
    "max_retries": {
        "en": "We are unable to process your request at this time. Please call again. Goodbye.",
        "hi": "हम अभी आपकी सहायता नहीं कर सकते। कृपया पुनः कॉल करें।",
        "mr": "आम्ही सध्या तुमची मदत करू शकत नाही. पुन्हा कॉल करा.",
    },
}


def _s(key: str, lang: str, **kwargs) -> str:
    text = STRINGS[key].get(lang, STRINGS[key]["en"])
    return text.format(**kwargs) if kwargs else text


# Marathi's only available Twilio TTS voices are Generative-tier (Google
# Chirp3 voices) — there's no Standard/Neural fallback for mr-IN, and
# Twilio does not appear to auto-select a Generative voice from the
# language attribute alone. Pin it explicitly.
VOICE_BY_LANG = {
    "mr-IN": "Google.mr-IN-Chirp3-HD-Aoede",
}


def _say(text: str, lang: str) -> str:
    voice = VOICE_BY_LANG.get(lang)
    voice_attr = f' voice="{escape(voice)}"' if voice else ""
    return f'<Say language="{escape(lang)}"{voice_attr}>{escape(text)}</Say>'


# Domain hints to bias Twilio's speech recognition toward booking/medical
# vocabulary. These matter most for Marathi (mr-IN), since Twilio does not
# offer Marathi the enhanced/experimental STT models that English and Hindi
# get — hints are one of the few accuracy levers left for that language.
SPEECH_HINTS = {
    "en": (
        "appointment, doctor, fever, headache, stomach pain, chest pain, "
        "cough, cold, back pain, skin rash, eye problem, ear pain, "
        "tooth pain, blood pressure, diabetes, pregnancy, child, injury"
    ),
    "hi": (
        "अपॉइंटमेंट, डॉक्टर, बुखार, सिरदर्द, पेट दर्द, सीने में दर्द, "
        "खांसी, जुकाम, कमर दर्द, त्वचा पर चकत्ते, आंख की समस्या, कान में दर्द, "
        "दांत दर्द, ब्लड प्रेशर, शुगर, गर्भावस्था, बच्चा, चोट"
    ),
    "mr": (
        "अपॉइंटमेंट, डॉक्टर, ताप, डोकेदुखी, पोटदुखी, छातीत दुखणे, "
        "खोकला, सर्दी, पाठदुखी, त्वचेवर पुरळ, डोळ्यांचा त्रास, कानदुखी, "
        "दातदुखी, ब्लड प्रेशर, साखर, गर्भधारणा, मूल, दुखापत"
    ),
}


def _speech_timeout_for(lang: str, base: int = 8) -> int:
    """
    Marathi doesn't get Twilio's enhanced/experimental STT models, so it
    runs on a slower, less accurate base model. A couple of extra seconds
    of pause-tolerance reduces premature cutoffs mid-sentence.
    """
    return base + 2 if lang == "mr" else base


def _gather_speech(action: str, prompt: str, twilio_lang: str, lang_code: str = "en", timeout: int = 8) -> str:
    hints = SPEECH_HINTS.get(lang_code, SPEECH_HINTS["en"])
    return (
        f'<Gather input="speech" action="{escape(action)}" method="POST" '
        f'language="{escape(twilio_lang)}" speechTimeout="auto" timeout="{timeout}" '
        f'hints="{escape(hints)}">'
        f'{_say(prompt, twilio_lang)}'
        f'</Gather>'
        f'<Redirect method="POST">{escape(action)}</Redirect>'
    )


def _gather_dtmf(action: str, prompt: str, lang: str, num_digits: int = 1) -> str:
    return (
        f'<Gather numDigits="{num_digits}" action="{escape(action)}" method="POST" timeout="10">'
        f'{_say(prompt, lang)}'
        f'</Gather>'
        f'<Redirect method="POST">{escape(action)}</Redirect>'
    )


def _twiml(*elements: str) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(elements) + "</Response>"


def _hangup_twiml(text: str, lang: str) -> str:
    return _twiml(_say(text, lang), "<Hangup/>")


def _format_time_for_tts(time_str: str) -> str:
    """Convert HH:MM:SS → '2:00 PM' for natural TTS."""
    try:
        t = datetime.strptime(time_str, "%H:%M:%S")
        return t.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return time_str


# ── Node: collect_name ────────────────────────────────────────────────────────

def build_collect_name_twiml(state: BookingCallState) -> str:
    lang = state["language"]
    twilio_lang = state["twilio_language"]
    action = f"{state['base_url']}/agent/v1/voice/turn"
    return _twiml(_gather_speech(action, _s("ask_name", lang), twilio_lang, lang_code=lang, timeout=_speech_timeout_for(lang)))


def process_collect_name(state: BookingCallState, speech_result: str, confidence: float = -1.0) -> dict:
    """
    Send transcript to Groq LLM for name extraction.
    Positive: confirms name back to patient, moves to collect_problem.
    Negative: asks patient to repeat (up to MAX_RETRIES).
    Never rejects based on Twilio confidence score — LLM decides.
    """
    lang = state["language"]
    twilio_lang = state["twilio_language"]
    action = f"{state['base_url']}/agent/v1/voice/turn"

    logger.info(f"[{state['call_sid']}] Name transcript: {speech_result!r} | confidence={confidence}")

    # ── LLM extraction ──
    extraction = extract_patient_name(speech_result or "", twilio_confidence=confidence)
    logger.info(f"[{state['call_sid']}] Name extraction: {extraction}")

    # ── POSITIVE scenario ──
    if extraction["found"] and extraction.get("name", "").strip():
        name = extraction["name"].strip()
        logger.info(f"[{state['call_sid']}] ✓ Name confirmed: {name!r}")

        confirm_msg = _s("name_confirmed", lang, name=name)
        ask_problem_msg = _s("ask_problem", lang)

        return {
            "step": "collect_problem",
            "patient_name": name,
            "retry_count": 0,
            "_twiml": _twiml(
                _say(confirm_msg, twilio_lang),
                _gather_speech(action, ask_problem_msg, twilio_lang, lang_code=lang, timeout=_speech_timeout_for(lang, base=10)),
            ),
        }

    # ── NEGATIVE scenario ──
    retry = state["retry_count"] + 1
    logger.warning(
        f"[{state['call_sid']}] ✗ Name not found "
        f"(retry {retry}/{MAX_RETRIES}) | reason: {extraction.get('reason')} | "
        f"transcript={speech_result!r}"
    )

    if retry > MAX_RETRIES:
        logger.error(f"[{state['call_sid']}] Max retries reached for name — using 'Patient' as fallback")
        # Graceful fallback: use "Patient" so the call continues rather than hanging up
        return {
            "step": "collect_problem",
            "patient_name": "Patient",
            "retry_count": 0,
            "_twiml": _twiml(
                _say(_s("ask_problem", lang), twilio_lang),
                _gather_speech(action, _s("ask_problem", lang), twilio_lang, lang_code=lang, timeout=_speech_timeout_for(lang, base=10)),
            ),
        }

    return {
        "step": "collect_name",
        "retry_count": retry,
        "_twiml": _twiml(
            _say(_s("name_not_found", lang), twilio_lang),
            _gather_speech(action, _s("ask_name", lang), twilio_lang, lang_code=lang, timeout=_speech_timeout_for(lang)),
        ),
    }


# ── Node: collect_problem ─────────────────────────────────────────────────────

def process_collect_problem(state: BookingCallState, speech_result: str, confidence: float = -1.0) -> dict:
    """
    Send transcript to Gemini LLM for problem extraction.
    Positive: confirms problem, triggers specialty detection with keyword boost.
    Negative: asks patient to describe again.
    Never rejects based on Twilio confidence score — LLM decides.
    """
    lang = state["language"]
    twilio_lang = state["twilio_language"]
    action = f"{state['base_url']}/agent/v1/voice/turn"

    logger.info(f"[{state['call_sid']}] Problem transcript: {speech_result!r} | confidence={confidence}")

    # ── LLM extraction ──
    extraction = extract_problem(speech_result or "", twilio_confidence=confidence)
    logger.info(f"[{state['call_sid']}] Problem extraction: {extraction}")

    # ── NEGATIVE scenario ──
    if not extraction["found"] or not extraction.get("problem", "").strip():
        retry = state["retry_count"] + 1
        logger.warning(
            f"[{state['call_sid']}] ✗ Problem not found "
            f"(retry {retry}/{MAX_RETRIES}) | reason: {extraction.get('reason')} | "
            f"transcript={speech_result!r}"
        )

        if retry > MAX_RETRIES:
            logger.error(f"[{state['call_sid']}] Max retries for problem — falling back to General Medicine")
            # Graceful fallback: route to General Medicine so call doesn't dead-end
            return {
                "step": "suggest_doctors",
                "problem_description": speech_result or "not specified",
                "detected_specialty": "General Medicine",
                "specialty_confidence": "low",
                "specialty_reasoning": "Fallback after max retries",
                "retry_count": 0,
                "_pending": "suggest_doctors",
                "_confirm_problem_tts": "",
            }

        return {
            "step": "collect_problem",
            "retry_count": retry,
            "_twiml": _twiml(
                _say(_s("problem_not_found", lang), twilio_lang),
                _gather_speech(action, _s("ask_problem", lang), twilio_lang, lang_code=lang, timeout=_speech_timeout_for(lang, base=10)),
            ),
        }

    # ── POSITIVE scenario ──
    problem = extraction["problem"].strip()
    logger.info(f"[{state['call_sid']}] ✓ Problem confirmed: {problem!r}")

    # Pass English keywords from extraction for multi-signal specialty matching
    keywords = extraction.get("keywords", [])
    logger.info(f"[{state['call_sid']}] Detecting specialty for: {problem!r} | keywords={keywords}")
    analysis = detect_specialty(problem, keywords=keywords)
    logger.info(f"[{state['call_sid']}] Specialty: {analysis['specialty']} ({analysis['confidence']})")

    confirm_msg = _s("problem_confirmed", lang, problem=problem)

    return {
        "step": "suggest_doctors",
        "problem_description": problem,
        "detected_specialty": analysis["specialty"],
        "specialty_confidence": analysis["confidence"],
        "specialty_reasoning": analysis["reasoning"],
        "retry_count": 0,
        "_pending": "suggest_doctors",
        "_confirm_problem_tts": confirm_msg,
    }


# ── Node: suggest_doctors ─────────────────────────────────────────────────────

async def fetch_doctors_for_specialty(specialty: str, db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(Doctor).where(
            and_(
                Doctor.specialization.ilike(f"%{specialty}%"),
                Doctor.availability_status == "available",
                Doctor.is_deleted == False,
            )
        ).limit(3)
    )
    doctors = result.scalars().all()

    if not doctors:
        result = await db.execute(
            select(Doctor).where(
                and_(
                    Doctor.specialization.ilike("%General%"),
                    Doctor.availability_status == "available",
                    Doctor.is_deleted == False,
                )
            ).limit(3)
        )
        doctors = result.scalars().all()

    return [
        {
            "id": d.id,
            "name": f"{d.first_name} {d.last_name}".strip(),
            "specialization": d.specialization,
            "consultation_fee": d.consultation_fee,
            "department_id": d.department_id,
        }
        for d in doctors
    ]


def build_suggest_doctors_twiml(
    state: BookingCallState,
    doctors: list[dict],
    confirm_problem_tts: str = "",
) -> str:
    lang = state["language"]
    twilio_lang = state["twilio_language"]
    action = f"{state['base_url']}/agent/v1/voice/turn"
    specialty = state.get("detected_specialty", "General Medicine")

    if not doctors:
        return _hangup_twiml(_s("no_doctors", lang), twilio_lang)

    intro = _s("suggest_doctors_intro", lang, specialty=specialty)
    options = "".join(
        _s("press_for_doctor", lang, n=i + 1, name=d["name"])
        for i, d in enumerate(doctors)
    )
    prompt = intro + options

    elements = []
    # Prepend problem confirmation TTS if present
    if confirm_problem_tts:
        elements.append(_say(confirm_problem_tts, twilio_lang))
    elements.append(_gather_dtmf(action, prompt, twilio_lang))

    return _twiml(*elements)


# ── Node: select_doctor ───────────────────────────────────────────────────────

def process_select_doctor(state: BookingCallState, digit: str) -> dict:
    doctors = state.get("suggested_doctors", [])

    try:
        idx = int(digit) - 1
        if 0 <= idx < len(doctors):
            doctor = doctors[idx]
            logger.info(f"[{state['call_sid']}] ✓ Doctor selected: {doctor['name']}")
            return {
                "step": "select_slot",
                "selected_doctor_id": doctor["id"],
                "selected_doctor_name": doctor["name"],
                "selected_doctor_specialization": doctor["specialization"],
                "retry_count": 0,
                "_pending": "select_slot",
            }
    except (ValueError, IndexError):
        pass

    logger.warning(f"[{state['call_sid']}] ✗ Invalid doctor digit: {digit!r}")
    return {
        "step": "suggest_doctors",
        "_twiml": build_suggest_doctors_twiml(state, doctors),
    }


# ── Node: select_slot ─────────────────────────────────────────────────────────

async def fetch_available_slots(doctor_id: int, db: AsyncSession) -> list[dict]:
    today = date.today()
    slots = []

    result = await db.execute(
        select(DoctorSchedule).where(
            and_(
                DoctorSchedule.doctor_id == doctor_id,
                DoctorSchedule.is_active == True,
            )
        )
    )
    schedules = result.scalars().all()

    if not schedules:
        return [
            {"date": str(today + timedelta(days=1)), "time": "10:00:00", "doctor_id": doctor_id},
            {"date": str(today + timedelta(days=2)), "time": "14:00:00", "doctor_id": doctor_id},
            {"date": str(today + timedelta(days=3)), "time": "11:00:00", "doctor_id": doctor_id},
        ]

    for offset in range(7):
        check_date = today + timedelta(days=offset + 1)
        day_of_week = check_date.weekday()
        for schedule in schedules:
            if schedule.day_of_week == day_of_week:
                slots.append({
                    "date": str(check_date),
                    "time": schedule.start_time.strftime("%H:%M:%S"),
                    "doctor_id": doctor_id,
                })
                if len(slots) >= 3:
                    return slots

    return slots or [
        {"date": str(today + timedelta(days=1)), "time": "10:00:00", "doctor_id": doctor_id},
    ]


def build_select_slot_twiml(state: BookingCallState, slots: list[dict]) -> str:
    lang = state["language"]
    twilio_lang = state["twilio_language"]
    action = f"{state['base_url']}/agent/v1/voice/turn"
    doctor_name = state.get("selected_doctor_name", "the doctor")

    intro = _s("ask_slot_intro", lang, name=doctor_name)
    options = "".join(
        _s("press_for_slot", lang, n=i + 1, date=s["date"], time=_format_time_for_tts(s["time"]))
        for i, s in enumerate(slots)
    )
    return _twiml(_gather_dtmf(action, intro + options, twilio_lang))


def process_select_slot(state: BookingCallState, digit: str) -> dict:
    slots = state.get("available_slots", [])

    try:
        idx = int(digit) - 1
        if 0 <= idx < len(slots):
            slot = slots[idx]
            logger.info(f"[{state['call_sid']}] ✓ Slot selected: {slot}")
            return {
                "step": "confirm",
                "selected_slot": slot,
                "retry_count": 0,
                "_pending": "confirm",
            }
    except (ValueError, IndexError):
        pass

    logger.warning(f"[{state['call_sid']}] ✗ Invalid slot digit: {digit!r}")
    return {
        "step": "select_slot",
        "_twiml": build_select_slot_twiml(state, slots),
    }


# ── Node: confirm booking ─────────────────────────────────────────────────────

async def confirm_and_book(state: BookingCallState, db: AsyncSession) -> dict:
    from app.models.appointment_model import Appointment
    from app.models.patient_model import Patient
    from app.repositories.patient_repository import PatientRepository
    import random
    import string

    lang        = state["language"]
    twilio_lang = state["twilio_language"]
    slot        = state["selected_slot"]
    doctor_id   = state["selected_doctor_id"]
    doctor_name = state.get("selected_doctor_name", "the doctor")
    patient_name = state.get("patient_name", "Patient")
    caller_number = state.get("from_number", "")

    try:
        # ── Resolve or create patient record from caller's phone number ──
        patient_repo = PatientRepository(db)
        patient = await patient_repo.get_by_phone(caller_number) if caller_number else None

        if not patient:
            name_parts = patient_name.strip().split(maxsplit=1)
            first_name = name_parts[0] if name_parts else "Patient"
            last_name  = name_parts[1] if len(name_parts) > 1 else ""

            patient_code = "PT-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

            patient = Patient(
                patient_code=patient_code,
                first_name=first_name,
                last_name=last_name,
                phone=caller_number,
                status="active",
            )
            patient = await patient_repo.create(patient)
            logger.info(
                f"[{state['call_sid']}] ✓ New patient created: "
                f"id={patient.id} | {first_name} {last_name} | {caller_number}"
            )
        else:
            logger.info(
                f"[{state['call_sid']}] ✓ Existing patient matched: "
                f"id={patient.id} | phone={caller_number}"
            )

        appt_no = "APT-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

        appt = Appointment(
            appointment_number=appt_no,
            patient_id=patient.id,
            doctor_id=doctor_id,
            department_id=None,
            appointment_date=slot["date"],
            appointment_time=slot["time"],   # HH:MM:SS — correct for MySQL TIME
            appointment_status="scheduled",
            symptoms=state.get("problem_description"),
            notes=f"Booked via AI Voice Agent. Patient: {patient_name} | Phone: {caller_number} | Lang: {lang}",
            consultation_type="in_person",
            reminder_sent=False,
            token_number=random.randint(1, 99),
        )
        db.add(appt)
        await db.commit()
        await db.refresh(appt)

        time_display = _format_time_for_tts(slot["time"])

        logger.info(
            f"[{state['call_sid']}] ✓ Appointment booked: {appt_no} | "
            f"Doctor: {doctor_name} | {slot['date']} {time_display}"
        )

        # ── Send SMS confirmation (non-blocking — failure won't affect call) ──
        sms_sent = _send_sms_confirmation(
            to_number=caller_number,
            lang=lang,
            name=patient_name,
            doctor=doctor_name,
            appt_date=slot["date"],
            appt_time=time_display,
            appt_no=appt_no,
        )
        if sms_sent:
            logger.info(f"[{state['call_sid']}] ✓ SMS confirmation sent to {caller_number}")

        confirm_text = _s(
            "confirm_booking", lang,
            doctor=doctor_name,
            date=slot["date"],
            time=time_display,
            appt_no=appt_no,
        )

        return {
            "step": "booked",
            "appointment_id": appt.id,
            "appointment_number": appt_no,
            "_twiml": _twiml(_say(confirm_text, twilio_lang), "<Hangup/>"),
        }

    except Exception as e:
        logger.error(f"[{state['call_sid']}] Booking failed: {e}")
        await db.rollback()
        return {
            "step": "error",
            "_twiml": _hangup_twiml(_s("error", lang), twilio_lang),
        }