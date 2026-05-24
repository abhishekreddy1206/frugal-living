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
