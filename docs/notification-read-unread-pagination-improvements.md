# NexaCare HMS — Notification Read/Unread, Mark All as Read & Pagination Improvements

**Repository:** `C:\Users\Admin\Desktop\NexaCare-Backend`  
**Branch:** `tejas-feature`  
**Date:** November 17, 2026  
**Status:** Completed & Fully Verified  

---

## 1. Existing Defects Discovered

### A. High-Severity Cross-User Bulk Update in `mark_all_as_read()`
In `NotificationRepository.mark_all_as_read()`, the queries for `Hospital Admin` and `Super Admin` contained a critical scoping vulnerability:
- **Hospital Admin Branch:** Executed `UPDATE notifications ... WHERE (hospital_id = :hospital_id OR user_id = :user_id) AND is_read = False`.
- **Super Admin Branch:** Executed `UPDATE notifications ... WHERE hospital_id = :hospital_id AND is_read = False`.
- **Impact:** When any Hospital Admin clicked "Mark all as read" in their personal notification bell, every unread notification across the entire hospital (including alerts for doctors, nurses, pharmacists, and accountants) was immediately marked as read. This destroyed unread counters and silenced active clinical alerts for all hospital staff.

### B. Non-Deterministic Pagination Ordering
In `NotificationRepository.list_user_notifications()`, pagination sorting used only:
- `query.order_by(Notification.created_at.desc()).offset(skip).limit(limit)`
- **Impact:** In MySQL/InnoDB, sorting on non-unique timestamps without a secondary tie-breaker causes non-deterministic row ordering across offset page boundaries. Notifications generated in batch within the same second shifted across pages, causing duplicate entries on consecutive pages or skipping records entirely.

### C. Missing Tenant Scoping in Single Read API
`NotificationService.mark_as_read()` and `NotificationRepository.mark_as_read()` only validated `notification.user_id == user_id`, omitting `hospital_id` validation:
- **Impact:** In multi-tenant environments where users or administrators navigate across tenant contexts, cross-hospital access was not strictly checked.

---

## 2. Root Cause of Cross-User Bulk Update

The notification repository originally conflated two distinct architectural concepts:
1. **Administrative Viewing Scoping (`_build_base_query`):** Where an admin may view hospital-wide notification events.
2. **Personal Inbox State Mutation (`mark_all_as_read`):** The notification bell UI is personal to the logged-in user. Even for an administrator, marking notifications as read must only acknowledge notifications addressed to that specific user.

Because `mark_all_as_read()` copied the administrative `hospital_id` filter from `_build_base_query()`, it converted a personal read-status update into a hospital-wide bulk update.

---

## 3. Mark All as Read Correction

In `app/repositories/notification_repository.py`:
- Removed the separate `is_super_admin` and `is_hospital_admin` branches in `mark_all_as_read()`.
- Standardized the update statement across all user roles to strictly require `Notification.user_id == user_id`:

```python
stmt = (
    update(Notification)
    .where(
        Notification.user_id == user_id,
        Notification.is_read.is_(False),
        Notification.is_deleted.is_(False),
    )
    .values(is_read=True, updated_at=utc_now())
)
if hospital_id is not None:
    stmt = stmt.where(
        or_(
            Notification.hospital_id == hospital_id,
            Notification.hospital_id.is_(None),
        )
    )
result = await self.db.execute(stmt)
return result.rowcount
```

### Security Properties
- **Zero Cross-User Blast Radius:** Only records matching `user_id == caller_id` are updated.
- **Role Isolation:** Hospital Admin and Super Admin accounts now only update their own notifications. Doctors' and nurses' notifications remain completely untouched.
- **Idempotency:** Only updates rows where `is_read == False`. Subsequent requests find 0 unread rows and return `updated_count: 0`.
- **Soft-Delete Safety:** Excludes soft-deleted notifications (`is_deleted == False`).
- **Legacy Compatibility:** Preserves legacy notifications where `hospital_id IS NULL`.

---

## 4. Pagination Sorting Correction

In `app/repositories/notification_repository.py`:
- Added a deterministic secondary unique sort tie-breaker to `list_user_notifications()`:

```python
query = query.order_by(Notification.created_at.desc(), Notification.id.desc()).offset(skip).limit(limit)
```

