from fastapi import APIRouter, Depends, status, File, UploadFile
from app.core.dependencies import CurrentUser, DbSession, bearer_scheme
from app.core.exceptions import ForbiddenException
from app.core.constants import UserRole
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.hospital_schema import HospitalCreate, HospitalUpdate, HospitalResponse, HospitalStatsResponse
from app.schemas.user_schema import UserCreate, UserUpdate, UserResponse
from app.services.hospital_service import HospitalService
from app.models.user_model import User
from app.schemas.super_admin_schema import (
    SuperAdminDashboardResponse,
    SuperAdminAnalyticsResponse,
    DashboardOverviewResponse,
    PatientAnalyticsResponse,
    UsersDashboardResponse,
    ModuleCatalogItem,
    HospitalModuleItem,
    HospitalModulesResponse,
    HospitalModuleToggleRequest,
    HospitalModulesBulkUpdateRequest,
)
from app.services.super_admin_service import SuperAdminService
from app.services.module_service import (
    ModuleService,
    ALL_MODULES,
    FOUNDATIONAL_MODULES,
    COMMERCIAL_MODULES,
)

router = APIRouter(dependencies=[Depends(bearer_scheme)])

async def require_super_admin(user: CurrentUser) -> User:
    if not user.role or user.role.name != UserRole.SUPER_ADMIN:
        raise ForbiddenException("Requires Super Admin role")
    return user


async def require_hospital_logo_uploader(user: CurrentUser) -> User:
    role = getattr(user, "role", None)
    role_name = ""
    if hasattr(role, "name"):
        role_name = str(role.name).lower().strip()
    elif isinstance(role, str):
        role_name = role.lower().strip()
    elif getattr(user, "is_superuser", False):
        role_name = "super admin"

    role_name_norm = role_name.replace("_", " ").strip()
    if role_name_norm not in ("super admin", "hospital admin"):
        raise ForbiddenException("Requires Super Admin or Hospital Admin role")
    return user

