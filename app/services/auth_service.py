import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import UserRole
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    LockedException,
    NotFoundException,
    ServiceUnavailableException,
    UnauthorizedException,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_2fa_challenge_token,
    create_login_otp_challenge_token,
    create_pin_setup_token,
    decode_token,
    get_password_hash,
    hash_pin,
    verify_password,
    verify_pin,
)
from app.models.refresh_token_model import RefreshToken
from app.models.user_model import User
from app.models.department_model import Department
from app.models.user_security_settings import UserSecuritySettings
from app.repositories.audit_repository import AuditRepository
from app.repositories.auth_repository import AuthRepository
from app.repositories.rbac_repository import RBACRepository
from app.schemas.auth_schema import (
    ActivateAccountRequest,
    ChangePasswordRequest,
    ChangePINRequest,
    ForgotPasswordRequest,
    ForgotPINRequest,
    LoginContext,
    LoginOTPChallengeResponse,
    LoginOTPVerifyRequest,
    LoginRequest,
    OTPVerifyRequest,
    OTPVerifyResponse,
    ProfileUpdateRequest,
    RegisterRequest,
    RegistrationRoleOption,
    ResetPasswordRequest,
    ResetPINRequest,
    SendOTPRequest,
    SendOTPResponse,
    SetPINRequest,
    TokenResponse,
    UserProfileResponse,
    TOTPSetupResponse,
    TOTPEnableRequest,
    TwoFAChallengeResponse,
    TOTPLoginRequest,
    Disable2FARequest,
)
from app.schemas.common_schema import MessageResponse
from app.utils.helpers import generate_user_code, mask_email, utc_now
from app.utils.otp_delivery import deliver_otp
from app.utils.otp_handler import generate_otp, store_otp, verify_otp
from app.utils.redis_service import cache_delete, cache_get, cache_set
from app.services.totp_service import TOTPService


_IN_MEMORY_CHALLENGE_JTI: dict[str, float] = {}
_CHALLENGE_JTI_LOCK = asyncio.Lock()


async def store_challenge_jti(jti: str, ttl: int = 300) -> None:
    stored = await cache_set(f"login_otp_jti:{jti}", "valid", ttl=ttl)
    if not stored:
        async with _CHALLENGE_JTI_LOCK:
            _IN_MEMORY_CHALLENGE_JTI[jti] = time.monotonic() + ttl


async def consume_challenge_jti(jti: str) -> bool:
    from app.utils.redis_service import get_redis
    client = await get_redis()
    if client:
        try:
            res = await client.delete(f"login_otp_jti:{jti}")
            if res > 0:
                return True
        except Exception:
            pass
    async with _CHALLENGE_JTI_LOCK:
        now = time.monotonic()
        expiry = _IN_MEMORY_CHALLENGE_JTI.get(jti)
        if expiry and expiry > now:
            del _IN_MEMORY_CHALLENGE_JTI[jti]
            return True
        if jti in _IN_MEMORY_CHALLENGE_JTI:
            del _IN_MEMORY_CHALLENGE_JTI[jti]
        return False


