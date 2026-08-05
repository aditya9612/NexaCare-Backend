from datetime import datetime, date, date
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.report_repository import ReportRepository
from fastapi import HTTPException
from pydantic import BaseModel
from app.schemas.report_schema import DailyRevenueResponse, PatientStatisticsResponse, AppointmentTrendsResponse, InventoryStatusResponse, PharmacySalesResponse, PharmacyInventoryResponse, PharmacyExpiryResponse, LabTestSummaryResponse, LabOrderedValueResponse, LabTechnicianWorkloadResponse, LabTurnaroundTimeResponse, UnifiedAccountantFinancialResponse, AccountantRevenueVsExpenseResponse, AccountantDepartmentWiseResponse, FinancialPeriod, ExportPayload

class ReportService:
    def __init__(self, db: AsyncSession):
        self.repo = ReportRepository(db)

    async def get_unified_accountant_financial_report(
        self,
        period: FinancialPeriod,
        target_date: date | None = None,
        month: int | str | None = None,
        year: int | str | None = None,
        start_date: date | None = None,
        end_date: date | None = None
    ) -> UnifiedAccountantFinancialResponse:
        from datetime import datetime, date, datetime
        import calendar

        if isinstance(month, str) and "-" in month:
            y_val, m_val = map(int, month.split('-'))
            month = m_val
            year = y_val
        elif isinstance(month, str):
            month = int(month)
            
        if isinstance(year, str):
            year = int(year)

        now = date.today()
        s_date = None
        e_date = None

        if period == FinancialPeriod.DAILY:
            s_date = target_date or now
            e_date = s_date
        elif period == FinancialPeriod.MONTHLY:
            m = month or now.month
            y = year or now.year
            try:
                last_day = calendar.monthrange(y, m)[1]
                s_date = date(y, m, 1)
                e_date = date(y, m, last_day)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid month or year")
        elif period == FinancialPeriod.YEARLY:
            y = year or now.year
            s_date = date(y, 1, 1)
            e_date = date(y, 12, 31)
        elif period == FinancialPeriod.CUSTOM:
            if not start_date or not end_date:
                raise HTTPException(status_code=400, detail="start_date and end_date are required for custom period")
            if start_date > end_date:
                raise HTTPException(status_code=400, detail="start_date cannot be after end_date")
            s_date = start_date
            e_date = end_date

        start_datetime = datetime.combine(s_date, datetime.min.time())
        end_datetime = datetime.combine(e_date, datetime.max.time())

        stats = await self.repo._get_accountant_financial_report(start_datetime, end_datetime)

        return UnifiedAccountantFinancialResponse(
            period=period,
            start_date=s_date,
            end_date=e_date,
            **stats
        )

    async def get_accountant_revenue_vs_expense(self, start_date: date | None = None, end_date: date | None = None) -> AccountantRevenueVsExpenseResponse:
        stats = await self.repo.get_accountant_revenue_vs_expense(start_date, end_date)
        return AccountantRevenueVsExpenseResponse(**stats)

    async def get_accountant_department_wise(self, start_date: date | None = None, end_date: date | None = None) -> AccountantDepartmentWiseResponse:
        stats = await self.repo.get_accountant_department_wise(start_date, end_date)
        return AccountantDepartmentWiseResponse(**stats)

    async def get_lab_turnaround_time(self, start_date: date | None = None, end_date: date | None = None, department_id: int | None = None) -> LabTurnaroundTimeResponse:
        stats = await self.repo.get_lab_turnaround_time(start_date, end_date, department_id)
        return LabTurnaroundTimeResponse(**stats)

    async def get_lab_technician_workload(self) -> LabTechnicianWorkloadResponse:
        stats = await self.repo.get_lab_technician_workload()
        return LabTechnicianWorkloadResponse(**stats)

    async def get_lab_ordered_value(self, start_date: date | None = None, end_date: date | None = None, department_id: int | None = None) -> LabOrderedValueResponse:
        s_date = start_date or date.today()
        e_date = end_date or s_date
        
        stats = await self.repo.get_lab_ordered_value(s_date, e_date, department_id)
        return LabOrderedValueResponse(**stats)

    async def get_lab_test_summary(self, start_date: date | None = None, end_date: date | None = None, department_id: int | None = None) -> LabTestSummaryResponse:
        s_date = start_date or date.today()
        e_date = end_date or s_date
        
        stats = await self.repo.get_lab_test_summary(s_date, e_date, department_id)
        return LabTestSummaryResponse(**stats)

    async def get_pharmacy_expiry(self, category: str | None = None) -> PharmacyExpiryResponse:
        stats = await self.repo.get_pharmacy_expiry(category)
        return PharmacyExpiryResponse(**stats)

    async def get_pharmacy_inventory(self, category: str | None = None) -> PharmacyInventoryResponse:
        stats = await self.repo.get_pharmacy_inventory(category)
        return PharmacyInventoryResponse(**stats)

    async def get_pharmacy_sales(self, start_date: date | None = None, end_date: date | None = None) -> PharmacySalesResponse:
        s_date = start_date or date.today()
        e_date = end_date or s_date
        
        stats = await self.repo.get_pharmacy_sales(s_date, e_date)
        return PharmacySalesResponse(**stats)

    async def get_inventory_status(self, department_id: int | None = None, category: str | None = None) -> InventoryStatusResponse:
        stats = await self.repo.get_inventory_status(department_id, category)
        return InventoryStatusResponse(**stats)

    async def get_appointment_trends(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        doctor_id: int | None = None,
        department_id: int | None = None
    ) -> AppointmentTrendsResponse:
        s_date = start_date or date.today()
        e_date = end_date or s_date
        
        trends = await self.repo.get_appointment_trends(s_date, e_date, doctor_id, department_id)
        return AppointmentTrendsResponse(**trends)

    async def get_patient_statistics(self, start_date: date | None = None, end_date: date | None = None) -> PatientStatisticsResponse:
        stats = await self.repo.get_patient_statistics(start_date, end_date)
        return PatientStatisticsResponse(**stats)

    async def get_daily_revenue(self, start_date: date | None = None, end_date: date | None = None) -> DailyRevenueResponse:
        s_date = start_date or date.today()
        e_date = end_date or s_date
        
        billing_rev, pharmacy_rev = await self.repo.get_daily_revenue(s_date, e_date)
        total_rev = billing_rev + pharmacy_rev
        return DailyRevenueResponse(
            date=s_date.isoformat(),
            billing_revenue=billing_rev,
            pharmacy_revenue=pharmacy_rev,
            total_revenue=total_rev
        )

    @staticmethod
    def build_export_payload(title: str, data: BaseModel, filters: dict = None, main_table_title: str = 'Main Data') -> ExportPayload:
        from datetime import datetime, date, datetime
        from app.schemas.report_schema import CollectionSection
        data_dict = data.model_dump()
        
        summary = {}
        lists = {}
        
        # Iteration preserves original field ordering exactly
        for k, v in data_dict.items():
            if isinstance(v, list):
                lists[k] = v
            else:
                summary[k] = v
                
        main_rows = []
        additional_sections = []
        
        if len(lists) == 1:
            main_rows = list(lists.values())[0]
        elif len(lists) > 1:
            primary_key = next((k for k in ['items', 'rows', 'data', 'trend'] if k in lists), None)
            if primary_key:
                main_rows = lists.pop(primary_key)
                
            for k, v in lists.items():
                section_title = k.replace('_', ' ').title()
                additional_sections.append(CollectionSection(title=section_title, rows=v))
        else:
            main_rows = [summary]
            summary = {}
            
        return ExportPayload(
            title=title,
            generated_at=datetime.now(),
            filters=filters or {},
            summary=summary,
            main_table_title=main_table_title,
            main_rows=main_rows,
            additional_sections=additional_sections
        )

    async def get_pharmacy_profit_loss(self, start_date, end_date):
        from app.schemas.report_schema import PharmacyProfitLossResponse
        data = await self.repo.get_pharmacy_profit_loss(start_date, end_date)
        return PharmacyProfitLossResponse(**data)

    async def get_lab_daily(self, date_filter: date | None = None):
        from app.schemas.report_schema import LabSummaryResponse
        from datetime import datetime, date
        import calendar
        now = date.today()
        target_date = date_filter or now
        
        start_time = datetime.combine(target_date, datetime.min.time())
        end_time = datetime.combine(target_date, datetime.max.time())
        
        data = await self.repo.get_lab_summary(start_time, end_time)
        data['period'] = target_date.strftime('%Y-%M-%d') # typo intentionally fixed below
        data['period'] = target_date.strftime('%Y-%m-%d')
        
        return LabSummaryResponse(**data)

    async def get_lab_monthly(self, month: str | None = None, year: str | None = None):
        from app.schemas.report_schema import LabSummaryResponse
        from datetime import datetime, date
        import calendar
        now = date.today()
        m = int(month) if month else now.month
        y = int(year) if year else now.year
        
        s_date = date(y, m, 1)
        e_date = date(y, m, calendar.monthrange(y, m)[1])
        
        start_time = datetime.combine(s_date, datetime.min.time())
        end_time = datetime.combine(e_date, datetime.max.time())
        
        data = await self.repo.get_lab_summary(start_time, end_time)
        data['period'] = f"{y}-{m:02d}"
        
        return LabSummaryResponse(**data)

    async def get_lab_performance(self, start_date: date | None = None, end_date: date | None = None):
        from app.schemas.report_schema import LabPerformanceResponse
        from datetime import datetime, date
        import calendar
        now = date.today()
        s_date = start_date or date(now.year, now.month, 1)
        e_date = end_date or date(now.year, now.month, calendar.monthrange(now.year, now.month)[1])
        
        start_time = datetime.combine(s_date, datetime.min.time())
        end_time = datetime.combine(e_date, datetime.max.time())
        
        data = await self.repo.get_lab_performance(start_time, end_time)
        return LabPerformanceResponse(**data)

    async def get_lab_revenue(self, start_date: date | None = None, end_date: date | None = None):
        from app.schemas.report_schema import LabRevenueResponse
        from datetime import datetime, date
        import calendar
        now = date.today()
        s_date = start_date or date(now.year, now.month, 1)
        e_date = end_date or date(now.year, now.month, calendar.monthrange(now.year, now.month)[1])
        
        start_time = datetime.combine(s_date, datetime.min.time())
        end_time = datetime.combine(e_date, datetime.max.time())
        
        data = await self.repo.get_lab_revenue(start_time, end_time)
        return LabRevenueResponse(**data)

    async def get_doctor_lab_reports(self, start_date, end_date):
        from app.schemas.report_schema import DoctorLabReportResponse
        from datetime import datetime, date
        import calendar
        now = date.today()
        s_date = start_date or date(now.year, now.month, 1)
        e_date = end_date or date(now.year, now.month, calendar.monthrange(now.year, now.month)[1])
        
        start_time = datetime.combine(s_date, datetime.min.time())
        end_time = datetime.combine(e_date, datetime.max.time())
        
        data = await self.repo.get_doctor_lab_reports(start_time, end_time)
        return DoctorLabReportResponse(**data)
