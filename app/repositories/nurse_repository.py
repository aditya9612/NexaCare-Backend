from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import LabOrderStatus
from app.models.department_model import Department
from app.models.lab_model import TestOrder
from app.models.nurse_model import (
    Nurse,
    NurseAttendance,
    NurseHandoverNote,
    NurseNotification,
    NursePatientAssignment,
    NurseShift,
    NurseTask,
    PatientVital,
)
from app.models.patient_model import Patient


class NurseRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return select(Nurse).outerjoin(Nurse.department)

    async def list_all(
        self,
        skip: int = 0,
        limit: int = 20,
        department_id: int | None = None,
        shift: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> list[Nurse]:
        query = self._base_query()
        if department_id:
            query = query.where(Nurse.department_id == department_id)
        if shift:
            query = query.where(Nurse.shift == shift)
        column = getattr(Nurse, sort_by, Nurse.created_at)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_all(
        self,
        department_id: int | None = None,
        shift: str | None = None,
    ) -> int:
        query = select(func.count()).select_from(Nurse)
        if department_id:
            query = query.where(Nurse.department_id == department_id)
        if shift:
            query = query.where(Nurse.shift == shift)
        return await self.db.scalar(query) or 0

    async def get_by_id(self, nurse_id: int) -> Nurse | None:
        result = await self.db.execute(self._base_query().where(Nurse.id == nurse_id))
        return result.scalar_one_or_none()

    async def get_by_license(self, license_number: str) -> Nurse | None:
        result = await self.db.execute(
            select(Nurse).where(Nurse.license_number == license_number)
        )
        return result.scalar_one_or_none()

    async def get_by_user_id(self, user_id: int) -> Nurse | None:
        result = await self.db.execute(select(Nurse).where(Nurse.user_id == user_id))
        return result.scalar_one_or_none()

    def _search_filter(self, q: str):
        pattern = f"%{q.lower()}%"
        return or_(
            func.lower(Nurse.nurse_code).like(pattern),
            func.lower(Nurse.license_number).like(pattern),
            func.lower(Nurse.shift).like(pattern),
            func.lower(Department.department_name).like(pattern),
        )

    async def search(self, q: str, skip: int = 0, limit: int = 20) -> list[Nurse]:
        query = self._base_query().where(self._search_filter(q))
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_search(self, q: str) -> int:
        return (
            await self.db.scalar(
                select(func.count())
                .select_from(Nurse)
                .outerjoin(Nurse.department)
                .where(self._search_filter(q))
            )
            or 0
        )

    async def create(self, nurse: Nurse) -> Nurse:
        self.db.add(nurse)
        await self.db.flush()
        await self.db.refresh(nurse)
        return nurse

    async def update(self, nurse: Nurse) -> Nurse:
        await self.db.flush()
        await self.db.refresh(nurse)
        return nurse

    async def delete(self, nurse: Nurse) -> None:
        await self.db.delete(nurse)
        await self.db.flush()


class NurseShiftRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _apply_filters(
        self,
        query,
        nurse_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
        shift_name: str | None = None,
    ):
        query = query.where(NurseShift.nurse_id == nurse_id)
        if start_date is not None:
            query = query.where(NurseShift.shift_date >= start_date)
        if end_date is not None:
            query = query.where(NurseShift.shift_date <= end_date)
        if shift_name is not None:
            query = query.where(NurseShift.shift_name == shift_name)
        return query

    async def list_by_nurse(
        self,
        nurse_id: int,
        skip: int = 0,
        limit: int = 20,
        start_date: date | None = None,
        end_date: date | None = None,
        shift_name: str | None = None,
        sort_by: str = "shift_date",
        sort_order: str = "desc",
    ) -> list[NurseShift]:
        query = select(NurseShift)
        query = self._apply_filters(
            query,
            nurse_id=nurse_id,
            start_date=start_date,
            end_date=end_date,
            shift_name=shift_name,
        )
        column = getattr(NurseShift, sort_by, NurseShift.shift_date)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_by_nurse(
        self,
        nurse_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
        shift_name: str | None = None,
    ) -> int:
        query = select(func.count(NurseShift.id))
        query = self._apply_filters(
            query,
            nurse_id=nurse_id,
            start_date=start_date,
            end_date=end_date,
            shift_name=shift_name,
        )
        return await self.db.scalar(query) or 0

    async def create(self, shift: NurseShift) -> NurseShift:
        self.db.add(shift)
        await self.db.flush()
        await self.db.refresh(shift)
        return shift

    async def get_by_id(self, shift_id: int) -> NurseShift | None:
        result = await self.db.execute(select(NurseShift).where(NurseShift.id == shift_id))
        return result.scalar_one_or_none()

    async def get_by_id_for_nurse(self, shift_id: int, nurse_id: int) -> NurseShift | None:
        result = await self.db.execute(
            select(NurseShift).where(
                NurseShift.id == shift_id,
                NurseShift.nurse_id == nurse_id,
            )
        )
        return result.scalar_one_or_none()

    async def update(self, shift: NurseShift) -> NurseShift:
        await self.db.flush()
        await self.db.refresh(shift)
        return shift

    async def get_latest_by_nurse(self, nurse_id: int) -> NurseShift | None:
        result = await self.db.execute(
            select(NurseShift)
            .where(NurseShift.nurse_id == nurse_id)
            .order_by(NurseShift.shift_date.desc(), NurseShift.start_time.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


class NurseAttendanceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _apply_filters(
        self,
        query,
        nurse_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
        status: str | None = None,
    ):
        query = query.where(NurseAttendance.nurse_id == nurse_id)
        if start_date is not None:
            query = query.where(NurseAttendance.attendance_date >= start_date)
        if end_date is not None:
            query = query.where(NurseAttendance.attendance_date <= end_date)
        if status is not None:
            query = query.where(NurseAttendance.status == status)
        return query

    async def list_by_nurse(
        self,
        nurse_id: int,
        skip: int = 0,
        limit: int = 20,
        start_date: date | None = None,
        end_date: date | None = None,
        status: str | None = None,
        sort_by: str = "attendance_date",
        sort_order: str = "desc",
    ) -> list[NurseAttendance]:
        query = select(NurseAttendance)
        query = self._apply_filters(
            query,
            nurse_id=nurse_id,
            start_date=start_date,
            end_date=end_date,
            status=status,
        )
        column = getattr(NurseAttendance, sort_by, NurseAttendance.attendance_date)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_by_nurse(
        self,
        nurse_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
        status: str | None = None,
    ) -> int:
        query = select(func.count(NurseAttendance.id))
        query = self._apply_filters(
            query,
            nurse_id=nurse_id,
            start_date=start_date,
            end_date=end_date,
            status=status,
        )
        return await self.db.scalar(query) or 0

    async def create(self, attendance: NurseAttendance) -> NurseAttendance:
        self.db.add(attendance)
        await self.db.flush()
        await self.db.refresh(attendance)
        return attendance


class NurseHandoverNoteRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _apply_filters(
        self,
        query,
        nurse_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
        status: str | None = None,
        shift_id: int | None = None,
    ):
        query = query.where(NurseHandoverNote.nurse_id == nurse_id)
        if start_date is not None:
            query = query.where(NurseHandoverNote.handover_date >= start_date)
        if end_date is not None:
            query = query.where(NurseHandoverNote.handover_date <= end_date)
        if status is not None:
            query = query.where(NurseHandoverNote.status == status)
        if shift_id is not None:
            query = query.where(NurseHandoverNote.shift_id == shift_id)
        return query

    async def list_by_nurse(
        self,
        nurse_id: int,
        skip: int = 0,
        limit: int = 20,
        start_date: date | None = None,
        end_date: date | None = None,
        status: str | None = None,
        shift_id: int | None = None,
        sort_by: str = "handover_date",
        sort_order: str = "desc",
    ) -> list[NurseHandoverNote]:
        query = select(NurseHandoverNote)
        query = self._apply_filters(
            query,
            nurse_id=nurse_id,
            start_date=start_date,
            end_date=end_date,
            status=status,
            shift_id=shift_id,
        )
        column = getattr(NurseHandoverNote, sort_by, NurseHandoverNote.handover_date)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_by_nurse(
        self,
        nurse_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
        status: str | None = None,
        shift_id: int | None = None,
    ) -> int:
        query = select(func.count(NurseHandoverNote.id))
        query = self._apply_filters(
            query,
            nurse_id=nurse_id,
            start_date=start_date,
            end_date=end_date,
            status=status,
            shift_id=shift_id,
        )
        return await self.db.scalar(query) or 0

    async def get_by_id(self, note_id: int, nurse_id: int) -> NurseHandoverNote | None:
        result = await self.db.execute(
            select(NurseHandoverNote).where(
                NurseHandoverNote.id == note_id,
                NurseHandoverNote.nurse_id == nurse_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, note: NurseHandoverNote) -> NurseHandoverNote:
        self.db.add(note)
        await self.db.flush()
        await self.db.refresh(note)
        return note

    async def update(self, note: NurseHandoverNote) -> NurseHandoverNote:
        await self.db.flush()
        await self.db.refresh(note)
        return note


class NursePatientAssignmentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self, nurse_id: int, status: str | None = None):
        query = (
            select(Patient)
            .join(
                NursePatientAssignment,
                NursePatientAssignment.patient_id == Patient.id,
            )
            .where(
                NursePatientAssignment.nurse_id == nurse_id,
                Patient.is_deleted.is_(False),
            )
        )
        if status is not None:
            query = query.where(NursePatientAssignment.status == status)
        return query

    async def list_patients_by_nurse(
        self,
        nurse_id: int,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> list[Patient]:
        query = self._base_query(nurse_id, status)
        column = getattr(Patient, sort_by, Patient.created_at)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_patients_by_nurse(
        self,
        nurse_id: int,
        status: str | None = None,
    ) -> int:
        query = (
            select(func.count(Patient.id))
            .join(
                NursePatientAssignment,
                NursePatientAssignment.patient_id == Patient.id,
            )
            .where(
                NursePatientAssignment.nurse_id == nurse_id,
                Patient.is_deleted.is_(False),
            )
        )
        if status is not None:
            query = query.where(NursePatientAssignment.status == status)
        return await self.db.scalar(query) or 0

    async def get_patient_by_id(self, patient_id: int) -> Patient | None:
        result = await self.db.execute(
            select(Patient).where(
                Patient.id == patient_id,
                Patient.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def get_assigned_patient(
        self, nurse_id: int, patient_id: int
    ) -> tuple[Patient, NursePatientAssignment] | None:
        result = await self.db.execute(
            select(Patient, NursePatientAssignment)
            .join(
                NursePatientAssignment,
                NursePatientAssignment.patient_id == Patient.id,
            )
            .where(
                NursePatientAssignment.nurse_id == nurse_id,
                NursePatientAssignment.patient_id == patient_id,
                Patient.is_deleted.is_(False),
            )
        )
        row = result.one_or_none()
        return row

    def _status_base_query(
        self,
        nurse_id: int,
        assignment_status: str | None = None,
        patient_status: str | None = None,
    ):
        query = (
            select(Patient, NursePatientAssignment)
            .join(
                NursePatientAssignment,
                NursePatientAssignment.patient_id == Patient.id,
            )
            .where(
                NursePatientAssignment.nurse_id == nurse_id,
                Patient.is_deleted.is_(False),
            )
        )
        if assignment_status is not None:
            query = query.where(NursePatientAssignment.status == assignment_status)
        if patient_status is not None:
            query = query.where(NursePatientAssignment.patient_status == patient_status)
        return query

    async def list_patient_statuses_by_nurse(
        self,
        nurse_id: int,
        skip: int = 0,
        limit: int = 20,
        assignment_status: str | None = None,
        patient_status: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ) -> list[tuple[Patient, NursePatientAssignment]]:
        query = self._status_base_query(nurse_id, assignment_status, patient_status)
        assignment_fields = {"patient_status", "status", "notes", "updated_at", "created_at"}
        if sort_by in assignment_fields:
            column = getattr(NursePatientAssignment, sort_by, NursePatientAssignment.updated_at)
        else:
            column = getattr(Patient, sort_by, Patient.first_name)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.all())

    async def count_patient_statuses_by_nurse(
        self,
        nurse_id: int,
        assignment_status: str | None = None,
        patient_status: str | None = None,
    ) -> int:
        query = (
            select(func.count(Patient.id))
            .join(
                NursePatientAssignment,
                NursePatientAssignment.patient_id == Patient.id,
            )
            .where(
                NursePatientAssignment.nurse_id == nurse_id,
                Patient.is_deleted.is_(False),
            )
        )
        if assignment_status is not None:
            query = query.where(NursePatientAssignment.status == assignment_status)
        if patient_status is not None:
            query = query.where(NursePatientAssignment.patient_status == patient_status)
        return await self.db.scalar(query) or 0


class NurseNotificationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _apply_filters(
        self,
        query,
        nurse_id: int,
        status: str = "Active",
        notification_type: str | None = None,
        priority: str | None = None,
    ):
        query = query.where(NurseNotification.nurse_id == nurse_id)
        if status is not None:
            query = query.where(NurseNotification.status == status)
        if notification_type is not None:
            query = query.where(NurseNotification.notification_type == notification_type)
        if priority is not None:
            query = query.where(NurseNotification.priority == priority)
        return query

    async def list_by_nurse(
        self,
        nurse_id: int,
        skip: int = 0,
        limit: int = 20,
        status: str = "Active",
        notification_type: str | None = None,
        priority: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> list[NurseNotification]:
        query = select(NurseNotification)
        query = self._apply_filters(
            query,
            nurse_id=nurse_id,
            status=status,
            notification_type=notification_type,
            priority=priority,
        )
        column = getattr(NurseNotification, sort_by, NurseNotification.created_at)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_by_nurse(
        self,
        nurse_id: int,
        status: str = "Active",
        notification_type: str | None = None,
        priority: str | None = None,
    ) -> int:
        query = select(func.count(NurseNotification.id))
        query = self._apply_filters(
            query,
            nurse_id=nurse_id,
            status=status,
            notification_type=notification_type,
            priority=priority,
        )
        return await self.db.scalar(query) or 0


class NursePatientVitalRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, vital: PatientVital) -> PatientVital:
        self.db.add(vital)
        await self.db.flush()
        await self.db.refresh(vital)
        return vital


class NurseTaskRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _apply_filters(
        self,
        query,
        nurse_id: int,
        due_date: date,
        patient_id: int | None = None,
        status: str | None = None,
        priority: str | None = None,
    ):
        query = query.where(
            NurseTask.nurse_id == nurse_id,
            NurseTask.due_date == due_date,
        )
        if patient_id is not None:
            query = query.where(NurseTask.patient_id == patient_id)
        if status is not None:
            query = query.where(NurseTask.status == status)
        if priority is not None:
            query = query.where(NurseTask.priority == priority)
        return query

    async def list_by_nurse(
        self,
        nurse_id: int,
        due_date: date,
        skip: int = 0,
        limit: int = 20,
        patient_id: int | None = None,
        status: str | None = None,
        priority: str | None = None,
        sort_by: str = "due_date",
        sort_order: str = "asc",
    ) -> list[NurseTask]:
        query = select(NurseTask)
        query = self._apply_filters(
            query,
            nurse_id=nurse_id,
            due_date=due_date,
            patient_id=patient_id,
            status=status,
            priority=priority,
        )
        column = getattr(NurseTask, sort_by, NurseTask.due_date)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_by_nurse(
        self,
        nurse_id: int,
        due_date: date,
        patient_id: int | None = None,
        status: str | None = None,
        priority: str | None = None,
    ) -> int:
        query = select(func.count(NurseTask.id))
        query = self._apply_filters(
            query,
            nurse_id=nurse_id,
            due_date=due_date,
            patient_id=patient_id,
            status=status,
            priority=priority,
        )
        return await self.db.scalar(query) or 0

    async def get_by_id(self, task_id: int, nurse_id: int) -> NurseTask | None:
        result = await self.db.execute(
            select(NurseTask).where(
                NurseTask.id == task_id,
                NurseTask.nurse_id == nurse_id,
            )
        )
        return result.scalar_one_or_none()

    async def update(self, task: NurseTask) -> NurseTask:
        await self.db.flush()
        await self.db.refresh(task)
        return task


class NursePatientLabTestRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self, patient_id: int, status: str | None = None):
        query = (
            select(TestOrder)
            .where(
                TestOrder.patient_id == patient_id,
                TestOrder.is_deleted.is_(False),
                TestOrder.status != LabOrderStatus.CANCELLED,
            )
            .options(
                selectinload(TestOrder.lab_test),
                selectinload(TestOrder.reports),
                selectinload(TestOrder.results),
            )
        )
        if status == "Pending":
            query = query.where(TestOrder.status != LabOrderStatus.COMPLETED)
        elif status == "Completed":
            query = query.where(TestOrder.status == LabOrderStatus.COMPLETED)
        return query

    async def list_by_patient(
        self,
        patient_id: int,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        sort_by: str = "ordered_at",
        sort_order: str = "desc",
    ) -> list[TestOrder]:
        query = self._base_query(patient_id, status)
        column = getattr(TestOrder, sort_by, TestOrder.ordered_at)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().unique().all())

    async def count_by_patient(
        self,
        patient_id: int,
        status: str | None = None,
    ) -> int:
        query = select(func.count(TestOrder.id)).where(
            TestOrder.patient_id == patient_id,
            TestOrder.is_deleted.is_(False),
            TestOrder.status != LabOrderStatus.CANCELLED,
        )
        if status == "Pending":
            query = query.where(TestOrder.status != LabOrderStatus.COMPLETED)
        elif status == "Completed":
            query = query.where(TestOrder.status == LabOrderStatus.COMPLETED)
        return await self.db.scalar(query) or 0
