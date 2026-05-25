"""End-to-end tests for admin moderation endpoints (communities + listings)."""
from __future__ import annotations

import uuid
from datetime import UTC

from fastapi.testclient import TestClient

from app.auth import DEV_USER_ID
from app.db import SessionLocal
from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers that create data via the API as the default DEV user (owner of
# DEV_HOUSEHOLD). The _auth_override autouse fixture is already active when
# these are called (unless the caller has already switched via as_moderator /
# as_admin), so create data BEFORE switching roles in tests where it matters.
# ---------------------------------------------------------------------------

def _make_community(name: str | None = None) -> dict:
    slug = f"slug-{uuid.uuid4().hex[:6]}"
    name = name or f"Community-{slug}"
    resp = client.post(
        "/api/v1/community/communities",
        json={"slug": slug, "name": name},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _make_listing() -> dict:
    item_resp = client.post(
        "/api/v1/community/items",
        json={"name": "Drill", "category": "tools", "quantity": 1},
    )
    assert item_resp.status_code == 200, item_resp.text
    item = item_resp.json()
    listing_resp = client.post(
        "/api/v1/community/listings",
        json={
            "item_id": item["id"],
            "allowed_exchange_types": ["borrow"],
            "quantity_available": 1,
            "community_ids": [],
            "share_in_radius": False,
        },
    )
    assert listing_resp.status_code == 200, listing_resp.text
    return listing_resp.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_list_communities_moderator(as_moderator):
    # Community is created before as_moderator overrides get_current_user.
    # We rely on the fact that _make_community uses the default DEV user via the
    # autouse _auth_override, which is replaced by as_moderator for the GET.
    # But as_moderator is already active in the fixture order by the time the
    # test body runs — so we must create via a DEV-user client call before
    # activating the moderator override.  The conftest as_moderator fixture
    # overrides at fixture time, so we create data inside the test body while
    # the override is already in place.  Since the moderator has no household
    # membership, we need the community creation to go through a DIFFERENT
    # invocation without the moderator override.
    # Solution: create community before fixtures, or use SessionLocal directly.
    slug = f"alpha-{uuid.uuid4().hex[:6]}"
    with SessionLocal() as db:
        from app.models.community import Community
        c = Community(name="Alpha", slug=slug, created_by_user_id=DEV_USER_ID)
        db.add(c)
        db.commit()
    r = client.get("/api/v1/admin/communities")
    assert r.status_code == 200
    assert any(row["name"] == "Alpha" for row in r.json())


def test_list_listings_moderator(as_moderator):
    with SessionLocal() as db:
        from app.models.community import CommunityItem, Listing
        item = CommunityItem(
            household_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            name="Drill", category="tools", quantity=1,
            created_by_user_id=DEV_USER_ID,
        )
        db.add(item)
        db.flush()
        listing = Listing(
            item_id=item.id,
            created_by_user_id=DEV_USER_ID,
            availability_status="available",
            allowed_exchange_types=["borrow"],
            quantity_available=1,
        )
        db.add(listing)
        db.commit()
        listing_id = listing.id
    r = client.get("/api/v1/admin/listings")
    assert r.status_code == 200
    rows = r.json()
    assert any(str(row["id"]) == str(listing_id) for row in rows)
    # The new item_name field surfaces the searchable label
    assert any(row.get("item_name") == "Drill" for row in rows)


def test_take_down_listing(as_moderator):
    with SessionLocal() as db:
        from app.models.community import CommunityItem, Listing
        item = CommunityItem(
            household_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            name="Saw", category="tools", quantity=1,
            created_by_user_id=DEV_USER_ID,
        )
        db.add(item)
        db.flush()
        listing = Listing(
            item_id=item.id, created_by_user_id=DEV_USER_ID,
            availability_status="available",
            allowed_exchange_types=["borrow"], quantity_available=1,
        )
        db.add(listing)
        db.commit()
        lid = listing.id

    r = client.post(
        f"/api/v1/admin/listings/{lid}/take-down",
        json={"reason": "off-platform contact info"},
    )
    assert r.status_code == 204
    with SessionLocal() as db:
        from app.models.community import Listing
        row = db.get(Listing, lid)
        assert row is not None
        assert row.deleted_at is not None
        assert row.availability_status == "removed"


def test_restore_listing(as_moderator):
    with SessionLocal() as db:
        from datetime import datetime

        from app.models.community import CommunityItem, Listing
        item = CommunityItem(
            household_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            name="Wrench", category="tools", quantity=1,
            created_by_user_id=DEV_USER_ID,
        )
        db.add(item)
        db.flush()
        listing = Listing(
            item_id=item.id, created_by_user_id=DEV_USER_ID,
            availability_status="removed",
            allowed_exchange_types=["borrow"], quantity_available=1,
            deleted_at=datetime.now(UTC),
        )
        db.add(listing)
        db.commit()
        lid = listing.id

    r = client.post(
        f"/api/v1/admin/listings/{lid}/restore",
        json={"reason": "appeal granted"},
    )
    assert r.status_code == 204
    with SessionLocal() as db:
        from app.models.community import Listing
        row = db.get(Listing, lid)
        assert row is not None
        assert row.deleted_at is None
        assert row.availability_status == "available"


def test_take_down_requires_reason(as_moderator):
    with SessionLocal() as db:
        from app.models.community import CommunityItem, Listing
        item = CommunityItem(
            household_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            name="Ladder", category="tools", quantity=1,
            created_by_user_id=DEV_USER_ID,
        )
        db.add(item)
        db.flush()
        listing = Listing(
            item_id=item.id, created_by_user_id=DEV_USER_ID,
            availability_status="available",
            allowed_exchange_types=["borrow"], quantity_available=1,
        )
        db.add(listing)
        db.commit()
        lid = listing.id

    r = client.post(f"/api/v1/admin/listings/{lid}/take-down", json={})
    assert r.status_code == 422


def test_take_down_community(as_moderator):
    with SessionLocal() as db:
        from app.models.community import Community
        c = Community(
            name="ToTakeDown", slug=f"takedown-{uuid.uuid4().hex[:6]}",
            created_by_user_id=DEV_USER_ID,
        )
        db.add(c)
        db.commit()
        cid = c.id

    r = client.post(
        f"/api/v1/admin/communities/{cid}/take-down",
        json={"reason": "abuse reports"},
    )
    assert r.status_code == 204
    with SessionLocal() as db:
        from app.models.community import Community
        row = db.get(Community, cid)
        assert row is not None
        assert row.deleted_at is not None


def test_restore_community(as_moderator):
    from datetime import UTC, datetime
    with SessionLocal() as db:
        from app.models.community import Community
        c = Community(
            name="WasTakenDown", slug=f"restore-{uuid.uuid4().hex[:6]}",
            created_by_user_id=DEV_USER_ID,
            deleted_at=datetime.now(UTC),
        )
        db.add(c)
        db.commit()
        cid = c.id

    r = client.post(
        f"/api/v1/admin/communities/{cid}/restore",
        json={"reason": "appeal granted"},
    )
    assert r.status_code == 204
    with SessionLocal() as db:
        from app.models.community import Community
        row = db.get(Community, cid)
        assert row is not None
        assert row.deleted_at is None


def test_restore_listing_preserves_paused_status(as_moderator):
    """Regression: restore_listing must not overwrite the owner's 'paused' intent."""
    with SessionLocal() as db:
        from app.models.community import CommunityItem, Listing
        item = CommunityItem(
            household_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            name="Sander", category="tools", quantity=1,
            created_by_user_id=DEV_USER_ID,
        )
        db.add(item)
        db.flush()
        listing = Listing(
            item_id=item.id, created_by_user_id=DEV_USER_ID,
            availability_status="paused",  # owner-set, not moderator-set
            allowed_exchange_types=["borrow"], quantity_available=1,
        )
        from datetime import UTC, datetime
        listing.deleted_at = datetime.now(UTC)  # but moderator soft-deleted it
        db.add(listing)
        db.commit()
        lid = listing.id

    r = client.post(
        f"/api/v1/admin/listings/{lid}/restore",
        json={"reason": "back online"},
    )
    assert r.status_code == 204
    with SessionLocal() as db:
        from app.models.community import Listing
        row = db.get(Listing, lid)
        assert row is not None
        assert row.deleted_at is None
        # The "paused" status should survive — only "removed" is reset to "available"
        assert row.availability_status == "paused"


def test_audit_log_recorded_with_reason(as_moderator):
    with SessionLocal() as db:
        from app.models.community import CommunityItem, Listing
        item = CommunityItem(
            household_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            name="Pliers", category="tools", quantity=1,
            created_by_user_id=DEV_USER_ID,
        )
        db.add(item)
        db.flush()
        listing = Listing(
            item_id=item.id, created_by_user_id=DEV_USER_ID,
            availability_status="available",
            allowed_exchange_types=["borrow"], quantity_available=1,
        )
        db.add(listing)
        db.commit()
        lid = listing.id

    client.post(
        f"/api/v1/admin/listings/{lid}/take-down",
        json={"reason": "policy violation"},
    )
    with SessionLocal() as db:
        from app.models.core import AuditLog
        rows = db.query(AuditLog).filter_by(action="admin.listing.taken_down").all()
        assert any(r.payload.get("reason") == "policy violation" for r in rows)


def test_regular_user_cannot_moderate():
    # The default _auth_override makes us the DEV user (role="user").
    with SessionLocal() as db:
        from app.models.community import CommunityItem, Listing
        item = CommunityItem(
            household_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            name="Tape", category="tools", quantity=1,
            created_by_user_id=DEV_USER_ID,
        )
        db.add(item)
        db.flush()
        listing = Listing(
            item_id=item.id, created_by_user_id=DEV_USER_ID,
            availability_status="available",
            allowed_exchange_types=["borrow"], quantity_available=1,
        )
        db.add(listing)
        db.commit()
        lid = listing.id

    r = client.post(
        f"/api/v1/admin/listings/{lid}/take-down",
        json={"reason": "x"},
    )
    assert r.status_code == 403


def test_get_community_detail(as_moderator):
    with SessionLocal() as db:
        from app.models.community import Community
        c = Community(
            name="WithDetail", slug=f"detail-{uuid.uuid4().hex[:6]}",
            created_by_user_id=DEV_USER_ID,
        )
        db.add(c)
        db.commit()
        cid = c.id

    r = client.get(f"/api/v1/admin/communities/{cid}")
    assert r.status_code == 200
    assert r.json()["name"] == "WithDetail"


def test_get_listing_detail(as_moderator):
    with SessionLocal() as db:
        from app.models.community import CommunityItem, Listing
        item = CommunityItem(
            household_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            name="Clamp", category="tools", quantity=1,
            created_by_user_id=DEV_USER_ID,
        )
        db.add(item)
        db.flush()
        listing = Listing(
            item_id=item.id, created_by_user_id=DEV_USER_ID,
            availability_status="available",
            allowed_exchange_types=["borrow"], quantity_available=1,
        )
        db.add(listing)
        db.commit()
        lid = listing.id

    r = client.get(f"/api/v1/admin/listings/{lid}")
    assert r.status_code == 200
    body = r.json()
    assert body["availability_status"] == "available"
