from fastapi import APIRouter, Depends, Query

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.vendor_schema import VendorCreate, VendorUpdate, VendorResponse
from app.services.vendor_service import VendorService
from app.utils.pagination import PaginatedResult

router = APIRouter()


@router.post("", response_model=APIResponse[VendorResponse], status_code=201)
async def create_vendor(
    data: VendorCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("vendor", "create")),
):
    vendor = await VendorService(db).create_vendor(data, current_user.id)
    return APIResponse(message="Vendor created", data=vendor)


@router.get("", response_model=APIResponse[PaginatedResult[VendorResponse]])
async def list_vendors(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    vendor_type: str | None = Query(None, pattern="^(expenses|inventory)$"),
    _: User = Depends(require_permission("vendor", "read")),
):
    result = await VendorService(db).list_vendors(page=page, size=size, vendor_type=vendor_type)
    return APIResponse(message="Vendors retrieved", data=result)


@router.get("/{vendor_id}", response_model=APIResponse[VendorResponse])
async def get_vendor(
    vendor_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("vendor", "read")),
):
    vendor = await VendorService(db).get_vendor(vendor_id)
    return APIResponse(message="Vendor retrieved", data=vendor)


@router.patch("/{vendor_id}", response_model=APIResponse[VendorResponse])
async def update_vendor(
    vendor_id: int,
    data: VendorUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("vendor", "update")),
):
    vendor = await VendorService(db).update_vendor(vendor_id, data, current_user.id)
    return APIResponse(message="Vendor updated", data=vendor)


@router.delete("/{vendor_id}", response_model=APIResponse[MessageResponse])
async def delete_vendor(
    vendor_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("vendor", "delete")),
):
    await VendorService(db).delete_vendor(vendor_id, current_user.id)
    return APIResponse(message="Vendor deleted", data=MessageResponse(message="Soft deleted"))
