# NexaCare Hospital Management SaaS — Centralized Hospital Branding Implementation Report

**Base Implementation Commit:** `c47d9fab766e98d027a9d36f7035d9d9b2170c31`
**Subsequent Header Alignment Commits:**
- `d2a46dfa37c73ce0bf8bf3019da6cbe045fd8fa4` (*fix: align lab report hospital branding header*)
- `43cdc34137cc93ce031a782113e08e4f55ce72f6` (*fix: align invoice hospital branding header*)

---

## 1. Executive Summary

This report documents the implementation of the **Centralized Multi-Tenant Hospital Branding System** across all 24 export, reporting, and document-generation features in the NexaCare Hospital Management SaaS backend.

### Key Objectives Achieved:
1. **Centralized Tenant-Authorized Resolution**: Replaced decentralized, duplicate database queries with `BrandingResolverService`, which enforces tenant authorization, resolves fallback assets, and maintains an in-memory TTL cache with automatic invalidation upon logo upload.
2. **Dual-Pipeline Logo Delivery**:
   - **Playwright/Chromium**: Delivers Base64 Data URIs (`data:image/png;base64,...`) to bypass headless browser filesystem security sandboxes.
   - **ReportLab Platypus**: Delivers verified, absolute OS filesystem paths to Platypus `RLImage` flowables.
3. **Elimination of All Hardcoded Hospital Identities**:
   - Replaced `NexaCare Pharmacy` in retail pharmacy invoices with dynamic hospital branding.
   - Replaced hardcoded `<b>NexaCare Hospital</b>` in single appointment visit PDFs with `create_reportlab_header_flowables()` and `NumberedCanvas`.
   - Replaced `NEXACARE AI 360 HEALTHCARE` in patient billing tax invoices with dynamic hospital branding.
   - Replaced the hardcoded Pune address fallback in patient discharge gate passes with dynamic database branding and ReportLab logo flowables.
4. **Unified Template Standardization**: Created Jinja2 partials (`brand_header.html` and `brand_footer.html`) included across all 12 HTML export templates, standardizing document titles, hospital logos, contact metadata, generation timestamps, and page numbering.
5. **Universal OpenPyXL Excel Header Banners**: Integrated `apply_excel_hospital_header()` and `auto_fit_columns()` across all 10 Excel tabular exports.
6. **Strict Preservation of Business Logic**: Preserved the 12-card appointment dashboard aggregation (`CANCELLED` + `NO_SHOW` combined metric) and avoided all database schema alterations or migrations.

---

## 2. Comprehensive 24-Feature Verification Matrix

