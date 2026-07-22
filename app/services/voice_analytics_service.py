from datetime import datetime
from typing import Optional

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import VoiceCallStatus
from app.models.voice_model import VoiceCall
from app.schemas.hospital_voice_schema import VoiceAnalyticsSummary
from app.utils.redis_service import cache_get, cache_set


class VoiceAnalyticsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def summary(
        self,
        hospital_id: int | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> VoiceAnalyticsSummary:
        period = f"{start.isoformat() if start else 'all'}:{end.isoformat() if end else 'all'}"
        cache_key = f"voice:analytics:{hospital_id or 'all'}:{period}"
        cached = await cache_get(cache_key)
        if cached:
            return VoiceAnalyticsSummary.model_validate(cached)

        filters = []
        if hospital_id is not None:
            filters.append(VoiceCall.hospital_id == hospital_id)
        if start is not None:
            filters.append(VoiceCall.created_at >= start)
        if end is not None:
            filters.append(VoiceCall.created_at <= end)

        async def _scalar(stmt):
            for f in filters:
                stmt = stmt.where(f)
            return await self.db.scalar(stmt) or 0

        total = await _scalar(select(func.count()).select_from(VoiceCall))
        completed = await _scalar(
            select(func.count()).select_from(VoiceCall).where(
                VoiceCall.call_status == VoiceCallStatus.COMPLETED
            )
        )
        failed = await _scalar(
            select(func.count()).select_from(VoiceCall).where(
                VoiceCall.call_status == VoiceCallStatus.FAILED
            )
        )
        booking_success = await _scalar(
            select(func.count()).select_from(VoiceCall).where(VoiceCall.booking_success.is_(True))
        )
        transfer_count = await _scalar(
            select(func.count())
            .select_from(VoiceCall)
            .where(VoiceCall.transferred_to_reception.is_(True))
        )
        faq_success = await _scalar(
            select(func.count()).select_from(VoiceCall).where(VoiceCall.faq_hit.is_(True))
        )
        ai_fallback = await _scalar(
            select(func.count()).select_from(VoiceCall).where(VoiceCall.ai_fallback.is_(True))
        )
        retry_count = await _scalar(select(func.coalesce(func.sum(VoiceCall.retry_count), 0)))
        avg_duration = await _scalar(
            select(func.coalesce(func.avg(VoiceCall.duration_seconds), 0.0))
        )

        lang_stmt = select(VoiceCall.language, func.count()).group_by(VoiceCall.language)
        for f in filters:
            lang_stmt = lang_stmt.where(f)
        lang_rows = (await self.db.execute(lang_stmt)).all()
        language_distribution = [{"language": lang or "unknown", "count": cnt} for lang, cnt in lang_rows]

        provider_stmt = select(
            VoiceCall.provider,
            func.count(),
            func.sum(
                case((VoiceCall.call_status == VoiceCallStatus.COMPLETED, 1), else_=0)
            ),
            func.sum(
                case((VoiceCall.call_status == VoiceCallStatus.FAILED, 1), else_=0)
            ),
        ).group_by(VoiceCall.provider)
        for f in filters:
            provider_stmt = provider_stmt.where(f)
        provider_rows = (await self.db.execute(provider_stmt)).all()

        provider_breakdown = []
        twilio_calls = 0
        exotel_calls = 0
        twilio_completed = 0
        exotel_completed = 0
        for provider, cnt, completed_cnt, failed_cnt in provider_rows:
            name = (provider or "unknown").lower()
            total_p = int(cnt or 0)
            done_p = int(completed_cnt or 0)
            fail_p = int(failed_cnt or 0)
            success_rate = round((done_p / total_p) * 100, 2) if total_p else 0.0
            provider_breakdown.append(
                {
                    "provider": name,
                    "count": total_p,
                    "completed": done_p,
                    "failed": fail_p,
                    "success_rate": success_rate,
                }
            )
            if name == "twilio":
                twilio_calls = total_p
                twilio_completed = done_p
            elif name == "exotel":
                exotel_calls = total_p
                exotel_completed = done_p

        summary = VoiceAnalyticsSummary(
            total_calls=int(total),
            booking_success=int(booking_success),
            language_distribution=language_distribution,
            transfer_count=int(transfer_count),
            avg_duration_seconds=round(float(avg_duration or 0.0), 2),
            faq_success=int(faq_success),
            ai_fallback=int(ai_fallback),
            retry_count=int(retry_count),
            completed_calls=int(completed),
            failed_calls=int(failed),
            provider_breakdown=provider_breakdown,
            twilio_calls=twilio_calls,
            exotel_calls=exotel_calls,
            twilio_success_rate=round((twilio_completed / twilio_calls) * 100, 2)
            if twilio_calls
            else 0.0,
            exotel_success_rate=round((exotel_completed / exotel_calls) * 100, 2)
            if exotel_calls
            else 0.0,
        )
        await cache_set(
            cache_key,
            summary.model_dump(mode="json"),
            ttl=settings.ANALYTICS_CACHE_TTL_SECONDS,
        )
        return summary
