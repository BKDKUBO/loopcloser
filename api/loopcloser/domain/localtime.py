"""Calendar dates in Manila time, the zone the API's today() uses. Stored timestamps are UTC."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

MANILA = ZoneInfo("Asia/Manila")


def local_date(dt: datetime) -> date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(MANILA).date()
