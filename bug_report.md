# Bug Fixes

This document catalogs bugs identified and fixed across the codebase, including their file locations, root causes, and applied fixes.

---
## Bug 0: Registration with same org and username
Auth - 1
If someone registers again with the same org_name and same username, the API currently returns the old user with success 201.

But the expected behavior is:

409 USERNAME_TAKEN

Auth - 2
What we did is not just making duplicate registration fail. We tried to implement these business rules:
Unknown org name → create org and make user admin.
Known org name → add user as member.
Duplicate username inside same org → 409 USERNAME_TAKEN.

Say, u sent this request:
{
  "org_name": "Sadik Org",
  "username": "sadik",
  "password": "123456"
}

The code first check if this is the first registraation for this organization. If yes, it creates the organization and makes the user an admin. 
If not, it checks if the username already exists in that organization. If it does, it returns 409 USERNAME_TAKEN. If not, it adds the user as a member of the existing organization.

## Bug 1: Datetime Parsing — Timezone Handling

**File:** `timeutils.py`
**Lines:** 14-15

### Description
`parse_input_datetime` stripped timezone information without normalizing to UTC first:

```python
dt = datetime.fromisoformat(value)
if dt.tzinfo is not None:
    dt = dt.replace(tzinfo=None)  # Bug: Drops offset without converting
```

This caused datetimes with offsets (e.g. `"2026-07-09T10:00:00+05:30"`) to be stored as-is after stripping the offset, losing the actual UTC time and resulting in booking times off by several hours.

### Fix
```python
if dt.tzinfo is not None:
    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
```
Now properly converts to UTC before stripping timezone info.

---

## Bug 2: Notification Deadlock

**File:** `notifications.py`
**Lines:** 20-25

### Description
Nested locks in `notify_created` and `notify_cancelled` could cause deadlocks:

```python
def notify_created(booking) -> None:
    with _email_lock:
        _send_email("created", booking)
        with _audit_lock:  # Nested lock acquisition
            _write_audit("created", booking)

def notify_cancelled(booking) -> None:
    with _audit_lock:
        _write_audit("cancelled", booking)
        with _email_lock:  # Opposite order - potential deadlock
            _send_email("cancelled", booking)
```

If one thread calls `notify_created` and another calls `notify_cancelled` simultaneously, a deadlock could occur, hanging the service.

### Fix
Use a single lock for both operations:

```python
_lock = threading.Lock()

def notify_created(booking) -> None:
    with _lock:
        _send_email("created", booking)
        _write_audit("created", booking)

def notify_cancelled(booking) -> None:
    with _lock:
        _write_audit("cancelled", booking)
        _send_email("cancelled", booking)
```

---

## Bug 3: Rate Limiting — Race Condition

**File:** `ratelimit.py`
**Lines:** 6-10

### Description
The rate limiting bucket was accessed without synchronization:

```python
bucket = _buckets.get(user_id, [])
bucket = [t for t in bucket if t > now - _WINDOW_SECONDS]
bucket.append(now)
_buckets[user_id] = bucket
```

Under concurrent requests from the same user, multiple threads could read, modify, and write the bucket simultaneously, causing the rate limit to be incorrectly applied or bypassed.

### Fix
Added a lock to make the operation atomic:

```python
_lock = threading.Lock()

def record_and_check(user_id: int) -> None:
    now = time.time()
    with _lock:
        bucket = _buckets.get(user_id, [])
        bucket = [t for t in bucket if t > now - _WINDOW_SECONDS]
        bucket.append(now)
        _buckets[user_id] = bucket
        if len(bucket) > _MAX_REQUESTS:
            raise AppError(429, "RATE_LIMITED", "Too many booking requests")
```

---

## Bug 4: Reference Codes — Race Condition

**File:** `reference.py`
**Lines:** 10-12

### Description
Reference code generation was not thread-safe:

```python
current = _counter["value"]
_format_pause()
_counter["value"] = current + 1
```

Under concurrent requests, multiple bookings could receive the same reference code if two threads read the counter before either incremented it.

### Fix
Added a lock to make the counter increment atomic:

```python
_lock = threading.Lock()

def next_reference_code() -> str:
    with _lock:
        current = _counter["value"]
        _counter["value"] = current + 1
        return f"CW-{current:06d}"
```

---

## Bug 5: Stats — Race Condition

**File:** `stats.py`
**Lines:** 17-24

### Description
Stats updates were not atomic:

```python
current = _stats.get(room_id, {"count": 0, "revenue": 0})
count, revenue = current["count"], current["revenue"]
_aggregate_pause()
_stats[room_id] = {"count": count + 1, "revenue": revenue + price_cents}
```

Multiple concurrent booking creations/cancellations could overwrite each other's changes, leading to inconsistent stats.

