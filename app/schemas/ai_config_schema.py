from datetime import datetime
from pydantic import Field
from app.schemas.common_schema import BaseSchema

class AIConfigBase(BaseSchema):
    feature_name: str = Field(..., min_length=2, max_length=100)
    description: str | None = Field(None, max_length=255)
    is_enabled: bool = True
    config_data: str | None = None

class AIConfigCreate(AIConfigBase):
    pass

class AIConfigUpdate(BaseSchema):
    description: str | None = Field(None, max_length=255)
    is_enabled: bool | None = None
    config_data: str | None = None

class AIConfigResponse(AIConfigBase):
    id: int
    created_at: datetime
    updated_at: datetime

class AIFeatureToggleRequest(BaseSchema):
    feature_name: str = Field(..., min_length=2, max_length=100)
    is_enabled: bool
