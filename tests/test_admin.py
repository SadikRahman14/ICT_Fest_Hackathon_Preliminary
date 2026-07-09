from datetime import datetime, timedelta, timezone


def future(hours):
    return (
        datetime.now(timezone.utc)
        + timedelta(hours=hours)
    ).replace(
        minute=0,
        second=0,
        microsecond=0,
    ).isoformat()


def test_usage_report_empty(api, room, admin_headers):
    today = (
        datetime.now(timezone.utc)
        + timedelta(days=2)
    ).strftime("%Y-%m-%d")

    r = api.get(
        f"/admin/usage-report?from={today}&to={today}",
        headers=admin_headers,
    )

    assert r.status_code == 200

    body = r.json()

    assert "rooms" in body
    assert len(body["rooms"]) >= 1

    room_data = body["rooms"][0]

    assert room_data["confirmed_bookings"] == 0
    assert room_data["revenue_cents"] == 0


def test_usage_report_after_booking(api, room, admin_headers):
    api.post(
        "/bookings",
        json={
            "room_id": room["id"],
            "start_time": future(50),
            "end_time": future(52),
        },
        headers=admin_headers,
    )

    booking_day = (
        datetime.now(timezone.utc)
        + timedelta(hours=50)
    ).strftime("%Y-%m-%d")

    r = api.get(
        f"/admin/usage-report?from={booking_day}&to={booking_day}",
        headers=admin_headers,
    )

    assert r.status_code == 200

    rooms = r.json()["rooms"]

    room_stats = next(
        x for x in rooms if x["room_id"] == room["id"]
    )

    assert room_stats["confirmed_bookings"] == 1
    assert room_stats["revenue_cents"] == 2000


def test_usage_report_multiple_bookings(api, room, admin_headers):
    api.post(
        "/bookings",
        json={
            "room_id": room["id"],
            "start_time": future(60),
            "end_time": future(62),
        },
        headers=admin_headers,
    )

    api.post(
        "/bookings",
        json={
            "room_id": room["id"],
            "start_time": future(65),
            "end_time": future(66),
        },
        headers=admin_headers,
    )

    day = (
        datetime.now(timezone.utc)
        + timedelta(hours=60)
    ).strftime("%Y-%m-%d")

    r = api.get(
        f"/admin/usage-report?from={day}&to={day}",
        headers=admin_headers,
    )

    assert r.status_code == 200

    room_stats = next(
        x for x in r.json()["rooms"]
        if x["room_id"] == room["id"]
    )

    assert room_stats["confirmed_bookings"] == 2
    assert room_stats["revenue_cents"] == 3000


def test_usage_report_includes_empty_rooms(api, admin_headers):
    room1 = api.post(
        "/rooms",
        json={
            "name": "Room A",
            "capacity": 5,
            "hourly_rate_cents": 1000,
        },
        headers=admin_headers,
    ).json()

    room2 = api.post(
        "/rooms",
        json={
            "name": "Room B",
            "capacity": 5,
            "hourly_rate_cents": 1000,
        },
        headers=admin_headers,
    ).json()

    api.post(
        "/bookings",
        json={
            "room_id": room1["id"],
            "start_time": future(70),
            "end_time": future(72),
        },
        headers=admin_headers,
    )

    day = (
        datetime.now(timezone.utc)
        + timedelta(hours=70)
    ).strftime("%Y-%m-%d")

    r = api.get(
        f"/admin/usage-report?from={day}&to={day}",
        headers=admin_headers,
    )

    assert r.status_code == 200

    rooms = r.json()["rooms"]

    assert len(rooms) >= 2

    stats1 = next(x for x in rooms if x["room_id"] == room1["id"])
    stats2 = next(x for x in rooms if x["room_id"] == room2["id"])

    assert stats1["confirmed_bookings"] == 1
    assert stats2["confirmed_bookings"] == 0


def test_member_cannot_access_usage_report(api):
    org = f"org-{datetime.now().timestamp()}"

    api.post(
        "/auth/register",
        json={
            "org_name": org,
            "username": "admin",
            "password": "password123",
        },
    )

    api.post(
        "/auth/register",
        json={
            "org_name": org,
            "username": "member",
            "password": "password123",
        },
    )

    login = api.post(
        "/auth/login",
        json={
            "org_name": org,
            "username": "member",
            "password": "password123",
        },
    )

    headers = {
        "Authorization": f"Bearer {login.json()['access_token']}"
    }

    today = datetime.now().strftime("%Y-%m-%d")

    r = api.get(
        f"/admin/usage-report?from={today}&to={today}",
        headers=headers,
    )

    assert r.status_code == 403


def test_usage_report_requires_auth(api):
    today = datetime.now().strftime("%Y-%m-%d")

    r = api.get(
        f"/admin/usage-report?from={today}&to={today}"
    )

    assert r.status_code == 401


def test_invalid_date_range(api, admin_headers):
    r = api.get(
        "/admin/usage-report?from=abc&to=xyz",
        headers=admin_headers,
    )

    assert r.status_code == 400


def test_export_endpoint(api, admin_headers):
    r = api.get(
        "/admin/export",
        headers=admin_headers,
    )

    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]


def test_export_requires_admin(api):
    org = f"org-{datetime.now().timestamp()}"

    api.post(
        "/auth/register",
        json={
            "org_name": org,
            "username": "admin",
            "password": "password123",
        },
    )

    api.post(
        "/auth/register",
        json={
            "org_name": org,
            "username": "member",
            "password": "password123",
        },
    )

    login = api.post(
        "/auth/login",
        json={
            "org_name": org,
            "username": "member",
            "password": "password123",
        },
    )

    headers = {
        "Authorization": f"Bearer {login.json()['access_token']}"
    }

    r = api.get(
        "/admin/export",
        headers=headers,
    )

    assert r.status_code == 403