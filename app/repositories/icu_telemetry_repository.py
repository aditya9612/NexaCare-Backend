from datetime import datetime
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.icu_telemetry_model import IcuDevice, IcuTelemetryAlert, IcuVitalReading


class IcuDeviceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, device_id: int) -> Optional[IcuDevice]:
        result = await self.db.execute(
            select(IcuDevice)
            .where(IcuDevice.id == device_id)
            .options(selectinload(IcuDevice.bed))
        )
        return result.scalar_one_or_none()

    async def get_by_api_key_hash(self, api_key_hash: str) -> Optional[IcuDevice]:
        result = await self.db.execute(
            select(IcuDevice)
            .where(IcuDevice.api_key_hash == api_key_hash, IcuDevice.is_active.is_(True))
            .options(selectinload(IcuDevice.bed))
        )
        return result.scalar_one_or_none()

    async def get_by_serial(self, device_serial: str) -> Optional[IcuDevice]:
        result = await self.db.execute(
            select(IcuDevice).where(IcuDevice.device_serial == device_serial)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[IcuDevice]:
        result = await self.db.execute(
            select(IcuDevice)
            .options(selectinload(IcuDevice.bed))
            .order_by(IcuDevice.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(self, device: IcuDevice) -> IcuDevice:
        self.db.add(device)
        await self.db.flush()
        await self.db.refresh(device)
        return device

    async def update_last_seen(self, device: IcuDevice, seen_at) -> None:
        device.last_seen_at = seen_at
        await self.db.flush()

    async def get_active_for_bed(self, bed_id: int, exclude_device_id: int | None = None) -> Optional[IcuDevice]:
        query = select(IcuDevice).where(IcuDevice.bed_id == bed_id, IcuDevice.is_active.is_(True))
        if exclude_device_id is not None:
            query = query.where(IcuDevice.id != exclude_device_id)
        result = await self.db.execute(query.limit(1))
        return result.scalar_one_or_none()

    async def save(self, device: IcuDevice) -> IcuDevice:
        await self.db.flush()
        await self.db.refresh(device)
        return device


class IcuVitalReadingRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, reading: IcuVitalReading) -> IcuVitalReading:
        self.db.add(reading)
        await self.db.flush()
        await self.db.refresh(reading)
        return reading

    async def get_by_id(self, reading_id: int) -> Optional[IcuVitalReading]:
        result = await self.db.execute(
            select(IcuVitalReading)
            .where(IcuVitalReading.id == reading_id)
            .options(
                selectinload(IcuVitalReading.bed),
                selectinload(IcuVitalReading.patient),
            )
        )
        return result.scalar_one_or_none()

    async def get_latest_for_bed(self, bed_id: int) -> Optional[IcuVitalReading]:
        result = await self.db.execute(
            select(IcuVitalReading)
            .where(IcuVitalReading.bed_id == bed_id)
            .options(
                selectinload(IcuVitalReading.bed),
                selectinload(IcuVitalReading.patient),
            )
            .order_by(IcuVitalReading.recorded_at.desc(), IcuVitalReading.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_for_patient(self, patient_id: int) -> Optional[IcuVitalReading]:
        result = await self.db.execute(
            select(IcuVitalReading)
            .where(IcuVitalReading.patient_id == patient_id)
            .options(
                selectinload(IcuVitalReading.bed),
                selectinload(IcuVitalReading.patient),
            )
            .order_by(IcuVitalReading.recorded_at.desc(), IcuVitalReading.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_per_bed(self, bed_ids: list[int] | None = None) -> list[IcuVitalReading]:
        subq = (
            select(
                IcuVitalReading.bed_id,
                func.max(IcuVitalReading.recorded_at).label("max_recorded_at"),
            )
            .group_by(IcuVitalReading.bed_id)
        )
        if bed_ids:
            subq = subq.where(IcuVitalReading.bed_id.in_(bed_ids))
        subq = subq.subquery()

        query = (
            select(IcuVitalReading)
            .join(
                subq,
                and_(
                    IcuVitalReading.bed_id == subq.c.bed_id,
                    IcuVitalReading.recorded_at == subq.c.max_recorded_at,
                ),
            )
            .options(
                selectinload(IcuVitalReading.bed),
                selectinload(IcuVitalReading.patient),
            )
            .order_by(IcuVitalReading.bed_id.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    def _history_filters(
        self,
        *,
        bed_id: int | None = None,
        patient_id: int | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ):
        conditions = []
        if bed_id is not None:
            conditions.append(IcuVitalReading.bed_id == bed_id)
        if patient_id is not None:
            conditions.append(IcuVitalReading.patient_id == patient_id)
        if from_time is not None:
            conditions.append(IcuVitalReading.recorded_at >= from_time)
        if to_time is not None:
            conditions.append(IcuVitalReading.recorded_at <= to_time)
        return conditions

    async def list_history(
        self,
        *,
        bed_id: int | None = None,
        patient_id: int | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[IcuVitalReading]:
        conditions = self._history_filters(
            bed_id=bed_id,
            patient_id=patient_id,
            from_time=from_time,
            to_time=to_time,
        )
        query = (
            select(IcuVitalReading)
            .where(*conditions)
            .options(
                selectinload(IcuVitalReading.bed),
                selectinload(IcuVitalReading.patient),
            )
            .order_by(IcuVitalReading.recorded_at.desc(), IcuVitalReading.id.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_history(
        self,
        *,
        bed_id: int | None = None,
        patient_id: int | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> int:
        conditions = self._history_filters(
            bed_id=bed_id,
            patient_id=patient_id,
            from_time=from_time,
            to_time=to_time,
        )
        return (
            await self.db.scalar(
                select(func.count()).select_from(IcuVitalReading).where(*conditions)
            )
        ) or 0


class IcuTelemetryAlertRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, alert: IcuTelemetryAlert) -> IcuTelemetryAlert:
        self.db.add(alert)
        await self.db.flush()
        await self.db.refresh(alert)
        return alert

    async def get_by_id(self, alert_id: int) -> Optional[IcuTelemetryAlert]:
        result = await self.db.execute(
            select(IcuTelemetryAlert)
            .where(IcuTelemetryAlert.id == alert_id)
            .options(
                selectinload(IcuTelemetryAlert.bed),
                selectinload(IcuTelemetryAlert.patient),
            )
        )
        return result.scalar_one_or_none()

    async def get_active_for_bed_and_vital(
        self, bed_id: int, vital_type: str
    ) -> Optional[IcuTelemetryAlert]:
        result = await self.db.execute(
            select(IcuTelemetryAlert).where(
                IcuTelemetryAlert.bed_id == bed_id,
                IcuTelemetryAlert.vital_type == vital_type,
                IcuTelemetryAlert.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def list_active(self, skip: int = 0, limit: int = 50) -> list[IcuTelemetryAlert]:
        result = await self.db.execute(
            select(IcuTelemetryAlert)
            .where(IcuTelemetryAlert.status == "active")
            .options(
                selectinload(IcuTelemetryAlert.bed),
                selectinload(IcuTelemetryAlert.patient),
            )
            .order_by(IcuTelemetryAlert.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_active_for_beds(self, bed_ids: list[int]) -> dict[int, int]:
        if not bed_ids:
            return {}
        result = await self.db.execute(
            select(IcuTelemetryAlert.bed_id, func.count())
            .where(
                IcuTelemetryAlert.bed_id.in_(bed_ids),
                IcuTelemetryAlert.status == "active",
            )
            .group_by(IcuTelemetryAlert.bed_id)
        )
        return {bed_id: count for bed_id, count in result.all()}

    async def count_active(self) -> int:
        return (
            await self.db.scalar(
                select(func.count())
                .select_from(IcuTelemetryAlert)
                .where(IcuTelemetryAlert.status == "active")
            )
        ) or 0
