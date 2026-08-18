"""
Sarvam AI Text-to-Speech client with on-disk cache for Twilio <Play>.

Two synthesis paths:
1) Cloned voice (preferred when SARVAM_VOICE_ID is set):
   POST https://studio.sarvam.ai/api/voice-library/synthesize
   body: {voice_id, language, pace, text}
2) Built-in speaker (SARVAM_SPEAKER):
   POST https://api.sarvam.ai/text-to-speech
   body: {speaker, language_code, ...}

Falls back to Twilio <Say> when disabled or when generation fails.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape

import httpx

from app.core.config import settings

logger = logging.getLogger("nexacare.services.sarvam_tts")

SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
SARVAM_CLONE_SYNTHESIZE_URL = "https://studio.sarvam.ai/api/voice-library/synthesize"

# Twilio <Say> voice pins (fallback when clone is off / fails)
VOICE_BY_LANG = {
    "mr-IN": "Google.mr-IN-Chirp3-HD-Aoede",
}

_SAFE_FILE_RE = re.compile(r"^[a-f0-9]{16,64}\.(mp3|wav)$")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _voice_id() -> str:
    return (settings.SARVAM_VOICE_ID or "").strip()


def _speaker() -> str:
    return (settings.SARVAM_SPEAKER or "").strip()


def uses_cloned_voice() -> bool:
    """True when Studio clone voice_id is configured."""
    vid = _voice_id()
    return bool(vid and _UUID_RE.match(vid))


def voice_clone_ready() -> bool:
    has_auth = bool(settings.SARVAM_API_KEY or settings.SARVAM_STUDIO_COOKIE)
    has_voice = bool(_voice_id() or _speaker())
    return bool(settings.VOICE_CLONE_ENABLED and has_auth and has_voice)


def cache_dir() -> Path:
    path = Path(settings.SARVAM_TTS_CACHE_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _codec_ext() -> str:
    codec = (settings.SARVAM_TTS_CODEC or "mp3").lower().strip()
    return "wav" if codec == "wav" else "mp3"


def _content_type(ext: str) -> str:
    return "audio/wav" if ext == "wav" else "audio/mpeg"


def _detect_audio_ext(audio: bytes) -> str:
    """
    Detect container from magic bytes.

    Studio clone downloads are WAV (RIFF/WAVE) even when we prefer mp3.
    Serving WAV bytes as audio/mpeg makes Twilio <Play> silent.
    """
    if len(audio) >= 12 and audio[:4] == b"RIFF" and audio[8:12] == b"WAVE":
        return "wav"
    if audio[:3] == b"ID3":
        return "mp3"
    if len(audio) >= 2 and audio[0] == 0xFF and (audio[1] & 0xE0) == 0xE0:
        return "mp3"
    return _codec_ext()


def _repair_cache_path(path: Path) -> Path:
    """If a cache file extension disagrees with contents, rewrite to correct name."""
    if not path.is_file() or path.stat().st_size <= 0:
        return path
    data = path.read_bytes()
    actual_ext = _detect_audio_ext(data)
    current_ext = path.suffix.lstrip(".").lower()
    if actual_ext == current_ext:
        return path
    fixed = path.with_suffix(f".{actual_ext}")
    if fixed != path:
        fixed.write_bytes(data)
        try:
            path.unlink()
        except OSError:
            pass
        logger.info(
            "Sarvam TTS cache repaired %s -> %s (was mislabeled)",
            path.name,
            fixed.name,
        )
        return fixed
    return path


def _active_voice_key() -> str:
    return _voice_id() or _speaker() or "default"


def _cache_key(text: str, language_code: str, voice_key: str) -> str:
    raw = "|".join(
        [
            text.strip(),
            language_code,
            voice_key,
            "clone" if uses_cloned_voice() else "builtin",
            settings.SARVAM_TTS_MODEL,
            _codec_ext(),
            str(settings.SARVAM_TTS_SAMPLE_RATE),
            str(settings.SARVAM_TTS_PACE),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _normalize_language(twilio_or_bcp47: str) -> str:
    """Map agent language codes to Sarvam BCP-47 codes."""
    value = (twilio_or_bcp47 or "en-IN").strip()
    mapping = {
        "en": "en-IN",
        "hi": "hi-IN",
        "mr": "mr-IN",
        "en-IN": "en-IN",
        "hi-IN": "hi-IN",
        "mr-IN": "mr-IN",
    }
    return mapping.get(value, value if "-" in value else "en-IN")


def _max_chars() -> int:
    if uses_cloned_voice():
        return int(settings.SARVAM_CLONE_MAX_CHARS or 1000)
    return 2400


def _auth_headers() -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://indus.sarvam.ai",
        "Referer": "https://indus.sarvam.ai/creator-studio/text-to-speech",
    }
    if settings.SARVAM_API_KEY:
        headers["api-subscription-key"] = settings.SARVAM_API_KEY
    if settings.SARVAM_STUDIO_COOKIE:
        headers["Cookie"] = settings.SARVAM_STUDIO_COOKIE.strip()
    return headers


def _decode_b64_audio(value: Any) -> Optional[bytes]:
    if value is None:
        return None
    if isinstance(value, list):
        if not value:
            return None
        value = "".join(str(v) for v in value)
    text = str(value).strip()
    if not text:
        return None
    # Strip data-URI prefix if present
    if "," in text and text.lower().startswith("data:"):
        text = text.split(",", 1)[1]
    try:
        return base64.b64decode(text)
    except Exception:
        return None


def _nested_dicts(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return data plus common nested containers (data/result/output)."""
    out = [data]
    for key in ("data", "result", "output", "job", "payload"):
        nested = data.get(key)
        if isinstance(nested, dict):
            out.append(nested)
    return out


