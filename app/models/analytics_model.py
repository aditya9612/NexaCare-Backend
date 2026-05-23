from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import KPIStatus, ReportExportFormat, ReportExportStatus
from app.core.database import Base
from app.models.mixins import TimestampMixin


class AnalyticsReport(Base, TimestampMixin):
    __tablename__ = "analytics_reports"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    report_name: Mapped[str] = mapped_column(String(150), index=True)
    report_type: Mapped[str] = mapped_column(String(50), index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime, index=True)
    report_data: Mapped[str] = mapped_column(Text)
    generated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class KPI(Base, TimestampMixin):
    __tablename__ = "kpis"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    kpi_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(50), index=True)
    current_value: Mapped[float] = mapped_column(Float, default=0.0)
    target_value: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(50), default=KPIStatus.ON_TRACK, index=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class DashboardMetric(Base, TimestampMixin):
    __tablename__ = "dashboard_metrics"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    metric_key: Mapped[str] = mapped_column(String(100), index=True)
    metric_label: Mapped[str] = mapped_column(String(150))
    category: Mapped[str] = mapped_column(String(50), index=True)
    value: Mapped[float] = mapped_column(Float, default=0.0)
    previous_value: Mapped[float] = mapped_column(Float, default=0.0)
    change_percent: Mapped[float] = mapped_column(Float, default=0.0)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class ReportExport(Base, TimestampMixin):
    __tablename__ = "report_exports"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    report_type: Mapped[str] = mapped_column(String(50), index=True)
    export_format: Mapped[str] = mapped_column(String(20), default=ReportExportFormat.PDF)
    status: Mapped[str] = mapped_column(String(50), default=ReportExportStatus.PENDING, index=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    filters: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class AIAnalytics(Base, TimestampMixin):
    __tablename__ = "ai_analytics"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime, index=True)
    total_sessions: Mapped[int] = mapped_column(Integer, default=0)
    total_messages: Mapped[int] = mapped_column(Integer, default=0)
    escalated_sessions: Mapped[int] = mapped_column(Integer, default=0)
    avg_messages_per_session: Mapped[float] = mapped_column(Float, default=0.0)
    top_intents: Mapped[str | None] = mapped_column(Text, nullable=True)
    language_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    avg_sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)
