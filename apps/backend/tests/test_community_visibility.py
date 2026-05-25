"""Tests for the canonical visibility helper. This is the security gate.

Audit fixes #1, #2, #4 (cascade, read-time membership check, is_active/deleted filters)
all assert here.
"""
from __future__ import annotations

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.community import CommunityMember
from app.models.core import Household, User
from app.services.community import communities as community_svc
from app.services.community import items as items_svc
from app.services.community import listings as listings_svc
from app.services.community import visibility


def _create_shared_listing(
    db, *, owner_household, owner_user, community=None, share_in_radius=False, share_radius_miles=None,
):
    item = items_svc.create_item(
        db, household=owner_household, user=owner_user, name="X", quantity=1,
    )
    listing = listings_svc.create_listing(
        db, household=owner_household, user=owner_user, item_id=item.id,
        allowed_exchange_types=["borrow"], quantity_available=1,
        community_ids=[community.id] if community else [],
        share_in_radius=share_in_radius,
        share_radius_miles=share_radius_miles,
    )
    return item, listing


# ---------- Community path ----------

def test_shared_community_visible_to_co_member(db, second_household, second_user):
    """Both households' users are members of community C; viewer sees lister's listing."""
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    c = community_svc.create_community(db, creator_user=owner, slug="cv1", name="cv1")
    # second_user joins by direct insertion (skipping the join-request flow for the unit test)
    db.add(CommunityMember(community_id=c.id, user_id=second_user.id, role="member"))
    db.flush()
    _, listing = _create_shared_listing(db, owner_household=owner_h, owner_user=owner, community=c)

    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id in [r.id for r in visible]


def test_listing_not_visible_after_lister_leaves_community(db, second_household, second_user):
    """Audit fix #2 — read-time membership check. Lister leaves community → no longer visible."""
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    c = community_svc.create_community(db, creator_user=owner, slug="cv2", name="cv2")
    db.add(CommunityMember(community_id=c.id, user_id=second_user.id, role="member"))
    db.flush()
    _, listing = _create_shared_listing(db, owner_household=owner_h, owner_user=owner, community=c)

    # Lister leaves (owner is sole owner, so we delete via membership delete directly for the test).
    owner_membership = (
        db.query(CommunityMember).filter_by(community_id=c.id, user_id=owner.id).one()
    )
    db.delete(owner_membership)
    db.flush()

    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]


def test_listing_not_visible_in_soft_deleted_community(db, second_household, second_user):
    """Audit fix #4 — community.deleted_at IS NULL filter."""
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    c = community_svc.create_community(db, creator_user=owner, slug="cv3", name="cv3")
    db.add(CommunityMember(community_id=c.id, user_id=second_user.id, role="member"))
    db.flush()
    _, listing = _create_shared_listing(db, owner_household=owner_h, owner_user=owner, community=c)
    community_svc.soft_delete_community(db, owner_user=owner, community=c)

    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]


def test_listing_not_visible_when_lister_deactivated(db, second_household, second_user):
    """Audit fix #4 — users.is_active = true filter on the membership join."""
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    c = community_svc.create_community(db, creator_user=owner, slug="cv4", name="cv4")
    db.add(CommunityMember(community_id=c.id, user_id=second_user.id, role="member"))
    db.flush()
    _, listing = _create_shared_listing(db, owner_household=owner_h, owner_user=owner, community=c)

    owner.is_active = False
    db.flush()

    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]


def test_listing_not_visible_when_no_overlap(db, second_household, second_user):
    """Lister is in community A; viewer is in community B; no radius — not visible."""
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    a = community_svc.create_community(db, creator_user=owner, slug="cv5a", name="cv5a")
    community_svc.create_community(db, creator_user=second_user, slug="cv5b", name="cv5b")
    _, listing = _create_shared_listing(db, owner_household=owner_h, owner_user=owner, community=a)
    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]


def test_viewer_does_not_see_own_household_listings(db):
    """You don't browse your own listings on the feed."""
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    c = community_svc.create_community(db, creator_user=owner, slug="cv6", name="cv6")
    _, listing = _create_shared_listing(db, owner_household=owner_h, owner_user=owner, community=c)
    visible = visibility.listings_visible_to(
        db, viewer_household=owner_h, viewer_user=owner,
    ).all()
    assert listing.id not in [r.id for r in visible]


