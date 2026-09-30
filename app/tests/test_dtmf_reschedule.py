"""Unit tests for DTMF reschedule appointment picker helpers."""

from datetime import date, time
from types import SimpleNamespace

from app.agent.nodes.reschedule import (
    appointment_to_candidate,
    confirm_and_reschedule,
    process_select_appointment,
)
from app.core.exceptions import BadRequestException
from app.schemas.appointment_schema import RescheduleRequest


def test_process_select_appointment_picks_by_digit():
    state = {
        "call_sid": "CA1",
        "language": "en",
        "twilio_language": "en-IN",
        "base_url": "http://localhost:8000",
        "reschedule_candidates": [
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
        ],
    }

    result = process_select_appointment(state, "2")
    assert result["_pending"] == "fetch_slots"
    assert result["appointment_id"] == 12
    assert result["patient_name"] == "Priya"
    assert result["selected_doctor_id"] == 4


def test_process_select_appointment_invalid_digit_replays_menu():
    state = {
        "call_sid": "CA1",
        "language": "en",
        "twilio_language": "en-IN",
        "base_url": "http://localhost:8000",
        "reschedule_candidates": [
            {
                "appointment_id": 11,
                "patient_name": "Rahul",
                "doctor_name": "Sharma",
                "date": "2026-10-01",
                "time": "10:00:00",
            }
        ],
    }
    result = process_select_appointment(state, "9")
    assert result["step"] == "reschedule_select_appointment"
    assert "Press 1 for Rahul" in result["_twiml"]


def test_appointment_to_candidate_uses_patient_and_doctor_names():
    appt = SimpleNamespace(
        id=5,
        appointment_number="N-5",
        patient_id=1,
        doctor_id=2,
        appointment_date=date(2026, 10, 3),
        appointment_time=time(9, 30),
        patient=SimpleNamespace(first_name="Asha", last_name="K"),
        doctor=SimpleNamespace(first_name="Mehta", last_name=""),
    )
    candidate = appointment_to_candidate(appt)
    assert candidate["appointment_id"] == 5
    assert candidate["patient_name"] == "Asha K"
    assert candidate["doctor_name"] == "Mehta"
    assert candidate["time"] == "09:30:00"


async def test_confirm_and_reschedule_success(monkeypatch):
    calls = []

    class _Svc:
        def __init__(self, db):
            self.db = db

        async def reschedule(self, data, user_id):
            calls.append((data, user_id))
            return SimpleNamespace(id=data.appointment_id)

    monkeypatch.setattr(
        "app.agent.nodes.reschedule.AppointmentService",
        _Svc,
    )

    state = {
        "call_sid": "CA1",
        "language": "en",
        "twilio_language": "en-IN",
        "base_url": "http://localhost:8000",
        "appointment_id": 11,
        "selected_slot": {"date": "2026-10-05", "time": "11:00:00"},
    }
    result = await confirm_and_reschedule(state, db=object())
    assert result["step"] == "rescheduled"
    assert "rescheduled successfully" in result["_twiml"]
    data, user_id = calls[0]
    assert isinstance(data, RescheduleRequest)
    assert data.appointment_id == 11
    assert data.appointment_date == date(2026, 10, 5)
    assert user_id is None


async def test_confirm_and_reschedule_terminal(monkeypatch):
    class _Svc:
        def __init__(self, db):
            pass

        async def reschedule(self, data, user_id):
            raise BadRequestException("Cannot reschedule a terminal appointment")

    monkeypatch.setattr(
        "app.agent.nodes.reschedule.AppointmentService",
        _Svc,
    )
    state = {
        "call_sid": "CA1",
        "language": "en",
        "twilio_language": "en-IN",
        "base_url": "",
        "appointment_id": 11,
        "selected_slot": {"date": "2026-10-05", "time": "11:00:00"},
    }
    result = await confirm_and_reschedule(state, db=object())
    assert result["step"] == "error"
    assert "cannot be rescheduled" in result["_twiml"]
