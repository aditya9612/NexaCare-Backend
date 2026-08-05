from datetime import date, datetime, timedelta
from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.billing_model import Payment, Billing
from app.models.expense_model import Expense
from app.models.pharmacy_model import PharmacyInvoice, Medicine
from app.models.patient_model import Patient
from app.models.appointment_model import Appointment
from app.models.inventory_model import InventoryItem, ReorderAlert
from app.models.lab_model import TestOrder, LabTest
from app.core.constants import LabOrderStatus

class ReportRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_daily_revenue(self, start_date: date, end_date: date) -> tuple[float, float]:
        start_of_period = datetime.combine(start_date, datetime.min.time())
        end_of_period = datetime.combine(end_date, datetime.max.time())

        # Billing Revenue
        billing_query = select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
            Payment.status == "completed",
            Payment.is_refund == False,
            Payment.payment_date >= start_of_period,
            Payment.payment_date <= end_of_period
        )
        billing_revenue = await self.db.scalar(billing_query) or 0.0

        # Pharmacy Revenue
        pharmacy_query = select(func.coalesce(func.sum(PharmacyInvoice.total_amount), 0.0)).where(
            PharmacyInvoice.status != "cancelled",
            PharmacyInvoice.is_deleted == False,
            PharmacyInvoice.created_at >= start_of_period,
            PharmacyInvoice.created_at <= end_of_period
        )
        pharmacy_revenue = await self.db.scalar(pharmacy_query) or 0.0

        return float(billing_revenue), float(pharmacy_revenue)

    async def get_patient_statistics(self, start_date: date | None = None, end_date: date | None = None) -> dict:
        total_filters = [Patient.is_deleted == False]
        if end_date:
            end_dt = datetime.combine(end_date, datetime.max.time())
            total_filters.append(Patient.created_at <= end_dt)

        counts_query = select(
            func.count(Patient.id).label("total"),
            func.sum(case((Patient.status == 'active', 1), else_=0)).label("active"),
            func.sum(case((Patient.status != 'active', 1), else_=0)).label("inactive")
        ).where(*total_filters)
        
        counts_res = await self.db.execute(counts_query)
        counts_row = counts_res.fetchone()
        
        total_patients = int(counts_row[0]) if counts_row and counts_row[0] is not None else 0
        active_patients = int(counts_row[1]) if counts_row and counts_row[1] is not None else 0
        inactive_patients = int(counts_row[2]) if counts_row and counts_row[2] is not None else 0

        new_filters = list(total_filters)
        if start_date:
            start_dt = datetime.combine(start_date, datetime.min.time())
            new_filters.append(Patient.created_at >= start_dt)

        new_patients = await self.db.scalar(select(func.count(Patient.id)).where(*new_filters)) or 0

        # Gender Distribution
        gender_query = select(
            func.coalesce(func.lower(Patient.gender), "unknown").label("gender"),
            func.count(Patient.id).label("count")
        ).where(*new_filters).group_by(func.coalesce(func.lower(Patient.gender), "unknown"))
        gender_res = await self.db.execute(gender_query)
        gender_dist = [{"gender": str(row.gender).capitalize() if str(row.gender).lower() != "unknown" else "Unknown", "count": row.count} for row in gender_res.all()]

        # Age Distribution
        age_expr = func.year(func.current_date()) - func.year(Patient.dob)
        age_case = case(
            (Patient.dob == None, "Unknown"),
            (age_expr < 18, "0-17"),
            (age_expr < 36, "18-35"),
            (age_expr < 61, "36-60"),
            else_="60+"
        )
        age_query = select(
            age_case.label("range"),
            func.count(Patient.id).label("count")
        ).where(*new_filters).group_by(age_case)
        age_res = await self.db.execute(age_query)
        age_dist = [{"range": row.range, "count": row.count} for row in age_res.all()]

        return {
            "total_patients": total_patients,
            "new_patients": new_patients,
            "active_patients": active_patients,
            "inactive_patients": inactive_patients,
            "gender_distribution": gender_dist,
            "age_distribution": age_dist
        }

    async def get_appointment_trends(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        doctor_id: int | None = None,
        department_id: int | None = None
    ) -> dict:
        filters = []
        if start_date:
            filters.append(Appointment.appointment_date >= start_date)
        if end_date:
            filters.append(Appointment.appointment_date <= end_date)
        if doctor_id:
            filters.append(Appointment.doctor_id == doctor_id)
        if department_id:
            filters.append(Appointment.department_id == department_id)

        # 1. Total count
        total_query = select(func.count(Appointment.id)).where(*filters)
        total_appointments = await self.db.scalar(total_query) or 0

        # 2. Trend grouped by date and status
        trend_query = select(
            Appointment.appointment_date.label("date"),
            Appointment.appointment_status.label("status"),
            func.count(Appointment.id).label("count")
        ).where(*filters).group_by(
            Appointment.appointment_date,
            Appointment.appointment_status
        ).order_by(
            Appointment.appointment_date.asc(),
            Appointment.appointment_status.asc()
        )
        
        trend_res = await self.db.execute(trend_query)
        trend = [
            {
                "date": row.date.isoformat() if hasattr(row.date, 'isoformat') else str(row.date),
                "status": row.status,
                "count": row.count
            }
            for row in trend_res.all()
        ]

        return {
            "total_appointments": total_appointments,
            "trend": trend
        }

    async def get_inventory_status(
        self,
        department_id: int | None = None,
        category: str | None = None
    ) -> dict:
        filters = [InventoryItem.is_deleted == False]
        if department_id:
            filters.append(InventoryItem.department_id == department_id)
        if category:
            filters.append(InventoryItem.category == category)

        today = date.today()
        thirty_days_later = today + timedelta(days=30)

        # 1. Aggregate Inventory Item metrics in a single query
        metrics_query = select(
            func.count(InventoryItem.id).label("total"),
            func.sum(case((InventoryItem.is_active == True, 1), else_=0)).label("active"),
            func.sum(case((InventoryItem.is_active == False, 1), else_=0)).label("inactive"),
            func.sum(case((
                (InventoryItem.quantity <= InventoryItem.reorder_level) & (InventoryItem.quantity > 0) & (InventoryItem.is_active == True), 1
            ), else_=0)).label("low_stock"),
            func.sum(case((
                (InventoryItem.quantity <= 0) & (InventoryItem.is_active == True), 1
            ), else_=0)).label("out_of_stock"),
            func.sum(case((
                (InventoryItem.expiry_date != None) & (InventoryItem.expiry_date >= today) & (InventoryItem.expiry_date <= thirty_days_later) & (InventoryItem.is_active == True), 1
            ), else_=0)).label("expiring"),
            func.sum(case((
                (InventoryItem.expiry_date != None) & (InventoryItem.expiry_date < today) & (InventoryItem.is_active == True), 1
            ), else_=0)).label("expired")
        ).where(*filters)

        metrics_res = await self.db.execute(metrics_query)
        metrics_row = metrics_res.fetchone()

        total_items = int(metrics_row.total) if metrics_row and metrics_row.total else 0
        active_items = int(metrics_row.active) if metrics_row and metrics_row.active else 0
        inactive_items = int(metrics_row.inactive) if metrics_row and metrics_row.inactive else 0
        low_stock_items = int(metrics_row.low_stock) if metrics_row and metrics_row.low_stock else 0
        out_of_stock_items = int(metrics_row.out_of_stock) if metrics_row and metrics_row.out_of_stock else 0
        expiring_items = int(metrics_row.expiring) if metrics_row and metrics_row.expiring else 0
        expired_items = int(metrics_row.expired) if metrics_row and metrics_row.expired else 0

        # 2. Reorder Alerts
        alerts_query = select(func.count(func.distinct(ReorderAlert.item_id))).join(
            InventoryItem, ReorderAlert.item_id == InventoryItem.id
        ).where(
            ReorderAlert.status == 'active',
            *filters
        )
        reorder_alerts = await self.db.scalar(alerts_query) or 0

        return {
            "total_items": total_items,
            "active_items": active_items,
            "inactive_items": inactive_items,
            "low_stock_items": low_stock_items,
            "out_of_stock_items": out_of_stock_items,
            "expiring_items": expiring_items,
            "expired_items": expired_items,
            "reorder_alerts": reorder_alerts
        }

    async def get_pharmacy_sales(self, start_date: date, end_date: date) -> dict:
        start_of_period = datetime.combine(start_date, datetime.min.time())
        end_of_period = datetime.combine(end_date, datetime.max.time())

        sales_query = select(
            func.coalesce(func.sum(PharmacyInvoice.total_amount), 0.0).label("total_sales"),
            func.count(PharmacyInvoice.id).label("total_invoices")
        ).where(
            PharmacyInvoice.status != "cancelled",
            PharmacyInvoice.is_deleted == False,
            PharmacyInvoice.created_at >= start_of_period,
            PharmacyInvoice.created_at <= end_of_period
        )

        res = await self.db.execute(sales_query)
        row = res.fetchone()

        total_sales = float(row.total_sales) if row and row.total_sales else 0.0
        total_invoices = int(row.total_invoices) if row and row.total_invoices else 0
        avg_invoice = round(total_sales / total_invoices, 2) if total_invoices > 0 else 0.0

        return {
            "total_sales": total_sales,
            "total_invoices": total_invoices,
            "average_invoice_value": avg_invoice
        }

    async def get_pharmacy_inventory(self, category: str | None = None) -> dict:
        filters = [Medicine.is_deleted == False]
        if category:
            filters.append(Medicine.category == category)

        metrics_query = select(
            func.count(Medicine.id).label("total"),
            func.sum(case((Medicine.is_active == True, 1), else_=0)).label("active"),
            func.sum(case((Medicine.is_active == False, 1), else_=0)).label("inactive"),
            func.sum(case((
                (Medicine.stock_quantity <= Medicine.reorder_level) & (Medicine.stock_quantity > 0) & (Medicine.is_active == True), 1
            ), else_=0)).label("low_stock"),
            func.sum(case((
                (Medicine.stock_quantity <= 0) & (Medicine.is_active == True), 1
            ), else_=0)).label("out_of_stock"),
            func.coalesce(func.sum(Medicine.stock_quantity), 0).label("total_stock")
        ).where(*filters)

        res = await self.db.execute(metrics_query)
        row = res.fetchone()

        total_medicines = int(row.total) if row and row.total else 0
        active_medicines = int(row.active) if row and row.active else 0
        inactive_medicines = int(row.inactive) if row and row.inactive else 0
        low_stock_medicines = int(row.low_stock) if row and row.low_stock else 0
        out_of_stock_medicines = int(row.out_of_stock) if row and row.out_of_stock else 0
        total_stock_quantity = int(row.total_stock) if row and row.total_stock else 0

        return {
            "total_medicines": total_medicines,
            "active_medicines": active_medicines,
            "inactive_medicines": inactive_medicines,
            "low_stock_medicines": low_stock_medicines,
            "out_of_stock_medicines": out_of_stock_medicines,
            "total_stock_quantity": total_stock_quantity
        }

    async def get_pharmacy_expiry(self, category: str | None = None) -> dict:
        filters = [
            Medicine.is_deleted == False,
            Medicine.is_active == True,
            Medicine.expiry_date != None
        ]
        if category:
            filters.append(Medicine.category == category)

        today = date.today()
        d30 = today + timedelta(days=30)
        d60 = today + timedelta(days=60)
        d90 = today + timedelta(days=90)

        metrics_query = select(
            func.coalesce(func.count(Medicine.id), 0).label("total"),
            func.coalesce(func.sum(case((Medicine.expiry_date < today, 1), else_=0)), 0).label("expired"),
            func.coalesce(func.sum(case(((Medicine.expiry_date >= today) & (Medicine.expiry_date <= d30), 1), else_=0)), 0).label("exp30"),
            func.coalesce(func.sum(case(((Medicine.expiry_date > d30) & (Medicine.expiry_date <= d60), 1), else_=0)), 0).label("exp60"),
            func.coalesce(func.sum(case(((Medicine.expiry_date > d60) & (Medicine.expiry_date <= d90), 1), else_=0)), 0).label("exp90")
        ).where(*filters)

        res = await self.db.execute(metrics_query)
        row = res.fetchone()

        total = int(row.total) if row and row.total else 0
        expired = int(row.expired) if row and row.expired else 0
        exp30 = int(row.exp30) if row and row.exp30 else 0
        exp60 = int(row.exp60) if row and row.exp60 else 0
        exp90 = int(row.exp90) if row and row.exp90 else 0

        return {
            "total_medicines": total,
            "expired_medicines": expired,
            "expiring_30_days": exp30,
            "expiring_60_days": exp60,
            "expiring_90_days": exp90
        }

    async def get_lab_test_summary(self, start_date: date, end_date: date, department_id: int | None = None) -> dict:
        start_of_period = datetime.combine(start_date, datetime.min.time())
        end_of_period = datetime.combine(end_date, datetime.max.time())

        filters = [
            TestOrder.is_deleted == False,
            TestOrder.ordered_at >= start_of_period,
            TestOrder.ordered_at <= end_of_period
        ]
        if department_id:
            filters.append(TestOrder.department_id == department_id)

        metrics_query = select(
            func.coalesce(func.count(TestOrder.id), 0).label("total"),
            func.coalesce(func.sum(case((TestOrder.status == LabOrderStatus.ORDERED, 1), else_=0)), 0).label("pending"),
            func.coalesce(func.sum(case(((TestOrder.status == LabOrderStatus.IN_PROGRESS) | (TestOrder.status == LabOrderStatus.SAMPLE_COLLECTED), 1), else_=0)), 0).label("in_progress"),
            func.coalesce(func.sum(case((TestOrder.status == LabOrderStatus.COMPLETED, 1), else_=0)), 0).label("completed"),
            func.coalesce(func.sum(case((TestOrder.status == LabOrderStatus.CANCELLED, 1), else_=0)), 0).label("cancelled")
        ).where(*filters)

        res = await self.db.execute(metrics_query)
        row = res.fetchone()

        total = int(row.total) if row and row.total else 0
        pending = int(row.pending) if row and row.pending else 0
        in_progress = int(row.in_progress) if row and row.in_progress else 0
        completed = int(row.completed) if row and row.completed else 0
        cancelled = int(row.cancelled) if row and row.cancelled else 0

        return {
            "total_tests": total,
            "pending_tests": pending,
            "in_progress_tests": in_progress,
            "completed_tests": completed,
            "cancelled_tests": cancelled
        }

    async def get_lab_ordered_value(self, start_date: date, end_date: date, department_id: int | None = None) -> dict:
        start_of_period = datetime.combine(start_date, datetime.min.time())
        end_of_period = datetime.combine(end_date, datetime.max.time())

        # Note: The database schema does not capture itemized payments natively linking Billing to TestOrder.
        # Financial revenue cannot currently be calculated.
        # This report represents only the catalogue value of ordered tests, calculated by summing LabTest.price.

        filters = [
            TestOrder.is_deleted == False,
            TestOrder.status != LabOrderStatus.CANCELLED,
            TestOrder.ordered_at >= start_of_period,
            TestOrder.ordered_at <= end_of_period
        ]
        if department_id:
            filters.append(TestOrder.department_id == department_id)

        metrics_query = select(
            func.coalesce(func.sum(LabTest.price), 0).label("total_val"),
            func.coalesce(func.count(TestOrder.id), 0).label("total_tests")
        ).join(
            LabTest, TestOrder.lab_test_id == LabTest.id
        ).where(*filters)

        res = await self.db.execute(metrics_query)
        row = res.fetchone()

        total_val = float(row.total_val) if row and row.total_val else 0.0
        total_tests = int(row.total_tests) if row and row.total_tests else 0
        avg_val = (total_val / total_tests) if total_tests > 0 else 0.0

        return {
            "total_ordered_value": total_val,
            "total_tests_ordered": total_tests,
            "average_test_value": avg_val
        }

    async def get_lab_technician_workload(self) -> dict:
        # Note: The database schema does not capture technician assignment at the TestOrder level.
        # Tests exist in a shared departmental pool. We cannot calculate per-technician pending/in-progress workloads.
        # We adapt the report to accurately reflect this schema limitation by summarizing the unassigned pool.
        
        filters = [
            TestOrder.is_deleted == False
        ]

        metrics_query = select(
            func.coalesce(func.sum(case((TestOrder.status == LabOrderStatus.ORDERED, 1), else_=0)), 0).label("pending"),
            func.coalesce(func.sum(case(((TestOrder.status == LabOrderStatus.IN_PROGRESS) | (TestOrder.status == LabOrderStatus.SAMPLE_COLLECTED), 1), else_=0)), 0).label("in_progress"),
            func.coalesce(func.sum(case((TestOrder.status == LabOrderStatus.COMPLETED, 1), else_=0)), 0).label("completed")
        ).where(*filters)

        res = await self.db.execute(metrics_query)
        row = res.fetchone()

        pending = int(row.pending) if row and row.pending else 0
        in_progress = int(row.in_progress) if row and row.in_progress else 0
        completed = int(row.completed) if row and row.completed else 0

        return {
            "assignment_supported": False,
            "message": "Technician assignment is not natively supported by the schema. Lab operates on a shared-pool basis.",
            "unassigned_pending_tests": pending,
            "unassigned_in_progress_tests": in_progress,
            "unassigned_completed_tests": completed
        }

    async def get_lab_turnaround_time(self, start_date: date | None = None, end_date: date | None = None, department_id: int | None = None) -> dict:
        filters = [
            TestOrder.is_deleted == False,
            TestOrder.status == LabOrderStatus.COMPLETED,
            TestOrder.completed_at != None,
            TestOrder.ordered_at != None
        ]
        
        if start_date:
            start_of_period = datetime.combine(start_date, datetime.min.time())
            filters.append(TestOrder.completed_at >= start_of_period)
        if end_date:
            end_of_period = datetime.combine(end_date, datetime.max.time())
            filters.append(TestOrder.completed_at <= end_of_period)
        if department_id:
            filters.append(TestOrder.department_id == department_id)

        # MySQL specific turnaround logic: difference between ordered_at and completed_at in seconds, then divide by 60 for minutes
        turnaround_expr = (func.unix_timestamp(TestOrder.completed_at) - func.unix_timestamp(TestOrder.ordered_at)) / 60

        metrics_query = select(
            func.coalesce(func.count(TestOrder.id), 0).label("total_completed_tests"),
            func.coalesce(func.avg(turnaround_expr), 0).label("avg_tat"),
            func.coalesce(func.min(turnaround_expr), 0).label("min_tat"),
            func.coalesce(func.max(turnaround_expr), 0).label("max_tat")
        ).where(*filters)

        res = await self.db.execute(metrics_query)
        row = res.fetchone()

        return {
            "total_completed_tests": int(row.total_completed_tests) if row and row.total_completed_tests else 0,
            "average_turnaround_minutes": int(row.avg_tat) if row and row.avg_tat else 0,
            "minimum_turnaround_minutes": int(row.min_tat) if row and row.min_tat else 0,
            "maximum_turnaround_minutes": int(row.max_tat) if row and row.max_tat else 0
        }

    async def _get_accountant_financial_report(self, start_time: datetime, end_time: datetime) -> dict:
        # 1. Billing metrics
        billing_query = select(
            func.coalesce(func.sum(Billing.total_amount), 0).label("total_billed"),
            func.coalesce(func.count(Billing.id), 0).label("total_bills")
        ).where(
            Billing.is_deleted == False,
            Billing.status != 'cancelled',
            Billing.created_at >= start_time,
            Billing.created_at <= end_time
        )
        
        # 2. Payment metrics
        payment_query = select(
            func.coalesce(func.sum(
                case((Payment.is_refund == False, Payment.amount), else_=-Payment.amount)
            ), 0).label("total_collected"),
            func.coalesce(func.count(Payment.id), 0).label("total_payments")
        ).where(
            Payment.status == 'completed',
            Payment.payment_date >= start_time,
            Payment.payment_date <= end_time
        )

        # 3. Expense metrics
        expense_query = select(
            func.coalesce(func.sum(Expense.amount), 0).label("total_expense"),
            func.coalesce(func.count(Expense.id), 0).label("total_expenses")
        ).where(
            Expense.is_deleted == False,
            Expense.status == 'Paid',
            Expense.expense_date >= start_time.date(),
            Expense.expense_date <= end_time.date()
        )

        b_res = await self.db.execute(billing_query)
        p_res = await self.db.execute(payment_query)
        e_res = await self.db.execute(expense_query)

        b_row = b_res.fetchone()
        p_row = p_res.fetchone()
        e_row = e_res.fetchone()

        billed_amount = float(b_row.total_billed) if b_row else 0.0
        collected_amount = float(p_row.total_collected) if p_row else 0.0
        expense_amount = float(e_row.total_expense) if e_row else 0.0

        return {
            "total_billed_amount": billed_amount,
            "total_collected_amount": collected_amount,
            "total_expense_amount": expense_amount,
            "net_cash_flow": collected_amount - expense_amount,
            "total_bills": int(b_row.total_bills) if b_row else 0,
            "total_payments": int(p_row.total_payments) if p_row else 0,
            "total_expenses": int(e_row.total_expenses) if e_row else 0
        }

    async def get_accountant_revenue_vs_expense(self, start_date: date | None = None, end_date: date | None = None) -> dict:
        import calendar
        now = date.today()

        s_date = start_date
        e_date = end_date

        if not s_date or not e_date:
            s_date = date(now.year, now.month, 1)
            last_day = calendar.monthrange(now.year, now.month)[1]
            e_date = date(now.year, now.month, last_day)

        start_time = datetime.combine(s_date, datetime.min.time())
        end_time = datetime.combine(e_date, datetime.max.time())
        
        base_result = await self._get_accountant_financial_report(start_time, end_time)

        billed = base_result["total_billed_amount"]
        collected = base_result["total_collected_amount"]
        expenses = base_result["total_expense_amount"]

        collection_rate = (collected / billed * 100) if billed > 0 else 0.0
        expense_ratio = (expenses / collected * 100) if collected > 0 else 0.0

        return {
            "total_billed_amount": billed,
            "total_collected_amount": collected,
            "total_expense_amount": expenses,
            "net_cash_flow": base_result["net_cash_flow"],
            "collection_rate_percent": round(collection_rate, 2),
            "expense_ratio_percent": round(expense_ratio, 2)
        }

    async def get_accountant_department_wise(self, start_date: date | None = None, end_date: date | None = None) -> dict:
        import calendar
        from sqlalchemy import and_
        from app.models.department_model import Department
        now = date.today()

        s_date = start_date
        e_date = end_date

        if not s_date or not e_date:
            s_date = date(now.year, now.month, 1)
            last_day = calendar.monthrange(now.year, now.month)[1]
            e_date = date(now.year, now.month, last_day)

        start_time = datetime.combine(s_date, datetime.min.time())
        end_time = datetime.combine(e_date, datetime.max.time())
        
        query = (
            select(
                Department.department_name,
                func.coalesce(func.sum(Payment.amount), 0.0).label('revenue'),
                func.count(func.distinct(
                    case((and_(Appointment.appointment_date >= s_date, Appointment.appointment_date <= e_date), Appointment.patient_id), else_=None)
                )).label('patient_count'),
                func.count(func.distinct(
                    case((and_(Appointment.appointment_date >= s_date, Appointment.appointment_date <= e_date), Appointment.id), else_=None)
                )).label('appointment_count')
            )
            .select_from(Department)
            .outerjoin(Appointment, Department.department_id == Appointment.department_id)
            .outerjoin(Billing, Appointment.id == Billing.appointment_id)
            .outerjoin(Payment, (Billing.id == Payment.billing_id) & (Payment.status == "completed") & (Payment.is_refund == False) & (Payment.payment_date >= start_time) & (Payment.payment_date <= end_time))
            .group_by(Department.department_id, Department.department_name)
        )
        
        result = await self.db.execute(query)
        rows = result.all()
        
        departments = []
        total_revenue = 0.0
        
        for row in rows:
            rev = float(row.revenue)
            total_revenue += rev
            departments.append({
                "department_name": row.department_name,
                "revenue": rev,
                "patient_count": row.patient_count,
                "appointment_count": row.appointment_count
            })
            
        return {
            "total_revenue": total_revenue,
            "departments": departments
        }

    async def get_pharmacy_profit_loss(self, start_date, end_date) -> dict:
        from app.models.pharmacy_model import PharmacyInvoice, Purchase, Medicine
        from sqlalchemy import select, func, and_
        from datetime import datetime, date
        import calendar

        now = date.today()
        s_date = start_date
        e_date = end_date
        if not s_date or not e_date:
            s_date = date(now.year, now.month, 1)
            last_day = calendar.monthrange(now.year, now.month)[1]
            e_date = date(now.year, now.month, last_day)

        start_time = datetime.combine(s_date, datetime.min.time())
        end_time = datetime.combine(e_date, datetime.max.time())

        sales_query = select(
            func.coalesce(func.sum(PharmacyInvoice.total_amount), 0.0).label('total_sales'),
            func.count(PharmacyInvoice.id).label('invoice_count')
        ).where(
            and_(
                PharmacyInvoice.is_deleted == False,
                PharmacyInvoice.status != 'cancelled',
                PharmacyInvoice.created_at >= start_time,
                PharmacyInvoice.created_at <= end_time
            )
        )
        
        cost_query = select(
            func.coalesce(func.sum(Purchase.total_amount), 0.0).label('total_cost')
        ).where(
            and_(
                Purchase.status != 'cancelled',
                Purchase.ordered_at >= start_time,
                Purchase.ordered_at <= end_time
            )
        )
        
        medicine_query = select(func.count(Medicine.id).label('medicine_count')).where(
            Medicine.is_deleted == False,
            Medicine.is_active == True
        )
        
        sales_result = await self.db.execute(sales_query)
        sales_row = sales_result.first()
        
        cost_result = await self.db.execute(cost_query)
        cost_row = cost_result.first()
        
        med_result = await self.db.execute(medicine_query)
        med_row = med_result.first()
        
        total_sales = float(sales_row.total_sales) if sales_row else 0.0
        invoice_count = int(sales_row.invoice_count) if sales_row else 0
        total_cost = float(cost_row.total_cost) if cost_row else 0.0
        medicine_count = int(med_row.medicine_count) if med_row else 0
        
        return {
            "total_sales": total_sales,
            "total_cost": total_cost,
            "gross_profit": total_sales - total_cost,
            "invoice_count": invoice_count,
            "medicine_count": medicine_count
        }

    async def get_lab_summary(self, start_time, end_time) -> dict:
        from app.models.lab_model import TestOrder, LabTest
        from sqlalchemy import select, func, and_, case
        from datetime import datetime, date
        
        query = select(
            func.count(TestOrder.id).label('total_orders'),
            func.sum(case((TestOrder.status == 'completed', 1), else_=0)).label('completed_orders'),
            func.sum(case((TestOrder.status != 'completed', 1), else_=0)).label('pending_orders'),
            func.coalesce(func.sum(LabTest.price), 0.0).label('total_revenue')
        ).join(LabTest, LabTest.id == TestOrder.lab_test_id).where(
            and_(
                TestOrder.is_deleted == False,
                TestOrder.ordered_at >= start_time,
                TestOrder.ordered_at <= end_time
            )
        )
        
        result = await self.db.execute(query)
        row = result.first()
        
        return {
            'total_orders': int(row.total_orders) if row and row.total_orders else 0,
            'completed_orders': int(row.completed_orders) if row and row.completed_orders else 0,
            'pending_orders': int(row.pending_orders) if row and row.pending_orders else 0,
            'total_revenue': float(row.total_revenue) if row and row.total_revenue else 0.0
        }

    async def get_lab_performance(self, start_time, end_time) -> dict:
        from app.models.lab_model import TestOrder
        from sqlalchemy import select, func, and_, case, text
        from datetime import datetime, date
        
        query = select(
            func.count(TestOrder.id).label('total_orders'),
            func.sum(case((TestOrder.status == 'completed', 1), else_=0)).label('completed_orders')
        ).where(
            and_(
                TestOrder.is_deleted == False,
                TestOrder.ordered_at >= start_time,
                TestOrder.ordered_at <= end_time
            )
        )
        
        result = await self.db.execute(query)
        row = result.first()
        
        avg_query = select(
            func.avg(
                func.timestampdiff(
                    text('HOUR'), TestOrder.ordered_at, TestOrder.completed_at
                )
            ).label('avg_hours')
        ).where(
            and_(
                TestOrder.is_deleted == False,
                TestOrder.status == 'completed',
                TestOrder.completed_at != None,
                TestOrder.ordered_at >= start_time,
                TestOrder.ordered_at <= end_time
            )
        )
        avg_result = await self.db.execute(avg_query)
        avg_row = avg_result.first()
        avg_hours = float(avg_row.avg_hours) if avg_row and avg_row.avg_hours is not None else None
        
        return {
            'total_orders': int(row.total_orders) if row and row.total_orders else 0,
            'completed_orders': int(row.completed_orders) if row and row.completed_orders else 0,
            'average_turnaround_hours': avg_hours
        }

    async def get_lab_revenue(self, start_time, end_time) -> dict:
        from app.models.lab_model import TestOrder, LabTest
        from sqlalchemy import select, func, and_, case
        from datetime import datetime, date
        
        total_query = select(
            func.coalesce(func.sum(LabTest.price), 0.0).label('total_revenue')
        ).select_from(TestOrder).join(LabTest, LabTest.id == TestOrder.lab_test_id).where(
            and_(
                TestOrder.is_deleted == False,
                TestOrder.ordered_at >= start_time,
                TestOrder.ordered_at <= end_time
            )
        )
        total_result = await self.db.execute(total_query)
        total_row = total_result.first()
        total_revenue = float(total_row.total_revenue) if total_row and total_row.total_revenue else 0.0
        
        by_test_query = select(
            LabTest.test_name,
            func.count(TestOrder.id).label('order_count'),
            func.coalesce(func.sum(LabTest.price), 0.0).label('revenue')
        ).select_from(TestOrder).join(LabTest, LabTest.id == TestOrder.lab_test_id).where(
            and_(
                TestOrder.is_deleted == False,
                TestOrder.ordered_at >= start_time,
                TestOrder.ordered_at <= end_time
            )
        ).group_by(LabTest.test_name).order_by(func.sum(LabTest.price).desc())
        
        by_test_result = await self.db.execute(by_test_query)
        revenue_by_test = [
            {
                'test_name': row.test_name,
                'order_count': int(row.order_count),
                'revenue': float(row.revenue)
            }
            for row in by_test_result.all()
        ]
        
        return {
            'total_revenue': total_revenue,
            'revenue_by_test': revenue_by_test
        }

    async def get_doctor_lab_reports(self, start_time, end_time) -> dict:
        from app.models.lab_model import TestOrder
        from app.models.doctor_model import Doctor
        from sqlalchemy import select, func, and_, case
        
        query = select(
            func.concat(Doctor.first_name, ' ', Doctor.last_name).label('doctor_name'),
            func.count(TestOrder.id).label('total_lab_orders'),
            func.sum(case((TestOrder.status == 'completed', 1), else_=0)).label('completed_reports'),
            func.sum(case((TestOrder.status == 'pending', 1), (TestOrder.status == 'ordered', 1), else_=0)).label('pending_reports'),
            func.sum(case((TestOrder.status == 'cancelled', 1), else_=0)).label('cancelled_reports')
        ).join(TestOrder, TestOrder.doctor_id == Doctor.id).where(
            and_(
                TestOrder.is_deleted == False,
                TestOrder.ordered_at >= start_time,
                TestOrder.ordered_at <= end_time
            )
        ).group_by(Doctor.id).order_by(func.count(TestOrder.id).desc())
        
        result = await self.db.execute(query)
        reports = [
            {
                'doctor_name': row.doctor_name,
                'total_lab_orders': int(row.total_lab_orders),
                'completed_reports': int(row.completed_reports),
                'pending_reports': int(row.pending_reports),
                'cancelled_reports': int(row.cancelled_reports)
            }
            for row in result.all()
        ]
        
        return {'reports': reports}
