from fastapi import APIRouter, Depends
from app.core.dependencies import DbSession, CurrentUser, require_permission
from app.services.settings_service import SettingsService
from app.schemas.settings_schema import (
    HospitalSettingResponse,
    HospitalSettingUpdate,
    NotificationSettingResponse,
    NotificationSettingUpdate,
    UserPreferenceResponse,
    UserPreferenceUpdate,
)
from app.schemas.appointment_setting_schema import (
    AppointmentSettingsResponse,
    AppointmentSettingsUpdate,
)

from app.core.exceptions import ForbiddenException
from app.core.constants import UserRole

router = APIRouter()


def _check_hospital_access(hospital_id: int, current_user: CurrentUser):
    """
    Enforce tenant isolation. A user can only access their own hospital's settings,
    unless they are a global SUPER_ADMIN.
    """
    role_name = current_user.role.name if current_user.role else ""
    if role_name == UserRole.SUPER_ADMIN:
        return
    if current_user.hospital_id != hospital_id:
        raise ForbiddenException("Cross-tenant access denied")


# ---------------------------------------------------------
# HOSPITAL SETTINGS
# ---------------------------------------------------------
@router.get(
    "/hospital/{hospital_id}",
    response_model=HospitalSettingResponse,
    summary="Get Hospital Settings",
    description="Retrieve the settings configuration for a specific hospital.",
    dependencies=[Depends(require_permission("settings", "read"))]
)
async def get_hospital_settings(hospital_id: int, db: DbSession, current_user: CurrentUser):
    _check_hospital_access(hospital_id, current_user)
    service = SettingsService(db)
    return await service.get_hospital_settings(hospital_id)


@router.patch(
    "/hospital/{hospital_id}",
    response_model=HospitalSettingResponse,
    summary="Update Hospital Settings",
    description="Partially update the settings configuration for a specific hospital.",
    dependencies=[Depends(require_permission("settings", "update"))]
)
async def update_hospital_settings(hospital_id: int, payload: HospitalSettingUpdate, db: DbSession, current_user: CurrentUser):
    _check_hospital_access(hospital_id, current_user)
    service = SettingsService(db)
    return await service.update_hospital_settings(
        hospital_id, 
        payload.model_dump(exclude_unset=True), 
        updated_by_user_id=current_user.id
    )


# ---------------------------------------------------------
# NOTIFICATION SETTINGS
# ---------------------------------------------------------
@router.get(
    "/notification/{hospital_id}",
    response_model=NotificationSettingResponse,
    summary="Get Notification Settings",
    description="Retrieve the notification configuration flags for a specific hospital.",
    dependencies=[Depends(require_permission("settings", "read"))]
)
async def get_notification_settings(hospital_id: int, db: DbSession, current_user: CurrentUser):
    _check_hospital_access(hospital_id, current_user)
    service = SettingsService(db)
    return await service.get_notification_settings(hospital_id)


@router.patch(
    "/notification/{hospital_id}",
    response_model=NotificationSettingResponse,
    summary="Update Notification Settings",
    description="Partially update the notification configuration flags for a specific hospital.",
    dependencies=[Depends(require_permission("settings", "update"))]
)
async def update_notification_settings(hospital_id: int, payload: NotificationSettingUpdate, db: DbSession, current_user: CurrentUser):
    _check_hospital_access(hospital_id, current_user)
    service = SettingsService(db)
    return await service.update_notification_settings(
        hospital_id, 
        payload.model_dump(exclude_unset=True), 
        updated_by_user_id=current_user.id
    )


# ---------------------------------------------------------
# USER PREFERENCES
# ---------------------------------------------------------
async def _check_user_preference_access(user_id: int, current_user: CurrentUser, db: DbSession, action: str):
    """
    Allow access if the current user owns the profile OR has the explicit admin permission.
    """
    if current_user.id == user_id:
        return
    checker = require_permission("settings", action)
    await checker(db, current_user)


@router.get(
    "/user/{user_id}",
    response_model=UserPreferenceResponse,
    summary="Get User Preferences",
    description="Retrieve personal UI and notification preferences for a specific user."
)
async def get_user_preferences(user_id: int, db: DbSession, current_user: CurrentUser):
    await _check_user_preference_access(user_id, current_user, db, "read")
    service = SettingsService(db)
    return await service.get_user_preferences(user_id)


@router.patch(
    "/user/{user_id}",
    response_model=UserPreferenceResponse,
    summary="Update User Preferences",
    description="Partially update personal UI and notification preferences for a specific user."
)
async def update_user_preferences(user_id: int, payload: UserPreferenceUpdate, db: DbSession, current_user: CurrentUser):
    await _check_user_preference_access(user_id, current_user, db, "update")
    service = SettingsService(db)
    return await service.update_user_preferences(
        user_id, 
        payload.model_dump(exclude_unset=True)
    )

# ---------------------------------------------------------
# APPOINTMENT SETTINGS
# ---------------------------------------------------------
@router.get(
    "/appointments/{hospital_id}",
    response_model=AppointmentSettingsResponse,
    summary="Get Appointment Settings",
    description="Retrieve appointment configuration for a specific hospital.",
    dependencies=[Depends(require_permission("appointment_settings", "read"))]
)
async def get_appointment_settings(hospital_id: int, db: DbSession, current_user: CurrentUser):
    _check_hospital_access(hospital_id, current_user)
    service = SettingsService(db)
    return await service.get_appointment_settings(hospital_id)


from fastapi import HTTPException
from app.core.constants import OperationMode

@router.put(
    "/appointments/{hospital_id}",
    response_model=AppointmentSettingsResponse,
    summary="Update Appointment Settings",
    description="Update appointment configuration for a specific hospital.",
    dependencies=[Depends(require_permission("appointment_settings", "update"))]
)
async def update_appointment_settings(hospital_id: int, payload: AppointmentSettingsUpdate, db: DbSession, current_user: CurrentUser):
    _check_hospital_access(hospital_id, current_user)
    
    if payload.operation_mode in (OperationMode.SHIFT_BASED, OperationMode.CUSTOM):
        raise HTTPException(
            status_code=501, 
            detail=f"{payload.operation_mode.value.upper()} mode is reserved for a future release."
        )

    service = SettingsService(db)
    return await service.update_appointment_settings(
        hospital_id, 
        payload.model_dump(exclude_unset=True),
        updated_by_user_id=current_user.id
    )
