"""
Verify Twilio credentials from .env.

Usage (from hms-backend folder):
  python scripts/test_twilio.py
  python scripts/test_twilio.py --call
"""
import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.core.config import get_settings

get_settings.cache_clear()
settings = get_settings()

from app.utils.twilio_client import twilio_client


async def main(do_call: bool) -> None:
    print("Twilio configuration check")
    print("-" * 40)
    print(f"Account SID:     {settings.TWILIO_ACCOUNT_SID or '(empty)'}")
    print(f"From number:     {settings.TWILIO_PHONE_NUMBER or '(empty)'}")
    print(f"WhatsApp from:   {settings.TWILIO_WHATSAPP_NUMBER or '(empty)'}")
    test_to = getattr(settings, "TWILIO_TEST_TO_NUMBER", "") or ""
    print(f"Test to number:  {test_to or '(empty)'}")
    print(f"Public base URL: {settings.PUBLIC_BASE_URL}")
    print(f"Configured:      {twilio_client.is_configured}")

    if not twilio_client.is_configured:
        print("\nFAIL: Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env")
        sys.exit(1)

    import httpx

    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}.json"
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url, auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        )
    if response.status_code != 200:
        print(f"\nFAIL: API auth failed ({response.status_code}): {response.text}")
        sys.exit(1)

    data = response.json()
    print(f"\nOK: Connected to Twilio account '{data.get('friendly_name', '')}'")
    print(f"    Status: {data.get('status')}")

    if not do_call:
        print("\nTip: Run with --call to place a test outbound call.")
        print("     Trial accounts must verify the TO number in Twilio Console first.")
        return

    to_number = test_to
    if not to_number or not settings.TWILIO_PHONE_NUMBER:
        print("\nFAIL: Set TWILIO_TEST_TO_NUMBER (or TWILIO_TO_NUMBER) and TWILIO_PHONE_NUMBER in .env")
        sys.exit(1)

    twiml_url = (
        f"{settings.PUBLIC_BASE_URL.rstrip('/')}"
        f"{settings.API_V1_PREFIX}/voice-reminder/twiml/1"
    )
    print(f"\nPlacing test call to {to_number} ...")
    print(f"TwiML URL: {twiml_url}")
    print("Note: Use ngrok HTTPS PUBLIC_BASE_URL for the call to play the full menu.")

    result = await twilio_client.initiate_call(to_number, twiml_url=twiml_url)
    print(f"Call initiated: {result}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Twilio credentials")
    parser.add_argument("--call", action="store_true", help="Place a test outbound call")
    asyncio.run(main(parser.parse_args().call))
