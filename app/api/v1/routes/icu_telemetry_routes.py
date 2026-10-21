from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query

from app.core.dependencies import CurrentUser, DbSession, get_tenant_hospital_id, require_permission
from app.core.exceptions import UnauthorizedException
from app.core.security import hash_api_key
from app.models.icu_telemetry_model import IcuDevice
from app.models.user_model import User
from app.repositories.icu_telemetry_repository import IcuDeviceRepository
from app.schemas.common_schema import APIResponse
from app.schemas.icu_telemetry_schema import (
    IcuDeviceCreate,
    IcuDeviceCreatedResponse,
    IcuDeviceResponse,
    IcuDeviceStatusUpdate,
    IcuDeviceUpdate,
    TelemetryAlertResponse,
    TelemetryIngest,
    TelemetryIngestResponse,
    VitalReadingResponse,
)
from app.services.icu_telemetry_service import IcuTelemetryService
from app.utils.pagination import PaginatedResult

router = APIRouter()


async def get_icu_device(
    db: DbSession,
    x_device_api_key: str = Header(..., alias="X-Device-API-Key"),
) -> IcuDevice:
    device = await IcuDeviceRepository(db).get_by_api_key_hash(hash_api_key(x_device_api_key))
    if not device:
        raise UnauthorizedException("Invalid device API key")
    return device


IcuDeviceAuth = Depends(get_icu_device)


@router.post(
    "/telemetry",
    response_model=APIResponse[TelemetryIngestResponse],
    status_code=201,
)
async def ingest_telemetry(
    data: TelemetryIngest,
    db: DbSession,
    device: IcuDevice = IcuDeviceAuth,
):
    result = await IcuTelemetryService(db).ingest_telemetry(device, data)
    return APIResponse(message="Telemetry ingested", data=result)


@router.get(
    "/vitals/beds/latest",
    response_model=APIResponse[list[VitalReadingResponse]],
)
async def get_latest_vitals_for_icu_beds(
    db: DbSession,
    current_user: CurrentUser,
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    hospital_id_param: Optional[int] = Query(None, alias="hospital_id"),
    _: User = Depends(require_permission("icu_telemetry", "read")),
):
    target_hospital_id = x_hospital_id if x_hospital_id is not None else hospital_id_param
    hospital_id = await get_tenant_hospital_id(current_user, target_hospital_id)
    result = await IcuTelemetryService(db).get_latest_for_icu_beds(hospital_id=hospital_id)
    return APIResponse(message="Latest ICU bed vitals retrieved", data=result)


@router.get(
    "/vitals/beds/{bed_id}/history",
    response_model=APIResponse[PaginatedResult[VitalReadingResponse]],
)
async def get_vitals_history_for_bed(
    bed_id: int,
    db: DbSession,
    current_user: CurrentUser,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    page: int = 1,
    size: int = 50,
    include_ecg: bool = False,
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    hospital_id_param: Optional[int] = Query(None, alias="hospital_id"),
    _: User = Depends(require_permission("icu_telemetry", "read")),
):
    target_hospital_id = x_hospital_id if x_hospital_id is not None else hospital_id_param
    hospital_id = await get_tenant_hospital_id(current_user, target_hospital_id)
    result = await IcuTelemetryService(db).get_history_for_bed(
        bed_id,
        from_time=from_time,
        to_time=to_time,
        page=page,
        size=size,
        include_ecg=include_ecg,
        hospital_id=hospital_id,
    )
    return APIResponse(message="Vitals history retrieved", data=result)


@router.get(
    "/vitals/patients/{patient_id}/history",
    response_model=APIResponse[PaginatedResult[VitalReadingResponse]],
)
async def get_vitals_history_for_patient(
    patient_id: int,
    db: DbSession,
    current_user: CurrentUser,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    page: int = 1,
    size: int = 50,
    include_ecg: bool = False,
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    hospital_id_param: Optional[int] = Query(None, alias="hospital_id"),
    _: User = Depends(require_permission("icu_telemetry", "read")),
):
    target_hospital_id = x_hospital_id if x_hospital_id is not None else hospital_id_param
    hospital_id = await get_tenant_hospital_id(current_user, target_hospital_id)
    result = await IcuTelemetryService(db).get_history_for_patient(
        patient_id,
        from_time=from_time,
        to_time=to_time,
        page=page,
        size=size,
        include_ecg=include_ecg,
        hospital_id=hospital_id,
    )
    return APIResponse(message="Vitals history retrieved", data=result)


@router.get(
    "/vitals/beds/{bed_id}/latest",
    response_model=APIResponse[VitalReadingResponse],
)
async def get_latest_vitals_for_bed(
    bed_id: int,
    db: DbSession,
    current_user: CurrentUser,
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    hospital_id_param: Optional[int] = Query(None, alias="hospital_id"),
    _: User = Depends(require_permission("icu_telemetry", "read")),
):
    target_hospital_id = x_hospital_id if x_hospital_id is not None else hospital_id_param
    hospital_id = await get_tenant_hospital_id(current_user, target_hospital_id)
    result = await IcuTelemetryService(db).get_latest_for_bed(bed_id, hospital_id=hospital_id)
    return APIResponse(message="Latest vitals retrieved", data=result)


