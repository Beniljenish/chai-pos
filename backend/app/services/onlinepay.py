"""Paying online for a food court order (README, "9.14").

    start()     check the cart at every outlet, price it, open one Razorpay order for the total
    fulfil()    once the payment is confirmed: place each outlet's order, refund any that cannot be
    money()     what an outlet is owed, and what must be refunded

Nothing reaches a kitchen until the payment is confirmed, so an order that was never paid for is
never cooked. Everything lands in the app's single Razorpay account; the operator settles with
each outlet afterwards (`OnlineSettlement`). Razorpay's own confirmation is the only thing that
marks a payment paid (the signature, then a look at the payment itself), exactly as for a till bill.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models import (
    CustomerAccount,
    FoodCourt,
    FoodCourtOutlet,
    OnlineOrder,
    OnlinePayment,
    OnlineSettlement,
    Order,
    OrderStatus,
    Shop,
)
from app.services import online, payments
from app.services.online import OnlineError

MAX_OUTLETS = 6
MAX_CHECKOUT_PAISE = 2_000_000  # ₹20,000 in one go: well above any food court meal


@dataclass
class PartIn:
    outlet_id: uuid.UUID
    request_id: uuid.UUID
    note: str
    items: list[online.Pick]
    pickup_at: datetime | None = None
    table_name: str = ""


_PAYMENT_WORDS = {
    "online_payments_off": ("Online payment is not available. Pay at the counter.", 503),
    "razorpay_unreachable": (
        "Could not reach the payment service. Try again, or pay at the counter.",
        502,
    ),
    "razorpay_keys_refused": ("Online payment is not available. Pay at the counter.", 502),
    "razorpay_refused": (
        "The payment service refused this. Try again, or pay at the counter.",
        502,
    ),
}


def _from_payment_error(e: payments.PaymentError) -> OnlineError:
    message, status = _PAYMENT_WORDS.get(e.code, ("Could not start the payment.", e.status))
    return OnlineError(e.code, message, status)


def start(
    db: Session,
    account: CustomerAccount,
    slug: str,
    checkout_id: uuid.UUID,
    orders: list[PartIn],
    message_ok: bool,
) -> OnlinePayment:
    """Open the payment for a cart. `checkout_id` is made by the page, so a second tap, or a
    retry after a bad signal, is the same payment and not a second charge."""
    existing = db.get(OnlinePayment, checkout_id)
    if existing is not None:
        if existing.customer_id != account.id:
            raise OnlineError("not_found", "No such payment", 404)
        return existing
    if not payments.online_enabled():
        raise OnlineError("online_payments_off", _PAYMENT_WORDS["online_payments_off"][0], 503)
    court = online._court(db, slug)
    if not orders:
        raise OnlineError("empty_order", "Choose at least one dish")
    if len(orders) > MAX_OUTLETS or len({o.outlet_id for o in orders}) != len(orders):
        raise OnlineError("order_too_big", "Choose dishes from up to six different outlets.")

    parts, total = [], 0
    for o in orders:
        outlet_name, amount = online.quote(db, slug, o.outlet_id, o.items, o.pickup_at)
        if amount <= 0:
            raise OnlineError("empty_order", "Choose at least one dish")
        total += amount
        parts.append(
            {
                "outlet_id": str(o.outlet_id),
                "outlet": outlet_name,
                "amount_paise": amount,
                "request_id": str(o.request_id),
                "note": online._clean_text(o.note, 120),
                "pickup_at": o.pickup_at.isoformat() if o.pickup_at else None,
                "table_name": online._clean_text(o.table_name, 20),
                "items": [[str(i.item_id), i.qty, [str(m) for m in i.mods]] for i in o.items],
            }
        )
    if total > MAX_CHECKOUT_PAISE:
        raise OnlineError("order_too_big", "That is a lot for one payment. Split it into two.")

    try:
        order = payments.client().create_order(
            {
                "amount": total,  # paise, like ours
                "currency": "INR",
                "receipt": f"OC-{checkout_id.hex[:12]}",
                "notes": {"online_payment": str(checkout_id), "court": court.name[:40]},
            }
        )
    except payments.PaymentError as e:
        raise _from_payment_error(e) from None
    op = OnlinePayment(
        id=checkout_id,
        customer_id=account.id,
        court_id=court.id,
        status="created",
        amount_paise=total,
        provider_order_id=str(order["id"]),
        parts=parts,
        message_ok=message_ok,
    )
    db.add(op)
    db.commit()
    return op


def _with_mods(row: list) -> list:
    """A saved item is [dish id, qty, [option ids]]; payments made before options existed have
    no third entry."""
    return row if len(row) >= 3 else [row[0], row[1], []]


def _refund(op: OnlinePayment, part: dict) -> None:
    """Give one outlet's share back. If Razorpay cannot be reached the refund is left for the
    admin (`money()` lists it) rather than lost."""
    try:
        payments.client().refund(op.provider_payment_id or "", part["amount_paise"])
    except payments.PaymentError as e:
        op.refund_error = e.code[:60]
        part["refunded"] = False
    else:
        op.refunded_paise += part["amount_paise"]
        part["refunded"] = True


def _lock(db: Session, op: OnlinePayment) -> None:
    """Hold this payment's row while one part is decided, so a verify and a webhook arriving
    together cannot both act on it. NO KEY UPDATE, not UPDATE: placing the order (in its own
    session, for the outlet's shop) inserts a row that points at this one, and that check
    would otherwise wait on us forever."""
    db.refresh(op, with_for_update={"key_share": True})


def fulfil(db: Session, op: OnlinePayment) -> None:
    """Place the order at every outlet for a paid payment, and refund the outlets that cannot
    take theirs. Safe to run twice, and from a crash halfway: each part is saved as it is
    decided, an already-placed order is found again by its request id, and a finished payment
    changes nothing."""
    _lock(db, op)
    if op.status != "paid":
        db.rollback()
        raise OnlineError("not_paid", "This payment has not been confirmed", 409)
    court = db.get(FoodCourt, op.court_id)
    account = db.get(CustomerAccount, op.customer_id)
    for index in range(len(op.parts)):
        _lock(db, op)  # fresh: another request may have decided parts since
        if op.fulfilled_at is not None:
            db.rollback()
            return
        parts = [dict(p) for p in op.parts]
        part = parts[index]
        if "status_key" in part or "error" in part:
            continue  # decided on an earlier pass
        try:
            placed = online.place_order(
                db,
                court.slug,
                uuid.UUID(part["outlet_id"]),
                online.OrderInput(
                    request_id=uuid.UUID(part["request_id"]),
                    customer_id=account.id,
                    name=account.name,
                    phone=account.phone,
                    note=part["note"],
                    message_ok=op.message_ok,
                    items=[
                        online.Pick(uuid.UUID(row[0]), row[1], tuple(uuid.UUID(m) for m in row[2]))
                        for row in map(_with_mods, part["items"])
                    ],
                    paid=(op.id, part["amount_paise"]),
                    pickup_at=(
                        datetime.fromisoformat(part["pickup_at"]) if part.get("pickup_at") else None
                    ),
                    table_name=part.get("table_name", ""),
                ),
            )
            part["status_key"], part["token"] = placed["status_key"], placed["token"]
        except OnlineError as e:
            part["error"], part["message"] = e.code, e.message
            _refund(op, part)
        op.parts = parts
        db.commit()
    _lock(db, op)
    if op.fulfilled_at is None:
        op.fulfilled_at = utcnow()
    db.commit()


def view(op: OnlinePayment) -> dict:
    """What the customer's page needs: the state, and each outlet's token once placed."""
    return {
        "id": op.id,
        "status": op.status,
        "amount_paise": op.amount_paise,
        "razorpay_order_id": op.provider_order_id,
        "error": op.error,
        "fulfilled": op.fulfilled_at is not None,
        "refunded_paise": op.refunded_paise,
        "orders": [
            {
                "outlet": p["outlet"],
                "amount_paise": p["amount_paise"],
                "status_key": p.get("status_key"),
                "token": p.get("token"),
                "error": p.get("error"),
                "message": p.get("message"),
                "refunded": p.get("refunded"),
            }
            for p in op.parts
        ]
        if op.fulfilled_at is not None
        else [],
    }


# ---------------------------------------------------------------- what each outlet is owed
def _paid_orders(db: Session, shop_id: uuid.UUID):
    """Online-paid orders of one outlet that still count as its sale: not cancelled by the
    outlet (those are refunded to the customer, not owed to the outlet)."""
    return (
        select(OnlineOrder)
        .join(Order, Order.id == OnlineOrder.order_id)
        .where(
            OnlineOrder.shop_id == shop_id,
            OnlineOrder.payment_id.is_not(None),
            Order.status != OrderStatus.cancelled,
        )
    )


def fee_of(paid_paise: int, fee_bp: int) -> int:
    """What the operator keeps of one order's payment: basis points, rounded half up per order so
    a month of small orders adds up exactly the same as the statement lines."""
    return (paid_paise * fee_bp * 2 + 10_000) // 20_000


def fee_bp_of(db: Session, shop_id: uuid.UUID) -> int:
    return db.scalar(select(FoodCourtOutlet.fee_bp).where(FoodCourtOutlet.shop_id == shop_id)) or 0


def outlet_money(db: Session, shop_id: uuid.UUID) -> dict:
    """What customers paid online for this outlet, the operator's fee, what the operator has paid
    it so far, and the difference. `db` is a system session (the figures cross tenants)."""
    fee_bp = fee_bp_of(db, shop_id)
    paid_each = db.scalars(select(_paid_orders(db, shop_id).subquery().c.paid_paise)).all()
    paid = sum(int(p or 0) for p in paid_each)
    fee = sum(fee_of(int(p or 0), fee_bp) for p in paid_each)
    settled = db.scalar(
        select(func.coalesce(func.sum(OnlineSettlement.amount_paise), 0)).where(
            OnlineSettlement.shop_id == shop_id
        )
    )
    settled = int(settled or 0)
    return {
        "orders": len(paid_each),
        "paid_paise": paid,
        "fee_bp": fee_bp,
        "fee_paise": fee,
        "net_paise": paid - fee,
        "settled_paise": settled,
        "owed_paise": paid - fee - settled,
    }


def statement(db: Session, shop_id: uuid.UUID, start: date, end: date) -> dict:
    """One outlet's statement for a range of days: what was sold online, what went back to
    customers, the operator's fee, what was paid to the outlet in the range, and what is still
    owed now (all time, not just the range). `db` is a system session."""
    if end < start or (end - start).days > 92:
        raise OnlineError("bad_range", "Choose up to 92 days", 422)
    fee_bp = fee_bp_of(db, shop_id)
    rows = db.execute(
        select(OnlineOrder, Order)
        .join(Order, Order.id == OnlineOrder.order_id)
        .where(
            OnlineOrder.shop_id == shop_id,
            OnlineOrder.payment_id.is_not(None),
            OnlineOrder.business_date >= start,
            OnlineOrder.business_date <= end,
        )
        .order_by(OnlineOrder.business_date, OnlineOrder.created_at)
    ).all()
    orders, sales, refunds, fee = [], 0, 0, 0
    for oo, order in rows:
        cancelled = order.status == OrderStatus.cancelled
        paid = int(oo.paid_paise or 0)
        orders.append(
            {
                "date": oo.business_date,
                "token": oo.token,
                "paid_paise": paid,
                "cancelled": cancelled,
                "refunded_paise": int(oo.refunded_paise or 0),
                "refund_pending": cancelled and not oo.refunded_paise,
                "fee_paise": 0 if cancelled else fee_of(paid, fee_bp),
            }
        )
        if cancelled:
            refunds += paid
        else:
            sales += paid
            fee += fee_of(paid, fee_bp)
    paid_out = db.scalars(
        select(OnlineSettlement)
        .where(
            OnlineSettlement.shop_id == shop_id,
            func.date(func.timezone("Asia/Kolkata", OnlineSettlement.created_at)) >= start,
            func.date(func.timezone("Asia/Kolkata", OnlineSettlement.created_at)) <= end,
        )
        .order_by(OnlineSettlement.created_at)
    ).all()
    money = outlet_money(db, shop_id)
    return {
        "from": start,
        "to": end,
        "fee_bp": fee_bp,
        "orders": orders,
        "sales_paise": sales,
        "refunds_paise": refunds,
        "fee_paise": fee,
        "earned_paise": sales - fee,
        "paid_out": [
            {"date": s.created_at, "amount_paise": s.amount_paise, "note": s.note} for s in paid_out
        ],
        "paid_out_paise": sum(s.amount_paise for s in paid_out),
        "owed_now_paise": money["owed_paise"],
    }


def auto_refund(order_id: uuid.UUID) -> None:
    """An outlet cancelled a whole order that the customer had paid for online: give the money
    back now instead of waiting for the admin. Best effort and safe to repeat: a refund that
    fails stays on the admin's "refunds due" list, and one already made is not made twice."""
    try:
        with online.system_session() as db:
            oo = db.scalar(select(OnlineOrder).where(OnlineOrder.order_id == order_id))
            if oo is None or oo.payment_id is None or oo.refunded_paise:
                return
            refund(db, f"order:{order_id}")
    except Exception:  # noqa: BLE001 - never breaks the outlet's sync
        logging.getLogger(__name__).exception("automatic refund failed")


def settle(db: Session, admin_id: uuid.UUID, shop_id: uuid.UUID, amount: int, note: str) -> None:
    owed = outlet_money(db, shop_id)["owed_paise"]
    if amount <= 0:
        raise OnlineError("bad_amount", "Enter an amount above zero", 422)
    if amount > owed:
        raise OnlineError("more_than_owed", "That is more than this outlet is owed", 409)
    db.add(
        OnlineSettlement(
            shop_id=shop_id,
            amount_paise=amount,
            note=online._clean_text(note, 120),
            created_by=admin_id,
        )
    )
    db.commit()


def refunds_due(db: Session) -> list[dict]:
    """Money that must go back to a customer: an outlet cancelled an order that was paid for, or
    an automatic refund could not be made. Each row's `ref` is what `refund()` takes."""
    out = []
    rows = db.execute(
        select(OnlineOrder, Order, Shop)
        .join(Order, Order.id == OnlineOrder.order_id)
        .join(Shop, Shop.id == OnlineOrder.shop_id)
        .where(
            OnlineOrder.payment_id.is_not(None),
            Order.status == OrderStatus.cancelled,
            OnlineOrder.refunded_paise == 0,
        )
        .order_by(Order.opened_at)
    ).all()
    for oo, _order, shop in rows:
        who = db.get(CustomerAccount, db.get(OnlinePayment, oo.payment_id).customer_id)
        out.append(
            {
                "ref": f"order:{oo.order_id}",
                "why": "The outlet cancelled a paid order",
                "outlet": shop.name,
                "token": oo.token,
                "customer": who.name,
                "phone": who.phone,
                "amount_paise": oo.paid_paise,
            }
        )
    for op in db.scalars(select(OnlinePayment).where(OnlinePayment.refund_error != "")):
        who = db.get(CustomerAccount, op.customer_id)
        for part in op.parts:
            if part.get("error") and part.get("refunded") is False:
                out.append(
                    {
                        "ref": f"part:{op.id}:{part['outlet_id']}",
                        "why": "An outlet could not take the order and the automatic refund failed",
                        "outlet": part["outlet"],
                        "token": None,
                        "customer": who.name,
                        "phone": who.phone,
                        "amount_paise": part["amount_paise"],
                    }
                )
    return out


def refund(db: Session, ref: str) -> None:
    """Make one refund from the list above. Idempotent: a refund already made is not made twice."""
    kind, _, rest = ref.partition(":")
    try:
        if kind == "order":
            oo = db.scalar(select(OnlineOrder).where(OnlineOrder.order_id == uuid.UUID(rest)))
            if oo is None or oo.payment_id is None:
                raise OnlineError("not_found", "No such refund", 404)
            op = db.get(OnlinePayment, oo.payment_id)
            order = db.scalar(select(Order).where(Order.id == oo.order_id))
            if order.status != OrderStatus.cancelled:
                raise OnlineError("not_cancelled", "That order was not cancelled", 409)
            if oo.refunded_paise:
                return
            _call_refund(op, oo.paid_paise)
            oo.refunded_paise = oo.paid_paise
            op.refunded_paise += oo.paid_paise
        elif kind == "part":
            payment_id, _, outlet_id = rest.partition(":")
            op = db.get(OnlinePayment, uuid.UUID(payment_id))
            parts = [dict(p) for p in (op.parts if op else [])]
            part = next((p for p in parts if p["outlet_id"] == outlet_id), None)
            if op is None or part is None or not part.get("error"):
                raise OnlineError("not_found", "No such refund", 404)
            if part.get("refunded"):
                return
            _call_refund(op, part["amount_paise"])
            part["refunded"] = True
            op.refunded_paise += part["amount_paise"]
            op.parts = parts
            if not any(p.get("error") and p.get("refunded") is False for p in parts):
                op.refund_error = ""
        else:
            raise OnlineError("not_found", "No such refund", 404)
    except ValueError:
        raise OnlineError("not_found", "No such refund", 404) from None
    db.commit()


def _call_refund(op: OnlinePayment, amount: int) -> None:
    try:
        payments.client().refund(op.provider_payment_id or "", amount)
    except payments.PaymentError as e:
        raise _from_payment_error(e) from None


def outlets_report(db: Session) -> list[dict]:
    """For the admin: every outlet of every court with its online money."""
    out = []
    rows = db.execute(
        select(FoodCourt, FoodCourtOutlet, Shop)
        .join(FoodCourtOutlet, FoodCourtOutlet.court_id == FoodCourt.id)
        .join(Shop, Shop.id == FoodCourtOutlet.shop_id)
        .order_by(FoodCourt.name, Shop.name)
    ).all()
    for court, outlet, shop in rows:
        out.append(
            {
                "court_id": court.id,
                "court": court.name,
                "outlet_id": outlet.id,
                "outlet": shop.name,
                **outlet_money(db, shop.id),
            }
        )
    return out
