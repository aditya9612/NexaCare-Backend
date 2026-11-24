# 03 MODULE-WISE CHANGE HISTORY

**Audit Title:** Architecture & Subsystem Change Breakdown
**Target Repository:** `C:\Users\Admin\Desktop\NexaCare-Backend`
**Current Branch:** `tejas-feature`
**Execution Timestamp:** 2026-11-23T21:12:30+05:30

---

## 1. Authentication & Security Framework

- **Files Affected:** `app/core/dependencies.py`, `app/core/config.py`, `app/core/database.py`, `app/main.py`.
- **Architectural Changes:**
  - Transitioned from loose parameter passing to strict dependency-injected tenant context resolution (`TenantWriteHospitalId`).
  - Added Redis-backed token blocklisting on logout to prevent replay attacks.
  - Hardened startup lifespan to prevent automated password overwrites.
  - Gated developer seed routes behind `ENABLE_DEV_RBAC_SEED=False`.
- **Completion Status:** **100% COMPLETE & VERIFIED**.

---

## 2. Super Admin & SaaS Platform Governance

- **Files Affected:** `app/api/v1/routes/super_admin_routes.py`, `app/schemas/super_admin_schema.py`, `app/models/module_model.py`, `app/services/module_service.py`.
- **Architectural Changes:**
  - Segregated platform-wide governance (hospital onboarding, module subscription assignments, subscription tiers) from tenant-level operations.
  - Super Admin is explicitly restricted from performing clinical actions on hospital patients without selecting an active hospital context.
  - Implemented dynamic subscription enable/disable APIs for hospital tenants.
- **Completion Status:** **100% COMPLETE & VERIFIED**.

---

## 3. Dynamic RBAC & Hospital-Wise Module Entitlements

- **Files Affected:** `app/api/v1/routes/rbac_routes.py`, `app/repositories/rbac_repository.py`, `app/services/rbac_service.py`, `app/models/role_model.py`, `alembic/versions/9f8e7d6c5b4a...py`, `b8a7c6d5e4f3...py`.
- **Architectural Changes:**
  - Replaced hardcoded role checks with dynamic database permission mappings.
  - Supported hospital-scoped custom roles via `roles.hospital_id`.
  - Added fail-closed `require_module_enabled` dependency: inactive modules immediately abort with `HTTP 403 Forbidden`.
- **Completion Status:** **100% COMPLETE & VERIFIED**.

---

## 4. Patient Management & Nursing Vitals

- **Files Affected:** `app/api/v1/routes/patient_routes.py`, `app/api/v1/routes/nurse_routes.py`, `app/services/patient_service.py`, `app/services/nurse_service.py`, `app/repositories/patient_repository.py`.
- **Architectural Changes:**
  - Scoped patient search, registration, and exports to `TenantWriteHospitalId`.
  - Scoped nurse rounds, shift assignments, and vital recordings to verified hospital context.
  - Eliminated patient data harvesting across hospital boundaries.
- **Completion Status:** **100% COMPLETE & VERIFIED**.

---

## 5. Doctors, Appointments & Inpatient Department (IPD)

- **Files Affected:** `app/api/v1/routes/doctor_routes.py`, `app/api/v1/routes/appointment_routes.py`, `app/api/v1/routes/bed_allocation_routes.py`, `app/api/v1/routes/discharge_routes.py`, `app/services/appointment_service.py`, `app/services/bed_allocation_service.py`.
- **Architectural Changes:**
  - Enforced `SELECT ... FOR UPDATE` database row locking on appointment slots and bed occupancy transitions.
  - Eliminated appointment slot double-booking and concurrent bed allocation race conditions.
  - Bound inpatient admissions and discharge approvals strictly to owning hospital tenant.
- **Completion Status:** **100% COMPLETE & VERIFIED**.

---

## 6. Pharmacy, Medicine Inventory & Bulk Uploads

- **Files Affected:** `app/api/v1/routes/pharmacy_routes.py`, `app/services/pharmacy_service.py`, `app/schemas/pharmacy_schema.py`.
- **Architectural Changes:**
  - Eliminated prescription IDOR (SEC-01) by scoping all prescription access and updates to `TenantWriteHospitalId`.
  - Added atomic database decrement (`SELECT ... FOR UPDATE`) during medicine dispensing to prevent stock overselling.
  - Bulk CSV uploads enforce row-by-row tenant validation, rejecting files with foreign hospital records.
- **Completion Status:** **100% COMPLETE & VERIFIED**.

---

## 7. Billing, Invoices & Financial Transactions

- **Files Affected:** `app/api/v1/routes/billing_routes.py`, `app/api/v1/routes/transaction_routes.py`, `app/api/v1/routes/expense_routes.py`, `app/api/v1/routes/vendor_routes.py`, `app/services/billing_service.py`, `app/services/expense_service.py`.
- **Architectural Changes:**
  - Removed insecure fallback to Hospital 1 in billing routes.
  - Enforced atomic transaction boundaries across invoices and line items with automatic rollback on payment failures.
  - Bulk expense uploads fail closed on tenant mismatch.
- **Completion Status:** **100% COMPLETE & VERIFIED**.

---

## 8. Clinical Records, Doctor Notes & Legal Medical History

- **Files Affected:** `app/api/v1/routes/clinical_record_router.py`, `app/services/clinical_record_service.py`, `app/services/doctor_medical_record_service.py`, `app/repositories/clinical_record_repository.py`.
- **Architectural Changes:**
  - Bound clinical notes, diagnoses, and medical histories to patient and hospital tenant.
  - Enforced immutable audit logging for all record views and modifications.
  - Enforced permission policy: doctors can create, read, and update notes, but cannot delete legal clinical records.
- **Completion Status:** **100% COMPLETE & VERIFIED**.

---

## 9. Voice, AI Chat & Background Workers

- **Files Affected:** `app/api/v1/routes/hospital_voice_routes.py`, `app/api/v1/routes/chat_routes.py`, `app/tasks/voice_tasks.py`, `app/tasks/whatsapp_tasks.py`.
- **Architectural Changes:**
  - Scoped AI chat threads to session hospital context; rejected body `hospital_id` override.
  - Mapped incoming Twilio/Exotel voice calls to registered hospital DIDs with signature verification.
  - Celery background workers process audio synthesis and notification retries asynchronously.
- **Completion Status:** **100% COMPLETE & VERIFIED**.
