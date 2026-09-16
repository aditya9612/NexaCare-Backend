"""
test_chat_hospital_scope.py — Phase 1 tenant security hardening tests.

Tests for verify_chat_hospital_scope() in app.core.chat_auth.

Covers:
  TEST 1 — Same hospital (all non-admin roles) → allowed
  TEST 2 — Cross-hospital (non-admin)          → 403 ForbiddenException
  TEST 3 — SUPER_ADMIN any hospital            → allowed
  TEST 4 — Patient cross-hospital              → 403 ForbiddenException
  TEST 5 — No hospital_id in request           → always allowed
  TEST 6 — HOSPITAL_ADMIN own hospital         → allowed
  TEST 7 — HOSPITAL_ADMIN cross-hospital       → 403 ForbiddenException
  TEST 8 — HOSPITAL_ADMIN no hospital_id       → allowed (no scope)
"""

from unittest.mock import MagicMock

import pytest

from app.core.chat_auth import verify_chat_hospital_scope
from app.core.constants import UserRole
from app.core.exceptions import ForbiddenException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(role_name: str, hospital_id: int | None = None) -> MagicMock:
    """Build a mock User with the specified role and hospital_id."""
    user = MagicMock()
    user.hospital_id = hospital_id
    user.role = MagicMock()
    user.role.name = role_name
    return user


# ---------------------------------------------------------------------------
# TEST 1 — Same hospital: non-admin user requests their own hospital
# ---------------------------------------------------------------------------

def test_same_hospital_allowed():
    """A patient/staff member requesting their own hospital is allowed."""
    user = _make_user(UserRole.PATIENT, hospital_id=1)
    result = verify_chat_hospital_scope(user, requested_hospital_id=1)
    assert result == 1


# ---------------------------------------------------------------------------
# TEST 2 — Cross-hospital: non-admin user requests a different hospital
# ---------------------------------------------------------------------------

def test_cross_hospital_raises_forbidden():
    """A patient requesting a hospital they do not belong to must get 403."""
    user = _make_user(UserRole.PATIENT, hospital_id=1)
    with pytest.raises(ForbiddenException):
        verify_chat_hospital_scope(user, requested_hospital_id=2)


def test_cross_hospital_doctor_raises_forbidden():
    """A doctor from hospital 1 requesting hospital 2 must get 403."""
    user = _make_user(UserRole.DOCTOR, hospital_id=1)
    with pytest.raises(ForbiddenException):
        verify_chat_hospital_scope(user, requested_hospital_id=99)


# ---------------------------------------------------------------------------
# TEST 3 — SUPER_ADMIN: can access any hospital
# ---------------------------------------------------------------------------

def test_super_admin_any_hospital_allowed():
    """SUPER_ADMIN can open a session scoped to any hospital."""
    user = _make_user(UserRole.SUPER_ADMIN, hospital_id=1)
    result = verify_chat_hospital_scope(user, requested_hospital_id=999)
    assert result == 999


def test_super_admin_without_own_hospital_id_allowed():
    """SUPER_ADMIN with no hospital_id can still open sessions for any hospital."""
    user = _make_user(UserRole.SUPER_ADMIN, hospital_id=None)
    result = verify_chat_hospital_scope(user, requested_hospital_id=42)
    assert result == 42


# ---------------------------------------------------------------------------
# TEST 4 — Patient cross-hospital: explicit 403
# ---------------------------------------------------------------------------

def test_patient_cross_hospital_raises_forbidden():
    """Patient from hospital 5 requesting hospital 10 must get 403."""
    user = _make_user(UserRole.PATIENT, hospital_id=5)
    with pytest.raises(ForbiddenException):
        verify_chat_hospital_scope(user, requested_hospital_id=10)


# ---------------------------------------------------------------------------
# TEST 5 — No hospital_id in request: always allowed regardless of role
# ---------------------------------------------------------------------------

def test_no_hospital_id_patient_allowed():
    """No hospital_id means no scope check; patient always allowed."""
    user = _make_user(UserRole.PATIENT, hospital_id=1)
    result = verify_chat_hospital_scope(user, requested_hospital_id=None)
    assert result is None


def test_no_hospital_id_admin_allowed():
    """No hospital_id means no scope check; admin always allowed."""
    user = _make_user(UserRole.HOSPITAL_ADMIN, hospital_id=3)
    result = verify_chat_hospital_scope(user, requested_hospital_id=None)
    assert result is None


# ---------------------------------------------------------------------------
# TEST 6 — HOSPITAL_ADMIN own hospital: allowed
# ---------------------------------------------------------------------------

def test_hospital_admin_own_hospital_allowed():
    """HOSPITAL_ADMIN can open a session for their own hospital."""
    user = _make_user(UserRole.HOSPITAL_ADMIN, hospital_id=7)
    result = verify_chat_hospital_scope(user, requested_hospital_id=7)
    assert result == 7


# ---------------------------------------------------------------------------
# TEST 7 — HOSPITAL_ADMIN cross-hospital: 403
# ---------------------------------------------------------------------------

def test_hospital_admin_cross_hospital_raises_forbidden():
    """HOSPITAL_ADMIN must not be allowed to open sessions for another hospital."""
    user = _make_user(UserRole.HOSPITAL_ADMIN, hospital_id=7)
    with pytest.raises(ForbiddenException):
        verify_chat_hospital_scope(user, requested_hospital_id=99)


# ---------------------------------------------------------------------------
# TEST 8 — HOSPITAL_ADMIN with no hospital_id assignment: no scope → allowed
# ---------------------------------------------------------------------------

def test_hospital_admin_no_hospital_id_no_scope_allowed():
    """If no hospital_id is requested, HOSPITAL_ADMIN is always allowed."""
    user = _make_user(UserRole.HOSPITAL_ADMIN, hospital_id=None)
    result = verify_chat_hospital_scope(user, requested_hospital_id=None)
    assert result is None


# ---------------------------------------------------------------------------
# TEST 9 — Return value is the requested hospital_id (not user.hospital_id)
# ---------------------------------------------------------------------------

def test_super_admin_returns_requested_not_own():
    """verify_chat_hospital_scope must return requested_hospital_id for SUPER_ADMIN."""
    user = _make_user(UserRole.SUPER_ADMIN, hospital_id=1)
    result = verify_chat_hospital_scope(user, requested_hospital_id=77)
    assert result == 77  # not 1


def test_patient_returns_own_hospital_id():
    """verify_chat_hospital_scope must return the authorised hospital_id."""
    user = _make_user(UserRole.PATIENT, hospital_id=3)
    result = verify_chat_hospital_scope(user, requested_hospital_id=3)
    assert result == 3


# ---------------------------------------------------------------------------
# TEST 10 — ForbiddenException is raised (not a generic Exception)
# ---------------------------------------------------------------------------

def test_forbidden_is_exact_type():
    """Ensure the exception type is ForbiddenException (not a generic error)."""
    user = _make_user(UserRole.NURSE, hospital_id=2)
    exc = None
    try:
        verify_chat_hospital_scope(user, requested_hospital_id=8)
    except ForbiddenException as e:
        exc = e
    assert exc is not None, "ForbiddenException was not raised"
