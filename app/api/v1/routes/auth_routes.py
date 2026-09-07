from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Request, Form, File, UploadFile, HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.core.dependencies import CurrentUser, DbSession
from app.schemas.auth_schema import (
    TOTPEnableResponse,
    ActivateAccountRequest,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    OTPVerifyRequest,
    ProfileUpdateRequest,
    RefreshTokenRequest,
    RegisterRequest,
    RegisterRoleName,
    GenderOption,
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
async def register(
    db: DbSession,
    email: str = Form(..., description="Valid email address (used for login and OTP email)"),
    password: str = Form(..., description="At least 8 characters"),
    full_name: str = Form(..., description="Full legal name"),
    phone: Optional[str] = Form(None, description="Mobile number for SMS OTP"),
    role_name: RegisterRoleName = Form(RegisterRoleName.PATIENT, description="Role from dropdown"),
    role_id: Optional[int] = Form(None, description="Deprecated - use role_name instead"),
    gender: Optional[GenderOption] = Form(None, description="Male, Female, or Other"),
    date_of_birth: Optional[date] = Form(None, description="Date of birth (YYYY-MM-DD). Must be in the past."),
    address: Optional[str] = Form(None, description="Physical address of the user"),
    profile_image: Optional[UploadFile] = File(None, description="Optional profile image upload"),
):
    try:
        update_dict = {
            "email": email,
            "password": password,
            "full_name": full_name,
            "role_name": role_name,
        }
        if phone is not None:
            update_dict["phone"] = phone
        if role_id is not None:
            update_dict["role_id"] = role_id
        if gender is not None:
            update_dict["gender"] = gender
        if date_of_birth is not None:
            update_dict["date_of_birth"] = date_of_birth
        if address is not None:
            update_dict["address"] = address

        if profile_image and profile_image.filename:
            profile_image_path = await save_profile_image(profile_image)
            update_dict["profile_image"] = profile_image_path

        data = RegisterRequest(**update_dict)
    except ValidationError as e:
        raise RequestValidationError(e.errors())

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


async def save_profile_image(file: UploadFile) -> str:
    import os
    import uuid
    from pathlib import Path
    import aiofiles
    from app.core.config import settings

    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(
            status_code=400,
            detail="File type not allowed. Only jpg, jpeg, png, and webp are allowed."
        )

    upload_dir = Path("app/uploads/profiles")
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    unique_filename = f"{uuid.uuid4().hex}{ext}"
    filepath = upload_dir / unique_filename

    content = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=400, detail="File too large")

    async with aiofiles.open(filepath, "wb") as f:
        await f.write(content)

    return str(filepath).replace(os.sep, "/")


@router.put("/profile", response_model=APIResponse[UserProfileResponse])
async def update_profile(
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    full_name: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    gender: Optional[str] = Form(None),
    date_of_birth: Optional[date] = Form(None),
    email: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    profile_image: Optional[UploadFile] = File(None)
):
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            data = ProfileUpdateRequest(**body)
        except ValidationError as e:
            raise RequestValidationError(e.errors())
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=[{"loc": ["body"], "msg": f"Invalid JSON payload: {str(e)}", "type": "json_invalid"}]
            )
    else:
        form_data = await request.form()
        update_dict = {}
        
        if "full_name" in form_data:
            update_dict["full_name"] = full_name
        if "phone" in form_data:
            update_dict["phone"] = phone
        if "gender" in form_data:
            update_dict["gender"] = gender
        if "date_of_birth" in form_data:
            update_dict["date_of_birth"] = date_of_birth
        if "email" in form_data:
            update_dict["email"] = email
        if "address" in form_data:
            update_dict["address"] = address
            
        if profile_image and profile_image.filename:
            profile_image_path = await save_profile_image(profile_image)
            update_dict["profile_image"] = profile_image_path
            
        try:
            data = ProfileUpdateRequest(**update_dict)
        except ValidationError as e:
            raise RequestValidationError(e.errors())

    profile = await AuthService(db).update_profile(current_user, data)
    return APIResponse(message="Profile updated", data=profile)

@router.post("/2fa/setup", response_model=APIResponse[TOTPSetupResponse])
async def setup_totp(db: DbSession, current_user: CurrentUser):
    setup_data = await AuthService(db).setup_totp(current_user)
    return APIResponse(message="2FA setup initialized", data=setup_data)

@router.post("/2fa/enable", response_model=APIResponse[TOTPEnableResponse])
async def enable_totp(data: TOTPEnableRequest, db: DbSession, current_user: CurrentUser):
    recovery_codes = await AuthService(db).enable_totp(current_user, data)
    return APIResponse(message="2FA successfully enabled", data=TOTPEnableResponse(recovery_codes=recovery_codes))

@router.post("/2fa/disable", response_model=APIResponse[MessageResponse])
async def disable_totp(data: Disable2FARequest, db: DbSession, current_user: CurrentUser):
    await AuthService(db).disable_totp(current_user, data)
    return APIResponse(message="2FA successfully disabled", data=MessageResponse(message="2FA disabled"))
