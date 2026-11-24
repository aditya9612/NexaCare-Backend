# 02 FILE-WISE TECHNICAL CHANGE HISTORY

**Audit Title:** Detailed Technical Justification for Every Application Code Modification
**Target Repository:** `C:\Users\Admin\Desktop\NexaCare-Backend`
**Current Branch:** `tejas-feature`
**Execution Timestamp:** 2026-11-23T21:12:00+05:30

---

## 1. Core Framework & Database Engine

### 1. `alembic/env.py` (+42, -0)
- **Previous Behavior:** During offline migration (`alembic upgrade head --sql`), Alembic threw `sqlalchemy.exc.NoInspectionAvailable: No inspection system is available for object of type MockConnection` and crashed with exit code 1 because 17 historical migrations dynamically call `sa.inspect(bind)` or `Inspector.from_engine(conn)`.
- **New Behavior:** Defines inline `_OfflineMockInspector` and `_MockResult` reflection stubs scoped inside `run_migrations_offline()`. In offline mode, inspect calls return safe empty collections; in online mode, standard MySQL reflection runs untouched.
- **Reason:** Enables zero-database offline DDL generation and static SQL schema verification without mutating historical migration scripts.
- **Security & Business Impact:** Ensures predictable schema migrations in production CI/CD pipelines.
- **Verification:** Verified via `alembic upgrade head --sql` (exit code 0) and `alembic upgrade head` (online upgrade to head `b8a7c6d5e4f3`).

### 2. `app/core/dependencies.py` (+237, -8)
- **Previous Behavior:** Allowed fallback to query parameter `hospital_id` or default Hospital 1 if not present in the user token. Failed to enforce fail-closed checks on hospital module entitlements.
- **New Behavior:** Introduced `TenantWriteHospitalId`, `resolve_tenant_write_id`, and `require_module_enabled`. Context resolution strictly prioritizes verified JWT claims and rejects untrusted client header/query overrides. Returns `HTTP 403 Forbidden` if the module is disabled for the tenant.
- **Reason:** Primary fix for SEC-01 through SEC-08 (IDOR and cross-tenant data tampering).
- **Security & Business Impact:** Enforces non-bypassable 5-stage authorization across all 323 mutating endpoints.
- **Verification:** Verified via `scratch/test_phase6d_route_wiring.py` (18 tests) and `scratch/test_multi_hospital_staging.py` (10 tests).

### 3. `app/core/config.py` (+1, -1)
- **Previous Behavior:** `ENABLE_DEV_RBAC_SEED` was not parameterized or defaulted to active.
- **New Behavior:** Enforces `ENABLE_DEV_RBAC_SEED: bool = False` by default.
- **Reason:** Prevents accidental re-seeding or exposure of test RBAC endpoints in production environments.
- **Security & Business Impact:** Closes unauthenticated / dev seed route security risk.
- **Verification:** Verified via `test_master_production_readiness.py`.

### 4. `app/core/database.py` (+1, -5)
- **Previous Behavior:** Startup lifespan had ambiguity around password resync for the Super Admin and test users.
- **New Behavior:** Hardened `_seed_default_super_admin` to disable password resynchronization in production (`allow_resync = False` when `APP_ENV=production`). Verified `_seed_nurse_adesh` is excluded from application startup.
- **Reason:** Prevents silent password overwrites of existing administrative accounts on application boot.
- **Security & Business Impact:** Ensures credential immutability and compliance.
- **Verification:** Verified via source code audit and `scratch/verify_db_permissions.py`.

### 5. `app/main.py` (+42, -2)
- **Previous Behavior:** Static file mounts exposed branding directories indiscriminately without explicit boundary documentation. Lifespan lacked graceful Redis Pub/Sub cleanup.
- **New Behavior:** Explicitly segregates public branding assets (`/uploads/branding`, `/uploads/hospitals`, `/uploads/doctors`) from sensitive clinical files (`uploads/patients/`, `uploads/secure/`), which are strictly routed through authenticated APIs. Added graceful shutdown for Redis Pub/Sub listener and database engine disposal.
- **Reason:** Prevents unauthenticated direct URL access to patient clinical documents.
- **Security & Business Impact:** HIPAA / DPDP Act compliance on medical document access.
- **Verification:** Verified via live Uvicorn socket smoke test (`scratch/test_live_server_and_load.py`).

---

## 2. API Domain Routes (21 Files)

### 6. `app/api/v1/routes/appointment_routes.py` (+35, -7)
- **Change:** Injected `TenantWriteHospitalId` into POST/PUT/PATCH/DELETE handlers. Removed client-controlled hospital IDs in booking and reschedule payloads.
- **Reason:** Fixed appointment IDOR vulnerability where users could schedule appointments in foreign hospitals.
- **Tests:** `test_phase6d_route_wiring.py`, `test_mysql_real_db_concurrency.py`.