def _find_audio_url(data: dict[str, Any]) -> Optional[str]:
    for obj in _nested_dicts(data):
        for key in (
            "audio_url",
            "url",
            "download_url",
            "signed_url",
            "file_url",
            "output_url",
            "presigned_url",
            "mp3_url",
            "wav_url",
            "audioUrl",
            "downloadUrl",
        ):
            val = obj.get(key)
            if isinstance(val, str) and val.startswith("http"):
                return val
    return None


def _find_job_id(data: dict[str, Any], response: httpx.Response) -> Optional[str]:
    """
    Studio synthesize returns:
      {"status":"success","data":{"job_id":"...","status":"queued"}}
    so job_id is nested under data.
    """
    for obj in _nested_dicts(data):
        for key in (
            "job_id",
            "request_id",
            "id",
            "upstream_request_id",
            "task_id",
            "synthesis_id",
        ):
            val = obj.get(key)
            if val and key != "status":
                # Prefer UUID-looking job ids over generic "success"
                text = str(val)
                if key == "job_id" or _UUID_RE.match(text):
                    return text
                if key in {"request_id", "upstream_request_id", "task_id", "synthesis_id", "id"}:
                    return text
    location = response.headers.get("Location") or response.headers.get("location")
    if location:
        return location.rstrip("/").split("/")[-1]
    # Header often present on Studio responses
    hdr = response.headers.get("x-request-id") or response.headers.get("X-Request-Id")
    if hdr and _UUID_RE.match(hdr.strip()):
        # x-request-id is request tracing, not always the job id — only use as last resort
        pass
    return None


def _job_status(data: dict[str, Any]) -> str:
    """Prefer nested data.status (queued/completed) over top-level status (success)."""
    nested = data.get("data")
    if isinstance(nested, dict):
        for key in ("status", "state"):
            val = nested.get(key)
            if val:
                return str(val).lower()
    for key in ("status", "state"):
        val = data.get(key)
        if val and str(val).lower() not in {"success", "ok"}:
            return str(val).lower()
    if isinstance(nested, dict) and nested.get("status"):
        return str(nested["status"]).lower()
    return str(data.get("status") or "").lower()


