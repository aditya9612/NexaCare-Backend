"""DTMF 3 cancel: patients → appointments → confirm → AppointmentService.cancel."""

from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

from starlette.requests import Request

from app.agent.router import service_menu
from app.core.constants import AppointmentStatus
from app.core.exceptions import BadRequestException, NotFoundException
from app.schemas.appointment_schema import CancelRequest

NOW = datetime(2026, 9, 30, 19, 19, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def _request(digit: str) -> Request:
    body = f"CallSid=CA_CANCEL&Digits={digit}".encode()
    sent = {"done": False}

    async def receive():
        if sent["done"]:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/agent/v1/voice/menu",
        "raw_path": b"/agent/v1/voice/menu",
        "query_string": b"",
        "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
    }
    return Request(scope, receive)


def _session(monkeypatch, **extra):
    store = {
        "CA_CANCEL": {
            "retry_count": 0,
            "from_number": "+917350334029",
            "twilio_language": "en-IN",
            "voice_profile": "Polly.Aditi",
            "patient_id": None,
            "language": "en",
            "base_url": "http://localhost:8000",
            "service": None,
            "cancel_step": None,
            **extra,
        }
    }

    async def get_session(call_sid):
        return store.get(call_sid)

    async def update_session(call_sid, updates):
        store[call_sid].update(updates)

    async def allow_webhook(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.agent.session_store.get_session", get_session)
    monkeypatch.setattr("app.agent.session_store.update_session", update_session)
    monkeypatch.setattr("app.agent.router.require_voice_webhook_auth", allow_webhook)
    monkeypatch.setattr("app.agent.nodes.cancel._now_ist", lambda: NOW)
    return store


class _Patients:
    def __init__(self, rows, dependents=None):
        self.rows = {p.id: p for p in rows}
        self.phone_rows = list(rows)
        self.dependents = dependents or {}

    async def list_by_phone(self, phone, limit=5):
        return [p for p in self.phone_rows if p.phone][:limit]

    async def get_by_phone(self, phone):
        hits = [p for p in self.phone_rows if p.phone]
        return hits[0] if hits else None

    async def get_by_id(self, patient_id):
        return self.rows.get(int(patient_id))

    async def list_dependents(self, guardian_patient_id):
        return list(self.dependents.get(int(guardian_patient_id), []))


class _Appts:
    def __init__(self, rows):
        self.rows = {a.id: a for a in rows}

    async def list_all(self, **kwargs):
        pid = kwargs.get("patient_id")
        statuses = kwargs.get("status") or []
        start = kwargs.get("start_date")
        out = []
        for row in self.rows.values():
            if pid is not None and row.patient_id != pid:
                continue
            if statuses and row.appointment_status not in statuses:
                continue
            if start and row.appointment_date < start:
                continue
            out.append(row)
        return out

    async def get_by_id(self, appointment_id):
        return self.rows.get(int(appointment_id))


class _Appointments:
    def __init__(self):
        self.calls = []
        self.error = None

    async def cancel(self, data, user_id):
        self.calls.append((data, user_id))
        if self.error:
            raise self.error
        return SimpleNamespace(id=data.appointment_id)


def _p(pid, first, last="", phone=None, guardian=None):
    return SimpleNamespace(
        id=pid,
        first_name=first,
        last_name=last,
        phone=phone,
        guardian_patient_id=guardian,
    )


def _a(aid, patient_id, status, day, hour=9, minute=0):
    return SimpleNamespace(
        id=aid,
        patient_id=patient_id,
        appointment_status=status,
        appointment_date=day,
        appointment_time=time(hour, minute),
    )


def _install(monkeypatch, patients: _Patients, appts: _Appts, service: _Appointments):
    monkeypatch.setattr("app.agent.nodes.cancel.PatientRepository", lambda db: patients)
    monkeypatch.setattr("app.agent.nodes.cancel.AppointmentRepository", lambda db: appts)
    monkeypatch.setattr("app.agent.nodes.cancel.AppointmentService", lambda db: service)


def _body(response) -> str:
    raw = response.body
    return raw.decode() if isinstance(raw, bytes) else raw


async def _confirm_cancel(monkeypatch, patients, appts, service):
    _install(monkeypatch, patients, appts, service)
    first = await service_menu(_request("3"), db=object())
    second = await service_menu(_request("1"), db=object())
    return first, second


def _holder_and_dependent():
    holder = _p(47, "जितेश", phone="+917350334029")
    dep = _p(226, "माझं नाव", guardian=47)
    return holder, dep


async def test_digit_3_no_patient(monkeypatch):
    store = _session(monkeypatch)
    store["CA_CANCEL"]["patient_id"] = None
    patients = _Patients([])
    appts = _Appts([])
    service = _Appointments()
    _install(monkeypatch, patients, appts, service)

    text = _body(await service_menu(_request("3"), db=object()))

    assert service.calls == []
    assert "could not find a patient record" in text
    assert "<Hangup/>" in text
    assert "not yet implemented" not in text


async def test_digit_3_one_patient_no_appointment(monkeypatch):
    _session(monkeypatch)
    holder, _ = _holder_and_dependent()
    patients = _Patients([holder])
    appts = _Appts([])
    service = _Appointments()
    _install(monkeypatch, patients, appts, service)

    text = _body(await service_menu(_request("3"), db=object()))

    assert service.calls == []
    assert "do not have an upcoming confirmed or pending appointment" in text
    assert "<Hangup/>" in text


async def test_digit_3_one_patient_one_pending_requires_confirm(monkeypatch):
    store = _session(monkeypatch)
    holder, _ = _holder_and_dependent()
    patients = _Patients([holder])
    appts = _Appts([_a(11, 47, AppointmentStatus.PENDING, date(2026, 10, 1))])
    service = _Appointments()
    _install(monkeypatch, patients, appts, service)

    text = _body(await service_menu(_request("3"), db=object()))

    assert service.calls == []
    assert store["CA_CANCEL"]["cancel_pending_id"] == 11
    assert store["CA_CANCEL"]["cancel_step"] == "confirm"
    assert "<Gather" in text
    assert "<Hangup/>" not in text or "</Gather>" in text
    assert "To cancel, press 1" in text


async def test_digit_3_one_patient_one_confirmed_then_dtmf_1_cancels(monkeypatch):
    _session(monkeypatch)
    holder, _ = _holder_and_dependent()
    patients = _Patients([holder])
    appts = _Appts([_a(11, 47, AppointmentStatus.CONFIRMED, date(2026, 10, 1))])
    service = _Appointments()
    first, second = await _confirm_cancel(monkeypatch, patients, appts, service)

    assert "To cancel, press 1" in _body(first)
    assert len(service.calls) == 1
    data, user_id = service.calls[0]
    assert isinstance(data, CancelRequest)
    assert data.appointment_id == 11
    assert data.reason == "Cancelled via voice assistant"
    assert user_id is None
    assert "Your appointment has been cancelled successfully." in _body(second)
    assert "<Hangup/>" in _body(second)


async def test_digit_3_one_patient_multiple_appointments_never_auto_cancels_first(monkeypatch):
    store = _session(monkeypatch)
    holder, _ = _holder_and_dependent()
    patients = _Patients([holder])
    confirmed = _a(10, 47, AppointmentStatus.CONFIRMED, date(2026, 10, 1), 9)
    pending_later = _a(22, 47, AppointmentStatus.PENDING, date(2026, 10, 5), 11)
    appts = _Appts([confirmed, pending_later])
    service = _Appointments()
    _install(monkeypatch, patients, appts, service)

    text = _body(await service_menu(_request("3"), db=object()))

    assert service.calls == []
    assert store["CA_CANCEL"]["cancel_candidates"] == [10, 22]
    assert store["CA_CANCEL"]["cancel_step"] == "select_appointment"
    assert "1" in text
    assert "<Gather" in text
    assert "press 1" not in text.lower() or "appointment" in text.lower()


async def test_digit_3_later_pending_not_hidden_by_earlier_confirmed(monkeypatch):
    store = _session(monkeypatch)
    holder, _ = _holder_and_dependent()
    patients = _Patients([holder])
    appts = _Appts(
        [
            _a(10, 47, AppointmentStatus.CONFIRMED, date(2026, 10, 1)),
            _a(22, 47, AppointmentStatus.PENDING, date(2026, 10, 10), 16),
        ]
    )
    service = _Appointments()
    _install(monkeypatch, patients, appts, service)

    await service_menu(_request("3"), db=object())
    assert 22 in store["CA_CANCEL"]["cancel_candidates"]
    assert 10 in store["CA_CANCEL"]["cancel_candidates"]


async def test_digit_3_multiple_patients_multiple_appointments(monkeypatch):
    store = _session(monkeypatch)
    holder, dep = _holder_and_dependent()
    patients = _Patients([holder, dep], dependents={47: [dep]})
    appts = _Appts(
        [
            _a(100, 47, AppointmentStatus.CONFIRMED, date(2026, 10, 1)),
            _a(239, 226, AppointmentStatus.PENDING, date(2026, 10, 1), 9),
            _a(240, 226, AppointmentStatus.CONFIRMED, date(2026, 10, 5), 11),
        ]
    )
    service = _Appointments()
    _install(monkeypatch, patients, appts, service)

    await service_menu(_request("3"), db=object())
    await service_menu(_request("2"), db=object())
    assert store["CA_CANCEL"]["cancel_patient_id"] == 226
    assert store["CA_CANCEL"]["cancel_candidates"] == [239, 240]
    assert service.calls == []

    await service_menu(_request("2"), db=object())
    assert store["CA_CANCEL"]["cancel_pending_id"] == 240
    text = _body(await service_menu(_request("1"), db=object()))
    assert [call[0].appointment_id for call in service.calls] == [240]
    assert "cancelled successfully" in text


async def test_digit_3_patient_dtmf_selects_second_patient(monkeypatch):
    store = _session(monkeypatch, language="mr", twilio_language="mr-IN")
    holder, dep = _holder_and_dependent()
    patients = _Patients([holder, dep], dependents={47: [dep]})
    appts = _Appts([_a(239, 226, AppointmentStatus.PENDING, date(2026, 10, 1))])
    service = _Appointments()
    _install(monkeypatch, patients, appts, service)

    first = _body(await service_menu(_request("3"), db=object()))
    assert service.calls == []
    assert store["CA_CANCEL"]["cancel_patient_ids"] == [47, 226]
    assert store["CA_CANCEL"]["cancel_step"] == "select_patient"
    assert "जितेश" in first
    assert "माझं नाव" in first
    assert "<Gather" in first

    second = _body(await service_menu(_request("2"), db=object()))
    assert store["CA_CANCEL"]["cancel_patient_id"] == 226
    assert store["CA_CANCEL"]["cancel_pending_id"] == 239
    assert store["CA_CANCEL"]["cancel_step"] == "confirm"
    assert service.calls == []
    assert "एक दाबा" in second


async def test_digit_3_appointment_dtmf_selects_exact_id_then_confirm(monkeypatch):
    store = _session(monkeypatch)
    holder, _ = _holder_and_dependent()
    patients = _Patients([holder])
    first_appt = _a(10, 47, AppointmentStatus.CONFIRMED, date(2026, 10, 1), 9)
    second_appt = _a(22, 47, AppointmentStatus.PENDING, date(2026, 10, 5), 11)
    appts = _Appts([first_appt, second_appt])
    service = _Appointments()
    _install(monkeypatch, patients, appts, service)

    await service_menu(_request("3"), db=object())
    await service_menu(_request("2"), db=object())
    assert store["CA_CANCEL"]["cancel_pending_id"] == 22
    assert service.calls == []

    text = _body(await service_menu(_request("1"), db=object()))
    assert service.calls[0][0].appointment_id == 22
    assert "cancelled successfully" in text


async def test_digit_3_final_dtmf_2_does_not_cancel(monkeypatch):
    _session(monkeypatch)
    holder, _ = _holder_and_dependent()
    patients = _Patients([holder])
    appts = _Appts([_a(11, 47, AppointmentStatus.PENDING, date(2026, 10, 1))])
    service = _Appointments()
    _install(monkeypatch, patients, appts, service)

    await service_menu(_request("3"), db=object())
    text = _body(await service_menu(_request("2"), db=object()))

    assert service.calls == []
    assert "has not been cancelled" in text
    assert "<Hangup/>" in text


async def test_digit_3_non_selected_appointments_unchanged(monkeypatch):
    _session(monkeypatch)
    holder, _ = _holder_and_dependent()
    patients = _Patients([holder])
    appts = _Appts(
        [
            _a(10, 47, AppointmentStatus.CONFIRMED, date(2026, 10, 1)),
            _a(22, 47, AppointmentStatus.PENDING, date(2026, 10, 5), 11),
        ]
    )
    service = _Appointments()
    _install(monkeypatch, patients, appts, service)

    await service_menu(_request("3"), db=object())
    await service_menu(_request("2"), db=object())
    await service_menu(_request("1"), db=object())

    assert [call[0].appointment_id for call in service.calls] == [22]
    assert appts.rows[10].appointment_status == AppointmentStatus.CONFIRMED


async def test_digit_3_past_and_non_cancellable_not_offered(monkeypatch):
    store = _session(monkeypatch)
    holder, _ = _holder_and_dependent()
    patients = _Patients([holder])
    appts = _Appts(
        [
            _a(1, 47, AppointmentStatus.PENDING, date(2026, 9, 1)),
            _a(2, 47, AppointmentStatus.COMPLETED, date(2026, 10, 2)),
            _a(3, 47, AppointmentStatus.CANCELLED, date(2026, 10, 3)),
            _a(4, 47, AppointmentStatus.PENDING, date(2026, 9, 30), 8),
            _a(11, 47, AppointmentStatus.PENDING, date(2026, 10, 1)),
        ]
    )
    service = _Appointments()
    _install(monkeypatch, patients, appts, service)

    await service_menu(_request("3"), db=object())
    assert store["CA_CANCEL"]["cancel_pending_id"] == 11
    assert store["CA_CANCEL"]["cancel_candidates"] == [11]


async def test_digit_3_session_appointment_id_only_confirms_when_unique(monkeypatch):
    store = _session(monkeypatch, appointment_id=44)
    holder, _ = _holder_and_dependent()
    patients = _Patients([holder])
    appts = _Appts([_a(44, 47, AppointmentStatus.PENDING, date(2026, 10, 1))])
    service = _Appointments()
    _install(monkeypatch, patients, appts, service)

    text = _body(await service_menu(_request("3"), db=object()))
    assert service.calls == []
    assert store["CA_CANCEL"]["cancel_pending_id"] == 44
    assert store["CA_CANCEL"]["cancel_step"] == "confirm"
    assert "will be cancelled" in text


async def test_digit_3_session_appointment_id_does_not_skip_list_when_multiple(monkeypatch):
    store = _session(monkeypatch, appointment_id=44)
    holder, _ = _holder_and_dependent()
    patients = _Patients([holder])
    appts = _Appts(
        [
            _a(44, 47, AppointmentStatus.PENDING, date(2026, 10, 1)),
            _a(55, 47, AppointmentStatus.CONFIRMED, date(2026, 10, 8)),
        ]
    )
    service = _Appointments()
    _install(monkeypatch, patients, appts, service)

    await service_menu(_request("3"), db=object())
    assert service.calls == []
    assert store["CA_CANCEL"]["cancel_step"] == "select_appointment"
    assert store["CA_CANCEL"]["cancel_candidates"] == [44, 55]


async def test_digit_3_invalid_session_appointment_falls_through_to_lookup(monkeypatch):
    store = _session(monkeypatch, appointment_id=404)
    holder, _ = _holder_and_dependent()
    patients = _Patients([holder])
    appts = _Appts([_a(11, 47, AppointmentStatus.PENDING, date(2026, 10, 1))])
    service = _Appointments()
    _install(monkeypatch, patients, appts, service)

    await service_menu(_request("3"), db=object())
    assert service.calls == []
    assert store["CA_CANCEL"]["cancel_pending_id"] == 11


async def test_digit_3_session_appointment_terminal_uses_other_cancellable(monkeypatch):
    store = _session(monkeypatch, appointment_id=44)
    holder, _ = _holder_and_dependent()
    patients = _Patients([holder])
    appts = _Appts(
        [
            _a(44, 47, AppointmentStatus.COMPLETED, date(2026, 10, 1)),
            _a(22, 47, AppointmentStatus.PENDING, date(2026, 10, 5)),
        ]
    )
    service = _Appointments()
    _install(monkeypatch, patients, appts, service)

    await service_menu(_request("3"), db=object())
    assert service.calls == []
    assert store["CA_CANCEL"]["cancel_pending_id"] == 22


async def test_digit_3_speaks_selected_language(monkeypatch):
    cases = (
        ("en", "en-IN", "Your appointment has been cancelled successfully."),
        ("hi", "hi-IN", "आपका अपॉइंटमेंट सफलतापूर्वक रद्द कर दिया गया है।"),
        ("mr", "mr-IN", "आपली अपॉइंटमेंट यशस्वीरित्या रद्द करण्यात आली आहे."),
    )
    for language, twilio_language, phrase in cases:
        _session(monkeypatch, language=language, twilio_language=twilio_language)
        holder, _ = _holder_and_dependent()
        patients = _Patients([holder])
        appts = _Appts([_a(11, 47, AppointmentStatus.PENDING, date(2026, 10, 1))])
        service = _Appointments()
        first, second = await _confirm_cancel(monkeypatch, patients, appts, service)
        assert "Gather" in _body(first)
        assert phrase in _body(second)
        assert f'language="{twilio_language}"' in _body(second) or "Play" in _body(second)
        assert "<Hangup/>" in _body(second)
        assert "not yet implemented" not in _body(second)


async def test_digit_3_confirm_then_terminal_error(monkeypatch):
    _session(monkeypatch)
    holder, _ = _holder_and_dependent()
    patients = _Patients([holder])
    appts = _Appts([_a(11, 47, AppointmentStatus.PENDING, date(2026, 10, 1))])
    service = _Appointments()
    service.error = BadRequestException("Cannot cancel a terminal appointment")
    _install(monkeypatch, patients, appts, service)

    await service_menu(_request("3"), db=object())
    text = _body(await service_menu(_request("1"), db=object()))
    assert "already completed or cancelled" in text
    assert "<Hangup/>" in text


async def test_digit_3_not_found_and_generic_error(monkeypatch):
    _session(monkeypatch)
    holder, _ = _holder_and_dependent()
    patients = _Patients([holder])
    appts = _Appts([_a(11, 47, AppointmentStatus.PENDING, date(2026, 10, 1))])

    missing = _Appointments()
    missing.error = NotFoundException("Appointment not found")
    _install(monkeypatch, patients, appts, missing)
    await service_menu(_request("3"), db=object())
    missing_text = _body(await service_menu(_request("1"), db=object()))
    assert "could not cancel your appointment" in missing_text

    _session(monkeypatch)
    broken = _Appointments()
    broken.error = RuntimeError("db down")
    _install(monkeypatch, patients, appts, broken)
    await service_menu(_request("3"), db=object())
    error_text = _body(await service_menu(_request("1"), db=object()))
    assert "could not cancel your appointment" in error_text
    assert "not yet implemented" not in error_text


async def test_digit_2_reschedule_single_appointment_offers_slots(monkeypatch):
    store = _session(monkeypatch, language="en", base_url="http://localhost:8000")

    candidate = {
        "appointment_id": 11,
        "appointment_number": "A-11",
        "patient_id": 7,
        "patient_name": "Rahul",
        "doctor_id": 3,
        "doctor_name": "Sharma",
        "date": "2026-10-01",
        "time": "10:00:00",
    }

    async def fake_list(*_args, **_kwargs):
        return [7], [candidate]

    async def fake_prepare(_db, state, chosen):
        return {
            "step": "select_slot",
            "service": "reschedule",
            "appointment_id": chosen["appointment_id"],
            "selected_doctor_id": chosen["doctor_id"],
            "selected_doctor_name": chosen["doctor_name"],
            "available_slots": [
                {"date": "2026-10-02", "time": "11:00:00", "doctor_id": 3},
            ],
            "_twiml": "<Response><Say>choose slot</Say></Response>",
        }

    monkeypatch.setattr(
        "app.agent.nodes.reschedule.list_upcoming_candidates",
        fake_list,
    )
    monkeypatch.setattr(
        "app.agent.nodes.reschedule.prepare_slot_selection",
        fake_prepare,
    )

    response = await service_menu(_request("2"), db=object())
    text = _body(response)

    assert "choose slot" in text
    assert "This service will be available soon." not in text
    assert store["CA_CANCEL"]["service"] == "reschedule"
    assert store["CA_CANCEL"]["step"] == "select_slot"
    assert store["CA_CANCEL"]["appointment_id"] == 11


async def test_digit_2_reschedule_multiple_asks_which_appointment(monkeypatch):
    store = _session(monkeypatch, language="en", base_url="http://localhost:8000")

    candidates = [
        {
            "appointment_id": 11,
            "appointment_number": "A-11",
            "patient_id": 7,
            "patient_name": "Rahul",
            "doctor_id": 3,
            "doctor_name": "Sharma",
            "date": "2026-10-01",
            "time": "10:00:00",
        },
        {
            "appointment_id": 12,
            "appointment_number": "A-12",
            "patient_id": 8,
            "patient_name": "Priya",
            "doctor_id": 4,
            "doctor_name": "Patel",
            "date": "2026-10-02",
            "time": "14:00:00",
        },
    ]

    async def fake_list(*_args, **_kwargs):
        return [7, 8], candidates

    monkeypatch.setattr(
        "app.agent.nodes.reschedule.list_upcoming_candidates",
        fake_list,
    )

    response = await service_menu(_request("2"), db=object())
    text = _body(response)

    assert "You have more than one upcoming appointment." in text
    assert "Press 1 for Rahul" in text
    assert "Press 2 for Priya" in text
    assert "<Gather" in text
    assert store["CA_CANCEL"]["step"] == "reschedule_select_appointment"
    assert store["CA_CANCEL"]["service"] == "reschedule"
    assert len(store["CA_CANCEL"]["reschedule_candidates"]) == 2


async def test_digit_2_reschedule_patient_not_found(monkeypatch):
    _session(monkeypatch, language="en", base_url="http://localhost:8000")

    async def fake_list(*_args, **_kwargs):
        return None, []

    monkeypatch.setattr(
        "app.agent.nodes.reschedule.list_upcoming_candidates",
        fake_list,
    )

    text = _body(await service_menu(_request("2"), db=object()))
    assert "could not find a patient record" in text
    assert "<Hangup/>" in text
    assert "This service will be available soon." not in text


async def test_digit_2_reschedule_no_appointment(monkeypatch):
    _session(monkeypatch, language="en", base_url="http://localhost:8000")

    async def fake_list(*_args, **_kwargs):
        return [7], []

    monkeypatch.setattr(
        "app.agent.nodes.reschedule.list_upcoming_candidates",
        fake_list,
    )

    text = _body(await service_menu(_request("2"), db=object()))
    assert "do not have an upcoming confirmed or pending appointment to reschedule" in text
    assert "<Hangup/>" in text


async def test_digit_1_still_enters_booking(monkeypatch):
    _session(monkeypatch)
    patients = _Patients([])
    appts = _Appts([])
    service = _Appointments()
    _install(monkeypatch, patients, appts, service)

    async def booking_twiml(*_args, **_kwargs):
        return "<Response><Say>collect name</Say></Response>"

    monkeypatch.setattr("app.agent.router._enter_booking_flow", booking_twiml)

    response = await service_menu(_request("1"), db=object())
    text = _body(response)

    assert text == "<Response><Say>collect name</Say></Response>"
    assert service.calls == []


async def test_digit_4_still_asks_faq(monkeypatch):
    _session(monkeypatch, language="en", base_url="http://localhost:8000")
    patients = _Patients([])
    appts = _Appts([])
    service = _Appointments()
    _install(monkeypatch, patients, appts, service)

    def faq_twiml(_state):
        return "<Response><Say>ask faq</Say></Response>"

    monkeypatch.setattr("app.agent.router.greet_node.build_ask_faq_twiml", faq_twiml)

    response = await service_menu(_request("4"), db=object())

    assert _body(response) == "<Response><Say>ask faq</Say></Response>"
    assert service.calls == []
