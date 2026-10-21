"""UPI match check (README, "9.16"): every UPI bill against the money Razorpay confirmed.

A cashier can ring a sale as UPI while the customer pays a personal QR, so the bill says UPI and
the shop's account never sees the money. This lists the UPI bills with no confirmed payment, the
ones whose confirmed amount differs, and money confirmed for a bill that was then voided, with a
count per cashier so a pattern shows. It only means something when the shop takes UPI through
Razorpay, so it says plainly when that is not set up.
"""

from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Bill, BillStatus, Payment, User
from app.services import payments
from app.services.insights import _parts


def _upi_paise(b: Bill) -> int:
    return sum(p for mode, p in _parts(b) if mode == "upi")


def build(db: Session, start: date, end: date) -> dict:
    bills = list(
        db.scalars(
            select(Bill)
            .where(Bill.business_date >= start, Bill.business_date <= end)
            .order_by(Bill.sold_at)
        )
    )
    ids = [b.id for b in bills]
    pays: dict = defaultdict(list)
    if ids:
        for p in db.scalars(select(Payment).where(Payment.bill_id.in_(ids))):
            pays[p.bill_id].append(p)
    ever = db.scalar(select(Payment.id).limit(1)) is not None
    names = dict(db.execute(select(User.id, User.name)).all())

    unconfirmed, differs, paid_void = [], [], []
    per = defaultdict(lambda: {"upi_bills": 0, "unconfirmed": 0, "unconfirmed_paise": 0})
    billed = confirmed = 0
    for b in bills:
        rows = pays.get(b.id, [])
        paid = sum(p.paid_paise or 0 for p in rows if p.status == "paid" and p.method == "upi")
        if b.status == BillStatus.void:
            if paid:
                paid_void.append({"bill_id": b.id, "invoice_no": b.invoice_no, "paid_paise": paid})
            continue
        upi = _upi_paise(b)
        if upi == 0:
            continue
        who = names.get(b.cashier_id, "Unknown")
        per[who]["upi_bills"] += 1
        billed += upi
        confirmed += min(paid, upi)
        if paid == 0:
            state = next((p.status for p in rows), "none")
            unconfirmed.append(
                {
                    "bill_id": b.id,
                    "invoice_no": b.invoice_no,
                    "sold_at": b.sold_at,
                    "cashier": who,
                    "upi_paise": upi,
                    "state": state,
                }
            )
            per[who]["unconfirmed"] += 1
            per[who]["unconfirmed_paise"] += upi
        elif paid != upi:
            differs.append(
                {
                    "bill_id": b.id,
                    "invoice_no": b.invoice_no,
                    "cashier": who,
                    "upi_paise": upi,
                    "paid_paise": paid,
                }
            )
    by_cashier = sorted(
        ({"name": n, **v} for n, v in per.items()),
        key=lambda r: (-r["unconfirmed_paise"], r["name"]),
    )
    return {
        "from": start,
        "to": end,
        "online_on": ever or payments.online_enabled(),
        "upi_bills": sum(r["upi_bills"] for r in by_cashier),
        "upi_billed_paise": billed,
        "confirmed_paise": confirmed,
        "unconfirmed": unconfirmed,
        "differs": differs,
        "paid_for_void": paid_void,
        "by_cashier": by_cashier,
    }
