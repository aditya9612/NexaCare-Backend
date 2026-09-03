"""
chat_auth.py — Isolated chat session hospital-scope authorization.

Phase 1: Prevent cross-hospital chat session spoofing.

This module is NEW and isolated.  It does NOT modify any existing
Voice Assistant, RAG, embedding, or FAQ code.

Authorization rules:
  SUPER_ADMIN   → may open a session for ANY valid hospital_id
  HOSPITAL_ADMIN → may open a session only for their own hospital_id
  All other roles → may open a session only if user.hospital_id matches
                     the requested hospital_id (same-hospital patient/staff)
  No hospital_id in request → always allowed (anonymous / no FAQ context)

Raises ForbiddenException (HTTP 403) when a mismatch is detected.
"""

from __future__ import annotations

from typing import Optional

from app.core.constants import UserRole
from app.core.exceptions import ForbiddenException
from app.models.user_model import User


def verify_chat_hospital_scope(user: User, requested_hospital_id: Optional[int]) -> Optional[int]:
    """
    Verify that *user* is authorised to open a chat session scoped to
    *requested_hospital_id*.

    Returns the resolved hospital_id to use (may equal the requested value
    or, for SUPER_ADMIN, is passed through unchanged).

    Raises ForbiddenException if the user is not authorised.

    Args:
        user: The currently authenticated User ORM object.
        requested_hospital_id: The hospital_id supplied in ChatSessionCreate.
                               None means no hospital scope was requested —
                               this is always allowed.

    Returns:
        Optional[int]: The authorised hospital_id, or None.
    """
    # No hospital scoping requested → nothing to check.
    if requested_hospital_id is None:
        return None

    role_name: str = user.role.name if user.role else ""

    # Super admins may access any hospital.
    if role_name == UserRole.SUPER_ADMIN:
        return requested_hospital_id

    # Hospital admins may only access their own hospital.
    if role_name == UserRole.HOSPITAL_ADMIN:
        if user.hospital_id and user.hospital_id == requested_hospital_id:
            return requested_hospital_id
        raise ForbiddenException(
            "Hospital Admin may only start a chat session for their own hospital."
        )

    # All other roles (Patient, Doctor, Nurse, etc.) must belong to the
    # requested hospital.
    if user.hospital_id and user.hospital_id == requested_hospital_id:
        return requested_hospital_id

    raise ForbiddenException(
        "You are not authorised to start a chat session for this hospital."
    )