| # | Document / Export Feature | HTTP Route & Service Method | Engine | Formula Sanitization | Branding Source | Logo Delivery Pipeline | Multi-Tenant Isolation | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | Appointments Tabular Export | `GET /appointments/export`<br>`AppointmentService.export_appointments` | OpenPyXL / HTML2PDF | `sanitize_excel_row` | `BrandingResolverService` | Base64 Data URI + File Path | Strict Tenant Scoped | **VERIFIED** |
| 2 | Single Appointment Visit Summary | `GET /appointments/{id}/download`<br>`AppointmentService.download_appointment_pdf` | ReportLab Platypus | N/A (Platypus Flowables) | `BrandingResolverService` | `create_reportlab_header_flowables` (OS Path) | Strict Tenant Scoped | **VERIFIED** |
| 3 | Billings Tabular Export | `GET /billings/export`<br>`BillingService.export_billings` | OpenPyXL / HTML2PDF | `sanitize_excel_row` | `BrandingResolverService` | Base64 Data URI + File Path | Strict Tenant Scoped | **VERIFIED** |
| 4 | Billing Patient Tax Invoice | `GET /billings/{id}/invoice`<br>`BillingService.generate_invoice` | Jinja2 / Playwright | N/A (HTML Table) | `BrandingResolverService` | `brand_header.html` (Base64 URI) | Strict Tenant Scoped | **VERIFIED** |
| 5 | Doctors Roster Export | `GET /doctors/export`<br>`DoctorService.export_doctors` | OpenPyXL / HTML2PDF | `sanitize_excel_row` | `BrandingResolverService` | Base64 Data URI + File Path | Strict Tenant Scoped | **VERIFIED** |
| 6 | Expenses Tabular Export | `GET /expenses/export`<br>`ExpenseService.export_expenses` | OpenPyXL / HTML2PDF | `sanitize_excel_row` | `BrandingResolverService` | Base64 Data URI + File Path | Strict Tenant Scoped | **VERIFIED** |
| 7 | Inventory Items Export | `GET /inventory/items/export`<br>`InventoryService.export_items` | OpenPyXL / HTML2PDF | `sanitize_excel_row` | `BrandingResolverService` | Base64 Data URI + File Path | Strict Tenant Scoped | **VERIFIED** |
| 8 | Lab Orders Tabular Export | `GET /lab/orders/export`<br>`LabService.export_orders` | OpenPyXL / HTML2PDF | `sanitize_excel_row` | `BrandingResolverService` | Base64 Data URI + File Path | Strict Tenant Scoped | **VERIFIED** |
| 9 | Single Diagnostic Lab Report | `GET /lab/reports/{id}/pdf`<br>`LabService._generate_report_pdf` | Jinja2 / Playwright | N/A (HTML Table) | `BrandingResolverService` | `brand_header.html` (Base64 URI) | Strict Tenant Scoped | **VERIFIED** |
| 10 | Lab Dashboard Analytics Report | `GET /lab/dashboard/export`<br>`LabDashboardPdf.generate` | Jinja2 / Playwright | N/A (HTML Table) | `BrandingResolverService` | Base64 Data URI | Strict Tenant Scoped | **VERIFIED** |
| 11 | Pharmacy Medicines Export | `GET /pharmacy/medicines/export`<br>`PharmacyService.export_medicines` | OpenPyXL / HTML2PDF | `sanitize_excel_row` | `BrandingResolverService` | Base64 Data URI + File Path | Strict Tenant Scoped | **VERIFIED** |
| 12 | Pharmacy Suppliers Export | `GET /pharmacy/suppliers/export`<br>`PharmacyService.export_suppliers` | OpenPyXL / HTML2PDF | `sanitize_excel_row` | `BrandingResolverService` | Base64 Data URI + File Path | Strict Tenant Scoped | **VERIFIED** |
| 13 | Pharmacy Retail Invoice | `GET /pharmacy/invoices/{id}/download`<br>`PharmacyService.download_invoice` | Jinja2 / Playwright | N/A (HTML Table) | `BrandingResolverService` | `brand_header.html` (Base64 URI) | Strict Tenant Scoped | **VERIFIED** |
| 14 | Patients Tabular Export | `GET /patients/export`<br>`PatientService.export_patients` | OpenPyXL / HTML2PDF | `sanitize_excel_row` | `BrandingResolverService` | Base64 Data URI + File Path | Strict Tenant Scoped | **VERIFIED** |
| 15 | Transactions Tabular Export | `GET /transactions/export`<br>`TransactionService.export_transactions` | OpenPyXL / HTML2PDF | `sanitize_excel_row` | `BrandingResolverService` | Base64 Data URI + File Path | Strict Tenant Scoped | **VERIFIED** |
| 16 | Vendors Tabular Export | `GET /vendors/export`<br>`VendorService.export_vendors` | OpenPyXL / HTML2PDF | `sanitize_excel_row` | `BrandingResolverService` | Base64 Data URI + File Path | Strict Tenant Scoped | **VERIFIED** |
| 17 | Bed Allocation Excel Export | `GET /bed-allocation/export/excel`<br>`BedAllocationService.export_bed_data_excel` | OpenPyXL | `sanitize_excel_row` | `BrandingResolverService` | OpenPyXL Header Banner | Strict Tenant Scoped | **VERIFIED** |
| 18 | Bed Allocation CSV Export | `GET /bed-allocation/export/csv`<br>`BedAllocationService.export_bed_data_csv` | Python `csv` | `sanitize_csv_row` | `BrandingResolverService` | N/A (Text Stream) | Strict Tenant Scoped | **VERIFIED** |
| 19 | Patient Discharge Gate Pass | `GET /discharges/{id}/gate-pass`<br>`DischargeService.download_gate_pass_pdf` | ReportLab Platypus | N/A (Platypus Flowables) | `BrandingResolverService` | Platypus `RLImage` (OS Path) | Strict Tenant Scoped | **VERIFIED** |
| 20 | Admin Daily Revenue Report | `GET /reports/admin/daily-revenue`<br>`ReportExportService.export_pdf/csv` | ReportLab / CSV | `sanitize_csv_cell` | `BrandingResolverService` | Platypus `RLImage` (OS Path) | Super Admin / Scoped | **VERIFIED** |
| 21 | Admin Patient Statistics Report | `GET /reports/admin/patient-statistics`<br>`ReportExportService.export_pdf/csv` | ReportLab / CSV | `sanitize_csv_cell` | `BrandingResolverService` | Platypus `RLImage` (OS Path) | Super Admin / Scoped | **VERIFIED** |
| 22 | Accountant Financial Report | `GET /reports/accountant/financial-summary`<br>`ReportExportService.export_pdf/csv` | ReportLab / CSV | `sanitize_csv_cell` | `BrandingResolverService` | Platypus `RLImage` (OS Path) | Accountant / Scoped | **VERIFIED** |
| 23 | Pharmacy Profit & Loss Report | `GET /reports/pharmacy/profit-loss`<br>`ReportExportService.export_pdf/csv` | ReportLab / CSV | `sanitize_csv_cell` | `BrandingResolverService` | Platypus `RLImage` (OS Path) | Pharmacy Admin / Scoped | **VERIFIED** |
| 24 | Generic Analytics CSV Export | `POST /reports/generate-excel`<br>`excel_generator.generate_excel_report` | Python `csv` | `sanitize_csv_dict` | Context Passed | N/A (CSV Stream) | Caller Scoped | **VERIFIED** |

