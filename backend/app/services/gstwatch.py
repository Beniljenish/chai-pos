"""GST registration threshold watch (README, "9.16").

An unregistered shop must register once its yearly turnover (before GST) passes a limit that
depends on what it sells and where. The app does not know the limit that applies, so the owner
types it after asking an accountant. Until then this only shows turnover.

Turnover is the printed taxable value of the financial year's bills (1 April to 31 March),
voided bills left out, the same bills the GST return is built from.
"""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time import business_date
from app.models import Bill, BillStatus, GstType, Shop

TRAILING_DAYS = 60  # run rate: how fast the shop has been selling lately
WATCH_AT_PCT = 80


def fy_bounds(today: date) -> tuple[date, date]:
    start = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
    return start, date(start.year + 1, 3, 31)


def _taxable(db: Session, start: date, end: date) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(Bill.taxable_paise), 0)).where(
                Bill.business_date >= start,
                Bill.business_date <= end,
                Bill.status == BillStatus.completed,
            )
        )
        or 0
    )


def build(db: Session, today: date | None = None) -> dict:
    today = today or business_date()
    shop = db.scalar(select(Shop))
    start, end = fy_bounds(today)
    turnover = _taxable(db, start, end)
    recent_from = max(start, today - timedelta(days=TRAILING_DAYS - 1))
    recent_days = (today - recent_from).days + 1
    daily = _taxable(db, recent_from, today) // recent_days
    threshold = shop.gst_threshold_paise
    registered = shop.gst_type != GstType.unregistered

    cross_on = None
    if threshold and turnover < threshold and daily > 0:
        days_left = -(-(threshold - turnover) // daily)  # ceiling
        # A trickle of sales never reaches the limit; do not forecast past ten years.
        cross_on = today + timedelta(days=days_left) if days_left <= 3650 else None
    pct = None if not threshold else turnover * 100 // threshold

    if registered:
        status = "registered"
    elif not threshold:
        status = "no_threshold"
    elif turnover >= threshold:
        status = "over"
    elif pct >= WATCH_AT_PCT or (cross_on is not None and cross_on <= end):
        status = "watch"
    else:
        status = "safe"
    return {
        "status": status,
        "fy_from": start,
        "fy_to": end,
        "turnover_paise": turnover,
        "threshold_paise": threshold,
        "percent": pct,
        "daily_paise": daily,
        "cross_on": cross_on,
    }
