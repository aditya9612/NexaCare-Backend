from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.core.logger import logger


class TwilioClient:
    """Twilio/Exotel-ready voice and WhatsApp integration."""

    def __init__(self):
        self.account_sid = settings.TWILIO_ACCOUNT_SID
        self.auth_token = settings.TWILIO_AUTH_TOKEN
        self.phone_number = settings.TWILIO_PHONE_NUMBER
        self.whatsapp_number = settings.TWILIO_WHATSAPP_NUMBER

    @property
    def is_configured(self) -> bool:
        return bool(self.account_sid and self.auth_token)

    async def initiate_call(self, to: str, twiml_url: Optional[str] = None) -> Dict[str, Any]:
        if not self.is_configured:
            logger.warning("Twilio not configured; simulating call to %s", to)
            return {"sid": f"SIM-{to[-4:]}", "status": "queued", "simulated": True}

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Calls.json"
        data = {"To": to, "From": self.phone_number}
        if twiml_url:
            data["Url"] = twiml_url
        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data, auth=(self.account_sid, self.auth_token))
            response.raise_for_status()
            return response.json()

    async def send_sms(self, to: str, body: str) -> Dict[str, Any]:
        if not self.is_configured:
            logger.warning("Twilio not configured; simulating SMS to %s", to)
            return {"sid": f"SMS-SIM-{to[-4:]}", "status": "queued", "simulated": True}

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        data = {"To": to, "From": self.phone_number, "Body": body}
        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data, auth=(self.account_sid, self.auth_token))
            response.raise_for_status()
            return response.json()

    async def send_whatsapp(self, to: str, body: str, media_url: Optional[str] = None) -> Dict[str, Any]:
        if not self.is_configured:
            logger.warning("Twilio WhatsApp not configured; simulating message to %s", to)
            return {"sid": f"WA-SIM-{to[-4:]}", "status": "queued", "simulated": True}

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        data = {
            "To": f"whatsapp:{to}",
            "From": f"whatsapp:{self.whatsapp_number}",
            "Body": body,
        }
        if media_url:
            data["MediaUrl"] = media_url
        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data, auth=(self.account_sid, self.auth_token))
            response.raise_for_status()
            return response.json()


twilio_client = TwilioClient()
