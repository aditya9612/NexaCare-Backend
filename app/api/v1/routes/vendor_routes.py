from typing import Optional
from enum import Enum
from fastapi import APIRouter, Depends, Header, Query, UploadFile, File, HTTPException
from fastapi.responses import Response, StreamingResponse

from app.core.dependencies import CurrentUser, DbSession, get_tenant_hospital_id, require_permission, resolve_tenant_id
from app.models.user_model import User
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.vendor_schema import VendorCreate, VendorUpdate, VendorResponse
from app.services.vendor_service import VendorService
from app.utils.pagination import PaginatedResult

router = APIRouter()


class VendorExportFormat(str, Enum):
    EXCEL = "excel"
    PDF = "pdf"


@router.get("/bulk-template")
async def download_bulk_template(
    db: DbSession,
    current_user: CurrentUser,
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    hospital_id_param: Optional[int] = Query(None, alias="hospital_id"),
    _: User = Depends(require_permission("vendor", "read")),
):
    target_hospital_id = x_hospital_id if x_hospital_id is not None else hospital_id_param
    hospital_id = await get_tenant_hospital_id(current_user, target_hospital_id)
    stream = await VendorService(db).generate_vendor_bulk_template(hospital_id=hospital_id, current_user=current_user)
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=vendors_bulk_template.xlsx"}
    )


@router.post("/bulk-upload", status_code=201)
async def upload_vendors_bulk(
    db: DbSession,
    current_user: CurrentUser,
    file: UploadFile = File(...),
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    hospital_id_param: Optional[int] = Query(None, alias="hospital_id"),
    _: User = Depends(require_permission("vendor", "create")),
):
    if not file.filename.endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Only .xlsx files are supported."
        )
        
    target_hospital_id = x_hospital_id if x_hospital_id is not None else hospital_id_param
    hospital_id = await get_tenant_hospital_id(current_user, target_hospital_id)
    result = await VendorService(db).import_vendors_from_excel(file, current_user.id, hospital_id=hospital_id, current_user=current_user)
    return APIResponse(message="Vendors bulk upload processed", data=result)


@router.get("/export")
async def export_vendors(
    db: DbSession,
    current_user: CurrentUser,
    format: VendorExportFormat = Query(VendorExportFormat.EXCEL),
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    hospital_id_param: Optional[int] = Query(None, alias="hospital_id"),
    _: User = Depends(require_permission("vendor", "read")),
):
    target_hospital_id = x_hospital_id if x_hospital_id is not None else hospital_id_param
    hospital_id = await get_tenant_hospital_id(current_user, target_hospital_id)
    data, media_type = await VendorService(db).export_vendors(format.value, hospital_id=hospital_id, current_user=current_user)
    
    if format == VendorExportFormat.EXCEL:
        return StreamingResponse(
            data,
            media_type=media_type,
            headers={"Content-Disposition": "attachment; filename=vendors_export.xlsx"}
        )
    else:
        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": "attachment; filename=vendors_export.pdf"}
        )


@router.post("", response_model=APIResponse[VendorResponse], status_code=201)
async def create_vendor(
    data: VendorCreate,
    db: DbSession,
    current_user: CurrentUser,
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    hospital_id_param: Optional[int] = Query(None, alias="hospital_id"),
    _: User = Depends(require_permission("vendor", "create")),
):
    target_hospital_id = x_hospital_id if x_hospital_id is not None else hospital_id_param
    hospital_id = await get_tenant_hospital_id(current_user, target_hospital_id)
    vendor = await VendorService(db).create_vendor(data, current_user.id, hospital_id=hospital_id, current_user=current_user)
    return APIResponse(message="Vendor created", data=vendor)


@router.get("", response_model=APIResponse[PaginatedResult[VendorResponse]])
async def list_vendors(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    vendor_type: str | None = Query(None, pattern="^(expense|expenses|inventory)$"),
    search: Optional[str] = Query(None),
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    hospital_id_param: Optional[int] = Query(None, alias="hospital_id"),
    _: User = Depends(require_permission("vendor", "read")),
):
    target_hospital_id = x_hospital_id if x_hospital_id is not None else hospital_id_param
    hospital_id = await get_tenant_hospital_id(current_user, target_hospital_id)
    result = await VendorService(db).list_vendors(
        page=page,
        size=size,
        vendor_type=vendor_type,
        search=search,
        hospital_id=hospital_id,
        current_user=current_user,
    )
    return APIResponse(message="Vendors retrieved", data=result)


@router.get("/{vendor_id}", response_model=APIResponse[VendorResponse])
async def get_vendor(
    vendor_id: int,
    db: DbSession,
    current_user: CurrentUser,
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    hospital_id_param: Optional[int] = Query(None, alias="hospital_id"),
    _: User = Depends(require_permission("vendor", "read")),
):
    target_hospital_id = x_hospital_id if x_hospital_id is not None else hospital_id_param
    hospital_id = await get_tenant_hospital_id(current_user, target_hospital_id)
    vendor = await VendorService(db).get_vendor(vendor_id, hospital_id=hospital_id, current_user=current_user)
    return APIResponse(message="Vendor retrieved", data=vendor)


@router.patch("/{vendor_id}", response_model=APIResponse[VendorResponse])
async def update_vendor(
    vendor_id: int,
    data: VendorUpdate,
    db: DbSession,
    current_user: CurrentUser,
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    hospital_id_param: Optional[int] = Query(None, alias="hospital_id"),
    _: User = Depends(require_permission("vendor", "update")),
):
    target_hospital_id = x_hospital_id if x_hospital_id is not None else hospital_id_param
    hospital_id = await get_tenant_hospital_id(current_user, target_hospital_id)
    vendor = await VendorService(db).update_vendor(vendor_id, data, current_user.id, hospital_id=hospital_id, current_user=current_user)
    return APIResponse(message="Vendor updated", data=vendor)


@router.delete("/{vendor_id}", response_model=APIResponse[MessageResponse])
async def delete_vendor(
    vendor_id: int,
    db: DbSession,
    current_user: CurrentUser,
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    hospital_id_param: Optional[int] = Query(None, alias="hospital_id"),
    _: User = Depends(require_permission("vendor", "delete")),
):
    target_hospital_id = x_hospital_id if x_hospital_id is not None else hospital_id_param
    hospital_id = await get_tenant_hospital_id(current_user, target_hospital_id)
    await VendorService(db).delete_vendor(vendor_id, current_user.id, hospital_id=hospital_id, current_user=current_user)
    return APIResponse(message="Vendor deleted", data=MessageResponse(message="Soft deleted"))
