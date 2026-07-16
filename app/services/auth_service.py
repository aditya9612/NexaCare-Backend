from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import UserRole
from app.core.exceptions import BadRequestException, ConflictException, NotFoundException, UnauthorizedException
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)
from app.models.refresh_token_model import RefreshToken
from app.models.user_model import User
from app.models.department_model import Department
from app.repositories.audit_repository import AuditRepository
from app.repositories.auth_repository import AuthRepository
from app.repositories.rbac_repository import RBACRepository
from app.schemas.auth_schema import (
    ActivateAccountRequest,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    OTPVerifyRequest,
    ProfileUpdateRequest,
    RegisterRequest,
    RegistrationRoleOption,
    ResetPasswordRequest,
    SendOTPRequest,
    TokenResponse,
    UserProfileResponse,
)
from app.utils.helpers import generate_user_code, utc_now
from app.utils.otp_delivery import deliver_otp
from app.utils.otp_handler import generate_otp, store_otp, verify_otp


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
        otp = generate_otp()
        store_otp(user.email, otp, settings.OTP_EXPIRE_MINUTES, phone=user.phone)
        await deliver_otp(email=user.email, phone=user.phone, otp=otp, purpose=purpose)
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

            await self._issue_and_deliver_otp(user, "account activation")
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
            nurse = await self.db.scalar(select(Nurse).where(Nurse.user_id == user.id))
            if nurse is None:
                from app.utils.helpers import generate_nurse_code
                from app.models.department_model import Department
                department = await self.db.scalar(
                    select(Department).order_by(Department.department_id.asc())
                )
                dept_id = department.department_id if department else None
                
                staff = await self.db.scalar(select(Staff).where(Staff.email == user.email))
                if staff and staff.department_id:
                    dept_id = staff.department_id
                
                nurse = Nurse(
                    nurse_code=generate_nurse_code(),
                    user_id=user.id,
                    license_number=f"LIC-{generate_nurse_code()}",
                    department_id=dept_id,
                    shift="Morning Shift",
                )
                self.db.add(nurse)
                await self.db.flush()
            return False
        elif user.role.name == UserRole.PATIENT:
            patient = await self.db.scalar(select(Patient).where(Patient.user_id == user.id))
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
            staff = await self.db.scalar(select(Staff).where(Staff.email == user.email))
            return staff is None or staff.is_deleted
        return False

    async def send_otp(self, data: SendOTPRequest) -> None:
        user = await self._get_user_by_identifier(data.email, data.phone)
        if not user or await self._is_user_deleted(user):
            raise NotFoundException("User not found")
        await self._issue_and_deliver_otp(user, "login")

    async def login(
        self,
        data: LoginRequest,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenResponse:
        from app.services.security_service import SecurityService
        from app.core.logger import logger

        user = None
        try:
            user = await self._get_user_by_identifier(data.email, data.phone)
            if not user:
                raise UnauthorizedException("Invalid credentials")

            if await self._is_user_deleted(user):
                raise UnauthorizedException("Account deactivated or deleted")

            if data.otp:
                if not verify_otp(email=data.email, otp=data.otp, phone=data.phone):
                    raise UnauthorizedException("Invalid credentials")
            elif not data.password or not verify_password(
                data.password, user.hashed_password
            ):
                raise UnauthorizedException("Invalid credentials")

            if not user.is_active:
                raise UnauthorizedException("Account not activated. Please verify OTP.")

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

        except UnauthorizedException as exc:
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
        access = create_access_token(user.id)
        refresh = create_refresh_token(user.id)
        expires_at = utc_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        await self.repo.save_refresh_token(
            RefreshToken(user_id=user.id, token=refresh, expires_at=expires_at)
        )
        return TokenResponse(access_token=access, refresh_token=refresh)

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
        if not verify_otp(email=data.email, otp=data.otp, phone=data.phone):
            raise BadRequestException("Invalid or expired OTP")
        user = await self._get_user_by_identifier(data.email, data.phone)
        if not user or await self._is_user_deleted(user):
            raise NotFoundException("User not found")
        if not user.is_active:
            raise BadRequestException("Account not activated")
        user.hashed_password = get_password_hash(data.new_password)
        await self.repo.update(user)
        await self.repo.revoke_all_user_tokens(user.id)

    async def change_password(self, user: User, data: ChangePasswordRequest) -> None:
        if not verify_password(data.current_password, user.hashed_password):
            raise BadRequestException("Current password is incorrect")
        user.hashed_password = get_password_hash(data.new_password)
        await self.repo.update(user)
        await self.repo.revoke_all_user_tokens(user.id)

    async def verify_otp_code(self, data: OTPVerifyRequest) -> None:
        user = await self._get_user_by_identifier(data.email, data.phone)
        if not user:
            raise NotFoundException("User not found")
        if not verify_otp(email=data.email, otp=data.otp, phone=data.phone):
            raise BadRequestException("Invalid or expired OTP")
        user.is_verified = True
        await self.repo.update(user)

    async def activate_account(self, data: ActivateAccountRequest) -> None:
        user = await self._get_user_by_identifier(data.email, data.phone)
        if not user:
            raise NotFoundException("User not found")
        if not user.is_verified:
            raise BadRequestException("Please verify OTP before activating your account.")
        user.is_active = True
        await self.repo.update(user)

    async def get_profile(self, user: User) -> UserProfileResponse:
        return UserProfileResponse(
            id=user.id,
            user_code=user.user_code,
            full_name=user.full_name,
            email=user.email,
            phone=user.phone,
            role_id=user.role_id,
            role_name=user.role.name if user.role else None,
            profile_image=user.profile_image,
            gender=user.gender,
            date_of_birth=user.date_of_birth,
            is_active=user.is_active,
            is_verified=user.is_verified,
            last_login=user.last_login,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    async def update_profile(self, user: User, data: ProfileUpdateRequest) -> UserProfileResponse:
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(user, key, value)
        await self.repo.update(user)
        return await self.get_profile(user)
