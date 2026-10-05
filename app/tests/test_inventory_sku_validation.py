import pytest
from pydantic import ValidationError

from app.schemas.inventory_schema import InventoryItemCreate


def test_sku_valid_examples():
    """Verify valid SKU formats are accepted by InventoryItemCreate."""
    valid_skus = ["MED-12345", "ITEM-001", "MED123-01"]
    for sku_val in valid_skus:
        item = InventoryItemCreate(
            name="Syringe 5ml",
            sku=sku_val,
            category="Medical Supplies",
            quantity=100,
            unit="pcs",
        )
        assert item.sku == sku_val


def test_sku_invalid_examples():
    """Verify invalid SKU formats are rejected with ValidationError by InventoryItemCreate."""
    invalid_skus = ["MEDICINE", "123456", "", "   ", "MED_123", "-12345"]
    for sku_val in invalid_skus:
        with pytest.raises(ValidationError) as exc_info:
            InventoryItemCreate(
                name="Syringe 5ml",
                sku=sku_val,
                category="Medical Supplies",
                quantity=100,
                unit="pcs",
            )
        errors = exc_info.value.errors()
        assert len(errors) >= 1
        assert "sku" in str(errors[0]["loc"]).lower()


def test_sku_missing_field_rejected():
    """Verify omitting the sku field raises ValidationError since SKU is mandatory."""
    data = {
        "name": "Syringe 5ml",
        "category": "Medical Supplies",
        "quantity": 100,
        "unit": "pcs",
    }
    with pytest.raises(ValidationError) as exc_info:
        InventoryItemCreate.model_validate(data)

    errors = exc_info.value.errors()
    assert any("sku" in str(err["loc"]).lower() and err["type"] == "missing" for err in errors)
