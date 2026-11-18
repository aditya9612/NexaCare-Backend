# NexaCare Authentication Architecture and Security Implementation Plan

> **Specification Reference**: `docs/NexaCare_Auth_Frontend_Backend_Guide_v2.pdf`  
> **Repository**: `NexaCare-Backend`  
> **Status**: Ready for Implementation  

---

## 1. Executive Summary & Goals

The NexaCare platform utilizes a **Shared Backend + Single Database** supporting three distinct user experiences:
1. **`SUPER_ADMIN`**: Global platform administrative portal.
2. **`ORGANIZATION`**: Hospital/Tenant Admin, Doctors, Nurses, Receptionists, Accountants, Pharmacists, and Lab Technicians.
3. **`PATIENT`**: Independent patient portal for appointments, lab records, prescriptions, and health queries.

### Core Objectives
1. **Server-Side Login Context Validation**: Support `login_type` (`SUPER_ADMIN`, `ORGANIZATION`, `PATIENT`). Reject role/context mismatches with `HTTP 403 Forbidden` while preserving standard `401 Unauthorized` for invalid credentials and disabled accounts.
2. **JWT Claims & Response Normalization**: Populate token claims (`role`, `role_id`, `hospital_id`) and return `role` and `user` profile in `TokenResponse` to eliminate frontend redirect ambiguity (e.g. Super Admin loading Admin dashboard).
3. **Stale Session & Access Token Revocation**: Invalidate access tokens upon logout, password change, and password reset via `user.last_logout_at`.
4. **Backend Authorization & RBAC Audit**: Close authorization gaps on administrative, financial report, discharge, and clinical record routes.
5. **Patient Data Isolation & IDOR Prevention**: Derive patient identity from server-side authenticated context; strictly prevent cross-patient and cross-hospital data tampering.
6. **Automated Regression Suite**: Add comprehensive automated tests covering all 17 security test scenarios.

---

## 2. Security Audit & Discovered Vulnerabilities

| # | Vulnerability / Issue | Target Files | Severity | Description & Fix |
|---|---|---|---|---|
| **V1** | **Missing Login Context Validation** | `app/schemas/auth_schema.py`<br>`app/services/auth_service.py` | **CRITICAL** | `POST /api/v1/auth/login` accepts any valid account regardless of portal origin. We must validate `login_type` against database `user.role.name` and reject mismatches with HTTP 403. |
| **V2** | **Omitted Token Claims & User Info in Login Response** | `app/core/security.py`<br>`app/schemas/auth_schema.py`<br>`app/services/auth_service.py` | **HIGH** | `TokenResponse` and access token JWT payloads lacked `role` and `hospital_id`. We will embed claims in JWT and include `role` and `user` in `TokenResponse`. |
| **V3** | **Unrevoked Access Tokens on Password Reset / Change** | `app/services/auth_service.py` | **MEDIUM** | Password changes revoked refresh tokens but not active access tokens. Updating `user.last_logout_at = utc_now()` immediately invalidates all active access tokens. |
| **V4** | **Clinical Records IDOR & Privilege Escalation** | `app/api/v1/routes/clinical_record_router.py`<br>`app/services/clinical_record_service.py`<br>`app/api/v1/routes/patient_routes.py` | **CRITICAL** | Patients were granted `patients:read` and `patients:update` in permissions seeding, allowing them to view/update other patients' clinical records. Must restrict CUD to clinical staff and enforce patient ownership scoping on reads. |
| **V5** | **Over-Permissive Discharge Routes** | `app/api/v1/routes/discharge_routes.py`<br>`app/services/discharge_service.py` | **HIGH** | `/discharge/initiate` and `/discharge/active` relied on `appointments:update/read`. Patients could initiate discharges or view active hospital discharge lists. We must restrict to clinical staff and enforce patient scoping. |
| **V6** | **Unprotected Admin & Financial Report Routes** | `app/api/v1/routes/admin_routes.py`<br>`app/api/v1/routes/report_routes.py` | **HIGH** | `/api/v1/admin/users`, `/admin/audit-logs`, and all `/reports/admin/...`, `/accountant/...`, `/pharmacy/...`, `/lab/...` routes only checked `CurrentUser`. Must enforce `AdminUser` or dedicated module read permissions. |
| **V7** | **Unchecked Patient Ownership in Appointment Tokens** | `app/services/appointment_service.py`<br>`app/api/v1/routes/appointment_routes.py` | **MEDIUM** | `GET /appointments/{id}/token` did not verify if the appointment belonged to the requesting patient. Must verify ownership via `_resolve_allowed_patient_ids`. |
| **V8** | **Patient Dashboard Allows Admin Bypass** | `app/core/dependencies.py`<br>`app/api/v1/routes/dashboard_routes.py` | **MEDIUM** | `require_roles(UserRole.PATIENT)` automatically allowed admin roles. We will add `allow_admin: bool = True` to support strict patient-only route isolation. |

