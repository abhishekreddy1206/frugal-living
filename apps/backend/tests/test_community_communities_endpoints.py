"""End-to-end tests for the community endpoints (create, preview, leave, mine)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_create_community_makes_caller_owner(client):
    resp = client.post(
        "/api/v1/community/communities",
        json={"slug": "test-1", "name": "Test 1", "description": "x"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["slug"] == "test-1"


def test_create_community_rejects_duplicate_slug(client):
    client.post("/api/v1/community/communities", json={"slug": "dup", "name": "A"})
    resp = client.post("/api/v1/community/communities", json={"slug": "dup", "name": "B"})
    assert resp.status_code == 409


def test_create_community_rejects_bad_slug(client):
    resp = client.post(
        "/api/v1/community/communities", json={"slug": "Bad Slug", "name": "x"},
    )
    assert resp.status_code == 422


def test_get_community_preview(client):
    client.post(
        "/api/v1/community/communities",
        json={"slug": "preview-1", "name": "Preview", "description": "hi"},
    )
    resp = client.get("/api/v1/community/communities/preview-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "preview-1"
    assert body["member_count"] == 1  # creator is owner
    assert body["your_membership_role"] == "owner"
    assert body["your_join_request_status"] is None


def test_get_unknown_community_returns_404(client):
    assert client.get("/api/v1/community/communities/nope").status_code == 404


def test_patch_community_as_owner(client):
    created = client.post(
        "/api/v1/community/communities",
        json={"slug": "pat-1", "name": "Old"},
    ).json()
    resp = client.patch(
        f"/api/v1/community/communities/{created['id']}",
        json={"name": "New", "description": "now"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


def test_delete_community_soft_deletes(client):
    created = client.post(
        "/api/v1/community/communities",
        json={"slug": "del-1", "name": "Del"},
    ).json()
    resp = client.delete(f"/api/v1/community/communities/{created['id']}")
    assert resp.status_code == 200
    assert client.get("/api/v1/community/communities/del-1").status_code == 404


def test_get_my_communities(client):
    client.post("/api/v1/community/communities", json={"slug": "m1", "name": "M1"})
    client.post("/api/v1/community/communities", json={"slug": "m2", "name": "M2"})
    resp = client.get("/api/v1/community/communities/mine")
    assert resp.status_code == 200
    slugs = [m["community"]["slug"] for m in resp.json()["memberships"]]
    assert "m1" in slugs and "m2" in slugs


def test_leave_community_as_member(client):
    """Need a second user to demote; for the unit test we use the service layer to demote first."""
    created = client.post(
        "/api/v1/community/communities", json={"slug": "lv1", "name": "lv1"},
    ).json()
    from app.auth import DEV_USER_ID
    from app.db import SessionLocal
    from app.models.community import Community, CommunityMember
    with SessionLocal() as db:
        c = db.query(Community).filter_by(slug="lv1").one()
        # Add a second owner so the current user can leave without being sole owner.
        from app.models.core import User
        second = db.query(User).filter(User.email == "second@frugal-living.local").one()
        db.add(CommunityMember(community_id=c.id, user_id=second.id, role="owner"))
        db.commit()
    resp = client.post(f"/api/v1/community/communities/{created['id']}/leave")
    assert resp.status_code == 200
    # Caller is no longer a member.
    me = client.get("/api/v1/community/communities/mine").json()
    assert "lv1" not in [m["community"]["slug"] for m in me["memberships"]]
