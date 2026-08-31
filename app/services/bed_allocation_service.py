from typing import List, Optional
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException, ConflictException
from app.models.bed_allocation_model import Floor, Room, Bed, BedActivityLog
from app.models.patient_model import Patient
from app.repositories.bed_allocation_repository import BedAllocationRepository
from app.schemas.bed_allocation_schema import (
    FloorCreate,
    FloorUpdate,
    RoomCreate,
    RoomUpdate,
    BedCreate,
    BedUpdate,
    BedAllocationRequest,
    BedReleaseRequest,
    BedTransferRequest,
    BedAnalyticsSummaryResponse,
    ICUAnalyticsResponse,
)
from app.utils.helpers import utc_now


class BedAllocationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = BedAllocationRepository(db)

    # Floor Services
    async def get_floor(self, floor_id: int) -> Floor:
        floor = await self.repo.get_floor_by_id(floor_id)
        if not floor:
            raise NotFoundException("Floor not found")
        for room in floor.rooms:
            for bed in room.beds:
                if bed.patient and getattr(bed.patient, "is_deleted", False):
                    bed.status = "Available"
                    bed.patient_id = None
                    bed.patient = None
                    bed.allocation_time = None
                    bed.admission_date = None
        return floor

    async def list_floors(self) -> List[Floor]:
        floors = await self.repo.list_floors()
        for floor in floors:
            for room in floor.rooms:
                for bed in room.beds:
                    if bed.patient and getattr(bed.patient, "is_deleted", False):
                        bed.status = "Available"
                        bed.patient_id = None
                        bed.patient = None
                        bed.allocation_time = None
                        bed.admission_date = None
        return floors

    async def create_floor(self, data: FloorCreate) -> Floor:
        existing = await self.repo.get_floor_by_number(data.number)
        if existing:
            raise ConflictException(f"Floor number {data.number} already exists")

        floor = Floor(
            number=data.number,
            name=data.name,
            type=data.type,
            description=data.description,
        )
        floor = await self.repo.create_floor(floor)

        if data.rooms:
            for r_data in data.rooms:
                room = Room(
                    floor_id=floor.id,
                    number=r_data.number,
                    name=r_data.name,
                    type=r_data.type,
                    capacity=r_data.capacity,
                    description=r_data.description,
                )
                room = await self.repo.create_room(room)
                # Auto-create beds up to room capacity
                for i in range(1, room.capacity + 1):
                    bed = Bed(
                        room_id=room.id,
                        name=f"Bed {i}",
                        type=room.type,
                        status="Available",
                    )
                    await self.repo.create_bed(bed)

        return await self.get_floor(floor.id)

    async def update_floor(self, floor_id: int, data: FloorUpdate) -> Floor:
        floor = await self.get_floor(floor_id)

        if data.number is not None and data.number != floor.number:
            existing = await self.repo.get_floor_by_number(data.number)
            if existing:
                raise ConflictException(f"Floor number {data.number} already exists")
            floor.number = data.number

        if data.name is not None:
            floor.name = data.name
        if data.type is not None:
            floor.type = data.type
        if data.description is not None:
            floor.description = data.description

        await self.db.flush()
        log = BedActivityLog(
            type="crud",
            message=f"Updated floor {floor.name} (Number: {floor.number}).",
            floor_id=floor.id,
        )
        await self.repo.create_activity_log(log)
        return await self.get_floor(floor.id)

    async def delete_floor(self, floor_id: int) -> None:
        floor = await self.get_floor(floor_id)

        for room in floor.rooms:
            for bed in room.beds:
                if bed.status == "Occupied":
                    raise BadRequestException("Cannot delete floor because it contains occupied beds.")

        log = BedActivityLog(
            type="crud",
            message=f"Deleted floor {floor.name} (Number: {floor.number}).",
            floor_id=floor.id,
        )
        await self.repo.create_activity_log(log)

        await self.repo.delete_floor(floor)

    # Room Services
    async def get_room(self, room_id: int) -> Room:
        room = await self.repo.get_room_by_id(room_id)
        if not room:
            raise NotFoundException("Room not found")
        for bed in room.beds:
            if bed.patient and getattr(bed.patient, "is_deleted", False):
                bed.status = "Available"
                bed.patient_id = None
                bed.patient = None
                bed.allocation_time = None
                bed.admission_date = None
        return room

    async def create_room(self, floor_id: int, data: RoomCreate) -> Room:
        floor = await self.get_floor(floor_id)

        existing = await self.repo.get_room_by_number(floor_id, data.number)
        if existing:
            raise ConflictException(f"Room number {data.number} already exists on floor {floor.name}")

        room = Room(
            floor_id=floor_id,
            number=data.number,
            name=data.name,
            type=data.type,
            capacity=data.capacity,
            description=data.description,
        )
        room = await self.repo.create_room(room)

        for i in range(1, room.capacity + 1):
            bed = Bed(
                room_id=room.id,
                name=f"Bed {i}",
                type=room.type,
                status="Available",
            )
            await self.repo.create_bed(bed)

        log = BedActivityLog(
            type="crud",
            message=f"Created room {room.name} under floor {floor.name}.",
            floor_id=floor_id,
            room_id=room.id,
        )
        await self.repo.create_activity_log(log)

        return await self.get_room(room.id)

    async def update_room(self, room_id: int, data: RoomUpdate) -> Room:
        room = await self.get_room(room_id)

        if data.number is not None and data.number != room.number:
            existing = await self.repo.get_room_by_number(room.floor_id, data.number)
            if existing:
                raise ConflictException(f"Room number {data.number} already exists on this floor")
            room.number = data.number

        if data.name is not None:
            room.name = data.name
        if data.type is not None:
            room.type = data.type
        if data.description is not None:
            room.description = data.description

        if data.capacity is not None:
            room.capacity = data.capacity

        await self.db.flush()

        log = BedActivityLog(
            type="crud",
            message=f"Updated room {room.name} under floor {room.floor.name if room.floor else ''}.",
            floor_id=room.floor_id,
            room_id=room.id,
        )
        await self.repo.create_activity_log(log)

        return await self.get_room(room.id)

    async def delete_room(self, room_id: int) -> None:
        room = await self.get_room(room_id)

        for bed in room.beds:
            if bed.status == "Occupied":
                raise BadRequestException("Cannot delete room because it contains occupied beds.")

        log = BedActivityLog(
            type="crud",
            message=f"Deleted room {room.name} under floor {room.floor.name if room.floor else ''}.",
            floor_id=room.floor_id,
            room_id=room.id,
        )
        await self.repo.create_activity_log(log)

        await self.repo.delete_room(room)

    # Bed Services
    async def get_bed(self, bed_id: int) -> Bed:
        bed = await self.repo.get_bed_by_id(bed_id)
        if not bed:
            raise NotFoundException("Bed not found")
        if bed.patient and getattr(bed.patient, "is_deleted", False):
            bed.status = "Available"
            bed.patient_id = None
            bed.patient = None
            bed.allocation_time = None
            bed.admission_date = None
        return bed

    async def create_bed(self, room_id: int, data: BedCreate) -> Bed:
        room = await self.get_room(room_id)

        if len(room.beds) >= room.capacity:
            room.capacity = len(room.beds) + 1

        existing = await self.repo.get_bed_by_name(room_id, data.name)
        if existing:
            raise ConflictException(f"Bed name '{data.name}' already exists in this room")

        bed = Bed(
            room_id=room_id,
            name=data.name,
            type=data.type,
            status=data.status or "Available",
        )
        bed = await self.repo.create_bed(bed)

        log = BedActivityLog(
            type="crud",
            message=f"Created bed {bed.name} in room {room.name}.",
            floor_id=room.floor_id,
            room_id=room.id,
            bed_id=bed.id,
        )
        await self.repo.create_activity_log(log)

        return await self.get_bed(bed.id)

    async def update_bed(self, bed_id: int, data: BedUpdate) -> Bed:
        bed = await self.get_bed(bed_id)

        if data.name is not None and data.name != bed.name:
            existing = await self.repo.get_bed_by_name(bed.room_id, data.name)
            if existing:
                raise ConflictException(f"Bed name '{data.name}' already exists in this room")
            bed.name = data.name

        if data.type is not None:
            bed.type = data.type

        if data.status is not None:
            is_occupied = (bed.patient_id is not None) or (bed.status == "Occupied")
            if is_occupied and data.status != bed.status:
                raise ConflictException("Cannot change bed status while the bed is occupied.")
            if data.status == "Occupied" and not bed.patient_id:
                raise BadRequestException("Cannot set bed status to Occupied without an associated patient.")
            bed.status = data.status

        await self.db.flush()

        log = BedActivityLog(
            type="crud",
            message=f"Updated bed {bed.name} details (Status: {bed.status}).",
            floor_id=bed.room.floor_id if bed.room else None,
            room_id=bed.room_id,
            bed_id=bed.id,
            patient_id=bed.patient_id,
        )
        await self.repo.create_activity_log(log)

        return await self.get_bed(bed.id)

    async def delete_bed(self, bed_id: int) -> None:
        bed = await self.get_bed(bed_id)

        if bed.status == "Occupied":
            raise BadRequestException("Cannot delete bed because it is currently occupied.")

        log = BedActivityLog(
            type="crud",
            message=f"Deleted bed {bed.name} from room {bed.room.name if bed.room else ''}.",
            floor_id=bed.room.floor_id if bed.room else None,
            room_id=bed.room_id,
            bed_id=bed.id,
        )
        await self.repo.create_activity_log(log)

        await self.repo.delete_bed(bed)

    # Patient Services
    async def get_patient(self, patient_id: int) -> Patient:
        patient = await self.repo.get_patient_by_id(patient_id)
        if not patient:
            raise NotFoundException("Patient not found")
        return patient

    # Bed Allocation Operations
    async def allocate_bed(self, bed_id: int, data: BedAllocationRequest) -> Bed:
        bed = await self.get_bed(bed_id)
        if bed.status != "Available":
            if bed.status == "Occupied":
                raise BadRequestException("Bed is already occupied")
            raise BadRequestException(f"Bed {bed.name} is not available. Current status: {bed.status}.")

        patient = await self.get_patient(data.patientId)

        from app.core.constants import PatientStatus
        if patient.status == PatientStatus.INACTIVE:
            raise BadRequestException(
                "Cannot allocate a bed to an inactive patient. Please activate the patient first."
            )
        from datetime import datetime as dt, timezone as tz, timedelta
        ist_tz = tz(timedelta(hours=5, minutes=30))
        admission_dt = data.admissionDate
        if admission_dt.tzinfo is None:
            admission_dt = admission_dt.replace(tzinfo=tz.utc)
        admission_date_ist = admission_dt.astimezone(ist_tz).date()
        current_date_ist = dt.now(ist_tz).date()

        if admission_date_ist < current_date_ist:
            raise BadRequestException("Admission date cannot be in the past.")

        from app.models.appointment_model import Appointment
        from sqlalchemy import select, desc
        stmt = (
            select(Appointment)
            .where(Appointment.patient_id == patient.id)
            .order_by(desc(Appointment.appointment_date), desc(Appointment.appointment_time))
            .limit(1)
        )
        res = await self.db.execute(stmt)
        appointment = res.scalar_one_or_none()

        if not appointment:
            raise HTTPException(
                status_code=404,
                detail="No appointment found for this patient."
            )

        status_norm = (appointment.appointment_status or "").strip().lower()
        if status_norm != "completed":
            if status_norm == "cancelled":
                raise HTTPException(
                    status_code=400,
                    detail="Cannot allocate bed for a cancelled appointment."
                )
            raise HTTPException(
                status_code=400,
                detail=f"Bed allocation is only allowed for patients with a completed appointment. Current appointment status: {appointment.appointment_status}."
            )

        bed.status = "Occupied"
        bed.patient_id = patient.id
        bed.allocation_time = utc_now()
        bed.admission_date = data.admissionDate

        floor_name = bed.room.floor.name if bed.room and bed.room.floor else ''
        admission_note = f"\n[Bed Admission]: Admitted to Bed {bed.name} (Room: {bed.room.name if bed.room else ''}, Floor: {floor_name}) on {data.admissionDate.strftime('%Y-%m-%d')}. Notes: {data.notes or 'None'}"
        patient.medical_history = f"{patient.medical_history or ''}{admission_note}".strip()

        await self.db.flush()

        log = BedActivityLog(
            type="allocation",
            message=f"Patient {patient.first_name} {patient.last_name} admitted and allocated to Bed {bed.name} (Room: {bed.room.name if bed.room else ''}).",
            floor_id=bed.room.floor_id if bed.room else None,
            room_id=bed.room_id,
            bed_id=bed.id,
            patient_id=patient.id,
        )
        await self.repo.create_activity_log(log)

        try:
            from app.models.doctor_model import Doctor
            from app.services.notification_service import NotificationService

            notif_service = NotificationService(self.db)

            # Notify Patient
            if patient.user_id:
                await notif_service.dispatch_notification(
                    user_id=patient.user_id,
                    title="Patient Admission",
                    message=f"You have been admitted to Bed {bed.name} on Floor: {floor_name}.",
                    notification_type="PATIENT_ADMISSION",
                    reference_type="BED_ALLOCATION",
                    reference_id=bed.id,
                    priority="HIGH",
                    email=patient.email,
                    phone=patient.phone,
                )

            # Notify Doctor
            if appointment and appointment.doctor_id:
                doc_user_id = await self.db.scalar(
                    select(Doctor.user_id).where(Doctor.id == appointment.doctor_id)
                )
                if doc_user_id:
                    await notif_service.dispatch_notification(
                        user_id=doc_user_id,
                        title="Patient Admission",
                        message=f"Your patient {patient.first_name} {patient.last_name} has been admitted to Bed {bed.name}.",
                        notification_type="PATIENT_ADMISSION",
                        reference_type="BED_ALLOCATION",
                        reference_id=bed.id,
                        priority="HIGH",
                        email=None,
                        phone=None,
                    )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Failed to dispatch admission notification: %s", exc)

        return await self.get_bed(bed.id)

    async def release_bed(self, bed_id: int, data: BedReleaseRequest) -> Bed:
        bed = await self.get_bed(bed_id)
        if bed.status != "Occupied" or not bed.patient_id:
            raise BadRequestException(f"Bed {bed.name} is not currently occupied.")

        patient = await self.get_patient(bed.patient_id)

        floor_name = bed.room.floor.name if bed.room and bed.room.floor else ''
        room_name = bed.room.name if bed.room else ''
        discharge_note = f"\n[Bed Discharge]: Discharged from Bed {bed.name} (Room: {room_name}, Floor: {floor_name}) on {utc_now().strftime('%Y-%m-%d')}. Discharge Notes: {data.dischargeNotes or 'None'}"
        patient.medical_history = f"{patient.medical_history or ''}{discharge_note}".strip()

        floor_id = bed.room.floor_id if bed.room else None
        room_id = bed.room_id
        patient_id = patient.id

        bed.status = "Available"
        bed.patient_id = None
        bed.allocation_time = None
        bed.admission_date = None

        await self.db.flush()

        log = BedActivityLog(
            type="release",
            message=f"Patient {patient.first_name} {patient.last_name} discharged and released from Bed {bed.name}.",
            floor_id=floor_id,
            room_id=room_id,
            bed_id=bed.id,
            patient_id=patient_id,
        )
        await self.repo.create_activity_log(log)

        try:
            from app.models.appointment_model import Appointment
            from app.models.doctor_model import Doctor
            from app.services.notification_service import NotificationService
            from sqlalchemy import select, desc

            notif_service = NotificationService(self.db)

            # Notify Patient
            if patient.user_id:
                await notif_service.dispatch_notification(
                    user_id=patient.user_id,
                    title="Patient Discharge",
                    message=f"You have been discharged from Bed {bed.name}. Please follow your discharge instructions.",
                    notification_type="PATIENT_DISCHARGE",
                    reference_type="BED_ALLOCATION",
                    reference_id=bed.id,
                    priority="NORMAL",
                    email=patient.email,
                    phone=patient.phone,
                )

            # Lookup Doctor
            stmt = (
                select(Appointment)
                .where(Appointment.patient_id == patient.id)
                .order_by(desc(Appointment.appointment_date), desc(Appointment.appointment_time))
                .limit(1)
            )
            res = await self.db.execute(stmt)
            appointment = res.scalar_one_or_none()

            if appointment and appointment.doctor_id:
                doc_user_id = await self.db.scalar(
                    select(Doctor.user_id).where(Doctor.id == appointment.doctor_id)
                )
                if doc_user_id:
                    await notif_service.dispatch_notification(
                        user_id=doc_user_id,
                        title="Patient Discharge",
                        message=f"Your patient {patient.first_name} {patient.last_name} has been discharged from Bed {bed.name}.",
                        notification_type="PATIENT_DISCHARGE",
                        reference_type="BED_ALLOCATION",
                        reference_id=bed.id,
                        priority="NORMAL",
                        email=None,
                        phone=None,
                    )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Failed to dispatch discharge notification: %s", exc)

        return await self.get_bed(bed.id)

    async def transfer_bed(self, data: BedTransferRequest) -> Bed:
        if data.sourceBedId == data.targetBedId:
            raise BadRequestException("Source and target beds cannot be the same.")

        source_bed = await self.get_bed(data.sourceBedId)
        if source_bed.status == "Maintenance":
            raise BadRequestException(f"Source bed '{source_bed.name}' is under maintenance.")
        elif source_bed.status == "Cleaning":
            raise BadRequestException(f"Source bed '{source_bed.name}' is currently under cleaning.")
        elif source_bed.status in ("Inactive", "Blocked", "Unavailable", "Reserved"):
            raise BadRequestException(f"Source bed '{source_bed.name}' is currently unavailable.")
        elif source_bed.status != "Occupied" or not source_bed.patient_id:
            raise BadRequestException(f"Source bed '{source_bed.name}' is not occupied.")

        target_bed = await self.get_bed(data.targetBedId)
        if target_bed.status == "Occupied":
            raise BadRequestException(f"Target bed '{target_bed.name}' is already occupied.")
        elif target_bed.status == "Maintenance":
            raise BadRequestException(f"Target bed '{target_bed.name}' is under maintenance.")
        elif target_bed.status == "Cleaning":
            raise BadRequestException(f"Target bed '{target_bed.name}' is currently under cleaning.")
        elif target_bed.status in ("Inactive", "Blocked", "Unavailable", "Reserved") or target_bed.status != "Available":
            raise BadRequestException(f"Target bed '{target_bed.name}' is currently unavailable.")

        patient = await self.get_patient(source_bed.patient_id)

        allocation_time = source_bed.allocation_time
        admission_date = source_bed.admission_date
        source_room_name = source_bed.room.name if source_bed.room else ""
        target_room_name = target_bed.room.name if target_bed.room else ""

        target_bed.status = "Occupied"
        target_bed.patient_id = patient.id
        target_bed.allocation_time = allocation_time
        target_bed.admission_date = admission_date

        source_bed.status = "Available"
        source_bed.patient_id = None
        source_bed.allocation_time = None
        source_bed.admission_date = None

        old_room_name = source_bed.room.name if source_bed.room else "None"
        old_floor_name = source_bed.room.floor.name if source_bed.room and source_bed.room.floor else "None"
        new_room_name = target_bed.room.name if target_bed.room else "None"
        new_floor_name = target_bed.room.floor.name if target_bed.room and target_bed.room.floor else "None"

        transfer_note = f"\n[Bed Transfer]: Transferred from Bed {source_bed.name} to Bed {target_bed.name} on {utc_now().strftime('%Y-%m-%d')}. From Room {old_room_name}, Floor {old_floor_name} to Room {new_room_name}, Floor {new_floor_name}"
        patient.medical_history = f"{patient.medical_history or ''}{transfer_note}".strip()

        await self.db.flush()

        log = BedActivityLog(
            type="transfer",
            message=(
                f"Patient {patient.first_name} {patient.last_name} transferred from Bed {source_bed.name} ({source_room_name}) "
                f"to Bed {target_bed.name} ({target_room_name})."
            ),
            floor_id=target_bed.room.floor_id if target_bed.room else None,
            room_id=target_bed.room_id,
            bed_id=target_bed.id,
            patient_id=patient.id,
        )
        await self.repo.create_activity_log(log)

        return await self.get_bed(target_bed.id)

    # Activity Log Services
    async def list_activity_logs(self, limit: int = 50) -> List[BedActivityLog]:
        return await self.repo.list_activity_logs(limit)

    # Analytics Services
    async def get_analytics_summary(self) -> BedAnalyticsSummaryResponse:
        total_floors = await self.repo.count_floors()
        total_rooms = await self.repo.count_rooms()
        total_beds = await self.repo.count_beds()
        occupied_beds = await self.repo.count_occupied_beds()
        available_beds = await self.repo.count_available_beds()
        reserved_beds = await self.repo.count_reserved_beds()
        maint_clean_beds = await self.repo.count_maint_clean_beds()

        utilization_percentage = 0.0
        if total_beds > 0:
            utilization_percentage = round((occupied_beds / total_beds) * 100, 2)

        return BedAnalyticsSummaryResponse(
            total_floors=total_floors,
            total_rooms=total_rooms,
            total_beds=total_beds,
            occupied_beds=occupied_beds,
            available_beds=available_beds,
            reserved_beds=reserved_beds,
            maint_clean_beds=maint_clean_beds,
            utilization_percentage=utilization_percentage,
        )


    async def get_icu_analytics(self) -> ICUAnalyticsResponse:
        total, occupied, available = await self.repo.get_icu_bed_stats()

        utilization_percentage = 0.0
        if total > 0:
            utilization_percentage = round((occupied / total) * 100, 2)

        return ICUAnalyticsResponse(
            total_icu_beds=total,
            occupied_icu_beds=occupied,
            available_icu_beds=available,
            icu_utilization_percentage=utilization_percentage,
        )
