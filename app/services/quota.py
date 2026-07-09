"""Quota management with database-level locking to prevent concurrent violations."""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError

from ..models import Booking, QuotaLock, User
from ..errors import AppError

QUOTA_LIMIT = 3
QUOTA_WINDOW_HOURS = 24


def acquire_quota_lock(db: Session, user_id: int, start_time: datetime) -> None:
    """
    Acquire a quota lock for a booking.
    
    This uses a database table to track quota usage and prevent concurrent
    quota violations through unique constraints and atomic operations.
    """
    now = datetime.utcnow()
    window_end = now + timedelta(hours=QUOTA_WINDOW_HOURS)
    
    # Only check quota if booking starts within the window
    if not (now < start_time <= window_end):
        return
    
    # Check if user exists
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise AppError(401, "UNAUTHORIZED", "Unknown user")
    
    # Count confirmed bookings in the window (excluding cancelled)
    current_count = (
        db.query(func.count(Booking.id))
        .filter(
            Booking.user_id == user_id,
            Booking.status == "confirmed",
            Booking.start_time > now,
            Booking.start_time <= window_end,
        )
        .scalar()
    ) or 0
    
    # Count active quota locks for this user
    lock_count = (
        db.query(func.count(QuotaLock.id))
        .filter(
            QuotaLock.user_id == user_id,
            QuotaLock.start_time > now,
            QuotaLock.start_time <= window_end,
        )
        .scalar()
    ) or 0
    
    # Total usage = confirmed bookings + pending locks
    total_usage = current_count + lock_count
    
    if total_usage >= QUOTA_LIMIT:
        raise AppError(409, "QUOTA_EXCEEDED", "Booking quota exceeded")
    
    # Try to acquire a lock - this creates a row that will prevent concurrent
    # bookings from exceeding the quota
    try:
        quota_lock = QuotaLock(
            user_id=user_id,
            start_time=start_time,
            booking_id=None  # Will be set after booking creation
        )
        db.add(quota_lock)
        db.flush()  # Flush to get the ID but don't commit yet
        
        # Store the lock ID in the session for later cleanup
        db.info['quota_lock_id'] = quota_lock.id
        
    except IntegrityError:
        db.rollback()
        raise AppError(409, "QUOTA_EXCEEDED", "Booking quota exceeded")


def release_quota_lock(db: Session) -> None:
    """Release the quota lock after booking creation or on error."""
    lock_id = db.info.get('quota_lock_id')
    if lock_id:
        quota_lock = db.query(QuotaLock).filter(QuotaLock.id == lock_id).first()
        if quota_lock:
            db.delete(quota_lock)
            db.flush()
        db.info.pop('quota_lock_id', None)


def update_quota_lock_with_booking(db: Session, booking_id: int) -> None:
    """Update the quota lock with the actual booking ID after creation."""
    lock_id = db.info.get('quota_lock_id')
    if lock_id:
        quota_lock = db.query(QuotaLock).filter(QuotaLock.id == lock_id).first()
        if quota_lock:
            quota_lock.booking_id = booking_id
            db.flush()


def cleanup_expired_locks(db: Session) -> None:
    """Remove expired quota locks that were never converted to bookings."""
    now = datetime.utcnow()
    expired_window = now - timedelta(hours=1)  # Locks older than 1 hour
    
    db.query(QuotaLock).filter(
        QuotaLock.booking_id.is_(None),
        QuotaLock.created_at < expired_window
    ).delete()
    db.commit()