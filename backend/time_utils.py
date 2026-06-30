"""Timezone helpers used across FRIDAY.

Database timestamps are intentionally stored as naive Asia/Kolkata values.  This
keeps compatibility with the existing schema while making behaviour identical
on a developer laptop and on Cloud Run (whose host timezone is normally UTC).
"""

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    """Return the current IST time as a naive datetime for database use."""
    return datetime.now(IST).replace(tzinfo=None)


def to_ist_naive(value: datetime) -> datetime:
    """Normalize an aware or naive datetime to a naive IST datetime."""
    if value.tzinfo is None:
        # Gemini is explicitly told to return IST. Preserve legacy naive values.
        return value
    return value.astimezone(IST).replace(tzinfo=None)


def parse_iso_datetime(value: object) -> Optional[datetime]:
    """Parse an ISO-8601 value and normalize it for the database."""
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return to_ist_naive(parsed)


def from_unix_timestamp(value: int | float) -> datetime:
    """Convert a Unix timestamp to a naive IST datetime."""
    return datetime.fromtimestamp(value, tz=timezone.utc).astimezone(IST).replace(tzinfo=None)