### Determinism Guarantee
- `created_at.desc()` sorts newest notifications first.
- `id.desc()` acts as a unique tie-breaker for notifications sharing identical millisecond timestamps.
- Completely eliminates page jitter, skipping, or duplicate rows across offset boundaries.
- Preserves existing offset/limit pagination, filtering, total count calculation, and `PaginatedResult` response schema.

---

## 5. Single-Read Tenant Hardening

In `app/api/v1/routes/notification_routes.py`:
- Resolved tenant ID from authenticated context: `hospital_id = resolve_tenant_id(current_user)`.
- Passed `hospital_id` to `NotificationService.mark_as_read()`.

In `app/services/notification_service.py` & `app/repositories/notification_repository.py`:
- Added tenant validation to `mark_as_read(notification_id, user_id, hospital_id=None)`:

```python
if (
    hospital_id is not None
    and notification.hospital_id is not None
    and notification.hospital_id != hospital_id
):
    raise ForbiddenException("Access denied: Notification belongs to another hospital tenant")
```

### Tenant Protection Properties
- Rejects cross-hospital attempts with HTTP 403 `ForbiddenException`.
- Preserves access to legacy notifications where `hospital_id IS NULL`.
- Rejects access to other users' notifications (`user_id != caller_id`).
- Returns HTTP 404 `NotFoundException` if notification does not exist.

---

## 6. API Compatibility & Response Formats

All changes are 100% backward-compatible:
- `GET /api/v1/notifications`: Continues returning `APIResponse[PaginatedResult[NotificationResponse]]`.
- `PATCH /api/v1/notifications/{notification_id}/read`: Continues returning `APIResponse[NotificationResponse]`.
- `PATCH /api/v1/notifications/read-all`: Continues returning `APIResponse[dict[str, Any]]` with `{"message": "All notifications marked as read", "updated_count": count}`.
- `GET /api/v1/notifications/unread-count`: Unaffected, continues returning `APIResponse[UnreadCountResponse]`.
- All method signatures preserve default parameter compatibility (`hospital_id: int | None = None`, `is_super_admin: bool = False`, `is_hospital_admin: bool = False`).

---

## 7. Database & Migration Safety

- **Zero Migrations:** No Alembic migrations created.
- **Zero Schema Changes:** The `is_read`, `hospital_id`, `created_at`, `user_id`, and `is_deleted` columns already exist in MySQL table `notifications`.
- **Zero Live DB Access:** All targeted tests run in isolated unit fixtures; real-session regression tests run in rollback savepoints.
- **Index Utilization:** Queries leverage existing indexes on `(user_id)`, `(hospital_id)`, `(is_read)`, `(created_at)`, and primary key `(id)`.

---

## 8. Test Suite Implementation

A dedicated test suite was implemented in `app/tests/test_notification_read_mark_all_pagination.py` containing 28 comprehensive tests:

### Part A: Mark All as Read Tests (11 tests)
1. `test_mark_all_as_read_own_notifications_updated`: Ordinary user updates only their own notifications.
2. `test_mark_all_as_read_other_users_remain_unread`: Other users' unread records remain untouched.
3. `test_mark_all_as_read_hospital_admin_only_updates_own`: Hospital Admin only updates their own notifications.
4. `test_mark_all_as_read_hospital_admin_cannot_clear_doctors`: Doctor notifications are not cleared by Hospital Admin.
5. `test_mark_all_as_read_hospital_admin_cannot_clear_nurses`: Nurse notifications are not cleared by Hospital Admin.
6. `test_mark_all_as_read_super_admin_only_updates_own`: Super Admin only updates their own notifications.
7. `test_mark_all_as_read_cross_hospital_notifications_untouched`: Scoped hospital updates exclude other hospitals.
8. `test_mark_all_as_read_repeated_requests_idempotent`: Consecutive calls return `updated_count: 0`.
9. `test_mark_all_as_read_empty_notification_list`: User with 0 unread alerts returns `updated_count: 0`.
10. `test_mark_all_as_read_already_read_remain_unchanged`: Only unread notifications are matched.
11. `test_mark_all_as_read_soft_deleted_excluded`: Soft-deleted records are excluded.

