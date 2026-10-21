"""What needs the owner, worked out from what the app already records (README, "9.10").

Nothing is stored: every alert is derived each time from bills, voids, shifts,
wastage, stock receipts and the closed day counts. The rules are fixed and
deliberately plain, so an alert can always be explained in one sentence:

  drawer short   a closed shift counted at least Rs 20 under what the bills say
  void burst     3 or more voids by one person within an hour
  discounts      more than Rs 50 given in a day and 3x the usual (last 14 days)
  wastage        a large entry waiting for approval
  price up       an ingredient's latest purchase cost 5% or more above the one before
  over recipe    used 10% or more over the recipe across 3 or more closed days

"act" is something to deal with now, "look" is worth a look, "info" is news.
"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import business_date as shop_date
from app.models import (
    Bill,
    BillStatus,
    BillVoid,
    Ingredient,
    StockReceipt,
    User,
    WastageEntry,
    WastageStatus,
)
from app.services import dayend, shifts

SHORT_DRAWER_PAISE = 2_000
OVER_DRAWER_PAISE = 10_000
VOID_BURST = 3
VOID_WINDOW = timedelta(hours=1)
DISCOUNT_FLOOR_PAISE = 5_000
DISCOUNT_MULTIPLE = 3
DISCOUNT_BASELINE_DAYS = 14
PRICE_RISE_PCT = 5
PRICE_LOOKBACK_DAYS = 14
OVER_RECIPE_PCT = 10
OVER_RECIPE_DAYS = 3
URGENCY = {"act": 0, "look": 1, "info": 2}
PER = {"ml": ("litre", 1000), "g": ("kg", 1000), "piece": ("piece", 1)}


def _tz() -> ZoneInfo:
    return ZoneInfo(get_settings().shop_timezone)


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time(0), tzinfo=_tz())


def _clock(dt: datetime) -> str:
    return dt.astimezone(_tz()).strftime("%I:%M %p").lstrip("0").lower()


def _alert(kind, urgency, period, title, detail, at=None, section="sales", key="") -> dict:
    return {
        "id": f"{kind}:{key}" if key else kind,
        "kind": kind,
        "urgency": urgency,
        "period": period,
        "title": title,
        "detail": detail,
        "at": at,
        "section": section,
    }


def build(db: Session, d: date | None = None) -> list[dict]:
    """Alerts for business day `d` (default: today), most urgent first."""
    from app.services.reports import rupees  # reports uses this module too

    d = d or shop_date()
    out: list[dict] = []
    names = dict(db.execute(select(User.id, User.name)).all())

    # ---- cash drawer
    for s in shifts.shift_report(db, d)["shifts"]:
        diff = s["difference_paise"]
        if diff is None or s["closed_at"] is None:
            continue
        who = s["opened_by_name"] or "A cashier"
        detail = (
            f"{who}'s shift on {s['device']}, counted {_clock(s['closed_at'])}. "
            f"The bills say {rupees(s['expected_cash_paise'])}, the drawer had "
            f"{rupees(s['counted_cash_paise'])}."
        )
        if diff <= -SHORT_DRAWER_PAISE:
            out.append(
                _alert(
                    "drawer_short",
                    "act",
                    "today",
                    f"Drawer short by {rupees(-diff)}",
                    detail,
                    s["closed_at"],
                    "sales",
                    str(s["id"]),
                )
            )
        elif diff >= OVER_DRAWER_PAISE:
            out.append(
                _alert(
                    "drawer_over",
                    "look",
                    "today",
                    f"Drawer over by {rupees(diff)}",
                    detail,
                    s["closed_at"],
                    "sales",
                    str(s["id"]),
                )
            )

    # ---- void bursts
    start, end = _day_start(d), _day_start(d + timedelta(days=1))
    voids = db.execute(
        select(BillVoid.voided_by, BillVoid.voided_at, Bill.total_paise)
        .join(Bill, Bill.id == BillVoid.bill_id)
        .where(BillVoid.voided_at >= start, BillVoid.voided_at < end)
        .order_by(BillVoid.voided_at)
    ).all()
    by_person = defaultdict(list)
    for who, at, total in voids:
        by_person[who].append((at, total))
    for who, rows in by_person.items():
        best: list = []
        for i, (at, _) in enumerate(rows):
            window = [r for r in rows[i:] if r[0] - at <= VOID_WINDOW]
            if len(window) > len(best):
                best = window
        if len(best) >= VOID_BURST:
            out.append(
                _alert(
                    "void_burst",
                    "act",
                    "today",
                    f"{len(best)} voids in one hour",
                    f"{names.get(who, 'Someone')} voided {len(best)} bills between "
                    f"{_clock(best[0][0])} and {_clock(best[-1][0])} "
                    f"({rupees(sum(t for _, t in best))}).",
                    best[-1][0],
                    "sales",
                    str(who),
                )
            )

    # ---- discounts above the usual
    today_bills = db.execute(
        select(Bill.discount_paise, Bill.discount_reason, Bill.cashier_id).where(
            Bill.business_date == d, Bill.status != BillStatus.void, Bill.discount_paise > 0
        )
    ).all()
    given = sum(r[0] for r in today_bills)
    if given >= DISCOUNT_FLOOR_PAISE:
        first = d - timedelta(days=DISCOUNT_BASELINE_DAYS)
        past = db.execute(
            select(Bill.business_date, Bill.discount_paise).where(
                Bill.business_date >= first,
                Bill.business_date < d,
                Bill.status != BillStatus.void,
                Bill.discount_paise > 0,
            )
        ).all()
        usual = sum(p for _, p in past) / DISCOUNT_BASELINE_DAYS
        if given >= DISCOUNT_MULTIPLE * usual:
            who = defaultdict(int)
            for paise, _, cashier in today_bills:
                who[cashier] += paise
            top = max(who, key=who.get)
            no_reason = sum(1 for _, reason, _ in today_bills if not reason.strip())
            out.append(
                _alert(
                    "discounts",
                    "look",
                    "today",
                    "Discounts above the usual",
                    f"{rupees(given)} given today"
                    + (
                        f", usual is about {rupees(round(usual))} a day"
                        if usual
                        else ", none in the last two weeks"
                    )
                    + f". Most by {names.get(top, 'someone')}"
                    + (f"; {no_reason} with no reason." if no_reason else "."),
                    None,
                    "sales",
                )
            )

    # ---- large wastage waiting
    pending = db.execute(
        select(WastageEntry.created_at).where(WastageEntry.status == WastageStatus.pending)
    ).all()
    if pending:
        n = len(pending)
        out.append(
            _alert(
                "wastage_pending",
                "act",
                "today",
                f"{n} large wastage {'entry' if n == 1 else 'entries'} waiting",
                "Approve or reject them under Day end. Until you decide, they count as missing.",
                max(r[0] for r in pending),
                "dayend",
            )
        )

    # ---- ingredient prices
    week_ago = d - timedelta(days=PRICE_LOOKBACK_DAYS)
    for ing in db.scalars(select(Ingredient).where(Ingredient.is_active)):
        last_two = db.scalars(
            select(StockReceipt)
            .where(
                StockReceipt.ingredient_id == ing.id,
                StockReceipt.cost_paise > 0,
                StockReceipt.base_qty > 0,
            )
            .order_by(StockReceipt.received_at.desc())
            .limit(2)
        ).all()
        if len(last_two) < 2 or last_two[0].business_date < week_ago:
            continue
        new = Decimal(last_two[0].cost_paise) / last_two[0].base_qty
        old = Decimal(last_two[1].cost_paise) / last_two[1].base_qty
        rise = (new - old) * 100 / old
        if rise >= PRICE_RISE_PCT:
            label, factor = PER[ing.base_unit.value]
            out.append(
                _alert(
                    "price_up",
                    "info",
                    "week",
                    f"{ing.name} cost went up {round(rise)}%",
                    f"{rupees(round(old * factor))} → {rupees(round(new * factor))} per {label} "
                    "since the last purchase. Check Margin for the items it affects.",
                    last_two[0].received_at,
                    "margin",
                    str(ing.id),
                )
            )

    # ---- using more than the recipe
    closed, lines = dayend.adherence_trend(db, d - timedelta(days=13), d)
    if len(closed) >= OVER_RECIPE_DAYS:
        for t in lines:
            if t.expected_usage > 0 and t.actual_usage * 100 >= t.expected_usage * (
                100 + OVER_RECIPE_PCT
            ):
                over = round((t.actual_usage / t.expected_usage - 1) * 100)
                out.append(
                    _alert(
                        "over_recipe",
                        "look",
                        "week",
                        f"{t.ingredient.name} running {over}% over the recipe",
                        f"Across the last {len(closed)} closed days. The recipe may need "
                        "updating, or check the scoop.",
                        None,
                        "dayend",
                        str(t.ingredient.id),
                    )
                )

    out.sort(
        key=lambda a: (
            URGENCY[a["urgency"]],
            -(a["at"].timestamp() if a["at"] else 0),
            a["title"],
        )
    )
    return out
