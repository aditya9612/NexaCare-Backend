"""
DTMF reschedule flow (digit 2 on service menu).

Supports multiple upcoming appointments under one phone number
(account holder + dependents): ask which appointment, then pick a new slot.
"""

from __future__ import annotations

import logging
from datetime import date, time
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.agent.state import BookingCallState
from app.agent.nodes import booking as book_node
from app.core.constants import AppointmentStatus
from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.models.appointment_model import Appointment
from app.repositories.patient_repository import PatientRepository
from app.schemas.appointment_schema import RescheduleRequest
from app.services.appointment_service import AppointmentService

logger = logging.getLogger("nexacare.agent.nodes.reschedule")

MAX_CANDIDATES = 5

_PROMPTS = {
    "select_intro": {
        "en": "You have more than one upcoming appointment. ",
        "hi": "आपकी एक से अधिक आगामी अपॉइंटमेंट हैं। ",
        "mr": "तुमच्या एकापेक्षा जास्त आगामी अपॉइंटमेंट आहेत. ",
    },
    "press_for_appt": {
        "en": "Press {n} for {patient} with Doctor {doctor} on {date} at {time}. ",
        "hi": "{patient} के लिए डॉक्टर {doctor} के साथ {date} को {time} वाली अपॉइंटमेंट के लिए {n} दबाएं। ",
        "mr": "{patient} साठी डॉक्टर {doctor} यांच्यासोबत {date} रोजी {time} च्या अपॉइंटमेंटसाठी {n} दाबा. ",
    },
    "single_intro": {
        "en": "Rescheduling the appointment for {patient} with Doctor {doctor}. ",
        "hi": "{patient} की डॉक्टर {doctor} के साथ अपॉइंटमेंट बदली जा रही है। ",
        "mr": "{patient} ची डॉक्टर {doctor} यांच्यासोबतची अपॉइंटमेंट बदलली जात आहे. ",
    },
    "patient_not_found": {
        "en": "We could not find a patient record for this phone number. Goodbye.",
        "hi": "इस फोन नंबर के लिए मरीज का रिकॉर्ड नहीं मिला। अलविदा।",
        "mr": "या फोन नंबरसाठी रुग्णाची नोंद सापडली नाही. नमस्कार.",
    },
    "no_appointment": {
        "en": "You do not have an upcoming confirmed or pending appointment to reschedule. Goodbye.",
        "hi": "बदलने के लिए आपकी कोई आगामी कन्फर्म या पेंडिंग अपॉइंटमेंट नहीं है। अलविदा।",
        "mr": "बदलण्यासाठी तुमची कोणतीही पुढील कन्फर्म किंवा पेंडिंग अपॉइंटमेंट नाही. नमस्कार.",
    },
    "no_slots": {
        "en": "No available slots were found for this doctor. Please call again later. Goodbye.",
        "hi": "इस डॉक्टर के लिए कोई उपलब्ध स्लॉट नहीं मिला। कृपया बाद में कॉल करें। अलविदा।",
        "mr": "या डॉक्टरांसाठी कोणतेही उपलब्ध स्लॉट सापडले नाहीत. कृपया नंतर कॉल करा. नमस्कार.",
    },
    "failed": {
        "en": "We could not reschedule your appointment. Please call again. Goodbye.",
        "hi": "हम आपका अपॉइंटमेंट नहीं बदल सके। कृपया फिर से कॉल करें। अलविदा।",
        "mr": "आम्ही तुमची अपॉइंटमेंट बदलू शकलो नाही. कृपया पुन्हा कॉल करा. नमस्कार.",
    },
    "terminal": {
        "en": "This appointment is already completed or cancelled and cannot be rescheduled. Goodbye.",
        "hi": "यह अपॉइंटमेंट पहले ही पूरी हो चुकी है या रद्द हो चुकी है, इसलिए इसे बदला नहीं जा सकता। अलविदा।",
        "mr": "ही अपॉइंटमेंट आधीच पूर्ण झाली आहे किंवा रद्द झाली आहे, त्यामुळे ती बदलता येणार नाही. नमस्कार.",
    },
    "success": {
        "en": "Your appointment has been rescheduled successfully. Goodbye.",
        "hi": "आपका अपॉइंटमेंट सफलतापूर्वक बदल दिया गया है। अलविदा।",
        "mr": "आपली अपॉइंटमेंट यशस्वीरित्या बदलण्यात आली आहे. नमस्कार.",
    },
}


def _s(key: str, lang: str, **kwargs) -> str:
    table = _PROMPTS.get(key, {})
    text = table.get(lang) or table.get("en") or ""
    return text.format(**kwargs) if kwargs else text


