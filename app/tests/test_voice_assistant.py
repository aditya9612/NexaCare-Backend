import pytest

from app.ai.voice_appointment_assistant.assistant import VoiceAppointmentAssistant
from app.ai.voice_appointment_assistant.emergency import emergency_message, is_emergency
from app.ai.voice_appointment_assistant.language import detect_language
from app.ai.voice_appointment_assistant.schemas import VoiceIntent, VoiceState, VoiceStep
from app.utils.twiml_builder import (
    gather_speech,
    gather_speech_or_dtmf,
    say,
    twilio_say_language,
    twiml_response,
)


def test_is_emergency_english():
    assert is_emergency("I have severe chest pain")
    assert is_emergency("breathing problem")


def test_is_emergency_hindi():
    assert is_emergency("सीने में दर्द है")


def test_emergency_message_multilingual():
    assert "emergency" in emergency_message("en").lower()
    assert "आपातकाल" in emergency_message("hi")
    assert "आपत्कालीन" in emergency_message("mr")


def test_detect_language_hindi():
    assert detect_language("नमस्ते मुझे अपॉइंटमेंट चाहिए") == "hi"


def test_detect_language_marathi():
    assert detect_language("नमस्कार मला भेट हवी आहे") == "mr"


def test_detect_language_english():
    assert detect_language("I want to book an appointment") == "en"


def test_twilio_say_language_codes():
    assert twilio_say_language("en") == "en-IN"
    assert twilio_say_language("hi") == "hi-IN"
    assert twilio_say_language("mr") == "mr-IN"


def test_gather_speech_contains_speech_input():
    xml = twiml_response(
        gather_speech("http://example.com/turn", "Hello", language="en-IN")
    )
    assert 'input="speech"' in xml
    assert "Hello" in xml
    assert "Redirect" in xml


def test_gather_speech_or_dtmf():
    xml = twiml_response(
        gather_speech_or_dtmf("http://example.com/turn", "Press 1 or speak", language="hi-IN")
    )
    assert "speech dtmf" in xml
    assert "Press 1 or speak" in xml


def test_booking_flow_one_question_at_a_time():
    assistant = VoiceAppointmentAssistant()
    state = VoiceState(call_sid="CA123", step=VoiceStep.GREET, language="en")

    turn = assistant.process_turn(state, "I want to book an appointment")
    assert turn.state.intent == VoiceIntent.BOOK
    assert turn.state.step == VoiceStep.BOOK_NAME
    assert "name" in turn.prompt.lower()

    turn = assistant.process_turn(turn.state, "Rahul Sharma")
    assert turn.state.step == VoiceStep.BOOK_DOCTOR
    assert turn.state.patient_name == "Rahul Sharma"

    turn = assistant.process_turn(turn.state, "cardiologist")
    assert turn.state.step == VoiceStep.BOOK_SYMPTOMS

    turn = assistant.process_turn(turn.state, "chest discomfort")
    assert turn.state.step == VoiceStep.BOOK_DATE

    turn = assistant.process_turn(turn.state, "tomorrow")
    assert turn.state.step == VoiceStep.BOOK_TIME

    turn = assistant.process_turn(turn.state, "10 am")
    assert turn.state.step in (VoiceStep.BOOK_MOBILE, VoiceStep.BOOK_CONFIRM)

    if turn.state.step == VoiceStep.BOOK_MOBILE:
        turn = assistant.process_turn(turn.state, "9876543210")
    assert turn.state.step == VoiceStep.BOOK_CONFIRM
    assert "Should I confirm" in turn.prompt or "confirm" in turn.prompt.lower()


def test_emergency_short_circuits_booking():
    assistant = VoiceAppointmentAssistant()
    state = VoiceState(call_sid="CA123", step=VoiceStep.BOOK_SYMPTOMS, language="en")
    turn = assistant.process_turn(state, "severe bleeding")
    assert turn.hangup is True
    assert turn.state.step == VoiceStep.EMERGENCY


def test_confirmation_format_includes_all_fields():
    assistant = VoiceAppointmentAssistant()
    state = VoiceState(
        call_sid="CA123",
        step=VoiceStep.BOOK_CONFIRM,
        language="en",
        patient_name="Rahul",
        doctor_or_department="Cardiologist",
        appointment_date="2026-05-28",
        appointment_time="10:00",
        mobile_number="9876543210",
    )
    turn = assistant.process_turn(state, "please repeat")
    assert "Rahul" in turn.prompt
    assert "Cardiologist" in turn.prompt
    assert "9876543210" in turn.prompt


def test_booking_json_payload():
    from app.ai.voice_appointment_assistant.schemas import VoiceBookingPayload

    state = VoiceState(
        patient_name="A",
        doctor_or_department="B",
        symptoms="C",
        appointment_date="2026-05-28",
        appointment_time="10:00",
        mobile_number="9999999999",
        language="hi",
    )
    payload = VoiceBookingPayload.from_state(state)
    assert payload.model_dump() == {
        "patient_name": "A",
        "doctor_or_department": "B",
        "symptoms": "C",
        "appointment_date": "2026-05-28",
        "appointment_time": "10:00",
        "mobile_number": "9999999999",
        "language": "hi",
    }


def test_start_call_greeting():
    assistant = VoiceAppointmentAssistant()
    state = VoiceState(call_sid="CA1", language="hi")
    turn = assistant.start_call(state)
    assert "नेक्सा" in turn.prompt or "Nexa" in turn.prompt
    assert turn.state.step == VoiceStep.INTENT
