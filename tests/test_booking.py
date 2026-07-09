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


def create_booking(api, headers, room_id, start_hour, end_hour):
    return api.post(
        "/bookings",
        json={
            "room_id": room_id,
            "start_time": future(start_hour),
            "end_time": future(end_hour),
        },
        headers=headers,
    )


def test_create_booking_success(api, room, admin_headers):
    r = create_booking(api, admin_headers, room["id"], 50, 52)

    assert r.status_code == 201

    body = r.json()

    assert body["room_id"] == room["id"]
    assert body["status"] == "confirmed"
    assert body["price_cents"] == 2000


def test_price_calculation(api, room, admin_headers):
    r = create_booking(api, admin_headers, room["id"], 60, 63)

    assert r.status_code == 201

    assert r.json()["price_cents"] == 3000


def test_one_hour_booking(api, room, admin_headers):
    r = create_booking(api, admin_headers, room["id"], 70, 71)

    assert r.status_code == 201


def test_eight_hour_booking(api, room, admin_headers):
    r = create_booking(api, admin_headers, room["id"], 80, 88)

    assert r.status_code == 201


def test_duration_over_eight_hours(api, room, admin_headers):
    r = create_booking(api, admin_headers, room["id"], 90, 99)

    assert r.status_code == 400


def test_zero_hour_booking(api, room, admin_headers):
    t = future(100)

    r = api.post(
        "/bookings",
        json={
            "room_id": room["id"],
            "start_time": t,
            "end_time": t,
        },
        headers=admin_headers,
    )

    assert r.status_code == 400


def test_fractional_duration(api, room, admin_headers):
    start = (
        datetime.now(timezone.utc)
        + timedelta(hours=110)
    ).replace(second=0, microsecond=0)

    end = start + timedelta(minutes=30)

    r = api.post(
        "/bookings",
        json={
            "room_id": room["id"],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
        headers=admin_headers,
    )

    assert r.status_code == 400


def test_past_booking(api, room, admin_headers):
    start = (
        datetime.now(timezone.utc)
        - timedelta(hours=2)
    ).isoformat()

    end = (
        datetime.now(timezone.utc)
        - timedelta(hours=1)
    ).isoformat()

    r = api.post(
        "/bookings",
        json={
            "room_id": room["id"],
            "start_time": start,
            "end_time": end,
        },
        headers=admin_headers,
    )

    assert r.status_code == 400


def test_end_before_start(api, room, admin_headers):
    r = create_booking(api, admin_headers, room["id"], 130, 129)

    assert r.status_code == 400


def test_room_not_found(api, admin_headers):
    r = create_booking(api, admin_headers, 999999, 140, 142)

    assert r.status_code == 404


def test_double_booking(api, room, admin_headers):
    first = create_booking(api, admin_headers, room["id"], 150, 152)

    assert first.status_code == 201

    second = create_booking(api, admin_headers, room["id"], 151, 153)

    assert second.status_code == 409


def test_back_to_back_booking(api, room, admin_headers):
    first = create_booking(api, admin_headers, room["id"], 160, 162)

    assert first.status_code == 201

    second = create_booking(api, admin_headers, room["id"], 162, 164)

    assert second.status_code == 201


def test_booking_list(api, booking, admin_headers):
    r = api.get(
        "/bookings",
        headers=admin_headers,
    )

    assert r.status_code == 200

    body = r.json()

    assert body["total"] >= 1
    assert len(body["items"]) >= 1


def test_booking_detail(api, booking, admin_headers):
    r = api.get(
        f"/bookings/{booking['id']}",
        headers=admin_headers,
    )

    assert r.status_code == 200

    assert r.json()["id"] == booking["id"]


def test_booking_not_found(api, admin_headers):
    r = api.get(
        "/bookings/999999",
        headers=admin_headers,
    )

    assert r.status_code == 404


def test_cancel_booking(api, booking, admin_headers):
    r = api.post(
        f"/bookings/{booking['id']}/cancel",
        headers=admin_headers,
    )

    assert r.status_code == 200

    assert r.json()["status"] == "cancelled"


def test_cancel_twice(api, booking, admin_headers):
    api.post(
        f"/bookings/{booking['id']}/cancel",
        headers=admin_headers,
    )

    r = api.post(
        f"/bookings/{booking['id']}/cancel",
        headers=admin_headers,
    )

    assert r.status_code == 409


def test_reference_code_exists(api, booking):
    assert booking["reference_code"] != ""


def test_booking_requires_auth(api):
    r = api.post(
        "/bookings",
        json={
            "room_id": 1,
            "start_time": future(200),
            "end_time": future(201),
        },
    )

    assert r.status_code == 401


def test_list_requires_auth(api):
    r = api.get("/bookings")

    assert r.status_code == 401


def test_cancel_requires_auth(api, booking):
    r = api.post(
        f"/bookings/{booking['id']}/cancel",
    )

    assert r.status_code == 401


def test_invalid_booking_id(api, admin_headers):
    r = api.post(
        "/bookings/999999/cancel",
        headers=admin_headers,
    )

    assert r.status_code == 404