---

## 3. Comprehensive File Inventory

### 3.1 Newly Created Core Modules & Utilities

| File Path | Purpose |
|---|---|
| `app/utils/excel_security.py` | Universal Excel formula injection sanitizer (`sanitize_excel_cell`, `sanitize_excel_row`, `TrustedFormula`). |
| `app/utils/csv_security.py` | Universal CSV formula injection sanitizer (`sanitize_csv_cell`, `sanitize_csv_row`, `sanitize_csv_dict`). |
| `app/services/branding_resolver_service.py` | Centralized `BrandingResolverService` and `HospitalBrandingContext` data model. |
| `app/utils/excel_branding.py` | OpenPyXL hospital header banners (`apply_excel_hospital_header`), header row styling (`style_excel_header_row`), column width auto-fitting (`auto_fit_columns`). |
| `app/utils/reportlab_branding.py` | ReportLab Platypus header flowables (`create_reportlab_header_flowables`) and two-pass "Page X of Y" canvas (`NumberedCanvas`). |
| `app/templates/partials/brand_header.html` | Unified HTML document header partial for Jinja2/Playwright PDF generation. |
| `app/templates/partials/brand_footer.html` | Unified HTML document footer partial with dynamic hospital contact details, timestamp, and page numbers. |
| `app/tests/test_branding_and_security_suite.py` | Comprehensive verification test suite covering branding, multi-tenancy, formula injection, and caching. |

### 3.2 Modified Backend Services (13 Services)

| Service File | Modifications & Remediations Applied |
|---|---|
| `app/services/hospital_service.py` | Added `clear_branding_cache(hospital.id)` hook upon successful logo upload to invalidate stale cached logos immediately. |
| `app/services/pharmacy_service.py` | Replaced hardcoded retail invoice branding with `BrandingResolverService`; sanitized cells and added OpenPyXL header banners to `export_medicines` and `export_suppliers`. |
| `app/services/doctor_service.py` | Integrated `BrandingResolverService`, `sanitize_excel_row`, and `apply_excel_hospital_header` into `export_doctors`. |
| `app/services/billing_service.py` | Integrated `BrandingResolverService`, `sanitize_excel_row`, and `apply_excel_hospital_header` into `export_billings`; dynamic branding in `generate_invoice`. |
| `app/services/patient_service.py` | Integrated `BrandingResolverService`, `sanitize_excel_row`, and `apply_excel_hospital_header` into `export_patients`. |
| `app/services/expense_service.py` | Integrated `BrandingResolverService`, `sanitize_excel_row`, and `apply_excel_hospital_header` into `export_expenses`. |
| `app/services/inventory_service.py` | Added `current_user` parameter propagation, `BrandingResolverService`, cell sanitization, and header banner to `export_items`. |
| `app/services/lab_service.py` | Integrated `BrandingResolverService` into diagnostic lab report PDF; sanitized cells and added header banner to `export_orders`. |
| `app/services/transaction_service.py` | Integrated `BrandingResolverService`, `sanitize_excel_row`, and `apply_excel_hospital_header` into `export_transactions`. |
| `app/services/vendor_service.py` | Restored all original CRUD methods (`list_vendors`, `get_vendor`, `update_vendor`, `delete_vendor`, `generate_vendor_bulk_template`, `import_vendors_from_excel`); implemented standalone `export_vendors` method with `BrandingResolverService`, cell sanitization, OpenPyXL header, and balanced PDF template rendering. |
| `app/services/bed_allocation_service.py` | Sanitized CSV cells in `export_bed_data_csv`; added `BrandingResolverService`, cell sanitization, and header banner to `export_bed_data_excel`. |
| `app/services/discharge_service.py` | Replaced hardcoded Pune fallback with dynamic `BrandingResolverService` and `RLImage` flowable in `download_gate_pass_pdf`. |
| `app/services/appointment_service.py` | Replaced hardcoded `<b>NexaCare Hospital</b>` with `create_reportlab_header_flowables` and `NumberedCanvas` in `download_appointment_pdf`; integrated `BrandingResolverService` in `export_appointments`. |
| `app/services/report_export_service.py` | Integrated `sanitize_csv_cell` into CSV generation; updated logo resolution with platform fallback for admin/accountant reports. |
| `app/services/razorpay_service.py` | Added safe import guard (`try: import razorpay except ImportError: razorpay = None`) to permit clean offline test runs. |

