from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LabOrderStatus, LabReportStatus, SampleStatus
from app.core.exceptions import BadRequestException, NotFoundException
from app.models.lab_model import LabReport, LabTest, Sample, TestOrder, TestResult
from app.repositories.audit_repository import AuditRepository
from app.repositories.department_repository import DepartmentRepository
from app.repositories.lab_repository import (
    LabReportRepository,
    LabTestRepository,
    SampleRepository,
    TestOrderRepository,
    TestResultRepository,
)
from app.schemas.lab_schema import (
    CriticalAlert,
    LabReportApprove,
    LabReportCreate,
    LabReportResponse,
    LabTestCreate,
    LabTestResponse,
    LabTestUpdate,
    SampleCreate,
    SampleUpdate,
    SampleResponse,
    TestOrderCreate,
    TestOrderUpdate,
    TestOrderResponse,
    TestResultCreate,
    TestResultResponse,
)
from app.utils.helpers import generate_lab_order_number, generate_lab_report_number, generate_lab_test_code, generate_sample_code, utc_now
from app.utils.pagination import build_paginated_result
from app.utils.pdf_generator import generate_lab_report_html


class LabService:
    def __init__(self, db: AsyncSession):
        self.test_repo = LabTestRepository(db)
        self.order_repo = TestOrderRepository(db)
        self.sample_repo = SampleRepository(db)
        self.result_repo = TestResultRepository(db)
        self.report_repo = LabReportRepository(db)
        self.audit_repo = AuditRepository(db)
        self.dept_repo = DepartmentRepository(db)

    async def _validate_department(self, department_id: int | None) -> None:
        if department_id is not None:
            dept = await self.dept_repo.get_by_id(department_id)
            if not dept:
                raise NotFoundException(f"Department with ID {department_id} not found")

    # --- Lab Test Catalog ---
    async def create_test(self, data: LabTestCreate, user_id: int) -> LabTestResponse:
        await self._validate_department(data.department_id)
        test = LabTest(test_code=generate_lab_test_code(), **data.model_dump())
        test = await self.test_repo.create(test)
        await self.audit_repo.create("create", "lab", user_id=user_id, resource_id=str(test.id))
        return LabTestResponse.model_validate(test)

    async def list_tests(
        self, page: int = 1, size: int = 20, sort_by: str = "created_at",
        sort_order: str = "desc", category: str | None = None,
    ):
        skip = (page - 1) * size
        items = await self.test_repo.list_all(skip=skip, limit=size, sort_by=sort_by,
                                               sort_order=sort_order, category=category)
        total = await self.test_repo.count_all(category=category)
        return build_paginated_result([LabTestResponse.model_validate(t) for t in items], total, page, size)

    async def search_tests(self, q: str, page: int = 1, size: int = 20):
        skip = (page - 1) * size
        items = await self.test_repo.search(q, skip=skip, limit=size)
        total = await self.test_repo.count_search(q)
        return build_paginated_result([LabTestResponse.model_validate(t) for t in items], total, page, size)

    async def get_test(self, test_id: int) -> LabTestResponse:
        test = await self.test_repo.get_by_id(test_id)
        if not test:
            raise NotFoundException("Lab test not found")
        return LabTestResponse.model_validate(test)

    async def update_test(self, test_id: int, data: LabTestUpdate, user_id: int) -> LabTestResponse:
        test = await self.test_repo.get_by_id(test_id)
        if not test:
            raise NotFoundException("Lab test not found")
        await self._validate_department(data.department_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(test, key, value)
        test = await self.test_repo.update(test)
        await self.audit_repo.create("update", "lab", user_id=user_id, resource_id=str(test.id))
        return LabTestResponse.model_validate(test)

    async def delete_test(self, test_id: int, user_id: int) -> None:
        test = await self.test_repo.get_by_id(test_id)
        if not test:
            raise NotFoundException("Lab test not found")
        await self.test_repo.soft_delete(test)
        await self.audit_repo.create("delete", "lab", user_id=user_id, resource_id=str(test.id))

    # --- Test Orders ---
    async def create_order(self, data: TestOrderCreate, user_id: int) -> TestOrderResponse:
        test = await self.test_repo.get_by_id(data.lab_test_id)
        if not test or not test.is_active:
            raise NotFoundException("Lab test not found or inactive")
        await self._validate_department(test.department_id)
        order = TestOrder(
            order_number=generate_lab_order_number(),
            ordered_at=utc_now(),
            department_id=test.department_id,
            **data.model_dump(),
        )
        order = await self.order_repo.create(order)
        await self.audit_repo.create("create", "lab_order", user_id=user_id, resource_id=str(order.id))
        return await self.get_order(order.id)

    async def list_orders(
        self, page: int = 1, size: int = 20, status: str | None = None, patient_id: int | None = None
    ):
        skip = (page - 1) * size
        items = await self.order_repo.list_all(skip=skip, limit=size, status=status, patient_id=patient_id)
        total = await self.order_repo.count_all(status=status, patient_id=patient_id)
        return build_paginated_result([self._order_response(o) for o in items], total, page, size)

    async def get_order(self, order_id: int) -> TestOrderResponse:
        order = await self.order_repo.get_by_id(order_id)
        if not order:
            raise NotFoundException("Test order not found")
        return self._order_response(order)

    async def update_order(
        self,
        order_id: int,
        data: TestOrderUpdate,
        user_id: int,
)     -> TestOrderResponse:
        order = await self.order_repo.get_by_id(order_id)

        if not order:
            raise NotFoundException("Test order not found")

        update_data = data.model_dump(exclude_unset=True)

        if "lab_test_id" in update_data:
            test = await self.test_repo.get_by_id(update_data["lab_test_id"])
            if not test or not test.is_active:
                raise NotFoundException("Lab test not found or inactive")
            update_data["department_id"] = test.department_id

        for key, value in update_data.items():
            setattr(order, key, value)

        order = await self.order_repo.update(order)

        await self.audit_repo.create(
            "update",
            "lab_order",
             user_id=user_id,
             resource_id=str(order.id),
        )

        return self._order_response(order)


    async def delete_order(self, order_id: int, user_id: int) -> None:
        order = await self.order_repo.get_by_id(order_id)

        if not order:
            raise NotFoundException("Test order not found")

        await self.order_repo.soft_delete(order)

        await self.audit_repo.create(
            "delete",
            "lab_order",
             user_id=user_id,
             resource_id=str(order.id),
        )

    def _order_response(self, order: TestOrder) -> TestOrderResponse:
        resp = TestOrderResponse.model_validate(order)
        if order.lab_test:
            resp.lab_test = LabTestResponse.model_validate(order.lab_test)
        return resp

    async def get_pending_tests(self, page: int = 1, size: int = 20):
        return await self.list_orders(page=page, size=size, status=LabOrderStatus.ORDERED)

    async def get_completed_tests(self, page: int = 1, size: int = 20):
        return await self.list_orders(page=page, size=size, status=LabOrderStatus.COMPLETED)

    # --- Samples ---
    async def collect_sample(self, data: SampleCreate, user_id: int) -> SampleResponse:
        order = await self.order_repo.get_by_id(data.test_order_id)
        if not order:
            raise NotFoundException("Test order not found")
        sample = Sample(
            test_order_id=data.test_order_id,
            sample_code=generate_sample_code(),
            sample_type=data.sample_type,
            collected_at=utc_now(),
            collection_date=data.collection_date,
            collected_by=user_id,
            status=data.status,
            volume=data.volume,
            notes=data.notes,
        )
        sample = await self.sample_repo.create(sample)
        order.status = LabOrderStatus.SAMPLE_COLLECTED
        await self.order_repo.update(order)
        await self.audit_repo.create("create", "lab_sample", user_id=user_id, resource_id=str(sample.id))
        return SampleResponse.model_validate(sample)

    async def list_samples(self, page: int = 1, size: int = 20, status: str | None = None):
        skip = (page - 1) * size
        items = await self.sample_repo.list_all(skip=skip, limit=size, status=status)
        total = await self.sample_repo.count_all(status=status)
        return build_paginated_result([SampleResponse.model_validate(s) for s in items], total, page, size)

    async def get_sample(self, sample_id: int) -> SampleResponse:
        sample = await self.sample_repo.get_by_id(sample_id)

        if not sample:
            raise NotFoundException("Sample not found")

        return SampleResponse.model_validate(sample)

    async def update_sample(
        self,
        sample_id: int,
        data: SampleUpdate,
        user_id: int,
    ) -> SampleResponse:
        sample = await self.sample_repo.get_by_id(sample_id)

        if not sample:
            raise NotFoundException("Sample not found")

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(sample, key, value)

        sample = await self.sample_repo.update(sample)

        await self.audit_repo.create(
            "update",
            "lab_sample",
            user_id=user_id,
            resource_id=str(sample.id),
        )

        return SampleResponse.model_validate(sample)

    async def delete_sample(
        self,
        sample_id: int,
        user_id: int,
    ) -> None:
        sample = await self.sample_repo.get_by_id(sample_id)

        if not sample:
            raise NotFoundException("Sample not found")

        await self.sample_repo.delete(sample)

        await self.audit_repo.create(
            "delete",
            "lab_sample",
            user_id=user_id,
            resource_id=str(sample.id),
        )     

    # --- Results ---
    async def enter_result(self, data: TestResultCreate, user_id: int) -> TestResultResponse:
        order = await self.order_repo.get_by_id(data.test_order_id)
        if not order:
            raise NotFoundException("Test order not found")
        result = TestResult(
            entered_by=user_id,
            entered_at=utc_now(),
            status="completed",
            **data.model_dump(),
        )
        result = await self.result_repo.create(result)
        order.status = LabOrderStatus.IN_PROGRESS
        await self.order_repo.update(order)
        await self.audit_repo.create("create", "lab_result", user_id=user_id, resource_id=str(result.id))
        return TestResultResponse.model_validate(result)

    async def list_results(
        self, page: int = 1, size: int = 20, test_order_id: int | None = None, is_critical: bool | None = None
    ):
        skip = (page - 1) * size
        items = await self.result_repo.list_all(skip=skip, limit=size, test_order_id=test_order_id, is_critical=is_critical)
        total = await self.result_repo.count_all(test_order_id=test_order_id, is_critical=is_critical)
        return build_paginated_result([TestResultResponse.model_validate(r) for r in items], total, page, size)

    async def get_critical_alerts(self) -> list[CriticalAlert]:
        results = await self.result_repo.get_critical_alerts()
        alerts = []
        for r in results:
            order = await self.order_repo.get_by_id(r.test_order_id)
            alerts.append(CriticalAlert(
                result_id=r.id,
                test_order_id=r.test_order_id,
                order_number=order.order_number if order else "",
                patient_id=order.patient_id if order else 0,
                parameter_name=r.parameter_name,
                result_value=r.result_value,
                entered_at=r.entered_at,
            ))
        return alerts

    # --- Reports ---
    async def create_report(self, data: LabReportCreate, user_id: int) -> LabReportResponse:
        order = await self.order_repo.get_by_id(data.test_order_id)
        if not order:
            raise NotFoundException("Test order not found")
        report = LabReport(
            test_order_id=data.test_order_id,
            report_number=generate_lab_report_number(),
            summary=data.summary,
            status=LabReportStatus.DRAFT,
            generated_at=utc_now(),
        )
        report = await self.report_repo.create(report)
        await self.audit_repo.create("create", "lab_report", user_id=user_id, resource_id=str(report.id))
        return LabReportResponse.model_validate(report)

    async def list_reports(self, page: int = 1, size: int = 20, status: str | None = None):
        skip = (page - 1) * size
        items = await self.report_repo.list_all(skip=skip, limit=size, status=status)
        total = await self.report_repo.count_all(status=status)
        return build_paginated_result([LabReportResponse.model_validate(r) for r in items], total, page, size)

    async def approve_report(self, report_id: int, data: LabReportApprove, user_id: int) -> LabReportResponse:
        report = await self.report_repo.get_by_id(report_id)
        if not report:
            raise NotFoundException("Lab report not found")
        if report.status == LabReportStatus.APPROVED:
            raise BadRequestException("Report already approved")

        report.status = LabReportStatus.APPROVED if data.approved else LabReportStatus.REJECTED
        report.approved_by = user_id
        report.approved_at = utc_now()
        if data.summary:
            report.summary = data.summary

        order = await self.order_repo.get_by_id(report.test_order_id)
        if order and data.approved:
            order.status = LabOrderStatus.COMPLETED
            order.completed_at = utc_now()
            await self.order_repo.update(order)
            path = await generate_lab_report_html(
                report.report_number,
                {"summary": report.summary or "", "order_number": order.order_number},
            )
            report.report_path = path

        report = await self.report_repo.update(report)
        await self.audit_repo.create("approve", "lab_report", user_id=user_id, resource_id=str(report.id))
        return LabReportResponse.model_validate(report)
