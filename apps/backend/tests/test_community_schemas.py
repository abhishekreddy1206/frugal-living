"""Schema validation tests for the community tier."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.community import ExtractedInventory, ItemCreate, ItemUpdate


def test_item_create_rejects_unknown_category():
    with pytest.raises(ValidationError):
        ItemCreate(name="Drill", category="vehicles")


def test_item_create_defaults():
    item = ItemCreate(name="Catan")
    assert item.category == "other"
    assert item.tags == []
    assert item.quantity == 1


def test_item_update_all_optional():
    # An empty update is valid — every field is optional.
    ItemUpdate()


def test_extracted_inventory_parses_permissive_category():
    # The vision path is untrusted; category is a plain string here.
    parsed = ExtractedInventory.model_validate(
        {"items": [{"name": "Tent", "category": "weird", "confidence": 0.8}]}
    )
    assert parsed.items[0].category == "weird"
