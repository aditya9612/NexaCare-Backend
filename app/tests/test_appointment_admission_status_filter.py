from datetime import date
from unittest.mock import MagicMock
import pytest
from sqlalchemy import select

from app.models.appointment_model import Appointment
from app.repositories.appointment_repository import AppointmentRepository


@pytest.fixture
def repo():
    return AppointmentRepository(MagicMock())


# 1. Test that Admit Recommended filter generates query matching only Admit Recommended status
def test_admit_recommended_filter_sql_structure(repo):
    q = repo._apply_filters(select(Appointment), admission_status="Admit Recommended")
    compiled = str(q.compile(compile_kwargs={"literal_binds": True}))
    where_clause = compiled.split("WHERE")[1].lower()

    # Must contain admission_status condition
    assert "appointments.admission_status" in where_clause
    assert "admit recommended" in where_clause

    # Must NOT contain historical admission_recommended flag in WHERE clause
    assert "admission_recommended" not in where_clause


# 2. Test that variants of Admit Recommended (case, hyphens, underscores) are supported
@pytest.mark.parametrize("variant", [
    "Admit Recommended",
    "admit recommended",
    "ADMIT RECOMMENDED",
    "Admit-Recommended",
    "admit-recommended",
    "admit_recommended",
])
def test_admit_recommended_casing_and_formatting_variants(repo, variant):
    q = repo._apply_filters(select(Appointment), admission_status=variant)
    compiled = str(q.compile(compile_kwargs={"literal_binds": True}))
    where_clause = compiled.split("WHERE")[1].lower()

    assert "admit recommended" in where_clause or "admit-recommended" in where_clause or "admit_recommended" in where_clause
    assert "admission_recommended" not in where_clause


# 3. Test that other admission statuses continue to filter appropriately
@pytest.mark.parametrize("status_val, expected_match", [
    ("Admitted", "admitted"),
    ("admitted", "admitted"),
    ("Discharged", "discharged"),
    ("Not Recommended", "not recommended"),
    ("Cancelled", "cancelled"),
])
def test_other_admission_status_filters_work(repo, status_val, expected_match):
    q = repo._apply_filters(select(Appointment), admission_status=status_val)
    compiled = str(q.compile(compile_kwargs={"literal_binds": True}))
    where_clause = compiled.split("WHERE")[1].lower()

    assert expected_match in where_clause
    assert "admission_recommended" not in where_clause


# 4. Test combining admission_status with other standard appointment filters
def test_admission_status_combined_with_other_filters(repo):
    target_date = date(2026, 10, 8)
    q = repo._apply_filters(
        select(Appointment),
        admission_status="Admit Recommended",
        doctor_id=12,
        department_id=4,
        patient_id=99,
        status="Confirmed",
        appointment_date=target_date,
        appointment_type="OPD",
    )
    compiled = str(q.compile(compile_kwargs={"literal_binds": True}))
    where_clause = compiled.split("WHERE")[1].lower()

    assert "doctor_id = 12" in where_clause
    assert "department_id = 4" in where_clause
    assert "patient_id = 99" in where_clause
    assert "confirmed" in where_clause
    assert "2026-10-08" in where_clause
    assert "opd" in where_clause
    assert "admit recommended" in where_clause
    assert "admission_recommended" not in where_clause


# 5. Test status filter (appointment_status) doesn't leak historical admission_recommended
def test_status_filter_admit_recommended_no_historical_flag(repo):
    q = repo._apply_filters(select(Appointment), status="Admit Recommended")
    compiled = str(q.compile(compile_kwargs={"literal_binds": True}))
    where_clause = compiled.split("WHERE")[1].lower()

    assert "admission_recommended" not in where_clause
