from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from app.core.config import settings


@lru_cache
def restaurant_tz() -> ZoneInfo:
    return ZoneInfo(settings.restaurant_tz)


def utcnow() -> datetime:
    return datetime.now(UTC)


def local_now() -> datetime:
    return datetime.now(restaurant_tz())


def business_date(moment: datetime | None = None) -> date:
    """The restaurant's calendar date for a moment (now by default).

    An order placed at 01:00 in Dhaka is 19:00 the previous day in UTC, it still
    belongs to today's business.
    """
    moment = moment or utcnow()
    return moment.astimezone(restaurant_tz()).date()


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """[start, end) of a local calendar day as UTC datetimes, for range filters."""
    start = datetime.combine(day, time.min, tzinfo=restaurant_tz())
    end = start + timedelta(days=1)
    return start.astimezone(UTC), end.astimezone(UTC)


def range_bounds(start_day: date, end_day: date) -> tuple[datetime, datetime]:
    """[start of start_day, end of end_day) in UTC, both days included."""
    return day_bounds(start_day)[0], day_bounds(end_day)[1]
