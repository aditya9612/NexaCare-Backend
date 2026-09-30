"""DTMF 3 cancel uses the existing service_menu branch only."""

from types import SimpleNamespace

from starlette.requests import Request

from app.agent.router import service_menu
from app.core.constants import AppointmentStatus
from app.core.exceptions import BadRequestException, NotFoundException
from app.schemas.appointment_schema import CancelRequest


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
            "from_number": "+919876543210",
            "twilio_language": "en-IN",
            "voice_profile": "Polly.Aditi",
            "patient_id": None,
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
    return store


class _Voice:
    def __init__(self, db):
        self.db = db
        self.patient = SimpleNamespace(
            id=7, guardian_patient_id=None, phone="+919876543210"
        )
        self.by_id_patient = None
        self.confirmed = [SimpleNamespace(id=11, patient_id=7)]
        self.pending = []
        self.dependents = {}
        self.search_results = []
        self.find_patient_calls = []
        self.find_upcoming_calls = []
        self.list_all_calls = []
        self.list_dependents_calls = []
        self.search_calls = []
        self.patient_repo = SimpleNamespace(
            get_by_id=self._get_by_id,
            list_dependents=self._list_dependents,
            search=self._search,
        )
        self.appointment_repo = SimpleNamespace(list_all=self._list_all)

    async def _find_patient(self, mobile):
        self.find_patient_calls.append(mobile)
        return self.patient

    async def _find_upcoming_appointment(self, mobile):
        self.find_upcoming_calls.append(mobile)
        return None

    async def _get_by_id(self, patient_id):
        return self.by_id_patient

    async def _list_dependents(self, guardian_patient_id):
        self.list_dependents_calls.append(guardian_patient_id)
        return list(self.dependents.get(guardian_patient_id, []))

    async def _search(self, q, skip=0, limit=20, **_kwargs):
        self.search_calls.append({"q": q, "limit": limit})
        return list(self.search_results)

    async def _list_all(self, **kwargs):
        self.list_all_calls.append(kwargs)
        status = kwargs.get("status")
        rows = []
        if status == AppointmentStatus.CONFIRMED:
            rows = list(self.confirmed)
        elif status == AppointmentStatus.PENDING:
            rows = list(self.pending)
        elif isinstance(status, (list, tuple, set)):
            if AppointmentStatus.CONFIRMED in status:
                rows.extend(self.confirmed)
            if AppointmentStatus.PENDING in status:
                rows.extend(self.pending)
        requested = kwargs.get("patient_id")
        if requested is not None:
            allowed = set(requested) if isinstance(requested, (list, tuple, set)) else {requested}
            rows = [row for row in rows if getattr(row, "patient_id", None) in allowed]
        limit = kwargs.get("limit") or 20
        return rows[:limit]


class _Appointments:
    def __init__(self, db):
        self.db = db
        self.calls = []
        self.error = None
        self.rows = {}

    async def get_by_id(self, appointment_id):
        row = self.rows.get(int(appointment_id))
        if row is None:
            raise NotFoundException("Appointment not found")
        return row

    async def cancel(self, data, user_id):
        self.calls.append((data, user_id))
        if self.error:
            raise self.error
        return SimpleNamespace(id=data.appointment_id)


def _install(monkeypatch, voice: _Voice, appointments: _Appointments):
    monkeypatch.setattr(
        "app.services.voice_assistant_service.VoiceAssistantService",
        lambda db: voice,
    )
    monkeypatch.setattr(
        "app.services.appointment_service.AppointmentService",
        lambda db: appointments,
    )


def _body(response) -> str:
    raw = response.body
    return raw.decode() if isinstance(raw, bytes) else raw


async def test_digit_3_cancels_confirmed_appointment(monkeypatch):
    _session(monkeypatch)
    voice = _Voice(None)
    appointments = _Appointments(None)
    _install(monkeypatch, voice, appointments)

    response = await service_menu(_request("3"), db=object())
    text = _body(response)

    assert len(appointments.calls) == 1
    data, user_id = appointments.calls[0]
    assert isinstance(data, CancelRequest)
    assert data.appointment_id == 11
    assert data.reason == "Cancelled via voice assistant"
    assert user_id is None
    assert voice.find_patient_calls == ["+919876543210"]
    assert voice.find_upcoming_calls == []
    assert len(voice.list_all_calls) == 1
    assert voice.list_all_calls[0]["status"] == [
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.PENDING,
    ]
    assert 7 in voice.list_all_calls[0]["patient_id"]
    assert voice.list_all_calls[0]["limit"] == 50
    assert "Your appointment has been cancelled successfully." in text
    assert "<Hangup/>" in text
    assert 'language="en-IN"' in text
    assert "not yet implemented" not in text


