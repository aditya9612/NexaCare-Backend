import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import AppointmentStatus, KPIStatus, ReportExportFormat, ReportExportStatus
from app.core.exceptions import NotFoundException
from app.models.analytics_model import AnalyticsReport, KPI, ReportExport
from app.models.appointment_model import Appointment
from app.models.billing_model import Billing
from app.models.chat_model import ChatSession
from app.models.doctor_model import Doctor
from app.models.patient_model import Patient
from app.models.voice_model import VoiceCall
from app.models.whatsapp_model import WhatsAppMessage
from app.repositories.analytics_repository import AnalyticsRepository
from app.repositories.chat_repository import ChatRepository
from app.repositories.voice_repository import VoiceRepository
from app.repositories.whatsapp_repository import WhatsAppRepository
from app.schemas.analytics_schema import (
    AppointmentAnalyticsResponse,
    ChartDataPoint,
    ChartSeries,
    DashboardSummaryResponse,
    DoctorAnalyticsResponse,
    ExportReportRequest,
    ExportReportResponse,
    ExportListItem,
    KPIResponse,
    ModuleAnalyticsResponse,
    PatientAnalyticsResponse,
    ReportListItem,
    RevenueAnalyticsResponse,
)
from app.services.chat_service import ChatService
from app.services.voice_service import VoiceService
from app.services.whatsapp_service import WhatsAppService
from app.utils.excel_generator import generate_excel_report
from app.utils.helpers import utc_now
from app.utils.pagination import build_paginated_result
from app.utils.pdf_generator import generate_lab_report_html
from app.utils.redis_service import cache_get, cache_set