def _extract_audio_from_payload(data: Any) -> Optional[bytes]:
    if not isinstance(data, dict):
        return None

    for obj in _nested_dicts(data):
        for key in (
            "audios",
            "audio",
            "audio_base64",
            "audioBase64",
            "content",
            "audio_content",
            "file",
        ):
            raw = _decode_b64_audio(obj.get(key))
            if raw:
                return raw
    return None


def _audio_from_status_payload(
    client: httpx.Client,
    data: dict[str, Any],
) -> Optional[bytes]:
    audio = _extract_audio_from_payload(data)
    if audio:
        return audio
    audio_url = _find_audio_url(data)
    if audio_url:
        file_resp = client.get(audio_url)
        file_resp.raise_for_status()
        return file_resp.content
    return None


def _poll_clone_job(
    client: httpx.Client,
    headers: dict[str, str],
    job_id: str,
    timeout: float,
) -> bytes:
    """
    Poll Studio job until audio is ready.

    Creator Studio follows synthesize with GET requests named by job_id.
    We try the known voice-library status paths.
    """
    candidates = [
        f"https://studio.sarvam.ai/api/voice-library/synthesize/{job_id}",
        f"https://studio.sarvam.ai/api/voice-library/jobs/{job_id}",
        f"https://studio.sarvam.ai/api/voice-library/job/{job_id}",
        f"https://studio.sarvam.ai/api/voice-library/status/{job_id}",
        f"https://studio.sarvam.ai/api/voice-library/synthesize/status/{job_id}",
        f"https://studio.sarvam.ai/api/voice-library/synthesize/jobs/{job_id}",
        f"https://studio.sarvam.ai/api/voice-library/history/{job_id}",
    ]
    deadline = time.monotonic() + max(timeout, 5.0)
    last_err = "no status response"
    working_url: Optional[str] = None

    while time.monotonic() < deadline:
        urls = [working_url] if working_url else candidates
        for url in urls:
            if not url:
                continue
            try:
                resp = client.get(url, headers=headers)
            except Exception as exc:
                last_err = str(exc)
                continue
            if resp.status_code == 404:
                continue
            if resp.status_code >= 400:
                last_err = f"{resp.status_code} {resp.text[:200]}"
                continue

            working_url = url
            content_type = (resp.headers.get("content-type") or "").lower()
            if "audio/" in content_type and resp.content:
                return resp.content

            try:
                data = resp.json()
            except Exception:
                if resp.content and len(resp.content) > 100:
                    return resp.content
                last_err = "non-json status body"
                continue

            audio = _audio_from_status_payload(client, data if isinstance(data, dict) else {})
            if audio:
                logger.info("Sarvam clone TTS job ready job_id=%s via %s", job_id, url)
                return audio

            status = _job_status(data if isinstance(data, dict) else {})
            if status in {"failed", "error", "cancelled"}:
                raise RuntimeError(f"Sarvam clone job failed: {data}")
            last_err = f"pending status={status or 'unknown'} url={url}"
            logger.debug("Sarvam clone TTS poll job_id=%s status=%s", job_id, status)
            break
        time.sleep(0.75)

    raise RuntimeError(f"Sarvam clone job timed out ({job_id}): {last_err}")