async def test_digit_3_uses_pending_when_confirmed_missing(monkeypatch):
    _session(monkeypatch)
    voice = _Voice(None)
    voice.confirmed = []
    voice.pending = [SimpleNamespace(id=22, patient_id=7)]
    appointments = _Appointments(None)
    _install(monkeypatch, voice, appointments)

    response = await service_menu(_request("3"), db=object())

    data, user_id = appointments.calls[0]
    assert data.appointment_id == 22
    assert user_id is None
    assert "Your appointment has been cancelled successfully." in _body(response)


async def test_digit_3_session_patient_id_uses_confirmed_then_pending(monkeypatch):
    _session(monkeypatch, from_number="", patient_id=7)
    voice = _Voice(None)
    voice.patient = None
    voice.by_id_patient = SimpleNamespace(id=7, guardian_patient_id=None, phone=None)
    voice.confirmed = []
    voice.pending = [SimpleNamespace(id=33, patient_id=7)]
    appointments = _Appointments(None)
    _install(monkeypatch, voice, appointments)

    response = await service_menu(_request("3"), db=object())

    assert len(voice.list_all_calls) == 1
    assert voice.list_all_calls[0]["status"] == [
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.PENDING,
    ]
    assert voice.list_all_calls[0]["patient_id"] == [7]
    assert voice.list_all_calls[0]["limit"] == 50
    assert voice.search_calls == []
    data, user_id = appointments.calls[0]
    assert data.appointment_id == 33
    assert data.reason == "Cancelled via voice assistant"
    assert user_id is None
    assert "Your appointment has been cancelled successfully." in _body(response)


async def test_digit_3_cancels_session_appointment_without_phone_lookup(monkeypatch):
    _session(monkeypatch, appointment_id=44, patient_id=7)
    voice = _Voice(None)
    voice.patient = SimpleNamespace(id=7, guardian_patient_id=None, phone="+919876543210")
    appointments = _Appointments(None)
    appointments.rows[44] = SimpleNamespace(id=44, patient_id=99)
    _install(monkeypatch, voice, appointments)

    text = _body(await service_menu(_request("3"), db=object()))

    data, user_id = appointments.calls[0]
    assert data.appointment_id == 44
    assert data.reason == "Cancelled via voice assistant"
    assert user_id is None
    assert voice.find_patient_calls == []
    assert voice.find_upcoming_calls == []
    assert voice.list_all_calls == []
    assert voice.list_dependents_calls == []
    assert voice.search_calls == []
    assert "Your appointment has been cancelled successfully." in text
    assert "<Hangup/>" in text


async def test_digit_3_invalid_session_appointment_id(monkeypatch):
    _session(monkeypatch, appointment_id=404)
    voice = _Voice(None)
    appointments = _Appointments(None)
    _install(monkeypatch, voice, appointments)

    text = _body(await service_menu(_request("3"), db=object()))

    assert appointments.calls == []
    assert voice.find_patient_calls == []
    assert "could not cancel your appointment" in text
    assert "<Hangup/>" in text


async def test_digit_3_session_appointment_already_terminal(monkeypatch):
    _session(monkeypatch, appointment_id=44, language="hi", twilio_language="hi-IN")
    voice = _Voice(None)
    appointments = _Appointments(None)
    appointments.rows[44] = SimpleNamespace(id=44, patient_id=99)
    appointments.error = BadRequestException("Cannot cancel a terminal appointment")
    _install(monkeypatch, voice, appointments)

    text = _body(await service_menu(_request("3"), db=object()))

    assert appointments.calls[0][0].appointment_id == 44
    assert voice.find_patient_calls == []
    assert "पहले ही पूरी हो चुकी है या रद्द हो चुकी है" in text
    assert 'language="hi-IN"' in text
    assert "<Hangup/>" in text


async def test_digit_3_speaks_selected_language(monkeypatch):
    cases = (
        ("en", "en-IN", "Your appointment has been cancelled successfully."),
        ("hi", "hi-IN", "आपका अपॉइंटमेंट सफलतापूर्वक रद्द कर दिया गया है।"),
        ("mr", "mr-IN", "आपली अपॉइंटमेंट यशस्वीरित्या रद्द करण्यात आली आहे."),
    )
    for language, twilio_language, phrase in cases:
        _session(
            monkeypatch,
            language=language,
            twilio_language=twilio_language,
            voice_profile="Polly.Aditi",
        )
        voice = _Voice(None)
        appointments = _Appointments(None)
        _install(monkeypatch, voice, appointments)

        text = _body(await service_menu(_request("3"), db=object()))

        data, user_id = appointments.calls[-1]
        assert data.appointment_id == 11
        assert data.reason == "Cancelled via voice assistant"
        assert user_id is None
        assert phrase in text
        assert f'language="{twilio_language}"' in text
        assert "<Hangup/>" in text
        assert "not yet implemented" not in text