### Part B: Pagination Tests (9 tests)
12. `test_pagination_first_page_returns_correct_records`: Validates `page=1, size=10, total=25, pages=3`.
13. `test_pagination_middle_page_returns_correct_records`: Validates `page=2, skip=10`.
14. `test_pagination_last_page_returns_correct_records`: Validates `page=3, skip=20, items=5`.
15. `test_pagination_invalid_page_returns_validation_error`: Validates `ge=1` validation.
16. `test_pagination_invalid_limit_returns_validation_error`: Validates `ge=1, le=100` validation.
17. `test_pagination_deterministic_sorting_identical_timestamps`: Verifies `(created_at.desc(), id.desc())`.
18. `test_pagination_read_unread_filters_return_correct_records`: Validates `is_read=True` and `is_read=False`.
19. `test_pagination_total_count_matches_filtered_results`: Validates count query matches list query filters.
20. `test_pagination_user_and_tenant_filters_apply_before_pagination`: Validates user and tenant scoping before pagination.

### Part C: Single Read API Tests (8 tests)
21. `test_mark_as_read_own_notification_success`: User marks their own alert as read.
22. `test_mark_as_read_other_user_notification_forbidden`: Cross-user read raises `ForbiddenException`.
23. `test_mark_as_read_cross_hospital_access_rejected`: Cross-hospital read raises `ForbiddenException`.
24. `test_mark_as_read_missing_notification_not_found`: Non-existent ID raises `NotFoundException`.
25. `test_mark_as_read_legacy_null_hospital_notification_preserved`: Legacy alerts (`hospital_id=None`) readable by owner.
26. `test_mark_as_read_repeated_requests_safe`: Repeated single reads return `is_read=True` safely.
27. `test_mark_as_read_hospital_admin_cannot_read_another_user_notification`: Hospital Admin cannot read doctor alerts.
28. `test_mark_as_read_super_admin_cannot_bypass_notification_ownership`: Super Admin cannot read patient alerts.

---

## 9. Test Execution Evidence

| Test Suite | Command | Result | Duration |
| :--- | :--- | :---: | :---: |
| **New Targeted Tests** | `pytest app/tests/test_notification_read_mark_all_pagination.py -v` | **28 passed** | 0.74s |
| **Baseline Workflow Improvements** | `pytest app/tests/test_notification_improvements.py -v` | **73 passed** | 5.10s |
| **Real Session Savepoint Tests** | `pytest app/tests/test_notification_savepoint_real_session.py -v` | **5 passed** | 5.12s |
| **Combined Notification Suite** | `pytest app/tests/test_notification_read_mark_all_pagination.py app/tests/test_notification_improvements.py app/tests/test_notification_savepoint_real_session.py -v` | **106 passed** | 10.10s |
| **Notification E2E Tests** | `pytest app/tests/test_notifications_e2e.py -v` | **3 passed** | 30.31s |
| **Domain Regression Suite (Appointments, Discharges, Lab, Nursing)** | `pytest app/tests/test_appointment_admission_status_filter.py app/tests/test_appointment_calendar_scoping.py app/tests/test_appointment_dashboard_export.py app/tests/test_appointment_excel_formula_injection.py app/tests/test_discharge_active_summary.py app/tests/test_lab.py app/tests/test_nurse_shifts.py -v` | **70 passed** | 14.04s |

---

## 10. Security & Regression Verification Summary

1. **Tenant Isolation:** Fully verified. All updates and reads enforce `Notification.user_id == user_id` and `notification.hospital_id == hospital_id` (or `None`).
2. **Transaction Safety:** SQLAlchemy `AsyncSession` transactions are clean; all bulk updates operate within the request's transaction block without premature commits.
3. **No Unrelated Modifications:** Working tree preserves the developer's pre-existing Swagger CDN changes in `app/main.py` without modification.
4. **Formatting:** `git diff --check HEAD` confirms zero whitespace errors, clean line breaks, and proper Python formatting.

---

## 11. Known Limitations

- **Offset Pagination Shifting:** As with any offset-based pagination system on live streams, if dozens of new notifications are ingested simultaneously while a user pages backwards, slight record shifting can occur. This is standard and expected for offset pagination.
- **Notifications with `hospital_id IS NULL`:** Legacy records created prior to multi-tenant migrations remain readable only by the owning `user_id`.

---

## 12. Final Production Readiness Assessment

All three notification enhancements (Read/Unread Tracking, Mark All as Read, and Deterministic Pagination) are **fully implemented, hardened, and verified**.

# `READY FOR MANUAL COMMIT`
