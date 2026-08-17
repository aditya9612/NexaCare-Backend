"""Voice reminder TwiML uses Twilio <Say> (outbound does not use Sarvam)."""

from app.ai.voice_call.handler import VoiceCallHandler
from app.services.voice_service import VoiceService


def test_handler_localized_menu_and_responses():
    handler = VoiceCallHandler()
    assert "1" in handler.menu_for_language("en")
    assert handler.menu_for_language("mr") != handler.menu_for_language("en")
    assert "पुष्टि" in handler.dtmf_response("confirm", "hi")


def test_gather_reminder_uses_twilio_say():
    service = VoiceService.__new__(VoiceService)
    xml = service._gather_reminder(
        "https://example.com/gather",
        "Hello appointment reminder",
        "No input goodbye",
        "en",
    )
    assert "<Gather" in xml
    assert "<Say language=" in xml
    assert "<Play>" not in xml
    assert "Hello appointment reminder" in xml
    assert "https://example.com/gather" in xml


def test_reminder_speak_uses_say_for_english():
    service = VoiceService.__new__(VoiceService)
    fragment = service._reminder_speak("Goodbye", "en")
    assert fragment.startswith("<Say")
    assert 'language="en-IN"' in fragment
    assert "Goodbye" in fragment


def test_reminder_speak_uses_marathi_voice():
    service = VoiceService.__new__(VoiceService)
    fragment = service._reminder_speak("नमस्कार", "mr")
    assert 'language="mr-IN"' in fragment
    assert 'voice="Google.mr-IN-Chirp3-HD-Aoede"' in fragment
