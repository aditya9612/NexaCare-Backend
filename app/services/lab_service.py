import os
from uuid import uuid4
from fastapi import UploadFile

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.constants import LabOrderStatus, LabReportStatus, SampleStatus
from app.core.exceptions import BadRequestException, NotFoundException, ForbiddenException, ConflictException
from app.models.lab_model import LabReport, LabTest, Sample, TestOrder, TestResult
from app.models.staff_model import Staff
from app.repositories.audit_repository import AuditRepository
from app.repositories.department_repository import DepartmentRepository
from app.repositories.lab_repository import (
    LabReportRepository,
    LabTestRepository,
    SampleRepository,
    TestOrderRepository,
    TestResultRepository,
)
from app.services.notification_service import NotificationService
from app.schemas.lab_schema import (
    CriticalAlert,
    LabReportApprove,
    RejectLabReportRequest,
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
        self.db = db
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

    async def _validate_doctor_department(self, user_id: int, department_id: int) -> None:
        from sqlalchemy import select
        from app.models.doctor_model import Doctor
        result = await self.db.execute(
            select(Doctor).where(
                Doctor.user_id == user_id,
                Doctor.is_deleted == False
            )
        )
        doctor = result.scalar_one_or_none()
        if doctor:
            if doctor.department_id != department_id:
                raise ForbiddenException("Doctors can only create/update lab tests for their own department")

    # --- Lab Test Catalog ---
    async def create_test(self, data: LabTestCreate, user_id: int) -> LabTestResponse:
        if not data.department_id:
            raise BadRequestException("Department ID is required to create lab test.")
        await self._validate_department(data.department_id)
        await self._validate_doctor_department(user_id, data.department_id)
        
        from app.models.doctor_model import Doctor
        from sqlalchemy import select
        result = await self.db.execute(
            select(Doctor).where(Doctor.user_id == user_id, Doctor.is_deleted == False)
        )
        doctor = result.scalar_one_or_none()
        doctor_id = doctor.id if doctor else None

        test = LabTest(test_code=generate_lab_test_code(), doctor_id=doctor_id, **data.model_dump())
        test = await self.test_repo.create(test)
        await self.audit_repo.create("create", "lab", user_id=user_id, resource_id=str(test.id))
        return LabTestResponse.model_validate(test)

    async def list_tests(
        self, page: int = 1, size: int = 20, sort_by: str = "created_at",
        sort_order: str = "desc", category: str | None = None, doctor_id: int | None = None,
    ):
        skip = (page - 1) * size
        items = await self.test_repo.list_all(skip=skip, limit=size, sort_by=sort_by,
                                               sort_order=sort_order, category=category, doctor_id=doctor_id)
        total = await self.test_repo.count_all(category=category, doctor_id=doctor_id)
        return build_paginated_result([LabTestResponse.model_validate(t) for t in items], total, page, size)

    async def search_tests(self, q: str, page: int = 1, size: int = 20, doctor_id: int | None = None):
        skip = (page - 1) * size
        items = await self.test_repo.search(q, skip=skip, limit=size, doctor_id=doctor_id)
        total = await self.test_repo.count_search(q, doctor_id=doctor_id)
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

        from app.models.doctor_model import Doctor
        from sqlalchemy import select
        result = await self.db.execute(
            select(Doctor).where(Doctor.user_id == user_id, Doctor.is_deleted == False)
        )
        doctor = result.scalar_one_or_none()
        if doctor and test.doctor_id != doctor.id:
            raise ForbiddenException("Doctors can only update lab tests generated by themselves")

        if not data.department_id:
            raise BadRequestException("Department ID is required to update lab test.")
        await self._validate_department(data.department_id)
        await self._validate_doctor_department(user_id, data.department_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(test, key, value)
        test = await self.test_repo.update(test)
        await self.audit_repo.create("update", "lab", user_id=user_id, resource_id=str(test.id))
        return LabTestResponse.model_validate(test)

    async def delete_test(self, test_id: int, user_id: int) -> None:
        test = await self.test_repo.get_by_id(test_id)
        if not test:
            raise NotFoundException("Lab test not found")

        from app.models.doctor_model import Doctor
        from sqlalchemy import select
        result = await self.db.execute(
            select(Doctor).where(Doctor.user_id == user_id, Doctor.is_deleted == False)
        )
        doctor = result.scalar_one_or_none()
        if doctor and test.doctor_id != doctor.id:
            raise ForbiddenException("Doctors can only delete lab tests generated by themselves")

        await self.test_repo.soft_delete(test)
        await self.audit_repo.create("delete", "lab", user_id=user_id, resource_id=str(test.id))

    # --- Test Orders ---
    async def create_order(self, data: TestOrderCreate, user_id: int) -> TestOrderResponse:
        if not data.appointment_id:
            raise BadRequestException("Appointment ID is required to create test order.")
        if not data.doctor_id:
            raise BadRequestException("Doctor ID is required to create test order.")

        # 5. For One appointment_id It Should be Possible to create only One Lab Test Order.
        from sqlalchemy import select
        existing_order_result = await self.db.execute(
            select(TestOrder).where(TestOrder.appointment_id == data.appointment_id, TestOrder.is_deleted == False)
        )
        existing_order = existing_order_result.scalar_one_or_none()
        if existing_order:
            raise ConflictException("A lab test order has already been created for this appointment")

        # Get the appointment and verify basic integrity (patient and doctor match)
        from app.models.appointment_model import Appointment
        appointment_result = await self.db.execute(
            select(Appointment).where(Appointment.id == data.appointment_id)
        )
        appointment = appointment_result.scalar_one_or_none()
        if not appointment:
            raise NotFoundException("Appointment not found")

        # 3. It Should be Possible For Doctor/Staff to Only Put Appointment Id of Selected Patient in appointment_id Field.
        if appointment.patient_id != data.patient_id:
            raise BadRequestException("Appointment patient does not match the test order patient")

        if appointment.doctor_id != data.doctor_id:
            raise BadRequestException("Appointment doctor does not match the test order doctor")

        # Check future date appointments
        from datetime import date
        from app.core.constants import AppointmentStatus
        if appointment.appointment_date is not None and appointment.appointment_date > date.today():
            raise BadRequestException("Cannot create test order for future date appointments")

        # Check completed appointments only
        appointment_status = (appointment.appointment_status or "").strip().lower()
        completed_status = AppointmentStatus.COMPLETED.strip().lower()
        if appointment_status != completed_status:
            raise BadRequestException("Can only create test order for completed appointments")

        # Resolve doctor profile of logged-in user
        from app.models.doctor_model import Doctor
        doc_result = await self.db.execute(
            select(Doctor).where(Doctor.user_id == user_id, Doctor.is_deleted == False)
        )
        doctor = doc_result.scalar_one_or_none()

        if doctor:
            # 2. It Should be Possible For Doctor to Only Put His Doctor Id in doctor_id Field.
            if data.doctor_id != doctor.id:
                raise ForbiddenException("Doctors can only create test orders using their own doctor ID")
            # 1. It Should be Possible For Doctor to Create Test order for his Patients Only.
            if appointment.doctor_id != doctor.id:
                raise ForbiddenException("Doctors can only create test orders for their own patients")

        test = await self.test_repo.get_by_id(data.lab_test_id)
        if not test or not test.is_active:
            raise NotFoundException("Lab test not found or inactive")

        if doctor:
            # 4. It Should be Possible For Doctor to Only Put Lab Test Id of Lab Tests Created by Him in lab_test_id Field.
            if test.doctor_id != doctor.id:
                raise ForbiddenException("Doctors can only order lab tests created by themselves")

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
        self,
        page: int = 1,
        size: int = 20,
        status: str | None = None,
        patient_id: int | None = None,
        doctor_id: int | None = None,
        current_user=None,
    ):
        skip = (page - 1) * size
        department_id = None

        if current_user:
            role_name = current_user.role.name.lower() if current_user.role else ""
            if role_name == "doctor":
                from app.repositories.doctor_repository import DoctorRepository
                doctor = await DoctorRepository(self.db).get_by_user_id(current_user.id)
                if doctor:
                    doctor_id = doctor.id
            elif role_name == "patient":
                from app.models.patient_model import Patient
                result = await self.db.execute(
                    select(Patient).where(Patient.user_id == current_user.id, Patient.is_deleted == False)
                )
                patient = result.scalar_one_or_none()
                if patient:
                    patient_id = patient.id
            elif role_name in ["lab technician", "lab_technician"]:
                result = await self.db.execute(
                    select(Staff).where(Staff.email == current_user.email)
                )
                staff = result.scalar_one_or_none()
                department_id = staff.department_id if staff else None

        items = await self.order_repo.list_all(
            skip=skip,
            limit=size,
            status=status,
            patient_id=patient_id,
            doctor_id=doctor_id,
            department_id=department_id,
        )
        total = await self.order_repo.count_all(
            status=status,
            patient_id=patient_id,
            doctor_id=doctor_id,
            department_id=department_id,
        )
        return build_paginated_result([self._order_response(o) for o in items], total, page, size)

    async def get_order(self, order_id: int) -> TestOrderResponse:
        order = await self.order_repo.get_by_id(order_id)
        if not order:
            raise NotFoundException("Test order not found")
        return self._order_response(order)

    async def update_order(self, order_id: int, data: TestOrderUpdate, user_id: int) -> TestOrderResponse:
        order = await self.order_repo.get_by_id(order_id)
        if not order:
            raise NotFoundException("Test order not found")

        # Get final values for validation
        p_id = data.patient_id if data.patient_id is not None else order.patient_id
        d_id = data.doctor_id if data.doctor_id is not None else order.doctor_id
        a_id = data.appointment_id if data.appointment_id is not None else order.appointment_id

        from app.models.patient_model import Patient
        from app.models.doctor_model import Doctor
        from app.models.appointment_model import Appointment

        if data.patient_id is not None:
            patient = await self.db.get(Patient, data.patient_id)
            if not patient:
                raise NotFoundException(f"Patient with ID {data.patient_id} not found")

        if data.doctor_id is not None:
            doctor = await self.db.get(Doctor, data.doctor_id)
            if not doctor:
                raise NotFoundException(f"Doctor with ID {data.doctor_id} not found")

        if data.lab_test_id is not None:
            test = await self.test_repo.get_by_id(data.lab_test_id)
            if not test or not test.is_active:
                raise NotFoundException("Lab test not found or inactive")
            order.department_id = test.department_id

        if a_id is not None:
            appointment = await self.db.get(Appointment, a_id)
            if not appointment:
                raise NotFoundException(f"Appointment with ID {a_id} not found")
            if appointment.patient_id != p_id or appointment.doctor_id != d_id:
                raise BadRequestException("Appointment does not match patient and doctor")

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(order, key, value)

        order = await self.order_repo.update(order)
        await self.audit_repo.create("update", "lab_order", user_id=user_id, resource_id=str(order.id))
        return self._order_response(order)

    async def delete_order(self, order_id: int, user_id: int) -> None:
        order = await self.order_repo.get_by_id(order_id)
        if not order:
            raise NotFoundException("Test order not found")
        await self.order_repo.soft_delete(order)
        await self.audit_repo.create("delete", "lab_order", user_id=user_id, resource_id=str(order.id))



    def _order_response(self, order: TestOrder) -> TestOrderResponse:
        resp = TestOrderResponse.model_validate(order)
        if order.lab_test:
            resp.lab_test = LabTestResponse.model_validate(order.lab_test)
        return resp

    async def get_pending_tests(self, page: int = 1, size: int = 20,  current_user=None):
        return await self.list_orders(page=page, size=size, status=LabOrderStatus.ORDERED, current_user=current_user)

    async def get_completed_tests(self, page: int = 1, size: int = 20, current_user=None):
        return await self.list_orders(page=page, size=size, status=LabOrderStatus.COMPLETED,  current_user=current_user,)

    # --- Samples ---
    async def collect_sample(self, data: SampleCreate, current_user) -> SampleResponse:
        order = await self.order_repo.get_by_id(data.test_order_id)
        if not order:
            raise NotFoundException("Test order not found")
        user_id = current_user.id
        role_name = current_user.role.name.lower() if current_user and current_user.role else ""

        if role_name in ["lab technician", "lab_technician"]:
            result = await self.db.execute(
                select(Staff).where(Staff.email == current_user.email)
            )
            staff = result.scalar_one_or_none()

            if not staff or not staff.department_id:
                raise BadRequestException("Lab technician department is not assigned")

            if order.department_id != staff.department_id:
                raise BadRequestException(
                    "You can collect samples only for test orders of your department"
                )
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

    async def list_samples(self, page: int = 1, size: int = 20, status: str | None = None, current_user=None):
        skip = (page - 1) * size

        department_id = None
        role_name = current_user.role.name.lower() if current_user and current_user.role else ""

        if role_name in ["lab technician", "lab_technician"]:
            result = await self.db.execute(
                select(Staff).where(Staff.email == current_user.email)
            )
            staff = result.scalar_one_or_none()
            department_id = staff.department_id if staff else None

        items = await self.sample_repo.list_all(
            skip=skip,
            limit=size,
            status=status,
            department_id=department_id,
        )

        total = await self.sample_repo.count_all(
            status=status,
            department_id=department_id,
        )
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
    async def enter_result(
        self,
        data: TestResultCreate,
        current_user,
        document: UploadFile | None = None,
    ) -> TestResultResponse:
        sample = await self.sample_repo.get_by_id(data.sample_id)
        if not sample:
            raise NotFoundException("Sample not found")

        if sample.status != SampleStatus.COLLECTED:
            raise BadRequestException(
                "You cannot enter test result before collecting sample"
            )

        order = await self.order_repo.get_by_id(sample.test_order_id)
        if not order:
            raise NotFoundException("Test order not found")

        role_name = current_user.role.name.lower() if current_user and current_user.role else ""

        if role_name in ["lab technician", "lab_technician"]:
            result = await self.db.execute(
                select(Staff).where(Staff.email == current_user.email)
            )
            staff = result.scalar_one_or_none()

            if not staff or not staff.department_id:
                raise BadRequestException("Lab technician department is not assigned")

            if order.department_id != staff.department_id:
                raise BadRequestException(
                    "You can enter test results only for test orders of your department"
            )     
        document_url = None

        if document:
            upload_dir = "uploads/lab_results"
            os.makedirs(upload_dir, exist_ok=True)

            file_ext = os.path.splitext(document.filename)[1]
            file_name = f"{uuid4()}{file_ext}"
            file_path = os.path.join(upload_dir, file_name)

            content = await document.read()
            with open(file_path, "wb") as f:
                f.write(content)

            document_url = file_path

        dump_data = data.model_dump()
        dump_data.pop("sample_id", None)
        dump_data["test_order_id"] = sample.test_order_id

        result = TestResult(
            entered_by=current_user.id,
            entered_at=utc_now(),
            status="completed",
            document_url=document_url,
            **dump_data,
        )

        result = await self.result_repo.create(result)

        order.status = LabOrderStatus.IN_PROGRESS
        await self.order_repo.update(order)

        await self.audit_repo.create(
            "create",
            "lab_result",
            user_id=current_user.id,
            resource_id=str(result.id),
        )

        try:
            await NotificationService(self.db).create_critical_value_alert(result, order)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to send critical value alert: {e}")

        return TestResultResponse.model_validate(result)
        
    async def list_results(
        self, page: int = 1, size: int = 20, test_order_id: int | None = None, is_critical: bool | None = None, current_user=None):
        skip = (page - 1) * size
        department_id = None
        role_name = current_user.role.name.lower() if current_user and current_user.role else ""

        if role_name in ["lab technician", "lab_technician"]:
            result = await self.db.execute(
                select(Staff).where(Staff.email == current_user.email)
            )
            staff = result.scalar_one_or_none()
            department_id = staff.department_id if staff else None
        items = await self.result_repo.list_all(skip=skip, limit=size, test_order_id=test_order_id, is_critical=is_critical, department_id=department_id)
        total = await self.result_repo.count_all(test_order_id=test_order_id, is_critical=is_critical, department_id=department_id)
        return build_paginated_result([TestResultResponse.model_validate(r) for r in items], total, page, size)
 
    async def get_result(self, result_id: int) -> TestResultResponse:
        result = await self.result_repo.get_by_id(result_id)

        if not result:
            raise NotFoundException("Test result not found")

        return TestResultResponse.model_validate(result)


    async def update_result(
        self,
        result_id: int,
        data,
        user_id: int,
    ) -> TestResultResponse:
        result = await self.result_repo.get_by_id(result_id)

        if not result:
            raise NotFoundException("Test result not found")

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(result, key, value)

        result = await self.result_repo.update(result)

        await self.audit_repo.create(
            "update",
            "lab_result",
            user_id=user_id,
            resource_id=str(result.id),
        )

        try:
            order = await self.order_repo.get_by_id(result.test_order_id)
            if order:
                await NotificationService(self.db).create_critical_value_alert(result, order)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to send critical value alert on update: {e}")

        return TestResultResponse.model_validate(result)    

    async def get_critical_alerts(self, current_user) -> list[CriticalAlert]:
        department_id = None
        role_name = current_user.role.name.lower() if current_user and current_user.role else "" 

        if role_name in ["lab technician", "lab_technician"]:
            result = await self.db.execute(
                select(Staff).where(Staff.email == current_user.email)
            )
            staff = result.scalar_one_or_none()

            if not staff or not staff.department_id:
                raise BadRequestException("Lab technician department is not assigned")

            department_id = staff.department_id  

        results = await self.result_repo.get_critical_alerts(  
            current_user_id=current_user.id,
            department_id=department_id, 
        )

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
    async def create_report(self, data: LabReportCreate, current_user) -> LabReportResponse:
        result = await self.result_repo.get_by_id(data.test_result_id)
        if not result:
            raise NotFoundException("Test result not found")

        order = await self.order_repo.get_by_id(result.test_order_id)
        if not order:
            raise NotFoundException("Test order not found")

        sample = await self.sample_repo.get_by_test_order(result.test_order_id)

        if not sample or sample.status != SampleStatus.COLLECTED:
            raise BadRequestException(
                "Cannot create lab report before collecting sample"
            )

        role_name = current_user.role.name.lower() if current_user and current_user.role else ""

        if role_name in ["lab technician", "lab_technician"]:
            staff_result = await self.db.execute(
                select(Staff).where(Staff.email == current_user.email)
            )
            staff = staff_result.scalar_one_or_none()

            if not staff or not staff.department_id:
                raise BadRequestException("Lab technician department is not assigned")

            if order.department_id != staff.department_id:
                raise BadRequestException(
                    "You can create lab reports only for test orders of your department"
                )        
               
        report = LabReport(
            test_order_id=result.test_order_id,
            report_number=generate_lab_report_number(),
            summary=data.summary,
            status=LabReportStatus.DRAFT,
            generated_at=utc_now(),
            generated_by=current_user.id,
            )
        report = await self.report_repo.create(report)
        await self.audit_repo.create("create", "lab_report", user_id=current_user.id, resource_id=str(report.id))
        return LabReportResponse.model_validate(report)

    async def list_reports(
        self,
        page: int = 1,
        size: int = 20,
        status: str | None = None,
        current_user=None,
    ):
        skip = (page - 1) * size

        department_id = None
        generated_by = None
        role_name = current_user.role.name.lower() if current_user and current_user.role else ""

        if role_name in ["lab technician", "lab_technician"]:
            staff_result = await self.db.execute(
                select(Staff).where(Staff.email == current_user.email)
            )
            staff = staff_result.scalar_one_or_none()

            if not staff or not staff.department_id:
                raise BadRequestException("Lab technician department is not assigned")

            department_id = staff.department_id
        generated_by = current_user.id

        items = await self.report_repo.list_all(
            skip=skip,
            limit=size,
            status=status,
            department_id=department_id,
            generated_by=generated_by,
        )

        total = await self.report_repo.count_all(
            status=status,
            department_id=department_id,
            generated_by=generated_by,
        )

        return build_paginated_result(
            [LabReportResponse.model_validate(r) for r in items],
            total,
            page,
        size,
    )
    
    async def get_report(self, report_id: int) -> LabReportResponse:
        report = await self.report_repo.get_by_id(report_id)

        if not report:
           raise NotFoundException("Lab report not found")

        return LabReportResponse.model_validate(report)

    async def _validate_lab_report_access(
        self,
        report: LabReport,
        current_user,
        action: str,
    ) -> None:
        role_name = (
            current_user.role.name.lower()
            if current_user and current_user.role
            else ""
        )

        if role_name not in ["lab technician", "lab_technician"]:
            return

        staff_result = await self.db.execute(
            select(Staff).where(Staff.email == current_user.email)
        )
        staff = staff_result.scalar_one_or_none()

        if not staff or not staff.department_id:
            raise BadRequestException(
                "Lab technician department is not assigned"
            )

        order = await self.order_repo.get_by_id(report.test_order_id)

        if not order:
            raise NotFoundException("Test order not found")

        generated_by_him = (
            getattr(report, "generated_by", None) == current_user.id
        )

        same_department = (
            order.department_id == staff.department_id
        )

        if not generated_by_him and not same_department:
            raise BadRequestException(
                f"You can {action} only reports generated by you or reports of your department"
            )     
    
    async def approve_report(self, report_id: int, data: LabReportApprove, current_user) -> LabReportResponse:
        report = await self.report_repo.get_by_id(report_id)
        if not report:
            raise NotFoundException("Lab report not found")
        if report.status == LabReportStatus.APPROVED:
            raise BadRequestException("Report already approved")
        await self._validate_lab_report_access(
            report,
            current_user,
            "approve/reject",
        )

        report.status = LabReportStatus.APPROVED if data.approved else LabReportStatus.REJECTED
        report.approved_by = current_user.id
        report.approved_at = utc_now()
        if data.remark:
            report.summary = data.remark

        order = await self.order_repo.get_by_id(report.test_order_id)
        if order and data.approved:
            order.status = LabOrderStatus.COMPLETED
            order.completed_at = utc_now()
            await self.order_repo.update(order)

            from app.models.patient_model import Patient
            from app.models.doctor_model import Doctor
            from sqlalchemy import select

            patient = await self.db.get(Patient, order.patient_id)
            doctor = await self.db.get(Doctor, order.doctor_id) if order.doctor_id else None
            
            result_objs = await self.db.execute(select(TestResult).where(TestResult.test_order_id == order.id))
            results = list(result_objs.scalars().all())

            columns = ["Parameter", "Result Value", "Unit", "Normal Range", "Is Critical"]
            rows = [
                [
                    r.parameter_name,
                    r.result_value,
                    r.unit or "-",
                    r.normal_range or "-",
                    "Yes" if r.is_critical else "No"
                ]
                for r in results
            ]

            report_data = {
                "order_number": order.order_number,
                "status": report.status,
                "generated_at": report.approved_at.strftime("%Y-%m-%d %H:%M:%S") if report.approved_at else utc_now().strftime("%Y-%m-%d %H:%M:%S"),
                "patient_name": f"{patient.first_name} {patient.last_name}" if patient else "Unknown",
                "patient_code": patient.patient_code if patient else "Unknown",
                "patient_gender": patient.gender if patient else "Unknown",
                "patient_dob": str(patient.dob) if patient and patient.dob else "Unknown",
                "doctor_name": f"Dr. {doctor.first_name} {doctor.last_name}" if doctor else "",
                "doctor_code": doctor.doctor_code if doctor else "",
                "test_name": order.lab_test.test_name if order.lab_test else "Unknown",
                "test_category": order.lab_test.category if order.lab_test else "Unknown",
                "summary": report.summary or "",
                "columns": columns,
                "rows": rows,
            }

            path = await generate_lab_report_html(
                report.report_number,
                report_data,
            )
            report.report_path = path

        report = await self.report_repo.update(report)
        await self.audit_repo.create(
            "approve",
            "lab_report",
            user_id=current_user.id,
            resource_id=str(report.id),
        )
        return LabReportResponse.model_validate(report)

    async def reject_lab_report(
        self,
        report_id: int,
        data: RejectLabReportRequest,
        user_id: int
    ) -> LabReportResponse:
        report = await self.report_repo.get_by_id(report_id)
        if not report:
            raise NotFoundException("Lab report not found")

        from app.core.constants import LabReportStatus
        if report.status == LabReportStatus.APPROVED:
            raise BadRequestException("Already approved report cannot be rejected")

        report = await self.report_repo.reject_report(
            report_id=report_id,
            remarks=data.remarks,
            rejected_by=user_id
        )

        await self.audit_repo.create(
            action="REPORT_REJECTED",
            resource="lab_report",
            user_id=user_id,
            resource_id=str(report.id),
            details=data.remarks
        )

        return LabReportResponse.model_validate(report)