def _doctor_display_name(doctor: Any) -> str:
    if not doctor:
        return "the doctor"
    return f"{getattr(doctor, 'first_name', '') or ''} {getattr(doctor, 'last_name', '') or ''}".strip() or "the doctor"


def _patient_display_name(patient: Any) -> str:
    if not patient:
        return "the patient"
    return f"{getattr(patient, 'first_name', '') or ''} {getattr(patient, 'last_name', '') or ''}".strip() or "the patient"


def _format_appt_time(value: time | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    return str(value)


def appointment_to_candidate(appt: Appointment) -> dict:
    patient = getattr(appt, "patient", None)
    doctor = getattr(appt, "doctor", None)
    appt_date = appt.appointment_date
    appt_time = appt.appointment_time
    return {
        "appointment_id": appt.id,
        "appointment_number": appt.appointment_number,
        "patient_id": appt.patient_id,
        "patient_name": _patient_display_name(patient),
        "doctor_id": appt.doctor_id,
        "doctor_name": _doctor_display_name(doctor),
        "date": str(appt_date) if appt_date else "",
        "time": _format_appt_time(appt_time),
    }


async def resolve_family_patient_ids(
    db: AsyncSession,
    *,
    phone: str | None,
    patient_id: int | None = None,
) -> Optional[list[int]]:
    """
    Return holder + dependent patient IDs for this phone.
    None => no patient found.
    """
    repo = PatientRepository(db)
    holder = await repo.get_by_phone(phone) if phone else None
    if holder is None and patient_id:
        holder = await repo.get_by_id(int(patient_id))
    if holder is None:
        return None
    dependents = await repo.list_dependents(holder.id)
    return [holder.id] + [d.id for d in dependents]


async def list_upcoming_candidates(
    db: AsyncSession,
    *,
    phone: str | None,
    patient_id: int | None = None,
    limit: int = MAX_CANDIDATES,
) -> tuple[Optional[list[int]], list[dict]]:
    """
    Returns (patient_ids_or_None, candidates).
    patient_ids is None when no patient record exists for the phone/id.
    """
    patient_ids = await resolve_family_patient_ids(db, phone=phone, patient_id=patient_id)
    if patient_ids is None:
        return None, []

    statuses = [AppointmentStatus.CONFIRMED, AppointmentStatus.PENDING]
    result = await db.execute(
        select(Appointment)
        .options(
            joinedload(Appointment.patient),
            joinedload(Appointment.doctor),
        )
        .where(
            Appointment.patient_id.in_(patient_ids),
            Appointment.appointment_status.in_(statuses),
            Appointment.appointment_date >= date.today(),
        )
        .order_by(Appointment.appointment_date.asc(), Appointment.appointment_time.asc())
        .limit(limit)
    )
    appointments = list(result.scalars().unique().all())
    return patient_ids, [appointment_to_candidate(a) for a in appointments]


def build_select_appointment_twiml(state: BookingCallState, candidates: list[dict]) -> str:
    lang = state.get("language") or "en"
    twilio_lang = state["twilio_language"]
    base_url = state.get("base_url", "")
    action = f"{state['base_url']}/agent/v1/voice/turn"

    intro = _s("select_intro", lang)
    options = "".join(
        _s(
            "press_for_appt",
            lang,
            n=i + 1,
            patient=c.get("patient_name") or "the patient",
            doctor=c.get("doctor_name") or "the doctor",
            date=c.get("date") or "",
            time=book_node._format_time_for_tts(c.get("time") or ""),
        )
        for i, c in enumerate(candidates)
    )
    return book_node._twiml(
        book_node._gather_dtmf(
            action,
            intro + options,
            twilio_lang,
            base_url=base_url,
            allow_generate=False,
        )
    )


def process_select_appointment(state: BookingCallState, digit: str) -> dict:
    candidates = state.get("reschedule_candidates") or []
    try:
        idx = int(digit) - 1
        if 0 <= idx < len(candidates):
            chosen = candidates[idx]
            logger.info(
                "[%s] ✓ Reschedule appointment selected: id=%s patient=%s",
                state.get("call_sid"),
                chosen.get("appointment_id"),
                chosen.get("patient_name"),
            )
            return {
                "step": "select_slot",
                "appointment_id": chosen["appointment_id"],
                "appointment_number": chosen.get("appointment_number"),
                "patient_id": chosen.get("patient_id"),
                "patient_name": chosen.get("patient_name"),
                "selected_doctor_id": chosen["doctor_id"],
                "selected_doctor_name": chosen.get("doctor_name"),
                "retry_count": 0,
                "_pending": "fetch_slots",
                "_chosen": chosen,
            }
    except (ValueError, IndexError):
        pass

    logger.warning(
        "[%s] ✗ Invalid reschedule appointment digit: %r",
        state.get("call_sid"),
        digit,
    )
    return {
        "step": "reschedule_select_appointment",
        "_twiml": build_select_appointment_twiml(state, candidates),
    }


def hangup_prompt(key: str, lang: str, twilio_lang: str, base_url: str = "") -> str:
    return book_node._hangup_twiml(_s(key, lang), twilio_lang, base_url=base_url)


async def prepare_slot_selection(
    db: AsyncSession,
    state: BookingCallState,
    candidate: dict,
) -> dict:
    """
    Load available slots for the appointment's doctor.
    Returns session updates including _twiml.
    """
    lang = state.get("language") or "en"
    twilio_lang = state["twilio_language"]
    base_url = state.get("base_url", "")
    doctor_id = int(candidate["doctor_id"])
    hospital_id = state.get("hospital_id")

    slots = await book_node.fetch_available_slots(
        doctor_id, db, hospital_id=hospital_id
    )
    if not slots:
        return {
            "step": "error",
            "_twiml": hangup_prompt("no_slots", lang, twilio_lang, base_url),
        }

    intro = _s(
        "single_intro",
        lang,
        patient=candidate.get("patient_name") or "the patient",
        doctor=candidate.get("doctor_name") or "the doctor",
    )
    slot_twiml = book_node.build_select_slot_twiml(
        {
            **state,
            "selected_doctor_name": candidate.get("doctor_name") or state.get("selected_doctor_name"),
        },
        slots,
    )
    # Prepend short context before the slot menu
    say_xml = book_node._say(intro, twilio_lang, base_url, allow_generate=False)
    marker = "<Response>"
    idx = slot_twiml.find(marker)
    if idx >= 0:
        insert_at = idx + len(marker)
        slot_twiml = slot_twiml[:insert_at] + say_xml + slot_twiml[insert_at:]

    return {
        "step": "select_slot",
        "service": "reschedule",
        "appointment_id": candidate["appointment_id"],
        "appointment_number": candidate.get("appointment_number"),
        "patient_id": candidate.get("patient_id"),
        "patient_name": candidate.get("patient_name"),
        "selected_doctor_id": doctor_id,
        "selected_doctor_name": candidate.get("doctor_name"),
        "available_slots": slots,
        "reschedule_candidates": state.get("reschedule_candidates"),
        "retry_count": 0,
        "_twiml": slot_twiml,
    }


async def confirm_and_reschedule(state: BookingCallState, db: AsyncSession) -> dict:
    lang = state.get("language") or "en"
    twilio_lang = state["twilio_language"]
    base_url = state.get("base_url", "")
    slot = state.get("selected_slot") or {}
    appointment_id = state.get("appointment_id")

    if not appointment_id or not slot:
        return {
            "step": "error",
            "_twiml": hangup_prompt("failed", lang, twilio_lang, base_url),
        }

    try:
        slot_date = book_node._parse_slot_date(slot["date"])
        slot_time = book_node._parse_slot_time(slot["time"])
    except (ValueError, KeyError, TypeError):
        return {
            "step": "error",
            "_twiml": hangup_prompt("failed", lang, twilio_lang, base_url),
        }

    try:
        await AppointmentService(db).reschedule(
            RescheduleRequest(
                appointment_id=int(appointment_id),
                appointment_date=slot_date,
                appointment_time=slot_time,
                notes="Rescheduled via voice DTMF",
            ),
            user_id=0,
        )
    except BadRequestException as exc:
        detail = str(getattr(exc, "detail", "") or "")
        key = "terminal" if "terminal" in detail.lower() else "failed"
        logger.error(
            "[%s] Reschedule rejected appointment_id=%s: %s",
            state.get("call_sid"),
            appointment_id,
            detail,
        )
        return {
            "step": "error",
            "_twiml": hangup_prompt(key, lang, twilio_lang, base_url),
        }
    except (NotFoundException, ConflictException) as exc:
        logger.error(
            "[%s] Reschedule failed appointment_id=%s: %s",
            state.get("call_sid"),
            appointment_id,
            exc,
        )
        return {
            "step": "error",
            "_twiml": hangup_prompt("failed", lang, twilio_lang, base_url),
        }
    except Exception as exc:
        logger.error(
            "[%s] Reschedule crashed appointment_id=%s: %s",
            state.get("call_sid"),
            appointment_id,
            exc,
        )
        return {
            "step": "error",
            "_twiml": hangup_prompt("failed", lang, twilio_lang, base_url),
        }

    logger.info(
        "[%s] ✓ Appointment %s rescheduled to %s %s",
        state.get("call_sid"),
        appointment_id,
        slot_date,
        slot_time,
    )
    return {
        "step": "rescheduled",
        "appointment_id": int(appointment_id),
        "_twiml": hangup_prompt("success", lang, twilio_lang, base_url),
    }
