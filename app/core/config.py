from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to the project root (NexaCare-Backend/), not process cwd.
# Relative env_file=".env" silently misses the file when uvicorn is started from a parent dir.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "NesaCare HMS"
    APP_ENV: str = "development"
    DEBUG: bool = True
    SQLALCHEMY_ECHO: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # Feature flag to enable/disable the Settings module gracefully.
    ENABLE_SETTINGS: bool = True

   

    
    DATABASE_URL: str = "mysql+aiomysql://nexauser:nexa123@localhost/nexacare"
    DATABASE_URL_SYNC: str = "mysql+pymysql://nexauser:nexa123@localhost/nexacare"

    
    

   

    SECRET_KEY: str = "change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    REDIS_URL: str = "redis://localhost:6379/0"

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@nesacare.com"

    SMS_API_KEY: str = ""
    WHATSAPP_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # Sarvam AI TTS / voice cloning (local + production voice agent prompts)
    # Cloned voice (SHIRISH): set SARVAM_VOICE_ID to Studio voice UUID (voice_id).
    # Built-in voice fallback: set SARVAM_SPEAKER to lowercase name (e.g. ratan).
    # Prefer VOICE_ID when both are set.
    VOICE_CLONE_ENABLED: bool = True
    SARVAM_API_KEY: str = ""
    SARVAM_VOICE_ID: str = ""  # Studio clone UUID, e.g. 27c4beed-27c5-4623-aabc-62339e9e40fa
    SARVAM_SPEAKER: str = ""  # built-in speaker name for public /text-to-speech (lowercase)
    # Optional browser session Cookie header if Studio synthesize requires login auth.
    SARVAM_STUDIO_COOKIE: str = ""
    SARVAM_TTS_MODEL: str = "bulbul:v3"
    SARVAM_TTS_CODEC: str = "mp3"  # mp3 | wav (Twilio <Play> supports both)
    SARVAM_TTS_SAMPLE_RATE: int = 16000  # telephony-friendly
    SARVAM_TTS_PACE: float = 1.0
    SARVAM_TTS_TIMEOUT_SECONDS: float = 30.0
    SARVAM_TTS_CACHE_DIR: str = "app/uploads/voice-cache"
    SARVAM_CLONE_MAX_CHARS: int = 1000  # Studio: cloned voices support up to 1000 chars/line

    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""
    TWILIO_WHATSAPP_NUMBER: str = ""
    TWILIO_TEST_TO_NUMBER: str = Field(
        default="",
        validation_alias=AliasChoices("TWILIO_TEST_TO_NUMBER", "TWILIO_TO_NUMBER"),
    )

    # Exotel (India-primary telephony). Per-hospital overrides live in HospitalVoiceConfig.
    EXOTEL_SID: str = ""
    EXOTEL_API_KEY: str = ""
    EXOTEL_API_TOKEN: str = ""
    EXOTEL_SUBDOMAIN: str = "api.exotel.com"
    EXOTEL_PHONE_NUMBER: str = ""
    EXOTEL_WEBHOOK_SECRET: str = ""
    DEFAULT_TELEPHONY_PROVIDER: str = "twilio"
    # When true, skip Twilio/Exotel signature checks (local tests only).
    SKIP_VOICE_WEBHOOK_AUTH: bool = False


    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""

    CHAT_SESSION_TTL_SECONDS: int = 3600
    ANALYTICS_CACHE_TTL_SECONDS: int = 300
    LAB_PENDING_TEST_THRESHOLD_HOURS: int = 24
    DOCTOR_APPOINTMENT_REMINDER_MINUTES: int = 30
    MEDICATION_REMINDER_MINUTES: int = 15
    CHAT_RATE_LIMIT_PER_MINUTE: int = 30
    VOICE_CONFIG_CACHE_TTL_SECONDS: int = 600
    VOICE_FAQ_CACHE_TTL_SECONDS: int = 600
    VOICE_AI_CONFIDENCE_THRESHOLD: float = 0.65
    # Phase 6: multi-turn FAQ, FAQ↔Booking switching, goodbye flow (default OFF)
    VOICE_PHASE6_ENABLED: bool = True

    # Public URL for Twilio/Exotel webhooks (use ngrok in local dev)
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    # Hospital info surfaced in FAQ / chatbot prompts
    HOSPITAL_NAME: str = "NesaCare Hospital"
    HOSPITAL_HOURS: str = "Mon-Sat 8:00 AM - 8:00 PM"
    HOSPITAL_LOCATION: str = "123 Healthcare Avenue"
    HOSPITAL_CONTACT: str = "+1-800-NESACARE"

    # Voice reminders: schedule calls this many hours before appointment
    VOICE_REMINDER_HOURS_BEFORE: int = 24

    UPLOAD_DIR: str = "app/uploads"
    MAX_UPLOAD_SIZE_MB: int = 10

    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "https://nexacaresuperadmin.netlify.app",
        "https://nexacare360.netlify.app",
    ]

    OTP_EXPIRE_MINUTES: int = 10
    # Dev helper: if set, this OTP always works in non-production envs.
    STATIC_OTP_CODE: str = "123456"

    # Create a default Super Admin on startup if that email is not registered yet.
    # Override SEED_SUPER_ADMIN_PASSWORD in production.
    SEED_SUPER_ADMIN: bool = True
    SEED_SUPER_ADMIN_EMAIL: str = "admin@nesacare1234.com"
    SEED_SUPER_ADMIN_PASSWORD: str = "admin@1234"
    # When true, always re-hash bootstrap admin password from SEED_SUPER_ADMIN_PASSWORD on startup
    # (use once to fix a bad row, or in dev). Ignored when APP_ENV is production unless you set this.
    SEED_SUPER_ADMIN_RESYNC_PASSWORD: bool = False

    # Allow Super Admin / Hospital Admin via POST /auth/register (disable in production).
    ALLOW_ADMIN_SELF_REGISTER: bool = True

    # ICU telemetry ingestion limits
    ICU_TELEMETRY_ECG_MAX_SAMPLES: int = 1000
    ICU_TELEMETRY_HISTORY_DEFAULT_HOURS: int = 24
    ICU_TELEMETRY_HISTORY_MAX_DAYS: int = 7


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()