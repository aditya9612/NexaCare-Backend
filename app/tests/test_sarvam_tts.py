"""Local smoke helpers for Sarvam voice cloning + TwiML Play fallback."""

import base64
from unittest.mock import MagicMock, patch

from app.agent.nodes.greeting import build_greeting_twiml
from app.services import sarvam_tts


def test_speak_falls_back_to_say_when_clone_disabled():
    with patch.object(sarvam_tts.settings, "VOICE_CLONE_ENABLED", False):
        xml = sarvam_tts.speak("Hello from NexaCare", "en-IN", "https://example.com")
    assert xml.startswith("<Say")
    assert "Hello from NexaCare" in xml
    assert "<Play>" not in xml


def test_speak_uses_play_when_clone_ready(tmp_path):
    fake_audio = b"ID3fake-mp3-bytes"

    with (
        patch.object(sarvam_tts.settings, "VOICE_CLONE_ENABLED", True),
        patch.object(sarvam_tts.settings, "SARVAM_API_KEY", "test-key"),
        patch.object(sarvam_tts.settings, "SARVAM_VOICE_ID", ""),
        patch.object(sarvam_tts.settings, "SARVAM_SPEAKER", "ratan"),
        patch.object(sarvam_tts.settings, "SARVAM_TTS_CACHE_DIR", str(tmp_path)),
        patch.object(sarvam_tts, "synthesize_to_bytes", return_value=fake_audio),
    ):
        xml = sarvam_tts.speak("Hello from NexaCare", "en-IN", "https://example.ngrok-free.app")

    assert xml.startswith("<Play>")
    assert "/agent/v1/voice/audio/" in xml
    assert "</Play>" in xml
    cached = list(tmp_path.glob("*.mp3"))
    assert len(cached) == 1
    assert cached[0].read_bytes() == fake_audio


def test_speak_uses_play_when_voice_id_ready(tmp_path):
    fake_audio = b"ID3clone-mp3-bytes"
    voice_id = "27c4beed-27c5-4623-aabc-62339e9e40fa"

    with (
        patch.object(sarvam_tts.settings, "VOICE_CLONE_ENABLED", True),
        patch.object(sarvam_tts.settings, "SARVAM_API_KEY", "test-key"),
        patch.object(sarvam_tts.settings, "SARVAM_VOICE_ID", voice_id),
        patch.object(sarvam_tts.settings, "SARVAM_SPEAKER", "ratan"),
        patch.object(sarvam_tts.settings, "SARVAM_TTS_CACHE_DIR", str(tmp_path)),
        patch.object(sarvam_tts, "synthesize_to_bytes", return_value=fake_audio),
    ):
        assert sarvam_tts.uses_cloned_voice() is True
        xml = sarvam_tts.speak("नमस्कार", "mr-IN", "https://example.ngrok-free.app")

    assert xml.startswith("<Play>")
    assert "/agent/v1/voice/audio/" in xml


def test_greeting_twiml_contains_play_when_clone_ready(tmp_path):
    fake_audio = b"ID3fake-mp3-bytes"
    base_url = "https://example.ngrok-free.app"

    with (
        patch.object(sarvam_tts.settings, "VOICE_CLONE_ENABLED", True),
        patch.object(sarvam_tts.settings, "SARVAM_API_KEY", "test-key"),
        patch.object(sarvam_tts.settings, "SARVAM_VOICE_ID", ""),
        patch.object(sarvam_tts.settings, "SARVAM_SPEAKER", "ratan"),
        patch.object(sarvam_tts.settings, "SARVAM_TTS_CACHE_DIR", str(tmp_path)),
        patch.object(sarvam_tts, "synthesize_to_bytes", return_value=fake_audio) as synth,
    ):
        from app.agent.nodes.greeting import GREETINGS, NO_INPUT, SERVICE_MENUS

        for text in (GREETINGS["en"], SERVICE_MENUS["en"], NO_INPUT["en"]):
            sarvam_tts.get_or_create_audio_file(text, "en-IN")
        synth.reset_mock()
        xml = build_greeting_twiml(base_url, "en", "en-IN")

    assert "<Play>" in xml
    assert "/agent/v1/voice/menu" in xml
    assert "<Gather" in xml
    assert synth.call_count == 0


def test_speak_cache_only_falls_back_without_generation(tmp_path):
    with (
        patch.object(sarvam_tts.settings, "VOICE_CLONE_ENABLED", True),
        patch.object(sarvam_tts.settings, "SARVAM_API_KEY", "test-key"),
        patch.object(sarvam_tts.settings, "SARVAM_VOICE_ID", ""),
        patch.object(sarvam_tts.settings, "SARVAM_SPEAKER", "ratan"),
        patch.object(sarvam_tts.settings, "SARVAM_TTS_CACHE_DIR", str(tmp_path)),
        patch.object(sarvam_tts, "synthesize_to_bytes") as synth,
    ):
        xml = sarvam_tts.speak(
            "Hello from NexaCare",
            "en-IN",
            "https://example.com",
            allow_generate=False,
        )

    assert xml.startswith("<Say")
    assert "Hello from NexaCare" in xml
    assert "<Play>" not in xml
    assert synth.call_count == 0


def test_read_cached_audio_rejects_unsafe_names(tmp_path):
    with patch.object(sarvam_tts.settings, "SARVAM_TTS_CACHE_DIR", str(tmp_path)):
        try:
            sarvam_tts.read_cached_audio("../etc/passwd")
            assert False, "expected ValueError"
        except ValueError:
            pass


