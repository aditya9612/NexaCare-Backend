import math
from typing import Generic, List, Sequence, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=100)
    sort_by: str = "created_at"
    sort_order: str = Field("desc", pattern="^(asc|desc)$")

    @property
    def skip(self) -> int:
        return (self.page - 1) * self.size


class PaginatedResult(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    size: int
    pages: int


def build_paginated_result(
    items: Sequence[T],
    total: int,
    page: int,
    size: int,
) -> PaginatedResult[T]:
    pages = math.ceil(total / size) if size else 0
    return PaginatedResult(
        items=list(items),
        total=total,
        page=page,
        size=size,
        pages=pages,
    )
