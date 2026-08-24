"""
Safe dev-only ngrok helper.

Avoids socket exhaustion on Windows when uvicorn --reload restarts the app:
- Does not call ngrok.kill() (that orphans processes and leaks sockets).
- Reuses an existing tunnel to the same local port when possible.
- Skips auto-start when PUBLIC_BASE_URL is already a non-localhost HTTPS URL.
- Tears down only the tunnel this process opened on shutdown.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.core.config import settings

logger = logging.getLogger("nexacare.ngrok")

_tunnel: Any | None = None
_tunnel_public_url: str | None = None


def _is_production() -> bool:
    return (settings.APP_ENV or "").lower() in ("production", "prod")


def _configured_public_url() -> str:
    return (settings.PUBLIC_BASE_URL or os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")


def _has_external_https_url() -> bool:
    """True when .env already points webhooks at a stable HTTPS URL (manual ngrok CLI, etc.)."""
    url = _configured_public_url()
    if not url.lower().startswith("https://"):
        return False
    host = url.lower()
    return "localhost" not in host and "127.0.0.1" not in host


def _local_target(port: int) -> str:
    return f"127.0.0.1:{port}"


def _tunnel_forwards_to_port(tunnel: Any, port: int) -> bool:
    addr = str(getattr(getattr(tunnel, "config", None), "get", lambda _k, _d=None: "")("addr", "") or "")
    if not addr:
        addr = str(getattr(tunnel, "data", {}).get("config", {}).get("addr", ""))
    targets = {f"http://127.0.0.1:{port}", f"http://localhost:{port}", _local_target(port)}
    return any(t in addr for t in targets) or addr.endswith(f":{port}")


def start_dev_tunnel(port: int = 8000) -> str | None:
    """
    Start or reuse an ngrok HTTP tunnel for local Twilio/Exotel webhooks.

    Returns the public HTTPS base URL, or None when ngrok is not used.
    """
    global _tunnel, _tunnel_public_url

    if _is_production():
        return None

    if not settings.ENABLE_NGROK_TUNNEL:
        if _has_external_https_url():
            logger.info(
                "Skipping embedded ngrok (ENABLE_NGROK_TUNNEL=false); using PUBLIC_BASE_URL=%s",
                _configured_public_url(),
            )
        return _configured_public_url() if _has_external_https_url() else None

    if _has_external_https_url():
        logger.info(
            "Skipping embedded ngrok; PUBLIC_BASE_URL already set to %s",
            _configured_public_url(),
        )
        return _configured_public_url()

    token = (settings.NGROK_AUTH_TOKEN or os.getenv("NGROK_AUTH_TOKEN") or "").strip()
    if not token:
        logger.info("NGROK_AUTH_TOKEN not set — skipping embedded ngrok tunnel")
        return None

    try:
        from pyngrok import conf, ngrok
    except ImportError:
        logger.warning("pyngrok is not installed — skipping embedded ngrok tunnel")
        return None

    try:
        conf.get_default().auth_token = token

        # Reuse an existing tunnel instead of opening a new one on every reload.
        for existing in ngrok.get_tunnels():
            if _tunnel_forwards_to_port(existing, port):
                _tunnel = existing
                _tunnel_public_url = existing.public_url
                os.environ["PUBLIC_BASE_URL"] = _tunnel_public_url
                logger.info("Reusing ngrok tunnel: %s -> %s", _tunnel_public_url, _local_target(port))
                return _tunnel_public_url

        _tunnel = ngrok.connect(_local_target(port), "http")
        _tunnel_public_url = _tunnel.public_url
        os.environ["PUBLIC_BASE_URL"] = _tunnel_public_url
        logger.info("Started ngrok tunnel: %s -> %s", _tunnel_public_url, _local_target(port))
        return _tunnel_public_url
    except Exception as exc:
        logger.warning("Embedded ngrok failed to start: %s", exc)
        return None


def stop_dev_tunnel() -> None:
    """Disconnect only the tunnel opened/reused by this process."""
    global _tunnel, _tunnel_public_url

    if _tunnel is None:
        return

    try:
        from pyngrok import ngrok

        public_url = _tunnel_public_url or getattr(_tunnel, "public_url", None)
        if public_url:
            ngrok.disconnect(public_url)
            logger.info("Disconnected ngrok tunnel %s", public_url)
    except Exception as exc:
        logger.debug("ngrok disconnect skipped: %s", exc)
    finally:
        _tunnel = None
        _tunnel_public_url = None