async def test_digit_3_patient_not_found(monkeypatch):
    _session(monkeypatch, patient_id=None)
    voice = _Voice(None)
    voice.patient = None
    appointments = _Appointments(None)
    _install(monkeypatch, voice, appointments)

    response = await service_menu(_request("3"), db=object())
    text = _body(response)

    assert appointments.calls == []
    assert "could not find a patient record" in text
    assert "<Hangup/>" in text
    assert "not yet implemented" not in text


async def test_digit_3_no_appointment(monkeypatch):
    _session(monkeypatch)
    voice = _Voice(None)
    voice.confirmed = []
    appointments = _Appointments(None)
    _install(monkeypatch, voice, appointments)

    response = await service_menu(_request("3"), db=object())
    text = _body(response)

    assert appointments.calls == []
    assert "do not have an upcoming confirmed or pending appointment" in text
    assert "<Hangup/>" in text
    assert "not yet implemented" not in text


async def test_digit_3_terminal_appointment(monkeypatch):
    _session(monkeypatch)
    voice = _Voice(None)
    appointments = _Appointments(None)
    appointments.error = BadRequestException("Cannot cancel a terminal appointment")
    _install(monkeypatch, voice, appointments)

    response = await service_menu(_request("3"), db=object())
    text = _body(response)

    assert len(appointments.calls) == 1
    assert "already completed or cancelled" in text
    assert "<Hangup/>" in text
    assert "not yet implemented" not in text


async def test_digit_3_not_found_and_generic_error(monkeypatch):
    _session(monkeypatch)
    voice = _Voice(None)
    missing = _Appointments(None)
    missing.error = NotFoundException("Appointment not found")
    _install(monkeypatch, voice, missing)

    missing_text = _body(await service_menu(_request("3"), db=object()))
    assert "could not cancel your appointment" in missing_text
    assert "<Hangup/>" in missing_text

    voice.upcoming = SimpleNamespace(id=11)
    broken = _Appointments(None)
    broken.error = RuntimeError("db down")
    _install(monkeypatch, voice, broken)
    error_text = _body(await service_menu(_request("3"), db=object()))
    assert "could not cancel your appointment" in error_text
    assert "not yet implemented" not in error_text


async def test_digit_2_reschedule_single_appointment_offers_slots(monkeypatch):
    store = _session(monkeypatch, language="en", base_url="http://localhost:8000")
    voice = _Voice(None)
    appointments = _Appointments(None)
    _install(monkeypatch, voice, appointments)

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
    voice = _Voice(None)
    appointments = _Appointments(None)
    _install(monkeypatch, voice, appointments)

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
    assert appointments.calls == []


async def test_digit_2_reschedule_patient_not_found(monkeypatch):
    _session(monkeypatch, language="en", base_url="http://localhost:8000")
    voice = _Voice(None)
    appointments = _Appointments(None)
    _install(monkeypatch, voice, appointments)

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
    voice = _Voice(None)
    appointments = _Appointments(None)
    _install(monkeypatch, voice, appointments)

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
    voice = _Voice(None)
    appointments = _Appointments(None)
    _install(monkeypatch, voice, appointments)

    async def booking_twiml(*_args, **_kwargs):
        return "<Response><Say>collect name</Say></Response>"

    monkeypatch.setattr("app.agent.router._enter_booking_flow", booking_twiml)

    response = await service_menu(_request("1"), db=object())
    text = _body(response)

    assert text == "<Response><Say>collect name</Say></Response>"
    assert appointments.calls == []
    assert voice.find_patient_calls == []


async def test_digit_4_still_asks_faq(monkeypatch):
    _session(monkeypatch, language="en", base_url="http://localhost:8000")
    voice = _Voice(None)
    appointments = _Appointments(None)
    _install(monkeypatch, voice, appointments)

    def faq_twiml(_state):
        return "<Response><Say>ask faq</Say></Response>"

    monkeypatch.setattr("app.agent.router.greet_node.build_ask_faq_twiml", faq_twiml)

    response = await service_menu(_request("4"), db=object())

    assert _body(response) == "<Response><Say>ask faq</Say></Response>"
    assert appointments.calls == []
    assert voice.find_patient_calls == []
