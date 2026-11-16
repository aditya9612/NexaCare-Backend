# NexaCare HMS — Low-Risk Notification Workflows Implementation

**Repository:** `C:\Users\Admin\Desktop\NexaCare-Backend`  
**Branch:** `tejas-feature`  
**Baseline HEAD:** `87dc3bf`  
**Execution Date:** November 16, 2026  

---

## 1. Overview

This document records the design, implementation, tenant security architecture, and test verification for the three remaining low-risk notification workflows in the NexaCare Hospital Management System backend:

1. **Discharge Billing Cleared → Attending Doctor Notification**
2. **Lab Sample Rejection → Doctor + Patient Notification**
3. **Staff Onboarding Welcome Notification**

Additionally, the previously implemented and approved **Appointment No-Show Notification** workflow was preserved, protected, and fully verified across all regression test suites.

---

## 2. Detailed Workflow Specifications

### Workflow A: Discharge Billing Cleared → Attending Doctor
- **Event Trigger:** `DischargeService.clear_billing()`. Triggers exclusively on genuine transition when `was_billing_cleared is False and discharge.billing_cleared is True` after the database repository update has completed.
- **Recipient:** Attending Doctor's linked User account (`discharge.doctor_id` -> `doctor.user_id`).
- **Notification Type:** `DISCHARGE_BILLING_CLEARED`
- **Reference Type & ID:** `reference_type="DISCHARGE"`, `reference_id=discharge.id`
- **Priority:** `NORMAL`
- **Duplicate Prevention:** Standard 600-second window scoped by `(user_id, notification_type, reference_type, reference_id)`.
- **Tenant Isolation:**
  - `discharge.hospital_id is not None`
  - `doctor = await db.get(Doctor, discharge.doctor_id)` with `doctor.hospital_id == discharge.hospital_id`
  - `doctor.user_id is not None`
  - Linked User active and tenant-matched:
    `select(User.is_active).where(User.id == doctor.user_id, User.hospital_id == discharge.hospital_id)`
  - Fails closed (`return`) on any missing record, tenant mismatch, or inactive user.
- **Payload:**
  - Title: `"Billing Clearance Completed"`
  - Message: `"Billing clearance for patient {patient_name} (Discharge #{discharge_number}) has been completed by the accounts department."`
  - Email HTML: Formal clearance summary confirming patient, doctor, discharge number, and status.
- **Failure Safety:** Enclosed in localized `try/except Exception`. Dispatches non-blocking warning log on network or socket failure; never aborts or rolls back successful billing clearance.

---

### Workflow B: Lab Sample Rejection → Doctor + Patient
- **Event Trigger:** `LabService.update_sample()`. Triggers exclusively on genuine transition when `was_rejected is False and new_status == "rejected"` after `sample_repo.update` and audit logging.
- **Recipients:** 
  1. Attending Doctor (`order.doctor_id` -> `doctor.user_id`)
  2. Patient (`order.patient_id` -> `patient.user_id`)
- **Notification Type:** `LAB_SAMPLE_REJECTED`
- **Reference Type & ID:** `reference_type="SAMPLE"`, `reference_id=sample.id`
- **Priority:** `NORMAL`
- **Duplicate Prevention:** 600-second window applied per recipient.
- **Independent Recipient Validation:**
  - Both recipients are validated and dispatched independently. A tenant mismatch or inactive status on the doctor does not suppress the patient notification, and vice versa.
  - TestOrder must have `hospital_id is not None`.
  - Doctor check: `doctor.hospital_id == order.hospital_id` and `User.id == doctor.user_id and User.hospital_id == order.hospital_id and User.is_active is True`.
  - Patient check: `patient.hospital_id == order.hospital_id` and `User.id == patient.user_id and User.hospital_id == order.hospital_id and User.is_active is True`.
  - Missing account on either party safely skips only that recipient.
- **Payload:**
  - Title: `"Lab Sample Rejected"`
  - Doctor Message: `"Lab sample {sample_code} for order {order_number} (Patient: {patient_name}) was rejected. Please review or coordinate recollection."`
  - Patient Message: `"Your lab sample {sample_code} for order {order_number} was rejected by the laboratory. Please contact the hospital or lab reception for recollection."`
- **Failure Safety:** Each recipient dispatch is isolated in its own `try/except` block. Failure dispatching to one does not suppress the other, and sample status update is never rolled back.

---