### Fix
Added a lock and removed artificial delays:

```python
_lock = threading.Lock()

def record_create(room_id: int, price_cents: int) -> None:
    with _lock:
        current = _stats.get(room_id, {"count": 0, "revenue": 0})
        _stats[room_id] = {
            "count": current["count"] + 1,
            "revenue": current["revenue"] + price_cents,
        }
```

---

## Bug 6: Cache — Thread Safety

**File:** `cache.py`
**Lines:** 6-7

### Description
Caches were modified without any synchronization, which could lead to inconsistent reads under concurrent access.

### Fix
Added locks for each cache:

```python
_report_lock = threading.Lock()
_availability_lock = threading.Lock()

def get_report(org_id: int, frm: str, to: str):
    with _report_lock:
        return _report_cache.get((org_id, frm, to))

# ... similar for other functions
```

---

## Bug 7: Booking Conflict Detection — Inefficient

**File:** `bookings.py`
**Lines:** 31-42

### Description
Conflict detection fetched all bookings and checked them in Python:

```python
existing = db.query(Booking).filter(
    Booking.room_id == room_id, Booking.status == "confirmed"
).all()
_pricing_warmup()
for b in existing:
    if b.start_time <= end and start <= b.end_time:
        return True
```

This was inefficient and could cause performance issues with many bookings, and it didn't use database-level checks for consistency.

### Fix
Use a database query to check for overlaps:

```python
existing = (
    db.query(Booking)
    .filter(
        Booking.room_id == room_id,
        Booking.status == "confirmed",
        Booking.start_time < end,   # existing.start < new.end
        start < Booking.end_time,   # new.start < existing.end
    )
    .first()
)
return existing is not None
```

---

## Bug 8: Pagination — Off by One

**File:** `bookings.py`
**Lines:** 122-125

### Description
Pagination had an off-by-one error and ignored the `limit` parameter:

```python
offset = (page - 1) * limit  # Correct calculation
items = (
    base.order_by(Booking.start_time.desc(), Booking.id.asc())
    .offset(page * limit)  # Wrong - should use offset variable
    .limit(10)              # Hardcoded, ignoring limit parameter
    .all()
)
```

