from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.core.constants import UserRole
from app.models.user_model import User
from app.models.nurse_model import Nurse, NursePatientAssignment, PatientUpdate, EmergencyAlert
from app.models.doctor_model import Doctor
from app.models.appointment_model import Appointment
from app.models.clinical_record_model import ClinicalRecord
from app.models.department_model import Department
from app.models.bed_allocation_model import Bed
from app.repositories.nurse_communication_repository import NurseCommunicationRepository
from app.schemas.nurse_communication_schema import (
    PatientUpdateCreate,
    PatientUpdateResponse,
    EmergencyAlertCreate,
    EmergencyAlertResponse,
)
from app.services.notification_service import NotificationService


class NurseCommunicationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = NurseCommunicationRepository(db)

    async def _get_nurse_by_user_id(self, user_id: int) -> Nurse:
        result = await self.db.execute(
            select(Nurse).where(Nurse.user_id == user_id)
        )
        nurse = result.scalar_one_or_none()
        if not nurse:
            raise ForbiddenException("Only registered nurses can perform this action")
        return nurse

    async def _validate_assignment(self, nurse_id: int, patient_id: int) -> None:
        result = await self.db.execute(
            select(NursePatientAssignment).where(
                NursePatientAssignment.nurse_id == nurse_id,
                NursePatientAssignment.patient_id == patient_id,
                NursePatientAssignment.status == "Active"
            )
        )
        assignment = result.scalar_one_or_none()
        if not assignment:
            raise ForbiddenException("Nurse is not actively assigned to this patient")

    async def get_assigned_doctor_user_id(self, patient_id: int) -> int | None:
        # 1. Try from latest confirmed/pending appointments
        stmt = (
            select(Doctor.user_id)
            .join(Appointment, Appointment.doctor_id == Doctor.id)
            .where(
                Appointment.patient_id == patient_id,
                Appointment.appointment_status.in_(["Confirmed", "Pending"])
            )
            .order_by(Appointment.appointment_date.desc(), Appointment.appointment_time.desc())
            .limit(1)
        )
        doc_user_id = await self.db.scalar(stmt)
        if doc_user_id:
            return doc_user_id

        # 2. Try from any appointment
        stmt_any = (
            select(Doctor.user_id)
            .join(Appointment, Appointment.doctor_id == Doctor.id)
            .where(Appointment.patient_id == patient_id)
            .order_by(Appointment.appointment_date.desc(), Appointment.appointment_time.desc())
            .limit(1)
        )
        doc_user_id = await self.db.scalar(stmt_any)
        if doc_user_id:
            return doc_user_id

        # 3. Try from latest clinical record
        stmt_cr = (
            select(Doctor.user_id)
            .join(ClinicalRecord, ClinicalRecord.doctor_id == Doctor.id)
            .where(ClinicalRecord.patient_id == patient_id)
            .order_by(ClinicalRecord.created_at.desc())
            .limit(1)
        )
        doc_user_id = await self.db.scalar(stmt_cr)
        return doc_user_id

    async def create_patient_update(self, data: PatientUpdateCreate, user_id: int) -> PatientUpdateResponse:
        nurse = await self._get_nurse_by_user_id(user_id)
        await self._validate_assignment(nurse.id, data.patient_id)

        # Get assigned doctor
        doctor_user_id = await self.get_assigned_doctor_user_id(data.patient_id)
        if not doctor_user_id:
            raise BadRequestException("No assigned doctor found for this patient")

        # Save patient update
        patient_update = PatientUpdate(
            patient_id=data.patient_id,
            nurse_id=nurse.id,
            update_type=data.update_type,
            message=data.message,
            severity=data.severity,
        )
        await self.repo.create_patient_update(patient_update)

        # Retrieve nurse user to populate name in notification and response
        nurse_user = await self.db.get(User, user_id)
        nurse_name = nurse_user.full_name if nurse_user else "Nurse"

        # Notify Doctor
        priority = "HIGH" if data.severity == "CRITICAL" else "NORMAL"
        notif_type = "CRITICAL_PATIENT_UPDATE" if data.severity == "CRITICAL" else "PATIENT_UPDATE"
        title = f"Critical Patient Update - Severity: {data.severity}" if data.severity == "CRITICAL" else "New Patient Update"

        doc_user = await self.db.get(User, doctor_user_id)
        await NotificationService(self.db).dispatch_notification(
            user_id=doctor_user_id,
            title=title,
            message=f"{data.message} (Recorded by: {nurse_name})",
            notification_type=notif_type,
            reference_type="PATIENT",
            reference_id=data.patient_id,
            priority=priority,
            email=doc_user.email if doc_user else None,
            phone=doc_user.phone if doc_user else None,
        )

        return PatientUpdateResponse(
            update_id=patient_update.id,
            patient_id=patient_update.patient_id,
            nurse_name=nurse_name,
            update_type=patient_update.update_type,
            message=patient_update.message,
            severity=patient_update.severity,
            created_at=patient_update.created_at,
        )

    async def get_patient_updates(self, patient_id: int, user: User) -> list[PatientUpdateResponse]:
        # Validate role access
        role_name = user.role.name if user.role else None
        if role_name in UserRole.ADMIN_ROLES:
            pass
        elif role_name == UserRole.DOCTOR:
            # Check if this doctor is associated with the patient
            doctor = await self.db.scalar(select(Doctor).where(Doctor.user_id == user.id))
            if not doctor:
                raise ForbiddenException("Access denied: doctor profile not found")
            has_appt = await self.db.scalar(
                select(Appointment.id).where(Appointment.patient_id == patient_id, Appointment.doctor_id == doctor.id).limit(1)
            )
            has_cr = await self.db.scalar(
                select(ClinicalRecord.id).where(ClinicalRecord.patient_id == patient_id, ClinicalRecord.doctor_id == doctor.id).limit(1)
            )
            if not (has_appt or has_cr):
                raise ForbiddenException("You are not the doctor for this patient")
        elif role_name == UserRole.NURSE:
            nurse = await self._get_nurse_by_user_id(user.id)
            await self._validate_assignment(nurse.id, patient_id)
        else:
            raise ForbiddenException("Requires Nurse, Doctor, or Admin permissions")

        # Retrieve updates
        updates = await self.repo.get_patient_updates(patient_id)
        results = []
        for u in updates:
            n_name = u.nurse.user.full_name if u.nurse and u.nurse.user else "Nurse"
            results.append(
                PatientUpdateResponse(
                    update_id=u.id,
                    patient_id=u.patient_id,
                    nurse_name=n_name,
                    update_type=u.update_type,
                    message=u.message,
                    severity=u.severity,
                    created_at=u.created_at,
                )
            )
        return results

    async def create_emergency_alert(self, data: EmergencyAlertCreate, user_id: int) -> EmergencyAlertResponse:
        nurse = await self._get_nurse_by_user_id(user_id)
        await self._validate_assignment(nurse.id, data.patient_id)

        # Save alert
        alert = EmergencyAlert(
            patient_id=data.patient_id,
            nurse_id=nurse.id,
            emergency_type=data.emergency_type,
            message=data.message,
        )
        await self.repo.create_emergency_alert(alert)

        # Trigger notifications asynchronously
        await self._notify_emergency_channels(data.patient_id, data.message)

        return EmergencyAlertResponse(
            id=alert.id,
            patient_id=alert.patient_id,
            nurse_id=alert.nurse_id,
            emergency_type=alert.emergency_type,
            message=alert.message,
            created_at=alert.created_at,
        )

    async def _notify_emergency_channels(self, patient_id: int, message: str) -> None:
        title = "Patient Emergency Alert"
        notif_service = NotificationService(self.db)

        # 1. Notify doctor
        doctor_user_id = await self.get_assigned_doctor_user_id(patient_id)
        if doctor_user_id:
            doc_user = await self.db.get(User, doctor_user_id)
            await notif_service.dispatch_notification(
                user_id=doctor_user_id,
                title=title,
                message=message,
                notification_type="PATIENT_EMERGENCY_ALERT",
                reference_type="PATIENT",
                reference_id=patient_id,
                priority="HIGH",
                email=doc_user.email if doc_user else None,
                phone=doc_user.phone if doc_user else None,
            )

        # 2. Notify assigned nurses
        assigned_nurses_stmt = (
            select(User)
            .join(Nurse, Nurse.user_id == User.id)
            .join(NursePatientAssignment, NursePatientAssignment.nurse_id == Nurse.id)
            .where(
                NursePatientAssignment.patient_id == patient_id,
                NursePatientAssignment.status == "Active",
                User.is_active.is_(True)
            )
        )
        assigned_nurses_res = await self.db.execute(assigned_nurses_stmt)
        assigned_nurses = assigned_nurses_res.scalars().all()
        for nurse_user in assigned_nurses:
            await notif_service.dispatch_notification(
                user_id=nurse_user.id,
                title=title,
                message=message,
                notification_type="PATIENT_EMERGENCY_ALERT",
                reference_type="PATIENT",
                reference_id=patient_id,
                priority="HIGH",
                email=nurse_user.email,
                phone=nurse_user.phone,
            )

        # 3. Notify Emergency Team (Users in department containing "Emergency")
        emergency_dept_stmt = select(Department.department_id).where(Department.department_name.ilike("%Emergency%"))
        emergency_nurses_stmt = (
            select(User)
            .join(Nurse, Nurse.user_id == User.id)
            .where(Nurse.department_id.in_(emergency_dept_stmt), User.is_active.is_(True))
        )
        emergency_nurses_res = await self.db.execute(emergency_nurses_stmt)
        emergency_nurses = emergency_nurses_res.scalars().all()

        emergency_docs_stmt = (
            select(User)
            .join(Doctor, Doctor.user_id == User.id)
            .where(Doctor.department_id.in_(emergency_dept_stmt), User.is_active.is_(True))
        )
        emergency_docs_res = await self.db.execute(emergency_docs_stmt)
        emergency_docs = emergency_docs_res.scalars().all()

        all_emergency_users = list(set(emergency_nurses + emergency_docs))
        for em_user in all_emergency_users:
            await notif_service.dispatch_notification(
                user_id=em_user.id,
                title="Emergency Alert (Emergency Team)",
                message=message,
                notification_type="PATIENT_EMERGENCY_ALERT",
                reference_type="PATIENT",
                reference_id=patient_id,
                priority="HIGH",
                email=em_user.email,
                phone=em_user.phone,
            )

        # 4. Notify ICU Team (if applicable - checked by bed allocation type ICU)
        is_in_icu = await self.db.scalar(
            select(Bed.id)
            .where(Bed.patient_id == patient_id, Bed.type == "ICU")
            .limit(1)
        )
        if is_in_icu:
            icu_dept_stmt = select(Department.department_id).where(Department.department_name.ilike("%ICU%"))
            icu_nurses_stmt = (
                select(User)
                .join(Nurse, Nurse.user_id == User.id)
                .where(Nurse.department_id.in_(icu_dept_stmt), User.is_active.is_(True))
            )
            icu_nurses_res = await self.db.execute(icu_nurses_stmt)
            icu_nurses = icu_nurses_res.scalars().all()

            icu_docs_stmt = (
                select(User)
                .join(Doctor, Doctor.user_id == User.id)
                .where(Doctor.department_id.in_(icu_dept_stmt), User.is_active.is_(True))
            )
            icu_docs_res = await self.db.execute(icu_docs_stmt)
            icu_docs = icu_docs_res.scalars().all()

            all_icu_users = list(set(icu_nurses + icu_docs))
            for icu_user in all_icu_users:
                await notif_service.dispatch_notification(
                    user_id=icu_user.id,
                    title="Emergency Alert (ICU Team)",
                    message=message,
                    notification_type="PATIENT_EMERGENCY_ALERT",
                    reference_type="PATIENT",
                    reference_id=patient_id,
                    priority="HIGH",
                    email=icu_user.email,
                    phone=icu_user.phone,
                )
