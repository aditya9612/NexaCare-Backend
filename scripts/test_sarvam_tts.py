#!/usr/bin/env python3
"""
Smoke-test Sarvam TTS for local voice cloning.

Usage (from repo root, with venv active):
  python scripts/test_sarvam_tts.py
  python scripts/test_sarvam_tts.py --text "नमस्कार" --lang mr-IN

Requires in .env:
  VOICE_CLONE_ENABLED=true
  SARVAM_API_KEY=...
  SARVAM_VOICE_ID=...   # Studio clone UUID (preferred for SHIRISH)
  # or SARVAM_SPEAKER=ratan for built-in voices
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Sarvam TTS local smoke test")
    parser.add_argument(
        "--text",
        default="नमस्कार! हे NexaCare AI अपॉइंटमेंट असिस्टंट आहे.",
    )
    parser.add_argument("--lang", default="mr-IN")
    parser.add_argument(
        "--out",
        default="app/uploads/voice-cache/sarvam_smoke_test.mp3",
        help="Where to write a copy of the generated audio",
    )
    args = parser.parse_args()

    from app.core.config import settings
    from app.services.sarvam_tts import (
        get_or_create_audio_file,
        uses_cloned_voice,
        voice_clone_ready,
    )

    print("VOICE_CLONE_ENABLED =", settings.VOICE_CLONE_ENABLED)
    print("SARVAM_VOICE_ID     =", settings.SARVAM_VOICE_ID or "(empty)")
    print("SARVAM_SPEAKER      =", settings.SARVAM_SPEAKER or "(empty)")
    print("uses_cloned_voice   =", uses_cloned_voice())
    print("SARVAM_TTS_MODEL    =", settings.SARVAM_TTS_MODEL)
    print("ready               =", voice_clone_ready())

    if not voice_clone_ready():
        print(
            "\nNot ready. Set VOICE_CLONE_ENABLED=true, SARVAM_API_KEY, "
            "and SARVAM_VOICE_ID (clone) or SARVAM_SPEAKER (built-in) in .env, then restart."
        )
        return 1

    path = get_or_create_audio_file(args.text, args.lang)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(path.read_bytes())
    print(f"\nOK — cached as {path}")
    print(f"Copied to {out} ({out.stat().st_size} bytes)")
    print("Play that file locally to verify your voice.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