### Fix
```python
offset = (page - 1) * limit
items = (
    base.order_by(Booking.start_time.asc(), Booking.id.asc())
    .offset(offset)
    .limit(limit)
    .all()
)
```
Also fixed ordering to ascending (requirement #11) instead of descending.

---

## Bug 9: Booking Visibility — Inconsistent Access Control

**File:** `bookings.py`
**Lines:** 139-149

### Description
The GET endpoint didn't properly restrict access for non-admin users:

```python
booking = (
    db.query(Booking)
    .join(Room, Booking.room_id == Room.id)
    .filter(Booking.id == booking_id, Room.org_id == user.org_id)
    .first()
)
```

This allowed any user in the same org to view any booking, violating requirement #10.

### Fix
Add a `user_id` filter for non-admin users:

```python
# Check if user is the owner or admin
booking = (
    db.query(Booking)
    .join(Room, Booking.room_id == Room.id)
    .filter(
        Booking.id == booking_id,
        Room.org_id == user.org_id,
        Booking.user_id == user.id,  # Non-admin users see only their own
    )
    .first()
)
# If not found but user is admin, try without user_id filter
if booking is None and user.role == "admin":
    booking = (
        db.query(Booking)
        .join(Room, Booking.room_id == Room.id)
        .filter(Booking.id == booking_id, Room.org_id == user.org_id)
        .first()
    )
```

---

## Bug 10: Cancellation Refund — Incorrect Logic

**File:** `bookings.py`
**Lines:** 189-192

### Description
The refund logic incorrectly calculated the refund percentage:

```python
if notice_hours > 48:  # Should be >=
    refund_percent = 100
elif notice >= timedelta(hours=24):
    refund_percent = 50
else:
    refund_percent = 50  # Should be 0
```

The 48-hour threshold should use `>=`, and refund should be 0% for less than 24 hours notice.

### Fix
```python
if notice_hours >= 48:
    refund_percent = 100
elif notice_hours >= 24:
    refund_percent = 50
else:
    refund_percent = 0

# Calculate refund amount (round to nearest cent, half-up)
refund_amount_cents = int(round(booking.price_cents * (refund_percent / 100.0)))
```

---

## Bug 11: Refresh Tokens — Not Single-Use

**File:** `auth.py`
**Lines:** 65-76

### Description
Refresh tokens were not being invalidated after use, violating requirement #8:

```python
@router.post("/refresh")
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    data = decode_token(payload.refresh_token)
    # ... no invalidation
    return {
        "access_token": create_access_token(user),
        "refresh_token": create_refresh_token(user),
    }
```

### Fix
Track used refresh tokens and invalidate them:

```python
_used_refresh_tokens: set[str] = set()

@router.post("/refresh")
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    data = decode_token(payload.refresh_token)
    if is_refresh_token_used(data["jti"]):
        raise AppError(401, "UNAUTHORIZED", "Refresh token already used")
    # ...
    mark_refresh_token_used(data["jti"])
    return { ... }
```

---

## Bug 12: Access Token Expiration — Wrong Calculation

**File:** `auth.py`
**Lines:** 38-46

### Description
Access token expiration was incorrectly multiplied by 60:

```python
lifetime = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES * 60)
```

This set expiration to 15 hours (900 minutes) instead of the required 15 minutes.

### Fix
```python
lifetime = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
```

---

## Bug 13: Booking Creation — Date Validation

**File:** `bookings.py`
**Lines:** 63-65

### Description
Booking start time had a 5-minute grace window:

```python
if start <= now - timedelta(seconds=300):
    raise AppError(400, "INVALID_BOOKING_WINDOW", "start_time must be in the future")
```

Requirement #2 states "start time must be strictly in the future at request time - no grace window."

### Fix
Remove the grace window:

```python
if start <= now:
    raise AppError(400, "INVALID_BOOKING_WINDOW", "start_time must be in the future")
```

---

## Bug 14: Export — Missing Org Isolation

**File:** `export.py`
**Lines:** 17-23

### Description
The export function didn't enforce org isolation for `include_all` mode:

```python
if include_all:
    if room_id is not None:
        rows = fetch_bookings_raw(db, room_id)  # No org check
    else:
        rows = _fetch_scoped(db, org_id, None, None)
```

An admin could potentially export bookings from other orgs by guessing room IDs.

### Fix
Always enforce org isolation in the base query:

```python
query = db.query(Booking).join(Room).filter(Room.org_id == org_id)
if not include_all:
    query = query.filter(Booking.user_id == user_id)
if room_id is not None:
    query = query.filter(Booking.room_id == room_id)
```

---

## Bug 15: Usage Report — Caching Invalidation

**File:** `bookings.py`
**Lines:** 111

### Description
The usage report cache was not being invalidated when bookings were created or cancelled, causing stale reports.

### Fix
Add cache invalidation in both create and cancel endpoints:

```python
# In create_booking
cache.invalidate_report(user.org_id)

# In cancel_booking
cache.invalidate_report(user.org_id)
```

---

## Bug 16: Booking Quota — Double Counting

**File:** `bookings.py`
**Lines:** 48-55

### Description
The quota check counted bookings in the window incorrectly and had an unnecessary sleep:

```python
count = (
    db.query(Booking)
    .filter(
        Booking.user_id == user_id,
        Booking.status == "confirmed",
        Booking.start_time > now,
        Booking.start_time <= window_end,
    )
    .count()
)
_quota_audit()  # Unnecessary sleep
if count >= QUOTA_LIMIT:
    raise AppError(409, "QUOTA_EXCEEDED", "Booking quota exceeded")
```

### Fix
Remove the artificial sleep and ensure the count is correct for the `(now, now+24h]` window:

```python
count = (
    db.query(Booking)
    .filter(
        Booking.user_id == user_id,
        Booking.status == "confirmed",
        Booking.start_time > now,        # Strictly after now
        Booking.start_time <= window_end,  # Inclusive of window end
    )
    .count()
)
```

---

## Bug 17: Database Connection — Thread Safety

**File:** `database.py`
**Lines:** 12-15

### Description
The database engine was created with `connect_args={"check_same_thread": False}`, which is unsafe for production use as it allows multiple threads to use the same connection concurrently.

### Fix
For SQLite, either use a connection pool per thread or switch to a different database for production. The current setup works for development but should be flagged for production use.

---

## Bug 18: Booking Stats — Inconsistency

**File:** `rooms.py`
**Lines:** 103-110

### Description
The stats endpoint returned potentially stale data from the in-memory cache without verifying consistency with the database.

### Fix
Add a check to recalculate stats from the database if they appear empty or potentially stale:

```python
stats_data = stats.get(room.id)
if stats_data["count"] == 0 and stats_data["revenue"] == 0:
    confirmed = (
        db.query(Booking)
        .filter(Booking.room_id == room.id, Booking.status == "confirmed")
        .all()
    )
    if confirmed:
        stats_data = {
            "count": len(confirmed),
            "revenue": sum(b.price_cents for b in confirmed),
        }
```

## Bug 19: Booking quota

**File:** `booking.py`

### Description
A member may hold at most 3 confirmed bookings with start time in the window.

### Fix
Added a quata.py file to check 3 confirmed belongings in the given timespace:


