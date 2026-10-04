"""Owner reports over more than one day (README, "Phase 7").

    range_report()   sales from one date to another: by day, item, hour, payment
    gst_summary()    one month in the shape of GSTR-1: B2C by rate, HSN summary,
                     documents issued
    stock_value()    what the stock on the shelf is worth at its latest cost

Every figure is the PRINTED invoice (the legal record), voided bills left out
and counted separately, like the daily sales report.
"""

import calendar
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models import Bill, BillStatus, MenuItem, Shop
from app.services.dayend import unit_costs
from app.services.stock import stock_on_hand

MAX_RANGE_DAYS = 92  # a quarter: enough for a GST return, small enough to be quick
Q3 = Decimal("0.001")


class ReportError(ValueError):
    pass


def _parts(b: Bill) -> list[tuple[str, int]]:
    """A bill's payment as (mode, paise) parts: split bills (Phase 6) count each
    part under its own mode; others are one part. Works before and after the
    payment_parts column exists."""
    parts = getattr(b, "payment_parts", None)
    if parts:
        return [(p["mode"], int(p["paise"])) for p in parts]
    return [(b.payment_mode.value, b.total_paise)]


def _bills(db: Session, start: date, end: date) -> list[Bill]:
    return list(
        db.scalars(
            select(Bill)
            .where(Bill.business_date >= start, Bill.business_date <= end)
            .order_by(Bill.sold_at)
            .options(selectinload(Bill.lines))
        )
    )


# ---------------------------------------------------------------- range
def range_report(db: Session, start: date, end: date) -> dict:
    if end < start:
        raise ReportError("The end date is before the start date")
    if (end - start).days >= MAX_RANGE_DAYS:
        raise ReportError(f"Choose at most {MAX_RANGE_DAYS} days")
    tz = ZoneInfo(get_settings().shop_timezone)
    every = _bills(db, start, end)
    bills = [b for b in every if b.status != BillStatus.void]
    voided = [b for b in every if b.status == BillStatus.void]

    days: dict[date, list[int]] = {
        start + timedelta(n): [0, 0] for n in range((end - start).days + 1)
    }
    hours: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    modes: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    items: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for b in bills:
        days[b.business_date][0] += 1
        days[b.business_date][1] += b.total_paise
        h = hours[b.sold_at.astimezone(tz).hour]
        h[0] += 1
        h[1] += b.total_paise
        for mode, paise in _parts(b):
            modes[mode][0] += 1
            modes[mode][1] += paise
        for ln in b.lines:
            items[ln.name_snapshot][0] += ln.qty
            items[ln.name_snapshot][1] += ln.total_paise
    return {
        "from": start,
        "to": end,
        "bills": len(bills),
        "total_paise": sum(b.total_paise for b in bills),
        "gst_paise": sum(b.cgst_paise + b.sgst_paise for b in bills),
        "days": [{"business_date": d, "bills": n, "total_paise": t} for d, (n, t) in days.items()],
        "items": [
            {"name": k, "qty": q, "total_paise": t}
            for k, (q, t) in sorted(items.items(), key=lambda kv: (-kv[1][1], kv[0]))
        ],
        "by_hour": [
            {"hour": h, "bills": n, "total_paise": t} for h, (n, t) in sorted(hours.items())
        ],
        "by_mode": [
            {"mode": m, "bills": n, "total_paise": t} for m, (n, t) in sorted(modes.items())
        ],
        "voids": {"bills": len(voided), "total_paise": sum(b.total_paise for b in voided)},
    }


# ---------------------------------------------------------------- GST
def month_bounds(month: str) -> tuple[date, date]:
    m = re.fullmatch(r"(\d{4})-(\d{2})", month or "")
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ReportError("Month must look like 2026-10")
    y, mo = int(m.group(1)), int(m.group(2))
    return date(y, mo, 1), date(y, mo, calendar.monthrange(y, mo)[1])


