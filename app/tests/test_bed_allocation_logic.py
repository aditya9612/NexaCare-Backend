import random
import uuid
from datetime import date, datetime, time, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.constants import (
    AdmissionStatus,
    AppointmentStatus,
    AppointmentType,
    BedStatus,
    PatientStatus,
    UserRole,
)
from app.core.database import AsyncSessionLocal, engine, get_db
from app.core.dependencies import get_current_active_user
from app.core.exceptions import BadRequestException

@pytest.fixture(autouse=True)
async def cleanup_db_pool():
    yield
    await engine.dispose()

from app.main import app
from app.models.appointment_model import Appointment
from app.models.bed_allocation_model import Bed, BedActivityLog, Floor, Room
from app.models.doctor_model import Doctor
from app.models.patient_model import Patient
from app.models.role_model import Role
from app.models.user_model import User
from app.schemas.bed_allocation_schema import BedAllocationRequest
from app.services.bed_allocation_service import BedAllocationService


def build_admin_user() -> User:
    role = Role(id=1, name=UserRole.HOSPITAL_ADMIN, description="Admin role")
    user = User(
        id=9999,
        user_code="USR-TEST-ADMIN",
        email="admin_test@nexacare.com",
        full_name="Admin Test User",
        role_id=role.id,
        is_active=True,
        is_verified=True,
        hashed_password="hashed_password",
    )
    user.role = role
    return user


async def create_test_environment(db):
    """Creates a fresh Floor, Room, Bed, Doctor, and Patient for isolated testing."""
    floor = Floor(
        number=random.randint(10000, 99999),
        name=f"Floor {uuid.uuid4().hex[:4]}",
        type="General",
    )
    db.add(floor)
    await db.flush()

    room = Room(
        floor_id=floor.id,
        number=random.randint(100, 999),
        name=f"Room {uuid.uuid4().hex[:4]}",
        type="General",
        capacity=2,
    )
    db.add(room)
    await db.flush()

    bed = Bed(
        room_id=room.id,
        name=f"Bed-{uuid.uuid4().hex[:4].upper()}",
        type="General",
        status=BedStatus.AVAILABLE.value,
    )
    db.add(bed)
    await db.flush()

    doctor = (await db.execute(select(Doctor))).scalars().first()
    if not doctor:
        doctor = Doctor(
            doctor_code=f"DOC-{uuid.uuid4().hex[:6].upper()}",
            first_name="Doctor",
            last_name="Test",
            specialization="General Medicine",
            license_number=f"LIC-{uuid.uuid4().hex[:6].upper()}",
            availability_status="available",
        )
        db.add(doctor)
        await db.flush()

    patient = Patient(
        patient_code=f"PAT-{uuid.uuid4().hex[:6].upper()}",
        first_name="Test",
        last_name="Patient",
        status=PatientStatus.ACTIVE,
        diagnosis="",
    )
    db.add(patient)
    await db.flush()

    return floor, room, bed, doctor, patient


@pytest.mark.asyncio
async def test_case_1_follow_up_appointment_rejected():
    """
    Case 1: Available bed, patient with Follow-up appointment (not recommended for admission).
    Must raise BadRequestException (400).
    Bed status must remain Available, patient_id must remain None, no BedActivityLog created.
    """
    async with AsyncSessionLocal() as db:
        floor, room, bed, doctor, patient = await create_test_environment(db)

        # Create Follow-up appointment
        followup_appt = Appointment(
            appointment_number=f"APT-{uuid.uuid4().hex[:8].upper()}",
            patient_id=patient.id,
            doctor_id=doctor.id,
            appointment_date=date.today(),
            appointment_time=time(10, 0),
            appointment_type=AppointmentType.FOLLOW_UP.value,
            appointment_status=AppointmentStatus.COMPLETED,
            admission_recommended=False,
            admission_status=AdmissionStatus.NOT_RECOMMENDED,
        )
        db.add(followup_appt)
        await db.commit()

        initial_logs_count = (
            await db.execute(
                select(BedActivityLog).where(BedActivityLog.bed_id == bed.id)
            )
        ).scalars().all()

        service = BedAllocationService(db)
        request_data = BedAllocationRequest(
            patientId=patient.id,
            admissionDate=datetime.now(timezone.utc) + timedelta(days=1),
        )

        with pytest.raises(BadRequestException) as exc_info:
            await service.allocate_bed(bed.id, request_data)

        assert "Bed allocation is not allowed for Follow-up appointments" in exc_info.value.detail

        # Invariant checks: Bed status remains Available, patient_id remains None, no logs
        await db.refresh(bed)
        assert bed.status == BedStatus.AVAILABLE.value
        assert bed.patient_id is None

        current_logs = (
            await db.execute(
                select(BedActivityLog).where(BedActivityLog.bed_id == bed.id)
            )
        ).scalars().all()
        assert len(current_logs) == len(initial_logs_count)


