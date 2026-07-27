"""Unit tests for voice booking patient name matching / resolve helpers."""

from app.models.patient_model import Patient
from app.services.voice_patient_resolver import names_match, split_spoken_name


def _patient(first: str, last: str = "") -> Patient:
    return Patient(
        patient_code="PT-TEST",
        first_name=first,
        last_name=last,
        status="active",
    )


def test_split_spoken_name():
    assert split_spoken_name("Rahul Sharma") == ("Rahul", "Sharma")
    assert split_spoken_name("Priya") == ("Priya", "")
    assert split_spoken_name("  ") == ("Patient", "")


def test_names_match_full_and_first():
    p = _patient("Priya", "Patel")
    assert names_match("Priya Patel", p) is True
    assert names_match("priya", p) is True
    assert names_match("Rahul", p) is False
    assert names_match("Rahul Sharma", p) is False


def test_names_match_ignores_punctuation_case():
    p = _patient("Rahul", "Sharma")
    assert names_match("rahul sharma", p) is True
    assert names_match("Rahul, Sharma", p) is True
