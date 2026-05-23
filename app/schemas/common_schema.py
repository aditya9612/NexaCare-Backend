from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class MessageResponse(BaseModel):
    message: str
    success: bool = True


class APIResponse(BaseModel, Generic[T]):
    success: bool = True
    message: str = "Success"
    data: Optional[T] = None


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    size: int
    pages: int


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class IDSchema(BaseSchema):
    id: int


class PaginationQuery(BaseModel):
    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=100)
    sort_by: str = "created_at"
    sort_order: str = Field("desc", pattern="^(asc|desc)$")
