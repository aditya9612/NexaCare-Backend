from fastapi import APIRouter, Depends, status
from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.branch_schema import BranchCreate, BranchUpdate, BranchResponse
from app.schemas.common_schema import APIResponse, MessageResponse
from app.services.branch_service import BranchService
from app.utils.pagination import PaginatedResult

router = APIRouter()

@router.post("", response_model=APIResponse[BranchResponse], status_code=status.HTTP_201_CREATED)
async def create_branch(
    data: BranchCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("branches", "create")),
):
    branch = await BranchService(db).create_branch(data, current_user)
    return APIResponse(message="Branch created successfully", data=branch)

@router.get("", response_model=APIResponse[PaginatedResult[BranchResponse]])
async def list_branches(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    hospital_id: int | None = None,
    _: User = Depends(require_permission("branches", "read")),
):
    result = await BranchService(db).list_branches(current_user, page=page, size=size, hospital_id=hospital_id)
    return APIResponse(message="Branches retrieved successfully", data=result)

@router.get("/{branch_id}", response_model=APIResponse[BranchResponse])
async def get_branch(
    branch_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("branches", "read")),
):
    branch = await BranchService(db).get_branch(branch_id, current_user)
    return APIResponse(message="Branch retrieved successfully", data=branch)

@router.put("/{branch_id}", response_model=APIResponse[BranchResponse])
async def update_branch(
    branch_id: int,
    data: BranchUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("branches", "update")),
):
    branch = await BranchService(db).update_branch(branch_id, data, current_user)
    return APIResponse(message="Branch updated successfully", data=branch)

@router.delete("/{branch_id}", response_model=APIResponse[MessageResponse])
async def delete_branch(
    branch_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("branches", "delete")),
):
    await BranchService(db).delete_branch(branch_id, current_user)
    return APIResponse(message="Branch deleted successfully", data=MessageResponse(message="Branch deleted"))
