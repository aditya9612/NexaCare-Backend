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


from pydantic import field_validator
from datetime import datetime, timezone

class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_validator("*", mode="before")
    @classmethod
    def coerce_zero_datetime(cls, v: any) -> any:
        if isinstance(v, str) and (v.startswith("0000-00-00") or v == "0000-00-00 00:00:00"):
            return datetime(1970, 1, 1)
        return v

    @field_validator("*", mode="after")
    @classmethod
    def localize_datetime(cls, v: any) -> any:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v



class IDSchema(BaseSchema):
    id: int


class PaginationQuery(BaseModel):
    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=100)
    sort_by: str = "created_at"
    sort_order: str = Field("desc", pattern="^(asc|desc)$")
