"""The owner's sales report for one business day.

Figures are the PRINTED totals (the legal invoices), voided bills excluded and
listed separately. Bills where the tablet and the server disagreed are listed so
the owner can look at them; they still count at the printed amount.
"""

from collections import defaultdict
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models import Bill, BillStatus, BillVoid, Payment, User
from app.models.dayend import DayCount


def sales_report(db: Session, d: date) -> dict:
    tz = ZoneInfo(get_settings().shop_timezone)
    every = db.scalars(
        select(Bill)
        .where(Bill.business_date == d)
        .order_by(Bill.sold_at)
        .options(selectinload(Bill.lines), selectinload(Bill.void).selectinload(BillVoid.user))
    ).all()
    bills = [b for b in every if b.status != BillStatus.void]
    voided = [b for b in every if b.status == BillStatus.void]
    cashiers = dict(db.execute(select(User.id, User.name)).all())

    by_mode: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_hour: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    by_cashier: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    items: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    rates: dict[int, list[int]] = defaultdict(lambda: [0, 0, 0])
    for b in bills:
        for key, bucket in (
            (b.payment_mode.value, by_mode),
            (b.sold_at.astimezone(tz).hour, by_hour),
            (cashiers.get(b.cashier_id, "?"), by_cashier),
        ):
            bucket[key][0] += 1
            bucket[key][1] += b.total_paise
        for ln in b.lines:
            items[ln.name_snapshot][0] += ln.qty
            items[ln.name_snapshot][1] += ln.total_paise
            r = rates[ln.gst_rate_bp]
            r[0] += ln.taxable_paise
            r[1] += ln.cgst_paise
            r[2] += ln.sgst_paise

    day = db.scalar(select(DayCount).where(DayCount.business_date == d))
    online = _online_payments(db, every)
    return {
        "business_date": d,
        "day_status": day.status.value if day else None,
        "bills": len(bills),
        "total_paise": sum(b.total_paise for b in bills),
        "taxable_paise": sum(b.taxable_paise for b in bills),
        "cgst_paise": sum(b.cgst_paise for b in bills),
        "sgst_paise": sum(b.sgst_paise for b in bills),
        "round_off_paise": sum(b.round_off_paise for b in bills),
        "by_mode": [
            {"mode": m, "bills": n, "total_paise": t} for m, (n, t) in sorted(by_mode.items())
        ],
        "by_hour": [
            {"hour": h, "bills": n, "total_paise": t} for h, (n, t) in sorted(by_hour.items())
        ],
        "by_cashier": [
            {"name": c, "bills": n, "total_paise": t}
            for c, (n, t) in sorted(by_cashier.items(), key=lambda kv: -kv[1][1])
        ],
        "items": [
            {"name": n, "qty": q, "total_paise": t}
            for n, (q, t) in sorted(items.items(), key=lambda kv: (-kv[1][1], kv[0]))
        ],
        "gst_by_rate": [
            {"rate_bp": rate, "taxable_paise": tx, "cgst_paise": c, "sgst_paise": s}
            for rate, (tx, c, s) in sorted(rates.items())
        ],
        "voids": [
            {
                "bill_id": b.id,
                "invoice_no": b.invoice_no,
                "total_paise": b.total_paise,
                "reason": b.void.reason.value,
                "note": b.void.note,
                "stock_returned": b.void.stock_returned,
                "voided_by_name": b.void.voided_by_name,
                "voided_at": b.void.voided_at,
            }
            for b in voided
            if b.void is not None
        ],
        "mismatches": [
            {
                "bill_id": b.id,
                "invoice_no": b.invoice_no,
                "total_paise": b.total_paise,
                "server_total_paise": int(b.server_totals.get("total", b.total_paise)),
            }
            for b in bills
            if b.totals_mismatch
        ],
        "online_payments": online,
    }


def _online_payments(db: Session, every: list[Bill]) -> list[dict]:
    """One line per bill paid (or meant to be paid) online, with what the owner
    should look at: not paid, paid a different amount, or paid and then voided."""
    from app.services.payments import problem  # local: payments imports models only

    by_id = {b.id: b for b in every}
    if not by_id:
        return []
    chosen: dict = {}
    for p in db.scalars(
        select(Payment).where(Payment.bill_id.in_(list(by_id))).order_by(Payment.created_at)
    ):
        # A paid row wins; otherwise the latest attempt.
        if chosen.get(p.bill_id) is None or chosen[p.bill_id].status != "paid":
            chosen[p.bill_id] = p
    return [
        {
            "bill_id": b.id,
            "invoice_no": b.invoice_no,
            "method": p.method,
            "status": p.status,
            "amount_paise": p.amount_paise,
            "paid_paise": p.paid_paise,
            "provider_payment_id": p.provider_payment_id,
            "error": p.error,
            "problem": problem(p, b),
        }
        for b in every
        if (p := chosen.get(b.id)) is not None
    ]
