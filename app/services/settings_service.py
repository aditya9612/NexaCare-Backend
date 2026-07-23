import json
import logging
from typing import Any, Dict

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.hospital_setting import HospitalSetting
from app.models.notification_setting import NotificationSetting
from app.models.user_preference import UserPreference
from app.repositories.settings_repository import (
    HospitalSettingRepository,
    NotificationSettingRepository,
    UserPreferenceRepository,
)
from app.utils.redis_service import cache_delete, cache_get, cache_set

logger = logging.getLogger(__name__)


class SettingsService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.hospital_repo = HospitalSettingRepository(db)
        self.notification_repo = NotificationSettingRepository(db)
        self.user_repo = UserPreferenceRepository(db)

    def _serialize(self, record) -> dict:
        """Helper to serialize SQLAlchemy models for Redis caching and API returns."""
        data = {}
        for c in record.__table__.columns:
            val = getattr(record, c.name)
            if hasattr(val, "isoformat"):
                val = val.isoformat()
            data[c.name] = val
        return data

    def _log_audit(self, category: str, old_data: dict, new_data: dict, user_id: int | None, hospital_id: int | None):
        """Standardized audit logger."""
        changed = {k: {"old": old_data.get(k), "new": new_data.get(k)} for k in new_data if new_data[k] != old_data.get(k) and k not in ["updated_at"]}
        if not changed:
            return
            
        logger.info(
            "AUDIT Settings Update | Category: %s | Changes: %s | User: %s | Hospital: %s",
            category,
            json.dumps(changed),
            user_id,
            hospital_id
        )

    async def _verify_entity_exists(self, repo, entity_id: int):
        from sqlalchemy import select
        from app.core.exceptions import NotFoundException
        if hasattr(repo, "get_by_hospital_id"):
            from app.models.hospital_model import Hospital
            res = await self.db.execute(select(Hospital.id).where(Hospital.id == entity_id))
            if not res.scalar_one_or_none():
                raise NotFoundException("Hospital not found")
        else:
            from app.models.user_model import User
            res = await self.db.execute(select(User.id).where(User.id == entity_id))
            if not res.scalar_one_or_none():
                raise NotFoundException("User not found")

    async def _get_with_fallback(self, cache_key: str, repo, entity_id: int, fallback_method) -> dict:
        """Core lookup logic handling cache, DB, fallback, and race conditions."""
        # Redis Read
        try:
            cached = await cache_get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning("Redis cache failure on get %s: %s", cache_key, e)

        # Database Read
        if hasattr(repo, "get_by_hospital_id"):
            record = await repo.get_by_hospital_id(entity_id)
        else:
            record = await repo.get_by_user_id(entity_id)

        # Auto-Create (Fallback)
        if not record:
            await self._verify_entity_exists(repo, entity_id)
            record = fallback_method(entity_id)
            try:
                record = await repo.create(record)
                await self.db.commit()
            except IntegrityError:
                await self.db.rollback()
                # Race condition recovered
                if hasattr(repo, "get_by_hospital_id"):
                    record = await repo.get_by_hospital_id(entity_id)
                else:
                    record = await repo.get_by_user_id(entity_id)
            except Exception:
                await self.db.rollback()
                raise

        # Redis Write
        data = self._serialize(record)
        try:
            await cache_set(cache_key, json.dumps(data), ttl=3600)
        except Exception as e:
            logger.warning("Redis cache failure on set %s: %s", cache_key, e)

        return data

    async def _update_with_audit(
        self, 
        repo, 
        entity_id: int, 
        update_data: dict, 
        category: str,
        user_id: int | None,
        hospital_id: int | None,
        cache_key: str,
        get_method
    ) -> dict:
        """Core update logic handling DB flush, commit, audit, and cache invalidation."""
        # Ensure record exists in DB first
        if hasattr(repo, "get_by_hospital_id"):
            record = await repo.get_by_hospital_id(entity_id)
        else:
            record = await repo.get_by_user_id(entity_id)
            
        if not record:
            await get_method(entity_id)
            if hasattr(repo, "get_by_hospital_id"):
                record = await repo.get_by_hospital_id(entity_id)
            else:
                record = await repo.get_by_user_id(entity_id)

        old_data = self._serialize(record)

        for key, value in update_data.items():
            if hasattr(record, key):
                setattr(record, key, value)

        record = await repo.update(record)
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        
        new_data = self._serialize(record)
        self._log_audit(category, old_data, new_data, user_id, hospital_id)

        try:
            await cache_delete(cache_key)
        except Exception as e:
            logger.warning("Redis cache failure on invalidate %s: %s", cache_key, e)

        return new_data

    # ---------------------------------------------------------
    # HOSPITAL SETTINGS
    # ---------------------------------------------------------
    def _default_hospital_setting(self, hospital_id: int) -> HospitalSetting:
        return HospitalSetting(
            hospital_id=hospital_id,
            timezone="UTC",
            currency="USD",
            gst_number=None,
            working_hours=settings.HOSPITAL_HOURS,
            contact_email=None,
            contact_phone=settings.HOSPITAL_CONTACT,
        )

    async def get_hospital_settings(self, hospital_id: int) -> dict:
        if not settings.ENABLE_SETTINGS:
            return self._serialize(self._default_hospital_setting(hospital_id))

        return await self._get_with_fallback(
            cache_key=f"settings:hospital:{hospital_id}",
            repo=self.hospital_repo,
            entity_id=hospital_id,
            fallback_method=self._default_hospital_setting
        )

    async def update_hospital_settings(self, hospital_id: int, update_data: dict, updated_by_user_id: int) -> dict:
        if not settings.ENABLE_SETTINGS:
            return self._serialize(self._default_hospital_setting(hospital_id))

        return await self._update_with_audit(
            repo=self.hospital_repo,
            entity_id=hospital_id,
            update_data=update_data,
            category="HospitalSettings",
            user_id=updated_by_user_id,
            hospital_id=hospital_id,
            cache_key=f"settings:hospital:{hospital_id}",
            get_method=self.get_hospital_settings
        )

    # ---------------------------------------------------------
    # NOTIFICATION SETTINGS
    # ---------------------------------------------------------
    def _default_notification_setting(self, hospital_id: int) -> NotificationSetting:
        return NotificationSetting(
            hospital_id=hospital_id,
            sms_on_appointment=True,
            email_on_appointment=True,
            sms_on_billing=False,
            email_on_billing=True,
        )

    async def get_notification_settings(self, hospital_id: int) -> dict:
        if not settings.ENABLE_SETTINGS:
            return self._serialize(self._default_notification_setting(hospital_id))

        return await self._get_with_fallback(
            cache_key=f"settings:notification:{hospital_id}",
            repo=self.notification_repo,
            entity_id=hospital_id,
            fallback_method=self._default_notification_setting
        )

    async def update_notification_settings(self, hospital_id: int, update_data: dict, updated_by_user_id: int) -> dict:
        if not settings.ENABLE_SETTINGS:
            return self._serialize(self._default_notification_setting(hospital_id))

        return await self._update_with_audit(
            repo=self.notification_repo,
            entity_id=hospital_id,
            update_data=update_data,
            category="NotificationSettings",
            user_id=updated_by_user_id,
            hospital_id=hospital_id,
            cache_key=f"settings:notification:{hospital_id}",
            get_method=self.get_notification_settings
        )

    # ---------------------------------------------------------
    # USER PREFERENCES
    # ---------------------------------------------------------
    def _default_user_preference(self, user_id: int) -> UserPreference:
        return UserPreference(
            user_id=user_id,
            theme="light",
            language="en",
            email_notifications=True,
            sms_notifications=True,
        )

    async def get_user_preferences(self, user_id: int) -> dict:
        if not settings.ENABLE_SETTINGS:
            return self._serialize(self._default_user_preference(user_id))

        return await self._get_with_fallback(
            cache_key=f"settings:user:{user_id}",
            repo=self.user_repo,
            entity_id=user_id,
            fallback_method=self._default_user_preference
        )

    async def update_user_preferences(self, user_id: int, update_data: dict) -> dict:
        if not settings.ENABLE_SETTINGS:
            return self._serialize(self._default_user_preference(user_id))

        return await self._update_with_audit(
            repo=self.user_repo,
            entity_id=user_id,
            update_data=update_data,
            category="UserPreferences",
            user_id=user_id,
            hospital_id=None,
            cache_key=f"settings:user:{user_id}",
            get_method=self.get_user_preferences
        )
