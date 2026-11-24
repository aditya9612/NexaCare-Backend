# 05 DATABASE AND MIGRATION CHANGE HISTORY

**Audit Title:** Database Schema Evolution, Alembic Migrations & Data Safety
**Target Repository:** `C:\Users\Admin\Desktop\NexaCare-Backend`
**Current Branch:** `tejas-feature`
**Target Database:** Local MySQL `nexacare` (MySQL 8.0.45 Community Server on localhost)
**Execution Timestamp:** 2026-11-23T21:13:30+05:30

---

## 1. Declarative Models & Schema Evolution

The application's data models in `app/models/` underwent targeted additive modifications to support multi-hospital tenancy and dynamic RBAC:

| Model File | Changes Implemented | Database Impact |
| :--- | :--- | :--- |
| `app/models/module_model.py` (Untracked) | Added `Module` and `HospitalModule` classes. | Created `modules` and `hospital_modules` tables for SaaS subscription management. |
| `app/models/role_model.py` (Tracked Modified) | Added `hospital_id` (nullable FK to `hospitals.id`) and `base_role_type`. | Enabled custom hospital-specific roles alongside system roles. |
| `app/models/billing_model.py` (Tracked Modified) | Added tenant compound index and explicit `hospital_id` references. | Guarantees billing query performance and strict tenant filtering. |
| `app/models/clinical_record_model.py` (Tracked Modified) | Added `hospital_id` foreign key and access tracking columns. | Binds clinical notes directly to hospital tenant context. |
| `app/models/patient_model.py` (Tracked Modified) | Added compound index on `(hospital_id, patient_code)`. | Fast tenant lookups and prevention of cross-hospital code collisions. |
| `app/models/__init__.py` (Tracked Modified) | Registered `Module` and `HospitalModule` in the declarative base. | Ensures all models are discovered by Alembic autogenerate and migrations. |

---

## 2. Alembic Migration History & Unified Head

The repository maintains **81 migration revisions** in `alembic/versions/` terminating in unified head `b8a7c6d5e4f3`:

### 1. Revision `9f8e7d6c5b4a` (`add_multi_hospital_modules_and_dynamic_rbac.py`):
- **Revises:** `4a59273b8083`
- **Actions:**
  - Creates table `modules` (id, code, name, description, is_active).
  - Creates table `hospital_modules` (id, hospital_id, module_id, is_active, subscribed_at, expires_at).
  - Adds `hospital_id` to `roles` table.
  - Seeds 12 standard modules (`PATIENT_MGMT`, `DOCTOR_MGMT`, `APPOINTMENTS`, `BILLING`, `PHARMACY`, `LABORATORY`, `BED_MGMT`, `SETTINGS`, `INVENTORY`, `EXPENSES`, `CLINICAL_RECORDS`, `VOICE_BOT`).
  - Automatically enables all modules for existing hospitals to ensure zero regression on legacy records.

### 2. Revision `b8a7c6d5e4f3` (`add_clinical_records_permissions.py`):
- **Revises:** `9f8e7d6c5b4a`
- **Actions:**
  - Idempotently inserts 4 new permissions: `clinical_records:create`, `clinical_records:read`, `clinical_records:update`, `clinical_records:delete`.
  - Maps `create`, `read`, `update` to `Doctor`.
  - Maps `create`, `read`, `update`, `delete` to `Hospital Admin` and `Super Admin`.
  - Ensures doctors cannot delete medical records (legal compliance).

### 3. Engine Patch: `alembic/env.py`:
- In `--sql` offline mode, intercepts `sa.inspect(MockConnection)` and `reflection.Inspector.from_engine(MockConnection)` calls originating in 17 historical migrations, returning safe empty reflection collections.
- Enables clean static DDL generation without requiring a live database connection.

---

## 3. Local MySQL `nexacare` Verification

1. **Pre-Migration Safety Backup:**
   - Full non-destructive mysqldump taken: [`scratch/backup_nexacare_pre_validation.sql`](file:///c:/Users/Admin/Desktop/NexaCare-Backend/scratch/backup_nexacare_pre_validation.sql) (1,621,790 bytes).
2. **Online Migration Execution:**
   - Command: `alembic upgrade head`.
   - Result: Upgraded `9f8e7d6c5b4a` $\rightarrow$ `b8a7c6d5e4f3` cleanly with exit code 0.
   - Status: `alembic current` confirms `b8a7c6d5e4f3 (head)`.
3. **Database Permissions Verification:**
   - Direct query of `permissions` and `role_permissions` verified all 11 active role mappings created idempotently.
4. **Data Safety:**
   - Zero columns dropped, zero data truncated, zero existing application records modified or deleted.
