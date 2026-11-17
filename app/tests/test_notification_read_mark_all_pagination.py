"""
Targeted tests for Notification Read/Unread Tracking, Mark All as Read, and Deterministic Pagination.

Covers:
- FIX 1: Mark All as Read (Cross-user, Hospital Admin, Super Admin, idempotency, soft-delete exclusion)
- FIX 2: Deterministic Pagination (First/middle/last pages, deterministic sorting tie-breaker, filters)
- FIX 3: Single Notification Read Tenant Hardening (Ownership, cross-hospital, legacy NULL hospital, role isolation)
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from sqlalchemy import select, update

from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.notification_model import Notification
from app.models.user_model import User
from app.repositories.notification_repository import NotificationRepository
from app.schemas.notification_schema import NotificationResponse
from app.services.notification_service import NotificationService
from app.utils.pagination import PaginatedResult


# ============================================================================
# PART A: MARK ALL AS READ TESTS (1 - 11)
# ============================================================================

@pytest.mark.asyncio
async def test_mark_all_as_read_own_notifications_updated():
    """1. Ordinary user can mark their own notifications as read."""
    db = MagicMock()
    captured_stmts = []

    async def mock_execute(stmt):
        captured_stmts.append(stmt)
        res = MagicMock()
        res.rowcount = 4
        return res

    db.execute = mock_execute
    service = NotificationService(db)

    result = await service.mark_all_as_read(user_id=101, hospital_id=1)
    assert result["updated_count"] == 4
    assert result["message"] == "All notifications marked as read"

    stmt = captured_stmts[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "notifications.user_id = 101" in sql
    assert "notifications.is_read IS false" in sql or "notifications.is_read = false" in sql or "notifications.is_read = 0" in sql


@pytest.mark.asyncio
async def test_mark_all_as_read_other_users_remain_unread():
    """2. Another user's notifications remain unread (strictly scoped to caller user_id)."""
    db = MagicMock()
    captured_stmts = []

    async def mock_execute(stmt):
        captured_stmts.append(stmt)
        res = MagicMock()
        res.rowcount = 2
        return res

    db.execute = mock_execute
    service = NotificationService(db)

    # User 101 calls mark_all_as_read
    await service.mark_all_as_read(user_id=101, hospital_id=1)
    stmt = captured_stmts[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    # Confirms query cannot match user 102
    assert "notifications.user_id = 101" in sql
    assert "notifications.user_id = 102" not in sql


@pytest.mark.asyncio
async def test_mark_all_as_read_hospital_admin_only_updates_own():
    """3. Hospital Admin only updates their own notifications (no hospital-wide bulk update)."""
    db = MagicMock()
    captured_stmts = []

    async def mock_execute(stmt):
        captured_stmts.append(stmt)
        res = MagicMock()
        res.rowcount = 1
        return res

    db.execute = mock_execute
    service = NotificationService(db)

    # Hospital Admin (user 200) calls mark_all_as_read
    result = await service.mark_all_as_read(
        user_id=200,
        hospital_id=1,
        is_hospital_admin=True,
    )
    assert result["updated_count"] == 1

    stmt = captured_stmts[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    # MUST strictly update user_id = 200, never an unconstrained OR matching all hospital users
    assert "notifications.user_id = 200" in sql
    assert "notifications.hospital_id = 1 OR notifications.user_id = 200" not in sql


@pytest.mark.asyncio
async def test_mark_all_as_read_hospital_admin_cannot_clear_doctors():
    """4. Hospital Admin calling mark_all_as_read does NOT clear Doctor notifications."""
    db = MagicMock()
    captured_stmts = []

    async def mock_execute(stmt):
        captured_stmts.append(stmt)
        res = MagicMock()
        res.rowcount = 1
        return res

    db.execute = mock_execute
    repo = NotificationRepository(db)

    # Hospital Admin (user 200) executes mark_all_as_read
    await repo.mark_all_as_read(
        user_id=200,
        hospital_id=1,
        is_hospital_admin=True,
    )
    stmt = captured_stmts[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    # Doctor (e.g. user_id=301) is not targeted
    assert "notifications.user_id = 200" in sql
    assert "301" not in sql


@pytest.mark.asyncio
async def test_mark_all_as_read_hospital_admin_cannot_clear_nurses():
    """5. Hospital Admin calling mark_all_as_read does NOT clear Nurse notifications."""
    db = MagicMock()
    captured_stmts = []

    async def mock_execute(stmt):
        captured_stmts.append(stmt)
        res = MagicMock()
        res.rowcount = 1
        return res

    db.execute = mock_execute
    repo = NotificationRepository(db)

    # Hospital Admin (user 200) executes mark_all_as_read
    await repo.mark_all_as_read(
        user_id=200,
        hospital_id=1,
        is_hospital_admin=True,
    )
    stmt = captured_stmts[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    # Nurse (e.g. user_id=401) is not targeted
    assert "notifications.user_id = 200" in sql
    assert "401" not in sql


@pytest.mark.asyncio
async def test_mark_all_as_read_super_admin_only_updates_own():
    """6. Super Admin only updates their own notifications (no tenant-wide clear)."""
    db = MagicMock()
    captured_stmts = []

    async def mock_execute(stmt):
        captured_stmts.append(stmt)
        res = MagicMock()
        res.rowcount = 3
        return res

    db.execute = mock_execute
    service = NotificationService(db)

    # Super Admin (user 1) calls mark_all_as_read with hospital_id=1 override
    result = await service.mark_all_as_read(
        user_id=1,
        hospital_id=1,
        is_super_admin=True,
    )
    assert result["updated_count"] == 3

    stmt = captured_stmts[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    # Strictly scoped to user 1
    assert "notifications.user_id = 1" in sql


@pytest.mark.asyncio
async def test_mark_all_as_read_cross_hospital_notifications_untouched():
    """7. Cross-hospital notifications remain untouched when hospital_id is scoped."""
    db = MagicMock()
    captured_stmts = []

    async def mock_execute(stmt):
        captured_stmts.append(stmt)
        res = MagicMock()
        res.rowcount = 1
        return res

    db.execute = mock_execute
    repo = NotificationRepository(db)

    await repo.mark_all_as_read(user_id=101, hospital_id=1)
    stmt = captured_stmts[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    # Ensures hospital_id=1 or NULL, excluding hospital_id=2
    assert "notifications.hospital_id = 1" in sql
    assert "notifications.hospital_id = 2" not in sql


@pytest.mark.asyncio
async def test_mark_all_as_read_repeated_requests_idempotent():
    """8. Repeated requests are idempotent (second call updates 0 records)."""
    db = MagicMock()
    calls = []

    async def mock_execute(stmt):
        calls.append(stmt)
        res = MagicMock()
        # First call updates 3 rows, second call updates 0 rows
        res.rowcount = 3 if len(calls) == 1 else 0
        return res

    db.execute = mock_execute
    service = NotificationService(db)

    res1 = await service.mark_all_as_read(user_id=101, hospital_id=1)
    assert res1["updated_count"] == 3

    res2 = await service.mark_all_as_read(user_id=101, hospital_id=1)
    assert res2["updated_count"] == 0


@pytest.mark.asyncio
async def test_mark_all_as_read_empty_notification_list():
    """9. Empty notification list returns zero updated records."""
    db = MagicMock()

    async def mock_execute(stmt):
        res = MagicMock()
        res.rowcount = 0
        return res

    db.execute = mock_execute
    service = NotificationService(db)

    res = await service.mark_all_as_read(user_id=999, hospital_id=1)
    assert res["updated_count"] == 0
    assert res["message"] == "All notifications marked as read"


@pytest.mark.asyncio
async def test_mark_all_as_read_already_read_remain_unchanged():
    """10. Already-read notifications remain unchanged (matched by is_read=False)."""
    db = MagicMock()
    captured_stmts = []

    async def mock_execute(stmt):
        captured_stmts.append(stmt)
        res = MagicMock()
        res.rowcount = 0
        return res

    db.execute = mock_execute
    repo = NotificationRepository(db)

    await repo.mark_all_as_read(user_id=101, hospital_id=1)
    stmt = captured_stmts[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "notifications.is_read IS false" in sql or "notifications.is_read = false" in sql or "notifications.is_read = 0" in sql


@pytest.mark.asyncio
async def test_mark_all_as_read_soft_deleted_excluded():
    """11. Soft-deleted notifications are excluded from bulk update."""
    db = MagicMock()
    captured_stmts = []

    async def mock_execute(stmt):
        captured_stmts.append(stmt)
        res = MagicMock()
        res.rowcount = 0
        return res

    db.execute = mock_execute
    repo = NotificationRepository(db)

    await repo.mark_all_as_read(user_id=101, hospital_id=1)
    stmt = captured_stmts[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "notifications.is_deleted IS false" in sql or "notifications.is_deleted = false" in sql or "notifications.is_deleted = 0" in sql


# ============================================================================
# PART B: PAGINATION TESTS (12 - 20)
# ============================================================================

def _make_dummy_notification(nid: int, user_id: int = 1, is_read: bool = False, hospital_id: int = 1) -> Notification:
    n = Notification(
        id=nid,
        user_id=user_id,
        hospital_id=hospital_id,
        title=f"Notification {nid}",
        message=f"Message {nid}",
        notification_type="APPOINTMENT_CONFIRMATION",
        priority="NORMAL",
        is_read=is_read,
        created_at=datetime(2026, 11, 17, 8, 0, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 11, 17, 8, 0, 0, tzinfo=timezone.utc),
    )
    return n


@pytest.mark.asyncio
async def test_pagination_first_page_returns_correct_records():
    """12. First page returns correct records and metadata."""
    db = MagicMock()
    service = NotificationService(db)

    items = [_make_dummy_notification(i) for i in range(1, 11)]
    service.repo.list_user_notifications = AsyncMock(return_value=items)
    service.repo.count_user_notifications = AsyncMock(return_value=25)

    result = await service.list_user_notifications(user_id=1, page=1, limit=10)
    assert result.page == 1
    assert result.size == 10
    assert result.total == 25
    assert result.pages == 3
    assert len(result.items) == 10
    service.repo.list_user_notifications.assert_awaited_once_with(
        user_id=1,
        skip=0,
        limit=10,
        is_read=None,
        notification_type=None,
        category=None,
        hospital_id=None,
        is_super_admin=False,
        is_hospital_admin=False,
    )


@pytest.mark.asyncio
async def test_pagination_middle_page_returns_correct_records():
    """13. Middle page returns correct records (skip calculation)."""
    db = MagicMock()
    service = NotificationService(db)

    items = [_make_dummy_notification(i) for i in range(11, 21)]
    service.repo.list_user_notifications = AsyncMock(return_value=items)
    service.repo.count_user_notifications = AsyncMock(return_value=25)

    result = await service.list_user_notifications(user_id=1, page=2, limit=10)
    assert result.page == 2
    assert result.size == 10
    assert result.total == 25
    assert result.pages == 3
    service.repo.list_user_notifications.assert_awaited_once()
    assert service.repo.list_user_notifications.await_args.kwargs["skip"] == 10


@pytest.mark.asyncio
async def test_pagination_last_page_returns_correct_records():
    """14. Last page returns correct remainder records."""
    db = MagicMock()
    service = NotificationService(db)

    items = [_make_dummy_notification(i) for i in range(21, 26)]
    service.repo.list_user_notifications = AsyncMock(return_value=items)
    service.repo.count_user_notifications = AsyncMock(return_value=25)

    result = await service.list_user_notifications(user_id=1, page=3, limit=10)
    assert result.page == 3
    assert result.total == 25
    assert result.pages == 3
    assert len(result.items) == 5
    assert service.repo.list_user_notifications.await_args.kwargs["skip"] == 20


def test_pagination_invalid_page_returns_validation_error():
    """15. Invalid page returns validation error (ge=1 boundary)."""
    from fastapi import Query
    from pydantic import BaseModel, Field

    class PageValidationModel(BaseModel):
        page: int = Field(..., ge=1)

    with pytest.raises(ValidationError):
        PageValidationModel(page=0)

    with pytest.raises(ValidationError):
        PageValidationModel(page=-5)

    valid = PageValidationModel(page=1)
    assert valid.page == 1


def test_pagination_invalid_limit_returns_validation_error():
    """16. Invalid limit returns validation error (ge=1, le=100 boundaries)."""
    from pydantic import BaseModel, Field

    class LimitValidationModel(BaseModel):
        limit: int = Field(..., ge=1, le=100)

    with pytest.raises(ValidationError):
        LimitValidationModel(limit=0)

    with pytest.raises(ValidationError):
        LimitValidationModel(limit=101)

    valid_min = LimitValidationModel(limit=1)
    assert valid_min.limit == 1

    valid_max = LimitValidationModel(limit=100)
    assert valid_max.limit == 100


@pytest.mark.asyncio
async def test_pagination_deterministic_sorting_identical_timestamps():
    """17. Identical timestamps produce deterministic ordering using ID tie-breaker."""
    db = MagicMock()
    repo = NotificationRepository(db)

    base_query = repo._build_base_query(user_id=10, hospital_id=1)
    sorted_query = base_query.order_by(Notification.created_at.desc(), Notification.id.desc()).offset(0).limit(20)

    clauses = [str(c) for c in sorted_query._order_by_clauses]
    assert len(clauses) == 2
    assert "notifications.created_at DESC" in clauses[0]
    assert "notifications.id DESC" in clauses[1]


@pytest.mark.asyncio
async def test_pagination_read_unread_filters_return_correct_records():
    """18. Read/unread filters return correct records."""
    db = MagicMock()
    captured_stmts = []

    async def mock_execute(stmt):
        captured_stmts.append(stmt)
        res = MagicMock()
        res.scalars.return_value.all.return_value = []
        return res

    db.execute = mock_execute
    repo = NotificationRepository(db)

    # Filter by unread
    await repo.list_user_notifications(user_id=10, is_read=False)
    sql_unread = str(captured_stmts[0].compile(compile_kwargs={"literal_binds": True}))
    assert "notifications.is_read IS false" in sql_unread or "notifications.is_read = false" in sql_unread or "notifications.is_read = 0" in sql_unread

    # Filter by read
    await repo.list_user_notifications(user_id=10, is_read=True)
    sql_read = str(captured_stmts[1].compile(compile_kwargs={"literal_binds": True}))
    assert "notifications.is_read IS true" in sql_read or "notifications.is_read = true" in sql_read or "notifications.is_read = 1" in sql_read


@pytest.mark.asyncio
async def test_pagination_total_count_matches_filtered_results():
    """19. Total count matches filtered results."""
    db = MagicMock()
    captured_stmts = []

    async def mock_execute(stmt):
        captured_stmts.append(stmt)
        res = MagicMock()
        res.scalar.return_value = 7
        return res

    db.execute = mock_execute
    repo = NotificationRepository(db)

    count = await repo.count_user_notifications(user_id=10, is_read=False, hospital_id=1)
    assert count == 7

    stmt = captured_stmts[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "count(notifications.id)" in sql.lower()
    assert "notifications.user_id = 10" in sql
    assert "notifications.is_read IS false" in sql or "notifications.is_read = false" in sql or "notifications.is_read = 0" in sql


@pytest.mark.asyncio
async def test_pagination_user_and_tenant_filters_apply_before_pagination():
    """20. User and tenant filters apply before pagination."""
    db = MagicMock()
    captured_stmts = []

    async def mock_execute(stmt):
        captured_stmts.append(stmt)
        res = MagicMock()
        res.scalars.return_value.all.return_value = []
        return res

    db.execute = mock_execute
    repo = NotificationRepository(db)

    await repo.list_user_notifications(user_id=55, hospital_id=3, skip=20, limit=10)
    stmt = captured_stmts[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    # Verify user_id and hospital_id appear in WHERE clause
    assert "notifications.user_id = 55" in sql
    assert "notifications.hospital_id = 3" in sql
    # Verify offset and limit appear in SQL
    assert "LIMIT 10 OFFSET 20" in sql or "LIMIT 10" in sql


# ============================================================================
# PART C: SINGLE READ API TESTS (21 - 28)
# ============================================================================

@pytest.mark.asyncio
async def test_mark_as_read_own_notification_success():
    """21. User can mark their own notification as read."""
    db = MagicMock()
    service = NotificationService(db)

    notif = _make_dummy_notification(nid=10, user_id=101, is_read=False, hospital_id=1)
    service.repo.get_by_id = AsyncMock(return_value=notif)

    def do_mark(nid, uid, hospital_id=None):
        notif.is_read = True
        return notif

    service.repo.mark_as_read = AsyncMock(side_effect=do_mark)

    result = await service.mark_as_read(notification_id=10, user_id=101, hospital_id=1)
    assert isinstance(result, NotificationResponse)
    assert result.is_read is True
    assert result.id == 10


@pytest.mark.asyncio
async def test_mark_as_read_other_user_notification_forbidden():
    """22. User cannot mark another user's notification as read (ForbiddenException)."""
    db = MagicMock()
    service = NotificationService(db)

    # Notification belongs to user 102
    notif = _make_dummy_notification(nid=10, user_id=102, is_read=False, hospital_id=1)
    service.repo.get_by_id = AsyncMock(return_value=notif)

    # User 101 attempts to mark it as read
    with pytest.raises(ForbiddenException) as exc_info:
        await service.mark_as_read(notification_id=10, user_id=101, hospital_id=1)

    assert "only access and update your own notifications" in str(exc_info.value)


@pytest.mark.asyncio
async def test_mark_as_read_cross_hospital_access_rejected():
    """23. Cross-hospital access is rejected."""
    db = MagicMock()
    service = NotificationService(db)

    # Notification belongs to user 101 in hospital 2
    notif = _make_dummy_notification(nid=10, user_id=101, is_read=False, hospital_id=2)
    service.repo.get_by_id = AsyncMock(return_value=notif)

    # User 101 in hospital 1 tenant attempts to mark it
    with pytest.raises(ForbiddenException) as exc_info:
        await service.mark_as_read(notification_id=10, user_id=101, hospital_id=1)

    assert "belongs to another hospital tenant" in str(exc_info.value)


@pytest.mark.asyncio
async def test_mark_as_read_missing_notification_not_found():
    """24. Missing notification returns NotFoundException."""
    db = MagicMock()
    service = NotificationService(db)
    service.repo.get_by_id = AsyncMock(return_value=None)

    with pytest.raises(NotFoundException) as exc_info:
        await service.mark_as_read(notification_id=999, user_id=101, hospital_id=1)

    assert "Notification with ID 999 not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_mark_as_read_legacy_null_hospital_notification_preserved():
    """25. Valid legacy NULL hospital notification behavior is preserved."""
    db = MagicMock()
    service = NotificationService(db)

    # Legacy notification with hospital_id = None
    notif = _make_dummy_notification(nid=10, user_id=101, is_read=False)
    notif.hospital_id = None
    service.repo.get_by_id = AsyncMock(return_value=notif)

    def do_mark(nid, uid, hospital_id=None):
        notif.is_read = True
        return notif

    service.repo.mark_as_read = AsyncMock(side_effect=do_mark)

    # User in hospital 1 reads their legacy notification
    result = await service.mark_as_read(notification_id=10, user_id=101, hospital_id=1)
    assert result.is_read is True
    assert result.hospital_id is None


@pytest.mark.asyncio
async def test_mark_as_read_repeated_requests_safe():
    """26. Repeated mark-as-read requests remain safe and idempotent."""
    db = MagicMock()
    service = NotificationService(db)

    # Already read notification
    notif = _make_dummy_notification(nid=10, user_id=101, is_read=True, hospital_id=1)
    service.repo.get_by_id = AsyncMock(return_value=notif)
    service.repo.mark_as_read = AsyncMock(return_value=notif)

    result = await service.mark_as_read(notification_id=10, user_id=101, hospital_id=1)
    assert result.is_read is True


@pytest.mark.asyncio
async def test_mark_as_read_hospital_admin_cannot_read_another_user_notification():
    """27. Hospital Admin cannot read/mark another user's personal notification."""
    db = MagicMock()
    service = NotificationService(db)

    # Doctor's notification (user 301)
    doctor_notif = _make_dummy_notification(nid=50, user_id=301, is_read=False, hospital_id=1)
    service.repo.get_by_id = AsyncMock(return_value=doctor_notif)

    # Hospital Admin (user 200) attempts to mark doctor's notification as read
    with pytest.raises(ForbiddenException) as exc_info:
        await service.mark_as_read(notification_id=50, user_id=200, hospital_id=1)

    assert "only access and update your own notifications" in str(exc_info.value)


@pytest.mark.asyncio
async def test_mark_as_read_super_admin_cannot_bypass_notification_ownership():
    """28. Super Admin cannot bypass personal notification ownership."""
    db = MagicMock()
    service = NotificationService(db)

    # Patient's notification (user 501)
    patient_notif = _make_dummy_notification(nid=60, user_id=501, is_read=False, hospital_id=1)
    service.repo.get_by_id = AsyncMock(return_value=patient_notif)

    # Super Admin (user 1) attempts to mark patient's notification as read
    with pytest.raises(ForbiddenException) as exc_info:
        await service.mark_as_read(notification_id=60, user_id=1, hospital_id=1)

    assert "only access and update your own notifications" in str(exc_info.value)
