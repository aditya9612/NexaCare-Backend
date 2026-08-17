from typing import Any, Optional

from app.core.constants import TelephonyProviderType
from app.telephony.base import CallResult, NormalizedWebhook, TelephonyProvider
from app.utils.twilio_client import TwilioClient, twilio_client
from app.utils.twiml_builder import dial as twiml_dial


class TwilioProvider(TelephonyProvider):
    """Twilio adapter — wraps existing TwilioClient without rewriting SMS/WhatsApp."""

    name = TelephonyProviderType.TWILIO

    def __init__(self, client: Optional[TwilioClient] = None, from_number: Optional[str] = None):
        self.client = client or twilio_client
        self.from_number = from_number or self.client.phone_number

    async def initiate_call(
        self,
        to: str,
        webhook_url: str,
        status_callback_url: Optional[str] = None,
        from_number: Optional[str] = None,
    ) -> CallResult:
        original_from = self.client.phone_number
        if from_number:
            self.client.phone_number = from_number
        try:
            result = await self.client.initiate_call(
                to,
                twiml_url=webhook_url,
                status_callback_url=status_callback_url,
            )
        finally:
            self.client.phone_number = original_from

        return CallResult(
            provider_call_id=str(result.get("sid") or ""),
            status=str(result.get("status") or "queued"),
            simulated=bool(result.get("simulated")),
            raw=result if isinstance(result, dict) else {},
        )

    def normalize_webhook(self, payload: dict[str, Any]) -> NormalizedWebhook:
        duration = payload.get("CallDuration") or payload.get("Duration")
        duration_seconds = None
        if duration is not None:
            try:
                duration_seconds = int(duration)
            except (TypeError, ValueError):
                duration_seconds = None

        return NormalizedWebhook(
            call_sid=str(payload.get("CallSid") or payload.get("call_sid") or ""),
            from_number=str(
                payload.get("From") or payload.get("Caller") or payload.get("from") or ""
            ),
            to_number=str(payload.get("To") or payload.get("Called") or ""),
            digits=str(payload.get("Digits") or ""),
            speech_result=str(payload.get("SpeechResult") or ""),
            confidence=(
                str(payload["Confidence"])
                if payload.get("Confidence") is not None
                else None
            ),
            call_status=str(payload.get("CallStatus") or "").lower(),
            duration_seconds=duration_seconds,
            provider=self.name,
            raw=payload,
        )

    def render_response(self, xml_or_body: str) -> str:
        return xml_or_body

    def dial_number(self, number: str, action_url: Optional[str] = None) -> str:
        # For reception transfer, Twilio defaults callerId to the inbound caller's callerId
        # when omitted. We must explicitly set callerId to the hospital's Twilio number.
        return twiml_dial(number, action_url=action_url, caller_id=self.from_number)
