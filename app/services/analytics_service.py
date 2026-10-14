import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import (
    AppointmentStatus,
    ChatSessionStatus,
    KPIStatus,
    ReportExportFormat,
    ReportExportStatus,
)
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

    async def get_dashboard(self, hospital_id: int | None = None) -> DashboardSummaryResponse:
        cache_key = f"analytics:dashboard:{hospital_id if hospital_id is not None else 'all'}"
        cached = await cache_get(cache_key)
        if cached:
            return DashboardSummaryResponse(**cached)

        today = date.today()
        revenue_query = select(func.coalesce(func.sum(Billing.paid_amount), 0.0)).where(Billing.is_deleted.is_(False))
        if hospital_id is not None:
            revenue_query = revenue_query.where(Billing.hospital_id == hospital_id)
        revenue = await self.db.scalar(revenue_query) or 0.0

        appt_today_query = select(func.count()).select_from(Appointment).where(
            Appointment.appointment_date == today,
            Appointment.appointment_status.notin_([AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW])
        )
        if hospital_id is not None:
            appt_today_query = appt_today_query.where(Appointment.hospital_id == hospital_id)
        appointments_today = await self.db.scalar(appt_today_query) or 0

        patient_query = select(func.count()).select_from(Patient).where(Patient.is_deleted.is_(False))
        if hospital_id is not None:
            patient_query = patient_query.where(Patient.hospital_id == hospital_id)
        total_patients = await self.db.scalar(patient_query) or 0

        doctor_query = select(func.count()).select_from(Doctor).where(Doctor.is_deleted.is_(False))
        if hospital_id is not None:
            doctor_query = doctor_query.where(Doctor.hospital_id == hospital_id)
        total_doctors = await self.db.scalar(doctor_query) or 0

        pending_query = select(func.count()).select_from(Appointment).where(
            Appointment.appointment_status == AppointmentStatus.PENDING
        )
        if hospital_id is not None:
            pending_query = pending_query.where(Appointment.hospital_id == hospital_id)
        pending = await self.db.scalar(pending_query) or 0

        ai_query = select(func.count()).select_from(ChatSession)
        if hospital_id is not None:
            ai_query = ai_query.join(Patient, ChatSession.patient_id == Patient.id).where(Patient.hospital_id == hospital_id)
        ai_sessions = await self.db.scalar(ai_query) or 0

        voice_query = select(func.count()).select_from(VoiceCall).where(
            func.date(VoiceCall.created_at) == today
        )
        if hospital_id is not None:
            voice_query = voice_query.where(VoiceCall.hospital_id == hospital_id)
        voice_today = await self.db.scalar(voice_query) or 0

        wa_query = select(func.count()).select_from(WhatsAppMessage).where(
            func.date(WhatsAppMessage.created_at) == today
        )
        if hospital_id is not None:
            wa_query = wa_query.join(Patient, WhatsAppMessage.patient_id == Patient.id).where(Patient.hospital_id == hospital_id)
        wa_today = await self.db.scalar(wa_query) or 0

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
                    data=await self._appointment_trend(7, hospital_id=hospital_id),
                )
            ],
        )
        await cache_set(
            cache_key,
            result.model_dump(mode="json"),
            ttl=settings.ANALYTICS_CACHE_TTL_SECONDS,
        )
        return result

    async def cache_dashboard_summary(self, hospital_id: int | None = None) -> None:
        await self.get_dashboard(hospital_id=hospital_id)

    async def get_revenue_analytics(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        hospital_id: int | None = None
    ) -> RevenueAnalyticsResponse:
        from app.models.billing_model import Payment
        start, end = self._date_range(start_date, end_date)
        bill_query = select(Billing).where(
            Billing.is_deleted.is_(False),
            Billing.created_at >= start,
            Billing.created_at <= end,
        )
        if hospital_id is not None:
            bill_query = bill_query.where(Billing.hospital_id == hospital_id)
        bills = await self.db.execute(bill_query)
        items = list(bills.scalars().all())
        total = sum(b.total_amount for b in items)
        paid = sum(b.paid_amount for b in items)
        pending = sum(b.balance_amount for b in items)

        # Aggregate payment methods for collected payments in range
        payment_query = (
            select(Payment.payment_method, func.sum(Payment.amount))
            .select_from(Payment)
        )
        if hospital_id is not None:
            payment_query = payment_query.join(Billing, Payment.billing_id == Billing.id).where(Billing.hospital_id == hospital_id)
        payment_query = payment_query.where(
            Payment.status == "completed",
            Payment.is_refund.is_(False),
            Payment.payment_date >= start,
            Payment.payment_date <= end,
        ).group_by(Payment.payment_method)
        
        payment_res = await self.db.execute(payment_query)
        payment_method_breakdown = [
            ChartDataPoint(label=row[0], value=float(row[1] or 0.0))
            for row in payment_res.all()
        ]

        return RevenueAnalyticsResponse(
            total_revenue=round(total, 2),
            paid_amount=round(paid, 2),
            pending_amount=round(pending, 2),
            daily_revenue=await self._revenue_trend(start, end, hospital_id=hospital_id),
            payment_method_breakdown=payment_method_breakdown,
        )

    async def get_appointment_analytics(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        hospital_id: int | None = None
    ) -> AppointmentAnalyticsResponse:
        from app.models.department_model import Department
        start, end = self._date_range(start_date, end_date)
        appt_query = select(Appointment).where(
            Appointment.created_at >= start,
            Appointment.created_at <= end,
        )
        if hospital_id is not None:
            appt_query = appt_query.where(Appointment.hospital_id == hospital_id)
        result = await self.db.execute(appt_query)
        appts = list(result.scalars().all())
        status_counts: Dict[str, int] = {}
        for a in appts:
            status_counts[a.appointment_status] = status_counts.get(a.appointment_status, 0) + 1

        # Query department breakdown in the exact same date range
        dept_query = (
            select(
                Department.department_id,
                Department.department_name,
                func.count(Appointment.id)
            )
            .join(Appointment, Appointment.department_id == Department.department_id)
            .where(
                Appointment.created_at >= start,
                Appointment.created_at <= end,
                Appointment.appointment_status.notin_([AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW])
            )
        )
        if hospital_id is not None:
            dept_query = dept_query.where(Appointment.hospital_id == hospital_id)
        dept_query = dept_query.group_by(Department.department_id, Department.department_name)
        
        dept_counts = await self.db.execute(dept_query)
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
            daily_trend=await self._appointment_trend(30, hospital_id=hospital_id),
            department_breakdown=department_breakdown,
        )

    async def get_doctor_analytics(self, hospital_id: int | None = None) -> DoctorAnalyticsResponse:
        total_q = select(func.count()).select_from(Doctor).where(Doctor.is_deleted.is_(False))
        if hospital_id is not None:
            total_q = total_q.where(Doctor.hospital_id == hospital_id)
        total = await self.db.scalar(total_q) or 0

        appt_counts_q = (
            select(Doctor.id, Doctor.first_name, Doctor.last_name, func.count(Appointment.id))
            .join(
                Appointment,
                and_(
                    Appointment.doctor_id == Doctor.id,
                    Appointment.appointment_status.notin_([AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW])
                ),
                isouter=True
            )
            .where(Doctor.is_deleted.is_(False))
        )
        if hospital_id is not None:
            appt_counts_q = appt_counts_q.where(Doctor.hospital_id == hospital_id)
        appt_counts_q = appt_counts_q.group_by(Doctor.id).order_by(func.count(Appointment.id).desc()).limit(10)
        appt_counts = await self.db.execute(appt_counts_q)

        top = [
            {"doctor_id": r[0], "name": f"{r[1]} {r[2]}", "appointments": r[3]}
            for r in appt_counts.all()
        ]
        avg = sum(t["appointments"] for t in top) / len(top) if top else 0.0

        avail_q = (
            select(Doctor.availability_status, func.count(Doctor.id))
            .where(Doctor.is_deleted.is_(False))
        )
        if hospital_id is not None:
            avail_q = avail_q.where(Doctor.hospital_id == hospital_id)
        avail_q = avail_q.group_by(Doctor.availability_status)
        avail = await self.db.execute(avail_q)

        return DoctorAnalyticsResponse(
            total_doctors=total,
            avg_appointments_per_doctor=round(avg, 2),
            top_doctors=top,
            availability_breakdown=[
                ChartDataPoint(label=r[0] or "unknown", value=float(r[1])) for r in avail.all()
            ],
        )

    async def get_patient_analytics(self, hospital_id: int | None = None) -> PatientAnalyticsResponse:
        total_q = select(func.count()).select_from(Patient).where(Patient.is_deleted.is_(False))
        if hospital_id is not None:
            total_q = total_q.where(Patient.hospital_id == hospital_id)
        total = await self.db.scalar(total_q) or 0

        thirty_days_ago = utc_now() - timedelta(days=30)
        new_q = select(func.count()).select_from(Patient).where(
            Patient.is_deleted.is_(False),
            Patient.created_at >= thirty_days_ago,
        )
        if hospital_id is not None:
            new_q = new_q.where(Patient.hospital_id == hospital_id)
        new_patients = await self.db.scalar(new_q) or 0

        gender_q = (
            select(Patient.gender, func.count(Patient.id))
            .where(Patient.is_deleted.is_(False))
        )
        if hospital_id is not None:
            gender_q = gender_q.where(Patient.hospital_id == hospital_id)
        gender_q = gender_q.group_by(Patient.gender)
        gender = await self.db.execute(gender_q)

        trend_query = (
            select(func.date(Patient.created_at), func.count(Patient.id))
            .where(
                Patient.is_deleted.is_(False),
                Patient.created_at >= thirty_days_ago,
            )
        )
        if hospital_id is not None:
            trend_query = trend_query.where(Patient.hospital_id == hospital_id)
        trend_query = trend_query.group_by(func.date(Patient.created_at)).order_by(func.date(Patient.created_at).asc())
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

    async def get_ai_chatbot_analytics(self, hospital_id: int | None = None) -> ModuleAnalyticsResponse:
        session_q = select(func.count()).select_from(ChatSession)
        escalated_q = select(func.count()).select_from(ChatSession).where(ChatSession.session_status == ChatSessionStatus.ESCALATED)
        active_q = select(func.count()).select_from(ChatSession).where(ChatSession.session_status == ChatSessionStatus.ACTIVE)
        if hospital_id is not None:
            session_q = session_q.join(Patient, ChatSession.patient_id == Patient.id).where(Patient.hospital_id == hospital_id)
            escalated_q = escalated_q.join(Patient, ChatSession.patient_id == Patient.id).where(Patient.hospital_id == hospital_id)
            active_q = active_q.join(Patient, ChatSession.patient_id == Patient.id).where(Patient.hospital_id == hospital_id)
        
        total_sessions = (await self.db.scalar(session_q)) or 0
        escalated = (await self.db.scalar(escalated_q)) or 0
        active = (await self.db.scalar(active_q)) or 0

        now = utc_now()
        return ModuleAnalyticsResponse(
            module="ai_chatbot",
            period_start=now - timedelta(days=30),
            period_end=now,
            metrics={
                "total_sessions": total_sessions,
                "active_sessions": active,
                "escalated_sessions": escalated,
                "escalation_rate": round(escalated / total_sessions * 100, 2) if total_sessions else 0.0,
            },
            charts=[],
        )

    async def get_voice_analytics(self, hospital_id: int | None = None) -> ModuleAnalyticsResponse:
        voice_q = select(VoiceCall.call_status, func.count(VoiceCall.id))
        if hospital_id is not None:
            voice_q = voice_q.where(VoiceCall.hospital_id == hospital_id)
        voice_q = voice_q.group_by(VoiceCall.call_status)
        breakdown_res = await self.db.execute(voice_q)
        breakdown = breakdown_res.all()
        status_map = {s: c for s, c in breakdown}
        total = sum(status_map.values())
        completed = status_map.get("completed", 0)
        failed = status_map.get("failed", 0)

        now = utc_now()
        return ModuleAnalyticsResponse(
            module="voice_reminder",
            period_start=now - timedelta(days=30),
            period_end=now,
            metrics={
                "total_calls": total,
                "completed_calls": completed,
                "failed_calls": failed,
                "completion_rate": round(completed / total * 100, 2) if total else 0.0,
            },
            charts=[
                ChartSeries(
                    name="Call Status",
                    data=[
                        ChartDataPoint(label=s or "unknown", value=float(c))
                        for s, c in breakdown
                    ],
                )
            ],
        )

    async def get_whatsapp_analytics(self, hospital_id: int | None = None) -> ModuleAnalyticsResponse:
        wa_q = select(WhatsAppMessage.delivery_status, func.count(WhatsAppMessage.id))
        if hospital_id is not None:
            wa_q = wa_q.join(Patient, WhatsAppMessage.patient_id == Patient.id).where(Patient.hospital_id == hospital_id)
        wa_q = wa_q.group_by(WhatsAppMessage.delivery_status)
        res = await self.db.execute(wa_q)
        breakdown = res.all()
        status_map = {s: c for s, c in breakdown}
        total = sum(status_map.values())
        delivered = status_map.get("delivered", 0) + status_map.get("read", 0)
        
        now = utc_now()
        return ModuleAnalyticsResponse(
            module="whatsapp",
            period_start=now - timedelta(days=30),
            period_end=now,
            metrics={
                "total_messages": total,
                "delivered_messages": delivered,
                "delivery_rate": round(delivered / total * 100, 2) if total else 0.0,
            },
            charts=[
                ChartSeries(
                    name="Delivery Status",
                    data=[
                        ChartDataPoint(label=s or "unknown", value=float(c))
                        for s, c in breakdown
                    ],
                )
            ],
        )

    async def list_kpis(self, category: str | None = None, hospital_id: int | None = None) -> List[KPIResponse]:
        first_day_of_month = date.today().replace(day=1)
        start_of_month = datetime.combine(first_day_of_month, datetime.min.time())
        rev_q = select(func.coalesce(func.sum(Billing.paid_amount), 0.0)).where(
            Billing.is_deleted.is_(False),
            Billing.created_at >= start_of_month,
        )
        if hospital_id is not None:
            rev_q = rev_q.where(Billing.hospital_id == hospital_id)
        curr_revenue = float((await self.db.scalar(rev_q)) or 0.0)
        rev_target = 100000.0

        total_appt_q = select(func.count()).select_from(Appointment)
        completed_appt_q = select(func.count()).select_from(Appointment).where(
            Appointment.appointment_status == AppointmentStatus.COMPLETED
        )
        if hospital_id is not None:
            total_appt_q = total_appt_q.where(Appointment.hospital_id == hospital_id)
            completed_appt_q = completed_appt_q.where(Appointment.hospital_id == hospital_id)
        tot_appts = (await self.db.scalar(total_appt_q)) or 0
        comp_appts = (await self.db.scalar(completed_appt_q)) or 0
        comp_rate = round(comp_appts / tot_appts * 100, 1) if tot_appts > 0 else 0.0
        comp_target = 85.0

        pat_q = select(func.count()).select_from(Patient).where(Patient.is_deleted.is_(False))
        if hospital_id is not None:
            pat_q = pat_q.where(Patient.hospital_id == hospital_id)
        has_patients = ((await self.db.scalar(pat_q)) or 0) > 0
        sat_rate = 95.0 if has_patients else 0.0
        sat_target = 90.0

        ai_tot_q = select(func.count()).select_from(ChatSession)
        ai_esc_q = select(func.count()).select_from(ChatSession).where(
            ChatSession.session_status == ChatSessionStatus.ESCALATED
        )
        if hospital_id is not None:
            ai_tot_q = ai_tot_q.join(Patient, ChatSession.patient_id == Patient.id).where(Patient.hospital_id == hospital_id)
            ai_esc_q = ai_esc_q.join(Patient, ChatSession.patient_id == Patient.id).where(Patient.hospital_id == hospital_id)
        tot_ai = (await self.db.scalar(ai_tot_q)) or 0
        esc_ai = (await self.db.scalar(ai_esc_q)) or 0
        esc_rate = round(esc_ai / tot_ai * 100, 1) if tot_ai > 0 else 0.0
        esc_target = 10.0

        now = utc_now()
        kpis = [
            KPIResponse(
                id=1,
                kpi_name="Monthly Revenue",
                category="revenue",
                current_value=curr_revenue,
                target_value=rev_target,
                status=KPIStatus.ON_TRACK if curr_revenue >= rev_target else KPIStatus.BEHIND,
                unit="INR",
                updated_at=now,
            ),
            KPIResponse(
                id=2,
                kpi_name="Appointment Completion Rate",
                category="appointments",
                current_value=comp_rate,
                target_value=comp_target,
                status=KPIStatus.ON_TRACK if comp_rate >= comp_target else (KPIStatus.AT_RISK if comp_rate > 0 else KPIStatus.BEHIND),
                unit="%",
                updated_at=now,
            ),
            KPIResponse(
                id=3,
                kpi_name="Patient Satisfaction",
                category="patients",
                current_value=sat_rate,
                target_value=sat_target,
                status=KPIStatus.ON_TRACK if sat_rate >= sat_target else KPIStatus.AT_RISK,
                unit="%",
                updated_at=now,
            ),
            KPIResponse(
                id=4,
                kpi_name="AI Escalation Rate",
                category="ai_chat",
                current_value=esc_rate,
                target_value=esc_target,
                status=KPIStatus.ON_TRACK if esc_rate <= esc_target else KPIStatus.AT_RISK,
                unit="%",
                updated_at=now,
            ),
        ]
        if category:
            kpis = [k for k in kpis if k.category == category]
        return kpis

    async def list_reports(
        self, page: int = 1, size: int = 20, report_type: str | None = None, hospital_id: int | None = None
    ):
        skip = (page - 1) * size
        items = await self.repo.list_reports(skip=skip, limit=size, report_type=report_type, hospital_id=hospital_id)
        total = await self.repo.count_reports(report_type=report_type, hospital_id=hospital_id)
        return build_paginated_result(
            [ReportListItem.model_validate(r) for r in items], total, page, size
        )

    async def list_exports(
        self, page: int = 1, size: int = 20, report_type: str | None = None, hospital_id: int | None = None
    ):
        skip = (page - 1) * size
        items = await self.repo.list_exports(skip=skip, limit=size, report_type=report_type, hospital_id=hospital_id)
        total = await self.repo.count_exports(report_type=report_type, hospital_id=hospital_id)
        return build_paginated_result(
            [ExportListItem.model_validate(r) for r in items], total, page, size
        )

    async def request_export(self, data: ExportReportRequest, user_id: int, hospital_id: int | None = None) -> ExportReportResponse:
        filters = dict(data.filters or {})
        if hospital_id:
            filters["hospital_id"] = hospital_id
        export = ReportExport(
            report_type=data.report_type,
            export_format=ReportExportFormat.PDF,
            status=ReportExportStatus.PENDING,
            filters=json.dumps(filters),
            requested_by=user_id,
        )
        export = await self.repo.create_export(export)
        try:
            from app.tasks.analytics_tasks import generate_export

            generate_export.delay(export.id)
        except Exception:
            await self.process_export(export.id, hospital_id=hospital_id)
        return ExportReportResponse(
            export_id=export.id,
            status=export.status,
            file_path=export.file_path,
            message="Export queued for processing",
        )

    async def request_export_excel(self, data: ExportReportRequest, user_id: int, hospital_id: int | None = None) -> ExportReportResponse:
        filters = dict(data.filters or {})
        if hospital_id:
            filters["hospital_id"] = hospital_id
        export = ReportExport(
            report_type=data.report_type,
            export_format=ReportExportFormat.EXCEL,
            status=ReportExportStatus.PENDING,
            filters=json.dumps(filters),
            requested_by=user_id,
        )
        export = await self.repo.create_export(export)
        try:
            from app.tasks.analytics_tasks import generate_export

            generate_export.delay(export.id)
        except Exception:
            await self.process_export(export.id, hospital_id=hospital_id)
        return ExportReportResponse(
            export_id=export.id,
            status=export.status,
            file_path=export.file_path,
            message="Excel export queued for processing",
        )

    async def process_export(self, export_id: int, hospital_id: int | None = None) -> None:
        export = await self.repo.get_export(export_id)
        if not export:
            raise NotFoundException("Export not found")

        if hospital_id is None and export.filters:
            try:
                filters_data = json.loads(export.filters)
                if isinstance(filters_data, dict) and "hospital_id" in filters_data:
                    hospital_id = filters_data["hospital_id"]
            except Exception:
                pass

        export.status = ReportExportStatus.PROCESSING
        await self.repo.update_export(export)

        try:
            rows = await self._build_export_rows(export.report_type, hospital_id=hospital_id)
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

    async def _build_export_rows(self, report_type: str, hospital_id: int | None = None) -> List[Dict[str, Any]]:
        if report_type == "revenue":
            data = await self.get_revenue_analytics(hospital_id=hospital_id)
            return [data.model_dump()]
        if report_type == "appointments":
            data = await self.get_appointment_analytics(hospital_id=hospital_id)
            return [data.model_dump()]
        if report_type == "dashboard":
            data = await self.get_dashboard(hospital_id=hospital_id)
            return [data.model_dump()]
        if report_type == "doctors":
            data = await self.get_doctor_analytics(hospital_id=hospital_id)
            return [data.model_dump()]
        if report_type == "patients":
            data = await self.get_patient_analytics(hospital_id=hospital_id)
            return [data.model_dump()]
        return [{"report_type": report_type, "hospital_id": hospital_id, "generated_at": utc_now().isoformat()}]

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

    async def _appointment_trend(self, days: int, hospital_id: int | None = None) -> List[ChartDataPoint]:
        points = []
        for i in range(days - 1, -1, -1):
            d = date.today() - timedelta(days=i)
            query = select(func.count()).select_from(Appointment).where(
                Appointment.appointment_date == d,
                Appointment.appointment_status.notin_([AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW])
            )
            if hospital_id is not None:
                query = query.where(Appointment.hospital_id == hospital_id)
            count = await self.db.scalar(query) or 0
            points.append(ChartDataPoint(label=d.isoformat(), value=float(count)))
        return points

    async def _revenue_trend(self, start: datetime, end: datetime, hospital_id: int | None = None) -> List[ChartDataPoint]:
        query = (
            select(func.date(Billing.created_at), func.sum(Billing.paid_amount))
            .where(Billing.is_deleted.is_(False), Billing.created_at >= start, Billing.created_at <= end)
        )
        if hospital_id is not None:
            query = query.where(Billing.hospital_id == hospital_id)
        query = query.group_by(func.date(Billing.created_at))
        result = await self.db.execute(query)
        return [ChartDataPoint(label=str(r[0]), value=float(r[1] or 0)) for r in result.all()]
