"""End-to-end tests for listing endpoints."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _make_item(client, name="Drill", category="tools", quantity=1):
    return client.post(
        "/api/v1/community/items",
        json={"name": name, "category": category, "quantity": quantity},
    ).json()


def test_create_listing_basic(client):
    item = _make_item(client)
    resp = client.post(
        "/api/v1/community/listings",
        json={
            "item_id": item["id"],
            "allowed_exchange_types": ["borrow"],
            "quantity_available": 1,
            "community_ids": [],
            "share_in_radius": False,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["allowed_exchange_types"] == ["borrow"]
    assert body["item"]["name"] == "Drill"


def test_create_listing_rejects_quantity_too_high(client):
    item = _make_item(client, quantity=2)
    resp = client.post(
        "/api/v1/community/listings",
        json={
            "item_id": item["id"], "allowed_exchange_types": ["borrow"],
            "quantity_available": 5,  # > item.quantity
            "community_ids": [], "share_in_radius": False,
        },
    )
    assert resp.status_code == 422


def test_create_listing_rejects_unknown_item(client):
    resp = client.post(
        "/api/v1/community/listings",
        json={
            "item_id": str(uuid.uuid4()), "allowed_exchange_types": ["gift"],
            "quantity_available": 1, "community_ids": [], "share_in_radius": False,
        },
    )
    assert resp.status_code == 404


def test_list_mine(client):
    item = _make_item(client)
    client.post(
        "/api/v1/community/listings",
        json={
            "item_id": item["id"], "allowed_exchange_types": ["borrow"],
            "quantity_available": 1, "community_ids": [], "share_in_radius": False,
        },
    )
    resp = client.get("/api/v1/community/listings/mine")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_patch_listing(client):
    item = _make_item(client)
    created = client.post(
        "/api/v1/community/listings",
        json={
            "item_id": item["id"], "allowed_exchange_types": ["borrow"],
            "quantity_available": 1, "community_ids": [], "share_in_radius": False,
        },
    ).json()
    resp = client.patch(
        f"/api/v1/community/listings/{created['id']}",
        json={"availability_status": "paused"},
    )
    assert resp.status_code == 200
    assert resp.json()["availability_status"] == "paused"


def test_delete_listing(client):
    item = _make_item(client)
    created = client.post(
        "/api/v1/community/listings",
        json={
            "item_id": item["id"], "allowed_exchange_types": ["borrow"],
            "quantity_available": 1, "community_ids": [], "share_in_radius": False,
        },
    ).json()
    resp = client.delete(f"/api/v1/community/listings/{created['id']}")
    assert resp.status_code == 200
    assert client.get("/api/v1/community/listings/mine").json() == []


def test_get_listing_owner_sees_own(client):
    """The owning household can always GET its own listing."""
    item = _make_item(client)
    created = client.post(
        "/api/v1/community/listings",
        json={
            "item_id": item["id"], "allowed_exchange_types": ["borrow"],
            "quantity_available": 1, "community_ids": [], "share_in_radius": False,
        },
    ).json()
    resp = client.get(f"/api/v1/community/listings/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_listing_unrelated_household_gets_404(client):
    """A second household with no shared community / no radius overlap → 404."""
    from app.db import SessionLocal
    from app.models.core import Household, User
    from app.services.community import items as items_svc
    from app.services.community import listings as listings_svc
    with SessionLocal() as db:
        second = db.query(User).filter(User.email == "second@frugal-living.local").one()
        second_household = db.query(Household).filter(Household.name == "Second Household").one()
        item = items_svc.create_item(db, household=second_household, user=second, name="X")
        listing = listings_svc.create_listing(
            db, household=second_household, user=second, item_id=item.id,
            allowed_exchange_types=["borrow"], quantity_available=1,
            community_ids=[], share_in_radius=False,
        )
        db.commit()
        listing_id = listing.id
    # The conftest auth override makes the caller the DEV household — no shared community,
    # no radius — must be invisible.
    resp = client.get(f"/api/v1/community/listings/{listing_id}")
    assert resp.status_code == 404


def test_get_listing_visible_via_shared_community(client):
    """A listing in a community the caller joined → 200."""
    from app.auth import DEV_USER_ID
    from app.db import SessionLocal
    from app.models.community import CommunityMember
    from app.models.core import Household, User
    from app.services.community import communities as community_svc
    from app.services.community import items as items_svc
    from app.services.community import listings as listings_svc
    with SessionLocal() as db:
        caller = db.get(User, DEV_USER_ID)
        second = db.query(User).filter(User.email == "second@frugal-living.local").one()
        second_household = db.query(Household).filter(Household.name == "Second Household").one()
        c = community_svc.create_community(
            db, creator_user=second, slug="visible-c", name="Visible",
        )
        db.add(CommunityMember(community_id=c.id, user_id=caller.id, role="member"))
        db.flush()
        item = items_svc.create_item(db, household=second_household, user=second, name="Tent")
        listing = listings_svc.create_listing(
            db, household=second_household, user=second, item_id=item.id,
            allowed_exchange_types=["borrow"], quantity_available=1,
            community_ids=[c.id], share_in_radius=False,
        )
        db.commit()
        listing_id = listing.id
    resp = client.get(f"/api/v1/community/listings/{listing_id}")
    assert resp.status_code == 200
    assert resp.json()["item"]["name"] == "Tent"
