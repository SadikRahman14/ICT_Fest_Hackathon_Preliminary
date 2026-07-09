from datetime import datetime

from fastapi.testclient import TestClient

from .conftest import future_time


def test_register_new_org(api):
    org = f"company-{datetime.now().timestamp()}"

    r = api.post(
        "/auth/register",
        json={
            "org_name": org,
            "username": "alice",
            "password": "password123",
        },
    )

    assert r.status_code == 201

    body = r.json()

    assert body["role"] == "admin"
    assert body["username"] == "alice"
    assert "user_id" in body
    assert "org_id" in body


def test_register_existing_org_becomes_member(api):
    org = f"company-{datetime.now().timestamp()}"

    admin = api.post(
        "/auth/register",
        json={
            "org_name": org,
            "username": "admin",
            "password": "password123",
        },
    )

    assert admin.status_code == 201

    member = api.post(
        "/auth/register",
        json={
            "org_name": org,
            "username": "bob",
            "password": "password123",
        },
    )

    assert member.status_code == 201
    assert member.json()["role"] == "member"


def test_duplicate_username_same_org(api):
    org = f"company-{datetime.now().timestamp()}"

    api.post(
        "/auth/register",
        json={
            "org_name": org,
            "username": "alice",
            "password": "password123",
        },
    )

    r = api.post(
        "/auth/register",
        json={
            "org_name": org,
            "username": "alice",
            "password": "anotherpassword",
        },
    )

    assert r.status_code == 409
    assert r.json()["code"] == "USERNAME_TAKEN"


def test_same_username_different_org(api):
    org1 = f"org1-{datetime.now().timestamp()}"
    org2 = f"org2-{datetime.now().timestamp()}"

    r1 = api.post(
        "/auth/register",
        json={
            "org_name": org1,
            "username": "alice",
            "password": "password123",
        },
    )

    r2 = api.post(
        "/auth/register",
        json={
            "org_name": org2,
            "username": "alice",
            "password": "password123",
        },
    )

    assert r1.status_code == 201
    assert r2.status_code == 201


def test_login_success(api, register_admin):
    r = api.post(
        "/auth/login",
        json={
            "org_name": register_admin["org"],
            "username": register_admin["username"],
            "password": register_admin["password"],
        },
    )

    assert r.status_code == 200

    body = r.json()

    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"


def test_login_wrong_password(api, register_admin):
    r = api.post(
        "/auth/login",
        json={
            "org_name": register_admin["org"],
            "username": register_admin["username"],
            "password": "wrongpassword",
        },
    )

    assert r.status_code == 401


def test_login_unknown_org(api):
    r = api.post(
        "/auth/login",
        json={
            "org_name": "does-not-exist",
            "username": "alice",
            "password": "password123",
        },
    )

    assert r.status_code == 401


def test_logout_invalidates_token(api, admin_headers):
    logout = api.post(
        "/auth/logout",
        headers=admin_headers,
    )

    assert logout.status_code == 200

    r = api.get(
        "/rooms",
        headers=admin_headers,
    )

    assert r.status_code == 401


def test_refresh_returns_new_tokens(api, register_admin):
    login = api.post(
        "/auth/login",
        json={
            "org_name": register_admin["org"],
            "username": register_admin["username"],
            "password": register_admin["password"],
        },
    )

    refresh_token = login.json()["refresh_token"]

    refresh = api.post(
        "/auth/refresh",
        json={
            "refresh_token": refresh_token,
        },
    )

    assert refresh.status_code == 200

    body = refresh.json()

    assert "access_token" in body
    assert "refresh_token" in body

    assert body["access_token"] != login.json()["access_token"]
    assert body["refresh_token"] != refresh_token


def test_refresh_token_single_use(api, register_admin):
    login = api.post(
        "/auth/login",
        json={
            "org_name": register_admin["org"],
            "username": register_admin["username"],
            "password": register_admin["password"],
        },
    )

    refresh_token = login.json()["refresh_token"]

    first = api.post(
        "/auth/refresh",
        json={
            "refresh_token": refresh_token,
        },
    )

    assert first.status_code == 200

    second = api.post(
        "/auth/refresh",
        json={
            "refresh_token": refresh_token,
        },
    )

    assert second.status_code == 401


def test_access_without_token(api):
    r = api.get("/rooms")

    assert r.status_code == 401


def test_invalid_token(api):
    r = api.get(
        "/rooms",
        headers={
            "Authorization": "Bearer invalid.token.value"
        },
    )

    assert r.status_code == 401


def test_wrong_token_type(api, register_admin):
    login = api.post(
        "/auth/login",
        json={
            "org_name": register_admin["org"],
            "username": register_admin["username"],
            "password": register_admin["password"],
        },
    )

    refresh = login.json()["refresh_token"]

    r = api.get(
        "/rooms",
        headers={
            "Authorization": f"Bearer {refresh}"
        },
    )

    assert r.status_code == 401