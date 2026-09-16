import datetime
import pytest
from pydantic import ValidationError

from app.core.exceptions import ConflictException
from app.models.doctor_model import DoctorSchedule
from app.schemas.doctor_schema import (
    DoctorScheduleCreate,
    DoctorScheduleResponse,
    DoctorScheduleUpdate,
)


def test_doctor_schedule_create_valid_days():
    """Verify DoctorScheduleCreate accepts day_of_week from 0 (Monday) to 6 (Sunday) without conversion."""
    # Monday = 0
    create_mon = DoctorScheduleCreate(
        day_of_week=0,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
        slot_duration_minutes=30,
    )
    assert create_mon.day_of_week == 0

    # Tuesday = 1
    create_tue = DoctorScheduleCreate(
        day_of_week=1,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
        slot_duration_minutes=30,
    )
    assert create_tue.day_of_week == 1

    # Sunday = 6
    create_sun = DoctorScheduleCreate(
        day_of_week=6,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
        slot_duration_minutes=30,
    )
    assert create_sun.day_of_week == 6


def test_doctor_schedule_create_invalid_days():
    """Verify invalid day_of_week values (-1 and 7) are rejected by Pydantic schema validation."""
    with pytest.raises(ValidationError):
        DoctorScheduleCreate(
            day_of_week=-1,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
            slot_duration_minutes=30,
        )

    with pytest.raises(ValidationError):
        DoctorScheduleCreate(
            day_of_week=7,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
            slot_duration_minutes=30,
        )


def test_doctor_schedule_update_valid_and_invalid_days():
    """Verify DoctorScheduleUpdate accepts 0..6 and rejects out of bounds days."""
    update_valid = DoctorScheduleUpdate(day_of_week=0)
    assert update_valid.day_of_week == 0

    update_sun = DoctorScheduleUpdate(day_of_week=6)
    assert update_sun.day_of_week == 6

    with pytest.raises(ValidationError):
        DoctorScheduleUpdate(day_of_week=-1)

    with pytest.raises(ValidationError):
        DoctorScheduleUpdate(day_of_week=7)


def test_doctor_schedule_response_exact_stored_values():
    """Verify DoctorScheduleResponse returns exact stored database values (0..6) without shifting."""
    db_schedule_mon = DoctorSchedule(
        id=101,
        doctor_id=1,
        day_of_week=0,  # Monday
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
        slot_duration_minutes=30,
        is_active=True,
    )
    response_mon = DoctorScheduleResponse.model_validate(db_schedule_mon)
    assert response_mon.day_of_week == 0

    db_schedule_tue = DoctorSchedule(
        id=102,
        doctor_id=1,
        day_of_week=1,  # Tuesday
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
        slot_duration_minutes=30,
        is_active=True,
    )
    response_tue = DoctorScheduleResponse.model_validate(db_schedule_tue)
    assert response_tue.day_of_week == 1

    db_schedule_sun = DoctorSchedule(
        id=103,
        doctor_id=1,
        day_of_week=6,  # Sunday
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
        slot_duration_minutes=30,
        is_active=True,
    )
    response_sun = DoctorScheduleResponse.model_validate(db_schedule_sun)
    assert response_sun.day_of_week == 6
