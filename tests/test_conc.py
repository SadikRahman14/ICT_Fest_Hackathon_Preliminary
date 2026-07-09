from concurrent.futures import ThreadPoolExecutor
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


def test_concurrent_same_room_booking(api, room, admin_headers):
    def book():
        return api.post(
            "/bookings",
            json={
                "room_id": room["id"],
                "start_time": future(50),
                "end_time": future(52),
            },
            headers=admin_headers,
        ).status_code

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(lambda _: book(), range(20)))

    assert results.count(201) == 1
    assert results.count(409) == 19


def test_concurrent_back_to_back_booking(api, room, admin_headers):
    def first():
        return api.post(
            "/bookings",
            json={
                "room_id": room["id"],
                "start_time": future(60),
                "end_time": future(61),
            },
            headers=admin_headers,
        )

    def second():
        return api.post(
            "/bookings",
            json={
                "room_id": room["id"],
                "start_time": future(61),
                "end_time": future(62),
            },
            headers=admin_headers,
        )

    r1 = first()
    r2 = second()

    assert r1.status_code == 201
    assert r2.status_code == 201


def test_refresh_token_single_use_under_concurrency(api, register_admin):
    login = api.post(
        "/auth/login",
        json={
            "org_name": register_admin["org"],
            "username": register_admin["username"],
            "password": register_admin["password"],
        },
    )

    refresh_token = login.json()["refresh_token"]

    def refresh():
        return api.post(
            "/auth/refresh",
            json={
                "refresh_token": refresh_token
            },
        ).status_code

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda _: refresh(), range(10)))

    assert results.count(200) == 1
    assert results.count(401) == 9


def test_concurrent_logout(api, admin_headers):
    def logout():
        return api.post(
            "/auth/logout",
            headers=admin_headers,
        ).status_code

    with ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(lambda _: logout(), range(10)))

    r = api.get(
        "/rooms",
        headers=admin_headers,
    )

    assert r.status_code == 401


def test_concurrent_cancel(api, booking, admin_headers):
    def cancel():
        return api.post(
            f"/bookings/{booking['id']}/cancel",
            headers=admin_headers,
        ).status_code

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda _: cancel(), range(10)))

    assert results.count(200) == 1
    assert results.count(409) == 9


def test_reference_codes_unique(api, room, admin_headers):
    refs = []

    for i in range(20):
        r = api.post(
            "/bookings",
            json={
                "room_id": room["id"],
                "start_time": future(100 + i * 2),
                "end_time": future(101 + i * 2),
            },
            headers=admin_headers,
        )

        assert r.status_code == 201

        refs.append(r.json()["reference_code"])

    assert len(refs) == len(set(refs))


def test_booking_quota(api, room, admin_headers):
    for i in range(3):
        r = api.post(
            "/bookings",
            json={
                "room_id": room["id"],
                "start_time": future(150 + i * 2),
                "end_time": future(151 + i * 2),
            },
            headers=admin_headers,
        )

        assert r.status_code == 201

    fourth = api.post(
        "/bookings",
        json={
            "room_id": room["id"],
            "start_time": future(170),
            "end_time": future(171),
        },
        headers=admin_headers,
    )

    assert fourth.status_code == 409


def test_many_parallel_bookings(api, room, admin_headers):
    def create(offset):
        return api.post(
            "/bookings",
            json={
                "room_id": room["id"],
                "start_time": future(300 + offset * 2),
                "end_time": future(301 + offset * 2),
            },
            headers=admin_headers,
        ).status_code

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(create, range(20)))

    assert all(x == 201 for x in results)