"""Twilio and Exotel webhook signature validation."""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Mapping
from fastapi import HTTPException, Request, status

import logging

from app.core.config import settings
from app.core.constants import TelephonyProviderType

# Use nexacare.* so TRACE lines appear in the uvicorn terminal (hms often does not).
logger = logging.getLogger("nexacare.voice.auth")

_DEV_ENVS = frozenset({"development", "dev", "local", "test"})


def _is_production() -> bool:
    return (settings.APP_ENV or "").strip().lower() in ("production", "prod")


def _env_flag_true(name: str) -> bool:
    """Read a boolean-like flag from the live process environment."""
    raw = (os.getenv(name) or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def should_skip_voice_webhook_auth() -> bool:
    """
    Bypass Twilio/Exotel signature checks only outside production.

    Triggers:
    - SKIP_VOICE_WEBHOOK_AUTH=true (settings or live os.environ)
    - APP_ENV in development/dev/local/test

    Production never bypasses here (production_checks also rejects SKIP=true).
    """
    if _is_production():
        return False

    if settings.SKIP_VOICE_WEBHOOK_AUTH or _env_flag_true("SKIP_VOICE_WEBHOOK_AUTH"):
        return True

    app_env = (settings.APP_ENV or os.getenv("APP_ENV") or "").strip().lower()
    return app_env in _DEV_ENVS


def _build_absolute_url(request: Request) -> str:
    """Prefer PUBLIC_BASE_URL so signature matches provider-configured webhook URL."""
    # Live os.environ may be updated by pyngrok after settings were cached at import.
    configured = (
        os.getenv("PUBLIC_BASE_URL")
        or settings.PUBLIC_BASE_URL
        or ""
    ).rstrip("/")
    if configured:
        return f"{configured}{request.url.path}"
    return str(request.url.replace(query=""))


def validate_twilio_signature(
    url: str,
    params: Mapping[str, str],
    signature: str,
    auth_token: str,
) -> bool:
    if not auth_token or not signature:
        return False
    # Twilio: HMAC-SHA1(url + sorted key+value pairs)
    s = url
    for key in sorted(params.keys()):
        s += key + str(params[key])
    digest = hmac.new(
        auth_token.encode("utf-8"),
        s.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    import base64

    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def validate_exotel_signature(
    body: bytes,
    signature: str | None,
    token_header: str | None,
    query_token: str | None,
) -> bool:
    """
    Exotel deployments vary. Accept either:
    1) Shared webhook secret via X-Exotel-Signature (HMAC-SHA256 of raw body)
    2) Shared secret via X-Exotel-Token / Authorization / ?token=
    """
    secret = settings.EXOTEL_WEBHOOK_SECRET or settings.EXOTEL_API_TOKEN
    if not secret:
        return False

    if token_header and hmac.compare_digest(token_header.strip(), secret):
        return True
    if query_token and hmac.compare_digest(query_token.strip(), secret):
        return True
    if signature:
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        # Also accept base64 forms
        if hmac.compare_digest(expected, signature.strip().lower()):
            return True
        import base64

        b64 = base64.b64encode(
            hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
        ).decode("utf-8")
        if hmac.compare_digest(b64, signature.strip()):
            return True
    return False


async def require_voice_webhook_auth(
    request: Request,
    provider: str,
) -> None:
    """Raise 403 if webhook signature/token is invalid."""
    signature_hdr = request.headers.get("X-Twilio-Signature", "")
    public_base = (os.getenv("PUBLIC_BASE_URL") or settings.PUBLIC_BASE_URL or "")
    skip = should_skip_voice_webhook_auth()

    logger.info(
        "TRACE require_voice_webhook_auth ENTER file=%s provider=%r path=%s "
        "SKIP_settings=%r SKIP_env=%r APP_ENV=%r skip=%s PUBLIC_BASE_URL=%r "
        "request.url=%r X-Twilio-Signature_present=%s",
        __file__,
        provider,
        request.url.path,
        settings.SKIP_VOICE_WEBHOOK_AUTH,
        os.getenv("SKIP_VOICE_WEBHOOK_AUTH"),
        settings.APP_ENV,
        skip,
        public_base,
        str(request.url),
        bool(signature_hdr),
    )
    # Guaranteed console visibility even if logging is misconfigured
    print(
        f"[TRACE] require_voice_webhook_auth ENTER skip={skip} "
        f"path={request.url.path} file={__file__}",
        flush=True,
    )

    if skip:
        logger.info(
            "TRACE require_voice_webhook_auth SKIP auth — returning without 403 "
            "(APP_ENV=%s SKIP_VOICE_WEBHOOK_AUTH=%s)",
            settings.APP_ENV,
            settings.SKIP_VOICE_WEBHOOK_AUTH or _env_flag_true("SKIP_VOICE_WEBHOOK_AUTH"),
        )
        print("[TRACE] require_voice_webhook_auth SKIP — no signature check", flush=True)
        return

    # Rate-limit abusive webhook traffic per client IP
    from app.utils.rate_limiter import voice_webhook_rate_limiter

    client_host = request.client.host if request.client else "unknown"
    try:
        voice_webhook_rate_limiter.check(f"voice-webhook:{provider}:{client_host}")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Voice webhook rate limit exceeded",
        )

    provider = (provider or "").lower()
    if provider == TelephonyProviderType.TWILIO:
        signature = signature_hdr
        form = await request.form()
        params = {k: (v if isinstance(v, str) else str(v)) for k, v in form.items()}
        url = _build_absolute_url(request)
        # Also try with query string if present (Twilio includes full URL)
        full_url = str(request.url)
        ok = validate_twilio_signature(
            url, params, signature, settings.TWILIO_AUTH_TOKEN
        ) or validate_twilio_signature(
            full_url.split("?")[0], params, signature, settings.TWILIO_AUTH_TOKEN
        )
        if (os.getenv("PUBLIC_BASE_URL") or settings.PUBLIC_BASE_URL) and request.url.query:
            ok = ok or validate_twilio_signature(
                f"{url}?{request.url.query}",
                params,
                signature,
                settings.TWILIO_AUTH_TOKEN,
            )

        logger.info(
            "TRACE require_voice_webhook_auth Twilio validate | url=%r ok=%s token_set=%s",
            url,
            ok,
            bool(settings.TWILIO_AUTH_TOKEN),
        )

        if not settings.TWILIO_AUTH_TOKEN:
            if settings.APP_ENV == "production":
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Twilio auth token not configured",
                )
            logger.info("TRACE Twilio AUTH_TOKEN missing — allowing in non-production")
            return
        if not ok:
            logger.info(
                "TRACE require_voice_webhook_auth BEFORE HTTP 403 "
                "detail='Invalid Twilio signature' path=%s url=%r",
                request.url.path,
                url,
            )
            print(
                "[TRACE] BEFORE HTTP 403 Invalid Twilio signature "
                f"path={request.url.path}",
                flush=True,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid Twilio signature",
                headers={"X-Voice-Auth-Reject": "invalid-twilio-signature"},
            )
        await _reject_replay(provider, signature or _payload_fingerprint(params), request.url.path)
        logger.info("TRACE require_voice_webhook_auth Twilio OK path=%s", request.url.path)
        return

    if provider == TelephonyProviderType.EXOTEL:
        body = await request.body()
        signature = request.headers.get("X-Exotel-Signature")
        token_header = (
            request.headers.get("X-Exotel-Token")
            or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        )
        query_token = request.query_params.get("token")
        if not (settings.EXOTEL_WEBHOOK_SECRET or settings.EXOTEL_API_TOKEN):
            if settings.APP_ENV == "production":
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Exotel webhook secret not configured",
                )
            logger.info("TRACE Exotel secret missing — allowing in non-production")
            return
        if not validate_exotel_signature(body, signature, token_header, query_token):
            logger.info(
                "TRACE require_voice_webhook_auth BEFORE HTTP 403 "
                "detail='Invalid Exotel signature' path=%s",
                request.url.path,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid Exotel signature",
                headers={"X-Voice-Auth-Reject": "invalid-exotel-signature"},
            )
        replay_token = signature or hashlib.sha256(body).hexdigest()
        await _reject_replay(provider, replay_token, request.url.path)
        return

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown provider")


def _payload_fingerprint(params: Mapping[str, str]) -> str:
    raw = "|".join(f"{k}={params[k]}" for k in sorted(params.keys()))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _reject_replay(provider: str, token: str, path: str) -> None:
    """Reject identical webhook payloads replayed within TTL (not CallSid — multi-turn safe)."""
    if not token:
        return
    try:
        from app.utils.redis_service import cache_get, cache_set

        key = f"voice:webhook:replay:{provider}:{hashlib.sha256((token + path).encode()).hexdigest()}"
        if await cache_get(key):
            logger.info(
                "TRACE _reject_replay BEFORE HTTP 403 detail='Replay detected' path=%s",
                path,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Replay detected",
                headers={"X-Voice-Auth-Reject": "replay-detected"},
            )
        await cache_set(key, {"seen": True}, ttl=120)
    except HTTPException:
        raise
    except Exception as exc:
        logger.info("TRACE Webhook replay check skipped: %s", exc)
