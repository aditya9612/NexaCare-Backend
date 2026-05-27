from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import VoiceCallStatus
from app.models.voice_model import CallAnalytics, CallSchedule, VoiceCall, VoiceCallLog, VoiceResponse


class VoiceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_call(self, call: VoiceCall) -> VoiceCall:
        self.db.add(call)
        await self.db.flush()
        await self.db.refresh(call)
        return call

    async def get_call(self, call_id: int) -> VoiceCall | None:
        result = await self.db.execute(
            select(VoiceCall)
            .options(selectinload(VoiceCall.logs), selectinload(VoiceCall.responses))
            .where(VoiceCall.id == call_id)
        )
        return result.scalar_one_or_none()

    async def get_call_by_provider_sid(self, provider_sid: str) -> VoiceCall | None:
        result = await self.db.execute(
            select(VoiceCall).where(VoiceCall.provider_call_id == provider_sid)
        )
        return result.scalar_one_or_none()

    async def update_call(self, call: VoiceCall) -> VoiceCall:
        await self.db.flush()
        await self.db.refresh(call)
        return call

    async def add_log(self, log: VoiceCallLog) -> VoiceCallLog:
        self.db.add(log)
        await self.db.flush()
        await self.db.refresh(log)
        return log

    async def add_response(self, response: VoiceResponse) -> VoiceResponse:
        self.db.add(response)
        await self.db.flush()
        await self.db.refresh(response)
        return response

    async def create_schedule(self, schedule: CallSchedule) -> CallSchedule:
        self.db.add(schedule)
        await self.db.flush()
        await self.db.refresh(schedule)
        return schedule

    async def list_calls(
        self,
        skip: int = 0,
        limit: int = 20,
        patient_id: int | None = None,
        call_status: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[VoiceCall]:
        query = select(VoiceCall)
        query = self._apply_filters(query, patient_id, call_status, start, end)
        result = await self.db.execute(query.order_by(VoiceCall.scheduled_time.desc()).offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_calls(
        self,
        patient_id: int | None = None,
        call_status: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> int:
        query = select(func.count()).select_from(VoiceCall)
        query = self._apply_filters(query, patient_id, call_status, start, end)
        return await self.db.scalar(query) or 0

    def _apply_filters(self, query, patient_id, call_status, start, end):
        if patient_id:
            query = query.where(VoiceCall.patient_id == patient_id)
        if call_status:
            query = query.where(VoiceCall.call_status == call_status)
        if start:
            query = query.where(VoiceCall.scheduled_time >= start)
        if end:
            query = query.where(VoiceCall.scheduled_time <= end)
        return query

    async def list_pending_calls(self, limit: int = 50) -> list[VoiceCall]:
        result = await self.db.execute(
            select(VoiceCall)
            .where(VoiceCall.call_status == VoiceCallStatus.PENDING)
            .order_by(VoiceCall.scheduled_time.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def status_breakdown(self) -> list[tuple[str, int]]:
        result = await self.db.execute(
            select(VoiceCall.call_status, func.count(VoiceCall.id)).group_by(VoiceCall.call_status)
        )
        return list(result.all())

    async def language_breakdown(self) -> list[tuple[str, int]]:
        result = await self.db.execute(
            select(VoiceCall.language, func.count(VoiceCall.id)).group_by(VoiceCall.language)
        )
        return list(result.all())

    async def avg_duration(self) -> float:
        result = await self.db.scalar(
            select(func.avg(VoiceCall.duration_seconds)).where(VoiceCall.duration_seconds.isnot(None))
        )
        return float(result or 0.0)

    async def save_analytics(self, analytics: CallAnalytics) -> CallAnalytics:
        self.db.add(analytics)
        await self.db.flush()
        await self.db.refresh(analytics)
        return analytics