### 7. `app/api/v1/routes/bed_allocation_routes.py` (+42, -14)
- **Change:** Enforced hospital tenant context on bed allocation, room creation, and inpatient admission endpoints.
- **Reason:** Prevented cross-tenant bed assignment where a patient in Hospital A was admitted to a bed in Hospital B.
- **Tests:** `test_phase6d_route_wiring.py`, `test_bed_allocation_logic.py`.

### 8. `app/api/v1/routes/billing_routes.py` (+22, -8)
- **Change:** Removed query parameter fallback `hospital_id: Optional[int] = 1`. Invoices now strictly bind to `current_user.hospital_id`.
- **Reason:** Fixed SEC-04 (Billing fallback to Hospital 1).
- **Tests:** `test_phase7_route_dispatch.py`, `test_daily_billing_report.py`.

### 9. `app/api/v1/routes/chat_routes.py` (+1, -1)
- **Change:** Scoped AI chat session creation to session user's hospital context; rejected body `hospital_id` override.
- **Reason:** Fixed SEC-11 (AI Chat body override).
- **Tests:** `test_chat_hospital_scope.py`.

### 10. `app/api/v1/routes/clinical_record_router.py` (+20, -4)
- **Change:** Replaced manual hospital parameters with `TenantWriteHospitalId`. Added doctor-patient hospital binding.
- **Reason:** Fixed SEC-06 (Clinical record cross-hospital update/delete).
- **Tests:** `test_phase8_residual_remediation.py`, `test_clinical_document_ownership.py`.

### 11. `app/api/v1/routes/department_routes.py` (+10, -2)
- **Change:** Scoped department creation, head-of-department assignments, and service catalog to authenticated tenant.
- **Reason:** Multi-tenant department isolation.
- **Tests:** `test_phase7_route_dispatch.py`.

### 12. `app/api/v1/routes/discharge_routes.py` (+22, -18)
- **Change:** Enforced `TenantWriteHospitalId` on discharge approvals and active discharge summary creation.
- **Reason:** Prevents unauthorized discharge approvals across hospital tenants.
- **Tests:** `test_discharge_active_summary.py`.

### 13. `app/api/v1/routes/doctor_routes.py` (+15, -3)
- **Change:** Scoped doctor profile management and schedule generation to tenant context.
- **Reason:** Prevents doctor record manipulation by unauthorized administrators.
- **Tests:** `test_doctor_schedule_day_of_week.py`.

### 14. `app/api/v1/routes/expense_routes.py` (+16, -4)
- **Change:** Bulk expense upload CSV parser validates that every row belongs to the authenticated hospital ID.
- **Reason:** Fixed SEC-12 (Expense bulk upload cross-tenant import).
- **Tests:** `test_phase8_residual_remediation.py`.

### 15. `app/api/v1/routes/hospital_voice_routes.py` (+3, -2)
- **Change:** Enforced DID-to-hospital lookup validation on voice FAQ and prompt configurations.
- **Reason:** Fixed SEC-13 (Voice helper hospital ID coercion).
- **Tests:** `test_hospital_voice_routes.py`.

### 16. `app/api/v1/routes/inventory_routes.py` (+26, -16)
- **Change:** Scoped inventory items, warehouses, and reorder levels to `TenantWriteHospitalId`.
- **Reason:** Prevents inventory theft / false stock adjustments across tenants.
- **Tests:** `test_inventory_tenant_security.py`.

### 17. `app/api/v1/routes/lab_routes.py` (+36, -11)
- **Change:** Bound lab order creation, technician verification, doctor approval, and OCR review to tenant hospital.
- **Reason:** Fixed SEC-09 (Lab OCR approval ownership).
- **Tests:** `test_phase8_residual_remediation.py`, `test_lab_report_approve.py`.

### 18. `app/api/v1/routes/nurse_routes.py` (+24, -7)
- **Change:** Scoped nurse rounds and vitals recording to session hospital context.
- **Reason:** Fixed SEC-08 (Nurse vitals tenant scoping).
- **Tests:** `test_phase8_residual_remediation.py`, `test_nurse_shifts.py`.

### 19. `app/api/v1/routes/patient_routes.py` (+50, -27)
- **Change:** Scoped patient registration, vitals, medical history, and exports to `TenantWriteHospitalId`.
- **Reason:** Prevents unauthorized patient record creation and cross-tenant data harvesting.
- **Tests:** `test_patient_export.py`, `test_patient_create_vitals_multipart.py`.

### 20. `app/api/v1/routes/pharmacy_routes.py` (+64, -18)
- **Change:** Enforced `TenantWriteHospitalId` across medicine catalog, batch management, prescriptions, and sales. Bulk medicine upload validates tenant context row-by-row.
- **Reason:** Fixed SEC-01 & SEC-10 (Pharmacy prescription & bulk upload IDOR).
- **Tests:** `test_phase8_residual_remediation.py`, `test_pharmacy_dispense_reservation.py`.

