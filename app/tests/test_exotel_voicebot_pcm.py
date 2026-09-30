"""Exotel Voicebot PCM conversion must accept WAV and Sarvam MP3 cache bytes."""

import audioop
import io
import shutil
import subprocess
import wave
from unittest.mock import MagicMock, patch

import pytest

from app.agent.exotel_voicebot import _looks_like_mp3, _to_pcm, _transcribe, _url_pcm


def _make_wav(rate: int = 8000, seconds: float = 0.05) -> bytes:
    frames = b"\x00\x10" * int(rate * seconds)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(frames)
    return buf.getvalue()


def _make_pcm(rate: int = 8000, seconds: float = 0.5) -> bytes:
    # Enough bytes to clear _MIN_CHUNK (3200).
    return b"\x00\x10" * int(rate * seconds)


def _make_mp3(rate: int = 8000) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    wav = _make_wav(rate=rate, seconds=0.1)
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "wav",
            "-i",
            "pipe:0",
            "-f",
            "mp3",
            "pipe:1",
        ],
        input=wav,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if proc.returncode != 0 or not proc.stdout:
        pytest.skip(f"ffmpeg could not encode mp3: {proc.stderr!r}")
    return proc.stdout


def test_looks_like_mp3_id3_and_frame_sync():
    assert _looks_like_mp3(b"ID3fake") is True
    assert _looks_like_mp3(bytes([0xFF, 0xFB, 0x00, 0x00])) is True
    assert _looks_like_mp3(_make_wav()) is False
    assert _looks_like_mp3(b"") is False


def test_to_pcm_accepts_wav():
    wav = _make_wav(rate=16000, seconds=0.05)
    pcm = _to_pcm(wav, 8000)
    assert len(pcm) > 0
    assert len(pcm) % 2 == 0
    # Downsampled from 16k → 8k should be shorter than source PCM frames.
    assert audioop.rms(pcm, 2) >= 0


def test_to_pcm_decodes_mp3():
    mp3 = _make_mp3(rate=8000)
    assert _looks_like_mp3(mp3) is True
    pcm = _to_pcm(mp3, 8000)
    assert len(pcm) > 0
    assert len(pcm) % 2 == 0


def test_url_pcm_decodes_cached_mp3(monkeypatch):
    mp3 = _make_mp3(rate=8000)
    name = "aabbccddeeff00112233445566778899.mp3"

    def fake_read(filename: str):
        assert filename == name
        return mp3, "audio/mpeg"

    monkeypatch.setattr(
        "app.services.sarvam_tts.read_cached_audio",
        fake_read,
    )
    pcm = _url_pcm(f"https://api.example/agent/v1/voice/audio/{name}", 8000)
    assert len(pcm) > 0
    assert len(pcm) % 2 == 0


def test_transcribe_uses_saaras_v4_and_returns_transcript():
    pcm = _make_pcm()
    response = MagicMock()
    response.status_code = 200
    response.text = '{"transcript":"Rahul"}'
    response.json.return_value = {"transcript": "Rahul"}

    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.post.return_value = response

    with (
        patch("app.agent.exotel_voicebot.settings.SARVAM_API_KEY", "test-key"),
        patch("app.agent.exotel_voicebot.settings.SARVAM_STT_MODEL", "saaras:v4"),
        patch("app.agent.exotel_voicebot.httpx.Client", return_value=client),
    ):
        assert _transcribe(pcm, 8000, "en-IN") == "Rahul"

    kwargs = client.post.call_args.kwargs
    assert kwargs["data"]["model"] == "saaras:v4"
    assert kwargs["data"]["language_code"] == "en-IN"


def test_transcribe_soft_fails_on_http_400():
    pcm = _make_pcm()
    response = MagicMock()
    response.status_code = 400
    response.text = '{"error":{"message":"Invalid model","code":"invalid_request_error"}}'
    response.json.return_value = {"error": {"message": "Invalid model"}}

    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.post.return_value = response

    with (
        patch("app.agent.exotel_voicebot.settings.SARVAM_API_KEY", "test-key"),
        patch("app.agent.exotel_voicebot.settings.SARVAM_STT_MODEL", "saaras:v4"),
        patch("app.agent.exotel_voicebot.httpx.Client", return_value=client),
    ):
        assert _transcribe(pcm, 8000, "hi-IN") == ""
