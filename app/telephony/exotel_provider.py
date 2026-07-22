from typing import Any, Optional
from xml.sax.saxutils import escape

import httpx

from app.core.config import settings
from app.core.constants import TelephonyProviderType
from app.core.logger import logger
from app.telephony.base import CallResult, NormalizedWebhook, TelephonyProvider


class ExotelProvider(TelephonyProvider):
    """Exotel Voice adapter for India-first deployments."""

    name = TelephonyProviderType.EXOTEL

    def __init__(
        self,
        sid: Optional[str] = None,
        api_key: Optional[str] = None,
        api_token: Optional[str] = None,
        subdomain: Optional[str] = None,
        from_number: Optional[str] = None,
    ):
        self.sid = sid or settings.EXOTEL_SID
        self.api_key = api_key or settings.EXOTEL_API_KEY
        self.api_token = api_token or settings.EXOTEL_API_TOKEN
        self.subdomain = subdomain or settings.EXOTEL_SUBDOMAIN
        self.from_number = from_number or settings.EXOTEL_PHONE_NUMBER

    @property
    def is_configured(self) -> bool:
        return bool(self.sid and self.api_key and self.api_token and self.from_number)

    async def initiate_call(
        self,
        to: str,
        webhook_url: str,
        status_callback_url: Optional[str] = None,
        from_number: Optional[str] = None,
    ) -> CallResult:
        caller_id = from_number or self.from_number
        if not self.is_configured:
            logger.warning("Exotel not configured; simulating call to %s", to)
            return CallResult(
                provider_call_id=f"EXO-SIM-{to[-4:]}",
                status="queued",
                simulated=True,
                raw={"simulated": True},
            )

        url = (
            f"https://{self.subdomain}/v1/Accounts/{self.sid}/Calls/connect.json"
        )
        data = {
            "From": to,
            "CallerId": caller_id,
            "Url": webhook_url,
        }
        if status_callback_url:
            data["StatusCallback"] = status_callback_url

        logger.info("========== EXOTEL REQUEST ==========")
        logger.info("TO: %s", to)
        logger.info("FROM/CallerId: %s", caller_id)
        logger.info("URL: %s", webhook_url)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                data=data,
                auth=(self.api_key, self.api_token),
            )
            logger.info("EXOTEL STATUS: %s", response.status_code)
            logger.info("EXOTEL BODY: %s", response.text)
            response.raise_for_status()
            body = response.json()

        call = body.get("Call") or body
        call_sid = str(call.get("Sid") or call.get("CallSid") or call.get("sid") or "")
        return CallResult(
            provider_call_id=call_sid,
            status=str(call.get("Status") or call.get("status") or "queued"),
            simulated=False,
            raw=body if isinstance(body, dict) else {"response": body},
        )

    def normalize_webhook(self, payload: dict[str, Any]) -> NormalizedWebhook:
        duration = (
            payload.get("DialCallDuration")
            or payload.get("ConversationDuration")
            or payload.get("CallDuration")
            or payload.get("Duration")
        )
        duration_seconds = None
        if duration is not None:
            try:
                duration_seconds = int(duration)
            except (TypeError, ValueError):
                duration_seconds = None

        call_sid = str(
            payload.get("CallSid")
            or payload.get("CallSid")
            or payload.get("call_sid")
            or payload.get("Sid")
            or ""
        )
        from_number = str(
            payload.get("From")
            or payload.get("CallFrom")
            or payload.get("from")
            or ""
        )
        to_number = str(
            payload.get("To")
            or payload.get("CallTo")
            or payload.get("to")
            or ""
        )
        digits = str(payload.get("digits") or payload.get("Digits") or "")
        speech = str(
            payload.get("SpeechResult")
            or payload.get("CustomField")
            or payload.get("speech")
            or ""
        )
        status = str(
            payload.get("Status")
            or payload.get("CallStatus")
            or payload.get("DialCallStatus")
            or ""
        ).lower()

        return NormalizedWebhook(
            call_sid=call_sid,
            from_number=from_number,
            to_number=to_number,
            digits=digits,
            speech_result=speech,
            confidence=(
                str(payload["Confidence"])
                if payload.get("Confidence") is not None
                else None
            ),
            call_status=status,
            duration_seconds=duration_seconds,
            provider=self.name,
            raw=payload,
        )

    def render_response(self, xml_or_body: str) -> str:
        # Exotel Passthru Applets accept Twilio-compatible Response XML in many setups.
        return xml_or_body

    def dial_number(self, number: str, action_url: Optional[str] = None) -> str:
        action_attr = f' action="{escape(action_url)}" method="POST"' if action_url else ""
        return (
            f"<Response>"
            f"<Dial{action_attr}><Number>{escape(number)}</Number></Dial>"
            f"</Response>"
        )
