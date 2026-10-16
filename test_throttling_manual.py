import asyncio
import os
import httpx

from app.core.config import settings
from app.core.security import create_access_token
from app.services.throttling_service import ThrottlingService

URL = "http://127.0.0.1:8000/api/v1/doctors/export?format=excel"
RESOURCE_KEY = "heavy:/api/v1/doctors/export"
LIMIT = getattr(settings, "THROTTLING_MAX_CONCURRENCY", 100)
TOKEN = os.environ.get("NEXACARE_TOKEN", "").strip() or create_access_token("1")


async def main():
    headers = {"Authorization": f"Bearer {TOKEN}"}

    print("==================================================")
    print("Manual Throttling Verification Test")
    print("Endpoint: GET /api/v1/doctors/export")
    print(f"Current Concurrency Limit: {LIMIT}")
    print("==================================================\n")

    # Step 1: Occupy all concurrency slots directly in Redis
    print(f"1. Occupying {LIMIT} heavy-route concurrency slots in Redis...")
    tokens = []
    for _ in range(LIMIT):
        s = await ThrottlingService.acquire_slot(RESOURCE_KEY, max_concurrency=LIMIT)
        if s.allowed and s.token:
            tokens.append(s.token)
    print(f"   {len(tokens)} / {LIMIT} slots occupied successfully.")

    async with httpx.AsyncClient(timeout=60) as client:
        # Step 2: Attempt (LIMIT + 1)th request while all slots are occupied
        print(f"\n2. Attempting request #{LIMIT + 1} while all {LIMIT} slots are occupied:")
        try:
            r_blocked = await client.get(URL, headers=headers)
            print(
                f"   Request #{LIMIT + 1} Response: HTTP {r_blocked.status_code}, "
                f"Retry-After={r_blocked.headers.get('Retry-After')}"
            )
            print(f"   Response Body: {r_blocked.text}")
            if r_blocked.status_code == 429:
                print("   >>> SUCCESS: Server rejected request with HTTP 429 (Too Many Requests)!")
            else:
                print(f"   >>> UNEXPECTED: Got status {r_blocked.status_code}")
        except Exception as e:
            print(f"   Request #{LIMIT + 1}: ERROR - {e}")

        # Step 3: Release active slots
        print(f"\n3. Releasing {len(tokens)} active concurrency slots...")
        for tok in tokens:
            await ThrottlingService.release_slot(RESOURCE_KEY, tok)
        print("   Slots released successfully.")

        # Step 4: Send request after slots are released
        print("\n4. Sending request after slot release:")
        try:
            r_ok = await client.get(URL, headers=headers)
            print(
                f"   Subsequent Request Response: HTTP {r_ok.status_code}, "
                f"Content-Type={r_ok.headers.get('content-type')}"
            )
            if r_ok.status_code == 200:
                print("   >>> SUCCESS: Server successfully processed request with HTTP 200 OK!")
        except Exception as e:
            print(f"   Subsequent Request: ERROR - {e}")

    print("\n==================================================")
    print("Throttling Verification Finished.")
    print("==================================================")


if __name__ == "__main__":
    asyncio.run(main())

