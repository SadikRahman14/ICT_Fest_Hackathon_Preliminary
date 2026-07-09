from datetime import datetime, timedelta, timezone


def future(hours):
    return (
        datetime.now(timezone.utc) + timedelta(hours=hours)
    ).replace(
        minute=0,
        second=0,
        microsecond=0,
    ).isoformat()


def test_admin_can_create_room(api, admin_headers):
    r = api.post(
        "/rooms",
        json={
            "name": "Meeting Room",
            "capacity": 10,
            "hourly_rate_cents": 2000,
        },
        headers=admin_headers,
    )

    assert r.status_code == 201

    body = r.json()

    assert body["name"] == "Meeting Room"
    assert body["capacity"] == 10
    assert body["hourly_rate_cents"] == 2000


def test_member_cannot_create_room(api):
    org = f"org-{datetime.now().timestamp()}"

    api.post(
        "/auth/register",
        json={
            "org_name": org,
            "username": "admin",
            "password": "pass123",
        },
    )

    api.post(
        "/auth/register",
        json={
            "org_name": org,
            "username": "member",
            "password": "pass123",
        },
    )

    login = api.post(
        "/auth/login",
        json={
            "org_name": org,
            "username": "member",
            "password": "pass123",
        },
    )

    token = login.json()["access_token"]

    r = api.post(
        "/rooms",
        json={
            "name": "Private Room",
            "capacity": 5,
            "hourly_rate_cents": 1500,
        },
        headers={
            "Authorization": f"Bearer {token}"
        },
    )

    assert r.status_code == 403


def test_list_rooms(api, admin_headers):
    api.post(
        "/rooms",
        json={
            "name": "Room A",
            "capacity": 5,
            "hourly_rate_cents": 1000,
        },
        headers=admin_headers,
    )

    api.post(
        "/rooms",
        json={
            "name": "Room B",
            "capacity": 8,
            "hourly_rate_cents": 1500,
        },
        headers=admin_headers,
    )

    r = api.get(
        "/rooms",
        headers=admin_headers,
    )

    assert r.status_code == 200

    rooms = r.json()

    assert len(rooms) >= 2


def test_availability_empty(api, room, admin_headers):
    r = api.get(
        f"/rooms/{room['id']}/availability?date=2035-01-01",
        headers=admin_headers,
    )

    assert r.status_code == 200

    body = r.json()

    assert body["busy"] == []


def test_availability_after_booking(api, room, admin_headers):
    api.post(
        "/bookings",
        json={
            "room_id": room["id"],
            "start_time": future(50),
            "end_time": future(52),
        },
        headers=admin_headers,
    )

    day = (
        datetime.now(timezone.utc)
        + timedelta(hours=50)
    ).strftime("%Y-%m-%d")

    r = api.get(
        f"/rooms/{room['id']}/availability?date={day}",
        headers=admin_headers,
    )

    assert r.status_code == 200

    busy = r.json()["busy"]

    assert len(busy) == 1

    assert "start_time" in busy[0]
    assert "end_time" in busy[0]


def test_availability_sorted(api, room, admin_headers):
    api.post(
        "/bookings",
        json={
            "room_id": room["id"],
            "start_time": future(60),
            "end_time": future(61),
        },
        headers=admin_headers,
    )

    api.post(
        "/bookings",
        json={
            "room_id": room["id"],
            "start_time": future(55),
            "end_time": future(56),
        },
        headers=admin_headers,
    )

    day = (
        datetime.now(timezone.utc)
        + timedelta(hours=55)
    ).strftime("%Y-%m-%d")

    r = api.get(
        f"/rooms/{room['id']}/availability?date={day}",
        headers=admin_headers,
    )

    assert r.status_code == 200

    busy = r.json()["busy"]

    assert busy[0]["start_time"] < busy[1]["start_time"]


def test_room_stats_empty(api, room, admin_headers):
    r = api.get(
        f"/rooms/{room['id']}/stats",
        headers=admin_headers,
    )

    assert r.status_code == 200

    body = r.json()

    assert body["room_id"] == room["id"]

    assert "total_confirmed_bookings" in body
    assert "total_revenue_cents" in body


def test_room_stats_after_booking(api, room, admin_headers):
    api.post(
        "/bookings",
        json={
            "room_id": room["id"],
            "start_time": future(70),
            "end_time": future(72),
        },
        headers=admin_headers,
    )

    r = api.get(
        f"/rooms/{room['id']}/stats",
        headers=admin_headers,
    )

    assert r.status_code == 200

    body = r.json()

    assert body["total_confirmed_bookings"] >= 1
    assert body["total_revenue_cents"] >= 2000


def test_room_not_found(api, admin_headers):
    r = api.get(
        "/rooms/999999/stats",
        headers=admin_headers,
    )

    assert r.status_code == 404


def test_availability_room_not_found(api, admin_headers):
    r = api.get(
        "/rooms/999999/availability?date=2035-01-01",
        headers=admin_headers,
    )

    assert r.status_code == 404


def test_invalid_date(api, room, admin_headers):
    r = api.get(
        f"/rooms/{room['id']}/availability?date=abc",
        headers=admin_headers,
    )

    assert r.status_code == 400


def test_rooms_require_auth(api):
    r = api.get("/rooms")

    assert r.status_code == 401