@router.get(
    "/vitals/patients/{patient_id}/latest",
    response_model=APIResponse[VitalReadingResponse],
)
async def get_latest_vitals_for_patient(
    patient_id: int,
    db: DbSession,
    current_user: CurrentUser,
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    hospital_id_param: Optional[int] = Query(None, alias="hospital_id"),
    _: User = Depends(require_permission("icu_telemetry", "read")),
):
    target_hospital_id = x_hospital_id if x_hospital_id is not None else hospital_id_param
    hospital_id = await get_tenant_hospital_id(current_user, target_hospital_id)
    result = await IcuTelemetryService(db).get_latest_for_patient(patient_id, hospital_id=hospital_id)
    return APIResponse(message="Latest vitals retrieved", data=result)


@router.get(
    "/alerts",
    response_model=APIResponse[list[TelemetryAlertResponse]],
)
async def list_active_alerts(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 50,
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    hospital_id_param: Optional[int] = Query(None, alias="hospital_id"),
    _: User = Depends(require_permission("icu_telemetry", "read")),
):
    target_hospital_id = x_hospital_id if x_hospital_id is not None else hospital_id_param
    hospital_id = await get_tenant_hospital_id(current_user, target_hospital_id)
    result = await IcuTelemetryService(db).list_active_alerts(page=page, size=size, hospital_id=hospital_id)
    return APIResponse(message="Active alerts retrieved", data=result)


@router.patch(
    "/alerts/{alert_id}/acknowledge",
    response_model=APIResponse[TelemetryAlertResponse],
)
async def acknowledge_alert(
    alert_id: int,
    db: DbSession,
    current_user: CurrentUser,
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    hospital_id_param: Optional[int] = Query(None, alias="hospital_id"),
    _: User = Depends(require_permission("icu_telemetry", "update")),
):
    target_hospital_id = x_hospital_id if x_hospital_id is not None else hospital_id_param
    hospital_id = await get_tenant_hospital_id(current_user, target_hospital_id)
    result = await IcuTelemetryService(db).acknowledge_alert(alert_id, current_user.id, hospital_id=hospital_id)
    return APIResponse(message="Alert acknowledged", data=result)


@router.post(
    "/devices",
    response_model=APIResponse[IcuDeviceCreatedResponse],
    status_code=201,
    tags=["Bed Allocation", "ICU Telemetry"]
)
async def register_device(
    data: IcuDeviceCreate,
    db: DbSession,
    current_user: CurrentUser,
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    hospital_id_param: Optional[int] = Query(None, alias="hospital_id"),
    _: User = Depends(require_permission("icu_telemetry", "create")),
):
    target_hospital_id = x_hospital_id if x_hospital_id is not None else hospital_id_param
    hospital_id = await get_tenant_hospital_id(current_user, target_hospital_id)
    result = await IcuTelemetryService(db).create_device(data, current_user.id, hospital_id=hospital_id)
    return APIResponse(message="ICU device registered", data=result)


@router.patch(
    "/devices/{device_id}",
    response_model=APIResponse[IcuDeviceResponse],
)
async def update_device(
    device_id: int,
    data: IcuDeviceUpdate,
    db: DbSession,
    current_user: CurrentUser,
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    hospital_id_param: Optional[int] = Query(None, alias="hospital_id"),
    _: User = Depends(require_permission("icu_telemetry", "update")),
):
    target_hospital_id = x_hospital_id if x_hospital_id is not None else hospital_id_param
    hospital_id = await get_tenant_hospital_id(current_user, target_hospital_id)
    result = await IcuTelemetryService(db).update_device(device_id, data, current_user.id, hospital_id=hospital_id)
    return APIResponse(message="ICU device updated", data=result)


@router.patch(
    "/devices/{device_id}/status",
    response_model=APIResponse[IcuDeviceResponse],
)
async def set_device_status(
    device_id: int,
    data: IcuDeviceStatusUpdate,
    db: DbSession,
    current_user: CurrentUser,
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    hospital_id_param: Optional[int] = Query(None, alias="hospital_id"),
    _: User = Depends(require_permission("icu_telemetry", "update")),
):
    target_hospital_id = x_hospital_id if x_hospital_id is not None else hospital_id_param
    hospital_id = await get_tenant_hospital_id(current_user, target_hospital_id)
    result = await IcuTelemetryService(db).set_device_status(
        device_id, data.is_active, current_user.id, hospital_id=hospital_id
    )
    message = "ICU device activated" if data.is_active else "ICU device deactivated"
    return APIResponse(message=message, data=result)


@router.get(
    "/devices",
    response_model=APIResponse[list[IcuDeviceResponse]],
)
async def list_devices(
    db: DbSession,
    current_user: CurrentUser,
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    hospital_id_param: Optional[int] = Query(None, alias="hospital_id"),
    _: User = Depends(require_permission("icu_telemetry", "read")),
):
    target_hospital_id = x_hospital_id if x_hospital_id is not None else hospital_id_param
    hospital_id = await get_tenant_hospital_id(current_user, target_hospital_id)
    result = await IcuTelemetryService(db).list_devices(hospital_id=hospital_id)
    return APIResponse(message="ICU devices retrieved", data=result)
