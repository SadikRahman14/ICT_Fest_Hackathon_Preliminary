from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture
def api():
    return client


def future_time(hours):
    return (
        datetime.now(timezone.utc)
        + timedelta(hours=hours)
    ).replace(
        minute=0,
        second=0,
        microsecond=0
    ).isoformat()


@pytest.fixture
def register_admin(api):
    org = f"org-{datetime.now().timestamp()}"

    r = api.post(
        "/auth/register",
        json={
            "org_name": org,
            "username": "admin",
            "password": "password123",
        },
    )

    assert r.status_code == 201

    return {
        "org": org,
        "username": "admin",
        "password": "password123",
    }


@pytest.fixture
def admin_token(api, register_admin):
    login = api.post(
        "/auth/login",
        json={
            "org_name": register_admin["org"],
            "username": register_admin["username"],
            "password": register_admin["password"],
        },
    )

    assert login.status_code == 200

    return login.json()["access_token"]


@pytest.fixture
def admin_headers(admin_token):
    return {
        "Authorization": f"Bearer {admin_token}"
    }


@pytest.fixture
def room(api, admin_headers):
    r = api.post(
        "/rooms",
        json={
            "name": "Conference Room",
            "capacity": 8,
            "hourly_rate_cents": 1000,
        },
        headers=admin_headers,
    )

    assert r.status_code == 201

    return r.json()


@pytest.fixture
def booking(api, room, admin_headers):
    r = api.post(
        "/bookings",
        json={
            "room_id": room["id"],
            "start_time": future_time(50),
            "end_time": future_time(52),
        },
        headers=admin_headers,
    )

    assert r.status_code == 201

    return r.json()