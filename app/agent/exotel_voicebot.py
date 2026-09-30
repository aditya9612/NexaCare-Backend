"""
Exotel Voicebot / AgentStream socket for /agent/v1/voice/incoming.

Exotel is the WebSocket client. This module only accepts that socket, plays
audio the existing HTTP voice handlers already return, and feeds caller
speech back into those same handlers. It does not replace them.
"""

from __future__ import annotations

import asyncio
import audioop
import base64
import hashlib
import hmac
import io
import json
import logging
import os
import shutil
import subprocess
import urllib.parse
import wave
from typing import Any
from xml.etree import ElementTree

import httpx
from fastapi import WebSocket, WebSocketDisconnect
from starlette.requests import Request

from app.core.config import settings
from app.core.database import AsyncSessionLocal

logger = logging.getLogger("nexacare.agent.exotel_voicebot")

_MIN_CHUNK = 3200
_MAX_CHUNK = 99840  # 100000 rounded down to a multiple of 320
_FRAME = 320
_SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"


def iter_pcm_chunks(pcm: bytes) -> list[bytes]:
    """Exotel rejects or drops playback when a chunk is not 3200..100000 and a multiple of 320."""
    if not pcm:
        return []
    if len(pcm) % 2:
        pcm = pcm[:-1]
    if len(pcm) % _FRAME:
        pcm += b"\x00" * (_FRAME - (len(pcm) % _FRAME))
    if len(pcm) < _MIN_CHUNK:
        pcm += b"\x00" * (_MIN_CHUNK - len(pcm))
    chunks: list[bytes] = []
    for offset in range(0, len(pcm), _MAX_CHUNK):
        piece = pcm[offset : offset + _MAX_CHUNK]
        if len(piece) < _MIN_CHUNK:
            piece += b"\x00" * (_MIN_CHUNK - len(piece))
        if len(piece) % _FRAME:
            piece += b"\x00" * (_FRAME - (len(piece) % _FRAME))
        chunks.append(piece)
    return chunks


