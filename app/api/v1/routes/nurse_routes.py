from fastapi import APIRouter, Depends

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.nurse_schema import NurseCreate, NurseResponse, NurseUpdate
from app.services.nurse_service import NurseService
from app.utils.pagination import PaginatedResult

router = APIRouter()


@router.post("", response_model=APIResponse[NurseResponse], status_code=201)
async def create_nurse(
    data: NurseCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("nurses", "create")),
):
    nurse = await NurseService(db).create(data, current_user.id)
    return APIResponse(message="Nurse created", data=nurse)


@router.get("", response_model=APIResponse[PaginatedResult[NurseResponse]])
async def list_nurses(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    department_id: int | None = None,
    shift: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    _: User = Depends(require_permission("nurses", "read")),
):
    result = await NurseService(db).list_nurses(
        page=page, size=size, department_id=department_id,
        shift=shift, sort_by=sort_by, sort_order=sort_order,
    )
    return APIResponse(message="Nurses retrieved", data=result)


@router.get("/search", response_model=APIResponse[PaginatedResult[NurseResponse]])
async def search_nurses(
    q: str,
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_permission("nurses", "read")),
):
    result = await NurseService(db).search(q, page=page, size=size)
    return APIResponse(message="Search results", data=result)


@router.get("/{nurse_id}", response_model=APIResponse[NurseResponse])
async def get_nurse(
    nurse_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("nurses", "read")),
):
    nurse = await NurseService(db).get_by_id(nurse_id)
    return APIResponse(message="Nurse retrieved", data=nurse)


@router.put("/{nurse_id}", response_model=APIResponse[NurseResponse])
async def update_nurse(
    nurse_id: int,
    data: NurseUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("nurses", "update")),
):
    nurse = await NurseService(db).update(nurse_id, data, current_user.id)
    return APIResponse(message="Nurse updated", data=nurse)


@router.delete("/{nurse_id}", response_model=APIResponse[MessageResponse])
async def delete_nurse(
    nurse_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("nurses", "delete")),
):
    await NurseService(db).delete(nurse_id, current_user.id)
    return APIResponse(message="Nurse deleted", data=MessageResponse(message="Deleted successfully"))