def test_uses_cloned_voice_requires_uuid():
    with patch.object(sarvam_tts.settings, "SARVAM_VOICE_ID", "SHIRISH"):
        assert sarvam_tts.uses_cloned_voice() is False
    with patch.object(
        sarvam_tts.settings, "SARVAM_VOICE_ID", "27c4beed-27c5-4623-aabc-62339e9e40fa"
    ):
        assert sarvam_tts.uses_cloned_voice() is True


def test_detect_audio_ext_wav_and_mp3():
    wav = b"RIFF....WAVEfmt "  # minimal RIFF/WAVE header shape
    wav = b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"fmt "
    assert sarvam_tts._detect_audio_ext(wav) == "wav"
    assert sarvam_tts._detect_audio_ext(b"ID3fake-mp3") == "mp3"


def test_read_cached_audio_serves_wav_content_type_for_mislabeled_mp3(tmp_path):
    # Valid-enough WAV magic; Twilio needs audio/wav even if filename ends with .mp3
    wav_bytes = b"RIFF" + (100).to_bytes(4, "little") + b"WAVE" + b"fmt " + (b"\x00" * 80)
    path = tmp_path / "aabbccddeeff00112233445566778899.mp3"
    path.write_bytes(wav_bytes)

    with patch.object(sarvam_tts.settings, "SARVAM_TTS_CACHE_DIR", str(tmp_path)):
        data, content_type = sarvam_tts.read_cached_audio(path.name)

    assert data == wav_bytes
    assert content_type == "audio/wav"


def test_get_or_create_saves_wav_extension_for_clone_bytes(tmp_path):
    wav_bytes = b"RIFF" + (100).to_bytes(4, "little") + b"WAVE" + b"fmt " + (b"\x00" * 80)
    with (
        patch.object(sarvam_tts.settings, "VOICE_CLONE_ENABLED", True),
        patch.object(sarvam_tts.settings, "SARVAM_API_KEY", "test-key"),
        patch.object(
            sarvam_tts.settings, "SARVAM_VOICE_ID", "27c4beed-27c5-4623-aabc-62339e9e40fa"
        ),
        patch.object(sarvam_tts.settings, "SARVAM_TTS_CACHE_DIR", str(tmp_path)),
        patch.object(sarvam_tts.settings, "SARVAM_TTS_CODEC", "mp3"),
        patch.object(sarvam_tts, "synthesize_to_bytes", return_value=wav_bytes),
    ):
        path = sarvam_tts.get_or_create_audio_file("नमस्कार", "mr-IN")

    assert path.suffix == ".wav"
    assert path.read_bytes() == wav_bytes


def test_find_job_id_reads_nested_data_job_id():
    resp = MagicMock()
    resp.headers = {}
    payload = {
        "status": "success",
        "data": {
            "job_id": "9c454cfd-543d-4f22-9e0d-31494b5c8bbc",
            "status": "queued",
        },
    }
    assert (
        sarvam_tts._find_job_id(payload, resp)
        == "9c454cfd-543d-4f22-9e0d-31494b5c8bbc"
    )
    assert sarvam_tts._job_status(payload) == "queued"


def test_synthesize_cloned_polls_nested_job_and_returns_audio():
    voice_id = "27c4beed-27c5-4623-aabc-62339e9e40fa"
    job_id = "9c454cfd-543d-4f22-9e0d-31494b5c8bbc"
    audio_bytes = b"ID3cloned-audio"

    synthesize_resp = MagicMock()
    synthesize_resp.status_code = 202
    synthesize_resp.headers = {"content-type": "application/json"}
    synthesize_resp.content = b"{}"
    synthesize_resp.text = "{}"
    synthesize_resp.json.return_value = {
        "status": "success",
        "data": {"job_id": job_id, "status": "queued"},
    }

    queued_resp = MagicMock()
    queued_resp.status_code = 200
    queued_resp.headers = {"content-type": "application/json"}
    queued_resp.content = b"{}"
    queued_resp.json.return_value = {
        "status": "success",
        "data": {"job_id": job_id, "status": "queued"},
    }

    done_resp = MagicMock()
    done_resp.status_code = 200
    done_resp.headers = {"content-type": "application/json"}
    done_resp.content = b"{}"
    done_resp.json.return_value = {
        "status": "success",
        "data": {
            "job_id": job_id,
            "status": "completed",
            "audio": base64.b64encode(audio_bytes).decode(),
        },
    }

    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.post.return_value = synthesize_resp
    client.get.side_effect = [queued_resp, done_resp]

    with (
        patch.object(sarvam_tts.settings, "SARVAM_VOICE_ID", voice_id),
        patch.object(sarvam_tts.settings, "SARVAM_API_KEY", "test-key"),
        patch.object(sarvam_tts.settings, "SARVAM_STUDIO_COOKIE", ""),
        patch.object(sarvam_tts.settings, "SARVAM_TTS_TIMEOUT_SECONDS", 5.0),
        patch.object(sarvam_tts, "time") as mock_time,
        patch.object(sarvam_tts.httpx, "Client", return_value=client),
    ):
        mock_time.monotonic.side_effect = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
        mock_time.sleep.return_value = None
        result = sarvam_tts._synthesize_cloned("नमस्कार", "mr-IN")

    assert result == audio_bytes
    assert client.post.called
    assert client.get.called