# ---------- Radius path ----------

def test_radius_visible_within_distance(db, second_household, second_user):
    from tests.conftest import set_household_location
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    # Two points ~0.1 mi apart in Brooklyn
    set_household_location(db, owner_h, 40.6782, -73.9442)
    set_household_location(db, second_household, 40.6796, -73.9442)

    _, listing = _create_shared_listing(
        db, owner_household=owner_h, owner_user=owner,
        share_in_radius=True, share_radius_miles=5,
    )
    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id in [r.id for r in visible]


def test_radius_not_visible_when_far(db, second_household, second_user):
    from tests.conftest import set_household_location
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    # Brooklyn and Boston ≈ 190 mi
    set_household_location(db, owner_h, 40.6782, -73.9442)
    set_household_location(db, second_household, 42.3601, -71.0589)

    _, listing = _create_shared_listing(
        db, owner_household=owner_h, owner_user=owner,
        share_in_radius=True, share_radius_miles=5,
    )
    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]


def test_radius_not_visible_when_lister_opted_out(db, second_household, second_user):
    """share_in_radius=False means even an adjacent household can't see via radius."""
    from tests.conftest import set_household_location
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    set_household_location(db, owner_h, 40.6782, -73.9442)
    set_household_location(db, second_household, 40.6796, -73.9442)

    _, listing = _create_shared_listing(
        db, owner_household=owner_h, owner_user=owner, share_in_radius=False,
    )
    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]


def test_radius_not_visible_when_viewer_has_no_location(db, second_household, second_user):
    from tests.conftest import set_household_location
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    set_household_location(db, owner_h, 40.6782, -73.9442)
    # second_household intentionally unset.

    _, listing = _create_shared_listing(
        db, owner_household=owner_h, owner_user=owner,
        share_in_radius=True, share_radius_miles=5,
    )
    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]


# ---------- Item / listing lifecycle ----------

def test_soft_deleted_listing_not_visible(db, second_household, second_user):
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    c = community_svc.create_community(db, creator_user=owner, slug="cv8", name="cv8")
    db.add(CommunityMember(community_id=c.id, user_id=second_user.id, role="member"))
    db.flush()
    _, listing = _create_shared_listing(db, owner_household=owner_h, owner_user=owner, community=c)
    listings_svc.soft_delete_listing(db, household=owner_h, user=owner, listing_id=listing.id)
    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]


def test_paused_listing_not_visible(db, second_household, second_user):
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    c = community_svc.create_community(db, creator_user=owner, slug="cv9", name="cv9")
    db.add(CommunityMember(community_id=c.id, user_id=second_user.id, role="member"))
    db.flush()
    _, listing = _create_shared_listing(db, owner_household=owner_h, owner_user=owner, community=c)
    listings_svc.update_listing(
        db, household=owner_h, user=owner, listing_id=listing.id,
        availability_status="paused",
    )
    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]


def test_listing_not_visible_after_item_soft_delete(db, second_household, second_user):
    """Audit fix #1 — item soft-delete cascades to listing, which then drops from feeds."""
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    c = community_svc.create_community(db, creator_user=owner, slug="cv10", name="cv10")
    db.add(CommunityMember(community_id=c.id, user_id=second_user.id, role="member"))
    db.flush()
    item, listing = _create_shared_listing(
        db, owner_household=owner_h, owner_user=owner, community=c,
    )
    items_svc.soft_delete_item(db, household=owner_h, user=owner, item_id=item.id)
    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]


def test_radius_not_visible_when_lister_deactivated(db, second_household, second_user):
    """Regression: radius path must filter on users.is_active too (audit fix #4 extended)."""
    from tests.conftest import set_household_location
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    set_household_location(db, owner_h, 40.6782, -73.9442)
    set_household_location(db, second_household, 40.6796, -73.9442)

    _, listing = _create_shared_listing(
        db, owner_household=owner_h, owner_user=owner,
        share_in_radius=True, share_radius_miles=5,
    )
    owner.is_active = False
    db.flush()

    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]
