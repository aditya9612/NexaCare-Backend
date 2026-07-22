from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CallResult:
    provider_call_id: str
    status: str = "queued"
    simulated: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedWebhook:
    """Provider-agnostic webhook payload for inbound/turn/status callbacks."""

    call_sid: str = ""
    from_number: str = ""
    to_number: str = ""
    digits: str = ""
    speech_result: str = ""
    confidence: Optional[str] = None
    call_status: str = ""
    duration_seconds: Optional[int] = None
    provider: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class TelephonyProvider(ABC):
    """Strategy interface for outbound calls and webhook/response rendering."""

    name: str = "base"

    @abstractmethod
    async def initiate_call(
        self,
        to: str,
        webhook_url: str,
        status_callback_url: Optional[str] = None,
        from_number: Optional[str] = None,
    ) -> CallResult:
        raise NotImplementedError

    @abstractmethod
    def normalize_webhook(self, payload: dict[str, Any]) -> NormalizedWebhook:
        raise NotImplementedError

    @abstractmethod
    def render_response(self, xml_or_body: str) -> str:
        """Return telephony XML/body. Twilio uses TwiML; Exotel may pass through or adapt."""
        raise NotImplementedError

    def dial_number(self, number: str, action_url: Optional[str] = None) -> str:
        """Return provider XML to transfer/dial a reception number."""
        raise NotImplementedError

    def say_language(self, lang_code: str) -> str:
        mapping = {"en": "en-IN", "hi": "hi-IN", "mr": "mr-IN"}
        return mapping.get(lang_code, "en-IN")
