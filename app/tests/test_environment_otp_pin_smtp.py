import asyncio
import os
import pytest
from unittest.mock import patch, AsyncMock

from app.core.config import Settings
from app.core.security import verify_pin, hash_pin
from app.utils.otp_handler import (
    _otp_store,
    generate_otp,
    store_otp,
    verify_otp,
    store_otp_sync,
    verify_otp_sync,
)
from app.utils.otp_delivery import deliver_otp
from app.services.auth_service import validate_non_trivial_pin
from app.core.exceptions import BadRequestException
from app.core.production_checks import validate_production_settings


@pytest.fixture(autouse=True)
def clean_otp_store():
    _otp_store.clear()
    yield
    _otp_store.clear()


@pytest.mark.asyncio
async def test_testing_environment_otp_and_pin():
    """Verify testing environment uses fixed OTP and PIN, skips SMTP when ENABLE_EMAIL_OTP=False, and enforces single use."""
    testing_settings = Settings(
        ENVIRONMENT="testing",
        TESTING_OTP="123456",
        TESTING_PIN="1234",
        ENABLE_EMAIL_OTP=False,
    )

    with patch("app.utils.otp_handler.settings", testing_settings), \
         patch("app.utils.otp_delivery.settings", testing_settings), \
         patch("app.core.security.settings", testing_settings), \
         patch("app.services.auth_service.settings", testing_settings), \
         patch("app.utils.otp_handler.get_redis", AsyncMock(return_value=None)), \
         patch("app.utils.redis_service.get_redis", AsyncMock(return_value=None)):

        assert testing_settings.is_testing is True
        assert testing_settings.is_production is False

        # 1. Fixed OTP Generation
        otp = generate_otp()
        assert otp == "123456"

        # 2. Skip SMTP delivery cleanly
        res = await deliver_otp(email="patient@test.com", phone="+919876543210", otp=otp, purpose="login")
        assert res["email_sent"] is True
        assert res["sms_sent"] is True

        # 3. Store and Verify fixed OTP
        await store_otp(email="patient@test.com", otp=otp, expiry_minutes=10, purpose="login")

        # First verification succeeds
        assert await verify_otp(email="patient@test.com", otp="123456", purpose="login") is True

        # Single-use: Second verification fails
        assert await verify_otp(email="patient@test.com", otp="123456", purpose="login") is False

        # 4. Testing PIN verification
        # Hash a dummy PIN, but in testing TESTING_PIN ("1234") must be accepted
        dummy_hash = hash_pin("9876")
        assert verify_pin("1234", dummy_hash) is True
        assert verify_pin("0000", dummy_hash) is False

        # 5. Non-trivial PIN validation permits TESTING_PIN in testing
        validate_non_trivial_pin("1234")  # Should not raise


@pytest.mark.asyncio
async def test_production_environment_security():
    """Verify production environment generates secure random OTP, rejects testing OTP/PIN, and validates SMTP."""
    prod_settings = Settings(
        ENVIRONMENT="production",
        APP_ENV="production",
        DEBUG=False,
        TESTING_OTP="123456",
        TESTING_PIN="1234",
        ENABLE_EMAIL_OTP=True,
        SMTP_HOST="smtp.gmail.com",
        SMTP_USERNAME="prod@hospital.com",
        SMTP_PASSWORD="validpassword123",
        SMTP_FROM_EMAIL="prod@hospital.com",
        SECRET_KEY="a" * 32,
        PUBLIC_BASE_URL="https://api.hospital.com",
        DATABASE_URL="mysql+aiomysql://user:pass@localhost/db",
        ALLOW_ADMIN_SELF_REGISTER=False,
        DEFAULT_TELEPHONY_PROVIDER="twilio",
        TWILIO_ACCOUNT_SID="AC123",
        TWILIO_AUTH_TOKEN="token123",
        TWILIO_PHONE_NUMBER="+1234567890",
    )

    with patch("app.utils.otp_handler.settings", prod_settings), \
         patch("app.utils.otp_delivery.settings", prod_settings), \
         patch("app.core.security.settings", prod_settings), \
         patch("app.core.production_checks.settings", prod_settings), \
         patch("app.utils.otp_handler.get_redis", AsyncMock(return_value=None)), \
         patch("app.utils.redis_service.get_redis", AsyncMock(return_value=None)):

        assert prod_settings.is_production is True
        assert prod_settings.is_testing is False

        # 1. OTP generation must be 6 digits and never equal TESTING_OTP
        generated_otps = {generate_otp() for _ in range(50)}
        assert len(generated_otps) > 1  # Dynamic random codes
        assert "123456" not in generated_otps

        # 2. Production strictly rejects TESTING_OTP even if stored
        store_otp_sync(email="victim@hospital.com", otp="123456", expiry_minutes=10, purpose="login")
        assert await verify_otp(email="victim@hospital.com", otp="123456", purpose="login") is False
        assert verify_otp_sync(email="victim@hospital.com", otp="123456", purpose="login") is False

        # 3. Legitimate random OTP works in production
        real_otp = generate_otp()
        await store_otp(email="user@hospital.com", otp=real_otp, expiry_minutes=10, purpose="login")
        assert await verify_otp(email="user@hospital.com", otp=real_otp, purpose="login") is True
        assert await verify_otp(email="user@hospital.com", otp=real_otp, purpose="login") is False

        # 4. Production strictly rejects TESTING_PIN if it doesn't match hash
        user_pin_hash = hash_pin("8391")
        assert verify_pin("1234", user_pin_hash) is False
        assert verify_pin("8391", user_pin_hash) is True

        # 5. Production configuration checks pass with valid SMTP
        validate_production_settings()


def test_production_missing_smtp_fails_safely():
    """Verify production rejects startup if ENABLE_EMAIL_OTP is True but SMTP is missing."""
    invalid_prod = Settings(
        ENVIRONMENT="production",
        APP_ENV="production",
        DEBUG=False,
        ENABLE_EMAIL_OTP=True,
        SMTP_HOST="",  # Missing SMTP Host!
        SMTP_USERNAME="",
        SMTP_PASSWORD="",
        SECRET_KEY="b" * 32,
        PUBLIC_BASE_URL="https://api.hospital.com",
        DATABASE_URL="mysql+aiomysql://user:pass@localhost/db",
        ALLOW_ADMIN_SELF_REGISTER=False,
    )

    with patch("app.core.production_checks.settings", invalid_prod):
        with pytest.raises(RuntimeError, match="SMTP configuration"):
            validate_production_settings()


@pytest.mark.asyncio
async def test_development_environment_behavior():
    """Verify development environment allows dynamic OTP with SMTP skipped when ENABLE_EMAIL_OTP=False."""
    dev_settings = Settings(
        ENVIRONMENT="development",
        DEBUG=True,
        ENABLE_EMAIL_OTP=False,
    )

    with patch("app.utils.otp_handler.settings", dev_settings), \
         patch("app.utils.otp_delivery.settings", dev_settings):

        assert dev_settings.is_development is True

        otp = generate_otp()
        assert len(otp) == 6

        # Skip SMTP delivery when disabled in dev
        res = await deliver_otp(email="dev@example.com", phone="+919876543210", otp=otp, purpose="login")
        assert res["email_sent"] is True
