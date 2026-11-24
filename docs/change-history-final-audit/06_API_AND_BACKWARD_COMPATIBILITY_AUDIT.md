# 06 API AND BACKWARD COMPATIBILITY AUDIT

**Audit Title:** API Contracts, Route Modifications & Backward Compatibility Audit
**Target Repository:** `C:\Users\Admin\Desktop\NexaCare-Backend`
**Current Branch:** `tejas-feature`
**Execution Timestamp:** 2026-11-23T21:14:00+05:30

---

## 1. Registered API Route Inventory

The application mounts **642 registered endpoints** across 22 router modules in `app/api/v1/routes/`:
- **Mutating Routes:** 323 endpoints (`POST`: 175, `PUT`: 55, `DELETE`: 56, `PATCH`: 37).
- **Read-Only API Routes:** 319 endpoints (`GET` under `/api/v1`).
- **Framework & Docs Routes:** 7 endpoints (`/health`, `/docs`, `/redoc`, `/api/v1/openapi.json`, etc.).

---

## 2. API Contract & Parameter Changes

During the remediation phases, parameter resolution was hardened across mutating endpoints to prevent tenant spoofing:

| Route Group | Parameter Before Remediation | Parameter After Remediation | Backward Compatibility Impact |
| :--- | :--- | :--- | :--- |
| **Billing Routes** | `hospital_id: Optional[int] = 1` (Query parameter) | Injected via `current_user.hospital_id` | **Non-Breaking:** Legacy clients omitting `hospital_id` are now safely mapped to their authenticated tenant instead of falling back to Hospital 1. |
| **Pharmacy Routes** | `hospital_id` in request body or path | Enforced via `TenantWriteHospitalId` | **Non-Breaking:** Valid requests from hospital users resolve seamlessly; cross-tenant spoofing attempts are rejected with `HTTP 403`. |
| **Bed Allocation Routes** | `hospital_id` in JSON body | Enforced via `TenantWriteHospitalId` | **Non-Breaking:** Valid payload `hospital_id` matching user session succeeds; mismatched payload returns `HTTP 400 Bad Request`. |
| **Bulk Uploads** | CSV files accepted without row tenant checks | Every CSV row checked against `hospital_id` | **Security Improvement:** Prevents accidental or malicious cross-tenant bulk imports. |
| **SaaS Modules** | All endpoints accessible if role permitted | Intercepted by `require_module_enabled` | **Expected Business Change:** Accessing an unsubscribed module returns `HTTP 403 Forbidden` (fail-closed). Existing hospitals were auto-subscribed to all modules in migration `9f8e7d6c5b4a`. |

---

## 3. OpenAPI Schema & Response Envelopes

1. **Standard Response Envelopes:** All endpoints serialize outbound responses through Pydantic models with `APIResponse` standard envelopes (`success`, `data`, `message`, `error`).
2. **Schema Validation:** Strict Pydantic models in `app/schemas/` filter sensitive internal database columns (e.g., `hashed_password`, internal salts) from being serialized in JSON responses.
3. **OpenAPI 3.1 Verification:** Live HTTP request to `/api/v1/openapi.json` confirmed that all 467 distinct paths generate valid OpenAPI 3.1 specifications without schema generation errors.
