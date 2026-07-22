from app.core.config import settings
from app.core.constants import TelephonyProviderType
from app.telephony.base import TelephonyProvider
from app.telephony.exotel_provider import ExotelProvider
from app.telephony.twilio_provider import TwilioProvider
from app.utils.credential_crypto import decrypt_secret


class ProviderFactory:
    """Factory for hospital-scoped telephony providers."""

    @classmethod
    def create(
        cls,
        provider_name: str | None = None,
        *,
        from_number: str | None = None,
        exotel_sid: str | None = None,
        exotel_api_key: str | None = None,
        exotel_api_token: str | None = None,
        exotel_subdomain: str | None = None,
    ) -> TelephonyProvider:
        name = (
            provider_name or settings.DEFAULT_TELEPHONY_PROVIDER or TelephonyProviderType.TWILIO
        ).lower()
        if name == TelephonyProviderType.EXOTEL:
            return ExotelProvider(
                sid=exotel_sid,
                api_key=decrypt_secret(exotel_api_key) if exotel_api_key else None,
                api_token=decrypt_secret(exotel_api_token) if exotel_api_token else None,
                subdomain=exotel_subdomain,
                from_number=from_number,
            )
        return TwilioProvider(from_number=from_number)

    @classmethod
    def from_hospital_config(cls, config=None) -> TelephonyProvider:
        if config is None:
            return cls.create()
        return cls.create(
            getattr(config, "telephony_provider", None),
            from_number=getattr(config, "from_number", None) or None,
            exotel_sid=getattr(config, "exotel_sid", None) or None,
            exotel_api_key=getattr(config, "exotel_api_key", None) or None,
            exotel_api_token=getattr(config, "exotel_api_token", None) or None,
            exotel_subdomain=getattr(config, "exotel_subdomain", None) or None,
        )

    @classmethod
    def get_default(cls) -> TelephonyProvider:
        return cls.create(settings.DEFAULT_TELEPHONY_PROVIDER)
