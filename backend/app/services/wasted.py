"""What the shop wasted, from its own wastage entries (README, "9.18"). No AI: sums and a
weekday split. Only entries that count as a known loss (approved); a cashier's large entry still
waiting for the owner, and one the owner rejected, are left out."""

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Ingredient, MenuItem, SoldOutEvent, WastageEntry, WastageStatus

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TOP = 5


def _top_reason(rows: list[WastageEntry]) -> str:
    sums: dict[str, int] = defaultdict(int)
    for r in rows:
        sums[r.reason.value] += r.value_paise
    return max(sums, key=lambda k: (sums[k], k))


def build(db: Session, end: date, days: int = 28) -> dict:
    start = end - timedelta(days=days - 1)
    rows = db.scalars(
        select(WastageEntry).where(
            WastageEntry.business_date >= start,
            WastageEntry.business_date <= end,
            WastageEntry.status == WastageStatus.approved,
        )
    ).all()
    names = {i.id: i.name for i in db.scalars(select(Ingredient))}
    names.update({m.id: m.name for m in db.scalars(select(MenuItem))})
    by_item: dict[str, int] = defaultdict(int)
    by_day = [0] * 7
    by_reason: dict[str, int] = defaultdict(int)
    for r in rows:
        by_item[names.get(r.ingredient_id or r.menu_item_id, "Unknown")] += r.value_paise
        by_day[r.business_date.weekday()] += r.value_paise
        by_reason[r.reason.value] += r.value_paise
    sold_out = db.execute(
        select(MenuItem.name, func.count())
        .join(SoldOutEvent, SoldOutEvent.menu_item_id == MenuItem.id)
        .where(SoldOutEvent.business_date >= start, SoldOutEvent.business_date <= end)
        .group_by(MenuItem.name)
        .order_by(func.count().desc(), MenuItem.name)
        .limit(TOP)
    ).all()
    total = sum(by_day)
    worst = max(range(7), key=lambda d: by_day[d]) if total else None
    return {
        "from": start,
        "to": end,
        "total_paise": total,
        "entries": len(rows),
        "items": [
            {"name": n, "paise": p}
            for n, p in sorted(by_item.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP]
            if p > 0
        ],
        "worst_day": None
        if worst is None
        else {
            "weekday": WEEKDAYS[worst],
            "paise": by_day[worst],
            "top_reason": _top_reason([r for r in rows if r.business_date.weekday() == worst]),
        },
        "sold_out": [{"name": n, "times": int(c)} for n, c in sold_out],
        "reasons": [
            {"reason": k, "paise": v} for k, v in sorted(by_reason.items(), key=lambda kv: -kv[1])
        ],
    }
