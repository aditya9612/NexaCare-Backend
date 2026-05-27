from fastapi import APIRouter, Depends, status
from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.department_schema import DepartmentCreate, DepartmentUpdate, DepartmentResponse
from app.schemas.common_schema import APIResponse, MessageResponse
from app.services.department_service import DepartmentService
from app.utils.pagination import PaginatedResult

router = APIRouter()

@router.post("", response_model=APIResponse[DepartmentResponse], status_code=status.HTTP_201_CREATED)
async def create_department(
    data: DepartmentCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("departments", "create")),
):
    department = await DepartmentService(db).create(data)
    return APIResponse(message="Department created successfully", data=department)

@router.get("", response_model=APIResponse[PaginatedResult[DepartmentResponse]])
async def list_departments(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_permission("departments", "read")),
):
    result = await DepartmentService(db).list_departments(page=page, size=size)
    return APIResponse(message="Departments retrieved", data=result)

@router.get("/{department_id}", response_model=APIResponse[DepartmentResponse])
async def get_department(
    department_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("departments", "read")),
):
    department = await DepartmentService(db).get_by_id(department_id)
    return APIResponse(message="Department retrieved", data=department)

@router.put("/{department_id}", response_model=APIResponse[DepartmentResponse])
async def update_department(
    department_id: int,
    data: DepartmentUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("departments", "update")),
):
    department = await DepartmentService(db).update(department_id, data)
    return APIResponse(message="Department updated successfully", data=department)

@router.delete("/{department_id}", response_model=APIResponse[MessageResponse])
async def delete_department(
    department_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("departments", "delete")),
):
    await DepartmentService(db).delete(department_id)
    return APIResponse(message="Department deleted successfully", data=MessageResponse(message="Department deleted"))
