from datetime import datetime

from pydantic import Field

from app.schemas.common_schema import BaseSchema


class RoleCreate(BaseSchema):
    name: str = Field(..., min_length=2, max_length=50)
    description: str | None = None


class RoleUpdate(BaseSchema):
    name: str | None = Field(None, min_length=2, max_length=50)
    description: str | None = None


class RoleResponse(BaseSchema):
    id: int
    name: str
    description: str | None


class PermissionResponse(BaseSchema):
    id: int
    name: str
    resource: str
    action: str
    description: str | None


class PermissionCreate(BaseSchema):
    name: str
    resource: str
    action: str
    description: str | None = None


class RolePermissionCreate(BaseSchema):
    role_id: int
    permission_id: int


class RolePermissionResponse(BaseSchema):
    id: int
    role_id: int
    permission_id: int
    role_name: str | None = None
    permission_name: str | None = None
    created_at: datetime | None = None
