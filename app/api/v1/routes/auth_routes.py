from typing import List

from fastapi import APIRouter, Depends, Request

from app.core.dependencies import CurrentUser, DbSession
from app.schemas.auth_schema import (
    ActivateAccountRequest,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    OTPVerifyRequest,
    ProfileUpdateRequest,
    RefreshTokenRequest,
    RegisterRequest,
    RegistrationRoleOption,
    ResetPasswordRequest,
    SendOTPRequest,
    TokenResponse,
    UserProfileResponse,
    TOTPSetupResponse,
    TOTPEnableRequest,
    TwoFAChallengeResponse,
    TOTPLoginRequest,
    Disable2FARequest,
)
from app.schemas.common_schema import APIResponse, MessageResponse
from app.services.auth_service import AuthService

router = APIRouter()


@router.get("/roles", response_model=APIResponse[List[RegistrationRoleOption]])
async def list_registration_roles(db: DbSession):
    """List all roles with id and name. Use role_name when registering (not role_id: 0)."""
    roles = await AuthService(db).list_registration_roles()
    return APIResponse(message="Roles for registration", data=roles)


@router.post("/register", response_model=APIResponse[MessageResponse], status_code=201)
async def register(data: RegisterRequest, db: DbSession):
    await AuthService(db).register(data)
    return APIResponse(
        message="Registration successful. Please verify OTP to activate account.",
        data=MessageResponse(message="OTP sent to your email and/or mobile number"),
    )


@router.post("/send-otp", response_model=APIResponse[MessageResponse])
async def send_otp(data: SendOTPRequest, db: DbSession):
    await AuthService(db).send_otp(data)
    return APIResponse(
        message="OTP sent",
        data=MessageResponse(message="OTP sent to your email and/or mobile number"),
    )


@router.post("/login", response_model=APIResponse[TokenResponse | TwoFAChallengeResponse])
async def login(data: LoginRequest, db: DbSession, request: Request):
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    result = await AuthService(db).login(
        data, ip_address=ip_address, user_agent=user_agent
    )
    if isinstance(result, TwoFAChallengeResponse):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=202, content={"message": "2FA required", "data": result.model_dump()})
    return APIResponse(message="Login successful", data=result)

@router.post("/login/2fa", response_model=APIResponse[TokenResponse])
async def login_2fa(data: TOTPLoginRequest, db: DbSession, request: Request):
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    tokens = await AuthService(db).verify_totp_login(
        data, ip_address=ip_address, user_agent=user_agent
    )
    return APIResponse(message="Login successful", data=tokens)


@router.post("/logout", response_model=APIResponse[MessageResponse])
async def logout(
    data: RefreshTokenRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    await AuthService(db).logout(data.refresh_token, current_user)
    return APIResponse(message="Logged out successfully", data=MessageResponse(message="Logged out"))


@router.post("/refresh-token", response_model=APIResponse[TokenResponse])
async def refresh_token(data: RefreshTokenRequest, db: DbSession):
    tokens = await AuthService(db).refresh_token(data.refresh_token)
    return APIResponse(message="Token refreshed", data=tokens)


@router.post("/forgot-password", response_model=APIResponse[MessageResponse])
async def forgot_password(data: ForgotPasswordRequest, db: DbSession):
    await AuthService(db).forgot_password(data)
    return APIResponse(
        message="If the email exists, an OTP has been sent",
        data=MessageResponse(message="OTP sent"),
    )


@router.post("/reset-password", response_model=APIResponse[MessageResponse])
async def reset_password(data: ResetPasswordRequest, db: DbSession):
    await AuthService(db).reset_password(data)
    return APIResponse(message="Password reset successful", data=MessageResponse(message="Password updated"))


@router.post("/change-password", response_model=APIResponse[MessageResponse])
async def change_password(data: ChangePasswordRequest, db: DbSession, current_user: CurrentUser):
    await AuthService(db).change_password(current_user, data)
    return APIResponse(message="Password changed", data=MessageResponse(message="Password updated"))


@router.post("/verify-otp", response_model=APIResponse[MessageResponse])
async def verify_otp(data: OTPVerifyRequest, db: DbSession):
    await AuthService(db).verify_otp_code(data)
    return APIResponse(message="OTP verified", data=MessageResponse(message="OTP valid"))


@router.post("/activate", response_model=APIResponse[MessageResponse])
async def activate_account(data: ActivateAccountRequest, db: DbSession):
    await AuthService(db).activate_account(data)
    return APIResponse(message="Account activated", data=MessageResponse(message="Account is now active"))


@router.get("/me", response_model=APIResponse[UserProfileResponse])
async def get_me(db: DbSession, current_user: CurrentUser):
    profile = await AuthService(db).get_profile(current_user)
    return APIResponse(message="Profile retrieved", data=profile)


@router.put("/profile", response_model=APIResponse[UserProfileResponse])
async def update_profile(data: ProfileUpdateRequest, db: DbSession, current_user: CurrentUser):
    profile = await AuthService(db).update_profile(current_user, data)
    return APIResponse(message="Profile updated", data=profile)

@router.post("/2fa/setup", response_model=APIResponse[TOTPSetupResponse])
async def setup_totp(db: DbSession, current_user: CurrentUser):
    setup_data = await AuthService(db).setup_totp(current_user)
    return APIResponse(message="2FA setup initialized", data=setup_data)

@router.post("/2fa/enable", response_model=APIResponse[MessageResponse])
async def enable_totp(data: TOTPEnableRequest, db: DbSession, current_user: CurrentUser):
    await AuthService(db).enable_totp(current_user, data)
    return APIResponse(message="2FA successfully enabled", data=MessageResponse(message="2FA enabled"))

@router.post("/2fa/disable", response_model=APIResponse[MessageResponse])
async def disable_totp(data: Disable2FARequest, db: DbSession, current_user: CurrentUser):
    await AuthService(db).disable_totp(current_user, data)
    return APIResponse(message="2FA successfully disabled", data=MessageResponse(message="2FA disabled"))
