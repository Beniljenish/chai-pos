from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


def business_date(at: datetime | None = None) -> date:
    """The shop-local calendar date. A sale at 00:30 IST on the 4th is a 4th sale,
    even though it is still the 3rd in UTC."""
    at = at or utcnow()
    return at.astimezone(ZoneInfo(get_settings().shop_timezone)).date()
