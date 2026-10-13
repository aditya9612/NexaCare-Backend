import asyncio
import os
import httpx

from app.services.throttling_service import ThrottlingService

URL = "http://127.0.0.1:8000/api/v1/patients/export"
RESOURCE_KEY = "heavy:/api/v1/patients/export"
TOKEN = os.environ["NEXACARE_TOKEN"]


async def main():
    headers = {"Authorization": f"Bearer {TOKEN}"}

    print("==================================================")
    print("Manual Throttling Verification Test")
    print("Endpoint: GET /api/v1/patients/export")
    print("Expected Concurrency Limit: 3")
    print("==================================================\n")

    # Step 1: Occupy all 3 heavy concurrency slots directly in Redis
    print("1. Occupying 3 heavy-route concurrency slots...")
    s1 = await ThrottlingService.acquire_slot(RESOURCE_KEY, max_concurrency=3)
    s2 = await ThrottlingService.acquire_slot(RESOURCE_KEY, max_concurrency=3)
    s3 = await ThrottlingService.acquire_slot(RESOURCE_KEY, max_concurrency=3)
    tokens = [s1.token, s2.token, s3.token]
    print("   3 slots occupied successfully.")

    async with httpx.AsyncClient(timeout=60) as client:
        # Step 2: Attempt 4th request while all 3 slots are occupied
        print("\n2. Attempting 4th request while all 3 slots are occupied:")
        try:
            r4 = await client.get(URL, headers=headers)
            print(
                f"   Request 4: HTTP {r4.status_code}, "
                f"Retry-After={r4.headers.get('Retry-After')}"
            )
        except Exception as e:
            print(f"   Request 4: ERROR - {e}")

        # Step 3: Release active slots
        print("\n3. Releasing active concurrency slots...")
        for tok in tokens:
            await ThrottlingService.release_slot(RESOURCE_KEY, tok)
        print("   Slots released successfully.")

        # Step 4: Send another request to verify slot release
        print("\n4. Sending request after slot release:")
        try:
            r5 = await client.get(URL, headers=headers)
            print(
                f"   Request 5: HTTP {r5.status_code}, "
                f"Retry-After={r5.headers.get('Retry-After')}"
            )
        except Exception as e:
            print(f"   Request 5: ERROR - {e}")

    print("\nNote on HTTP Concurrency Limitation:")
    print(
        "Without artificial server delays, sending concurrent HTTP requests directly can be non-deterministic "
        "if the export route executes faster than network request dispatch. Pre-occupying slots guarantees "
        "deterministic verification of HTTP 429 responses and Retry-After headers without modifying production code."
    )


if __name__ == "__main__":
    asyncio.run(main())

