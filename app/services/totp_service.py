import pyotp
import bcrypt
import secrets

from app.core.security import encrypt_totp_secret, decrypt_totp_secret

class TOTPService:
    @staticmethod
    def generate_secret() -> str:
        """Generate a new base32 secret for TOTP."""
        return pyotp.random_base32()

    @staticmethod
    def generate_provisioning_uri(secret: str, email: str, issuer_name: str = "NexaCare") -> str:
        """Generate the otpauth URI for QR code generation."""
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=email, issuer_name=issuer_name)

    @staticmethod
    def verify_totp(secret: str, code: str, valid_window: int = 1) -> bool:
        """Verify a TOTP code against a secret with a small clock drift allowance."""
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=valid_window)

    @staticmethod
    def encrypt_secret(secret: str) -> str:
        """Encrypt the TOTP secret for storage."""
        return encrypt_totp_secret(secret)

    @staticmethod
    def decrypt_secret(encrypted_secret: str) -> str:
        """Decrypt the stored TOTP secret."""
        return decrypt_totp_secret(encrypted_secret)

    @staticmethod
    def generate_recovery_codes(count: int = 10, length: int = 10) -> list[str]:
        """Generate a list of random recovery codes."""
        return [secrets.token_hex(length // 2) for _ in range(count)]

    @staticmethod
    def hash_recovery_code(code: str) -> str:
        """Hash a recovery code using bcrypt."""
        return bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def verify_recovery_code(code: str, hashed_code: str) -> bool:
        """Verify a plain recovery code against a stored hash."""
        try:
            return bcrypt.checkpw(code.encode("utf-8"), hashed_code.encode("utf-8"))
        except (ValueError, TypeError):
            return False
