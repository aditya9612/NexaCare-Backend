from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics_model import AIAnalytics, AnalyticsReport, DashboardMetric, KPI, ReportExport


class AnalyticsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_kpis(self, category: str | None = None) -> list[KPI]:
        query = select(KPI)
        if category:
            query = query.where(KPI.category == category)
        result = await self.db.execute(query.order_by(KPI.kpi_name))
        return list(result.scalars().all())

    async def get_kpi(self, kpi_id: int) -> KPI | None:
        result = await self.db.execute(select(KPI).where(KPI.id == kpi_id))
        return result.scalar_one_or_none()

    async def upsert_kpi(self, kpi: KPI) -> KPI:
        self.db.add(kpi)
        await self.db.flush()
        await self.db.refresh(kpi)
        return kpi

    async def create_report(self, report: AnalyticsReport) -> AnalyticsReport:
        self.db.add(report)
        await self.db.flush()
        await self.db.refresh(report)
        return report

    async def list_reports(self, skip: int = 0, limit: int = 20, report_type: str | None = None) -> list[AnalyticsReport]:
        query = select(AnalyticsReport)
        if report_type:
            query = query.where(AnalyticsReport.report_type == report_type)
        result = await self.db.execute(query.order_by(AnalyticsReport.created_at.desc()).offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_reports(self, report_type: str | None = None) -> int:
        query = select(func.count()).select_from(AnalyticsReport)
        if report_type:
            query = query.where(AnalyticsReport.report_type == report_type)
        return await self.db.scalar(query) or 0

    async def create_export(self, export: ReportExport) -> ReportExport:
        self.db.add(export)
        await self.db.flush()
        await self.db.refresh(export)
        return export

    async def get_export(self, export_id: int) -> ReportExport | None:
        result = await self.db.execute(select(ReportExport).where(ReportExport.id == export_id))
        return result.scalar_one_or_none()

    async def update_export(self, export: ReportExport) -> ReportExport:
        await self.db.flush()
        await self.db.refresh(export)
        return export

    async def save_dashboard_metric(self, metric: DashboardMetric) -> DashboardMetric:
        self.db.add(metric)
        await self.db.flush()
        await self.db.refresh(metric)
        return metric

    async def save_ai_analytics(self, analytics: AIAnalytics) -> AIAnalytics:
        self.db.add(analytics)
        await self.db.flush()
        await self.db.refresh(analytics)
        return analytics