### Workflow C: Staff Onboarding Welcome
- **Event Trigger:** `StaffService.create_staff()`. Triggers immediately after successful creation and database flush of the new `User` record, creation of the `Staff` record, and audit entry generation.
- **Recipient:** The newly created staff member's User account (`user.id`).
- **Notification Type:** `STAFF_ONBOARDING_WELCOME`
- **Reference Type & ID:** `reference_type="STAFF"`, `reference_id=staff.id`
- **Priority:** `NORMAL`
- **Tenant Isolation:**
  - `staff.hospital_id is not None` and `user.hospital_id is not None`
  - `staff.hospital_id == user.hospital_id`
  - Linked User active in tenant: `select(User.is_active).where(User.id == user.id, User.hospital_id == staff.hospital_id)`
  - Fails closed on any mismatch.
- **Critical Credential Protection:**
  - Zero passwords, temporary credentials, hashes, tokens, OTPs, or authentication secrets are exposed in the notification title, message body, email subject, or email HTML.
  - Title: `"Welcome to NexaCare"`
  - Message: `"Welcome {full_name}! Your staff profile has been created with role {role_name} and Staff Code {staff_code}."`
  - Email HTML: Welcome greeting detailing full name, staff code, role, department, and general instructions to access the staff portal using their registered email.
- **Failure Safety:** Wrapped in `try/except Exception`. Dispatches warning log on socket or dispatch failure; never aborts staff creation.

---

## 3. Security & Multi-Tenant Protection

All three implementations adhere to NexaCare's strict tenant isolation rules:

1. **Hospital-Level Scoping:** Every entity (`Discharge`, `TestOrder`, `Staff`) must have a valid non-null `hospital_id`.
2. **Linked User Verification:** Recipient users are verified via direct indexed scalar queries:
   `SELECT is_active FROM users WHERE id = :user_id AND hospital_id = :hospital_id`
3. **Active Account Enforcement:** Only accounts where `is_active is True` receive notifications. Deactivated or suspended accounts are suppressed.
4. **Credential Isolation:** The onboarding welcome workflow was audited and verified to contain zero credential or secret tokens.
5. **Deduplication:** Inherits `NotificationRepository.exists_duplicate()` with the 600-second cutoff window to prevent spamming on rapid operations.

---

## 4. Protected Existing Work

The **Appointment No-Show Notification** implementation remains fully intact and uncommitted in the working tree:
- `app/services/appointment_service.py` (`_notify_no_show_safely` with User tenant validation)
- `app/services/notification_service.py` (`notify_appointment_no_show`)
- `app/tests/test_notification_improvements.py` (12 no-show tests)

Developer's pre-existing Swagger CDN changes in `app/main.py` remain completely untouched.

---

## 5. Test Suite Verification & Results

| Test Category | Command | Result |
| :--- | :--- | :---: |
| **All Notification Improvement Tests (73 total)** | `pytest app/tests/test_notification_improvements.py -v` | **73 passed** in 5.03s |
| **New 3-Workflow Tests (31 total)** | `pytest app/tests/test_notification_improvements.py -k "discharge or sample or staff" -v` | **31 passed** in 3.51s |
| **Appointment No-Show Tests (12 total)** | `pytest app/tests/test_notification_improvements.py -k "no_show" -v` | **12 passed** in 0.83s |
| **Appointment Regression Suite (53 total)** | `pytest app/tests/test_appointment_admission_status_filter.py app/tests/test_appointment_calendar_scoping.py app/tests/test_appointment_dashboard_export.py app/tests/test_appointment_excel_formula_injection.py -v` | **53 passed** in 16.05s |
| **Discharge Active Summary Suite (5 total)** | `pytest app/tests/test_discharge_active_summary.py -v` | **5 passed** in 1.45s |
| **Lab Order & Catalog Suite (8 total)** | `pytest app/tests/test_lab.py -v` | **8 passed** in 1.81s |
| **Nurse Shifts Regression Suite (4 total)** | `pytest app/tests/test_nurse_shifts.py -v` | **4 passed** in 2.46s |
| **Real Session Savepoint Tests (5 total)** | `pytest app/tests/test_notification_savepoint_real_session.py -v` | **5 passed** in 5.12s |

---

## 6. Scope & Architectural Boundaries

- **Zero Migrations:** No database schema alterations or Alembic migrations were created.
- **Zero Live DB Access:** Tests run deterministically with mock isolation or targeted local dev session savepoints.
- **Zero Uncommitted Git Operations:** No `git add`, `git commit`, `git push`, `git reset`, or `git checkout` was performed.
- All modifications are cleanly staged in the working tree for user review.
