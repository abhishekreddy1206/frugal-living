"""Tests for the communities service."""

from __future__ import annotations

import pytest

from app.auth import DEV_USER_ID
from app.models.community import CommunityMember
from app.models.core import AuditLog, Event, User
from app.services.community import communities as svc
from app.services.community.communities import (
    CommunitySlugTaken,
    NotACommunityMember,
)


def _user(db):
    return db.get(User, DEV_USER_ID)


def test_create_community_makes_creator_owner(db):
    user = _user(db)
    c = svc.create_community(
        db,
        creator_user=user,
        slug="park-slope-tools",
        name="Park Slope Tools",
    )
    assert c.slug == "park-slope-tools"
    member = db.query(CommunityMember).filter_by(community_id=c.id, user_id=user.id).one()
    assert member.role == "owner"
    assert db.query(Event).filter_by(event_type="community.community.created").count() == 1
    assert db.query(AuditLog).filter_by(action="community.community.created").count() == 1


def test_create_community_rejects_duplicate_slug(db):
    user = _user(db)
    svc.create_community(db, creator_user=user, slug="dup", name="A")
    with pytest.raises(CommunitySlugTaken):
        svc.create_community(db, creator_user=user, slug="dup", name="B")


def test_get_by_slug_returns_none_when_missing(db):
    assert svc.get_community_by_slug(db, "nope") is None


def test_get_by_slug_excludes_soft_deleted(db):
    user = _user(db)
    c = svc.create_community(db, creator_user=user, slug="gone", name="Gone")
    svc.soft_delete_community(db, owner_user=user, community=c)
    assert svc.get_community_by_slug(db, "gone") is None


def test_soft_delete_requires_owner(db):
    user = _user(db)
    c = svc.create_community(db, creator_user=user, slug="o1", name="o1")
    # Demote ourselves to member so the owner-check fails.
    member = db.query(CommunityMember).filter_by(community_id=c.id, user_id=user.id).one()
    member.role = "member"
    db.flush()
    with pytest.raises(NotACommunityMember):
        svc.soft_delete_community(db, owner_user=user, community=c)


def test_leave_community_removes_membership(db):
    user = _user(db)
    c = svc.create_community(db, creator_user=user, slug="l1", name="l1")
    # The owner can't leave the *only* owner row (409); demote to member-only first.
    member = db.query(CommunityMember).filter_by(community_id=c.id, user_id=user.id).one()
    member.role = "member"
    db.flush()
    svc.leave_community(db, user=user, community=c)
    assert db.query(CommunityMember).filter_by(community_id=c.id, user_id=user.id).count() == 0


def test_owner_cannot_leave_if_sole_owner(db):
    user = _user(db)
    c = svc.create_community(db, creator_user=user, slug="o2", name="o2")
    from app.services.community.communities import SoleOwnerCannotLeave

    with pytest.raises(SoleOwnerCannotLeave):
        svc.leave_community(db, user=user, community=c)