@router.post("/hospitals", response_model=APIResponse[HospitalResponse], status_code=201)
async def create_hospital(
    data: HospitalCreate,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    hospital = await HospitalService(db).create_hospital(data, current_user.id)
    return APIResponse(message="Hospital created successfully", data=hospital)

@router.get("/hospitals", response_model=APIResponse[list[HospitalResponse]])
async def list_hospitals(
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    hospitals = await HospitalService(db).list_hospitals()
    return APIResponse(message="Hospitals retrieved successfully", data=hospitals)

@router.get("/hospitals/{id}", response_model=APIResponse[HospitalResponse])
async def get_hospital(
    id: int,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    hospital = await HospitalService(db).get_hospital(id)
    return APIResponse(message="Hospital retrieved successfully", data=hospital)

@router.put("/hospitals/{id}", response_model=APIResponse[HospitalResponse])
async def update_hospital(
    id: int,
    data: HospitalUpdate,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    hospital = await HospitalService(db).update_hospital(id, data, current_user.id)
    return APIResponse(message="Hospital updated successfully", data=hospital)

@router.post("/hospitals/{id}/logo", response_model=APIResponse[HospitalResponse])
async def upload_hospital_logo(
    id: int,
    db: DbSession,
    file: UploadFile = File(...),
    current_user: User = Depends(require_hospital_logo_uploader)
):
    role = getattr(current_user, "role", None)
    role_name = ""
    if hasattr(role, "name"):
        role_name = str(role.name).lower().strip()
    elif isinstance(role, str):
        role_name = role.lower().strip()
    elif getattr(current_user, "is_superuser", False):
        role_name = "super admin"

    role_name_norm = role_name.replace("_", " ").strip()

    if role_name_norm in ("super admin", "super_admin"):
        effective_hospital_id = id
    elif role_name_norm in ("hospital admin", "hospital_admin"):
        user_hosp_id = getattr(current_user, "hospital_id", None)
        if not user_hosp_id or user_hosp_id <= 0:
            raise ForbiddenException("Access denied: User is not associated with a valid hospital")
        if id != user_hosp_id:
            raise ForbiddenException("Access denied: Cannot upload logo for another hospital")
        effective_hospital_id = user_hosp_id
    else:
        raise ForbiddenException("Requires Super Admin or Hospital Admin role")

    hospital = await HospitalService(db).upload_logo(effective_hospital_id, file, current_user.id)
    return APIResponse(message="Hospital logo uploaded successfully", data=hospital)

@router.delete("/hospitals/{id}", response_model=APIResponse[MessageResponse])
async def deactivate_hospital(
    id: int,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    await HospitalService(db).delete_hospital(id, current_user.id)
    return APIResponse(message="Hospital deactivated successfully", data=MessageResponse(message="Hospital deactivated"))

@router.get("/hospitals/{id}/stats", response_model=APIResponse[HospitalStatsResponse])
async def get_hospital_stats(
    id: int,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    stats = await HospitalService(db).get_hospital_stats(id)
    return APIResponse(message="Hospital stats retrieved successfully", data=stats)

# Hospital Admin Management
@router.post("/hospital-admins", response_model=APIResponse[UserResponse], status_code=201)
async def create_hospital_admin(
    data: UserCreate,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    admin = await HospitalService(db).create_hospital_admin(data, current_user.id)
    return APIResponse(message="Hospital Admin created successfully", data=admin)

@router.get("/hospital-admins", response_model=APIResponse[list[UserResponse]])
async def list_hospital_admins(
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    admins = await HospitalService(db).list_hospital_admins()
    return APIResponse(message="Hospital Admins retrieved successfully", data=admins)

@router.put("/hospital-admins/{id}", response_model=APIResponse[UserResponse])
async def update_hospital_admin(
    id: int,
    data: UserUpdate,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    admin = await HospitalService(db).update_hospital_admin(id, data, current_user.id)
    return APIResponse(message="Hospital Admin updated successfully", data=admin)

@router.delete("/hospital-admins/{id}", response_model=APIResponse[MessageResponse])
async def deactivate_hospital_admin(
    id: int,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    await HospitalService(db).delete_hospital_admin(id, current_user.id)
    return APIResponse(message="Hospital Admin deactivated successfully", data=MessageResponse(message="Hospital Admin deactivated"))

@router.get("/dashboard", response_model=APIResponse[SuperAdminDashboardResponse])
async def get_super_admin_dashboard(
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    stats = await SuperAdminService(db).get_dashboard_stats()
    return APIResponse(message="Super Admin dashboard stats retrieved successfully", data=stats)

@router.get("/dashboard/analytics", response_model=APIResponse[SuperAdminAnalyticsResponse])
async def get_super_admin_analytics(
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    analytics = await SuperAdminService(db).get_analytics()
    return APIResponse(message="Super Admin analytics retrieved successfully", data=analytics)

@router.get("/dashboard/overview", response_model=APIResponse[DashboardOverviewResponse])
async def get_super_admin_dashboard_overview(
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    overview = await SuperAdminService(db).get_dashboard_overview()
    return APIResponse(message="Dashboard overview retrieved successfully", data=overview)

@router.get("/dashboard/patients", response_model=APIResponse[PatientAnalyticsResponse])
async def get_super_admin_dashboard_patients(
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    patients = await SuperAdminService(db).get_patient_analytics_dashboard()
    return APIResponse(message="Patient analytics retrieved successfully", data=patients)

@router.get("/dashboard/users", response_model=APIResponse[UsersDashboardResponse])
async def get_super_admin_dashboard_users(
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    users = await SuperAdminService(db).get_users_dashboard()
    return APIResponse(message="Users dashboard metrics retrieved successfully", data=users)


@router.get("/modules", response_model=APIResponse[list[ModuleCatalogItem]])
async def list_modules_catalog(
    db: DbSession,
    current_user: User = Depends(require_super_admin),
):
    """
    List master catalog of all 18 modules (14 foundational + 4 commercial).
    """
    service = ModuleService(db)
    all_db_modules = await service.repo.get_all_modules()
    db_mod_map = {m.code: m for m in all_db_modules}

    catalog = []
    for code in ALL_MODULES:
        db_m = db_mod_map.get(code)
        tier = "FOUNDATIONAL" if code in FOUNDATIONAL_MODULES else "COMMERCIAL"
        catalog.append(
            ModuleCatalogItem(
                code=code,
                name=db_m.name if db_m else code.replace("_", " ").title(),
                tier=tier,
                description=db_m.description if db_m else f"{code} module",
                is_active=db_m.is_active if db_m else True,
            )
        )
    return APIResponse(message="Module catalog retrieved successfully", data=catalog)


@router.get("/hospitals/{hospital_id}/modules", response_model=APIResponse[HospitalModulesResponse])
async def get_hospital_modules(
    hospital_id: int,
    db: DbSession,
    current_user: User = Depends(require_super_admin),
):
    """
    Get all module entitlement statuses for a specific hospital.
    """
    service = ModuleService(db)
    active_codes = await service.get_active_modules(hospital_id)
    hosp_modules = await service.repo.get_hospital_modules(hospital_id)
    hm_map = {hm.module_code: hm for hm in hosp_modules}

    items = []
    for code in ALL_MODULES:
        hm = hm_map.get(code)
        is_active = code in active_codes
        tier = "FOUNDATIONAL" if code in FOUNDATIONAL_MODULES else "COMMERCIAL"
        items.append(
            HospitalModuleItem(
                module_code=code,
                module_name=code.replace("_", " ").title(),
                tier=tier,
                is_active=is_active,
                status=hm.status if hm else ("ACTIVE" if is_active else "INACTIVE"),
                activated_at=hm.activated_at if hm else None,
                expires_at=hm.expires_at if hm else None,
            )
        )
    return APIResponse(
        message="Hospital modules retrieved successfully",
        data=HospitalModulesResponse(hospital_id=hospital_id, modules=items),
    )


@router.put("/hospitals/{hospital_id}/modules", response_model=APIResponse[HospitalModulesResponse])
async def bulk_update_hospital_modules(
    hospital_id: int,
    payload: HospitalModulesBulkUpdateRequest,
    db: DbSession,
    current_user: User = Depends(require_super_admin),
):
    """
    Bulk update module entitlement statuses for a hospital.
    """
    service = ModuleService(db)
    for mod in payload.modules:
        await service.set_hospital_module_status(
            hospital_id=hospital_id,
            module_code=mod.module_code,
            is_active=mod.is_active,
            status=mod.status,
        )
    await db.commit()
    return await get_hospital_modules(hospital_id, db, current_user)


@router.patch("/hospitals/{hospital_id}/modules/{module_code}", response_model=APIResponse[MessageResponse])
async def toggle_hospital_module(
    hospital_id: int,
    module_code: str,
    payload: HospitalModuleToggleRequest,
    db: DbSession,
    current_user: User = Depends(require_super_admin),
):
    """
    Toggle a single module entitlement status for a hospital.
    """
    service = ModuleService(db)
    await service.set_hospital_module_status(
        hospital_id=hospital_id,
        module_code=module_code,
        is_active=payload.is_active,
        status=payload.status,
    )
    await db.commit()
    action_str = "activated" if payload.is_active else "deactivated"
    return APIResponse(
        message=f"Module '{module_code}' {action_str} successfully for hospital {hospital_id}",
        data=MessageResponse(message="Success"),
    )
