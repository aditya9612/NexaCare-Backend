import re
from datetime import datetime

from pydantic import Field, field_validator, model_validator

from app.schemas.common_schema import BaseSchema


def validate_role_name(value: str | None, required: bool = True) -> str | None:
    if value is None:
        if required:
            raise ValueError("Role name is required")
        return value
        
    # Check for empty / whitespace / null string
    if not value or not value.strip() or value.lower() == "null":
        raise ValueError("Role name cannot be blank or 'null'")
        
    # Check for leading/trailing spaces
    if value.startswith(" ") or value.endswith(" "):
        raise ValueError("Role name should not contain leading or trailing spaces")
        
    stripped = value.strip()
    
    # Check if only contains alphabets and spaces
    if not re.match(r"^[a-zA-Z\s]+$", stripped):
        raise ValueError("Role name must contain only alphabets and spaces")
        
    if "  " in stripped:
        raise ValueError("Role name should not contain consecutive spaces")
        
    return stripped


class RoleCreate(BaseSchema):
    name: str = Field(..., min_length=2, max_length=50)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        res = validate_role_name(value, required=True)
        if res is None:
            raise ValueError("Role name is required")
        return res


class RoleUpdate(BaseSchema):
    name: str | None = Field(None, min_length=2, max_length=50)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return validate_role_name(value, required=False)


class RoleResponse(BaseSchema):
    id: int
    name: str
    description: str | None


def validate_permission_name(value: str | None, required: bool = True) -> str | None:
    if value is None:
        if required:
            raise ValueError("Permission name is required")
        return value
    if not value or not value.strip() or value.lower() == "null":
        raise ValueError("Permission name cannot be blank or 'null'")
    if value.startswith(" ") or value.endswith(" "):
        raise ValueError("Permission name should not contain leading or trailing spaces")
    stripped = value.strip()
    if not re.match(r"^[a-z_]+:[a-z_]+$", stripped):
        raise ValueError("Permission name must contain only lowercase letters and underscores, formatted as 'resource:action'")
    return stripped


def validate_permission_field(field_name: str, value: str | None, required: bool = True) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{field_name} is required")
        return value
    if not value or not value.strip() or value.lower() == "null":
        raise ValueError(f"{field_name} cannot be blank or 'null'")
    if value.startswith(" ") or value.endswith(" "):
        raise ValueError(f"{field_name} should not contain leading or trailing spaces")
    stripped = value.strip()
    if not re.match(r"^[a-z_]+$", stripped):
        raise ValueError(f"{field_name} must contain only lowercase letters and underscores")
    return stripped


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

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        res = validate_permission_name(value, required=True)
        if res is None:
            raise ValueError("Permission name is required")
        return res

    @field_validator("resource")
    @classmethod
    def validate_resource(cls, value: str) -> str:
        res = validate_permission_field("Resource", value, required=True)
        if res is None:
            raise ValueError("Resource is required")
        return res

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str) -> str:
        res = validate_permission_field("Action", value, required=True)
        if res is None:
            raise ValueError("Action is required")
        return res

    @model_validator(mode="after")
    def validate_name_matches_resource_action(self) -> "PermissionCreate":
        if self.name != f"{self.resource}:{self.action}":
            raise ValueError(f"Permission name '{self.name}' must be exactly '{self.resource}:{self.action}'")
        return self


class PermissionUpdate(BaseSchema):
    name: str | None = None
    resource: str | None = None
    action: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return validate_permission_name(value, required=False)

    @field_validator("resource")
    @classmethod
    def validate_resource(cls, value: str | None) -> str | None:
        return validate_permission_field("Resource", value, required=False)

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str | None) -> str | None:
        return validate_permission_field("Action", value, required=False)



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
