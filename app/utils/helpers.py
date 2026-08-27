import uuid
from datetime import date, datetime, timezone, timedelta


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_today_ist() -> date:
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).date()



def generate_code(prefix: str) -> str:
    return f"{prefix}-{utc_now().strftime('%Y%m%d')}{uuid.uuid4().hex[:6].upper()}"


def generate_mrn() -> str:
    return generate_code("PAT")


def generate_user_code() -> str:
    return generate_code("USR")


def generate_doctor_code() -> str:
    return generate_code("DOC")


def generate_nurse_code() -> str:
    return generate_code("NRS")


def generate_staff_code() -> str:
    return generate_code("STF")



def generate_appointment_number() -> str:
    return generate_code("APT")


def generate_admission_number() -> str:
    return generate_code("ADM")


def generate_invoice_number() -> str:
    return generate_code("INV")


def generate_bill_number() -> str:
    return generate_code("BIL")


def generate_claim_number() -> str:
    return generate_code("CLM")


def generate_discharge_number() -> str:
    return generate_code("DIS")


def generate_gate_pass_number() -> str:
    return generate_code("GP")


def generate_prescription_number() -> str:
    return generate_code("RX")


def generate_pharmacy_invoice_number() -> str:
    return generate_code("PHR")


def generate_purchase_number() -> str:
    return generate_code("PUR")


def generate_lab_order_number() -> str:
    return generate_code("LAB")


def generate_sample_code() -> str:
    return generate_code("SMP")


def generate_lab_report_number() -> str:
    return generate_code("RPT")


def generate_lab_test_code() -> str:
    return generate_code("TST")


def generate_stock_transaction_number() -> str:
    return generate_code("STK")


def generate_chat_session_id() -> str:
    return f"CHAT-{uuid.uuid4().hex}"


def generate_campaign_code() -> str:
    return generate_code("CMP")


def generate_medicine_sku() -> str:
    return generate_code("MED")




def calculate_gst_amount(amount: float, gst_rate: float) -> float:
    return round(amount * gst_rate / 100, 2)


def calculate_line_total(quantity: int, unit_price: float, gst_rate: float = 0.0) -> tuple[float, float, float]:
    subtotal = round(quantity * unit_price, 2)
    gst_amount = calculate_gst_amount(subtotal, gst_rate)
    line_total = round(subtotal + gst_amount, 2)
    return subtotal, gst_amount, line_total


def calculate_bill_totals(
    subtotal: float,
    discount_percent: float = 0.0,
    discount_amount: float = 0.0,
    gst_rate: float = 18.0,
    tax_amount: float = 0.0,
) -> dict[str, float]:
    discount = discount_amount or round(subtotal * discount_percent / 100, 2)
    taxable = max(subtotal - discount, 0.0)
    gst_amount = calculate_gst_amount(taxable, gst_rate)
    total = round(taxable + gst_amount + tax_amount, 2)
    return {
        "subtotal": round(subtotal, 2),
        "discount_amount": round(discount, 2),
        "gst_amount": gst_amount,
        "tax_amount": round(tax_amount, 2),
        "total_amount": total,
    }