@pytest.mark.asyncio
async def test_case_2_opd_appointment_rejected():
    """
    Case 2: Available bed, patient with OPD appointment.
    Must raise BadRequestException (400).
    Bed status must remain Available, no BedActivityLog created.
    """
    async with AsyncSessionLocal() as db:
        floor, room, bed, doctor, patient = await create_test_environment(db)

        opd_appt = Appointment(
            appointment_number=f"APT-{uuid.uuid4().hex[:8].upper()}",
            patient_id=patient.id,
            doctor_id=doctor.id,
            appointment_date=date.today(),
            appointment_time=time(11, 0),
            appointment_type=AppointmentType.OPD.value,
            appointment_status=AppointmentStatus.COMPLETED,
            admission_recommended=False,
            admission_status=AdmissionStatus.NOT_RECOMMENDED,
        )
        db.add(opd_appt)
        await db.commit()

        initial_logs_count = (
            await db.execute(
                select(BedActivityLog).where(BedActivityLog.bed_id == bed.id)
            )
        ).scalars().all()

        service = BedAllocationService(db)
        request_data = BedAllocationRequest(
            patientId=patient.id,
            admissionDate=datetime.now(timezone.utc) + timedelta(days=1),
        )

        with pytest.raises(BadRequestException) as exc_info:
            await service.allocate_bed(bed.id, request_data)

        assert "Bed allocation is not allowed for OPD appointments" in exc_info.value.detail

        await db.refresh(bed)
        assert bed.status == BedStatus.AVAILABLE.value
        assert bed.patient_id is None

        current_logs = (
            await db.execute(
                select(BedActivityLog).where(BedActivityLog.bed_id == bed.id)
            )
        ).scalars().all()
        assert len(current_logs) == len(initial_logs_count)


@pytest.mark.asyncio
async def test_case_3_ipd_appointment_without_valid_admission_rejected():
    """
    Case 3: Available bed, patient with IPD appointment where admission_recommended is False
    and admission_status is None / Not Recommended.
    Must raise BadRequestException (400).
    Bed status must remain Available.
    """
    async with AsyncSessionLocal() as db:
        floor, room, bed, doctor, patient = await create_test_environment(db)

        ipd_appt = Appointment(
            appointment_number=f"APT-{uuid.uuid4().hex[:8].upper()}",
            patient_id=patient.id,
            doctor_id=doctor.id,
            appointment_date=date.today(),
            appointment_time=time(9, 0),
            appointment_type=AppointmentType.IPD.value,
            appointment_status=AppointmentStatus.CONFIRMED,
            admission_recommended=False,
            admission_status=AdmissionStatus.NOT_RECOMMENDED,
        )
        db.add(ipd_appt)
        await db.commit()

        service = BedAllocationService(db)
        request_data = BedAllocationRequest(
            patientId=patient.id,
            admissionDate=datetime.now(timezone.utc) + timedelta(days=1),
        )

        with pytest.raises(BadRequestException) as exc_info:
            await service.allocate_bed(bed.id, request_data)

        assert "Bed allocation requires a valid admission recommendation" in exc_info.value.detail

        await db.refresh(bed)
        assert bed.status == BedStatus.AVAILABLE.value
        assert bed.patient_id is None


