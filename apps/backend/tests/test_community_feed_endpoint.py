"""Feed endpoint — funnels through the visibility helper end-to-end."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.db import SessionLocal
from app.main import app
from app.models.community import CommunityMember
from app.models.core import Household, User


@pytest.fixture
def client():
    return TestClient(app)


def _make_listing_in_other_household_shared_to_caller():
    """Setup: the SECOND household creates an item + listing in a community
    that the FIRST household's user (the API caller) joins.
    Returns the listing id."""
    from app.services.community import communities as community_svc
    from app.services.community import items as items_svc
    from app.services.community import listings as listings_svc
    with SessionLocal() as db:
        first_user = db.get(User, DEV_USER_ID)
        second = db.query(User).filter(User.email == "second@frugal-living.local").one()
        second_household = db.query(Household).filter(Household.name == "Second Household").one()
        c = community_svc.create_community(
            db, creator_user=second, slug="feed-c", name="feed-c",
        )
        db.add(CommunityMember(community_id=c.id, user_id=first_user.id, role="member"))
        db.flush()
        item = items_svc.create_item(
            db, household=second_household, user=second, name="Borrowable Item", quantity=1,
        )
        listing = listings_svc.create_listing(
            db, household=second_household, user=second, item_id=item.id,
            allowed_exchange_types=["borrow"], quantity_available=1,
            community_ids=[c.id], share_in_radius=False,
        )
        db.commit()
        return listing.id


def test_feed_returns_shared_listing(client):
    listing_id = _make_listing_in_other_household_shared_to_caller()
    resp = client.get("/api/v1/community/feed")
    assert resp.status_code == 200
    body = resp.json()
    ids = [row["listing"]["id"] for row in body["rows"]]
    assert str(listing_id) in ids
    # And the row carries the matched_community_id (community path).
    for row in body["rows"]:
        if row["listing"]["id"] == str(listing_id):
            assert row["matched_community_id"] is not None
            assert row["distance_miles"] is None


def test_feed_does_not_return_own_household_listings(client):
    """Own household's listings never appear in the feed (visibility helper rule)."""
    # Create an item + listing for the caller's own household.
    item = client.post(
        "/api/v1/community/items", json={"name": "My Drill", "category": "tools"},
    ).json()
    client.post(
        "/api/v1/community/listings",
        json={
            "item_id": item["id"], "allowed_exchange_types": ["borrow"],
            "quantity_available": 1, "community_ids": [], "share_in_radius": False,
        },
    )
    resp = client.get("/api/v1/community/feed")
    assert resp.status_code == 200
    for row in resp.json()["rows"]:
        assert row["listing"]["item"]["name"] != "My Drill"


def test_feed_radius_match_includes_distance(client):
    """Set both households' locations; verify the row carries distance_miles."""
    from app.services.community import items as items_svc
    from app.services.community import listings as listings_svc
    from tests.conftest import set_household_location
    with SessionLocal() as db:
        first_h = db.get(Household, DEV_HOUSEHOLD_ID)
        second = db.query(User).filter(User.email == "second@frugal-living.local").one()
        second_household = db.query(Household).filter(Household.name == "Second Household").one()
        set_household_location(db, first_h, 40.6782, -73.9442)
        set_household_location(db, second_household, 40.6796, -73.9442)
        item = items_svc.create_item(
            db, household=second_household, user=second, name="Radius Item", quantity=1,
        )
        listings_svc.create_listing(
            db, household=second_household, user=second, item_id=item.id,
            allowed_exchange_types=["borrow"], quantity_available=1,
            community_ids=[], share_in_radius=True, share_radius_miles=5,
        )
        db.commit()
    resp = client.get("/api/v1/community/feed")
    assert resp.status_code == 200
    found = next(
        (r for r in resp.json()["rows"] if r["listing"]["item"]["name"] == "Radius Item"),
        None,
    )
    assert found is not None
    assert found["distance_miles"] is not None
    assert 0.0 <= found["distance_miles"] <= 1.0


def test_feed_filters_by_community_id(client):
    listing_id = _make_listing_in_other_household_shared_to_caller()
    # Get caller's communities; find the feed-c one
    mine = client.get("/api/v1/community/communities/mine").json()
    feed_c = next(m for m in mine["memberships"] if m["community"]["slug"] == "feed-c")
    resp = client.get(
        f"/api/v1/community/feed?community_id={feed_c['community']['id']}"
    )
    assert resp.status_code == 200
    ids = [r["listing"]["id"] for r in resp.json()["rows"]]
    assert str(listing_id) in ids


def test_feed_empty_when_caller_unconnected(client):
    resp = client.get("/api/v1/community/feed")
    assert resp.status_code == 200
    # No listings set up for this test → empty rows.
    assert resp.json()["rows"] == []


def test_feed_category_filter(client):
    """Regression: ?category=... must not raise a duplicate-alias 500.
    Verifies the feed correctly applies category filtering through the visibility helper."""
    from app.services.community import items as items_svc
    from app.services.community import listings as listings_svc

    listing_id = _make_listing_in_other_household_shared_to_caller()
    # Create another listing with a different category in the same community.
    with SessionLocal() as db:
        second = db.query(User).filter(User.email == "second@frugal-living.local").one()
        second_household = db.query(Household).filter(Household.name == "Second Household").one()
        from app.models.community import Community
        c = db.query(Community).filter_by(slug="feed-c").one()
        book_item = items_svc.create_item(
            db, household=second_household, user=second, name="A Book", quantity=1,
            category="books",
        )
        book_listing = listings_svc.create_listing(
            db, household=second_household, user=second, item_id=book_item.id,
            allowed_exchange_types=["borrow"], quantity_available=1,
            community_ids=[c.id], share_in_radius=False,
        )
        db.commit()
        book_listing_id = book_listing.id

    # Filter to tools category — the original listing was created without an explicit
    # category in _make_listing_in_other_household_shared_to_caller; default is "other".
    resp = client.get("/api/v1/community/feed?category=books")
    assert resp.status_code == 200, resp.text
    ids = [r["listing"]["id"] for r in resp.json()["rows"]]
    assert str(book_listing_id) in ids
    assert str(listing_id) not in ids  # category filter excludes the "other" listing
