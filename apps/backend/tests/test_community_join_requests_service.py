"""Tests for the join-requests service. Idempotency on approve is the key safety property."""
from __future__ import annotations

import uuid

import pytest

from app.auth import DEV_USER_ID
from app.models.community import (
    CommunityMember,
)
from app.models.core import AuditLog, Event, User
from app.services.community import communities as community_svc
from app.services.community import join_requests as svc
from app.services.community.join_requests import (
    AlreadyAMember,
    AlreadyDecided,
    AlreadyPending,
    JoinRequestNotFound,
)


def _make_community_and_second_user(db):
    """Create a community owned by DEV_USER and a second user who'll request to join."""
    owner = db.get(User, DEV_USER_ID)
    c = community_svc.create_community(db, creator_user=owner, slug="js1", name="Join Suite 1")
    requester = User(
        id=uuid.uuid4(),
        email=f"req-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Requester",
    )
    db.add(requester)
    db.flush()
    return c, owner, requester


def test_request_to_join_creates_pending(db):
    c, _, requester = _make_community_and_second_user(db)
    req = svc.request_to_join(db, user=requester, community=c)
    assert req.status == "pending"
    assert db.query(Event).filter_by(event_type="community.join_request.requested").count() == 1


def test_request_to_join_rejects_duplicate_pending(db):
    c, _, requester = _make_community_and_second_user(db)
    svc.request_to_join(db, user=requester, community=c)
    with pytest.raises(AlreadyPending):
        svc.request_to_join(db, user=requester, community=c)


def test_request_to_join_rejects_existing_member(db):
    c, owner, _ = _make_community_and_second_user(db)
    # Owner is already a member.
    with pytest.raises(AlreadyAMember):
        svc.request_to_join(db, user=owner, community=c)


def test_approve_request_creates_membership_and_is_idempotent(db):
    c, owner, requester = _make_community_and_second_user(db)
    req = svc.request_to_join(db, user=requester, community=c)
    member = svc.approve_request(db, owner_user=owner, request=req)
    assert member.role == "member"
    db.refresh(req)
    assert req.status == "approved"
    # Second approve raises (request is no longer pending).
    with pytest.raises(AlreadyDecided):
        svc.approve_request(db, owner_user=owner, request=req)
    # Audit row was written.
    assert db.query(AuditLog).filter_by(action="community.join_request.approved").count() == 1


def test_decline_request(db):
    c, owner, requester = _make_community_and_second_user(db)
    req = svc.request_to_join(db, user=requester, community=c)
    svc.decline_request(db, owner_user=owner, request=req, note="not yet")
    db.refresh(req)
    assert req.status == "declined"
    assert req.decision_note == "not yet"
    # The user has no membership.
    assert (
        db.query(CommunityMember)
        .filter_by(community_id=c.id, user_id=requester.id)
        .count() == 0
    )


def test_decline_already_decided_request_is_rejected(db):
    c, owner, requester = _make_community_and_second_user(db)
    req = svc.request_to_join(db, user=requester, community=c)
    svc.decline_request(db, owner_user=owner, request=req)
    with pytest.raises(AlreadyDecided):
        svc.decline_request(db, owner_user=owner, request=req)


def test_withdraw_request(db):
    c, _, requester = _make_community_and_second_user(db)
    req = svc.request_to_join(db, user=requester, community=c)
    svc.withdraw_request(db, user=requester, request=req)
    db.refresh(req)
    assert req.status == "withdrawn"


def test_list_pending_excludes_decided(db):
    c, owner, requester = _make_community_and_second_user(db)
    svc.request_to_join(db, user=requester, community=c)
    other_user = User(id=uuid.uuid4(), email=f"o-{uuid.uuid4().hex[:6]}@x.com", display_name="o")
    db.add(other_user)
    db.flush()
    req2 = svc.request_to_join(db, user=other_user, community=c)
    svc.decline_request(db, owner_user=owner, request=req2)
    pending = svc.list_pending_requests(db, community=c)
    assert len(pending) == 1


def test_get_request_or_404(db):
    with pytest.raises(JoinRequestNotFound):
        svc.get_request_or_404(db, uuid.uuid4())
