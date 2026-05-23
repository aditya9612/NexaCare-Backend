from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    success: bool = True
    message: str = "Success"
    data: Optional[T] = None


def success_response(data: Any = None, message: str = "Success") -> dict:
    return {"success": True, "message": message, "data": data}


def error_response(message: str, data: Any = None) -> dict:
    return {"success": False, "message": message, "data": data}
