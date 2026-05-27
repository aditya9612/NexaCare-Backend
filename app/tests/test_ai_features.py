import pytest

from app.ai.appointment_assistant.assistant import AppointmentAssistant
from app.ai.appointment_assistant.schemas import BookingStep, BookingState
from app.ai.voice_call.handler import VoiceCallHandler
from app.utils.twiml_builder import gather, say, twiml_response


def test_voice_handler_dtmf_mapping():
    handler = VoiceCallHandler()
    assert handler.parse_dtmf("1") == "confirm_appointment"
    assert handler.parse_dtmf("2") == "cancel_appointment"
    assert handler.parse_dtmf("3") == "reschedule_appointment"
    assert handler.parse_dtmf("9") == "unknown"


def test_twiml_builder_contains_gather():
    xml = twiml_response(gather("http://example.com/gather", "Press 1 to confirm", num_digits=1))
    assert "Gather" in xml
    assert "Press 1 to confirm" in xml
    assert xml.startswith('<?xml version="1.0"')


def test_booking_state_roundtrip():
    state = BookingState(
        step=BookingStep.PICK_SLOT,
        patient_id=1,
        doctor_id=2,
        doctor_name="Dr. Smith",
    )
    restored = BookingState.from_dict(state.to_dict())
    assert restored.step == BookingStep.PICK_SLOT
    assert restored.doctor_id == 2


def test_parse_datetime_from_text():
    assistant = object.__new__(AppointmentAssistant)
    d, t = assistant._parse_datetime_from_text("tomorrow at 10 am")
    assert d is not None
    assert t is not None
    assert t.hour == 10
