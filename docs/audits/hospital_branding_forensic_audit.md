# NexaCare Hospital Management SaaS — Final Forensic Audit Report
## Product-Wide Export, Report & Multi-Tenant Hospital Branding Audit

---

## 1. Executive Summary

This forensic audit evaluates all 24 export, reporting, and document-generation endpoints in the **NexaCare Hospital Management SaaS** backend repository.

### Key Audit Findings Prior to Remediation:
1. **Spreadsheet Formula Injection (CWE-1236)**: Only `appointment_service.py` implemented formula cell sanitization. All other 10 Excel and CSV export facilities (`expense_service.py`, `inventory_service.py`, `lab_service.py`, `transaction_service.py`, `vendor_service.py`, `bed_allocation_service.py`, `report_export_service.py`, `excel_generator.py`) wrote raw database strings directly to cells, leaving administrative users vulnerable to CSV/Excel formula injection upon opening generated files in Microsoft Excel or LibreOffice Calc.
2. **Broken Hospital Logo Rendering in HTML/Playwright PDFs**: 10 out of 11 Jinja templates passed raw local file paths (e.g. `C:/Users/Admin/.../uploads/logo.png`) or `None` into HTML `<img>` tags. Playwright's headless Chromium rejects raw local filesystem paths due to web security sandbox origin policies, rendering broken image placeholders or failing entirely.
3. **Hardcoded Hospital Identities**:
   - Retail Pharmacy Invoices (`pharmacy_service.py:download_invoice`) used hardcoded inline HTML (`NexaCare Pharmacy`).
   - Single Appointment Consultation Summaries (`appointment_service.py:download_appointment_pdf`) hardcoded `<b>NexaCare Hospital</b>`.
   - Billing Invoices (`billing_service.py:generate_invoice`) hardcoded `NEXACARE AI 360 HEALTHCARE`.
   - Discharge Gate Passes (`discharge_service.py:download_gate_pass_pdf`) defaulted to a hardcoded Pune address (`123 Healthcare Boulevard, Medical Enclave, Pune, MH - 411001`).
4. **Header and Footer Inconsistencies**: No unified standard existed across Jinja templates. Some had no headers, some had ad-hoc HTML tables, and none provided consistent document metadata (Record count, Period, Generation timestamp, Page X of Y).
5. **Decentralized Tenant Branding Resolution**: Each service performed independent, ad-hoc, and inconsistent database queries to fetch hospital records, with duplicate logo path fallback logic scattered across 9 different Python files.

---

## 2. Comprehensive 24-Feature Audit Matrix