### 3.3 Modified API Routes & Utility Modules

| File Path | Modifications |
|---|---|
| `app/api/v1/routes/inventory_routes.py` | Updated route handler to pass `current_user=current_user` to `InventoryService.export_items()` for tenant-aware branding. |
| `app/utils/excel_generator.py` | Sanitized CSV dictionary rows via `sanitize_csv_dict()` in `generate_excel_report()`. |
| `app/utils/lab_dashboard_pdf.py` | Added fallback default logo resolution. |

### 3.4 Remediated Jinja2 HTML Templates (12 Templates)

All 12 templates were refactored to include `partials/brand_header.html` and `partials/brand_footer.html`:
1. `app/templates/appointments_export_template.html`
2. `app/templates/billings_export_template.html`
3. `app/templates/doctors_export_template.html`
4. `app/templates/expenses_export_template.html`
5. `app/templates/inventory_items_export_template.html`
6. `app/templates/invoice_template.html` *(Further refined in commit `43cdc34`)*
7. `app/templates/lab_orders_export_template.html`
8. `app/templates/medicines_export_template.html`
9. `app/templates/patients_export_template.html`
10. `app/templates/suppliers_export_template.html`
11. `app/templates/transactions_export_template.html`
12. `app/templates/vendors_export_template.html`

---

## 4. Core Architectural Implementations

### 4.1 `BrandingResolverService`
Located in `app/services/branding_resolver_service.py`.

```python
class BrandingResolverService:
    @classmethod
    async def resolve_branding(
        cls,
        db: AsyncSession,
        current_user: Any,
        hospital_id: Optional[int] = None,
        x_hospital_id: Optional[str] = None,
    ) -> HospitalBrandingContext:
```

#### Workflow & Security Enforcement:
1. **Tenant Isolation**:
   - Hospital Admins, Doctors, Nurses, and Staff have a non-null `current_user.hospital_id`.
   - If an explicit `hospital_id` or header `x_hospital_id` is passed, it is strictly validated against `current_user.hospital_id`. If there is a mismatch, a `ForbiddenException("Access denied to another hospital's branding")` is raised immediately.
2. **Super Admin Access**:
   - Super Admins can pass an explicit `hospital_id` to generate branding for any specific tenant.
   - If no tenant ID is specified, Super Admins receive the platform network branding (`NexaCare Healthcare Network`).
3. **In-Memory TTL Caching**:
   - Branding contexts are cached in `_BRANDING_CACHE` for 60 seconds (1 minute).
   - Cache keys are scoped by hospital ID (e.g. `hospital:1` or `super_admin:network`).
   - Invalidation occurs automatically via `clear_branding_cache(hospital_id)` during logo uploads or hospital record updates.
4. **Fallback Asset Resolution**:
   - If a hospital has not uploaded a logo or the stored file path is inaccessible, the service resolves `app/static/images/logo.png`.
   - Both `logo_path` (for ReportLab) and `logo_data_uri` (for Playwright HTML) are populated.

---

### 4.2 Excel Branding Utilities (`app/utils/excel_branding.py`)

