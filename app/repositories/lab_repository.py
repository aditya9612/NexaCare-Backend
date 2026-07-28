from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.lab_model import LabReport, LabTest, Sample, TestOrder, TestResult
from app.utils.helpers import utc_now


class LabTestRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return select(LabTest).where(LabTest.is_deleted.is_(False))

    async def list_all(
        self, skip: int = 0, limit: int = 20, sort_by: str = "created_at",
        sort_order: str = "desc", category: str | None = None, doctor_id: int | None = None
    ) -> list[LabTest]:
        query = self._base_query()
        if category:
            query = query.where(LabTest.category == category)
        if doctor_id is not None:
            query = query.where(LabTest.doctor_id == doctor_id)
        column = getattr(LabTest, sort_by, LabTest.created_at)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_all(self, category: str | None = None, doctor_id: int | None = None) -> int:
        query = select(func.count()).select_from(LabTest).where(LabTest.is_deleted.is_(False))
        if category:
            query = query.where(LabTest.category == category)
        if doctor_id is not None:
            query = query.where(LabTest.doctor_id == doctor_id)
        return (await self.db.scalar(query)) or 0

    async def search(self, q: str, skip: int = 0, limit: int = 20, doctor_id: int | None = None) -> list[LabTest]:
        pattern = f"%{q.lower()}%"
        query = self._base_query().where(
            or_(
                func.lower(LabTest.test_name).like(pattern),
                func.lower(LabTest.test_code).like(pattern),
                func.lower(LabTest.category).like(pattern),
            )
        )
        if doctor_id is not None:
            query = query.where(LabTest.doctor_id == doctor_id)
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_search(self, q: str, doctor_id: int | None = None) -> int:
        pattern = f"%{q.lower()}%"
        query = select(func.count()).select_from(LabTest).where(
            LabTest.is_deleted.is_(False),
            or_(
                func.lower(LabTest.test_name).like(pattern),
                func.lower(LabTest.test_code).like(pattern),
            ),
        )
        if doctor_id is not None:
            query = query.where(LabTest.doctor_id == doctor_id)
        return (await self.db.scalar(query)) or 0

    async def get_by_id(self, test_id: int) -> LabTest | None:
        result = await self.db.execute(self._base_query().where(LabTest.id == test_id))
        return result.scalar_one_or_none()

    async def create(self, test: LabTest) -> LabTest:
        self.db.add(test)
        await self.db.flush()
        await self.db.refresh(test)
        return test

    async def update(self, test: LabTest) -> LabTest:
        await self.db.flush()
        await self.db.refresh(test)
        return test

    async def soft_delete(self, test: LabTest) -> None:
        test.is_deleted = True
        test.deleted_at = utc_now()
        await self.db.flush()


class TestOrderRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return (
            select(TestOrder)
            .where(TestOrder.is_deleted.is_(False))
            .options(selectinload(TestOrder.lab_test))
        )

    async def list_all(
        self, skip: int = 0, limit: int = 20, status: str | None = None, patient_id: int | None = None, doctor_id: int | None = None, department_id: int | None = None
    ) -> list[TestOrder]:
        query = self._base_query()
        if status:
            query = query.where(TestOrder.status == status)
        if patient_id:
            query = query.where(TestOrder.patient_id == patient_id)
        if doctor_id is not None:
            query = query.where(TestOrder.doctor_id == doctor_id)
        if department_id is not None:
            query = query.where(TestOrder.department_id == department_id)
        result = await self.db.execute(query.order_by(TestOrder.ordered_at.desc()).offset(skip).limit(limit))
        return list(result.scalars().unique().all())

    async def count_all(self, status: str | None = None, patient_id: int | None = None, doctor_id: int | None = None, department_id: int | None = None) -> int:
        query = select(func.count()).select_from(TestOrder).where(TestOrder.is_deleted.is_(False))
        if status:
            query = query.where(TestOrder.status == status)
        if patient_id:
            query = query.where(TestOrder.patient_id == patient_id)
        if doctor_id is not None:
            query = query.where(TestOrder.doctor_id == doctor_id)
        if department_id is not None:
            query = query.where(TestOrder.department_id == department_id)
        return (await self.db.scalar(query)) or 0

    async def get_by_id(self, order_id: int) -> TestOrder | None:
        result = await self.db.execute(self._base_query().where(TestOrder.id == order_id))
        return result.scalar_one_or_none()

    async def create(self, order: TestOrder) -> TestOrder:
        self.db.add(order)
        await self.db.flush()
        await self.db.refresh(order)
        return order

    async def update(self, order: TestOrder) -> TestOrder:
        await self.db.flush()
        await self.db.refresh(order)
        return order

    async def soft_delete(self, order: TestOrder) -> None:
        order.is_deleted = True
        order.deleted_at = utc_now()
        await self.db.flush()


class SampleRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self, skip: int = 0, limit: int = 20, status: str | None = None, department_id: int | None = None) -> list[Sample]:
        query = select(Sample).join(TestOrder, Sample.test_order_id == TestOrder.id)
        if status:
            query = query.where(Sample.status == status)
        if department_id:
                query = query.where(TestOrder.department_id == department_id)
        result = await self.db.execute(query.order_by(Sample.created_at.desc()).offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_all(self, status: str | None = None, department_id: int | None = None) -> int:
        query = select(func.count()).select_from(Sample).join(TestOrder, Sample.test_order_id == TestOrder.id)
        if status:
            query = query.where(Sample.status == status)
        if department_id:
            query = query.where(TestOrder.department_id == department_id)
        return (await self.db.scalar(query)) or 0

    async def get_by_id(self, sample_id: int) -> Sample | None:
        result = await self.db.execute(
            select(Sample).where(Sample.id == sample_id)
        )
        return result.scalar_one_or_none() 

    async def get_by_test_order(self, test_order_id: int) -> Sample | None:
        result = await self.db.execute(
            select(Sample)
            .where(Sample.test_order_id == test_order_id)
            .order_by(Sample.created_at.desc())
            .limit(1)
       )
        return result.scalar_one_or_none()       

    async def create(self, sample: Sample) -> Sample:
        self.db.add(sample)
        await self.db.flush()
        await self.db.refresh(sample)
        return sample

    async def update(self, sample: Sample) -> Sample:
        await self.db.flush()
        await self.db.refresh(sample)
        return sample  

    async def delete(self, sample: Sample) -> None:
        await self.db.delete(sample)
        await self.db.flush()       


class TestResultRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(
        self, skip: int = 0, limit: int = 20, test_order_id: int | None = None, is_critical: bool | None = None, department_id: int | None = None
    ) -> list[TestResult]:
        query = (
            select(TestResult)
            .join(TestOrder, TestResult.test_order_id == TestOrder.id)
        )
        if test_order_id:
            query = query.where(TestResult.test_order_id == test_order_id)
        if is_critical is not None:
            query = query.where(TestResult.is_critical.is_(is_critical))
        if department_id:
            query = query.where(TestOrder.department_id == department_id)    
        result = await self.db.execute(query.order_by(TestResult.created_at.desc()).offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_all(self, test_order_id: int | None = None, is_critical: bool | None = None, department_id: int | None = None) -> int:
        query = (
            select(func.count())
            .select_from(TestResult)
            .join(TestOrder, TestResult.test_order_id == TestOrder.id)
        )
        if test_order_id:
            query = query.where(TestResult.test_order_id == test_order_id)
        if is_critical is not None:
            query = query.where(TestResult.is_critical.is_(is_critical))
        if department_id:
            query = query.where(TestOrder.department_id == department_id)
        return (await self.db.scalar(query)) or 0

    async def get_by_test_order(self, test_order_id: int) -> TestResult | None:
        result = await self.db.execute(
            select(TestResult).where(TestResult.test_order_id == test_order_id)
        )
        return result.scalar_one_or_none()    

    async def create(self, result: TestResult) -> TestResult:
        self.db.add(result)
        await self.db.flush()
        await self.db.refresh(result)
        return result

    async def get_by_id(self, result_id: int) -> TestResult | None:
        result = await self.db.execute(
            select(TestResult).where(TestResult.id == result_id)
        )
        return result.scalar_one_or_none()

    async def update(self, result: TestResult) -> TestResult:
        await self.db.flush()
        await self.db.refresh(result)
        return result    

    async def get_critical_alerts(
        self,
        skip: int = 0,
        limit: int = 50,
        current_user_id: int | None = None,
        department_id: int | None = None,
    ) -> list[TestResult]:
        query = (
            select(TestResult)
            .join(TestOrder, TestResult.test_order_id == TestOrder.id)
            .where(TestResult.is_critical.is_(True))
        )

        if current_user_id and department_id:
            query = query.where(
                or_(
                    TestResult.entered_by == current_user_id,
                    TestOrder.department_id == department_id,
                )
            )
        elif current_user_id:
            query = query.where(TestResult.entered_by == current_user_id)
        elif department_id:
            query = query.where(TestOrder.department_id == department_id)

        result = await self.db.execute(
            query.order_by(TestResult.created_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())


class LabReportRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(
       self,
       skip: int = 0,
       limit: int = 20,
       status: str | None = None,
       department_id: int | None = None,
       generated_by: int | None = None,
    ) -> list[LabReport]:
        query = (
           select(LabReport)
           .join(TestOrder, LabReport.test_order_id == TestOrder.id)
        )

        if status:
            query = query.where(LabReport.status == status)

        if department_id and generated_by:
            query = query.where(
                or_(
                    TestOrder.department_id == department_id,
                    LabReport.generated_by == generated_by,
                )
            )
        elif department_id:
            query = query.where(TestOrder.department_id == department_id)
        elif generated_by:
            query = query.where(LabReport.generated_by == generated_by) 

        result = await self.db.execute(
            query.order_by(LabReport.created_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def count_all(
        self,
        status: str | None = None,
        department_id: int | None = None,
        generated_by: int | None = None,
    ) -> int:
        query = (
            select(func.count())
            .select_from(LabReport)
            .join(TestOrder, LabReport.test_order_id == TestOrder.id)
        )

        if status:
            query = query.where(LabReport.status == status)

        if department_id and generated_by:
            query = query.where(
                or_(
                    TestOrder.department_id == department_id,
                    LabReport.generated_by == generated_by,
                )
            )
        elif department_id:
            query = query.where(TestOrder.department_id == department_id)
        elif generated_by:
            query = query.where(LabReport.generated_by == generated_by)
        
        return (await self.db.scalar(query)) or 0
      
    async def get_by_id(self, report_id: int) -> LabReport | None:
        result = await self.db.execute(select(LabReport).where(LabReport.id == report_id))
        return result.scalar_one_or_none()

    async def create(self, report: LabReport) -> LabReport:
        self.db.add(report)
        await self.db.flush()
        await self.db.refresh(report)
        return report

    async def update(self, report: LabReport) -> LabReport:
        await self.db.flush()
        await self.db.refresh(report)
        return report

    async def delete(self, report: LabReport) -> None:
        await self.db.delete(report)
        await self.db.flush()

    async def reject_report(
        self,
        report_id: int,
        remarks: str,
        rejected_by: int
    ) -> LabReport | None:
        report = await self.get_by_id(report_id)
        if not report:
            return None
        from app.core.constants import LabReportStatus
        report.status = LabReportStatus.REJECTED
        report.remarks = remarks
        await self.db.flush()
        await self.db.refresh(report)
        return report


    async def get_upcoming_lab_reports(self, doctor_id: int, limit: int = 10) -> list[LabReport]:
        from app.core.constants import LabReportStatus
        query = (
            select(LabReport)
            .join(TestOrder, LabReport.test_order_id == TestOrder.id)
            .where(
                TestOrder.doctor_id == doctor_id,
                TestOrder.is_deleted.is_(False),
                LabReport.status != LabReportStatus.APPROVED
            )
            .order_by(LabReport.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
