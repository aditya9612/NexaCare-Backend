"""Phase 1 Voice AI unit tests — providers, language, medical safety, webhook normalize."""

from app.core.constants import TelephonyProviderType, VoiceLanguage
from app.services.medical_safety_guard import MedicalSafetyGuard
from app.telephony.factory import ProviderFactory
from app.telephony.webhook_normalizer import normalize_webhook
from app.ai.voice_appointment_assistant.language import detect_language, language_select_prompt


def test_provider_factory_defaults_to_twilio():
    provider = ProviderFactory.create("twilio")
    assert provider.name == TelephonyProviderType.TWILIO


def test_provider_factory_exotel():
    provider = ProviderFactory.create("exotel")
    assert provider.name == TelephonyProviderType.EXOTEL


def test_twilio_webhook_normalize():
    payload = {
        "CallSid": "CA123",
        "From": "+919876543210",
        "To": "+911234567890",
        "Digits": "1",
        "SpeechResult": "book appointment",
        "Confidence": "0.9",
        "CallStatus": "completed",
        "CallDuration": "42",
    }
    n = normalize_webhook("twilio", payload)
    assert n.call_sid == "CA123"
    assert n.digits == "1"
    assert n.duration_seconds == 42
    assert n.provider == "twilio"


def test_exotel_webhook_normalize():
    payload = {
        "CallSid": "EXO999",
        "CallFrom": "9876543210",
        "CallTo": "08012345678",
        "digits": "2",
        "Status": "completed",
    }
    n = normalize_webhook("exotel", payload)
    assert n.call_sid == "EXO999"
    assert n.from_number == "9876543210"
    assert n.digits == "2"
    assert n.provider == "exotel"


def test_language_dtmf_map():
    assert VoiceLanguage.DTMF_MAP["1"] == "en"
    assert VoiceLanguage.DTMF_MAP["2"] == "hi"
    assert VoiceLanguage.DTMF_MAP["3"] == "mr"


def test_detect_language_is_fallback_only_helper():
    assert detect_language("नमस्ते मुझे मदद चाहिए", "en") == "hi"
    assert detect_language("hello I need help", "en") == "en"


def test_language_select_prompt_mentions_dtmf():
    prompt = language_select_prompt("en")
    assert "1" in prompt and "English" in prompt
    assert "2" in prompt and "Hindi" in prompt
    assert "3" in prompt and "Marathi" in prompt


def test_medical_safety_blocks_medicine():
    result = MedicalSafetyGuard.check("which medicine should I take for fever?", "en")
    assert result.is_medical_advice is True
    assert "not allowed" in result.refusal_message.lower() or "medical" in result.refusal_message.lower()


def test_medical_safety_allows_hours_question():
    result = MedicalSafetyGuard.check("what are your hospital hours?", "en")
    assert result.is_medical_advice is False


def test_indian_phone_last10_formats():
    from app.utils.phone_utils import indian_mobile_last10, normalize_phone

    assert indian_mobile_last10("9876543210") == "9876543210"
    assert indian_mobile_last10("+919876543210") == "9876543210"
    assert indian_mobile_last10("0919876543210") == "9876543210"
    assert normalize_phone("9876543210").endswith("9876543210")


def test_credential_crypto_roundtrip():
    from app.utils.credential_crypto import decrypt_secret, encrypt_secret

    plain = "exotel-secret-token"
    enc = encrypt_secret(plain)
    assert enc.startswith("enc:v1:")
    assert decrypt_secret(enc) == plain
    assert decrypt_secret(plain) == plain  # legacy plaintext passthrough


def test_twilio_signature_validation_helper():
    from app.telephony.webhook_auth import validate_twilio_signature
    import base64
    import hashlib
    import hmac

    url = "https://example.com/api/v1/voice-assistant/twiml/inbound"
    params = {"CallSid": "CA123", "From": "+919876543210"}
    token = "test_auth_token"
    s = url + "".join(k + params[k] for k in sorted(params.keys()))
    expected = base64.b64encode(
        hmac.new(token.encode(), s.encode(), hashlib.sha1).digest()
    ).decode()
    assert validate_twilio_signature(url, params, expected, token) is True
    assert validate_twilio_signature(url, params, "bad", token) is False


def test_assistant_url_provider_paths():
    from unittest.mock import MagicMock

    from app.services.voice_assistant_service import VoiceAssistantService

    svc = VoiceAssistantService(MagicMock())
    tw = svc._assistant_url("/turn", "twilio")
    exo = svc._assistant_url("/turn", "exotel")
    assert "/voice-assistant/twiml/turn" in tw
    assert "/voice-assistant/exotel/turn" in exo
