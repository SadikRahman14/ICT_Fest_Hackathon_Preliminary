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


def register(api, org, username):
    api.post(
        "/auth/register",
        json={
            "org_name": org,
            "username": username,
            "password": "password123",
        },
    )


def login(api, org, username):
    r = api.post(
        "/auth/login",
        json={
            "org_name": org,
            "username": username,
            "password": "password123",
        },
    )

    return {
        "Authorization": f"Bearer {r.json()['access_token']}"
    }


def test_rooms_are_isolated_between_orgs(api):
    org1 = f"org1-{datetime.now().timestamp()}"
    org2 = f"org2-{datetime.now().timestamp()}"

    register(api, org1, "alice")
    register(api, org2, "bob")

    h1 = login(api, org1, "alice")
    h2 = login(api, org2, "bob")

    room = api.post(
        "/rooms",
        json={
            "name": "Secret Room",
            "capacity": 4,
            "hourly_rate_cents": 1000,
        },
        headers=h1,
    )

    room_id = room.json()["id"]

    r = api.get(
        f"/rooms/{room_id}/stats",
        headers=h2,
    )

    assert r.status_code == 404


def test_availability_hidden_from_other_org(api):
    org1 = f"org1-{datetime.now().timestamp()}"
    org2 = f"org2-{datetime.now().timestamp()}"

    register(api, org1, "alice")
    register(api, org2, "bob")

    h1 = login(api, org1, "alice")
    h2 = login(api, org2, "bob")

    room = api.post(
        "/rooms",
        json={
            "name": "Board Room",
            "capacity": 8,
            "hourly_rate_cents": 2000,
        },
        headers=h1,
    )

    room_id = room.json()["id"]

    day = (
        datetime.now(timezone.utc)
        + timedelta(days=2)
    ).strftime("%Y-%m-%d")

    r = api.get(
        f"/rooms/{room_id}/availability?date={day}",
        headers=h2,
    )

    assert r.status_code == 404


def test_booking_hidden_from_other_org(api):
    org1 = f"org1-{datetime.now().timestamp()}"
    org2 = f"org2-{datetime.now().timestamp()}"

    register(api, org1, "alice")
    register(api, org2, "bob")

    h1 = login(api, org1, "alice")
    h2 = login(api, org2, "bob")

    room = api.post(
        "/rooms",
        json={
            "name": "Meeting",
            "capacity": 6,
            "hourly_rate_cents": 1000,
        },
        headers=h1,
    )

    booking = api.post(
        "/bookings",
        json={
            "room_id": room.json()["id"],
            "start_time": future(50),
            "end_time": future(52),
        },
        headers=h1,
    )

    booking_id = booking.json()["id"]

    r = api.get(
        f"/bookings/{booking_id}",
        headers=h2,
    )

    assert r.status_code == 404


def test_other_org_cannot_cancel_booking(api):
    org1 = f"org1-{datetime.now().timestamp()}"
    org2 = f"org2-{datetime.now().timestamp()}"

    register(api, org1, "alice")
    register(api, org2, "bob")

    h1 = login(api, org1, "alice")
    h2 = login(api, org2, "bob")

    room = api.post(
        "/rooms",
        json={
            "name": "Room",
            "capacity": 5,
            "hourly_rate_cents": 1000,
        },
        headers=h1,
    )

    booking = api.post(
        "/bookings",
        json={
            "room_id": room.json()["id"],
            "start_time": future(60),
            "end_time": future(61),
        },
        headers=h1,
    )

    booking_id = booking.json()["id"]

    r = api.post(
        f"/bookings/{booking_id}/cancel",
        headers=h2,
    )

    assert r.status_code == 404


def test_member_cannot_view_other_members_booking(api):
    org = f"org-{datetime.now().timestamp()}"

    register(api, org, "admin")

    api.post(
        "/auth/register",
        json={
            "org_name": org,
            "username": "member",
            "password": "password123",
        },
    )

    h_admin = login(api, org, "admin")
    h_member = login(api, org, "member")

    room = api.post(
        "/rooms",
        json={
            "name": "Room",
            "capacity": 5,
            "hourly_rate_cents": 1000,
        },
        headers=h_admin,
    )

    booking = api.post(
        "/bookings",
        json={
            "room_id": room.json()["id"],
            "start_time": future(70),
            "end_time": future(71),
        },
        headers=h_admin,
    )

    booking_id = booking.json()["id"]

    r = api.get(
        f"/bookings/{booking_id}",
        headers=h_member,
    )

    assert r.status_code == 404


def test_admin_can_view_member_booking(api):
    org = f"org-{datetime.now().timestamp()}"

    register(api, org, "admin")

    api.post(
        "/auth/register",
        json={
            "org_name": org,
            "username": "member",
            "password": "password123",
        },
    )

    h_admin = login(api, org, "admin")
    h_member = login(api, org, "member")

    room = api.post(
        "/rooms",
        json={
            "name": "Room",
            "capacity": 5,
            "hourly_rate_cents": 1000,
        },
        headers=h_admin,
    )

    booking = api.post(
        "/bookings",
        json={
            "room_id": room.json()["id"],
            "start_time": future(80),
            "end_time": future(81),
        },
        headers=h_member,
    )

    booking_id = booking.json()["id"]

    r = api.get(
        f"/bookings/{booking_id}",
        headers=h_admin,
    )

    assert r.status_code == 200


def test_admin_can_cancel_member_booking(api):
    org = f"org-{datetime.now().timestamp()}"

    register(api, org, "admin")

    api.post(
        "/auth/register",
        json={
            "org_name": org,
            "username": "member",
            "password": "password123",
        },
    )

    h_admin = login(api, org, "admin")
    h_member = login(api, org, "member")

    room = api.post(
        "/rooms",
        json={
            "name": "Conference",
            "capacity": 10,
            "hourly_rate_cents": 1000,
        },
        headers=h_admin,
    )

    booking = api.post(
        "/bookings",
        json={
            "room_id": room.json()["id"],
            "start_time": future(90),
            "end_time": future(91),
        },
        headers=h_member,
    )

    booking_id = booking.json()["id"]

    r = api.post(
        f"/bookings/{booking_id}/cancel",
        headers=h_admin,
    )

    assert r.status_code == 200