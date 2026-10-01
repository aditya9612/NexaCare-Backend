"""
DTMF 3 — Cancel Appointment.

Caller mobile → related patients (max 5) → optional patient DTMF →
Pending+Confirmed appointments → optional appointment DTMF → confirm →
AppointmentService.cancel of cancel_pending_id only.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import session_store
from app.agent.nodes import booking as book_node
from app.ai.voice_appointment_assistant.prompts import (
    cancel_appointments_choose,
    cancel_appointments_intro,
    cancel_confirm,
    cancel_declined,
    cancel_failed,
    cancel_final_confirm,
    cancel_invalid_selection,
    cancel_no_appointment,
    cancel_patient_not_found,
    cancel_patient_option,
    cancel_patients_intro,
    cancel_showing_next_nine,
    cancel_success,
    cancel_terminal,
)
from app.core.constants import AppointmentStatus
from app.core.exceptions import BadRequestException, NotFoundException
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.patient_repository import PatientRepository
from app.schemas.appointment_schema import CancelRequest
from app.services.appointment_service import AppointmentService

logger = logging.getLogger("nexacare.agent.nodes.cancel")

MAX_PATIENTS = 5
MAX_APPOINTMENTS = 9
MAX_RETRIES = 2
CANCELLABLE = (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)
_CANCEL_SUCCESS_EN = (
    "Your appointment has been successfully cancelled. "
    "Thank you for calling NexaCare. Have a nice day."
)

DIGIT_WORDS = {
    "en": ("1", "2", "3", "4", "5", "6", "7", "8", "9"),
    "hi": ("एक", "दो", "तीन", "चार", "पांच", "छह", "सात", "आठ", "नौ"),
    "mr": ("एक", "दोन", "तीन", "चार", "पाच", "सहा", "सात", "आठ", "नऊ"),
}

_MONTHS = {
    "en": (
        "",
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
    "hi": (
        "",
        "जनवरी",
        "फरवरी",
        "मार्च",
        "अप्रैल",
        "मई",
        "जून",
        "जुलाई",
        "अगस्त",
        "सितंबर",
        "अक्टूबर",
        "नवंबर",
        "दिसंबर",
    ),
    "mr": (
        "",
        "जानेवारी",
        "फेब्रुवारी",
        "मार्च",
        "एप्रिल",
        "मे",
        "जून",
        "जुलै",
        "ऑगस्ट",
        "सप्टेंबर",
        "ऑक्टोबर",
        "नोव्हेंबर",
        "डिसेंबर",
    ),
}


def _now_ist() -> datetime:
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def _display_name(patient) -> str:
    first = (getattr(patient, "first_name", None) or "").strip()
    last = (getattr(patient, "last_name", None) or "").strip()
    return f"{first} {last}".strip() or "patient"


def _digit_word(language: str, index: int) -> str:
    words = DIGIT_WORDS.get(language) or DIGIT_WORDS["en"]
    if 0 <= index < len(words):
        return words[index]
    return str(index + 1)


def _format_when(appt, language: str) -> str:
    day = getattr(appt, "appointment_date", None)
    tval = getattr(appt, "appointment_time", None)
    months = _MONTHS.get(language) or _MONTHS["en"]
    if day is None:
        date_part = ""
    else:
        month = months[day.month] if 1 <= day.month <= 12 else str(day.month)
        date_part = f"{day.day} {month}"

    hour = tval.hour if isinstance(tval, time) else 0
    minute = tval.minute if isinstance(tval, time) else 0
    if language == "hi":
        if hour < 12:
            period = "सुबह"
        elif hour < 16:
            period = "दोपहर"
        else:
            period = "शाम"
        clock = hour % 12 or 12
        time_part = f"{period} {clock} बजे" if minute == 0 else f"{period} {clock}:{minute:02d} बजे"
        return f"{date_part} को {time_part}".strip()
    if language == "mr":
        if hour < 12:
            period = "सकाळी"
        elif hour < 16:
            period = "दुपारी"
        else:
            period = "संध्याकाळी"
        clock = hour % 12 or 12
        time_part = f"{period} {clock} वाजता" if minute == 0 else f"{period} {clock}:{minute:02d} वाजता"
        return f"{date_part} रोजी {time_part}".strip()
    return f"on {date_part} at {book_node._format_time_for_tts(str(tval) if tval else '')}".strip()


def _is_upcoming(appt, now: datetime) -> bool:
    day = getattr(appt, "appointment_date", None)
    tval = getattr(appt, "appointment_time", None)
    if day is None:
        return False
    today = now.date()
    if day > today:
        return True
    if day < today:
        return False
    if tval is None:
        return True
    current = now.time().replace(tzinfo=None)
    appt_time = tval.replace(tzinfo=None) if getattr(tval, "tzinfo", None) else tval
    return appt_time >= current


def _is_cancellable(appt) -> bool:
    return getattr(appt, "appointment_status", None) in CANCELLABLE


def _hangup(state, text: str) -> str:
    return book_node._twiml(
        book_node._say(
            text,
            state["twilio_language"],
            state.get("base_url") or "",
            allow_generate=False,
        ),
        "<Hangup/>",
    )


def _gather(state, prompt: str) -> str:
    action = f"{state.get('base_url') or ''}/agent/v1/voice/menu"
    return book_node._twiml(
        book_node._gather_dtmf(
            action,
            prompt,
            state["twilio_language"],
            num_digits=1,
            base_url=state.get("base_url") or "",
            allow_generate=False,
        )
    )


def _error_hangup() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Response><Say language="en-IN">'
        "We are sorry, something went wrong. Please call again. Goodbye."
        "</Say><Hangup/></Response>"
    )


async def find_related_patients(repo: PatientRepository, phone: str) -> list:
    if not phone:
        return []
    found: dict[int, object] = {}

    matches = await repo.list_by_phone(phone, limit=MAX_PATIENTS)
    if not matches:
        one = await repo.get_by_phone(phone)
        matches = [one] if one else []

    async def _add(patient) -> None:
        if patient is None:
            return
        pid = patient.id
        if pid in found:
            return
        found[pid] = patient

    for patient in matches:
        await _add(patient)
        guardian_id = getattr(patient, "guardian_patient_id", None)
        if guardian_id:
            guardian = await repo.get_by_id(guardian_id)
            await _add(guardian)
            if guardian is not None:
                for dep in await repo.list_dependents(guardian.id):
                    await _add(dep)
        for dep in await repo.list_dependents(patient.id):
            await _add(dep)

    ordered = sorted(found.values(), key=lambda p: p.id)
    return ordered[:MAX_PATIENTS]


async def list_cancellable_appointments(repo: AppointmentRepository, patient_id: int) -> list:
    now = _now_ist()
    rows = await repo.list_all(
        patient_id=patient_id,
        status=list(CANCELLABLE),
        start_date=now.date(),
        sort_by="appointment_date",
        sort_order="asc",
        limit=50,
    )
    upcoming = [row for row in rows if _is_upcoming(row, now) and _is_cancellable(row)]
    upcoming.sort(
        key=lambda row: (
            getattr(row, "appointment_date", None),
            getattr(row, "appointment_time", None) or time.min,
        )
    )
    return upcoming


async def _all_family_appointments(repo: AppointmentRepository, patients: list) -> list:
    collected = []
    for patient in patients:
        collected.extend(await list_cancellable_appointments(repo, patient.id))
    collected.sort(
        key=lambda row: (
            getattr(row, "appointment_date", None),
            getattr(row, "appointment_time", None) or time.min,
            getattr(row, "id", 0),
        )
    )
    return collected


def _patient_menu_prompt(language: str, names: list[str]) -> str:
    parts = [cancel_patients_intro(language)]
    for index, name in enumerate(names):
        parts.append(cancel_patient_option(language, name, _digit_word(language, index)))
    return " ".join(parts)


def _appointment_menu_prompt(language: str, name: str, appointments: list, truncated: bool) -> str:
    parts = []
    if truncated:
        parts.append(cancel_showing_next_nine(language))
    parts.append(cancel_appointments_intro(language, name))
    for index, appt in enumerate(appointments):
        parts.append(f"{_digit_word(language, index)} — {_format_when(appt, language)}.")
    parts.append(cancel_appointments_choose(language))
    return " ".join(parts)


async def _invalid_retry(call_sid: str, state: dict, replay_twiml: str) -> str:
    retry = int(state.get("retry_count") or 0) + 1
    await session_store.update_session(call_sid, {"retry_count": retry})
    if retry > MAX_RETRIES:
        return _error_hangup()
    language = state.get("language") or "en"
    prefix = cancel_invalid_selection(language)
    twilio_lang = state["twilio_language"]
    base_url = state.get("base_url") or ""
    action = f"{base_url}/agent/v1/voice/menu"
    # Replay the same gather, prefixed with invalid-selection.
    inner = replay_twiml
    if inner.startswith("<?xml"):
        start = inner.find("<Gather")
        end = inner.rfind("</Response>")
        if start != -1 and end != -1:
            gather = inner[start:end]
            return (
                '<?xml version="1.0" encoding="UTF-8"?><Response>'
                f"{book_node._say(prefix, twilio_lang, base_url, allow_generate=False)}"
                f"{gather}"
                "</Response>"
            )
    return book_node._twiml(
        book_node._say(prefix, twilio_lang, base_url, allow_generate=False),
        book_node._gather_dtmf(
            action,
            replay_twiml,
            twilio_lang,
            num_digits=1,
            base_url=base_url,
            allow_generate=False,
        ),
    )


async def _enter_confirm(call_sid: str, state: dict, appt, patient_name: str, *, final: bool) -> str:
    language = state.get("language") or "en"
    when = _format_when(appt, language)
    prompt = (
        cancel_final_confirm(language, patient_name, when)
        if final
        else cancel_confirm(language, patient_name, when)
    )
    await session_store.update_session(
        call_sid,
        {
            "cancel_step": "confirm",
            "cancel_pending_id": appt.id,
            "cancel_patient_id": getattr(appt, "patient_id", state.get("cancel_patient_id")),
            "retry_count": 0,
        },
    )
    return _gather(state, prompt)


async def _enter_appointments(db: AsyncSession, call_sid: str, state: dict, patient) -> str:
    language = state.get("language") or "en"
    repo = AppointmentRepository(db)
    appointments = await list_cancellable_appointments(repo, patient.id)
    if not appointments:
        logger.info("  ↳ [%s] Cancel: no upcoming appointment for patient %s", call_sid, patient.id)
        return _hangup(state, cancel_no_appointment(language))

    name = _display_name(patient)
    truncated = len(appointments) > MAX_APPOINTMENTS
    shown = appointments[:MAX_APPOINTMENTS]
    await session_store.update_session(
        call_sid,
        {
            "cancel_patient_id": patient.id,
            "cancel_candidates": [row.id for row in shown],
            "cancel_list_truncated": truncated,
            "retry_count": 0,
        },
    )
    if len(shown) == 1:
        return await _enter_confirm(call_sid, state, shown[0], name, final=False)

    await session_store.update_session(call_sid, {"cancel_step": "select_appointment"})
    return _gather(state, _appointment_menu_prompt(language, name, shown, truncated))


async def start_cancel_flow(db: AsyncSession, call_sid: str, state: dict) -> str:
    language = state.get("language") or "en"
    phone = state.get("from_number") or ""
    patients_repo = PatientRepository(db)
    appt_repo = AppointmentRepository(db)

    try:
        patients = await find_related_patients(patients_repo, phone)
        if not patients:
            logger.info("  ↳ [%s] Cancel: patient not found", call_sid)
            return _hangup(state, cancel_patient_not_found(language))

        names = [_display_name(p) for p in patients]
        ids = [p.id for p in patients]
        await session_store.update_session(
            call_sid,
            {
                "cancel_patient_ids": ids,
                "cancel_patient_names": names,
                "retry_count": 0,
            },
        )

        session_appointment_id = state.get("appointment_id")
        family_appts = await _all_family_appointments(appt_repo, patients)
        if session_appointment_id:
            try:
                session_appt = await appt_repo.get_by_id(int(session_appointment_id))
            except (TypeError, ValueError):
                session_appt = None
            related_ids = set(ids)
            if (
                session_appt is not None
                and session_appt.patient_id in related_ids
                and _is_cancellable(session_appt)
                and _is_upcoming(session_appt, _now_ist())
                and len(family_appts) == 1
                and family_appts[0].id == session_appt.id
            ):
                patient = next(p for p in patients if p.id == session_appt.patient_id)
                await session_store.update_session(
                    call_sid,
                    {
                        "cancel_patient_id": patient.id,
                        "cancel_candidates": [session_appt.id],
                    },
                )
                return await _enter_confirm(
                    call_sid, state, session_appt, _display_name(patient), final=True
                )

        if len(patients) == 1:
            return await _enter_appointments(db, call_sid, state, patients[0])

        await session_store.update_session(call_sid, {"cancel_step": "select_patient"})
        return _gather(state, _patient_menu_prompt(language, names))
    except Exception as exc:
        logger.error("  ✗ [%s] Cancel start failed: %s", call_sid, exc)
        logger.error("cancel start traceback", exc_info=True)
        return _hangup(state, cancel_failed(language))


async def handle_cancel_digit(db: AsyncSession, call_sid: str, state: dict, digit: str) -> str:
    language = state.get("language") or "en"
    step = state.get("cancel_step")
    try:
        if step == "select_patient":
            return await _handle_patient_digit(db, call_sid, state, digit)
        if step == "select_appointment":
            return await _handle_appointment_digit(db, call_sid, state, digit)
        if step == "confirm":
            return await _handle_confirm_digit(db, call_sid, state, digit)
        return _hangup(state, cancel_failed(language))
    except Exception as exc:
        logger.error("  ✗ [%s] Cancel digit failed: %s", call_sid, exc)
        logger.error("cancel digit traceback", exc_info=True)
        return _hangup(state, cancel_failed(language))


async def _handle_patient_digit(db: AsyncSession, call_sid: str, state: dict, digit: str) -> str:
    language = state.get("language") or "en"
    ids = list(state.get("cancel_patient_ids") or [])
    names = list(state.get("cancel_patient_names") or [])
    replay = _gather(state, _patient_menu_prompt(language, names))
    if not digit or not digit.isdigit():
        return await _invalid_retry(call_sid, state, replay)
    index = int(digit) - 1
    if index < 0 or index >= len(ids):
        return await _invalid_retry(call_sid, state, replay)

    patient = await PatientRepository(db).get_by_id(ids[index])
    if patient is None:
        return _hangup(state, cancel_patient_not_found(language))
    await session_store.update_session(call_sid, {"retry_count": 0})
    return await _enter_appointments(db, call_sid, state, patient)


async def _handle_appointment_digit(db: AsyncSession, call_sid: str, state: dict, digit: str) -> str:
    language = state.get("language") or "en"
    candidates = list(state.get("cancel_candidates") or [])
    names = list(state.get("cancel_patient_names") or [])
    patient_id = state.get("cancel_patient_id")
    name = ""
    ids = list(state.get("cancel_patient_ids") or [])
    if patient_id and ids and names and patient_id in ids:
        name = names[ids.index(patient_id)]
    if not name:
        patient = await PatientRepository(db).get_by_id(patient_id) if patient_id else None
        name = _display_name(patient) if patient else "patient"

    repo = AppointmentRepository(db)
    shown = []
    for appt_id in candidates:
        row = await repo.get_by_id(int(appt_id))
        if row is not None:
            shown.append(row)
    truncated = bool(state.get("cancel_list_truncated"))
    replay = _gather(state, _appointment_menu_prompt(language, name, shown, truncated))

    if not digit or not digit.isdigit():
        return await _invalid_retry(call_sid, state, replay)
    index = int(digit) - 1
    if index < 0 or index >= len(candidates):
        return await _invalid_retry(call_sid, state, replay)

    selected_id = int(candidates[index])
    appt = await repo.get_by_id(selected_id)
    if appt is None or not _is_cancellable(appt) or not _is_upcoming(appt, _now_ist()):
        if appt is not None and not _is_cancellable(appt):
            return _hangup(state, cancel_terminal(language))
        return _hangup(state, cancel_no_appointment(language))
    if patient_id and appt.patient_id != patient_id:
        return _hangup(state, cancel_failed(language))

    await session_store.update_session(call_sid, {"retry_count": 0})
    return await _enter_confirm(call_sid, state, appt, name, final=True)


async def _handle_confirm_digit(db: AsyncSession, call_sid: str, state: dict, digit: str) -> str:
    language = state.get("language") or "en"
    pending_id = state.get("cancel_pending_id")
    patient_id = state.get("cancel_patient_id")
    name = "patient"
    ids = list(state.get("cancel_patient_ids") or [])
    names = list(state.get("cancel_patient_names") or [])
    if patient_id and ids and names and patient_id in ids:
        name = names[ids.index(patient_id)]

    appt = None
    if pending_id is not None:
        appt = await AppointmentRepository(db).get_by_id(int(pending_id))
    when = _format_when(appt, language) if appt else ""
    prompt = cancel_final_confirm(language, name, when)
    replay = _gather(state, prompt)

    if digit == "2":
        return _hangup(state, cancel_declined(language))
    if digit != "1":
        return await _invalid_retry(call_sid, state, replay)

    if appt is None:
        return _hangup(state, cancel_failed(language))
    if not _is_cancellable(appt):
        return _hangup(state, cancel_terminal(language))
    if not _is_upcoming(appt, _now_ist()):
        return _hangup(state, cancel_no_appointment(language))

    try:
        await AppointmentService(db).cancel(
            CancelRequest(
                appointment_id=int(pending_id),
                reason="Cancelled via voice assistant",
            ),
            user_id=None,
        )
    except BadRequestException as exc:
        detail = str(getattr(exc, "detail", "") or "")
        logger.error("  ✗ [%s] Cancel rejected: %s", call_sid, detail)
        if "terminal" in detail.lower():
            return _hangup(state, cancel_terminal(language))
        return _hangup(state, cancel_failed(language))
    except NotFoundException:
        logger.error("  ✗ [%s] Cancel not found", call_sid)
        return _hangup(state, cancel_failed(language))

    logger.info("  ↳ [%s] Appointment %s cancelled", call_sid, pending_id)
    await session_store.update_session(
        call_sid, {"cancel_hangup_after_playback": True}
    )
    text = _CANCEL_SUCCESS_EN if language == "en" else cancel_success(language)
    return _hangup(state, text)