def _synthesize_cloned(text: str, language_code: str) -> bytes:
    """
    Studio cloned-voice path used by Creator Studio for SHIRISH.
    Captured from DevTools: POST /api/voice-library/synthesize with voice_id.
    Async flow:
      202 {"status":"success","data":{"job_id":"...","status":"queued"}}
      then poll until audio is available.
    """
    voice_id = _voice_id()
    if not voice_id:
        raise RuntimeError("SARVAM_VOICE_ID is not configured")
    if not (settings.SARVAM_API_KEY or settings.SARVAM_STUDIO_COOKIE):
        raise RuntimeError("SARVAM_API_KEY or SARVAM_STUDIO_COOKIE is required for clones")

    lang = _normalize_language(language_code)
    payload = {
        "voice_id": voice_id,
        "language": lang,
        "pace": float(settings.SARVAM_TTS_PACE or 1.0),
        "text": text,
    }
    headers = _auth_headers()
    timeout = float(settings.SARVAM_TTS_TIMEOUT_SECONDS or 30.0)

    logger.info(
        "Sarvam clone TTS request voice_id=%s lang=%s chars=%s",
        voice_id,
        lang,
        len(text),
    )

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.post(SARVAM_CLONE_SYNTHESIZE_URL, headers=headers, json=payload)

        if response.status_code >= 400:
            logger.error(
                "Sarvam clone TTS failed status=%s body=%s",
                response.status_code,
                response.text[:500],
            )
            response.raise_for_status()

        # Binary audio returned directly
        content_type = (response.headers.get("content-type") or "").lower()
        if "audio/" in content_type and response.content:
            return response.content

        try:
            data = response.json()
        except Exception as exc:
            if response.content and len(response.content) > 100:
                return response.content
            raise RuntimeError("Sarvam clone TTS returned non-JSON body") from exc

        if not isinstance(data, dict):
            raise RuntimeError(f"Sarvam clone TTS unexpected payload type: {type(data)}")

        audio = _audio_from_status_payload(client, data)
        if audio:
            return audio

        # 202 Accepted / async job — poll until ready
        job_id = _find_job_id(data, response)
        job_status = _job_status(data)
        if job_id and response.status_code in (200, 202):
            logger.info(
                "Sarvam clone TTS async job_id=%s http=%s job_status=%s body=%s",
                job_id,
                response.status_code,
                job_status,
                str(data)[:300],
            )
            return _poll_clone_job(client, headers, job_id, timeout)

        logger.error(
            "Sarvam clone TTS no job_id/audio http=%s body=%s",
            response.status_code,
            str(data)[:500],
        )

    raise RuntimeError(
        "Sarvam clone TTS returned no audio. "
        "If status was 401/403, set SARVAM_STUDIO_COOKIE from Creator Studio DevTools."
    )


