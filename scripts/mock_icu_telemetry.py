#!/usr/bin/env python3
"""Mock ICU monitor telemetry for local development and demos."""

from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime, timezone

import httpx


def build_payload(demo_alerts: bool) -> dict:
    if demo_alerts and random.random() < 0.2:
        heart_rate = random.uniform(135, 150)
        spo2 = random.uniform(82, 87)
    else:
        heart_rate = random.uniform(65, 95)
        spo2 = random.uniform(95, 99)

    samples = [round(random.uniform(-0.5, 0.5), 4) for _ in range(20)]
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "heart_rate": round(heart_rate, 1),
        "systolic_bp": round(random.uniform(105, 130), 1),
        "diastolic_bp": round(random.uniform(65, 85), 1),
        "spo2": round(spo2, 1),
        "respiratory_rate": round(random.uniform(14, 20), 1),
        "temperature": round(random.uniform(36.5, 37.2), 1),
        "ecg_data": {"sampling_hz": 250, "samples": samples},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Send mock ICU telemetry to NexaCare API")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--api-key",
        required=True,
        help="Device API key from POST /api/v1/icu/devices",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Seconds between telemetry posts (default: 5)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="Number of posts (0 = run until interrupted)",
    )
    parser.add_argument(
        "--demo-alerts",
        action="store_true",
        help="Occasionally send out-of-range vitals to trigger alerts",
    )
    args = parser.parse_args()

    url = f"{args.base_url.rstrip('/')}/api/v1/icu/telemetry"
    headers = {"X-Device-API-Key": args.api_key, "Content-Type": "application/json"}

    sent = 0
    print(f"Posting mock telemetry to {url} every {args.interval}s")
    try:
        with httpx.Client(timeout=30.0) as client:
            while True:
                payload = build_payload(args.demo_alerts)
                response = client.post(url, json=payload, headers=headers)
                sent += 1
                if response.status_code >= 400:
                    print(f"[{sent}] ERROR {response.status_code}: {response.text}")
                else:
                    body = response.json()
                    data = body.get("data", {})
                    alerts = data.get("alerts_created", 0)
                    print(
                        f"[{sent}] OK reading_id={data.get('reading_id')} "
                        f"HR={payload['heart_rate']} SpO2={payload['spo2']} alerts={alerts}"
                    )
                if args.count and sent >= args.count:
                    break
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    except httpx.HTTPError as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
