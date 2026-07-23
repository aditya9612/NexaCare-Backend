from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hospital_setting import HospitalSetting
from app.models.notification_setting import NotificationSetting
from app.models.user_preference import UserPreference
from app.models.appointment_setting import AppointmentSetting


class HospitalSettingRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, setting: HospitalSetting) -> HospitalSetting:
        self.db.add(setting)
        await self.db.flush()
        await self.db.refresh(setting)
        return setting

    async def get_by_hospital_id(self, hospital_id: int) -> HospitalSetting | None:
        result = await self.db.execute(
            select(HospitalSetting).where(HospitalSetting.hospital_id == hospital_id)
        )
        return result.scalar_one_or_none()

    async def update(self, setting: HospitalSetting) -> HospitalSetting:
        await self.db.flush()
        await self.db.refresh(setting)
        return setting


class NotificationSettingRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, setting: NotificationSetting) -> NotificationSetting:
        self.db.add(setting)
        await self.db.flush()
        await self.db.refresh(setting)
        return setting

    async def get_by_hospital_id(self, hospital_id: int) -> NotificationSetting | None:
        result = await self.db.execute(
            select(NotificationSetting).where(NotificationSetting.hospital_id == hospital_id)
        )
        return result.scalar_one_or_none()

    async def update(self, setting: NotificationSetting) -> NotificationSetting:
        await self.db.flush()
        await self.db.refresh(setting)
        return setting


class UserPreferenceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, preference: UserPreference) -> UserPreference:
        self.db.add(preference)
        await self.db.flush()
        await self.db.refresh(preference)
        return preference

    async def get_by_user_id(self, user_id: int) -> UserPreference | None:
        result = await self.db.execute(
            select(UserPreference).where(UserPreference.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def update(self, preference: UserPreference) -> UserPreference:
        await self.db.flush()
        await self.db.refresh(preference)
        return preference


class AppointmentSettingsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, setting: AppointmentSetting) -> AppointmentSetting:
        self.db.add(setting)
        await self.db.flush()
        await self.db.refresh(setting)
        return setting

    async def get_by_hospital_id(self, hospital_id: int) -> AppointmentSetting | None:
        result = await self.db.execute(
            select(AppointmentSetting).where(AppointmentSetting.hospital_id == hospital_id)
        )
        return result.scalar_one_or_none()

    async def update(self, setting: AppointmentSetting) -> AppointmentSetting:
        await self.db.flush()
        await self.db.refresh(setting)
        return setting