def _synthesize_builtin(text: str, language_code: str) -> bytes:
    """Public Bulbul API path for built-in speakers (ratan, shubh, ...)."""
    if not settings.SARVAM_API_KEY:
        raise RuntimeError("SARVAM_API_KEY is not configured")
    speaker = _speaker()
    if not speaker:
        raise RuntimeError("SARVAM_SPEAKER is not configured")

    payload = {
        "text": text,
        "language_code": _normalize_language(language_code),
        "speaker": speaker,
        "model": settings.SARVAM_TTS_MODEL or "bulbul:v3",
        "pace": float(settings.SARVAM_TTS_PACE or 1.0),
        "speech_sample_rate": str(int(settings.SARVAM_TTS_SAMPLE_RATE or 16000)),
        "output_audio_codec": _codec_ext(),
    }
    headers = {
        "api-subscription-key": settings.SARVAM_API_KEY,
        "Content-Type": "application/json",
    }
    timeout = float(settings.SARVAM_TTS_TIMEOUT_SECONDS or 30.0)

    logger.info(
        "Sarvam TTS request speaker=%s lang=%s chars=%s model=%s",
        speaker,
        payload["language_code"],
        len(text),
        payload["model"],
    )

    with httpx.Client(timeout=timeout) as client:
        response = client.post(SARVAM_TTS_URL, headers=headers, json=payload)

    if response.status_code >= 400:
        logger.error(
            "Sarvam TTS failed status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
        response.raise_for_status()

    data = response.json()
    audios = data.get("audios") or []
    if not audios:
        raise RuntimeError("Sarvam TTS returned no audios")

    if isinstance(audios, list):
        b64 = "".join(audios)
    else:
        b64 = str(audios)
    return base64.b64decode(b64)


def synthesize_to_bytes(text: str, language_code: str) -> bytes:
    """
    Call Sarvam TTS and return decoded audio bytes.
    Uses Studio voice_id path for clones; otherwise public speaker path.
    """
    clean = (text or "").strip()
    if not clean:
        raise ValueError("TTS text is empty")

    max_chars = _max_chars()
    if len(clean) > max_chars:
        clean = clean[:max_chars]

    if uses_cloned_voice():
        return _synthesize_cloned(clean, language_code)
    return _synthesize_builtin(clean, language_code)


def get_cached_audio_file(text: str, language_code: str) -> Optional[Path]:
    """Return cached audio path when present; never calls Sarvam."""
    voice_key = _active_voice_key()
    key = _cache_key(text, _normalize_language(language_code), voice_key)
    directory = cache_dir()

    for ext in ("wav", "mp3"):
        candidate = directory / f"{key}.{ext}"
        if candidate.exists() and candidate.stat().st_size > 0:
            path = _repair_cache_path(candidate)
            logger.debug("Sarvam TTS cache hit %s", path.name)
            return path
    return None


def get_or_create_audio_file(text: str, language_code: str) -> Path:
    """Return cached audio path, generating via Sarvam on miss."""
    cached = get_cached_audio_file(text, language_code)
    if cached:
        return cached

    audio = synthesize_to_bytes(text, language_code)
    voice_key = _active_voice_key()
    key = _cache_key(text, _normalize_language(language_code), voice_key)
    directory = cache_dir()
    ext = _detect_audio_ext(audio)
    path = directory / f"{key}.{ext}"
    path.write_bytes(audio)
    logger.info(
        "Sarvam TTS cached %s (%s bytes, format=%s)",
        path.name,
        len(audio),
        ext,
    )
    return path


def public_audio_url(base_url: str, filename: str) -> str:
    return f"{base_url.rstrip('/')}/agent/v1/voice/audio/{filename}"


def resolve_play_url(
    text: str,
    language_code: str,
    base_url: str,
    *,
    allow_generate: bool = True,
) -> Optional[str]:
    """
    Return a public Play URL for cloned-voice audio.

    When allow_generate is False (webhook fast path), only cached audio is used
    so Twilio gets TwiML immediately without waiting on Sarvam.
    """
    if not voice_clone_ready():
        return None
    if not base_url:
        logger.warning("Sarvam TTS skipped: missing base_url")
        return None
    try:
        if allow_generate:
            path = get_or_create_audio_file(text, language_code)
        else:
            path = get_cached_audio_file(text, language_code)
            if not path:
                logger.debug("Sarvam TTS cache miss (allow_generate=False)")
                return None
        return public_audio_url(base_url, path.name)
    except Exception as exc:
        logger.warning("Sarvam TTS failed, will fallback to <Say>: %s", exc)
        return None


def twilio_say(text: str, twilio_lang: str) -> str:
    """Twilio <Say> fallback element."""
    voice = VOICE_BY_LANG.get(twilio_lang)
    voice_attr = f' voice="{escape(voice)}"' if voice else ""
    return f'<Say language="{escape(twilio_lang)}"{voice_attr}>{escape(text)}</Say>'


def speak(
    text: str,
    twilio_lang: str,
    base_url: str = "",
    *,
    allow_generate: bool = True,
) -> str:
    """
    Preferred prompt element for the voice agent.
    Uses <Play> with Sarvam cloned audio when available; otherwise <Say>.

    Pass allow_generate=False on latency-sensitive webhooks (incoming call,
    language select) to avoid blocking on live Sarvam synthesis.
    """
    play_url = resolve_play_url(
        text,
        twilio_lang,
        base_url,
        allow_generate=allow_generate,
    )
    if play_url:
        return f'<Play>{escape(play_url)}</Play>'
    return twilio_say(text, twilio_lang)


def read_cached_audio(filename: str) -> tuple[bytes, str]:
    """
    Load a cached audio file for the public audio webhook.
    Content-Type is derived from magic bytes so mislabeled .mp3 WAV still plays.
    Raises FileNotFoundError / ValueError on bad input.
    """
    if not _SAFE_FILE_RE.match(filename or ""):
        raise ValueError("invalid audio filename")
    path = cache_dir() / filename
    if not path.is_file():
        raise FileNotFoundError(filename)
    data = path.read_bytes()
    return data, _content_type(_detect_audio_ext(data))
