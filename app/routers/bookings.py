"""Booking creation, listing, detail and cancellation."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_

from .. import cache
from ..auth import get_current_user
from ..database import get_db
from ..errors import AppError
from ..models import Booking, Room, User
from ..schemas import BookingCreateRequest
from ..serializers import serialize_booking
from ..services import notifications, ratelimit, reference, stats
from ..services.refunds import log_refund
from ..timeutils import iso_utc, parse_input_datetime

router = APIRouter(tags=["bookings"])

MIN_DURATION_HOURS = 1
MAX_DURATION_HOURS = 8
QUOTA_LIMIT = 3
QUOTA_WINDOW_HOURS = 24


def _has_conflict(db: Session, room_id: int, start: datetime, end: datetime) -> bool:
    """Check for overlapping confirmed bookings.
    
    Two bookings overlap iff existing.start < new.end AND new.start < existing.end.
    Back-to-back bookings (end == start) are allowed.
    """
    existing = (
        db.query(Booking)
        .filter(
            Booking.room_id == room_id,
            Booking.status == "confirmed",
            Booking.start_time < end,
            start < Booking.end_time,
        )
        .first()
    )
    return existing is not None


def _check_quota(db: Session, user_id: int, now: datetime, start: datetime) -> None:
    """Check if user has exceeded booking quota for the next 24 hours."""
    window_end = now + timedelta(hours=QUOTA_WINDOW_HOURS)
    if not (now < start <= window_end):
        return
    
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
    if count >= QUOTA_LIMIT:
        raise AppError(409, "QUOTA_EXCEEDED", "Booking quota exceeded")


@router.post("/bookings", status_code=201)
def create_booking(
    payload: BookingCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Rate limit check (must happen first)
    ratelimit.record_and_check(user.id)

    start = parse_input_datetime(payload.start_time)
    end = parse_input_datetime(payload.end_time)
    now = datetime.utcnow()

    # Validate start time is strictly in the future (no grace window)
    if start <= now:
        raise AppError(400, "INVALID_BOOKING_WINDOW", "start_time must be in the future")

    # Validate duration
    duration_hours = (end - start).total_seconds() / 3600
    if duration_hours != int(duration_hours):
        raise AppError(400, "INVALID_BOOKING_WINDOW", "Duration must be a whole number of hours")
    
    duration_hours = int(duration_hours)
    if duration_hours < MIN_DURATION_HOURS or duration_hours > MAX_DURATION_HOURS:
        raise AppError(400, "INVALID_BOOKING_WINDOW", f"Duration must be between {MIN_DURATION_HOURS} and {MAX_DURATION_HOURS} hours")

    # Validate end time is after start time
    if end <= start:
        raise AppError(400, "INVALID_BOOKING_WINDOW", "end_time must be after start_time")

    # Check room exists in user's org
    room = db.query(Room).filter(Room.id == payload.room_id, Room.org_id == user.org_id).first()
    if room is None:
        raise AppError(404, "ROOM_NOT_FOUND", "Room not found")

    # Check for double-booking (with database-level consistency)
    if _has_conflict(db, room.id, start, end):
        raise AppError(409, "ROOM_CONFLICT", "Room already booked for this interval")

    # Check quota
    _check_quota(db, user.id, now, start)

    # Calculate price
    price_cents = room.hourly_rate_cents * duration_hours

    # Create booking with unique reference code
    booking = Booking(
        room_id=room.id,
        user_id=user.id,
        start_time=start,
        end_time=end,
        status="confirmed",
        reference_code=reference.next_reference_code(),
        price_cents=price_cents,
        created_at=now,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)

    # Update stats and cache
    stats.record_create(room.id, price_cents)
    cache.invalidate_availability(room.id, start.date().isoformat())
    cache.invalidate_report(user.org_id)
    
    # Send notifications
    notifications.notify_created(booking)

    return serialize_booking(booking)


@router.get("/bookings")
def list_bookings(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Query user's own bookings only
    base = db.query(Booking).filter(Booking.user_id == user.id)
    total = base.count()
    
    offset = (page - 1) * limit
    items = (
        base.order_by(Booking.start_time.asc(), Booking.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    
    return {
        "items": [serialize_booking(b) for b in items],
        "page": page,
        "limit": limit,
        "total": total,
    }


@router.get("/bookings/{booking_id}")
def get_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Users can only see their own bookings
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
    
    # Admins can see any booking in their org
    if booking is None and user.role == "admin":
        booking = (
            db.query(Booking)
            .join(Room, Booking.room_id == Room.id)
            .filter(Booking.id == booking_id, Room.org_id == user.org_id)
            .first()
        )
    
    if booking is None:
        raise AppError(404, "BOOKING_NOT_FOUND", "Booking not found")

    response = serialize_booking(booking)
    response["refunds"] = [
        {
            "amount_cents": r.amount_cents,
            "status": r.status,
            "processed_at": iso_utc(r.processed_at),
        }
        for r in booking.refunds
    ]
    return response


@router.post("/bookings/{booking_id}/cancel")
def cancel_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # First, check if booking exists in user's org
    booking = (
        db.query(Booking)
        .join(Room, Booking.room_id == Room.id)
        .filter(Booking.id == booking_id, Room.org_id == user.org_id)
        .first()
    )
    if booking is None:
        raise AppError(404, "BOOKING_NOT_FOUND", "Booking not found")
    
    # Only owner or admin can cancel
    if user.role != "admin" and booking.user_id != user.id:
        raise AppError(404, "BOOKING_NOT_FOUND", "Booking not found")

    # Check if already cancelled
    if booking.status == "cancelled":
        raise AppError(409, "ALREADY_CANCELLED", "Booking already cancelled")

    # Calculate refund based on notice period
    now = datetime.utcnow()
    notice = booking.start_time - now
    notice_hours = notice.total_seconds() / 3600
    
    if notice_hours >= 48:
        refund_percent = 100
    elif notice_hours >= 24:
        refund_percent = 50
    else:
        refund_percent = 0

    # Calculate refund amount (round to nearest cent, half-up)
    refund_amount_cents = int(round(booking.price_cents * (refund_percent / 100.0)))

    # Create refund log entry
    if refund_percent > 0:
        log_refund(db, booking, refund_percent)
    else:
        # Log zero refund
        from ..models import RefundLog
        entry = RefundLog(
            booking_id=booking.id,
            amount_cents=0,
            status="processed",
            processed_at=now,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)

    # Update booking status
    booking.status = "cancelled"
    db.commit()
    db.refresh(booking)

    # Update stats and cache
    stats.record_cancel(booking.room_id, booking.price_cents)
    cache.invalidate_availability(booking.room_id, booking.start_time.date().isoformat())
    cache.invalidate_report(user.org_id)
    
    # Send notifications
    notifications.notify_cancelled(booking)

    return {
        "id": booking.id,
        "status": "cancelled",
        "refund_percent": refund_percent,
        "refund_amount_cents": refund_amount_cents,
    }