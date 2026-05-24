"""End-to-end tests for the join-request endpoints. The DEV_USER_ID acts as the
community owner via the conftest auth override; a second seeded user requests
to join (created via the service layer for the test setup)."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models.community import CommunityJoinRequest, CommunityMember
from app.models.core import User


@pytest.fixture
def client():
    return TestClient(app)


def _make_community(client, slug="js-1"):
    c = client.post(
        "/api/v1/community/communities", json={"slug": slug, "name": slug},
    ).json()
    return c


def _second_user():
    with SessionLocal() as db:
        return db.query(User).filter(User.email == "second@frugal-living.local").one()


def test_request_to_join_via_service_then_owner_lists_pending(client):
    c = _make_community(client, "js-2")
    # The conftest auth override makes the API caller the OWNER. A second user
    # requests via the service layer (the API would require their own session).
    second = _second_user()
    from app.services.community import communities as community_svc
    from app.services.community import join_requests as jr_svc
    with SessionLocal() as db:
        community = community_svc.get_community_or_404(db, uuid.UUID(c["id"]))
        jr_svc.request_to_join(db, user=db.get(User, second.id), community=community)
        db.commit()

    resp = client.get(f"/api/v1/community/communities/{c['id']}/join-requests")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"


def test_owner_approve_creates_membership(client):
    c = _make_community(client, "js-3")
    second = _second_user()
    from app.services.community import communities as community_svc
    from app.services.community import join_requests as jr_svc
    with SessionLocal() as db:
        community = community_svc.get_community_or_404(db, uuid.UUID(c["id"]))
        req = jr_svc.request_to_join(db, user=db.get(User, second.id), community=community)
        db.commit()
        req_id = req.id
    resp = client.post(
        f"/api/v1/community/communities/{c['id']}/join-requests/{req_id}/approve",
    )
    assert resp.status_code == 200
    with SessionLocal() as db:
        membership = db.query(CommunityMember).filter_by(
            community_id=uuid.UUID(c["id"]), user_id=second.id,
        ).one()
        assert membership.role == "member"


def test_approve_already_decided_returns_409(client):
    c = _make_community(client, "js-4")
    second = _second_user()
    from app.services.community import communities as community_svc
    from app.services.community import join_requests as jr_svc
    with SessionLocal() as db:
        community = community_svc.get_community_or_404(db, uuid.UUID(c["id"]))
        req = jr_svc.request_to_join(db, user=db.get(User, second.id), community=community)
        db.commit()
        req_id = req.id
    first = client.post(
        f"/api/v1/community/communities/{c['id']}/join-requests/{req_id}/approve",
    )
    assert first.status_code == 200
    second_call = client.post(
        f"/api/v1/community/communities/{c['id']}/join-requests/{req_id}/approve",
    )
    assert second_call.status_code == 409


def test_decline_request(client):
    c = _make_community(client, "js-5")
    second = _second_user()
    from app.services.community import communities as community_svc
    from app.services.community import join_requests as jr_svc
    with SessionLocal() as db:
        community = community_svc.get_community_or_404(db, uuid.UUID(c["id"]))
        req = jr_svc.request_to_join(db, user=db.get(User, second.id), community=community)
        db.commit()
        req_id = req.id
    resp = client.post(
        f"/api/v1/community/communities/{c['id']}/join-requests/{req_id}/decline",
        json={"note": "not yet"},
    )
    assert resp.status_code == 200
    with SessionLocal() as db:
        assert db.get(CommunityJoinRequest, req_id).status == "declined"


def test_self_request_via_endpoint_409_if_already_member(client):
    """The endpoint POST /join-requests asks the active user (the caller via the
    auth override) to request to join — but the caller is already the owner."""
    c = _make_community(client, "js-6")
    resp = client.post(f"/api/v1/community/communities/{c['id']}/join-requests")
    # Caller is already a member (owner) → 409.
    assert resp.status_code == 409
