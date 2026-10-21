"""Bill trail and the day's changes (README, "9.16").

A bill is never edited (the database refuses), so the story of a sale is a list of facts: who
rang it, what was taken off and why, which items were cancelled on the running order, how the
payment went, and if it was voided, by whom. This reads those facts into one timeline per bill,
and a day's list of everything that took money out of a sale.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Bill,
    BillVoid,
    Device,
    Order,
    OrderEvent,
    OrderEventKind,
    Payment,
    User,
)

LATE_SYNC_MINUTES = 30
FLAG_TEXT = {
    "discount_over_limit": "The discount was over the limit set for cashiers",
    "discount_without_reason": "A discount was given with no reason written",
    "payment_parts_mismatch": "The payment parts did not add up to the bill",
    "credit_without_customer": "Put on credit with no customer chosen",
}
EVENT_TITLE = {
    OrderEventKind.open: "Order opened",
    OrderEventKind.kot: "Items sent to the kitchen",
    OrderEventKind.cancel: "Items cancelled",
    OrderEventKind.move: "Moved to another table",
    OrderEventKind.details: "Details changed",
    OrderEventKind.bill_printed: "Bill printed",
    OrderEventKind.ready: "Kitchen finished items",
    OrderEventKind.settle: "Paid",
    OrderEventKind.cancel_order: "Whole order cancelled",
}


def _fact(at, kind, title, detail="", by="", amount=None) -> dict:
    return {
        "at": at,
        "kind": kind,
        "title": title,
        "detail": detail,
        "by": by,
        "amount_paise": amount,
    }


def _line_names(order: Order | None) -> dict:
    lines = (order.state or {}).get("lines", []) if order else []
    return {ln["line_id"]: ln.get("name", "an item") for ln in lines}


def _event_fact(e: OrderEvent, names: dict, who: dict) -> dict:
    detail = ""
    if e.kind == OrderEventKind.cancel:
        detail = f"{e.data.get('qty', '')} x {names.get(e.data.get('line_id'), 'an item')}"
        if e.data.get("reason"):
            detail += f" ({e.data['reason']})"
    elif e.kind == OrderEventKind.cancel_order:
        detail = str(e.data.get("reason", ""))
    return _fact(e.at, f"order_{e.kind.value}", EVENT_TITLE[e.kind], detail, who.get(e.by, ""))


def bill_trail(db: Session, bill: Bill) -> list[dict]:
    who = dict(db.execute(select(User.id, User.name)).all())
    device = db.scalar(select(Device.code).where(Device.id == bill.device_id)) or ""
    out = [
        _fact(
            bill.sold_at,
            "sold",
            "Bill rung up",
            f"{bill.invoice_no} on {device}, paid by {bill.payment_mode.value}",
            who.get(bill.cashier_id, ""),
            bill.total_paise,
        )
    ]
    late = (bill.received_at - bill.sold_at).total_seconds() / 60
    if late >= LATE_SYNC_MINUTES:
        out.append(
            _fact(
                bill.received_at,
                "late",
                "Reached the server late",
                f"{int(late)} minutes after the sale (the tablet was offline)",
            )
        )
    if bill.discount_paise:
        out.append(
            _fact(
                bill.sold_at,
                "discount",
                "Discount given",
                bill.discount_reason or "No reason written",
                who.get(bill.cashier_id, ""),
                bill.discount_paise,
            )
        )
    for flag in bill.flags or []:
        out.append(_fact(bill.sold_at, "flag", FLAG_TEXT.get(flag, flag)))
    if bill.order_id:
        order = db.scalar(select(Order).where(Order.id == bill.order_id))
        names = _line_names(order)
        for e in db.scalars(
            select(OrderEvent).where(OrderEvent.order_id == bill.order_id).order_by(OrderEvent.at)
        ):
            out.append(_event_fact(e, names, who))
    for p in db.scalars(select(Payment).where(Payment.bill_id == bill.id)):
        word = {"paid": "Payment confirmed", "failed": "Payment failed"}.get(
            p.status, "Payment asked for"
        )
        out.append(
            _fact(
                p.paid_at or p.created_at,
                "payment",
                word,
                f"{p.method.upper()} through {p.provider}" + (f": {p.error}" if p.error else ""),
                "",
                p.paid_paise if p.status == "paid" else p.amount_paise,
            )
        )
    void = db.scalar(select(BillVoid).where(BillVoid.bill_id == bill.id))
    if void:
        out.append(
            _fact(
                void.voided_at,
                "void",
                "Bill voided",
                f"{void.reason.value.replace('_', ' ')}"
                + (f" - {void.note}" if void.note else "")
                + ("; stock came back" if void.stock_returned else "; stock stayed used"),
                who.get(void.voided_by, ""),
                bill.total_paise,
            )
        )
    return sorted(out, key=lambda f: f["at"])


def _window(d: date) -> tuple[datetime, datetime]:
    tz = ZoneInfo(get_settings().shop_timezone)
    start = datetime.combine(d, time(0), tzinfo=tz)
    return start, start + timedelta(days=1)


def changes(db: Session, d: date) -> dict:
    """Everything on one business day that took money or items out of a sale."""
    who = dict(db.execute(select(User.id, User.name)).all())
    rows: list[dict] = []
    start, end = _window(d)
    for v, b in db.execute(
        select(BillVoid, Bill)
        .join(Bill, Bill.id == BillVoid.bill_id)
        .where(BillVoid.voided_at >= start, BillVoid.voided_at < end)
    ):
        r = _fact(
            v.voided_at,
            "void",
            f"Voided {b.invoice_no}",
            v.reason.value.replace("_", " ") + (f" - {v.note}" if v.note else ""),
            who.get(v.voided_by, ""),
            b.total_paise,
        )
        rows.append({**r, "bill_id": b.id, "order_id": None})
    for b in db.scalars(select(Bill).where(Bill.business_date == d, Bill.discount_paise > 0)):
        r = _fact(
            b.sold_at,
            "discount",
            f"Discount on {b.invoice_no}",
            b.discount_reason or "No reason written",
            who.get(b.cashier_id, ""),
            b.discount_paise,
        )
        rows.append({**r, "bill_id": b.id, "order_id": None})
    orders = {o.id: o for o in db.scalars(select(Order).where(Order.business_date == d))}
    if orders:
        for e in db.scalars(
            select(OrderEvent).where(
                OrderEvent.order_id.in_(list(orders)),
                OrderEvent.kind.in_([OrderEventKind.cancel, OrderEventKind.cancel_order]),
            )
        ):
            r = _event_fact(e, _line_names(orders[e.order_id]), who)
            rows.append({**r, "bill_id": None, "order_id": e.order_id})
    for b in db.scalars(select(Bill).where(Bill.business_date == d)):
        late = (b.received_at - b.sold_at).total_seconds() / 60
        if late >= LATE_SYNC_MINUTES * 4:
            r = _fact(
                b.received_at,
                "late",
                f"{b.invoice_no} reached the server late",
                f"{int(late)} minutes after the sale",
                who.get(b.cashier_id, ""),
                b.total_paise,
            )
            rows.append({**r, "bill_id": b.id, "order_id": None})
    rows.sort(key=lambda r: r["at"])
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    return {"date": d, "rows": rows, "counts": counts}