Standardizes all OpenPyXL tabular exports with a cohesive hospital header banner:
- **Row 1**: Hospital Name (14pt Bold, Brand Blue `#1E40AF`).
- **Row 2**: Formatted Contact Line (Address, Phone, Email, Website) (9pt Regular Gray `#4B5563`).
- **Row 3**: Report Metadata (Report Title, Generation Timestamp, Total Records) (9pt Italic Gray `#6B7280`).
- **Row 4**: Empty spacing row (Height 10).
- **Row 5+**: Table column headers with Navy fill (`#1E40AF`), White bold text, thin borders, and auto-fitted column widths (`auto_fit_columns`).

---

### 4.3 ReportLab Platypus Standards (`app/utils/reportlab_branding.py`)

Standardizes all ReportLab Platypus PDF documents (Appointment Summaries, Discharge Gate Passes, Administrative Reports):
1. **`create_reportlab_header_flowables()`**:
   - Generates a Platypus `Table` containing the hospital logo (`RLImage`) on the left and hospital name, address, contact details, and document title on the right.
   - Handles missing or unreadable logos gracefully by rendering text-only headers.
2. **`NumberedCanvas`**:
   - A two-pass ReportLab canvas subclass that dynamically computes the total page count.
   - Draws a running footer on every page containing the hospital legal name, confidential notice, generation date, and `"Page X of Y"`.

---

## 5. Hardcoded Identity Elimination Audit

| Feature | Pre-Implementation State | Post-Implementation State |
|---|---|---|
| **Pharmacy Retail Invoice** | Hardcoded inline HTML: `NexaCare Pharmacy` | Uses `brand_header.html` and `branding.hospital_name`. |
| **Appointment Visit Summary** | Hardcoded Platypus string: `<b>NexaCare Hospital</b>` | Uses `create_reportlab_header_flowables(branding, "APPOINTMENT CONSULTATION SUMMARY")` with hospital logo and metadata. |
| **Billing Patient Invoice** | Hardcoded title: `NEXACARE AI 360 HEALTHCARE` | Dynamically renders `branding.hospital_name`, `branding.contact_line`, and `branding.logo_data_uri`. |
| **Discharge Gate Pass** | Hardcoded fallback: `123 Healthcare Boulevard, Medical Enclave, Pune, MH - 411001` | Resolves actual hospital address from database via `BrandingResolverService`. |

---

## 6. Verification & Test Suite Summary

### 6.1 Historical Baseline (At Commit `c47d9fab766e98d027a9d36f7035d9d9b2170c31`)

At the time the core implementation commit `c47d9fab766e` was created, the automated test suites verified 54 passing tests:

- **`test_branding_and_security_suite.py`**: **37 passed out of 37 tests** (29 core security/branding + 8 vendor CRUD and export tests).
  - Formula injection neutralization (DDE, `=HYPERLINK`, control characters, signed numerics).
  - Multi-tenant isolation (ForbiddenException on cross-tenant access).
  - Dual-pipeline logo rendering (Base64 data URIs and absolute OS paths).
  - In-memory cache hit/miss and invalidation behavior.
  - Template rendering across all 12 Jinja templates with header/footer partials.
  - Vendor CRUD methods (`list_vendors`, `get_vendor`, `update_vendor`, `delete_vendor`, `generate_vendor_bulk_template`).
  - Vendor Excel and PDF exports with branding and formula injection protection.
- **`test_appointment_excel_formula_injection.py`**: **15 passed out of 15 tests**.
- **`test_doctor_bulk_template.py`**: **2 passed out of 2 tests**.
- **Total Initial Automated Tests**: **54 passed out of 54 tests (100% success)**.
- **Python Syntax Compilation (`py_compile`)**: **100% clean** across all 22 modified source files.
- **FastAPI Application Import (`import app.main`)**: **Passed cleanly**.

### 6.2 Subsequent Test Suite Expansion (Post-Commit Verification)

During subsequent pre-push verification and visual layout verification of PDF headers (commits `d2a46dfa37c73ce0bf8bf3019da6cbe045fd8fa4` and `43cdc34137cc93ce031a782113e08e4f55ce72f6`), additional unit, regression, and security tests were added to `app/tests/test_branding_and_security_suite.py`, expanding the single test file from 37 to **64 tests**:

- **Expanded `test_branding_and_security_suite.py`**: **64 passed out of 64 tests** (100% pass rate in 12.45s).
- This 64-test result represents subsequent verification and regression coverage, preserving the original 37-test implementation baseline.
