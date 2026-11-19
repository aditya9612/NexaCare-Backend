"""
Verification script for Environment-based OTP, PIN, and SMTP configuration in NexaCare Backend.
Tests all requirements across Testing, Production, and Development environments.
"""

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unittest.mock import patch, MagicMock
from app.core.config import Settings
from app.core.security import verify_pin, hash_pin
from app.utils.otp_handler import (
    _otp_store,
    generate_otp,
    store_otp_sync,
    verify_otp_sync,
)
from app.utils.email_sender import _send_sync_email
from app.services.auth_service import validate_non_trivial_pin
from app.core.exceptions import BadRequestException
from app.core.production_checks import validate_production_settings


def test_configuration_loading():
    print("Testing 1: Configuration Loading & Environment Resolution...")
    # Test default
    s_dev = Settings(ENVIRONMENT="development")
    assert s_dev.ENVIRONMENT == "development"
    assert s_dev.APP_ENV == "development"
    assert s_dev.is_development is True
    assert s_dev.is_testing is False
    assert s_dev.is_production is False

    # Test testing
    s_test = Settings(ENVIRONMENT="testing", TESTING_OTP="123456", TESTING_PIN="1234", ENABLE_EMAIL_OTP=False)
    assert s_test.is_testing is True
    assert s_test.TESTING_OTP == "123456"
    assert s_test.TESTING_PIN == "1234"
    assert s_test.ENABLE_EMAIL_OTP is False

    # Test production
    s_prod = Settings(ENVIRONMENT="production")
    assert s_prod.is_production is True
    assert s_prod.is_testing is False

    # Test backward compatibility aliases
    s_alias = Settings(SMTP_USER="legacy@hospital.com", SMTP_FROM="from@hospital.com")
    assert s_alias.SMTP_USERNAME == "legacy@hospital.com"
    assert s_alias.SMTP_USER == "legacy@hospital.com"
    assert s_alias.SMTP_FROM_EMAIL == "from@hospital.com"
    assert s_alias.SMTP_FROM == "from@hospital.com"
    print("  -> PASSED: Configuration & aliases correctly loaded.")


def test_testing_environment():
    print("Testing 2: Testing Environment (Fixed OTP, Fixed PIN, Skip SMTP, Single-use)...")
    test_settings = Settings(
        ENVIRONMENT="testing",
        TESTING_OTP="123456",
        TESTING_PIN="1234",
        ENABLE_EMAIL_OTP=False,
    )

    with patch("app.utils.otp_handler.settings", test_settings), \
         patch("app.core.security.settings", test_settings), \
         patch("app.services.auth_service.settings", test_settings), \
         patch("app.utils.email_sender.settings", test_settings):

        # A. Fixed OTP Generation
        otp = generate_otp()
        assert otp == "123456", f"Expected fixed OTP '123456', got {otp}"

        # B. Skip SMTP delivery when ENABLE_EMAIL_OTP is False
        email_sent = _send_sync_email("test@example.com", "Subject", "<h1>Test</h1>")
        assert email_sent is True, "Expected _send_sync_email to return True when ENABLE_EMAIL_OTP=False in testing"

        # C. Store and verify fixed OTP with single-use consumption
        _otp_store.clear()
        store_otp_sync(email="patient@test.com", otp=otp, expiry_minutes=10, purpose="login")
        assert verify_otp_sync(email="patient@test.com", otp="123456", purpose="login") is True
        # Second attempt must fail (single-use)
        assert verify_otp_sync(email="patient@test.com", otp="123456", purpose="login") is False

        # D. Testing PIN verification
        dummy_hash = hash_pin("9999")
        assert verify_pin("1234", dummy_hash) is True, "Expected TESTING_PIN '1234' to verify in testing"
        assert verify_pin("0000", dummy_hash) is False

        # E. validate_non_trivial_pin permits TESTING_PIN in testing
        validate_non_trivial_pin("1234")  # Should not raise exception
    print("  -> PASSED: Testing environment behavior verified.")