@pytest.mark.asyncio
async def test_case_4_ipd_appointment_with_valid_admission_succeeds():
    """
    Case 4: Available bed, patient with IPD appointment where admission_recommended is True
    and admission_status is Admit Recommended.
    Allocation succeeds: bed status -> Occupied, patient_id is set,
    appointment.admission_status -> Admitted, BedActivityLog created.
    """
    async with AsyncSessionLocal() as db:
        floor, room, bed, doctor, patient = await create_test_environment(db)

        ipd_appt = Appointment(
            appointment_number=f"APT-{uuid.uuid4().hex[:8].upper()}",
            patient_id=patient.id,
            doctor_id=doctor.id,
            appointment_date=date.today(),
            appointment_time=time(14, 0),
            appointment_type=AppointmentType.IPD.value,
            appointment_status=AppointmentStatus.ADMIT_RECOMMENDED,
            admission_recommended=True,
            admission_status=AdmissionStatus.ADMIT_RECOMMENDED,
        )
        db.add(ipd_appt)
        await db.commit()

        service = BedAllocationService(db)
        alloc_date = datetime.now(timezone.utc) + timedelta(days=1)
        request_data = BedAllocationRequest(
            patientId=patient.id,
            admissionDate=alloc_date,
            notes="Admission via emergency doctor recommendation",
        )

        allocated_bed = await service.allocate_bed(bed.id, request_data)
        await db.commit()

        assert allocated_bed.status == BedStatus.OCCUPIED.value
        assert allocated_bed.patient_id == patient.id

        await db.refresh(ipd_appt)
        assert ipd_appt.admission_status == AdmissionStatus.ADMITTED
        assert ipd_appt.appointment_status == AppointmentStatus.COMPLETED
        assert ipd_appt.admission_recommended is True
        assert ipd_appt.admission_number is not None

        logs = (
            await db.execute(
                select(BedActivityLog).where(
                    BedActivityLog.bed_id == bed.id,
                    BedActivityLog.type == "allocation",
                )
            )
        ).scalars().all()
        assert len(logs) >= 1
        assert logs[-1].patient_id == patient.id


@pytest.mark.asyncio
async def test_direct_appointment_id_followup_and_opd_rejected():
    """
    Verify that explicitly passing appointmentId of Follow-up or OPD appointment
    is strictly rejected and cannot bypass validation.
    """
    async with AsyncSessionLocal() as db:
        floor, room, bed, doctor, patient = await create_test_environment(db)

        followup_appt = Appointment(
            appointment_number=f"APT-{uuid.uuid4().hex[:8].upper()}",
            patient_id=patient.id,
            doctor_id=doctor.id,
            appointment_date=date.today(),
            appointment_time=time(10, 0),
            appointment_type=AppointmentType.FOLLOW_UP.value,
            appointment_status=AppointmentStatus.COMPLETED,
            admission_recommended=False,
        )
        opd_appt = Appointment(
            appointment_number=f"APT-{uuid.uuid4().hex[:8].upper()}",
            patient_id=patient.id,
            doctor_id=doctor.id,
            appointment_date=date.today(),
            appointment_time=time(11, 0),
            appointment_type=AppointmentType.OPD.value,
            appointment_status=AppointmentStatus.COMPLETED,
            admission_recommended=False,
        )
        db.add_all([followup_appt, opd_appt])
        await db.commit()

        service = BedAllocationService(db)

        # 1. Target Follow-up explicitly
        with pytest.raises(BadRequestException) as exc_1:
            await service.allocate_bed(
                bed.id,
                BedAllocationRequest(
                    patientId=patient.id,
                    appointmentId=followup_appt.id,
                    admissionDate=datetime.now(timezone.utc) + timedelta(days=1),
                ),
            )
        assert "Bed allocation is not allowed for Follow-up appointments" in exc_1.value.detail

        # 2. Target OPD explicitly
        with pytest.raises(BadRequestException) as exc_2:
            await service.allocate_bed(
                bed.id,
                BedAllocationRequest(
                    patientId=patient.id,
                    appointmentId=opd_appt.id,
                    admissionDate=datetime.now(timezone.utc) + timedelta(days=1),
                ),
            )
        assert "Bed allocation is not allowed for OPD appointments" in exc_2.value.detail


