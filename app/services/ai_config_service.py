from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import NotFoundException
from app.models.ai_config_model import AIConfiguration
from app.repositories.ai_config_repository import AIConfigRepository
from app.repositories.audit_repository import AuditRepository
from app.schemas.ai_config_schema import (
    AIConfigResponse,
    AIConfigUpdate,
    AIFeatureToggleRequest,
)

class AIConfigService:
    def __init__(self, db: AsyncSession):
        self.repo = AIConfigRepository(db)
        self.audit_repo = AuditRepository(db)

    async def _ensure_default_configs(self) -> None:
        defaults = [
            ("chatbot", "Chatbot for symptom analysis and emergency class"),
            ("voice_assistant", "AI Voice call appointment booking assistant"),
            ("whatsapp", "WhatsApp reminders and campaign management")
        ]
        for name, desc in defaults:
            existing = await self.repo.get_by_feature_name(name)
            if not existing:
                config = AIConfiguration(
                    feature_name=name,
                    description=desc,
                    is_enabled=True,
                    config_data="{}"
                )
                await self.repo.create(config)

    async def list_configurations(self) -> list[AIConfigResponse]:
        await self._ensure_default_configs()
        configs = await self.repo.list_configs()
        return [AIConfigResponse.model_validate(c) for c in configs]

    async def update_configuration(self, feature_name: str, data: AIConfigUpdate, user_id: int) -> AIConfigResponse:
        await self._ensure_default_configs()
        config = await self.repo.get_by_feature_name(feature_name)
        if not config:
            raise NotFoundException(f"AI Configuration for '{feature_name}' not found")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(config, key, value)
        config = await self.repo.update(config)
        await self.audit_repo.create("update", "ai_configurations", user_id=user_id, resource_id=str(config.id))
        return AIConfigResponse.model_validate(config)

    async def toggle_feature(self, data: AIFeatureToggleRequest, user_id: int) -> AIConfigResponse:
        await self._ensure_default_configs()
        config = await self.repo.get_by_feature_name(data.feature_name)
        if not config:
            raise NotFoundException(f"AI Configuration for '{data.feature_name}' not found")
        config.is_enabled = data.is_enabled
        config = await self.repo.update(config)
        await self.audit_repo.create("toggle", "ai_configurations", user_id=user_id, resource_id=str(config.id))
        return AIConfigResponse.model_validate(config)