def test_production_environment():
    print("Testing 3: Production Environment (Random OTP, Never accept testing OTP/PIN, SMTP validation)...")
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
         patch("app.core.security.settings", prod_settings), \
         patch("app.services.auth_service.settings", prod_settings), \
         patch("app.core.production_checks.settings", prod_settings):

        # A. Secure Random OTP generation - must never generate TESTING_OTP
        otps = {generate_otp() for _ in range(100)}
        assert len(otps) > 1, "Expected high entropy random OTPs"
        assert "123456" not in otps, "Production must never generate TESTING_OTP"

        # B. Production strictly rejects TESTING_OTP even if stored
        _otp_store.clear()
        store_otp_sync(email="victim@hospital.com", otp="123456", expiry_minutes=10, purpose="login")
        assert verify_otp_sync(email="victim@hospital.com", otp="123456", purpose="login") is False, \
            "Production must strictly reject TESTING_OTP"

        # C. Real OTP is verified and single-use consumed
        real_otp = generate_otp()
        store_otp_sync(email="doctor@hospital.com", otp=real_otp, expiry_minutes=10, purpose="login")
        assert verify_otp_sync(email="doctor@hospital.com", otp=real_otp, purpose="login") is True
        assert verify_otp_sync(email="doctor@hospital.com", otp=real_otp, purpose="login") is False

        # D. Testing PIN is rejected in production
        real_user_pin_hash = hash_pin("8391")
        assert verify_pin("1234", real_user_pin_hash) is False, "Production must reject TESTING_PIN"
        assert verify_pin("8391", real_user_pin_hash) is True

        # E. validate_non_trivial_pin strictly rejects trivial '1234' in production
        try:
            validate_non_trivial_pin("1234")
            assert False, "Production should reject consecutive sequence '1234'"
        except BadRequestException:
            pass

        # F. Production configuration passes with valid SMTP
        validate_production_settings()
    print("  -> PASSED: Production environment security strictly enforced.")


def test_production_missing_smtp_rejected():
    print("Testing 4: Production Fail-Safe (Missing SMTP with ENABLE_EMAIL_OTP=True)...")
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
        try:
            validate_production_settings()
            assert False, "Production should raise RuntimeError when SMTP is missing and ENABLE_EMAIL_OTP is True"
        except RuntimeError as exc:
            assert "SMTP configuration" in str(exc)
            print("  -> PASSED: Missing SMTP correctly triggers RuntimeError at startup.")


def test_development_environment():
    print("Testing 5: Development Environment (Random OTP, Skip SMTP when ENABLE_EMAIL_OTP=False)...")
    dev_settings = Settings(
        ENVIRONMENT="development",
        DEBUG=True,
        ENABLE_EMAIL_OTP=False,
    )

    with patch("app.utils.otp_handler.settings", dev_settings), \
         patch("app.utils.email_sender.settings", dev_settings):

        otp = generate_otp()
        assert len(otp) == 6 and otp.isdigit()

        # Skips SMTP when ENABLE_EMAIL_OTP is False in development
        email_sent = _send_sync_email("dev@example.com", "Subject", "<h1>Test</h1>")
        assert email_sent is True

        # Dev direct OTP: in development with DEBUG=True, TESTING_OTP ("123456") is directly accepted without calling send-otp!
        _otp_store.clear()
        assert verify_otp_sync(email="direct@hospital.com", otp="123456", purpose="login") is True
    print("  -> PASSED: Development environment behavior (including direct dev OTP login) verified.")


if __name__ == "__main__":
    test_configuration_loading()
    test_testing_environment()
    test_production_environment()
    test_production_missing_smtp_rejected()
    test_development_environment()
    print("\n=======================================================")
    print("ALL ENVIRONMENT-BASED OTP, PIN, AND SMTP CHECKS PASSED!")
    print("=======================================================")