@pytest.mark.asyncio
async def test_cancelled_discharged_pending_appointments_rejected():
    """
    Verify that cancelled, already discharged, and pending appointments are rejected.
    """
    async with AsyncSessionLocal() as db:
        floor, room, bed, doctor, patient = await create_test_environment(db)

        # Cancelled IPD appointment
        cancelled_appt = Appointment(
            appointment_number=f"APT-{uuid.uuid4().hex[:8].upper()}",
            patient_id=patient.id,
            doctor_id=doctor.id,
            appointment_date=date.today(),
            appointment_time=time(10, 0),
            appointment_type=AppointmentType.IPD.value,
            appointment_status=AppointmentStatus.CANCELLED,
            admission_recommended=True,
            admission_status=AdmissionStatus.CANCELLED,
        )
        # Discharged IPD appointment
        discharged_appt = Appointment(
            appointment_number=f"APT-{uuid.uuid4().hex[:8].upper()}",
            patient_id=patient.id,
            doctor_id=doctor.id,
            appointment_date=date.today(),
            appointment_time=time(11, 0),
            appointment_type=AppointmentType.IPD.value,
            appointment_status=AppointmentStatus.COMPLETED,
            admission_recommended=True,
            admission_status=AdmissionStatus.DISCHARGED,
        )
        # Pending IPD appointment
        pending_appt = Appointment(
            appointment_number=f"APT-{uuid.uuid4().hex[:8].upper()}",
            patient_id=patient.id,
            doctor_id=doctor.id,
            appointment_date=date.today(),
            appointment_time=time(12, 0),
            appointment_type=AppointmentType.IPD.value,
            appointment_status=AppointmentStatus.PENDING,
            admission_recommended=True,
            admission_status=AdmissionStatus.ADMIT_RECOMMENDED,
        )
        db.add_all([cancelled_appt, discharged_appt, pending_appt])
        await db.commit()

        service = BedAllocationService(db)

        # Cancelled
        with pytest.raises(BadRequestException) as exc_c:
            await service.allocate_bed(
                bed.id,
                BedAllocationRequest(
                    patientId=patient.id,
                    appointmentId=cancelled_appt.id,
                    admissionDate=datetime.now(timezone.utc) + timedelta(days=1),
                ),
            )
        assert "cancelled" in exc_c.value.detail.lower()

        # Discharged
        with pytest.raises(BadRequestException) as exc_d:
            await service.allocate_bed(
                bed.id,
                BedAllocationRequest(
                    patientId=patient.id,
                    appointmentId=discharged_appt.id,
                    admissionDate=datetime.now(timezone.utc) + timedelta(days=1),
                ),
            )
        assert "discharged" in exc_d.value.detail.lower()

        # Pending
        with pytest.raises(BadRequestException) as exc_p:
            await service.allocate_bed(
                bed.id,
                BedAllocationRequest(
                    patientId=patient.id,
                    appointmentId=pending_appt.id,
                    admissionDate=datetime.now(timezone.utc) + timedelta(days=1),
                ),
            )
        assert "pending appointment" in exc_p.value.detail.lower()


