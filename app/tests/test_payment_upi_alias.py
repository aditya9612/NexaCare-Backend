import pytest
from pydantic import ValidationError

from app.schemas.billing_schema import PaymentCreate


def test_payment_create_upi_with_transaction_reference_camel_case():
    """Verify that paymentMethod='UPI' and transactionReference='vbhjk76543' pass validation."""
    data = {
        "amount": 800.0,
        "paymentMethod": "UPI",
        "transactionReference": "vbhjk76543",
    }
    payment = PaymentCreate.model_validate(data)
    assert payment.payment_method == "upi"
    assert payment.transaction_ref == "vbhjk76543"


def test_payment_create_upi_with_transaction_reference_snake_case():
    """Verify that payment_method='UPI' and transaction_reference='vbhjk76543' pass validation."""
    data = {
        "amount": 800.0,
        "payment_method": "UPI",
        "transaction_reference": "vbhjk76543",
    }
    payment = PaymentCreate.model_validate(data)
    assert payment.payment_method == "upi"
    assert payment.transaction_ref == "vbhjk76543"


def test_payment_create_upi_with_transaction_ref_original():
    """Verify that payment_method='UPI' and transaction_ref='vbhjk76543' pass validation."""
    data = {
        "amount": 800.0,
        "payment_method": "UPI",
        "transaction_ref": "vbhjk76543",
    }
    payment = PaymentCreate.model_validate(data)
    assert payment.payment_method == "upi"
    assert payment.transaction_ref == "vbhjk76543"


def test_payment_create_upi_without_transaction_reference_fails():
    """Verify that UPI payment without any transaction reference fails validation."""
    data = {
        "amount": 800.0,
        "paymentMethod": "UPI",
    }
    with pytest.raises(ValidationError) as exc_info:
        PaymentCreate.model_validate(data)

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert "Transaction reference is required for upi payments" in str(errors[0]["msg"])