---

## 3. Step-by-Step Implementation Plan

### Step 1: Authentication Schema & Contract (`app/schemas/auth_schema.py`)
- Define `LoginContext(str, Enum)` with values `SUPER_ADMIN`, `ORGANIZATION`, `PATIENT`.
- Add `login_type: LoginContext | str | None = None` to `LoginRequest`.
- Update `TokenResponse` to include:
  - `role: str | None = None`
  - `user: UserProfileResponse | None = None`

### Step 2: JWT Claim Enrichment (`app/core/security.py`)
- Update `create_access_token` to accept `extra_claims: Optional[dict[str, Any]] = None`.
- Populate `role`, `role_id`, and `hospital_id` in token payloads.

### Step 3: Shared Login Context Validation & Session Revocation (`app/services/auth_service.py`)
- In `login()`:
  - Authenticate credentials first; return HTTP 401 Unauthorized for invalid credentials or inactive accounts.
  - Inspect verified user's database role:
    - If `login_type == "SUPER_ADMIN"`: require `user.role.name == UserRole.SUPER_ADMIN`. Mismatch -> 403 Forbidden.
    - If `login_type == "ORGANIZATION"`: require `user.role.name` in organization roles (`Hospital Admin`, `Doctor`, `Nurse`, `Receptionist`, `Accountant`, `Pharmacist`, `Lab Technician`). Mismatch -> 403 Forbidden.
    - If `login_type == "PATIENT"`: require `user.role.name == UserRole.PATIENT`. Mismatch -> 403 Forbidden.
- In `_issue_tokens()`:
  - Embed claims (`role`, `role_id`, `hospital_id`).
  - Return `TokenResponse` with `role` and `user: UserProfileResponse`.
- In `change_password()` & `reset_password()`:
  - Update `user.last_logout_at = utc_now()` to immediately revoke all outstanding access tokens.

### Step 4: Strict Role Dependencies (`app/core/dependencies.py`)
- Add `allow_admin: bool = True` parameter to `require_roles`.
- When `allow_admin=False`, ensure only exact listed roles are permitted.

### Step 5: Admin & Report Route Protections (`app/api/v1/routes/`)
- In `admin_routes.py`: Protect `/users` and `/audit-logs` with `AdminUser`.
- In `report_routes.py`:
  - Protect `/admin/...` with `AdminUser`.
  - Protect `/accountant/...` with `require_permission("billing", "read")`.
  - Protect `/pharmacy/...` with `require_permission("pharmacy", "read")`.
  - Protect `/lab/...` with `require_permission("lab", "read")`.
- In `dashboard_routes.py`: Enforce `require_roles(UserRole.PATIENT, allow_admin=False)` on `GET /dashboard/patient`.

### Step 6: Patient Data Isolation & IDOR Fixes
- In `clinical_record_router.py`: Restrict create/update/delete to doctors/admins; scope reads to `allowed_patient_ids`.
- In `patient_routes.py`: In `list_patient_clinical_records`, verify patient access ownership before fetching.
- In `discharge_routes.py`: Restrict `/discharge/initiate` to doctors/admins; restrict `/discharge/active` to staff; scope individual discharge reads to `allowed_patient_ids`.
- In `appointment_service.py`: Enforce patient ownership in `get_token`.

### Step 7: Automated Test Suite (`app/tests/test_auth_architecture_security.py`)
Cover all 17 required scenarios:
1. Valid Super Admin login.
2. Valid Organization Admin login.
3. Valid Doctor, Receptionist, and Staff login.
4. Valid Patient login.
5. Super Admin attempting ORGANIZATION login -> 403 Forbidden.
6. Patient attempting ORGANIZATION login -> 403 Forbidden.
7. Organization account attempting PATIENT login -> 403 Forbidden.
8. Non-Super Admin attempting SUPER_ADMIN login -> 403 Forbidden.
9. Invalid credentials & disabled accounts -> 401 Unauthorized.
10. Invalid / unknown role handling.
11. Correct JWT claims & populated `TokenResponse`.
12. Refresh-token & logout revocation behavior.
13. Patient accessing another patient's records -> 403/404.
14. Patient accessing staff/admin-only APIs -> 403 Forbidden.
15. Cross-hospital access attempts.
16. Unauthorized direct API requests without valid token -> 401.
17. Backward compatibility for legacy logins without `login_type`.
