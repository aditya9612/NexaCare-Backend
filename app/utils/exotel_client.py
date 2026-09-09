from typing import Any, Dict, Optional
import httpx
from app.core.config import settings
from app.core.logger import logger


class ExotelClient:
    """Exotel WhatsApp & SMS Client"""

    def __init__(
        self,
        sid: Optional[str] = None,
        api_key: Optional[str] = None,
        api_token: Optional[str] = None,
        subdomain: Optional[str] = None,
        from_number: Optional[str] = None,
        whatsapp_number: Optional[str] = None,
    ):
        self.sid = sid or settings.EXOTEL_SID
        self.api_key = api_key or settings.EXOTEL_API_KEY
        self.api_token = api_token or settings.EXOTEL_API_TOKEN
        self.subdomain = subdomain or settings.EXOTEL_SUBDOMAIN
        self.from_number = from_number or settings.EXOTEL_PHONE_NUMBER
        self.whatsapp_number = whatsapp_number or getattr(settings, "EXOTEL_WHATSAPP_NUMBER", None) or self.from_number

    @property
    def is_configured(self) -> bool:
        return bool(self.sid and self.api_key and self.api_token)

    async def send_whatsapp(
        self,
        to: str,
        body: str,
        media_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send WhatsApp message using Exotel WhatsApp API."""
        clean_to = to.replace("whatsapp:", "").replace("+", "").strip()
        from_num = (self.whatsapp_number or self.from_number or "").replace("whatsapp:", "").replace("+", "").strip()

        if not self.is_configured:
            logger.warning("Exotel WhatsApp not configured; simulating message to %s", to)
            return {
                "sid": f"EXO-WA-SIM-{clean_to[-4:]}",
                "status": "queued",
                "simulated": True,
            }

        # Exotel WhatsApp V2 endpoint
        url = f"https://{self.subdomain}/v2/accounts/{self.sid}/messages"

        # Format E.164 without leading plus or standard India formatting
        if not clean_to.startswith("91") and len(clean_to) == 10:
            clean_to = f"91{clean_to}"

        msg_content: Dict[str, Any] = {
            "type": "text",
            "text": {
                "body": body
            }
        }

        if media_url:
            msg_content = {
                "type": "media",
                "media": {
                    "url": media_url,
                    "caption": body
                }
            }

        payload = {
            "whatsapp": {
                "messages": [
                    {
                        "from": from_num,
                        "to": clean_to,
                        "content": msg_content
                    }
                ]
            }
        }

        logger.info("========== EXOTEL WHATSAPP REQUEST ==========")
        logger.info("TO: %s | FROM: %s | URL: %s", clean_to, from_num, url)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    json=payload,
                    auth=(self.api_key, self.api_token),
                )
                logger.info("EXOTEL WA STATUS: %s", response.status_code)
                logger.info("EXOTEL WA RESPONSE: %s", response.text)

                if response.status_code in (200, 201, 202):
                    resp_data = response.json()
                    msg_id = ""
                    if isinstance(resp_data, dict):
                        msg_id = resp_data.get("sid") or resp_data.get("message_id") or resp_data.get("id") or ""
                    return {
                        "sid": msg_id or f"EXO-WA-{clean_to[-4:]}",
                        "status": "sent",
                        "raw": resp_data,
                    }
                else:
                    # Fallback to SMS if WhatsApp service is not enabled on account
                    logger.warning("Exotel WhatsApp endpoint returned %s; falling back to Exotel SMS", response.status_code)
                    return await self.send_sms(to=to, body=body)
        except Exception as exc:
            logger.error("Exotel WhatsApp dispatch error: %s; falling back to SMS", exc)
            return await self.send_sms(to=to, body=body)

    async def send_sms(
        self,
        to: str,
        body: str,
    ) -> Dict[str, Any]:
        """Send SMS using Exotel SMS API."""
        clean_to = to.replace("whatsapp:", "").replace("+", "").strip()
        from_num = self.from_number or ""

        if not self.is_configured:
            logger.warning("Exotel SMS not configured; simulating SMS to %s", to)
            return {
                "sid": f"EXO-SMS-SIM-{clean_to[-4:]}",
                "status": "queued",
                "simulated": True,
            }

        url = f"https://{self.subdomain}/v1/Accounts/{self.sid}/Sms/send.json"
        data = {
            "From": from_num,
            "To": clean_to,
            "Body": body,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                data=data,
                auth=(self.api_key, self.api_token),
            )
            logger.info("EXOTEL SMS STATUS: %s", response.status_code)
            logger.info("EXOTEL SMS BODY: %s", response.text)
            response.raise_for_status()
            resp_data = response.json()
            sms_obj = resp_data.get("SMSMessage") or resp_data
            return {
                "sid": sms_obj.get("Sid") or f"EXO-SMS-{clean_to[-4:]}",
                "status": sms_obj.get("Status") or "sent",
                "raw": resp_data,
            }


exotel_client = ExotelClient()
