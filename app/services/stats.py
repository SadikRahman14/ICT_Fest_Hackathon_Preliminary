"""Live per-room booking statistics.

Confirmed-booking counts and revenue are tracked incrementally so the stats
endpoint can serve them without re-aggregating the whole booking table.
"""
import threading

_stats: dict[int, dict] = {}
_lock = threading.Lock()


def record_create(room_id: int, price_cents: int) -> None:
    with _lock:
        current = _stats.get(room_id, {"count": 0, "revenue": 0})
        _stats[room_id] = {
            "count": current["count"] + 1,
            "revenue": current["revenue"] + price_cents
        }


def record_cancel(room_id: int, price_cents: int) -> None:
    with _lock:
        current = _stats.get(room_id, {"count": 0, "revenue": 0})
        _stats[room_id] = {
            "count": max(0, current["count"] - 1),
            "revenue": max(0, current["revenue"] - price_cents)
        }


def get(room_id: int) -> dict:
    with _lock:
        return _stats.get(room_id, {"count": 0, "revenue": 0}).copy()


def recalculate_from_db(db_session, room_id: int) -> None:
    """Recalculate stats from database to ensure consistency."""
    from ..models import Booking
    from sqlalchemy import func
    
    result = (
        db_session.query(
            func.count(Booking.id),
            func.sum(Booking.price_cents)
        )
        .filter(
            Booking.room_id == room_id,
            Booking.status == "confirmed"
        )
        .first()
    )
    
    count = result[0] or 0
    revenue = result[1] or 0
    
    with _lock:
        _stats[room_id] = {"count": count, "revenue": revenue}