class AnalyticsService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AnalyticsRepository(db)
        self.chat_repo = ChatRepository(db)
        self.voice_repo = VoiceRepository(db)
        self.whatsapp_repo = WhatsAppRepository(db)

    def _date_range(self, start: Optional[date], end: Optional[date]) -> tuple[datetime, datetime]:
        end_d = end or date.today()
        start_d = start or (end_d - timedelta(days=30))
        return (
            datetime.combine(start_d, datetime.min.time()),
            datetime.combine(end_d, datetime.max.time()),
        )

    async def get_dashboard(self) -> DashboardSummaryResponse:
        cached = await cache_get("analytics:dashboard")
        if cached:
            return DashboardSummaryResponse(**cached)

        today = date.today()
        revenue = await self.db.scalar(
            select(func.coalesce(func.sum(Billing.paid_amount), 0.0)).where(Billing.is_deleted.is_(False))
        ) or 0.0
        appointments_today = await self.db.scalar(
            select(func.count()).select_from(Appointment).where(Appointment.appointment_date == today)
        ) or 0
        total_patients = await self.db.scalar(
            select(func.count()).select_from(Patient).where(Patient.is_deleted.is_(False))
        ) or 0
        total_doctors = await self.db.scalar(
            select(func.count()).select_from(Doctor).where(Doctor.is_deleted.is_(False))
        ) or 0
        pending = await self.db.scalar(
            select(func.count()).select_from(Appointment).where(
                Appointment.appointment_status == AppointmentStatus.PENDING
            )
        ) or 0
        ai_sessions = await self.chat_repo.count_sessions()
        voice_today = await self.db.scalar(
            select(func.count()).select_from(VoiceCall).where(
                func.date(VoiceCall.created_at) == today
            )
        ) or 0
        wa_today = await self.db.scalar(
            select(func.count()).select_from(WhatsAppMessage).where(
                func.date(WhatsAppMessage.created_at) == today
            )
        ) or 0

        result = DashboardSummaryResponse(
            revenue=float(revenue),
            appointments_today=appointments_today,
            total_patients=total_patients,
            total_doctors=total_doctors,
            pending_appointments=pending,
            ai_chat_sessions=ai_sessions,
            voice_calls_today=voice_today,
            whatsapp_messages_today=wa_today,
            charts=[
                ChartSeries(
                    name="Appointments (7 days)",
                    data=await self._appointment_trend(7),
                )
            ],
        )
        await cache_set(
            "analytics:dashboard",
            result.model_dump(mode="json"),
            ttl=settings.ANALYTICS_CACHE_TTL_SECONDS,
        )
        return result

    async def cache_dashboard_summary(self) -> None:
        await self.get_dashboard()

    async def get_revenue_analytics(
        self, start_date: Optional[date] = None, end_date: Optional[date] = None
    ) -> RevenueAnalyticsResponse:
        start, end = self._date_range(start_date, end_date)
        bills = await self.db.execute(
            select(Billing).where(
                Billing.is_deleted.is_(False),
                Billing.created_at >= start,
                Billing.created_at <= end,
            )
        )
        items = list(bills.scalars().all())
        total = sum(b.total_amount for b in items)
        paid = sum(b.paid_amount for b in items)
        pending = sum(b.balance_amount for b in items)

        return RevenueAnalyticsResponse(
            total_revenue=round(total, 2),
            paid_amount=round(paid, 2),
            pending_amount=round(pending, 2),
            daily_revenue=await self._revenue_trend(start, end),
            payment_method_breakdown=[],
        )

    async def get_appointment_analytics(
        self, start_date: Optional[date] = None, end_date: Optional[date] = None
    ) -> AppointmentAnalyticsResponse:
        from app.models.department_model import Department
        start, end = self._date_range(start_date, end_date)
        result = await self.db.execute(
            select(Appointment).where(
                Appointment.created_at >= start,
                Appointment.created_at <= end,
            )
        )
        appts = list(result.scalars().all())
        status_counts: Dict[str, int] = {}
        for a in appts:
            status_counts[a.appointment_status] = status_counts.get(a.appointment_status, 0) + 1

        # Query department breakdown in the exact same date range
        dept_counts = await self.db.execute(
            select(
                Department.department_id,
                Department.department_name,
                func.count(Appointment.id)
            )
            .join(Appointment, Appointment.department_id == Department.department_id)
            .where(
                Appointment.created_at >= start,
                Appointment.created_at <= end,
            )
            .group_by(Department.department_id, Department.department_name)
        )
        
        department_breakdown = [
            ChartDataPoint(
                label=row[1],
                value=float(row[2]),
                metadata={"department_id": row[0]}
            )
            for row in dept_counts.all()
        ]

        return AppointmentAnalyticsResponse(
            total=len(appts),
            completed=status_counts.get(AppointmentStatus.COMPLETED, 0),
            cancelled=status_counts.get(AppointmentStatus.CANCELLED, 0),
            no_show=status_counts.get(AppointmentStatus.NO_SHOW, 0),
            status_breakdown=[
                ChartDataPoint(label=k, value=float(v)) for k, v in status_counts.items()
            ],
            daily_trend=await self._appointment_trend(30),
            department_breakdown=department_breakdown,
        )

    async def get_doctor_analytics(self) -> DoctorAnalyticsResponse:
        total = await self.db.scalar(
            select(func.count()).select_from(Doctor).where(Doctor.is_deleted.is_(False))
        ) or 0
        appt_counts = await self.db.execute(
            select(Doctor.id, Doctor.first_name, Doctor.last_name, func.count(Appointment.id))
            .join(Appointment, Appointment.doctor_id == Doctor.id, isouter=True)
            .where(Doctor.is_deleted.is_(False))
            .group_by(Doctor.id)
            .order_by(func.count(Appointment.id).desc())
            .limit(10)
        )
        top = [
            {"doctor_id": r[0], "name": f"{r[1]} {r[2]}", "appointments": r[3]}
            for r in appt_counts.all()
        ]
        avg = sum(t["appointments"] for t in top) / len(top) if top else 0.0

        avail = await self.db.execute(
            select(Doctor.availability_status, func.count(Doctor.id))
            .where(Doctor.is_deleted.is_(False))
            .group_by(Doctor.availability_status)
        )
        return DoctorAnalyticsResponse(
            total_doctors=total,
            avg_appointments_per_doctor=round(avg, 2),
            top_doctors=top,
            availability_breakdown=[
                ChartDataPoint(label=r[0] or "unknown", value=float(r[1])) for r in avail.all()
            ],
        )

    async def get_patient_analytics(self) -> PatientAnalyticsResponse:
        total = await self.db.scalar(
            select(func.count()).select_from(Patient).where(Patient.is_deleted.is_(False))
        ) or 0
        thirty_days_ago = utc_now() - timedelta(days=30)
        new_patients = await self.db.scalar(
            select(func.count()).select_from(Patient).where(
                Patient.is_deleted.is_(False),
                Patient.created_at >= thirty_days_ago,
            )
        ) or 0
        gender = await self.db.execute(
            select(Patient.gender, func.count(Patient.id))
            .where(Patient.is_deleted.is_(False))
            .group_by(Patient.gender)
        )

        # Query patient registrations grouped by date for the last 30 days
        trend_query = (
            select(func.date(Patient.created_at), func.count(Patient.id))
            .where(
                Patient.is_deleted.is_(False),
                Patient.created_at >= thirty_days_ago,
            )
            .group_by(func.date(Patient.created_at))
            .order_by(func.date(Patient.created_at).asc())
        )
        trend_res = await self.db.execute(trend_query)
        registration_trend = [
            ChartDataPoint(label=str(row[0]), value=float(row[1]))
            for row in trend_res.all()
        ]

        return PatientAnalyticsResponse(
            total_patients=total,
            new_patients=new_patients,
            active_patients=total,
            gender_breakdown=[
                ChartDataPoint(label=r[0] or "unknown", value=float(r[1])) for r in gender.all()
            ],
            registration_trend=registration_trend,
        )

    async def get_ai_chatbot_analytics(self) -> ModuleAnalyticsResponse:
        chat_analytics = await ChatService(self.db).get_analytics()
        now = utc_now()
        return ModuleAnalyticsResponse(
            module="ai_chatbot",
            period_start=now - timedelta(days=30),
            period_end=now,
            metrics=chat_analytics.model_dump(),
            charts=[
                ChartSeries(
                    name="Top Intents",
                    data=[
                        ChartDataPoint(label=i["intent"], value=float(i["count"]))
                        for i in chat_analytics.top_intents
                    ],
                )
            ],
        )

    async def get_voice_analytics(self) -> ModuleAnalyticsResponse:
        voice = await VoiceService(self.db).get_analytics()
        now = utc_now()
        return ModuleAnalyticsResponse(
            module="voice_reminder",
            period_start=now - timedelta(days=30),
            period_end=now,
            metrics=voice.model_dump(),
            charts=[
                ChartSeries(
                    name="Call Status",
                    data=[
                        ChartDataPoint(label=s["status"], value=float(s["count"]))
                        for s in voice.status_breakdown
                    ],
                )
            ],
        )

    async def get_whatsapp_analytics(self) -> ModuleAnalyticsResponse:
        wa = await WhatsAppService(self.db).get_analytics()
        now = utc_now()
        return ModuleAnalyticsResponse(
            module="whatsapp",
            period_start=now - timedelta(days=30),
            period_end=now,
            metrics=wa.model_dump(),
            charts=[],
        )

    async def list_kpis(self, category: str | None = None) -> List[KPIResponse]:
        kpis = await self.repo.list_kpis(category)
        if not kpis:
            await self._seed_default_kpis()
            kpis = await self.repo.list_kpis(category)
        return [KPIResponse.model_validate(k) for k in kpis]

    async def list_reports(self, page: int = 1, size: int = 20, report_type: str | None = None):
        skip = (page - 1) * size
        items = await self.repo.list_reports(skip=skip, limit=size, report_type=report_type)
        total = await self.repo.count_reports(report_type=report_type)
        return build_paginated_result(
            [ReportListItem.model_validate(r) for r in items], total, page, size
        )

    async def list_exports(self, page: int = 1, size: int = 20, report_type: str | None = None):
        skip = (page - 1) * size
        items = await self.repo.list_exports(skip=skip, limit=size, report_type=report_type)
        total = await self.repo.count_exports(report_type=report_type)
        return build_paginated_result(
            [ExportListItem.model_validate(r) for r in items], total, page, size
        )

    async def request_export(self, data: ExportReportRequest, user_id: int) -> ExportReportResponse:
        export = ReportExport(
            report_type=data.report_type,
            export_format=ReportExportFormat.PDF,
            status=ReportExportStatus.PENDING,
            filters=json.dumps(data.filters or {}),
            requested_by=user_id,
        )
        export = await self.repo.create_export(export)
        try:
            from app.tasks.analytics_tasks import generate_export

            generate_export.delay(export.id)
        except Exception:
            await self.process_export(export.id)
        return ExportReportResponse(
            export_id=export.id,
            status=export.status,
            file_path=export.file_path,
            message="Export queued for processing",
        )


    async def request_export_excel(self, data: ExportReportRequest, user_id: int) -> ExportReportResponse:
        export = ReportExport(
            report_type=data.report_type,
            export_format=ReportExportFormat.EXCEL,
            status=ReportExportStatus.PENDING,
            filters=json.dumps(data.filters or {}),
            requested_by=user_id,
        )
        export = await self.repo.create_export(export)
        try:
            from app.tasks.analytics_tasks import generate_export

            generate_export.delay(export.id)
        except Exception:
            await self.process_export(export.id)
        return ExportReportResponse(
            export_id=export.id,
            status=export.status,
            file_path=export.file_path,
            message="Excel export queued for processing",
        )


    async def process_export(self, export_id: int) -> None:
        export = await self.repo.get_export(export_id)
        if not export:
            raise NotFoundException("Export not found")

        export.status = ReportExportStatus.PROCESSING
        await self.repo.update_export(export)

        try:
            rows = await self._build_export_rows(export.report_type)
            if export.export_format == ReportExportFormat.EXCEL:
                file_path = generate_excel_report(export.report_type, rows)
            else:
                file_path = await generate_lab_report_html(
                    f"RPT-{export.id}",
                    {"title": export.report_type, "rows": rows},
                )
            export.status = ReportExportStatus.COMPLETED
            export.file_path = file_path
            export.completed_at = utc_now()
        except Exception as exc:
            export.status = ReportExportStatus.FAILED
            export.error_message = str(exc)

        await self.repo.update_export(export)

    async def _build_export_rows(self, report_type: str) -> List[Dict[str, Any]]:
        if report_type == "revenue":
            data = await self.get_revenue_analytics()
            return [data.model_dump()]
        if report_type == "appointments":
            data = await self.get_appointment_analytics()
            return [data.model_dump()]
        if report_type == "dashboard":
            data = await self.get_dashboard()
            return [data.model_dump()]
        return [{"report_type": report_type, "generated_at": utc_now().isoformat()}]

    async def _seed_default_kpis(self) -> None:
        defaults = [
            ("Monthly Revenue", "revenue", 0, 100000, KPIStatus.ON_TRACK, "INR"),
            ("Appointment Completion Rate", "appointments", 0, 85, KPIStatus.ON_TRACK, "%"),
            ("Patient Satisfaction", "patients", 0, 90, KPIStatus.ON_TRACK, "%"),
            ("AI Escalation Rate", "ai_chat", 0, 10, KPIStatus.ON_TRACK, "%"),
        ]
        for name, category, current, target, status, unit in defaults:
            await self.repo.upsert_kpi(
                KPI(
                    kpi_name=name,
                    category=category,
                    current_value=current,
                    target_value=target,
                    status=status,
                    unit=unit,
                )
            )

    async def _appointment_trend(self, days: int) -> List[ChartDataPoint]:
        points = []
        for i in range(days - 1, -1, -1):
            d = date.today() - timedelta(days=i)
            count = await self.db.scalar(
                select(func.count()).select_from(Appointment).where(Appointment.appointment_date == d)
            ) or 0
            points.append(ChartDataPoint(label=d.isoformat(), value=float(count)))
        return points

    async def _revenue_trend(self, start: datetime, end: datetime) -> List[ChartDataPoint]:
        result = await self.db.execute(
            select(func.date(Billing.created_at), func.sum(Billing.paid_amount))
            .where(Billing.is_deleted.is_(False), Billing.created_at >= start, Billing.created_at <= end)
            .group_by(func.date(Billing.created_at))
        )
        return [ChartDataPoint(label=str(r[0]), value=float(r[1] or 0)) for r in result.all()]
