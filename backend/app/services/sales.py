"""The owner's sales report for one business day.

Figures are the PRINTED totals (the legal invoices), voided bills excluded and
listed separately. Bills where the tablet and the server disagreed are listed so
the owner can look at them; they still count at the printed amount.
"""

from collections import defaultdict
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models import Bill, BillStatus, BillVoid, CreditRepayment, User
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
    from app.services.billing import credit_paise, payment_split  # local: billing imports a lot

    for b in bills:
        # A split bill counts each part under its own mode (cash 20 + UPI 40).
        for mode, paise in payment_split(b):
            by_mode[mode][0] += 1
            by_mode[mode][1] += paise
        for key, bucket in (
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

    repaid = db.scalar(
        select(func.coalesce(func.sum(CreditRepayment.amount_paise), 0)).where(
            CreditRepayment.business_date == d
        )
    )
    day = db.scalar(select(DayCount).where(DayCount.business_date == d))
    return {
        "business_date": d,
        "day_status": day.status.value if day else None,
        "bills": len(bills),
        "total_paise": sum(b.total_paise for b in bills),
        "taxable_paise": sum(b.taxable_paise for b in bills),
        "cgst_paise": sum(b.cgst_paise for b in bills),
        "sgst_paise": sum(b.sgst_paise for b in bills),
        "round_off_paise": sum(b.round_off_paise for b in bills),
        # Phase 6: discounts given, credit given (on khata), credit repaid today.
        "discount_paise": sum(b.discount_paise for b in bills),
        "discounts": [
            {
                "bill_id": b.id,
                "invoice_no": b.invoice_no,
                "discount_paise": b.discount_paise,
                "total_paise": b.total_paise,
                "reason": b.discount_reason,
                "by_name": cashiers.get(b.cashier_id, "?"),
                "over_limit": "discount_over_limit" in (b.flags or []),
            }
            for b in bills
            if b.discount_paise
        ],
        "credit_given_paise": sum(credit_paise(b) for b in bills),
        "repaid_paise": int(repaid or 0),
        "flagged": [
            {"bill_id": b.id, "invoice_no": b.invoice_no, "flags": b.flags}
            for b in bills
            if b.flags
        ],
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
    }