### 21. `app/api/v1/routes/rbac_routes.py` (+98, -44)
- **Change:** Integrated dynamic role and permission management. Added fail-safe guards on dev seed endpoints (`ENABLE_DEV_RBAC_SEED`).
- **Reason:** Transition from hardcoded role strings to dynamic SaaS RBAC.
- **Tests:** `test_custom_role_permissions_remediation.py`.

### 22. `app/api/v1/routes/room_tariff_routes.py` (+13, -17)
- **Change:** Scoped room tariff pricing to `TenantWriteHospitalId`.
- **Reason:** Prevents tampering with billing room rates by unauthorized users.
- **Tests:** `test_phase7_route_dispatch.py`.

### 23. `app/api/v1/routes/staff_routes.py` (+25, -9)
- **Change:** Removed handling that permitted staff records with NULL `hospital_id`.
- **Reason:** Fixed SEC-05 (Staff NULL tenant handling).
- **Tests:** `test_phase7_route_dispatch.py`.

### 24. `app/api/v1/routes/super_admin_routes.py` (+124, -1)
- **Change:** Added endpoints for hospital module subscription management and platform-level tier governance. Enforced `require_role([UserRole.SUPER_ADMIN])`.
- **Reason:** Fixed SEC-15 (Super Admin scope ambiguity).
- **Tests:** `test_multi_hospital_saas_implementation.py`.

### 25. `app/api/v1/routes/transaction_routes.py` (+17, -5)
- **Change:** Scoped financial transaction history lookups and exports to `TenantWriteHospitalId`.
- **Reason:** Financial privacy and audit compliance.
- **Tests:** `test_phase7_route_dispatch.py`.

### 26. `app/api/v1/routes/vendor_routes.py` (+15, -17)
- **Change:** Scoped vendor profiles and purchase orders to tenant hospital.
- **Reason:** Multi-tenant vendor isolation.
- **Tests:** `test_vendor_payment_duplicate_validation.py`.

---

## 3. Database Models, Repositories & Services

### Models (6 Files):
- `app/models/__init__.py`: Registered `Module` and `HospitalModule`.
- `app/models/module_model.py` (Untracked, 35 lines): Defines `Module` (catalog) and `HospitalModule` (subscription mapping).
- `app/models/role_model.py`: Added `hospital_id` to `Role` for hospital-specific custom roles.
- `app/models/billing_model.py`, `clinical_record_model.py`, `patient_model.py`: Added explicit `hospital_id` foreign keys and tenant compound indexes.

### Repositories (6 Files):
- `app/repositories/clinical_record_repository.py`: Enforces `hospital_id` filter on notes and medical history queries.
- `app/repositories/doctor_medical_record_repository.py`: Enforces doctor-patient tenant binding.
- `app/repositories/patient_repository.py`: Enforces tenant-filtered searches and lookups.
- `app/repositories/rbac_repository.py`: Dynamic permission query resolvers.
- `app/repositories/module_repository.py` (Untracked, 75 lines): Active module subscription lookup and caching.

### Services (20 Files):
- `app/services/pharmacy_service.py`: Added `SELECT ... FOR UPDATE` row locks on medicine stock decrement.
- `app/services/bed_allocation_service.py`: Added row locks on bed occupancy state transitions.
- `app/services/appointment_service.py`: Conflict detection on doctor time slots.
- `app/services/billing_service.py`: Enforced transactional consistency on bill items and payments.
- `app/services/module_service.py` (Untracked, 252 lines): Fail-closed SaaS subscription validator.
- Remaining services (`chat`, `clinical_record`, `department`, `discharge`, `doctor`, `expense`, `lab`, `nurse`, `patient`, `rbac`, `room_tariff`, `staff`, `transaction`, `vendor`): Scoped business logic to verified tenant context.

---

## 4. Background Tasks, Tests & Migrations

- `app/tasks/voice_tasks.py`: Tenant-aware async TTS and voice reminder dispatch.
- `app/tasks/whatsapp_tasks.py`: Tenant-aware WhatsApp notification retry worker.
- `app/tests/conftest.py`: Added fixtures for synthetic multi-hospital tokens and database session overrides.
- `alembic/versions/9f8e7d6c5b4a...py` (Untracked, 194 lines): Schema migration creating `modules` and `hospital_modules`.
- `alembic/versions/b8a7c6d5e4f3...py` (Untracked, 114 lines): Idempotent permission migration for clinical records.
- 3 Untracked Test Suites: `test_clinical_document_ownership.py`, `test_custom_role_permissions_remediation.py`, `test_multi_hospital_saas_implementation.py`.