def validate_non_trivial_pin(pin: str) -> None:
    if len(set(pin)) == 1:
        raise BadRequestException("PIN cannot consist of identical digits (e.g., 0000 or 1111)")
    sequences = {
        "0123", "1234", "2345", "3456", "4567", "5678", "6789",
        "9876", "8765", "7654", "6543", "5432", "4321", "3210",
        "012345", "123456", "234567", "345678", "456789",
        "987654", "876543", "765432", "654321", "543210"
    }
    if pin in sequences:
        raise BadRequestException("PIN cannot be a simple consecutive sequence (e.g., 1234 or 123456)")


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AuthRepository(db)
        self.rbac_repo = RBACRepository(db)
        self.audit_repo = AuditRepository(db)

    async def _get_user_by_identifier(
        self, email: str | None = None, phone: str | None = None
    ) -> User | None:
        if email:
            return await self.repo.get_by_email(email)
        if phone:
            return await self.repo.get_by_phone(phone)
        return None

    async def _issue_and_deliver_otp(self, user: User, purpose: str) -> str:
        from app.core.logger import logger
        otp = generate_otp()
        await store_otp(user.email, otp, settings.OTP_EXPIRE_MINUTES, phone=user.phone, purpose=purpose)
        delivery_res = await deliver_otp(email=user.email, phone=user.phone, otp=otp, purpose=purpose)
        email_sent = delivery_res.get("email_sent", False)
        sms_sent = delivery_res.get("sms_sent", False)

        if settings.DEBUG:
            logger.info(
                "[DEV MODE] Generated OTP for user %s (%s): %s (email_sent=%s, sms_sent=%s)",
                user.email,
                user.phone,
                otp,
                email_sent,
                sms_sent,
            )
            return otp

        if not email_sent and not sms_sent:
            raise ServiceUnavailableException(
                "Failed to deliver OTP to your registered email or phone. Please check configuration or try again later."
            )
        return otp

    async def _resolve_register_role_id(self, data: RegisterRequest) -> int:
        role_name = data.role_name.value
        if data.role_id:
            role = await self.rbac_repo.get_role_by_id(data.role_id)
            if not role:
                raise BadRequestException(f"role_id {data.role_id} does not exist")
            if role.name != role_name:
                raise BadRequestException(
                    f"role_id {data.role_id} is '{role.name}', but role_name is '{role_name}'. "
                    "Use only role_name, or ensure both match."
                )
            return role.id

        role = await self.rbac_repo.get_role_by_name(role_name)
        if not role:
            raise BadRequestException(f"Role '{role_name}' not found. Run database seed.")
        return role.id

    async def list_registration_roles(self) -> list[RegistrationRoleOption]:
        allow_admin = settings.ALLOW_ADMIN_SELF_REGISTER
        roles = await self.rbac_repo.list_roles()
        return [
            RegistrationRoleOption(
                id=role.id,
                name=role.name,
                description=role.description,
                allowed_for_registration=(
                    allow_admin or role.name not in UserRole.ADMIN_ROLES
                ),
            )
            for role in roles
        ]

    async def register(self, data: RegisterRequest) -> User:
        if (
            data.role_name.value in UserRole.ADMIN_ROLES
            and not settings.ALLOW_ADMIN_SELF_REGISTER
        ):
            raise BadRequestException(
                "Super Admin and Hospital Admin cannot be created via public register. "
                "Set ALLOW_ADMIN_SELF_REGISTER=true in .env for development, or use SEED_SUPER_ADMIN."
            )
        email_norm = data.email.strip().lower()
        if await self.repo.get_by_email(email_norm):
            raise BadRequestException("Email already registered")
        if data.phone and await self.repo.get_by_phone(data.phone):
            raise BadRequestException("Phone number already registered")

        role_id = await self._resolve_register_role_id(data)

        user = User(
            user_code=generate_user_code(),
            email=email_norm,
            hashed_password=get_password_hash(data.password),
            full_name=data.full_name,
            phone=data.phone,
            role_id=role_id,
            gender=data.gender,
            date_of_birth=data.date_of_birth,
            address=data.address,
            profile_image=data.profile_image,
            is_active=False,
            is_verified=False,
        )
        try:
            user = await self.repo.create(user)
            # Fetch user with role name loaded
            user = await self.repo.get_by_id(user.id)
            if user and user.role and user.role.name in {
                UserRole.RECEPTIONIST,
                UserRole.ACCOUNTANT,
                UserRole.PHARMACIST,
                UserRole.LAB_TECHNICIAN,
            }:
                from app.models.staff_model import Staff
                from app.utils.helpers import generate_staff_code

                department = await self.db.scalar(
                    select(Department).order_by(Department.department_id.asc())
                )

                if not department:
                    raise BadRequestException(
                        "No department found. Please create a department before registering staff."
    )

                staff = Staff(
                    full_name=user.full_name,
                    email=user.email,
                    phone=user.phone,
                    staff_code=generate_staff_code(),
                    department_id=department.department_id,
                    role_name=user.role.name,
                    status=1,
                )
                self.db.add(staff)
                await self.db.flush()

            await self.audit_repo.create("register", "users", user_id=user.id, resource_id=str(user.id))
        except IntegrityError as exc:
            raise ConflictException("Email or phone already registered") from exc

        return user

    async def _is_user_deleted(self, user: User) -> bool:
        from app.models.doctor_model import Doctor
        from app.models.nurse_model import Nurse
        from app.models.patient_model import Patient
        from app.models.staff_model import Staff
        from sqlalchemy import select

        if user.role.name == UserRole.DOCTOR:
            doctor = await self.db.scalar(select(Doctor).where(Doctor.user_id == user.id))
            return doctor is None or doctor.is_deleted
        elif user.role.name == UserRole.NURSE:
            return False
        elif user.role.name == UserRole.PATIENT:
            patient = await self.db.scalar(select(Patient).where(Patient.user_id == user.id))
            if patient is None:
                from app.utils.phone_utils import indian_mobile_last10
                from sqlalchemy import or_, func

                patient_conditions = []
                if user.phone:
                    patient_conditions.append(Patient.phone == user.phone)
                    last10 = indian_mobile_last10(user.phone)
                    if last10 and len(last10) == 10:
                        patient_conditions.append(Patient.phone.like(f"%{last10}%"))
                if user.email:
                    patient_conditions.append(func.lower(Patient.email) == user.email.strip().lower())

                if patient_conditions:
                    existing_patient = await self.db.scalar(
                        select(Patient).where(
                            Patient.is_deleted.is_(False),
                            or_(*patient_conditions)
                        ).order_by(Patient.id.asc()).limit(1)
                    )
                    if existing_patient:
                        existing_patient.user_id = user.id
                        patient = existing_patient
                        await self.db.flush()

                if patient is None:
                    from app.utils.helpers import generate_mrn
                    parts = (user.full_name or "Patient User").split(maxsplit=1)
                    first_name = parts[0]
                    last_name = parts[1] if len(parts) > 1 else "User"

                    patient = Patient(
                        patient_code=generate_mrn(),
                        user_id=user.id,
                        first_name=first_name,
                        last_name=last_name,
                        phone=user.phone,
                        email=user.email,
                        status="active",
                    )
                    self.db.add(patient)
                    await self.db.flush()
            return patient.is_deleted
        elif user.role.name in {
            UserRole.RECEPTIONIST,
            UserRole.ACCOUNTANT,
            UserRole.PHARMACIST,
            UserRole.LAB_TECHNICIAN,
        }:
            from app.schemas.staff_schema import StaffStatus
            staff = await self.db.scalar(select(Staff).where(Staff.email == user.email))
            return staff is None or staff.is_deleted or staff.status == StaffStatus.INACTIVE.value
        return False

    async def _find_patient_by_identifier(
        self, email: str | None = None, phone: str | None = None
    ):
        from app.models.patient_model import Patient
        from app.utils.phone_utils import indian_mobile_last10
        from sqlalchemy import or_, func, select

        conditions = []
        if phone:
            conditions.append(Patient.phone == phone)
            last10 = indian_mobile_last10(phone)
            if last10 and len(last10) == 10:
                conditions.append(Patient.phone.like(f"%{last10}%"))
        if email:
            conditions.append(func.lower(Patient.email) == email.strip().lower())

        if not conditions:
            return None

        return await self.db.scalar(
            select(Patient).where(
                Patient.is_deleted.is_(False),
                or_(*conditions)
            ).order_by(Patient.guardian_patient_id.is_(None).desc(), Patient.id.asc()).limit(1)
        )

    async def _create_or_link_patient_user(self, patient) -> User:
        from app.models.role_model import Role
        from app.utils.helpers import generate_user_code
        from app.core.constants import UserRole
        from app.core.security import get_password_hash
        import secrets
        from sqlalchemy import select

        if patient.user_id:
            user = await self.repo.get_by_id(patient.user_id)
            if user:
                return user

        patient_role = await self.db.scalar(select(Role).where(Role.name == UserRole.PATIENT))
        role_id = patient_role.id if patient_role else 2

        full_name = f"{patient.first_name} {patient.last_name}".strip() or "Patient"
        email_val = patient.email or f"patient_{patient.patient_code.lower().replace('-', '_')}@nexacare.local"
        phone_val = patient.phone

        user = User(
            user_code=generate_user_code(),
            email=email_val,
            phone=phone_val,
            hashed_password=get_password_hash(secrets.token_urlsafe(16)),
            full_name=full_name,
            role_id=role_id,
            gender=patient.gender,
            date_of_birth=patient.dob,
            address=patient.address,
            is_active=True,
            is_verified=True,
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)

        patient.user_id = user.id
        await self.db.flush()
        return user

    async def send_otp(self, data: SendOTPRequest) -> SendOTPResponse:
        user = await self._get_user_by_identifier(data.email, data.phone)
        if not user or await self._is_user_deleted(user):
            if data.phone or data.email:
                patient_match = await self._find_patient_by_identifier(data.email, data.phone)
                if patient_match:
                    user = await self._create_or_link_patient_user(patient_match)
            if not user or await self._is_user_deleted(user):
                raise NotFoundException("User not found")

        # Do not send OTPs to placeholder addresses such as @nexacare.local
        if not user.email or user.email.lower().endswith("@nexacare.local") or ".local" in user.email.lower():
            raise BadRequestException("No valid email address registered for this account. Please contact hospital support.")

        purpose = "account activation" if not user.is_verified else "login"
        await self._issue_and_deliver_otp(user, purpose)
        masked = mask_email(user.email)
        return SendOTPResponse(
            message=f"OTP sent to your registered email {masked}",
            masked_email=masked,
        )

    def _validate_login_context(self, user: User, login_type_attr: Any) -> None:
        if login_type_attr is None:
            return

        context_val = (
            login_type_attr.value
            if isinstance(login_type_attr, LoginContext)
            else str(login_type_attr).strip().upper()
        )
        if not context_val:
            raise BadRequestException("login_type cannot be blank. Allowed values: SUPER_ADMIN, ORGANIZATION, PATIENT")

        actual_role = user.role.name if user.role else None
        if not actual_role:
            raise ForbiddenException("Account has no role assigned")

        if context_val == LoginContext.SUPER_ADMIN.value:
            if actual_role != UserRole.SUPER_ADMIN:
                raise ForbiddenException("Access denied: Super Admin portal only accepts Super Admin accounts")
        elif context_val == LoginContext.ORGANIZATION.value:
            organization_roles = {
                UserRole.HOSPITAL_ADMIN,
                UserRole.DOCTOR,
                UserRole.NURSE,
                UserRole.RECEPTIONIST,
                UserRole.ACCOUNTANT,
                UserRole.PHARMACIST,
                UserRole.LAB_TECHNICIAN,
            }
            if actual_role not in organization_roles:
                raise ForbiddenException(f"Access denied: Organization portal does not permit {actual_role} accounts")
        elif context_val == LoginContext.PATIENT.value:
            if actual_role != UserRole.PATIENT:
                raise ForbiddenException("Access denied: Patient portal only accepts Patient accounts")
        else:
            raise BadRequestException(f"Invalid login_type: {login_type_attr}")

    async def login(
        self,
        data: LoginRequest,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenResponse | TwoFAChallengeResponse | LoginOTPChallengeResponse:
        from app.services.security_service import SecurityService
        from app.core.logger import logger

        user = None
        try:
            user = await self._get_user_by_identifier(data.email, data.phone)
            if not user and data.otp and (data.phone or data.email):
                patient_match = await self._find_patient_by_identifier(data.email, data.phone)
                if patient_match:
                    user = await self._create_or_link_patient_user(patient_match)

            if not user:
                raise UnauthorizedException("Invalid credentials")

            if await self._is_user_deleted(user):
                raise UnauthorizedException("Account deactivated or deleted")

            # Validate Login Context before issuing OTP challenge or validating credentials
            self._validate_login_context(user, getattr(data, "login_type", None))

            # Block login if user has not completed OTP verification
            if not user.is_verified or not user.is_active:
                raise UnauthorizedException("Account not verified. Please verify OTP first before logging in.")

            # Method A: Mobile / Username + PIN Login
            if data.pin:
                if not user.hashed_pin:
                    raise BadRequestException("PIN is not configured for this account. Please log in with password or OTP.")

                now_utc = datetime.now(timezone.utc)
                if user.pin_locked_until:
                    locked_until = user.pin_locked_until
                    if locked_until.tzinfo is None:
                        locked_until = locked_until.replace(tzinfo=timezone.utc)
                    if locked_until > now_utc:
                        raise LockedException("PIN is temporarily locked due to too many failed attempts. Try again later or reset your PIN.")
                    else:
                        user.pin_locked_until = None
                        user.pin_failed_attempts = 0

                if not verify_pin(data.pin, user.hashed_pin):
                    user.pin_failed_attempts = (user.pin_failed_attempts or 0) + 1
                    if user.pin_failed_attempts >= 5:
                        user.pin_locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
                    await self.repo.update(user)
                    raise UnauthorizedException("Invalid PIN")

                user.pin_failed_attempts = 0
                user.pin_locked_until = None

            # Method OTP: Mobile + OTP Login
            elif data.otp:
                # Use registered user's email as canonical OTP identity with purpose="login"
                if not await verify_otp(email=user.email, otp=data.otp, phone=user.phone, purpose="login"):
                    raise UnauthorizedException("Invalid credentials")

            # Method B: Password Login
            elif data.password:
                if not verify_password(data.password, user.hashed_password):
                    raise UnauthorizedException("Invalid credentials")

                is_super_admin = bool(user.role and user.role.name == UserRole.SUPER_ADMIN)

                # If user has not configured a PIN or explicitly requested OTP: issue short-lived challenge
                # SUPER_ADMIN has full system access and directly logs in with password without OTP challenge
                if not is_super_admin and (not user.hashed_pin or data.require_otp):
                    if not user.is_active:
                        raise UnauthorizedException("Account not activated. Please verify OTP.")

                    if not user.email or user.email.lower().endswith("@nexacare.local") or ".local" in user.email.lower():
                        raise BadRequestException("No valid email address registered for this account. Please contact hospital support.")

                    await self._issue_and_deliver_otp(user, "password_login")
                    challenge_token, jti = create_login_otp_challenge_token(user.id, user.email, "password_login")
                    await store_challenge_jti(jti, ttl=300)
                    masked = mask_email(user.email)
                    return LoginOTPChallengeResponse(
                        challenge_token=challenge_token,
                        masked_email=masked,
                        message=f"OTP sent to your registered email {masked}",
                        require_otp=True,
                        is_pin_set=False,
                    )
            else:
                raise UnauthorizedException("Invalid credentials")

            if not user.is_active or not user.is_verified:
                raise UnauthorizedException("Account not verified. Please verify OTP first before logging in.")

            # 2FA intercept logic
            if settings.ENABLE_2FA_FEATURE:
                result = await self.db.execute(select(UserSecuritySettings).where(UserSecuritySettings.user_id == user.id))
                security_settings = result.scalar_one_or_none()
                if security_settings and security_settings.is_2fa_enabled:
                    challenge_token, jti = create_2fa_challenge_token(user.id)
                    await cache_set(f"2fa_jti:{jti}", "valid", ttl=300)

                    try:
                        await SecurityService(self.db).record_login(
                            user_id=user.id,
                            ip_address=ip_address,
                            user_agent=user_agent,
                            status="CHALLENGE",
                            details="2FA challenge issued",
                        )
                    except Exception as e:
                        logger.exception("Failed to record login history", exc_info=True)
                        try:
                            await self.db.rollback()
                        except Exception:
                            pass

                    return TwoFAChallengeResponse(challenge_token=challenge_token)

            user.last_login = utc_now()
            await self.repo.update(user)
            tokens = await self._issue_tokens(user)

            # Record successful login safely
            try:
                await SecurityService(self.db).record_login(
                    user_id=user.id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    status="SUCCESS",
                    details="Login successful",
                )
            except Exception as e:
                logger.exception("Failed to record login history", exc_info=True)
                try:
                    await self.db.rollback()
                except Exception:
                    pass

            return tokens

        except (UnauthorizedException, BadRequestException, LockedException, ForbiddenException) as exc:
            # Record failed login safely
            try:
                user_id = user.id if user else None
                await SecurityService(self.db).record_login(
                    user_id=user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    status="FAILED",
                    details=str(exc.detail),
                )
            except Exception as e:
                logger.exception("Failed to record failed login history", exc_info=True)
                try:
                    await self.db.rollback()
                except Exception:
                    pass
            raise exc
        except Exception as exc:
            logger.exception("Login failed with unexpected exception", exc_info=True)
            raise exc

    async def _issue_tokens(self, user: User) -> TokenResponse:
        role_name = user.role.name if user.role else None
        extra_claims = {
            "role": role_name,
            "role_id": user.role_id,
            "hospital_id": user.hospital_id,
        }
        access = create_access_token(user.id, extra_claims=extra_claims)
        refresh = create_refresh_token(user.id)
        expires_at = utc_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        await self.repo.save_refresh_token(
            RefreshToken(user_id=user.id, token=refresh, expires_at=expires_at)
        )
        user_profile = UserProfileResponse.model_validate(user)
        user_profile.role_name = role_name
        user_profile.role = role_name
        user_profile.hospital_id = user.hospital_id
        user_profile.is_pin_set = bool(user.hashed_pin)
        setup_token = None
        if not user.hashed_pin:
            setup_token, _ = create_pin_setup_token(user.id, user.email)
        return TokenResponse(
            access_token=access,
            refresh_token=refresh,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            role=role_name,
            is_pin_set=bool(user.hashed_pin),
            setup_token=setup_token,
            user=user_profile,
        )



    async def logout(self, refresh_token: str, user: User) -> None:
        try:
            payload = decode_token(refresh_token)
        except ValueError as exc:
            raise UnauthorizedException("Invalid refresh token") from exc

        if payload.get("type") != "refresh":
            raise UnauthorizedException("Invalid token type")

        stored = await self.repo.get_refresh_token(refresh_token)
        if not stored or stored.expires_at < utc_now():
            raise UnauthorizedException("Refresh token expired or revoked")

        if stored.user_id != user.id or int(payload.get("sub", 0)) != user.id:
            raise UnauthorizedException("Token does not belong to this user")

        await self.repo.revoke_refresh_token(stored)
        user.last_logout_at = utc_now()
        await self.repo.update(user)
        await self.audit_repo.create("logout", "auth", user_id=user.id)

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        try:
            payload = decode_token(refresh_token)
        except ValueError as exc:
            raise UnauthorizedException("Invalid refresh token") from exc

        if payload.get("type") != "refresh":
            raise UnauthorizedException("Invalid token type")

        stored = await self.repo.get_refresh_token(refresh_token)
        if not stored or stored.expires_at < utc_now():
            raise UnauthorizedException("Refresh token expired or revoked")

        user = await self.repo.get_by_id(int(payload["sub"]))
        if not user or not user.is_active or await self._is_user_deleted(user):
            raise UnauthorizedException("User not found or inactive")

        await self.repo.revoke_refresh_token(stored)
        return await self._issue_tokens(user)

    async def forgot_password(self, data: ForgotPasswordRequest) -> None:
        user = await self._get_user_by_identifier(data.email, data.phone)
        if not user or await self._is_user_deleted(user):
            raise NotFoundException("User not found")
        await self._issue_and_deliver_otp(user, "password reset")

    async def reset_password(self, data: ResetPasswordRequest) -> None:
        if not await verify_otp(email=data.email, otp=data.otp, phone=data.phone):
            raise BadRequestException("Invalid or expired OTP")
        user = await self._get_user_by_identifier(data.email, data.phone)
        if not user or await self._is_user_deleted(user):
            raise NotFoundException("User not found")
        if not user.is_active:
            raise BadRequestException("Account not activated")
        user.hashed_password = get_password_hash(data.new_password)
        user.last_logout_at = utc_now()
        await self.repo.update(user)
        await self.repo.revoke_all_user_tokens(user.id)

    async def change_password(self, user: User, data: ChangePasswordRequest) -> None:
        if not verify_password(data.current_password, user.hashed_password):
            raise BadRequestException("Current password is incorrect")
        user.hashed_password = get_password_hash(data.new_password)
        user.last_logout_at = utc_now()
        await self.repo.update(user)
        await self.repo.revoke_all_user_tokens(user.id)


    async def verify_otp_code(self, data: OTPVerifyRequest) -> OTPVerifyResponse:
        user = await self._get_user_by_identifier(data.email, data.phone)
        if not user:
            raise NotFoundException("User not found")
        if not await verify_otp(email=data.email, otp=data.otp, phone=data.phone):
            raise BadRequestException("Invalid or expired OTP")
        user.is_verified = True
        user.is_active = True
        await self.repo.update(user)
        setup_token, _ = create_pin_setup_token(user.id, user.email or user.phone or "")
        return OTPVerifyResponse(
            message="OTP verified successfully",
            setup_token=setup_token,
            is_active=True,
            is_verified=True,
        )

    async def activate_account(self, data: ActivateAccountRequest) -> OTPVerifyResponse:
        user = await self._get_user_by_identifier(data.email, data.phone)
        if not user:
            raise NotFoundException("User not found")
        if not user.is_verified:
            if not data.otp or not await verify_otp(email=data.email, otp=data.otp, phone=data.phone):
                raise BadRequestException("Invalid or expired OTP. Please verify OTP before activating your account.")
            user.is_verified = True
        user.is_active = True
        await self.repo.update(user)
        setup_token, _ = create_pin_setup_token(user.id, user.email or user.phone or "")
        return OTPVerifyResponse(
            message="Account activated successfully",
            setup_token=setup_token,
            is_active=True,
            is_verified=True,
        )


    async def get_profile(self, user: User) -> UserProfileResponse:
        role_name = user.role.name if user.role else None
        active_hosp = getattr(user, "active_hospital_id", None)
        hospital_id = active_hosp if active_hosp is not None else user.hospital_id
        return UserProfileResponse(
            id=user.id,
            user_code=user.user_code,
            full_name=user.full_name,
            email=user.email,
            phone=user.phone,
            role_id=user.role_id,
            role_name=role_name,
            role=role_name,
            hospital_id=hospital_id,
            profile_image=user.profile_image,
            gender=user.gender,
            date_of_birth=user.date_of_birth,
            address=user.address,
            is_active=user.is_active,
            is_verified=user.is_verified,
            last_login=user.last_login,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


    async def update_profile(self, user: User, data: ProfileUpdateRequest) -> UserProfileResponse:
        if data.email is not None and data.email != user.email:
            email_norm = data.email.strip().lower()
            existing_user = await self.repo.get_by_email(email_norm)
            if existing_user:
                raise ConflictException("Email already exists")

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(user, key, value)
        await self.repo.update(user)
        return await self.get_profile(user)

    async def delete_profile_image(self, user: User) -> None:
        if user.profile_image:
            import os
            clean_path = user.profile_image.lstrip("/")
            full_path = os.path.join("app", clean_path) if not clean_path.startswith("app/") else clean_path
            if os.path.exists(full_path):
                try:
                    os.remove(full_path)
                except Exception:
                    pass

            user.profile_image = None
            await self.repo.update(user)

    async def setup_totp(self, user: User) -> TOTPSetupResponse:
        if not settings.ENABLE_2FA_FEATURE:
            raise NotFoundException("2FA feature is disabled")

        # Check if settings exist
        result = await self.db.execute(select(UserSecuritySettings).where(UserSecuritySettings.user_id == user.id))
        security_settings = result.scalar_one_or_none()

        secret = TOTPService.generate_secret()
        encrypted_secret = TOTPService.encrypt_secret(secret)

        if not security_settings:
            security_settings = UserSecuritySettings(
                user_id=user.id,
                is_2fa_enabled=False,
                totp_secret_encrypted=encrypted_secret
            )
            self.db.add(security_settings)
        else:
            if security_settings.is_2fa_enabled:
                raise ConflictException("2FA is already enabled")
            security_settings.totp_secret_encrypted = encrypted_secret

        await self.db.commit()

        uri = TOTPService.generate_provisioning_uri(secret, user.email)
        return TOTPSetupResponse(secret=secret, provisioning_uri=uri)

    async def enable_totp(self, user: User, data: TOTPEnableRequest) -> list[str]:
        if not settings.ENABLE_2FA_FEATURE:
            raise NotFoundException("2FA feature is disabled")

        result = await self.db.execute(select(UserSecuritySettings).where(UserSecuritySettings.user_id == user.id))
        security_settings = result.scalar_one_or_none()

        if not security_settings or not security_settings.totp_secret_encrypted:
            raise BadRequestException("TOTP setup not initialized")

        if security_settings.is_2fa_enabled:
            raise ConflictException("2FA is already enabled")

        try:
            secret = TOTPService.decrypt_secret(security_settings.totp_secret_encrypted)
        except ValueError:
            raise BadRequestException("Invalid or corrupted TOTP secret")

        if not TOTPService.verify_totp(secret, data.code):
            raise BadRequestException("Invalid TOTP code")

        security_settings.is_2fa_enabled = True

        # Phase 1: We can generate recovery codes here (unintegrated in login)
        plain_codes = TOTPService.generate_recovery_codes()
        hashed_codes = [TOTPService.hash_recovery_code(c) for c in plain_codes]
        security_settings.recovery_codes_hashed = hashed_codes

        await self.db.commit()
        return plain_codes

    async def verify_totp_login(
        self,
        data: TOTPLoginRequest,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenResponse:
        from app.services.security_service import SecurityService
        from app.utils.redis_service import cache_get, cache_delete, cache_set, cache_incr
        from app.core.logger import logger

        try:
            payload = decode_token(data.challenge_token)
        except ValueError:
            raise UnauthorizedException("Invalid challenge token")

        if payload.get("type") != "2fa_challenge":
            raise UnauthorizedException("Invalid token type")

        jti = payload.get("jti")
        user_id = int(payload.get("sub", 0))

        # Rate Limiting: Check failed attempt thresholds
        target_limit_key = f"2fa_attempts:{user_id}"
        ip_limit_key = f"2fa_attempts:ip:{ip_address}" if ip_address else None

        attempts = await cache_get(target_limit_key)
        if attempts and int(attempts) >= settings.RATE_LIMIT_2FA_TARGET_LIMIT:
            raise UnauthorizedException("Too many failed 2FA attempts. Try again later.")

        if ip_limit_key:
            ip_attempts = await cache_get(ip_limit_key)
            if ip_attempts and int(ip_attempts) >= settings.RATE_LIMIT_2FA_IP_LIMIT:
                raise UnauthorizedException("Too many failed 2FA attempts. Try again later.")

        # Replay prevention
        jti_status = await cache_get(f"2fa_jti:{jti}")
        if not jti_status:
            raise UnauthorizedException("Challenge token expired or already consumed")

        user = await self.repo.get_by_id(user_id)
        if not user or not user.is_active or await self._is_user_deleted(user):
            raise UnauthorizedException("User not found or inactive")

        result = await self.db.execute(select(UserSecuritySettings).where(UserSecuritySettings.user_id == user.id))
        security_settings = result.scalar_one_or_none()

        if not security_settings or not security_settings.is_2fa_enabled:
            raise BadRequestException("2FA is not enabled for this account")

        # Verification Logic
        is_valid = False
        used_recovery_code = None

        try:
            secret = TOTPService.decrypt_secret(security_settings.totp_secret_encrypted)
            if TOTPService.verify_totp(secret, data.code):
                is_valid = True
        except Exception:
            pass

        if not is_valid and security_settings.recovery_codes_hashed:
            # Check recovery codes
            updated_hashes = []
            for hashed_code in security_settings.recovery_codes_hashed:
                if not is_valid and TOTPService.verify_recovery_code(data.code, hashed_code):
                    is_valid = True
                    used_recovery_code = hashed_code
                else:
                    updated_hashes.append(hashed_code)

            if is_valid:
                security_settings.recovery_codes_hashed = updated_hashes
                await self.db.commit()

        if not is_valid:
            # Increment failed attempt counters atomically
            await cache_incr(target_limit_key, ttl=settings.RATE_LIMIT_2FA_WINDOW)
            if ip_limit_key:
                await cache_incr(ip_limit_key, ttl=settings.RATE_LIMIT_2FA_WINDOW)

            try:
                await SecurityService(self.db).record_login(
                    user_id=user.id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    status="FAILED",
                    details="Invalid TOTP or Recovery code",
                )
            except Exception:
                pass
            raise UnauthorizedException("Invalid TOTP or Recovery code")

        # Success - consume JTI and clear failed attempt counter
        await cache_delete(f"2fa_jti:{jti}")
        await cache_delete(target_limit_key)

        user.last_login = utc_now()
        await self.repo.update(user)
        tokens = await self._issue_tokens(user)

        try:
            await SecurityService(self.db).record_login(
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                status="SUCCESS",
                details="2FA Login successful (Recovery code)" if used_recovery_code else "2FA Login successful",
            )
        except Exception:
            pass

        return tokens

    async def disable_totp(self, user: User, data: Disable2FARequest) -> None:
        if not verify_password(data.password, user.hashed_password):
            raise BadRequestException("Invalid password")

        result = await self.db.execute(select(UserSecuritySettings).where(UserSecuritySettings.user_id == user.id))
        security_settings = result.scalar_one_or_none()

        if not security_settings or not security_settings.is_2fa_enabled:
            raise BadRequestException("2FA is not enabled")

        try:
            secret = TOTPService.decrypt_secret(security_settings.totp_secret_encrypted)
        except ValueError:
            raise BadRequestException("Invalid or corrupted TOTP secret")

        if not TOTPService.verify_totp(secret, data.code):
            raise BadRequestException("Invalid TOTP code")

        security_settings.is_2fa_enabled = False
        security_settings.totp_secret_encrypted = None
        security_settings.recovery_codes_hashed = None

        await self.db.commit()

    async def verify_password_login_otp(
        self,
        data: LoginOTPVerifyRequest,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenResponse | TwoFAChallengeResponse:
        from app.services.security_service import SecurityService
        from app.core.logger import logger

        try:
            payload = decode_token(data.challenge_token)
        except Exception as exc:
            raise UnauthorizedException("Invalid or expired challenge token") from exc

        if payload.get("type") != "login_otp_challenge":
            raise UnauthorizedException("Invalid challenge token type")

        jti = payload.get("jti")
        if not jti or not await consume_challenge_jti(jti):
            raise UnauthorizedException("Challenge token has expired or already been used")

        user_id = int(payload.get("sub"))
        user = await self.repo.get_by_id(user_id)
        if not user or await self._is_user_deleted(user):
            raise UnauthorizedException("User not found or deactivated")

        if not user.is_active or not user.is_verified:
            raise UnauthorizedException("Account not verified. Please verify OTP first before logging in.")

        # Verify OTP atomically
        otp_valid = await verify_otp(
            email=user.email,
            otp=data.otp,
            phone=user.phone,
            purpose="password_login",
        )
        if not otp_valid:
            try:
                await SecurityService(self.db).record_login(
                    user_id=user.id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    status="FAILED",
                    details="Invalid OTP during password+OTP verification",
                )
            except Exception:
                pass
            raise UnauthorizedException("Invalid credentials")

        # 2FA intercept logic
        if settings.ENABLE_2FA_FEATURE:
            result = await self.db.execute(select(UserSecuritySettings).where(UserSecuritySettings.user_id == user.id))
            security_settings = result.scalar_one_or_none()
            if security_settings and security_settings.is_2fa_enabled:
                challenge_token, jti_2fa = create_2fa_challenge_token(user.id)
                await cache_set(f"2fa_jti:{jti_2fa}", "valid", ttl=300)

                try:
                    await SecurityService(self.db).record_login(
                        user_id=user.id,
                        ip_address=ip_address,
                        user_agent=user_agent,
                        status="CHALLENGE",
                        details="2FA challenge issued",
                    )
                except Exception:
                    pass

                return TwoFAChallengeResponse(challenge_token=challenge_token)

        user.last_login = utc_now()
        await self.repo.update(user)
        tokens = await self._issue_tokens(user)

        # If user has not set a PIN yet, provide a setup_token for convenient first-time PIN setup
        if not user.hashed_pin:
            setup_token, _ = create_pin_setup_token(user.id, user.email)
            tokens.setup_token = setup_token

        try:
            await SecurityService(self.db).record_login(
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                status="SUCCESS",
                details="Password + OTP login successful",
            )
        except Exception as e:
            logger.exception("Failed to record login history", exc_info=True)
            try:
                await self.db.rollback()
            except Exception:
                pass

        return tokens

    async def set_pin(
        self,
        data: SetPINRequest,
        current_user: User | None = None,
    ) -> dict[str, Any]:
        user = current_user
        if not user:
            if not data.setup_token:
                raise UnauthorizedException("Authentication or setup token is required to set PIN")
            try:
                payload = decode_token(data.setup_token)
            except Exception as exc:
                raise UnauthorizedException("Invalid or expired setup token") from exc

            if payload.get("type") not in ("pin_setup", "access"):
                raise UnauthorizedException("Invalid token type for PIN setup")

            user_id = int(payload.get("sub"))
            user = await self.repo.get_by_id(user_id)
            if not user or await self._is_user_deleted(user):
                raise UnauthorizedException("User not found or deactivated")

        # Validate non-trivial PIN
        validate_non_trivial_pin(data.pin)

        user.hashed_pin = hash_pin(data.pin)
        user.pin_set_at = datetime.now(timezone.utc)
        user.pin_failed_attempts = 0
        user.pin_locked_until = None
        await self.repo.update(user)

        await self.audit_repo.create("set_pin", "users", user_id=user.id, resource_id=str(user.id))
        return {"is_pin_set": True, "message": "PIN configured successfully"}

    async def change_pin(
        self,
        current_user: User,
        data: ChangePINRequest,
    ) -> dict[str, Any]:
        if not current_user.hashed_pin:
            raise BadRequestException("No PIN is currently configured. Please set a PIN first.")

        if not verify_pin(data.current_pin, current_user.hashed_pin):
            raise UnauthorizedException("Current PIN is incorrect")

        validate_non_trivial_pin(data.new_pin)

        current_user.hashed_pin = hash_pin(data.new_pin)
        current_user.pin_set_at = datetime.now(timezone.utc)
        current_user.pin_failed_attempts = 0
        current_user.pin_locked_until = None
        await self.repo.update(current_user)

        await self.audit_repo.create("change_pin", "users", user_id=current_user.id, resource_id=str(current_user.id))
        return {"is_pin_set": True, "message": "PIN changed successfully"}

    async def forgot_pin(self, data: ForgotPINRequest) -> SendOTPResponse:
        user = await self._get_user_by_identifier(data.email, data.phone)
        if not user or await self._is_user_deleted(user):
            raise NotFoundException("User not found")

        if not user.email or user.email.lower().endswith("@nexacare.local") or ".local" in user.email.lower():
            raise BadRequestException("No valid email address registered for this account. Please contact hospital support.")

        await self._issue_and_deliver_otp(user, "pin_reset")
        masked = mask_email(user.email)
        return SendOTPResponse(
            message=f"OTP sent to your registered email {masked} for PIN reset",
            masked_email=masked,
        )

    async def reset_pin(self, data: ResetPINRequest) -> MessageResponse:
        user = await self._get_user_by_identifier(data.email, data.phone)
        if not user or await self._is_user_deleted(user):
            raise NotFoundException("User not found")

        otp_valid = await verify_otp(
            email=user.email,
            otp=data.otp,
            phone=user.phone,
            purpose="pin_reset",
        )
        if not otp_valid:
            raise UnauthorizedException("Invalid or expired OTP")

        validate_non_trivial_pin(data.new_pin)

        user.hashed_pin = hash_pin(data.new_pin)
        user.pin_set_at = datetime.now(timezone.utc)
        user.pin_failed_attempts = 0
        user.pin_locked_until = None
        await self.repo.update(user)

        await self.audit_repo.create("reset_pin", "users", user_id=user.id, resource_id=str(user.id))
        return MessageResponse(message="PIN reset successfully. You can now login with your new PIN.")

