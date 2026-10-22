"""Festivals and other days the owner expects to be different (README, "9.21"): for each coming
one, what the same date brought last year against that weekday's usual, so the owner can prepare.

Fixed-date national days are suggested; **moveable festivals (Diwali, Pongal, Eid...) are not
guessed**: their dates change every year and a wrong one would mislead. The owner adds them.
"""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Bill, BillStatus, SpecialDay

FIXED = [(1, 1, "New Year's Day"), (1, 26, "Republic Day"), (5, 1, "May Day"),
         (8, 15, "Independence Day"), (10, 2, "Gandhi Jayanti"), (12, 25, "Christmas")]  # fmt: skip


def _sales(db: Session, d: date) -> tuple[int, int]:
    row = db.execute(
        select(func.coalesce(func.sum(Bill.total_paise), 0), func.count()).where(
            Bill.business_date == d, Bill.status != BillStatus.void
        )
    ).one()
    return int(row[0]), int(row[1])


def _a_year_before(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # 29 February
        return d.replace(year=d.year - 1, day=28)


def look_back(db: Session, d: date) -> dict:
    """Last year's same date, and the average of that weekday in the four weeks before it."""
    then = _a_year_before(d)
    sales, bills = _sales(db, then)
    usual = [_sales(db, then - timedelta(days=7 * w))[0] for w in range(1, 5)]
    usual = [u for u in usual if u > 0]
    return {
        "last_year_date": then,
        "last_year_paise": sales,
        "last_year_bills": bills,
        "usual_weekday_paise": round(sum(usual) / len(usual)) if usual else None,
    }


def upcoming(db: Session, today: date, days: int = 120) -> dict:
    end = today + timedelta(days=days)
    mine = db.scalars(
        select(SpecialDay)
        .where(SpecialDay.day >= today, SpecialDay.day <= end)
        .order_by(SpecialDay.day)
    ).all()
    have = {(m.day, m.name) for m in mine}
    suggestions = []
    for year in (today.year, today.year + 1):
        for month, dd, name in FIXED:
            d = date(year, month, dd)
            if today <= d <= end and (d, name) not in have:
                suggestions.append({"day": d, "name": name})
    suggestions.sort(key=lambda s: s["day"])
    return {
        "days": [{"id": m.id, "day": m.day, "name": m.name, **look_back(db, m.day)} for m in mine],
        "suggestions": suggestions,
    }