| # | Document / Export Feature | HTTP Route | Method | Service & Generator Method | Engine | Branding Source | Formula Injection (Pre-Fix) | Logo Status (Pre-Fix) | Multi-Tenant Scoping |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Appointments Tabular Export | `/appointments/export` | GET | `AppointmentService.export_appointments` | OpenPyXL / HTML2PDF | Ad-hoc DB lookup | Sanitized | Base64 (Fixed) | Tenant Scoped |
| 2 | Single Appointment Visit Summary | `/appointments/{id}/download` | GET | `AppointmentService.download_appointment_pdf` | ReportLab Platypus | **Hardcoded "NexaCare Hospital"** | N/A | Hardcoded Text Only | Tenant Scoped |
| 3 | Billings Tabular Export | `/billings/export` | GET | `BillingService.export_billings` | OpenPyXL / HTML2PDF | Ad-hoc DB lookup | **VULNERABLE** | Raw file path (Broken) | Tenant Scoped |
| 4 | Billing Patient Tax Invoice | `/billings/{id}/invoice` | GET | `BillingService.generate_invoice` | Jinja2 / Playwright | Ad-hoc DB lookup | N/A | Raw file path (Broken) | Tenant Scoped |
| 5 | Doctors Roster Export | `/doctors/export` | GET | `DoctorService.export_doctors` | OpenPyXL / HTML2PDF | Ad-hoc DB lookup | **VULNERABLE** | Raw file path (Broken) | Tenant Scoped |
| 6 | Expenses Tabular Export | `/expenses/export` | GET | `ExpenseService.export_expenses` | OpenPyXL / HTML2PDF | None (No branding) | **VULNERABLE** | No Logo | Tenant Scoped |
| 7 | Inventory Items Export | `/inventory/items/export` | GET | `InventoryService.export_items` | OpenPyXL / HTML2PDF | None (No branding) | **VULNERABLE** | No Logo | Tenant Scoped |
| 8 | Lab Orders Tabular Export | `/lab/orders/export` | GET | `LabService.export_orders` | OpenPyXL / HTML2PDF | None (No branding) | **VULNERABLE** | No Logo | Tenant Scoped |
| 9 | Single Diagnostic Lab Report | `/lab/reports/{id}/pdf` | GET | `LabService._generate_report_pdf` | Jinja2 / Playwright | Ad-hoc DB lookup | N/A | Base64 / File Path | Tenant Scoped |
| 10 | Lab Dashboard Analytics Report | `/lab/dashboard/export` | GET | `LabDashboardPdf.generate` | Jinja2 / Playwright | Ad-hoc DB lookup | N/A | Base64 / File Path | Tenant Scoped |
| 11 | Pharmacy Medicines Export | `/pharmacy/medicines/export` | GET | `PharmacyService.export_medicines` | OpenPyXL / HTML2PDF | Ad-hoc DB lookup | **VULNERABLE** | Raw file path (Broken) | Tenant Scoped |
| 12 | Pharmacy Suppliers Export | `/pharmacy/suppliers/export` | GET | `PharmacyService.export_suppliers` | OpenPyXL / HTML2PDF | Ad-hoc DB lookup | **VULNERABLE** | Raw file path (Broken) | Tenant Scoped |
| 13 | Pharmacy Retail Invoice | `/pharmacy/invoices/{id}/download` | GET | `PharmacyService.download_invoice` | Jinja2 / Playwright | **Hardcoded "NexaCare Pharmacy"** | N/A | Hardcoded Text Only | Tenant Scoped |
| 14 | Patients Tabular Export | `/patients/export` | GET | `PatientService.export_patients` | OpenPyXL / HTML2PDF | Ad-hoc DB lookup | **VULNERABLE** | Raw file path (Broken) | Tenant Scoped |
| 15 | Transactions Tabular Export | `/transactions/export` | GET | `TransactionService.export_transactions` | OpenPyXL / HTML2PDF | None (No branding) | **VULNERABLE** | No Logo | Tenant Scoped |
| 16 | Vendors Tabular Export | `/vendors/export` | GET | `VendorService.export_vendors` | OpenPyXL / HTML2PDF | Ad-hoc DB lookup | **VULNERABLE** | Raw file path (Broken) | Tenant Scoped |
| 17 | Bed Allocation Excel Export | `/bed-allocation/export/excel` | GET | `BedAllocationService.export_bed_data_excel` | OpenPyXL | None (No branding) | **VULNERABLE** | No Header | Tenant Scoped |
| 18 | Bed Allocation CSV Export | `/bed-allocation/export/csv` | GET | `BedAllocationService.export_bed_data_csv` | Python `csv` | None (No branding) | **VULNERABLE** | N/A | Tenant Scoped |
| 19 | Patient Discharge Gate Pass | `/discharges/{id}/gate-pass` | GET | `DischargeService.download_gate_pass_pdf` | ReportLab Platypus | Ad-hoc DB lookup | N/A | Local File Path (ReportLab) | Tenant Scoped (Fallback to Pune) |
| 20 | Admin Daily Revenue Report | `/reports/admin/daily-revenue` | GET | `ReportExportService.export_pdf/csv` | ReportLab / CSV | Generic default | **VULNERABLE (CSV)** | Static Fallback | Tenant Scoped |
| 21 | Admin Patient Statistics Report | `/reports/admin/patient-statistics` | GET | `ReportExportService.export_pdf/csv` | ReportLab / CSV | Generic default | **VULNERABLE (CSV)** | Static Fallback | Tenant Scoped |
| 22 | Accountant Financial Report | `/reports/accountant/financial-summary` | GET | `ReportExportService.export_pdf/csv` | ReportLab / CSV | Generic default | **VULNERABLE (CSV)** | Static Fallback | Tenant Scoped |
| 23 | Pharmacy Profit & Loss Report | `/reports/pharmacy/profit-loss` | GET | `ReportExportService.export_pdf/csv` | ReportLab / CSV | Ad-hoc DB lookup | **VULNERABLE (CSV)** | File Path | Tenant Scoped |
| 24 | Generic Analytics CSV Export | `/reports/generate-excel` | POST | `excel_generator.generate_excel_report` | Python `csv` | None | **VULNERABLE (CSV)** | None | Untracked |

---

## 3. Root Cause Analysis

### A. Broken Hospital Logo Rendering in Chromium/Playwright
When converting Jinja2 HTML templates into PDF using headless Chromium (Playwright), passing local filesystem paths such as `<img src="C:/Users/Admin/Desktop/NexaCare-Backend/uploads/hospital_logos/hosp_1.png">` fails because Chromium blocks `file://` and raw OS path resource loads from sandboxed renderer processes.
**Resolution**: Hospital logos must be encoded into Base64 Data URIs (`data:image/png;base64,...`) prior to template injection.

### B. Broken Logo Rendering in ReportLab
ReportLab Platypus `RLImage` flowables require a valid, verified absolute local OS path (`C:/.../logo.png`) or a PIL Image object. Passing Base64 URIs into ReportLab `Image()` causes unhandled exceptions.
**Resolution**: The centralized branding context must resolve and provide both `logo_path` (absolute verified OS file path) and `logo_data_uri` (Base64 data URI).

### C. Spreadsheet Formula Injection (CWE-1236)
When exporting data containing user-supplied text (such as patient names, medical notes, disease diagnoses, medicine names, vendor names, or payment reference IDs) that start with `=`, `+`, `-`, `@`, `\t`, `\r`, `|`, `%`, or `;`, spreadsheet applications interpret the cell as an executable formula or dynamic data exchange (DDE) command.
**Resolution**: Universal sanitization via `sanitize_excel_cell()` and `sanitize_csv_cell()` prepending a single quote (`'`) to neutralise formula triggers while rigorously preserving genuine numeric values (e.g. `-150.00`).

---

## 4. Verification and Remediation Objectives

1. Create a centralized `BrandingResolverService` returning an immutable `HospitalBrandingContext` with in-memory TTL caching and tenant isolation enforcement.
2. Provide universal sanitization utilities (`app/utils/excel_security.py` and `app/utils/csv_security.py`).
3. Standardize Excel export layouts across all 11 Excel generators using `apply_excel_hospital_header()`, `style_excel_header_row()`, and `auto_fit_columns()`.
4. Harmonize PDF templates using reusable partials (`brand_header.html` and `brand_footer.html`).
5. Eliminate all hardcoded identities across single-document generators.
6. Verify 100% test pass rate with isolated, zero-database-mutation automated test suites.