@pytest.mark.asyncio
async def test_unavailable_bed_rejected():
    """
    Given an Occupied or Maintenance bed, allocation must be rejected
    even if the patient has a valid IPD admission appointment.
    """
    async with AsyncSessionLocal() as db:
        floor, room, bed, doctor, patient = await create_test_environment(db)

        bed.status = BedStatus.OCCUPIED.value
        await db.commit()

        ipd_appt = Appointment(
            appointment_number=f"APT-{uuid.uuid4().hex[:8].upper()}",
            patient_id=patient.id,
            doctor_id=doctor.id,
            appointment_date=date.today(),
            appointment_time=time(10, 0),
            appointment_type=AppointmentType.IPD.value,
            appointment_status=AppointmentStatus.ADMIT_RECOMMENDED,
            admission_recommended=True,
            admission_status=AdmissionStatus.ADMIT_RECOMMENDED,
        )
        db.add(ipd_appt)
        await db.commit()

        service = BedAllocationService(db)
        with pytest.raises(BadRequestException) as exc_occ:
            await service.allocate_bed(
                bed.id,
                BedAllocationRequest(
                    patientId=patient.id,
                    admissionDate=datetime.now(timezone.utc) + timedelta(days=1),
                ),
            )
        assert "occupied" in exc_occ.value.detail.lower()

        # Test Maintenance bed
        bed.status = BedStatus.MAINTENANCE.value
        await db.commit()
        with pytest.raises(BadRequestException) as exc_maint:
            await service.allocate_bed(
                bed.id,
                BedAllocationRequest(
                    patientId=patient.id,
                    admissionDate=datetime.now(timezone.utc) + timedelta(days=1),
                ),
            )
        assert "not available" in exc_maint.value.detail.lower()


@pytest.mark.asyncio
async def test_direct_api_endpoint_bed_allocation():
    """
    Test POST /api/beds/{bedId}/allocate over HTTP:
    1. Follow-up appointment returns HTTP 400.
    2. Valid IPD admission appointment returns HTTP 200 with allocated bed.
    """
    async with AsyncSessionLocal() as db:
        floor, room, bed, doctor, patient = await create_test_environment(db)

        followup_appt = Appointment(
            appointment_number=f"APT-{uuid.uuid4().hex[:8].upper()}",
            patient_id=patient.id,
            doctor_id=doctor.id,
            appointment_date=date.today(),
            appointment_time=time(10, 0),
            appointment_type=AppointmentType.FOLLOW_UP.value,
            appointment_status=AppointmentStatus.COMPLETED,
            admission_recommended=False,
        )
        db.add(followup_appt)
        await db.commit()

        admin_user = build_admin_user()

        async def _override_user():
            return admin_user

        async def _override_db():
            yield db

        app.dependency_overrides[get_current_active_user] = _override_user
        app.dependency_overrides[get_db] = _override_db

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            future_dt = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

            # 1. Attempt allocating with Follow-up appointment -> Expect 400 Bad Request
            res = await client.post(
                f"/api/beds/{bed.id}/allocate",
                json={
                    "patientId": patient.id,
                    "appointmentId": followup_appt.id,
                    "admissionDate": future_dt,
                    "notes": "Direct API test for Follow-up",
                },
            )
            assert res.status_code == 400
            data = res.json()
            assert "Follow-up" in str(data)

            # Ensure bed status is still Available
            await db.refresh(bed)
            assert bed.status == BedStatus.AVAILABLE.value

            # 2. Add valid IPD appointment
            ipd_appt = Appointment(
                appointment_number=f"APT-{uuid.uuid4().hex[:8].upper()}",
                patient_id=patient.id,
                doctor_id=doctor.id,
                appointment_date=date.today(),
                appointment_time=time(15, 0),
                appointment_type=AppointmentType.IPD.value,
                appointment_status=AppointmentStatus.ADMIT_RECOMMENDED,
                admission_recommended=True,
                admission_status=AdmissionStatus.ADMIT_RECOMMENDED,
            )
            db.add(ipd_appt)
            await db.commit()

            # Attempt allocating with valid IPD appointment -> Expect 200 OK
            res_success = await client.post(
                f"/api/beds/{bed.id}/allocate",
                json={
                    "patientId": patient.id,
                    "appointmentId": ipd_appt.id,
                    "admissionDate": future_dt,
                    "notes": "Direct API test for IPD success",
                },
            )
            assert res_success.status_code == 200
            res_data = res_success.json()
            assert res_data["success"] is True
            assert res_data["data"]["status"] == BedStatus.OCCUPIED.value
            assert res_data["data"]["patient_id"] == patient.id

        app.dependency_overrides.clear()
