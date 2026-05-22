"""Model-level tests for the community inventory table."""
from __future__ import annotations

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.community import CommunityItem


def test_community_item_roundtrip(db):
    item = CommunityItem(
        household_id=DEV_HOUSEHOLD_ID,
        created_by_user_id=DEV_USER_ID,
        name="Catan",
        category="games",
    )
    db.add(item)
    db.flush()

    fetched = db.get(CommunityItem, item.id)
    assert fetched is not None
    assert fetched.name == "Catan"
    assert fetched.category == "games"
    # Server/Python defaults applied.
    assert fetched.quantity == 1
    assert fetched.tags == []
    assert fetched.source == "manual"
    assert fetched.metadata_ == {}
    assert fetched.deleted_at is None