def _tag(el: ElementTree.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def plan_twiml(twiml: str) -> tuple[list[tuple[str, str, str]], bool, bool]:
    """Pull prompts the caller should hear. Skip the post-Gather fallback."""
    root = ElementTree.fromstring(twiml)
    prompts: list[tuple[str, str, str]] = []
    expects_input = False
    should_close = False
    seen_gather = False
    for child in list(root):
        tag = _tag(child)
        if tag == "Gather":
            seen_gather = True
            expects_input = True
            for nested in list(child):
                if _tag(nested) in ("Say", "Play"):
                    prompts.append(_prompt(nested))
            continue
        if seen_gather:
            continue
        if tag in ("Say", "Play"):
            prompts.append(_prompt(child))
        elif tag in ("Hangup", "Dial"):
            should_close = True
    if expects_input:
        should_close = False
    return prompts, expects_input, should_close


def _prompt(el: ElementTree.Element) -> tuple[str, str, str]:
    kind = "text" if _tag(el) == "Say" else "url"
    lang = el.attrib.get("language") or "en-IN"
    return kind, (el.text or "").strip(), lang


def _sample_rate(raw: str | None) -> int:
    try:
        rate = int(str(raw or "8000"))
    except (TypeError, ValueError):
        return 8000
    return rate if rate in (8000, 16000, 24000) else 8000


def _looks_like_mp3(audio: bytes) -> bool:
    """Detect MP3 from ID3 tag or MPEG frame sync (Sarvam TTS cache default)."""
    if len(audio) < 2:
        return False
    if audio[:3] == b"ID3":
        return True
    return audio[0] == 0xFF and (audio[1] & 0xE0) == 0xE0


def _wav_to_pcm(audio: bytes, rate: int) -> bytes:
    with wave.open(io.BytesIO(audio), "rb") as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        src_rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    if width != 2:
        frames = audioop.lin2lin(frames, width, 2)
    if channels > 1:
        frames = audioop.tomono(frames, 2, 0.5, 0.5)
    if src_rate != rate and frames:
        frames, _ = audioop.ratecv(frames, 2, 1, src_rate, rate, None)
    return frames


def _ffmpeg_to_pcm(audio: bytes, rate: int) -> bytes:
    """
    Decode MP3 (or other ffmpeg-readable audio) to mono s16le PCM at ``rate``.

    Exotel Voicebot streams raw PCM; Twilio <Play> accepts MP3, so cached Sarvam
    TTS is often MP3. ffmpeg is required only on this Voicebot path.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.warning("exotel voicebot ffmpeg not found; cannot decode non-wav audio")
        return b""
    try:
        proc = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "-ac",
                "1",
                "-ar",
                str(int(rate)),
                "pipe:1",
            ],
            input=audio,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("exotel voicebot ffmpeg decode failed: %s", exc)
        return b""
    if proc.returncode != 0 or not proc.stdout:
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        logger.warning(
            "exotel voicebot ffmpeg decode exit=%s bytes_in=%s err=%s",
            proc.returncode,
            len(audio),
            err[:300] if err else "-",
        )
        return b""
    return proc.stdout


def _to_pcm(audio: bytes, rate: int) -> bytes:
    """Convert TTS/Play bytes (WAV or MP3) to mono PCM for Exotel streaming."""
    if not audio:
        return b""
    if len(audio) >= 12 and audio[:4] == b"RIFF" and audio[8:12] == b"WAVE":
        return _wav_to_pcm(audio, rate)
    if _looks_like_mp3(audio) or audio[:4] != b"RIFF":
        kind = "mp3" if _looks_like_mp3(audio) else "non-wav"
        pcm = _ffmpeg_to_pcm(audio, rate)
        if pcm:
            logger.debug(
                "exotel voicebot decoded %s to pcm bytes_in=%s bytes_out=%s rate=%s",
                kind,
                len(audio),
                len(pcm),
                rate,
            )
            return pcm
        logger.warning(
            "exotel voicebot audio is not wav and decode failed (%s bytes, kind=%s)",
            len(audio),
            kind,
        )
        return b""
    return b""


def _tts_pcm(text: str, language: str, rate: int) -> bytes:
    from app.services import sarvam_tts

    clean = (text or "").strip()
    if not clean:
        return b""
    if sarvam_tts.uses_cloned_voice():
        return _to_pcm(sarvam_tts.synthesize_to_bytes(clean, language), rate)
    if not settings.SARVAM_API_KEY or not sarvam_tts._speaker():
        logger.warning("exotel voicebot TTS skipped: Sarvam speaker is not configured")
        return b""
    payload = {
        "text": clean[: sarvam_tts._max_chars()],
        "language_code": sarvam_tts._normalize_language(language),
        "speaker": sarvam_tts._speaker(),
        "model": settings.SARVAM_TTS_MODEL or "bulbul:v3",
        "pace": float(settings.SARVAM_TTS_PACE or 1.0),
        "speech_sample_rate": str(rate),
        "output_audio_codec": "wav",
    }
    headers = {
        "api-subscription-key": settings.SARVAM_API_KEY,
        "Content-Type": "application/json",
    }
    timeout = float(settings.SARVAM_TTS_TIMEOUT_SECONDS or 30.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(sarvam_tts.SARVAM_TTS_URL, headers=headers, json=payload)
    response.raise_for_status()
    audios = response.json().get("audios") or []
    b64 = "".join(audios) if isinstance(audios, list) else str(audios)
    return _to_pcm(base64.b64decode(b64), rate)


def _url_pcm(url: str, rate: int) -> bytes:
    from app.services.sarvam_tts import read_cached_audio

    marker = "/agent/v1/voice/audio/"
    if marker in url:
        filename = url.split(marker, 1)[1].split("?", 1)[0]
        data, _content_type = read_cached_audio(filename)
        return _to_pcm(data, rate)
    with httpx.Client(timeout=30.0) as client:
        response = client.get(url)
    response.raise_for_status()
    return _to_pcm(response.content, rate)


async def speakable_pcm(twiml: str, sample_rate: int) -> tuple[bytes, bool, bool]:
    prompts, expects_input, should_close = plan_twiml(twiml)
    parts: list[bytes] = []
    for kind, value, lang in prompts:
        if not value:
            continue
        try:
            if kind == "text":
                pcm = await asyncio.to_thread(_tts_pcm, value, lang, sample_rate)
            else:
                pcm = await asyncio.to_thread(_url_pcm, value, sample_rate)
        except Exception:
            logger.exception("exotel voicebot prompt audio failed")
            pcm = b""
        if pcm:
            parts.append(pcm)
    return b"".join(parts), expects_input, should_close


def _twilio_signature(url: str, params: dict[str, str], token: str) -> str:
    payload = url + "".join(key + params[key] for key in sorted(params))
    digest = hmac.new(token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def _voice_request(method: str, path: str, query: dict[str, str], form: dict[str, str]) -> Request:
    base = (os.getenv("PUBLIC_BASE_URL") or settings.PUBLIC_BASE_URL or "http://localhost:8000").rstrip("/")
    token = settings.TWILIO_AUTH_TOKEN or ""
    signature = _twilio_signature(f"{base}{path}", form, token)
    body = urllib.parse.urlencode(form).encode() if method == "POST" else b""
    sent = False

    async def receive():
        nonlocal sent
        chunk = b"" if sent else body
        sent = True
        return {"type": "http.request", "body": chunk, "more_body": False}

    headers = [(b"host", b"localhost"), (b"x-twilio-signature", signature.encode())]
    if method == "POST":
        headers.append((b"content-type", b"application/x-www-form-urlencoded"))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": urllib.parse.urlencode(query).encode(),
        "headers": headers,
        "client": ("127.0.0.1", 0),
        "server": ("localhost", 443),
    }
    return Request(scope, receive)


async def opening_twiml(call_sid: str, from_number: str, to_number: str) -> str:
    """Run the existing incoming-call handler and return its XML."""
    from app.agent.router import incoming_call

    request = _voice_request(
        "GET",
        "/agent/v1/voice/incoming",
        {
            "CallSid": call_sid,
            "From": from_number,
            "To": to_number,
            "CallFrom": from_number,
            "CallTo": to_number,
        },
        {},
    )
    async with AsyncSessionLocal() as db:
        try:
            response = await incoming_call(request, db)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    body = response.body or b""
    return body.decode("utf-8", errors="replace")


def _pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _transcribe(pcm: bytes, rate: int, language: str) -> str:
    """Transcribe Exotel PCM via Sarvam STT. Soft-fails so one bad turn keeps the call alive."""
    if not settings.SARVAM_API_KEY or len(pcm) < _MIN_CHUNK:
        return ""
    from app.services import sarvam_tts

    wav = _pcm_to_wav(pcm, rate)
    model = (settings.SARVAM_STT_MODEL or "saaras:v4").strip() or "saaras:v4"
    lang = sarvam_tts._normalize_language(language) if language else "unknown"
    data = {
        "model": model,
        "language_code": lang or "unknown",
    }
    files = {"file": ("caller.wav", wav, "audio/wav")}
    headers = {"api-subscription-key": settings.SARVAM_API_KEY}
    timeout = float(settings.SARVAM_TTS_TIMEOUT_SECONDS or 30.0)
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(_SARVAM_STT_URL, headers=headers, data=data, files=files)
        if response.status_code >= 400:
            logger.warning(
                "exotel voicebot STT failed status=%s model=%s language=%s pcm_bytes=%s rate=%s body=%s",
                response.status_code,
                model,
                lang,
                len(pcm),
                rate,
                (response.text or "")[:500],
            )
            return ""
        payload = response.json()
        return str(payload.get("transcript") or "").strip()
    except Exception:
        logger.exception(
            "exotel voicebot STT request error model=%s language=%s pcm_bytes=%s rate=%s",
            model,
            lang,
            len(pcm),
            rate,
        )
        return ""


# DTMF during these steps must hit /lang or /menu — not /turn.
_LANG_STEPS = frozenset({"language_select"})
_MENU_STEPS = frozenset({"greeting", "service_menu"})


def _route_for_step(step: str) -> tuple[str, str]:
    """Return (path, handler_name) matching the HTTP voice Gather actions."""
    if step in _LANG_STEPS:
        return "/agent/v1/voice/lang", "language_select"
    if step in _MENU_STEPS:
        return "/agent/v1/voice/menu", "service_menu"
    return "/agent/v1/voice/turn", "conversation_turn"


async def _existing_input_twiml(
    call_sid: str,
    speech: str,
    digits: str,
) -> str:
    """
    Invoke the same HTTP handler the Gather action would have hit.

    Exotel Voicebot only plays TwiML audio and ignores Gather action URLs, so
    DTMF/speech must be routed by session step to /lang, /menu, or /turn.
    """
    from app.agent import session_store
    from app.agent.router import conversation_turn, language_select, service_menu

    state = await session_store.get_session(call_sid)
    step = str((state or {}).get("step") or "")
    path, handler_name = _route_for_step(step)

    handlers = {
        "language_select": language_select,
        "service_menu": service_menu,
        "conversation_turn": conversation_turn,
    }
    handler = handlers[handler_name]

    if handler_name == "language_select":
        form = {
            "CallSid": call_sid,
            "Digits": digits,
            "SpeechResult": speech,
        }
    elif handler_name == "service_menu":
        form = {
            "CallSid": call_sid,
            "Digits": digits or speech,
        }
    else:
        form = {
            "CallSid": call_sid,
            "SpeechResult": speech,
            "Digits": digits,
            "Confidence": "1.0",
        }

    logger.info(
        "exotel voicebot route step=%s path=%s call_sid=%s digits=%r speech=%r",
        step or "-",
        path,
        call_sid,
        digits,
        (speech[:80] + "…") if len(speech) > 80 else speech,
    )

    request = _voice_request("POST", path, {}, form)
    async with AsyncSessionLocal() as db:
        try:
            response = await handler(request, db)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return (response.body or b"").decode("utf-8", errors="replace")


async def _existing_turn_twiml(
    call_sid: str,
    speech: str,
    digits: str,
) -> str:
    """Back-compat alias — routes by session step like HTTP Gather actions."""
    return await _existing_input_twiml(call_sid, speech, digits)


def _rms(pcm: bytes) -> float:
    if len(pcm) < 2:
        return 0.0
    return float(audioop.rms(pcm, 2))


def _dtmf_digit(event: dict[str, Any]) -> str:
    """Read one keypad digit from either Exotel DTMF payload shape."""
    raw = event.get("dtmf")
    if isinstance(raw, dict):
        value = raw.get("digit")
    elif isinstance(raw, str):
        value = raw
    else:
        value = event.get("digit")
    digit = str(value or "").strip()
    if len(digit) == 1:
        return digit
    return ""


async def _send_pcm(websocket: WebSocket, stream_sid: str, pcm: bytes, mark_name: str) -> None:
    for chunk in iter_pcm_chunks(pcm):
        await websocket.send_text(
            json.dumps(
                {
                    "event": "media",
                    "stream_sid": stream_sid,
                    "media": {"payload": base64.b64encode(chunk).decode("ascii")},
                }
            )
        )
    await websocket.send_text(
        json.dumps(
            {
                "event": "mark",
                "stream_sid": stream_sid,
                "mark": {"name": mark_name},
            }
        )
    )


async def handle_exotel_voicebot(websocket: WebSocket) -> None:
    await websocket.accept()
    logger.info("exotel voicebot websocket accepted path=%s", websocket.url.path)

    stream_sid = ""
    sample_rate = _sample_rate(websocket.query_params.get("sample-rate"))
    call_sid = ""
    language = "en-IN"
    awaiting_mark = False
    ignore_media = False
    mark_name = ""
    discarded = 0
    speech = bytearray()
    speech_ms = 0
    silence_ms = 0
    busy = False

    try:
        while True:
            incoming = await websocket.receive()
            if incoming.get("type") == "websocket.disconnect":
                break
            raw = incoming.get("text")
            if not raw:
                continue
            try:
                event: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("exotel voicebot ignored non-json frame")
                continue
            name = str(event.get("event") or "")

            if name == "start":
                start = event.get("start") or {}
                stream_sid = str(start.get("stream_sid") or event.get("stream_sid") or "")
                call_sid = str(start.get("call_sid") or stream_sid or "unknown")
                if not websocket.query_params.get("sample-rate"):
                    media_format = start.get("media_format") or {}
                    sample_rate = _sample_rate(media_format.get("sample_rate"))
                from_number = str(start.get("from") or "")
                to_number = str(start.get("to") or "")
                logger.info(
                    "exotel voicebot start call_sid=%s from=%s to=%s rate=%s",
                    call_sid,
                    from_number,
                    to_number,
                    sample_rate,
                )
                try:
                    twiml = await opening_twiml(call_sid, from_number, to_number)
                    from app.agent import session_store

                    state = await session_store.get_session(call_sid)
                    if state and state.get("twilio_language"):
                        language = str(state["twilio_language"])
                    pcm, _expects, should_close = await speakable_pcm(twiml, sample_rate)
                except Exception:
                    logger.exception("exotel voicebot opening failed call_sid=%s", call_sid)
                    pcm, should_close = b"", False
                if pcm and stream_sid:
                    mark_name = "open-1"
                    awaiting_mark = True
                    discarded = 0
                    await _send_pcm(websocket, stream_sid, pcm, mark_name)
                if should_close:
                    await websocket.close()
                    return
                continue

            if name == "mark" and awaiting_mark:
                got = str((event.get("mark") or {}).get("name") or "")
                if got == mark_name:
                    awaiting_mark = False
                    discarded = 0
                    speech.clear()
                    speech_ms = 0
                    silence_ms = 0
                continue

            if name == "media" and ignore_media:
                continue

            if name == "media" and awaiting_mark:
                discarded += 1
                if discarded >= 50:
                    awaiting_mark = False
                    speech.clear()
                    speech_ms = 0
                    silence_ms = 0
                continue

            if name == "stop" or not stream_sid:
                if name == "stop":
                    break
                continue

            if name == "dtmf" and not busy:
                digit = _dtmf_digit(event)
                if digit and stream_sid:
                    busy = True
                    ignore_media = True
                    try:
                        closed, sent, language = await _run_input(
                            websocket,
                            stream_sid,
                            call_sid,
                            "",
                            digit,
                            sample_rate,
                            language,
                        )
                    except Exception:
                        logger.exception("exotel voicebot dtmf failed call_sid=%s", call_sid)
                        continue
                    finally:
                        busy = False
                        ignore_media = False
                    if closed:
                        return
                    if sent:
                        awaiting_mark = True
                        mark_name = "turn"
                        discarded = 0
                continue

            if name != "media" or busy:
                continue

            payload = (event.get("media") or {}).get("payload") or ""
            try:
                frame = base64.b64decode(payload)
            except Exception:
                continue
            if _rms(frame) >= 500:
                speech.extend(frame)
                speech_ms += 100
                silence_ms = 0
            elif speech_ms:
                silence_ms += 100
            if speech_ms >= 300 and silence_ms >= 700 and stream_sid:
                heard = bytes(speech)
                speech.clear()
                speech_ms = 0
                silence_ms = 0
                busy = True
                ignore_media = True
                try:
                    transcript = await asyncio.to_thread(
                        _transcribe, heard, sample_rate, language
                    )
                    if transcript:
                        closed, sent, language = await _run_input(
                            websocket,
                            stream_sid,
                            call_sid,
                            transcript,
                            "",
                            sample_rate,
                            language,
                        )
                        if closed:
                            return
                        if sent:
                            awaiting_mark = True
                            mark_name = "turn"
                            discarded = 0
                except Exception:
                    logger.exception("exotel voicebot turn failed call_sid=%s", call_sid)
                finally:
                    busy = False
                    ignore_media = False
    except WebSocketDisconnect:
        logger.info("exotel voicebot disconnected call_sid=%s", call_sid or "-")


async def _run_input(
    websocket: WebSocket,
    stream_sid: str,
    call_sid: str,
    speech: str,
    digits: str,
    sample_rate: int,
    language: str,
) -> tuple[bool, bool, str]:
    twiml = await _existing_input_twiml(call_sid, speech, digits)
    from app.agent import session_store

    state = await session_store.get_session(call_sid)
    if state and state.get("twilio_language"):
        language = str(state["twilio_language"])
    pcm, _expects, should_close = await speakable_pcm(twiml, sample_rate)
    if pcm:
        await _send_pcm(websocket, stream_sid, pcm, "turn")
    # Keypad 1-4 must play the existing turn and leave this socket open.
    keep_alive = digits in {"1", "2", "3", "4"}
    if should_close and not keep_alive:
        await websocket.close()
    return should_close and not keep_alive, bool(pcm), language