def gst_summary(db: Session, month: str) -> dict:
    """The month's sales the way GSTR-1 asks for them. Every customer of a tea
    shop is unregistered and in the shop's own state, so all sales are B2C
    (small), intra-state: CGST + SGST, place of supply = the shop's state.
    Nil-rated (0%) sales are reported separately, not as a B2C rate row."""
    start, end = month_bounds(month)
    shop = db.scalar(select(Shop))
    every = _bills(db, start, end)
    bills = [b for b in every if b.status != BillStatus.void]
    hsn_of = dict(db.execute(select(MenuItem.id, MenuItem.hsn_sac)).all())

    by_rate: dict[int, list[int]] = defaultdict(lambda: [0, 0, 0])
    hsn: dict[tuple[str, int], dict] = {}
    nil = 0
    for b in bills:
        for ln in b.lines:
            if ln.gst_rate_bp == 0 or b.gst_type.value != "regular":
                nil += ln.taxable_paise
            else:
                r = by_rate[ln.gst_rate_bp]
                r[0] += ln.taxable_paise
                r[1] += ln.cgst_paise
                r[2] += ln.sgst_paise
            # The item's code today: bills do not keep their own copy of it.
            key = (hsn_of.get(ln.menu_item_id, ""), ln.gst_rate_bp)
            row = hsn.setdefault(
                key,
                {"names": [], "qty": 0, "taxable": 0, "cgst": 0, "sgst": 0, "total": 0},
            )
            if ln.name_snapshot not in row["names"]:
                row["names"].append(ln.name_snapshot)
            row["qty"] += ln.qty
            row["taxable"] += ln.taxable_paise
            row["cgst"] += ln.cgst_paise
            row["sgst"] += ln.sgst_paise
            row["total"] += ln.total_paise

    # Documents issued (GSTR-1 table 13): each tablet's invoice series.
    series: dict[str, list[Bill]] = defaultdict(list)
    for b in every:
        series[b.invoice_no.rsplit("/", 1)[0]].append(b)
    documents = []
    for prefix, bs in sorted(series.items()):
        bs.sort(key=lambda b: b.local_seq)
        span = bs[-1].local_seq - bs[0].local_seq + 1
        cancelled = sum(1 for b in bs if b.status == BillStatus.void)
        documents.append(
            {
                "series": prefix,
                "from": bs[0].invoice_no,
                "to": bs[-1].invoice_no,
                "total": span,
                "cancelled": cancelled,
                # Numbers in the range that never reached the server (see Tablets).
                "missing": span - len(bs),
                "net_issued": len(bs) - cancelled,
            }
        )
    return {
        "month": month,
        "gst_type": shop.gst_type.value,
        "gstin": shop.gstin,
        "state_code": shop.state_code,
        "b2cs": [
            {
                "place_of_supply": shop.state_code,
                "rate_bp": rate,
                "taxable_paise": t,
                "cgst_paise": c,
                "sgst_paise": s,
            }
            for rate, (t, c, s) in sorted(by_rate.items())
        ],
        "nil_rated_paise": nil,
        "hsn": [
            {
                "hsn_sac": code,
                "description": ", ".join(row["names"][:3]) + ("…" if len(row["names"]) > 3 else ""),
                "uqc": "NOS",
                "rate_bp": rate,
                "qty": row["qty"],
                "taxable_paise": row["taxable"],
                "cgst_paise": row["cgst"],
                "sgst_paise": row["sgst"],
                "total_paise": row["total"],
            }
            for (code, rate), row in sorted(hsn.items())
        ],
        "documents": documents,
        "totals": {
            "invoices": len(bills),
            "invoice_value_paise": sum(b.total_paise for b in bills),
            "taxable_paise": sum(b.taxable_paise for b in bills),
            "cgst_paise": sum(b.cgst_paise for b in bills),
            "sgst_paise": sum(b.sgst_paise for b in bills),
        },
    }


# ---------------------------------------------------------------- stock value
def stock_value(db: Session) -> dict:
    """On hand x latest cost per base unit (a batch item: its ingredients' cost).
    Negative stock is worth nothing here and is listed so it gets fixed."""
    rows = [r for r in stock_on_hand(db) if r.ingredient.is_active or r.qty != 0]
    costs = unit_costs(db, [r.ingredient for r in rows])
    items = []
    for r in rows:
        cost = costs.get(r.ingredient.id, Decimal(0))
        value = (r.qty * cost).quantize(Decimal(1), rounding=ROUND_HALF_UP) if r.qty > 0 else 0
        items.append(
            {
                "ingredient_id": r.ingredient.id,
                "name": r.ingredient.name,
                "kind": r.ingredient.kind.value,
                "base_unit": r.ingredient.base_unit.value,
                "on_hand": str(r.qty.quantize(Q3)),
                "unit_cost_paise": str(cost.quantize(Decimal("0.0001"))),
                "value_paise": int(value),
                "negative": r.qty < 0,
                "no_cost": cost == 0,
            }
        )
    items.sort(key=lambda x: (-x["value_paise"], x["name"]))
    return {"items": items, "total_paise": sum(x["value_paise"] for x in items)}
